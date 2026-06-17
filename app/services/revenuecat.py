import logging
from datetime import datetime, timezone
import httpx
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models.user import User

logger = logging.getLogger(__name__)

async def fetch_revenuecat_subscriber(app_user_id: str) -> dict | None:
    """
    Fetch subscriber info directly from RevenueCat REST API
    """
    if not settings.REVENUECAT_REST_API_KEY:
        logger.warning("REVENUECAT_REST_API_KEY is not configured. Skipping REST API sync.")
        return None

    url = f"{settings.REVENUECAT_API_BASE_URL}/subscribers/{app_user_id}"
    headers = {
        "Authorization": f"Bearer {settings.REVENUECAT_REST_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=10.0)
            if response.status_code == 404:
                logger.info(f"User {app_user_id} not found in RevenueCat.")
                return None
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"RevenueCat HTTP error fetching subscriber {app_user_id}: {e.response.status_code} - {e.response.text}")
        raise
    except httpx.RequestError as e:
        logger.error(f"RevenueCat request error fetching subscriber {app_user_id}: {str(e)}")
        raise

def sync_subscriber_to_user(
    db: Session,
    user: User,
    subscriber_data: dict,
    event_type: str | None = None,
    event_timestamp: datetime | None = None,
) -> User:
    """
    Sync subscription entitlement details to User database model
    """
    subscriber = subscriber_data.get("subscriber", {})
    entitlements = subscriber.get("entitlements", {})

    pro_entitlement = entitlements.get(settings.REVENUECAT_PRO_ENTITLEMENT_ID)

    is_pro = False
    expires_at = None
    product_id = None
    store = None
    environment = None

    if pro_entitlement:
        expires_date_str = pro_entitlement.get("expires_date")
        if expires_date_str:
            try:
                # Convert ISO 8601 string to timezone-aware datetime
                dt_str = expires_date_str.replace("Z", "+00:00")
                expires_at = datetime.fromisoformat(dt_str)
                is_pro = expires_at > datetime.now(timezone.utc)
            except Exception as e:
                logger.error(f"Failed to parse expires_date {expires_date_str}: {e}")
                is_pro = True  # Fallback to active if expires parsing fails but entitlement is returned
        else:
            # Lifetime entitlement has no expires_date
            is_pro = True

        product_id = pro_entitlement.get("product_identifier")
        
        # Determine store and environment from corresponding subscription
        subscriptions = subscriber.get("subscriptions", {})
        if product_id and product_id in subscriptions:
            sub = subscriptions[product_id]
            store = sub.get("store")
            is_sandbox = sub.get("is_sandbox", False)
            environment = "sandbox" if is_sandbox else "production"

    # Update columns on user model
    user.plan_tier = "pro" if is_pro else "free"
    user.plan_expires_at = expires_at
    user.revenuecat_app_user_id = subscriber.get("original_app_user_id") or user.id
    user.revenuecat_product_id = product_id
    
    if store:
        user.revenuecat_store = store
    if environment:
        user.revenuecat_environment = environment

    if event_timestamp:
        user.plan_last_event_at = event_timestamp
    if event_type:
        user.plan_last_revenuecat_event_type = event_type

    db.add(user)
    db.commit()
    db.refresh(user)

    logger.info(
        f"Synced User {user.id} subscription: tier={user.plan_tier}, product={user.revenuecat_product_id}, store={user.revenuecat_store}"
    )
    return user
