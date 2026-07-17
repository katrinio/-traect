const apiBase = window.TRAECT_API_BASE || "";
const storageKey = "traect.workspace_id";
const commentLimit = 300;
const weekParts = isoWeek(new Date());

const state = {
  workspace: null,
  domains: [],
  currentReview: null,
  timeline: { items: null, loading: false, error: null },
  activeView: "current",
  setupDraft: [{ name: "" }],
  setupWorkspaceName: "",
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
  currentTradeoff: document.getElementById("current-tradeoff"),
  currentTradeoffContent: document.getElementById("current-tradeoff-content"),
  currentGroups: document.getElementById("current-groups"),
  timelineEntries: document.getElementById("timeline-entries"),
  timelineStatus: document.getElementById("timeline-status"),
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

const modePresentation = {
  focus: { symbol: "▲", label: "Primary focus", group: "Primary focus" },
  maintain: { symbol: "✓", label: "Maintained", group: "Maintained" },
  ignore: { symbol: "○", label: "Paused", group: "Paused" },
};

const statusLabels = {
  good: ["✓", "Stable"],
  warning: ["⚠", "At Risk"],
  critical: ["!", "Critical"],
};

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => {
    setActiveView(button.dataset.view || "current");
  });
});

if (el.setupForm) {
  el.setupForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await withStatus(el.setupStatus, saveSetup);
  });
}

if (el.reviewForm) {
  el.reviewForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await withStatus(el.reviewStatus, saveReview);
  });
}

const addInitialDomainButton = document.getElementById("add-domain");
if (addInitialDomainButton) {
  addInitialDomainButton.addEventListener("click", () => {
    state.setupDraft.push({ name: "" });
    renderSetup();
  });
}

const addActiveDomainButton = document.getElementById("add-active-domain");
if (addActiveDomainButton) {
  addActiveDomainButton.addEventListener("click", async () => {
    await withStatus(el.manageStatus, createDomainFromManage);
  });
}

if (el.editReviewButton) {
  el.editReviewButton.addEventListener("click", () => {
    setActiveView("edit");
  });
}

if (el.backToCurrentButton) {
  el.backToCurrentButton.addEventListener("click", () => {
    setActiveView("current");
  });
}

boot().catch((error) => setStatus(el.setupStatus || el.reviewStatus || el.manageStatus, error.message, true));

async function boot() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
  await loadState();
  render();
}

async function loadState() {
  const currentWorkspace = await fetchJSON("/workspaces/current", { ignore404: true });
  if (!currentWorkspace) {
    state.workspace = null;
    state.domains = [];
    state.currentReview = null;
    state.activeView = "current";
    return;
  }
  state.workspace = currentWorkspace;
  const [domains, review] = await Promise.all([
    fetchJSON(`/workspaces/${state.workspace.id}/domains`),
    fetchJSON(`/workspaces/${state.workspace.id}/weeks/current`, { ignore404: true }),
  ]);
  state.domains = domains.items;
  state.currentReview = review;
}

function render() {
  renderNavigation();
  if (el.headline) {
    el.headline.textContent = state.workspace ? state.workspace.name : "Workspace setup";
  }

  if (!state.workspace) {
    showOnly("setup");
    if (el.setupView) {
      renderSetup();
    }
    return;
  }

  if (el.weekMeta) {
    el.weekMeta.textContent = `Week ${weekParts.week}, ${weekParts.year}`;
  }

  renderCurrent();
  renderTimeline();
  renderEdit();
  renderDomains();
  showOnly(state.activeView);
}

function renderNavigation() {
  const shouldShow = Boolean(state.workspace);
  if (el.mainNav) {
    el.mainNav.classList.toggle("hidden", !shouldShow);
  }
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.setAttribute("aria-selected", String(shouldShow && button.dataset.view === state.activeView));
  });
}

function showOnly(view) {
  if (el.setupView) {
    el.setupView.classList.toggle("hidden", view !== "setup");
  }
  if (el.currentView) {
    el.currentView.classList.toggle("hidden", view !== "current");
  }
  if (el.timelineView) {
    el.timelineView.classList.toggle("hidden", view !== "timeline");
  }
  if (el.editView) {
    el.editView.classList.toggle("hidden", view !== "edit");
  }
  if (el.manageView) {
    el.manageView.classList.toggle("hidden", view !== "domains");
  }
}

