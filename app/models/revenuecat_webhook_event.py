from datetime import datetime
from sqlalchemy import String, DateTime, JSON, func
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

class RevenueCatWebhookEvent(Base):
    __tablename__ = "revenuecat_webhook_events"

    event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    app_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    original_app_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    aliases: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    environment: Mapped[str] = mapped_column(String(50), nullable=False)
    store: Mapped[str | None] = mapped_column(String(50), nullable=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    raw_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
