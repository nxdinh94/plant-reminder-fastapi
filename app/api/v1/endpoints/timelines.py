from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.endpoints.common import bump_version, soft_delete
from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.plant import Plant
from app.models.timeline import Timeline
from app.models.user import User
from app.schemas.timeline import TimelineCreate, TimelineResponse, TimelineUpdate


router = APIRouter(prefix="/timelines", tags=["timelines"])


def _ensure_plant_owner(db: Session, plant_id: str, user_id: str) -> None:
    plant = db.execute(
        select(Plant).where(
            Plant.id == plant_id,
            Plant.user_id == user_id,
            Plant.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if plant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plant not found")


@router.get("", response_model=list[TimelineResponse])
def list_timelines(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Timeline]:
    return list(
        db.execute(
            select(Timeline)
            .where(
                Timeline.user_id == current_user.id,
                Timeline.deleted_at.is_(None),
            )
            .order_by(Timeline.updated_at.desc())
        ).scalars()
    )


@router.post("", response_model=TimelineResponse, status_code=status.HTTP_201_CREATED)
def create_timeline(
    payload: TimelineCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Timeline:
    _ensure_plant_owner(db, payload.plant_id, current_user.id)
    entity = Timeline(user_id=current_user.id, **payload.model_dump())
    db.add(entity)
    db.commit()
    db.refresh(entity)
    return entity


@router.patch("/{timeline_id}", response_model=TimelineResponse)
def update_timeline(
    timeline_id: str,
    payload: TimelineUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Timeline:
    entity = db.execute(
        select(Timeline).where(
            Timeline.id == timeline_id,
            Timeline.user_id == current_user.id,
            Timeline.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timeline entry not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(entity, key, value)
    bump_version(entity)
    db.add(entity)
    db.commit()
    db.refresh(entity)
    return entity


@router.delete("/{timeline_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_timeline(
    timeline_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    entity = db.execute(
        select(Timeline).where(
            Timeline.id == timeline_id,
            Timeline.user_id == current_user.id,
            Timeline.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timeline entry not found")
    soft_delete(entity)
    db.add(entity)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
