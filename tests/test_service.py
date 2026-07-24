from __future__ import annotations

import json
import re
import shutil
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from tests.support import MutableClock, week_clock
from tests.support import wsgi_request as _request
from traect.api.app import build_app, server_address_from_environment
from traect.app.database import MIGRATIONS_ROOT, create_schema, migrate_schema
from traect.app.errors import ConflictError, ValidationError
from traect.app.service import TraectService, WeekStateInput
from traect.domain.enums import DomainAttention, DomainCondition, ReviewLifecycle
from traect.domain.models import Week, WeekDomainState


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


def test_canonical_enums_and_model_fields() -> None:
    assert [value.value for value in DomainAttention] == ["primary_focus", "maintained", "paused"]
    assert [value.value for value in DomainCondition] == ["stable", "at_risk", "critical"]
    assert {"attention", "condition"} <= set(WeekDomainState.__table__.columns.keys())
    assert "mode" not in WeekDomainState.__table__.columns
    assert "status" not in WeekDomainState.__table__.columns
    assert "focus_domain_id" not in Week.__table__.columns
    assert "focus_domain_name" not in Week.__table__.columns


def test_health_endpoint_is_available_without_workspace(tmp_path: Path) -> None:
    app = build_app(f"sqlite:///{tmp_path / 'health.db'}")

    response = _request(app, "GET", "/health")

    assert response["status"].startswith("200")
    assert json.loads(response["body"]) == {"status": "ok"}


def test_health_endpoint_reports_unavailable_database(tmp_path: Path) -> None:
    database_dir = tmp_path / "database"
    database_dir.mkdir()
    app = build_app(f"sqlite:///{database_dir / 'health.db'}")
    shutil.rmtree(database_dir)

    response = _request(app, "GET", "/health")

    assert response["status"].startswith("503")
    assert json.loads(response["body"]) == {"status": "unavailable"}


def test_server_address_uses_environment_and_rejects_invalid_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRAECT_HOST", raising=False)
    monkeypatch.delenv("TRAECT_PORT", raising=False)
    assert server_address_from_environment() == ("127.0.0.1", 8000)

    monkeypatch.setenv("TRAECT_HOST", "0.0.0.0")
    monkeypatch.setenv("TRAECT_PORT", "9876")
    assert server_address_from_environment() == ("0.0.0.0", 9876)

    monkeypatch.setenv("TRAECT_PORT", "invalid")
    with pytest.raises(ValueError, match="TRAECT_PORT"):
        server_address_from_environment()


def test_create_and_list_domains(session: Session) -> None:
    service = TraectService(session)
    workspace = service.create_workspace("Life")
    service.create_domain(workspace.id, "Work")
    service.create_domain(workspace.id, "Health")

    domains = service.list_domains(workspace.id)

    assert [domain.name for domain in domains if domain.archived_at is None] == ["Work", "Health"]


def test_unique_active_domain_name(session: Session) -> None:
    service = TraectService(session)
    workspace = service.create_workspace("Life")
    service.create_domain(workspace.id, "Work")

    with pytest.raises(ValidationError):
        service.create_domain(workspace.id, "Work")


def test_unique_active_domain_name_is_case_insensitive(session: Session) -> None:
    service = TraectService(session)
    workspace = service.create_workspace("Life")
    service.create_domain(workspace.id, "Work")

    with pytest.raises(ValidationError):
        service.create_domain(workspace.id, "work")


def test_create_workspace_with_initial_domains(session: Session) -> None:
    service = TraectService(session)
    workspace = service.create_workspace_with_domains("Life", ["Work", "Health"])

    assert workspace.id is not None
    assert [domain.name for domain in service.list_domains(workspace.id, include_archived=False)] == ["Work", "Health"]


def test_setup_validation_rejects_empty_and_duplicate_domains(session: Session) -> None:
    service = TraectService(session)

    with pytest.raises(ValidationError):
        service.create_workspace_with_domains("Life", ["", "Work"])

    with pytest.raises(ValidationError):
        service.create_workspace_with_domains("Life", ["Work", "work"])


def test_reorder_archive_restore(session: Session) -> None:
    service = TraectService(session)
    workspace = service.create_workspace("Life")
    first = service.create_domain(workspace.id, "Work")
    second = service.create_domain(workspace.id, "Health")

    service.reorder_domains(workspace.id, [second.id, first.id])
    assert [domain.id for domain in service.list_domains(workspace.id, include_archived=False)] == [second.id, first.id]

    service.archive_domain(first.id)
    assert [domain.id for domain in service.list_domains(workspace.id, include_archived=False)] == [second.id]

    restored = service.restore_domain(first.id)
    assert restored.archived_at is None
    assert [domain.id for domain in service.list_domains(workspace.id, include_archived=False)] == [second.id, first.id]


def test_rename_domain(session: Session) -> None:
    service = TraectService(session)
    workspace = service.create_workspace("Life")
    domain = service.create_domain(workspace.id, "Work")

    updated = service.update_domain(domain.id, name="Career")

    assert updated.name == "Career"


