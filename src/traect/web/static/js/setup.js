import { escapeHtml } from "/js/presentation.js";

export function renderSetup(container, draft, callbacks) {
  if (!container) return;
  container.replaceChildren(...draft.map((item, index) => renderSetupDomain(item, index, callbacks)));
}

function renderSetupDomain(item, index, callbacks) {
  const row = document.createElement("section");
  row.className = "domain";
  row.innerHTML = `
    <div class="domain-grid">
      <label class="full">Domain
        <input type="text" name="setup_domain_${index}" value="${escapeHtml(item.name)}" autocomplete="off">
      </label>
      <div class="domain-actions full">
        <button class="secondary" type="button" data-up="${index}">Up</button>
        <button class="secondary" type="button" data-down="${index}">Down</button>
        <button class="ghost" type="button" data-remove="${index}">Remove</button>
      </div>
    </div>
  `;
  row.querySelector("[data-up]").addEventListener("click", () => callbacks.onMove(index, -1));
  row.querySelector("[data-down]").addEventListener("click", () => callbacks.onMove(index, 1));
  row.querySelector("[data-remove]").addEventListener("click", () => callbacks.onRemove(index));
  row.querySelector("input").addEventListener("input", (event) => {
    item.name = event.target.value;
  });
  return row;
}
