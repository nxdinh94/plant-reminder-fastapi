import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.models.revenuecat_webhook_event import RevenueCatWebhookEvent
from app.services.revenuecat import fetch_revenuecat_subscriber, sync_subscriber_to_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/revenuecat", tags=["revenuecat"])

SYNC_EVENT_TYPES = {
    "INITIAL_PURCHASE",
    "RENEWAL",
    "UNCANCELLATION",
    "NON_RENEWING_PURCHASE",
    "SUBSCRIPTION_EXTENDED",
    "REFUND_REVERSED",
    "TEMPORARY_ENTITLEMENT_GRANT",
    "CANCELLATION",
    "EXPIRATION",
    "BILLING_ISSUE",
    "SUBSCRIPTION_PAUSED",
    "PRODUCT_CHANGE",
    "TRANSFER",
    "PURCHASE_REDEEMED",
}

def resolve_user_ids(event: dict) -> list[str]:
    """
    Extract all unique user IDs that should be synchronized for this webhook event.
    """
    event_type = event.get("type")
    user_ids = []

    if event_type == "TRANSFER":
        to_user = event.get("transferred_to")
        if to_user:
            user_ids.append(to_user)
        from_users = event.get("transferred_from")
        if from_users:
            if isinstance(from_users, list):
                user_ids.extend(from_users)
            else:
                user_ids.append(from_users)
        if not user_ids:
            app_user_id = event.get("app_user_id")
            if app_user_id:
                user_ids.append(app_user_id)
        return list(set(user_ids))

    app_user_id = event.get("app_user_id")
    if app_user_id:
        user_ids.append(app_user_id)

    original_app_user_id = event.get("original_app_user_id")
    if original_app_user_id:
        user_ids.append(original_app_user_id)

    redeemed_by = event.get("redeemed_by")
    if redeemed_by:
        user_ids.append(redeemed_by)

    redeemed_by_app_user_id = event.get("redeemed_by_app_user_id")
    if redeemed_by_app_user_id:
        user_ids.append(redeemed_by_app_user_id)

    aliases = event.get("aliases")
    if aliases:
        if isinstance(aliases, list):
            user_ids.extend(aliases)
        else:
            user_ids.append(aliases)

    # Filter out empty/None values and deduplicate
    return list(set(uid for uid in user_ids if uid))

@router.post("/webhook")
async def revenuecat_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Process incoming RevenueCat webhook event
    """
    # 1. Verify Authentication Header
    auth_header = request.headers.get("Authorization")
    if not auth_header or auth_header != settings.REVENUECAT_WEBHOOK_AUTH_HEADER:
        logger.warning("Rejected RevenueCat webhook call: unauthorized")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized webhook request",
        )

    # 2. Parse and validate payload structure
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object")

    api_version = payload.get("api_version")
    event = payload.get("event")

    if not api_version or not isinstance(event, dict):
        raise HTTPException(status_code=400, detail="Missing api_version or event structure")

    event_id = event.get("id")
    event_type = event.get("type")
    environment = event.get("environment")

    if not event_id or not event_type or not environment:
        raise HTTPException(status_code=400, detail="Missing required event fields")

    # 3. Check for duplicates idempotently
    existing_event = db.execute(
        select(RevenueCatWebhookEvent).where(RevenueCatWebhookEvent.event_id == event_id)
    ).scalar_one_or_none()
    
    if existing_event:
        logger.info(f"Ignored duplicate RevenueCat webhook event: {event_id}")
        return {"status": "ignored", "message": "Duplicate event ID"}

    # 4. Parse event metadata
    app_user_id = event.get("app_user_id") or event.get("original_app_user_id") or "unknown"
    original_app_user_id = event.get("original_app_user_id")
    aliases = event.get("aliases")
    store = event.get("store")
    
    event_timestamp_ms = event.get("event_timestamp_ms")
    event_timestamp = None
    if event_timestamp_ms is not None:
        try:
            event_timestamp = datetime.fromtimestamp(event_timestamp_ms / 1000.0, tz=timezone.utc)
        except Exception as e:
            logger.error(f"Failed to parse event_timestamp_ms {event_timestamp_ms}: {e}")

    # 5. Idempotently record event in db
    webhook_event = RevenueCatWebhookEvent(
        event_id=event_id,
        event_type=event_type,
        app_user_id=app_user_id,
        original_app_user_id=original_app_user_id,
        aliases=aliases,
        environment=environment,
        store=store,
        raw_payload=payload,
    )
    db.add(webhook_event)
    db.commit()

    # 6. Execute sync rules depending on event families
    if event_type == "TEST":
        logger.info(f"Received RevenueCat TEST webhook event {event_id}")
        return {"status": "success", "message": "TEST event received"}

    if event_type not in SYNC_EVENT_TYPES:
        logger.info(f"Unsupported/No-op event type received: {event_type}. Recorded only.")
        return {"status": "success", "message": f"Unsupported event type {event_type} ignored"}

    # Process user sync
    resolved_ids = resolve_user_ids(event)
    logger.info(f"Resolved user IDs for event {event_id} ({event_type}): {resolved_ids}")

    for uid in resolved_ids:
        # Check if user exists locally
        local_user = db.execute(select(User).where(User.id == uid)).scalar_one_or_none()
        if not local_user:
            logger.info(f"Resolved user ID {uid} does not exist in local database. Skipping tier update.")
            continue

        try:
            # Sync user entitlement state by fetching latest subscriber details from REST
            rc_subscriber = await fetch_revenuecat_subscriber(uid)
            if rc_subscriber:
                sync_subscriber_to_user(
                    db=db,
                    user=local_user,
                    subscriber_data=rc_subscriber,
                    event_type=event_type,
                    event_timestamp=event_timestamp,
                )
        except Exception as e:
            logger.error(f"Failed to fetch or sync subscriber {uid} from RevenueCat REST API: {e}")
            # Raise 500 error for transient failure to let RevenueCat retry the webhook
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Transient failure syncing with RevenueCat API",
            )

    return {"status": "success", "message": f"Successfully processed event {event_type}"}
