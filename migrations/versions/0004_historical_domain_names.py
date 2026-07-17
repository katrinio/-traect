"""preserve historical domain names

Revision ID: 0004_historical_domain_names
Revises: 0003_active_domain_names
Create Date: 2026-07-17 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_historical_domain_names"
down_revision = "0003_active_domain_names"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("week") as batch:
        batch.add_column(sa.Column("focus_domain_name", sa.String(length=120), nullable=True))
        batch.add_column(sa.Column("sacrificed_domain_name", sa.String(length=120), nullable=True))
    with op.batch_alter_table("week_domain_state") as batch:
        batch.add_column(sa.Column("domain_name", sa.String(length=120), nullable=True))

    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE week_domain_state SET domain_name = "
            "(SELECT name FROM domain WHERE domain.id = week_domain_state.domain_id)"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE week SET focus_domain_name = "
            "(SELECT name FROM domain WHERE domain.id = week.focus_domain_id) "
            "WHERE focus_domain_id IS NOT NULL"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE week SET sacrificed_domain_name = "
            "(SELECT name FROM domain WHERE domain.id = week.sacrificed_domain_id) "
            "WHERE sacrificed_domain_id IS NOT NULL"
        )
    )

    with op.batch_alter_table("week_domain_state") as batch:
        batch.alter_column("domain_name", existing_type=sa.String(length=120), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("week_domain_state") as batch:
        batch.drop_column("domain_name")
    with op.batch_alter_table("week") as batch:
        batch.drop_column("sacrificed_domain_name")
        batch.drop_column("focus_domain_name")
