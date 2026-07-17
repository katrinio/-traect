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
from traect.app.database import create_schema
from traect.app.focus_history import FocusHistoryService, parse_focus_history_range
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
    domains: list[int],
    iso_year: int,
    iso_week: int,
    focus_domain_id: int | None,
) -> None:
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
                    attention=(
                        DomainAttention.PRIMARY_FOCUS if domain_id == focus_domain_id else DomainAttention.MAINTAINED
                    ),
                    condition=DomainCondition.STABLE,
                )
                for domain_id in domains
            ],
        )
    finally:
        clock.value = current


def aggregate(service: TraectService, reviewed_weeks: int | None = 12) -> dict[str, object]:
    workspace_id = service.get_current_workspace().id
    return FocusHistoryService(service.session).aggregate(
        workspace_id,
        current_iso_week=service.current_iso_week(),
        reviewed_weeks=reviewed_weeks,
    )


def test_empty_and_no_focus_history_keep_reviewed_week_denominator(session: Session) -> None:
    clock = MutableClock(week_clock(2026, 12))
    service = TraectService(session, clock=clock)
    workspace = service.create_workspace("Life")
    work = service.create_domain(workspace.id, "Work")

    assert aggregate(service)["summary"] == {
        "reviewed_week_count": 0,
        "focused_week_count": 0,
        "no_focus_week_count": 0,
        "excluded_week_count": 0,
    }

    save_week(service, clock, workspace.id, [work.id], 2026, 12, None)
    history = aggregate(service)

    assert history["summary"] == {
        "reviewed_week_count": 1,
        "focused_week_count": 0,
        "no_focus_week_count": 1,
        "excluded_week_count": 0,
    }
    assert history["domains"] == []
    assert history["zero_focus_domains"] == [{"domain_id": work.id, "name": "Work"}]


def test_distribution_uses_domain_identity_archives_and_all_reviewed_weeks(session: Session) -> None:
    clock = MutableClock(week_clock(2026, 15))
    service = TraectService(session, clock=clock)
    workspace = service.create_workspace("Life")
    first_work = service.create_domain(workspace.id, "Work")
    health = service.create_domain(workspace.id, "Health")
    domain_ids = [first_work.id, health.id]
    save_week(service, clock, workspace.id, domain_ids, 2026, 10, first_work.id)
    save_week(service, clock, workspace.id, domain_ids, 2026, 12, health.id)
    save_week(service, clock, workspace.id, domain_ids, 2026, 13, first_work.id)
    save_week(service, clock, workspace.id, domain_ids, 2026, 15, None)
    service.archive_domain(first_work.id)
    second_work = service.create_domain(workspace.id, "Work")

    history = aggregate(service)
    rows = history["domains"]

    assert history["summary"] == {
        "reviewed_week_count": 4,
        "focused_week_count": 3,
        "no_focus_week_count": 1,
        "excluded_week_count": 0,
    }
    assert [(row["domain_id"], row["focus_count"], row["focus_share"]) for row in rows] == [
        (first_work.id, 2, 0.5),
        (health.id, 1, 0.25),
    ]
    assert rows[0]["archived"] is True
    assert rows[0]["most_recent_focus"]["iso_week"] == 13
    assert history["zero_focus_domains"] == [{"domain_id": second_work.id, "name": "Work"}]
    assert [item["iso_week"] for item in history["weeks"]] == [15, 13, 12, 10]
    assert history["weeks"][0]["focus"] is None


def test_last_reviewed_weeks_ignore_calendar_gaps_and_include_saved_provisional(session: Session) -> None:
    clock = MutableClock(week_clock(2026, 20))
    service = TraectService(session, clock=clock)
    workspace = service.create_workspace("Life")
    work = service.create_domain(workspace.id, "Work")
    for iso_week in range(1, 14):
        save_week(service, clock, workspace.id, [work.id], 2026, iso_week, work.id)
    save_week(service, clock, workspace.id, [work.id], 2026, 20, work.id)

    history = aggregate(service, 12)

    assert history["summary"]["reviewed_week_count"] == 12
    assert [week["iso_week"] for week in history["weeks"]] == [20, *range(13, 2, -1)]
    assert history["weeks"][0]["lifecycle"] == "provisional"
    assert history["weeks"][1]["lifecycle"] == "final"


