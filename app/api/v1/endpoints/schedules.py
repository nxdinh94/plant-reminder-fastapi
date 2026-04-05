from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.endpoints.common import bump_version, soft_delete
from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.action_type import ActionType
from app.models.plant import Plant
from app.models.schedule import Schedule
from app.models.user import User
from app.schemas.schedule import (
    ScheduleCreate,
    ScheduleDeltaItem,
    ScheduleDeltaResponse,
    ScheduleDeltaTombstone,
    ScheduleResponse,
    ScheduleUpdate,
)


router = APIRouter(prefix="/schedules", tags=["schedules"])


def _validate_frequency(frequency_type: str, frequency_days: int | None, days_of_week: list[str] | None) -> None:
    normalized = frequency_type.upper()
    if normalized == "INTERVAL" and (frequency_days is None or frequency_days <= 0):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="frequency_days must be > 0 for INTERVAL schedules",
        )
    if normalized == "SPECIFIC_DAYS" and not days_of_week:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="days_of_week is required for SPECIFIC_DAYS schedules",
        )


def _ensure_ownership(db: Session, user_id: str, plant_id: str, action_type_id: str) -> None:
    plant = db.execute(
        select(Plant).where(
            Plant.id == plant_id,
            Plant.user_id == user_id,
            Plant.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if plant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plant not found")

    action_type = db.execute(
        select(ActionType).where(
            ActionType.id == action_type_id,
            ActionType.user_id == user_id,
            ActionType.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if action_type is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action type not found")


@router.get("", response_model=list[ScheduleResponse])
def list_schedules(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Schedule]:
    return list(
        db.execute(
            select(Schedule)
            .where(
                Schedule.user_id == current_user.id,
                Schedule.deleted_at.is_(None),
            )
            .order_by(Schedule.next_due_at.asc(), Schedule.updated_at.desc())
        ).scalars()
    )


@router.post("", response_model=ScheduleResponse, status_code=status.HTTP_201_CREATED)
def create_schedule(
    payload: ScheduleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Schedule:
    _validate_frequency(payload.frequency_type, payload.frequency_days, payload.days_of_week)
    _ensure_ownership(db, current_user.id, payload.plant_id, payload.action_type_id)

    entity = Schedule(user_id=current_user.id, **payload.model_dump())
    db.add(entity)
    db.commit()
    db.refresh(entity)
    return entity


@router.patch("/{schedule_id}", response_model=ScheduleResponse)
def update_schedule(
    schedule_id: str,
    payload: ScheduleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Schedule:
    entity = db.execute(
        select(Schedule).where(
            Schedule.id == schedule_id,
            Schedule.user_id == current_user.id,
            Schedule.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")

    update_data = payload.model_dump(exclude_unset=True)
    candidate_frequency = update_data.get("frequency_type", entity.frequency_type)
    candidate_days = update_data.get("frequency_days", entity.frequency_days)
    candidate_week = update_data.get("days_of_week", entity.days_of_week)
    _validate_frequency(candidate_frequency, candidate_days, candidate_week)

    candidate_plant_id = update_data.get("plant_id", entity.plant_id)
    candidate_action_type_id = update_data.get("action_type_id", entity.action_type_id)
    _ensure_ownership(db, current_user.id, candidate_plant_id, candidate_action_type_id)

    for key, value in update_data.items():
        setattr(entity, key, value)
    bump_version(entity)
    db.add(entity)
    db.commit()
    db.refresh(entity)
    return entity


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_schedule(
    schedule_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    entity = db.execute(
        select(Schedule).where(
            Schedule.id == schedule_id,
            Schedule.user_id == current_user.id,
            Schedule.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    soft_delete(entity)
    db.add(entity)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/delta", response_model=ScheduleDeltaResponse)
def get_schedule_delta(
    since: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ScheduleDeltaResponse:
    now = datetime.now(timezone.utc)

    changes_query = select(Schedule).where(
        Schedule.user_id == current_user.id,
        Schedule.deleted_at.is_(None),
    )
    tombstones_query = select(Schedule).where(
        Schedule.user_id == current_user.id,
        Schedule.deleted_at.is_not(None),
    )

    if since is not None:
        changes_query = changes_query.where(Schedule.updated_at >= since)
        tombstones_query = tombstones_query.where(Schedule.deleted_at >= since)

    changes = list(db.execute(changes_query.order_by(Schedule.updated_at.asc())).scalars())
    tombstones = list(db.execute(tombstones_query.order_by(Schedule.deleted_at.asc())).scalars())

    return ScheduleDeltaResponse(
        server_time=now,
        since=since,
        next_cursor=now,
        schedules=[
            ScheduleDeltaItem(
                id=item.id,
                plant_id=item.plant_id,
                action_type_id=item.action_type_id,
                frequency_type=item.frequency_type,
                frequency_days=item.frequency_days,
                days_of_week=item.days_of_week,
                scheduled_time=item.scheduled_time,
                next_due_at=item.next_due_at,
                updated_at=item.updated_at,
                version=item.version,
            )
            for item in changes
        ],
        tombstones=[
            ScheduleDeltaTombstone(
                id=item.id,
                deleted_at=item.deleted_at,
                version=item.version,
            )
            for item in tombstones
            if item.deleted_at is not None
        ],
    )
