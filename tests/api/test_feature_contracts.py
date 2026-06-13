from datetime import date

from fastapi.testclient import TestClient


def auth_headers(client: TestClient, email: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 201
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_feature_crud_contracts(client: TestClient) -> None:
    headers = auth_headers(client, "contracts@example.com")

    action_type_response = client.post(
        "/api/v1/action-types",
        json={"name": "Watering", "icon": "water", "color": "#00AEEF"},
        headers=headers,
    )
    assert action_type_response.status_code == 201
    action_type_id = action_type_response.json()["id"]

    plant_response = client.post(
        "/api/v1/plants",
        json={
            "name": "Monstera",
            "species": "Monstera deliciosa",
            "potted_date": "2026-01-01",
            "image_path": "/local/path.jpg",
            "note": "Indoor",
            "is_paused": False,
        },
        headers=headers,
    )
    assert plant_response.status_code == 201
    plant_id = plant_response.json()["id"]

    schedule_response = client.post(
        "/api/v1/schedules",
        json={
            "plant_id": plant_id,
            "action_type_id": action_type_id,
            "frequency_type": "INTERVAL",
            "frequency_days": 3,
            "scheduled_time": "09:00:00",
            "start_date": "2026-01-01",
        },
        headers=headers,
    )
    assert schedule_response.status_code == 201
    schedule_id = schedule_response.json()["id"]

    schedule_delta_response = client.get("/api/v1/schedules/delta", headers=headers)
    assert schedule_delta_response.status_code == 200
    schedule_delta_payload = schedule_delta_response.json()
    assert any(item["id"] == schedule_id for item in schedule_delta_payload["schedules"])

    task_completion_response = client.post(
        "/api/v1/task-completions",
        json={
            "schedule_id": schedule_id,
            "completion_date": str(date.today()),
        },
        headers=headers,
    )
    assert task_completion_response.status_code == 201

    note_response = client.post(
        "/api/v1/notes",
        json={
            "plant_id": plant_id,
            "entry_date": "2026-01-02",
            "content": "Looks healthy",
            "tags": ["growth"],
            "image_paths": ["/local/notes/img1.jpg"],
        },
        headers=headers,
    )
    assert note_response.status_code == 201

    invalid_note_response = client.post(
        "/api/v1/notes",
        json={
            "plant_id": plant_id,
            "entry_date": "2026-01-03",
            "content": "Invalid image path should fail",
            "tags": [],
            "image_paths": ["../escape.jpg"],
        },
        headers=headers,
    )
    assert invalid_note_response.status_code == 422

    profile_get = client.get("/api/v1/profile/settings", headers=headers)
    assert profile_get.status_code == 200

    profile_update = client.put(
        "/api/v1/profile/settings",
        json={"points": 10, "streak_day": 2, "theme": "DARK"},
        headers=headers,
    )
    assert profile_update.status_code == 200
    assert profile_update.json()["points"] == 10


def test_sync_push_pull_contract(client: TestClient) -> None:
    headers = auth_headers(client, "sync-contracts@example.com")

    plant_response = client.post(
        "/api/v1/plants",
        json={
            "name": "Aloe",
            "species": "Aloe vera",
            "potted_date": "2026-02-01",
            "is_paused": False,
        },
        headers=headers,
    )
    assert plant_response.status_code == 201
    plant_id = plant_response.json()["id"]

    pull_before = client.get("/api/v1/sync/pull", headers=headers)
    assert pull_before.status_code == 200

    push_response = client.post(
        "/api/v1/sync/push",
        json={
            "operations": [
                {
                    "operation_id": "op-1",
                    "entity_type": "plants",
                    "operation": "update",
                    "entity_id": plant_id,
                    "payload": {"name": "Aloe Updated"},
                }
            ]
        },
        headers=headers,
    )
    assert push_response.status_code == 200
    first_result = push_response.json()["results"][0]
    assert first_result["status"] == "applied"

    note_push_response = client.post(
        "/api/v1/sync/push",
        json={
            "operations": [
                {
                    "operation_id": "op-note-1",
                    "entity_type": "notes",
                    "operation": "upsert",
                    "entity_id": None,
                    "payload": {
                        "plant_id": plant_id,
                        "entry_date": "2026-06-13",
                        "content": "New leaf unfurled",
                        "tags": ["growth", "photo"],
                        "image_paths": ["/uploads/note-1.jpg"],
                    },
                }
            ]
        },
        headers=headers,
    )
    assert note_push_response.status_code == 200
    note_result = note_push_response.json()["results"][0]
    assert note_result["status"] == "applied"
    note_id = note_result["entity_id"]
    assert note_id is not None

    duplicate_response = client.post(
        "/api/v1/sync/push",
        json={
            "operations": [
                {
                    "operation_id": "op-1",
                    "entity_type": "plants",
                    "operation": "update",
                    "entity_id": plant_id,
                    "payload": {"name": "Aloe Updated Again"},
                }
            ]
        },
        headers=headers,
    )
    assert duplicate_response.status_code == 200
    second_result = duplicate_response.json()["results"][0]
    assert second_result["status"] == "duplicate"

    pull_after = client.get("/api/v1/sync/pull", headers=headers)
    assert pull_after.status_code == 200
    payload = pull_after.json()
    assert "plants" in payload["changes"]
    assert any(item["id"] == plant_id for item in payload["changes"]["plants"])
    assert "notes" in payload["changes"]
    assert any(
        item["id"] == note_id
        and item["plant_id"] == plant_id
        and item["entry_date"] == "2026-06-13"
        and item["content"] == "New leaf unfurled"
        and item["tags"] == ["growth", "photo"]
        and item["image_paths"] == ["/uploads/note-1.jpg"]
        for item in payload["changes"]["notes"]
    )

    other_headers = auth_headers(client, "sync-contracts-other@example.com")
    other_pull = client.get("/api/v1/sync/pull", headers=other_headers)
    assert other_pull.status_code == 200
    assert not any(item["id"] == note_id for item in other_pull.json()["changes"]["notes"])


def test_schedule_recurrence_and_completion_filters(client: TestClient) -> None:
    headers = auth_headers(client, "recurrence-contracts@example.com")

    action_type_response = client.post(
        "/api/v1/action-types",
        json={"name": "Prune", "icon": "prune", "color": "#FEB05D"},
        headers=headers,
    )
    assert action_type_response.status_code == 201
    action_type_id = action_type_response.json()["id"]

    plant_response = client.post(
        "/api/v1/plants",
        json={
            "name": "Ficus",
            "species": "Ficus elastica",
            "potted_date": "2026-02-10",
            "is_paused": False,
        },
        headers=headers,
    )
    assert plant_response.status_code == 201
    plant_id = plant_response.json()["id"]

    invalid_interval = client.post(
        "/api/v1/schedules",
        json={
            "plant_id": plant_id,
            "action_type_id": action_type_id,
            "frequency_type": "INTERVAL",
            "frequency_days": 0,
            "scheduled_time": "10:00:00",
            "start_date": "2026-02-10",
        },
        headers=headers,
    )
    assert invalid_interval.status_code == 422

    invalid_specific_days = client.post(
        "/api/v1/schedules",
        json={
            "plant_id": plant_id,
            "action_type_id": action_type_id,
            "frequency_type": "SPECIFIC_DAYS",
            "scheduled_time": "10:00:00",
            "start_date": "2026-02-10",
        },
        headers=headers,
    )
    assert invalid_specific_days.status_code == 422

    valid_schedule = client.post(
        "/api/v1/schedules",
        json={
            "plant_id": plant_id,
            "action_type_id": action_type_id,
            "frequency_type": "SPECIFIC_DAYS",
            "days_of_week": ["MONDAY", "THURSDAY"],
            "scheduled_time": "10:00:00",
            "start_date": "2026-02-10",
        },
        headers=headers,
    )
    assert valid_schedule.status_code == 201
    schedule_id = valid_schedule.json()["id"]

    completion_date = "2026-02-12"
    create_completion = client.post(
        "/api/v1/task-completions",
        json={
            "schedule_id": schedule_id,
            "completion_date": completion_date,
        },
        headers=headers,
    )
    assert create_completion.status_code == 201

    list_response = client.get(
        "/api/v1/task-completions?start_date=2026-02-01&end_date=2026-02-28",
        headers=headers,
    )
    assert list_response.status_code == 200
    completions = list_response.json()
    assert any(item["schedule_id"] == schedule_id and item["completion_date"] == completion_date for item in completions)

    toggle_off = client.put(
        f"/api/v1/task-completions/{schedule_id}/{completion_date}/toggle",
        json={"completed": False},
        headers=headers,
    )
    assert toggle_off.status_code == 200
    assert toggle_off.json() is None


def test_cross_user_resource_isolation(client: TestClient) -> None:
    headers_user_a = auth_headers(client, "owner-a@example.com")
    headers_user_b = auth_headers(client, "owner-b@example.com")

    plant_response = client.post(
        "/api/v1/plants",
        json={
            "name": "Private Plant",
            "species": "Ficus lyrata",
            "potted_date": "2026-03-01",
            "is_paused": False,
        },
        headers=headers_user_a,
    )
    assert plant_response.status_code == 201
    plant_id = plant_response.json()["id"]

    get_other_user_plant = client.get(f"/api/v1/plants/{plant_id}", headers=headers_user_b)
    patch_other_user_plant = client.patch(
        f"/api/v1/plants/{plant_id}",
        json={"name": "Should Not Update"},
        headers=headers_user_b,
    )
    delete_other_user_plant = client.delete(f"/api/v1/plants/{plant_id}", headers=headers_user_b)
    sync_other_user_note = client.post(
        "/api/v1/sync/push",
        json={
            "operations": [
                {
                    "operation_id": "op-cross-user-note",
                    "entity_type": "notes",
                    "operation": "upsert",
                    "payload": {
                        "plant_id": plant_id,
                        "entry_date": "2026-06-13",
                        "content": "Should not attach to another user's plant",
                        "tags": [],
                        "image_paths": [],
                    },
                }
            ]
        },
        headers=headers_user_b,
    )

    assert get_other_user_plant.status_code == 404
    assert patch_other_user_plant.status_code == 404
    assert delete_other_user_plant.status_code == 404
    assert sync_other_user_note.status_code == 200
    sync_result = sync_other_user_note.json()["results"][0]
    assert sync_result["status"] == "failed"
    assert sync_result["error"] == "Plant not found"


def test_client_cannot_override_user_id_in_payload(client: TestClient) -> None:
    headers = auth_headers(client, "payload-owner@example.com")
    session_response = client.get("/api/v1/auth/session", headers=headers)
    assert session_response.status_code == 200
    current_user_id = session_response.json()["id"]

    forced_user_id = "00000000-0000-0000-0000-000000000000"
    create_response = client.post(
        "/api/v1/plants",
        json={
            "name": "Tamper Attempt",
            "species": "Epipremnum aureum",
            "potted_date": "2026-03-10",
            "is_paused": False,
            "user_id": forced_user_id,
        },
        headers=headers,
    )

    assert create_response.status_code == 201
    payload = create_response.json()
    assert payload["user_id"] == current_user_id
    assert payload["user_id"] != forced_user_id
