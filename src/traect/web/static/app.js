const apiBase = window.TRAECT_API_BASE || "";
const storageKey = "traect.workspace_id";
const weekParts = isoWeek(new Date());

const state = {
  workspace: null,
  domains: [],
  currentReview: null,
  activeView: "current",
  setupDraft: [{ name: "" }],
  setupWorkspaceName: "",
};

const el = {
  headline: document.getElementById("headline"),
  saveState: document.getElementById("save-state"),
  mainNav: document.getElementById("main-nav"),
  setupView: document.getElementById("setup-view"),
  currentView: document.getElementById("current-view"),
  editView: document.getElementById("edit-view"),
  manageView: document.getElementById("manage-view"),
  weekMeta: document.getElementById("week-meta"),
  editWeekMeta: document.getElementById("edit-week-meta"),
  domainCount: document.getElementById("domain-count"),
  editDomainCount: document.getElementById("edit-domain-count"),
  currentGroups: document.getElementById("current-groups"),
  reviewDomains: document.getElementById("review-domains"),
  manageDomains: document.getElementById("manage-domains"),
  archivedDomains: document.getElementById("archived-domains"),
  setupDomains: document.getElementById("setup-domains"),
  setupForm: document.getElementById("setup-form"),
  reviewForm: document.getElementById("review-form"),
  domainForm: document.getElementById("domain-form"),
  setupStatus: document.getElementById("setup-status"),
  reviewStatus: document.getElementById("review-status"),
  manageStatus: document.getElementById("manage-status"),
  editReviewButton: document.getElementById("edit-review"),
  backToCurrentButton: document.getElementById("back-to-current"),
};

