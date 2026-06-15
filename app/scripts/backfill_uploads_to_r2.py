from __future__ import annotations

import argparse
import logging
from pathlib import Path
import uuid

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import ChatPlantProposal, Note, Plant
from app.services.media_storage import MediaStorageError, store_local_image_file_sync


logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill local /uploads image paths to Cloudflare R2 URLs.")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without uploading or updating rows.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if settings.media_storage_backend != "r2":
        raise SystemExit("Set MEDIA_STORAGE_BACKEND=r2 before running this backfill.")

    with SessionLocal() as db:
        summary = backfill(db, dry_run=args.dry_run)
        if args.dry_run:
            db.rollback()
        else:
            db.commit()

    logger.info(
        "Backfill complete: plants=%s notes=%s proposals=%s missing=%s skipped=%s",
        summary["plants"],
        summary["notes"],
        summary["proposals"],
        summary["missing"],
        summary["skipped"],
    )


def backfill(db: Session, *, dry_run: bool) -> dict[str, int]:
    cache: dict[tuple[str, str], str] = {}
    summary = {"plants": 0, "notes": 0, "proposals": 0, "missing": 0, "skipped": 0}

    for plant in db.query(Plant).all():
        updated = _backfill_single_path(plant.image_path, plant.user_id, cache, dry_run=dry_run)
        if updated.status == "updated":
            plant.image_path = updated.value
            summary["plants"] += 1
        else:
            summary[updated.status] += 1

    for note in db.query(Note).all():
        paths = note.image_paths or []
        new_paths: list[str] = []
        changed = False
        for image_path in paths:
            updated = _backfill_single_path(image_path, note.user_id, cache, dry_run=dry_run)
            if updated.status == "updated":
                new_paths.append(updated.value)
                changed = True
            else:
                new_paths.append(image_path)
                summary[updated.status] += 1
        if changed:
            note.image_paths = new_paths
            summary["notes"] += 1

    for proposal in db.query(ChatPlantProposal).all():
        updated = _backfill_single_path(proposal.image_path, proposal.user_id, cache, dry_run=dry_run)
        if updated.status == "updated":
            proposal.image_path = updated.value
            summary["proposals"] += 1
        else:
            summary[updated.status] += 1

    return summary


class _BackfillResult:
    def __init__(self, status: str, value: str = "") -> None:
        self.status = status
        self.value = value


def _backfill_single_path(
    image_path: str | None,
    user_id: str,
    cache: dict[tuple[str, str], str],
    *,
    dry_run: bool,
) -> _BackfillResult:
    local_path = _resolve_local_upload_path(image_path)
    if local_path is None:
        return _BackfillResult("skipped")
    if not local_path.exists():
        logger.warning("Missing local upload file: %s", local_path)
        return _BackfillResult("missing")

    cache_key = (user_id, str(local_path.resolve()))
    if cache_key in cache:
        return _BackfillResult("updated", cache[cache_key])

    if dry_run:
        logger.info("Would upload %s for user %s", local_path, user_id)
        return _BackfillResult("updated", f"dry-run://{local_path.name}")

    try:
        stored = store_local_image_file_sync(
            local_path,
            user_id=user_id,
            file_id=_stable_file_id(user_id, local_path),
        )
    except MediaStorageError:
        logger.exception("Failed to upload %s for user %s", local_path, user_id)
        raise

    cache[cache_key] = stored.path
    return _BackfillResult("updated", stored.path)


def _stable_file_id(user_id: str, local_path: Path) -> str:
    if _looks_like_uuid(local_path.stem):
        return local_path.stem
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{user_id}:{local_path.as_posix()}"))


def _resolve_local_upload_path(image_path: str | None) -> Path | None:
    if not image_path:
        return None
    normalized = image_path.replace("\\", "/").strip()
    if not normalized or normalized.startswith(("http://", "https://", "content://", "file://")):
        return None

    marker = "/uploads/"
    if normalized.startswith("/uploads/"):
        return settings.upload_dir_path / normalized.removeprefix("/uploads/")
    if marker in normalized:
        return settings.upload_dir_path / normalized.split(marker, 1)[1]

    path = Path(normalized)
    if path.is_absolute():
        return path
    return None


def _looks_like_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


if __name__ == "__main__":
    main()
