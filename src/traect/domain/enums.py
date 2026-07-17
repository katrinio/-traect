from __future__ import annotations

from enum import StrEnum


class DomainCondition(StrEnum):
    STABLE = "stable"
    AT_RISK = "at_risk"
    CRITICAL = "critical"


class DomainAttention(StrEnum):
    PRIMARY_FOCUS = "primary_focus"
    MAINTAINED = "maintained"
    PAUSED = "paused"
