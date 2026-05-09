"""make chat_message_id nullable in chat_plant_proposals

Revision ID: 20260509_0007
Revises: 20260509_0006
Create Date: 2026-05-09
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260509_0007"
down_revision: str | None = "20260509_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "chat_plant_proposals",
        "chat_message_id",
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "chat_plant_proposals",
        "chat_message_id",
        nullable=False,
    )
