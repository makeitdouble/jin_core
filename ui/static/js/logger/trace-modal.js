let traceModal;
let traceModalContent;
let traceModalReason;
let traceModalTitle;
let traceModalCopyButton;
let traceModalContextCopyText = "";
let traceModalL1StreamId = null;
let traceModalL1StreamStatus = null;
let traceModalL1StreamReasoning = null;
let traceModalL1StreamAnswer = null;
let traceModalL1StreamFrame = null;

const CONTEXT_DELAYED_MEMORY_STORE_CHANGED_EVENT =
  "jin:delayed-memory-store-changed";
const CONTEXT_FILES_STORE_CHANGED_EVENT =
  "jin:files-store-changed";
const CONTEXT_ATTACHMENT_HOVER_BOUND_DATASET_KEY =
  "jinContextAttachmentHoverBound";

function clearContextAttachedFileHoverPreview() {
  if (traceModalContent) {
    traceModalContent
      .querySelectorAll(
        '[data-jin-context-attachment-hover-bound="1"]'
      )
      .forEach((row) => {
        row.dispatchEvent(
          new Event("mouseleave")
        );
      });
  }

  if (
      typeof window.hideJinAttachmentHoverPreview === "function"
  ) {
    window.hideJinAttachmentHoverPreview();
  }
}

function ensureTraceModal() {
  if (traceModal) {
    return;
  }

  traceModal =
    document.createElement("div");

  traceModal.className =
    "fixed inset-0 z-50 hidden items-center justify-center bg-black/70 p-4";

  const panel =
    document.createElement("div");

  panel.className =
    "delayed-memory-modal-panel w-full max-w-5xl max-h-[86vh] rounded border border-zinc-700 bg-zinc-950 shadow-2xl flex flex-col";

  const header =
    document.createElement("div");

  header.className =
    "h-11 shrink-0 border-b border-zinc-800 px-4 flex items-center justify-between";

  traceModalTitle =
    document.createElement("div");

  traceModalTitle.className =
    "text-xs uppercase tracking-widest text-zinc-300";

  traceModalTitle.textContent =
    "Trace";

  const headerActions =
    document.createElement("div");

  headerActions.className =
    "delayed-memory-modal-actions";

  traceModalCopyButton =
    document.createElement("button");

  traceModalCopyButton.type =
    "button";

  traceModalCopyButton.className =
    "delayed-memory-modal-icon-button jin-context-copy-button hidden";

  traceModalCopyButton.setAttribute(
    "aria-label",
    "Copy context"
  );

  traceModalCopyButton.title =
    "Copy raw context";

  traceModalCopyButton.innerHTML =
    '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="11" height="12" rx="1.5"></rect><path d="M15 8V5.5A1.5 1.5 0 0 0 13.5 4h-9A1.5 1.5 0 0 0 3 5.5v10A1.5 1.5 0 0 0 4.5 17H8"></path></svg>';

  const closeButton =
    document.createElement("button");

  closeButton.type =
    "button";

  closeButton.className =
    "delayed-memory-modal-icon-button delayed-memory-modal-close";

  closeButton.setAttribute(
    "aria-label",
    "Close"
  );

  closeButton.textContent =
    "\u00d7";

  traceModalReason =
    document.createElement("div");

  traceModalReason.className =
    "hidden border-b border-zinc-800 px-4 py-3 text-[12px] leading-relaxed text-red-200";

  traceModalReason.style.overflowWrap =
    "anywhere";

  traceModalContent =
    document.createElement("div");

  traceModalContent.className =
    "delayed-memory-modal-content min-h-0 flex-1 overflow-auto p-4 text-[12px] leading-relaxed text-zinc-200";

  traceModalContent.style.overflowWrap =
    "anywhere";

  header.appendChild(
    traceModalTitle
  );

  headerActions.appendChild(
    traceModalCopyButton
  );

  headerActions.appendChild(
    closeButton
  );

  header.appendChild(
    headerActions
  );

  panel.appendChild(
    header
  );

  panel.appendChild(
    traceModalReason
  );

  panel.appendChild(
    traceModalContent
  );

  traceModal.appendChild(
    panel
  );

  document.body.appendChild(
    traceModal
  );

  function closeTraceModal() {
    setContextDelayedMemoryHover(
      "",
      false
    );
    clearContextAttachedFileHoverPreview();

    traceModal.classList.add(
      "hidden"
    );

    traceModal.classList.remove(
      "flex"
    );

    traceModalL1StreamId =
      null;

    traceModalL1StreamStatus =
      null;

    traceModalL1StreamReasoning =
      null;

    traceModalL1StreamAnswer =
      null;

    if (traceModalL1StreamFrame !== null) {
      cancelAnimationFrame(
        traceModalL1StreamFrame
      );

      traceModalL1StreamFrame =
        null;
    }
  }

  async function copyTraceModalContext() {
    const text = String(
      traceModalContextCopyText || ""
    );

    if (!text) {
      return;
    }

    let copied = false;

    if (
        navigator.clipboard
        && typeof navigator.clipboard.writeText === "function"
    ) {
      try {
        await navigator.clipboard.writeText(
          text
        );
        copied = true;
      } catch (_) {
        copied = false;
      }
    }

    if (!copied) {
      const textarea =
        document.createElement("textarea");

      textarea.value = text;
      textarea.setAttribute(
        "readonly",
        ""
      );
      textarea.style.position =
        "fixed";
      textarea.style.opacity =
        "0";
      textarea.style.pointerEvents =
        "none";

      document.body.appendChild(
        textarea
      );
      textarea.select();

      try {
        copied = document.execCommand(
          "copy"
        );
      } catch (_) {
        copied = false;
      }

      textarea.remove();
    }

    if (!copied) {
      return;
    }

    traceModalCopyButton.classList.add(
      "is-copied"
    );
    traceModalCopyButton.setAttribute(
      "aria-label",
      "Context copied"
    );
    traceModalCopyButton.title =
      "Copied";

    window.setTimeout(
      function () {
        if (!traceModalCopyButton) {
          return;
        }

        traceModalCopyButton.classList.remove(
          "is-copied"
        );
        traceModalCopyButton.setAttribute(
          "aria-label",
          "Copy context"
        );
        traceModalCopyButton.title =
          "Copy raw context";
      },
      900
    );
  }

  traceModalCopyButton.addEventListener(
    "click",
    copyTraceModalContext
  );

  closeButton.addEventListener(
    "click",
    closeTraceModal
  );

  traceModal.addEventListener(
    "click",
    function (event) {
      if (event.target === traceModal) {
        closeTraceModal();
      }
    }
  );

  document.addEventListener(
    "keydown",
    function (event) {
      if (event.key === "Escape") {
        const delayedMemoryReportModal =
          document.querySelector(
            ".delayed-memory-report-modal.flex:not(.hidden)"
          );

        if (delayedMemoryReportModal) {
          return;
        }

        closeTraceModal();
      }
    }
  );

  window.addEventListener(
    CONTEXT_DELAYED_MEMORY_STORE_CHANGED_EVENT,
    function (event) {
      const detail = event && event.detail || {};

      syncContextDelayedMemoryRows(
        detail.reportId || ""
      );
    }
  );

  window.addEventListener(
    CONTEXT_FILES_STORE_CHANGED_EVENT,
    function () {
      syncContextAttachedFileRows();
    }
  );
}


function appendTraceSection(
  parent,
  title,
  content,
) {
  const section =
    document.createElement("section");

  section.className =
    "mb-4 rounded border border-zinc-800 bg-black/20";

  const heading =
    document.createElement("div");

  heading.className =
    "border-b border-zinc-800 px-3 py-2 text-[10px] uppercase tracking-widest text-zinc-400";

  heading.textContent =
    title;

  const body =
    document.createElement("pre");

  body.className =
    "max-h-[34vh] overflow-auto whitespace-pre-wrap p-3 text-[12px] leading-relaxed text-zinc-200";

  body.style.overflowWrap =
    "anywhere";

  body.textContent =
    String(content || "").trim()
    || "<empty>";

  section.appendChild(
    heading
  );

  section.appendChild(
    body
  );

  parent.appendChild(
    section
  );
}

