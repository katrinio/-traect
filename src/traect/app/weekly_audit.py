from __future__ import annotations

import logging
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import MetaData, Table, delete, inspect, select, update
from sqlalchemy.engine import Connection, Engine, RowMapping

from traect.app.issue_codes import WeeklyIssueCode

__all__ = [
    "AuditScope",
    "AuditSeverity",
    "RepairKind",
    "RepairStatus",
    "WeeklyAuditReport",
    "WeeklyIssueCode",
    "audit_weekly_data",
    "audit_weekly_data_in_connection",
]

logger = logging.getLogger(__name__)


class AuditSeverity(StrEnum):
    INFO = "info"
    REPAIRABLE = "repairable"
    MANUAL_REVIEW = "manual_review"
    FATAL = "fatal"


class RepairKind(StrEnum):
    REMOVE_DUPLICATE_STATE = "remove_duplicate_domain_state"
    NORMALIZE_ATTENTION = "normalize_attention"
    NORMALIZE_CONDITION = "normalize_condition"
    PROMOTE_LEGACY_FOCUS = "promote_legacy_focus"
    SYNC_LEGACY_FOCUS = "sync_legacy_focus"
    REMOVE_DUPLICATE_WEEK = "remove_duplicate_week"


class RepairStatus(StrEnum):
    PROPOSED = "proposed"
    APPLIED = "applied"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True)
class AuditScope:
    workspace_id: int | None = None
    iso_year: int | None = None
    iso_week: int | None = None

    def __post_init__(self) -> None:
        if (self.iso_year is None) != (self.iso_week is None):
            raise ValueError("iso_year and iso_week must be provided together")


@dataclass(frozen=True)
class AuditIssue:
    workspace_id: int | None
    week_id: int | None
    iso_year: int | None
    iso_week: int | None
    code: WeeklyIssueCode
    severity: AuditSeverity
    message: str
    domain_ids: tuple[int, ...] = ()
    related_week_ids: tuple[int, ...] = ()
    repairable: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["code"] = self.code.value
        payload["severity"] = self.severity.value
        payload["domain_ids"] = list(self.domain_ids)
        payload["related_week_ids"] = list(self.related_week_ids)
        return payload


@dataclass(frozen=True)
class RepairAction:
    kind: RepairKind
    week_id: int
    domain_id: int | None = None
    state_ids: tuple[int, ...] = ()
    duplicate_week_ids: tuple[int, ...] = ()
    column: str | None = None
    value: str | int | None = None


@dataclass(frozen=True)
class RepairResult:
    kind: RepairKind
    week_id: int
    status: RepairStatus
    domain_id: int | None = None
    affected_ids: tuple[int, ...] = ()
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["kind"] = self.kind.value
        payload["status"] = self.status.value
        payload["affected_ids"] = list(self.affected_ids)
        return payload


@dataclass
class WeeklyAuditReport:
    audited_at: datetime
    database_scope: dict[str, Any]
    total_weeks_inspected: int
    total_states_inspected: int
    issues: list[AuditIssue] = field(default_factory=list)
    repairs: list[RepairResult] = field(default_factory=list)

    @property
    def issue_counts_by_code(self) -> dict[str, int]:
        counts = Counter(issue.code.value for issue in self.issues)
        return dict(sorted(counts.items()))

    @property
    def issue_counts_by_severity(self) -> dict[str, int]:
        counts = Counter(issue.severity.value for issue in self.issues)
        return dict(sorted(counts.items()))

    @property
    def repairs_proposed(self) -> int:
        return len(self.repairs)

    @property
    def repairs_applied(self) -> int:
        return sum(repair.status == RepairStatus.APPLIED for repair in self.repairs)

    @property
    def repairs_rolled_back(self) -> int:
        return sum(repair.status == RepairStatus.ROLLED_BACK for repair in self.repairs)

    @property
    def unresolved_manual_review(self) -> int:
        return sum(issue.severity in {AuditSeverity.MANUAL_REVIEW, AuditSeverity.FATAL} for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "audited_at": self.audited_at.isoformat(),
            "database_scope": self.database_scope,
            "total_weeks_inspected": self.total_weeks_inspected,
            "total_states_inspected": self.total_states_inspected,
            "issue_counts_by_code": self.issue_counts_by_code,
            "issue_counts_by_severity": self.issue_counts_by_severity,
            "repairs_proposed": self.repairs_proposed,
            "repairs_applied": self.repairs_applied,
            "repairs_rolled_back": self.repairs_rolled_back,
            "unresolved_manual_review": self.unresolved_manual_review,
            "issues": [issue.to_dict() for issue in self.issues],
            "repairs": [repair.to_dict() for repair in self.repairs],
        }


