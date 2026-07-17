from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.orm import Session

from traect.app.history import (
    CANONICAL_ATTENTION_VALUES,
    load_history_rows,
    parse_reviewed_week_range,
    resolve_domain_identity,
    review_lifecycle,
)
from traect.app.issue_codes import WeeklyIssueCode

parse_focus_history_range = parse_reviewed_week_range


class FocusHistoryService:
    """Build descriptive focus history directly from persisted weekly snapshots."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def aggregate(
        self,
        workspace_id: int,
        *,
        current_iso_week: tuple[int, int],
        reviewed_weeks: int | None,
    ) -> dict[str, Any]:
        rows = load_history_rows(self.session, workspace_id)
        return self._aggregate_rows(
            rows.weeks,
            rows.states,
            rows.domains,
            current_iso_week=current_iso_week,
            reviewed_weeks=reviewed_weeks,
        )

    @staticmethod
    def _aggregate_rows(
        week_rows: Sequence[Any],
        state_rows: Sequence[Any],
        domain_rows: Sequence[Any],
        *,
        current_iso_week: tuple[int, int],
        reviewed_weeks: int | None,
    ) -> dict[str, Any]:
        states_by_week: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
        for state in state_rows:
            states_by_week[int(state["week_id"])].append(state)

        weeks_by_period: dict[tuple[int, int], list[Mapping[str, Any]]] = defaultdict(list)
        for week in week_rows:
            period = (int(week["iso_year"]), int(week["iso_week"]))
            if period <= current_iso_week:
                weeks_by_period[period].append(week)

        selected: list[tuple[Mapping[str, Any], Mapping[str, Any] | None]] = []
        excluded_reasons: Counter[str] = Counter()
        for period in sorted(weeks_by_period, reverse=True):
            duplicate_weeks = weeks_by_period[period]
            if len(duplicate_weeks) != 1:
                excluded_reasons[WeeklyIssueCode.DUPLICATE_WEEK.value] += 1
                continue

            week = duplicate_weeks[0]
            states = states_by_week[int(week["id"])]
            domain_ids = [int(state["domain_id"]) for state in states]
            if len(domain_ids) != len(set(domain_ids)):
                excluded_reasons[WeeklyIssueCode.DUPLICATE_DOMAIN_STATE.value] += 1
                continue
            if any(str(state["attention"]) not in CANONICAL_ATTENTION_VALUES for state in states):
                excluded_reasons[WeeklyIssueCode.INVALID_ATTENTION.value] += 1
                continue
            primary_states = [state for state in states if str(state["attention"]) == "primary_focus"]
            if len(primary_states) > 1:
                excluded_reasons[WeeklyIssueCode.MULTIPLE_PRIMARY_FOCUS.value] += 1
                continue

            selected.append((week, primary_states[0] if primary_states else None))
            if reviewed_weeks is not None and len(selected) == reviewed_weeks:
                break

        domains_by_id = {int(domain["id"]): domain for domain in domain_rows}
        focus_events: dict[int, list[dict[str, Any]]] = defaultdict(list)
        sequence: list[dict[str, Any]] = []
        for week, focus_state in selected:
            iso_year = int(week["iso_year"])
            iso_week = int(week["iso_week"])
            week_reference = {
                "week_id": int(week["id"]),
                "iso_year": iso_year,
                "iso_week": iso_week,
                "lifecycle": review_lifecycle(iso_year, iso_week, current_iso_week),
            }
            focus = None
            if focus_state is not None:
                domain_id = int(focus_state["domain_id"])
                identity = resolve_domain_identity(domains_by_id.get(domain_id), focus_state["domain_name"])
                focus = {
                    "domain_id": domain_id,
                    "name": identity["name"],
                    "unavailable": identity["unavailable"],
                    "name_source": identity["name_source"],
                }
                focus_events[domain_id].append(
                    {**week_reference, "name": identity["name"], "name_source": identity["name_source"]}
                )
            sequence.append({**week_reference, "focus": focus})

        reviewed_week_count = len(selected)
        focused_week_count = sum(focus is not None for _, focus in selected)
        domain_results = []
        for domain_id, events in focus_events.items():
            domain = domains_by_id.get(domain_id)
            latest = events[0]
            domain_results.append(
                {
                    "domain_id": domain_id,
                    "name": latest["name"],
                    "name_source": latest["name_source"],
                    "archived": domain is not None and domain["archived_at"] is not None,
                    "unavailable": domain is None,
                    "focus_count": len(events),
                    "focus_share": len(events) / reviewed_week_count if reviewed_week_count else 0.0,
                    "most_recent_focus": {
                        "week_id": latest["week_id"],
                        "iso_year": latest["iso_year"],
                        "iso_week": latest["iso_week"],
                        "lifecycle": latest["lifecycle"],
                    },
                    "weeks": events,
                }
            )

        def ranking_key(item: Mapping[str, Any]) -> tuple[Any, ...]:
            recent = item["most_recent_focus"]
            metadata = domains_by_id.get(int(item["domain_id"]))
            sort_order = int(metadata["sort_order"]) if metadata is not None else 2**31
            return (
                -int(item["focus_count"]),
                -int(recent["iso_year"]),
                -int(recent["iso_week"]),
                sort_order,
                str(item["name"]).casefold(),
                int(item["domain_id"]),
            )

        domain_results.sort(key=ranking_key)
        focused_domain_ids = set(focus_events)
        zero_focus_domains = [
            {"domain_id": int(domain["id"]), "name": str(domain["name"])}
            for domain in domain_rows
            if domain["archived_at"] is None and int(domain["id"]) not in focused_domain_ids
        ]

        return {
            "range": {"type": "reviewed_weeks", "value": reviewed_weeks},
            "summary": {
                "reviewed_week_count": reviewed_week_count,
                "focused_week_count": focused_week_count,
                "no_focus_week_count": reviewed_week_count - focused_week_count,
                "excluded_week_count": sum(excluded_reasons.values()),
            },
            "excluded_reasons": dict(sorted(excluded_reasons.items())),
            "domains": domain_results,
            "zero_focus_domains": zero_focus_domains,
            "weeks": sequence,
        }
