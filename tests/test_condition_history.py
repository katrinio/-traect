from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from tests.support import MutableClock, week_clock
from tests.support import wsgi_request as request
from traect.api.app import build_app
from traect.app.condition_history import ConditionHistoryService
from traect.app.database import create_schema
from traect.app.service import TraectService, WeekStateInput
from traect.domain.enums import DomainAttention, DomainCondition


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    create_schema(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False, future=True)
    try:
        with factory() as session:
            yield session
    finally:
        engine.dispose()


def save_week(
    service: TraectService,
    clock: MutableClock,
    workspace_id: int,
    domain_conditions: dict[int, DomainCondition],
    iso_year: int,
    iso_week: int,
    domain_attentions: dict[int, DomainAttention] | None = None,
) -> None:
    domain_attentions = domain_attentions or {}
    current = clock.value
    clock.value = week_clock(iso_year, iso_week)
    try:
        service.upsert_week(
            workspace_id,
            iso_year,
            iso_week,
            states=[
                WeekStateInput(
                    domain_id=domain_id,
                    attention=domain_attentions.get(domain_id, DomainAttention.MAINTAINED),
                    condition=condition,
                )
                for domain_id, condition in domain_conditions.items()
            ],
        )
    finally:
        clock.value = current


def aggregate(
    service: TraectService,
    workspace_id: int,
    domain_id: int | None = None,
    reviewed_weeks: int | None = 12,
) -> dict[str, object]:
    return ConditionHistoryService(service.session).aggregate(
        workspace_id,
        current_iso_week=service.current_iso_week(),
        reviewed_weeks=reviewed_weeks,
        domain_id=domain_id,
    )


def test_no_reviews_selects_first_active_domain_with_calm_empty_summary(session: Session) -> None:
    clock = MutableClock(week_clock(2026, 10))
    service = TraectService(session, clock=clock)
    workspace = service.create_workspace("Life")
    work = service.create_domain(workspace.id, "Work")
    service.create_domain(workspace.id, "Health")

    payload = aggregate(service, workspace.id)

    assert payload["domains"][0]["domain_id"] == work.id
    assert payload["history"]["summary"] == {
        "reviewed_week_count": 0,
        "recorded_state_count": 0,
        "present_state_count": 0,
        "absent_state_count": 0,
        "excluded_state_count": 0,
        "coverage_share": 0.0,
        "latest_record": None,
        "counts": {"stable": 0, "at_risk": 0, "critical": 0},
        "shares": {"stable": 0.0, "at_risk": 0.0, "critical": 0.0},
    }


def test_distribution_coverage_latest_transition_and_absence_break(session: Session) -> None:
    clock = MutableClock(week_clock(2026, 4))
    service = TraectService(session, clock=clock)
    workspace = service.create_workspace("Life")
    health = service.create_domain(workspace.id, "Health")
    save_week(service, clock, workspace.id, {health.id: DomainCondition.STABLE}, 2026, 1)
    save_week(service, clock, workspace.id, {health.id: DomainCondition.AT_RISK}, 2026, 2)
    save_week(service, clock, workspace.id, {health.id: DomainCondition.STABLE}, 2026, 3)
    service.session.execute(
        text(
            "DELETE FROM week_domain_state WHERE week_id = "
            "(SELECT id FROM week WHERE workspace_id = :workspace_id AND iso_week = 3)"
        ),
        {"workspace_id": workspace.id},
    )
    service.session.expunge_all()
    save_week(service, clock, workspace.id, {health.id: DomainCondition.CRITICAL}, 2026, 4)

    history = aggregate(service, workspace.id, health.id)["history"]
    summary = history["summary"]

    assert summary["recorded_state_count"] == 3
    assert summary["present_state_count"] == 3
    assert summary["absent_state_count"] == 1
    assert summary["coverage_share"] == 0.75
    assert summary["counts"] == {"stable": 1, "at_risk": 1, "critical": 1}
    assert summary["shares"] == pytest.approx({"stable": 1 / 3, "at_risk": 1 / 3, "critical": 1 / 3})
    assert summary["latest_record"]["condition"] == "critical"
    assert summary["latest_record"]["lifecycle"] == "provisional"
    assert [week["presence"] for week in history["weeks"]] == ["recorded", "recorded", "absent", "recorded"]
    assert history["transitions"] == [
        {
            "from": "stable",
            "to": "at_risk",
            "from_week": {"week_id": 1, "iso_year": 2026, "iso_week": 1},
            "to_week": {"week_id": 2, "iso_year": 2026, "iso_week": 2},
        }
    ]
    assert [run["count"] for run in history["runs"]] == [1, 1, 1]