@dataclass(frozen=True)
class _Schema:
    domain: Table
    week: Table
    state: Table
    attention_column: str | None
    condition_column: str | None
    has_legacy_focus: bool
    has_external_week_references: bool


@dataclass
class _ScanResult:
    issues: list[AuditIssue]
    actions: list[RepairAction]
    total_weeks: int
    total_states: int


ATTENTION_MAPPING = {
    "primary_focus": "primary_focus",
    "maintained": "maintained",
    "paused": "paused",
    "focus": "primary_focus",
    "maintain": "maintained",
    "ignore": "paused",
}
CONDITION_MAPPING = {
    "stable": "stable",
    "at_risk": "at_risk",
    "critical": "critical",
    "good": "stable",
    "warning": "at_risk",
}
CANONICAL_ATTENTION = {"primary_focus", "maintained", "paused"}
CANONICAL_CONDITION = {"stable", "at_risk", "critical"}


def audit_weekly_data(
    engine: Engine,
    *,
    scope: AuditScope | None = None,
    fix_safe: bool = False,
    clock: Callable[[], datetime] | None = None,
) -> WeeklyAuditReport:
    audit_scope = scope or AuditScope()
    audited_at = (clock or (lambda: datetime.now(UTC)))()
    if audited_at.tzinfo is None:
        audited_at = audited_at.replace(tzinfo=UTC)
    logger.info(
        "Weekly data audit started: workspace_id=%s iso_year=%s iso_week=%s fix_safe=%s",
        audit_scope.workspace_id,
        audit_scope.iso_year,
        audit_scope.iso_week,
        fix_safe,
    )

    with engine.connect() as connection:
        report, scan = _audit_in_connection(connection, audit_scope, audited_at)
    if fix_safe:
        report.repairs.extend(_apply_repairs(engine, audit_scope, audited_at.date(), scan.actions))
    else:
        report.repairs.extend(_proposed_results(scan.actions))

    logger.info(
        "Weekly data audit completed: weeks=%s states=%s proposed=%s applied=%s unresolved=%s",
        report.total_weeks_inspected,
        report.total_states_inspected,
        len(scan.actions),
        report.repairs_applied,
        report.unresolved_manual_review,
    )
    return report


def audit_weekly_data_in_connection(
    connection: Connection,
    *,
    scope: AuditScope,
    audited_at: datetime,
) -> WeeklyAuditReport:
    """Run the read-only audit inside an existing transaction."""
    report, scan = _audit_in_connection(connection, scope, audited_at)
    report.repairs.extend(_proposed_results(scan.actions))
    return report


def _audit_in_connection(
    connection: Connection,
    scope: AuditScope,
    audited_at: datetime,
) -> tuple[WeeklyAuditReport, _ScanResult]:
    if audited_at.tzinfo is None:
        audited_at = audited_at.replace(tzinfo=UTC)
    scan = _scan(connection, scope, audited_at.date())
    report = WeeklyAuditReport(
        audited_at=audited_at,
        database_scope={
            "dialect": connection.dialect.name,
            "workspace_id": scope.workspace_id,
            "iso_year": scope.iso_year,
            "iso_week": scope.iso_week,
        },
        total_weeks_inspected=scan.total_weeks,
        total_states_inspected=scan.total_states,
        issues=scan.issues,
    )
    return report, scan


def _load_schema(connection: Connection) -> _Schema | None:
    inspector = inspect(connection)
    table_names = set(inspector.get_table_names())
    required = {"domain", "week", "week_domain_state"}
    if not table_names & required:
        return None
    if not required <= table_names:
        missing = ", ".join(sorted(required - table_names))
        raise RuntimeError(f"weekly audit cannot inspect an incomplete schema; missing tables: {missing}")
    metadata = MetaData()
    domain = Table("domain", metadata, autoload_with=connection)
    week = Table("week", metadata, autoload_with=connection)
    state = Table("week_domain_state", metadata, autoload_with=connection)
    attention_column = "attention" if "attention" in state.c else ("mode" if "mode" in state.c else None)
    condition_column = "condition" if "condition" in state.c else ("status" if "status" in state.c else None)
    external_week_references = any(
        foreign_key.get("referred_table") == "week"
        for table_name in table_names - {"week_domain_state"}
        for foreign_key in inspector.get_foreign_keys(table_name)
    )
    return _Schema(
        domain=domain,
        week=week,
        state=state,
        attention_column=attention_column,
        condition_column=condition_column,
        has_legacy_focus="focus_domain_id" in week.c,
        has_external_week_references=external_week_references,
    )


