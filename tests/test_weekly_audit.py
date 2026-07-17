from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text

from traect.app.database import create_schema
from traect.app.weekly_audit import (
    AuditScope,
    AuditSeverity,
    RepairStatus,
    WeeklyIssueCode,
    audit_weekly_data,
)
from traect.cli import main

AUDIT_CLOCK = lambda: datetime(2026, 7, 15, 12, tzinfo=UTC)


@pytest.fixture
def legacy_engine() -> Iterator[Engine]:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE workspace (id INTEGER PRIMARY KEY, name VARCHAR(120));"))
        connection.execute(
            text(
                "CREATE TABLE domain ("
                "id INTEGER PRIMARY KEY, workspace_id INTEGER, name VARCHAR(120), archived_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE week ("
                "id INTEGER PRIMARY KEY, workspace_id INTEGER, iso_year INTEGER, iso_week INTEGER, "
                "starts_on DATE, ends_on DATE, focus_domain_id INTEGER, focus_domain_name VARCHAR(120), "
                "sacrificed_domain_id INTEGER, sacrificed_domain_name VARCHAR(120), "
                "sacrifice_reason VARCHAR(240), notes TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE week_domain_state ("
                "id INTEGER PRIMARY KEY, week_id INTEGER, domain_id INTEGER, domain_name VARCHAR(120), "
                "attention VARCHAR(32), condition VARCHAR(32), comment TEXT)"
            )
        )
        connection.execute(text("INSERT INTO workspace (id, name) VALUES (1, 'Life'), (2, 'Other')"))
        connection.execute(
            text(
                "INSERT INTO domain (id, workspace_id, name, archived_at) VALUES "
                "(1, 1, 'Work', NULL), (2, 1, 'Health', NULL), "
                "(3, 1, 'Archived', '2026-07-01'), (4, 2, 'Other', NULL)"
            )
        )
    try:
        yield engine
    finally:
        engine.dispose()


def _insert_week(
    engine: Engine,
    *,
    week_id: int = 1,
    workspace_id: int = 1,
    iso_year: int = 2026,
    iso_week: int = 29,
    starts_on: str = "2026-07-13",
    ends_on: str = "2026-07-19",
    focus_domain_id: int | None = None,
    sacrificed_domain_id: int | None = None,
    sacrifice_reason: str | None = None,
    notes: str | None = None,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO week ("
                "id, workspace_id, iso_year, iso_week, starts_on, ends_on, "
                "focus_domain_id, focus_domain_name, sacrificed_domain_id, sacrificed_domain_name, "
                "sacrifice_reason, notes) VALUES ("
                ":id, :workspace_id, :iso_year, :iso_week, :starts_on, :ends_on, "
                ":focus_domain_id, :focus_domain_name, :sacrificed_domain_id, :sacrificed_domain_name, "
                ":sacrifice_reason, :notes)"
            ),
            {
                "id": week_id,
                "workspace_id": workspace_id,
                "iso_year": iso_year,
                "iso_week": iso_week,
                "starts_on": starts_on,
                "ends_on": ends_on,
                "focus_domain_id": focus_domain_id,
                "focus_domain_name": _domain_name(focus_domain_id),
                "sacrificed_domain_id": sacrificed_domain_id,
                "sacrificed_domain_name": _domain_name(sacrificed_domain_id),
                "sacrifice_reason": sacrifice_reason,
                "notes": notes,
            },
        )


def _insert_state(
    engine: Engine,
    state_id: int,
    domain_id: int | None,
    *,
    week_id: int = 1,
    attention: str | None = "maintained",
    condition: str | None = "stable",
    comment: str | None = None,
    domain_name: str | None = None,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO week_domain_state "
                "(id, week_id, domain_id, domain_name, attention, condition, comment) "
                "VALUES (:id, :week_id, :domain_id, :domain_name, :attention, :condition, :comment)"
            ),
            {
                "id": state_id,
                "week_id": week_id,
                "domain_id": domain_id,
                "domain_name": domain_name if domain_name is not None else _domain_name(domain_id),
                "attention": attention,
                "condition": condition,
                "comment": comment,
            },
        )


def _domain_name(domain_id: int | None) -> str | None:
    if domain_id is None:
        return None
    return {1: "Work", 2: "Health", 3: "Archived", 4: "Other"}.get(domain_id)


def _codes(engine: Engine) -> list[WeeklyIssueCode]:
    return [issue.code for issue in audit_weekly_data(engine, clock=AUDIT_CLOCK).issues]


