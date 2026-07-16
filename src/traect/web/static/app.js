const apiBase = window.TRAECT_API_BASE || "";
const storageKey = "traect.workspace_id";
const today = new Date();
const weekParts = isoWeek(today);

const state = {
  workspace: null,
  domains: [],
  week: null,
  view: "review",
  setupDraft: [{ name: "" }],
};

const headlineEl = document.getElementById("headline");
const saveStateEl = document.getElementById("save-state");
const weekMetaEl = document.getElementById("week-meta");
const domainCountEl = document.getElementById("domain-count");
const reviewViewEl = document.getElementById("review-view");
const setupViewEl = document.getElementById("setup-view");
const manageViewEl = document.getElementById("manage-view");
const reviewForm = document.getElementById("review-form");
const setupForm = document.getElementById("setup-form");
const setupDomainsEl = document.getElementById("setup-domains");
const reviewDomainsEl = document.getElementById("review-domains");
const manageDomainsEl = document.getElementById("manage-domains");
const archivedDomainsEl = document.getElementById("archived-domains");
const setupStatusEl = document.getElementById("setup-status");
const reviewStatusEl = document.getElementById("review-status");
const manageStatusEl = document.getElementById("manage-status");

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.view));
});
document.getElementById("add-domain").addEventListener("click", () => {
  state.setupDraft.push({ name: "" });
  renderSetup();
});
document.getElementById("add-active-domain").addEventListener("click", async () => {
  await withInlineError(manageStatusEl, createDomainFromManage);
});
document.getElementById("save-order").addEventListener("click", async () => {
  await withInlineError(manageStatusEl, saveOrder);
});
setupForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await withInlineError(setupStatusEl, createWorkspaceWithDomains);
});
reviewForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await withInlineError(reviewStatusEl, saveWeek);
});

boot().catch((error) => setStatus(reviewStatusEl, error.message, true));

async function boot() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
  await loadState();
  render();
}

async function loadState() {
  const current = await fetchJSON("/workspaces/current", { ignore404: true });
  if (!current) {
    state.workspace = null;
    state.domains = [];
    state.week = null;
    state.view = "review";
    return;
  }
  state.workspace = current;
  const [domains, week] = await Promise.all([
    fetchJSON(`/workspaces/${state.workspace.id}/domains`),
    fetchJSON(`/workspaces/${state.workspace.id}/weeks/current`, { ignore404: true }),
  ]);
  state.domains = domains.items;
  state.week = week;
}

function render() {
  renderTabs();
  headlineEl.textContent = state.workspace
    ? `${state.workspace.name}`
    : "Create a workspace to start";
  if (!state.workspace) {
    weekMetaEl.textContent = "";
    domainCountEl.textContent = "";
    showView("setup");
    renderSetup();
    return;
  }
  weekMetaEl.textContent = `Week ${weekParts.week}, ${weekParts.year}`;
  renderReview();
  renderManage();
  showView(state.view);
}

function renderTabs() {
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.setAttribute("aria-selected", String(button.dataset.view === state.view));
  });
}

function showView(view) {
  state.view = view;
  setupViewEl.classList.toggle("hidden", view !== "setup" && !state.workspace);
  reviewViewEl.classList.toggle("hidden", view !== "review" || !state.workspace);
  manageViewEl.classList.toggle("hidden", view !== "domains" || !state.workspace);
  renderTabs();
}

function renderSetup() {
  setupDomainsEl.replaceChildren(...state.setupDraft.map((item, index) => renderSetupDomain(item, index)));
  setStatus(setupStatusEl, "");
}

function renderSetupDomain(item, index) {
  const row = document.createElement("section");
  row.className = "domain";
  row.innerHTML = `
    <div class="domain-grid">
      <label class="full">Domain
        <input type="text" name="domain_${index}" value="${escapeHtml(item.name)}" autocomplete="off">
      </label>
      <div class="domain-actions full">
        <button class="secondary" type="button" data-move-up="${index}">Up</button>
        <button class="secondary" type="button" data-move-down="${index}">Down</button>
        <button class="ghost" type="button" data-remove="${index}">Remove</button>
      </div>
    </div>
  `;
  row.querySelector(`[data-remove]`).addEventListener("click", () => {
    if (state.setupDraft.length > 1) {
      state.setupDraft.splice(index, 1);
      renderSetup();
    }
  });
  row.querySelector(`[data-move-up]`).addEventListener("click", () => moveSetupDomain(index, -1));
  row.querySelector(`[data-move-down]`).addEventListener("click", () => moveSetupDomain(index, 1));
  row.querySelector("input").addEventListener("input", (event) => {
    item.name = event.target.value;
  });
  return row;
}

function moveSetupDomain(index, offset) {
  const target = index + offset;
  if (target < 0 || target >= state.setupDraft.length) return;
  [state.setupDraft[index], state.setupDraft[target]] = [state.setupDraft[target], state.setupDraft[index]];
  renderSetup();
}

