import json
import logging
from datetime import date, timedelta

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage
from app.schemas.chat import PlantDetectionData
import app.services.agent_chat as agent_chat_service
from app.services.agent_chat import agent


def register_and_auth_headers(client: TestClient, email: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 201
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_agent_chat_small_talk_uses_tool(client: TestClient, caplog) -> None:
    headers = register_and_auth_headers(client, "agent-chat@example.com")
    caplog.set_level(logging.INFO, logger="app.api.v1.endpoints.agent")

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
    assert "Agent chat tool calls" in caplog.text
    assert "small_talk_tool" in caplog.text


def test_agent_chat_small_talk_bypasses_langgraph_when_llm_enabled(
    client: TestClient,
    monkeypatch,
) -> None:
    headers = register_and_auth_headers(client, "agent-chat-local-small-talk@example.com")

    class FailingGraph:
        def invoke(self, *_args, **_kwargs):
            raise AssertionError("small talk should not invoke LangGraph")

    original_graph = agent._graph
    original_llm_enabled = agent._llm_enabled
    agent._graph = FailingGraph()
    agent._llm_enabled = True
    monkeypatch.setattr(
        agent_chat_service,
        "generate_small_talk_response",
        lambda message, history=None, language="en": "Hi!",
    )
    try:
        response = client.post(
            "/api/v1/agent/chat",
            json={"message": "hi", "thread_id": "small_talk_local_thread"},
            headers=headers,
        )
    finally:
        agent._graph = original_graph
        agent._llm_enabled = original_llm_enabled

    assert response.status_code == 200
    payload = response.json()
    assert payload["reply"] == "Hi!"
    assert payload["tool_calls"] == [{"name": "small_talk_tool"}]


def test_agent_chat_reports_only_current_turn_graph_tool_calls(client: TestClient) -> None:
    headers = register_and_auth_headers(client, "agent-current-turn-tools@example.com")

    previous_messages = [
        HumanMessage(content="show my plants"),
        AIMessage(
            content="",
            tool_calls=[
                {"name": "users_plant_insight_tool", "args": {}, "id": "previous-plant"}
            ],
        ),
        HumanMessage(content="show my journal"),
        AIMessage(
            content="",
            tool_calls=[
                {"name": "users_journal_insight_tool", "args": {}, "id": "previous-journal"}
            ],
        ),
    ]

    class CurrentTurnGraph:
        def get_state(self, _config):
            class Snapshot:
                values = {"messages": previous_messages}
                interrupts = []

            return Snapshot()

        def invoke(self, *_args, **_kwargs):
            return {
                "messages": previous_messages
                + [
                    HumanMessage(content="can you help with something"),
                    AIMessage(
                        content="Sure.",
                        tool_calls=[
                            {"name": "small_talk_tool", "args": {}, "id": "current-small-talk"}
                        ],
                    ),
                    AIMessage(content="Sure."),
                ]
            }

    original_graph = agent._graph
    original_llm_enabled = agent._llm_enabled
    agent._graph = CurrentTurnGraph()
    agent._llm_enabled = True
    try:
        response = client.post(
            "/api/v1/agent/chat",
            json={
                "message": "can you help with something",
                "thread_id": "current_turn_tool_thread",
            },
            headers=headers,
        )
    finally:
        agent._graph = original_graph
        agent._llm_enabled = original_llm_enabled

    assert response.status_code == 200
    payload = response.json()
    assert payload["reply"] == "Sure."
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


def test_agent_chat_plant_question_uses_plant_insight_tool(client: TestClient) -> None:
    headers = register_and_auth_headers(client, "agent-plant-insight@example.com")
    action_type_response = client.post(
        "/api/v1/action-types",
        json={"name": "Water", "icon": "water", "color": "#00AEEF"},
        headers=headers,
    )
    assert action_type_response.status_code == 201
    pothos_response = client.post(
        "/api/v1/plants",
        json={
            "name": "Pothos",
            "species": "Epipremnum aureum",
            "note": "Trailing plant on the kitchen shelf.",
            "water": "Water when the top soil dries.",
        },
        headers=headers,
    )
    assert pothos_response.status_code == 201
    snake_plant_response = client.post(
        "/api/v1/plants",
        json={
            "name": "Snake Plant",
            "species": "Dracaena trifasciata",
            "note": "Bedroom plant.",
        },
        headers=headers,
    )
    assert snake_plant_response.status_code == 201
    schedule_response = client.post(
        "/api/v1/schedules",
        json={
            "plant_id": pothos_response.json()["id"],
            "action_type_id": action_type_response.json()["id"],
            "frequency_type": "INTERVAL",
            "frequency_days": 3,
            "scheduled_time": "09:00:00",
            "start_date": "2026-06-01",
        },
        headers=headers,
    )
    assert schedule_response.status_code == 201
    completion_response = client.post(
        "/api/v1/task-completions",
        json={
            "schedule_id": schedule_response.json()["id"],
            "completion_date": "2026-06-18",
        },
        headers=headers,
    )
    assert completion_response.status_code == 201

    response = client.post(
        "/api/v1/agent/chat",
        json={"message": "show all plants I have"},
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["tool_calls"] == [{"name": "users_plant_insight_tool"}]
    assert "Pothos" in payload["reply"]
    assert "Snake Plant" in payload["reply"]
    assert "schedules: 1, task completions: 1" in payload["reply"]
    assert "users_journal_insight_tool" not in [call["name"] for call in payload["tool_calls"]]


def test_agent_chat_missed_yesterday_uses_plant_insight_tool(client: TestClient) -> None:
    headers = register_and_auth_headers(client, "agent-missed-yesterday@example.com")
    action_type_response = client.post(
        "/api/v1/action-types",
        json={"name": "Water", "icon": "water", "color": "#00AEEF"},
        headers=headers,
    )
    assert action_type_response.status_code == 201
    plant_response = client.post(
        "/api/v1/plants",
        json={"name": "Pothos", "species": "Epipremnum aureum"},
        headers=headers,
    )
    assert plant_response.status_code == 201

    yesterday = date.today() - timedelta(days=1)
    schedule_response = client.post(
        "/api/v1/schedules",
        json={
            "plant_id": plant_response.json()["id"],
            "action_type_id": action_type_response.json()["id"],
            "frequency_type": "INTERVAL",
            "frequency_days": 1,
            "scheduled_time": "09:00:00",
            "start_date": yesterday.isoformat(),
        },
        headers=headers,
    )
    assert schedule_response.status_code == 201

    response = client.post(
        "/api/v1/agent/chat",
        json={"message": "tell me all task that i missed yesterday"},
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["tool_calls"] == [{"name": "users_plant_insight_tool"}]
    assert "datetime_tool" not in [call["name"] for call in payload["tool_calls"]]
    assert "**You missed 1 scheduled plant task(s)" in payload["reply"]
    assert "| Plant | Task | Time |" in payload["reply"]
    assert "Pothos" in payload["reply"]
    assert "missed 1 scheduled plant task" in payload["reply"]


def test_agent_chat_journal_question_uses_journal_insight_tool(client: TestClient) -> None:
    headers = register_and_auth_headers(client, "agent-journal-insight@example.com")
    plant_response = client.post(
        "/api/v1/plants",
        json={"name": "Pothos", "species": "Epipremnum aureum"},
        headers=headers,
    )
    assert plant_response.status_code == 201
    note_response = client.post(
        "/api/v1/notes",
        json={
            "plant_id": plant_response.json()["id"],
            "entry_date": "2026-06-18",
            "content": "New leaf opened near the window.",
            "tags": ["growth"],
            "image_paths": [],
        },
        headers=headers,
    )
    assert note_response.status_code == 201

    response = client.post(
        "/api/v1/agent/chat",
        json={"message": "what did I write about my pothos?"},
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["tool_calls"] == [{"name": "users_journal_insight_tool"}]
    assert "New leaf opened" in payload["reply"]
    assert "users_plant_insight_tool" not in [call["name"] for call in payload["tool_calls"]]


def test_agent_chat_ambiguous_my_plant_question_does_not_call_journal_tool(
    client: TestClient,
) -> None:
    headers = register_and_auth_headers(client, "agent-ambiguous-plant@example.com")
    plant_response = client.post(
        "/api/v1/plants",
        json={"name": "Snake Plant", "species": "Dracaena trifasciata"},
        headers=headers,
    )
    assert plant_response.status_code == 201

    response = client.post(
        "/api/v1/agent/chat",
        json={"message": "tell me about my plant"},
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["tool_calls"] == [{"name": "users_plant_insight_tool"}]


def test_agent_chat_insight_tools_do_not_expose_other_users_data(client: TestClient) -> None:
    owner_headers = register_and_auth_headers(client, "agent-owner-insight@example.com")
    other_headers = register_and_auth_headers(client, "agent-other-insight@example.com")

    owner_plant = client.post(
        "/api/v1/plants",
        json={"name": "Owner Orchid", "species": "Phalaenopsis"},
        headers=owner_headers,
    )
    assert owner_plant.status_code == 201
    owner_note = client.post(
        "/api/v1/notes",
        json={
            "plant_id": owner_plant.json()["id"],
            "entry_date": "2026-06-18",
            "content": "Owner-only bloom note.",
            "tags": ["bloom"],
            "image_paths": [],
        },
        headers=owner_headers,
    )
    assert owner_note.status_code == 201

    other_plant = client.post(
        "/api/v1/plants",
        json={"name": "Other Cactus", "species": "Mammillaria"},
        headers=other_headers,
    )
    assert other_plant.status_code == 201
    other_note = client.post(
        "/api/v1/notes",
        json={
            "plant_id": other_plant.json()["id"],
            "entry_date": "2026-06-18",
            "content": "Other-only cactus note.",
            "tags": ["private"],
            "image_paths": [],
        },
        headers=other_headers,
    )
    assert other_note.status_code == 201

    plant_response = client.post(
        "/api/v1/agent/chat",
        json={"message": "what plants do I have?"},
        headers=owner_headers,
    )
    journal_response = client.post(
        "/api/v1/agent/chat",
        json={"message": "show my journal entries"},
        headers=owner_headers,
    )

    assert plant_response.status_code == 200
    assert "Owner Orchid" in plant_response.json()["reply"]
    assert "Other Cactus" not in plant_response.json()["reply"]
    assert journal_response.status_code == 200
    assert "Owner-only bloom note" in journal_response.json()["reply"]
    assert "Other-only cactus note" not in journal_response.json()["reply"]


def test_agent_chat_insight_empty_states_are_clear(client: TestClient) -> None:
    headers = register_and_auth_headers(client, "agent-empty-insight@example.com")

    plant_response = client.post(
        "/api/v1/agent/chat",
        json={"message": "what plants do I have?"},
        headers=headers,
    )
    journal_response = client.post(
        "/api/v1/agent/chat",
        json={"message": "show my journal entries"},
        headers=headers,
    )

    assert plant_response.status_code == 200
    assert plant_response.json()["tool_calls"] == [{"name": "users_plant_insight_tool"}]
    assert "do not have any saved plants yet" in plant_response.json()["reply"]
    assert journal_response.status_code == 200
    assert journal_response.json()["tool_calls"] == [{"name": "users_journal_insight_tool"}]
    assert "do not have any plant journal entries yet" in journal_response.json()["reply"]


def test_agent_chat_plant_insight_falls_back_when_langgraph_fails(client: TestClient) -> None:
    headers = register_and_auth_headers(client, "agent-graph-fallback@example.com")
    plant_response = client.post(
        "/api/v1/plants",
        json={"name": "Fallback Fern", "species": "Nephrolepis exaltata"},
        headers=headers,
    )
    assert plant_response.status_code == 201

    class FailingGraph:
        def get_state(self, _config):
            class Snapshot:
                values = {}

            return Snapshot()

        def invoke(self, *_args, **_kwargs):
            raise RuntimeError("simulated graph failure")

    original_graph = agent._graph
    original_llm_enabled = agent._llm_enabled
    agent._graph = FailingGraph()
    agent._llm_enabled = True
    try:
        response = client.post(
            "/api/v1/agent/chat",
            json={"message": "show all plants I have"},
            headers=headers,
        )
    finally:
        agent._graph = original_graph
        agent._llm_enabled = original_llm_enabled

    assert response.status_code == 200
    payload = response.json()
    assert payload["tool_calls"] == [{"name": "users_plant_insight_tool"}]
    assert "Fallback Fern" in payload["reply"]
