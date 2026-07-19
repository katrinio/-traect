import { createTimelineWeekLink, formatPercentage, formatWeekLabel, setStatus } from "/js/presentation.js";

export function mapFocusHistory(payload) {
  if (!payload || !payload.summary || !Array.isArray(payload.domains) || !Array.isArray(payload.weeks)) {
    throw new Error("Focus history response is incomplete.");
  }
  if (!Array.isArray(payload.zero_focus_domains) || !payload.excluded_reasons || !payload.range) {
    throw new Error("Focus history response is incomplete.");
  }
  return payload;
}

export function renderFocusHistory(elements, history, callbacks) {
  if (!elements.content || !elements.status || !elements.range) return;
  elements.range.value = history.range;
  elements.range.disabled = history.loading;
  if (history.loading) {
    setStatus(elements.status, "Loading focus history…");
    elements.content.replaceChildren();
    return;
  }
  if (history.error) {
    setStatus(elements.status, "Focus history could not be loaded. Try again.", true);
    const retry = document.createElement("button");
    retry.className = "secondary focus-history-retry";
    retry.type = "button";
    retry.textContent = "Retry";
    retry.addEventListener("click", callbacks.onRetry);
    elements.content.replaceChildren(retry);
    return;
  }
  setStatus(elements.status, "");
  if (!history.data) {
    elements.content.replaceChildren();
    return;
  }
  const data = history.data;
  if (data.summary.reviewed_week_count === 0) {
    elements.content.replaceChildren(renderEmptyHistory());
    return;
  }
  const sections = [renderSummary(data.summary)];
  if (data.summary.excluded_week_count > 0) sections.push(renderIntegrityNotice(data.summary.excluded_week_count));
  if (data.domains.length > 0) sections.push(renderDistribution(data.domains, data.summary.reviewed_week_count));
  else sections.push(renderNoFocusedWeeks());
  if (data.zero_focus_domains.length > 0) sections.push(renderZeroFocusDomains(data.zero_focus_domains));
  sections.push(renderSequence(data.weeks));
  elements.content.replaceChildren(...sections);
}

function renderEmptyHistory() {
  const empty = document.createElement("div");
  empty.className = "focus-history-empty";
  const title = document.createElement("p");
  title.textContent = "No focus history yet.";
  const explanation = document.createElement("p");
  explanation.className = "hint";
  explanation.textContent = "Primary focus will appear here after weekly reviews are saved.";
  empty.append(title, explanation);
  return empty;
}

function renderSummary(summary) {
  const container = document.createElement("div");
  container.className = "focus-history-summary";

  const items = [
    { label: "reviewed", value: summary.reviewed_week_count },
    { label: "focused", value: summary.focused_week_count },
    { label: "empty", value: summary.no_focus_week_count },
  ];

  for (const item of items) {
    const cell = document.createElement("div");
    cell.className = "focus-summary-cell";

    const value = document.createElement("div");
    value.className = "focus-summary-value";
    value.textContent = String(item.value);

    const label = document.createElement("div");
    label.className = "focus-summary-label";
    label.textContent = item.label;

    cell.append(value, label);
    container.appendChild(cell);
  }

  return container;
}

function renderIntegrityNotice(excludedCount) {
  const notice = document.createElement("p");
  notice.className = "status focus-history-integrity";
  notice.setAttribute("role", "status");
  notice.textContent = `${excludedCount} saved ${excludedCount === 1 ? "week was" : "weeks were"} excluded because focus data is inconsistent.`;
  return notice;
}

function renderDistribution(domains, reviewedWeekCount) {
  const section = document.createElement("section");
  section.className = "focus-history-distribution";
  const heading = document.createElement("h4");
  heading.className = "section-title";
  heading.textContent = "Distribution";
  const rows = document.createElement("div");
  rows.className = "focus-history-bars";
  rows.replaceChildren(...domains.map((domain) => renderDomainHistory(domain, reviewedWeekCount)));
  section.append(heading, rows);
  return section;
}

