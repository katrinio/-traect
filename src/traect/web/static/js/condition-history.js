import {
  conditionPresentation,
  createTimelineWeekLink,
  formatPercentage,
  formatWeekLabel,
  setStatus,
} from "/js/presentation.js";

export function mapConditionHistory(payload) {
  if (!payload || !payload.range || !Array.isArray(payload.domains) || !payload.integrity) {
    throw new Error("Condition history response is incomplete.");
  }
  if (payload.history && (!payload.history.summary || !Array.isArray(payload.history.weeks))) {
    throw new Error("Condition history response is incomplete.");
  }
  if (payload.history && (!payload.history.paused_sequences || !Array.isArray(payload.history.paused_sequences.streaks))) {
    throw new Error("Condition history response is incomplete.");
  }
  return payload;
}

export function renderConditionHistory(elements, state, callbacks) {
  if (!elements.content || !elements.status || !elements.domain) return;
  elements.domain.disabled = state.loading;
  if (state.data) renderDomainOptions(elements.domain, state.data.domains, state.domainId);
  if (state.loading) {
    setStatus(elements.status, "Loading Condition history…");
    elements.content.replaceChildren();
    return;
  }
  if (state.error) {
    setStatus(elements.status, "Condition history could not be loaded. Try again.", true);
    const retry = document.createElement("button");
    retry.className = "secondary condition-history-retry";
    retry.type = "button";
    retry.textContent = "Retry";
    retry.addEventListener("click", callbacks.onRetry);
    elements.content.replaceChildren(retry);
    return;
  }
  setStatus(elements.status, "");
  if (!state.data) {
    elements.content.replaceChildren();
    return;
  }
  if (!state.data.history) {
    elements.content.replaceChildren(renderNoDomains());
    return;
  }
  const history = state.data.history;
  const sections = [];
  if (state.data.integrity.excluded_week_count > 0) {
    sections.push(renderIntegrityNotice(state.data.integrity.excluded_week_count, "review"));
  }
  if (history.summary.reviewed_week_count === 0) {
    sections.push(renderEmptyHistory());
  } else {
    sections.push(renderLatest(history.summary.latest_record));
    if (history.summary.excluded_state_count > 0) {
      sections.push(renderIntegrityNotice(history.summary.excluded_state_count, "Condition record"));
    }
    if (history.summary.recorded_state_count === 0) {
      sections.push(renderNoRecordedCondition(history.summary.excluded_state_count));
    } else {
      sections.push(renderTimeline(history.weeks));
      sections.push(renderDistribution(history.summary));
    }
    sections.push(renderPausedSequences(history.paused_sequences, history.weeks));
  }
  elements.content.replaceChildren(...sections);
}

function renderDomainOptions(select, domains, selectedDomainId) {
  const options = domains.map((domain) => {
    const suffix = domain.archived ? " · Archived" : (domain.unavailable ? " · Unavailable" : "");
    const option = document.createElement("option");
    option.value = String(domain.domain_id);
    option.textContent = `${domain.name}${suffix}`;
    return option;
  });
  select.replaceChildren(...options);
  if (selectedDomainId !== null) select.value = String(selectedDomainId);
}

function renderNoDomains() {
  const empty = document.createElement("p");
  empty.className = "condition-history-empty";
  empty.textContent = "No Domains are available for Condition history.";
  return empty;
}

function renderEmptyHistory() {
  const empty = document.createElement("div");
  empty.className = "condition-history-empty";
  const title = document.createElement("p");
  title.textContent = "No Condition history yet.";
  const explanation = document.createElement("p");
  explanation.className = "hint";
  explanation.textContent = "Condition records will appear here after weekly reviews are saved.";
  empty.append(title, explanation);
  return empty;
}

function renderDomainHeader(domain) {
  const heading = document.createElement("div");
  heading.className = "condition-domain-heading";
  const name = document.createElement("h4");
  name.className = "section-title";
  name.textContent = domain.name;
  heading.appendChild(name);
  if (domain.archived || domain.unavailable) {
    const status = document.createElement("span");
    status.className = "condition-domain-status";
    status.textContent = domain.archived ? "Archived" : "Unavailable";
    heading.appendChild(status);
  }
  return heading;
}

