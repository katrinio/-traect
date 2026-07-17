import { fetchJSON } from "/js/api.js";
import { mapConditionHistory, renderConditionHistory } from "/js/condition-history.js";
import { renderCurrent } from "/js/current.js";
import { renderDomainManagement } from "/js/domains.js";
import { mapFocusHistory, renderFocusHistory } from "/js/focus-history.js";
import {
  activeDomains,
  hasDuplicateNames,
  setStatus,
  withStatus,
} from "/js/presentation.js";
import { collectReviewPayload, renderReview } from "/js/review.js";
import { renderSetup } from "/js/setup.js";
import { mapTimelineHistory, renderTimeline } from "/js/timeline.js";

const storageKey = "traect.workspace_id";

const state = {
  workspace: null,
  domains: [],
  currentWeek: null,
  currentReview: null,
  timeline: { items: null, loading: false, error: null },
  focusHistory: { data: null, loading: false, error: null, range: "12" },
  conditionHistory: { data: null, loading: false, error: null, domainId: null },
  historyView: "focus",
  activeView: "current",
  setupDraft: [{ name: "" }],
};

const el = {
  headline: document.getElementById("headline"),
  mainNav: document.getElementById("main-nav"),
  setupView: document.getElementById("setup-view"),
  currentView: document.getElementById("current-view"),
  timelineView: document.getElementById("timeline-view"),
  editView: document.getElementById("edit-view"),
  manageView: document.getElementById("manage-view"),
  weekMeta: document.getElementById("week-meta"),
  currentLifecycle: document.getElementById("current-lifecycle"),
  currentTradeoff: document.getElementById("current-tradeoff"),
  currentTradeoffContent: document.getElementById("current-tradeoff-content"),
  currentGroups: document.getElementById("current-groups"),
  timelineEntries: document.getElementById("timeline-entries"),
  timelineStatus: document.getElementById("timeline-status"),
  focusHistoryContent: document.getElementById("focus-history-content"),
  focusHistoryStatus: document.getElementById("focus-history-status"),
  focusHistoryRange: document.getElementById("focus-history-range"),
  historyFocusTab: document.getElementById("history-focus-tab"),
  historyConditionTab: document.getElementById("history-condition-tab"),
  focusHistoryPanel: document.getElementById("focus-history-panel"),
  conditionHistoryPanel: document.getElementById("condition-history-panel"),
  conditionHistoryContent: document.getElementById("condition-history-content"),
  conditionHistoryStatus: document.getElementById("condition-history-status"),
  conditionHistoryDomain: document.getElementById("condition-history-domain"),
  reviewDomains: document.getElementById("review-domains"),
  manageDomains: document.getElementById("manage-domains"),
  archivedDomains: document.getElementById("archived-domains"),
  setupDomains: document.getElementById("setup-domains"),
  setupForm: document.getElementById("setup-form"),
  reviewForm: document.getElementById("review-form"),
  setupStatus: document.getElementById("setup-status"),
  reviewStatus: document.getElementById("review-status"),
  manageStatus: document.getElementById("manage-status"),
  editReviewButton: document.getElementById("edit-review"),
  backToCurrentButton: document.getElementById("back-to-current"),
};

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => setActiveView(button.dataset.view || "current"));
});

el.setupForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  await withStatus(el.setupStatus, saveSetup);
});

el.reviewForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  await withStatus(el.reviewStatus, saveReview);
});

document.getElementById("add-domain")?.addEventListener("click", () => {
  state.setupDraft.push({ name: "" });
  renderSetupView();
});

document.getElementById("add-active-domain")?.addEventListener("click", async () => {
  await withStatus(el.manageStatus, createDomainFromManage);
});

el.focusHistoryRange?.addEventListener("change", () => {
  state.focusHistory.range = el.focusHistoryRange.value;
  state.focusHistory.data = null;
  state.conditionHistory.data = null;
  loadActiveHistory();
});

el.historyFocusTab?.addEventListener("click", () => setHistoryView("focus"));
el.historyConditionTab?.addEventListener("click", () => setHistoryView("condition"));
el.conditionHistoryDomain?.addEventListener("change", () => {
  state.conditionHistory.domainId = Number(el.conditionHistoryDomain.value);
  loadConditionHistory();
});

el.editReviewButton?.addEventListener("click", () => setActiveView("edit"));
el.backToCurrentButton?.addEventListener("click", () => setActiveView("current"));

boot().catch((error) => setStatus(el.setupStatus || el.reviewStatus || el.manageStatus, error.message, true));

async function boot() {
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
  await loadState();
  render();
}

async function loadState() {
  const currentWorkspace = await fetchJSON("/workspaces/current", { ignore404: true });
  if (!currentWorkspace) {
    state.workspace = null;
    state.domains = [];
    state.currentWeek = null;
    state.currentReview = null;
    state.activeView = "current";
    return;
  }
  state.workspace = currentWorkspace;
  const [domains, currentWeek] = await Promise.all([
    fetchJSON(`/workspaces/${state.workspace.id}/domains`),
    fetchJSON(`/workspaces/${state.workspace.id}/weeks/current-context`),
  ]);
  state.domains = domains.items;
  state.currentWeek = currentWeek;
  state.currentReview = currentWeek.review;
}

