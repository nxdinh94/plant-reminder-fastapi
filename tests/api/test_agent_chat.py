import json

from fastapi.testclient import TestClient
from app.schemas.chat import PlantDetectionData
from app.services.agent_chat import agent


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
    assert isinstance(payload["reply"], str)
    assert payload["reply"].strip()
    assert payload["tool_calls"] == [{"name": "small_talk_tool"}]


def test_agent_chat_requires_auth(client: TestClient) -> None:
    response = client.post(
        "/api/v1/agent/chat",
        json={"message": "hello"},
    )

    assert response.status_code == 401


def test_agent_chat_datetime_uses_tool(client: TestClient) -> None:
    headers = register_and_auth_headers(client, "agent-datetime@example.com")

    response = client.post(
        "/api/v1/agent/chat",
        json={"message": "what time is it now?"},
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert "Current datetime in" in payload["reply"]
    assert payload["tool_calls"] == [{"name": "datetime_tool"}]


def test_agent_chat_with_image_uses_plant_detect_tool_and_returns_json(client: TestClient) -> None:
    headers = register_and_auth_headers(client, "agent-image@example.com")

    original = agent._detect_plant
    agent._detect_plant = lambda _img: PlantDetectionData(
        plant_name="Pothos",
        species="Epipremnum aureum",
        note="Bright indirect light; water when top soil dries.",
    )
    try:
        response = client.post(
            "/api/v1/agent/chat",
            json={
                "message": "analyze this image",
                "image_base64": "dGVzdA==dGVzdA==dGVzdA==dGVzdA==",
            },
            headers=headers,
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["tool_calls"] == [{"name": "plant_image_detect_tool"}]
        parsed = json.loads(payload["reply"])
        assert parsed["is_plant"] is True
        assert parsed["data"]["plant_name"] == "Pothos"
    finally:
        agent._detect_plant = original
