import { escapeHtml, modePresentation, setStatus, statusLabels } from "/js/presentation.js";
import { createTradeOffSummary } from "/js/tradeoff.js";

export function mapTimelineHistory(payload) {
  if (!payload || !Array.isArray(payload.items)) throw new Error("Timeline response is incomplete.");
  return payload.items.map((review) => {
    const issues = [];
    if (!Number.isInteger(review.iso_year) || !Number.isInteger(review.iso_week)) {
      issues.push("Week date is incomplete.");
    }
    const rawStates = Array.isArray(review.states) ? review.states : [];
    if (!Array.isArray(review.states)) issues.push("Domain states are missing.");
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
    if (review.focus_domain_id && !review.focus_domain_name) issues.push("The saved Main focus name is missing.");
    if (review.sacrificed_domain_id && !review.sacrificed_domain_name) {
      issues.push("The saved What gave way name is missing.");
    }
    if (review.sacrifice_reason !== null && review.sacrifice_reason !== undefined
      && typeof review.sacrifice_reason !== "string") {
      issues.push("The saved Why value is invalid.");
    }
    let lifecycle = review.lifecycle;
    if (!["provisional", "final"].includes(lifecycle)) {
      issues.push("The saved lifecycle is invalid.");
      lifecycle = "final";
    }
    const editable = lifecycle === "provisional" && review.editable === true;
    return { ...review, lifecycle, editable, states, issues };
  });
}

export function renderTimeline(elements, timeline, callbacks) {
  if (!elements.entries || !elements.status) return;
  if (timeline.loading) {
    setStatus(elements.status, "Loading timeline…");
    elements.entries.replaceChildren();
    return;
  }
  if (timeline.error) {
    setStatus(elements.status, "Timeline could not be loaded. Try again.", true);
    const retry = document.createElement("button");
    retry.className = "secondary timeline-retry";
    retry.type = "button";
    retry.textContent = "Retry";
    retry.addEventListener("click", callbacks.onRetry);
    elements.entries.replaceChildren(retry);
    return;
  }
  setStatus(elements.status, "");
  if (timeline.items === null) {
    elements.entries.replaceChildren();
    return;
  }
  if (timeline.items.length === 0) {
    elements.entries.replaceChildren(renderEmptyTimeline(callbacks.onCurrent));
    return;
  }
  elements.entries.replaceChildren(
    ...timeline.items.map((review, index) => renderTimelineWeek(review, index, callbacks.onEdit)),
  );
}

function renderEmptyTimeline(onCurrent) {
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
  current.addEventListener("click", onCurrent);
  empty.append(title, explanation, current);
  return empty;
}

function renderTimelineWeek(review, index, onEdit) {
  const details = document.createElement("details");
  details.className = "timeline-week";
  details.open = index < 3;

  const summary = document.createElement("summary");
  summary.className = "timeline-week-summary";
  const heading = document.createElement("span");
  heading.className = "timeline-week-heading";
  heading.setAttribute("role", "heading");
  heading.setAttribute("aria-level", "3");
  heading.textContent = Number.isInteger(review.iso_year) && Number.isInteger(review.iso_week)
    ? `Week ${review.iso_week}, ${review.iso_year}`
    : "Unknown week";
  const lifecycle = document.createElement("span");
  lifecycle.className = "timeline-week-lifecycle";
  lifecycle.textContent = review.lifecycle === "provisional" ? "Provisional" : "Final";
  const compactTradeoff = document.createElement("span");
  compactTradeoff.className = "timeline-week-compact-tradeoff";
  compactTradeoff.textContent = timelineCompactTradeoff(review);
  summary.append(heading, lifecycle, compactTradeoff);

  const content = document.createElement("div");
  content.className = "timeline-week-details";
  const tradeoff = document.createElement("div");
  tradeoff.className = "timeline-tradeoff";
  tradeoff.appendChild(createTradeOffSummary(review, {
    focusName: typeof review.focus_domain_name === "string" ? review.focus_domain_name : null,
    sacrificedName: typeof review.sacrificed_domain_name === "string" ? review.sacrificed_domain_name : null,
  }));
  content.appendChild(tradeoff);

  const groups = document.createElement("div");
  groups.className = "timeline-groups";
  for (const mode of ["focus", "maintain", "ignore"]) {
    const entries = review.states.filter((item) => item.mode === mode);
    if (entries.length) groups.appendChild(renderTimelineGroup(mode, entries));
  }
  content.appendChild(groups);

  if (review.editable) {
    const edit = document.createElement("button");
    edit.className = "secondary timeline-edit-review";
    edit.type = "button";
    edit.textContent = "Edit review";
    edit.addEventListener("click", onEdit);
    content.appendChild(edit);
  }
  if (review.issues.length) {
    const integrity = document.createElement("p");
    integrity.className = "status error timeline-integrity";
    integrity.textContent = `Some saved data could not be shown: ${[...new Set(review.issues)].join(" ")}`;
    content.appendChild(integrity);
  }
  details.append(summary, content);
  return details;
}

function timelineCompactTradeoff(review) {
  if (!review.focus_domain_id && !review.focus_domain_name) return "No primary focus";
  const focus = typeof review.focus_domain_name === "string" ? review.focus_domain_name : "Unknown domain";
  const sacrificed = typeof review.sacrificed_domain_name === "string"
    ? review.sacrificed_domain_name
    : "None recorded";
  return `Focus: ${focus} · Gave way: ${sacrificed}`;
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
