import { conditionPresentation, setStatus } from "/js/presentation.js";

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
    sections.push(renderDomainHeader(history.domain), renderLatest(history.summary.latest_record));
    if (history.summary.excluded_state_count > 0) {
      sections.push(renderIntegrityNotice(history.summary.excluded_state_count, "Condition record"));
    }
    sections.push(renderCoverage(history.summary));
    if (history.summary.recorded_state_count === 0) {
      sections.push(renderNoRecordedCondition(history.summary.excluded_state_count));
    } else {
      sections.push(renderDistribution(history.summary));
    }
    sections.push(renderSequence(history.weeks));
    sections.push(renderPausedSequences(history.paused_sequences));
    if (history.transitions.length) sections.push(renderTransitions(history.transitions));
    if (history.runs.length) sections.push(renderRuns(history.runs));
    if (history.observations.length) sections.push(renderObservations(history.observations));
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
    value.textContent = `${conditionPresentation[latest.condition].label} · Week ${latest.iso_week}, ${latest.iso_year}`;
    if (latest.lifecycle === "provisional") value.append(" · Provisional");
  } else value.textContent = "No recorded Condition in this period.";
  section.append(heading, value);
  return section;
}

function renderDistribution(summary) {
  const section = document.createElement("section");
  section.className = "condition-distribution";
  const heading = document.createElement("h4");
  heading.className = "section-title";
  heading.textContent = "Recorded Conditions";
  const list = document.createElement("dl");
  list.className = "condition-summary";
  appendMetric(list, "Recorded states", String(summary.recorded_state_count));
  for (const condition of ["stable", "at_risk", "critical"]) {
    const presentation = conditionPresentation[condition];
    appendMetric(
      list,
      presentation.label,
      `${summary.counts[condition]} · ${formatPercentage(summary.shares[condition])}`,
    );
  }
  section.append(heading, list);
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

function renderPausedSequences(sequences) {
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
        ? `${formatReviewedWeeks(sequences.current_streak.length)} · Started Week ${sequences.current_streak.started.iso_week}, ${sequences.current_streak.started.iso_year}`
        : "No active paused sequence",
    ),
    renderPausedSummary(
      "Longest paused sequence",
      `${formatReviewedWeeks(sequences.longest_streak.length)} · ${formatWeekRange(sequences.longest_streak)}`,
    ),
  );
  const list = document.createElement("ol");
  list.className = "paused-sequence-list";
  for (const streak of sequences.streaks) list.appendChild(renderPausedStreak(streak));
  section.append(summaries, list);

  if (sequences.observations.length) {
    const observations = document.createElement("ul");
    observations.className = "paused-sequence-observations";
    for (const observation of sequences.observations) {
      const item = document.createElement("li");
      item.dataset.observationCode = observation.code;
      item.textContent = observation.text;
      observations.appendChild(item);
    }
    section.appendChild(observations);
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

function renderPausedStreak(streak) {
  const item = document.createElement("li");
  item.className = "paused-sequence-item";
  const heading = document.createElement("p");
  heading.textContent = `${formatWeekRange(streak)} · ${formatReviewedWeeks(streak.length)}${streak.active ? " · Current" : ""}`;
  const weeks = document.createElement("ul");
  for (const week of streak.weeks) {
    const weekItem = document.createElement("li");
    const link = document.createElement("a");
    link.href = `#timeline-week-${week.week_id}`;
    link.setAttribute("aria-label", `Open paused sequence review for Week ${week.iso_week}, ${week.iso_year}`);
    link.textContent = `Week ${week.iso_week}, ${week.iso_year} · Paused`;
    link.addEventListener("click", () => {
      const target = document.getElementById(`timeline-week-${week.week_id}`);
      if (target instanceof HTMLDetailsElement) target.open = true;
    });
    weekItem.appendChild(link);
    weeks.appendChild(weekItem);
  }
  item.append(heading, weeks);
  return item;
}

function formatWeekRange(streak) {
  const started = `Week ${streak.started.iso_week}, ${streak.started.iso_year}`;
  const ended = `Week ${streak.ended.iso_week}, ${streak.ended.iso_year}`;
  return started === ended ? started : `${started} → ${ended}`;
}

function formatReviewedWeeks(count) {
  return `${count} consecutive reviewed ${count === 1 ? "week" : "weeks"}`;
}

function renderWeek(week) {
  const item = document.createElement("li");
  item.className = `condition-week condition-week-${week.presence}`;
  const link = document.createElement("a");
  link.href = `#timeline-week-${week.week_id}`;
  link.setAttribute("aria-label", `Open saved review for Week ${week.iso_week}, ${week.iso_year}`);
  link.textContent = `Week ${week.iso_week}, ${week.iso_year}`;
  link.addEventListener("click", () => {
    const target = document.getElementById(`timeline-week-${week.week_id}`);
    if (target instanceof HTMLDetailsElement) target.open = true;
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

function formatPercentage(share) {
  return `${Math.round(Number(share) * 100)}%`;
}
