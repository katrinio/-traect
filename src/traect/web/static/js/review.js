import {
  attentionOptions,
  commentLimit,
  conditionOptions,
  conditionPresentation,
  escapeHtml,
  selectedNumber,
  summaryOptions,
} from "/js/presentation.js";

export function renderReview(container, domains, review) {
  if (!container) return;
  const statesByDomainId = new Map((review?.states || []).map((item) => [item.domain_id, item]));
  container.replaceChildren(
    ...domains.map((domain) => {
      const state = statesByDomainId.get(domain.id);
      const currentState = state || { attention: "paused", starting_condition: null, condition: null, comment: null };
      return renderEditRow(domain, currentState);
    })
  );
  const sacrificedSelect = document.querySelector("select[name='sacrificed_domain_id']");
  sacrificedSelect.innerHTML = summaryOptions(domains);

  const focusedDomains = domains.filter(
    (domain) => statesByDomainId.get(domain.id)?.attention === "primary_focus",
  );
  const primaryFocusId = focusedDomains.length === 1 ? focusedDomains[0].id : null;
  sacrificedSelect.value = review?.sacrificed_domain_id ? String(review.sacrificed_domain_id) : "";
  document.querySelector("input[name='sacrifice_reason']").value = review?.sacrifice_reason || "";
  updateTradeOffControls(primaryFocusId);

  sacrificedSelect.onchange = () => {
    if (sacrificedSelect.value === String(selectedPrimaryFocusId())) sacrificedSelect.value = "";
    synchronizeTradeOffReason();
  };
  document.querySelector("textarea[name='notes']").value = review?.notes || "";
}

export function collectReviewPayload(domains) {
  return {
    sacrificed_domain_id: selectedNumber("sacrificed_domain_id"),
    sacrifice_reason: document.querySelector("input[name='sacrifice_reason']").value.trim() || null,
    notes: document.querySelector("textarea[name='notes']").value.trim() || null,
    states: domains.map((domain) => {
      const startingConditionSelect = document.querySelector(`select[name="starting_condition_${domain.id}"]`);
      return {
        domain_id: domain.id,
        attention: document.querySelector(`select[name="attention_${domain.id}"]`).value,
        starting_condition: startingConditionSelect ? startingConditionSelect.value : null,
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
    <span class="minimum-level-context" id="${minimumContextId}">
      <span class="minimum-level-label">Minimum acceptable level</span>
      <span class="minimum-level-value">${escapeHtml(minimumAcceptableLevel)}</span>
    </span>
  ` : "";
  const isInitialized = currentState?.starting_condition !== null && currentState?.starting_condition !== undefined;
  const isLegacy = !isInitialized && currentState?.condition !== null && currentState?.condition !== undefined;

  let conditionHtml = "";
  let conditionLabel = isLegacy ? "Recorded condition" : "Condition at start";

  if (isInitialized) {
    const condition = currentState.starting_condition || "stable";
    const presentation = conditionPresentation[condition] || conditionPresentation.stable;
    conditionHtml = `
      <span class="condition-mark" data-condition="${condition}">
        <span class="condition-symbol" aria-hidden="true">${presentation.symbol}</span>
        <span class="condition-label">${presentation.label}</span>
      </span>
    `;
  } else if (isLegacy) {
    const condition = currentState.condition || "stable";
    const presentation = conditionPresentation[condition] || conditionPresentation.stable;
    conditionHtml = `
      <span class="condition-mark" data-condition="${condition}">
        <span class="condition-symbol" aria-hidden="true">${presentation.symbol}</span>
        <span class="condition-label">${presentation.label}</span>
      </span>
    `;
  } else {
    conditionHtml = `
      <select name="starting_condition_${domain.id}" ${minimumAcceptableLevel ? `aria-describedby="${minimumContextId}"` : ""}>
        ${conditionOptions().map(([value, label]) => `<option value="${value}">${label}</option>`).join("")}
      </select>
    `;
  }

  const row = document.createElement("section");
  row.className = "domain";
  row.innerHTML = `
    <div class="domain-head">
      <div class="domain-name">${escapeHtml(domain.name)}</div>
    </div>
    <div class="domain-grid">
      <span class="grid-label">${conditionLabel}</span>
      <div class="grid-value">${minimumContext}${conditionHtml}</div>
      <span class="grid-label">Attention this week</span>
      <div class="grid-value">
        <select name="attention_${domain.id}">
          ${attentionOptions().map(([value, label]) => `<option value="${value}">${label}</option>`).join("")}
        </select>
      </div>
      <details class="domain-context full" ${comment ? "open" : ""}>
        <summary>${comment ? "Edit context" : "Add context"}</summary>
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

  attentionSelect.value = currentState?.attention || "paused";
  if (startingConditionSelect) {
    startingConditionSelect.value = currentState?.starting_condition || "stable";
  }
  commentInput.value = comment;
  updateCommentContext(commentInput, commentSummary, characterCount);

  attentionSelect.addEventListener("change", () => {
    if (attentionSelect.value === "primary_focus") {
      enforceSinglePrimaryFocus(domain.id);
    } else {
      updateTradeOffControls(selectedPrimaryFocusId());
    }
  });
  commentInput.addEventListener("input", () => updateCommentContext(commentInput, commentSummary, characterCount));
  return row;
}

function enforceSinglePrimaryFocus(primaryFocusId) {
  document.querySelectorAll("select[name^='attention_']").forEach((select) => {
    const domainId = Number(select.name.replace("attention_", ""));
    if (domainId === primaryFocusId) select.value = "primary_focus";
    else if (select.value === "primary_focus") select.value = "maintained";
  });
  updateTradeOffControls(primaryFocusId);
}

function selectedPrimaryFocusId() {
  const selected = [...document.querySelectorAll("select[name^='attention_']")]
    .find((select) => select.value === "primary_focus");
  return selected ? Number(selected.name.replace("attention_", "")) : null;
}

function updateTradeOffControls(primaryFocusId) {
  const sacrificedSelect = document.querySelector("select[name='sacrificed_domain_id']");
  sacrificedSelect.disabled = primaryFocusId === null;
  sacrificedSelect.querySelector("option[value='']").textContent = primaryFocusId === null
    ? "Choose a main focus first"
    : "None this week";
  sacrificedSelect.querySelectorAll("option").forEach((option) => {
    option.disabled = option.value === String(primaryFocusId);
  });
  if (primaryFocusId === null || sacrificedSelect.value === String(primaryFocusId)) sacrificedSelect.value = "";
  synchronizeTradeOffReason();
}

function synchronizeTradeOffReason() {
  const sacrificedSelect = document.querySelector("select[name='sacrificed_domain_id']");
  const reasonInput = document.querySelector("input[name='sacrifice_reason']");
  const hasSacrifice = Boolean(sacrificedSelect.value);
  reasonInput.disabled = !hasSacrifice;
  reasonInput.placeholder = hasSacrifice ? "What caused this trade-off?" : "Choose what gave way first";
  if (!hasSacrifice) reasonInput.value = "";
}

function updateCommentContext(input, summary, counter) {
  const length = input.value.length;
  summary.textContent = length > 0 ? "Edit context" : "Add context";
  counter.textContent = `${length} / ${commentLimit}`;
}
