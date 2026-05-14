"""create knowledge topic and article tables

Revision ID: 20260513_0009
Revises: 20260511_0008
Create Date: 2026-05-13
"""

from alembic import op
import sqlalchemy as sa


revision = "20260513_0009"
down_revision = "20260511_0008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "knowledge_topics",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("cover_image_url", sa.String(length=1024), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_knowledge_topics_slug", "knowledge_topics", ["slug"], unique=True)
    op.create_index("ix_knowledge_topics_sort_order", "knowledge_topics", ["sort_order"], unique=False)

    op.create_table(
        "knowledge_articles",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("topic_id", sa.String(length=36), nullable=False),
        sa.Column("slug", sa.String(length=140), nullable=False),
        sa.Column("title", sa.String(length=220), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("hero_image_url", sa.String(length=1024), nullable=False),
        sa.Column("html_content", sa.Text(), nullable=False),
        sa.Column("read_minutes", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["topic_id"], ["knowledge_topics.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_knowledge_articles_slug", "knowledge_articles", ["slug"], unique=True)
    op.create_index("ix_knowledge_articles_topic_id", "knowledge_articles", ["topic_id"], unique=False)
    op.create_index("ix_knowledge_articles_sort_order", "knowledge_articles", ["sort_order"], unique=False)


def downgrade():
    op.drop_index("ix_knowledge_articles_sort_order", table_name="knowledge_articles")
    op.drop_index("ix_knowledge_articles_topic_id", table_name="knowledge_articles")
    op.drop_index("ix_knowledge_articles_slug", table_name="knowledge_articles")
    op.drop_table("knowledge_articles")

    op.drop_index("ix_knowledge_topics_sort_order", table_name="knowledge_topics")
    op.drop_index("ix_knowledge_topics_slug", table_name="knowledge_topics")
    op.drop_table("knowledge_topics")