function renderLatest(latest) {
  const section = document.createElement("section");
  section.className = "condition-latest";
  const heading = document.createElement("h4");
  heading.className = "section-title";
  heading.textContent = "Most recent record";
  const value = document.createElement("p");
  if (latest) {
    value.textContent = `${conditionPresentation[latest.condition].label} · ${formatWeekLabel(latest)}`;
    if (latest.lifecycle === "provisional") value.append(" · Provisional");
  } else value.textContent = "No recorded Condition in this period.";
  section.append(heading, value);
  return section;
}

function renderDistribution(summary) {
  const section = document.createElement("section");
  section.className = "condition-distribution";

  const headingContainer = document.createElement("div");
  headingContainer.className = "condition-distribution-heading";
  const heading = document.createElement("h4");
  heading.className = "section-title";
  heading.textContent = "Recorded states";
  const count = document.createElement("span");
  count.className = "condition-distribution-count";
  count.textContent = String(summary.recorded_state_count);
  headingContainer.append(heading, count);

  const list = document.createElement("dl");
  list.className = "condition-summary";

  for (const condition of ["stable", "at_risk", "critical"]) {
    const presentation = conditionPresentation[condition];
    const row = document.createElement("div");
    row.className = "condition-summary-row";

    const iconCell = document.createElement("span");
    iconCell.className = `condition-summary-icon condition-state-${condition}`;
    iconCell.textContent = presentation.symbol;

    const labelCell = document.createElement("dt");
    labelCell.className = "condition-summary-label";
    labelCell.textContent = presentation.label;

    const valueCell = document.createElement("dd");
    valueCell.className = "condition-summary-value";
    valueCell.textContent = `${summary.counts[condition]} · ${formatPercentage(summary.shares[condition])}`;

    row.append(iconCell, labelCell, valueCell);
    list.appendChild(row);
  }

  section.append(headingContainer, list);
  return section;
}

function renderCoverage(summary) {
  const section = document.createElement("section");
  section.className = "condition-coverage";
  const heading = document.createElement("h4");
  heading.className = "section-title";
  heading.textContent = "Snapshot coverage";
  const value = document.createElement("p");
  value.className = "hint";
  value.textContent = `Present in ${summary.present_state_count} of ${summary.reviewed_week_count} reviewed weeks · ${summary.absent_state_count} absent from reviewed snapshots.`;
  section.append(heading, value);
  return section;
}

function appendMetric(list, label, value) {
  const row = document.createElement("div");
  const term = document.createElement("dt");
  const definition = document.createElement("dd");
  term.textContent = label;
  definition.textContent = value;
  row.append(term, definition);
  list.appendChild(row);
}

function renderNoRecordedCondition(excludedCount) {
  const notice = document.createElement("p");
  notice.className = "condition-history-empty";
  notice.textContent = excludedCount > 0
    ? "Condition history for this Domain cannot be summarized until its historical data is reviewed."
    : "No Condition was recorded for this Domain during the selected period.";
  return notice;
}

function renderTimeline(weeks) {
  const section = document.createElement("section");
  section.className = "condition-timeline";
  const heading = document.createElement("h4");
  heading.className = "section-title";
  heading.textContent = "Condition timeline";

  const container = document.createElement("div");
  container.className = "condition-timeline-container";

  // Week numbers row
  const numberRow = document.createElement("div");
  numberRow.className = "condition-timeline-numbers";

  // Timeline markers row
  const timelineRow = document.createElement("div");
  timelineRow.className = "condition-timeline-markers";

  for (const week of weeks) {
    const numberCell = document.createElement("div");
    numberCell.className = "condition-timeline-number";
    numberCell.textContent = week.iso_week;
    numberRow.appendChild(numberCell);

    const marker = document.createElement("div");
    marker.className = `condition-timeline-marker condition-timeline-${week.presence}`;

    if (week.presence === "recorded") {
      marker.className += ` condition-state-${week.condition}`;
      const icon = document.createElement("span");
      icon.className = "condition-marker-icon";
      const presentation = conditionPresentation[week.condition];
      icon.textContent = presentation.symbol;
      marker.appendChild(icon);
      marker.setAttribute("title", `${presentation.label} · Week ${week.iso_week}`);
    } else if (week.presence === "absent") {
      marker.textContent = "—";
      marker.setAttribute("title", `Absent from snapshot · Week ${week.iso_week}`);
    } else {
      marker.textContent = "×";
      marker.setAttribute("title", `Excluded historical state · Week ${week.iso_week}`);
    }
    timelineRow.appendChild(marker);
  }

  // Legend
  const legend = document.createElement("div");
  legend.className = "condition-timeline-legend";
  const legendItems = [
    { symbol: conditionPresentation.stable.symbol, label: "Stable", className: "condition-state-stable" },
    { symbol: conditionPresentation.at_risk.symbol, label: "At risk", className: "condition-state-at_risk" },
    { symbol: conditionPresentation.critical.symbol, label: "Critical", className: "condition-state-critical" },
    { symbol: "—", label: "Paused", className: "condition-timeline-absent" },
  ];

  for (const item of legendItems) {
    const legendItem = document.createElement("div");
    legendItem.className = "condition-legend-item";
    const icon = document.createElement("span");
    icon.className = `condition-legend-icon ${item.className}`;
    icon.textContent = item.symbol;
    const label = document.createElement("span");
    label.className = "condition-legend-label";
    label.textContent = item.label;
    legendItem.append(icon, label);
    legend.appendChild(legendItem);
  }

  container.append(numberRow, timelineRow, legend);
  section.append(heading, container);
  return section;
}

