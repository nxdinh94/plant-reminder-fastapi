import uuid
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SyncMetadataMixin


class Plant(SyncMetadataMixin, Base):
    __tablename__ = "plants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    species: Mapped[str] = mapped_column(String(120), nullable=False)
    potted_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    image_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    overview: Mapped[str | None] = mapped_column(Text, nullable=True)
    water: Mapped[str | None] = mapped_column(Text, nullable=True)
    sunlight: Mapped[str | None] = mapped_column(Text, nullable=True)
    fertilizer: Mapped[str | None] = mapped_column(Text, nullable=True)
    propagating: Mapped[str | None] = mapped_column(Text, nullable=True)
    varieties: Mapped[str | None] = mapped_column(Text, nullable=True)
    humidity: Mapped[str | None] = mapped_column(Text, nullable=True)
    temperature: Mapped[str | None] = mapped_column(Text, nullable=True)
    soil: Mapped[str | None] = mapped_column(Text, nullable=True)
    running: Mapped[str | None] = mapped_column(Text, nullable=True)
    potting_and_repotting: Mapped[str | None] = mapped_column(Text, nullable=True)
    pests_and_diseases: Mapped[str | None] = mapped_column(Text, nullable=True)
    toxicity: Mapped[str | None] = mapped_column(Text, nullable=True)
    propagation: Mapped[str | None] = mapped_column(Text, nullable=True)
