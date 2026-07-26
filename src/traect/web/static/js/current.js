import { attentionPresentation, conditionPresentation, escapeHtml } from "/js/presentation.js";
import { renderCurrentTradeOff } from "/js/tradeoff.js";

export function renderCurrent(elements, domains, review, allDomains = domains) {
  if (!elements.groups) return;
  renderCurrentTradeOff(elements.tradeoff, elements.tradeoffContent, allDomains, review);
  const statesByDomainId = new Map((review?.states || []).map((item) => [item.domain_id, item]));
  const grouped = { primary_focus: [], maintained: [], paused: [] };

  for (const domain of domains) {
    const currentState = statesByDomainId.get(domain.id) || { attention: "paused", condition: "stable" };
    grouped[currentState.attention].push({ domain, state: currentState });
  }

  const groups = [
    [attentionPresentation.primary_focus.group, grouped.primary_focus],
    [attentionPresentation.maintained.group, grouped.maintained],
    [attentionPresentation.paused.group, grouped.paused],
  ].filter(([, entries]) => entries.length > 0);
  elements.groups.replaceChildren(...groups.map(([title, entries]) => renderGroup(title, entries)));
}

function renderGroup(title, entries) {
  const section = document.createElement("section");
  section.className = "domain-group";
  const heading = document.createElement("h3");
  heading.className = "section-title";
  heading.textContent = title;
  const body = document.createElement("div");
  body.className = "current-rows";
  for (const entry of entries) body.appendChild(renderCurrentRow(entry.domain, entry.state));
  section.append(heading, body);
  return section;
}

function renderCurrentRow(domain, currentState) {
  const isInitialized = currentState.starting_condition !== null && currentState.starting_condition !== undefined;
  const isLegacy = !isInitialized && currentState.condition !== null && currentState.condition !== undefined;

  let conditionValue = "stable";
  if (isInitialized) {
    conditionValue = currentState.starting_condition;
  } else if (isLegacy) {
    conditionValue = currentState.condition;
  }

  const conditionPresent = conditionPresentation[conditionValue] || conditionPresentation.stable;
  const attentionValue = currentState.attention || "paused";
  const attentionPresent = attentionPresentation[attentionValue] || attentionPresentation.paused;
  const conditionLabel = isLegacy ? "Recorded condition" : "Condition at start";

  const row = document.createElement("div");
  row.className = "current-row";
  row.innerHTML = `
    <div class="current-row-content">
      <span class="domain-name">${escapeHtml(domain.name)}</span>
      <div class="current-state-row">
        <span class="state-label">${conditionLabel}</span>
        <span class="condition-mark" data-condition="${conditionValue}">
          <span class="condition-symbol" aria-hidden="true">${conditionPresent.symbol}</span>
          <span class="condition-label">${conditionPresent.label}</span>
        </span>
      </div>
      <div class="current-state-row">
        <span class="state-label">Attention this week</span>
        <span class="attention-value">${attentionPresent.symbol} ${attentionPresent.label}</span>
      </div>
    </div>
  `;
  return row;
}
