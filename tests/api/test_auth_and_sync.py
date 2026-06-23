from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_password
from app.models.action_type import ActionType
from app.models.profile_setting import ProfileSetting
from app.models.user import User
from conftest import TestingSessionLocal


DEFAULT_ACTION_TYPE_NAMES = {"Watering", "Fertilize", "Prune", "Mist", "Repot"}


def register_user(
    client: TestClient,
    email: str = "user@example.com",
    password: str = "password123",
) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password},
    )
    assert response.status_code == 201
    return response.json()


def auth_headers(client: TestClient, email: str) -> dict[str, str]:
    tokens = register_user(client, email=email)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def create_legacy_user(email: str = "legacy@example.com", password: str = "password123") -> User:
    db = TestingSessionLocal()
    try:
        user = User(email=email, password_hash=hash_password(password))
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def delete_user_defaults(user_id: str) -> None:
    db = TestingSessionLocal()
    try:
        db.query(ProfileSetting).filter(ProfileSetting.user_id == user_id).delete()
        db.query(ActionType).filter(ActionType.user_id == user_id).delete()
        db.commit()
    finally:
        db.close()


def get_user_default_counts(user_id: str) -> tuple[int, int, set[str]]:
    db = TestingSessionLocal()
    try:
        profile_count = db.query(ProfileSetting).filter(ProfileSetting.user_id == user_id).count()
        action_types = list(
            db.execute(select(ActionType).where(ActionType.user_id == user_id)).scalars()
        )
        return profile_count, len(action_types), {action_type.name for action_type in action_types}
    finally:
        db.close()


def test_headers_passthrough_when_provided(client: TestClient) -> None:
    response = client.get(
        "/api/v1/health/live",
        headers={"X-Request-ID": "req-123", "X-Operation-ID": "op-123"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-123"
    assert response.headers["X-Operation-ID"] == "op-123"


def test_operation_id_is_generated_for_mutations(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "mutation@example.com", "password": "password123"},
        headers={"X-Request-ID": "req-register"},
    )

    assert response.status_code == 201
    assert response.headers["X-Request-ID"] == "req-register"
    assert response.headers["X-Operation-ID"]


def test_auth_login_and_refresh_flow(client: TestClient) -> None:
    register_user(client, email="authflow@example.com")

    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": "authflow@example.com", "password": "password123"},
    )
    assert login_response.status_code == 200
    login_tokens = login_response.json()
    assert login_tokens["access_token"]
    assert login_tokens["refresh_token"]

    refresh_response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": login_tokens["refresh_token"]},
    )
    assert refresh_response.status_code == 200
    refreshed_tokens = refresh_response.json()
    assert refreshed_tokens["access_token"]
    assert refreshed_tokens["refresh_token"]


def test_register_creates_profile_settings_and_default_action_types(client: TestClient) -> None:
    tokens = register_user(client, email="defaults-register@example.com")
    session_response = client.get(
        "/api/v1/auth/session",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    user_id = session_response.json()["id"]

    profile_count, action_type_count, action_type_names = get_user_default_counts(user_id)

    assert profile_count == 1
    assert action_type_count == 5
    assert action_type_names == DEFAULT_ACTION_TYPE_NAMES


def test_login_backfills_defaults_for_existing_user(client: TestClient) -> None:
    user = create_legacy_user(email="legacy-login@example.com")

    response = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "password123"},
    )

    assert response.status_code == 200
    profile_count, action_type_count, action_type_names = get_user_default_counts(user.id)
    assert profile_count == 1
    assert action_type_count == 5
    assert action_type_names == DEFAULT_ACTION_TYPE_NAMES


def test_refresh_backfills_defaults_for_existing_user(client: TestClient) -> None:
    tokens = register_user(client, email="defaults-refresh@example.com")
    session_response = client.get(
        "/api/v1/auth/session",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    user_id = session_response.json()["id"]
    delete_user_defaults(user_id)

    response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )

    assert response.status_code == 200
    profile_count, action_type_count, action_type_names = get_user_default_counts(user_id)
    assert profile_count == 1
    assert action_type_count == 5
    assert action_type_names == DEFAULT_ACTION_TYPE_NAMES


def test_sync_bootstrap_backfills_defaults_without_duplicates(client: TestClient) -> None:
    tokens = register_user(client, email="defaults-bootstrap@example.com")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    session_response = client.get("/api/v1/auth/session", headers=headers)
    user_id = session_response.json()["id"]
    delete_user_defaults(user_id)

    first_response = client.get("/api/v1/sync/bootstrap", headers=headers)
    second_response = client.get("/api/v1/sync/bootstrap", headers=headers)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    profile_count, action_type_count, action_type_names = get_user_default_counts(user_id)
    assert profile_count == 1
    assert action_type_count == 5
    assert action_type_names == DEFAULT_ACTION_TYPE_NAMES


def test_deleted_action_type_name_conflict_does_not_break_login(client: TestClient) -> None:
    tokens = register_user(client, email="deleted-default@example.com")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    action_types_response = client.get("/api/v1/action-types", headers=headers)
    watering_id = next(
        action_type["id"]
        for action_type in action_types_response.json()
        if action_type["name"] == "Watering"
    )
    delete_response = client.delete(f"/api/v1/action-types/{watering_id}", headers=headers)

    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": "deleted-default@example.com", "password": "password123"},
    )

    assert delete_response.status_code == 204
    assert login_response.status_code == 200
    active_action_types_response = client.get("/api/v1/action-types", headers=headers)
    active_action_type_names = {item["name"] for item in active_action_types_response.json()}
    assert "Watering" not in active_action_type_names
    assert len(active_action_type_names) == 4


def test_auth_session_returns_current_user(client: TestClient) -> None:
    headers = auth_headers(client, "session-user@example.com")
    response = client.get("/api/v1/auth/session", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"]
    assert payload["email"] == "session-user@example.com"
    assert payload["is_active"] is True


def test_auth_session_requires_valid_access_token(client: TestClient) -> None:
    response = client.get("/api/v1/auth/session")
    assert response.status_code == 401


def test_sync_endpoints_require_access_token(client: TestClient) -> None:
    capabilities_response = client.get("/api/v1/sync/capabilities")
    bootstrap_response = client.get("/api/v1/sync/bootstrap")

    assert capabilities_response.status_code == 401
    assert bootstrap_response.status_code == 401


def test_sync_capabilities_and_bootstrap(client: TestClient) -> None:
    registration_payload = register_user(client, email="sync@example.com")
    access_token = registration_payload["access_token"]
    auth_headers = {"Authorization": f"Bearer {access_token}"}

    capabilities_response = client.get("/api/v1/sync/capabilities", headers=auth_headers)
    assert capabilities_response.status_code == 200
    capabilities_payload = capabilities_response.json()
    assert capabilities_payload["api_base_path"] == "/api/v1"
    assert capabilities_payload["api_version"] == "v1"
    assert capabilities_payload["idempotency"]["operation_header"] == "X-Operation-ID"
    assert any(entity["name"] == "plants" for entity in capabilities_payload["entities"])

    bootstrap_response = client.get("/api/v1/sync/bootstrap", headers=auth_headers)
    assert bootstrap_response.status_code == 200
    bootstrap_payload = bootstrap_response.json()
    assert bootstrap_payload["user_id"]
    assert bootstrap_payload["baseline_cursor"]
    assert bootstrap_payload["capabilities_path"] == "/api/v1/sync/capabilities"
