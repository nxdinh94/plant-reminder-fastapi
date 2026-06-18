from datetime import date, datetime, time, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.endpoints.common import bump_version, soft_delete
from app.core.config import settings
from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.models.profile_setting import ProfileSetting
from app.models.sync_operation import SyncOperation
from app.models import Plant, Note, Schedule, TaskCompletion, ActionType
from app.schemas.sync import (
    SyncBootstrapResponse,
    SyncCapabilitiesResponse,
    SyncEntityCapability,
    SyncIdempotencyCapability,
    SyncPullResponse,
    SyncPushOperation,
    SyncPushOperationResult,
    SyncPushRequest,
    SyncPushResponse,
)
from app.schemas.profile import ProfileSettingsUpdate
from app.schemas.plant import PlantCreate, PlantUpdate
from app.schemas.note import NoteCreate, NoteUpdate
from app.schemas.schedule import ScheduleCreate, ScheduleUpdate
from app.schemas.task_completion import TaskCompletionCreate, TaskCompletionUpdate
from app.schemas.action_type import ActionTypeCreate, ActionTypeUpdate

router = APIRouter()

MODEL_MAP = {
    "plant": Plant,
    "plants": Plant,
    "note": Note,
    "notes": Note,
    "schedule": Schedule,
    "schedules": Schedule,
    "task_completion": TaskCompletion,
    "task_completions": TaskCompletion,
    "action_type": ActionType,
    "action_types": ActionType,
    "profile_setting": ProfileSetting,
    "profile_settings": ProfileSetting,
}

CREATE_SCHEMA_MAP = {
    "plant": PlantCreate,
    "plants": PlantCreate,
    "note": NoteCreate,
    "notes": NoteCreate,
    "schedule": ScheduleCreate,
    "schedules": ScheduleCreate,
    "task_completion": TaskCompletionCreate,
    "task_completions": TaskCompletionCreate,
    "action_type": ActionTypeCreate,
    "action_types": ActionTypeCreate,
}

UPDATE_SCHEMA_MAP = {
    "plant": PlantUpdate,
    "plants": PlantUpdate,
    "note": NoteUpdate,
    "notes": NoteUpdate,
    "schedule": ScheduleUpdate,
    "schedules": ScheduleUpdate,
    "task_completion": TaskCompletionUpdate,
    "task_completions": TaskCompletionUpdate,
    "action_type": ActionTypeUpdate,
    "action_types": ActionTypeUpdate,
}

SYNC_ENTITIES = [
    SyncEntityCapability(name="plant"),
    SyncEntityCapability(name="plants"),
    SyncEntityCapability(name="note"),
    SyncEntityCapability(name="notes"),
    SyncEntityCapability(name="schedule"),
    SyncEntityCapability(name="schedules"),
    SyncEntityCapability(name="task_completion"),
    SyncEntityCapability(name="task_completions"),
    SyncEntityCapability(name="action_type"),
    SyncEntityCapability(name="action_types"),
    SyncEntityCapability(name="profile_setting"),
    SyncEntityCapability(name="profile_settings"),
]

SYNC_IDEMPOTENCY = SyncIdempotencyCapability()


def _serialize_value(value: Any) -> Any:
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return value


def _path_to_url(image_path: str | None) -> str | None:
    if not image_path:
        return None
    if image_path.startswith("http"):
        return image_path
    normalized = image_path.replace("\\", "/")
    upload_dir_str = str(settings.upload_dir_path).replace("\\", "/")
    if normalized.startswith(upload_dir_str):
        relative = normalized[len(upload_dir_str):].lstrip("/")
        return f"/uploads/{relative}"
    if "/uploads/" in normalized:
        idx = normalized.index("/uploads/")
        return normalized[idx:]
    return f"/uploads/{normalized.rsplit('/', 1)[-1]}"


def _serialize_entity(entity: Any) -> dict[str, Any]:
    result = {column.name: _serialize_value(getattr(entity, column.name)) for column in entity.__table__.columns}
    if hasattr(entity, "image_path") and result.get("image_path"):
        result["image_path"] = _path_to_url(result["image_path"])
    return result


