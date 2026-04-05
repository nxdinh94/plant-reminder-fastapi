"""add sync schema tables

Revision ID: 20260404_0002
Revises: 20260404_0001
Create Date: 2026-04-04
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260404_0002"
down_revision: str | None = "20260404_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _sync_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    ]


def upgrade() -> None:
    op.create_table(
        "action_types",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("icon", sa.String(length=80), nullable=False),
        sa.Column("color", sa.String(length=16), nullable=False),
        *_sync_columns(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_action_types_user_name"),
    )
    op.create_index(op.f("ix_action_types_user_id"), "action_types", ["user_id"], unique=False)

    op.create_table(
        "plants",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("species", sa.String(length=120), nullable=False),
        sa.Column("potted_date", sa.Date(), nullable=True),
        sa.Column("image_path", sa.String(length=1024), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("is_paused", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        *_sync_columns(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_plants_user_id"), "plants", ["user_id"], unique=False)

    op.create_table(
        "profile_settings",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("streak_day", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("theme", sa.String(length=32), nullable=False, server_default="LIGHT"),
        sa.Column("start_of_week", sa.String(length=16), nullable=True),
        sa.Column("device_preferences", sa.JSON(), nullable=True),
        *_sync_columns(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "schedules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("plant_id", sa.String(length=36), nullable=False),
        sa.Column("action_type_id", sa.String(length=36), nullable=False),
        sa.Column("frequency_type", sa.String(length=32), nullable=False),
        sa.Column("frequency_days", sa.Integer(), nullable=True),
        sa.Column("days_of_week", sa.JSON(), nullable=True),
        sa.Column("scheduled_time", sa.Time(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("last_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        *_sync_columns(),
        sa.ForeignKeyConstraint(["action_type_id"], ["action_types.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["plant_id"], ["plants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_schedules_action_type_id"), "schedules", ["action_type_id"], unique=False)
    op.create_index(op.f("ix_schedules_next_due_at"), "schedules", ["next_due_at"], unique=False)
    op.create_index(op.f("ix_schedules_plant_id"), "schedules", ["plant_id"], unique=False)
    op.create_index(op.f("ix_schedules_user_id"), "schedules", ["user_id"], unique=False)

    op.create_table(
        "task_completions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("schedule_id", sa.String(length=36), nullable=False),
        sa.Column("completion_date", sa.Date(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        *_sync_columns(),
        sa.ForeignKeyConstraint(["schedule_id"], ["schedules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("schedule_id", "completion_date", name="uq_task_completion_per_date"),
    )
    op.create_index(op.f("ix_task_completions_completion_date"), "task_completions", ["completion_date"], unique=False)
    op.create_index(op.f("ix_task_completions_schedule_id"), "task_completions", ["schedule_id"], unique=False)
    op.create_index(op.f("ix_task_completions_user_id"), "task_completions", ["user_id"], unique=False)

    op.create_table(
        "notes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("plant_id", sa.String(length=36), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("image_paths", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        *_sync_columns(),
        sa.ForeignKeyConstraint(["plant_id"], ["plants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_notes_plant_id"), "notes", ["plant_id"], unique=False)
    op.create_index(op.f("ix_notes_user_id"), "notes", ["user_id"], unique=False)

    op.create_table(
        "timelines",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("plant_id", sa.String(length=36), nullable=False),
        sa.Column("image_path", sa.String(length=1024), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        *_sync_columns(),
        sa.ForeignKeyConstraint(["plant_id"], ["plants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_timelines_plant_id"), "timelines", ["plant_id"], unique=False)
    op.create_index(op.f("ix_timelines_user_id"), "timelines", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_timelines_user_id"), table_name="timelines")
    op.drop_index(op.f("ix_timelines_plant_id"), table_name="timelines")
    op.drop_table("timelines")

    op.drop_index(op.f("ix_notes_user_id"), table_name="notes")
    op.drop_index(op.f("ix_notes_plant_id"), table_name="notes")
    op.drop_table("notes")

    op.drop_index(op.f("ix_task_completions_user_id"), table_name="task_completions")
    op.drop_index(op.f("ix_task_completions_schedule_id"), table_name="task_completions")
    op.drop_index(op.f("ix_task_completions_completion_date"), table_name="task_completions")
    op.drop_table("task_completions")

    op.drop_index(op.f("ix_schedules_user_id"), table_name="schedules")
    op.drop_index(op.f("ix_schedules_plant_id"), table_name="schedules")
    op.drop_index(op.f("ix_schedules_next_due_at"), table_name="schedules")
    op.drop_index(op.f("ix_schedules_action_type_id"), table_name="schedules")
    op.drop_table("schedules")

    op.drop_table("profile_settings")

    op.drop_index(op.f("ix_plants_user_id"), table_name="plants")
    op.drop_table("plants")

    op.drop_index(op.f("ix_action_types_user_id"), table_name="action_types")
    op.drop_table("action_types")