function setActiveView(view) {
  state.activeView = view;
  render();
  if (view === "timeline" && state.timeline.items === null && !state.timeline.loading) {
    loadTimeline();
  }
}

function renderSetup() {
  if (!el.setupDomains || !el.setupStatus) return;
  el.setupDomains.replaceChildren(...state.setupDraft.map((item, index) => renderSetupDomain(item, index)));
  setStatus(el.setupStatus, "");
}

function renderSetupDomain(item, index) {
  const row = document.createElement("section");
  row.className = "domain";
  row.innerHTML = `
    <div class="domain-grid">
      <label class="full">Domain
        <input type="text" name="setup_domain_${index}" value="${escapeHtml(item.name)}" autocomplete="off">
      </label>
      <div class="domain-actions full">
        <button class="secondary" type="button" data-up="${index}">Up</button>
        <button class="secondary" type="button" data-down="${index}">Down</button>
        <button class="ghost" type="button" data-remove="${index}">Remove</button>
      </div>
    </div>
  `;
  row.querySelector("[data-up]").addEventListener("click", () => moveSetupDomain(index, -1));
  row.querySelector("[data-down]").addEventListener("click", () => moveSetupDomain(index, 1));
  row.querySelector("[data-remove]").addEventListener("click", () => {
    if (state.setupDraft.length > 1) {
      state.setupDraft.splice(index, 1);
      renderSetup();
    }
  });
  row.querySelector("input").addEventListener("input", (event) => {
    item.name = event.target.value;
  });
  return row;
}

function moveSetupDomain(index, offset) {
  const next = index + offset;
  if (next < 0 || next >= state.setupDraft.length) return;
  [state.setupDraft[index], state.setupDraft[next]] = [state.setupDraft[next], state.setupDraft[index]];
  renderSetup();
}

function renderCurrent() {
  if (!el.currentGroups) return;
  const review = state.currentReview;
  renderCurrentTradeOff(review);
  const statesByDomainId = new Map((review?.states || []).map((item) => [item.domain_id, item]));
  const grouped = {
    focus: [],
    maintain: [],
    ignore: [],
  };

  for (const domain of activeDomains()) {
    const currentState = statesByDomainId.get(domain.id) || { mode: "ignore", status: "good" };
    grouped[currentState.mode].push({ domain, state: currentState });
  }

  const groups = [
    ["Focus", grouped.focus],
    ["Maintenance", grouped.maintain],
    ["Ignored", grouped.ignore],
  ].filter(([, entries]) => entries.length > 0);

  el.currentGroups.replaceChildren(...groups.map(([title, entries]) => renderGroup(title, entries)));
}

function renderCurrentTradeOff(review) {
  if (!el.currentTradeoff || !el.currentTradeoffContent) return;
  if (!review) {
    el.currentTradeoff.classList.add("hidden");
    el.currentTradeoffContent.replaceChildren();
    return;
  }

  const domainsById = new Map(state.domains.map((domain) => [domain.id, domain]));
  el.currentTradeoff.classList.remove("hidden");
  el.currentTradeoffContent.replaceChildren(createTradeOffSummary(review, {
    focusName: review.focus_domain_id ? domainName(domainsById, review.focus_domain_id) : null,
    sacrificedName: review.sacrificed_domain_id ? domainName(domainsById, review.sacrificed_domain_id) : null,
  }));
}

function createTradeOffSummary(review, names) {
  if (!review.focus_domain_id && !names.focusName) {
    const empty = document.createElement("p");
    empty.className = "tradeoff-empty";
    empty.textContent = "No primary focus recorded.";
    return empty;
  }

  const list = document.createElement("dl");
  list.className = "tradeoff-list";
  list.appendChild(renderTradeOffRow("focus", "Main focus", names.focusName || "Unknown domain"));

  const sacrificed = names.sacrificedName || "None recorded";
  list.appendChild(renderTradeOffRow("sacrifice", "What gave way", sacrificed));
  if (typeof review.sacrifice_reason === "string" && review.sacrifice_reason) {
    list.appendChild(renderTradeOffRow("reason", "Why", review.sacrifice_reason));
  }
  return list;
}

