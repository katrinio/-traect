"""add minimum acceptable level

Revision ID: 0008_minimum_acceptable_level
Revises: 0007_historical_week_corrections
Create Date: 2026-07-17 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_minimum_acceptable_level"
down_revision = "0007_historical_week_corrections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("domain") as batch:
        batch.add_column(sa.Column("minimum_acceptable_level", sa.String(length=500), nullable=True))
    with op.batch_alter_table("week_domain_state") as batch:
        batch.add_column(sa.Column("minimum_acceptable_level_snapshot", sa.String(length=500), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("week_domain_state") as batch:
        batch.drop_column("minimum_acceptable_level_snapshot")
    with op.batch_alter_table("domain") as batch:
        batch.drop_column("minimum_acceptable_level")