const modeLabels = {
  focus: "▲ Focus",
  maintain: "✓ Maintenance",
  ignore: "○ Ignored",
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

if (el.domainForm) {
  el.domainForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await withStatus(el.manageStatus, saveDomainOrder);
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

const saveOrderButton = document.getElementById("save-order");
if (saveOrderButton) {
  saveOrderButton.addEventListener("click", async () => {
    await withStatus(el.manageStatus, saveDomainOrder);
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

boot().catch((error) => setStatus(el.reviewStatus, error.message, true));

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
  el.headline.textContent = state.workspace ? state.workspace.name : "Workspace setup";

  if (!state.workspace) {
    showOnly("setup");
    renderSetup();
    return;
  }

  el.weekMeta.textContent = `Week ${weekParts.week}, ${weekParts.year}`;
  el.editWeekMeta.textContent = `Week ${weekParts.week}, ${weekParts.year}`;
  el.domainCount.textContent = `${activeDomains().length} active domains`;
  el.editDomainCount.textContent = `${activeDomains().length} active domains`;

  renderCurrent();
  renderEdit();
  renderDomains();
  showOnly(state.activeView);
}

function renderNavigation() {
  const shouldShow = Boolean(state.workspace);
  el.mainNav.classList.toggle("hidden", !shouldShow);
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.setAttribute("aria-selected", String(shouldShow && button.dataset.view === state.activeView));
  });
}

function showOnly(view) {
  el.setupView.classList.toggle("hidden", view !== "setup");
  el.currentView.classList.toggle("hidden", view !== "current");
  el.editView.classList.toggle("hidden", view !== "edit");
  el.manageView.classList.toggle("hidden", view !== "domains");
}

function setActiveView(view) {
  state.activeView = view;
  render();
}

function renderSetup() {
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
  const review = state.currentReview;
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

  el.currentGroups.replaceChildren(
    renderGroup("Focus", "Focus", grouped.focus),
    renderGroup("Maintenance", "Maintenance", grouped.maintain),
    renderGroup("Ignored", "Ignored", grouped.ignore),
  );
}

function renderGroup(title, headline, entries) {
  const section = document.createElement("section");
  section.className = "domain-group";
  section.innerHTML = `
    <h3 class="section-title">${escapeHtml(title)}</h3>
    <div class="rule"></div>
  `;
  const body = document.createElement("div");
  body.className = "domains";
  if (entries.length === 0) {
    const empty = document.createElement("div");
    empty.className = "muted";
    empty.textContent = "None";
    body.appendChild(empty);
  } else {
    for (const entry of entries) {
      body.appendChild(renderCurrentRow(entry.domain, entry.state));
    }
  }
  section.appendChild(body);
  return section;
}

function renderCurrentRow(domain, currentState) {
  const row = document.createElement("div");
  row.className = "domain";
  row.innerHTML = `
    <div class="domain-head">
      <div class="domain-name">${escapeHtml(domain.name)}</div>
      <div class="status-mark" data-status="${currentState.status || "good"}">
        <span class="status-symbol">${statusLabels[currentState.status]?.[0] || "○"}</span>
        <span class="status-text">${statusLabels[currentState.status]?.[1] || "Stable"}</span>
      </div>
    </div>
  `;
  return row;
}

function renderEdit() {
  const review = state.currentReview;
  const statesByDomainId = new Map((review?.states || []).map((item) => [item.domain_id, item]));
  const active = activeDomains();
  el.reviewDomains.replaceChildren(...active.map((domain) => renderEditRow(domain, statesByDomainId.get(domain.id))));
  document.querySelector("select[name='focus_domain_id']").innerHTML = summaryOptions(active, review?.focus_domain_id);
  document.querySelector("select[name='sacrificed_domain_id']").innerHTML = summaryOptions(active, review?.sacrificed_domain_id);
  document.querySelector("select[name='focus_domain_id']").value = review?.focus_domain_id ? String(review.focus_domain_id) : "";
  document.querySelector("select[name='sacrificed_domain_id']").value = review?.sacrificed_domain_id ? String(review.sacrificed_domain_id) : "";
  document.querySelector("textarea[name='sacrifice_reason']").value = review?.sacrifice_reason || "";
  document.querySelector("textarea[name='notes']").value = review?.notes || "";
}

function renderEditRow(domain, currentState) {
  const row = document.createElement("section");
  row.className = "domain";
  row.innerHTML = `
    <div class="domain-head">
      <div class="domain-name">${escapeHtml(domain.name)}</div>
    </div>
    <div class="domain-grid">
      <label>Mode
        <select name="mode_${domain.id}">
          ${modeOptions().map(([value, label]) => `<option value="${value}">${label}</option>`).join("")}
        </select>
      </label>
      <label>Status
        <select name="status_${domain.id}">
          <option value="good">✓ Stable</option>
          <option value="warning">⚠ At Risk</option>
          <option value="critical">! Critical</option>
        </select>
      </label>
      <label class="full">Comment
        <textarea name="comment_${domain.id}" placeholder="Optional"></textarea>
      </label>
    </div>
  `;
  row.querySelector(`select[name="mode_${domain.id}"]`).value = currentState?.mode || "ignore";
  row.querySelector(`select[name="status_${domain.id}"]`).value = currentState?.status || "good";
  row.querySelector(`textarea[name="comment_${domain.id}"]`).value = currentState?.comment || "";
  return row;
}

function renderDomains() {
  const active = activeDomains();
  const archived = state.domains.filter((domain) => domain.archived_at !== null).sort(bySortOrder);
  el.manageDomains.replaceChildren(...active.map((domain) => renderManagedDomain(domain, false)));
  el.archivedDomains.replaceChildren(...archived.map((domain) => renderManagedDomain(domain, true)));
}

function renderManagedDomain(domain, archived) {
  const row = document.createElement("section");
  row.className = "domain";
  row.innerHTML = `
    <div class="domain-grid">
      <label class="full">Domain
        <input type="text" name="domain_name_${domain.id}" value="${escapeHtml(domain.name)}" autocomplete="off">
      </label>
      <div class="domain-actions full">
        ${archived ? `<button class="secondary" type="button" data-restore="${domain.id}">Restore</button>` : ""}
        ${!archived ? `<button class="secondary" type="button" data-up="${domain.id}">Up</button>` : ""}
        ${!archived ? `<button class="secondary" type="button" data-down="${domain.id}">Down</button>` : ""}
        ${!archived ? `<button class="ghost" type="button" data-archive="${domain.id}">Archive</button>` : ""}
      </div>
    </div>
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
  const up = row.querySelector("[data-up]");
  const down = row.querySelector("[data-down]");
  const archive = row.querySelector("[data-archive]");
  const restore = row.querySelector("[data-restore]");
  if (up) up.addEventListener("click", () => moveDomain(domain.id, -1));
  if (down) down.addEventListener("click", () => moveDomain(domain.id, 1));
  if (archive) archive.addEventListener("click", () => archiveDomain(domain.id));
  if (restore) restore.addEventListener("click", () => restoreDomain(domain.id));
  return row;
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
  await loadState();
  state.activeView = "current";
  render();
}

async function saveReview() {
  const active = activeDomains();
  const payload = {
    focus_domain_id: selectedNumber("focus_domain_id"),
    sacrificed_domain_id: selectedNumber("sacrificed_domain_id"),
    sacrifice_reason: document.querySelector("textarea[name='sacrifice_reason']").value.trim() || null,
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
  state.activeView = "current";
  render();
}

async function saveDomainOrder() {
  const ids = activeDomains().map((domain) => domain.id);
  await fetchJSON(`/workspaces/${state.workspace.id}/domains/order`, {
    method: "PUT",
    body: JSON.stringify({ domain_ids: ids }),
  });
  await loadState();
  render();
}

async function moveDomain(domainId, offset) {
  const ids = activeDomains().map((domain) => domain.id);
  const index = ids.indexOf(domainId);
  const target = index + offset;
  if (index < 0 || target < 0 || target >= ids.length) return;
  [ids[index], ids[target]] = [ids[target], ids[index]];
  await fetchJSON(`/workspaces/${state.workspace.id}/domains/order`, {
    method: "PUT",
    body: JSON.stringify({ domain_ids: ids }),
  });
  await loadState();
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

function summaryOptions(active, selectedId) {
  const options = ['<option value="">None</option>'];
  for (const domain of active) {
    options.push(`<option value="${domain.id}">${escapeHtml(domain.name)}</option>`);
  }
  return options.join("");
}

function modeOptions() {
  return [
    ["focus", "▲ Focus"],
    ["maintain", "✓ Maintain"],
    ["ignore", "○ Ignore"],
  ];
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

function setActiveView(view) {
  state.activeView = view;
  render();
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