def test_valid_week_and_archived_domain_have_no_findings(legacy_engine: Engine) -> None:
    _insert_week(legacy_engine, focus_domain_id=1, sacrificed_domain_id=3, sacrifice_reason="Release")
    _insert_state(legacy_engine, 1, 1, attention="primary_focus")
    _insert_state(legacy_engine, 2, 3, attention="paused", condition="at_risk")

    report = audit_weekly_data(legacy_engine, clock=AUDIT_CLOCK)

    assert report.total_weeks_inspected == 1
    assert report.total_states_inspected == 2
    assert report.issues == []


def test_detects_multiple_primary_focus_states(legacy_engine: Engine) -> None:
    _insert_week(legacy_engine)
    _insert_state(legacy_engine, 1, 1, attention="primary_focus")
    _insert_state(legacy_engine, 2, 2, attention="primary_focus")

    report = audit_weekly_data(legacy_engine, clock=AUDIT_CLOCK)
    issue = next(issue for issue in report.issues if issue.code == WeeklyIssueCode.MULTIPLE_PRIMARY_FOCUS)

    assert issue.severity == AuditSeverity.MANUAL_REVIEW
    assert issue.domain_ids == (1, 2)
    assert issue.repairable is False


@pytest.mark.parametrize(
    ("focus_domain_id", "primary_domain_id", "expected_code", "expected_severity"),
    [
        (1, 2, WeeklyIssueCode.LEGACY_FOCUS_MISMATCH, AuditSeverity.REPAIRABLE),
        (3, None, WeeklyIssueCode.LEGACY_FOCUS_MISSING_STATE, AuditSeverity.MANUAL_REVIEW),
    ],
)
def test_detects_legacy_focus_inconsistencies(
    legacy_engine: Engine,
    focus_domain_id: int,
    primary_domain_id: int | None,
    expected_code: WeeklyIssueCode,
    expected_severity: AuditSeverity,
) -> None:
    _insert_week(legacy_engine, focus_domain_id=focus_domain_id)
    _insert_state(legacy_engine, 1, 1, attention="maintained")
    _insert_state(
        legacy_engine,
        2,
        2,
        attention="primary_focus" if primary_domain_id == 2 else "maintained",
    )

    report = audit_weekly_data(legacy_engine, clock=AUDIT_CLOCK)
    issue = next(issue for issue in report.issues if issue.code == expected_code)

    assert issue.severity == expected_severity


@pytest.mark.parametrize(("conflicting", "expected_severity"), [(False, "repairable"), (True, "manual_review")])
def test_classifies_duplicate_domain_states(legacy_engine: Engine, conflicting: bool, expected_severity: str) -> None:
    _insert_week(legacy_engine)
    _insert_state(legacy_engine, 1, 1, attention="maintained")
    _insert_state(legacy_engine, 2, 1, attention="paused" if conflicting else "maintained")

    report = audit_weekly_data(legacy_engine, clock=AUDIT_CLOCK)
    issue = next(issue for issue in report.issues if issue.code == WeeklyIssueCode.DUPLICATE_DOMAIN_STATE)

    assert issue.severity.value == expected_severity
    assert issue.repairable is (not conflicting)


@pytest.mark.parametrize(
    ("sacrificed_domain_id", "reason", "attention", "expected_codes"),
    [
        (1, None, "primary_focus", {WeeklyIssueCode.FOCUS_EQUALS_SACRIFICE}),
        (2, None, "maintained", {WeeklyIssueCode.SACRIFICE_WITHOUT_FOCUS, WeeklyIssueCode.SACRIFICE_MISSING_STATE}),
        (None, "Meaningful history", "maintained", {WeeklyIssueCode.REASON_WITHOUT_SACRIFICE}),
    ],
)
def test_detects_ambiguous_trade_offs(
    legacy_engine: Engine,
    sacrificed_domain_id: int | None,
    reason: str | None,
    attention: str,
    expected_codes: set[WeeklyIssueCode],
) -> None:
    _insert_week(legacy_engine, sacrificed_domain_id=sacrificed_domain_id, sacrifice_reason=reason)
    _insert_state(legacy_engine, 1, 1, attention=attention)

    report = audit_weekly_data(legacy_engine, clock=AUDIT_CLOCK)
    matching = {issue.code for issue in report.issues} & expected_codes

    assert matching == expected_codes
    assert all(issue.severity == AuditSeverity.MANUAL_REVIEW for issue in report.issues if issue.code in expected_codes)