def _scan(connection: Connection, scope: AuditScope, today: date) -> _ScanResult:
    schema = _load_schema(connection)
    if schema is None:
        return _ScanResult(issues=[], actions=[], total_weeks=0, total_states=0)

    domains = {
        int(row["id"]): row for row in connection.execute(select(schema.domain)).mappings() if row["id"] is not None
    }
    all_weeks = list(connection.execute(select(schema.week)).mappings())
    selected_weeks = [row for row in all_weeks if _week_in_scope(row, scope)]
    selected_week_ids = {_as_int(row.get("id")) for row in selected_weeks}
    all_states = list(connection.execute(select(schema.state)).mappings())
    selected_states = [row for row in all_states if _as_int(row.get("week_id")) in selected_week_ids]
    all_week_ids = {_as_int(week.get("id")) for week in all_weeks}
    orphan_states = [row for row in all_states if _as_int(row.get("week_id")) not in all_week_ids]

    states_by_week: dict[int, list[RowMapping]] = defaultdict(list)
    for state in selected_states:
        week_id = _as_int(state.get("week_id"))
        if week_id is not None:
            states_by_week[week_id].append(state)

    issues: list[AuditIssue] = []
    actions: list[RepairAction] = []
    for state in orphan_states:
        if scope.workspace_id is None and scope.iso_year is None:
            issues.append(
                AuditIssue(
                    workspace_id=None,
                    week_id=_as_int(state.get("week_id")),
                    iso_year=None,
                    iso_week=None,
                    code=WeeklyIssueCode.INCOMPLETE_SNAPSHOT,
                    severity=AuditSeverity.FATAL,
                    message="Domain state references a Week that does not exist.",
                    domain_ids=_domain_ids([state]),
                )
            )

    week_by_id = {_as_int(row.get("id")): row for row in selected_weeks}
    for week in selected_weeks:
        week_id = _as_int(week.get("id"))
        if week_id is None:
            issues.append(
                _issue(
                    week,
                    WeeklyIssueCode.INCOMPLETE_SNAPSHOT,
                    AuditSeverity.FATAL,
                    "Week has no identifier.",
                )
            )
            continue
        week_issues, week_actions = _audit_week(schema, week, states_by_week[week_id], domains, today)
        issues.extend(week_issues)
        actions.extend(week_actions)

    duplicate_issues, duplicate_actions, weeks_to_delete = _audit_duplicate_weeks(
        schema, selected_weeks, states_by_week
    )
    issues.extend(duplicate_issues)
    actions = [action for action in actions if action.week_id not in weeks_to_delete]
    actions.extend(duplicate_actions)

    issues.sort(key=_issue_sort_key)
    actions = _deduplicate_actions(actions)
    return _ScanResult(
        issues=issues,
        actions=actions,
        total_weeks=len(week_by_id),
        total_states=len(selected_states),
    )


