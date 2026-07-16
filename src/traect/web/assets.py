from __future__ import annotations

APP_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    <meta name="theme-color" content="#f7f4ef">
    <link rel="manifest" href="/manifest.webmanifest">
    <link rel="icon" href="/icon.svg" type="image/svg+xml">
    <title>-traect</title>
    <style>
      :root {
        color-scheme: light;
        --bg: #f7f4ef;
        --panel: #ffffff;
        --line: #ded8ce;
        --text: #1f2328;
        --muted: #6b716f;
        --focus: #0f5fff;
        --space-1: 0.5rem;
        --space-2: 0.75rem;
        --space-3: 1rem;
        --space-4: 1.5rem;
        --radius: 0.5rem;
      }
      * { box-sizing: border-box; }
      html, body {
        margin: 0;
        min-height: 100%;
        background: var(--bg);
        color: var(--text);
        font: 16px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }
      body { padding: calc(env(safe-area-inset-top) + 1rem) 1rem calc(env(safe-area-inset-bottom) + 2rem); }
      .app { max-width: 50rem; margin: 0 auto; }
      header { display: flex; align-items: end; justify-content: space-between; gap: 1rem; margin-bottom: 1.25rem; }
      h1 { margin: 0; font-size: 1.5rem; font-weight: 650; letter-spacing: 0; }
      .meta { color: var(--muted); font-size: 0.95rem; }
      form { display: grid; gap: 1.25rem; }
      section { display: grid; gap: 0.75rem; }
      .section-title { margin: 0; font-size: 0.95rem; font-weight: 600; color: var(--muted); }
      .domains { display: grid; gap: 0.75rem; }
      .domain { display: grid; gap: 0.75rem; padding: 0.9rem 0; border-top: 1px solid var(--line); }
      .domain:first-child { border-top: 0; padding-top: 0; }
      .domain-head { display: flex; align-items: baseline; justify-content: space-between; gap: 0.75rem; }
      .domain-name { font-weight: 600; font-size: 1rem; }
      .domain-grid { display: grid; gap: 0.6rem; grid-template-columns: repeat(2, minmax(0, 1fr)); }
      label { display: grid; gap: 0.35rem; font-size: 0.88rem; color: var(--muted); }
      select, textarea, input[type="text"] {
        width: 100%; border: 1px solid var(--line); border-radius: var(--radius); background: var(--panel);
        color: var(--text); padding: 0.72rem 0.8rem; font: inherit; min-height: 2.75rem;
      }
      select:focus,
      textarea:focus,
      input[type="text"]:focus,
      button:focus {
        outline: 2px solid var(--focus);
        outline-offset: 2px;
      }
      textarea { min-height: 3.5rem; resize: vertical; }
      .full { grid-column: 1 / -1; }
      .week-summary { display: grid; gap: 0.75rem; }
      .summary-grid { display: grid; gap: 0.75rem; }
      .actions { display: flex; justify-content: end; padding-top: 0.25rem; }
      button {
        border: 0; border-radius: 999px; background: var(--text); color: white; padding: 0.85rem 1.2rem;
        font: inherit; font-weight: 600; min-height: 2.75rem;
      }
      .status { min-height: 1.25rem; color: var(--muted); font-size: 0.95rem; }
      .error { color: #a62b2b; }
      .toolbar {
        display: flex;
        gap: 0.75rem;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 0.5rem;
      }
      .small { font-size: 0.9rem; color: var(--muted); }
      @media (max-width: 40rem) {
        header { align-items: start; flex-direction: column; }
        .domain-grid { grid-template-columns: 1fr; }
        .actions { justify-content: stretch; }
        button { width: 100%; }
      }
    </style>
  </head>
  <body>
    <main class="app">
      <header>
        <div>
          <h1>-traect</h1>
          <div class="meta" id="week-meta">Weekly review</div>
        </div>
        <div class="meta" id="save-state"></div>
      </header>

      <form id="review-form">
        <section>
          <div class="toolbar">
            <h2 class="section-title">Domains</h2>
            <div class="small" id="domain-count"></div>
          </div>
          <div class="domains" id="domains"></div>
        </section>

        <section class="week-summary">
          <h2 class="section-title">Week</h2>
          <div class="summary-grid">
            <label>Focus
              <select name="focus_domain_id"></select>
            </label>
            <label>Sacrificed
              <select name="sacrificed_domain_id"></select>
            </label>
            <label>Reason<textarea name="sacrifice_reason"></textarea></label>
            <label>Notes<textarea name="notes"></textarea></label>
          </div>
        </section>

        <div class="actions">
          <button type="submit">Save</button>
        </div>
        <div class="status" id="status"></div>
      </form>
    </main>
    <script>
      window.TRAECT_API_BASE = "";
    </script>
    <script src="/app.js" type="module"></script>
  </body>
</html>
"""

APP_JS = """const apiBase = window.TRAECT_API_BASE || "";
const storageKey = "traect.workspace_id";
const today = new Date();
const weekParts = isoWeek(today);
const state = { workspaceId: null, domains: [], week: null };

const form = document.getElementById("review-form");
const domainsEl = document.getElementById("domains");
const statusEl = document.getElementById("status");
const saveStateEl = document.getElementById("save-state");
const weekMetaEl = document.getElementById("week-meta");
const domainCountEl = document.getElementById("domain-count");

weekMetaEl.textContent = `Week ${weekParts.week}, ${weekParts.year}`;

const statusOptions = [
  ["good", "Good"],
  ["warning", "Warning"],
  ["critical", "Critical"],
];
const modeOptions = [
  ["focus", "Focus"],
  ["maintain", "Maintain"],
  ["ignore", "Ignore"],
];

boot().catch((error) => setStatus(error.message, true));

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  await save();
});

