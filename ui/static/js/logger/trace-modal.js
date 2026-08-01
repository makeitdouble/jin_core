let traceModal;
let traceModalContent;
let traceModalReason;
let traceModalTitle;
let traceModalL1StreamId = null;
let traceModalL1StreamStatus = null;
let traceModalL1StreamReasoning = null;
let traceModalL1StreamAnswer = null;
let traceModalL1StreamFrame = null;

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

  const closeButton =
    document.createElement("button");

  closeButton.type =
    "button";

  closeButton.className =
    "text-xs text-zinc-400 hover:text-zinc-100 transition";

  closeButton.textContent =
    "close";

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

  header.appendChild(
    closeButton
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
        closeTraceModal();
      }
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

function renderTraceDetails(
  details,
  title = "Trace",
) {
  traceModalContent.replaceChildren();

  const parsed =
    parseTraceJson(details);

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