function renderTradeOffRow(field, label, value) {
  const row = document.createElement("div");
  row.className = "tradeoff-row";
  row.dataset.tradeoffField = field;
  const term = document.createElement("dt");
  term.textContent = label;
  const description = document.createElement("dd");
  description.textContent = value;
  row.append(term, description);
  return row;
}

function domainName(domainsById, domainId) {
  return domainsById.get(domainId)?.name || "Unknown domain";
}

function renderGroup(title, entries) {
  const section = document.createElement("section");
  section.className = "domain-group";
  const heading = document.createElement("h3");
  heading.className = "section-title";
  heading.textContent = title;
  const body = document.createElement("div");
  body.className = "current-rows";
  for (const entry of entries) {
    body.appendChild(renderCurrentRow(entry.domain, entry.state));
  }
  section.append(heading, body);
  return section;
}

function renderCurrentRow(domain, currentState) {
  const status = currentState.status || "good";
  const [symbol, label] = statusLabels[status] || statusLabels.good;
  const row = document.createElement("div");
  row.className = "current-row";
  row.innerHTML = `
    <span class="domain-name">${escapeHtml(domain.name)}</span>
    <span class="status-mark" data-status="${status}" title="${escapeHtml(label)}" aria-label="${escapeHtml(label)}">
      <span class="status-symbol" aria-hidden="true">${symbol}</span>
    </span>
  `;
  return row;
}

async function loadTimeline() {
  state.timeline.loading = true;
  state.timeline.error = null;
  renderTimeline();
  try {
    const payload = await fetchJSON(`/workspaces/${state.workspace.id}/weeks`);
    state.timeline.items = mapTimelineHistory(payload);
  } catch (error) {
    state.timeline.error = error.message || "Timeline could not be loaded.";
  } finally {
    state.timeline.loading = false;
    renderTimeline();
  }
}

function mapTimelineHistory(payload) {
  if (!payload || !Array.isArray(payload.items)) {
    throw new Error("Timeline response is incomplete.");
  }
  return payload.items.map((review) => {
    const issues = [];
    if (!Number.isInteger(review.iso_year) || !Number.isInteger(review.iso_week)) {
      issues.push("Week date is incomplete.");
    }
    const rawStates = Array.isArray(review.states) ? review.states : [];
    if (!Array.isArray(review.states)) {
      issues.push("Domain states are missing.");
    }
    const states = rawStates.flatMap((item) => {
      if (!item || typeof item.domain_name !== "string" || !item.domain_name.trim()) {
        issues.push("A Domain state has no historical name.");
        return [];
      }
      if (!(item.mode in modePresentation) || !(item.status in statusLabels)) {
        issues.push(`The saved state for ${item.domain_name} is invalid.`);
        return [];
      }
      return [{ ...item, domain_name: item.domain_name.trim() }];
    });
    if (review.focus_domain_id && !review.focus_domain_name) {
      issues.push("The saved Main focus name is missing.");
    }
    if (review.sacrificed_domain_id && !review.sacrificed_domain_name) {
      issues.push("The saved What gave way name is missing.");
    }
    if (review.sacrifice_reason !== null && review.sacrifice_reason !== undefined
      && typeof review.sacrifice_reason !== "string") {
      issues.push("The saved Why value is invalid.");
    }
    return { ...review, states, issues };
  });
}

