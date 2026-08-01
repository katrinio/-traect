import {
  attentionOptions,
  commentLimit,
  conditionOptions,
  escapeHtml,
} from "/js/shared/dom.js";

let activeMinimumLevelPopover = null;
let minimumLevelDocumentListenersBound = false;
const canHoverMinimumLevel = window.matchMedia("(hover: hover) and (pointer: fine)").matches;
let preservedTradeoff = { sacrificedDomainId: null, sacrificeReason: null };

export function renderReview(container, domains, review) {
  if (!container) return;
  closeMinimumLevelPopover();
  preservedTradeoff = {
    sacrificedDomainId: review?.sacrificed_domain_id ?? null,
    sacrificeReason: review?.sacrifice_reason ?? null,
  };
  const statesByDomainId = new Map((review?.states || []).map((item) => [item.domain_id, item]));
  container.replaceChildren(...domains.map((domain) => renderEditRow(domain, statesByDomainId.get(domain.id))));
  document.querySelector("textarea[name='notes']").value = review?.notes || "";
}

export function collectReviewPayload(domains) {
  return {
    sacrificed_domain_id: preservedTradeoff.sacrificedDomainId,
    sacrifice_reason: preservedTradeoff.sacrificeReason,
    notes: document.querySelector("textarea[name='notes']").value.trim() || null,
    states: domains.map((domain) => {
      const startingConditionSelect = document.querySelector(`select[name="starting_condition_${domain.id}"]`);
      const conditionValue = startingConditionSelect ? startingConditionSelect.value : null;
      return {
        domain_id: domain.id,
        attention: document.querySelector(`select[name="attention_${domain.id}"]`).value,
        condition: conditionValue,
        comment: document.querySelector(`textarea[name="comment_${domain.id}"]`).value.trim() || null,
      };
    }),
  };
}

function renderEditRow(domain, currentState) {
  const comment = currentState?.comment || "";
  const minimumAcceptableLevel = domain.minimum_acceptable_level;
  const minimumContextId = `minimum-level-context-${domain.id}`;
  const minimumContext = minimumAcceptableLevel ? `
    <span class="minimum-level-popover-wrap">
      <button class="minimum-level-trigger" type="button" aria-label="Show minimum acceptable level for ${escapeHtml(domain.name)}"
        aria-expanded="false" aria-controls="${minimumContextId}">
        <svg class="minimum-level-icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <path class="minimum-level-icon-pole" d="M4.5 2.5v11" />
          <path class="minimum-level-icon-flag" d="M5 3h7l-1.5 2L12 7H5z" />
        </svg>
      </button>
      <span class="minimum-level-popover" id="${minimumContextId}" role="tooltip" hidden>
        <span class="minimum-level-title">Minimum acceptable level</span>
        <span class="minimum-level-value">${escapeHtml(minimumAcceptableLevel)}</span>
      </span>
    </span>
  ` : "";
  const isInitialized = currentState?.starting_condition !== null && currentState?.starting_condition !== undefined;
  const row = document.createElement("section");
  row.className = "domain";
  row.innerHTML = `
    <div class="domain-head">
      <div class="domain-name">${escapeHtml(domain.name)}${minimumContext}</div>
    </div>
    <div class="domain-grid">
      <label>Attention
        <select name="attention_${domain.id}">
          ${attentionOptions().map(([value, label]) => `<option value="${value}">${label}</option>`).join("")}
        </select>
      </label>
      <label>Current state
        <select name="starting_condition_${domain.id}" ${isInitialized ? "disabled" : ""}>
          ${conditionOptions().map(([value, label]) => `<option value="${value}">${label}</option>`).join("")}
        </select>
      </label>
      <details class="domain-context full" ${comment ? "open" : ""}>
        <summary>${comment ? "Edit context" : "Notes"}</summary>
        <label class="context-field">Context
          <textarea name="comment_${domain.id}" maxlength="${commentLimit}"
            placeholder="What explains this attention choice or condition?"></textarea>
          <span class="character-count" aria-live="polite"></span>
        </label>
      </details>
    </div>
  `;
  const attentionSelect = row.querySelector(`select[name="attention_${domain.id}"]`);
  const startingConditionSelect = row.querySelector(`select[name="starting_condition_${domain.id}"]`);
  const commentInput = row.querySelector(`textarea[name="comment_${domain.id}"]`);
  const commentSummary = row.querySelector(".domain-context summary");
  const characterCount = row.querySelector(".character-count");
  const minimumTrigger = row.querySelector(".minimum-level-trigger");

  attentionSelect.value = currentState?.attention || "paused";
  startingConditionSelect.value = currentState?.starting_condition || "stable";
  commentInput.value = comment;
  updateCommentContext(commentInput, commentSummary, characterCount);
  if (minimumTrigger) bindMinimumLevelPopover(row, minimumTrigger);

  attentionSelect.addEventListener("change", () => {
    if (attentionSelect.value === "primary_focus") {
      enforceSinglePrimaryFocus(domain.id);
    }
  });
  commentInput.addEventListener("input", () => updateCommentContext(commentInput, commentSummary, characterCount));
  return row;
}

