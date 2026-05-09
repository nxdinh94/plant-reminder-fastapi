import uuid
import json

from sqlalchemy import ForeignKey, String, Text, Integer, DateTime
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ChatPlantProposal(TimestampMixin, Base):
    __tablename__ = "chat_plant_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chat_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    proposal_payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    image_path: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_edited_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_plant_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    @property
    def plant_name(self) -> str:
        return self.proposal_payload.get("plant_name", "")

    @property
    def species(self) -> str:
        return self.proposal_payload.get("species", "")

    @property
    def note(self) -> str:
        return self.proposal_payload.get("note", "")

    @property
    def image_url(self) -> str:
        return self.image_path
