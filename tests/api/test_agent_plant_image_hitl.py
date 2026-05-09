from fastapi.testclient import TestClient

from app.schemas.chat import PlantDetectionData
from app.services.agent_chat import agent
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
