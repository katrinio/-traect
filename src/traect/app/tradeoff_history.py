from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any, cast

from sqlalchemy.orm import Session

from traect.app.errors import NotFoundError
from traect.app.history import load_history_rows
from traect.app.issue_codes import WeeklyIssueCode

VALID_ATTENTIONS = {"primary_focus", "maintained", "paused"}


class TradeoffHistoryService:
    """Aggregate explicit focus and What gave way co-occurrences without inference."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def aggregate(
        self,
        workspace_id: int,
        *,
        current_iso_week: tuple[int, int],
        reviewed_weeks: int | None,
        focus_domain_id: int | None = None,
        sacrifice_domain_id: int | None = None,
    ) -> dict[str, Any]:
        rows = load_history_rows(self.session, workspace_id)
        return self._aggregate_rows(
            rows.weeks,
            rows.states,
            rows.domains,
            current_iso_week=current_iso_week,
            reviewed_weeks=reviewed_weeks,
            focus_domain_id=focus_domain_id,
            sacrifice_domain_id=sacrifice_domain_id,
        )

    @staticmethod
    def _aggregate_rows(
        week_rows: Sequence[Any],
        state_rows: Sequence[Any],
        domain_rows: Sequence[Any],
        *,
        current_iso_week: tuple[int, int],
        reviewed_weeks: int | None,
        focus_domain_id: int | None = None,
        sacrifice_domain_id: int | None = None,
    ) -> dict[str, Any]:
        states_by_week: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
        for state in state_rows:
            states_by_week[int(state["week_id"])].append(state)
        domains_by_id = {int(domain["id"]): domain for domain in domain_rows}

        weeks_by_period: dict[tuple[int, int], list[Mapping[str, Any]]] = defaultdict(list)
        for week in week_rows:
            period = (int(week["iso_year"]), int(week["iso_week"]))
            if period <= current_iso_week:
                weeks_by_period[period].append(week)

        selected: list[Mapping[str, Any]] = []
        duplicate_issues: list[dict[str, Any]] = []
        for period in sorted(weeks_by_period, reverse=True):
            candidates = weeks_by_period[period]
            if len(candidates) != 1:
                duplicate_issues.append(
                    {
                        "code": WeeklyIssueCode.DUPLICATE_WEEK.value,
                        "iso_year": period[0],
                        "iso_week": period[1],
                    }
                )
                continue
            selected.append(candidates[0])
            if reviewed_weeks is not None and len(selected) == reviewed_weeks:
                break

        weeks = [
            _extract_week_tradeoff(
                week,
                states_by_week[int(week["id"])],
                domains_by_id,
                current_iso_week,
            )
            for week in selected
        ]
        valid_pairs = [week for week in weeks if week["status"] == "paired"]
        summary = _build_summary(weeks, duplicate_issues)
        sacrifices = _aggregate_sacrifices(valid_pairs, domains_by_id)
        pairs = _aggregate_pairs(valid_pairs, domains_by_id)
        focus_breakdowns = _build_focus_breakdowns(weeks, domains_by_id)
        sacrifice_breakdowns = _build_sacrifice_breakdowns(valid_pairs, domains_by_id)

        focus_ids = {int(item["focus"]["domain_id"]) for item in focus_breakdowns}
        sacrifice_ids = {int(item["sacrifice"]["domain_id"]) for item in sacrifice_breakdowns}
        if focus_domain_id is not None and focus_domain_id not in focus_ids:
            raise NotFoundError("Domain has no Primary focus history in this workspace")
        if sacrifice_domain_id is not None and sacrifice_domain_id not in sacrifice_ids:
            raise NotFoundError("Domain has no What gave way history in this workspace")

        issues = [
            {
                "code": str(week["excluded_reason"]),
                "week_id": week["week_id"],
                "iso_year": week["iso_year"],
                "iso_week": week["iso_week"],
            }
            for week in weeks
            if week["status"] == "excluded"
        ]
        issues.extend(duplicate_issues)
        issues.sort(key=lambda item: (-int(item["iso_year"]), -int(item["iso_week"]), str(item["code"])))
        return {
            "range": {"type": "reviewed_weeks", "value": reviewed_weeks},
            "filters": {"focus_domain_id": focus_domain_id, "sacrifice_domain_id": sacrifice_domain_id},
            "summary": summary,
            "sacrifices": sacrifices,
            "pairs": pairs,
            "focus_breakdowns": focus_breakdowns,
            "sacrifice_breakdowns": sacrifice_breakdowns,
            "selected_focus": next(
                (item for item in focus_breakdowns if item["focus"]["domain_id"] == focus_domain_id), None
            ),
            "selected_sacrifice": next(
                (item for item in sacrifice_breakdowns if item["sacrifice"]["domain_id"] == sacrifice_domain_id),
                None,
            ),
            "weeks": weeks,
            "integrity": {
                "excluded_pair_count": summary["excluded_pair_count"],
                "issues": issues,
                "excluded_reasons": dict(sorted(Counter(issue["code"] for issue in issues).items())),
            },
            "observations": _build_observations(sacrifices, pairs, summary),
        }


def _extract_week_tradeoff(
    week: Mapping[str, Any],
    states: Sequence[Mapping[str, Any]],
    domains_by_id: Mapping[int, Mapping[str, Any]],
    current_iso_week: tuple[int, int],
) -> dict[str, Any]:
    raw_sacrifice_id = week.get("sacrificed_domain_id")
    reference = {**_week_reference(week, current_iso_week), "has_sacrifice": raw_sacrifice_id is not None}
    domain_ids = [int(state["domain_id"]) for state in states]
    if len(domain_ids) != len(set(domain_ids)):
        return _excluded_week(reference, WeeklyIssueCode.DUPLICATE_DOMAIN_STATE.value)
    if any(str(state["attention"]) not in VALID_ATTENTIONS for state in states):
        return _excluded_week(reference, WeeklyIssueCode.INVALID_ATTENTION.value)
    primary_states = [state for state in states if str(state["attention"]) == "primary_focus"]
    if len(primary_states) > 1:
        return _excluded_week(reference, WeeklyIssueCode.MULTIPLE_PRIMARY_FOCUS.value)

    focus_state = primary_states[0] if primary_states else None
    focus = _domain_reference(focus_state, domains_by_id) if focus_state is not None else None
    if raw_sacrifice_id is None:
        return {
            **reference,
            "status": "focus_without_sacrifice" if focus is not None else "no_focus",
            "focus": focus,
            "sacrifice": None,
            "excluded_reason": None,
        }
    sacrifice_id = int(raw_sacrifice_id)
    if focus is None:
        return _excluded_week(reference, WeeklyIssueCode.SACRIFICE_WITHOUT_FOCUS.value)
    if int(focus["domain_id"]) == sacrifice_id:
        return _excluded_week(reference, WeeklyIssueCode.FOCUS_EQUALS_SACRIFICE.value, focus=focus)
    sacrifice_states = [state for state in states if int(state["domain_id"]) == sacrifice_id]
    if len(sacrifice_states) != 1:
        return _excluded_week(reference, WeeklyIssueCode.SACRIFICE_MISSING_STATE.value, focus=focus)
    sacrifice = _domain_reference(sacrifice_states[0], domains_by_id)
    return {
        **reference,
        "status": "paired",
        "focus": focus,
        "sacrifice": sacrifice,
        "excluded_reason": None,
    }


def _excluded_week(
    reference: Mapping[str, Any],
    reason: str,
    *,
    focus: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {**reference, "status": "excluded", "focus": focus, "sacrifice": None, "excluded_reason": reason}


def _domain_reference(
    state: Mapping[str, Any],
    domains_by_id: Mapping[int, Mapping[str, Any]],
) -> dict[str, Any]:
    domain_id = int(state["domain_id"])
    metadata = domains_by_id.get(domain_id)
    historical_name = str(state.get("domain_name", "")).strip()
    name = historical_name or (str(metadata["name"]) if metadata is not None else "Unavailable Domain")
    return {
        "domain_id": domain_id,
        "name": name,
        "archived": metadata is not None and metadata["archived_at"] is not None,
        "unavailable": metadata is None,
    }


def _week_reference(week: Mapping[str, Any], current_iso_week: tuple[int, int]) -> dict[str, Any]:
    iso_year = int(week["iso_year"])
    iso_week = int(week["iso_week"])
    return {
        "week_id": int(week["id"]),
        "iso_year": iso_year,
        "iso_week": iso_week,
        "lifecycle": "provisional" if (iso_year, iso_week) == current_iso_week else "final",
    }


def _build_summary(weeks: Sequence[Mapping[str, Any]], duplicate_issues: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    focus_week_count = sum(week["focus"] is not None for week in weeks)
    sacrifice_week_count = sum(bool(week["has_sacrifice"]) for week in weeks)
    return {
        "reviewed_week_count": len(weeks),
        "focus_week_count": focus_week_count,
        "sacrifice_week_count": sacrifice_week_count,
        "valid_pair_count": sum(week["status"] == "paired" for week in weeks),
        "focus_without_sacrifice_count": sum(week["status"] == "focus_without_sacrifice" for week in weeks),
        "no_focus_count": sum(week["status"] == "no_focus" for week in weeks),
        "excluded_pair_count": sum(week["status"] == "excluded" for week in weeks) + len(duplicate_issues),
    }


def _aggregate_sacrifices(
    valid_pairs: Sequence[Mapping[str, Any]],
    domains_by_id: Mapping[int, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    events: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for week in valid_pairs:
        events[int(week["sacrifice"]["domain_id"])].append(week)
    denominator = len(valid_pairs)
    results = []
    for weeks in events.values():
        domain = dict(weeks[0]["sacrifice"])
        results.append(
            {
                **domain,
                "count": len(weeks),
                "share_of_pairs": len(weeks) / denominator if denominator else 0.0,
                "most_recent": _source_week(weeks[0]),
            }
        )
    results.sort(key=lambda item: _domain_ranking_key(item, domains_by_id, "count", "most_recent"))
    return results


def _aggregate_pairs(
    valid_pairs: Sequence[Mapping[str, Any]],
    domains_by_id: Mapping[int, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    events: dict[tuple[int, int], list[Mapping[str, Any]]] = defaultdict(list)
    for week in valid_pairs:
        key = (int(week["focus"]["domain_id"]), int(week["sacrifice"]["domain_id"]))
        events[key].append(week)
    denominator = len(valid_pairs)
    results = []
    for weeks in events.values():
        results.append(
            {
                "focus": dict(weeks[0]["focus"]),
                "sacrifice": dict(weeks[0]["sacrifice"]),
                "count": len(weeks),
                "share_of_pairs": len(weeks) / denominator if denominator else 0.0,
                "most_recent": _source_week(weeks[0]),
                "weeks": [_source_week(week) for week in weeks],
            }
        )
    results.sort(key=lambda item: _pair_ranking_key(item, domains_by_id))
    return results


def _build_focus_breakdowns(
    weeks: Sequence[Mapping[str, Any]],
    domains_by_id: Mapping[int, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    events: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for week in weeks:
        if week["focus"] is not None and week["status"] in {"paired", "focus_without_sacrifice"}:
            events[int(week["focus"]["domain_id"])].append(week)
    results = []
    for focus_weeks in events.values():
        paired = [week for week in focus_weeks if week["status"] == "paired"]
        sacrifice_counts: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
        for week in paired:
            sacrifice_counts[int(week["sacrifice"]["domain_id"])].append(week)
        sacrifices = [
            {
                "sacrifice": dict(domain_weeks[0]["sacrifice"]),
                "count": len(domain_weeks),
                "share_of_focus_weeks": len(domain_weeks) / len(focus_weeks),
                "most_recent": _source_week(domain_weeks[0]),
            }
            for domain_weeks in sacrifice_counts.values()
        ]
        sacrifices.sort(key=lambda item: _nested_ranking_key(item, domains_by_id, "sacrifice"))
        results.append(
            {
                "focus": dict(focus_weeks[0]["focus"]),
                "focus_week_count": len(focus_weeks),
                "paired_week_count": len(paired),
                "no_tradeoff_count": len(focus_weeks) - len(paired),
                "sacrifices": sacrifices,
            }
        )
    results.sort(key=lambda item: _domain_identity_key(cast(Mapping[str, Any], item["focus"]), domains_by_id))
    return results


def _build_sacrifice_breakdowns(
    valid_pairs: Sequence[Mapping[str, Any]],
    domains_by_id: Mapping[int, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    events: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for week in valid_pairs:
        events[int(week["sacrifice"]["domain_id"])].append(week)
    results = []
    for sacrifice_weeks in events.values():
        focus_counts: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
        for week in sacrifice_weeks:
            focus_counts[int(week["focus"]["domain_id"])].append(week)
        focuses = [
            {
                "focus": dict(domain_weeks[0]["focus"]),
                "count": len(domain_weeks),
                "share_of_sacrifice_weeks": len(domain_weeks) / len(sacrifice_weeks),
                "most_recent": _source_week(domain_weeks[0]),
            }
            for domain_weeks in focus_counts.values()
        ]
        focuses.sort(key=lambda item: _nested_ranking_key(item, domains_by_id, "focus"))
        results.append(
            {
                "sacrifice": dict(sacrifice_weeks[0]["sacrifice"]),
                "sacrifice_week_count": len(sacrifice_weeks),
                "focuses": focuses,
            }
        )
    results.sort(key=lambda item: _domain_identity_key(cast(Mapping[str, Any], item["sacrifice"]), domains_by_id))
    return results


def _source_week(week: Mapping[str, Any]) -> dict[str, Any]:
    return {key: week[key] for key in ("week_id", "iso_year", "iso_week", "lifecycle")}


def _domain_identity_key(domain: Mapping[str, Any], domains_by_id: Mapping[int, Mapping[str, Any]]) -> tuple[Any, ...]:
    metadata = domains_by_id.get(int(domain["domain_id"]))
    return (
        int(metadata["sort_order"]) if metadata is not None else 2**31,
        str(domain["name"]).casefold(),
        int(domain["domain_id"]),
    )


def _domain_ranking_key(
    item: Mapping[str, Any],
    domains_by_id: Mapping[int, Mapping[str, Any]],
    count_key: str,
    recent_key: str,
) -> tuple[Any, ...]:
    recent = item[recent_key]
    return (
        -int(item[count_key]),
        -int(recent["iso_year"]),
        -int(recent["iso_week"]),
        *_domain_identity_key(item, domains_by_id),
    )


def _pair_ranking_key(item: Mapping[str, Any], domains_by_id: Mapping[int, Mapping[str, Any]]) -> tuple[Any, ...]:
    recent = item["most_recent"]
    return (
        -int(item["count"]),
        -int(recent["iso_year"]),
        -int(recent["iso_week"]),
        *_domain_identity_key(cast(Mapping[str, Any], item["focus"]), domains_by_id),
        *_domain_identity_key(cast(Mapping[str, Any], item["sacrifice"]), domains_by_id),
    )


def _nested_ranking_key(
    item: Mapping[str, Any], domains_by_id: Mapping[int, Mapping[str, Any]], domain_key: str
) -> tuple[Any, ...]:
    recent = item["most_recent"]
    return (
        -int(item["count"]),
        -int(recent["iso_year"]),
        -int(recent["iso_week"]),
        *_domain_identity_key(cast(Mapping[str, Any], item[domain_key]), domains_by_id),
    )


def _build_observations(
    sacrifices: Sequence[Mapping[str, Any]],
    pairs: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
) -> list[dict[str, str]]:
    observations: list[dict[str, str]] = []
    if sacrifices:
        top = sacrifices[0]
        observations.append(
            {
                "code": "most_recorded_what_gave_way",
                "text": (
                    f"{top['name']} was recorded as What gave way in {top['count']} "
                    f"of {summary['valid_pair_count']} trade-off weeks."
                ),
            }
        )
    if pairs:
        top_pair = pairs[0]
        observations.append(
            {
                "code": "most_recorded_pair",
                "text": (
                    f"{top_pair['focus']['name']} and {top_pair['sacrifice']['name']} were recorded together "
                    f"in {top_pair['count']} reviewed weeks."
                ),
            }
        )
    return observations