function renderReview() {
  domainCountEl.textContent = `${state.domains.filter((domain) => domain.archived_at === null).length} active domains`;
  const week = state.week;
  const weekStates = new Map((week?.states || []).map((item) => [item.domain_id, item]));
  const activeDomains = state.domains.filter((domain) => domain.archived_at === null).sort(bySortOrder);
  reviewDomainsEl.replaceChildren(...activeDomains.map((domain) => renderReviewDomain(domain, weekStates.get(domain.id))));
  populateSummarySelects(activeDomains);
  document.querySelector("select[name='focus_domain_id']").value = week?.focus_domain_id ? String(week.focus_domain_id) : "";
  document.querySelector("select[name='sacrificed_domain_id']").value = week?.sacrificed_domain_id ? String(week.sacrificed_domain_id) : "";
  document.querySelector("textarea[name='sacrifice_reason']").value = week?.sacrifice_reason || "";
  document.querySelector("textarea[name='notes']").value = week?.notes || "";
}

function renderReviewDomain(domain, existing) {
  const wrapper = document.createElement("section");
  wrapper.className = "domain";
  const status = existing?.status || "inactive";
  wrapper.innerHTML = `
    <div class="domain-head">
      <div class="domain-name">${escapeHtml(domain.name)}</div>
      <div class="status-mark" data-status="${status}">
        <span class="status-symbol">${statusSymbol(status)}</span>
        <span class="status-text">${statusLabel(status)}</span>
      </div>
    </div>
    <div class="domain-grid">
      <label>Status
        <select name="status_${domain.id}">
          ${statusOptions().map(([value, label]) => `<option value="${value}">${label}</option>`).join("")}
        </select>
      </label>
      <label>Mode
        <select name="mode_${domain.id}">
          ${modeOptions().map(([value, label]) => `<option value="${value}">${label}</option>`).join("")}
        </select>
      </label>
      <label class="full">Comment
        <textarea name="comment_${domain.id}" placeholder="Optional"></textarea>
      </label>
    </div>
  `;
  wrapper.querySelector(`select[name="status_${domain.id}"]`).value = existing?.status || "warning";
  wrapper.querySelector(`select[name="mode_${domain.id}"]`).value = existing?.mode || "maintain";
  wrapper.querySelector(`textarea[name="comment_${domain.id}"]`).value = existing?.comment || "";
  return wrapper;
}

function renderManage() {
  const activeDomains = state.domains.filter((domain) => domain.archived_at === null).sort(bySortOrder);
  const archivedDomains = state.domains.filter((domain) => domain.archived_at !== null).sort(bySortOrder);
  manageDomainsEl.replaceChildren(...activeDomains.map((domain) => renderManageDomain(domain, false)));
  archivedDomainsEl.replaceChildren(...archivedDomains.map((domain) => renderManageDomain(domain, true)));
}

function renderManageDomain(domain, archived) {
  const wrapper = document.createElement("section");
  wrapper.className = "domain";
  wrapper.innerHTML = `
    <div class="domain-grid">
      <label class="full">Domain
        <input type="text" name="name_${domain.id}" value="${escapeHtml(domain.name)}" autocomplete="off">
      </label>
      <div class="domain-actions full">
        ${archived ? `<button class="secondary" type="button" data-restore="${domain.id}">Restore</button>` : ""}
        ${!archived ? `<button class="secondary" type="button" data-move-up="${domain.id}">Up</button>` : ""}
        ${!archived ? `<button class="secondary" type="button" data-move-down="${domain.id}">Down</button>` : ""}
        ${!archived ? `<button class="ghost" type="button" data-archive="${domain.id}">Archive</button>` : ""}
      </div>
    </div>
  `;
  const input = wrapper.querySelector(`input[name="name_${domain.id}"]`);
  input.addEventListener("change", async () => {
    await renameDomain(domain.id, input.value);
  });
  const up = wrapper.querySelector("[data-move-up]");
  const down = wrapper.querySelector("[data-move-down]");
  const archive = wrapper.querySelector("[data-archive]");
  const restore = wrapper.querySelector("[data-restore]");
  if (up) up.addEventListener("click", () => moveManagedDomain(domain.id, -1));
  if (down) down.addEventListener("click", () => moveManagedDomain(domain.id, 1));
  if (archive) archive.addEventListener("click", () => archiveDomain(domain.id));
  if (restore) restore.addEventListener("click", () => restoreDomain(domain.id));
  return wrapper;
}

function populateSummarySelects(activeDomains) {
  const options = [
    '<option value="">None</option>',
    ...activeDomains.map((domain) => `<option value="${domain.id}">${escapeHtml(domain.name)}</option>`),
  ];
  document.querySelector("select[name='focus_domain_id']").innerHTML = options.join("");
  document.querySelector("select[name='sacrificed_domain_id']").innerHTML = options.join("");
}

