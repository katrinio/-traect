"""unify product terminology

Revision ID: 0005_unify_product_terminology
Revises: 0004_historical_domain_names
Create Date: 2026-07-17 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_unify_product_terminology"
down_revision = "0004_historical_domain_names"
branch_labels = None
depends_on = None


def _validate_values(column: str, known: set[str]) -> None:
    connection = op.get_bind()
    values = connection.execute(
        sa.text(f'SELECT DISTINCT "{column}" FROM week_domain_state WHERE "{column}" IS NOT NULL')
    ).scalars()
    unknown = sorted(str(value) for value in values if str(value).lower() not in known)
    if unknown:
        rendered = ", ".join(repr(value) for value in unknown)
        raise RuntimeError(f"cannot migrate week_domain_state.{column}: unknown values: {rendered}")


def upgrade() -> None:
    attention_mapping = {
        "focus": "primary_focus",
        "primary_focus": "primary_focus",
        "maintain": "maintained",
        "maintained": "maintained",
        "ignore": "paused",
        "paused": "paused",
    }
    condition_mapping = {
        "good": "stable",
        "stable": "stable",
        "warning": "at_risk",
        "at_risk": "at_risk",
        "critical": "critical",
    }
    _validate_values("mode", set(attention_mapping))
    _validate_values("status", set(condition_mapping))

    with op.batch_alter_table("week_domain_state") as batch:
        batch.add_column(sa.Column("attention", sa.String(length=13), nullable=True))
        batch.add_column(sa.Column("condition", sa.String(length=8), nullable=True))

    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE week_domain_state SET attention = CASE lower(mode) "
            "WHEN 'focus' THEN 'primary_focus' WHEN 'primary_focus' THEN 'primary_focus' "
            "WHEN 'maintain' THEN 'maintained' WHEN 'maintained' THEN 'maintained' "
            "WHEN 'ignore' THEN 'paused' WHEN 'paused' THEN 'paused' END"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE week_domain_state SET condition = CASE lower(status) "
            "WHEN 'good' THEN 'stable' WHEN 'stable' THEN 'stable' "
            "WHEN 'warning' THEN 'at_risk' WHEN 'at_risk' THEN 'at_risk' "
            "WHEN 'critical' THEN 'critical' END"
        )
    )
    with op.batch_alter_table("week_domain_state") as batch:
        batch.drop_column("mode")
        batch.drop_column("status")
        batch.alter_column("attention", existing_type=sa.String(length=13), nullable=False)
        batch.alter_column("condition", existing_type=sa.String(length=8), nullable=False)


def downgrade() -> None:
    attention_mapping = {
        "primary_focus": "primary_focus",
        "maintained": "maintained",
        "paused": "paused",
        "focus": "focus",
        "maintain": "maintain",
        "ignore": "ignore",
    }
    condition_mapping = {
        "stable": "stable",
        "at_risk": "at_risk",
        "critical": "critical",
        "good": "good",
        "warning": "warning",
    }
    _validate_values("attention", set(attention_mapping))
    _validate_values("condition", set(condition_mapping))

    with op.batch_alter_table("week_domain_state") as batch:
        batch.add_column(sa.Column("mode", sa.String(length=8), nullable=True))
        batch.add_column(sa.Column("status", sa.String(length=8), nullable=True))

    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE week_domain_state SET mode = CASE lower(attention) "
            "WHEN 'primary_focus' THEN 'focus' WHEN 'focus' THEN 'focus' "
            "WHEN 'maintained' THEN 'maintain' WHEN 'maintain' THEN 'maintain' "
            "WHEN 'paused' THEN 'ignore' WHEN 'ignore' THEN 'ignore' END"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE week_domain_state SET status = CASE lower(condition) "
            "WHEN 'stable' THEN 'good' WHEN 'good' THEN 'good' "
            "WHEN 'at_risk' THEN 'warning' WHEN 'warning' THEN 'warning' "
            "WHEN 'critical' THEN 'critical' END"
        )
    )
    with op.batch_alter_table("week_domain_state") as batch:
        batch.drop_column("attention")
        batch.drop_column("condition")
        batch.alter_column("mode", existing_type=sa.String(length=8), nullable=False)
        batch.alter_column("status", existing_type=sa.String(length=8), nullable=False)