function render() {
  renderNavigation();
  if (el.headline) el.headline.textContent = state.workspace ? state.workspace.name : "Workspace setup";
  if (!state.workspace) {
    showOnly("setup");
    renderSetupView();
    return;
  }

  renderCurrentMetadata();
  const active = activeDomains(state.domains);
  const reviewContextByDomainId = new Map(
    (state.currentWeek?.review_domains || []).map((domain) => [domain.domain_id, domain]),
  );
  const reviewDomains = active.map((domain) => ({
    ...domain,
    minimum_acceptable_level: reviewContextByDomainId.get(domain.id)?.minimum_acceptable_level ?? null,
  }));
  renderCurrent(
    { groups: el.currentGroups, tradeoff: el.currentTradeoff, tradeoffContent: el.currentTradeoffContent },
    active,
    state.currentReview,
    state.domains,
  );
  renderTimelineView();
  renderReview(el.reviewDomains, reviewDomains, state.currentReview);
  renderDomainsView();
  showOnly(state.activeView);
}

function renderCurrentMetadata() {
  if (el.weekMeta && state.currentWeek) {
    el.weekMeta.textContent = `Week ${state.currentWeek.iso_week}, ${state.currentWeek.iso_year}`;
  }
  if (el.currentLifecycle) {
    if (!state.currentReview) el.currentLifecycle.textContent = "";
    else if (state.currentReview.lifecycle === "provisional") {
      el.currentLifecycle.textContent = "Provisional · changes can still be recorded this week";
    } else el.currentLifecycle.textContent = "Final · this review is read-only";
  }
  if (el.editReviewButton) el.editReviewButton.textContent = state.currentReview ? "Edit review" : "Start review";
}

function renderNavigation() {
  const shouldShow = Boolean(state.workspace);
  el.mainNav?.classList.toggle("hidden", !shouldShow);
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.setAttribute("aria-selected", String(shouldShow && button.dataset.view === state.activeView));
  });
}

function showOnly(view) {
  el.setupView?.classList.toggle("hidden", view !== "setup");
  el.currentView?.classList.toggle("hidden", view !== "current");
  el.timelineView?.classList.toggle("hidden", view !== "timeline");
  el.editView?.classList.toggle("hidden", view !== "edit");
  el.manageView?.classList.toggle("hidden", view !== "domains");
}

function setActiveView(view) {
  state.activeView = view;
  render();
  if (view === "timeline") {
    if (state.timeline.items === null && !state.timeline.loading) loadTimeline();
    loadActiveHistory();
  }
}

function setHistoryView(view) {
  state.historyView = view;
  renderTimelineView();
  loadActiveHistory();
}

function loadActiveHistory() {
  if (state.historyView === "focus") {
    if (state.focusHistory.data === null && !state.focusHistory.loading) loadFocusHistory();
  } else if (state.conditionHistory.data === null && !state.conditionHistory.loading) loadConditionHistory();
}

function renderSetupView() {
  renderSetup(el.setupDomains, state.setupDraft, {
    onMove: moveSetupDomain,
    onRemove: (index) => {
      if (state.setupDraft.length > 1) {
        state.setupDraft.splice(index, 1);
        renderSetupView();
      }
    },
  });
  setStatus(el.setupStatus, "");
}

function moveSetupDomain(index, offset) {
  const next = index + offset;
  if (next < 0 || next >= state.setupDraft.length) return;
  [state.setupDraft[index], state.setupDraft[next]] = [state.setupDraft[next], state.setupDraft[index]];
  renderSetupView();
}

function renderTimelineView() {
  renderHistoryTabs();
  renderTimeline(
    { entries: el.timelineEntries, status: el.timelineStatus },
    state.timeline,
    {
      onRetry: loadTimeline,
      onCurrent: () => setActiveView("current"),
      onEdit: () => setActiveView("edit"),
    },
  );
  renderFocusHistory(
    { content: el.focusHistoryContent, status: el.focusHistoryStatus, range: el.focusHistoryRange },
    state.focusHistory,
    { onRetry: loadFocusHistory },
  );
  renderConditionHistory(
    {
      content: el.conditionHistoryContent,
      status: el.conditionHistoryStatus,
      domain: el.conditionHistoryDomain,
    },
    state.conditionHistory,
    { onRetry: loadConditionHistory },
  );
}

function renderHistoryTabs() {
  const focusSelected = state.historyView === "focus";
  el.historyFocusTab?.setAttribute("aria-selected", String(focusSelected));
  el.historyConditionTab?.setAttribute("aria-selected", String(!focusSelected));
  el.focusHistoryPanel?.classList.toggle("hidden", !focusSelected);
  el.conditionHistoryPanel?.classList.toggle("hidden", focusSelected);
}

