"""Add immutable starting_condition snapshot to weekly reviews.

Revision ID: 0009_starting_condition_snapshot
Revises: 0008_minimum_acceptable_level

Fresh databases created from the squashed baseline already have this
column through metadata.create_all(). Existing databases that reached
0008 before the application model added starting_condition need the
column added here.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# Alembic revision identifiers
revision = "0009_starting_condition_snapshot"
down_revision = "0008_minimum_acceptable_level"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("week_domain_state")}
    if "starting_condition" not in columns:
        op.add_column("week_domain_state", sa.Column("starting_condition", sa.String(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("week_domain_state")}
    if "starting_condition" in columns:
        op.drop_column("week_domain_state", "starting_condition")
