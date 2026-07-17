from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from tests.support import MutableClock, week_clock
from tests.support import wsgi_request as request
from traect.api.app import build_app
from traect.app.database import create_schema
from traect.app.errors import ConflictError, ValidationError
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


def test_domain_service_normalizes_and_validates_minimum_acceptable_level(session: Session) -> None:
    service = TraectService(session)
    workspace = service.create_workspace("Life")

    unset = service.create_domain(workspace.id, "Work")
    configured = service.create_domain(
        workspace.id,
        "Health",
        minimum_acceptable_level="  Move gently twice a week.\nKeep appointments manageable.  ",
    )

    assert unset.minimum_acceptable_level is None
    assert configured.minimum_acceptable_level == "Move gently twice a week.\nKeep appointments manageable."

    service.update_domain(configured.id, name="Health and care")
    assert configured.minimum_acceptable_level == "Move gently twice a week.\nKeep appointments manageable."
    service.update_domain(configured.id, minimum_acceptable_level="   ")
    assert configured.minimum_acceptable_level is None
    service.update_domain(configured.id, minimum_acceptable_level="Rest is acceptable.")
    service.update_domain(configured.id, minimum_acceptable_level=None)
    assert configured.minimum_acceptable_level is None

    with pytest.raises(ValidationError, match="500 characters or fewer"):
        service.update_domain(configured.id, minimum_acceptable_level="x" * 501)
    with pytest.raises(ValidationError, match="string or null"):
        service.update_domain(configured.id, minimum_acceptable_level=42)


def test_domain_api_is_backward_compatible_and_exposes_optional_field(tmp_path: Path) -> None:
    app = build_app(f"sqlite:///{tmp_path / 'domains.db'}")
    request(app, "POST", "/workspaces", body=b'{"name":"Life","domains":[{"name":"Work"}]}')

    existing = json.loads(request(app, "GET", "/workspaces/1/domains")["body"])["items"][0]
    created = json.loads(
        request(
            app,
            "POST",
            "/workspaces/1/domains",
            body=(
                b'{"name":"Health","minimum_acceptable_level":'
                b'"  Care remains manageable.\\nAppointments stay visible.  "}'
            ),
        )["body"]
    )

    assert existing["minimum_acceptable_level"] is None
    assert created["minimum_acceptable_level"] == "Care remains manageable.\nAppointments stay visible."

    renamed = json.loads(request(app, "PATCH", "/domains/2", body=b'{"name":"Care"}')["body"])
    assert renamed["minimum_acceptable_level"] == created["minimum_acceptable_level"]
    cleared = json.loads(request(app, "PATCH", "/domains/2", body=b'{"minimum_acceptable_level":null}')["body"])
    assert cleared["minimum_acceptable_level"] is None


def test_workspace_creation_accepts_but_does_not_require_domain_context(tmp_path: Path) -> None:
    app = build_app(f"sqlite:///{tmp_path / 'workspace.db'}")
    response = request(
        app,
        "POST",
        "/workspaces",
        body=(
            b'{"name":"Life","domains":['
            b'{"name":"Work"},'
            b'{"name":"Home","minimum_acceptable_level":"The home remains usable."}'
            b"]}"
        ),
    )
    domains = json.loads(request(app, "GET", "/workspaces/1/domains")["body"])["items"]

    assert response["status"].startswith("200")
    assert [domain["minimum_acceptable_level"] for domain in domains] == [None, "The home remains usable."]


def test_provisional_save_copies_and_refreshes_snapshot_without_evaluating_condition(session: Session) -> None:
    clock = MutableClock(week_clock(2026, 29))
    service = TraectService(session, clock=clock)
    workspace = service.create_workspace("Life")
    health = service.create_domain(
        workspace.id,
        "Health",
        minimum_acceptable_level="Keep essential care manageable.",
    )

    week = service.upsert_week(
        workspace.id,
        2026,
        29,
        states=[WeekStateInput(health.id, DomainCondition.CRITICAL, DomainAttention.MAINTAINED)],
    )
    assert week.domain_states[0].minimum_acceptable_level_snapshot == "Keep essential care manageable."
    assert week.domain_states[0].condition == DomainCondition.CRITICAL

    service.update_domain(health.id, minimum_acceptable_level="Keep appointments and medication visible.")
    refreshed = service.upsert_week(
        workspace.id,
        2026,
        29,
        states=[WeekStateInput(health.id, DomainCondition.STABLE, DomainAttention.MAINTAINED)],
    )
    assert refreshed.domain_states[0].minimum_acceptable_level_snapshot == ("Keep appointments and medication visible.")
    assert refreshed.domain_states[0].condition == DomainCondition.STABLE


def test_final_and_archived_history_preserves_snapshot(session: Session) -> None:
    clock = MutableClock(week_clock(2026, 28))
    service = TraectService(session, clock=clock)
    workspace = service.create_workspace("Life")
    home = service.create_domain(workspace.id, "Home", minimum_acceptable_level="The home remains usable.")
    week = service.upsert_week(
        workspace.id,
        2026,
        28,
        states=[WeekStateInput(home.id, DomainCondition.AT_RISK, DomainAttention.MAINTAINED)],
    )

    clock.value = week_clock(2026, 29)
    service.update_domain(home.id, minimum_acceptable_level="A newer definition.")
    service.archive_domain(home.id)

    with pytest.raises(ConflictError, match="final"):
        service.upsert_week(
            workspace.id,
            2026,
            28,
            states=[WeekStateInput(home.id, DomainCondition.STABLE, DomainAttention.MAINTAINED)],
        )
    historical = service.list_weeks(workspace.id)[0]
    assert historical.id == week.id
    assert historical.domain_states[0].minimum_acceptable_level_snapshot == "The home remains usable."
    assert historical.domain_states[0].condition == DomainCondition.AT_RISK


def test_current_review_context_uses_current_configuration_until_next_save(tmp_path: Path) -> None:
    clock = MutableClock(week_clock(2026, 29))
    app = build_app(f"sqlite:///{tmp_path / 'context.db'}", clock=clock)
    request(
        app,
        "POST",
        "/workspaces",
        body=(b'{"name":"Life","domains":[{"name":"Health","minimum_acceptable_level":"Original context."}]}'),
    )

    unsaved = json.loads(request(app, "GET", "/workspaces/1/weeks/current-context")["body"])
    assert unsaved["review"] is None
    assert unsaved["review_domains"] == [
        {"domain_id": 1, "name": "Health", "minimum_acceptable_level": "Original context."}
    ]

    request(
        app,
        "PUT",
        "/workspaces/1/weeks/2026/29",
        body=b'{"states":[{"domain_id":1,"attention":"maintained","condition":"at_risk"}]}',
    )
    request(
        app,
        "PATCH",
        "/domains/1",
        body=b'{"minimum_acceptable_level":"Changed after the saved review."}',
    )
    saved = json.loads(request(app, "GET", "/workspaces/1/weeks/current-context")["body"])

    assert saved["review_domains"][0]["minimum_acceptable_level"] == "Changed after the saved review."
    assert saved["review"]["states"][0]["minimum_acceptable_level"] == "Original context."
