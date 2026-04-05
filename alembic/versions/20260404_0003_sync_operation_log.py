"""add sync operation log

Revision ID: 20260404_0003
Revises: 20260404_0002
Create Date: 2026-04-04
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260404_0003"
down_revision: str | None = "20260404_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sync_operations",
        sa.Column("operation_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("operation_id"),
    )
    op.create_index(op.f("ix_sync_operations_user_id"), "sync_operations", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_sync_operations_user_id"), table_name="sync_operations")
    op.drop_table("sync_operations")
