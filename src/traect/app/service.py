from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, tzinfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from traect.app.errors import ConflictError, NotFoundError, ValidationError
from traect.domain.enums import DomainAttention, DomainCondition, ReviewLifecycle
from traect.domain.models import Domain, Week, WeekDomainState, Workspace

MINIMUM_ACCEPTABLE_LEVEL_LIMIT = 500
logger = logging.getLogger(__name__)


class _Unset:
    pass


UNSET = _Unset()


def _week_bounds(iso_year: int, iso_week: int) -> tuple[date, date]:
    starts_on = date.fromisocalendar(iso_year, iso_week, 1)
    ends_on = date.fromisocalendar(iso_year, iso_week, 7)
    return starts_on, ends_on


@dataclass(frozen=True)
class WeekStateInput:
    domain_id: int
    condition: DomainCondition
    attention: DomainAttention
    comment: str | None = None


class TraectService:
    def __init__(
        self,
        session: Session,
        *,
        clock: Callable[[], datetime] | None = None,
        timezone: tzinfo = UTC,
    ) -> None:
        self.session = session
        self.clock = clock or (lambda: datetime.now(UTC))
        self.timezone = timezone

    def create_workspace(self, name: str) -> Workspace:
        self._validate_workspace_name(name)
        workspace = Workspace(name=name)
        self.session.add(workspace)
        self.session.flush()
        logger.info("Workspace created: workspace_id=%s name=%s", workspace.id, workspace.name)
        return workspace

    def create_workspace_with_domains(
        self,
        name: str,
        domain_names: list[str],
        minimum_acceptable_levels: list[str | None] | None = None,
    ) -> Workspace:
        self._validate_workspace_name(name)
        cleaned_names = [self._normalize_domain_name(domain_name) for domain_name in domain_names]
        if not cleaned_names or any(not domain_name for domain_name in cleaned_names):
            raise ValidationError("at least one domain is required")
        if len({domain_name.casefold() for domain_name in cleaned_names}) != len(cleaned_names):
            raise ValidationError("domain names must be unique within a workspace")
        if minimum_acceptable_levels is None:
            minimum_acceptable_levels = [None] * len(cleaned_names)
        if len(minimum_acceptable_levels) != len(cleaned_names):
            raise ValidationError("each initial Domain must have one minimum acceptable level value")
        normalized_levels = [self._normalize_minimum_acceptable_level(value) for value in minimum_acceptable_levels]
        workspace = self.create_workspace(name)
        for index, (domain_name, minimum_acceptable_level) in enumerate(zip(cleaned_names, normalized_levels)):
            domain = Domain(
                name=domain_name,
                sort_order=index,
                minimum_acceptable_level=minimum_acceptable_level,
            )
            domain.workspace_id = workspace.id
            self.session.add(domain)
        self.session.flush()
        logger.info(
            "Workspace created with domains: workspace_id=%s name=%s domain_count=%s",
            workspace.id,
            workspace.name,
            len(cleaned_names),
        )
        return workspace

    def get_workspace(self, workspace_id: int) -> Workspace:
        workspace = self.session.get(Workspace, workspace_id)
        if workspace is None:
            raise NotFoundError("workspace not found")
        return workspace

    def get_current_workspace(self) -> Workspace:
        workspace = self.session.execute(select(Workspace).order_by(Workspace.id.asc())).scalars().first()
        if workspace is None:
            raise NotFoundError("workspace not found")
        return workspace

    def create_domain(
        self,
        workspace_id: int,
        name: str,
        *,
        minimum_acceptable_level: str | None = None,
    ) -> Domain:
        workspace = self.get_workspace(workspace_id)
        cleaned_name = self._normalize_domain_name(name)
        if not cleaned_name:
            raise ValidationError("domain name is required")
        self._ensure_active_domain_name_unique(workspace.id, cleaned_name)

        next_order = self._next_domain_sort_order(workspace.id)
        domain = Domain(
            name=cleaned_name,
            sort_order=next_order,
            minimum_acceptable_level=self._normalize_minimum_acceptable_level(minimum_acceptable_level),
        )
        domain.workspace_id = workspace.id
        domain.archived_at = None
        self.session.add(domain)
        self.session.flush()
        logger.info(
            "Domain created: workspace_id=%s domain_id=%s name=%s sort_order=%s",
            workspace.id,
            domain.id,
            domain.name,
            domain.sort_order,
        )
        return domain

    def list_domains(self, workspace_id: int, include_archived: bool = True) -> list[Domain]:
        workspace = self.get_workspace(workspace_id)
        stmt = select(Domain).where(Domain.workspace_id == workspace.id)
        if not include_archived:
            stmt = stmt.where(Domain.archived_at.is_(None))
        stmt = stmt.order_by(Domain.archived_at.is_not(None), Domain.sort_order, Domain.id)
        return list(self.session.execute(stmt).scalars())

    def update_domain(
        self,
        domain_id: int,
        *,
        name: str | None = None,
        sort_order: int | None = None,
        minimum_acceptable_level: str | None | _Unset = UNSET,
    ) -> Domain:
        domain = self.get_domain(domain_id)
        if name is not None:
            cleaned_name = self._normalize_domain_name(name)
            if not cleaned_name:
                raise ValidationError("domain name is required")
            self._ensure_active_domain_name_unique(domain.workspace_id, cleaned_name, exclude_domain_id=domain.id)
            domain.name = cleaned_name
        if sort_order is not None:
            domain.sort_order = sort_order
        if not isinstance(minimum_acceptable_level, _Unset):
            domain.minimum_acceptable_level = self._normalize_minimum_acceptable_level(minimum_acceptable_level)
        self.session.flush()
        logger.info("Domain updated: domain_id=%s workspace_id=%s", domain.id, domain.workspace_id)
        return domain

    def reorder_domains(self, workspace_id: int, domain_ids: list[int]) -> list[Domain]:
        workspace = self.get_workspace(workspace_id)
        active_domains = self.list_domains(workspace.id, include_archived=False)
        active_ids = {domain.id for domain in active_domains}
        if set(domain_ids) != active_ids or len(domain_ids) != len(active_domains):
            raise ValidationError("reorder list must contain each active domain exactly once")

        ordered: list[Domain] = []
        for index, domain_id in enumerate(domain_ids):
            domain = self.get_domain(domain_id)
            if domain.workspace_id != workspace.id or domain.archived_at is not None:
                raise ValidationError("domain must belong to the workspace and be active")
            domain.sort_order = index
            ordered.append(domain)
        self.session.flush()
        logger.info("Domains reordered: workspace_id=%s domain_count=%s", workspace.id, len(ordered))
        return ordered

    def archive_domain(self, domain_id: int) -> Domain:
        domain = self.get_domain(domain_id)
        domain.archived_at = datetime.now(UTC)
        self.session.flush()
        logger.info("Domain archived: domain_id=%s workspace_id=%s", domain.id, domain.workspace_id)
        return domain

    def restore_domain(self, domain_id: int) -> Domain:
        domain = self.get_domain(domain_id)
        self._ensure_active_domain_name_unique(domain.workspace_id, domain.name, exclude_domain_id=domain.id)
        domain.archived_at = None
        domain.sort_order = self._next_domain_sort_order(domain.workspace_id)
        self.session.flush()
        logger.info("Domain restored: domain_id=%s workspace_id=%s", domain.id, domain.workspace_id)
        return domain

    def upsert_week(
        self,
        workspace_id: int,
        iso_year: int,
        iso_week: int,
        *,
        sacrificed_domain_id: int | None = None,
        sacrifice_reason: str | None = None,
        notes: str | None = None,
        states: list[WeekStateInput] | None = None,
    ) -> Week:
        workspace = self.get_workspace(workspace_id)
        lifecycle = self.lifecycle_for_week(iso_year, iso_week)
        if lifecycle == ReviewLifecycle.FINAL:
            logger.warning(
                "Weekly review edit rejected: workspace_id=%s iso_year=%s iso_week=%s reason=final",
                workspace_id,
                iso_year,
                iso_week,
            )
            raise ConflictError("This weekly review is final and can no longer be edited.")
        starts_on, ends_on = _week_bounds(iso_year, iso_week)
        week = self._get_or_create_week(workspace.id, iso_year, iso_week, starts_on, ends_on)
        created = len(week.domain_states) == 0 and week.notes is None and week.sacrificed_domain_id is None

        if sacrificed_domain_id is not None:
            self._validate_domain_in_workspace(sacrificed_domain_id, workspace.id)

        active_domains = self.list_domains(workspace.id, include_archived=False)
        active_domains_by_id = {domain.id: domain for domain in active_domains}
        active_domain_ids = set(active_domains_by_id)
        if states is None:
            # A save without explicit states seeds one neutral state per active
            # Domain: MAINTAINED attention (no Primary focus asserted) and
            # AT_RISK condition. These are deliberately non-committal defaults,
            # not a claim about the week — a caller that omits states is creating
            # the Week shell, not recording judgements about each Domain.
            states = [
                WeekStateInput(
                    domain_id=domain_id,
                    condition=DomainCondition.AT_RISK,
                    attention=DomainAttention.MAINTAINED,
                )
                for domain_id in sorted(active_domain_ids)
            ]

        state_by_domain_id = {state.domain_id: state for state in week.domain_states}
        self.validate_week_values(
            states,
            expected_domain_ids=active_domain_ids,
            sacrificed_domain_id=sacrificed_domain_id,
            sacrifice_reason=sacrifice_reason,
            membership_error="weekly review must contain one state for each active domain",
        )

        week.sacrificed_domain_id = sacrificed_domain_id
        week.sacrificed_domain_name = (
            self.get_domain(sacrificed_domain_id).name if sacrificed_domain_id is not None else None
        )
        week.sacrifice_reason = sacrifice_reason
        week.notes = notes

        # Primary focus is enforced by a partial unique index (one primary_focus
        # row per Week). Moving focus from Domain A to Domain B must therefore
        # happen in two flushed steps: first demote any previously saved
        # primary_focus row that is no longer primary_focus in the incoming
        # states, then flush so the old row is gone before the loop below writes
        # the new one. Merging these into a single pass would momentarily leave
        # two primary_focus rows in the Week and violate the index — do not
        # "simplify" the intermediate flush away.
        input_by_domain_id = {state.domain_id: state for state in states}
        for saved_state in week.domain_states:
            desired_state = input_by_domain_id.get(saved_state.domain_id)
            if saved_state.attention == DomainAttention.PRIMARY_FOCUS and (
                desired_state is None or desired_state.attention != DomainAttention.PRIMARY_FOCUS
            ):
                saved_state.attention = DomainAttention.MAINTAINED
        self.session.flush()

        for state_input in states:
            self._validate_domain_in_workspace(state_input.domain_id, workspace.id)
            current = state_by_domain_id.get(state_input.domain_id)
            domain = active_domains_by_id[state_input.domain_id]
            if current is None:
                state = WeekDomainState(
                    domain_name=domain.name,
                    condition=state_input.condition,
                    attention=state_input.attention,
                    minimum_acceptable_level_snapshot=domain.minimum_acceptable_level,
                    comment=state_input.comment,
                )
                state.week_id = week.id
                state.domain_id = state_input.domain_id
                week.domain_states.append(state)
            else:
                current.domain_name = domain.name
                current.condition = state_input.condition
                current.attention = state_input.attention
                current.minimum_acceptable_level_snapshot = domain.minimum_acceptable_level
                current.comment = state_input.comment

        self.session.flush()
        logger.info(
            "Weekly review saved: "
            "workspace_id=%s week_id=%s iso_year=%s iso_week=%s states=%s created=%s sacrificed_domain_id=%s",
            workspace.id,
            week.id,
            iso_year,
            iso_week,
            len(states),
            created,
            sacrificed_domain_id,
        )
        return week

    def validate_week_values(
        self,
        states: list[WeekStateInput],
        *,
        expected_domain_ids: set[int],
        sacrificed_domain_id: int | None,
        sacrifice_reason: str | None,
        membership_error: str,
    ) -> None:
        incoming_domain_ids = {state.domain_id for state in states}
        if len(incoming_domain_ids) != len(states):
            raise ValidationError("weekly review cannot contain duplicate Domain states")
        if incoming_domain_ids != expected_domain_ids or len(states) != len(expected_domain_ids):
            raise ValidationError(membership_error)
        if any(not isinstance(state.attention, DomainAttention) for state in states):
            raise ValidationError("weekly review contains an invalid attention value")
        if any(not isinstance(state.condition, DomainCondition) for state in states):
            raise ValidationError("weekly review contains an invalid condition value")

        focused_domain_ids = [state.domain_id for state in states if state.attention == DomainAttention.PRIMARY_FOCUS]
        if len(focused_domain_ids) > 1:
            raise ValidationError("only one Domain can have Primary focus attention")
        primary_focus_id = focused_domain_ids[0] if focused_domain_ids else None
        if sacrificed_domain_id is not None and sacrificed_domain_id not in incoming_domain_ids:
            raise ValidationError("what gave way must be present in the weekly Domain snapshot")
        if sacrificed_domain_id is not None and primary_focus_id is None:
            raise ValidationError("what gave way requires a main focus")
        if sacrifice_reason is not None and sacrificed_domain_id is None:
            raise ValidationError("trade-off reason requires a domain that gave way")
        if primary_focus_id is not None and primary_focus_id == sacrificed_domain_id:
            raise ValidationError("main focus and what gave way must be different domains")
        if any(state.comment is not None and len(state.comment) > 300 for state in states):
            raise ValidationError("domain context must be 300 characters or fewer")

    def get_current_week(self, workspace_id: int) -> Week:
        week = self.get_current_week_optional(workspace_id)
        if week is None:
            raise NotFoundError("current week not found")
        return week

    def get_current_week_optional(self, workspace_id: int) -> Week | None:
        self.get_workspace(workspace_id)
        iso_year, iso_week = self.current_iso_week()
        return self.session.execute(
            select(Week).where(Week.workspace_id == workspace_id, Week.iso_year == iso_year, Week.iso_week == iso_week)
        ).scalar_one_or_none()

    def current_iso_week(self) -> tuple[int, int]:
        now = self.clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        iso_year, iso_week, _ = now.astimezone(self.timezone).date().isocalendar()
        return iso_year, iso_week

    def lifecycle_for_week(self, iso_year: int, iso_week: int) -> ReviewLifecycle:
        try:
            week_start, _ = _week_bounds(iso_year, iso_week)
        except ValueError as exc:
            raise ValidationError("weekly review has an invalid ISO year or week") from exc
        current_year, current_week = self.current_iso_week()
        current_start, _ = _week_bounds(current_year, current_week)
        if week_start > current_start:
            raise ValidationError("A weekly review cannot be created for a future week.")
        if week_start < current_start:
            return ReviewLifecycle.FINAL
        return ReviewLifecycle.PROVISIONAL

    def review_lifecycle(self, week: Week) -> ReviewLifecycle:
        return self.lifecycle_for_week(week.iso_year, week.iso_week)

    def list_weeks(self, workspace_id: int, *, limit: int = 52) -> list[Week]:
        workspace = self.get_workspace(workspace_id)
        stmt = (
            select(Week)
            .options(selectinload(Week.domain_states))
            .where(Week.workspace_id == workspace.id)
            .order_by(Week.iso_year.desc(), Week.iso_week.desc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars())

    def get_domain(self, domain_id: int) -> Domain:
        domain = self.session.get(Domain, domain_id)
        if domain is None:
            raise NotFoundError("domain not found")
        return domain

    def _get_or_create_week(
        self, workspace_id: int, iso_year: int, iso_week: int, starts_on: date, ends_on: date
    ) -> Week:
        week = self.session.execute(
            select(Week).where(Week.workspace_id == workspace_id, Week.iso_year == iso_year, Week.iso_week == iso_week)
        ).scalar_one_or_none()
        if week is None:
            week = Week(
                iso_year=iso_year,
                iso_week=iso_week,
                starts_on=starts_on,
                ends_on=ends_on,
            )
            week.workspace_id = workspace_id
            self.session.add(week)
            self.session.flush()
        return week

    def _ensure_active_domain_name_unique(
        self, workspace_id: int, name: str, *, exclude_domain_id: int | None = None
    ) -> None:
        normalized_name = name.casefold()
        stmt = select(Domain.name).where(Domain.workspace_id == workspace_id, Domain.archived_at.is_(None))
        if exclude_domain_id is not None:
            stmt = stmt.where(Domain.id != exclude_domain_id)
        names = [row[0].casefold() for row in self.session.execute(stmt).all()]
        if normalized_name in names:
            raise ValidationError("active domain name must be unique within a workspace")

    def _validate_domain_in_workspace(self, domain_id: int, workspace_id: int) -> Domain:
        domain = self.get_domain(domain_id)
        if domain.workspace_id != workspace_id:
            raise ValidationError("domain does not belong to workspace")
        return domain

    def _next_domain_sort_order(self, workspace_id: int) -> int:
        stmt = select(func.max(Domain.sort_order)).where(Domain.workspace_id == workspace_id)
        current_max = self.session.execute(stmt).scalar_one()
        return 0 if current_max is None else current_max + 1

    def _validate_workspace_name(self, name: str) -> None:
        if not self._normalize_domain_name(name):
            raise ValidationError("workspace name is required")

    def _normalize_domain_name(self, name: str) -> str:
        return name.strip()

    def _normalize_minimum_acceptable_level(self, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValidationError("minimum acceptable level must be a string or null")
        normalized = value.strip()
        if len(normalized) > MINIMUM_ACCEPTABLE_LEVEL_LIMIT:
            raise ValidationError(
                f"minimum acceptable level must be {MINIMUM_ACCEPTABLE_LEVEL_LIMIT} characters or fewer"
            )
        return normalized or None