async function loadFocusHistory() {
  state.focusHistory.loading = true;
  state.focusHistory.error = null;
  renderTimelineView();
  try {
    const range = encodeURIComponent(state.focusHistory.range);
    const payload = await fetchJSON(`/workspaces/${state.workspace.id}/history/focus?reviewed_weeks=${range}`);
    state.focusHistory.data = mapFocusHistory(payload);
  } catch (error) {
    state.focusHistory.error = error.message || "Focus history could not be loaded.";
  } finally {
    state.focusHistory.loading = false;
    renderTimelineView();
  }
}

async function loadConditionHistory() {
  state.conditionHistory.loading = true;
  state.conditionHistory.error = null;
  renderTimelineView();
  try {
    const range = encodeURIComponent(state.focusHistory.range);
    const domain = state.conditionHistory.domainId === null
      ? ""
      : `&domain_id=${encodeURIComponent(state.conditionHistory.domainId)}`;
    const payload = await fetchJSON(
      `/workspaces/${state.workspace.id}/history/condition?reviewed_weeks=${range}${domain}`,
    );
    state.conditionHistory.data = mapConditionHistory(payload);
    state.conditionHistory.domainId = payload.history?.domain.domain_id ?? null;
  } catch (error) {
    state.conditionHistory.error = error.message || "Condition history could not be loaded.";
  } finally {
    state.conditionHistory.loading = false;
    renderTimelineView();
  }
}

async function loadTimeline() {
  state.timeline.loading = true;
  state.timeline.error = null;
  renderTimelineView();
  try {
    const payload = await fetchJSON(`/workspaces/${state.workspace.id}/weeks`);
    state.timeline.items = mapTimelineHistory(payload);
  } catch (error) {
    state.timeline.error = error.message || "Timeline could not be loaded.";
  } finally {
    state.timeline.loading = false;
    renderTimelineView();
  }
}

function renderDomainsView() {
  renderDomainManagement(
    { active: el.manageDomains, archived: el.archivedDomains },
    state.domains,
    {
      onRename: (domainId, name) => withStatus(el.manageStatus, () => renameDomain(domainId, name)),
      onMinimumLevel: (domainId, value) => withStatus(
        el.manageStatus,
        () => updateMinimumAcceptableLevel(domainId, value),
      ),
      onArchive: (domainId) => withStatus(el.manageStatus, () => archiveDomain(domainId)),
      onRestore: (domainId) => withStatus(el.manageStatus, () => restoreDomain(domainId)),
      onReorder: (domainIds) => withStatus(el.manageStatus, () => reorderDomains(domainIds)),
    },
  );
}

async function saveSetup() {
  const workspaceName = el.setupForm.workspace_name.value.trim();
  const domainNames = state.setupDraft.map((item) => item.name.trim());
  if (!workspaceName) throw new Error("Workspace name is required.");
  if (domainNames.length === 0 || domainNames.some((name) => !name)) throw new Error("Domain names are required.");
  if (hasDuplicateNames(domainNames)) throw new Error("Domain names must be unique.");

  const response = await fetchJSON("/workspaces", {
    method: "POST",
    body: JSON.stringify({ name: workspaceName, domains: domainNames.map((name) => ({ name })) }),
  });
  window.localStorage.setItem(storageKey, String(response.id));
  window.location.replace("/");
}

async function saveReview() {
  const payload = collectReviewPayload(activeDomains(state.domains));
  await fetchJSON(
    `/workspaces/${state.workspace.id}/weeks/${state.currentWeek.iso_year}/${state.currentWeek.iso_week}`,
    { method: "PUT", body: JSON.stringify(payload) },
  );
  await loadState();
  state.timeline = { items: null, loading: false, error: null };
  state.focusHistory = { ...state.focusHistory, data: null, error: null };
  state.conditionHistory = { ...state.conditionHistory, data: null, error: null };
  state.activeView = "current";
  render();
}

async function renameDomain(domainId, name) {
  await fetchJSON(`/domains/${domainId}`, { method: "PATCH", body: JSON.stringify({ name }) });
  await refresh();
}

async function updateMinimumAcceptableLevel(domainId, value) {
  await fetchJSON(`/domains/${domainId}`, {
    method: "PATCH",
    body: JSON.stringify({ minimum_acceptable_level: value.trim() || null }),
  });
  await refresh();
}

async function archiveDomain(domainId) {
  await fetchJSON(`/domains/${domainId}/archive`, { method: "POST" });
  await refresh();
}

async function restoreDomain(domainId) {
  await fetchJSON(`/domains/${domainId}/restore`, { method: "POST" });
  await refresh();
}

async function reorderDomains(domainIds) {
  await fetchJSON(`/workspaces/${state.workspace.id}/domains/order`, {
    method: "PUT",
    body: JSON.stringify({ domain_ids: domainIds }),
  });
  await refresh();
}

async function createDomainFromManage() {
  const name = window.prompt("Domain name");
  if (!name) return;
  await fetchJSON(`/workspaces/${state.workspace.id}/domains`, {
    method: "POST",
    body: JSON.stringify({ name }),
  });
  await refresh();
}

async function refresh() {
  await loadState();
  state.focusHistory = { ...state.focusHistory, data: null, error: null };
  state.conditionHistory = { ...state.conditionHistory, data: null, error: null };
  render();
}
