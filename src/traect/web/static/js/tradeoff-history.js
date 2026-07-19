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
  const sections = [];
  if (data.pairs.length > 0) {
    sections.push(renderRecordedMetrics(data));
    sections.push(renderSacrificeRanking(data.sacrifices, data.summary.valid_pair_count));
    sections.push(renderPairRanking(data.pairs, data.summary.valid_pair_count));
  } else {
    sections.push(renderNoPairs(data.summary));
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

function renderRecordedMetrics(data) {
  const container = document.createElement("div");
  container.className = "tradeoff-recorded-metrics";

  const title = document.createElement("div");
  title.className = "tradeoff-recorded-title";
  title.textContent = "Recorded trade-offs";

  const metrics = document.createElement("div");
  metrics.className = "tradeoff-recorded-values";

  // Calculate distinct domains appearing in valid pairs
  const domainsSet = new Set();
  for (const pair of data.pairs) {
    domainsSet.add(pair.focus.name);
    domainsSet.add(pair.sacrifice.name);
  }
  const uniqueDomains = domainsSet.size;

  // Unique combinations = number of distinct directional pairs
  const uniqueCombinations = data.pairs.length;

  // Valid pairs = total valid weekly records with both sides
  const validPairs = data.summary.valid_pair_count;

  const pairsMetric = document.createElement("span");
  pairsMetric.textContent = `${validPairs} pairs`;

  const domainsMetric = document.createElement("span");
  domainsMetric.textContent = `${uniqueDomains} domains`;

  const combinationsMetric = document.createElement("span");
  combinationsMetric.textContent = `${uniqueCombinations} unique combinations`;

  metrics.append(pairsMetric, domainsMetric, combinationsMetric);
  container.append(title, metrics);
  return container;
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
  const section = makeSection("What gave way most often");
  const container = document.createElement("div");
  container.className = "tradeoff-ranking-chart";
  for (const domain of sacrifices) {
    const row = document.createElement("div");
    row.className = "tradeoff-chart-row";

    const label = document.createElement("div");
    label.className = "tradeoff-chart-label";
    const name = document.createElement("span");
    name.textContent = domain.name;
    appendDomainStatus(name, domain);
    label.appendChild(name);

    const barContainer = document.createElement("div");
    barContainer.className = "tradeoff-chart-bar-container";
    const bar = document.createElement("div");
    bar.className = "tradeoff-chart-bar";
    bar.style.width = (domain.share_of_pairs * 100) + "%";
    barContainer.appendChild(bar);

    const percentage = document.createElement("span");
    percentage.className = "tradeoff-chart-percentage";
    percentage.textContent = formatPercentage(domain.share_of_pairs);

    row.append(label, barContainer, percentage);
    container.appendChild(row);
  }
  section.appendChild(container);
  return section;
}

function renderPairRanking(pairs, denominator) {
  const section = makeSection("Recurring trade-offs");
  const list = document.createElement("div");
  list.className = "tradeoff-pair-ranking";
  for (const pair of pairs) list.appendChild(renderPair(pair, denominator));
  section.appendChild(list);
  return section;
}

function renderPair(pair, denominator) {
  const item = document.createElement("div");
  item.className = "tradeoff-pair";

  const source = document.createElement("div");
  source.className = "tradeoff-pair-source";
  const sourceName = document.createElement("span");
  sourceName.textContent = pair.focus.name;
  appendDomainStatus(sourceName, pair.focus);
  source.appendChild(sourceName);

  const flow = document.createElement("div");
  flow.className = "tradeoff-pair-flow";
  const connector = document.createElement("div");
  connector.className = "tradeoff-pair-connector";
  connector.setAttribute("aria-hidden", "true");

  const destName = document.createElement("span");
  destName.className = "tradeoff-pair-dest-name";
  destName.textContent = pair.sacrifice.name;
  appendDomainStatus(destName, pair.sacrifice);

  const metric = document.createElement("span");
  metric.className = "tradeoff-pair-metric";
  metric.textContent = formatPercentage(pair.share_of_pairs);

  flow.append(connector, destName, metric);
  item.append(source, flow);
  return item;
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
