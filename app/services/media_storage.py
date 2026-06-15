from __future__ import annotations

from dataclasses import dataclass
import asyncio
from pathlib import Path
from urllib.parse import quote
import uuid

import httpx
from fastapi import UploadFile, status

from app.core.config import settings


ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
CONTENT_TYPES_BY_EXTENSION = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
MAX_FILE_SIZE = 10 * 1024 * 1024
WORKER_SECRET_HEADER = "X-Upload-Secret"


@dataclass(frozen=True)
class StoredMedia:
    path: str
    file_id: str
    key: str
    content_type: str


class MediaStorageError(Exception):
    pass


class MediaStorageValidationError(MediaStorageError):
    def __init__(self, detail: str, status_code: int) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


class MediaStorageConfigurationError(MediaStorageError):
    pass


class MediaStorageRemoteError(MediaStorageError):
    pass


async def store_upload_file(file: UploadFile, *, user_id: str) -> StoredMedia:
    content = await file.read()
    return await store_image_bytes_async(
        content,
        user_id=user_id,
        original_filename=file.filename,
        supplied_content_type=file.content_type,
    )


async def store_image_bytes_async(
    content: bytes,
    *,
    user_id: str,
    original_filename: str | None,
    supplied_content_type: str | None,
    file_id: str | None = None,
) -> StoredMedia:
    prepared = _prepare_image(
        content,
        user_id=user_id,
        original_filename=original_filename,
        supplied_content_type=supplied_content_type,
        file_id=file_id,
    )

    if settings.media_storage_backend == "r2":
        url = await _put_r2_object_async(prepared.key, content, prepared.content_type)
        return StoredMedia(
            path=url,
            file_id=prepared.file_id,
            key=prepared.key,
            content_type=prepared.content_type,
        )

    return _store_local_image(content, prepared)


def store_image_bytes_sync(
    content: bytes,
    *,
    user_id: str,
    original_filename: str | None,
    supplied_content_type: str | None,
    file_id: str | None = None,
) -> StoredMedia:
    prepared = _prepare_image(
        content,
        user_id=user_id,
        original_filename=original_filename,
        supplied_content_type=supplied_content_type,
        file_id=file_id,
    )

    if settings.media_storage_backend == "r2":
        url = _put_r2_object_sync(prepared.key, content, prepared.content_type)
        return StoredMedia(
            path=url,
            file_id=prepared.file_id,
            key=prepared.key,
            content_type=prepared.content_type,
        )

    return _store_local_image(content, prepared)


def store_local_image_file_sync(path: Path, *, user_id: str, file_id: str | None = None) -> StoredMedia:
    if not path.exists() or not path.is_file():
        raise MediaStorageValidationError(
            f"Local upload file not found: {path}",
            status.HTTP_404_NOT_FOUND,
        )
    return store_image_bytes_sync(
        path.read_bytes(),
        user_id=user_id,
        original_filename=path.name,
        supplied_content_type=None,
        file_id=file_id or (path.stem if _looks_like_uuid(path.stem) else None),
    )


@dataclass(frozen=True)
class _PreparedImage:
    file_id: str
    extension: str
    content_type: str
    key: str


def _prepare_image(
    content: bytes,
    *,
    user_id: str,
    original_filename: str | None,
    supplied_content_type: str | None,
    file_id: str | None,
) -> _PreparedImage:
    if len(content) > MAX_FILE_SIZE:
        raise MediaStorageValidationError(
            "File too large. Maximum size is 10MB.",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )
    if not content:
        raise MediaStorageValidationError(
            "File is empty.",
            status.HTTP_400_BAD_REQUEST,
        )

    extension = Path(original_filename or "").suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise MediaStorageValidationError(
            f"Unsupported file type. Allowed: {allowed}",
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )

    content_type = _content_type_for_extension(extension, supplied_content_type)
    resolved_file_id = file_id or str(uuid.uuid4())
    key = _object_key(user_id=user_id, file_id=resolved_file_id, extension=extension)
    return _PreparedImage(
        file_id=resolved_file_id,
        extension=extension,
        content_type=content_type,
        key=key,
    )


def _content_type_for_extension(extension: str, supplied_content_type: str | None) -> str:
    expected = CONTENT_TYPES_BY_EXTENSION[extension]
    normalized = (supplied_content_type or "").split(";", 1)[0].strip().lower()
    if normalized and normalized != "application/octet-stream" and normalized != expected:
        raise MediaStorageValidationError(
            "Content type does not match file extension.",
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )
    return expected


def _store_local_image(content: bytes, prepared: _PreparedImage) -> StoredMedia:
    settings.upload_dir_path.mkdir(parents=True, exist_ok=True)
    filename = f"{prepared.file_id}{prepared.extension}"
    file_path = settings.upload_dir_path / filename
    file_path.write_bytes(content)
    return StoredMedia(
        path=f"/uploads/{filename}",
        file_id=prepared.file_id,
        key=filename,
        content_type=prepared.content_type,
    )


