import { bySortOrder, escapeHtml, minimumAcceptableLevelLimit } from "/js/presentation.js";

export function renderDomainManagement(elements, domains, callbacks) {
  if (!elements.active || !elements.archived) return;
  const active = domains.filter((domain) => domain.archived_at === null).sort(bySortOrder);
  const archived = domains.filter((domain) => domain.archived_at !== null).sort(bySortOrder);
  elements.active.replaceChildren(...active.map((domain) => renderActiveDomainRow(domain, callbacks)));
  elements.archived.replaceChildren(...archived.map((domain) => renderArchivedDomainRow(domain, callbacks)));
  enableDragReorder(elements.active, callbacks.onReorder);
}

function renderActiveDomainRow(domain, callbacks) {
  const details = document.createElement("details");
  details.className = "domain-accordion";
  details.dataset.id = String(domain.id);

  const summary = document.createElement("summary");
  summary.className = "domain-accordion-summary";

  const arrow = document.createElement("span");
  arrow.className = "domain-accordion-arrow";
  arrow.setAttribute("aria-hidden", "true");
  arrow.textContent = "▼";
  summary.appendChild(arrow);

  const summaryContent = document.createElement("div");
  summaryContent.className = "domain-accordion-summary-content";
  summaryContent.innerHTML = `
    <span class="drag-handle" aria-hidden="true">⋮⋮</span>
    <span class="domain-accordion-name">${escapeHtml(domain.name)}</span>
  `;
  summary.appendChild(summaryContent);

  const archiveButton = document.createElement("button");
  archiveButton.className = "ghost row-action";
  archiveButton.type = "button";
  archiveButton.setAttribute("data-archive", String(domain.id));
  archiveButton.textContent = "Archive";
  summary.appendChild(archiveButton);

  const content = document.createElement("div");
  content.className = "domain-accordion-content";
  const minimumLevelField = document.createElement("label");
  minimumLevelField.className = "minimum-level-field";
  minimumLevelField.innerHTML = `
    Minimum acceptable level
    <textarea maxlength="${minimumAcceptableLevelLimit}"
      placeholder="What is the minimum state that still feels acceptable?"></textarea>
  `;

  details.append(summary, content);
  content.appendChild(minimumLevelField);

  const minimumLevel = minimumLevelField.querySelector("textarea");
  minimumLevel.value = domain.minimum_acceptable_level || "";
  minimumLevel.addEventListener("change", () => callbacks.onMinimumLevel(domain.id, minimumLevel.value));
  archiveButton.addEventListener("click", () => callbacks.onArchive(domain.id));

  // Prevent drag handle from triggering details expand
  const dragHandle = summaryContent.querySelector(".drag-handle");
  dragHandle.addEventListener("pointerdown", (e) => e.stopPropagation(), true);

  return details;
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
