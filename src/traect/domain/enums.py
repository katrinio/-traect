from __future__ import annotations

from enum import StrEnum


class WeekDomainStatus(StrEnum):
    GOOD = "good"
    WARNING = "warning"
    CRITICAL = "critical"


class WeekDomainMode(StrEnum):
    FOCUS = "focus"
    MAINTAIN = "maintain"
    IGNORE = "ignore"


class ReviewLifecycle(StrEnum):
    PROVISIONAL = "provisional"
    FINAL = "final"
