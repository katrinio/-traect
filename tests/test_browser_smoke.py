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
    paused: set[str] | None = None,
    conditions: dict[str, str] | None = None,
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
        paused=paused,
        conditions=conditions,
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
    paused: set[str] | None = None,
    conditions: dict[str, str] | None = None,
) -> dict[str, Any]:
    paused = paused or set()
    conditions = conditions or {}
    states = [
        {
            "domain_id": domain_id,
            "attention": "primary_focus" if name == focus else ("paused" if name in paused else "maintained"),
            "condition": conditions.get(name, "stable"),
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


def set_minimum_acceptable_level(base_url: str, domain_id: int, value: str | None) -> dict[str, Any]:
    return request_json(
        base_url,
        "PATCH",
        f"/domains/{domain_id}",
        {"minimum_acceptable_level": value},
    )


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
    page.locator("select[name^='attention_']").first.select_option("primary_focus")
    expect(what_gave_way).to_be_enabled()
    page.get_by_role("button", name="Save").click()

    expect(current_groups.get_by_role("heading", name="Primary focus")).to_be_visible()
    expect(current_groups.get_by_text("Work", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Timeline")).to_be_visible()
    assert page_errors == []


@pytest.mark.browser
def test_domain_minimum_level_can_be_saved_and_cleared(page: Page, live_app: LiveApp) -> None:
    workspace_id, domains = seed_workspace(live_app, ["Health"])
    page.goto(live_app)
    page.get_by_role("button", name="Domains").click()

    minimum = page.get_by_role("textbox", name="Minimum acceptable level")
    minimum.fill("  Essential care remains manageable.\nAppointments stay visible.  ")
    minimum.press("Tab")

    expect(minimum).to_have_value("Essential care remains manageable.\nAppointments stay visible.")
    saved = request_json(live_app, "GET", f"/workspaces/{workspace_id}/domains")["items"][0]
    assert saved["minimum_acceptable_level"] == "Essential care remains manageable.\nAppointments stay visible."

    minimum.fill("")
    minimum.press("Tab")
    expect(minimum).to_have_value("")
    cleared = request_json(live_app, "GET", f"/workspaces/{workspace_id}/domains")["items"][0]
    assert cleared["id"] == domains["Health"]
    assert cleared["minimum_acceptable_level"] is None


@pytest.mark.browser
def test_edit_review_shows_minimum_level_only_for_configured_domain(page: Page, live_app: LiveApp) -> None:
    _, domains = seed_workspace(live_app, ["Health", "Work"])
    set_minimum_acceptable_level(live_app, domains["Health"], "Keep essential care manageable.")

    page.goto(live_app)
    page.get_by_role("button", name="Start review").click()

    health = page.locator("#review-domains .domain").filter(has_text="Health")
    work = page.locator("#review-domains .domain").filter(has_text="Work")
    expect(health.get_by_text("Minimum acceptable level", exact=True)).to_be_visible()
    expect(health.get_by_text("Keep essential care manageable.", exact=True)).to_be_visible()
    expect(health.get_by_role("combobox", name="Condition now")).to_have_attribute(
        "aria-describedby",
        f"minimum-level-context-{domains['Health']}",
    )
    expect(work.locator(".minimum-level-context")).to_have_count(0)
    expect(page.locator("#current-view .minimum-level-context")).to_have_count(0)


@pytest.mark.browser
def test_minimum_level_renders_multiline_html_like_text_safely_on_mobile(page: Page, live_app: LiveApp) -> None:
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    _, domains = seed_workspace(live_app, ["Home"])
    value = "<img src=x onerror=alert(1)>\n" + "A usable fallback state " * 16
    set_minimum_acceptable_level(live_app, domains["Home"], value)

    page.set_viewport_size({"width": 360, "height": 760})
    page.goto(live_app)
    page.get_by_role("button", name="Start review").click()

    context = page.locator(".minimum-level-context")
    expect(context).to_contain_text("<img src=x onerror=alert(1)>")
    expect(context.locator("img")).to_have_count(0)
    assert context.evaluate("element => element.scrollWidth <= element.clientWidth")
    assert page_errors == []


@pytest.mark.browser
def test_edit_review_changes_primary_focus_through_attention_only(page: Page, live_app: LiveApp) -> None:
    workspace_id, domains = seed_workspace(live_app, ["Work", "Health"])
    save_current_review(
        live_app,
        workspace_id,
        domains,
        focus="Work",
        conditions={"Work": "stable", "Health": "critical"},
    )
    page.goto(live_app)
    page.get_by_role("button", name="Edit review").click()

    expect(page.locator("select[name='focus_domain_id']")).to_have_count(0)
    page.locator(f"select[name='attention_{domains['Health']}']").select_option("primary_focus")
    page.get_by_role("button", name="Save").click()

    saved = request_json(live_app, "GET", f"/workspaces/{workspace_id}/weeks/current-context")["review"]
    states = {state["domain_name"]: state for state in saved["states"]}
    assert saved["main_focus"] == {"domain_id": domains["Health"], "name": "Health"}
    assert states["Work"]["attention"] == "maintained"
    assert states["Work"]["condition"] == "stable"
    assert states["Health"]["attention"] == "primary_focus"
    assert states["Health"]["condition"] == "critical"
    assert "focus_domain_id" not in saved


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
def test_current_does_not_infer_sacrifice_from_paused_domain(page: Page, live_app: LiveApp) -> None:
    workspace_id, domains = seed_workspace(live_app, ["Work", "Health"])
    save_current_review(live_app, workspace_id, domains, focus="Work", paused={"Health"})

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
        paused={"Sport"},
        conditions={"Work": "stable", "Health": "at_risk", "Sport": "critical"},
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
    expect(week.locator("[data-condition='at_risk'][aria-label='Condition: At risk']")).to_be_visible()
    expect(week.locator("[data-condition='critical'][aria-label='Condition: Critical']")).to_be_visible()


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
                        "main_focus": {"domain_id": domains[long_name], "name": long_name},
                        "sacrificed_domain_id": None,
                        "sacrificed_domain_name": None,
                        "sacrifice_reason": long_reason,
                        "states": [
                            {
                                "domain_id": domains[long_name],
                                "domain_name": long_name,
                                "attention": "primary_focus",
                                "condition": "stable",
                            },
                            {"domain_id": 999, "attention": "broken", "condition": "stable"},
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
    expect(timeline.locator(".timeline-entries").get_by_text(long_name, exact=True)).to_have_count(2)
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
def test_focus_history_empty_state_stays_out_of_current(page: Page, live_app: LiveApp) -> None:
    seed_workspace(live_app, ["Work", "Health"])

    page.goto(live_app)
    expect(page.get_by_role("heading", name="Focus history")).not_to_be_visible()
    page.get_by_role("button", name="Timeline").click()

    expect(page.get_by_role("heading", name="Focus history")).to_be_visible()
    expect(page.get_by_text("No focus history yet.", exact=True)).to_be_visible()
    expect(
        page.get_by_text("Primary focus will appear here after weekly reviews are saved.", exact=True)
    ).to_be_visible()


@pytest.mark.browser
def test_focus_history_renders_distribution_details_sequence_and_archived_domain(
    page: Page,
    live_app: LiveApp,
) -> None:
    workspace_id, domains = seed_workspace(live_app, ["Work", "Health", "Home"])
    save_week_review(live_app, workspace_id, domains, 2026, 23, focus="Work")
    save_week_review(live_app, workspace_id, domains, 2026, 25, focus="Health")
    save_week_review(live_app, workspace_id, domains, 2026, 27, focus="Work")
    save_week_review(live_app, workspace_id, domains, 2026, 29)
    request_json(live_app, "POST", f"/domains/{domains['Work']}/archive")

    page.goto(live_app)
    page.get_by_role("button", name="Timeline").click()
    history = page.locator(".focus-history")
    summary = history.locator(".focus-history-summary")

    expect(summary.locator("dd")).to_have_text(["4", "3", "1"])
    expect(history.get_by_text("Percentages use all reviewed weeks", exact=False)).to_be_visible()
    work = history.locator(".focus-domain-history", has_text="Work")
    health = history.locator(".focus-domain-history", has_text="Health")
    expect(work.get_by_text("Archived", exact=True)).to_be_visible()
    expect(work.get_by_text("2 of 4 reviewed weeks · 50%", exact=True)).to_be_visible()
    expect(health.get_by_text("1 of 4 reviewed weeks · 25%", exact=True)).to_be_visible()
    expect(work.locator(".focus-domain-bar")).to_have_attribute(
        "aria-label",
        "Work: 2 of 4 reviewed weeks, 50%",
    )
    expect(work.locator(".focus-domain-bar-fill")).to_have_attribute("style", "width: 50%;")
    expect(history.get_by_text("No Primary focus in this period", exact=True)).to_be_visible()
    expect(history.get_by_text("Home", exact=True)).to_be_visible()

    work.locator("summary").click()
    expect(work.get_by_text("Week 27, 2026", exact=True)).to_be_visible()
    expect(work.get_by_text("Week 23, 2026", exact=True)).to_be_visible()
    expect(work.get_by_text("Week 25, 2026", exact=True)).to_have_count(0)

    sequence = history.locator(".focus-history-sequence")
    current_link = sequence.get_by_role("link", name="Open saved review for Week 29, 2026")
    expect(current_link).to_contain_text("No Primary focus · Provisional")
    current_target = current_link.get_attribute("href")
    assert current_target is not None
    current_link.click()
    expect(page.locator(current_target)).to_have_attribute("open", "")
    assert "dominated" not in history.inner_text().lower()
    assert "neglected" not in history.inner_text().lower()
    assert "should" not in history.inner_text().lower()


@pytest.mark.browser
def test_focus_history_range_uses_reviewed_weeks_and_updates_the_summary(page: Page, live_app: LiveApp) -> None:
    workspace_id, domains = seed_workspace(live_app, ["Work"])
    for iso_week in range(16, 29):
        save_week_review(live_app, workspace_id, domains, 2026, iso_week, focus="Work")

    page.goto(live_app)
    page.get_by_role("button", name="Timeline").click()
    history = page.locator(".focus-history")
    summary_values = history.locator(".focus-history-summary dd")
    expect(summary_values).to_have_text(["12", "12", "0"])

    history.get_by_label("Range").select_option("26")
    expect(summary_values).to_have_text(["13", "13", "0"])
    expect(history.get_by_label("Range")).to_have_value("26")


@pytest.mark.browser
def test_focus_history_integrity_notice_uses_backend_metadata(page: Page, live_app: LiveApp) -> None:
    seed_workspace(live_app, ["Work"])
    page.route(
        "**/history/focus?*",
        lambda route: route.fulfill(
            json={
                "range": {"type": "reviewed_weeks", "value": 12},
                "summary": {
                    "reviewed_week_count": 1,
                    "focused_week_count": 0,
                    "no_focus_week_count": 1,
                    "excluded_week_count": 1,
                },
                "excluded_reasons": {"multiple_primary_focus": 1},
                "domains": [],
                "zero_focus_domains": [{"domain_id": 1, "name": "Work"}],
                "weeks": [
                    {
                        "week_id": 1,
                        "iso_year": 2026,
                        "iso_week": 28,
                        "lifecycle": "final",
                        "focus": None,
                    }
                ],
            }
        ),
    )

    page.goto(live_app)
    page.get_by_role("button", name="Timeline").click()

    expect(
        page.get_by_text("1 saved week was excluded because focus data is inconsistent.", exact=True)
    ).to_be_visible()
    expect(page.get_by_text("No reviewed week in this period has a Primary focus.", exact=True)).to_be_visible()


@pytest.mark.browser
def test_condition_history_empty_state_and_domain_selector_stay_in_timeline(page: Page, live_app: LiveApp) -> None:
    seed_workspace(live_app, ["Work", "Health"])

    page.goto(live_app)
    expect(page.get_by_role("heading", name="Condition history")).not_to_be_visible()
    page.get_by_role("button", name="Timeline").click()
    page.get_by_role("tab", name="Condition").click()

    expect(page.get_by_role("heading", name="Condition history")).to_be_visible()
    domain_select = page.locator("#condition-history-domain")
    expect(domain_select).to_have_value("1")
    expect(domain_select.locator("option")).to_have_text(["Work", "Health"])
    expect(page.get_by_text("No Condition history yet.", exact=True)).to_be_visible()
    expect(page.get_by_role("tab", name="Condition")).to_have_attribute("aria-selected", "true")
    expect(page.get_by_role("tab", name="Focus")).to_have_attribute("aria-selected", "false")
    page.get_by_role("tab", name="Trade-offs").click()
    expect(page.get_by_text("No trade-off history yet.", exact=True)).to_be_visible()
    expect(
        page.get_by_text("Recorded weekly trade-offs will appear here after reviews are saved.", exact=True)
    ).to_be_visible()


@pytest.mark.browser
def test_condition_history_renders_distribution_gaps_changes_and_archived_domain(
    page: Page,
    live_app: LiveApp,
) -> None:
    workspace_id, domains = seed_workspace(live_app, ["Health", "Work"])
    save_week_review(live_app, workspace_id, domains, 2026, 25, conditions={"Health": "stable"})
    save_week_review(live_app, workspace_id, domains, 2026, 26, conditions={"Health": "at_risk"})
    request_json(live_app, "POST", f"/domains/{domains['Health']}/archive")
    save_week_review(live_app, workspace_id, {"Work": domains["Work"]}, 2026, 27)
    request_json(live_app, "POST", f"/domains/{domains['Health']}/restore")
    save_week_review(live_app, workspace_id, domains, 2026, 28, conditions={"Health": "critical"})
    request_json(live_app, "POST", f"/domains/{domains['Health']}/archive")
    save_current_review(live_app, workspace_id, {"Work": domains["Work"]})

    page.goto(live_app)
    page.get_by_role("button", name="Timeline").click()
    page.get_by_role("tab", name="Condition").click()
    panel = page.locator("#condition-history-panel")
    panel.get_by_label("Domain").select_option(str(domains["Health"]))

    expect(panel.get_by_text("Archived", exact=True)).to_be_visible()
    expect(panel.get_by_text("Critical · Week 28, 2026", exact=False)).to_be_visible()
    expect(panel.get_by_text("Present in 3 of 5 reviewed weeks", exact=False)).to_be_visible()
    expect(panel.locator(".condition-summary dd")).to_have_text(["3", "1 · 33%", "1 · 33%", "1 · 33%"])
    weeks = panel.locator(".condition-week")
    expect(weeks).to_have_count(5)
    expect(weeks.nth(2)).to_contain_text("Week 27, 2026")
    expect(weeks.nth(2)).to_contain_text("Absent from snapshot")
    expect(weeks.nth(4)).to_contain_text("Provisional")
    expect(panel.get_by_text("Changed from Stable to At risk between Weeks 25 and 26.", exact=True)).to_be_visible()
    expect(panel.get_by_text("Changed from At risk to Critical", exact=False)).to_have_count(0)

    week_28 = panel.get_by_role("link", name="Open saved review for Week 28, 2026")
    target = week_28.get_attribute("href")
    assert target is not None
    week_28.click()
    expect(page.locator(target)).to_have_attribute("open", "")

    copy = panel.inner_text().lower()
    for forbidden in ["caused", "because", "improved", "worsened", "should", "recovery"]:
        assert forbidden not in copy


@pytest.mark.browser
def test_condition_history_range_is_shared_with_focus_history(page: Page, live_app: LiveApp) -> None:
    workspace_id, domains = seed_workspace(live_app, ["Work"])
    for iso_week in range(16, 29):
        save_week_review(live_app, workspace_id, domains, 2026, iso_week, conditions={"Work": "stable"})

    page.goto(live_app)
    page.get_by_role("button", name="Timeline").click()
    page.get_by_role("tab", name="Condition").click()
    panel = page.locator("#condition-history-panel")
    expect(panel.get_by_text("Present in 12 of 12 reviewed weeks", exact=False)).to_be_visible()

    page.get_by_label("Range").select_option("26")
    expect(panel.get_by_text("Present in 13 of 13 reviewed weeks", exact=False)).to_be_visible()
    page.get_by_role("tab", name="Focus").click()
    expect(page.locator(".focus-history-summary dd")).to_have_text(["13", "0", "13"])
    expect(page.get_by_label("Range")).to_have_value("26")


@pytest.mark.browser
def test_condition_history_excluded_state_is_explicit(page: Page, live_app: LiveApp) -> None:
    seed_workspace(live_app, ["Work"])
    page.route(
        "**/history/condition?*",
        lambda route: route.fulfill(
            json={
                "range": {"type": "reviewed_weeks", "value": 12},
                "domains": [
                    {
                        "domain_id": 1,
                        "name": "Work",
                        "archived": False,
                        "unavailable": False,
                        "recorded_state_count": 0,
                        "latest_record": None,
                    }
                ],
                "integrity": {"excluded_week_count": 0, "excluded_reasons": {}},
                "history": {
                    "domain": {
                        "domain_id": 1,
                        "name": "Work",
                        "archived": False,
                        "unavailable": False,
                        "recorded_state_count": 0,
                        "latest_record": None,
                    },
                    "summary": {
                        "reviewed_week_count": 1,
                        "recorded_state_count": 0,
                        "present_state_count": 1,
                        "absent_state_count": 0,
                        "excluded_state_count": 1,
                        "coverage_share": 1.0,
                        "latest_record": None,
                        "counts": {"stable": 0, "at_risk": 0, "critical": 0},
                        "shares": {"stable": 0.0, "at_risk": 0.0, "critical": 0.0},
                    },
                    "weeks": [
                        {
                            "week_id": 1,
                            "iso_year": 2026,
                            "iso_week": 28,
                            "lifecycle": "final",
                            "presence": "excluded",
                            "condition": None,
                            "excluded_reason": "invalid_condition",
                        }
                    ],
                    "transitions": [],
                    "runs": [],
                    "paused_sequences": {
                        "current_streak": {"active": False, "length": 0, "started": None},
                        "longest_streak": None,
                        "streaks": [],
                        "excluded_state_count": 0,
                        "excluded_reasons": {},
                        "observations": [],
                    },
                    "observations": [
                        {"code": "condition_excluded", "text": "1 Condition record could not be interpreted safely."}
                    ],
                    "excluded_reasons": {"invalid_condition": 1},
                },
            }
        ),
    )

    page.goto(live_app)
    page.get_by_role("button", name="Timeline").click()
    page.get_by_role("tab", name="Condition").click()

    expect(
        page.get_by_text("1 Condition record was excluded because historical data is inconsistent.", exact=True)
    ).to_be_visible()
    expect(page.locator(".condition-week-excluded")).to_contain_text("Excluded historical state")
    expect(
        page.get_by_text(
            "Condition history for this Domain cannot be summarized until its historical data is reviewed.",
            exact=True,
        )
    ).to_be_visible()


@pytest.mark.browser
def test_paused_history_renders_sequences_links_archival_and_observational_copy(
    page: Page,
    live_app: LiveApp,
) -> None:
    workspace_id, domains = seed_workspace(live_app, ["Learning"])
    for iso_week in (25, 26, 27):
        save_week_review(live_app, workspace_id, domains, 2026, iso_week, paused={"Learning"})
    save_week_review(live_app, workspace_id, domains, 2026, 28)
    save_current_review(live_app, workspace_id, domains, paused={"Learning"})
    request_json(live_app, "POST", f"/domains/{domains['Learning']}/archive")

    page.goto(live_app)
    page.get_by_role("button", name="Timeline").click()
    page.get_by_role("tab", name="Condition").click()
    panel = page.locator("#condition-history-panel")

    expect(panel.get_by_text("Archived", exact=True)).to_be_visible()
    expect(panel.get_by_role("heading", name="Paused history")).to_be_visible()
    expect(panel.get_by_text("1 consecutive reviewed week · Started Week 29, 2026", exact=True)).to_be_visible()
    expect(
        panel.get_by_text("3 consecutive reviewed weeks · Week 25, 2026 → Week 27, 2026", exact=True)
    ).to_be_visible()
    expect(panel.locator(".paused-sequence-item")).to_have_count(2)
    week_link = panel.get_by_role("link", name="Open paused sequence review for Week 26, 2026")
    expect(week_link).to_have_text("Week 26, 2026 · Paused")
    week_link.click()
    expect(page.locator("#timeline-week-2")).to_have_attribute("open", "")

    copy = panel.locator(".paused-sequences").inner_text().lower()
    for forbidden in ["neglect", "abandon", "dormant", "too long", "should", "reactivate"]:
        assert forbidden not in copy

    page.set_viewport_size({"width": 375, "height": 800})
    assert panel.locator(".paused-sequence-summaries").evaluate(
        "element => getComputedStyle(element).gridTemplateColumns.split(' ').length === 1"
    )
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


@pytest.mark.browser
def test_paused_history_has_calm_empty_state_when_attention_was_never_paused(
    page: Page,
    live_app: LiveApp,
) -> None:
    workspace_id, domains = seed_workspace(live_app, ["Work"])
    save_current_review(live_app, workspace_id, domains)

    page.goto(live_app)
    page.get_by_role("button", name="Timeline").click()
    page.get_by_role("tab", name="Condition").click()

    expect(page.get_by_text("No paused sequences have been recorded.", exact=True)).to_be_visible()


@pytest.mark.browser
def test_tradeoff_patterns_render_rankings_breakdowns_reverse_pairs_and_sources(
    page: Page,
    live_app: LiveApp,
) -> None:
    workspace_id, domains = seed_workspace(live_app, ["Work", "Social"])
    save_week_review(live_app, workspace_id, domains, 2026, 25, focus="Work", sacrificed="Social")
    save_week_review(live_app, workspace_id, domains, 2026, 26, focus="Work", sacrificed="Social")
    save_week_review(live_app, workspace_id, domains, 2026, 27, focus="Social", sacrificed="Work")
    save_week_review(live_app, workspace_id, domains, 2026, 28, focus="Work")
    save_current_review(live_app, workspace_id, domains, focus="Work", sacrificed="Social")
    request_json(live_app, "POST", f"/domains/{domains['Social']}/archive")

    page.goto(live_app)
    page.get_by_role("button", name="Timeline").click()
    page.get_by_role("tab", name="Trade-offs").click()
    panel = page.locator("#tradeoff-history-panel")

    expect(panel.get_by_role("heading", name="Trade-off patterns")).to_be_visible()
    expect(panel.locator(".tradeoff-history-summary dd")).to_have_text(["5", "5", "4", "4", "1", "0"])
    ranking = panel.locator(".tradeoff-sacrifice-ranking li")
    expect(ranking).to_have_count(2)
    expect(ranking.nth(0)).to_contain_text("Social")
    expect(ranking.nth(0)).to_contain_text("3 of 4 recorded trade-offs · 75%")
    expect(ranking.nth(0)).to_contain_text("Archived")

    pairs = panel.locator(".tradeoff-pair")
    expect(pairs).to_have_count(2)
    expect(pairs.nth(0)).to_contain_text("Work → Social")
    expect(pairs.nth(0)).to_contain_text("3 of 4 recorded trade-offs · 75%")
    expect(pairs.nth(1)).to_contain_text("Social → Work")
    pairs.nth(0).locator("summary").click()
    source = pairs.nth(0).get_by_role("link", name="Open trade-off review for Week 26, 2026")
    source.click()
    expect(page.locator("#timeline-week-2")).to_have_attribute("open", "")

    work_breakdown = panel.get_by_text("When Work was Primary focus · 4 weeks", exact=False)
    work_breakdown.click()
    expect(panel.get_by_text("Social was recorded as What gave way · 3 of 4 weeks · 75%", exact=True)).to_be_visible()
    expect(panel.get_by_text("No trade-off · 1 of 4 weeks", exact=True)).to_be_visible()
    social_breakdown = panel.get_by_text("When Social was What gave way · 3 weeks", exact=False)
    social_breakdown.click()
    expect(panel.get_by_text("Work was Primary focus · 3 weeks · 100%", exact=True)).to_be_visible()
    expect(panel.get_by_text("Week 29, 2026 · Work → Social · Provisional", exact=True)).to_be_visible()

    copy = panel.inner_text().lower()
    for forbidden in ["caused", "resulted", "harmed", "neglected", "should", "predict", "impact score"]:
        assert forbidden not in copy

    page.set_viewport_size({"width": 375, "height": 800})
    expect(panel.locator(".tradeoff-pair-label").first).to_contain_text("Work → Social")
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


@pytest.mark.browser
def test_tradeoff_patterns_empty_states_shared_range_and_integrity_notice(
    page: Page,
    live_app: LiveApp,
) -> None:
    workspace_id, domains = seed_workspace(live_app, ["Work"])
    save_current_review(live_app, workspace_id, domains, focus="Work")

    page.goto(live_app)
    page.get_by_role("button", name="Timeline").click()
    page.get_by_role("tab", name="Trade-offs").click()
    panel = page.locator("#tradeoff-history-panel")
    expect(panel.get_by_text("No Domain was recorded as What gave way during this period.", exact=True)).to_be_visible()
    expect(panel.locator(".tradeoff-history-summary dd")).to_have_text(["1", "1", "0", "0", "1", "0"])

    page.get_by_label("Range").select_option("26")
    expect(page.get_by_label("Range")).to_have_value("26")
    page.get_by_role("tab", name="Focus").click()
    expect(page.get_by_label("Range")).to_have_value("26")

    page.route(
        "**/history/trade-offs?*",
        lambda route: route.fulfill(
            json={
                "range": {"type": "reviewed_weeks", "value": 26},
                "filters": {"focus_domain_id": None, "sacrifice_domain_id": None},
                "summary": {
                    "reviewed_week_count": 1,
                    "focus_week_count": 0,
                    "sacrifice_week_count": 1,
                    "valid_pair_count": 0,
                    "focus_without_sacrifice_count": 0,
                    "no_focus_count": 0,
                    "excluded_pair_count": 1,
                },
                "sacrifices": [],
                "pairs": [],
                "focus_breakdowns": [],
                "sacrifice_breakdowns": [],
                "selected_focus": None,
                "selected_sacrifice": None,
                "weeks": [
                    {
                        "week_id": 1,
                        "iso_year": 2026,
                        "iso_week": 29,
                        "lifecycle": "provisional",
                        "status": "excluded",
                        "focus": None,
                        "sacrifice": None,
                        "excluded_reason": "sacrifice_without_focus",
                    }
                ],
                "integrity": {
                    "excluded_pair_count": 1,
                    "issues": [{"code": "sacrifice_without_focus", "week_id": 1, "iso_year": 2026, "iso_week": 29}],
                    "excluded_reasons": {"sacrifice_without_focus": 1},
                },
                "observations": [],
            }
        ),
    )
    page.get_by_role("tab", name="Trade-offs").click()
    page.get_by_label("Range").select_option("52")
    expect(
        panel.get_by_text("1 trade-off record was excluded because historical data is inconsistent.", exact=True)
    ).to_be_visible()
    expect(
        panel.get_by_text("Trade-off patterns cannot be summarized until the historical data is reviewed.", exact=True)
    ).to_be_visible()


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
