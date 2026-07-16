"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-07-16 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "domain",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_domain_workspace_name"),
    )
    op.create_index(op.f("ix_domain_workspace_id"), "domain", ["workspace_id"], unique=False)
    op.create_table(
        "week",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("iso_year", sa.Integer(), nullable=False),
        sa.Column("iso_week", sa.Integer(), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("focus_domain_name", sa.String(length=120), nullable=True),
        sa.Column("sacrificed_domain_name", sa.String(length=120), nullable=True),
        sa.Column("sacrifice_reason", sa.String(length=240), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_id", "iso_year", "iso_week", name="uq_week_workspace_iso_week"),
    )
    op.create_index(op.f("ix_week_workspace_id"), "week", ["workspace_id"], unique=False)
    op.create_table(
        "week_domain_state",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("week_id", sa.Integer(), nullable=False),
        sa.Column("domain_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("good", "warning", "critical", name="week_domain_status", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "mode",
            sa.Enum("focus", "maintain", "ignore", name="week_domain_mode", native_enum=False),
            nullable=False,
        ),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["domain_id"], ["domain.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["week_id"], ["week.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("week_id", "domain_id", name="uq_week_domain_state_week_domain"),
    )
    op.create_index(op.f("ix_week_domain_state_domain_id"), "week_domain_state", ["domain_id"], unique=False)
    op.create_index(op.f("ix_week_domain_state_week_id"), "week_domain_state", ["week_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_week_domain_state_week_id"), table_name="week_domain_state")
    op.drop_index(op.f("ix_week_domain_state_domain_id"), table_name="week_domain_state")
    op.drop_table("week_domain_state")
    op.drop_index(op.f("ix_week_workspace_id"), table_name="week")
    op.drop_table("week")
    op.drop_index(op.f("ix_domain_workspace_id"), table_name="domain")
    op.drop_table("domain")
    op.drop_table("workspace")
