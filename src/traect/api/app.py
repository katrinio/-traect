from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from datetime import date
from pathlib import Path
from typing import Any, cast
from wsgiref.simple_server import make_server

from sqlalchemy import select

from traect.app.database import make_engine, make_session_factory, migrate_schema
from traect.app.errors import NotFoundError, TraectError, ValidationError
from traect.app.service import TraectService, WeekStateInput
from traect.domain.enums import WeekDomainMode, WeekDomainStatus
from traect.domain.models import Workspace

WEB_ROOT = Path(__file__).resolve().parents[1] / "web"


def build_app(database_url: str) -> Callable[[Mapping[str, Any], Callable[..., Any]], list[bytes]]:
    engine = make_engine(database_url)
    migrate_schema(engine)
    session_factory = make_session_factory(engine)

    def app(environ: Mapping[str, Any], start_response: Callable[..., Any]) -> list[bytes]:
        method = environ["REQUEST_METHOD"]
        path = environ.get("PATH_INFO", "/")
        if method == "GET" and path in {"/", "/index.html"}:
            return _serve_root(start_response, session_factory)
        static = _serve_static(start_response, method, path)
        if static is not None:
            return static
        with session_factory() as session:
            service = TraectService(session)
            try:
                input_stream = cast(Any, environ["wsgi.input"])
                body = input_stream.read(int(environ.get("CONTENT_LENGTH", "0") or 0))
                payload = _load_payload(body)
                result = _dispatch(service, method, path, payload)
                session.commit()
                return _json_response(start_response, "200 OK", result)
            except ValidationError as exc:
                session.rollback()
                return _json_response(start_response, "400 Bad Request", {"error": str(exc)})
            except NotFoundError as exc:
                session.rollback()
                return _json_response(start_response, "404 Not Found", {"error": str(exc)})
            except TraectError as exc:
                session.rollback()
                return _json_response(start_response, "422 Unprocessable Entity", {"error": str(exc)})
            except KeyError as exc:
                session.rollback()
                message = f"missing required field: {exc.args[0]}"
                return _json_response(start_response, "400 Bad Request", {"error": message})
            except (TypeError, ValueError) as exc:
                session.rollback()
                message = f"invalid request: {exc}" if str(exc) else "invalid request"
                return _json_response(start_response, "400 Bad Request", {"error": message})

    return app


def _respond(start_response: Callable[..., Any], status: str, content_type: str, body: str) -> list[bytes]:
    start_response(status, [("Content-Type", content_type), ("Cache-Control", "no-cache")])
    return [body.encode()]


def _json_response(start_response: Callable[..., Any], status: str, payload: Any) -> list[bytes]:
    body = json.dumps(payload, default=_json_default)
    return _respond(start_response, status, "application/json; charset=utf-8", body)


def _serve_root(
    start_response: Callable[..., Any],
    session_factory: Callable[[], Any],
) -> list[bytes]:
    with session_factory() as session:
        workspace_exists = session.execute(select(Workspace.id)).first() is not None
    template = "templates/app.html" if workspace_exists else "templates/setup.html"
    body = (WEB_ROOT / template).read_text(encoding="utf-8")
    return _respond(start_response, "200 OK", "text/html; charset=utf-8", body)


def _serve_static(start_response: Callable[..., Any], method: str, path: str) -> list[bytes] | None:
    if method != "GET":
        return None
    mapping = {
        "/tokens.css": ("static/tokens.css", "text/css; charset=utf-8"),
        "/typography.css": ("static/typography.css", "text/css; charset=utf-8"),
        "/layout.css": ("static/layout.css", "text/css; charset=utf-8"),
        "/components.css": ("static/components.css", "text/css; charset=utf-8"),
        "/app.js": ("static/app.js", "text/javascript; charset=utf-8"),
        "/manifest.webmanifest": ("static/manifest.webmanifest", "application/manifest+json"),
        "/sw.js": ("static/sw.js", "text/javascript; charset=utf-8"),
        "/icon.svg": ("static/icon.svg", "image/svg+xml"),
    }
    if path not in mapping:
        return None
    relative_path, content_type = mapping[path]
    body = (WEB_ROOT / relative_path).read_text(encoding="utf-8")
    return _respond(start_response, "200 OK", content_type, body)


def _dispatch(service: TraectService, method: str, path: str, payload: dict[str, Any]) -> Any:
    parts = [part for part in path.split("/") if part]
    if method == "POST" and parts == ["workspaces"]:
        domains = [item["name"] for item in payload.get("domains", [])]
        if domains:
            return _workspace(service.create_workspace_with_domains(payload["name"], domains))
        return _workspace(service.create_workspace(payload["name"]))
    if method == "GET" and parts == ["workspaces", "current"]:
        return _workspace(service.get_current_workspace())
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
        "focus_domain_name": week.focus_domain_name,
        "sacrificed_domain_id": week.sacrificed_domain_id,
        "sacrificed_domain_name": week.sacrificed_domain_name,
        "sacrifice_reason": week.sacrifice_reason,
        "notes": week.notes,
        "states": [
            {
                "domain_id": state.domain_id,
                "domain_name": state.domain_name,
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
    try:
        parsed = json.loads(body)
    except UnicodeDecodeError, json.JSONDecodeError:
        raise ValidationError("request body must contain valid JSON")
    if not isinstance(parsed, dict):
        raise ValidationError("request body must be a JSON object")
    return cast(dict[str, Any], parsed)


def main() -> None:
    database_url = os.environ.get("TRAECT_DATABASE_URL", "sqlite:///traect.db")
    app = build_app(database_url)
    with make_server("127.0.0.1", 8000, app) as server:
        print("Serving on http://127.0.0.1:8000")
        server.serve_forever()
