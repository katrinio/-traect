from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from io import BytesIO
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from traect.api.app import build_app
from traect.app.database import MIGRATIONS_ROOT, create_schema, migrate_schema
from traect.app.errors import ValidationError
from traect.app.service import TraectService, WeekStateInput
from traect.domain.enums import WeekDomainMode, WeekDomainStatus


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

    updated = service.update_domain(domain.id, name="Focus")

    assert updated.name == "Focus"


def test_week_upsert_is_idempotent(session: Session) -> None:
    service = TraectService(session)
    workspace = service.create_workspace("Life")
    work = service.create_domain(workspace.id, "Work")
    health = service.create_domain(workspace.id, "Health")

    week1 = service.upsert_week(
        workspace.id,
        2026,
        29,
        focus_domain_id=work.id,
        sacrificed_domain_id=health.id,
        sacrifice_reason="Release",
        notes="Tight week",
        states=[
            WeekStateInput(work.id, WeekDomainStatus.GOOD, WeekDomainMode.FOCUS, "Shipped"),
            WeekStateInput(health.id, WeekDomainStatus.WARNING, WeekDomainMode.MAINTAIN, "Limited sleep"),
        ],
    )
    week2 = service.upsert_week(
        workspace.id,
        2026,
        29,
        focus_domain_id=work.id,
        sacrificed_domain_id=health.id,
        sacrifice_reason="Release",
        notes="Tight week",
        states=[
            WeekStateInput(work.id, WeekDomainStatus.GOOD, WeekDomainMode.FOCUS, "Shipped"),
            WeekStateInput(health.id, WeekDomainStatus.WARNING, WeekDomainMode.MAINTAIN, "Limited sleep"),
        ],
    )

    assert week1.id == week2.id
    assert len(week2.domain_states) == 2


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
            WeekStateInput(work.id, WeekDomainStatus.GOOD, WeekDomainMode.FOCUS),
            WeekStateInput(health.id, WeekDomainStatus.GOOD, WeekDomainMode.MAINTAIN),
        ],
    )

    assert week.focus_domain_id == work.id


def test_week_rejects_multiple_primary_focus_domains(session: Session) -> None:
    service = TraectService(session)
    workspace = service.create_workspace("Life")
    work = service.create_domain(workspace.id, "Work")
    health = service.create_domain(workspace.id, "Health")

    with pytest.raises(ValidationError, match="only one primary focus"):
        service.upsert_week(
            workspace.id,
            2026,
            29,
            states=[
                WeekStateInput(work.id, WeekDomainStatus.GOOD, WeekDomainMode.FOCUS),
                WeekStateInput(health.id, WeekDomainStatus.GOOD, WeekDomainMode.FOCUS),
            ],
        )


def test_week_rejects_domain_context_over_300_characters(session: Session) -> None:
    service = TraectService(session)
    workspace = service.create_workspace("Life")
    work = service.create_domain(workspace.id, "Work")

    with pytest.raises(ValidationError, match="300 characters or fewer"):
        service.upsert_week(
            workspace.id,
            2026,
            29,
            states=[WeekStateInput(work.id, WeekDomainStatus.GOOD, WeekDomainMode.MAINTAIN, "x" * 301)],
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
            states=[WeekStateInput(work.id, WeekDomainStatus.GOOD, WeekDomainMode.MAINTAIN)],
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
            states=[WeekStateInput(work.id, WeekDomainStatus.GOOD, WeekDomainMode.FOCUS)],
        )


def test_archived_domains_excluded_from_new_reviews_but_kept_in_history(session: Session) -> None:
    service = TraectService(session)
    workspace = service.create_workspace("Life")
    work = service.create_domain(workspace.id, "Work")
    health = service.create_domain(workspace.id, "Health")

    service.upsert_week(
        workspace.id,
        2026,
        28,
        states=[
            WeekStateInput(work.id, WeekDomainStatus.GOOD, WeekDomainMode.FOCUS),
            WeekStateInput(health.id, WeekDomainStatus.WARNING, WeekDomainMode.MAINTAIN),
        ],
    )
    service.archive_domain(health.id)

    historical = service.list_weeks(workspace.id)
    assert historical[0].domain_states and {state.domain_id for state in historical[0].domain_states} == {
        work.id,
        health.id,
    }

    next_week = service.upsert_week(
        workspace.id,
        2026,
        29,
        states=[WeekStateInput(work.id, WeekDomainStatus.GOOD, WeekDomainMode.FOCUS)],
    )
    assert {state.domain_id for state in next_week.domain_states} == {work.id}


