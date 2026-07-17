from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.request import Request, urlopen
from wsgiref.simple_server import WSGIServer, make_server

import pytest
from playwright.sync_api import Locator, Page, expect, sync_playwright

from tests.support import MutableClock
from traect.api.app import build_app


class LiveApp(str):
    clock: MutableClock

    def __new__(cls, value: str, clock: MutableClock) -> LiveApp:
        instance = super().__new__(cls, value)
        instance.clock = clock
        return instance


@pytest.fixture
def page() -> Iterator[Page]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(service_workers="block")
        page = context.new_page()
        try:
            yield page
        finally:
            context.close()
            browser.close()


@pytest.fixture
def live_app(tmp_path: Path) -> Iterator[LiveApp]:
    clock = MutableClock(datetime(2026, 7, 17, 12, tzinfo=UTC))
    app = build_app(f"sqlite:///{tmp_path / 'browser.db'}", clock=clock)
    server: WSGIServer = make_server("127.0.0.1", 0, app)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield LiveApp(f"http://127.0.0.1:{server.server_port}", clock)
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
    base_url: LiveApp,
    workspace_id: int,
    domains: dict[str, int],
    *,
    focus: str | None = None,
    sacrificed: str | None = None,
    reason: str | None = None,
    ignored: set[str] | None = None,
) -> dict[str, Any]:
    iso_year, iso_week, _ = base_url.clock().date().isocalendar()
    return save_week_review(
        base_url,
        workspace_id,
        domains,
        iso_year,
        iso_week,
        focus=focus,
        sacrificed=sacrificed,
        reason=reason,
        ignored=ignored,
    )


def save_week_review(
    base_url: LiveApp,
    workspace_id: int,
    domains: dict[str, int],
    iso_year: int,
    iso_week: int,
    *,
    focus: str | None = None,
    sacrificed: str | None = None,
    reason: str | None = None,
    ignored: set[str] | None = None,
    conditions: dict[str, str] | None = None,
) -> dict[str, Any]:
    ignored = ignored or set()
    conditions = conditions or {}
    states = [
        {
            "domain_id": domain_id,
            "mode": "focus" if name == focus else ("ignore" if name in ignored else "maintain"),
            "status": conditions.get(name, "good"),
            "comment": None,
        }
        for name, domain_id in domains.items()
    ]
    previous_now = base_url.clock.value
    provisional_date = date.fromisocalendar(iso_year, iso_week, 3)
    base_url.clock.value = datetime.combine(provisional_date, datetime.min.time(), tzinfo=UTC)
    try:
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
    finally:
        base_url.clock.value = previous_now


def tradeoff_value(page: Page, field: str) -> Locator:
    return page.locator(f"[data-tradeoff-field='{field}'] dd")