def test_week_upsert_is_idempotent(session: Session) -> None:
    service = TraectService(session)
    workspace = service.create_workspace("Life")
    work = service.create_domain(workspace.id, "Work")
    health = service.create_domain(workspace.id, "Health")

    week1 = service.upsert_week(
        workspace.id,
        2026,
        29,
        sacrificed_domain_id=health.id,
        sacrifice_reason="Release",
        notes="Tight week",
        states=[
            WeekStateInput(work.id, DomainCondition.STABLE, DomainAttention.PRIMARY_FOCUS, "Shipped"),
            WeekStateInput(health.id, DomainCondition.AT_RISK, DomainAttention.MAINTAINED, "Limited sleep"),
        ],
    )
    week2 = service.upsert_week(
        workspace.id,
        2026,
        29,
        sacrificed_domain_id=health.id,
        sacrifice_reason="Release",
        notes="Tight week",
        states=[
            WeekStateInput(work.id, DomainCondition.STABLE, DomainAttention.PRIMARY_FOCUS, "Shipped"),
            WeekStateInput(health.id, DomainCondition.AT_RISK, DomainAttention.MAINTAINED, "Limited sleep"),
        ],
    )

    assert week1.id == week2.id
    assert len(week2.domain_states) == 2


def test_service_logs_basic_state_changes(session: Session, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO")
    service = TraectService(session, clock=lambda: datetime(2026, 7, 23, 12, tzinfo=UTC))

    workspace = service.create_workspace("Life")
    work = service.create_domain(workspace.id, "Work")
    health = service.create_domain(workspace.id, "Health")
    service.upsert_week(
        workspace.id,
        2026,
        30,
        sacrificed_domain_id=health.id,
        sacrifice_reason="Release",
        states=[
            WeekStateInput(work.id, DomainCondition.STABLE, DomainAttention.PRIMARY_FOCUS),
            WeekStateInput(health.id, DomainCondition.AT_RISK, DomainAttention.MAINTAINED),
        ],
    )

    messages = [record.getMessage() for record in caplog.records]
    assert any("Workspace created:" in message for message in messages)
    assert any("Domain created:" in message for message in messages)
    assert any("Weekly review saved:" in message for message in messages)


def test_week_derives_a_single_main_focus_from_domain_attention(session: Session) -> None:
    service = TraectService(session)
    workspace = service.create_workspace("Life")
    work = service.create_domain(workspace.id, "Work")
    health = service.create_domain(workspace.id, "Health")

    week = service.upsert_week(
        workspace.id,
        2026,
        29,
        states=[
            WeekStateInput(work.id, DomainCondition.STABLE, DomainAttention.PRIMARY_FOCUS),
            WeekStateInput(health.id, DomainCondition.STABLE, DomainAttention.MAINTAINED),
        ],
    )

    primary_focus = week.primary_focus_state()
    assert primary_focus is not None
    assert primary_focus.domain_id == work.id


def test_week_rejects_multiple_primary_focus_domains(session: Session) -> None:
    service = TraectService(session)
    workspace = service.create_workspace("Life")
    work = service.create_domain(workspace.id, "Work")
    health = service.create_domain(workspace.id, "Health")

    with pytest.raises(ValidationError, match="only one Domain can have Primary focus attention"):
        service.upsert_week(
            workspace.id,
            2026,
            29,
            states=[
                WeekStateInput(work.id, DomainCondition.STABLE, DomainAttention.PRIMARY_FOCUS),
                WeekStateInput(health.id, DomainCondition.STABLE, DomainAttention.PRIMARY_FOCUS),
            ],
        )


def test_week_rejects_duplicate_domain_states(session: Session) -> None:
    service = TraectService(session)
    workspace = service.create_workspace("Life")
    work = service.create_domain(workspace.id, "Work")

    with pytest.raises(ValidationError, match="duplicate Domain states"):
        service.upsert_week(
            workspace.id,
            2026,
            29,
            states=[
                WeekStateInput(work.id, DomainCondition.STABLE, DomainAttention.MAINTAINED),
                WeekStateInput(work.id, DomainCondition.STABLE, DomainAttention.PRIMARY_FOCUS),
            ],
        )


@pytest.mark.parametrize(
    ("attention", "condition", "message"),
    [
        ("unexpected", DomainCondition.STABLE, "invalid attention"),
        (DomainAttention.MAINTAINED, "unexpected", "invalid condition"),
    ],
)
def test_week_rejects_invalid_runtime_enum_values(
    session: Session,
    attention: Any,
    condition: Any,
    message: str,
) -> None:
    service = TraectService(session)
    workspace = service.create_workspace("Life")
    work = service.create_domain(workspace.id, "Work")

    with pytest.raises(ValidationError, match=message):
        service.upsert_week(
            workspace.id,
            2026,
            29,
            states=[
                WeekStateInput(
                    work.id,
                    cast(DomainCondition, condition),
                    cast(DomainAttention, attention),
                )
            ],
        )


def test_week_rejects_sacrifice_missing_from_snapshot(session: Session) -> None:
    service = TraectService(session)
    workspace = service.create_workspace("Life")
    work = service.create_domain(workspace.id, "Work")
    archived = service.create_domain(workspace.id, "Archived")
    service.archive_domain(archived.id)

    with pytest.raises(ValidationError, match="present in the weekly Domain snapshot"):
        service.upsert_week(
            workspace.id,
            2026,
            29,
            sacrificed_domain_id=archived.id,
            states=[WeekStateInput(work.id, DomainCondition.STABLE, DomainAttention.PRIMARY_FOCUS)],
        )


def test_changing_primary_focus_updates_only_attention(session: Session) -> None:
    service = TraectService(session)
    workspace = service.create_workspace("Life")
    work = service.create_domain(workspace.id, "Work")
    health = service.create_domain(workspace.id, "Health")
    service.upsert_week(
        workspace.id,
        2026,
        29,
        states=[
            WeekStateInput(work.id, DomainCondition.STABLE, DomainAttention.MAINTAINED),
            WeekStateInput(health.id, DomainCondition.CRITICAL, DomainAttention.PRIMARY_FOCUS),
        ],
    )

    week = service.upsert_week(
        workspace.id,
        2026,
        29,
        states=[
            WeekStateInput(work.id, DomainCondition.STABLE, DomainAttention.PRIMARY_FOCUS),
            WeekStateInput(health.id, DomainCondition.CRITICAL, DomainAttention.MAINTAINED),
        ],
    )

    states = {state.domain_id: state for state in week.domain_states}
    assert states[work.id].attention == DomainAttention.PRIMARY_FOCUS
    assert states[work.id].condition == DomainCondition.STABLE
    assert states[health.id].attention == DomainAttention.MAINTAINED
    assert states[health.id].condition == DomainCondition.CRITICAL
    primary_focus = week.primary_focus_state()
    assert primary_focus is not None and primary_focus.domain_id == work.id


def test_week_rejects_domain_context_over_300_characters(session: Session) -> None:
    service = TraectService(session)
    workspace = service.create_workspace("Life")
    work = service.create_domain(workspace.id, "Work")

    with pytest.raises(ValidationError, match="300 characters or fewer"):
        service.upsert_week(
            workspace.id,
            2026,
            29,
            states=[WeekStateInput(work.id, DomainCondition.STABLE, DomainAttention.MAINTAINED, "x" * 301)],
        )


def test_week_rejects_what_gave_way_without_a_main_focus(session: Session) -> None:
    service = TraectService(session)
    workspace = service.create_workspace("Life")
    work = service.create_domain(workspace.id, "Work")

    with pytest.raises(ValidationError, match="requires a main focus"):
        service.upsert_week(
            workspace.id,
            2026,
            29,
            sacrificed_domain_id=work.id,
            states=[WeekStateInput(work.id, DomainCondition.STABLE, DomainAttention.MAINTAINED)],
        )


def test_week_rejects_trade_off_reason_without_what_gave_way(session: Session) -> None:
    service = TraectService(session)
    workspace = service.create_workspace("Life")
    work = service.create_domain(workspace.id, "Work")

    with pytest.raises(ValidationError, match="requires a domain that gave way"):
        service.upsert_week(
            workspace.id,
            2026,
            29,
            sacrifice_reason="Release",
            states=[WeekStateInput(work.id, DomainCondition.STABLE, DomainAttention.PRIMARY_FOCUS)],
        )


def test_archived_domains_excluded_from_new_reviews_but_kept_in_history(session: Session) -> None:
    clock = MutableClock(week_clock(2026, 28))
    service = TraectService(session, clock=clock)
    workspace = service.create_workspace("Life")
    work = service.create_domain(workspace.id, "Work")
    health = service.create_domain(workspace.id, "Health")

    service.upsert_week(
        workspace.id,
        2026,
        28,
        states=[
            WeekStateInput(work.id, DomainCondition.STABLE, DomainAttention.PRIMARY_FOCUS),
            WeekStateInput(health.id, DomainCondition.AT_RISK, DomainAttention.MAINTAINED),
        ],
    )
    service.archive_domain(health.id)

    historical = service.list_weeks(workspace.id)
    assert historical[0].domain_states and {state.domain_id for state in historical[0].domain_states} == {
        work.id,
        health.id,
    }

    clock.value = week_clock(2026, 29)
    next_week = service.upsert_week(
        workspace.id,
        2026,
        29,
        states=[WeekStateInput(work.id, DomainCondition.STABLE, DomainAttention.PRIMARY_FOCUS)],
    )
    assert {state.domain_id for state in next_week.domain_states} == {work.id}


def test_historical_states_remain_available_after_archival(session: Session) -> None:
    service = TraectService(session, clock=lambda: week_clock(2026, 28))
    workspace = service.create_workspace("Life")
    work = service.create_domain(workspace.id, "Work")

    week = service.upsert_week(
        workspace.id,
        2026,
        28,
        states=[WeekStateInput(work.id, DomainCondition.STABLE, DomainAttention.PRIMARY_FOCUS)],
    )
    service.archive_domain(work.id)

    assert week.domain_states[0].domain_id == work.id


def test_cross_workspace_relationship_validation(session: Session) -> None:
    service = TraectService(session)
    workspace_a = service.create_workspace("A")
    workspace_b = service.create_workspace("B")
    domain_a = service.create_domain(workspace_a.id, "Work")
    service.create_domain(workspace_b.id, "Health")

    with pytest.raises(ValidationError):
        service.upsert_week(
            workspace_b.id,
            2026,
            29,
            states=[WeekStateInput(domain_a.id, DomainCondition.STABLE, DomainAttention.PRIMARY_FOCUS)],
        )

    with pytest.raises(ValidationError):
        service.reorder_domains(workspace_b.id, [domain_a.id])


def test_empty_database_renders_setup_then_weekly_review(tmp_path: Path) -> None:
    database = tmp_path / "traect.db"
    app = build_app(f"sqlite:///{database}")

    setup_response = _request(app, "GET", "/")
    assert setup_response["status"].startswith("200")
    assert "Workspace setup" in setup_response["body"]

    create_response = _request(
        app,
        "POST",
        "/workspaces",
        body=b'{"name":"Life","domains":[{"name":"Work"},{"name":"Health"}]}',
    )
    assert create_response["status"].startswith("200")

    review_response = _request(app, "GET", "/")
    assert "Current" in review_response["body"]
    assert "Workspace setup" not in review_response["body"]


def test_current_workspace_route_returns_created_workspace(tmp_path: Path) -> None:
    database = tmp_path / "traect.db"
    app = build_app(f"sqlite:///{database}")

    response = _request(app, "POST", "/workspaces", body=b'{"name":"Life","domains":[{"name":"Work"}]}')
    assert response["status"].startswith("200")

    current_workspace = _request(app, "GET", "/workspaces/current")
    assert current_workspace["status"].startswith("200")
    assert '"name": "Life"' in current_workspace["body"]


def test_root_navigation_exposes_current_timeline_and_domains(tmp_path: Path) -> None:
    app = build_app(f"sqlite:///{tmp_path / 'traect.db'}")
    _request(app, "POST", "/workspaces", body=b'{"name":"Life","domains":[{"name":"Work"}]}')

    response = _request(app, "GET", "/")

    assert response["status"].startswith("200")
    assert "Current" in response["body"]
    assert "Timeline" in response["body"]
    assert "Domains" in response["body"]
    assert "Workspace Setup / Domains" not in response["body"]
    assert "Workspace setup" not in response["body"]


def test_frontend_modules_are_served_without_exposing_other_paths(tmp_path: Path) -> None:
    app = build_app(f"sqlite:///{tmp_path / 'traect.db'}")

    module = _request(app, "GET", "/js/api.js")
    traversal = _request(app, "GET", "/js/../app.js")

    assert module["status"].startswith("200")
    assert "text/javascript" in module["headers"]
    assert traversal["status"].startswith("404")


def test_migrated_schema_allows_reusing_an_archived_domain_name(tmp_path: Path) -> None:
    app = build_app(f"sqlite:///{tmp_path / 'traect.db'}")
    workspace = _request(app, "POST", "/workspaces", body=b'{"name":"Life","domains":[{"name":"Work"}]}')
    assert workspace["status"].startswith("200")

    archived = _request(app, "POST", "/domains/1/archive")
    assert archived["status"].startswith("200")

    replacement = _request(app, "POST", "/workspaces/1/domains", body=b'{"name":"Work"}')
    assert replacement["status"].startswith("200")


def test_migrations_adopt_a_legacy_create_all_database(tmp_path: Path) -> None:
    database = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{database}", future=True)
    create_schema(engine)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO workspace (name) VALUES ('Existing workspace')"))
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
    engine.dispose()

    app = build_app(f"sqlite:///{database}")

    response = _request(app, "GET", "/workspaces/current")
    assert response["status"].startswith("200")
    assert "Existing workspace" in response["body"]
    verification_engine = create_engine(f"sqlite:///{database}")
    try:
        with verification_engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
                "0008_minimum_acceptable_level"
            )
    finally:
        verification_engine.dispose()