function normalizeTraceModalDisplayText(value) {
  if (value === null || typeof value === "undefined") {
    return "";
  }

  if (typeof value === "string") {
    return value.trim();
  }

  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }

  if (Array.isArray(value)) {
    return value
      .map((item) => normalizeTraceModalDisplayText(item))
      .filter(Boolean)
      .join(", ");
  }

  if (typeof value === "object") {
    try {
      return JSON.stringify(
        value,
        null,
        2
      );
    } catch (_error) {
      return String(value);
    }
  }

  return String(value);
}

function appendTraceModalField(
  parent,
  label,
  value,
) {
  const normalizedValue =
    normalizeTraceModalDisplayText(value);

  if (!normalizedValue) {
    return;
  }

  const row =
    document.createElement("div");

  row.className =
    "delayed-memory-modal-field";

  const key =
    document.createElement("div");

  key.className =
    "delayed-memory-modal-label";

  key.textContent =
    label;

  const text =
    document.createElement("div");

  text.className =
    "delayed-memory-modal-value";

  text.textContent =
    normalizedValue;

  row.appendChild(
    key
  );

  row.appendChild(
    text
  );

  parent.appendChild(
    row
  );
}

function appendTraceModalBody(
  parent,
  title,
  content,
) {
  const normalizedBody =
    normalizeTraceModalDisplayText(content);

  if (!normalizedBody) {
    return;
  }

  const section =
    document.createElement("section");

  section.className =
    "delayed-memory-modal-section";

  const heading =
    document.createElement("div");

  heading.className =
    "delayed-memory-modal-section-title";

  heading.textContent =
    title;

  const pre =
    document.createElement("pre");

  pre.className =
    "delayed-memory-modal-body";

  pre.textContent =
    normalizedBody;

  section.appendChild(
    heading
  );

  section.appendChild(
    pre
  );

  parent.appendChild(
    section
  );
}

function appendTraceModalCard(
  parent,
  titleText,
  renderContent,
) {
  const card =
    document.createElement("div");

  card.className =
    "jin-context-card jin-context-card-plain delayed-memory-modal-card";

  const header =
    document.createElement("div");

  header.className =
    "jin-context-card-header delayed-memory-modal-card-header";
  header.title =
    "Click to collapse / expand";
  header.tabIndex = 0;
  header.setAttribute(
    "role",
    "button"
  );
  header.setAttribute(
    "aria-expanded",
    "true"
  );

  const heading =
    document.createElement("div");

  heading.className =
    "jin-context-card-heading";

  const title =
    document.createElement("div");

  title.className =
    "jin-context-card-title delayed-memory-modal-card-title";
  title.textContent =
    `[ ${String(titleText || "").trim()} ]`;

  heading.appendChild(title);
  header.appendChild(heading);

  const toggle = () => {
    const collapsed =
      !card.classList.contains(
        "is-collapsed"
      );

    card.classList.toggle(
      "is-collapsed",
      collapsed
    );
    header.setAttribute(
      "aria-expanded",
      collapsed ? "false" : "true"
    );
  };

  header.addEventListener(
    "click",
    toggle
  );
  header.addEventListener(
    "keydown",
    (event) => {
      if (
        event.target !== header
        || !["Enter", " "].includes(event.key)
      ) {
        return;
      }

      event.preventDefault();
      toggle();
    }
  );

  const body =
    document.createElement("div");

  body.className =
    "jin-context-card-body delayed-memory-modal-card-body";

  if (typeof renderContent === "function") {
    renderContent(body);
  }

  card.append(header, body);
  parent.appendChild(card);

  return card;
}

function prettifyTraceFieldName(value) {
  return String(value || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, function (letter) {
      return letter.toUpperCase();
    });
}

function formatStructuredTraceValue(value) {
  if (value === null || typeof value === "undefined") {
    return "<empty>";
  }

  if (Array.isArray(value) || typeof value === "object") {
    try {
      return JSON.stringify(
        value,
        null,
        2
      );
    } catch (_error) {
      return String(value);
    }
  }

  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }

  const text = String(value);
  return text || "<empty>";
}

function appendStructuredTraceFields(
  parent,
  data,
  orderedKeys = [],
) {
  const source =
    data && typeof data === "object" && !Array.isArray(data)
      ? data
      : {};

  const fields =
    document.createElement("section");

  fields.className =
    "delayed-memory-modal-fields";

  const keys = [];
  const seen = new Set();

  orderedKeys.concat(Object.keys(source)).forEach((key) => {
    if (seen.has(key) || !Object.prototype.hasOwnProperty.call(source, key)) {
      return;
    }
    seen.add(key);
    keys.push(key);
  });

  keys.forEach((key) => {
    const row =
      document.createElement("div");

    row.className =
      "delayed-memory-modal-field";

    const label =
      document.createElement("div");

    label.className =
      "delayed-memory-modal-label";

    label.textContent =
      prettifyTraceFieldName(key);

    const value =
      document.createElement("div");

    value.className =
      "delayed-memory-modal-value";

    value.textContent =
      formatStructuredTraceValue(source[key]);

    row.appendChild(label);
    row.appendChild(value);
    fields.appendChild(row);
  });

  parent.appendChild(fields);
}

function renderL4FactTrace(parsed) {
  const fact =
    parsed && parsed.fact && typeof parsed.fact === "object"
      ? parsed.fact
      : {};

  appendStructuredTraceFields(
    traceModalContent,
    fact,
    [
      "id",
      "key",
      "value",
      "category",
      "mention_count",
      "created_at",
      "updated_at",
      "source_session_ids",
      "source_runtime_snapshot_ids",
      "source_keys",
      "source_fact_ids",
    ]
  );
}

function appendL4ResponseGroup(
  title,
  value,
) {
  const section =
    document.createElement("section");

  section.className =
    "delayed-memory-modal-section";

  const heading =
    document.createElement("div");

  heading.className =
    "delayed-memory-modal-section-title";

  heading.textContent =
    title;

  section.appendChild(heading);
  traceModalContent.appendChild(section);

  if (value && typeof value === "object" && !Array.isArray(value)) {
    appendStructuredTraceFields(
      section,
      value
    );
    return;
  }

  appendTraceModalBody(
    section,
    "Value",
    value
  );
}

function renderL4SummarizerResponseTrace(parsed) {
  if (parsed.no_changes) {
    const empty =
      document.createElement("div");

    empty.className =
      "l4-trace-no-changes";

    empty.textContent =
      "No changes";

    traceModalContent.appendChild(empty);
    return;
  }

  const payload = parsed.payload;
  const phase = String(parsed.phase || "").toLowerCase();

  if (phase === "extraction" && payload && Array.isArray(payload.facts)) {
    payload.facts.forEach((fact, index) => {
      appendL4ResponseGroup(
        `Fact ${index + 1}`,
        fact
      );
    });
    return;
  }

  if (phase === "merge" && payload && Array.isArray(payload.operations)) {
    payload.operations.forEach((operation, index) => {
      const action =
        operation && operation.action
          ? ` · ${String(operation.action).toUpperCase()}`
          : "";

      appendL4ResponseGroup(
        `Operation ${index + 1}${action}`,
        operation
      );
    });
    return;
  }

  if (payload && typeof payload === "object" && !Array.isArray(payload)) {
    appendStructuredTraceFields(
      traceModalContent,
      payload
    );
    return;
  }

  appendTraceModalBody(
    traceModalContent,
    "Response",
    parsed.raw || payload || ""
  );
}