function renderTimeline() {
  if (!el.timelineEntries || !el.timelineStatus) return;
  if (state.timeline.loading) {
    setStatus(el.timelineStatus, "Loading timeline…");
    el.timelineEntries.replaceChildren();
    return;
  }
  if (state.timeline.error) {
    setStatus(el.timelineStatus, "Timeline could not be loaded. Try again.", true);
    const retry = document.createElement("button");
    retry.className = "secondary timeline-retry";
    retry.type = "button";
    retry.textContent = "Retry";
    retry.addEventListener("click", loadTimeline);
    el.timelineEntries.replaceChildren(retry);
    return;
  }
  setStatus(el.timelineStatus, "");
  if (state.timeline.items === null) {
    el.timelineEntries.replaceChildren();
    return;
  }
  if (state.timeline.items.length === 0) {
    const empty = document.createElement("div");
    empty.className = "timeline-empty";
    const title = document.createElement("p");
    title.textContent = "No weekly reviews yet.";
    const explanation = document.createElement("p");
    explanation.className = "hint";
    explanation.textContent = "The history will appear here after the first review is saved.";
    const current = document.createElement("button");
    current.className = "secondary";
    current.type = "button";
    current.textContent = "Back to Current";
    current.addEventListener("click", () => setActiveView("current"));
    empty.append(title, explanation, current);
    el.timelineEntries.replaceChildren(empty);
    return;
  }
  el.timelineEntries.replaceChildren(...state.timeline.items.map(renderTimelineWeek));
}

function renderTimelineWeek(review) {
  const article = document.createElement("article");
  article.className = "timeline-week";
  const heading = document.createElement("h3");
  heading.className = "timeline-week-heading";
  heading.textContent = Number.isInteger(review.iso_year) && Number.isInteger(review.iso_week)
    ? `Week ${review.iso_week}, ${review.iso_year}`
    : "Unknown week";
  article.appendChild(heading);

  const tradeoff = document.createElement("div");
  tradeoff.className = "timeline-tradeoff";
  tradeoff.appendChild(createTradeOffSummary(review, {
    focusName: typeof review.focus_domain_name === "string" ? review.focus_domain_name : null,
    sacrificedName: typeof review.sacrificed_domain_name === "string" ? review.sacrificed_domain_name : null,
  }));
  article.appendChild(tradeoff);

  const groups = document.createElement("div");
  groups.className = "timeline-groups";
  for (const mode of ["focus", "maintain", "ignore"]) {
    const entries = review.states.filter((item) => item.mode === mode);
    if (entries.length) groups.appendChild(renderTimelineGroup(mode, entries));
  }
  article.appendChild(groups);

  if (review.issues.length) {
    const integrity = document.createElement("p");
    integrity.className = "status error timeline-integrity";
    integrity.textContent = `Some saved data could not be shown: ${[...new Set(review.issues)].join(" ")}`;
    article.appendChild(integrity);
  }
  return article;
}

function renderTimelineGroup(mode, entries) {
  const section = document.createElement("section");
  section.className = "timeline-group";
  const heading = document.createElement("h4");
  heading.className = "section-title";
  heading.textContent = modePresentation[mode].group;
  const rows = document.createElement("div");
  rows.className = "timeline-domain-rows";
  rows.replaceChildren(...entries.map(renderTimelineDomainRow));
  section.append(heading, rows);
  return section;
}

function renderTimelineDomainRow(item) {
  const attention = modePresentation[item.mode];
  const [conditionSymbol, conditionLabel] = statusLabels[item.status];
  const row = document.createElement("div");
  row.className = "timeline-domain-row";
  row.dataset.mode = item.mode;
  row.dataset.status = item.status;
  row.innerHTML = `
    <span class="attention-mark" title="${escapeHtml(attention.label)}" aria-label="Attention: ${escapeHtml(attention.label)}">
      <span aria-hidden="true">${attention.symbol}</span>
    </span>
    <span class="timeline-domain-name">${escapeHtml(item.domain_name)}</span>
    <span class="status-mark" data-status="${item.status}" title="${escapeHtml(conditionLabel)}" aria-label="Condition: ${escapeHtml(conditionLabel)}">
      <span class="status-symbol" aria-hidden="true">${conditionSymbol}</span>
    </span>
  `;
  return row;
}