def test_missing_calendar_week_breaks_consecutive_records_without_inventing_snapshot(session: Session) -> None:
    clock = MutableClock(week_clock(2026, 3))
    service = TraectService(session, clock=clock)
    workspace = service.create_workspace("Life")
    work = service.create_domain(workspace.id, "Work")
    save_week(service, clock, workspace.id, {work.id: DomainCondition.STABLE}, 2026, 1)
    save_week(service, clock, workspace.id, {work.id: DomainCondition.STABLE}, 2026, 3)

    history = aggregate(service, workspace.id, work.id)["history"]

    assert [week["iso_week"] for week in history["weeks"]] == [1, 3]
    assert history["transitions"] == []
    assert [run["count"] for run in history["runs"]] == [1, 1]


def test_archived_domains_and_same_names_remain_separate(session: Session) -> None:
    clock = MutableClock(week_clock(2026, 5))
    service = TraectService(session, clock=clock)
    workspace = service.create_workspace("Life")
    first_work = service.create_domain(workspace.id, "Work")
    save_week(service, clock, workspace.id, {first_work.id: DomainCondition.AT_RISK}, 2026, 4)
    service.archive_domain(first_work.id)
    second_work = service.create_domain(workspace.id, "Work")
    save_week(service, clock, workspace.id, {second_work.id: DomainCondition.STABLE}, 2026, 5)

    payload = aggregate(service, workspace.id)

    assert [(item["domain_id"], item["archived"]) for item in payload["domains"]] == [
        (second_work.id, False),
        (first_work.id, True),
    ]
    assert payload["history"]["domain"]["domain_id"] == second_work.id


def test_last_reviewed_range_uses_reviews_across_iso_boundary(session: Session) -> None:
    clock = MutableClock(week_clock(2026, 13))
    service = TraectService(session, clock=clock)
    workspace = service.create_workspace("Life")
    work = service.create_domain(workspace.id, "Work")
    periods = [(2025, 52), *[(2026, week) for week in range(1, 14)]]
    for iso_year, iso_week in periods:
        save_week(service, clock, workspace.id, {work.id: DomainCondition.STABLE}, iso_year, iso_week)

    payload = aggregate(service, workspace.id, work.id, 12)

    assert payload["history"]["summary"]["reviewed_week_count"] == 12
    assert [(week["iso_year"], week["iso_week"]) for week in payload["history"]["weeks"]] == [
        *[(2026, week) for week in range(2, 14)]
    ]


def test_correction_and_invalid_condition_are_reflected_without_cached_counts(session: Session) -> None:
    clock = MutableClock(week_clock(2026, 2))
    service = TraectService(session, clock=clock)
    workspace = service.create_workspace("Life")
    work = service.create_domain(workspace.id, "Work")
    save_week(service, clock, workspace.id, {work.id: DomainCondition.STABLE}, 2026, 1)
    save_week(service, clock, workspace.id, {work.id: DomainCondition.AT_RISK}, 2026, 2)

    service.session.execute(
        text(
            "UPDATE week_domain_state SET condition = 'critical' WHERE week_id = "
            "(SELECT id FROM week WHERE workspace_id = :workspace_id AND iso_week = 1)"
        ),
        {"workspace_id": workspace.id},
    )
    corrected = aggregate(service, workspace.id, work.id)["history"]
    assert corrected["summary"]["counts"] == {"stable": 0, "at_risk": 1, "critical": 1}

    service.session.execute(
        text(
            "UPDATE week_domain_state SET condition = 'unknown' WHERE week_id = "
            "(SELECT id FROM week WHERE workspace_id = :workspace_id AND iso_week = 1)"
        ),
        {"workspace_id": workspace.id},
    )
    invalid = aggregate(service, workspace.id, work.id)["history"]
    assert invalid["summary"]["recorded_state_count"] == 1
    assert invalid["summary"]["excluded_state_count"] == 1
    assert invalid["weeks"][0]["presence"] == "excluded"
    assert invalid["weeks"][0]["excluded_reason"] == "invalid_condition"
    assert invalid["transitions"] == []