def test_all_history_crosses_iso_year_and_reflects_persisted_correction(session: Session) -> None:
    clock = MutableClock(week_clock(2026, 2))
    service = TraectService(session, clock=clock)
    workspace = service.create_workspace("Life")
    work = service.create_domain(workspace.id, "Work")
    health = service.create_domain(workspace.id, "Health")
    save_week(service, clock, workspace.id, [work.id, health.id], 2025, 52, work.id)
    save_week(service, clock, workspace.id, [work.id, health.id], 2026, 2, work.id)

    before = aggregate(service, None)
    assert before["domains"][0]["focus_count"] == 2

    week_id = before["weeks"][1]["week_id"]
    service.session.execute(
        text("UPDATE week_domain_state SET attention = 'maintained' WHERE week_id = :week_id"),
        {"week_id": week_id},
    )
    service.session.execute(
        text(
            "UPDATE week_domain_state SET attention = 'primary_focus' "
            "WHERE week_id = :week_id AND domain_id = :domain_id"
        ),
        {"week_id": week_id, "domain_id": health.id},
    )

    corrected = aggregate(service, None)
    assert [(row["domain_id"], row["focus_count"]) for row in corrected["domains"]] == [
        (work.id, 1),
        (health.id, 1),
    ]
    assert [(week["iso_year"], week["iso_week"]) for week in corrected["weeks"]] == [(2026, 2), (2025, 52)]


def test_integrity_exclusions_and_missing_domain_fallback_are_deterministic() -> None:
    history = FocusHistoryService._aggregate_rows(
        week_rows=[
            {"id": 5, "iso_year": 2026, "iso_week": 5},
            {"id": 4, "iso_year": 2026, "iso_week": 4},
            {"id": 3, "iso_year": 2026, "iso_week": 3},
            {"id": 2, "iso_year": 2026, "iso_week": 3},
            {"id": 1, "iso_year": 2026, "iso_week": 1},
        ],
        state_rows=[
            {"id": 1, "week_id": 5, "domain_id": 10, "domain_name": "Ghost", "attention": "primary_focus"},
            {"id": 2, "week_id": 4, "domain_id": 1, "domain_name": "Work", "attention": "primary_focus"},
            {"id": 3, "week_id": 4, "domain_id": 2, "domain_name": "Health", "attention": "primary_focus"},
            {"id": 4, "week_id": 3, "domain_id": 1, "domain_name": "Work", "attention": "maintained"},
            {"id": 5, "week_id": 2, "domain_id": 2, "domain_name": "Health", "attention": "maintained"},
            {"id": 6, "week_id": 1, "domain_id": 2, "domain_name": "Health", "attention": "primary_focus"},
        ],
        domain_rows=[
            {"id": 1, "name": "Work", "sort_order": 1, "archived_at": None},
            {"id": 2, "name": "Health", "sort_order": 2, "archived_at": None},
        ],
        current_iso_week=(2026, 5),
        reviewed_weeks=None,
    )

    assert history["summary"] == {
        "reviewed_week_count": 2,
        "focused_week_count": 2,
        "no_focus_week_count": 0,
        "excluded_week_count": 2,
    }
    assert history["excluded_reasons"] == {"duplicate_week": 1, "multiple_primary_focus": 1}
    assert history["domains"][0]["name"] == "Ghost"
    assert history["domains"][0]["name_source"] == "snapshot"
    assert history["domains"][0]["unavailable"] is True


