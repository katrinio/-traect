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
  const condition = currentState.condition || "stable";
  const presentation = conditionPresentation[condition] || conditionPresentation.stable;
  const row = document.createElement("div");
  row.className = "current-row";
  row.innerHTML = `
    <span class="domain-name">${escapeHtml(domain.name)}</span>
    <span class="condition-mark" data-condition="${condition}" title="${escapeHtml(presentation.label)}" aria-label="${escapeHtml(presentation.label)}">
      <span class="condition-symbol" aria-hidden="true">${presentation.symbol}</span>
    </span>
  `;
  return row;
}