def test_conflicting_duplicate_and_missing_reference_integrity_handling() -> None:
    payload = ConditionHistoryService._aggregate_rows(
        week_rows=[
            {"id": 3, "iso_year": 2026, "iso_week": 3},
            {"id": 2, "iso_year": 2026, "iso_week": 2},
            {"id": 1, "iso_year": 2026, "iso_week": 1},
        ],
        state_rows=[
            {"id": 1, "week_id": 1, "domain_id": 99, "domain_name": "Gone", "condition": "stable"},
            {"id": 2, "week_id": 2, "domain_id": 99, "domain_name": "Gone", "condition": "stable"},
            {"id": 3, "week_id": 2, "domain_id": 99, "domain_name": "Gone", "condition": "critical"},
        ],
        domain_rows=[],
        current_iso_week=(2026, 3),
        reviewed_weeks=None,
        domain_id=99,
    )

    history = payload["history"]
    assert history["domain"]["name"] == "Unavailable Domain"
    assert history["domain"]["unavailable"] is True
    assert [week["presence"] for week in history["weeks"]] == ["recorded", "excluded", "absent"]
    assert history["summary"]["excluded_state_count"] == 1
    assert history["excluded_reasons"] == {"duplicate_domain_state": 1}


def test_duplicate_week_is_not_counted_twice() -> None:
    payload = ConditionHistoryService._aggregate_rows(
        week_rows=[
            {"id": 2, "iso_year": 2026, "iso_week": 2},
            {"id": 3, "iso_year": 2026, "iso_week": 2},
            {"id": 1, "iso_year": 2026, "iso_week": 1},
        ],
        state_rows=[{"id": 1, "week_id": 1, "domain_id": 1, "domain_name": "Work", "condition": "stable"}],
        domain_rows=[{"id": 1, "name": "Work", "sort_order": 1, "archived_at": None}],
        current_iso_week=(2026, 2),
        reviewed_weeks=None,
        domain_id=1,
    )

    assert payload["history"]["summary"]["reviewed_week_count"] == 1
    assert payload["integrity"] == {
        "excluded_week_count": 1,
        "excluded_reasons": {"duplicate_week": 1},
    }


def test_condition_history_uses_three_bounded_queries(session: Session) -> None:
    clock = MutableClock(week_clock(2026, 1))
    service = TraectService(session, clock=clock)
    workspace = service.create_workspace("Life")
    work = service.create_domain(workspace.id, "Work")
    save_week(service, clock, workspace.id, {work.id: DomainCondition.STABLE}, 2026, 1)
    statements: list[str] = []
    event.listen(session.get_bind(), "before_cursor_execute", lambda *args: statements.append(args[2]))

    aggregate(service, workspace.id, work.id)

    assert len(statements) == 3


def test_condition_history_api_shape_validation_and_no_score(tmp_path: Path) -> None:
    clock = MutableClock(datetime(2026, 7, 17, 12, tzinfo=UTC))
    app = build_app(f"sqlite:///{tmp_path / 'condition.db'}", clock=clock)
    request(app, "POST", "/workspaces", body=b'{"name":"Life","domains":[{"name":"Health"}]}')
    request(
        app,
        "PUT",
        "/workspaces/1/weeks/2026/29",
        body=b'{"states":[{"domain_id":1,"attention":"maintained","condition":"at_risk"}]}',
    )

    response = request(app, "GET", "/workspaces/1/history/condition?domain_id=1&reviewed_weeks=all")
    payload = json.loads(response["body"])

    assert response["status"].startswith("200")
    assert payload["range"] == {"type": "reviewed_weeks", "value": None}
    assert payload["history"]["summary"]["counts"] == {"stable": 0, "at_risk": 1, "critical": 0}
    assert payload["history"]["summary"]["shares"] == {"stable": 0.0, "at_risk": 1.0, "critical": 0.0}
    assert payload["history"]["weeks"][0]["presence"] == "recorded"
    assert payload["history"]["weeks"][0]["lifecycle"] == "provisional"
    assert payload["history"]["paused_sequences"] == {
        "current_streak": {"active": False, "length": 0, "started": None},
        "longest_streak": None,
        "streaks": [],
        "excluded_state_count": 0,
        "excluded_reasons": {},
        "observations": [],
    }
    assert {item["code"] for item in payload["history"]["observations"]} == {
        "condition_frequency",
        "latest_condition",
    }
    assert "score" not in json.dumps(payload).lower()

    request(
        app,
        "PUT",
        "/workspaces/1/weeks/2026/29",
        body=b'{"states":[{"domain_id":1,"attention":"paused","condition":"at_risk"}]}',
    )
    paused_payload = json.loads(
        request(app, "GET", "/workspaces/1/history/condition?domain_id=1&reviewed_weeks=all")["body"]
    )
    assert paused_payload["history"]["paused_sequences"]["current_streak"] == {
        "active": True,
        "length": 1,
        "started": {"week_id": 1, "iso_year": 2026, "iso_week": 29},
    }
    assert paused_payload["history"]["paused_sequences"]["longest_streak"]["length"] == 1

    missing = request(app, "GET", "/workspaces/1/history/condition?domain_id=999")
    invalid_domain = request(app, "GET", "/workspaces/1/history/condition?domain_id=health")
    invalid_range = request(app, "GET", "/workspaces/1/history/condition?reviewed_weeks=10")
    assert missing["status"].startswith("404")
    assert invalid_domain["status"].startswith("400")
    assert invalid_range["status"].startswith("400")


