from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.profile_setting import ProfileSetting


def ensure_user_defaults(db: Session, user_id: str) -> bool:
    """Create default records for a user if they don't already exist.

    Returns True if any new records were created, False if everything
    already existed.
    """
    created = False

    existing = db.execute(
        select(ProfileSetting).where(ProfileSetting.user_id == user_id)
    ).scalar_one_or_none()

    if existing is None:
        db.add(ProfileSetting(user_id=user_id))
        created = True

    return created
