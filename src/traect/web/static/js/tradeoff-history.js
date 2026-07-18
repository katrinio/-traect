import { createTimelineWeekLink, formatPercentage, formatWeekLabel, setStatus } from "/js/presentation.js";

export function mapTradeoffHistory(payload) {
  if (!payload || !payload.summary || !payload.range || !payload.integrity) {
    throw new Error("Trade-off history response is incomplete.");
  }
  for (const key of ["sacrifices", "pairs", "focus_breakdowns", "sacrifice_breakdowns", "weeks", "observations"]) {
    if (!Array.isArray(payload[key])) throw new Error("Trade-off history response is incomplete.");
  }
  return payload;
}

export function renderTradeoffHistory(elements, history, callbacks) {
  if (!elements.content || !elements.status) return;
  if (history.loading) {
    setStatus(elements.status, "Loading trade-off patterns…");
    elements.content.replaceChildren();
    return;
  }
  if (history.error) {
    setStatus(elements.status, "Trade-off patterns could not be loaded. Try again.", true);
    const retry = document.createElement("button");
    retry.className = "secondary tradeoff-history-retry";
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
  if (data.summary.reviewed_week_count === 0 && data.summary.excluded_pair_count === 0) {
    elements.content.replaceChildren(renderEmptyHistory());
    return;
  }
  const sections = [renderSummary(data.summary)];
  if (data.integrity.excluded_pair_count > 0) {
    sections.push(renderIntegrity(data.integrity.excluded_pair_count));
  }
  if (!data.pairs.length) sections.push(renderNoPairs(data.summary));
  else {
    sections.push(renderSacrificeRanking(data.sacrifices, data.summary.valid_pair_count));
    sections.push(renderPairRanking(data.pairs, data.summary.valid_pair_count));
    sections.push(renderFocusBreakdowns(data.focus_breakdowns));
    sections.push(renderSacrificeBreakdowns(data.sacrifice_breakdowns));
  }
  elements.content.replaceChildren(...sections);
}

function renderEmptyHistory() {
  const empty = document.createElement("div");
  empty.className = "tradeoff-history-empty";
  const title = document.createElement("p");
  title.textContent = "No trade-off history yet.";
  const explanation = document.createElement("p");
  explanation.className = "hint";
  explanation.textContent = "Recorded weekly trade-offs will appear here after reviews are saved.";
  empty.append(title, explanation);
  return empty;
}

function renderSummary(summary) {
  const list = document.createElement("dl");
  list.className = "tradeoff-history-summary";
  for (const [label, value] of [
    ["Valid focus–trade-off pairs", summary.valid_pair_count],
    ["With Primary focus", summary.focus_week_count],
    ["With What gave way", summary.sacrifice_week_count],
  ]) appendMetric(list, label, value);
  return list;
}

function appendMetric(list, label, value) {
  const row = document.createElement("div");
  const term = document.createElement("dt");
  const definition = document.createElement("dd");
  term.textContent = label;
  definition.textContent = String(value);
  row.append(term, definition);
  list.appendChild(row);
}

function renderIntegrity(count) {
  const notice = document.createElement("p");
  notice.className = "status tradeoff-history-integrity";
  notice.setAttribute("role", "status");
  notice.textContent = `${count} trade-off ${count === 1 ? "record was" : "records were"} excluded because historical data is inconsistent.`;
  return notice;
}

function renderNoPairs(summary) {
  const notice = document.createElement("p");
  notice.className = "tradeoff-history-empty";
  notice.textContent = summary.excluded_pair_count > 0
    && (summary.reviewed_week_count === 0 || summary.excluded_pair_count >= summary.reviewed_week_count)
    ? "Trade-off patterns cannot be summarized until the historical data is reviewed."
    : "No Domain was recorded as What gave way during this period.";
  return notice;
}

function renderSacrificeRanking(sacrifices, denominator) {
  const section = makeSection("What gave way most often", "Counts and shares use valid recorded trade-offs.");
  const list = document.createElement("ol");
  list.className = "tradeoff-sacrifice-ranking";
  for (const domain of sacrifices) {
    const item = document.createElement("li");
    const name = document.createElement("span");
    name.textContent = domain.name;
    appendDomainStatus(name, domain);
    const metric = document.createElement("span");
    metric.textContent = `${domain.count} of ${denominator} recorded trade-offs · ${formatPercentage(domain.share_of_pairs)}`;
    const recent = document.createElement("span");
    recent.className = "hint";
    recent.textContent = `Most recent: ${formatWeekLabel(domain.most_recent)}`;
    item.append(name, metric, recent);
    list.appendChild(item);
  }
  section.appendChild(list);
  return section;
}

function renderPairRanking(pairs, denominator) {
  const section = makeSection(
    "Recurring combinations",
    "The direction reads Primary focus → What gave way. It describes recorded co-occurrence only.",
  );
  const list = document.createElement("div");
  list.className = "tradeoff-pair-ranking";
  for (const pair of pairs) list.appendChild(renderPair(pair, denominator));
  section.appendChild(list);
  return section;
}

function renderPair(pair, denominator) {
  const details = document.createElement("details");
  details.className = "tradeoff-pair";
  const summary = document.createElement("summary");
  const label = document.createElement("span");
  label.className = "tradeoff-pair-label";
  label.textContent = `${pair.focus.name} → ${pair.sacrifice.name}`;
  const accessible = document.createElement("span");
  accessible.className = "visually-hidden";
  accessible.textContent = `Primary focus: ${pair.focus.name}. What gave way: ${pair.sacrifice.name}.`;
  appendDomainStatus(label, pair.focus);
  appendDomainStatus(label, pair.sacrifice);
  const metric = document.createElement("span");
  metric.textContent = `${pair.count} of ${denominator} recorded trade-offs · ${formatPercentage(pair.share_of_pairs)}`;
  const bar = document.createElement("span");
  bar.className = "tradeoff-pair-bar";
  bar.setAttribute("role", "img");
  bar.setAttribute("aria-label", `${pair.count} of ${denominator} recorded trade-offs`);
  const fill = document.createElement("span");
  fill.style.width = formatPercentage(pair.share_of_pairs);
  bar.appendChild(fill);
  summary.append(label, accessible, metric, bar);

  const detail = document.createElement("div");
  detail.className = "tradeoff-pair-detail";
  const recent = document.createElement("p");
  recent.textContent = `Most recent: ${formatWeekLabel(pair.most_recent)}.`;
  detail.appendChild(recent);
  details.append(summary, detail);
  return details;
}

function renderFocusBreakdowns(breakdowns) {
  const section = makeSection(
    "▶ By Primary focus",
    "Expand to see what gave way when each Domain was Primary focus.",
  );
  for (const breakdown of breakdowns) {
    const details = document.createElement("details");
    details.className = "tradeoff-breakdown";
    const summary = document.createElement("summary");
    summary.textContent = `When ${breakdown.focus.name} was Primary focus · ${breakdown.focus_week_count} weeks`;
    appendDomainStatus(summary, breakdown.focus);
    const list = document.createElement("ul");
    for (const item of breakdown.sacrifices) {
      const row = document.createElement("li");
      row.textContent = `${item.sacrifice.name} was recorded as What gave way · ${item.count} of ${breakdown.focus_week_count} weeks · ${formatPercentage(item.share_of_focus_weeks)}`;
      list.appendChild(row);
    }
    if (breakdown.no_tradeoff_count > 0) {
      const row = document.createElement("li");
      row.textContent = `No trade-off · ${breakdown.no_tradeoff_count} of ${breakdown.focus_week_count} weeks`;
      list.appendChild(row);
    }
    details.append(summary, list);
    section.appendChild(details);
  }
  return section;
}

function renderSacrificeBreakdowns(breakdowns) {
  const section = makeSection("▶ By What gave way", "Expand to see what was Primary focus when each Domain gave way.");
  for (const breakdown of breakdowns) {
    const details = document.createElement("details");
    details.className = "tradeoff-breakdown";
    const summary = document.createElement("summary");
    summary.textContent = `When ${breakdown.sacrifice.name} was What gave way · ${breakdown.sacrifice_week_count} weeks`;
    appendDomainStatus(summary, breakdown.sacrifice);
    const list = document.createElement("ul");
    for (const item of breakdown.focuses) {
      const row = document.createElement("li");
      row.textContent = `${item.focus.name} was Primary focus · ${item.count} weeks · ${formatPercentage(item.share_of_sacrifice_weeks)}`;
      list.appendChild(row);
    }
    details.append(summary, list);
    section.appendChild(details);
  }
  return section;
}

function renderChronology(weeks) {
  const section = makeSection("Reviewed weeks", "Saved weekly trade-off records in reverse chronological order.");
  const list = document.createElement("ol");
  list.className = "tradeoff-history-weeks";
  for (const week of weeks) {
    const label = week.status === "paired"
      ? `${week.focus.name} → ${week.sacrifice.name}`
      : (week.status === "focus_without_sacrifice"
        ? `${week.focus.name} · No trade-off`
        : (week.status === "no_focus" ? "No Primary focus" : "Excluded historical record"));
    list.appendChild(renderWeekLink(week, "Open saved trade-off review", label));
  }
  section.appendChild(list);
  return section;
}

function renderWeekLink(week, ariaPrefix, label = "") {
  const item = document.createElement("li");
  const lifecycle = week.lifecycle === "provisional" ? " · Provisional" : "";
  item.appendChild(createTimelineWeekLink(week, {
    text: `${formatWeekLabel(week)}${label ? ` · ${label}` : ""}${lifecycle}`,
    ariaLabel: `${ariaPrefix} for ${formatWeekLabel(week)}`,
  }));
  return item;
}

function renderObservations(observations) {
  const section = makeSection("Recorded observations");
  const list = document.createElement("ul");
  for (const observation of observations) {
    const item = document.createElement("li");
    item.dataset.observationCode = observation.code;
    item.textContent = observation.text;
    list.appendChild(item);
  }
  section.appendChild(list);
  return section;
}

function makeSection(title, hint = "") {
  const section = document.createElement("section");
  const heading = document.createElement("h4");
  heading.className = "section-title";
  heading.textContent = title;
  section.appendChild(heading);
  if (hint) {
    const explanation = document.createElement("p");
    explanation.className = "hint";
    explanation.textContent = hint;
    section.appendChild(explanation);
  }
  return section;
}

function appendDomainStatus(element, domain) {
  const statuses = [];
  if (domain.archived) statuses.push("Archived");
  if (domain.unavailable) statuses.push("Unavailable");
  if (!statuses.length) return;
  const status = document.createElement("span");
  status.className = "tradeoff-domain-status";
  status.textContent = ` · ${statuses.join(" · ")}`;
  element.appendChild(status);
}