function renderL4SkipTrace(parsed) {
  if (
    String(parsed.reason || "").toLowerCase()
      === "runtime_context_budget_exhausted"
  ) {
    appendTraceModalCard(
      traceModalContent,
      "L4 MERGE BUDGET",
      (body) => {
        const fields =
          document.createElement("section");

        fields.className =
          "delayed-memory-modal-fields";

        appendTraceModalField(
          fields,
          "Reason",
          parsed.reason
        );
        appendTraceModalField(
          fields,
          "Pending queue",
          parsed.pending_count
        );
        appendTraceModalField(
          fields,
          "First pending ID",
          parsed.first_pending_id
        );
        appendTraceModalField(
          fields,
          "Context window",
          parsed.runtime_context_window_tokens
            ? `${parsed.runtime_context_window_tokens} tokens`
            : ""
        );
        appendTraceModalField(
          fields,
          "Prompt estimate",
          parsed.estimated_prompt_tokens
            ? `${parsed.estimated_prompt_tokens} tokens`
            : ""
        );
        appendTraceModalField(
          fields,
          "Response estimate",
          parsed.estimated_response_tokens
            ? `${parsed.estimated_response_tokens} tokens`
            : ""
        );
        appendTraceModalField(
          fields,
          "Provider reserve",
          parsed.runtime_output_reserve_tokens
            ? `${parsed.runtime_output_reserve_tokens} tokens`
            : ""
        );
        appendTraceModalField(
          fields,
          "Reasoning headroom target",
          parsed.default_response_headroom_tokens
            ? `${parsed.default_response_headroom_tokens} tokens`
            : ""
        );
        appendTraceModalField(
          fields,
          "Reasoning headroom used",
          parsed.response_headroom_tokens
            ? `${parsed.response_headroom_tokens} tokens`
            : ""
        );
        appendTraceModalField(
          fields,
          "Estimated total",
          parsed.estimated_total_tokens
            ? `${parsed.estimated_total_tokens} tokens`
            : ""
        );
        appendTraceModalField(
          fields,
          "Overflow",
          Number(parsed.overflow_tokens || 0)
            ? `${parsed.overflow_tokens} tokens`
            : "0 tokens"
        );

        body.appendChild(fields);

        appendTraceModalBody(
          body,
          "What happened",
          parsed.summary
        );
        appendTraceModalBody(
          body,
          "Retry behavior",
          parsed.retry_behavior
        );
      }
    );

    appendTraceModalCard(
      traceModalContent,
      "MERGE PAYLOAD",
      (body) => {
        appendTraceModalBody(
          body,
          "Pending candidate",
          parsed.merge_candidate || {}
        );
        appendTraceModalBody(
          body,
          "Full service request payload",
          parsed.request_payload || {}
        );
      }
    );

    return;
  }

  appendTraceModalBody(
    traceModalContent,
    "What happened",
    parsed.summary || "The L4 model response was not usable."
  );

  const fields =
    document.createElement("section");

  fields.className =
    "delayed-memory-modal-fields";

  appendTraceModalField(
    fields,
    "Phase",
    parsed.phase
  );

  appendTraceModalField(
    fields,
    "Finish reason",
    parsed.finish_reason
  );

  appendTraceModalField(
    fields,
    "Limit reached",
    parsed.limit_type
  );

  appendTraceModalField(
    fields,
    "Model",
    parsed.model
  );

  appendTraceModalField(
    fields,
    "Context window",
    parsed.context_window_tokens
      ? `${parsed.context_window_tokens} tokens`
      : ""
  );

  appendTraceModalField(
    fields,
    "Requested max output",
    parsed.requested_max_output_tokens
      ? `${parsed.requested_max_output_tokens} tokens`
      : ""
  );

  appendTraceModalField(
    fields,
    "Effective max output",
    parsed.effective_max_output_tokens
      ? `${parsed.effective_max_output_tokens} tokens`
      : ""
  );

  appendTraceModalField(
    fields,
    "Prompt tokens",
    parsed.prompt_tokens
  );

  appendTraceModalField(
    fields,
    "Generated tokens",
    parsed.completion_tokens
  );

  appendTraceModalField(
    fields,
    "Total tokens",
    parsed.total_tokens
  );

  appendTraceModalField(
    fields,
    "Assistant response",
    parsed.assistant_content
  );

  appendTraceModalField(
    fields,
    "Reasoning generated",
    parsed.reasoning_generated
  );

  if (fields.childElementCount) {
    traceModalContent.appendChild(
      fields
    );
  }

  appendTraceModalBody(
    traceModalContent,
    "What JIN did",
    "The incomplete response was discarded. No L4 facts were merged or removed."
  );

  appendTraceModalBody(
    traceModalContent,
    "Retry behavior",
    parsed.retry_behavior
  );

  const pendingCount =
    Number(
      parsed.pending_count
      || parsed.selected_fields_count
      || 0
    );

  if (pendingCount) {
    appendTraceModalBody(
      traceModalContent,
      "Pending batch kept",
      `${pendingCount} item${pendingCount === 1 ? "" : "s"} remain pending.`
    );
  }

  if (
      Array.isArray(parsed.pending_ids)
      && parsed.pending_ids.length
  ) {
    appendTraceModalBody(
      traceModalContent,
      "Pending IDs",
      parsed.pending_ids.join("\n")
    );
  }
}

function isSummarizerRequestPayload(parsed) {
  return Boolean(
    parsed
    && typeof parsed === "object"
    && Array.isArray(parsed.messages)
    && parsed.messages.some((message) => {
      return (
        message
        && typeof message === "object"
        && typeof message.role === "string"
        && Object.prototype.hasOwnProperty.call(
          message,
          "content"
        )
      );
    })
  );
}

function renderSummarizerRequestTrace(
  parsed,
  title,
) {
  const fields =
    document.createElement("section");

  fields.className =
    "delayed-memory-modal-fields";

  appendTraceModalField(
    fields,
    "Title",
    title
  );

  appendTraceModalField(
    fields,
    "Model",
    parsed.model
  );

  appendTraceModalField(
    fields,
    "Temperature",
    parsed.temperature
  );

  appendTraceModalField(
    fields,
    "Max tokens",
    parsed.max_tokens
  );

  appendTraceModalField(
    fields,
    "Stream",
    parsed.stream
  );

  appendTraceModalField(
    fields,
    "Messages",
    parsed.messages.length
  );

  traceModalContent.appendChild(
    fields
  );

  parsed.messages.forEach((message, index) => {
    const role =
      normalizeTraceModalDisplayText(message.role)
      || `message ${index + 1}`;

    appendTraceModalBody(
      traceModalContent,
      `${role} message`,
      message.content
    );
  });

  const extra = {};

  Object.entries(parsed).forEach(([key, value]) => {
    if (
        [
          "model",
          "messages",
          "temperature",
          "max_tokens",
          "stream",
        ].includes(key)
    ) {
      return;
    }

    extra[key] = value;
  });

  if (Object.keys(extra).length) {
    appendTraceModalBody(
      traceModalContent,
      "Extra request options",
      extra
    );
  }
}

function formatEmbeddedSummarizerReasoning(details) {
  const text =
    String(details || "");

  const sectionMarker =
    "Summarizer response details:";

  const sectionIndex =
    text.indexOf(sectionMarker);

  if (sectionIndex < 0) {
    return text;
  }

  const jsonStart =
    text.indexOf(
      "{",
      sectionIndex + sectionMarker.length
    );

  if (jsonStart < 0) {
    return text;
  }

  const responseText =
    text.slice(jsonStart);

  const response =
    parseTraceJson(
      responseText.trim()
    );

  if (
      !response
      || response.kind !== "summarizer_response"
      || typeof response.reasoning_content !== "string"
      || !response.reasoning_content
  ) {
    return text;
  }

  const serializedReasoning =
    JSON.stringify(
      response.reasoning_content
    );

  const fieldText =
    `"reasoning_content": ${serializedReasoning}`;

  const fieldIndex =
    responseText.indexOf(fieldText);

  if (fieldIndex < 0) {
    return text;
  }

  const lineStart =
    responseText.lastIndexOf(
      "\n",
      fieldIndex
    ) + 1;

  const indent =
    responseText.slice(
      lineStart,
      fieldIndex
    );

  let fieldEnd =
    fieldIndex + fieldText.length;

  if (responseText[fieldEnd] === ",") {
    fieldEnd += 1;
  }

  const reasoning =
    response.reasoning_content.replace(
      /\r\n?/g,
      "\n"
    );

  const formattedField = [
    `"reasoning_content":`,
    `${indent}--------------------`,
    reasoning,
    "",
  ].join("\n");

  return (
    text.slice(0, jsonStart)
    + responseText.slice(0, fieldIndex)
    + formattedField
    + responseText.slice(fieldEnd)
  );
}


function contextElement(
  tag,
  className,
  text = null,
) {
  const element =
    document.createElement(tag);

  if (className) {
    element.className = className;
  }

  if (text !== null) {
    element.textContent = text;
  }

  return element;
}

