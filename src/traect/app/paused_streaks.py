from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any


def calculate_paused_streaks(
    weeks: Sequence[Mapping[str, Any]],
    *,
    current_iso_week: tuple[int, int],
) -> dict[str, Any]:
    """Describe explicit Paused sequences in persisted, chronological reviews."""
    streaks: list[dict[str, Any]] = []
    current: list[Mapping[str, Any]] = []

    def close_streak() -> None:
        nonlocal current
        if current:
            streaks.append(_streak(current, current_iso_week))
            current = []

    for week in weeks:
        follows_previous = bool(current) and _weeks_are_consecutive(current[-1], week)
        explicitly_paused = week["attention_presence"] == "recorded" and week["attention"] == "paused"
        if not explicitly_paused:
            close_streak()
            continue
        if current and not follows_previous:
            close_streak()
        current.append(week)
    close_streak()

    active = next((streak for streak in reversed(streaks) if streak["active"]), None)
    longest = (
        max(
            streaks,
            key=lambda streak: (streak["length"], -streak["started"]["iso_year"], -streak["started"]["iso_week"]),
        )
        if streaks
        else None
    )
    excluded_reasons = Counter(
        str(week["attention_excluded_reason"]) for week in weeks if week["attention_presence"] == "excluded"
    )
    return {
        "current_streak": (
            {"active": True, "length": active["length"], "started": active["started"]}
            if active is not None
            else {"active": False, "length": 0, "started": None}
        ),
        "longest_streak": longest,
        "streaks": streaks,
        "excluded_state_count": sum(excluded_reasons.values()),
        "excluded_reasons": dict(sorted(excluded_reasons.items())),
    }


def _streak(weeks: Sequence[Mapping[str, Any]], current_iso_week: tuple[int, int]) -> dict[str, Any]:
    references = [_week_reference(week) for week in weeks]
    last = references[-1]
    return {
        "length": len(references),
        "started": references[0],
        "ended": last,
        "active": (last["iso_year"], last["iso_week"]) == current_iso_week,
        "weeks": references,
    }


def _weeks_are_consecutive(first: Mapping[str, Any], second: Mapping[str, Any]) -> bool:
    first_date = date.fromisocalendar(int(first["iso_year"]), int(first["iso_week"]), 1)
    second_date = date.fromisocalendar(int(second["iso_year"]), int(second["iso_week"]), 1)
    return (second_date - first_date).days == 7


def _week_reference(week: Mapping[str, Any]) -> dict[str, int]:
    return {"week_id": int(week["week_id"]), "iso_year": int(week["iso_year"]), "iso_week": int(week["iso_week"])}