def test_known_legacy_enums_are_repairable_and_unknown_values_are_fatal(legacy_engine: Engine) -> None:
    _insert_week(legacy_engine)
    _insert_state(legacy_engine, 1, 1, attention="focus", condition="good")
    _insert_state(legacy_engine, 2, 2, attention="mystery", condition="unknown")

    report = audit_weekly_data(legacy_engine, clock=AUDIT_CLOCK)
    issues = {(issue.code, issue.domain_ids): issue for issue in report.issues}

    assert issues[(WeeklyIssueCode.INVALID_ATTENTION, (1,))].severity == AuditSeverity.REPAIRABLE
    assert issues[(WeeklyIssueCode.INVALID_CONDITION, (1,))].severity == AuditSeverity.REPAIRABLE
    assert issues[(WeeklyIssueCode.INVALID_ATTENTION, (2,))].severity == AuditSeverity.FATAL
    assert issues[(WeeklyIssueCode.INVALID_CONDITION, (2,))].severity == AuditSeverity.FATAL


def test_unknown_attention_is_not_overwritten_from_legacy_focus(legacy_engine: Engine) -> None:
    _insert_week(legacy_engine, focus_domain_id=1)
    _insert_state(legacy_engine, 1, 1, attention="mystery")

    report = audit_weekly_data(legacy_engine, clock=AUDIT_CLOCK, fix_safe=True)

    assert report.repairs_applied == 0
    assert _raw_states(legacy_engine) == [(1, 1, "mystery", "stable")]


def test_detects_invalid_future_incomplete_and_missing_references(legacy_engine: Engine) -> None:
    _insert_week(legacy_engine, week_id=1, iso_week=99, starts_on="2026-01-01", ends_on="2026-01-02")
    _insert_state(legacy_engine, 1, None, week_id=1, domain_name="Missing id")
    _insert_week(
        legacy_engine,
        week_id=2,
        iso_week=30,
        starts_on="2026-07-20",
        ends_on="2026-07-26",
    )
    _insert_state(legacy_engine, 2, 999, week_id=2)

    codes = _codes(legacy_engine)

    assert WeeklyIssueCode.INVALID_ISO_WEEK in codes
    assert WeeklyIssueCode.INCOMPLETE_SNAPSHOT in codes
    assert WeeklyIssueCode.FUTURE_WEEK in codes
    assert WeeklyIssueCode.MISSING_DOMAIN_REFERENCE in codes


@pytest.mark.parametrize(("conflicting", "expected_severity"), [(False, "repairable"), (True, "manual_review")])
def test_classifies_duplicate_weeks(legacy_engine: Engine, conflicting: bool, expected_severity: str) -> None:
    _insert_week(legacy_engine, week_id=1, notes="Same")
    _insert_week(legacy_engine, week_id=2, notes="Different" if conflicting else "Same")
    _insert_state(legacy_engine, 1, 1, week_id=1)
    _insert_state(legacy_engine, 2, 1, week_id=2)

    report = audit_weekly_data(legacy_engine, clock=AUDIT_CLOCK)
    issue = next(issue for issue in report.issues if issue.code == WeeklyIssueCode.DUPLICATE_WEEK)

    assert issue.severity.value == expected_severity
    assert issue.related_week_ids == (1, 2)


def test_dry_run_does_not_mutate_and_safe_repairs_are_idempotent(legacy_engine: Engine) -> None:
    _insert_week(legacy_engine, focus_domain_id=1)
    _insert_state(legacy_engine, 1, 1, attention="maintain", condition="good")
    _insert_state(legacy_engine, 2, 1, attention="maintain", condition="good")
    before = _raw_states(legacy_engine)

    dry_report = audit_weekly_data(legacy_engine, clock=AUDIT_CLOCK)

    assert _raw_states(legacy_engine) == before
    assert dry_report.repairs_proposed >= 3
    fixed = audit_weekly_data(legacy_engine, clock=AUDIT_CLOCK, fix_safe=True)
    assert fixed.repairs_applied >= 3
    assert fixed.repairs_rolled_back == 0
    assert _raw_states(legacy_engine) == [(1, 1, "primary_focus", "stable")]

    repeated = audit_weekly_data(legacy_engine, clock=AUDIT_CLOCK, fix_safe=True)
    assert repeated.repairs_applied == 0
    assert repeated.issues == []


def test_safe_repair_synchronizes_stale_legacy_focus(legacy_engine: Engine) -> None:
    _insert_week(legacy_engine, focus_domain_id=1)
    _insert_state(legacy_engine, 1, 1, attention="maintained")
    _insert_state(legacy_engine, 2, 2, attention="primary_focus")

    report = audit_weekly_data(legacy_engine, clock=AUDIT_CLOCK, fix_safe=True)

    assert report.repairs_applied == 1
    with legacy_engine.connect() as connection:
        focus = connection.execute(text("SELECT focus_domain_id, focus_domain_name FROM week WHERE id = 1")).one()
    assert focus == (2, "Health")