function parseContextTraceSnapshot(details) {
  const text =
    String(details || "").replace(
      /\r\n?/g,
      "\n"
    );

  const header =
    text.match(
      /^SYSTEM PROMPT(?: \(INTERNAL ACTION RULES HIDDEN\))?\n-+\n/
    );
  const userMarker =
    /\nUSER PROMPT \/ CONTEXT PAYLOAD\n-+\n/;
  const user =
    userMarker.exec(text);

  if (!header || !user) {
    return null;
  }

  return {
    hiddenInternalActionRules:
      header[0].includes(
        "INTERNAL ACTION RULES HIDDEN"
      ),
    systemPrompt:
      text.slice(
        header[0].length,
        user.index
      ).trim(),
    userPrompt:
      text.slice(
        user.index + user[0].length
      ).trim(),
  };
}

function parseContextAttributes(raw) {
  const attributes = [];
  const pattern =
    /([A-Za-z_][\w.-]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s]+))/g;
  let match;

  while ((match = pattern.exec(String(raw || "")))) {
    attributes.push(
      `${match[1]}=${match[2] ?? match[3] ?? match[4] ?? ""}`
    );
  }

  return attributes;
}

function parseContextRuntimeActionMarkerTitle(
  line,
  nextLine,
) {
  if (
      !/^Follow-up:\s*(?:true|false)\s*$/i.test(
        String(nextLine || "").trim()
      )
  ) {
    return "";
  }

  const marker =
    String(line || "").trim();
  const match =
    marker.match(
      /^<([A-Z][A-Z0-9_]*)(?::[^>\n]*)?>(?:<\/\1>)?$/
    );

  return match ? match[1] : "";
}

function splitContextPlainText(text) {
  const blocks = [];
  let title = "SYSTEM RULES";
  let lines = [];

  const flush = (runtimeActionMarker = false) => {
    const content =
      lines.join("\n").trim();

    if (content) {
      blocks.push({
        title,
        content,
        attributes: [],
        xml: false,
        runtimeActionMarker,
      });
    }

    lines = [];
  };

  const sourceLines =
    String(text || "").split("\n");

  for (let i = 0; i < sourceLines.length; i += 1) {
    const line = sourceLines[i];
    const heading = line.trim();
    const markerTitle =
      parseContextRuntimeActionMarkerTitle(
        line,
        sourceLines[i + 1]
      );

    if (markerTitle) {
      flush();
      title = markerTitle;
      lines.push(line);

      for (i += 1; i < sourceLines.length; i += 1) {
        const actionLine = sourceLines[i];

        if (!actionLine.trim()) {
          break;
        }

        if (actionLine.trim() === `${markerTitle}:`) {
          continue;
        }

        lines.push(actionLine);
      }

      flush(true);
      title = "SYSTEM RULES";
      continue;
    }

    if (
        /^[A-Z][A-Z0-9 _/&()\-]{3,}:$/.test(heading)
    ) {
      flush();
      title = heading.slice(0, -1);
      continue;
    }

    lines.push(line);
  }

  flush();
  return blocks;
}

function parseContextBlocks(text) {
  const source =
    String(text || "").replace(
      /\r\n?/g,
      "\n"
    );
  const lines = source.split("\n");
  const blocks = [];
  let plain = [];

  const flushPlain = () => {
    const content =
      plain.join("\n").trim();

    if (content) {
      blocks.push(
        ...splitContextPlainText(content)
      );
    }

    plain = [];
  };

  for (let i = 0; i < lines.length; i += 1) {
    const markerTitle =
      parseContextRuntimeActionMarkerTitle(
        lines[i],
        lines[i + 1]
      );

    if (markerTitle) {
      plain.push(lines[i]);

      for (i += 1; i < lines.length; i += 1) {
        plain.push(lines[i]);

        if (!lines[i].trim()) {
          break;
        }
      }

      continue;
    }

    const open =
      lines[i].match(
        /^\s*<([A-Za-z][\w.-]*)(\s+[^>]*)?>\s*$/
      );

    if (!open) {
      plain.push(lines[i]);
      continue;
    }

    const closeText =
      `</${open[1]}>`;
    let close = -1;

    for (let j = i + 1; j < lines.length; j += 1) {
      if (lines[j].trim() === closeText) {
        close = j;
        break;
      }
    }

    if (close < 0) {
      plain.push(lines[i]);
      continue;
    }

    flushPlain();
    blocks.push({
      title: open[1],
      attributes:
        parseContextAttributes(open[2]),
      content:
        lines.slice(i + 1, close)
          .join("\n")
          .trim(),
      xml: true,
    });
    i = close;
  }

  flushPlain();
  return blocks;
}

function contextBadge(text, attribute = false) {
  return contextElement(
    "span",
    attribute
      ? "jin-context-badge jin-context-badge-attribute"
      : "jin-context-badge",
    text
  );
}

function parseContextRows(content) {
  const lines =
    String(content || "")
      .split("\n")
      .filter((line) => line.trim());

  const chat = lines.map((line) => {
    const match =
      line.match(
        /^\s*<(USER|JIN|SERVICE|BRAIN)>([\s\S]*?)(?:<\/\1>)?\s*$/
      );

    return match
      ? {
          kind: "chat",
          key: match[1],
          value: match[2].trim(),
        }
      : null;
  });

  if (chat.length && chat.every(Boolean)) {
    return chat;
  }

  const tags = lines.map((line) => {
    const match =
      line.match(
        /^\s*<([A-Za-z][\w.-]*)>([\s\S]*?)<\/\1>\s*$/
      );

    return match
      ? {
          kind: "kv",
          key: match[1],
          value: match[2].trim(),
        }
      : null;
  });

  if (tags.length && tags.every(Boolean)) {
    return tags;
  }

  const fields = lines
    .map((line) => {
      const match =
        line.match(
          /^\s*([^:]{1,90}):\s*(.*)$/
        );

      return match
        ? {
            kind: "kv",
            key: match[1].trim(),
            value: match[2].trim(),
          }
        : null;
    })
    .filter(Boolean);

  if (
      fields.length >= 2
      && fields.length / Math.max(lines.length, 1) >= 0.7
  ) {
    return fields;
  }

  return [];
}

function normalizeContextDelayedMemoryReportId(value) {
  const match =
    String(value || "")
      .trim()
      .match(/^([a-z0-9]{6})(?:_|$)/i);

  return match
    ? String(match[1] || "").toLowerCase()
    : "";
}

function getContextDelayedMemoryReports() {
  const runtime =
    window.JinRuntime
    && window.JinRuntime.runtime;

  if (
      !runtime
      || typeof runtime.getDelayedMemoryReports !== "function"
  ) {
    return {};
  }

  const reports =
    runtime.getDelayedMemoryReports();

  return (
      reports
      && typeof reports === "object"
      && !Array.isArray(reports)
    )
      ? reports
      : {};
}

function getContextDelayedMemoryReport(reportId) {
  const normalizedReportId =
    normalizeContextDelayedMemoryReportId(reportId);
  const reports =
    getContextDelayedMemoryReports();
  const report =
    normalizedReportId
    && reports[normalizedReportId];

  if (
      !report
      || typeof report !== "object"
      || Array.isArray(report)
  ) {
    return null;
  }

  return {
    ...report,
    _storage_key: normalizedReportId,
  };
}

function setContextDelayedMemoryHover(
  reportId,
  active
) {
  const memoryView =
    window.JinRuntime
    && window.JinRuntime.memoryView;

  if (
      memoryView
      && typeof memoryView.setDelayedMemoryReportHover === "function"
  ) {
    memoryView.setDelayedMemoryReportHover(
      reportId,
      active
    );
    return;
  }

  const buildAvatarMemoryHoverId =
    window.JinRuntime
    && window.JinRuntime.buildAvatarMemoryHoverId;
  const avatarMemoryHoverId =
    active
    && typeof buildAvatarMemoryHoverId === "function"
      ? buildAvatarMemoryHoverId(
          "delayed",
          reportId
        )
      : "";

  window.dispatchEvent(
    new CustomEvent(
      "jin:memory-row-avatar-hover",
      {
        detail: avatarMemoryHoverId
          ? {
              active: true,
              avatarMemoryHoverId,
            }
          : {
              active: false,
            },
      }
    )
  );
}

