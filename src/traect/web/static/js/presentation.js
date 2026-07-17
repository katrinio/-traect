export const commentLimit = 300;

export const attentionPresentation = {
  primary_focus: { symbol: "▲", label: "Primary focus", group: "Primary focus" },
  maintained: { symbol: "✓", label: "Maintained", group: "Maintained" },
  paused: { symbol: "○", label: "Paused", group: "Paused" },
};

export const conditionPresentation = {
  stable: { symbol: "✓", label: "Stable" },
  at_risk: { symbol: "⚠", label: "At risk" },
  critical: { symbol: "!", label: "Critical" },
};

export function activeDomains(domains) {
  return domains.filter((domain) => domain.archived_at === null).sort(bySortOrder);
}

export function summaryOptions(domains) {
  const options = ['<option value="">None this week</option>'];
  for (const domain of domains) {
    options.push(`<option value="${domain.id}">${escapeHtml(domain.name)}</option>`);
  }
  return options.join("");
}

export function attentionOptions() {
  return Object.entries(attentionPresentation).map(([value, item]) => [value, `${item.symbol} ${item.label}`]);
}

export function conditionOptions() {
  return Object.entries(conditionPresentation).map(([value, item]) => [value, `${item.symbol} ${item.label}`]);
}

export function selectedNumber(name) {
  const value = document.querySelector(`select[name='${name}']`).value;
  return value ? Number(value) : null;
}

export function hasDuplicateNames(names) {
  const normalized = names.map((name) => name.toLowerCase());
  return new Set(normalized).size !== normalized.length;
}

export async function withStatus(element, action) {
  try {
    await action();
    setStatus(element, "");
  } catch (error) {
    setStatus(element, error.message, true);
  }
}

export function setStatus(element, message, isError = false) {
  if (!element) return;
  element.textContent = message;
  element.className = isError ? "status error" : "status";
}

export function bySortOrder(left, right) {
  return left.sort_order - right.sort_order || left.id - right.id;
}

export function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);
}