async function createWorkspaceWithDomains() {
  const workspaceName = setupForm.workspace_name.value.trim();
  const trimmedNames = state.setupDraft.map((item) => item.name.trim());
  clearSetupErrors();
  if (!workspaceName) {
    setStatus(setupStatusEl, "Workspace name is required.", true);
    return;
  }
  if (trimmedNames.length === 0 || trimmedNames.some((name) => !name)) {
    setStatus(setupStatusEl, "Domain names are required.", true);
    return;
  }
  if (hasDuplicateNames(trimmedNames)) {
    setStatus(setupStatusEl, "Domain names must be unique.", true);
    return;
  }
  const response = await fetchJSON("/workspaces", {
    method: "POST",
    body: JSON.stringify({ name: workspaceName, domains: trimmedNames.map((name) => ({ name })) }),
  });
  window.localStorage.setItem(storageKey, String(response.id));
  await loadState();
  state.view = "review";
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

async function renameDomain(domainId, name) {
  await withInlineError(manageStatusEl, async () => {
    await fetchJSON(`/domains/${domainId}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    });
    await loadState();
    render();
  });
}

async function moveManagedDomain(domainId, offset) {
  const activeDomains = state.domains.filter((domain) => domain.archived_at === null).sort(bySortOrder);
  const index = activeDomains.findIndex((domain) => domain.id === domainId);
  const target = index + offset;
  if (index < 0 || target < 0 || target >= activeDomains.length) return;
  const ids = activeDomains.map((domain) => domain.id);
  [ids[index], ids[target]] = [ids[target], ids[index]];
  await withInlineError(manageStatusEl, () => saveOrder(ids));
}

async function saveOrder(explicitIds = null) {
  const activeDomains = state.domains.filter((domain) => domain.archived_at === null).sort(bySortOrder);
  const ids = explicitIds || activeDomains.map((domain) => domain.id);
  await fetchJSON(`/workspaces/${state.workspace.id}/domains/order`, {
    method: "PUT",
    body: JSON.stringify({ domain_ids: ids }),
  });
  await loadState();
  render();
}

async function archiveDomain(domainId) {
  await withInlineError(manageStatusEl, async () => {
    await fetchJSON(`/domains/${domainId}/archive`, { method: "POST" });
    await loadState();
    render();
  });
}

async function restoreDomain(domainId) {
  await withInlineError(manageStatusEl, async () => {
    await fetchJSON(`/domains/${domainId}/restore`, { method: "POST" });
    await loadState();
    render();
  });
}

async function saveWeek() {
  const activeDomains = state.domains.filter((domain) => domain.archived_at === null).sort(bySortOrder);
  const payload = {
    focus_domain_id: selectedNumber("focus_domain_id"),
    sacrificed_domain_id: selectedNumber("sacrificed_domain_id"),
    sacrifice_reason: document.querySelector("textarea[name='sacrifice_reason']").value.trim() || null,
    notes: document.querySelector("textarea[name='notes']").value.trim() || null,
    states: activeDomains.map((domain) => ({
      domain_id: domain.id,
      status: document.querySelector(`select[name='status_${domain.id}']`).value,
      mode: document.querySelector(`select[name='mode_${domain.id}']`).value,
      comment: document.querySelector(`textarea[name='comment_${domain.id}']`).value.trim() || null,
    })),
  };
  await fetchJSON(`/workspaces/${state.workspace.id}/weeks/${weekParts.year}/${weekParts.week}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  await loadState();
  render();
  setStatus(reviewStatusEl, "Saved");
}

function selectedNumber(name) {
  const value = document.querySelector(`select[name='${name}']`).value;
  return value ? Number(value) : null;
}

function hasDuplicateNames(names) {
  const normalized = names.map((name) => name.toLowerCase());
  return new Set(normalized).size !== normalized.length;
}

function clearSetupErrors() {
  setStatus(setupStatusEl, "");
}

async function withInlineError(element, action) {
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

function setView(view) {
  state.view = view;
  render();
}

function statusOptions() {
  return [
    ["good", "▲ Focus"],
    ["warning", "✓ Maintain"],
    ["critical", "⚠ At Risk"],
  ];
}

function modeOptions() {
  return [
    ["focus", "Focus"],
    ["maintain", "Maintain"],
    ["ignore", "Ignore"],
  ];
}

function statusLabel(status) {
  const map = {
    good: "▲ Focus",
    warning: "✓ Maintain",
    critical: "⚠ At Risk",
    inactive: "○ Inactive",
  };
  return map[status] || "○ Inactive";
}

function statusSymbol(status) {
  const map = {
    good: "▲",
    warning: "✓",
    critical: "⚠",
    inactive: "○",
  };
  return map[status] || "○";
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