def test_safe_repair_removes_exact_duplicate_week(legacy_engine: Engine) -> None:
    _insert_week(legacy_engine, week_id=1)
    _insert_week(legacy_engine, week_id=2)
    _insert_state(legacy_engine, 1, 1, week_id=1)
    _insert_state(legacy_engine, 2, 1, week_id=2)

    report = audit_weekly_data(legacy_engine, clock=AUDIT_CLOCK, fix_safe=True)

    assert report.repairs_applied == 1
    with legacy_engine.connect() as connection:
        assert connection.execute(text("SELECT id FROM week ORDER BY id")).scalars().all() == [1]
        assert connection.execute(text("SELECT week_id FROM week_domain_state")).scalars().all() == [1]


def test_duplicate_week_with_external_reference_requires_manual_review(legacy_engine: Engine) -> None:
    with legacy_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE external_week_reference ("
                "id INTEGER PRIMARY KEY, week_id INTEGER, FOREIGN KEY (week_id) REFERENCES week(id))"
            )
        )
    _insert_week(legacy_engine, week_id=1)
    _insert_week(legacy_engine, week_id=2)
    _insert_state(legacy_engine, 1, 1, week_id=1)
    _insert_state(legacy_engine, 2, 1, week_id=2)

    report = audit_weekly_data(legacy_engine, clock=AUDIT_CLOCK, fix_safe=True)
    issue = next(issue for issue in report.issues if issue.code == WeeklyIssueCode.DUPLICATE_WEEK)

    assert issue.severity == AuditSeverity.MANUAL_REVIEW
    assert report.repairs_applied == 0


def test_ambiguous_records_are_left_untouched(legacy_engine: Engine) -> None:
    _insert_week(legacy_engine, focus_domain_id=1, sacrificed_domain_id=1)
    _insert_state(legacy_engine, 1, 1, attention="primary_focus")
    before = _raw_states(legacy_engine)

    report = audit_weekly_data(legacy_engine, clock=AUDIT_CLOCK, fix_safe=True)

    assert report.repairs_applied == 0
    assert report.unresolved_manual_review == 1
    assert _raw_states(legacy_engine) == before


def test_repair_failure_rolls_back_the_whole_week(legacy_engine: Engine) -> None:
    _insert_week(legacy_engine)
    _insert_state(legacy_engine, 1, 1, attention="maintain")
    _insert_state(legacy_engine, 2, 2, condition="good")
    with legacy_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TRIGGER reject_second_repair BEFORE UPDATE ON week_domain_state "
                "WHEN NEW.id = 2 BEGIN SELECT RAISE(ABORT, 'boom'); END"
            )
        )

    report = audit_weekly_data(legacy_engine, clock=AUDIT_CLOCK, fix_safe=True)

    assert report.repairs_rolled_back == 2
    assert all(repair.status == RepairStatus.ROLLED_BACK for repair in report.repairs)
    assert _raw_states(legacy_engine) == [(1, 1, "maintain", "stable"), (2, 2, "maintained", "good")]


def test_scope_filters_workspace_and_iso_week(legacy_engine: Engine) -> None:
    _insert_week(legacy_engine, week_id=1, iso_week=29)
    _insert_state(legacy_engine, 1, 1, week_id=1, attention="unknown")
    _insert_week(
        legacy_engine,
        week_id=2,
        workspace_id=2,
        iso_week=28,
        starts_on="2026-07-06",
        ends_on="2026-07-12",
    )
    _insert_state(legacy_engine, 2, 4, week_id=2)

    report = audit_weekly_data(
        legacy_engine,
        scope=AuditScope(workspace_id=2, iso_year=2026, iso_week=28),
        clock=AUDIT_CLOCK,
    )

    assert report.total_weeks_inspected == 1
    assert report.total_states_inspected == 1
    assert report.issues == []


def test_json_report_and_cli_output_are_machine_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "audit.db"
    engine = create_engine(f"sqlite:///{database}", future=True)
    create_schema(engine)
    engine.dispose()
    monkeypatch.setenv("TRAECT_DATABASE_URL", f"sqlite:///{database}")

    exit_code = main(["audit", "weekly-data", "--format", "json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["total_weeks_inspected"] == 0
    assert payload["issue_counts_by_code"] == {}
    assert payload["repairs_applied"] == 0
    assert "database_url" not in payload


def _raw_states(engine: Engine) -> list[tuple[int, int, str, str]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT id, domain_id, attention, condition FROM week_domain_state ORDER BY id")
        ).all()
    return [(int(row[0]), int(row[1]), str(row[2]), str(row[3])) for row in rows]
