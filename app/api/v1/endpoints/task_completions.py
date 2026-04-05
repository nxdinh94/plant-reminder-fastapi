from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.api.v1.endpoints.common import bump_version, soft_delete
from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.schedule import Schedule
from app.models.task_completion import TaskCompletion
from app.models.user import User
from app.schemas.task_completion import (
    TaskCompletionCreate,
    TaskCompletionResponse,
    TaskCompletionToggleRequest,
    TaskCompletionUpdate,
)


router = APIRouter(prefix="/task-completions", tags=["task-completions"])


def _ensure_schedule_owner(db: Session, schedule_id: str, user_id: str) -> None:
    schedule = db.execute(
        select(Schedule).where(
            Schedule.id == schedule_id,
            Schedule.user_id == user_id,
            Schedule.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if schedule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")


@router.get("", response_model=list[TaskCompletionResponse])
def list_task_completions(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TaskCompletion]:
    filters = [TaskCompletion.user_id == current_user.id, TaskCompletion.deleted_at.is_(None)]
    if start_date is not None:
        filters.append(TaskCompletion.completion_date >= start_date)
    if end_date is not None:
        filters.append(TaskCompletion.completion_date <= end_date)

    return list(
        db.execute(
            select(TaskCompletion)
            .where(and_(*filters))
            .order_by(TaskCompletion.completion_date.desc(), TaskCompletion.created_at.desc())
        ).scalars()
    )


@router.post("", response_model=TaskCompletionResponse, status_code=status.HTTP_201_CREATED)
def create_task_completion(
    payload: TaskCompletionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TaskCompletion:
    _ensure_schedule_owner(db, payload.schedule_id, current_user.id)

    existing = db.execute(
        select(TaskCompletion).where(
            TaskCompletion.user_id == current_user.id,
            TaskCompletion.schedule_id == payload.schedule_id,
            TaskCompletion.completion_date == payload.completion_date,
            TaskCompletion.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Completion already exists")

    entity = TaskCompletion(
        user_id=current_user.id,
        schedule_id=payload.schedule_id,
        completion_date=payload.completion_date,
        completed_at=payload.completed_at or datetime.now(timezone.utc),
    )
    db.add(entity)
    db.commit()
    db.refresh(entity)
    return entity


@router.patch("/{task_completion_id}", response_model=TaskCompletionResponse)
def update_task_completion(
    task_completion_id: str,
    payload: TaskCompletionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TaskCompletion:
    entity = db.execute(
        select(TaskCompletion).where(
            TaskCompletion.id == task_completion_id,
            TaskCompletion.user_id == current_user.id,
            TaskCompletion.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task completion not found")

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(entity, key, value)
    bump_version(entity)
    db.add(entity)
    db.commit()
    db.refresh(entity)
    return entity


@router.put("/{schedule_id}/{completion_date}/toggle", response_model=TaskCompletionResponse | None)
def toggle_task_completion(
    schedule_id: str,
    completion_date: date,
    payload: TaskCompletionToggleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TaskCompletion | None:
    _ensure_schedule_owner(db, schedule_id, current_user.id)

    entity = db.execute(
        select(TaskCompletion).where(
            TaskCompletion.user_id == current_user.id,
            TaskCompletion.schedule_id == schedule_id,
            TaskCompletion.completion_date == completion_date,
            TaskCompletion.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    if payload.completed:
        if entity is None:
            entity = TaskCompletion(
                user_id=current_user.id,
                schedule_id=schedule_id,
                completion_date=completion_date,
                completed_at=datetime.now(timezone.utc),
            )
        else:
            entity.completed_at = datetime.now(timezone.utc)
            bump_version(entity)
        db.add(entity)
        db.commit()
        db.refresh(entity)
        return entity

    if entity is None:
        return None

    soft_delete(entity)
    db.add(entity)
    db.commit()
    return None


@router.delete("/{task_completion_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_task_completion(
    task_completion_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    entity = db.execute(
        select(TaskCompletion).where(
            TaskCompletion.id == task_completion_id,
            TaskCompletion.user_id == current_user.id,
            TaskCompletion.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task completion not found")
    soft_delete(entity)
    db.add(entity)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
