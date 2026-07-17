from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from tests.support import MutableClock, week_clock
from tests.support import wsgi_request as request
from traect.api.app import build_app
from traect.app.database import create_schema
from traect.app.service import TraectService, WeekStateInput
from traect.app.tradeoff_history import TradeoffHistoryService
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


def week(week_id: int, iso_week: int, sacrifice_id: int | None = None) -> dict[str, object]:
    return {
        "id": week_id,
        "iso_year": 2026,
        "iso_week": iso_week,
        "sacrificed_domain_id": sacrifice_id,
        "sacrificed_domain_name": None,
    }


def state(state_id: int, week_id: int, domain_id: int, name: str, attention: str) -> dict[str, object]:
    return {
        "id": state_id,
        "week_id": week_id,
        "domain_id": domain_id,
        "domain_name": name,
        "attention": attention,
        "condition": "stable",
    }


def domain(domain_id: int, name: str, order: int, archived: bool = False) -> dict[str, object]:
    return {
        "id": domain_id,
        "name": name,
        "sort_order": order,
        "archived_at": "2026-01-01" if archived else None,
    }


def aggregate(
    weeks: list[dict[str, object]],
    states: list[dict[str, object]],
    domains: list[dict[str, object]],
    *,
    reviewed_weeks: int | None = None,
    current: tuple[int, int] = (2026, 6),
    focus_domain_id: int | None = None,
    sacrifice_domain_id: int | None = None,
) -> dict[str, object]:
    return TradeoffHistoryService._aggregate_rows(
        weeks,
        states,
        domains,
        current_iso_week=current,
        reviewed_weeks=reviewed_weeks,
        focus_domain_id=focus_domain_id,
        sacrifice_domain_id=sacrifice_domain_id,
    )


def test_empty_history_has_explicit_zero_summary() -> None:
    payload = aggregate([], [], [domain(1, "Work", 1)])

    assert payload["summary"] == {
        "reviewed_week_count": 0,
        "focus_week_count": 0,
        "sacrifice_week_count": 0,
        "valid_pair_count": 0,
        "focus_without_sacrifice_count": 0,
        "no_focus_count": 0,
        "excluded_pair_count": 0,
    }
    assert payload["pairs"] == []
    assert payload["weeks"] == []


def test_rankings_ordered_pairs_breakdowns_denominators_and_provisional_week() -> None:
    domains = [domain(1, "Work", 1), domain(2, "Social", 2, archived=True), domain(3, "Health", 3)]
    weeks = [
        week(6, 6, 2),
        week(5, 5, 1),
        week(4, 4, 2),
        week(3, 3, 2),
        week(2, 2),
        week(1, 1),
    ]
    states = [
        state(1, 1, 1, "Work", "maintained"),
        state(2, 1, 2, "Social", "maintained"),
        state(3, 2, 1, "Work", "primary_focus"),
        state(4, 2, 2, "Social", "maintained"),
        state(5, 3, 1, "Work", "primary_focus"),
        state(6, 3, 2, "Social", "maintained"),
        state(7, 4, 1, "Work", "primary_focus"),
        state(8, 4, 2, "Social", "maintained"),
        state(9, 5, 1, "Work", "maintained"),
        state(10, 5, 2, "Social", "primary_focus"),
        state(11, 6, 2, "Social", "maintained"),
        state(12, 6, 3, "Health", "primary_focus"),
    ]

    payload = aggregate(weeks, states, domains)

    assert payload["summary"] == {
        "reviewed_week_count": 6,
        "focus_week_count": 5,
        "sacrifice_week_count": 4,
        "valid_pair_count": 4,
        "focus_without_sacrifice_count": 1,
        "no_focus_count": 1,
        "excluded_pair_count": 0,
    }
    assert [(item["name"], item["count"], item["share_of_pairs"]) for item in payload["sacrifices"]] == [
        ("Social", 3, 0.75),
        ("Work", 1, 0.25),
    ]
    assert [
        (item["focus"]["domain_id"], item["sacrifice"]["domain_id"], item["count"]) for item in payload["pairs"]
    ] == [(1, 2, 2), (3, 2, 1), (2, 1, 1)]
    assert payload["pairs"][0]["most_recent"]["iso_week"] == 4
    assert payload["pairs"][1]["most_recent"]["lifecycle"] == "provisional"
    work = payload["focus_breakdowns"][0]
    assert (work["focus_week_count"], work["paired_week_count"], work["no_tradeoff_count"]) == (3, 2, 1)
    assert work["sacrifices"][0]["share_of_focus_weeks"] == pytest.approx(2 / 3)
    social = next(item for item in payload["sacrifice_breakdowns"] if item["sacrifice"]["domain_id"] == 2)
    assert [(item["focus"]["domain_id"], item["count"]) for item in social["focuses"]] == [(1, 2), (3, 1)]
    assert payload["sacrifices"][0]["archived"] is True
    assert [item["status"] for item in payload["weeks"]] == [
        "paired",
        "paired",
        "paired",
        "paired",
        "focus_without_sacrifice",
        "no_focus",
    ]