function renderDomainHistory(domain, reviewedWeekCount) {
  const container = document.createElement("div");
  container.className = "focus-domain-history";

  // Domain name with status flags
  const nameRow = document.createElement("div");
  nameRow.className = "focus-domain-name-row";
  const name = document.createElement("span");
  name.className = "focus-domain-name";
  name.textContent = domain.name;
  if (domain.archived || domain.unavailable) {
    const flags = [];
    if (domain.archived) flags.push("Archived");
    if (domain.unavailable) flags.push("Unavailable");
    const status = document.createElement("span");
    status.className = "focus-domain-status";
    status.textContent = ` · ${flags.join(" · ")}`;
    nameRow.append(name, status);
  } else {
    nameRow.append(name);
  }

  // Progress bar
  const percentage = formatPercentage(domain.focus_share);
  const chart = document.createElement("div");
  chart.className = "focus-domain-bar";
  chart.setAttribute("role", "img");
  chart.setAttribute("aria-label", `${domain.name}: ${domain.focus_count} of ${reviewedWeekCount} reviewed weeks, ${percentage}`);
  const fill = document.createElement("span");
  fill.className = "focus-domain-bar-fill";
  fill.style.width = percentage;
  chart.appendChild(fill);

  // Metrics and most recent week
  const metricRow = document.createElement("div");
  metricRow.className = "focus-domain-metric-row";
  const metric = document.createElement("span");
  metric.className = "focus-domain-metric";
  metric.textContent = `${domain.focus_count} / ${reviewedWeekCount} · ${percentage}`;
  const recent = document.createElement("span");
  recent.className = "focus-domain-recent";
  recent.textContent = formatWeekLabel(domain.most_recent_focus);
  metricRow.append(metric, recent);

  // Collapsible weeks list
  const details = document.createElement("details");
  details.className = "focus-domain-weeks-detail";
  const summary = document.createElement("summary");
  summary.textContent = `View all ${domain.focus_count} weeks`;
  const list = document.createElement("ul");
  list.className = "focus-domain-weeks-list";
  list.replaceChildren(...domain.weeks.map((week) => renderWeekPlainItem(week)));
  details.append(summary, list);

  container.append(nameRow, chart, metricRow, details);
  return container;
}

function renderNoFocusedWeeks() {
  const notice = document.createElement("p");
  notice.className = "focus-history-no-focus";
  notice.textContent = "No reviewed week in this period has a Primary focus.";
  return notice;
}

function renderZeroFocusDomains(domains) {
  const section = document.createElement("section");
  section.className = "focus-history-zero";
  const heading = document.createElement("h4");
  heading.className = "section-title";
  heading.textContent = "No Primary focus in this period";
  const list = document.createElement("ul");
  for (const domain of domains) {
    const item = document.createElement("li");
    item.textContent = domain.name;
    list.appendChild(item);
  }
  section.append(heading, list);
  return section;
}

function renderSequence(weeks) {
  const section = document.createElement("section");
  section.className = "focus-history-sequence";

  const details = document.createElement("details");
  details.className = "focus-history-accordion";

  const summary = document.createElement("summary");
  summary.className = "focus-history-accordion-summary";
  const title = document.createElement("span");
  title.textContent = "Reviewed weeks";
  const count = document.createElement("span");
  count.className = "focus-history-accordion-count";
  count.textContent = `(${weeks.length})`;
  summary.append(title, " ", count);

  const list = document.createElement("ol");
  list.className = "focus-history-weeks-list";
  list.replaceChildren(...weeks.map((week) => renderWeekPlainItem(week, true)));

  details.append(summary, list);
  section.appendChild(details);
  return section;
}

function renderWeekLinkItem(week, includeFocus = false) {
  const item = document.createElement("li");
  const lifecycle = week.lifecycle === "provisional" ? " · Provisional" : "";
  const focus = includeFocus ? ` · ${week.focus?.name || "No Primary focus"}` : "";
  item.appendChild(createTimelineWeekLink(week, {
    text: `${formatWeekLabel(week)}${focus}${lifecycle}`,
    ariaLabel: `Open saved review for ${formatWeekLabel(week)}`,
  }));
  return item;
}

function renderWeekPlainItem(week, includeFocus = false) {
  const item = document.createElement("li");
  const lifecycle = week.lifecycle === "provisional" ? " · Provisional" : "";
  const focus = includeFocus ? ` · ${week.focus?.name || "No Primary focus"}` : "";
  item.textContent = `${formatWeekLabel(week)}${focus}${lifecycle}`;
  return item;
}
