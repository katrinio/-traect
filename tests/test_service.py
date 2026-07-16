from __future__ import annotations

from collections.abc import Callable
from io import BytesIO
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from traect.api.app import build_app
from traect.app.database import create_schema
from traect.app.errors import ValidationError
from traect.app.service import TraectService, WeekStateInput
from traect.domain.enums import WeekDomainMode, WeekDomainStatus


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    create_schema(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False, future=True)
    with factory() as session:
        yield session


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
    assert "Weekly review" in review_response["body"]


def test_current_workspace_route_returns_created_workspace(tmp_path: Path) -> None:
    database = tmp_path / "traect.db"
    app = build_app(f"sqlite:///{database}")

    response = _request(app, "POST", "/workspaces", body=b'{"name":"Life","domains":[{"name":"Work"}]}')
    assert response["status"].startswith("200")

    current_workspace = _request(app, "GET", "/workspaces/current")
    assert current_workspace["status"].startswith("200")
    assert '"name": "Life"' in current_workspace["body"]


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