def test_integrity_exclusions_are_explicit_and_duplicate_week_is_not_counted_twice() -> None:
    weeks = [week(6, 5), week(5, 5), week(4, 4, 99), week(3, 3, 1), week(2, 2, 2), week(1, 1, 2)]
    states = [
        state(1, 1, 1, "Work", "maintained"),
        state(2, 1, 2, "Social", "maintained"),
        state(3, 2, 1, "Work", "primary_focus"),
        state(4, 2, 2, "Social", "primary_focus"),
        state(5, 3, 1, "Work", "primary_focus"),
        state(6, 4, 1, "Work", "primary_focus"),
    ]

    payload = aggregate(weeks, states, [domain(1, "Work", 1), domain(2, "Social", 2)])

    assert payload["summary"]["reviewed_week_count"] == 4
    assert payload["summary"]["valid_pair_count"] == 0
    assert payload["summary"]["excluded_pair_count"] == 5
    assert payload["integrity"]["excluded_reasons"] == {
        "duplicate_week": 1,
        "focus_equals_sacrifice": 1,
        "multiple_primary_focus": 1,
        "sacrifice_missing_state": 1,
        "sacrifice_without_focus": 1,
    }
    assert all(item["status"] == "excluded" for item in payload["weeks"])


def test_missing_current_domain_reference_and_same_names_keep_stable_identities() -> None:
    payload = aggregate(
        [week(2, 2, 3), week(1, 1, 2)],
        [
            state(1, 1, 1, "Work", "primary_focus"),
            state(2, 1, 2, "Same", "maintained"),
            state(3, 2, 1, "Work", "primary_focus"),
            state(4, 2, 3, "Same", "maintained"),
        ],
        [domain(1, "Work", 1), domain(2, "Same", 2)],
        current=(2026, 2),
    )

    assert [item["domain_id"] for item in payload["sacrifices"]] == [3, 2]
    assert payload["sacrifices"][0]["unavailable"] is True
    assert payload["pairs"][0]["sacrifice"]["name"] == "Same"
    assert len(payload["pairs"]) == 2


def test_tradeoff_history_domain_identity_fallback_rules() -> None:
    payload = aggregate(
        [week(3, 3), week(2, 2), week(1, 1)],
        [
            state(1, 3, 1, "", "primary_focus"),
            state(2, 2, 9, "Ghost", "primary_focus"),
            state(3, 1, 8, " ", "primary_focus"),
        ],
        [domain(1, "Work", 1)],
        current=(2026, 3),
    )

    focus_by_week = {item["week_id"]: item["focus"] for item in payload["weeks"]}
    assert focus_by_week[3] == {
        "domain_id": 1,
        "name": "Work",
        "archived": False,
        "unavailable": False,
        "name_source": "current_domain",
    }
    assert focus_by_week[2] == {
        "domain_id": 9,
        "name": "Ghost",
        "archived": False,
        "unavailable": True,
        "name_source": "snapshot",
    }
    assert focus_by_week[1] == {
        "domain_id": 8,
        "name": "Unavailable Domain",
        "archived": False,
        "unavailable": True,
        "name_source": "fallback",
    }


