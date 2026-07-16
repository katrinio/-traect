from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

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
