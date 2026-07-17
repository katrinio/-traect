import { bySortOrder, escapeHtml } from "/js/presentation.js";

export function renderDomainManagement(elements, domains, callbacks) {
  if (!elements.active || !elements.archived) return;
  const active = domains.filter((domain) => domain.archived_at === null).sort(bySortOrder);
  const archived = domains.filter((domain) => domain.archived_at !== null).sort(bySortOrder);
  elements.active.replaceChildren(...active.map((domain) => renderActiveDomainRow(domain, callbacks)));
  elements.archived.replaceChildren(...archived.map((domain) => renderArchivedDomainRow(domain, callbacks)));
  enableDragReorder(elements.active, callbacks.onReorder);
}

function renderActiveDomainRow(domain, callbacks) {
  const row = document.createElement("div");
  row.className = "domain-row";
  row.dataset.id = String(domain.id);
  row.innerHTML = `
    <span class="drag-handle" aria-hidden="true">⋮⋮</span>
    <input class="inline-input" type="text" value="${escapeHtml(domain.name)}" autocomplete="off" aria-label="Domain name">
    <button class="ghost row-action" type="button" data-archive="${domain.id}">Archive</button>
  `;
  const input = row.querySelector("input");
  input.addEventListener("change", () => callbacks.onRename(domain.id, input.value));
  row.querySelector("[data-archive]").addEventListener("click", () => callbacks.onArchive(domain.id));
  return row;
}

function renderArchivedDomainRow(domain, callbacks) {
  const row = document.createElement("div");
  row.className = "domain-row";
  row.innerHTML = `
    <span class="domain-name-static">${escapeHtml(domain.name)}</span>
    <button class="ghost row-action" type="button" data-restore="${domain.id}">Restore</button>
  `;
  row.querySelector("[data-restore]").addEventListener("click", () => callbacks.onRestore(domain.id));
  return row;
}

function enableDragReorder(container, onReorder) {
  const originalOrder = [...container.querySelectorAll(".domain-row")].map((row) => row.dataset.id);
  container.querySelectorAll(".drag-handle").forEach((handle) => {
    handle.addEventListener("pointerdown", (event) => {
      const draggingRow = handle.closest(".domain-row");
      if (!draggingRow) return;
      event.preventDefault();
      draggingRow.classList.add("dragging");
      handle.setPointerCapture(event.pointerId);

      const onMove = (moveEvent) => {
        for (const sibling of container.querySelectorAll(".domain-row")) {
          if (sibling === draggingRow) continue;
          const rect = sibling.getBoundingClientRect();
          if (moveEvent.clientY < rect.top || moveEvent.clientY > rect.bottom) continue;
          const before = moveEvent.clientY < rect.top + rect.height / 2;
          container.insertBefore(draggingRow, before ? sibling : sibling.nextSibling);
          break;
        }
      };

      const onUp = () => {
        draggingRow.classList.remove("dragging");
        handle.releasePointerCapture(event.pointerId);
        document.removeEventListener("pointermove", onMove);
        document.removeEventListener("pointerup", onUp);
        const newOrder = [...container.querySelectorAll(".domain-row")].map((row) => row.dataset.id);
        if (newOrder.join() !== originalOrder.join()) onReorder(newOrder.map(Number));
      };
      document.addEventListener("pointermove", onMove);
      document.addEventListener("pointerup", onUp);
    });
  });
}
