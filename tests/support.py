from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from io import BytesIO


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def week_clock(iso_year: int, iso_week: int) -> datetime:
    day = datetime.fromisocalendar(iso_year, iso_week, 3)
    return day.replace(tzinfo=UTC)


def wsgi_request(
    app: Callable[[dict[str, object], Callable[..., object]], list[bytes]],
    method: str,
    path: str,
    *,
    body: bytes = b"",
) -> dict[str, str]:
    status_line = ""
    headers: list[tuple[str, str]] = []

    def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
        nonlocal status_line, headers
        status_line = status
        headers = response_headers

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": BytesIO(body),
    }
    response_body = b"".join(app(environ, start_response)).decode()
    return {"status": status_line, "body": response_body, "headers": str(headers)}
