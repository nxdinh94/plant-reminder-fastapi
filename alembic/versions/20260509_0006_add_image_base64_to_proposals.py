"""no-op migration for image_base64 support in proposal_payload

Revision ID: 20260509_0006
Revises: 20260503_0005
Create Date: 2026-05-09

Note: image_base64 is stored in the proposal_payload JSON column,
no schema change needed.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260509_0006"
down_revision: str | None = "20260503_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