async function boot() {
  state.workspaceId = await getOrCreateWorkspace();
  const [domains, week] = await Promise.all([loadDomains(), loadCurrentWeek()]);
  state.domains = domains;
  state.week = week;
  render();
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
}

async function getOrCreateWorkspace() {
  const stored = window.localStorage.getItem(storageKey);
  if (stored) return Number(stored);
  const response = await request("/workspaces", {
    method: "POST",
    body: JSON.stringify({ name: "Life" }),
  });
  window.localStorage.setItem(storageKey, String(response.id));
  return response.id;
}

async function loadDomains() {
  const response = await request(`/workspaces/${state.workspaceId}/domains`);
  return response.items.filter((domain) => domain.archived_at === null);
}

async function loadCurrentWeek() {
  try {
    return await request(`/workspaces/${state.workspaceId}/weeks/current`);
  } catch (error) {
    if (error.status === 404) return null;
    throw error;
  }
}

function render() {
  domainCountEl.textContent = `${state.domains.length} active domains`;
  const week = state.week;
  const weekStates = new Map((week?.states || []).map((item) => [item.domain_id, item]));
  domainsEl.replaceChildren(...state.domains.map((domain) => renderDomain(domain, weekStates.get(domain.id))));
  populateSummarySelects();
  form.focus_domain_id.value = week?.focus_domain_id ? String(week.focus_domain_id) : "";
  form.sacrificed_domain_id.value = week?.sacrificed_domain_id ? String(week.sacrificed_domain_id) : "";
  form.sacrifice_reason.value = week?.sacrifice_reason || "";
  form.notes.value = week?.notes || "";
}

function renderDomain(domain, existing) {
  const wrapper = document.createElement("section");
  wrapper.className = "domain";
  wrapper.innerHTML = `
    <div class="domain-head">
      <div class="domain-name">${escapeHtml(domain.name)}</div>
    </div>
    <div class="domain-grid">
      <label>Status
        <select name="status_${domain.id}">
          ${statusOptions.map(([value, label]) => `<option value="${value}">${label}</option>`).join("")}
        </select>
      </label>
      <label>Mode
        <select name="mode_${domain.id}">
          ${modeOptions.map(([value, label]) => `<option value="${value}">${label}</option>`).join("")}
        </select>
      </label>
      <label class="full">Comment
        <textarea name="comment_${domain.id}" placeholder="Optional"></textarea>
      </label>
    </div>
  `;
  const status = wrapper.querySelector(`select[name="status_${domain.id}"]`);
  const mode = wrapper.querySelector(`select[name="mode_${domain.id}"]`);
  const comment = wrapper.querySelector(`textarea[name="comment_${domain.id}"]`);
  status.value = existing?.status || "warning";
  mode.value = existing?.mode || "maintain";
  comment.value = existing?.comment || "";
  return wrapper;
}

function populateSummarySelects() {
  const options = [
    '<option value="">None</option>',
    ...state.domains.map((domain) => `<option value="${domain.id}">${escapeHtml(domain.name)}</option>`),
  ];
  form.focus_domain_id.innerHTML = options.join("");
  form.sacrificed_domain_id.innerHTML = options.join("");
}

async function save() {
  setStatus("Saving...");
  const payload = {
    focus_domain_id: form.focus_domain_id.value ? Number(form.focus_domain_id.value) : null,
    sacrificed_domain_id: form.sacrificed_domain_id.value ? Number(form.sacrificed_domain_id.value) : null,
    sacrifice_reason: form.sacrifice_reason.value.trim() || null,
    notes: form.notes.value.trim() || null,
    states: state.domains.map((domain) => ({
      domain_id: domain.id,
      status: form[`status_${domain.id}`].value,
      mode: form[`mode_${domain.id}`].value,
      comment: form[`comment_${domain.id}`].value.trim() || null,
    })),
  };
  const week = await request(`/workspaces/${state.workspaceId}/weeks/${weekParts.year}/${weekParts.week}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  state.week = week;
  render();
  setStatus("Saved");
}

async function request(path, options = {}) {
  const response = await fetch(`${apiBase}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const error = new Error(data?.error || response.statusText);
    error.status = response.status;
    throw error;
  }
  return data;
}

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.className = isError ? "status error" : "status";
  saveStateEl.textContent = isError ? "" : message === "Saved" ? "Saved" : "";
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
  return value.replace(/[&<>\"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);
}
"""

MANIFEST = """{
  "name": "-traect",
  "short_name": "traect",
  "start_url": "/",
  "scope": "/",
  "display": "standalone",
  "background_color": "#f7f4ef",
  "theme_color": "#f7f4ef",
  "icons": []
}
"""

SW_JS = """self.addEventListener("install", (event) => {
  event.waitUntil(self.skipWaiting());
});
self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});
self.addEventListener("fetch", (event) => {
  event.respondWith(fetch(event.request));
});
"""

ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" role="img" aria-label="-traect">
  <rect width="128" height="128" rx="24" fill="#1f2328"/>
  <path d="M32 40h64v16H32zM32 68h40v16H32z" fill="#f7f4ef"/>
</svg>
"""
