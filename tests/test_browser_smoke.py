from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.request import Request, urlopen
from wsgiref.simple_server import WSGIServer, make_server

import pytest
from playwright.sync_api import Locator, Page, expect, sync_playwright

from traect.api.app import build_app


@pytest.fixture
def page() -> Iterator[Page]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            yield page
        finally:
            browser.close()


@pytest.fixture
def live_app(tmp_path: Path) -> Iterator[str]:
    app = build_app(f"sqlite:///{tmp_path / 'browser.db'}")
    server: WSGIServer = make_server("127.0.0.1", 0, app)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def request_json(base_url: str, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = json.dumps(payload).encode() if payload is not None else None
    request = Request(
        f"{base_url}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urlopen(request) as response:
        return dict(json.load(response))


def seed_workspace(base_url: str, domain_names: list[str]) -> tuple[int, dict[str, int]]:
    workspace = request_json(
        base_url,
        "POST",
        "/workspaces",
        {"name": "Life", "domains": [{"name": name} for name in domain_names]},
    )
    workspace_id = int(workspace["id"])
    domains = request_json(base_url, "GET", f"/workspaces/{workspace_id}/domains")["items"]
    return workspace_id, {str(domain["name"]): int(domain["id"]) for domain in domains}


def save_current_review(
    base_url: str,
    workspace_id: int,
    domains: dict[str, int],
    *,
    focus: str | None = None,
    sacrificed: str | None = None,
    reason: str | None = None,
    ignored: set[str] | None = None,
) -> dict[str, Any]:
    ignored = ignored or set()
    iso_year, iso_week, _ = date.today().isocalendar()
    states = [
        {
            "domain_id": domain_id,
            "mode": "focus" if name == focus else ("ignore" if name in ignored else "maintain"),
            "status": "good",
            "comment": None,
        }
        for name, domain_id in domains.items()
    ]
    return request_json(
        base_url,
        "PUT",
        f"/workspaces/{workspace_id}/weeks/{iso_year}/{iso_week}",
        {
            "focus_domain_id": domains.get(focus) if focus else None,
            "sacrificed_domain_id": domains.get(sacrificed) if sacrificed else None,
            "sacrifice_reason": reason,
            "notes": None,
            "states": states,
        },
    )


def tradeoff_value(page: Page, field: str) -> Locator:
    return page.locator(f"[data-tradeoff-field='{field}'] dd")


@pytest.mark.browser
def test_onboarding_to_weekly_review(page: Page, live_app: str) -> None:
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    page.goto(live_app)
    expect(page.get_by_role("heading", name="Workspace setup")).to_be_visible()

    page.get_by_label("Workspace name").fill("Life")
    page.get_by_label("Domain").fill("Work")
    page.get_by_role("button", name="Add Domain").click()
    page.get_by_label("Domain").nth(1).fill("Health")
    page.get_by_role("button", name="Create Workspace").click()

    expect(page.locator("#headline")).to_have_text("Life")
    current_groups = page.locator("#current-groups")
    expect(current_groups.get_by_text("Work", exact=True)).to_be_visible()
    expect(current_groups.get_by_text("Health", exact=True)).to_be_visible()

    page.get_by_role("button", name="Edit review").click()
    what_gave_way = page.locator("select[name='sacrificed_domain_id']")
    expect(what_gave_way).to_be_disabled()
    page.locator("select[name^='mode_']").first.select_option("focus")
    expect(what_gave_way).to_be_enabled()
    page.locator("select[name='focus_domain_id']").select_option(label="Work")
    page.get_by_role("button", name="Save").click()

    expect(current_groups.get_by_role("heading", name="Focus")).to_be_visible()
    expect(current_groups.get_by_text("Work", exact=True)).to_be_visible()
    assert page_errors == []


@pytest.mark.browser
def test_current_shows_full_saved_tradeoff_as_read_only_summary(page: Page, live_app: str) -> None:
    workspace_id, domains = seed_workspace(live_app, ["Work", "Health"])
    save_current_review(live_app, workspace_id, domains, focus="Work", sacrificed="Health", reason="Release")

    page.goto(live_app)

    tradeoff = page.locator("#current-tradeoff")
    expect(tradeoff).to_be_visible()
    expect(tradeoff.get_by_role("heading", name="This week")).to_be_visible()
    expect(tradeoff_value(page, "focus")).to_have_text("Work")
    expect(tradeoff_value(page, "sacrifice")).to_have_text("Health")
    expect(tradeoff_value(page, "reason")).to_have_text("Release")
    expect(tradeoff.locator("input, select, textarea, button")).to_have_count(0)
    expect(page.get_by_role("button", name="Edit review")).to_have_count(1)


@pytest.mark.browser
def test_current_shows_neutral_state_when_review_has_no_primary_focus(page: Page, live_app: str) -> None:
    workspace_id, domains = seed_workspace(live_app, ["Work", "Health"])
    save_current_review(live_app, workspace_id, domains)

    page.goto(live_app)

    tradeoff = page.locator("#current-tradeoff")
    expect(tradeoff.get_by_text("No primary focus recorded.", exact=True)).to_be_visible()
    expect(tradeoff.locator(".tradeoff-row")).to_have_count(0)


@pytest.mark.browser
def test_current_shows_none_recorded_when_focus_has_no_sacrifice(page: Page, live_app: str) -> None:
    workspace_id, domains = seed_workspace(live_app, ["Work", "Health"])
    save_current_review(live_app, workspace_id, domains, focus="Work")

    page.goto(live_app)

    expect(tradeoff_value(page, "focus")).to_have_text("Work")
    expect(tradeoff_value(page, "sacrifice")).to_have_text("None recorded")
    expect(page.locator("[data-tradeoff-field='reason']")).to_have_count(0)


@pytest.mark.browser
def test_current_omits_why_when_saved_tradeoff_has_no_reason(page: Page, live_app: str) -> None:
    workspace_id, domains = seed_workspace(live_app, ["Work", "Health"])
    save_current_review(live_app, workspace_id, domains, focus="Work", sacrificed="Health")

    page.goto(live_app)

    expect(tradeoff_value(page, "focus")).to_have_text("Work")
    expect(tradeoff_value(page, "sacrifice")).to_have_text("Health")
    expect(page.locator("[data-tradeoff-field='reason']")).to_have_count(0)


@pytest.mark.browser
def test_current_hides_tradeoff_when_week_has_no_saved_review(page: Page, live_app: str) -> None:
    seed_workspace(live_app, ["Work", "Health"])

    page.goto(live_app)

    expect(page.locator("#current-tradeoff")).to_be_hidden()
    expect(page.get_by_role("button", name="Edit review")).to_be_visible()


@pytest.mark.browser
def test_current_does_not_infer_sacrifice_from_ignored_domain(page: Page, live_app: str) -> None:
    workspace_id, domains = seed_workspace(live_app, ["Work", "Health"])
    save_current_review(live_app, workspace_id, domains, focus="Work", ignored={"Health"})

    page.goto(live_app)

    expect(tradeoff_value(page, "sacrifice")).to_have_text("None recorded")
    expect(tradeoff_value(page, "sacrifice")).not_to_have_text("Health")


@pytest.mark.browser
def test_current_wraps_long_tradeoff_values_on_mobile_without_changing_data(page: Page, live_app: str) -> None:
    focus_name = "Deeply focused project with a deliberately long domain name"
    sacrificed_name = "Long-term recovery and relationships that received less attention"
    reason = "R" * 300
    workspace_id, domains = seed_workspace(live_app, [focus_name, sacrificed_name])
    saved = save_current_review(
        live_app,
        workspace_id,
        domains,
        focus=focus_name,
        sacrificed=sacrificed_name,
        reason=reason,
    )
    page.set_viewport_size({"width": 375, "height": 760})

    page.goto(live_app)

    focus_row = page.locator("[data-tradeoff-field='focus']")
    term_box = focus_row.locator("dt").bounding_box()
    value_box = focus_row.locator("dd").bounding_box()
    assert term_box is not None and value_box is not None
    assert value_box["y"] >= term_box["y"] + term_box["height"]
    expect(tradeoff_value(page, "focus")).to_have_text(focus_name)
    expect(tradeoff_value(page, "sacrifice")).to_have_text(sacrificed_name)
    expect(tradeoff_value(page, "reason")).to_have_text(reason)
    assert saved["sacrifice_reason"] == reason


@pytest.mark.browser
@pytest.mark.parametrize("domain_count", [3, 20])
def test_current_domain_overview_still_handles_domain_counts(page: Page, live_app: str, domain_count: int) -> None:
    domain_names = [f"Domain {index}" for index in range(1, domain_count + 1)]
    seed_workspace(live_app, domain_names)

    page.goto(live_app)

    expect(page.locator("#current-groups .current-row")).to_have_count(domain_count)
    expect(page.get_by_role("button", name="Edit review")).to_be_visible()