def _audit_week(
    schema: _Schema,
    week: RowMapping,
    states: list[RowMapping],
    domains: Mapping[int, RowMapping],
    today: date,
) -> tuple[list[AuditIssue], list[RepairAction]]:
    issues: list[AuditIssue] = []
    actions: list[RepairAction] = []
    workspace_id = _as_int(week.get("workspace_id"))
    iso_year = _as_int(week.get("iso_year"))
    iso_week = _as_int(week.get("iso_week"))

    missing_week_fields = [name for name in ("workspace_id", "iso_year", "iso_week") if week.get(name) is None]
    if missing_week_fields:
        issues.append(
            _issue(
                week,
                WeeklyIssueCode.INCOMPLETE_SNAPSHOT,
                AuditSeverity.FATAL,
                f"Week is missing required fields: {', '.join(missing_week_fields)}.",
            )
        )

    expected_dates: tuple[date, date] | None = None
    try:
        if iso_year is None or iso_week is None:
            raise ValueError
        expected_dates = (
            date.fromisocalendar(iso_year, iso_week, 1),
            date.fromisocalendar(iso_year, iso_week, 7),
        )
    except ValueError:
        issues.append(
            _issue(
                week,
                WeeklyIssueCode.INVALID_ISO_WEEK,
                AuditSeverity.FATAL,
                "Week contains an invalid ISO year or week number.",
            )
        )
    if expected_dates is not None:
        if expected_dates[0] > today:
            issues.append(
                _issue(
                    week,
                    WeeklyIssueCode.FUTURE_WEEK,
                    AuditSeverity.MANUAL_REVIEW,
                    "Historical review is dated in the future.",
                )
            )
        starts_on = _as_date(week.get("starts_on"))
        ends_on = _as_date(week.get("ends_on"))
        if starts_on != expected_dates[0] or ends_on != expected_dates[1]:
            issues.append(
                _issue(
                    week,
                    WeeklyIssueCode.INVALID_WEEK_DATES,
                    AuditSeverity.MANUAL_REVIEW,
                    "Stored week boundaries do not match the ISO week.",
                )
            )

    state_issues, state_actions = _audit_states(schema, week, states, domains)
    issues.extend(state_issues)
    actions.extend(state_actions)

    normalized_attentions = [
        _normalized_value(state.get(schema.attention_column), ATTENTION_MAPPING)
        if schema.attention_column is not None
        else None
        for state in states
    ]
    primary_states = [state for state, value in zip(states, normalized_attentions) if value == "primary_focus"]
    primary_domain_ids = _domain_ids(primary_states)
    if len(primary_states) > 1:
        safely_deduplicated = len(set(primary_domain_ids)) == 1 and _duplicates_are_identical(primary_states, schema)
        severity = AuditSeverity.REPAIRABLE if safely_deduplicated else AuditSeverity.MANUAL_REVIEW
        issues.append(
            _issue(
                week,
                WeeklyIssueCode.MULTIPLE_PRIMARY_FOCUS,
                severity,
                "Week contains more than one Domain state with Primary focus.",
                domain_ids=primary_domain_ids,
                repairable=safely_deduplicated,
            )
        )

    legacy_issues, legacy_actions = _audit_legacy_focus(schema, week, states, primary_states, domains)
    issues.extend(legacy_issues)
    actions.extend(legacy_actions)

    sacrificed_id = _as_int(week.get("sacrificed_domain_id"))
    state_domain_ids = {_as_int(state.get("domain_id")) for state in states}
    primary_id = _as_int(primary_states[0].get("domain_id")) if len(primary_states) == 1 else None
    if sacrificed_id is not None:
        if sacrificed_id not in state_domain_ids:
            issues.append(
                _issue(
                    week,
                    WeeklyIssueCode.SACRIFICE_MISSING_STATE,
                    AuditSeverity.MANUAL_REVIEW,
                    "Sacrificed Domain is absent from this week's snapshot.",
                    domain_ids=(sacrificed_id,),
                )
            )
        if primary_id is None:
            issues.append(
                _issue(
                    week,
                    WeeklyIssueCode.SACRIFICE_WITHOUT_FOCUS,
                    AuditSeverity.MANUAL_REVIEW,
                    "Week has a sacrificed Domain but no unambiguous Primary focus.",
                    domain_ids=(sacrificed_id,),
                )
            )
        elif primary_id == sacrificed_id:
            issues.append(
                _issue(
                    week,
                    WeeklyIssueCode.FOCUS_EQUALS_SACRIFICE,
                    AuditSeverity.MANUAL_REVIEW,
                    "Primary focus and sacrificed Domain are the same.",
                    domain_ids=(sacrificed_id,),
                )
            )
        sacrificed_domain = domains.get(sacrificed_id)
        if sacrificed_domain is None:
            issues.append(
                _issue(
                    week,
                    WeeklyIssueCode.MISSING_DOMAIN_REFERENCE,
                    AuditSeverity.FATAL,
                    "Sacrificed Domain references a missing Domain record.",
                    domain_ids=(sacrificed_id,),
                )
            )
        elif workspace_id is not None and _as_int(sacrificed_domain.get("workspace_id")) != workspace_id:
            issues.append(
                _issue(
                    week,
                    WeeklyIssueCode.DOMAIN_WORKSPACE_MISMATCH,
                    AuditSeverity.FATAL,
                    "Sacrificed Domain belongs to another Workspace.",
                    domain_ids=(sacrificed_id,),
                )
            )
    if week.get("sacrifice_reason") is not None and sacrificed_id is None:
        issues.append(
            _issue(
                week,
                WeeklyIssueCode.REASON_WITHOUT_SACRIFICE,
                AuditSeverity.MANUAL_REVIEW,
                "Week contains a trade-off reason without a sacrificed Domain.",
            )
        )
    return issues, actions