function renderEdit() {
  if (!el.reviewDomains) return;
  const review = state.currentReview;
  const statesByDomainId = new Map((review?.states || []).map((item) => [item.domain_id, item]));
  const active = activeDomains();
  el.reviewDomains.replaceChildren(...active.map((domain) => renderEditRow(domain, statesByDomainId.get(domain.id))));
  const focusSelect = document.querySelector("select[name='focus_domain_id']");
  const sacrificedSelect = document.querySelector("select[name='sacrificed_domain_id']");
  focusSelect.innerHTML = summaryOptions(active);
  sacrificedSelect.innerHTML = summaryOptions(active);

  const focusedDomains = active.filter((domain) => statesByDomainId.get(domain.id)?.mode === "focus");
  const savedFocusId = active.some((domain) => domain.id === review?.focus_domain_id) ? review.focus_domain_id : null;
  const selectedFocusId = savedFocusId || (focusedDomains.length === 1 ? focusedDomains[0].id : null);
  focusSelect.value = selectedFocusId ? String(selectedFocusId) : "";
  sacrificedSelect.value = review?.sacrificed_domain_id ? String(review.sacrificed_domain_id) : "";
  document.querySelector("input[name='sacrifice_reason']").value = review?.sacrifice_reason || "";
  synchronizeFocusControls(selectedFocusId);

  focusSelect.onchange = () => synchronizeFocusControls(selectedNumber("focus_domain_id"));
  sacrificedSelect.onchange = () => {
    if (sacrificedSelect.value === focusSelect.value) {
      sacrificedSelect.value = "";
    }
    synchronizeTradeOffReason();
  };
  document.querySelector("textarea[name='notes']").value = review?.notes || "";
}

function renderEditRow(domain, currentState) {
  const comment = currentState?.comment || "";
  const row = document.createElement("section");
  row.className = "domain";
  row.innerHTML = `
    <div class="domain-head">
      <div class="domain-name">${escapeHtml(domain.name)}</div>
    </div>
    <div class="domain-grid">
      <label>Attention this week
        <select name="mode_${domain.id}">
          ${modeOptions().map(([value, label]) => `<option value="${value}">${label}</option>`).join("")}
        </select>
      </label>
      <label>Condition now
        <select name="status_${domain.id}">
          <option value="good">✓ Stable</option>
          <option value="warning">⚠ At risk</option>
          <option value="critical">! Critical</option>
        </select>
      </label>
      <details class="domain-context full" ${comment ? "open" : ""}>
        <summary>${comment ? "Edit context" : "Add context"}</summary>
        <label class="context-field">Context
          <textarea name="comment_${domain.id}" maxlength="${commentLimit}"
            placeholder="What explains this attention choice or condition?"></textarea>
          <span class="character-count" aria-live="polite"></span>
        </label>
      </details>
    </div>
  `;
  const modeSelect = row.querySelector(`select[name="mode_${domain.id}"]`);
  const commentInput = row.querySelector(`textarea[name="comment_${domain.id}"]`);
  const commentSummary = row.querySelector(".domain-context summary");
  const characterCount = row.querySelector(".character-count");

  modeSelect.value = currentState?.mode || "ignore";
  row.querySelector(`select[name="status_${domain.id}"]`).value = currentState?.status || "good";
  commentInput.value = comment;
  updateCommentContext(commentInput, commentSummary, characterCount);

  modeSelect.addEventListener("change", () => {
    const focusSelect = document.querySelector("select[name='focus_domain_id']");
    if (modeSelect.value === "focus") {
      focusSelect.value = String(domain.id);
      synchronizeFocusControls(domain.id);
    } else if (focusSelect.value === String(domain.id)) {
      focusSelect.value = "";
      synchronizeFocusControls(null);
    }
  });
  commentInput.addEventListener("input", () => updateCommentContext(commentInput, commentSummary, characterCount));
  return row;
}

function synchronizeFocusControls(focusDomainId) {
  document.querySelectorAll("select[name^='mode_']").forEach((select) => {
    const domainId = Number(select.name.replace("mode_", ""));
    if (domainId === focusDomainId) {
      select.value = "focus";
    } else if (select.value === "focus") {
      select.value = "maintain";
    }
  });
  const sacrificedSelect = document.querySelector("select[name='sacrificed_domain_id']");
  sacrificedSelect.disabled = focusDomainId === null;
  sacrificedSelect.querySelector("option[value='']").textContent = focusDomainId === null
    ? "Choose a main focus first"
    : "None this week";
  sacrificedSelect.querySelectorAll("option").forEach((option) => {
    option.disabled = option.value === String(focusDomainId);
  });
  if (focusDomainId === null) {
    sacrificedSelect.value = "";
  }
  if (sacrificedSelect && sacrificedSelect.value === String(focusDomainId)) {
    sacrificedSelect.value = "";
  }
  synchronizeTradeOffReason();
}

