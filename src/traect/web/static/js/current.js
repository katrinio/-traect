import { escapeHtml, statusLabels } from "/js/presentation.js";
import { renderCurrentTradeOff } from "/js/tradeoff.js";

export function renderCurrent(elements, domains, review, allDomains = domains) {
  if (!elements.groups) return;
  renderCurrentTradeOff(elements.tradeoff, elements.tradeoffContent, allDomains, review);
  const statesByDomainId = new Map((review?.states || []).map((item) => [item.domain_id, item]));
  const grouped = { focus: [], maintain: [], ignore: [] };

  for (const domain of domains) {
    const currentState = statesByDomainId.get(domain.id) || { mode: "ignore", status: "good" };
    grouped[currentState.mode].push({ domain, state: currentState });
  }

  const groups = [
    ["Focus", grouped.focus],
    ["Maintenance", grouped.maintain],
    ["Ignored", grouped.ignore],
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
  const status = currentState.status || "good";
  const [symbol, label] = statusLabels[status] || statusLabels.good;
  const row = document.createElement("div");
  row.className = "current-row";
  row.innerHTML = `
    <span class="domain-name">${escapeHtml(domain.name)}</span>
    <span class="status-mark" data-status="${status}" title="${escapeHtml(label)}" aria-label="${escapeHtml(label)}">
      <span class="status-symbol" aria-hidden="true">${symbol}</span>
    </span>
  `;
  return row;
}