def _audit_states(
    schema: _Schema,
    week: RowMapping,
    states: list[RowMapping],
    domains: Mapping[int, RowMapping],
) -> tuple[list[AuditIssue], list[RepairAction]]:
    issues: list[AuditIssue] = []
    actions: list[RepairAction] = []
    week_id = _required_week_id(week)
    workspace_id = _as_int(week.get("workspace_id"))
    by_domain: dict[int | None, list[RowMapping]] = defaultdict(list)
    for state in states:
        domain_id = _as_int(state.get("domain_id"))
        by_domain[domain_id].append(state)
        missing = [name for name in ("week_id", "domain_id") if state.get(name) is None]
        if "domain_name" in schema.state.c and state.get("domain_name") in {None, ""}:
            missing.append("domain_name")
        if missing:
            issues.append(
                _issue(
                    week,
                    WeeklyIssueCode.INCOMPLETE_SNAPSHOT,
                    AuditSeverity.FATAL,
                    f"Domain state is missing required fields: {', '.join(missing)}.",
                    domain_ids=(() if domain_id is None else (domain_id,)),
                )
            )
        if domain_id is not None:
            domain = domains.get(domain_id)
            if domain is None:
                issues.append(
                    _issue(
                        week,
                        WeeklyIssueCode.MISSING_DOMAIN_REFERENCE,
                        AuditSeverity.FATAL,
                        "Week state references a missing Domain record.",
                        domain_ids=(domain_id,),
                    )
                )
            elif workspace_id is not None and _as_int(domain.get("workspace_id")) != workspace_id:
                issues.append(
                    _issue(
                        week,
                        WeeklyIssueCode.DOMAIN_WORKSPACE_MISMATCH,
                        AuditSeverity.FATAL,
                        "Week state Domain belongs to another Workspace.",
                        domain_ids=(domain_id,),
                    )
                )
        attention_issue, attention_action = _audit_enum_value(
            week,
            state,
            schema.attention_column,
            ATTENTION_MAPPING,
            CANONICAL_ATTENTION,
            WeeklyIssueCode.INVALID_ATTENTION,
            RepairKind.NORMALIZE_ATTENTION,
        )
        condition_issue, condition_action = _audit_enum_value(
            week,
            state,
            schema.condition_column,
            CONDITION_MAPPING,
            CANONICAL_CONDITION,
            WeeklyIssueCode.INVALID_CONDITION,
            RepairKind.NORMALIZE_CONDITION,
        )
        if attention_issue is not None:
            issues.append(attention_issue)
        if attention_action is not None:
            actions.append(attention_action)
        if condition_issue is not None:
            issues.append(condition_issue)
        if condition_action is not None:
            actions.append(condition_action)

    for domain_id, duplicates in by_domain.items():
        if len(duplicates) < 2:
            continue
        identical = _duplicates_are_identical(duplicates, schema)
        state_ids = tuple(
            sorted(
                identifier for identifier in (_as_int(row.get("id")) for row in duplicates) if identifier is not None
            )
        )
        safely_repairable = identical and len(state_ids) == len(duplicates)
        issues.append(
            _issue(
                week,
                WeeklyIssueCode.DUPLICATE_DOMAIN_STATE,
                AuditSeverity.REPAIRABLE if safely_repairable else AuditSeverity.MANUAL_REVIEW,
                (
                    "Week contains exact duplicate Domain states."
                    if safely_repairable
                    else "Week contains conflicting duplicate Domain states."
                ),
                domain_ids=(() if domain_id is None else (domain_id,)),
                repairable=safely_repairable,
            )
        )
        if safely_repairable:
            actions.append(
                RepairAction(
                    kind=RepairKind.REMOVE_DUPLICATE_STATE,
                    week_id=week_id,
                    domain_id=domain_id,
                    state_ids=state_ids[1:],
                )
            )
    return issues, actions


def _audit_enum_value(
    week: RowMapping,
    state: RowMapping,
    column: str | None,
    mapping: Mapping[str, str],
    canonical: set[str],
    code: WeeklyIssueCode,
    kind: RepairKind,
) -> tuple[AuditIssue | None, RepairAction | None]:
    domain_id = _as_int(state.get("domain_id"))
    if column is None:
        return (
            _issue(
                week,
                WeeklyIssueCode.INCOMPLETE_SNAPSHOT,
                AuditSeverity.FATAL,
                "Domain state schema has no attention or condition column.",
                domain_ids=(() if domain_id is None else (domain_id,)),
            ),
            None,
        )
    raw = state.get(column)
    normalized = _normalized_value(raw, mapping)
    if isinstance(raw, str) and raw in canonical:
        return None, None
    if normalized is not None:
        state_id = _as_int(state.get("id"))
        repairable = state_id is not None
        return (
            _issue(
                week,
                code,
                AuditSeverity.REPAIRABLE if repairable else AuditSeverity.FATAL,
                f"Domain state uses known legacy {column} value {raw!r}.",
                domain_ids=(() if domain_id is None else (domain_id,)),
                repairable=repairable,
            ),
            (
                RepairAction(
                    kind=kind,
                    week_id=_required_week_id(week),
                    domain_id=domain_id,
                    state_ids=(state_id,),
                    column=column,
                    value=normalized,
                )
                if repairable and state_id is not None
                else None
            ),
        )
    return (
        _issue(
            week,
            code,
            AuditSeverity.FATAL,
            f"Domain state uses unknown {column} value {raw!r}.",
            domain_ids=(() if domain_id is None else (domain_id,)),
        ),
        None,
    )


