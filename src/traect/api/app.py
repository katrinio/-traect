from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import date
from typing import Any, cast
from urllib.parse import parse_qs

from traect.app.database import create_schema, make_engine, make_session_factory
from traect.app.errors import NotFoundError, TraectError, ValidationError
from traect.app.service import TraectService, WeekStateInput
from traect.domain.enums import WeekDomainMode, WeekDomainStatus
from traect.web.assets import APP_HTML, APP_JS, ICON_SVG, MANIFEST, SW_JS


def build_app(database_url: str) -> Callable[[Mapping[str, Any], Callable[..., Any]], list[bytes]]:
    engine = make_engine(database_url)
    create_schema(engine)
    session_factory = make_session_factory(engine)

    def app(environ: Mapping[str, Any], start_response: Callable[..., Any]) -> list[bytes]:
        method = environ["REQUEST_METHOD"]
        path = environ.get("PATH_INFO", "/")
        if method == "GET" and path in {"/", "/index.html"}:
            return _respond(start_response, "200 OK", "text/html; charset=utf-8", APP_HTML)
        if method == "GET" and path == "/app.js":
            return _respond(start_response, "200 OK", "text/javascript; charset=utf-8", APP_JS)
        if method == "GET" and path == "/manifest.webmanifest":
            return _respond(start_response, "200 OK", "application/manifest+json", MANIFEST)
        if method == "GET" and path == "/sw.js":
            return _respond(start_response, "200 OK", "text/javascript; charset=utf-8", SW_JS)
        if method == "GET" and path == "/icon.svg":
            return _respond(start_response, "200 OK", "image/svg+xml", ICON_SVG)
        input_stream = cast(Any, environ["wsgi.input"])
        body = input_stream.read(int(environ.get("CONTENT_LENGTH", "0") or 0))
        payload = _load_payload(body)
        query = parse_qs(environ.get("QUERY_STRING", ""))

        with session_factory() as session:
            service = TraectService(session)
            try:
                result = _dispatch(service, method, path, payload, query)
                session.commit()
                start_response("200 OK", [("Content-Type", "application/json")])
                return [json.dumps(result, default=_json_default).encode()]
            except ValidationError as exc:
                session.rollback()
                start_response("400 Bad Request", [("Content-Type", "application/json")])
                return [json.dumps({"error": str(exc)}).encode()]
            except NotFoundError as exc:
                session.rollback()
                start_response("404 Not Found", [("Content-Type", "application/json")])
                return [json.dumps({"error": str(exc)}).encode()]
            except TraectError as exc:
                session.rollback()
                start_response("422 Unprocessable Entity", [("Content-Type", "application/json")])
                return [json.dumps({"error": str(exc)}).encode()]

    return app


def _respond(start_response: Callable[..., Any], status: str, content_type: str, body: str) -> list[bytes]:
    start_response(status, [("Content-Type", content_type), ("Cache-Control", "no-cache")])
    return [body.encode()]


def _dispatch(
    service: TraectService, method: str, path: str, payload: dict[str, Any], query: dict[str, list[str]]
) -> Any:
    parts = [part for part in path.split("/") if part]
    if method == "POST" and parts == ["workspaces"]:
        return _workspace(service.create_workspace(payload["name"]))
    if method == "GET" and len(parts) == 2 and parts[0] == "workspaces":
        return _workspace(service.get_workspace(int(parts[1])))
    if method == "POST" and len(parts) == 3 and parts[0] == "workspaces" and parts[2] == "domains":
        domain = service.create_domain(int(parts[1]), payload["name"])
        return _domain(domain)
    if method == "GET" and len(parts) == 3 and parts[0] == "workspaces" and parts[2] == "domains":
        domains = service.list_domains(int(parts[1]))
        return {"items": [_domain(domain) for domain in domains]}
    if (
        method == "PUT"
        and len(parts) == 4
        and parts[0] == "workspaces"
        and parts[2] == "domains"
        and parts[3] == "order"
    ):
        domains = service.reorder_domains(int(parts[1]), [int(domain_id) for domain_id in payload["domain_ids"]])
        return {"items": [_domain(domain) for domain in domains]}
    if method == "PATCH" and len(parts) == 2 and parts[0] == "domains":
        domain = service.update_domain(int(parts[1]), name=payload.get("name"), sort_order=payload.get("sort_order"))
        return _domain(domain)
    if method == "POST" and len(parts) == 3 and parts[0] == "domains" and parts[2] == "archive":
        return _domain(service.archive_domain(int(parts[1])))
    if method == "POST" and len(parts) == 3 and parts[0] == "domains" and parts[2] == "restore":
        return _domain(service.restore_domain(int(parts[1])))
    if method == "PUT" and len(parts) == 5 and parts[0] == "workspaces" and parts[2] == "weeks":
        states = [
            WeekStateInput(
                domain_id=item["domain_id"],
                status=WeekDomainStatus(item["status"]),
                mode=WeekDomainMode(item["mode"]),
                comment=item.get("comment"),
            )
            for item in payload.get("states", [])
        ]
        week = service.upsert_week(
            int(parts[1]),
            int(parts[3]),
            int(parts[4]),
            focus_domain_id=payload.get("focus_domain_id"),
            sacrificed_domain_id=payload.get("sacrificed_domain_id"),
            sacrifice_reason=payload.get("sacrifice_reason"),
            notes=payload.get("notes"),
            states=states or None,
        )
        return _week(week)
    if method == "GET" and parts == ["workspaces"] and "workspace_id" in query:
        return {}
    if (
        method == "GET"
        and len(parts) == 4
        and parts[0] == "workspaces"
        and parts[2] == "weeks"
        and parts[3] == "current"
    ):
        return _week(service.get_current_week(int(parts[1])))
    if method == "GET" and len(parts) == 3 and parts[0] == "workspaces" and parts[2] == "weeks":
        weeks = service.list_weeks(int(parts[1]))
        return {"items": [_week(week) for week in weeks]}
    raise NotFoundError("route not found")


def _workspace(workspace: Any) -> dict[str, Any]:
    return {"id": workspace.id, "name": workspace.name}


def _domain(domain: Any) -> dict[str, Any]:
    return {
        "id": domain.id,
        "workspace_id": domain.workspace_id,
        "name": domain.name,
        "sort_order": domain.sort_order,
        "archived_at": domain.archived_at,
    }


def _week(week: Any) -> dict[str, Any]:
    return {
        "id": week.id,
        "workspace_id": week.workspace_id,
        "iso_year": week.iso_year,
        "iso_week": week.iso_week,
        "starts_on": week.starts_on,
        "ends_on": week.ends_on,
        "focus_domain_id": week.focus_domain_id,
        "sacrificed_domain_id": week.sacrificed_domain_id,
        "sacrifice_reason": week.sacrifice_reason,
        "notes": week.notes,
        "states": [
            {
                "domain_id": state.domain_id,
                "status": state.status,
                "mode": state.mode,
                "comment": state.comment,
            }
            for state in week.domain_states
        ],
    }


def _json_default(value: Any) -> Any:
    if isinstance(value, (date,)):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    return str(value)


def _load_payload(body: bytes) -> dict[str, Any]:
    if not body:
        return {}
    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        raise ValidationError("request body must be a JSON object")
    return cast(dict[str, Any], parsed)
