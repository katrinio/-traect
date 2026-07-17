"""define canonical focus source

Revision ID: 0006_canonical_focus_source
Revises: 0005_unify_product_terminology
Create Date: 2026-07-17 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_canonical_focus_source"
down_revision = "0005_unify_product_terminology"
branch_labels = None
depends_on = None


def _validate_focus_data() -> None:
    rows = op.get_bind().execute(
        sa.text(
            "SELECT w.id, w.focus_domain_id, "
            "SUM(CASE WHEN s.attention = 'primary_focus' THEN 1 ELSE 0 END) AS primary_count, "
            "SUM(CASE WHEN s.domain_id = w.focus_domain_id THEN 1 ELSE 0 END) AS focus_state_count "
            "FROM week AS w LEFT JOIN week_domain_state AS s ON s.week_id = w.id "
            "GROUP BY w.id, w.focus_domain_id ORDER BY w.id"
        )
    )
    multiple: list[int] = []
    missing: list[int] = []
    for week_id, focus_domain_id, primary_count, focus_state_count in rows:
        if primary_count > 1:
            multiple.append(week_id)
        elif primary_count == 0 and focus_domain_id is not None and focus_state_count == 0:
            missing.append(week_id)
    issues: list[str] = []
    if multiple:
        issues.append(f"multiple Primary focus states in weeks {multiple}")
    if missing:
        issues.append(f"focus_domain_id has no WeekDomainState in weeks {missing}")
    if issues:
        raise RuntimeError("cannot define canonical focus source: " + "; ".join(issues))


def upgrade() -> None:
    _validate_focus_data()
    op.get_bind().execute(
        sa.text(
            "UPDATE week_domain_state AS candidate SET attention = 'primary_focus' "
            "WHERE EXISTS ("
            "SELECT 1 FROM week AS w WHERE w.id = candidate.week_id "
            "AND w.focus_domain_id = candidate.domain_id"
            ") AND NOT EXISTS ("
            "SELECT 1 FROM week_domain_state AS existing "
            "WHERE existing.week_id = candidate.week_id AND existing.attention = 'primary_focus'"
            ")"
        )
    )
    op.create_index(
        "uq_week_domain_state_primary_focus",
        "week_domain_state",
        ["week_id"],
        unique=True,
        sqlite_where=sa.text("attention = 'primary_focus'"),
        postgresql_where=sa.text("attention = 'primary_focus'"),
    )
    with op.batch_alter_table("week") as batch:
        batch.drop_column("focus_domain_name")
        batch.drop_column("focus_domain_id")


def downgrade() -> None:
    duplicate_weeks = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT week_id FROM week_domain_state WHERE attention = 'primary_focus' "
                "GROUP BY week_id HAVING COUNT(*) > 1 ORDER BY week_id"
            )
        )
        .scalars()
        .all()
    )
    if duplicate_weeks:
        raise RuntimeError(f"cannot restore focus_domain_id: multiple Primary focus states in weeks {duplicate_weeks}")

    op.drop_index("uq_week_domain_state_primary_focus", table_name="week_domain_state")
    with op.batch_alter_table("week") as batch:
        batch.add_column(sa.Column("focus_domain_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("focus_domain_name", sa.String(length=120), nullable=True))
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE week SET focus_domain_id = ("
            "SELECT domain_id FROM week_domain_state AS state "
            "WHERE state.week_id = week.id AND state.attention = 'primary_focus'"
            "), focus_domain_name = ("
            "SELECT domain_name FROM week_domain_state AS state "
            "WHERE state.week_id = week.id AND state.attention = 'primary_focus'"
            ")"
        )
    )
    with op.batch_alter_table("week") as batch:
        batch.create_foreign_key(
            "fk_week_focus_domain_id_domain",
            "domain",
            ["focus_domain_id"],
            ["id"],
            ondelete="SET NULL",
        )
