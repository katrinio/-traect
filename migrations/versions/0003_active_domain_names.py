"""allow archived domain names to be reused

Revision ID: 0003_active_domain_names
Revises: 0002_weekly_workflow
Create Date: 2026-07-17 00:00:00.000000
"""

from __future__ import annotations

from alembic import op

revision = "0003_active_domain_names"
down_revision = "0002_weekly_workflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("domain") as batch:
        batch.drop_constraint("uq_domain_workspace_name", type_="unique")


def downgrade() -> None:
    with op.batch_alter_table("domain") as batch:
        batch.create_unique_constraint("uq_domain_workspace_name", ["workspace_id", "name"])
