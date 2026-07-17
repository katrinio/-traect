from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from threading import Thread
from wsgiref.simple_server import WSGIServer, make_server

import pytest
from playwright.sync_api import Page, expect, sync_playwright

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
