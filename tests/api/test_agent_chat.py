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
    assert any(term in payload["reply"] for term in ["Current datetime in", "UTC", "GMT", "2026"])
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


def test_agent_chat_with_image_updates_langgraph_state(client: TestClient) -> None:
    from app.services.agent_chat import SYSTEM_PROMPT
    headers = register_and_auth_headers(client, "agent-image-state@example.com")

    update_state_calls = []

    class MockGraph:
        def get_state(self, config):
            class Snapshot:
                values = {}
            return Snapshot()

        def update_state(self, config, values):
            update_state_calls.append((config, values))

    original_graph = agent._graph
    agent._graph = MockGraph()
    original_detect = agent._detect_plant
    agent._detect_plant = lambda _img: PlantDetectionData(
        plant_name="Pothos",
        species="Epipremnum aureum",
        note="Bright indirect light; water when top soil dries.",
    )

    try:
        response = client.post(
            "/api/v1/agent/chat",
            json={
                "message": "tell me about this plant",
                "image_base64": "dGVzdA==dGVzdA==dGVzdA==dGVzdA==",
                "thread_id": "test_image_thread",
            },
            headers=headers,
        )
        assert response.status_code == 200

        # Verify update_state was called
        assert len(update_state_calls) == 1
        config, values = update_state_calls[0]
        assert config["configurable"]["thread_id"] == "test_image_thread"
        messages = values["messages"]
        assert len(messages) == 3
        assert messages[0].content.startswith(SYSTEM_PROMPT)
        assert "tell me about this plant" in messages[1].content
        assert "[Uploaded a plant image.]" in messages[1].content

        parsed_reply = json.loads(messages[2].content)
        assert parsed_reply["is_plant"] is True
        assert parsed_reply["data"]["plant_name"] == "Pothos"
    finally:
        agent._graph = original_graph
        agent._detect_plant = original_detect


def test_agent_chat_with_image_and_question_returns_plain_text(client: TestClient) -> None:
    headers = register_and_auth_headers(client, "agent-image-question@example.com")

    original_classify = agent._classify_intent
    original_answer = agent._answer_question_with_image

    agent._classify_intent = lambda _msg: "QUESTION"
    agent._answer_question_with_image = lambda _msg, _img: "This is a beautiful Pothos plant."

    try:
        response = client.post(
            "/api/v1/agent/chat",
            json={
                "message": "what is this plant?",
                "image_base64": "dGVzdA==dGVzdA==dGVzdA==dGVzdA==",
            },
            headers=headers,
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["reply"] == "This is a beautiful Pothos plant."
        assert payload["tool_calls"] == []
    finally:
        agent._classify_intent = original_classify
        agent._answer_question_with_image = original_answer