function renderSequence(weeks) {
  const section = document.createElement("section");
  section.className = "condition-sequence";
  const heading = document.createElement("h4");
  heading.className = "section-title";
  heading.textContent = "Reviewed weeks";
  const explanation = document.createElement("p");
  explanation.className = "hint";
  explanation.textContent = "A dash means the review exists but this Domain is absent from its saved snapshot.";
  const list = document.createElement("ol");
  for (const week of weeks) list.appendChild(renderWeek(week));
  section.append(heading, explanation, list);
  return section;
}

function renderPausedSequences(sequences, weeks) {
  const section = document.createElement("section");
  section.className = "paused-sequences";
  const heading = document.createElement("h4");
  heading.className = "section-title";
  heading.textContent = "Paused history";
  section.appendChild(heading);

  if (sequences.excluded_state_count > 0) {
    section.appendChild(renderIntegrityNotice(sequences.excluded_state_count, "Attention record"));
  }

  if (!sequences.streaks.length) {
    const empty = document.createElement("p");
    empty.className = "condition-history-empty";
    empty.textContent = "No paused sequences have been recorded.";
    section.appendChild(empty);
    return section;
  }

  const summaries = document.createElement("div");
  summaries.className = "paused-sequence-summaries";
  summaries.append(
    renderPausedSummary(
      "Current paused sequence",
      sequences.current_streak.active
        ? `${formatReviewedWeeks(sequences.current_streak.length)} · Started ${formatWeekLabel(sequences.current_streak.started)}`
        : "No active paused sequence",
    ),
    renderPausedSummary(
      "Longest paused sequence",
      `${formatReviewedWeeks(sequences.longest_streak.length)} · ${formatWeekRange(sequences.longest_streak)}`,
    ),
  );
  section.append(summaries);

  if (weeks && weeks.length > 0) {
    section.appendChild(renderPausedTimeline(weeks, sequences));
  }

  return section;
}

function renderPausedSummary(label, value) {
  const summary = document.createElement("div");
  const heading = document.createElement("h5");
  heading.textContent = label;
  const text = document.createElement("p");
  text.textContent = value;
  summary.append(heading, text);
  return summary;
}

function renderPausedTimeline(weeks, sequences) {
  const section = document.createElement("section");
  section.className = "paused-timeline";

  const container = document.createElement("div");
  container.className = "paused-timeline-container";

  // Week numbers row
  const numberRow = document.createElement("div");
  numberRow.className = "paused-timeline-numbers";

  // Timeline markers row
  const timelineRow = document.createElement("div");
  timelineRow.className = "paused-timeline-markers";

  // Build a set of paused week numbers for quick lookup
  const pausedWeekNumbers = new Set();
  for (const streak of sequences.streaks) {
    for (const week of streak.weeks) {
      pausedWeekNumbers.add(week.iso_week);
    }
  }

  for (const week of weeks) {
    const numberCell = document.createElement("div");
    numberCell.className = "paused-timeline-number";
    numberCell.textContent = week.iso_week;
    numberRow.appendChild(numberCell);

    const marker = document.createElement("div");
    marker.className = "paused-timeline-marker";

    if (pausedWeekNumbers.has(week.iso_week)) {
      marker.classList.add("paused-timeline-paused");
      marker.textContent = "—";
      marker.setAttribute("title", `Paused · Week ${week.iso_week}`);
    } else {
      marker.classList.add("paused-timeline-active");
      if (week.presence === "recorded") {
        const presentation = conditionPresentation[week.condition];
        marker.textContent = presentation.symbol;
        marker.setAttribute("title", `${presentation.label} · Week ${week.iso_week}`);
      } else {
        marker.textContent = "·";
        marker.setAttribute("title", `No record · Week ${week.iso_week}`);
      }
    }
    timelineRow.appendChild(marker);
  }

  container.append(numberRow, timelineRow);
  section.appendChild(container);
  return section;
}

