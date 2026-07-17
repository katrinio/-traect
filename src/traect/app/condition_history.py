from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.orm import Session

from traect.app.errors import NotFoundError
from traect.app.history import (
    CANONICAL_ATTENTION_VALUES,
    load_history_rows,
    resolve_domain_identity,
    review_lifecycle,
    week_reference,
    weeks_are_consecutive,
)
from traect.app.issue_codes import WeeklyIssueCode
from traect.app.paused_streaks import calculate_paused_streaks

CONDITION_LABELS = {"stable": "Stable", "at_risk": "At risk", "critical": "Critical"}


class ConditionHistoryService:
    """Describe persisted Domain Conditions without inferring causes or scores."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def aggregate(
        self,
        workspace_id: int,
        *,
        current_iso_week: tuple[int, int],
        reviewed_weeks: int | None,
        domain_id: int | None = None,
    ) -> dict[str, Any]:
        rows = load_history_rows(self.session, workspace_id)
        return self._aggregate_rows(
            rows.weeks,
            rows.states,
            rows.domains,
            current_iso_week=current_iso_week,
            reviewed_weeks=reviewed_weeks,
            domain_id=domain_id,
        )

    @staticmethod
    def _aggregate_rows(
        week_rows: Sequence[Any],
        state_rows: Sequence[Any],
        domain_rows: Sequence[Any],
        *,
        current_iso_week: tuple[int, int],
        reviewed_weeks: int | None,
        domain_id: int | None,
    ) -> dict[str, Any]:
        states_by_week_domain: dict[tuple[int, int], list[Any]] = defaultdict(list)
        for state in state_rows:
            states_by_week_domain[(int(state["week_id"]), int(state["domain_id"]))].append(state)

        weeks_by_period: dict[tuple[int, int], list[Any]] = defaultdict(list)
        for week in week_rows:
            period = (int(week["iso_year"]), int(week["iso_week"]))
            if period <= current_iso_week:
                weeks_by_period[period].append(week)

        selected_weeks: list[Any] = []
        excluded_reasons: Counter[str] = Counter()
        for period in sorted(weeks_by_period, reverse=True):
            candidates = weeks_by_period[period]
            if len(candidates) != 1:
                excluded_reasons[WeeklyIssueCode.DUPLICATE_WEEK.value] += 1
                continue
            selected_weeks.append(candidates[0])
            if reviewed_weeks is not None and len(selected_weeks) == reviewed_weeks:
                break

        domains_by_id = {int(domain["id"]): domain for domain in domain_rows}
        valid_states_by_domain: dict[int, list[tuple[Any, Any]]] = defaultdict(list)
        relevant_domain_ids = set(domains_by_id)
        for week in selected_weeks:
            week_id = int(week["id"])
            week_domain_ids = {
                state_domain_id for state_week_id, state_domain_id in states_by_week_domain if state_week_id == week_id
            }
            relevant_domain_ids.update(week_domain_ids)
            for state_domain_id in week_domain_ids:
                classification = _classify_states(states_by_week_domain[(week_id, state_domain_id)])
                if classification["presence"] == "recorded":
                    valid_states_by_domain[state_domain_id].append((week, classification["state"]))

        domain_index: list[dict[str, Any]] = []
        for candidate_id in relevant_domain_ids:
            metadata = domains_by_id.get(candidate_id)
            valid_states = valid_states_by_domain.get(candidate_id, [])
            is_active = metadata is not None and metadata["archived_at"] is None
            if not is_active and not valid_states:
                continue
            latest = valid_states[0] if valid_states else None
            identity = resolve_domain_identity(metadata, latest[1]["domain_name"] if latest else None)
            domain_index.append(
                {
                    "domain_id": candidate_id,
                    "name": identity["name"],
                    "name_source": identity["name_source"],
                    "archived": identity["archived"],
                    "unavailable": identity["unavailable"],
                    "recorded_state_count": len(valid_states),
                    "latest_record": _latest_record(latest, current_iso_week),
                    "sort_order": int(metadata["sort_order"]) if metadata is not None else 2**31,
                }
            )
        domain_index.sort(
            key=lambda item: (
                item["archived"] or item["unavailable"],
                item["sort_order"],
                item["name"].casefold(),
                item["domain_id"],
            )
        )
        for item in domain_index:
            item.pop("sort_order")

        if domain_id is None:
            domain_id = int(domain_index[0]["domain_id"]) if domain_index else None
        selected_domain = next((item for item in domain_index if item["domain_id"] == domain_id), None)
        if domain_id is not None and selected_domain is None:
            raise NotFoundError("Domain has no Condition history in this workspace")

        detail = (
            _build_domain_history(
                int(domain_id),
                selected_domain,
                selected_weeks,
                states_by_week_domain,
                current_iso_week,
            )
            if domain_id is not None and selected_domain is not None
            else None
        )
        return {
            "range": {"type": "reviewed_weeks", "value": reviewed_weeks},
            "domains": domain_index,
            "history": detail,
            "integrity": {
                "excluded_week_count": sum(excluded_reasons.values()),
                "excluded_reasons": dict(sorted(excluded_reasons.items())),
            },
        }


def _classify_states(states: Sequence[Any]) -> dict[str, Any]:
    if not states:
        return {"presence": "absent", "condition": None, "reason": None, "state": None}
    conditions = {str(state["condition"]) for state in states}
    if len(states) > 1 and len(conditions) > 1:
        return {
            "presence": "excluded",
            "condition": None,
            "reason": WeeklyIssueCode.DUPLICATE_DOMAIN_STATE.value,
            "state": None,
        }
    state = states[0]
    condition = str(state["condition"])
    if condition not in CONDITION_LABELS:
        return {
            "presence": "excluded",
            "condition": None,
            "reason": WeeklyIssueCode.INVALID_CONDITION.value,
            "state": None,
        }
    return {"presence": "recorded", "condition": condition, "reason": None, "state": state}


def _classify_attention_states(states: Sequence[Any]) -> dict[str, Any]:
    if not states:
        return {"presence": "absent", "attention": None, "reason": None}
    attentions = {str(state.get("attention", "")) for state in states}
    if len(states) > 1 and len(attentions) > 1:
        return {
            "presence": "excluded",
            "attention": None,
            "reason": WeeklyIssueCode.DUPLICATE_DOMAIN_STATE.value,
        }
    attention = str(states[0].get("attention", ""))
    if attention not in CANONICAL_ATTENTION_VALUES:
        return {
            "presence": "excluded",
            "attention": None,
            "reason": WeeklyIssueCode.INVALID_ATTENTION.value,
        }
    return {"presence": "recorded", "attention": attention, "reason": None}


def _latest_record(
    latest: tuple[Mapping[str, Any], Mapping[str, Any]] | None,
    current_iso_week: tuple[int, int],
) -> dict[str, Any] | None:
    if latest is None:
        return None
    week, state = latest
    return _record_reference(week, str(state["condition"]), current_iso_week)


def _record_reference(week: Mapping[str, Any], condition: str, current_iso_week: tuple[int, int]) -> dict[str, Any]:
    iso_year = int(week["iso_year"])
    iso_week = int(week["iso_week"])
    return {
        "week_id": int(week["id"]),
        "iso_year": iso_year,
        "iso_week": iso_week,
        "lifecycle": review_lifecycle(iso_year, iso_week, current_iso_week),
        "condition": condition,
    }


def _build_domain_history(
    domain_id: int,
    domain: Mapping[str, Any],
    selected_weeks: Sequence[Any],
    states_by_week_domain: Mapping[tuple[int, int], Sequence[Any]],
    current_iso_week: tuple[int, int],
) -> dict[str, Any]:
    chronological_weeks = []
    excluded_state_reasons: Counter[str] = Counter()
    for week in reversed(selected_weeks):
        states = states_by_week_domain.get((int(week["id"]), domain_id), [])
        classification = _classify_states(states)
        attention_classification = _classify_attention_states(states)
        iso_year = int(week["iso_year"])
        iso_week = int(week["iso_week"])
        entry = {
            "week_id": int(week["id"]),
            "iso_year": iso_year,
            "iso_week": iso_week,
            "lifecycle": review_lifecycle(iso_year, iso_week, current_iso_week),
            "presence": classification["presence"],
            "condition": classification["condition"],
            "excluded_reason": classification["reason"],
            "attention_presence": attention_classification["presence"],
            "attention": attention_classification["attention"],
            "attention_excluded_reason": attention_classification["reason"],
        }
        if classification["presence"] == "excluded":
            excluded_state_reasons[str(classification["reason"])] += 1
        chronological_weeks.append(entry)

    counts = {condition: 0 for condition in CONDITION_LABELS}
    for week in chronological_weeks:
        if week["presence"] == "recorded":
            counts[str(week["condition"])] += 1
    recorded_state_count = sum(counts.values())
    excluded_state_count = sum(excluded_state_reasons.values())
    present_state_count = recorded_state_count + excluded_state_count
    reviewed_week_count = len(chronological_weeks)
    shares = {
        condition: count / recorded_state_count if recorded_state_count else 0.0 for condition, count in counts.items()
    }
    latest_week = next(
        (week for week in reversed(chronological_weeks) if week["presence"] == "recorded"),
        None,
    )
    transitions, runs = _transitions_and_runs(chronological_weeks)
    paused_sequences = calculate_paused_streaks(chronological_weeks, current_iso_week=current_iso_week)
    paused_sequences["observations"] = _build_paused_observations(str(domain["name"]), paused_sequences)
    summary = {
        "reviewed_week_count": reviewed_week_count,
        "recorded_state_count": recorded_state_count,
        "present_state_count": present_state_count,
        "absent_state_count": reviewed_week_count - present_state_count,
        "excluded_state_count": excluded_state_count,
        "coverage_share": present_state_count / reviewed_week_count if reviewed_week_count else 0.0,
        "latest_record": latest_week,
        "counts": counts,
        "shares": shares,
    }
    return {
        "domain": dict(domain),
        "summary": summary,
        "weeks": chronological_weeks,
        "transitions": transitions,
        "runs": runs,
        "paused_sequences": paused_sequences,
        "observations": _build_observations(str(domain["name"]), summary),
        "excluded_reasons": dict(sorted(excluded_state_reasons.items())),
    }


def _transitions_and_runs(weeks: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    transitions: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    previous: Mapping[str, Any] | None = None
    current_run: dict[str, Any] | None = None
    for week in weeks:
        consecutive = previous is not None and weeks_are_consecutive(previous, week)
        if week["presence"] != "recorded" or not consecutive:
            if current_run is not None:
                runs.append(current_run)
            current_run = _start_run(week) if week["presence"] == "recorded" else None
            previous = week if week["presence"] == "recorded" else None
            continue

        assert previous is not None
        if previous["condition"] != week["condition"]:
            transitions.append(
                {
                    "from": previous["condition"],
                    "to": week["condition"],
                    "from_week": week_reference(previous),
                    "to_week": week_reference(week),
                }
            )
            if current_run is not None:
                runs.append(current_run)
            current_run = _start_run(week)
        elif current_run is not None:
            current_run["count"] += 1
            current_run["to_week"] = week_reference(week)
        previous = week
    if current_run is not None:
        runs.append(current_run)
    return transitions, runs


def _start_run(week: Mapping[str, Any]) -> dict[str, Any]:
    reference = week_reference(week)
    return {"condition": week["condition"], "count": 1, "from_week": reference, "to_week": reference}


def _build_observations(name: str, summary: Mapping[str, Any]) -> list[dict[str, str]]:
    observations = []
    recorded = int(summary["recorded_state_count"])
    for condition, label in CONDITION_LABELS.items():
        count = int(summary["counts"][condition])
        if count:
            observations.append(
                {
                    "code": "condition_frequency",
                    "text": f"{name} was recorded as {label} in {count} of {recorded} reviewed states.",
                }
            )
    latest = summary["latest_record"]
    if latest is not None:
        observations.append(
            {
                "code": "latest_condition",
                "text": f"The most recent recorded Condition is {CONDITION_LABELS[latest['condition']]}.",
            }
        )
    absent = int(summary["absent_state_count"])
    if absent:
        observations.append(
            {
                "code": "condition_absent",
                "text": f"No Condition was recorded for this Domain in {absent} reviewed snapshots.",
            }
        )
    excluded = int(summary["excluded_state_count"])
    if excluded:
        observations.append(
            {
                "code": "condition_excluded",
                "text": f"{excluded} Condition record could not be interpreted safely.",
            }
        )
    return observations


def _build_paused_observations(name: str, sequences: Mapping[str, Any]) -> list[dict[str, str]]:
    observations: list[dict[str, str]] = []
    current = sequences["current_streak"]
    if current["active"]:
        observations.append(
            {
                "code": "current_paused_sequence",
                "text": f"{name} has been Paused for {current['length']} consecutive reviewed weeks.",
            }
        )
        observations.append(
            {
                "code": "paused_sequence_started",
                "text": f"The current paused sequence began in Week {current['started']['iso_week']}.",
            }
        )
    longest = sequences["longest_streak"]
    if longest is not None:
        observations.append(
            {
                "code": "longest_paused_sequence",
                "text": f"The longest recorded paused sequence lasted {longest['length']} reviewed weeks.",
            }
        )
    return observations
