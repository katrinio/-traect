from __future__ import annotations

from enum import StrEnum


class WeeklyIssueCode(StrEnum):
    """Stable codes describing weekly-data integrity issues.

    Shared vocabulary between the weekly audit engine and the read-only
    history services: the audit uses these codes to classify repairable and
    manual-review findings, while history aggregations use the same codes to
    report why a week or Domain state was excluded from a calculation.
    """

    DUPLICATE_WEEK = "duplicate_week"
    INVALID_ISO_WEEK = "invalid_iso_week"
    DUPLICATE_DOMAIN_STATE = "duplicate_domain_state"
    MULTIPLE_PRIMARY_FOCUS = "multiple_primary_focus"
    LEGACY_FOCUS_MISMATCH = "legacy_focus_mismatch"
    LEGACY_FOCUS_MISSING_STATE = "legacy_focus_missing_state"
    INVALID_ATTENTION = "invalid_attention"
    INVALID_CONDITION = "invalid_condition"
    FOCUS_EQUALS_SACRIFICE = "focus_equals_sacrifice"
    SACRIFICE_MISSING_STATE = "sacrifice_missing_state"
    SACRIFICE_WITHOUT_FOCUS = "sacrifice_without_focus"
    REASON_WITHOUT_SACRIFICE = "reason_without_sacrifice"
    MISSING_DOMAIN_REFERENCE = "missing_domain_reference"
    FUTURE_WEEK = "future_week"
    INCOMPLETE_SNAPSHOT = "incomplete_snapshot"
    INVALID_WEEK_DATES = "invalid_week_dates"
    DOMAIN_WORKSPACE_MISMATCH = "domain_workspace_mismatch"
