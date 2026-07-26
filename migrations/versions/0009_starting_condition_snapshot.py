"""Add immutable starting_condition snapshot to weekly reviews.

Revision ID: 0009_starting_condition_snapshot
Revises: 0008_minimum_acceptable_level

This migration is a no-op because the squashed migration (0008) already
created the starting_condition column and made condition nullable as part
of the metadata.create_all() during initial schema creation.

For databases that were migrated through the old revision chain, this
marker exists to maintain migration history consistency.
"""

from __future__ import annotations

# Alembic revision identifiers
revision = "0009_starting_condition_snapshot"
down_revision = "0008_minimum_acceptable_level"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No-op: starting_condition and condition nullable are already in the schema
    # via the squashed migration (0008)
    pass


def downgrade() -> None:
    # No-op
    pass
