from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from traect.app.errors import ValidationError

SUPPORTED_REVIEWED_WEEK_RANGES = {12, 26, 52}


@dataclass(frozen=True)
class HistoryRows:
    weeks: list[Any]
    states: list[Any]
    domains: list[Any]


def parse_reviewed_week_range(value: str | None) -> int | None:
    if value is None:
        return 12
    if value == "all":
        return None
    try:
        reviewed_weeks = int(value)
    except ValueError as exc:
        raise ValidationError("reviewed_weeks must be 12, 26, 52, or all") from exc
    if reviewed_weeks not in SUPPORTED_REVIEWED_WEEK_RANGES:
        raise ValidationError("reviewed_weeks must be 12, 26, 52, or all")
    return reviewed_weeks


def load_history_rows(session: Session, workspace_id: int) -> HistoryRows:
    weeks = list(
        session.execute(
            text(
                "SELECT id, iso_year, iso_week, sacrificed_domain_id, sacrificed_domain_name FROM week "
                "WHERE workspace_id = :workspace_id "
                "ORDER BY iso_year DESC, iso_week DESC, id DESC"
            ),
            {"workspace_id": workspace_id},
        ).mappings()
    )
    states = list(
        session.execute(
            text(
                "SELECT state.id, state.week_id, state.domain_id, state.domain_name, "
                "state.attention, state.condition "
                "FROM week_domain_state AS state "
                "JOIN week AS review ON review.id = state.week_id "
                "WHERE review.workspace_id = :workspace_id "
                "ORDER BY state.week_id, state.id"
            ),
            {"workspace_id": workspace_id},
        ).mappings()
    )
    domains = list(
        session.execute(
            text(
                "SELECT id, name, sort_order, archived_at FROM domain "
                "WHERE workspace_id = :workspace_id ORDER BY sort_order, id"
            ),
            {"workspace_id": workspace_id},
        ).mappings()
    )
    return HistoryRows(weeks=weeks, states=states, domains=domains)
