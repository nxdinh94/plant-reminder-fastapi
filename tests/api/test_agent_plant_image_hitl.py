from fastapi.testclient import TestClient

from app.schemas.chat import PlantDetectionData
from app.services.agent_chat import agent
import app.services.agent_chat as agent_chat_module
from app.services.media_storage import StoredMedia
from tests.api.test_agent_chat import register_and_auth_headers


def test_plant_image_detect_then_accept(client: TestClient) -> None:
    headers = register_and_auth_headers(client, "plant-accept@example.com")

    original = agent._detect_plant
    agent._detect_plant = lambda _img: PlantDetectionData(
        plant_name="Peace Lily",
        species="Spathiphyllum wallisii",
        note="Keep in indirect light and water when top soil is dry.",
    )
    try:
        analyze = client.post(
            "/api/v1/agent/plant-image/analyze",
            json={"image_base64": "dGVzdA==dGVzdA==dGVzdA==dGVzdA=="},
            headers=headers,
        )
        assert analyze.status_code == 200
        payload = analyze.json()
        assert payload["status"] == "detected"
        assert payload["decision_required"] is True
        proposal_id = payload["proposal_id"]

        decision = client.post(
            "/api/v1/agent/plant-image/decision",
            json={"proposal_id": proposal_id, "decision": "accept"},
            headers=headers,
        )
        assert decision.status_code == 200
        decision_payload = decision.json()
        assert decision_payload["status"] == "accepted"
        assert decision_payload["data"]["plant_name"] == "Peace Lily"
        assert decision_payload["plant_url"]

        plants = client.get("/api/v1/plants", headers=headers)
        assert plants.status_code == 200
        assert any(item["name"] == "Peace Lily" for item in plants.json())
    finally:
        agent._detect_plant = original


def test_plant_image_analyze_stores_and_accepts_r2_url(
    client: TestClient,
    monkeypatch,
) -> None:
    headers = register_and_auth_headers(client, "plant-r2-accept@example.com")
    r2_url = "https://files.example.com/users/11111111-1111-4111-8111-111111111111/images/22222222-2222-4222-8222-222222222222.jpg"

    original = agent._detect_plant
    agent._detect_plant = lambda _img: PlantDetectionData(
        plant_name="R2 Lily",
        species="Spathiphyllum wallisii",
        note="Keep in indirect light.",
    )
    monkeypatch.setattr(
        agent_chat_module,
        "store_image_bytes_sync",
        lambda *_args, **_kwargs: StoredMedia(
            path=r2_url,
            file_id="22222222-2222-4222-8222-222222222222",
            key="users/11111111-1111-4111-8111-111111111111/images/22222222-2222-4222-8222-222222222222.jpg",
            content_type="image/jpeg",
        ),
    )

    try:
        analyze = client.post(
            "/api/v1/agent/plant-image/analyze",
            json={"image_base64": "dGVzdA==dGVzdA==dGVzdA==dGVzdA=="},
            headers=headers,
        )
        assert analyze.status_code == 200
        analyze_payload = analyze.json()
        assert analyze_payload["data"]["image_path"] == r2_url

        decision = client.post(
            "/api/v1/agent/plant-image/decision",
            json={"proposal_id": analyze_payload["proposal_id"], "decision": "accept"},
            headers=headers,
        )
        assert decision.status_code == 200

        plants = client.get("/api/v1/plants", headers=headers)
        assert plants.status_code == 200
        assert any(
            item["name"] == "R2 Lily" and item["image_path"] == r2_url
            for item in plants.json()
        )
    finally:
        agent._detect_plant = original


def test_plant_image_detect_then_edit(client: TestClient) -> None:
    headers = register_and_auth_headers(client, "plant-edit@example.com")

    original = agent._detect_plant
    agent._detect_plant = lambda _img: PlantDetectionData(
        plant_name="Snake Plant",
        species="Dracaena trifasciata",
        note="Water lightly every 2-3 weeks.",
    )
    try:
        analyze = client.post(
            "/api/v1/agent/plant-image/analyze",
            json={"image_base64": "dGVzdA==dGVzdA==dGVzdA==dGVzdA=="},
            headers=headers,
        )
        proposal_id = analyze.json()["proposal_id"]

        decision = client.post(
            "/api/v1/agent/plant-image/decision",
            json={
                "proposal_id": proposal_id,
                "decision": "edit",
                "edited_data": {
                    "plant_name": "Sansevieria",
                    "species": "Dracaena trifasciata",
                    "note": "Bright indirect light, sparse watering.",
                },
            },
            headers=headers,
        )
        assert decision.status_code == 200
        decision_payload = decision.json()
        assert decision_payload["status"] == "edited"
        assert decision_payload["data"]["plant_name"] == "Sansevieria"
    finally:
        agent._detect_plant = original