def test_paused_sequences_current_longest_interruptions_and_iso_boundary(session: Session) -> None:
    clock = MutableClock(week_clock(2026, 2))
    service = TraectService(session, clock=clock)
    workspace = service.create_workspace("Life")
    learning = service.create_domain(workspace.id, "Learning")
    attention_by_period = [
        (2025, 51, DomainAttention.PAUSED),
        (2025, 52, DomainAttention.PAUSED),
        (2026, 1, DomainAttention.MAINTAINED),
        (2026, 2, DomainAttention.PAUSED),
    ]
    for iso_year, iso_week, attention in attention_by_period:
        save_week(
            service,
            clock,
            workspace.id,
            {learning.id: DomainCondition.STABLE},
            iso_year,
            iso_week,
            {learning.id: attention},
        )

    sequences = aggregate(service, workspace.id, learning.id, None)["history"]["paused_sequences"]

    assert sequences["current_streak"] == {
        "active": True,
        "length": 1,
        "started": {"week_id": 4, "iso_year": 2026, "iso_week": 2},
    }
    assert sequences["longest_streak"]["length"] == 2
    assert [(item["length"], item["active"]) for item in sequences["streaks"]] == [(2, False), (1, True)]
    assert [week["iso_week"] for week in sequences["streaks"][0]["weeks"]] == [51, 52]


@pytest.mark.parametrize("interrupting_attention", [DomainAttention.MAINTAINED, DomainAttention.PRIMARY_FOCUS])
def test_non_paused_attention_interrupts_sequence(
    session: Session,
    interrupting_attention: DomainAttention,
) -> None:
    payload = ConditionHistoryService._aggregate_rows(
        week_rows=[
            {"id": 3, "iso_year": 2026, "iso_week": 3},
            {"id": 2, "iso_year": 2026, "iso_week": 2},
            {"id": 1, "iso_year": 2026, "iso_week": 1},
        ],
        state_rows=[
            {
                "id": period,
                "week_id": period,
                "domain_id": 1,
                "domain_name": "Work",
                "condition": "stable",
                "attention": attention,
            }
            for period, attention in [(1, "paused"), (2, interrupting_attention.value), (3, "paused")]
        ],
        domain_rows=[{"id": 1, "name": "Work", "sort_order": 1, "archived_at": None}],
        current_iso_week=(2026, 3),
        reviewed_weeks=None,
        domain_id=1,
    )

    assert [streak["length"] for streak in payload["history"]["paused_sequences"]["streaks"]] == [1, 1]