def test_historical_states_remain_available_after_archival(session: Session) -> None:
    service = TraectService(session)
    workspace = service.create_workspace("Life")
    work = service.create_domain(workspace.id, "Work")

    week = service.upsert_week(
        workspace.id,
        2026,
        28,
        states=[WeekStateInput(work.id, WeekDomainStatus.GOOD, WeekDomainMode.FOCUS)],
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
            states=[WeekStateInput(domain_a.id, WeekDomainStatus.GOOD, WeekDomainMode.FOCUS)],
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
                "0004_historical_domain_names"
            )
    finally:
        verification_engine.dispose()


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
        week_names = connection.execute(
            text("SELECT focus_domain_name, sacrificed_domain_name FROM week WHERE id = 1")
        ).one()
        state_names = (
            connection.execute(text("SELECT domain_name FROM week_domain_state ORDER BY domain_id")).scalars().all()
        )
    engine.dispose()
    assert week_names == ("Work", "Health")
    assert state_names == ["Work", "Health"]


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


def test_history_is_reverse_chronological_and_bounded_to_52_weeks(session: Session) -> None:
    service = TraectService(session)
    workspace = service.create_workspace("Life")
    work = service.create_domain(workspace.id, "Work")
    for iso_year, iso_week in [(2025, week) for week in range(1, 53)] + [(2026, 1)]:
        service.upsert_week(
            workspace.id,
            iso_year,
            iso_week,
            states=[WeekStateInput(work.id, WeekDomainStatus.GOOD, WeekDomainMode.MAINTAIN)],
        )

    history = service.list_weeks(workspace.id)

    assert len(history) == 52
    assert (history[0].iso_year, history[0].iso_week) == (2026, 1)
    assert (history[-1].iso_year, history[-1].iso_week) == (2025, 2)


def test_history_api_preserves_saved_domain_names_and_membership(tmp_path: Path) -> None:
    app = build_app(f"sqlite:///{tmp_path / 'traect.db'}")
    _request(app, "POST", "/workspaces", body=b'{"name":"Life","domains":[{"name":"Work"},{"name":"Health"}]}')
    saved = _request(
        app,
        "PUT",
        "/workspaces/1/weeks/2026/28",
        body=(
            b'{"focus_domain_id":1,"sacrificed_domain_id":2,"sacrifice_reason":"Release",'
            b'"states":[{"domain_id":1,"mode":"focus","status":"good"},'
            b'{"domain_id":2,"mode":"ignore","status":"warning"}]}'
        ),
    )
    assert saved["status"].startswith("200")
    _request(app, "PATCH", "/domains/1", body=b'{"name":"Career"}')
    _request(app, "POST", "/domains/2/archive")
    _request(app, "POST", "/workspaces/1/domains", body=b'{"name":"Rest"}')

    response = _request(app, "GET", "/workspaces/1/weeks")
    history = json.loads(response["body"])["items"]

    assert response["status"].startswith("200")
    assert history[0]["focus_domain_name"] == "Work"
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


def _request(
    app: Callable[[dict[str, object], Callable[..., object]], list[bytes]],
    method: str,
    path: str,
    *,
    body: bytes = b"",
) -> dict[str, str]:
    status_line = ""
    headers: list[tuple[str, str]] = []

    def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
        nonlocal status_line, headers
        status_line = status
        headers = response_headers

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": BytesIO(body),
    }
    response_body = b"".join(app(environ, start_response)).decode()
    return {"status": status_line, "body": response_body, "headers": str(headers)}