function renderPausedStreak(streak) {
  const item = document.createElement("li");
  item.className = "paused-sequence-item";
  const heading = document.createElement("p");
  heading.textContent = `${formatWeekRange(streak)} · ${formatReviewedWeeks(streak.length)}${streak.active ? " · Current" : ""}`;
  const weeks = document.createElement("ul");
  for (const week of streak.weeks) {
    const weekItem = document.createElement("li");
    weekItem.appendChild(createTimelineWeekLink(week, {
      text: `${formatWeekLabel(week)} · Paused`,
      ariaLabel: `Open paused sequence review for ${formatWeekLabel(week)}`,
    }));
    weeks.appendChild(weekItem);
  }
  item.append(heading, weeks);
  return item;
}

function formatWeekRange(streak) {
  const started = formatWeekLabel(streak.started);
  const ended = formatWeekLabel(streak.ended);
  return started === ended ? started : `${started} → ${ended}`;
}

function formatReviewedWeeks(count) {
  return `${count} consecutive reviewed ${count === 1 ? "week" : "weeks"}`;
}

function renderWeek(week) {
  const item = document.createElement("li");
  item.className = `condition-week condition-week-${week.presence}`;
  const link = createTimelineWeekLink(week, {
    text: formatWeekLabel(week),
    ariaLabel: `Open saved review for ${formatWeekLabel(week)}`,
  });
  const value = document.createElement("span");
  if (week.presence === "recorded") {
    const presentation = conditionPresentation[week.condition];
    value.textContent = `${presentation.symbol} ${presentation.label}`;
  } else if (week.presence === "absent") value.textContent = "— Absent from snapshot";
  else value.textContent = "— Excluded historical state";
  const lifecycle = document.createElement("span");
  lifecycle.className = "condition-week-lifecycle";
  lifecycle.textContent = week.lifecycle === "provisional" ? "Provisional" : "Final";
  item.append(link, value, lifecycle);
  return item;
}

function renderTransitions(transitions) {
  const section = document.createElement("section");
  section.className = "condition-transitions";
  const heading = document.createElement("h4");
  heading.className = "section-title";
  heading.textContent = "Recorded changes";
  const list = document.createElement("ul");
  for (const transition of transitions) {
    const item = document.createElement("li");
    item.textContent = `Changed from ${conditionPresentation[transition.from].label} to ${conditionPresentation[transition.to].label} between Weeks ${transition.from_week.iso_week} and ${transition.to_week.iso_week}.`;
    list.appendChild(item);
  }
  section.append(heading, list);
  return section;
}

function renderRuns(runs) {
  const section = document.createElement("section");
  section.className = "condition-runs";
  const heading = document.createElement("h4");
  heading.className = "section-title";
  heading.textContent = "Consecutive records";
  const list = document.createElement("ul");
  for (const run of runs) {
    const item = document.createElement("li");
    const weeks = run.from_week.iso_week === run.to_week.iso_week
      ? `Week ${run.from_week.iso_week}`
      : `Weeks ${run.from_week.iso_week}–${run.to_week.iso_week}`;
    item.textContent = `${conditionPresentation[run.condition].label} · ${run.count} consecutive ${run.count === 1 ? "record" : "records"} · ${weeks}`;
    list.appendChild(item);
  }
  section.append(heading, list);
  return section;
}

function renderObservations(observations) {
  const section = document.createElement("section");
  section.className = "condition-observations";
  const heading = document.createElement("h4");
  heading.className = "section-title";
  heading.textContent = "Recorded observations";
  const list = document.createElement("ul");
  for (const observation of observations) {
    const item = document.createElement("li");
    item.dataset.observationCode = observation.code;
    item.textContent = observation.text;
    list.appendChild(item);
  }
  section.append(heading, list);
  return section;
}

function renderIntegrityNotice(count, subject) {
  const notice = document.createElement("p");
  notice.className = "status condition-history-integrity";
  notice.setAttribute("role", "status");
  notice.textContent = `${count} ${subject}${count === 1 ? " was" : "s were"} excluded because historical data is inconsistent.`;
  return notice;
}