async def _put_r2_object_async(key: str, content: bytes, content_type: str) -> str:
    if not settings.r2_worker_upload_url:
        return await asyncio.to_thread(_put_r2_object_s3_sync, key, content, content_type)

    upload_url = _worker_object_url(key)
    headers = _worker_upload_headers(content_type)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.put(upload_url, content=content, headers=headers)
    except httpx.HTTPError as exc:
        raise MediaStorageRemoteError(f"R2 Worker upload request failed: {exc}") from exc
    return _parse_worker_response(response, key)


def _put_r2_object_sync(key: str, content: bytes, content_type: str) -> str:
    if not settings.r2_worker_upload_url:
        return _put_r2_object_s3_sync(key, content, content_type)

    upload_url = _worker_object_url(key)
    headers = _worker_upload_headers(content_type)
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.put(upload_url, content=content, headers=headers)
    except httpx.HTTPError as exc:
        raise MediaStorageRemoteError(f"R2 Worker upload request failed: {exc}") from exc
    return _parse_worker_response(response, key)


def _put_r2_object_s3_sync(key: str, content: bytes, content_type: str) -> str:
    account_id = (settings.r2_account_id or "").strip()
    access_key_id = (settings.r2_access_key_id or "").strip()
    secret_access_key = (settings.r2_secret_access_key or "").strip()
    bucket_name = (settings.r2_bucket_name or "").strip()
    if not all([account_id, access_key_id, secret_access_key, bucket_name]):
        raise MediaStorageConfigurationError(
            "R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, and R2_BUCKET_NAME "
            "are required when R2_WORKER_UPLOAD_URL is not configured"
        )

    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ModuleNotFoundError as exc:
        raise MediaStorageConfigurationError(
            "boto3 is required for direct R2 uploads. Reinstall backend dependencies."
        ) from exc

    client = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name="auto",
    )
    try:
        client.put_object(
            Bucket=bucket_name,
            Key=key,
            Body=content,
            ContentType=content_type,
            CacheControl="public, max-age=31536000, immutable",
        )
    except (BotoCoreError, ClientError) as exc:
        raise MediaStorageRemoteError(f"R2 direct upload failed: {exc}") from exc

    return _public_url_for_key(key)


def _worker_object_url(key: str) -> str:
    worker_url = (settings.r2_worker_upload_url or "").strip().rstrip("/")
    if not worker_url:
        raise MediaStorageConfigurationError("R2_WORKER_UPLOAD_URL is required for R2 media storage")
    return f"{worker_url}/objects/{quote(key, safe='/')}"


def _worker_upload_headers(content_type: str) -> dict[str, str]:
    shared_secret = (settings.r2_worker_shared_secret or "").strip()
    if not shared_secret:
        raise MediaStorageConfigurationError("R2_WORKER_SHARED_SECRET is required for R2 media storage")
    return {
        "Accept": "application/json",
        "Content-Type": content_type,
        WORKER_SECRET_HEADER: shared_secret,
    }


def _parse_worker_response(response: httpx.Response, key: str) -> str:
    if response.status_code >= 400:
        detail = response.text[:350]
        raise MediaStorageRemoteError(
            f"R2 Worker upload failed with status {response.status_code}: {detail}"
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise MediaStorageRemoteError("R2 Worker returned invalid JSON") from exc

    worker_url = payload.get("url")
    if isinstance(worker_url, str) and worker_url.strip():
        return _validate_public_url(worker_url.strip())
    return _public_url_for_key(key)


def _public_url_for_key(key: str) -> str:
    public_base_url = (settings.r2_public_base_url or "").strip().rstrip("/")
    if not public_base_url:
        raise MediaStorageConfigurationError("R2_PUBLIC_BASE_URL is required for R2 media storage")
    return f"{public_base_url}/{key}"


def _validate_public_url(url: str) -> str:
    public_base_url = (settings.r2_public_base_url or "").strip().rstrip("/")
    if not public_base_url:
        raise MediaStorageConfigurationError("R2_PUBLIC_BASE_URL is required for R2 media storage")
    if not url.startswith(f"{public_base_url}/"):
        raise MediaStorageRemoteError("R2 Worker returned a URL outside R2_PUBLIC_BASE_URL")
    return url


def _object_key(*, user_id: str, file_id: str, extension: str) -> str:
    prefix = settings.r2_key_prefix.strip().strip("/")
    suffix = f"users/{user_id}/images/{file_id}{extension}"
    if prefix:
        return f"{prefix}/{suffix}"
    return suffix


def _looks_like_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True