function openContextDelayedMemoryReport(reportId) {
  const report =
    getContextDelayedMemoryReport(reportId);
  const memoryView =
    window.JinRuntime
    && window.JinRuntime.memoryView;

  if (
      !report
      || !memoryView
      || typeof memoryView.openDelayedMemoryReportModal !== "function"
  ) {
    return false;
  }

  setContextDelayedMemoryHover(
    reportId,
    false
  );
  memoryView.openDelayedMemoryReportModal(
    report
  );
  return true;
}

function parseContextLongTermMemoryLine(line) {
  const source = String(line || "").trim();
  const separatorIndex = source.indexOf(":");
  const idMatch = source.match(
    /\[\s*id\s*:\s*(F\d+)\s*\]/i
  );

  if (
    separatorIndex <= 0
    || !idMatch
    || typeof idMatch.index !== "number"
    || idMatch.index <= separatorIndex
  ) {
    return null;
  }

  const delayedMemoryIds = [];
  const seenDelayedMemoryIds = new Set();
  const delayedPattern =
    /\[\s*delayed_memory_id\s*:\s*([^\]]+?)\s*\]/gi;
  let delayedMatch = null;

  while ((delayedMatch = delayedPattern.exec(source)) !== null) {
    const reportId = normalizeContextDelayedMemoryReportId(
      delayedMatch[1]
    );

    if (!reportId || seenDelayedMemoryIds.has(reportId)) {
      continue;
    }

    seenDelayedMemoryIds.add(reportId);
    delayedMemoryIds.push(reportId);
  }

  const ageMatch = source.match(
    /\(\s*([0-9]+(?:s|m|h|d))\s+ago\s*\)\s*$/i
  );

  return {
    id: String(idMatch[1] || "").toUpperCase(),
    key: source.slice(0, separatorIndex).trim(),
    value: source.slice(separatorIndex + 1, idMatch.index).trim(),
    age: ageMatch
      ? `${String(ageMatch[1] || "").toLowerCase()} ago`
      : "",
    delayedMemoryIds,
  };
}

function resolveContextLongTermFactReport(delayedMemoryIds) {
  for (const rawReportId of Array.isArray(delayedMemoryIds) ? delayedMemoryIds : []) {
    const reportId = normalizeContextDelayedMemoryReportId(rawReportId);
    const report = getContextDelayedMemoryReport(reportId);

    if (reportId && report) {
      return {
        reportId,
        report,
      };
    }
  }

  return null;
}

function getContextLongTermFactReportTitle(linked) {
  if (!linked || !linked.report) {
    return "";
  }

  return String(
    linked.report.title
    || linked.report.summary
    || linked.report._storage_key
    || linked.reportId
    || ""
  ).trim();
}

function syncContextLongTermFactIdLink(node, delayedMemoryIds) {
  if (!node) {
    return null;
  }

  const linked = resolveContextLongTermFactReport(
    delayedMemoryIds
  );
  const linkedTitle = getContextLongTermFactReportTitle(linked);

  node.classList.toggle(
    "is-linked",
    Boolean(linked)
  );
  node.title = linkedTitle;
  node.setAttribute(
    "aria-disabled",
    linked ? "false" : "true"
  );

  return linked;
}

function renderContextLongTermMemoryBody(parent, content) {
  const records = String(content || "")
    .split("\n")
    .map(parseContextLongTermMemoryLine)
    .filter(Boolean);

  if (!records.length) {
    renderContextBody(parent, content);
    return;
  }

  const list = contextElement(
    "div",
    "jin-context-kv-list jin-context-l4-list"
  );

  records.forEach((record) => {
    const row = contextElement(
      "div",
      "jin-context-kv-row jin-context-l4-row"
    );
    const keyCell = contextElement(
      "div",
      "jin-context-kv-key jin-context-l4-key"
    );
    const factId = record.delayedMemoryIds.length
      ? document.createElement("button")
      : document.createElement("span");

    factId.className = "jin-context-l4-fact-id";
    factId.textContent = record.id;

    if (record.delayedMemoryIds.length) {
      factId.type = "button";
      syncContextLongTermFactIdLink(
        factId,
        record.delayedMemoryIds
      );

      factId.addEventListener("mouseenter", () => {
        syncContextLongTermFactIdLink(
          factId,
          record.delayedMemoryIds
        );
      });
      factId.addEventListener("focus", () => {
        syncContextLongTermFactIdLink(
          factId,
          record.delayedMemoryIds
        );
      });
      factId.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();

        const linked = syncContextLongTermFactIdLink(
          factId,
          record.delayedMemoryIds
        );

        if (linked) {
          openContextDelayedMemoryReport(
            linked.reportId
          );
        }
      });
    }

    keyCell.appendChild(factId);
    keyCell.appendChild(
      contextElement(
        "span",
        "jin-context-l4-separator",
        "·"
      )
    );
    keyCell.appendChild(
      contextElement(
        "span",
        "jin-context-l4-fact-key",
        record.key
      )
    );

    if (record.age) {
      keyCell.appendChild(
        contextElement(
          "span",
          "jin-context-l4-separator",
          "·"
        )
      );
      keyCell.appendChild(
        contextElement(
          "span",
          "jin-context-l4-age",
          record.age
        )
      );
    }

    row.appendChild(keyCell);
    row.appendChild(
      contextElement(
        "div",
        "jin-context-kv-value jin-context-l4-value",
        record.value || "<empty>"
      )
    );
    list.appendChild(row);
  });

  parent.appendChild(list);
}

function syncContextDelayedMemoryRow(row) {
  if (!row || !row.dataset) {
    return;
  }

  const reportId =
    normalizeContextDelayedMemoryReportId(
      row.dataset.delayedMemoryId
    );
  const report =
    getContextDelayedMemoryReport(reportId);
  const pinButton =
    row.querySelector(
      ".jin-context-delayed-pin"
    );
  const missing = !report;

  row.classList.toggle(
    "is-missing",
    missing
  );
  row.dataset.delayedMemoryMissing =
    missing ? "true" : "false";
  row.setAttribute(
    "aria-disabled",
    missing ? "true" : "false"
  );

  if (missing) {
    row.removeAttribute("role");
    row.removeAttribute("tabindex");
    row.classList.remove("is-pinned");

    if (pinButton) {
      pinButton.disabled = true;
      pinButton.classList.remove(
        "delayed-memory-modal-pin-active",
        "delayed-memory-modal-pin-loaded"
      );
      pinButton.title =
        "Delayed memory report deleted";
    }

    return;
  }

  row.setAttribute(
    "role",
    "button"
  );
  row.setAttribute(
    "tabindex",
    "0"
  );

  if (!pinButton) {
    return;
  }

  const runtime =
    window.JinRuntime
    && window.JinRuntime.runtime;
  const pinned =
    Boolean(report.pinned);
  const loaded =
    !pinned
    && runtime
    && typeof runtime.isDelayedMemoryReportLoaded === "function"
    && runtime.isDelayedMemoryReportLoaded(reportId);

  pinButton.disabled = false;
  row.classList.toggle(
    "is-pinned",
    pinned
  );
  pinButton.classList.toggle(
    "delayed-memory-modal-pin-active",
    pinned
  );
  pinButton.classList.toggle(
    "delayed-memory-modal-pin-loaded",
    Boolean(loaded)
  );
  pinButton.setAttribute(
    "aria-pressed",
    pinned ? "true" : "false"
  );
  pinButton.setAttribute(
    "aria-label",
    loaded
      ? "Unload delayed memory"
      : (
          pinned
            ? "Unpin delayed memory"
            : "Pin delayed memory"
        )
  );
  pinButton.title =
    loaded
      ? "Unload delayed memory from context"
      : (
          pinned
            ? "Unpin delayed memory"
            : "Pin delayed memory"
        );
}

function syncContextDelayedMemoryRows(reportId = "") {
  if (!traceModalContent) {
    return;
  }

  const normalizedReportId =
    normalizeContextDelayedMemoryReportId(
      reportId
    );
  const rows =
    Array.from(
      traceModalContent.querySelectorAll(
        ".jin-context-delayed-row"
      )
    );

  rows.forEach((row) => {
    if (
        normalizedReportId
        && normalizeContextDelayedMemoryReportId(
          row.dataset.delayedMemoryId
        ) !== normalizedReportId
    ) {
      return;
    }

    syncContextDelayedMemoryRow(
      row
    );
  });
}

