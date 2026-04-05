from urllib.parse import unquote


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
        raise ValueError("remote image urls are not allowed in path-only sync")
    if decoded.startswith("content://"):
        return decoded
    if decoded.startswith("file://"):
        return decoded
    if decoded.startswith("/") or (len(decoded) > 2 and decoded[1] == ":" and decoded[2] == "/"):
        return decoded
    raise ValueError("image path must be a local absolute path or file/content URI")
