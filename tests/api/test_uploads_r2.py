from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import media_storage
from app.services.media_storage import MediaStorageRemoteError


def auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "upload-r2@example.com", "password": "password123"},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_upload_proxies_to_r2_and_returns_public_url(
    client: TestClient,
    monkeypatch,
    tmp_path,
) -> None:
    captured: dict[str, object] = {}

    async def fake_put(key: str, content: bytes, content_type: str) -> str:
        captured["key"] = key
        captured["content"] = content
        captured["content_type"] = content_type
        return f"https://files.example.com/{key}"

    monkeypatch.setattr(settings, "media_storage_backend", "r2")
    monkeypatch.setattr(settings, "r2_worker_upload_url", "https://worker.example.com")
    monkeypatch.setattr(settings, "r2_worker_shared_secret", "secret")
    monkeypatch.setattr(settings, "r2_public_base_url", "https://files.example.com")
    monkeypatch.setattr(settings, "r2_key_prefix", "uploads")
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    monkeypatch.setattr(media_storage, "_put_r2_object_async", fake_put)

    response = client.post(
        "/api/v1/uploads",
        files={"file": ("leaf.jpg", b"image-bytes", "image/jpeg")},
        headers=auth_headers(client),
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["path"].startswith("https://files.example.com/uploads/users/")
    assert payload["file_id"]
    assert captured["content"] == b"image-bytes"
    assert captured["content_type"] == "image/jpeg"
    assert not list(tmp_path.iterdir())


def test_upload_uses_direct_r2_when_worker_url_is_not_configured(
    client: TestClient,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_put(key: str, content: bytes, content_type: str) -> str:
        captured["key"] = key
        captured["content"] = content
        captured["content_type"] = content_type
        return f"https://files.example.com/{key}"

    monkeypatch.setattr(settings, "media_storage_backend", "r2")
    monkeypatch.setattr(settings, "r2_worker_upload_url", None)
    monkeypatch.setattr(settings, "r2_account_id", "account-id")
    monkeypatch.setattr(settings, "r2_access_key_id", "access-key")
    monkeypatch.setattr(settings, "r2_secret_access_key", "secret-key")
    monkeypatch.setattr(settings, "r2_bucket_name", "r2-first-bucket")
    monkeypatch.setattr(settings, "r2_public_base_url", "https://files.example.com")
    monkeypatch.setattr(settings, "r2_key_prefix", "uploads")
    monkeypatch.setattr(media_storage, "_put_r2_object_s3_sync", fake_put)

    response = client.post(
        "/api/v1/uploads",
        files={"file": ("leaf.jpg", b"image-bytes", "image/jpeg")},
        headers=auth_headers(client),
    )

    assert response.status_code == 201
    assert response.json()["path"].startswith("https://files.example.com/uploads/users/")
    assert str(captured["key"]).startswith("uploads/users/")
    assert captured["content"] == b"image-bytes"
    assert captured["content_type"] == "image/jpeg"


def test_upload_returns_bad_gateway_when_worker_fails(
    client: TestClient,
    monkeypatch,
) -> None:
    async def fake_put(_key: str, _content: bytes, _content_type: str) -> str:
        raise MediaStorageRemoteError("worker unavailable")

    monkeypatch.setattr(settings, "media_storage_backend", "r2")
    monkeypatch.setattr(settings, "r2_worker_upload_url", "https://worker.example.com")
    monkeypatch.setattr(settings, "r2_worker_shared_secret", "secret")
    monkeypatch.setattr(settings, "r2_public_base_url", "https://files.example.com")
    monkeypatch.setattr(media_storage, "_put_r2_object_async", fake_put)

    response = client.post(
        "/api/v1/uploads",
        files={"file": ("leaf.jpg", b"image-bytes", "image/jpeg")},
        headers=auth_headers(client),
    )

    assert response.status_code == 502
    assert "worker unavailable" in response.json()["detail"]


def test_upload_rejects_invalid_file_types(client: TestClient) -> None:
    response = client.post(
        "/api/v1/uploads",
        files={"file": ("notes.txt", b"text", "text/plain")},
        headers=auth_headers(client),
    )

    assert response.status_code == 415


def test_upload_rejects_oversized_files(client: TestClient) -> None:
    response = client.post(
        "/api/v1/uploads",
        files={"file": ("leaf.jpg", b"x" * (10 * 1024 * 1024 + 1), "image/jpeg")},
        headers=auth_headers(client),
    )

    assert response.status_code == 413
