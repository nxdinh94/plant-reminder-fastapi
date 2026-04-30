from fastapi.testclient import TestClient


def register_and_auth_headers(client: TestClient, email: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 201
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_agent_chat_small_talk_uses_tool(client: TestClient) -> None:
    headers = register_and_auth_headers(client, "agent-chat@example.com")

    response = client.post(
        "/api/v1/agent/chat",
        json={"message": "hello there"},
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert "Hi!" in payload["reply"]
    assert payload["tool_calls"] == [{"name": "small_talk_tool"}]


def test_agent_chat_requires_auth(client: TestClient) -> None:
    response = client.post(
        "/api/v1/agent/chat",
        json={"message": "hello"},
    )

    assert response.status_code == 401