function synchronizeTradeOffReason() {
  const sacrificedSelect = document.querySelector("select[name='sacrificed_domain_id']");
  const reasonInput = document.querySelector("input[name='sacrifice_reason']");
  const hasSacrifice = Boolean(sacrificedSelect.value);
  reasonInput.disabled = !hasSacrifice;
  reasonInput.placeholder = hasSacrifice ? "What caused this trade-off?" : "Choose what gave way first";
  if (!hasSacrifice) {
    reasonInput.value = "";
  }
}

function updateCommentContext(input, summary, counter) {
  const length = input.value.length;
  summary.textContent = length > 0 ? "Edit context" : "Add context";
  counter.textContent = `${length} / ${commentLimit}`;
}

function renderDomains() {
  if (!el.manageDomains || !el.archivedDomains) return;
  const active = activeDomains();
  const archived = state.domains.filter((domain) => domain.archived_at !== null).sort(bySortOrder);
  el.manageDomains.replaceChildren(...active.map((domain) => renderActiveDomainRow(domain)));
  el.archivedDomains.replaceChildren(...archived.map((domain) => renderArchivedDomainRow(domain)));
  enableDragReorder(el.manageDomains);
}

function renderActiveDomainRow(domain) {
  const row = document.createElement("div");
  row.className = "domain-row";
  row.dataset.id = String(domain.id);
  row.innerHTML = `
    <span class="drag-handle" aria-hidden="true">⋮⋮</span>
    <input class="inline-input" type="text" value="${escapeHtml(domain.name)}" autocomplete="off" aria-label="Domain name">
    <button class="ghost row-action" type="button" data-archive="${domain.id}">Archive</button>
  `;
  const input = row.querySelector("input");
  input.addEventListener("change", async () => withStatus(el.manageStatus, async () => {
    await fetchJSON(`/domains/${domain.id}`, {
      method: "PATCH",
      body: JSON.stringify({ name: input.value }),
    });
    await loadState();
    render();
  }));
  row.querySelector("[data-archive]").addEventListener("click", () => archiveDomain(domain.id));
  return row;
}

function renderArchivedDomainRow(domain) {
  const row = document.createElement("div");
  row.className = "domain-row";
  row.innerHTML = `
    <span class="domain-name-static">${escapeHtml(domain.name)}</span>
    <button class="ghost row-action" type="button" data-restore="${domain.id}">Restore</button>
  `;
  row.querySelector("[data-restore]").addEventListener("click", () => restoreDomain(domain.id));
  return row;
}