function renderContextDelayedMemoryBody(
  parent,
  content
) {
  const lines =
    String(content || "")
      .split("\n")
      .map(line => line.trim())
      .filter(Boolean);

  if (!lines.length) {
    parent.appendChild(
      contextElement(
        "div",
        "jin-context-empty",
        "EMPTY"
      )
    );
    return;
  }

  const list =
    contextElement(
      "div",
      "jin-context-delayed-list"
    );

  lines.forEach((line) => {
    const reportId =
      normalizeContextDelayedMemoryReportId(
        line
      );
    const row =
      contextElement(
        "div",
        "jin-context-delayed-row"
      );
    const pinButton =
      contextElement(
        "button",
        "delayed-memory-modal-icon-button delayed-memory-modal-pin jin-context-delayed-pin"
      );
    const label =
      contextElement(
        "span",
        "jin-context-delayed-label",
        line
      );

    row.dataset.delayedMemoryId =
      reportId;
    pinButton.type = "button";
    pinButton.setAttribute(
      "aria-pressed",
      "false"
    );
    pinButton.innerHTML =
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.7 3.3 20.7 9.3 18.6 11.4 16.9 9.7 13.7 12.9 14.4 15.7 12.9 17.2 9.4 13.7 5.3 17.8 4.2 16.7 8.3 12.6 4.8 9.1 6.3 7.6 9.1 8.3 12.3 5.1 10.6 3.4 12.7 1.3Z"/></svg>';

    row.appendChild(pinButton);
    row.appendChild(label);

    row.addEventListener(
      "click",
      function (event) {
        if (
            event.target
            && event.target.closest(
              ".jin-context-delayed-pin"
            )
        ) {
          return;
        }

        if (
            row.dataset.delayedMemoryMissing === "true"
        ) {
          return;
        }

        if (!openContextDelayedMemoryReport(reportId)) {
          syncContextDelayedMemoryRow(row);
        }
      }
    );

    row.addEventListener(
      "keydown",
      function (event) {
        if (
            event.target !== row
            || (
              event.key !== "Enter"
              && event.key !== " "
            )
            || row.dataset.delayedMemoryMissing === "true"
        ) {
          return;
        }

        event.preventDefault();

        if (!openContextDelayedMemoryReport(reportId)) {
          syncContextDelayedMemoryRow(row);
        }
      }
    );

    row.addEventListener(
      "mouseenter",
      function () {
        if (
            row.dataset.delayedMemoryMissing === "true"
        ) {
          return;
        }

        setContextDelayedMemoryHover(
          reportId,
          true
        );
      }
    );

    row.addEventListener(
      "mouseleave",
      function () {
        setContextDelayedMemoryHover(
          reportId,
          false
        );
      }
    );

    pinButton.addEventListener(
      "click",
      function (event) {
        event.preventDefault();
        event.stopPropagation();

        const report =
          getContextDelayedMemoryReport(
            reportId
          );
        const runtime =
          window.JinRuntime
          && window.JinRuntime.runtime;

        if (
            !report
            || !runtime
            || (
              typeof runtime.handleDelayedMemoryReportPinClick !== "function"
              && typeof runtime.setDelayedMemoryReportPinned !== "function"
            )
        ) {
          syncContextDelayedMemoryRow(row);
          return;
        }

        if (typeof runtime.handleDelayedMemoryReportPinClick === "function") {
          runtime.handleDelayedMemoryReportPinClick(
            reportId
          );
        } else {
          runtime.setDelayedMemoryReportPinned(
            reportId,
            !Boolean(report.pinned)
          );
        }
        syncContextDelayedMemoryRow(row);
      }
    );

    list.appendChild(row);
    syncContextDelayedMemoryRow(row);
  });

  parent.appendChild(list);
}

function parseContextAttachedFileLine(line) {
  const text = String(line || "").trim();
  const match = text.match(/^(.*?)\s*\[\s*id\s*:\s*([a-z0-9]{6})\s*\]\s*$/i);
  if (!match) return null;
  return {
    name: String(match[1] || "").trim(),
    id: String(match[2] || "").toLowerCase(),
  };
}

function syncContextAttachedFileRows() {
  if (!traceModalContent) return;
  traceModalContent.querySelectorAll(".jin-context-attached-file-row").forEach((row) => {
    const fileId = String(row.dataset.attachedFileId || "").toLowerCase();
    const record = window.JinFiles && typeof window.JinFiles.getFile === "function"
      ? window.JinFiles.getFile(fileId)
      : null;
    const pin = row.querySelector(".jin-context-attached-file-pin");
    const pinned = Boolean(record && record.pinned);
    row.classList.toggle("is-pinned", pinned);
    row.classList.toggle("opacity-50", !record);
    if (pin) {
      pin.disabled = !record;
      pin.classList.toggle("delayed-memory-modal-pin-active", pinned);
      pin.setAttribute("aria-pressed", pinned ? "true" : "false");
      pin.title = pinned ? "Remove file from JIN context" : "Attach file to JIN context";
    }
  });
}

function renderContextAttachedFilesBody(parent, content) {
  const records = String(content || "")
    .split("\n")
    .map(parseContextAttachedFileLine)
    .filter(Boolean);

  if (!records.length) return;

  const list = contextElement("div", "jin-context-delayed-list");
  records.forEach((item) => {
    const row = contextElement("div", "jin-context-delayed-row jin-context-attached-file-row");
    row.dataset.attachedFileId = item.id;
    row.setAttribute("role", "button");
    row.setAttribute("tabindex", "0");

    const pin = contextElement(
      "button",
      "delayed-memory-modal-icon-button delayed-memory-modal-pin jin-context-delayed-pin jin-context-attached-file-pin"
    );
    pin.type = "button";
    pin.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.7 3.3 20.7 9.3 18.6 11.4 16.9 9.7 13.7 12.9 14.4 15.7 12.9 17.2 9.4 13.7 5.3 17.8 4.2 16.7 8.3 12.6 4.8 9.1 6.3 7.6 9.1 8.3 12.3 5.1 10.6 3.4 12.7 1.3Z"/></svg>';
    const label = contextElement(
      "span",
      "jin-context-delayed-label",
      `${item.name} [ id: ${item.id} ]`
    );

    pin.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const record = window.JinFiles && window.JinFiles.getFile(item.id);
      if (!record || !window.JinFiles) return;
      void window.JinFiles.setPinned(item.id, !Boolean(record.pinned));
    });

    const open = () => {
      const record = window.JinFiles && window.JinFiles.getFile(item.id);
      if (record && typeof window.openJinAttachmentModal === "function") {
        window.openJinAttachmentModal(record);
      }
    };
    row.addEventListener("click", (event) => {
      if (event.target && event.target.closest(".jin-context-attached-file-pin")) return;
      open();
    });
    row.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      open();
    });

    row.append(pin, label);
    list.appendChild(row);
  });
  parent.appendChild(list);
  syncContextAttachedFileRows();
}

function parseContextUserPromptAttachedFileRow(row) {
  if (!row) {
    return null;
  }

  const keyElement =
    row.querySelector(
      ".jin-context-kv-key"
    );
  const valueElement =
    row.querySelector(
      ".jin-context-kv-value"
    );
  const key =
    String(
      keyElement && keyElement.textContent || ""
    ).trim();
  const value =
    String(
      valueElement && valueElement.textContent || ""
    ).trim();
  const pathMatch =
    key.match(
      /(?:^|\s)(\/assets\/files\/[^\s:]+)\s*$/i
    );
  const idMatch =
    value.match(
      /\[\s*id\s*:\s*([a-z0-9]{6})\s*\]/i
    );

  if (
      !pathMatch
      || !idMatch
      || !/^image(?:\s*,|$)/i.test(value)
  ) {
    return null;
  }

  const id =
    String(idMatch[1] || "")
      .trim()
      .toLowerCase();
  const path =
    String(pathMatch[1] || "").trim();
  const mimeMatch =
    value.match(
      /^image\s*,\s*([^,\s]+)/i
    );
  const storedRecord =
    window.JinFiles
    && typeof window.JinFiles.getFile === "function"
      ? window.JinFiles.getFile(id)
      : null;

  return {
    id,
    kind: "image",
    type:
      mimeMatch
        ? String(mimeMatch[1] || "")
        : "image",
    url: path,
    ...(storedRecord || {}),
  };
}