def test_squashed_migration_creates_the_current_schema(tmp_path: Path) -> None:
    database = tmp_path / "fresh.db"
    engine = create_engine(f"sqlite:///{database}", future=True)
    migrate_schema(engine)

    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        domain_columns = {column["name"] for column in inspect(connection).get_columns("domain")}
        week_columns = {column["name"] for column in inspect(connection).get_columns("week")}
        state_columns = {column["name"] for column in inspect(connection).get_columns("week_domain_state")}
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    engine.dispose()

    assert {"workspace", "domain", "week", "week_domain_state"} <= tables
    assert "minimum_acceptable_level" in domain_columns
    assert "focus_domain_id" not in week_columns
    assert {"attention", "condition", "minimum_acceptable_level_snapshot"} <= state_columns
    assert revision == "0008_minimum_acceptable_level"


def test_squashed_migration_rejects_a_database_on_the_previous_chain(tmp_path: Path) -> None:
    database = tmp_path / "previous-chain.db"
    engine = create_engine(f"sqlite:///{database}", future=True)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES ('0007_historical_week_corrections')")
        )

    with pytest.raises(RuntimeError, match="predates the squashed baseline"):
        migrate_schema(engine)
    engine.dispose()


@pytest.mark.skip(reason="the historical migration chain was intentionally squashed into the baseline")
def test_historical_name_migration_backfills_existing_reviews(tmp_path: Path) -> None:
    database = tmp_path / "existing.db"
    engine = create_engine(f"sqlite:///{database}", future=True)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_ROOT))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0003_active_domain_names")
        connection.execute(text("INSERT INTO workspace (id, name) VALUES (1, 'Life')"))
        connection.execute(
            text(
                "INSERT INTO domain (id, workspace_id, name, sort_order) VALUES (1, 1, 'Work', 0), (2, 1, 'Health', 1)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO week "
                "(id, workspace_id, iso_year, iso_week, starts_on, ends_on, focus_domain_id, sacrificed_domain_id) "
                "VALUES (1, 1, 2026, 28, '2026-07-06', '2026-07-12', 1, 2)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO week_domain_state (week_id, domain_id, status, mode) "
                "VALUES (1, 1, 'good', 'focus'), (1, 2, 'warning', 'ignore')"
            )
        )

    migrate_schema(engine)

    with engine.connect() as connection:
        sacrificed_name = connection.execute(text("SELECT sacrificed_domain_name FROM week WHERE id = 1")).scalar_one()
        state_names = (
            connection.execute(text("SELECT domain_name FROM week_domain_state ORDER BY domain_id")).scalars().all()
        )
        primary_focus_id = connection.execute(
            text("SELECT domain_id FROM week_domain_state WHERE attention = 'primary_focus'")
        ).scalar_one()
        week_columns = {column["name"] for column in inspect(connection).get_columns("week")}
    engine.dispose()
    assert sacrificed_name == "Health"
    assert state_names == ["Work", "Health"]
    assert primary_focus_id == 1
    assert "focus_domain_id" not in week_columns
    assert "focus_domain_name" not in week_columns