function bindMinimumLevelPopover(row, trigger) {
  const popover = row.querySelector(`#${trigger.getAttribute("aria-controls")}`);
  if (!popover) return;
  const popoverWrap = trigger.closest(".minimum-level-popover-wrap");
  if (!popoverWrap) return;
  bindMinimumLevelDocumentListeners();

  trigger.addEventListener("click", () => {
    const isPinned = activeMinimumLevelPopover?.trigger === trigger && activeMinimumLevelPopover.pinned;
    if (isPinned) closeMinimumLevelPopover({ restoreFocus: false });
    else openMinimumLevelPopover(popoverWrap, trigger, popover, { pinned: true });
  });

  if (canHoverMinimumLevel) {
    popoverWrap.addEventListener("mouseenter", () => {
      if (activeMinimumLevelPopover?.trigger !== trigger || !activeMinimumLevelPopover.pinned) {
        openMinimumLevelPopover(popoverWrap, trigger, popover, { pinned: false });
      }
    });
    popoverWrap.addEventListener("mouseleave", () => {
      if (activeMinimumLevelPopover?.trigger === trigger && !activeMinimumLevelPopover.pinned) {
        closeMinimumLevelPopover({ restoreFocus: false });
      }
    });
  }

  trigger.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeMinimumLevelPopover({ restoreFocus: true });
    }
  });
}

function bindMinimumLevelDocumentListeners() {
  if (minimumLevelDocumentListenersBound) return;
  minimumLevelDocumentListenersBound = true;
  document.addEventListener("click", (event) => {
    if (!activeMinimumLevelPopover) return;
    if (!activeMinimumLevelPopover.wrap.contains(event.target)) {
      closeMinimumLevelPopover({ restoreFocus: false });
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeMinimumLevelPopover({ restoreFocus: true });
  });
}

function openMinimumLevelPopover(wrap, trigger, popover, { pinned }) {
  if (activeMinimumLevelPopover?.trigger !== trigger) closeMinimumLevelPopover({ restoreFocus: false });
  activeMinimumLevelPopover = { wrap, trigger, popover, pinned };
  popover.hidden = false;
  trigger.setAttribute("aria-expanded", "true");
  trigger.classList.toggle("is-open", pinned);
}

function closeMinimumLevelPopover({ restoreFocus = false } = {}) {
  if (!activeMinimumLevelPopover) return;
  const { trigger, popover } = activeMinimumLevelPopover;
  popover.hidden = true;
  trigger.setAttribute("aria-expanded", "false");
  trigger.classList.remove("is-open");
  activeMinimumLevelPopover = null;
  if (restoreFocus) trigger.focus();
}

function enforceSinglePrimaryFocus(primaryFocusId) {
  document.querySelectorAll("select[name^='attention_']").forEach((select) => {
    const domainId = Number(select.name.replace("attention_", ""));
    if (domainId === primaryFocusId) select.value = "primary_focus";
    else if (select.value === "primary_focus") select.value = "maintained";
  });
}

function updateCommentContext(input, summary, counter) {
  const length = input.value.length;
  summary.textContent = length > 0 ? "Edit context" : "Notes";
  counter.textContent = `${length} / ${commentLimit}`;
}
