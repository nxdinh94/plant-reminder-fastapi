from fastapi.testclient import TestClient


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