@pytest.mark.browser
def test_onboarding_to_weekly_review(page: Page, live_app: LiveApp) -> None:
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

    page.get_by_role("button", name="Start review").click()
    expect(page.get_by_text("This review remains provisional until the week ends.", exact=False)).to_be_visible()
    what_gave_way = page.locator("select[name='sacrificed_domain_id']")
    expect(what_gave_way).to_be_disabled()
    page.locator("select[name^='mode_']").first.select_option("focus")
    expect(what_gave_way).to_be_enabled()
    page.locator("select[name='focus_domain_id']").select_option(label="Work")
    page.get_by_role("button", name="Save").click()

    expect(current_groups.get_by_role("heading", name="Focus")).to_be_visible()
    expect(current_groups.get_by_text("Work", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Timeline")).to_be_visible()
    assert page_errors == []


@pytest.mark.browser
def test_current_shows_full_saved_tradeoff_as_read_only_summary(page: Page, live_app: LiveApp) -> None:
    workspace_id, domains = seed_workspace(live_app, ["Work", "Health"])
    save_current_review(live_app, workspace_id, domains, focus="Work", sacrificed="Health", reason="Release")

    page.goto(live_app)

    tradeoff = page.locator("#current-tradeoff")
    expect(tradeoff).to_be_visible()
    expect(tradeoff.get_by_role("heading", name="This week")).to_be_visible()
    expect(tradeoff_value(page, "focus")).to_have_text("Work")
    expect(tradeoff_value(page, "sacrifice")).to_have_text("Health")
    expect(tradeoff_value(page, "reason")).to_have_text("Release")
    expect(page.locator("#current-lifecycle")).to_have_text("Provisional · changes can still be recorded this week")
    expect(tradeoff.locator("input, select, textarea, button")).to_have_count(0)
    expect(page.get_by_role("button", name="Edit review")).to_have_count(1)


@pytest.mark.browser
def test_current_shows_neutral_state_when_review_has_no_primary_focus(page: Page, live_app: LiveApp) -> None:
    workspace_id, domains = seed_workspace(live_app, ["Work", "Health"])
    save_current_review(live_app, workspace_id, domains)

    page.goto(live_app)

    tradeoff = page.locator("#current-tradeoff")
    expect(tradeoff.get_by_text("No primary focus recorded.", exact=True)).to_be_visible()
    expect(tradeoff.locator(".tradeoff-row")).to_have_count(0)


@pytest.mark.browser
def test_current_shows_none_recorded_when_focus_has_no_sacrifice(page: Page, live_app: LiveApp) -> None:
    workspace_id, domains = seed_workspace(live_app, ["Work", "Health"])
    save_current_review(live_app, workspace_id, domains, focus="Work")

    page.goto(live_app)

    expect(tradeoff_value(page, "focus")).to_have_text("Work")
    expect(tradeoff_value(page, "sacrifice")).to_have_text("None recorded")
    expect(page.locator("[data-tradeoff-field='reason']")).to_have_count(0)


@pytest.mark.browser
def test_current_omits_why_when_saved_tradeoff_has_no_reason(page: Page, live_app: LiveApp) -> None:
    workspace_id, domains = seed_workspace(live_app, ["Work", "Health"])
    save_current_review(live_app, workspace_id, domains, focus="Work", sacrificed="Health")

    page.goto(live_app)

    expect(tradeoff_value(page, "focus")).to_have_text("Work")
    expect(tradeoff_value(page, "sacrifice")).to_have_text("Health")
    expect(page.locator("[data-tradeoff-field='reason']")).to_have_count(0)


@pytest.mark.browser
def test_current_hides_tradeoff_when_week_has_no_saved_review(page: Page, live_app: LiveApp) -> None:
    seed_workspace(live_app, ["Work", "Health"])

    page.goto(live_app)

    expect(page.locator("#current-tradeoff")).to_be_hidden()
    expect(page.get_by_role("button", name="Start review")).to_be_visible()


@pytest.mark.browser
def test_current_does_not_infer_sacrifice_from_ignored_domain(page: Page, live_app: LiveApp) -> None:
    workspace_id, domains = seed_workspace(live_app, ["Work", "Health"])
    save_current_review(live_app, workspace_id, domains, focus="Work", ignored={"Health"})

    page.goto(live_app)

    expect(tradeoff_value(page, "sacrifice")).to_have_text("None recorded")
    expect(tradeoff_value(page, "sacrifice")).not_to_have_text("Health")


@pytest.mark.browser
def test_current_wraps_long_tradeoff_values_on_mobile_without_changing_data(page: Page, live_app: LiveApp) -> None:
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
def test_current_domain_overview_still_handles_domain_counts(page: Page, live_app: LiveApp, domain_count: int) -> None:
    domain_names = [f"Domain {index}" for index in range(1, domain_count + 1)]
    seed_workspace(live_app, domain_names)

    page.goto(live_app)

    expect(page.locator("#current-groups .current-row")).to_have_count(domain_count)
    expect(page.get_by_role("button", name="Start review")).to_be_visible()


@pytest.mark.browser
def test_timeline_empty_state_and_viewing_it_does_not_create_a_review(page: Page, live_app: LiveApp) -> None:
    workspace_id, _ = seed_workspace(live_app, ["Work"])

    page.goto(live_app)
    page.get_by_role("button", name="Timeline").click()

    expect(page.get_by_text("No weekly reviews yet.", exact=True)).to_be_visible()
    history_hint = page.get_by_text("The history will appear here after the first review is saved.", exact=True)
    expect(history_hint).to_be_visible()
    expect(page.get_by_role("button", name="Back to Current")).to_be_visible()
    assert request_json(live_app, "GET", f"/workspaces/{workspace_id}/weeks")["items"] == []


@pytest.mark.browser
def test_timeline_orders_weeks_and_renders_tradeoff_variants(page: Page, live_app: LiveApp) -> None:
    workspace_id, domains = seed_workspace(live_app, ["Work", "Health"])
    save_week_review(live_app, workspace_id, domains, 2026, 25)
    save_week_review(live_app, workspace_id, domains, 2026, 26, focus="Work")
    save_week_review(live_app, workspace_id, domains, 2026, 27, focus="Work", sacrificed="Health")
    save_week_review(
        live_app,
        workspace_id,
        domains,
        2026,
        28,
        focus="Work",
        sacrificed="Health",
        reason="Release",
    )

    page.goto(live_app)
    page.get_by_role("button", name="Timeline").click()

    weeks = page.locator(".timeline-week")
    expect(weeks).to_have_count(4)
    expect(weeks.locator(".timeline-week-heading")).to_have_text(
        ["Week 28, 2026", "Week 27, 2026", "Week 26, 2026", "Week 25, 2026"]
    )
    expect(weeks.nth(0).locator("[data-tradeoff-field='reason'] dd")).to_have_text("Release")
    expect(weeks.nth(1).locator("[data-tradeoff-field='sacrifice'] dd")).to_have_text("Health")
    expect(weeks.nth(1).locator("[data-tradeoff-field='reason']")).to_have_count(0)
    expect(weeks.nth(2).locator("[data-tradeoff-field='sacrifice'] dd")).to_have_text("None recorded")
    expect(weeks.nth(0)).to_have_attribute("open", "")
    expect(weeks.nth(1)).to_have_attribute("open", "")
    expect(weeks.nth(2)).to_have_attribute("open", "")
    expect(weeks.nth(3)).not_to_have_attribute("open", "")
    expect(weeks.nth(3).locator(".timeline-week-compact-tradeoff")).to_have_text("No primary focus")
    weeks.nth(3).locator(".timeline-week-summary").press("Enter")
    expect(weeks.nth(3).get_by_text("No primary focus recorded.", exact=True)).to_be_visible()
    expect(weeks.nth(3).locator(".tradeoff-row")).to_have_count(0)


@pytest.mark.browser
def test_timeline_places_saved_current_week_first(page: Page, live_app: LiveApp) -> None:
    workspace_id, domains = seed_workspace(live_app, ["Work"])
    today = live_app.clock().date()
    current_year, current_week, _ = today.isocalendar()
    prior_year, prior_week, _ = (today - timedelta(days=7)).isocalendar()
    save_week_review(live_app, workspace_id, domains, prior_year, prior_week)
    save_current_review(live_app, workspace_id, domains, focus="Work")

    page.goto(live_app)
    page.get_by_role("button", name="Timeline").click()

    headings = page.locator(".timeline-week-heading")
    expect(headings).to_have_count(2)
    expect(headings.first).to_have_text(f"Week {current_week}, {current_year}")
    weeks = page.locator(".timeline-week")
    expect(weeks.nth(0).locator(".timeline-week-lifecycle")).to_have_text("Provisional")
    expect(weeks.nth(1).locator(".timeline-week-lifecycle")).to_have_text("Final")
    expect(weeks.nth(0).get_by_role("button", name="Edit review")).to_be_visible()
    expect(weeks.nth(1).get_by_role("button", name="Edit review")).to_have_count(0)


@pytest.mark.browser
def test_timeline_keeps_attention_condition_and_historical_domains_separate(page: Page, live_app: LiveApp) -> None:
    workspace_id, domains = seed_workspace(live_app, ["Work", "Health", "Sport"])
    save_week_review(
        live_app,
        workspace_id,
        domains,
        2026,
        28,
        focus="Work",
        sacrificed="Health",
        ignored={"Sport"},
        conditions={"Work": "good", "Health": "warning", "Sport": "critical"},
    )
    request_json(live_app, "PATCH", f"/domains/{domains['Work']}", {"name": "Career"})
    request_json(live_app, "POST", f"/domains/{domains['Health']}/archive")
    request_json(live_app, "POST", f"/workspaces/{workspace_id}/domains", {"name": "Rest"})

    page.goto(live_app)
    page.get_by_role("button", name="Timeline").click()

    week = page.locator(".timeline-week")
    expect(week.locator(".timeline-domain-name", has_text="Work")).to_be_visible()
    expect(week.locator(".timeline-domain-name", has_text="Health")).to_be_visible()
    expect(week.locator(".timeline-domain-name", has_text="Sport")).to_be_visible()
    expect(week.get_by_text("Career", exact=True)).to_have_count(0)
    expect(week.get_by_text("Rest", exact=True)).to_have_count(0)
    primary_attention = week.locator(".timeline-domain-row").nth(0).locator("[aria-label='Attention: Primary focus']")
    expect(primary_attention).to_be_visible()
    expect(week.locator("[data-status='warning'][aria-label='Condition: At Risk']")).to_be_visible()
    expect(week.locator("[data-status='critical'][aria-label='Condition: Critical']")).to_be_visible()


@pytest.mark.browser
@pytest.mark.parametrize("week_count", [1, 5, 20, 52])
def test_timeline_handles_expected_history_sizes(page: Page, live_app: LiveApp, week_count: int) -> None:
    workspace_id, domains = seed_workspace(live_app, ["Work"])
    for week in range(1, week_count + 1):
        save_week_review(live_app, workspace_id, domains, 2025, week)

    page.goto(live_app)
    page.get_by_role("button", name="Timeline").click()

    expect(page.locator(".timeline-week")).to_have_count(week_count)


@pytest.mark.browser
def test_timeline_survives_malformed_week_and_preserves_long_mobile_text(page: Page, live_app: LiveApp) -> None:
    long_name = "Long historical Domain name " + "D" * 85
    long_reason = "R" * 240
    workspace_id, domains = seed_workspace(live_app, [long_name])
    save_week_review(live_app, workspace_id, domains, 2026, 28, focus=long_name, reason=None)

    page.route(
        f"{live_app}/workspaces/{workspace_id}/weeks",
        lambda route: route.fulfill(
            json={
                "items": [
                    {
                        "iso_year": 2026,
                        "iso_week": 28,
                        "focus_domain_id": domains[long_name],
                        "focus_domain_name": long_name,
                        "sacrificed_domain_id": None,
                        "sacrificed_domain_name": None,
                        "sacrifice_reason": long_reason,
                        "states": [
                            {
                                "domain_id": domains[long_name],
                                "domain_name": long_name,
                                "mode": "focus",
                                "status": "good",
                            },
                            {"domain_id": 999, "mode": "broken", "status": "good"},
                        ],
                    }
                ]
            }
        ),
    )
    page.set_viewport_size({"width": 375, "height": 760})

    page.goto(live_app)
    page.get_by_role("button", name="Timeline").click()

    timeline = page.locator("#timeline-view")
    expect(timeline.get_by_text(long_name, exact=True)).to_have_count(2)
    expect(timeline.locator("[data-tradeoff-field='reason'] dd")).to_have_text(long_reason)
    expect(timeline.get_by_text("Some saved data could not be shown:", exact=False)).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


@pytest.mark.browser
def test_timeline_failed_request_is_actionable(page: Page, live_app: LiveApp) -> None:
    workspace_id, _ = seed_workspace(live_app, ["Work"])
    page.route(
        f"{live_app}/workspaces/{workspace_id}/weeks",
        lambda route: route.fulfill(status=500, json={"error": "history unavailable"}),
    )

    page.goto(live_app)
    page.get_by_role("button", name="Timeline").click()

    expect(page.get_by_text("Timeline could not be loaded. Try again.", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Retry")).to_be_visible()


@pytest.mark.browser
def test_current_uses_backend_week_context_instead_of_browser_date(page: Page, live_app: LiveApp) -> None:
    workspace_id, _ = seed_workspace(live_app, ["Work"])
    page.route(
        f"{live_app}/workspaces/{workspace_id}/weeks/current-context",
        lambda route: route.fulfill(
            json={
                "iso_year": 2020,
                "iso_week": 53,
                "lifecycle": "provisional",
                "editable": True,
                "review": None,
            }
        ),
    )

    page.goto(live_app)

    expect(page.locator("#week-meta")).to_have_text("Week 53, 2020")
    expect(page.get_by_role("button", name="Start review")).to_be_visible()


@pytest.mark.browser
def test_final_update_error_is_shown_in_edit_review(page: Page, live_app: LiveApp) -> None:
    workspace_id, _ = seed_workspace(live_app, ["Work"])
    page.route(
        f"{live_app}/workspaces/{workspace_id}/weeks/2026/29",
        lambda route: route.fulfill(
            status=409,
            json={"error": "This weekly review is final and can no longer be edited."},
        ),
    )

    page.goto(live_app)
    page.get_by_role("button", name="Start review").click()
    page.get_by_role("button", name="Save").click()

    expect(page.locator("#review-status")).to_have_text("This weekly review is final and can no longer be edited.")
    assert request_json(live_app, "GET", f"/workspaces/{workspace_id}/weeks")["items"] == []
