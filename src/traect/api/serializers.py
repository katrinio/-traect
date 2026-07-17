from __future__ import annotations

from typing import Any

from traect.app.service import TraectService
from traect.domain.enums import ReviewLifecycle


def workspace_response(workspace: Any) -> dict[str, Any]:
    return {"id": workspace.id, "name": workspace.name}


def domain_response(domain: Any) -> dict[str, Any]:
    return {
        "id": domain.id,
        "workspace_id": domain.workspace_id,
        "name": domain.name,
        "sort_order": domain.sort_order,
        "minimum_acceptable_level": domain.minimum_acceptable_level,
        "archived_at": domain.archived_at,
    }


def current_week_context_response(service: TraectService, workspace_id: int) -> dict[str, Any]:
    iso_year, iso_week = service.current_iso_week()
    review = service.get_current_week_optional(workspace_id)
    review_domains = []
    for domain in service.list_domains(workspace_id, include_archived=False):
        review_domains.append(
            {
                "domain_id": domain.id,
                "name": domain.name,
                "minimum_acceptable_level": domain.minimum_acceptable_level,
            }
        )
    return {
        "iso_year": iso_year,
        "iso_week": iso_week,
        "lifecycle": ReviewLifecycle.PROVISIONAL,
        "editable": True,
        "review_domains": review_domains,
        "review": week_response(review, ReviewLifecycle.PROVISIONAL) if review is not None else None,
    }


def week_response(week: Any, lifecycle: ReviewLifecycle) -> dict[str, Any]:
    primary_focus = week.primary_focus_state()
    return {
        "id": week.id,
        "workspace_id": week.workspace_id,
        "iso_year": week.iso_year,
        "iso_week": week.iso_week,
        "lifecycle": lifecycle,
        "editable": lifecycle == ReviewLifecycle.PROVISIONAL,
        "starts_on": week.starts_on,
        "ends_on": week.ends_on,
        "main_focus": (
            {"domain_id": primary_focus.domain_id, "name": primary_focus.domain_name}
            if primary_focus is not None
            else None
        ),
        "sacrificed_domain_id": week.sacrificed_domain_id,
        "sacrificed_domain_name": week.sacrificed_domain_name,
        "sacrifice_reason": week.sacrifice_reason,
        "notes": week.notes,
        "states": [
            {
                "domain_id": state.domain_id,
                "domain_name": state.domain_name,
                "condition": state.condition,
                "attention": state.attention,
                "minimum_acceptable_level": state.minimum_acceptable_level_snapshot,
                "comment": state.comment,
            }
            for state in week.domain_states
        ],
    }