def _audit_legacy_focus(
    schema: _Schema,
    week: RowMapping,
    states: list[RowMapping],
    primary_states: list[RowMapping],
    domains: Mapping[int, RowMapping],
) -> tuple[list[AuditIssue], list[RepairAction]]:
    if not schema.has_legacy_focus:
        return [], []
    week_id = _required_week_id(week)
    legacy_id = _as_int(week.get("focus_domain_id"))
    legacy_name = week.get("focus_domain_name") if "focus_domain_name" in schema.week.c else None
    state_by_domain = defaultdict(list)
    for state in states:
        state_by_domain[_as_int(state.get("domain_id"))].append(state)

    if legacy_id is None:
        if legacy_name not in {None, ""}:
            return [
                _issue(
                    week,
                    WeeklyIssueCode.LEGACY_FOCUS_MISMATCH,
                    AuditSeverity.MANUAL_REVIEW,
                    "Legacy focus name exists without a Domain identifier.",
                )
            ], []
        if len(primary_states) != 1:
            return [], []
        canonical_id = _as_int(primary_states[0].get("domain_id"))
        if canonical_id is None or not _domain_is_valid_for_week(canonical_id, domains, week):
            return [], []
        return [
            _issue(
                week,
                WeeklyIssueCode.LEGACY_FOCUS_MISMATCH,
                AuditSeverity.REPAIRABLE,
                "Canonical Primary focus exists but the legacy focus field is empty.",
                domain_ids=(canonical_id,),
                repairable=True,
            )
        ], [
            RepairAction(
                kind=RepairKind.SYNC_LEGACY_FOCUS,
                week_id=week_id,
                domain_id=canonical_id,
                value=canonical_id,
            )
        ]

    matching_states = state_by_domain.get(legacy_id, [])
    if not matching_states:
        return [
            _issue(
                week,
                WeeklyIssueCode.LEGACY_FOCUS_MISSING_STATE,
                AuditSeverity.MANUAL_REVIEW,
                "Legacy focus points to a Domain absent from this week's snapshot.",
                domain_ids=(legacy_id,),
            )
        ], []
    matching_states_are_one_fact = len(matching_states) == 1 or _duplicates_are_identical(matching_states, schema)
    matching_attention_is_known = schema.attention_column is not None and all(
        _normalized_value(state.get(schema.attention_column), ATTENTION_MAPPING) is not None
        for state in matching_states
    )
    if (
        len(primary_states) == 0
        and matching_states_are_one_fact
        and matching_attention_is_known
        and schema.attention_column is not None
        and _domain_is_valid_for_week(legacy_id, domains, week)
    ):
        state_ids = sorted(
            identifier
            for identifier in (_as_int(state.get("id")) for state in matching_states)
            if identifier is not None
        )
        state_id = state_ids[0] if state_ids else None
        if state_id is not None:
            return [
                _issue(
                    week,
                    WeeklyIssueCode.LEGACY_FOCUS_MISMATCH,
                    AuditSeverity.REPAIRABLE,
                    "Legacy focus can be promoted to the canonical Primary focus state.",
                    domain_ids=(legacy_id,),
                    repairable=True,
                )
            ], [
                RepairAction(
                    kind=RepairKind.PROMOTE_LEGACY_FOCUS,
                    week_id=week_id,
                    domain_id=legacy_id,
                    state_ids=(state_id,),
                    column=schema.attention_column,
                    value="primary_focus",
                )
            ]
    if len(primary_states) == 1:
        canonical_id = _as_int(primary_states[0].get("domain_id"))
        if canonical_id == legacy_id or canonical_id is None:
            return [], []
        if not _domain_is_valid_for_week(canonical_id, domains, week):
            return [], []
        return [
            _issue(
                week,
                WeeklyIssueCode.LEGACY_FOCUS_MISMATCH,
                AuditSeverity.REPAIRABLE,
                "Legacy focus disagrees with the canonical Primary focus state.",
                domain_ids=tuple(sorted({legacy_id, canonical_id})),
                repairable=True,
            )
        ], [
            RepairAction(
                kind=RepairKind.SYNC_LEGACY_FOCUS,
                week_id=week_id,
                domain_id=canonical_id,
                value=canonical_id,
            )
        ]
    return [], []


