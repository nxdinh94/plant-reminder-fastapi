"""add chat messages table for per-user thread history

Revision ID: 20260503_0005
Revises: 20260430_0004
Create Date: 2026-05-03
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260503_0005"
down_revision: str | None = "20260430_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chat_messages_user_id"), "chat_messages", ["user_id"], unique=False)
    op.create_index(
        "ix_chat_messages_user_thread_created_at",
        "chat_messages",
        ["user_id", "thread_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_chat_messages_user_thread_id",
        "chat_messages",
        ["user_id", "thread_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_chat_messages_user_thread_id", table_name="chat_messages")
    op.drop_index("ix_chat_messages_user_thread_created_at", table_name="chat_messages")
    op.drop_index(op.f("ix_chat_messages_user_id"), table_name="chat_messages")
    op.drop_table("chat_messages")
