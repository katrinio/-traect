from __future__ import annotations

from typing import Any

from traect.api.serializers import (
    current_week_context_response,
    domain_response,
    week_response,
    workspace_response,
)
from traect.app.errors import NotFoundError, ValidationError
from traect.app.service import UNSET, TraectService, WeekStateInput
from traect.domain.enums import DomainAttention, DomainCondition


def dispatch(service: TraectService, method: str, path: str, payload: dict[str, Any]) -> Any:
    parts = [part for part in path.split("/") if part]
    if method == "POST" and parts == ["workspaces"]:
        domain_items = payload.get("domains", [])
        domains = [item["name"] for item in domain_items]
        if domains:
            return workspace_response(
                service.create_workspace_with_domains(
                    payload["name"],
                    domains,
                    [item.get("minimum_acceptable_level") for item in domain_items],
                )
            )
        return workspace_response(service.create_workspace(payload["name"]))
    if method == "GET" and parts == ["workspaces", "current"]:
        return workspace_response(service.get_current_workspace())
    if method == "GET" and len(parts) == 2 and parts[0] == "workspaces":
        return workspace_response(service.get_workspace(int(parts[1])))
    if method == "POST" and len(parts) == 3 and parts[0] == "workspaces" and parts[2] == "domains":
        return domain_response(
            service.create_domain(
                int(parts[1]),
                payload["name"],
                minimum_acceptable_level=payload.get("minimum_acceptable_level"),
            )
        )
    if method == "GET" and len(parts) == 3 and parts[0] == "workspaces" and parts[2] == "domains":
        return {"items": [domain_response(domain) for domain in service.list_domains(int(parts[1]))]}
    if (
        method == "PUT"
        and len(parts) == 4
        and parts[0] == "workspaces"
        and parts[2] == "domains"
        and parts[3] == "order"
    ):
        domains = service.reorder_domains(int(parts[1]), [int(domain_id) for domain_id in payload["domain_ids"]])
        return {"items": [domain_response(domain) for domain in domains]}
    if method == "PATCH" and len(parts) == 2 and parts[0] == "domains":
        minimum_acceptable_level = payload.get("minimum_acceptable_level", UNSET)
        domain = service.update_domain(
            int(parts[1]),
            name=payload.get("name"),
            sort_order=payload.get("sort_order"),
            minimum_acceptable_level=minimum_acceptable_level,
        )
        return domain_response(domain)
    if method == "POST" and len(parts) == 3 and parts[0] == "domains" and parts[2] == "archive":
        return domain_response(service.archive_domain(int(parts[1])))
    if method == "POST" and len(parts) == 3 and parts[0] == "domains" and parts[2] == "restore":
        return domain_response(service.restore_domain(int(parts[1])))
    if method == "PUT" and len(parts) == 5 and parts[0] == "workspaces" and parts[2] == "weeks":
        return _upsert_week(service, parts, payload)
    if (
        method == "GET"
        and len(parts) == 4
        and parts[0] == "workspaces"
        and parts[2] == "weeks"
        and parts[3] == "current-context"
    ):
        return current_week_context_response(service, int(parts[1]))
    if (
        method == "GET"
        and len(parts) == 4
        and parts[0] == "workspaces"
        and parts[2] == "weeks"
        and parts[3] == "current"
    ):
        week = service.get_current_week(int(parts[1]))
        return week_response(week, service.review_lifecycle(week))
    if method == "GET" and len(parts) == 3 and parts[0] == "workspaces" and parts[2] == "weeks":
        weeks = service.list_weeks(int(parts[1]))
        return {"items": [week_response(week, service.review_lifecycle(week)) for week in weeks]}
    raise NotFoundError("route not found")


def _upsert_week(service: TraectService, parts: list[str], payload: dict[str, Any]) -> dict[str, Any]:
    if "focus_domain_id" in payload or "focus_domain_name" in payload:
        raise ValidationError("Primary focus must be represented by Domain attention")
    states = [
        WeekStateInput(
            domain_id=item["domain_id"],
            condition=DomainCondition(item["condition"]),
            attention=DomainAttention(item["attention"]),
            comment=item.get("comment"),
        )
        for item in payload.get("states", [])
    ]
    week = service.upsert_week(
        int(parts[1]),
        int(parts[3]),
        int(parts[4]),
        sacrificed_domain_id=payload.get("sacrificed_domain_id"),
        sacrifice_reason=payload.get("sacrifice_reason"),
        notes=payload.get("notes"),
        states=states or None,
    )
    return week_response(week, service.review_lifecycle(week))