function bindContextUserPromptAttachedFilePreviews(parent) {
  if (!parent) {
    return;
  }

  parent
    .querySelectorAll(
      ".jin-context-kv-row"
    )
    .forEach((row) => {
      const attachment =
        parseContextUserPromptAttachedFileRow(
          row
        );

      if (!attachment) {
        return;
      }

      row.classList.add(
        "jin-context-user-attached-file-row"
      );

      const bind = () => {
        if (
            !row.isConnected
            || row.dataset[
              CONTEXT_ATTACHMENT_HOVER_BOUND_DATASET_KEY
            ] === "1"
        ) {
          return true;
        }

        if (
            typeof window.bindJinAttachmentHoverPreview !== "function"
        ) {
          return false;
        }

        window.bindJinAttachmentHoverPreview(
          row,
          attachment,
          {
            hoverPreviewMaxPx: 100,
          }
        );
        row.dataset[
          CONTEXT_ATTACHMENT_HOVER_BOUND_DATASET_KEY
        ] = "1";
        return true;
      };

      if (!bind()) {
        window.addEventListener(
          "jin:attachment-ui-ready",
          bind,
          {once: true}
        );
      }
    });
}

function renderContextUserPromptBody(parent, content) {
  renderContextBody(
    parent,
    content
  );
  bindContextUserPromptAttachedFilePreviews(
    parent
  );
}

function renderContextBody(parent, content) {
  const text =
    String(content || "").trim();

  if (!text) {
    parent.appendChild(
      contextElement(
        "div",
        "jin-context-empty",
        "EMPTY"
      )
    );
    return;
  }

  const rows =
    parseContextRows(text);

  if (rows.length) {
    const list =
      contextElement(
        "div",
        "jin-context-kv-list"
      );

    rows.forEach((row) => {
      const item =
        contextElement(
          "div",
          row.kind === "chat"
            ? `jin-context-chat-row jin-context-chat-${row.key.toLowerCase()}`
            : "jin-context-kv-row"
        );

      item.appendChild(
        contextElement(
          "div",
          row.kind === "chat"
            ? "jin-context-chat-role"
            : "jin-context-kv-key",
          row.key
        )
      );
      item.appendChild(
        contextElement(
          "div",
          row.kind === "chat"
            ? "jin-context-chat-content"
            : "jin-context-kv-value",
          row.value || "<empty>"
        )
      );
      list.appendChild(item);
    });

    parent.appendChild(list);
    return;
  }

  const lines =
    text.split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
  const simpleList =
    lines.length > 1
    && lines.length <= 40
    && lines.every((line) => (
      /^\d+[.)]\s+/.test(line)
      || /^[A-Za-z0-9_#.-]+(?:\s+.*)?$/.test(line)
    ));

  if (simpleList) {
    const list =
      contextElement(
        "div",
        "jin-context-line-list"
      );

    lines.forEach((line) => {
      list.appendChild(
        contextElement(
          "div",
          "jin-context-line-item",
          line
        )
      );
    });

    parent.appendChild(list);
    return;
  }

  parent.appendChild(
    contextElement(
      "pre",
      "jin-context-raw",
      text
    )
  );
}

function setContextCardCollapsed(
  card,
  collapsed,
) {
  card.classList.toggle(
    "is-collapsed",
    collapsed
  );

  const header =
    card.querySelector(
      ".jin-context-card-header"
    );

  if (header) {
    header.setAttribute(
      "aria-expanded",
      collapsed ? "false" : "true"
    );
  }

  if (
      !collapsed
      && card.classList.contains(
        "jin-context-card-action-markers"
      )
  ) {
    const markerStack =
      card.querySelector(
        ".jin-context-action-markers-stack"
      );

    Array.from(
      markerStack ? markerStack.children : []
    ).forEach((markerCard) => {
      if (
          markerCard.classList.contains(
            "jin-context-card"
          )
      ) {
        setContextCardCollapsed(
          markerCard,
          false
        );
      }
    });
  }
}

function appendContextCard(
  parent,
  block,
  onToggle = null,
) {
  const card =
    contextElement(
      "section",
      `jin-context-card ${block.xml ? "jin-context-card-xml" : "jin-context-card-plain"}`
    );
  const header =
    contextElement(
      "div",
      "jin-context-card-header"
    );
  const heading =
    contextElement(
      "div",
      "jin-context-card-heading"
    );
  const meta =
    contextElement(
      "div",
      "jin-context-card-meta"
    );
  const body =
    contextElement(
      "div",
      "jin-context-card-body"
    );

  header.title =
    "Click to collapse / expand";
  header.style.cursor =
    "pointer";
  header.tabIndex = 0;
  header.setAttribute("role", "button");
  header.setAttribute("aria-expanded", "true");

  const displayTitle =
    String(block.title || "")
      .trim()
      .toUpperCase() === "SESSION_ACTIONS_HISTORY"
      ? "SESSION_ACTIONS"
      : block.title;

  heading.appendChild(
    contextElement(
      "div",
      "jin-context-card-title",
      displayTitle
    )
  );

  block.attributes.forEach((attribute) => {
    meta.appendChild(
      contextBadge(attribute, true)
    );
  });
  meta.appendChild(
    contextBadge(
      block.metaLabel
      || `${String(block.content || "").split("\n").filter((line) => line.trim()).length} lines`
    )
  );

  const toggle = () => {
    const collapsed =
      !card.classList.contains(
        "is-collapsed"
      );

    setContextCardCollapsed(
      card,
      collapsed
    );

    if (typeof onToggle === "function") {
      onToggle(card, collapsed);
    }
  };

  header.addEventListener(
    "click",
    toggle
  );
  header.addEventListener(
    "keydown",
    function (event) {
      if (
          event.key !== "Enter"
          && event.key !== " "
      ) {
        return;
      }

      event.preventDefault();
      toggle();
    }
  );

  header.appendChild(heading);
  header.appendChild(meta);
  card.appendChild(header);
  card.appendChild(body);
  const normalizedBlockTitle = String(block.title || "")
    .trim()
    .toUpperCase();

  if (typeof block.renderBody === "function") {
    block.renderBody(body);
  } else if (normalizedBlockTitle === "LONG_TERM_MEMORY") {
    renderContextLongTermMemoryBody(
      body,
      block.content
    );
  } else if (normalizedBlockTitle === "DELAYED_MEMORY") {
    renderContextDelayedMemoryBody(
      body,
      block.content
    );
  } else if (normalizedBlockTitle === "ATTACHED_FILES") {
    renderContextAttachedFilesBody(
      body,
      block.content
    );
  } else {
    renderContextBody(
      body,
      block.content
    );
  }
  parent.appendChild(card);
  return card;
}

function appendContextActionMarkersCard(
  parent,
  markerBlocks,
  onToggle = null,
) {
  const markerStack =
    contextElement(
      "div",
      "jin-context-stack jin-context-action-markers-stack"
    );

  const groupCard =
    appendContextCard(
      parent,
      {
        title: "ACTION MARKERS",
        content: markerBlocks
          .map((block) => block.content || "")
          .join("\n"),
        attributes: [],
        xml: false,
        metaLabel: `${markerBlocks.length} markers`,
        renderBody: (body) => {
          markerBlocks.forEach((block) => {
            appendContextCard(
              markerStack,
              block
            );
          });
          body.appendChild(markerStack);
        },
      },
      onToggle
    );

  groupCard.classList.add(
    "jin-context-card-action-markers"
  );
  setContextCardCollapsed(
    groupCard,
    true
  );

  return groupCard;
}