def test_last_reviewed_range_uses_persisted_reviews_and_reflects_correction() -> None:
    weeks = [week(index, index * 2, 2) for index in range(1, 14)]
    states = []
    for index in range(1, 14):
        states.extend(
            [
                state(index * 2, index, 1, "Work", "primary_focus"),
                state(index * 2 + 1, index, 2, "Social", "maintained"),
            ]
        )
    payload = aggregate(
        weeks, states, [domain(1, "Work", 1), domain(2, "Social", 2)], reviewed_weeks=12, current=(2026, 26)
    )
    assert payload["summary"]["reviewed_week_count"] == 12
    assert [item["iso_week"] for item in payload["weeks"]] == list(range(26, 2, -2))

    weeks[-1]["sacrificed_domain_id"] = None
    corrected = aggregate(
        weeks, states, [domain(1, "Work", 1), domain(2, "Social", 2)], reviewed_weeks=12, current=(2026, 26)
    )
    assert corrected["summary"]["valid_pair_count"] == 11
    assert corrected["summary"]["focus_without_sacrifice_count"] == 1


def test_api_filters_shape_queries_and_three_query_regression(session: Session, tmp_path: Path) -> None:
    clock = MutableClock(week_clock(2026, 1))
    service = TraectService(session, clock=clock)
    workspace = service.create_workspace("Life")
    work = service.create_domain(workspace.id, "Work")
    social = service.create_domain(workspace.id, "Social")
    service.upsert_week(
        workspace.id,
        2026,
        1,
        sacrificed_domain_id=social.id,
        states=[
            WeekStateInput(
                domain_id=work.id,
                attention=DomainAttention.PRIMARY_FOCUS,
                condition=DomainCondition.STABLE,
            ),
            WeekStateInput(
                domain_id=social.id,
                attention=DomainAttention.MAINTAINED,
                condition=DomainCondition.STABLE,
            ),
        ],
    )
    statements: list[str] = []
    event.listen(session.get_bind(), "before_cursor_execute", lambda *args: statements.append(args[2]))
    payload = TradeoffHistoryService(session).aggregate(
        workspace.id,
        current_iso_week=(2026, 1),
        reviewed_weeks=12,
        focus_domain_id=work.id,
        sacrifice_domain_id=social.id,
    )
    assert len(statements) == 3
    assert payload["selected_focus"]["focus"]["domain_id"] == work.id
    assert payload["selected_sacrifice"]["sacrifice"]["domain_id"] == social.id

    app = build_app(
        f"sqlite:///{tmp_path / 'tradeoffs.db'}",
        clock=MutableClock(datetime(2026, 7, 17, 12, tzinfo=UTC)),
    )
    request(app, "POST", "/workspaces", body=b'{"name":"Life","domains":[{"name":"Work"},{"name":"Social"}]}')
    request(
        app,
        "PUT",
        "/workspaces/1/weeks/2026/29",
        body=b'{"sacrificed_domain_id":2,"states":[{"domain_id":1,"attention":"primary_focus","condition":"stable"},{"domain_id":2,"attention":"maintained","condition":"stable"}]}',
    )
    response = request(
        app,
        "GET",
        "/workspaces/1/history/trade-offs?reviewed_weeks=all&focus_domain_id=1&sacrifice_domain_id=2",
    )
    api_payload = json.loads(response["body"])
    assert response["status"].startswith("200")
    assert api_payload["range"] == {"type": "reviewed_weeks", "value": None}
    assert api_payload["weeks"][0]["status"] == "paired"
    assert api_payload["weeks"][0]["lifecycle"] == "provisional"
    assert api_payload["pairs"][0]["share_of_pairs"] == 1.0
    assert not {"cause", "effect", "impact", "damage", "score"} & set(api_payload)

    assert request(app, "GET", "/workspaces/1/history/trade-offs?reviewed_weeks=10")["status"].startswith("400")
    assert request(app, "GET", "/workspaces/1/history/trade-offs?focus_domain_id=x")["status"].startswith("400")
    assert request(app, "GET", "/workspaces/1/history/trade-offs?focus_domain_id=999")["status"].startswith("404")
