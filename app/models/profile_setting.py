from sqlalchemy import ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SyncMetadataMixin


class ProfileSetting(SyncMetadataMixin, Base):
    __tablename__ = "profile_settings"

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    points: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    streak_day: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    theme: Mapped[str] = mapped_column(String(32), nullable=False, server_default="LIGHT")
    start_of_week: Mapped[str | None] = mapped_column(String(16), nullable=True)
    device_preferences: Mapped[dict | None] = mapped_column(JSON, nullable=True)