function renderContextSnapshotTrace(snapshot) {
  const blocks =
    parseContextBlocks(
      snapshot.systemPrompt
    );
  const overview =
    contextElement(
      "div",
      "jin-context-overview"
    );
  const badges =
    contextElement(
      "div",
      "jin-context-overview-badges"
    );

  const collapseAllToggle =
    contextElement(
      "div",
      "jin-context-overview-title",
      "COLLAPSE ALL"
    );

  collapseAllToggle.tabIndex = 0;
  collapseAllToggle.setAttribute(
    "role",
    "button"
  );
  collapseAllToggle.style.cursor =
    "pointer";
  collapseAllToggle.style.userSelect =
    "none";

  overview.appendChild(
    collapseAllToggle
  );
  badges.appendChild(
    contextBadge(`${blocks.length} blocks`)
  );
  badges.appendChild(
    contextBadge(
      `${snapshot.systemPrompt.length.toLocaleString()} system chars`
    )
  );
  if (snapshot.hiddenInternalActionRules) {
    badges.appendChild(
      contextBadge("internal rules hidden")
    );
  }
  overview.appendChild(badges);
  traceModalContent.appendChild(overview);

  const stack =
    contextElement(
      "div",
      "jin-context-stack"
    );

  const getCards = () =>
    Array.from(stack.children).filter(
      (element) =>
        element.classList.contains(
          "jin-context-card"
        )
    );

  const syncCollapseAllToggle = () => {
    const cards =
      getCards();
    const allCollapsed =
      cards.length > 0
      && cards.every((card) =>
        card.classList.contains(
          "is-collapsed"
        )
      );
    const label =
      allCollapsed
        ? "EXPAND ALL"
        : "COLLAPSE ALL";

    collapseAllToggle.textContent =
      label;
    collapseAllToggle.title =
      allCollapsed
        ? "Expand all context blocks"
        : "Collapse all context blocks";
    collapseAllToggle.setAttribute(
      "aria-label",
      collapseAllToggle.title
    );
  };

  const toggleAllCards = () => {
    const cards =
      getCards();
    const allCollapsed =
      cards.length > 0
      && cards.every((card) =>
        card.classList.contains(
          "is-collapsed"
        )
      );

    cards.forEach((card) => {
      setContextCardCollapsed(
        card,
        !allCollapsed
      );
    });

    syncCollapseAllToggle();
  };

  collapseAllToggle.addEventListener(
    "click",
    toggleAllCards
  );
  collapseAllToggle.addEventListener(
    "keydown",
    function (event) {
      if (
          event.key !== "Enter"
          && event.key !== " "
      ) {
        return;
      }

      event.preventDefault();
      toggleAllCards();
    }
  );

  const actionMarkerBlocks =
    blocks.filter((block) =>
      block.runtimeActionMarker === true
    );
  let actionMarkersInserted = false;

  blocks.forEach((block) => {
    if (block.runtimeActionMarker === true) {
      if (!actionMarkersInserted) {
        appendContextActionMarkersCard(
          stack,
          actionMarkerBlocks,
          syncCollapseAllToggle
        );
        actionMarkersInserted = true;
      }
      return;
    }

    appendContextCard(
      stack,
      block,
      syncCollapseAllToggle
    );
  });

  const userCard =
    appendContextCard(
      stack,
      {
        title: "USER PROMPT / CONTEXT PAYLOAD",
        content:
          snapshot.userPrompt || "<empty>",
        attributes: [],
        xml: false,
        renderBody: (body) => {
          renderContextUserPromptBody(
            body,
            snapshot.userPrompt || "<empty>"
          );
        },
      },
      syncCollapseAllToggle
    );

  userCard.classList.add(
    "jin-context-card-user"
  );

  syncCollapseAllToggle();
  traceModalContent.appendChild(stack);
}

function renderTraceDetails(
  details,
  title = "Trace",
) {
  clearContextAttachedFileHoverPreview();
  traceModalContent.replaceChildren();
  traceModalContextCopyText = "";

  if (traceModalCopyButton) {
    traceModalCopyButton.classList.add(
      "hidden"
    );
    traceModalCopyButton.classList.remove(
      "is-copied"
    );
    traceModalCopyButton.setAttribute(
      "aria-label",
      "Copy context"
    );
    traceModalCopyButton.title =
      "Copy raw context";
  }

  const contextSnapshot =
    parseContextTraceSnapshot(details);

  traceModal.classList.toggle(
    "jin-context-trace-modal",
    Boolean(contextSnapshot)
  );

  if (contextSnapshot) {
    traceModalContextCopyText = [
      contextSnapshot.systemPrompt,
      contextSnapshot.userPrompt,
    ]
      .filter((part) => String(part || "").trim())
      .join("\n\n");

    if (traceModalCopyButton) {
      traceModalCopyButton.classList.remove(
        "hidden"
      );
    }

    renderContextSnapshotTrace(
      contextSnapshot
    );

    return;
  }

  const parsed =
    parseTraceJson(details);

  if (
      parsed
      && parsed.kind === "l4_fact"
  ) {
    renderL4FactTrace(
      parsed
    );

    return;
  }

  if (
      parsed
      && parsed.kind === "l4_summarizer_response"
  ) {
    renderL4SummarizerResponseTrace(
      parsed
    );

    return;
  }

  if (
      parsed
      && parsed.kind === "l4_skip"
  ) {
    renderL4SkipTrace(
      parsed
    );

    return;
  }

  if (
      parsed
      && parsed.kind === "user_payload_trace"
  ) {
    renderUserPayloadTrace(
      parsed
    );

    return;
  }

  if (isSummarizerRequestPayload(parsed)) {
    renderSummarizerRequestTrace(
      parsed,
      title
    );

    return;
  }

  if (
      parsed
      && parsed.kind === "summarizer_response"
  ) {
    const meta = {
      model: parsed.model || "",
      finish_reason: parsed.finish_reason || "",
      allow_reasoning_fallback: Boolean(parsed.allow_reasoning_fallback),
      used_reasoning_fallback: Boolean(parsed.used_reasoning_fallback),
      usage: parsed.usage || {},
    };

    appendTraceSection(
      traceModalContent,
      "Meta",
      JSON.stringify(
        meta,
        null,
        2
      )
    );

    appendTraceSection(
      traceModalContent,
      "Assistant content",
      parsed.content || ""
    );

    appendTraceSection(
      traceModalContent,
      "Reasoning content",
      parsed.reasoning_content || ""
    );

    appendTraceSection(
      traceModalContent,
      "Extracted L1 memory text",
      parsed.extracted_memory || ""
    );

    appendTraceSection(
      traceModalContent,
      "Raw message",
      JSON.stringify(
        parsed.message || {},
        null,
        2
      )
    );

    return;
  }

  const pre =
    document.createElement("pre");

  pre.className =
    "whitespace-pre-wrap text-[12px] leading-relaxed text-zinc-200";

  pre.style.overflowWrap =
    "anywhere";

  pre.textContent =
    formatEmbeddedSummarizerReasoning(
      details
    );

  traceModalContent.appendChild(
    pre
  );
}

function getTraceTitle(
  details,
  fallbackTitle,
) {
  const parsed =
    parseTraceJson(details);

  if (
      parsed
      && parsed.kind === "summarizer_response"
  ) {
    return "Summarizer response";
  }

  if (isSummarizerRequestPayload(parsed)) {
    return fallbackTitle || "Summarizer request";
  }

  return fallbackTitle;
}

function showTrace(
  details,
  title = "Trace",
  reason = null,
) {
  ensureTraceModal();

  traceModalL1StreamId =
    null;

  traceModalL1StreamStatus =
    null;

  traceModalL1StreamReasoning =
    null;

  traceModalL1StreamAnswer =
    null;

  if (traceModalL1StreamFrame !== null) {
    cancelAnimationFrame(
      traceModalL1StreamFrame
    );

    traceModalL1StreamFrame =
      null;
  }

  traceModalTitle.textContent =
    title;

  if (reason) {
    traceModalReason.textContent =
      `Reason: ${reason}`;

    traceModalReason.classList.remove(
      "hidden"
    );
  } else {
    traceModalReason.textContent =
      "";

    traceModalReason.classList.add(
      "hidden"
    );
  }

  renderTraceDetails(
    details,
    title
  );

  traceModal.classList.remove(
    "hidden"
  );

  traceModal.classList.add(
    "flex"
  );
}



window.showTrace =
  showTrace;