def _focus_migration_database(
    tmp_path: Path,
    *,
    focus_domain_id: int | None,
    attentions: dict[int, str],
) -> tuple[Engine, Config]:
    database = tmp_path / "focus-source.db"
    engine = create_engine(f"sqlite:///{database}", future=True)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_ROOT))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0005_unify_product_terminology")
        connection.execute(text("INSERT INTO workspace (id, name) VALUES (1, 'Life')"))
        connection.execute(
            text(
                "INSERT INTO domain (id, workspace_id, name, sort_order, archived_at) VALUES "
                "(1, 1, 'Work', 0, '2026-07-10'), (2, 1, 'Health', 1, NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO week "
                "(id, workspace_id, iso_year, iso_week, starts_on, ends_on, focus_domain_id, focus_domain_name) "
                "VALUES (1, 1, 2026, 28, '2026-07-06', '2026-07-12', :focus_domain_id, :focus_name)"
            ),
            {
                "focus_domain_id": focus_domain_id,
                "focus_name": "Work" if focus_domain_id == 1 else ("Health" if focus_domain_id == 2 else None),
            },
        )
        for domain_id, attention in attentions.items():
            connection.execute(
                text(
                    "INSERT INTO week_domain_state "
                    "(week_id, domain_id, domain_name, attention, condition) "
                    "VALUES (1, :domain_id, :domain_name, :attention, 'stable')"
                ),
                {
                    "domain_id": domain_id,
                    "domain_name": "Work" if domain_id == 1 else "Health",
                    "attention": attention,
                },
            )
    return engine, config


