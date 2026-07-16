"""weekly workflow

Revision ID: 0002_weekly_workflow
Revises: 0001_initial_schema
Create Date: 2026-07-16 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_weekly_workflow"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("domain") as batch:
        batch.add_column(sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_index(
            "uq_domain_workspace_active_name",
            ["workspace_id", "name"],
            unique=True,
            sqlite_where=sa.text("archived_at IS NULL"),
        )
    with op.batch_alter_table("week") as batch:
        batch.add_column(sa.Column("focus_domain_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("sacrificed_domain_id", sa.Integer(), nullable=True))
        batch.drop_column("focus_domain_name")
        batch.drop_column("sacrificed_domain_name")
        batch.create_foreign_key(
            "fk_week_focus_domain_id_domain", "domain", ["focus_domain_id"], ["id"], ondelete="SET NULL"
        )
        batch.create_foreign_key(
            "fk_week_sacrificed_domain_id_domain", "domain", ["sacrificed_domain_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    with op.batch_alter_table("week") as batch:
        batch.add_column(sa.Column("focus_domain_name", sa.String(length=120), nullable=True))
        batch.add_column(sa.Column("sacrificed_domain_name", sa.String(length=120), nullable=True))
        batch.drop_constraint("fk_week_sacrificed_domain_id_domain", type_="foreignkey")
        batch.drop_constraint("fk_week_focus_domain_id_domain", type_="foreignkey")
        batch.drop_column("focus_domain_id")
        batch.drop_column("sacrificed_domain_id")
    with op.batch_alter_table("domain") as batch:
        batch.drop_index("uq_domain_workspace_active_name")
        batch.drop_column("archived_at")
        batch.drop_column("sort_order")
