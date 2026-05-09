"""add plant image proposals for hitl gating

Revision ID: 20260430_0004
Revises: 20260404_0003
Create Date: 2026-04-30
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260430_0004"
down_revision: str | None = "20260404_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plant_image_proposals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("plant_name", sa.String(length=200), nullable=False),
        sa.Column("species", sa.String(length=200), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index(op.f("ix_plant_image_proposals_user_id"), "plant_image_proposals", ["user_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_plant_image_proposals_user_id"), table_name="plant_image_proposals")
    op.drop_table("plant_image_proposals")
