from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.endpoints.common import bump_version
from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.profile_setting import ProfileSetting
from app.models.user import User
from app.schemas.profile import ProfileSettingsResponse, ProfileSettingsUpdate


router = APIRouter(prefix="/profile", tags=["profile"])


def _get_or_create_profile_settings(db: Session, user_id: str) -> ProfileSetting:
    entity = db.execute(
        select(ProfileSetting).where(
            ProfileSetting.user_id == user_id,
            ProfileSetting.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if entity is not None:
        return entity

    entity = ProfileSetting(user_id=user_id)
    db.add(entity)
    db.commit()
    db.refresh(entity)
    return entity


@router.get("/settings", response_model=ProfileSettingsResponse)
def get_profile_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProfileSetting:
    return _get_or_create_profile_settings(db, current_user.id)


@router.put("/settings", response_model=ProfileSettingsResponse)
def update_profile_settings(
    payload: ProfileSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProfileSetting:
    entity = _get_or_create_profile_settings(db, current_user.id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(entity, key, value)
    bump_version(entity)
    db.add(entity)
    db.commit()
    db.refresh(entity)
    return entity
