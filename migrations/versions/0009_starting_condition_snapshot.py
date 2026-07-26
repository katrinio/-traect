"""Add immutable starting_condition snapshot to weekly reviews.

Revision ID: 0009_starting_condition_snapshot
Revises: 0008_minimum_acceptable_level

Adds starting_condition as immutable snapshot of domain state at week start.
Existing records remain with NULL starting_condition (legacy data).
Makes condition nullable to support new workflow.
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
    # Make condition nullable (was NOT NULL, now allows NULL for new uninitialized records)
    with op.batch_alter_table("week_domain_state", schema=None) as batch_op:
        batch_op.alter_column(
            "condition",
            existing_type=sa.String(),
            nullable=True,
            existing_nullable=False,
        )

    # Add starting_condition column (immutable snapshot)
    # NULL for legacy records, filled for new initialized records
    with op.batch_alter_table("week_domain_state", schema=None) as batch_op:
        batch_op.add_column(sa.Column("starting_condition", sa.String(), nullable=True))
        # Add check constraint to enforce valid state combinations
        batch_op.create_check_constraint(
            "ck_week_domain_state_valid_state",
            """
            (starting_condition IS NOT NULL AND condition IS NULL) OR
            (starting_condition IS NULL AND condition IS NOT NULL) OR
            (starting_condition IS NULL AND condition IS NULL)
            """,
        )


def downgrade() -> None:
    with op.batch_alter_table("week_domain_state", schema=None) as batch_op:
        batch_op.drop_constraint("ck_week_domain_state_valid_state", type_="check")
        batch_op.drop_column("starting_condition")

    # Restore condition as NOT NULL
    # This will fail if there are any NULL values in condition
    with op.batch_alter_table("week_domain_state", schema=None) as batch_op:
        batch_op.alter_column(
            "condition",
            existing_type=sa.String(),
            nullable=False,
            existing_nullable=True,
        )
