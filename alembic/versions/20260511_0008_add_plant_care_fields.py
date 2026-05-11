"""add plant care fields

Revision ID: 20260511_0008
Revises: 20260509_0007
Create Date: 2026-05-11
"""
from alembic import op
import sqlalchemy as sa

revision = "20260511_0008"
down_revision = "20260509_0007"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("plants", sa.Column("overview", sa.Text(), nullable=True))
    op.add_column("plants", sa.Column("water", sa.Text(), nullable=True))
    op.add_column("plants", sa.Column("sunlight", sa.Text(), nullable=True))
    op.add_column("plants", sa.Column("fertilizer", sa.Text(), nullable=True))
    op.add_column("plants", sa.Column("propagating", sa.Text(), nullable=True))
    op.add_column("plants", sa.Column("varieties", sa.Text(), nullable=True))
    op.add_column("plants", sa.Column("humidity", sa.Text(), nullable=True))
    op.add_column("plants", sa.Column("temperature", sa.Text(), nullable=True))
    op.add_column("plants", sa.Column("soil", sa.Text(), nullable=True))
    op.add_column("plants", sa.Column("running", sa.Text(), nullable=True))
    op.add_column("plants", sa.Column("potting_and_repotting", sa.Text(), nullable=True))
    op.add_column("plants", sa.Column("pests_and_diseases", sa.Text(), nullable=True))
    op.add_column("plants", sa.Column("toxicity", sa.Text(), nullable=True))
    op.add_column("plants", sa.Column("propagation", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("plants", "propagation")
    op.drop_column("plants", "toxicity")
    op.drop_column("plants", "pests_and_diseases")
    op.drop_column("plants", "potting_and_repotting")
    op.drop_column("plants", "running")
    op.drop_column("plants", "soil")
    op.drop_column("plants", "temperature")
    op.drop_column("plants", "humidity")
    op.drop_column("plants", "varieties")
    op.drop_column("plants", "propagating")
    op.drop_column("plants", "fertilizer")
    op.drop_column("plants", "sunlight")
    op.drop_column("plants", "water")
    op.drop_column("plants", "overview")
