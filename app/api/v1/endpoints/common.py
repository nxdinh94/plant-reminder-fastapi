from datetime import datetime, timezone
from typing import Any


def bump_version(entity: Any) -> None:
    current = getattr(entity, "version", 0) or 0
    setattr(entity, "version", int(current) + 1)


def soft_delete(entity: Any) -> None:
    setattr(entity, "deleted_at", datetime.now(timezone.utc))
    bump_version(entity)