def test_plant_image_not_detected_returns_natural_message(client: TestClient) -> None:
    headers = register_and_auth_headers(client, "plant-not-detected@example.com")

    original = agent._detect_plant
    agent._detect_plant = lambda _img: None
    try:
        analyze = client.post(
            "/api/v1/agent/plant-image/analyze",
            json={"image_base64": "dGVzdA==dGVzdA==dGVzdA==dGVzdA=="},
            headers=headers,
        )
        assert analyze.status_code == 200
        payload = analyze.json()
        assert payload["status"] == "not_detected"
        assert "couldn't clearly detect a plant" in payload["reply"]
        assert payload["decision_required"] is False
    finally:
        agent._detect_plant = original


def test_plant_image_second_analyze_blocked_until_decision(client: TestClient) -> None:
    headers = register_and_auth_headers(client, "plant-blocked@example.com")

    original = agent._detect_plant
    agent._detect_plant = lambda _img: PlantDetectionData(
        plant_name="Pothos",
        species="Epipremnum aureum",
        note="Allow top 1-2 inches of soil to dry before watering.",
    )
    try:
        first = client.post(
            "/api/v1/agent/plant-image/analyze",
            json={"image_base64": "dGVzdA==dGVzdA==dGVzdA==dGVzdA=="},
            headers=headers,
        )
        assert first.status_code == 200
        first_payload = first.json()
        assert first_payload["status"] == "detected"
        assert first_payload["decision_required"] is True

        second = client.post(
            "/api/v1/agent/plant-image/analyze",
            json={"image_base64": "dGVzdA==dGVzdA==dGVzdA==dGVzdA=="},
            headers=headers,
        )
        assert second.status_code == 200
        second_payload = second.json()
        assert second_payload["status"] == "detected"
        assert second_payload["decision_required"] is True
        assert second_payload["proposal_id"] == first_payload["proposal_id"]
        assert "decision is still pending" in second_payload["reply"].lower()
    finally:
        agent._detect_plant = original


def test_plant_image_analyze_with_question(client: TestClient) -> None:
    headers = register_and_auth_headers(client, "plant-image-question@example.com")

    original_classify = agent._classify_intent
    original_answer = agent._answer_question_with_image

    agent._classify_intent = lambda _msg: "QUESTION"
    agent._answer_question_with_image = lambda _msg, _img: "This looks like a Monstera deliciosa."

    try:
        response = client.post(
            "/api/v1/agent/plant-image/analyze",
            json={
                "message": "is this plant healthy?",
                "image_base64": "dGVzdA==dGVzdA==dGVzdA==dGVzdA==",
            },
            headers=headers,
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "detected"
        assert payload["reply"] == "This looks like a Monstera deliciosa."
        assert payload["decision_required"] is False
        assert payload["proposal_id"] is None
        assert payload["data"] is None
    finally:
        agent._classify_intent = original_classify
        agent._answer_question_with_image = original_answer


def test_plant_image_analyze_and_decision_saves_history_to_chat(client: TestClient) -> None:
    headers = register_and_auth_headers(client, "plant-history-test@example.com")
    thread_id = "test-thread-id-999"

    original = agent._detect_plant
    agent._detect_plant = lambda _img: PlantDetectionData(
        plant_name="Fern",
        species="Nephrolepis exaltata",
        note="Keep moist and warm.",
    )
    try:
        # 1. Post to analyze
        analyze = client.post(
            "/api/v1/agent/plant-image/analyze",
            json={
                "image_base64": "dGVzdA==dGVzdA==dGVzdA==dGVzdA==",
                "thread_id": thread_id,
            },
            headers=headers,
        )
        assert analyze.status_code == 200
        proposal_id = analyze.json()["proposal_id"]

        # Verify SQL history has the uploaded image and analysis proposals
        history_after_analyze = client.get(
            f"/api/v1/agent/chat/history?thread_id={thread_id}",
            headers=headers,
        )
        assert history_after_analyze.status_code == 200
        items = history_after_analyze.json()["items"]
        assert len(items) == 2
        assert items[0]["role"] == "user"
        assert "Uploaded a plant image" in items[0]["content"]
        assert items[1]["role"] == "assistant"
        assert "I detected a plant" in items[1]["content"]

        # 2. Reject decision
        decision = client.post(
            "/api/v1/agent/plant-image/decision",
            json={
                "proposal_id": proposal_id,
                "decision": "reject",
                "thread_id": thread_id,
            },
            headers=headers,
        )
        assert decision.status_code == 200

        # Verify SQL history has decision actions recorded
        history_after_decision = client.get(
            f"/api/v1/agent/chat/history?thread_id={thread_id}",
            headers=headers,
        )
        assert history_after_decision.status_code == 200
        items_dec = history_after_decision.json()["items"]
        assert len(items_dec) == 4
        assert items_dec[2]["role"] == "user"
        assert "I reject the proposal" in items_dec[2]["content"]
        assert items_dec[3]["role"] == "assistant"
        assert "Understood" in items_dec[3]["content"]

    finally:
        agent._detect_plant = original

