"""add historical week correction metadata

Revision ID: 0007_historical_week_corrections
Revises: 0006_canonical_focus_source
Create Date: 2026-07-17 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_historical_week_corrections"
down_revision = "0006_canonical_focus_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("week") as batch:
        batch.add_column(sa.Column("corrected_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("correction_note", sa.String(length=300), nullable=True))
        batch.add_column(sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))


def downgrade() -> None:
    with op.batch_alter_table("week") as batch:
        batch.drop_column("revision")
        batch.drop_column("correction_note")
        batch.drop_column("corrected_at")
