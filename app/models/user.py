import uuid
from datetime import datetime

from sqlalchemy import Boolean, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    plan_tier: Mapped[str] = mapped_column(
        String(50),
        default="free",
        server_default="free",
        nullable=False,
    )
    revenuecat_app_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    revenuecat_product_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    revenuecat_store: Mapped[str | None] = mapped_column(String(50), nullable=True)
    revenuecat_environment: Mapped[str | None] = mapped_column(String(50), nullable=True)
    plan_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    plan_last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    plan_last_revenuecat_event_type: Mapped[str | None] = mapped_column(String(100), nullable=True)