def test_focus_history_domain_identity_fallback_rules() -> None:
    history = FocusHistoryService._aggregate_rows(
        week_rows=[
            {"id": 3, "iso_year": 2026, "iso_week": 3},
            {"id": 2, "iso_year": 2026, "iso_week": 2},
            {"id": 1, "iso_year": 2026, "iso_week": 1},
        ],
        state_rows=[
            {"id": 1, "week_id": 3, "domain_id": 1, "domain_name": "", "attention": "primary_focus"},
            {"id": 2, "week_id": 2, "domain_id": 9, "domain_name": "Ghost", "attention": "primary_focus"},
            {"id": 3, "week_id": 1, "domain_id": 8, "domain_name": " ", "attention": "primary_focus"},
        ],
        domain_rows=[{"id": 1, "name": "Work", "sort_order": 1, "archived_at": None}],
        current_iso_week=(2026, 3),
        reviewed_weeks=None,
    )

    domains = {domain["domain_id"]: domain for domain in history["domains"]}
    assert domains[1]["name"] == "Work"
    assert domains[1]["name_source"] == "current_domain"
    assert domains[1]["unavailable"] is False
    assert domains[9]["name"] == "Ghost"
    assert domains[9]["name_source"] == "snapshot"
    assert domains[9]["unavailable"] is True
    assert domains[8]["name"] == "Unavailable Domain"
    assert domains[8]["name_source"] == "fallback"
    assert domains[8]["unavailable"] is True


def test_focus_history_uses_three_bounded_queries(session: Session) -> None:
    clock = MutableClock(week_clock(2026, 2))
    service = TraectService(session, clock=clock)
    workspace = service.create_workspace("Life")
    work = service.create_domain(workspace.id, "Work")
    save_week(service, clock, workspace.id, [work.id], 2026, 2, work.id)
    statements: list[str] = []
    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", lambda *args: statements.append(args[2]))

    FocusHistoryService(session).aggregate(workspace.id, current_iso_week=(2026, 2), reviewed_weeks=12)

    assert len(statements) == 3


@pytest.mark.parametrize(("value", "expected"), [(None, 12), ("12", 12), ("26", 26), ("52", 52), ("all", None)])
def test_supported_ranges(value: str | None, expected: int | None) -> None:
    assert parse_focus_history_range(value) == expected


@pytest.mark.parametrize("value", ["", "0", "13", "everything"])
def test_invalid_ranges_are_rejected(value: str) -> None:
    with pytest.raises(Exception, match="12, 26, 52, or all"):
        parse_focus_history_range(value)


def test_focus_history_api_shape_ranges_and_week_references(tmp_path: Path) -> None:
    clock = MutableClock(datetime(2026, 7, 17, 12, tzinfo=UTC))
    app = build_app(f"sqlite:///{tmp_path / 'focus.db'}", clock=clock)
    request(app, "POST", "/workspaces", body=b'{"name":"Life","domains":[{"name":"Work"}]}')
    request(
        app,
        "PUT",
        "/workspaces/1/weeks/2026/29",
        body=b'{"states":[{"domain_id":1,"attention":"primary_focus","condition":"stable"}]}',
    )

    response = request(app, "GET", "/workspaces/1/history/focus?reviewed_weeks=all")
    payload = json.loads(response["body"])

    assert response["status"].startswith("200")
    assert payload["range"] == {"type": "reviewed_weeks", "value": None}
    assert payload["summary"]["reviewed_week_count"] == 1
    assert payload["domains"][0]["focus_share"] == 1.0
    assert payload["weeks"][0] == {
        "week_id": 1,
        "iso_year": 2026,
        "iso_week": 29,
        "lifecycle": "provisional",
        "focus": {"domain_id": 1, "name": "Work", "archived": False, "unavailable": False, "name_source": "snapshot"},
    }

    invalid = request(app, "GET", "/workspaces/1/history/focus?reviewed_weeks=10")
    repeated = request(app, "GET", "/workspaces/1/history/focus?reviewed_weeks=12&reviewed_weeks=26")
    assert invalid["status"].startswith("400")
    assert repeated["status"].startswith("400")