@pytest.mark.parametrize(
    ("focus_domain_id", "attentions", "expected"),
    [
        (1, {1: "primary_focus", 2: "maintained"}, [(1, "primary_focus"), (2, "maintained")]),
        (1, {1: "maintained", 2: "paused"}, [(1, "primary_focus"), (2, "paused")]),
        (1, {1: "maintained", 2: "primary_focus"}, [(1, "maintained"), (2, "primary_focus")]),
        (None, {1: "maintained", 2: "paused"}, [(1, "maintained"), (2, "paused")]),
    ],
)
@pytest.mark.skip(reason="the historical migration chain was intentionally squashed into the baseline")
def test_focus_source_migration_preserves_or_repairs_unambiguous_history(
    tmp_path: Path,
    focus_domain_id: int | None,
    attentions: dict[int, str],
    expected: list[tuple[int, str]],
) -> None:
    engine, config = _focus_migration_database(
        tmp_path,
        focus_domain_id=focus_domain_id,
        attentions=attentions,
    )
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")

    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT domain_id, attention FROM week_domain_state WHERE week_id = 1 ORDER BY domain_id")
        ).all()
        week_columns = {column["name"] for column in inspect(connection).get_columns("week")}
        state_indexes = {index["name"] for index in inspect(connection).get_indexes("week_domain_state")}
        archived_at = connection.execute(text("SELECT archived_at FROM domain WHERE id = 1")).scalar_one()
    engine.dispose()
    assert rows == expected
    assert {"focus_domain_id", "focus_domain_name"}.isdisjoint(week_columns)
    assert "uq_week_domain_state_primary_focus" in state_indexes
    assert archived_at is not None


@pytest.mark.parametrize(
    ("attentions", "expected_error"),
    [
        ({2: "maintained"}, "focus_domain_id has no WeekDomainState in weeks [1]"),
        ({1: "primary_focus", 2: "primary_focus"}, "multiple Primary focus states in weeks [1]"),
    ],
)
@pytest.mark.skip(reason="the historical migration chain was intentionally squashed into the baseline")
def test_focus_source_migration_reports_ambiguous_history(
    tmp_path: Path,
    attentions: dict[int, str],
    expected_error: str,
) -> None:
    engine, config = _focus_migration_database(tmp_path, focus_domain_id=1, attentions=attentions)
    connection = engine.connect()
    config.attributes["connection"] = connection
    with pytest.raises(RuntimeError, match=re.escape(expected_error)):
        command.upgrade(config, "head")
    connection.close()

    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        week_columns = {column["name"] for column in inspect(connection).get_columns("week")}
    engine.dispose()
    assert revision == "0005_unify_product_terminology"
    assert {"focus_domain_id", "focus_domain_name"} <= week_columns


@pytest.mark.skip(reason="the historical migration chain was intentionally squashed into the baseline")
def test_focus_source_migration_downgrade_derives_legacy_fields(tmp_path: Path) -> None:
    engine, config = _focus_migration_database(
        tmp_path,
        focus_domain_id=2,
        attentions={1: "primary_focus", 2: "maintained"},
    )
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        command.downgrade(config, "0005_unify_product_terminology")
    with engine.connect() as connection:
        restored = connection.execute(text("SELECT focus_domain_id, focus_domain_name FROM week WHERE id = 1")).one()
    engine.dispose()
    assert restored == (1, "Work")