def _get_entity_by_id(db: Session, model: Any, user_id: str, entity_id: str | None) -> Any | None:
    if entity_id is None:
        return None
    if model is ProfileSetting:
        return db.execute(
            select(ProfileSetting).where(
                ProfileSetting.user_id == user_id,
                ProfileSetting.deleted_at.is_(None),
            )
        ).scalar_one_or_none()
    return db.execute(
        select(model).where(
            model.id == entity_id,
            model.user_id == user_id,
            model.deleted_at.is_(None),
        )
    ).scalar_one_or_none()


def _ensure_note_plant_owner(db: Session, payload: dict[str, Any], current_user: User) -> None:
    plant_id = payload.get("plant_id")
    if not plant_id:
        return

    plant = db.execute(
        select(Plant).where(
            Plant.id == plant_id,
            Plant.user_id == current_user.id,
            Plant.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if plant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plant not found")


def _apply_profile_settings_mutation(
    db: Session,
    operation: str,
    payload: dict[str, Any],
    current_user: User,
) -> str:
    entity = db.execute(
        select(ProfileSetting).where(
            ProfileSetting.user_id == current_user.id,
            ProfileSetting.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    if operation == "delete":
        if entity is not None:
            db.delete(entity)
        return current_user.id

    data = ProfileSettingsUpdate.model_validate(payload).model_dump(exclude_unset=True)
    if entity is None:
        entity = ProfileSetting(user_id=current_user.id, **data)
    else:
        for key, value in data.items():
            setattr(entity, key, value)
        bump_version(entity)
    db.add(entity)
    return entity.user_id


def _apply_generic_mutation(
    db: Session,
    item: SyncPushOperation,
    current_user: User,
) -> str | None:
    model = MODEL_MAP.get(item.entity_type)
    if model is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported entity_type")

    if model is ProfileSetting:
        return _apply_profile_settings_mutation(db, item.operation, item.payload, current_user)

    if item.operation == "create":
        create_schema = CREATE_SCHEMA_MAP[item.entity_type]
        data = create_schema.model_validate(item.payload).model_dump(exclude_unset=True)
        if model is Note:
            _ensure_note_plant_owner(db, data, current_user)
        entity = model(user_id=current_user.id, **data)
        if item.entity_id:
            entity.id = item.entity_id
        db.add(entity)
        db.flush()
        return entity.id

    entity = _get_entity_by_id(db, model, current_user.id, item.entity_id)

    if item.operation == "upsert":
        if entity is None:
            create_schema = CREATE_SCHEMA_MAP[item.entity_type]
            data = create_schema.model_validate(item.payload).model_dump(exclude_unset=True)
            if model is Note:
                _ensure_note_plant_owner(db, data, current_user)
            entity = model(user_id=current_user.id, **data)
            if item.entity_id:
                entity.id = item.entity_id
            db.add(entity)
            db.flush()
            return entity.id
        update_schema = UPDATE_SCHEMA_MAP[item.entity_type]
        update_data = update_schema.model_validate(item.payload).model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(entity, key, value)
        bump_version(entity)
        db.add(entity)
        db.flush()
        return entity.id

    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found")

    if item.operation == "update":
        update_schema = UPDATE_SCHEMA_MAP[item.entity_type]
        update_data = update_schema.model_validate(item.payload).model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(entity, key, value)
        bump_version(entity)
        db.add(entity)
        db.flush()
        return entity.id

    if item.operation == "delete":
        if model is TaskCompletion:
            soft_delete(entity)
            db.add(entity)
            db.flush()
            return entity.id
        db.delete(entity)
        db.flush()
        return entity.id

    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported operation")


@router.get("/capabilities", response_model=SyncCapabilitiesResponse)
def get_sync_capabilities(_: User = Depends(get_current_user)) -> SyncCapabilitiesResponse:
    return SyncCapabilitiesResponse(
        server_time=datetime.now(timezone.utc),
        api_base_path=settings.api_v1_prefix,
        api_version="v1",
        entities=SYNC_ENTITIES,
        idempotency=SYNC_IDEMPOTENCY,
    )


@router.get("/bootstrap", response_model=SyncBootstrapResponse)
def bootstrap_sync(current_user: User = Depends(get_current_user)) -> SyncBootstrapResponse:
    return SyncBootstrapResponse(
        server_time=datetime.now(timezone.utc),
        user_id=current_user.id,
        baseline_cursor=current_user.updated_at,
        cursor_field="updated_at",
        capabilities_path=f"{settings.api_v1_prefix}/sync/capabilities",
    )


@router.post("/push", response_model=SyncPushResponse)
def push_sync_operations(
    payload: SyncPushRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SyncPushResponse:
    results: list[SyncPushOperationResult] = []

    for item in payload.operations:
        existing = db.get(SyncOperation, item.operation_id)
        if existing is not None and existing.user_id == current_user.id:
            results.append(
                SyncPushOperationResult(
                    operation_id=item.operation_id,
                    entity_type=item.entity_type,
                    entity_id=existing.entity_id,
                    status="duplicate",
                    retryable=False,
                    error=existing.error,
                )
            )
            continue

        try:
            entity_id = _apply_generic_mutation(db, item, current_user)
            db.add(
                SyncOperation(
                    operation_id=item.operation_id,
                    user_id=current_user.id,
                    entity_type=item.entity_type,
                    entity_id=entity_id,
                    status="applied",
                    error=None,
                )
            )
            results.append(
                SyncPushOperationResult(
                    operation_id=item.operation_id,
                    entity_type=item.entity_type,
                    entity_id=entity_id,
                    status="applied",
                    retryable=False,
                )
            )
        except HTTPException as exc:
            db.rollback()
            detail = str(exc.detail)
            try:
                db.add(
                    SyncOperation(
                        operation_id=item.operation_id,
                        user_id=current_user.id,
                        entity_type=item.entity_type,
                        entity_id=item.entity_id,
                        status="failed",
                        error=detail,
                    )
                )
            except Exception:
                pass
            results.append(
                SyncPushOperationResult(
                    operation_id=item.operation_id,
                    entity_type=item.entity_type,
                    entity_id=item.entity_id,
                    status="failed",
                    retryable=exc.status_code >= 500,
                    error=detail,
                )
            )
        except IntegrityError as exc:
            db.rollback()
            error = str(exc.orig)
            results.append(
                SyncPushOperationResult(
                    operation_id=item.operation_id,
                    entity_type=item.entity_type,
                    entity_id=item.entity_id,
                    status="failed",
                    retryable=False,
                    error=error,
                )
            )
        except Exception as exc:
            db.rollback()
            results.append(
                SyncPushOperationResult(
                    operation_id=item.operation_id,
                    entity_type=item.entity_type,
                    entity_id=item.entity_id,
                    status="failed",
                    retryable=True,
                    error=str(exc),
                )
            )

    db.commit()
    return SyncPushResponse(server_time=datetime.now(timezone.utc), results=results)


@router.get("/pull", response_model=SyncPullResponse)
def pull_sync_changes(
    since: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SyncPullResponse:
    changes: dict[str, list[dict[str, Any]]] = {}
    tombstones: dict[str, list[dict[str, Any]]] = {}
    now = datetime.now(timezone.utc)

    for entity_name, model in MODEL_MAP.items():
        change_filters = [model.user_id == current_user.id, model.deleted_at.is_(None)]
        if since is not None:
            change_filters.append(model.updated_at >= since)

        change_rows = list(db.execute(select(model).where(and_(*change_filters))).scalars())
        changes[entity_name] = [_serialize_entity(row) for row in change_rows]

        tombstone_filters = [model.user_id == current_user.id, model.deleted_at.is_not(None)]
        if since is not None:
            tombstone_filters.append(model.deleted_at >= since)

        deleted_rows = list(db.execute(select(model).where(and_(*tombstone_filters))).scalars())
        tombstones[entity_name] = [
            {
                "id": getattr(row, "id", getattr(row, "user_id", None)),
                "deleted_at": _serialize_value(row.deleted_at),
                "version": getattr(row, "version", 0),
            }
            for row in deleted_rows
        ]

    return SyncPullResponse(
        server_time=now,
        since=since,
        next_cursor=now,
        changes=changes,
        tombstones=tombstones,
    )
