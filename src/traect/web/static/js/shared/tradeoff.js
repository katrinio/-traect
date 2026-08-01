export function renderCurrentTradeOff(section, content, domains, review) {
  if (!section || !content) return;
  if (!review) {
    section.classList.add("hidden");
    content.replaceChildren();
    return;
  }

  const domainsById = new Map(domains.map((domain) => [domain.id, domain]));
  section.classList.remove("hidden");
  content.replaceChildren(createTradeOffSummary(review, {
    focusName: review.main_focus?.name || null,
    sacrificedName: review.sacrificed_domain_name
      || (review.sacrificed_domain_id ? domainName(domainsById, review.sacrificed_domain_id) : null),
  }));
}

export function createTradeOffSummary(review, names) {
  if (!review.main_focus && !names.focusName) {
    const empty = document.createElement("p");
    empty.className = "tradeoff-empty";
    empty.textContent = "No primary focus recorded.";
    return empty;
  }

  const list = document.createElement("dl");
  list.className = "tradeoff-list";
  list.appendChild(renderTradeOffRow("focus", "Main focus", names.focusName || "Unknown domain"));
  list.appendChild(renderTradeOffRow("sacrifice", "What gave way", names.sacrificedName || "None recorded"));
  if (typeof review.sacrifice_reason === "string" && review.sacrifice_reason) {
    list.appendChild(renderTradeOffRow("reason", "Why", review.sacrifice_reason));
  }
  return list;
}

function renderTradeOffRow(field, label, value) {
  const row = document.createElement("div");
  row.className = "tradeoff-row";
  row.dataset.tradeoffField = field;
  const term = document.createElement("dt");
  term.textContent = label;
  const description = document.createElement("dd");
  description.textContent = value;
  row.append(term, description);
  return row;
}

function domainName(domainsById, domainId) {
  return domainsById.get(domainId)?.name || "Unknown domain";
}