@pytest.mark.skip(reason="the historical migration chain was intentionally squashed into the baseline")
def test_terminology_migration_preserves_history_and_supports_downgrade(tmp_path: Path) -> None:
    database = tmp_path / "terminology.db"
    engine = create_engine(f"sqlite:///{database}", future=True)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_ROOT))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0004_historical_domain_names")
        connection.execute(text("INSERT INTO workspace (id, name) VALUES (1, 'Life')"))
        connection.execute(
            text(
                "INSERT INTO domain (id, workspace_id, name, sort_order, archived_at) VALUES "
                "(1, 1, 'Work', 0, NULL), (2, 1, 'Health', 1, '2026-07-10'), "
                "(3, 1, 'Rest', 2, NULL), (4, 1, 'Family', 3, NULL), "
                "(5, 1, 'Sport', 4, NULL), (6, 1, 'Study', 5, NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO week (id, workspace_id, iso_year, iso_week, starts_on, ends_on) "
                "VALUES (1, 1, 2026, 28, '2026-07-06', '2026-07-12')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO week_domain_state (week_id, domain_id, domain_name, mode, status) VALUES "
                "(1, 1, 'Work', 'FOCUS', 'GOOD'), "
                "(1, 2, 'Health', 'maintain', 'warning'), "
                "(1, 3, 'Rest', 'IGNORE', 'CRITICAL'), "
                "(1, 4, 'Family', 'primary_focus', 'stable'), "
                "(1, 5, 'Sport', 'maintained', 'at_risk'), "
                "(1, 6, 'Study', 'paused', 'critical')"
            )
        )
        command.upgrade(config, "0005_unify_product_terminology")

    with engine.connect() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("week_domain_state")}
        rows = connection.execute(
            text("SELECT domain_id, attention, condition FROM week_domain_state WHERE week_id = 1 ORDER BY domain_id")
        ).all()
        archived_at = connection.execute(text("SELECT archived_at FROM domain WHERE id = 2")).scalar_one()
    assert {"attention", "condition"} <= columns
    assert "mode" not in columns and "status" not in columns
    assert rows == [
        (1, "primary_focus", "stable"),
        (2, "maintained", "at_risk"),
        (3, "paused", "critical"),
        (4, "primary_focus", "stable"),
        (5, "maintained", "at_risk"),
        (6, "paused", "critical"),
    ]
    assert archived_at is not None

    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0004_historical_domain_names")
    with engine.connect() as connection:
        downgraded = connection.execute(
            text("SELECT domain_id, mode, status FROM week_domain_state WHERE week_id = 1 ORDER BY domain_id")
        ).all()
    engine.dispose()
    assert downgraded == [
        (1, "focus", "good"),
        (2, "maintain", "warning"),
        (3, "ignore", "critical"),
        (4, "focus", "good"),
        (5, "maintain", "warning"),
        (6, "ignore", "critical"),
    ]


@pytest.mark.skip(reason="the historical migration chain was intentionally squashed into the baseline")
def test_terminology_migration_rejects_unknown_values_before_changing_schema(tmp_path: Path) -> None:
    database = tmp_path / "unknown-terminology.db"
    engine = create_engine(f"sqlite:///{database}", future=True)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_ROOT))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0004_historical_domain_names")
        connection.execute(text("INSERT INTO workspace (id, name) VALUES (1, 'Life')"))
        connection.execute(text("INSERT INTO domain (id, workspace_id, name, sort_order) VALUES (1, 1, 'Work', 0)"))
        connection.execute(
            text(
                "INSERT INTO week (id, workspace_id, iso_year, iso_week, starts_on, ends_on) "
                "VALUES (1, 1, 2026, 28, '2026-07-06', '2026-07-12')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO week_domain_state (week_id, domain_id, domain_name, mode, status) "
                "VALUES (1, 1, 'Work', 'unexpected', 'good')"
            )
        )

    connection = engine.connect()
    config.attributes["connection"] = connection
    with pytest.raises(RuntimeError, match="unknown values: 'unexpected'"):
        command.upgrade(config, "head")
    connection.close()

    with engine.connect() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("week_domain_state")}
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    engine.dispose()
    assert {"mode", "status"} <= columns
    assert "attention" not in columns and "condition" not in columns
    assert revision == "0004_historical_domain_names"


@pytest.mark.parametrize(
    ("body", "expected_error"),
    [
        (b"not json", "request body must contain valid JSON"),
        (b"[]", "request body must be a JSON object"),
        (b"{}", "missing required field: name"),
    ],
)
def test_invalid_workspace_requests_return_json_errors(tmp_path: Path, body: bytes, expected_error: str) -> None:
    app = build_app(f"sqlite:///{tmp_path / 'traect.db'}")

    response = _request(app, "POST", "/workspaces", body=body)

    assert response["status"].startswith("400")
    assert expected_error in response["body"]
    assert "application/json" in response["headers"]


def test_invalid_week_values_return_json_error(tmp_path: Path) -> None:
    app = build_app(f"sqlite:///{tmp_path / 'traect.db'}")
    _request(app, "POST", "/workspaces", body=b'{"name":"Life","domains":[{"name":"Work"}]}')

    response = _request(app, "PUT", "/workspaces/1/weeks/2026/99", body=b"{}")

    assert response["status"].startswith("400")
    assert "error" in response["body"]


