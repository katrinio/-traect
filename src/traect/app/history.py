"""Shared read path for history features.

This module deliberately uses raw SQL instead of the ORM. The ORM enum
columns on ``WeekDomainState`` raise on unknown values, but history features
(like the weekly audit) must be able to read legacy rows with unknown
``attention`` or ``condition`` values in order to report them as excluded
instead of crashing. Converting these queries to ORM calls would reintroduce
load-time failures on imperfect historical data — the raw rows here are an
intentional architectural boundary, not technical debt.
"""

from __future__ import annotations

from collections.abc import Mapping
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


def resolve_domain_identity(
    metadata: Mapping[str, Any] | None,
    snapshot_name: Any,
) -> dict[str, Any]:
    """Resolve the display identity of a Domain in historical aggregations.

    Canonical fallback order shared by every history feature:

    1. a non-empty historical snapshot name is shown as saved;
    2. an empty snapshot name with a valid Domain reference falls back to the
       current Domain name, marked with ``name_source == "current_domain"``;
    3. without both a snapshot name and a Domain reference the neutral
       ``"Unavailable Domain"`` placeholder is used.

    ``unavailable`` reflects only the Domain reference: a readable snapshot
    name never hides a missing reference, and an empty snapshot name alone
    never makes a Domain unavailable.
    """
    historical_name = str(snapshot_name).strip() if snapshot_name is not None else ""
    archived = metadata is not None and metadata["archived_at"] is not None
    if historical_name:
        return {
            "name": historical_name,
            "archived": archived,
            "unavailable": metadata is None,
            "name_source": "snapshot",
        }
    if metadata is not None:
        return {
            "name": str(metadata["name"]),
            "archived": archived,
            "unavailable": False,
            "name_source": "current_domain",
        }
    return {"name": "Unavailable Domain", "archived": False, "unavailable": True, "name_source": "fallback"}