def _audit_duplicate_weeks(
    schema: _Schema,
    weeks: list[RowMapping],
    states_by_week: Mapping[int, list[RowMapping]],
) -> tuple[list[AuditIssue], list[RepairAction], set[int]]:
    groups: dict[tuple[int | None, int | None, int | None], list[RowMapping]] = defaultdict(list)
    for week in weeks:
        groups[
            (_as_int(week.get("workspace_id")), _as_int(week.get("iso_year")), _as_int(week.get("iso_week")))
        ].append(week)
    issues: list[AuditIssue] = []
    actions: list[RepairAction] = []
    weeks_to_delete: set[int] = set()
    for duplicates in groups.values():
        if len(duplicates) < 2:
            continue
        ordered = sorted(duplicates, key=_required_week_id)
        canonical = ordered[0]
        week_ids = tuple(_required_week_id(row) for row in ordered)
        structurally_identical = all(
            _week_signature(schema, row, states_by_week.get(_required_week_id(row), []))
            == _week_signature(schema, canonical, states_by_week.get(_required_week_id(canonical), []))
            for row in ordered[1:]
        )
        identical = structurally_identical and not schema.has_external_week_references
        issues.append(
            _issue(
                canonical,
                WeeklyIssueCode.DUPLICATE_WEEK,
                AuditSeverity.REPAIRABLE if identical else AuditSeverity.MANUAL_REVIEW,
                (
                    "Workspace contains structurally identical duplicate Week records."
                    if identical
                    else "Workspace contains duplicate Week records that cannot be removed automatically."
                ),
                related_week_ids=week_ids,
                repairable=identical,
            )
        )
        if identical:
            duplicate_ids = week_ids[1:]
            weeks_to_delete.update(duplicate_ids)
            actions.append(
                RepairAction(
                    kind=RepairKind.REMOVE_DUPLICATE_WEEK,
                    week_id=week_ids[0],
                    duplicate_week_ids=duplicate_ids,
                )
            )
    return issues, actions, weeks_to_delete


def _week_signature(schema: _Schema, week: RowMapping, states: list[RowMapping]) -> tuple[Any, ...]:
    week_fields = (
        "starts_on",
        "ends_on",
        "sacrificed_domain_id",
        "sacrificed_domain_name",
        "sacrifice_reason",
        "notes",
        "focus_domain_id",
        "focus_domain_name",
    )
    values = tuple(week.get(name) for name in week_fields if name in schema.week.c)
    state_signatures = sorted((_state_signature(state, schema) for state in states), key=repr)
    return values, tuple(state_signatures)


def _state_signature(state: RowMapping, schema: _Schema) -> tuple[Any, ...]:
    fields = (
        "domain_id",
        "domain_name",
        schema.attention_column,
        schema.condition_column,
        "minimum_acceptable_level_snapshot",
        "comment",
    )
    return tuple(state.get(name) for name in fields if name is not None and name in schema.state.c)


def _duplicates_are_identical(states: list[RowMapping], schema: _Schema) -> bool:
    if not states:
        return False
    signature = _state_signature(states[0], schema)
    return all(_state_signature(state, schema) == signature for state in states[1:])


def _apply_repairs(
    engine: Engine,
    scope: AuditScope,
    today: date,
    actions: Sequence[RepairAction],
) -> list[RepairResult]:
    grouped: dict[int, list[RepairAction]] = defaultdict(list)
    for action in actions:
        grouped[action.week_id].append(action)
    results: list[RepairResult] = []
    for week_id in sorted(grouped):
        week_actions = grouped[week_id]
        try:
            with engine.begin() as connection:
                schema = _load_schema(connection)
                if schema is None:
                    raise RuntimeError("weekly tables disappeared before repair")
                for action in week_actions:
                    _apply_action(connection, schema, action)
                verification = _scan(connection, scope, today)
                remaining = {
                    (action.kind, action.week_id): _repair_still_needed(action, verification.actions)
                    for action in week_actions
                }
                if any(remaining.values()):
                    raise RuntimeError("safe repair did not satisfy its post-repair validation")
            results.extend(_applied_result(action) for action in week_actions)
            logger.info("Weekly data repairs committed: week_id=%s count=%s", week_id, len(week_actions))
        except Exception as exc:
            logger.exception("Weekly data repairs rolled back: week_id=%s", week_id)
            results.extend(_rolled_back_result(action, str(exc)) for action in week_actions)
    return results


def _apply_action(connection: Connection, schema: _Schema, action: RepairAction) -> None:
    if action.kind == RepairKind.REMOVE_DUPLICATE_STATE:
        connection.execute(delete(schema.state).where(schema.state.c.id.in_(action.state_ids)))
        return
    if action.kind in {RepairKind.NORMALIZE_ATTENTION, RepairKind.NORMALIZE_CONDITION, RepairKind.PROMOTE_LEGACY_FOCUS}:
        if action.column is None or action.column not in schema.state.c or not action.state_ids:
            raise RuntimeError(f"repair {action.kind.value} lacks a valid state target")
        connection.execute(
            update(schema.state).where(schema.state.c.id.in_(action.state_ids)).values({action.column: action.value})
        )
        return
    if action.kind == RepairKind.SYNC_LEGACY_FOCUS:
        if "focus_domain_id" not in schema.week.c:
            raise RuntimeError("legacy focus column is no longer present")
        values: dict[str, Any] = {"focus_domain_id": action.value}
        if "focus_domain_name" in schema.week.c:
            domain_name = connection.execute(
                select(schema.domain.c.name).where(schema.domain.c.id == action.value)
            ).scalar_one_or_none()
            values["focus_domain_name"] = domain_name
        connection.execute(update(schema.week).where(schema.week.c.id == action.week_id).values(values))
        return
    if action.kind == RepairKind.REMOVE_DUPLICATE_WEEK:
        if action.duplicate_week_ids:
            connection.execute(delete(schema.state).where(schema.state.c.week_id.in_(action.duplicate_week_ids)))
            connection.execute(delete(schema.week).where(schema.week.c.id.in_(action.duplicate_week_ids)))
        return
    raise RuntimeError(f"unsupported repair kind: {action.kind.value}")


