import uuid
from datetime import date, datetime, time

from sqlalchemy import Date, DateTime, ForeignKey, Integer, JSON, String, Text, Time
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SyncMetadataMixin


class Schedule(SyncMetadataMixin, Base):
    __tablename__ = "schedules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plant_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("plants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action_type_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("action_types.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    frequency_type: Mapped[str] = mapped_column(String(32), nullable=False)
    frequency_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    days_of_week: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    scheduled_time: Mapped[time] = mapped_column(Time, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
