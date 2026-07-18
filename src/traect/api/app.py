from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from traect.api.routes import dispatch
from traect.api.version import get_version_string
from traect.app.database import make_engine, make_session_factory, migrate_schema
from traect.app.errors import ConflictError, NotFoundError, TraectError, ValidationError
from traect.app.service import TraectService
from traect.domain.models import Workspace

WEB_ROOT = Path(__file__).resolve().parents[1] / "web"


def build_app(
    database_url: str,
    *,
    clock: Callable[[], datetime] | None = None,
    timezone_name: str | None = None,
) -> Callable[[Mapping[str, Any], Callable[..., Any]], list[bytes]]:
    engine = make_engine(database_url)
    migrate_schema(engine)
    session_factory = make_session_factory(engine)
    timezone = ZoneInfo(timezone_name or os.environ.get("TRAECT_TIMEZONE", "UTC"))

    def app(environ: Mapping[str, Any], start_response: Callable[..., Any]) -> list[bytes]:
        method = environ["REQUEST_METHOD"]
        path = environ.get("PATH_INFO", "/")
        if method == "GET" and path == "/health":
            return _health_response(start_response, engine)
        if method == "GET" and path in {"/", "/index.html"}:
            return _serve_root(start_response, session_factory)
        static = _serve_static(start_response, method, path)
        if static is not None:
            return static
        with session_factory() as session:
            service = TraectService(session, clock=clock, timezone=timezone)
            try:
                input_stream = cast(Any, environ["wsgi.input"])
                body = input_stream.read(int(environ.get("CONTENT_LENGTH", "0") or 0))
                payload = _load_payload(body)
                query = parse_qs(str(environ.get("QUERY_STRING", "")), keep_blank_values=True)
                result = dispatch(service, method, path, payload, query)
                session.commit()
                return _json_response(start_response, "200 OK", result)
            except ValidationError as exc:
                session.rollback()
                return _json_response(start_response, "400 Bad Request", {"error": str(exc)})
            except ConflictError as exc:
                session.rollback()
                return _json_response(start_response, "409 Conflict", {"error": str(exc)})
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


def _health_response(start_response: Callable[..., Any], engine: Engine) -> list[bytes]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return _json_response(start_response, "503 Service Unavailable", {"status": "unavailable"})
    return _json_response(start_response, "200 OK", {"status": "ok"})


def _serve_root(
    start_response: Callable[..., Any],
    session_factory: Callable[[], Any],
) -> list[bytes]:
    with session_factory() as session:
        workspace_exists = session.execute(select(Workspace.id)).first() is not None
    template = "templates/app.html" if workspace_exists else "templates/setup.html"
    body = (WEB_ROOT / template).read_text(encoding="utf-8")
    version = get_version_string()
    body = _inject_version(body, version)
    return _respond(start_response, "200 OK", "text/html; charset=utf-8", body)


def _inject_version(html: str, version: str) -> str:
    """Inject version query parameter into static asset URLs for cache busting."""
    replacements = [
        ('href="/tokens.css"', f'href="/tokens.css?v={version}"'),
        ('href="/typography.css"', f'href="/typography.css?v={version}"'),
        ('href="/layout.css"', f'href="/layout.css?v={version}"'),
        ('href="/components.css"', f'href="/components.css?v={version}"'),
        ('src="/app.js', f'src="/app.js?v={version}'),
        ('href="/sw.js', f'href="/sw.js?v={version}'),
    ]
    for old, new in replacements:
        html = html.replace(old, new)
    return html


def _serve_static(start_response: Callable[..., Any], method: str, path: str) -> list[bytes] | None:
    if method != "GET":
        return None
    # Remove version query parameter for file lookup
    clean_path = path.split("?")[0]
    if clean_path.startswith("/js/"):
        static_root = (WEB_ROOT / "static" / "js").resolve()
        candidate = (WEB_ROOT / "static" / clean_path.removeprefix("/")).resolve()
        if candidate.is_relative_to(static_root) and candidate.is_file() and candidate.suffix == ".js":
            body = candidate.read_text(encoding="utf-8")
            return _respond(start_response, "200 OK", "text/javascript; charset=utf-8", body)
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
    if clean_path not in mapping:
        return None
    relative_path, content_type = mapping[clean_path]
    body = (WEB_ROOT / relative_path).read_text(encoding="utf-8")
    return _respond(start_response, "200 OK", content_type, body)


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
    host, port = server_address_from_environment()
    with make_server(host, port, app) as server:
        print(f"Serving on http://{host}:{port}")
        server.serve_forever()


def server_address_from_environment() -> tuple[str, int]:
    host = os.environ.get("TRAECT_HOST", "127.0.0.1").strip()
    if not host:
        raise ValueError("TRAECT_HOST must not be empty")
    raw_port = os.environ.get("TRAECT_PORT", "8000")
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError("TRAECT_PORT must be an integer between 1 and 65535") from exc
    if not 1 <= port <= 65535:
        raise ValueError("TRAECT_PORT must be an integer between 1 and 65535")
    return host, port