def _repair_still_needed(action: RepairAction, proposed: Iterable[RepairAction]) -> bool:
    return any(
        candidate.kind == action.kind
        and candidate.week_id == action.week_id
        and candidate.domain_id == action.domain_id
        for candidate in proposed
    )


def _proposed_results(actions: Sequence[RepairAction]) -> list[RepairResult]:
    return [
        RepairResult(
            kind=action.kind,
            week_id=action.week_id,
            domain_id=action.domain_id,
            affected_ids=action.state_ids or action.duplicate_week_ids,
            status=RepairStatus.PROPOSED,
        )
        for action in actions
    ]


def _applied_result(action: RepairAction) -> RepairResult:
    return RepairResult(
        kind=action.kind,
        week_id=action.week_id,
        domain_id=action.domain_id,
        affected_ids=action.state_ids or action.duplicate_week_ids,
        status=RepairStatus.APPLIED,
    )


def _rolled_back_result(action: RepairAction, message: str) -> RepairResult:
    return RepairResult(
        kind=action.kind,
        week_id=action.week_id,
        domain_id=action.domain_id,
        affected_ids=action.state_ids or action.duplicate_week_ids,
        status=RepairStatus.ROLLED_BACK,
        message=message,
    )


def _week_in_scope(week: RowMapping, scope: AuditScope) -> bool:
    if scope.workspace_id is not None and _as_int(week.get("workspace_id")) != scope.workspace_id:
        return False
    if scope.iso_year is not None:
        return _as_int(week.get("iso_year")) == scope.iso_year and _as_int(week.get("iso_week")) == scope.iso_week
    return True


def _normalized_value(value: Any, mapping: Mapping[str, str]) -> str | None:
    if not isinstance(value, str):
        return None
    return mapping.get(value.lower())


def _domain_is_valid_for_week(domain_id: int, domains: Mapping[int, RowMapping], week: RowMapping) -> bool:
    domain = domains.get(domain_id)
    if domain is None:
        return False
    workspace_id = _as_int(week.get("workspace_id"))
    return workspace_id is not None and _as_int(domain.get("workspace_id")) == workspace_id


def _domain_ids(states: Iterable[RowMapping]) -> tuple[int, ...]:
    return tuple(
        sorted(
            {
                identifier
                for identifier in (_as_int(state.get("domain_id")) for state in states)
                if identifier is not None
            }
        )
    )


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except TypeError, ValueError:
        return None


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _required_week_id(week: RowMapping) -> int:
    week_id = _as_int(week.get("id"))
    if week_id is None:
        raise RuntimeError("weekly audit cannot repair a Week without an identifier")
    return week_id


def _issue(
    week: RowMapping,
    code: WeeklyIssueCode,
    severity: AuditSeverity,
    message: str,
    *,
    domain_ids: tuple[int, ...] = (),
    related_week_ids: tuple[int, ...] = (),
    repairable: bool = False,
) -> AuditIssue:
    return AuditIssue(
        workspace_id=_as_int(week.get("workspace_id")),
        week_id=_as_int(week.get("id")),
        iso_year=_as_int(week.get("iso_year")),
        iso_week=_as_int(week.get("iso_week")),
        code=code,
        severity=severity,
        message=message,
        domain_ids=domain_ids,
        related_week_ids=related_week_ids,
        repairable=repairable,
    )


def _issue_sort_key(issue: AuditIssue) -> tuple[int, int, str, tuple[int, ...]]:
    return (
        issue.week_id if issue.week_id is not None else -1,
        issue.workspace_id if issue.workspace_id is not None else -1,
        issue.code.value,
        issue.domain_ids,
    )


def _deduplicate_actions(actions: list[RepairAction]) -> list[RepairAction]:
    unique: dict[tuple[Any, ...], RepairAction] = {}
    for action in actions:
        key = (
            action.kind,
            action.week_id,
            action.domain_id,
            action.state_ids,
            action.duplicate_week_ids,
            action.column,
            action.value,
        )
        unique[key] = action
    return sorted(
        unique.values(),
        key=lambda item: (
            item.week_id,
            item.kind.value,
            item.domain_id if item.domain_id is not None else -1,
        ),
    )