def test_missing_review_absent_state_and_excluded_state_break_paused_sequences() -> None:
    payload = ConditionHistoryService._aggregate_rows(
        week_rows=[
            {"id": 6, "iso_year": 2026, "iso_week": 7},
            {"id": 5, "iso_year": 2026, "iso_week": 6},
            {"id": 4, "iso_year": 2026, "iso_week": 5},
            {"id": 3, "iso_year": 2026, "iso_week": 4},
            {"id": 2, "iso_year": 2026, "iso_week": 2},
            {"id": 1, "iso_year": 2026, "iso_week": 1},
        ],
        state_rows=[
            {
                "id": 1,
                "week_id": 1,
                "domain_id": 1,
                "domain_name": "Work",
                "condition": "stable",
                "attention": "paused",
            },
            {
                "id": 2,
                "week_id": 2,
                "domain_id": 1,
                "domain_name": "Work",
                "condition": "stable",
                "attention": "paused",
            },
            {
                "id": 3,
                "week_id": 4,
                "domain_id": 1,
                "domain_name": "Work",
                "condition": "stable",
                "attention": "paused",
            },
            {
                "id": 4,
                "week_id": 5,
                "domain_id": 1,
                "domain_name": "Work",
                "condition": "stable",
                "attention": "unknown",
            },
            {
                "id": 5,
                "week_id": 6,
                "domain_id": 1,
                "domain_name": "Work",
                "condition": "stable",
                "attention": "paused",
            },
        ],
        domain_rows=[{"id": 1, "name": "Work", "sort_order": 1, "archived_at": "2026-01-01"}],
        current_iso_week=(2026, 7),
        reviewed_weeks=None,
        domain_id=1,
    )

    history = payload["history"]
    assert history["domain"]["archived"] is True
    assert [week["attention_presence"] for week in history["weeks"]] == [
        "recorded",
        "recorded",
        "absent",
        "recorded",
        "excluded",
        "recorded",
    ]
    assert [streak["length"] for streak in history["paused_sequences"]["streaks"]] == [2, 1, 1]
    assert history["paused_sequences"]["excluded_reasons"] == {"invalid_attention": 1}
    assert history["paused_sequences"]["current_streak"]["active"] is True


def test_paused_sequence_recomputes_after_historical_correction(session: Session) -> None:
    clock = MutableClock(week_clock(2026, 2))
    service = TraectService(session, clock=clock)
    workspace = service.create_workspace("Life")
    work = service.create_domain(workspace.id, "Work")
    for iso_week in (1, 2):
        save_week(
            service,
            clock,
            workspace.id,
            {work.id: DomainCondition.STABLE},
            2026,
            iso_week,
            {work.id: DomainAttention.PAUSED},
        )
    assert aggregate(service, workspace.id, work.id)["history"]["paused_sequences"]["current_streak"]["length"] == 2

    service.session.execute(
        text("UPDATE week_domain_state SET attention = 'maintained' WHERE week_id = 1 AND domain_id = :domain_id"),
        {"domain_id": work.id},
    )

    sequences = aggregate(service, workspace.id, work.id)["history"]["paused_sequences"]
    assert sequences["current_streak"]["length"] == 1
    assert sequences["longest_streak"]["length"] == 1


def test_missing_current_review_means_historical_pause_is_not_active() -> None:
    payload = ConditionHistoryService._aggregate_rows(
        week_rows=[{"id": 1, "iso_year": 2026, "iso_week": 3}],
        state_rows=[
            {
                "id": 1,
                "week_id": 1,
                "domain_id": 1,
                "domain_name": "Work",
                "condition": "stable",
                "attention": "paused",
            }
        ],
        domain_rows=[{"id": 1, "name": "Work", "sort_order": 1, "archived_at": None}],
        current_iso_week=(2026, 4),
        reviewed_weeks=None,
        domain_id=1,
    )

    sequences = payload["history"]["paused_sequences"]
    assert sequences["current_streak"] == {"active": False, "length": 0, "started": None}
    assert sequences["streaks"][0]["active"] is False


def test_conflicting_duplicate_attention_is_excluded_and_breaks_sequence() -> None:
    payload = ConditionHistoryService._aggregate_rows(
        week_rows=[
            {"id": 3, "iso_year": 2026, "iso_week": 3},
            {"id": 2, "iso_year": 2026, "iso_week": 2},
            {"id": 1, "iso_year": 2026, "iso_week": 1},
        ],
        state_rows=[
            {
                "id": 1,
                "week_id": 1,
                "domain_id": 1,
                "domain_name": "Work",
                "condition": "stable",
                "attention": "paused",
            },
            {
                "id": 2,
                "week_id": 2,
                "domain_id": 1,
                "domain_name": "Work",
                "condition": "stable",
                "attention": "paused",
            },
            {
                "id": 3,
                "week_id": 2,
                "domain_id": 1,
                "domain_name": "Work",
                "condition": "stable",
                "attention": "maintained",
            },
            {
                "id": 4,
                "week_id": 3,
                "domain_id": 1,
                "domain_name": "Work",
                "condition": "stable",
                "attention": "paused",
            },
        ],
        domain_rows=[{"id": 1, "name": "Work", "sort_order": 1, "archived_at": None}],
        current_iso_week=(2026, 3),
        reviewed_weeks=None,
        domain_id=1,
    )

    sequences = payload["history"]["paused_sequences"]
    assert [streak["length"] for streak in sequences["streaks"]] == [1, 1]
    assert sequences["excluded_reasons"] == {"duplicate_domain_state": 1}
