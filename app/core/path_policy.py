from urllib.parse import unquote, urlparse

from app.core.config import settings


MAX_IMAGE_PATH_LENGTH = 1024


def normalize_image_path(path: str) -> str:
    value = path.strip()
    if not value:
        raise ValueError("image path cannot be blank")
    if len(value) > MAX_IMAGE_PATH_LENGTH:
        raise ValueError("image path exceeds max length")

    decoded = unquote(value).replace("\\", "/")
    if ".." in decoded:
        raise ValueError("path traversal segments are not allowed")
    if decoded.startswith(("http://", "https://")):
        return _normalize_remote_image_url(decoded)
    if decoded.startswith("content://"):
        return decoded
    if decoded.startswith("file://"):
        return decoded
    if decoded.startswith("/") or (len(decoded) > 2 and decoded[1] == ":" and decoded[2] == "/"):
        return decoded
    raise ValueError("image path must be a local absolute path or file/content URI")


def _normalize_remote_image_url(value: str) -> str:
    if not value.startswith("https://"):
        raise ValueError("remote image urls must use https")

    allowed_base = (settings.r2_public_base_url or "").strip().rstrip("/")
    if not allowed_base:
        raise ValueError("remote image urls are not allowed unless R2_PUBLIC_BASE_URL is configured")

    parsed_value = urlparse(value)
    parsed_base = urlparse(allowed_base)
    if parsed_value.scheme != "https" or parsed_value.netloc != parsed_base.netloc:
        raise ValueError("remote image url must match configured R2_PUBLIC_BASE_URL")

    base_path = parsed_base.path.rstrip("/")
    if base_path and not (
        parsed_value.path == base_path or parsed_value.path.startswith(f"{base_path}/")
    ):
        raise ValueError("remote image url must be under configured R2_PUBLIC_BASE_URL")

    return value
