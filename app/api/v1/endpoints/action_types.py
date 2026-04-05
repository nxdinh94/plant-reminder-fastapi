from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.endpoints.common import bump_version, soft_delete
from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.action_type import ActionType
from app.models.user import User
from app.schemas.action_type import ActionTypeCreate, ActionTypeResponse, ActionTypeUpdate


router = APIRouter(prefix="/action-types", tags=["action-types"])


@router.get("", response_model=list[ActionTypeResponse])
def list_action_types(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ActionType]:
    return list(
        db.execute(
            select(ActionType)
            .where(
                ActionType.user_id == current_user.id,
                ActionType.deleted_at.is_(None),
            )
            .order_by(ActionType.name.asc())
        ).scalars()
    )


@router.post("", response_model=ActionTypeResponse, status_code=status.HTTP_201_CREATED)
def create_action_type(
    payload: ActionTypeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ActionType:
    entity = ActionType(user_id=current_user.id, **payload.model_dump())
    db.add(entity)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Action type name already exists") from exc
    db.refresh(entity)
    return entity


@router.patch("/{action_type_id}", response_model=ActionTypeResponse)
def update_action_type(
    action_type_id: str,
    payload: ActionTypeUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ActionType:
    entity = db.execute(
        select(ActionType).where(
            ActionType.id == action_type_id,
            ActionType.user_id == current_user.id,
            ActionType.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action type not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(entity, key, value)
    bump_version(entity)
    db.add(entity)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Action type name already exists") from exc
    db.refresh(entity)
    return entity


@router.delete("/{action_type_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_action_type(
    action_type_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    entity = db.execute(
        select(ActionType).where(
            ActionType.id == action_type_id,
            ActionType.user_id == current_user.id,
            ActionType.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action type not found")
    soft_delete(entity)
    db.add(entity)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