@pytest.mark.parametrize(
    ("attention", "condition"),
    [
        ("primary_focus", "stable"),
        ("maintained", "at_risk"),
        ("paused", "critical"),
    ],
)
def test_canonical_week_state_values_round_trip(tmp_path: Path, attention: str, condition: str) -> None:
    app = build_app(f"sqlite:///{tmp_path / 'traect.db'}")
    _request(app, "POST", "/workspaces", body=b'{"name":"Life","domains":[{"name":"Work"}]}')
    body = (
        b"{"
        + b'"states":[{"domain_id":1,"attention":"'
        + attention.encode()
        + b'","condition":"'
        + condition.encode()
        + b'"}]}'
    )

    response = _request(app, "PUT", "/workspaces/1/weeks/2026/29", body=body)
    payload = json.loads(response["body"])
    state = payload["states"][0]

    assert response["status"].startswith("200")
    assert state == {
        "domain_id": 1,
        "domain_name": "Work",
        "attention": attention,
        "condition": condition,
        "minimum_acceptable_level": None,
        "comment": None,
    }
    assert "mode" not in state
    assert "status" not in state
    assert payload["main_focus"] == ({"domain_id": 1, "name": "Work"} if attention == "primary_focus" else None)
    assert "focus_domain_id" not in payload
    assert "focus_domain_name" not in payload


def test_legacy_week_state_fields_are_not_accepted(tmp_path: Path) -> None:
    app = build_app(f"sqlite:///{tmp_path / 'traect.db'}")
    _request(app, "POST", "/workspaces", body=b'{"name":"Life","domains":[{"name":"Work"}]}')

    response = _request(
        app,
        "PUT",
        "/workspaces/1/weeks/2026/29",
        body=b'{"states":[{"domain_id":1,"mode":"maintain","status":"good"}]}',
    )

    assert response["status"].startswith("400")
    assert "missing required field: condition" in response["body"]


def test_duplicate_focus_request_field_is_not_accepted(tmp_path: Path) -> None:
    app = build_app(f"sqlite:///{tmp_path / 'traect.db'}")
    _request(app, "POST", "/workspaces", body=b'{"name":"Life","domains":[{"name":"Work"}]}')

    response = _request(
        app,
        "PUT",
        "/workspaces/1/weeks/2026/29",
        body=(b'{"focus_domain_id":1,"states":[{"domain_id":1,"attention":"primary_focus","condition":"stable"}]}'),
    )

    assert response["status"].startswith("400")
    assert "Primary focus must be represented by Domain attention" in response["body"]


def test_history_is_reverse_chronological_and_bounded_to_52_weeks(session: Session) -> None:
    clock = MutableClock(week_clock(2025, 1))
    service = TraectService(session, clock=clock)
    workspace = service.create_workspace("Life")
    work = service.create_domain(workspace.id, "Work")
    for iso_year, iso_week in [(2025, week) for week in range(1, 53)] + [(2026, 1)]:
        clock.value = week_clock(iso_year, iso_week)
        service.upsert_week(
            workspace.id,
            iso_year,
            iso_week,
            states=[WeekStateInput(work.id, DomainCondition.STABLE, DomainAttention.MAINTAINED)],
        )

    history = service.list_weeks(workspace.id)

    assert len(history) == 52
    assert (history[0].iso_year, history[0].iso_week) == (2026, 1)
    assert (history[-1].iso_year, history[-1].iso_week) == (2025, 2)


def test_history_api_preserves_saved_domain_names_and_membership(tmp_path: Path) -> None:
    clock = MutableClock(week_clock(2026, 28))
    app = build_app(f"sqlite:///{tmp_path / 'traect.db'}", clock=clock)
    _request(app, "POST", "/workspaces", body=b'{"name":"Life","domains":[{"name":"Work"},{"name":"Health"}]}')
    saved = _request(
        app,
        "PUT",
        "/workspaces/1/weeks/2026/28",
        body=(
            b'{"sacrificed_domain_id":2,"sacrifice_reason":"Release",'
            b'"states":[{"domain_id":1,"attention":"primary_focus","condition":"stable"},'
            b'{"domain_id":2,"attention":"paused","condition":"at_risk"}]}'
        ),
    )
    assert saved["status"].startswith("200")
    clock.value = week_clock(2026, 29)
    _request(app, "PATCH", "/domains/1", body=b'{"name":"Career"}')
    _request(app, "POST", "/domains/2/archive")
    _request(app, "POST", "/workspaces/1/domains", body=b'{"name":"Rest"}')

    response = _request(app, "GET", "/workspaces/1/weeks")
    history = json.loads(response["body"])["items"]

    assert response["status"].startswith("200")
    assert history[0]["main_focus"] == {"domain_id": 1, "name": "Work"}
    assert history[0]["sacrificed_domain_name"] == "Health"
    assert [item["domain_name"] for item in history[0]["states"]] == ["Work", "Health"]
    assert all(item["domain_name"] != "Rest" for item in history[0]["states"])


def test_viewing_empty_history_does_not_create_a_review(tmp_path: Path) -> None:
    app = build_app(f"sqlite:///{tmp_path / 'traect.db'}")
    _request(app, "POST", "/workspaces", body=b'{"name":"Life","domains":[{"name":"Work"}]}')

    first = json.loads(_request(app, "GET", "/workspaces/1/weeks")["body"])
    second = json.loads(_request(app, "GET", "/workspaces/1/weeks")["body"])

    assert first == {"items": []}
    assert second == {"items": []}