function enableDragReorder(container) {
  const originalOrder = [...container.querySelectorAll(".domain-row")].map((row) => row.dataset.id);
  container.querySelectorAll(".drag-handle").forEach((handle) => {
    handle.addEventListener("pointerdown", (event) => {
      const draggingRow = handle.closest(".domain-row");
      if (!draggingRow) return;
      event.preventDefault();
      draggingRow.classList.add("dragging");
      handle.setPointerCapture(event.pointerId);

      const onMove = (moveEvent) => {
        for (const sibling of container.querySelectorAll(".domain-row")) {
          if (sibling === draggingRow) continue;
          const rect = sibling.getBoundingClientRect();
          if (moveEvent.clientY < rect.top || moveEvent.clientY > rect.bottom) continue;
          const before = moveEvent.clientY < rect.top + rect.height / 2;
          container.insertBefore(draggingRow, before ? sibling : sibling.nextSibling);
          break;
        }
      };

      const onUp = async () => {
        draggingRow.classList.remove("dragging");
        handle.releasePointerCapture(event.pointerId);
        document.removeEventListener("pointermove", onMove);
        document.removeEventListener("pointerup", onUp);
        const newOrder = [...container.querySelectorAll(".domain-row")].map((row) => row.dataset.id);
        if (newOrder.join() === originalOrder.join()) return;
        await withStatus(el.manageStatus, async () => {
          await fetchJSON(`/workspaces/${state.workspace.id}/domains/order`, {
            method: "PUT",
            body: JSON.stringify({ domain_ids: newOrder.map(Number) }),
          });
          await loadState();
          render();
        });
      };

      document.addEventListener("pointermove", onMove);
      document.addEventListener("pointerup", onUp);
    });
  });
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
  const active = activeDomains();
  const payload = {
    focus_domain_id: selectedNumber("focus_domain_id"),
    sacrificed_domain_id: selectedNumber("sacrificed_domain_id"),
    sacrifice_reason: document.querySelector("input[name='sacrifice_reason']").value.trim() || null,
    notes: document.querySelector("textarea[name='notes']").value.trim() || null,
    states: active.map((domain) => ({
      domain_id: domain.id,
      mode: document.querySelector(`select[name="mode_${domain.id}"]`).value,
      status: document.querySelector(`select[name="status_${domain.id}"]`).value,
      comment: document.querySelector(`textarea[name="comment_${domain.id}"]`).value.trim() || null,
    })),
  };
  await fetchJSON(`/workspaces/${state.workspace.id}/weeks/${weekParts.year}/${weekParts.week}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  await loadState();
  state.timeline = { items: null, loading: false, error: null };
  state.activeView = "current";
  render();
}

async function archiveDomain(domainId) {
  await fetchJSON(`/domains/${domainId}/archive`, { method: "POST" });
  await loadState();
  render();
}

async function restoreDomain(domainId) {
  await fetchJSON(`/domains/${domainId}/restore`, { method: "POST" });
  await loadState();
  render();
}

async function createDomainFromManage() {
  const name = window.prompt("Domain name");
  if (!name) return;
  await fetchJSON(`/workspaces/${state.workspace.id}/domains`, {
    method: "POST",
    body: JSON.stringify({ name }),
  });
  await loadState();
  render();
}

function activeDomains() {
  return state.domains.filter((domain) => domain.archived_at === null).sort(bySortOrder);
}

function summaryOptions(active) {
  const options = ['<option value="">None this week</option>'];
  for (const domain of active) {
    options.push(`<option value="${domain.id}">${escapeHtml(domain.name)}</option>`);
  }
  return options.join("");
}

function modeOptions() {
  return Object.entries(modePresentation).map(([value, item]) => [value, `${item.symbol} ${item.label}`]);
}

function selectedNumber(name) {
  const value = document.querySelector(`select[name='${name}']`).value;
  return value ? Number(value) : null;
}

function hasDuplicateNames(names) {
  const normalized = names.map((name) => name.toLowerCase());
  return new Set(normalized).size !== normalized.length;
}

async function withStatus(element, action) {
  try {
    await action();
    setStatus(element, "");
  } catch (error) {
    setStatus(element, error.message, true);
  }
}

function setStatus(element, message, isError = false) {
  if (!element) return;
  element.textContent = message;
  element.className = isError ? "status error" : "status";
}

async function fetchJSON(path, options = {}) {
  const response = await fetch(`${apiBase}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    if (options.ignore404 && response.status === 404) return null;
    const error = new Error(data?.error || response.statusText);
    error.status = response.status;
    throw error;
  }
  return data;
}

function bySortOrder(left, right) {
  return left.sort_order - right.sort_order || left.id - right.id;
}

function isoWeek(date) {
  const target = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const dayNumber = (target.getUTCDay() + 6) % 7;
  target.setUTCDate(target.getUTCDate() - dayNumber + 3);
  const firstThursday = new Date(Date.UTC(target.getUTCFullYear(), 0, 4));
  const week = 1 + Math.round(((target - firstThursday) / 86400000 - 3 + ((firstThursday.getUTCDay() + 6) % 7)) / 7);
  return { year: target.getUTCFullYear(), week };
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);
}
