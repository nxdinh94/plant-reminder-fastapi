import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from app.core.config import settings
from tests.api.test_auth_and_sync import register_user

def test_webhook_unauthorized(client: TestClient) -> None:
    response = client.post(
        "/api/v1/revenuecat/webhook",
        json={"api_version": "1.0", "event": {"id": "1", "type": "TEST", "environment": "SANDBOX"}},
        headers={"Authorization": "Bearer invalid_secret"}
    )
    assert response.status_code == 401

def test_webhook_malformed_payload(client: TestClient) -> None:
    headers = {"Authorization": settings.REVENUECAT_WEBHOOK_AUTH_HEADER}
    
    # Missing event
    response = client.post(
        "/api/v1/revenuecat/webhook",
        json={"api_version": "1.0"},
        headers=headers
    )
    assert response.status_code == 400

    # Missing event type or environment
    response = client.post(
        "/api/v1/revenuecat/webhook",
        json={"api_version": "1.0", "event": {"id": "1"}},
        headers=headers
    )
    assert response.status_code == 400

def test_webhook_test_event(client: TestClient) -> None:
    headers = {"Authorization": settings.REVENUECAT_WEBHOOK_AUTH_HEADER}
    response = client.post(
        "/api/v1/revenuecat/webhook",
        json={
            "api_version": "1.0",
            "event": {
                "id": "test_evt_1",
                "type": "TEST",
                "environment": "SANDBOX",
                "app_user_id": "some_user"
            }
        },
        headers=headers
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"

def test_webhook_idempotency_duplicate(client: TestClient) -> None:
    headers = {"Authorization": settings.REVENUECAT_WEBHOOK_AUTH_HEADER}
    payload = {
        "api_version": "1.0",
        "event": {
            "id": "dup_evt_1",
            "type": "TEST",
            "environment": "SANDBOX",
            "app_user_id": "some_user"
        }
    }
    
    # Send first time
    response = client.post("/api/v1/revenuecat/webhook", json=payload, headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    # Send second time
    response = client.post("/api/v1/revenuecat/webhook", json=payload, headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"

@pytest.mark.asyncio
async def test_webhook_initial_purchase_upgrades_user(client: TestClient) -> None:
    # 1. Register user
    reg = register_user(client, email="rc_purchase@example.com")
    access_token = reg["access_token"]
    
    # Get user ID via session
    response = client.get("/api/v1/auth/session", headers={"Authorization": f"Bearer {access_token}"})
    assert response.status_code == 200
    user_id = response.json()["id"]

    headers = {"Authorization": settings.REVENUECAT_WEBHOOK_AUTH_HEADER}
    event_timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    
    mock_rc_response = {
        "subscriber": {
            "original_app_user_id": user_id,
            "entitlements": {
                settings.REVENUECAT_PRO_ENTITLEMENT_ID: {
                    "expires_date": "2030-01-01T00:00:00Z",
                    "product_identifier": "monthly",
                    "purchase_date": "2026-06-17T00:00:00Z"
                }
            },
            "subscriptions": {
                "monthly": {
                    "expires_date": "2030-01-01T00:00:00Z",
                    "is_sandbox": True,
                    "original_purchase_date": "2026-06-17T00:00:00Z",
                    "purchase_date": "2026-06-17T00:00:00Z",
                    "store": "app_store"
                }
            }
        }
    }

    with patch("app.api.v1.endpoints.revenuecat.fetch_revenuecat_subscriber", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_rc_response
        
        response = client.post(
            "/api/v1/revenuecat/webhook",
            json={
                "api_version": "1.0",
                "event": {
                    "id": "purchase_evt_1",
                    "type": "INITIAL_PURCHASE",
                    "environment": "SANDBOX",
                    "app_user_id": user_id,
                    "event_timestamp_ms": event_timestamp_ms
                }
            },
            headers=headers
        )
        
        assert response.status_code == 200
        mock_fetch.assert_called_once_with(user_id)
        
        # Verify user upgraded to pro tier
        session_resp = client.get("/api/v1/auth/session", headers={"Authorization": f"Bearer {access_token}"})
        assert session_resp.status_code == 200
        assert session_resp.json()["plan_tier"] == "pro"

@pytest.mark.asyncio
async def test_webhook_expiration_downgrades_user(client: TestClient) -> None:
    # 1. Register user
    reg = register_user(client, email="rc_expire@example.com")
    access_token = reg["access_token"]
    
    # Get user ID
    response = client.get("/api/v1/auth/session", headers={"Authorization": f"Bearer {access_token}"})
    user_id = response.json()["id"]
    
    headers = {"Authorization": settings.REVENUECAT_WEBHOOK_AUTH_HEADER}
    event_timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    
    # Mock active pro response
    mock_active = {
        "subscriber": {
            "original_app_user_id": user_id,
            "entitlements": {
                settings.REVENUECAT_PRO_ENTITLEMENT_ID: {
                    "expires_date": "2030-01-01T00:00:00Z",
                    "product_identifier": "monthly",
                    "purchase_date": "2026-06-17T00:00:00Z"
                }
            },
            "subscriptions": {
                "monthly": {
                    "expires_date": "2030-01-01T00:00:00Z",
                    "is_sandbox": True,
                    "store": "app_store"
                }
            }
        }
    }
    
    # 2. Upgrade user to Pro via Webhook first
    with patch("app.api.v1.endpoints.revenuecat.fetch_revenuecat_subscriber", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_active
        response = client.post(
            "/api/v1/revenuecat/webhook",
            json={
                "api_version": "1.0",
                "event": {
                    "id": "init_p",
                    "type": "INITIAL_PURCHASE",
                    "environment": "SANDBOX",
                    "app_user_id": user_id,
                    "event_timestamp_ms": event_timestamp_ms
                }
            },
            headers=headers
        )
        assert response.status_code == 200
        
    # Verify user is Pro
    session_resp = client.get("/api/v1/auth/session", headers={"Authorization": f"Bearer {access_token}"})
    assert session_resp.json()["plan_tier"] == "pro"
    
    # Mock expired response
    mock_expired = {
        "subscriber": {
            "original_app_user_id": user_id,
            "entitlements": {},
            "subscriptions": {
                "monthly": {
                    "expires_date": "2026-06-17T00:00:00Z",
                    "is_sandbox": True,
                    "store": "app_store"
                }
            }
        }
    }

    # 3. Downgrade user via Expiration webhook
    with patch("app.api.v1.endpoints.revenuecat.fetch_revenuecat_subscriber", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_expired
        
        response = client.post(
            "/api/v1/revenuecat/webhook",
            json={
                "api_version": "1.0",
                "event": {
                    "id": "expiration_evt_1",
                    "type": "EXPIRATION",
                    "environment": "SANDBOX",
                    "app_user_id": user_id,
                    "event_timestamp_ms": event_timestamp_ms
                }
            },
            headers=headers
        )
        assert response.status_code == 200
        mock_fetch.assert_called_once_with(user_id)
        
        # Verify user is downgraded to free tier
        session_resp = client.get("/api/v1/auth/session", headers={"Authorization": f"Bearer {access_token}"})
        assert session_resp.json()["plan_tier"] == "free"

@pytest.mark.asyncio
async def test_webhook_transfer_handles_source_and_destination(client: TestClient) -> None:
    # 1. Register target user
    reg_tgt = register_user(client, email="tgt_user@example.com")
    tgt_access_token = reg_tgt["access_token"]
    response = client.get("/api/v1/auth/session", headers={"Authorization": f"Bearer {tgt_access_token}"})
    tgt_user_id = response.json()["id"]

    # 2. Register source user who currently has Pro
    reg_src = register_user(client, email="src_user@example.com")
    src_access_token = reg_src["access_token"]
    response = client.get("/api/v1/auth/session", headers={"Authorization": f"Bearer {src_access_token}"})
    src_user_id = response.json()["id"]

    headers = {"Authorization": settings.REVENUECAT_WEBHOOK_AUTH_HEADER}
    event_timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    # Upgrade source user to Pro first
    mock_src_pro = {
        "subscriber": {
            "original_app_user_id": src_user_id,
            "entitlements": {
                settings.REVENUECAT_PRO_ENTITLEMENT_ID: {
                    "expires_date": "2030-01-01T00:00:00Z",
                    "product_identifier": "yearly",
                    "purchase_date": "2026-06-17T00:00:00Z"
                }
            },
            "subscriptions": {
                "yearly": {
                    "expires_date": "2030-01-01T00:00:00Z",
                    "is_sandbox": True,
                    "store": "app_store"
                }
            }
        }
    }
    with patch("app.api.v1.endpoints.revenuecat.fetch_revenuecat_subscriber", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_src_pro
        response = client.post(
            "/api/v1/revenuecat/webhook",
            json={
                "api_version": "1.0",
                "event": {
                    "id": "init_src",
                    "type": "INITIAL_PURCHASE",
                    "environment": "SANDBOX",
                    "app_user_id": src_user_id,
                    "event_timestamp_ms": event_timestamp_ms
                }
            },
            headers=headers
        )
        assert response.status_code == 200

    # Verify source is Pro, target is Free
    assert client.get("/api/v1/auth/session", headers={"Authorization": f"Bearer {src_access_token}"}).json()["plan_tier"] == "pro"
    assert client.get("/api/v1/auth/session", headers={"Authorization": f"Bearer {tgt_access_token}"}).json()["plan_tier"] == "free"

    # Mock responses for the transfer event queries
    # Target user gets active Pro
    mock_target_resp = {
        "subscriber": {
            "original_app_user_id": tgt_user_id,
            "entitlements": {
                settings.REVENUECAT_PRO_ENTITLEMENT_ID: {
                    "expires_date": "2030-01-01T00:00:00Z",
                    "product_identifier": "yearly",
                    "purchase_date": "2026-06-17T00:00:00Z"
                }
            },
            "subscriptions": {
                "yearly": {
                    "expires_date": "2030-01-01T00:00:00Z",
                    "is_sandbox": True,
                    "store": "app_store"
                }
            }
        }
    }
    # Source user loses Pro
    mock_source_resp = {
        "subscriber": {
            "original_app_user_id": src_user_id,
            "entitlements": {},
            "subscriptions": {}
        }
    }

    async def mock_fetch_func(uid):
        if uid == tgt_user_id:
            return mock_target_resp
        elif uid == src_user_id:
            return mock_source_resp
        return None

    with patch("app.api.v1.endpoints.revenuecat.fetch_revenuecat_subscriber", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.side_effect = mock_fetch_func
        
        response = client.post(
            "/api/v1/revenuecat/webhook",
            json={
                "api_version": "1.0",
                "event": {
                    "id": "transfer_evt_1",
                    "type": "TRANSFER",
                    "environment": "SANDBOX",
                    "transferred_from": [src_user_id],
                    "transferred_to": tgt_user_id,
                    "event_timestamp_ms": event_timestamp_ms
                }
            },
            headers=headers
        )
        
        assert response.status_code == 200
        
        # Verify transfer updated both users correctly
        assert client.get("/api/v1/auth/session", headers={"Authorization": f"Bearer {tgt_access_token}"}).json()["plan_tier"] == "pro"
        assert client.get("/api/v1/auth/session", headers={"Authorization": f"Bearer {src_access_token}"}).json()["plan_tier"] == "free"

def test_webhook_non_tier_events(client: TestClient) -> None:
    headers = {"Authorization": settings.REVENUECAT_WEBHOOK_AUTH_HEADER}
    
    # Send INVOICE_ISSUANCE (should be recorded only, not sync subscriber)
    with patch("app.api.v1.endpoints.revenuecat.fetch_revenuecat_subscriber", new_callable=AsyncMock) as mock_fetch:
        response = client.post(
            "/api/v1/revenuecat/webhook",
            json={
                "api_version": "1.0",
                "event": {
                    "id": "invoice_evt_1",
                    "type": "INVOICE_ISSUANCE",
                    "environment": "SANDBOX",
                    "app_user_id": "nonexistent"
                }
            },
            headers=headers
        )
        assert response.status_code == 200
        mock_fetch.assert_not_called()