def test_current_previous_and_future_week_lifecycle(session: Session) -> None:
    service = TraectService(session, clock=lambda: week_clock(2026, 29))

    assert service.lifecycle_for_week(2026, 29) == ReviewLifecycle.PROVISIONAL
    assert service.lifecycle_for_week(2026, 28) == ReviewLifecycle.FINAL
    with pytest.raises(ValidationError, match="future week"):
        service.lifecycle_for_week(2026, 30)


def test_provisional_review_updates_idempotently_then_becomes_final(session: Session) -> None:
    clock = MutableClock(week_clock(2026, 29))
    service = TraectService(session, clock=clock)
    workspace = service.create_workspace("Life")
    work = service.create_domain(workspace.id, "Work")
    states = [WeekStateInput(work.id, DomainCondition.STABLE, DomainAttention.MAINTAINED)]

    first = service.upsert_week(workspace.id, 2026, 29, notes="First", states=states)
    second = service.upsert_week(workspace.id, 2026, 29, notes="Updated", states=states)

    assert first.id == second.id
    assert second.notes == "Updated"
    assert service.review_lifecycle(second) == ReviewLifecycle.PROVISIONAL
    with pytest.raises(ValidationError, match="future week"):
        service.upsert_week(workspace.id, 2026, 30, states=states)

    clock.value = week_clock(2026, 30)
    assert service.review_lifecycle(second) == ReviewLifecycle.FINAL
    with pytest.raises(ConflictError, match="final and can no longer be edited"):
        service.upsert_week(workspace.id, 2026, 29, notes="Too late", states=states)
    assert second.notes == "Updated"


def test_lifecycle_api_is_computed_and_does_not_create_missing_reviews(tmp_path: Path) -> None:
    clock = MutableClock(week_clock(2026, 29))
    app = build_app(f"sqlite:///{tmp_path / 'lifecycle.db'}", clock=clock)
    _request(app, "POST", "/workspaces", body=b'{"name":"Life","domains":[{"name":"Work"}]}')

    empty_context = json.loads(_request(app, "GET", "/workspaces/1/weeks/current-context")["body"])
    assert empty_context == {
        "iso_year": 2026,
        "iso_week": 29,
        "lifecycle": "provisional",
        "editable": True,
        "review_domains": [{"domain_id": 1, "name": "Work", "minimum_acceptable_level": None}],
        "review": None,
    }
    assert json.loads(_request(app, "GET", "/workspaces/1/weeks")["body"]) == {"items": []}

    created = _request(
        app,
        "PUT",
        "/workspaces/1/weeks/2026/29",
        body=(b'{"lifecycle":"final","states":[{"domain_id":1,"attention":"maintained","condition":"stable"}]}'),
    )
    provisional = json.loads(created["body"])
    assert provisional["lifecycle"] == "provisional"
    assert provisional["editable"] is True

    clock.value = week_clock(2026, 30)
    history = json.loads(_request(app, "GET", "/workspaces/1/weeks")["body"])["items"]
    assert len(history) == 1
    assert history[0]["lifecycle"] == "final"
    assert history[0]["editable"] is False
    rejected = _request(
        app,
        "PUT",
        "/workspaces/1/weeks/2026/29",
        body=b'{"states":[{"domain_id":1,"attention":"maintained","condition":"stable"}]}',
    )
    assert rejected["status"].startswith("409")
    assert "final and can no longer be edited" in rejected["body"]

    next_context = json.loads(_request(app, "GET", "/workspaces/1/weeks/current-context")["body"])
    assert next_context["review"] is None
    assert len(json.loads(_request(app, "GET", "/workspaces/1/weeks")["body"])["items"]) == 1


def test_iso_year_and_week_53_boundaries(session: Session) -> None:
    new_year_service = TraectService(session, clock=lambda: datetime(2025, 12, 29, 12, tzinfo=UTC))
    assert new_year_service.current_iso_week() == (2026, 1)
    assert new_year_service.lifecycle_for_week(2025, 52) == ReviewLifecycle.FINAL
    assert new_year_service.lifecycle_for_week(2026, 1) == ReviewLifecycle.PROVISIONAL

    after_week_53 = TraectService(session, clock=lambda: datetime(2021, 1, 4, 12, tzinfo=UTC))
    assert after_week_53.current_iso_week() == (2021, 1)
    assert after_week_53.lifecycle_for_week(2020, 53) == ReviewLifecycle.FINAL


def test_timezone_controls_sunday_monday_week_boundary(session: Session) -> None:
    boundary = datetime(2026, 7, 12, 23, 30, tzinfo=UTC)

    utc_service = TraectService(session, clock=lambda: boundary)
    belgrade_service = TraectService(session, clock=lambda: boundary, timezone=ZoneInfo("Europe/Belgrade"))

    assert utc_service.current_iso_week() == (2026, 28)
    assert belgrade_service.current_iso_week() == (2026, 29)


def test_viewing_lifecycle_does_not_mutate_review(session: Session) -> None:
    service = TraectService(session, clock=lambda: week_clock(2026, 29))
    workspace = service.create_workspace("Life")
    work = service.create_domain(workspace.id, "Work")
    week = service.upsert_week(
        workspace.id,
        2026,
        29,
        states=[WeekStateInput(work.id, DomainCondition.STABLE, DomainAttention.MAINTAINED)],
    )
    original_updated_at = week.updated_at

    assert service.review_lifecycle(service.get_current_week(workspace.id)) == ReviewLifecycle.PROVISIONAL
    assert len(service.list_weeks(workspace.id)) == 1
    assert week.updated_at == original_updated_at
