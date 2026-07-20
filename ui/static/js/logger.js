const consoleStream =
  document.getElementById("console-stream");

let traceModal;
let traceModalContent;
let traceModalReason;
let traceModalTitle;
let traceModalL1StreamId = null;
let traceModalL1StreamStatus = null;
let traceModalL1StreamReasoning = null;
let traceModalL1StreamAnswer = null;
let traceModalL1StreamFrame = null;

const l1SummarizerStreams =
  new Map();

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

function parseTraceJson(details) {
  try {
    return JSON.parse(
      String(details || "")
    );
  } catch (_error) {
    return null;
  }
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


function getL1SummarizerStreamState(
  streamId,
) {
  if (!l1SummarizerStreams.has(streamId)) {
    l1SummarizerStreams.set(
      streamId,
      {
        id: streamId,
        title: "L1 summarizer stream",
        status: "waiting",
        reasoning: "",
        answer: "",
        logDiv: null,
        button: null,
      }
    );
  }

  return l1SummarizerStreams.get(
    streamId
  );
}

function appendL1SummarizerStreamSection(
  parent,
  title,
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

  section.appendChild(
    heading
  );

  section.appendChild(
    body
  );

  parent.appendChild(
    section
  );

  return body;
}

function updateL1SummarizerStreamText(
  element,
  text,
  placeholder,
) {
  if (!element) {
    return;
  }

  const stickToBottom =
    element.scrollHeight
    - element.scrollTop
    - element.clientHeight
    < 32;

  element.textContent =
    text || placeholder;

  if (stickToBottom) {
    element.scrollTop =
      element.scrollHeight;
  }
}

function refreshL1SummarizerStreamModal(
  streamId,
) {
  if (
      traceModalL1StreamId !== streamId
      || !l1SummarizerStreams.has(streamId)
  ) {
    return;
  }

  const state =
    l1SummarizerStreams.get(streamId);

  updateL1SummarizerStreamText(
    traceModalL1StreamStatus,
    state.status,
    "waiting"
  );

  updateL1SummarizerStreamText(
    traceModalL1StreamReasoning,
    state.reasoning,
    "<waiting for reasoning>"
  );

  updateL1SummarizerStreamText(
    traceModalL1StreamAnswer,
    state.answer,
    "<waiting for answer>"
  );
}

function scheduleL1SummarizerStreamModalRefresh(
  streamId,
) {
  if (traceModalL1StreamId !== streamId) {
    return;
  }

  if (traceModalL1StreamFrame !== null) {
    return;
  }

  traceModalL1StreamFrame =
    requestAnimationFrame(
      function () {
        traceModalL1StreamFrame =
          null;

        refreshL1SummarizerStreamModal(
          streamId
        );
      }
    );
}

function showL1SummarizerStream(
  streamId,
) {
  ensureTraceModal();

  const state =
    getL1SummarizerStreamState(
      streamId
    );

  if (traceModalL1StreamFrame !== null) {
    cancelAnimationFrame(
      traceModalL1StreamFrame
    );

    traceModalL1StreamFrame =
      null;
  }

  traceModalL1StreamId =
    streamId;

  traceModalTitle.textContent =
    state.title;

  traceModalReason.textContent =
    "";

  traceModalReason.classList.add(
    "hidden"
  );

  traceModalContent.replaceChildren();

  traceModalL1StreamStatus =
    appendL1SummarizerStreamSection(
      traceModalContent,
      "Status"
    );

  traceModalL1StreamReasoning =
    appendL1SummarizerStreamSection(
      traceModalContent,
      "Reasoning content"
    );

  traceModalL1StreamAnswer =
    appendL1SummarizerStreamSection(
      traceModalContent,
      "Assistant content"
    );

  refreshL1SummarizerStreamModal(
    streamId
  );

  traceModal.classList.remove(
    "hidden"
  );

  traceModal.classList.add(
    "flex"
  );
}

function ensureL1SummarizerStreamButton(
  state,
) {
  if (
      state.button
      || !state.logDiv
  ) {
    return;
  }

  const payloadButton =
    Array.from(
      state.logDiv.querySelectorAll("button")
    ).find((button) => (
      button.textContent.trim().toLowerCase() === "payload"
    ));

  let actions =
    payloadButton
      ? payloadButton.parentElement
      : null;

  if (!actions) {
    actions =
      document.createElement("div");

    actions.className =
      "mt-2 flex flex-wrap items-center gap-2";

    state.logDiv.appendChild(
      actions
    );
  }

  const streamButton =
    document.createElement("button");

  streamButton.type =
    "button";

  streamButton.className =
    "mt-2 inline-flex items-center rounded border border-blue-500/20 px-2 py-1 text-[10px] uppercase tracking-wider text-blue-300 hover:bg-blue-500/10 transition";

  streamButton.textContent =
    "stream";

  streamButton.addEventListener(
    "click",
    function () {
      showL1SummarizerStream(
        state.id
      );
    }
  );

  actions.appendChild(
    streamButton
  );

  state.button =
    streamButton;
}

function registerL1SummarizerRequest(
  logDiv,
  message,
  meta,
) {
  const streamId =
    String(
      meta?.summarizer_stream_id
      || ""
    );

  if (
      !streamId
      || String(meta?.memory_level || "").toUpperCase() !== "L1"
      || String(meta?.memory_event || "") !== "summarizer_request"
  ) {
    return;
  }

  const state =
    getL1SummarizerStreamState(
      streamId
    );

  state.logDiv =
    logDiv;

  state.title =
    String(message || "L1 summarizer stream")
    .replace(/request$/i, "stream");

  if (state.status !== "waiting") {
    ensureL1SummarizerStreamButton(
      state
    );
  }
}

function handleL1SummarizerStreamEvent(
  meta,
) {
  const event =
    String(
      meta?.memory_event
      || ""
    );

  const streamId =
    String(
      meta?.summarizer_stream_id
      || ""
    );

  if (
      !streamId
      || String(meta?.memory_level || "").toUpperCase() !== "L1"
      || !event.startsWith("summarizer_stream_")
  ) {
    return false;
  }

  const state =
    getL1SummarizerStreamState(
      streamId
    );

  if (event === "summarizer_stream_start") {
    state.status =
      "streaming";
  } else if (event === "summarizer_stream_chunk") {
    const chunk =
      String(
        meta?.summarizer_stream_chunk
        || ""
      );

    if (meta?.summarizer_stream_kind === "thinking") {
      state.reasoning +=
        chunk;
    } else if (meta?.summarizer_stream_kind === "content") {
      state.answer +=
        chunk;
    }

    state.status =
      "streaming";
  } else if (event === "summarizer_stream_end") {
    state.status =
      "complete";
  } else if (event === "summarizer_stream_error") {
    state.status =
      "failed";
  }

  ensureL1SummarizerStreamButton(
    state
  );

  scheduleL1SummarizerStreamModalRefresh(
    streamId
  );

  return true;
}

function prettifyTraceDetails(details) {
  const text =
    String(details || "");

  if (!text.trim()) {
    return "";
  }

  try {
    return JSON.stringify(
      JSON.parse(text),
      null,
      2
    );
  } catch (_error) {
    return text;
  }
}

function extractTraceReason(
  message,
  details,
) {
  const text =
    String(
      details
      || message
      || ""
    );

  if (!text.trim()) {
    return "";
  }

  const likelyReasonMatch =
    text.match(
      /^Likely reason:\s*(.+)$/m
    );

  if (likelyReasonMatch) {
    return likelyReasonMatch[1].trim();
  }

  const httpStatusMatch =
    text.match(
      /HTTPStatusError:\s*(.+?)(?:\r?\n|$)/
    );

  if (httpStatusMatch) {
    return httpStatusMatch[1]
      .replace(
        /\s+for url '([^']+)'/,
        function (_match, url) {
          return ` for ${summarizeTraceUrl(url)}`;
        }
      )
      .trim();
  }

  const errorLines =
    Array.from(
      text.matchAll(
        /^([A-Za-z_][\w.]*Error|Exception):\s*(.+)$/gm
      )
    );

  if (errorLines.length) {
    const match =
      errorLines[errorLines.length - 1];

    return `${match[1]}: ${match[2]}`.trim();
  }

  const nonEmptyLines =
    text
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);

  return (
    nonEmptyLines[nonEmptyLines.length - 1]
    || ""
  );
}

function summarizeTraceUrl(url) {
  try {
    const parsed =
      new URL(url);

    return `${parsed.host}${parsed.pathname}`;
  } catch (_error) {
    return url;
  }
}

function splitInlineTrace(
  message,
  details,
) {
  if (details) {
    return {
      message,
      details,
    };
  }

  const text =
    String(message ?? "");

  const traceStart =
    text.indexOf(
      "Traceback (most recent call last):"
    );

  if (traceStart === -1) {
    return {
      message: text,
      details: null,
    };
  }

  const summary =
    text.slice(
      0,
      traceStart,
    ).trim()
    || "Traceback captured.";

  return {
    message: summary,
    details: text.slice(
      traceStart
    ),
  };
}

function parseValidatorLogPayload(
  message,
  details,
) {
  const payloadLines = [];
  const visibleLines = [];

  String(message || "")
    .split(/\r?\n/)
    .forEach((line) => {
      const payloadMatch =
        line.match(
          /^(Preview|Raw chunk|Safe chunk):\s*"([\s\S]*)"$/
        );

      if (payloadMatch) {
        payloadLines.push(
          `${payloadMatch[1]}:\n${payloadMatch[2]}`
        );
        return;
      }

      if (
          line.trim()
          && line.trim() !== "Payload available."
      ) {
        visibleLines.push(
          line
        );
      }
    });

  const explicitDetails =
    details !== null
    && details !== undefined
    && String(details).trim()
      ? String(details)
      : "";

  return {
    message: visibleLines.join("\n").trim(),
    payload: explicitDetails || payloadLines.join("\n\n").trim(),
  };
}

const SESSION_ACTIONS_PREVIEW_LIMIT = 5;

const sessionActionsLogState = {
  mode: "",
  sequenceId: "",
  items: [],
  signature: "",
  logDiv: null,
  tagSpan: null,
  list: null,
  actions: null,
  fullButton: null,
};

let sessionActionsModal = null;
let sessionActionsModalTitle = null;
let sessionActionsModalList = null;
let sessionActionsModalMode = "";
let sessionActionsModalSequenceId = "";
let sessionActionsModalItems = [];
let sessionActionsAgeTimer = null;
const pendingCancelledSessionActions = [];
const cancelledSessionActionPartKeys = new Set();

function normalizeSessionActionName(value) {
  return String(value || "")
    .trim()
    .toUpperCase();
}

function normalizeSessionActionColor(value) {
  const match = String(value || "")
    .trim()
    .match(/^#?([0-9a-f]{3}|[0-9a-f]{6})$/i);

  if (!match) {
    return "";
  }

  let hex = match[1].toLowerCase();

  if (hex.length === 3) {
    hex = hex
      .split("")
      .map((char) => char + char)
      .join("");
  }

  return `#${hex}`;
}

function buildSessionActionPartKey(
  item,
  part,
  partIndex,
) {
  return [
    String(item.createdAt || 0),
    String(partIndex),
    normalizeSessionActionName(part.text),
    (part.colors || []).join(","),
  ].join("|");
}

function sessionActionPartMatchesCancellation(
  part,
  cancellation,
) {
  const normalizedText =
    normalizeSessionActionName(part.text);
  const actionName =
    cancellation.actionName;

  if (
    normalizedText !== actionName
    && !normalizedText.startsWith(`${actionName} `)
    && !normalizedText.startsWith(`${actionName}:`)
  ) {
    return false;
  }

  return (
    !cancellation.color
    || (part.colors || []).includes(
      cancellation.color
    )
  );
}

function applyCancelledSessionActions(
  items,
) {
  items.forEach((item) => {
    item.parts.forEach((part, partIndex) => {
      const partKey =
        buildSessionActionPartKey(
          item,
          part,
          partIndex
        );

      if (part.cancelled) {
        cancelledSessionActionPartKeys.add(
          partKey
        );
      } else if (
        cancelledSessionActionPartKeys.has(
          partKey
        )
      ) {
        part.cancelled = true;
      }
    });
  });

  while (pendingCancelledSessionActions.length) {
    const cancellation =
      pendingCancelledSessionActions[0];
    let matched = false;

    for (
      let itemIndex = items.length - 1;
      itemIndex >= 0 && !matched;
      itemIndex -= 1
    ) {
      const item = items[itemIndex];

      if (
        item.createdAt
        && item.createdAt < cancellation.createdAfter
      ) {
        continue;
      }

      for (
        let partIndex = item.parts.length - 1;
        partIndex >= 0;
        partIndex -= 1
      ) {
        const part = item.parts[partIndex];

        if (
          !sessionActionPartMatchesCancellation(
            part,
            cancellation
          )
        ) {
          continue;
        }

        if (!part.cancelled) {
          part.cancelled = true;
          cancelledSessionActionPartKeys.add(
            buildSessionActionPartKey(
              item,
              part,
              partIndex
            )
          );
        }

        matched = true;
        break;
      }
    }

    if (!matched) {
      break;
    }

    pendingCancelledSessionActions.shift();
  }

  return items;
}

function normalizeSessionActionParts(
  parts,
  fallbackText,
) {
  const normalizedParts = Array.isArray(parts)
    ? parts
        .map((part) => {
          if (!part || typeof part !== "object") {
            return null;
          }

          const text =
            String(part.text || "").trim();

          if (!text) {
            return null;
          }

          const detail =
            String(part.detail || "").trim();

          const colors = Array.isArray(part.colors)
            ? part.colors
                .map((color) =>
                  String(color || "").trim().toLowerCase()
                )
                .filter((color, index, array) => (
                  /^#[0-9a-f]{6}$/.test(color)
                  && array.indexOf(color) === index
                ))
            : [];

          return {
            text,
            detail,
            colors,
            cancelled:
              Boolean(part.cancelled),
          };
        })
        .filter(Boolean)
    : [];

  if (normalizedParts.length) {
    return normalizedParts;
  }

  const text =
    String(fallbackText || "").trim();

  if (!text) {
    return [];
  }

  const detailSeparator =
    " - ";

  const detailSeparatorIndex =
    text.indexOf(
      detailSeparator
    );

  if (detailSeparatorIndex < 0) {
    return [{
      text,
      detail: "",
      colors: [],
      cancelled: false,
    }];
  }

  const visibleText =
    text.slice(
      0,
      detailSeparatorIndex
    ).trim();

  const detail =
    text.slice(
      detailSeparatorIndex
      + detailSeparator.length
    ).trim();

  return [{
    text: visibleText || text,
    detail: visibleText ? detail : "",
    colors: [],
    cancelled: false,
  }];
}

function normalizeSessionActionItems(
  items,
) {
  if (!Array.isArray(items)) {
    return [];
  }

  const normalizedItems = items
    .map((item) => {
      if (!item || typeof item !== "object") {
        return null;
      }

      const text =
        String(item.text || "").trim();

      if (!text) {
        return null;
      }

      const createdAt =
        Number(item.created_at || 0);

      return {
        text,
        parts: normalizeSessionActionParts(
          item.parts,
          text
        ),
        createdAt:
          Number.isFinite(createdAt)
            ? createdAt
            : 0,
      };
    })
    .filter(Boolean);

  return applyCancelledSessionActions(
    normalizedItems
  );
}

function formatSessionActionAge(
  createdAt,
) {
  const timestamp =
    Number(createdAt || 0);

  if (!Number.isFinite(timestamp) || timestamp <= 0) {
    return "now";
  }

  const seconds = Math.max(
    0,
    Math.floor(
      (Date.now() / 1000) - timestamp
    )
  );

  if (seconds < 60) {
    return `${seconds}s ago`;
  }

  const minutes =
    Math.floor(seconds / 60);

  if (minutes < 60) {
    return `${minutes}m ago`;
  }

  const hours =
    Math.floor(minutes / 60);

  return `${hours}h ago`;
}

function refreshSessionActionAges() {
  document
    .querySelectorAll("[data-session-action-created-at]")
    .forEach((node) => {
      node.textContent =
        formatSessionActionAge(
          node.dataset.sessionActionCreatedAt
        );
    });
}

function ensureSessionActionsAgeTimer() {
  if (sessionActionsAgeTimer !== null) {
    return;
  }

  sessionActionsAgeTimer =
    window.setInterval(
      refreshSessionActionAges,
      1000
    );
}

function buildSessionActionColorSwatches(
  colors,
) {
  const swatches =
    document.createElement("span");

  swatches.className =
    "inline-flex items-center gap-1 align-middle";

  colors.forEach((color) => {
    const swatch =
      document.createElement("span");

    swatch.textContent =
      "■";

    swatch.style.color =
      color;

    swatch.title =
      color;

    swatches.appendChild(
      swatch
    );
  });

  return swatches;
}


function buildSessionActionRow(
  item,
  index,
) {
  const row =
    document.createElement("div");

  row.className =
    "min-w-0 whitespace-pre-wrap break-words";

  row.style.overflowWrap =
    "anywhere";

  const prefix =
    document.createElement("span");

  prefix.textContent =
    `${index + 1}. `;

  row.appendChild(
    prefix
  );

  const parts =
    normalizeSessionActionParts(
      item.parts,
      item.text
    );

  parts.forEach((part, partIndex) => {
    const action =
      document.createElement("span");

    action.className =
      "inline-flex items-center gap-1";

    if (part.colors.length) {
      action.appendChild(
        buildSessionActionColorSwatches(
          part.colors
        )
      );
    }

    const actionName =
      document.createElement("span");

    actionName.textContent =
      part.text;

    if (part.cancelled) {
      actionName.classList.add(
        "line-through",
        "decoration-1",
        "opacity-60"
      );
    }

    action.appendChild(
      actionName
    );

    if (part.detail) {
      action.title =
        part.detail;

      action.className =
        "cursor-help";
    }

    row.appendChild(
      action
    );

    if (partIndex < parts.length - 1) {
      row.appendChild(
        document.createTextNode(", ")
      );
    }
  });

  row.appendChild(
    document.createTextNode(" (")
  );

  const age =
    document.createElement("span");

  age.dataset.sessionActionCreatedAt =
    String(item.createdAt || 0);

  age.textContent =
    formatSessionActionAge(
      item.createdAt
    );

  row.appendChild(
    age
  );

  row.appendChild(
    document.createTextNode(")")
  );

  return row;
}


function getSessionActionsTitle(
  mode,
) {
  return mode === "sequence"
    ? "[ SEQUENCE ]"
    : "[ SESSION ACTIONS ]";
}

function ensureSessionActionsModal() {
  if (sessionActionsModal) {
    return;
  }

  sessionActionsModal =
    document.createElement("div");

  sessionActionsModal.className =
    "fixed inset-0 z-50 hidden items-center justify-center bg-black/70 p-4";

  const panel =
    document.createElement("div");

  panel.className =
    "w-full max-w-3xl max-h-[86vh] rounded border border-zinc-700 bg-zinc-950 shadow-2xl flex flex-col";

  const header =
    document.createElement("div");

  header.className =
    "h-11 shrink-0 border-b border-zinc-800 px-4 flex items-center justify-between";

  sessionActionsModalTitle =
    document.createElement("div");

  sessionActionsModalTitle.className =
    "font-mono text-xs font-bold text-zinc-300";

  const closeButton =
    document.createElement("button");

  closeButton.type =
    "button";

  closeButton.className =
    "text-xs text-zinc-400 hover:text-zinc-100 transition";

  closeButton.textContent =
    "close";

  sessionActionsModalList =
    document.createElement("div");

  sessionActionsModalList.className =
    "min-h-0 flex-1 overflow-auto p-4 font-mono text-[12px] leading-relaxed text-zinc-300 space-y-1";

  header.appendChild(
    sessionActionsModalTitle
  );

  header.appendChild(
    closeButton
  );

  panel.appendChild(
    header
  );

  panel.appendChild(
    sessionActionsModalList
  );

  sessionActionsModal.appendChild(
    panel
  );

  document.body.appendChild(
    sessionActionsModal
  );

  function closeSessionActionsModal() {
    sessionActionsModal.classList.add(
      "hidden"
    );

    sessionActionsModal.classList.remove(
      "flex"
    );
  }

  closeButton.addEventListener(
    "click",
    closeSessionActionsModal
  );

  sessionActionsModal.addEventListener(
    "click",
    function (event) {
      if (event.target === sessionActionsModal) {
        closeSessionActionsModal();
      }
    }
  );

  document.addEventListener(
    "keydown",
    function (event) {
      if (
        event.key === "Escape"
        && !sessionActionsModal.classList.contains("hidden")
      ) {
        closeSessionActionsModal();
      }
    }
  );
}

function sessionActionItemMatches(
  left,
  right,
) {
  return Boolean(
    left
    && right
    && left.text === right.text
    && left.createdAt === right.createdAt
    && JSON.stringify(left.parts)
      === JSON.stringify(right.parts)
  );
}

function syncSessionActionsModal(
  mode,
  sequenceId,
  items,
) {
  if (!sessionActionsModal) {
    return;
  }

  sessionActionsModalTitle.textContent =
    getSessionActionsTitle(
      mode
    );

  const sameStream = (
    sessionActionsModalMode === mode
    && sessionActionsModalSequenceId === sequenceId
  );

  const canAppend = (
    sameStream
    && sessionActionsModalItems.length <= items.length
    && sessionActionsModalItems.every(
      (item, index) => sessionActionItemMatches(
        item,
        items[index]
      )
    )
  );

  if (!canAppend) {
    sessionActionsModalList.replaceChildren();
    sessionActionsModalItems = [];
  }

  for (
    let index = sessionActionsModalItems.length;
    index < items.length;
    index += 1
  ) {
    sessionActionsModalList.appendChild(
      buildSessionActionRow(
        items[index],
        index
      )
    );
  }

  sessionActionsModalMode =
    mode;

  sessionActionsModalSequenceId =
    sequenceId;

  sessionActionsModalItems =
    items.map((item) => ({
      ...item,
      parts: item.parts.map((part) => ({
        ...part,
      })),
    }));

  sessionActionsModalList.scrollTop =
    sessionActionsModalList.scrollHeight;
}

function showSessionActionsModal() {
  ensureSessionActionsModal();

  syncSessionActionsModal(
    sessionActionsLogState.mode,
    sessionActionsLogState.sequenceId,
    sessionActionsLogState.items
  );

  sessionActionsModal.classList.remove(
    "hidden"
  );

  sessionActionsModal.classList.add(
    "flex"
  );
}

function ensureSessionActionsLog() {
  if (sessionActionsLogState.logDiv) {
    return sessionActionsLogState.logDiv;
  }

  const logDiv =
    document.createElement("div");

  logDiv.className =
    "mb-1 min-w-0 whitespace-pre-wrap break-words font-mono text-[12px] bg-zinc-500/5 p-2 rounded border border-zinc-500/10";

  logDiv.style.overflowWrap =
    "anywhere";

  logDiv.dataset.logKind =
    "session-actions";

  const tagSpan =
    document.createElement("span");

  tagSpan.className =
    "text-zinc-300 font-bold logger-tag block";

  const list =
    document.createElement("div");

  list.className =
    "mt-1 text-zinc-400 space-y-1";

  const actions =
    document.createElement("div");

  actions.className =
    "mt-2 flex flex-wrap items-center gap-2 hidden";

  const fullButton =
    document.createElement("button");

  fullButton.type =
    "button";

  fullButton.className =
    "inline-flex items-center rounded border border-zinc-600/40 px-2 py-1 text-[10px] uppercase tracking-wider text-zinc-300 hover:bg-zinc-700/40 transition";

  fullButton.textContent =
    "full";

  fullButton.addEventListener(
    "click",
    showSessionActionsModal
  );

  actions.appendChild(
    fullButton
  );

  logDiv.appendChild(
    tagSpan
  );

  logDiv.appendChild(
    list
  );

  logDiv.appendChild(
    actions
  );

  sessionActionsLogState.logDiv =
    logDiv;

  sessionActionsLogState.tagSpan =
    tagSpan;

  sessionActionsLogState.list =
    list;

  sessionActionsLogState.actions =
    actions;

  sessionActionsLogState.fullButton =
    fullButton;

  return logDiv;
}

function updateSessionActionsLog(
  payload = {},
) {
  const mode =
    String(payload.mode || "").toLowerCase() === "sequence"
      ? "sequence"
      : "session_actions";

  const sequenceId =
    String(payload.sequence_id || "");

  const items =
    normalizeSessionActionItems(
      payload.items
    );

  if (!items.length) {
    return;
  }

  const signature =
    JSON.stringify({
      mode,
      sequenceId,
      items,
    });

  if (signature === sessionActionsLogState.signature) {
    return;
  }

  const logDiv =
    ensureSessionActionsLog();

  const wasConnected =
    logDiv.isConnected;

  sessionActionsLogState.mode =
    mode;

  sessionActionsLogState.sequenceId =
    sequenceId;

  sessionActionsLogState.items =
    items;

  sessionActionsLogState.signature =
    signature;

  sessionActionsLogState.tagSpan.textContent =
    getSessionActionsTitle(
      mode
    );

  const previewStartIndex =
    Math.max(
      0,
      items.length - SESSION_ACTIONS_PREVIEW_LIMIT
    );

  sessionActionsLogState.list.replaceChildren(
    ...items
      .slice(
        previewStartIndex
      )
      .map(
        (item, index) => buildSessionActionRow(
          item,
          previewStartIndex + index
        )
      )
  );

  sessionActionsLogState.actions.classList.toggle(
    "hidden",
    items.length <= SESSION_ACTIONS_PREVIEW_LIMIT
  );

  if (wasConnected) {
    moveLogToBottomWithFlip(
      logDiv
    );
  } else {
    consoleStream.appendChild(
      logDiv
    );
  }

  syncSessionActionsModal(
    mode,
    sequenceId,
    items
  );

  ensureSessionActionsAgeTimer();
  refreshSessionActionAges();

  consoleStream.scrollTop =
    consoleStream.scrollHeight;
}

window.updateSessionActionsLog =
  updateSessionActionsLog;

function markSessionActionCancelled(
  actionName,
  color = "",
) {
  const normalizedName =
    normalizeSessionActionName(
      actionName
    );

  if (!normalizedName) {
    return;
  }

  pendingCancelledSessionActions.push({
    actionName: normalizedName,
    color: normalizeSessionActionColor(
      color
    ),
    createdAfter:
      (Date.now() / 1000) - 2,
  });

  if (!sessionActionsLogState.items.length) {
    return;
  }

  const payloadItems =
    sessionActionsLogState.items.map((item) => ({
      text: item.text,
      created_at: item.createdAt,
      parts: item.parts.map((part) => ({
        text: part.text,
        detail: part.detail,
        colors: part.colors,
        cancelled: part.cancelled,
      })),
    }));

  sessionActionsLogState.signature =
    "";

  updateSessionActionsLog({
    mode: sessionActionsLogState.mode,
    sequence_id: sessionActionsLogState.sequenceId,
    items: payloadItems,
  });
}

window.markSessionActionCancelled =
  markSessionActionCancelled;

function findLiveFlowLog(
  flowId,
) {
  if (!flowId) {
    return null;
  }

  return consoleStream.querySelector(
    `[data-flow-id="${CSS.escape(flowId)}"]`
  );
}

function moveLogToBottomWithFlip(
  logDiv,
) {
  const firstRect =
    logDiv.getBoundingClientRect();

  consoleStream.appendChild(
    logDiv
  );

  const lastRect =
    logDiv.getBoundingClientRect();

  const deltaY =
    firstRect.top - lastRect.top;

  if (!deltaY) {
    return;
  }

  logDiv.style.transform =
    `translateY(${deltaY}px)`;

  logDiv.style.transition =
    "transform 0s";

  requestAnimationFrame(
    function () {
      logDiv.style.transition =
        "transform 180ms ease-out";

      logDiv.style.transform =
        "translateY(0)";
    }
  );
}

function dismissLogAfterClear(
  logDiv,
) {

  window.setTimeout(
    function () {
      const height =
        logDiv.offsetHeight;

      logDiv.style.maxHeight =
        `${height}px`;

      logDiv.style.overflow =
        "hidden";

      logDiv.style.transition =
        "opacity 160ms ease, transform 160ms ease, max-height 180ms ease, margin 180ms ease, padding 180ms ease";

      requestAnimationFrame(
        function () {
          logDiv.style.opacity =
            "0";
          logDiv.style.transform =
            "translateY(-4px)";
          logDiv.style.maxHeight =
            "0";
          logDiv.style.marginTop =
            "0";
          logDiv.style.marginBottom =
            "0";
          logDiv.style.paddingTop =
            "0";
          logDiv.style.paddingBottom =
            "0";
        }
      );

      window.setTimeout(
        function () {
          logDiv.remove();
        },
        190
      );
    },
    450
  );

}


function normalizeInternalActionName(action) {
  return String(
    action || ""
  )
    .trim()
    .replace(/^INTERNAL_ACTION_/i, "")
    .replace(/^CAN_/i, "")
    .replace(/[^a-z0-9]+/gi, "_")
    .replace(/^_+|_+$/g, "")
    .toUpperCase();
}

function prettifyInternalActionName(action) {
  return normalizeInternalActionName(
    action
  )
    .replace(/_/g, " ")
    .trim();
}

function getInternalActionPayload(data) {
  if (!data) {
    return null;
  }

  const payloadKeys = [
    "payload",
    "action_payload",
    "runtime_action_payload",
    "asset_result",
    "skill_result",
    "runtime_todo_result",
    "delayed_memory_report",
    "details",
  ];

  for (const key of payloadKeys) {
    const value =
      data[key];

    if (value !== undefined && value !== null && value !== "") {
      return value;
    }
  }

  return null;
}

function formatInternalActionPayload(payload) {
  if (typeof payload === "string") {
    return prettifyTraceDetails(
      payload
    );
  }

  try {
    return JSON.stringify(
      payload,
      null,
      2
    );
  } catch (_error) {
    return String(
      payload
    );
  }
}

function formatUserPayloadValue(
  value,
  depth = 0,
) {
  if (Array.isArray(value)) {
    if (!value.length) {
      return "[]";
    }

    return value
      .map((item, index) => {
        return (
          `${"  ".repeat(depth)}${index + 1}. `
          + formatUserPayloadValue(
            item,
            depth + 1,
          )
        );
      })
      .join("\n");
  }

  if (
      value
      && typeof value === "object"
  ) {
    return formatUserPayload(
      value,
      depth + 1,
    );
  }

  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }

  if (
      value === null
      || value === undefined
  ) {
    return "";
  }

  return String(value);
}

function formatUserPayload(
  payload,
  depth = 0,
) {
  const data =
    payload && typeof payload === "object"
      ? payload
      : {
          text: String(payload || ""),
        };

  const lines = [];

  Object.keys(data).forEach((key) => {
    const value =
      formatUserPayloadValue(
        data[key],
        depth,
      );

    lines.push(
      `${key}: ${value || "<empty>"}`
    );
  });

  return lines.join("\n");
}

function summarizeAttachmentsForPayloadTrace(
  attachments,
) {
  if (!Array.isArray(attachments)) {
    return [];
  }

  return attachments.map((attachment, index) => {
    if (
        !attachment
        || typeof attachment !== "object"
    ) {
      return {
        index: index + 1,
        value: String(attachment || ""),
      };
    }

    return {
      index: index + 1,
      kind: attachment.kind || "",
      name: attachment.name || attachment.filename || "",
      type: attachment.type || attachment.mime_type || "",
      redacted: Boolean(
        attachment.data_url
        || attachment.text_content
      ),
    };
  });
}

function buildUserPayloadContextTrace(
  payload,
) {
  const data =
    payload && typeof payload === "object"
      ? payload
      : {
          text: String(payload || ""),
        };

  const contextFields = {};

  [
    "runtime_pattern_counter",
    "runtime_repeated_input_count",
    "user_idle",
    "user_idle_seconds",
    "user_idle_paused",
    "pending_last_response_rating",
  ].forEach((key) => {
    if (
        data[key] !== undefined
        && data[key] !== null
        && data[key] !== ""
    ) {
      contextFields[key] = data[key];
    }
  });

  if (Array.isArray(data.active_memory_records)) {
    contextFields.active_memory_records =
      data.active_memory_records;
  }

  if (Array.isArray(data.attachments)) {
    contextFields.attachments =
      summarizeAttachmentsForPayloadTrace(
        data.attachments
      );
  }

  return {
    prompt_to_jin: String(data.text || ""),
    context_fields: contextFields,
  };
}

function buildUserPayloadTrace(
  payload,
) {
  const data =
    payload && typeof payload === "object"
      ? payload
      : {
          text: String(payload || ""),
        };

  return {
    kind: "user_payload_trace",
    context: buildUserPayloadContextTrace(
      data
    ),
  };
}

function formatUserPayloadTrace(
  payload,
) {
  return JSON.stringify(
    buildUserPayloadTrace(
      payload
    ),
    null,
    2
  );
}

function renderUserPayloadTrace(
  parsed,
) {
  const context =
    parsed.context || {};

  appendTraceModalBody(
    traceModalContent,
    "Prompt to JIN",
    context.prompt_to_jin || ""
  );

  appendTraceModalBody(
    traceModalContent,
    "Context fields sent with this turn",
    context.context_fields || {}
  );
}

function log_user(
  payload = {}
) {
  const text =
    String(
      payload && payload.text
        ? payload.text
        : ""
    ).trim();

  const logDiv =
    document.createElement("div");

  logDiv.className =
    "mb-1 min-w-0 whitespace-pre-wrap break-words font-mono text-[12px] bg-sky-500/5 p-2 rounded border border-sky-500/10";

  logDiv.dataset.logKind =
    "user";

  logDiv.style.overflowWrap =
    "anywhere";

  const tagSpan =
    document.createElement("span");

  tagSpan.className =
    "text-sky-300 font-bold logger-tag block";

  tagSpan.textContent =
    "[USER]";

  logDiv.appendChild(
    tagSpan
  );

  if (text) {
    const messageSpan =
      document.createElement("span");

    messageSpan.className =
      "block mt-1 text-sky-100/70";

    messageSpan.textContent =
      text;

    logDiv.appendChild(
      messageSpan
    );
  }

  const actions =
    document.createElement("div");

  actions.className =
    "mt-2 flex flex-wrap items-center gap-2";

  const payloadButton =
    document.createElement("button");

  payloadButton.type =
    "button";

  payloadButton.className =
    "inline-flex items-center rounded border border-sky-500/20 px-2 py-1 text-[10px] uppercase tracking-wider text-sky-300 hover:bg-sky-500/10 transition";

  payloadButton.textContent =
    "payload";

  payloadButton.addEventListener(
    "click",
    function () {
      showTrace(
        formatUserPayloadTrace(
          payload
        ),
        "User payload"
      );
    }
  );

  actions.appendChild(
    payloadButton
  );

  logDiv.appendChild(
    actions
  );

  consoleStream.appendChild(
    logDiv
  );

  consoleStream.scrollTop =
    consoleStream.scrollHeight;
}

function log_internal_action(
  action,
  data = {}
) {
  const actionName =
    normalizeInternalActionName(
      action
    );

  if (!actionName || actionName === "SAVE_SESSION" || actionName === "SAVE_SESSION") {
    return;
  }

  const title =
    `[ ACTION : ${prettifyInternalActionName(actionName)} ]`;

  const text =
    String(
      data.text || data.query || ""
    ).trim();

  const payload =
    getInternalActionPayload(
      data
    );

  const cancelledByUser =
    String(data.status || "").toLowerCase() === "failed"
    && Boolean(
      data.confirmation_id
      || data.guard_confirmation_id
    )
    && /\bcancelled\s*$/i.test(text);

  const logDiv =
    document.createElement("div");

  logDiv.className =
    "mb-1 min-w-0 whitespace-pre-wrap break-words font-mono text-[12px] bg-emerald-500/5 p-2 rounded border border-emerald-500/10";

  logDiv.dataset.logKind =
    "action";

  logDiv.style.overflowWrap =
    "anywhere";

  const tagSpan =
    document.createElement("span");

  tagSpan.className =
    "text-emerald-300 font-bold logger-tag block";

  tagSpan.textContent =
    title;

  if (cancelledByUser) {
    tagSpan.classList.add(
      "line-through",
      "opacity-60"
    );
  }

  logDiv.appendChild(
    tagSpan
  );

  if (text) {
    const messageSpan =
      document.createElement("span");

    messageSpan.className =
      "block mt-1 text-emerald-100/70";

    messageSpan.style.overflowWrap =
      "anywhere";

    messageSpan.textContent =
      text;

    if (cancelledByUser) {
      messageSpan.classList.add(
        "line-through",
        "opacity-60"
      );
    }

    logDiv.appendChild(
      messageSpan
    );
  }

  if (payload !== null) {
    const actions =
      document.createElement("div");

    actions.className =
      "mt-2 flex flex-wrap items-center gap-2";

    const payloadButton =
      document.createElement("button");

    payloadButton.type =
      "button";

    payloadButton.className =
      "inline-flex items-center rounded border border-emerald-500/20 px-2 py-1 text-[10px] uppercase tracking-wider text-emerald-300 hover:bg-emerald-500/10 transition";

    payloadButton.textContent =
      "payload";

    payloadButton.addEventListener(
      "click",
      function () {
        showTrace(
          formatInternalActionPayload(
            payload
          ),
          title
        );
      }
    );

    actions.appendChild(
      payloadButton
    );

    logDiv.appendChild(
      actions
    );
  }

  consoleStream.appendChild(
    logDiv
  );

  consoleStream.scrollTop =
    consoleStream.scrollHeight;
}

function appendLog(
  tag,
  message,
  details = null,
  meta = {},
) {
  if (handleL1SummarizerStreamEvent(meta)) {
    return null;
  }

  const normalized =
    splitInlineTrace(
      message,
      details,
    );

  const flowId =
    meta?.flow_id;

  const existingFlowLog =
    tag === "[FLOW]"
      ? findLiveFlowLog(
          flowId
        )
      : null;

  const logDiv =
    existingFlowLog
    || document.createElement("div");

  logDiv.className =
    "mb-1 min-w-0 whitespace-pre-wrap break-words";

  logDiv.style.overflowWrap =
    "anywhere";

  if (flowId) {
    logDiv.dataset.flowId =
      flowId;
  }

  if (existingFlowLog) {
    logDiv.replaceChildren();
  }

  const normalizedTag =
    String(tag || "").toUpperCase();

  let logKind =
    "default";

  if (normalizedTag.includes("ERROR")) {
    logKind =
      "error";
  } else if (normalizedTag.includes("USER")) {
    logKind =
      "user";
  } else if (normalizedTag.includes("VALIDATOR")) {
    logKind =
      "validator";
  } else if (normalizedTag.includes("SYSTEM")) {
    logKind =
      "system";
  } else if (normalizedTag.includes("SESSION")) {
    logKind =
      "session";
  } else if (normalizedTag.includes("LATEST SNAPSHOTS")) {
    logKind =
      "session";
  } else if (normalizedTag.includes("ACTIVE_MEMORY")) {
    logKind =
      "active-memory";
  } else if (normalizedTag.includes("MEMORY:")) {
    logKind =
      "memory";
  } else if (normalizedTag.includes("SUMMARIZER")) {
    logKind =
      "memory";
  } else if (normalizedTag.includes("FLOW")) {
    logKind =
      "flow";
  } else if (normalizedTag.includes("SERVICE")) {
    logKind =
      "service";
  } else if (normalizedTag.includes("BRAIN")) {
    logKind =
      "brain";
  } else if (normalizedTag.includes("BEFORE")) {
    logKind =
      "before";
  } else if (normalizedTag.includes("AFTER")) {
    logKind =
      "after";
  } else if (normalizedTag.includes("USAGE")) {
    logKind =
      "usage";
  }

  logDiv.dataset.logKind =
    logKind;

  let tagClass =
    "text-zinc-500";

  if (tag.includes("BEFORE")) {
    tagClass =
      "text-amber-500";
  }

  if (tag.includes("BRAIN")) {
    tagClass =
      "text-pink-500";
  }

  if (tag.includes("SERVICE")) {
    tagClass =
      "text-blue-500";
  }

  if (tag.includes("SUMMARIZER")) {
    tagClass =
      "text-blue-400 font-bold";

    logDiv.classList.add(
      "font-mono",
      "text-[12px]",
      "bg-blue-500/5",
      "p-2",
      "rounded",
      "border",
      "border-blue-500/10",
    );
  }

  if (tag.includes("MEMORY:")) {
    tagClass =
      "text-blue-300 font-bold";

    logDiv.classList.add(
      "font-mono",
      "text-[12px]",
      "bg-blue-500/5",
      "p-2",
      "rounded",
      "border",
      "border-blue-500/10",
    );
  }

  if (tag.includes("SESSION")) {
    tagClass =
      "text-cyan-300 font-bold";

    logDiv.classList.add(
      "font-mono",
      "text-[12px]",
      "bg-cyan-500/5",
      "p-2",
      "rounded",
      "border",
      "border-cyan-500/10",
    );
  }

  if (tag.includes("LATEST SNAPSHOTS")) {
    tagClass =
      "text-cyan-300 font-bold";

    logDiv.classList.add(
      "font-mono",
      "text-[12px]",
      "bg-cyan-500/5",
      "p-2",
      "rounded",
      "border",
      "border-cyan-500/10",
    );
  }

  if (tag.includes("ACTIVE_MEMORY")) {
    tagClass =
      "text-zinc-300 font-bold";

    logDiv.classList.add(
      "font-mono",
      "text-[12px]",
      "bg-zinc-500/5",
      "p-2",
      "rounded",
      "border",
      "border-zinc-500/10",
    );
  }

  if (tag.includes("AFTER")) {
    tagClass =
      "text-purple-500";
  }

  if (tag.includes("SYSTEM")) {
    tagClass =
      "text-emerald-500";
  }

  if (tag.includes("VALIDATOR")) {
    tagClass =
      "text-amber-300 font-bold";

    logDiv.classList.add(
      "font-mono",
      "text-[12px]",
      "bg-amber-500/5",
      "p-2",
      "rounded",
      "border",
      "border-amber-500/10",
    );
  }

  if (tag.includes("FLOW TELEMETRY")) {
    tagClass =
      "text-purple-400";
  }

  if (tag === "[FLOW]") {
    tagClass =
      "text-zinc-400";

    logDiv.classList.add(
      "font-mono",
      "text-[12px]",
      "bg-zinc-500/5",
      "p-2",
      "rounded",
      "border",
      "border-zinc-500/10",
    );
  }

  if (tag.includes("USER")) {
    tagClass =
      "text-sky-300 font-bold";
  }

  if (tag.includes("FLOW")) {
    tagClass =
      "text-purple-300 font-bold";
  }

  if (tag.includes("USAGE")) {
    tagClass =
      "text-zinc-300 font-bold";
  }

  if (tag.includes("ERROR")) {
    tagClass =
      "text-red-500 font-bold";

    logDiv.classList.add(
      "font-mono",
      "text-[12px]",
      "bg-red-500/5",
      "p-2",
      "rounded",
      "border",
      "border-red-500/10",
    );
  }

  const tagSpan =
    document.createElement("span");

  tagSpan.className =
    `${tagClass} logger-tag block`;

  tagSpan.textContent =
    tag;

  logDiv.appendChild(
    tagSpan
  );

  const messageSpan =
    document.createElement("span");

  messageSpan.className =
    "block mt-1 text-zinc-400";

  messageSpan.style.overflowWrap =
    "anywhere";

  const validatorPayload =
    tag.includes("VALIDATOR")
      ? parseValidatorLogPayload(
          normalized.message,
          normalized.details
        )
      : null;

  messageSpan.textContent =
    validatorPayload
      ? validatorPayload.message
      : normalized.message;

  if (messageSpan.textContent) {
    logDiv.appendChild(
      messageSpan
    );
  }

  if (
      validatorPayload
      && validatorPayload.payload
  ) {
    const actions =
      document.createElement("div");

    actions.className =
      "mt-2 flex flex-wrap items-center gap-2";

    const payloadButton =
      document.createElement("button");

    payloadButton.type =
      "button";

    payloadButton.className =
      "inline-flex items-center rounded border border-amber-500/20 px-2 py-1 text-[10px] uppercase tracking-wider text-amber-300 hover:bg-amber-500/10 transition";

    payloadButton.textContent =
      "payload";

    payloadButton.addEventListener(
      "click",
      function () {
        showTrace(
          prettifyTraceDetails(
            validatorPayload.payload
          ),
          "Validator payload"
        );
      }
    );

    actions.appendChild(
      payloadButton
    );

    logDiv.appendChild(
      actions
    );
  }

  if (normalized.details && !validatorPayload) {
    const isSummarizer =
      tag.includes("SUMMARIZER")
      || tag.includes("MEMORY:")
      || tag.includes("ACTIVE_MEMORY");

    const isSession =
      tag.includes("SESSION");

    const isLatestSnapshots =
      tag.includes("LATEST SNAPSHOTS");

    const isActiveMemory =
      tag.includes("ACTIVE_MEMORY");

    const isUser =
      tag.includes("USER");

    const isPatternResult =
      isSummarizer
      && String(
        normalized.message
      ).includes(
        "L2 pattern memory"
      );

    const shouldShowReason =
      tag.includes("ERROR")
      || (
          tag.includes("MEMORY:")
          && (
              String(normalized.message).includes("skipped")
              || String(normalized.message).includes("failed")
          )
      );

    const reason =
      shouldShowReason
        ? extractTraceReason(
            normalized.message,
            normalized.details
          )
        : "";

    const actions =
      document.createElement("div");

    actions.className =
      "mt-2 flex flex-wrap items-center gap-2";

    const traceButton =
      document.createElement("button");

    traceButton.type =
      "button";

    traceButton.className =
      isActiveMemory
        ? "inline-flex items-center rounded border border-zinc-600/40 px-2 py-1 text-[10px] uppercase tracking-wider text-zinc-300 hover:bg-zinc-700/40 transition"
        : isSummarizer
        ? "mt-2 inline-flex items-center rounded border border-blue-500/20 px-2 py-1 text-[10px] uppercase tracking-wider text-blue-300 hover:bg-blue-500/10 transition"
        : isSession || isLatestSnapshots
        ? "inline-flex items-center rounded border border-cyan-500/20 px-2 py-1 text-[10px] uppercase tracking-wider text-cyan-300 hover:bg-cyan-500/10 transition"
        : "mt-2 inline-flex items-center rounded border border-red-500/20 px-2 py-1 text-[10px] uppercase tracking-wider text-red-300 hover:bg-red-500/10 transition";

    traceButton.textContent =
      isPatternResult
        ? "patterns"
        : isSession || isLatestSnapshots || isActiveMemory
        ? "show"
        : isSummarizer
        ? "payload"
        : isUser
        ? "payload"
        : "trace";

    traceButton.addEventListener(
      "click",
      function () {
        showTrace(
          isUser
            ? formatUserPayloadTrace(
                parseTraceJson(normalized.details)
                || normalized.details
              )
            : prettifyTraceDetails(normalized.details),
          getTraceTitle(
            normalized.details,
            isPatternResult
              ? "L2 pattern memory"
              : isLatestSnapshots
              ? "Latest snapshots"
              : isSession
              ? "Session bootstrap"
              : tag.includes("ACTIVE_MEMORY")
              ? "Active memory payload"
              : isSummarizer
              ? normalized.message || "Summarizer payload"
              : "Trace"
          ),
          reason
        );
      }
    );

    actions.appendChild(
      traceButton
    );

    if (
        isSession
        || isLatestSnapshots
        || isActiveMemory
    ) {
      const clearButton =
        document.createElement("button");

      clearButton.type =
        "button";

      clearButton.className =
        "inline-flex items-center rounded border border-zinc-600/40 px-2 py-1 text-[10px] uppercase tracking-wider text-zinc-300 hover:bg-zinc-700/40 transition";

      clearButton.textContent =
        isActiveMemory
          ? "delete"
          : "clear";

      clearButton.addEventListener(
        "click",
        function () {
          if (
              isLatestSnapshots
              && window.clearOtherLatestRuntimeMemorySnapshots
          ) {
            window.clearOtherLatestRuntimeMemorySnapshots();
          } else if (isActiveMemory) {
            if (
                window.JinRuntime
                && window.JinRuntime.runtime
                && window.JinRuntime.runtime.clearActiveMemoryRecords
            ) {
              window.JinRuntime.runtime.clearActiveMemoryRecords();
            }
          } else if (window.clearPersistedSessionBootstrap) {
            window.clearPersistedSessionBootstrap();
          }

          normalized.details = null;
          clearButton.disabled = true;
          clearButton.textContent =
            isActiveMemory
              ? "deleted"
              : "cleared";
          traceButton.disabled = true;
          traceButton.classList.add("opacity-40");
          dismissLogAfterClear(
            logDiv
          );
        }
      );

      actions.appendChild(
        clearButton
      );
    }

    logDiv.appendChild(
      actions
    );
  }

  if (existingFlowLog) {
    moveLogToBottomWithFlip(
      logDiv
    );
  } else {
    consoleStream.appendChild(
      logDiv
    );
  }

  registerL1SummarizerRequest(
    logDiv,
    normalized.message,
    meta
  );

  consoleStream.scrollTop =
    consoleStream.scrollHeight;

  return logDiv;
}

window.appendLog =
  appendLog;

window.log_user =
  log_user;

window.log_internal_action =
  log_internal_action;

window.showTrace =
  showTrace;


const consolePanel = document.getElementById("console-panel");
    const consoleDragHandle = document.getElementById("console-drag-handle");
    const PANEL_VIEWPORT_GAP = 8;

    function syncSceneShadeToPanelCollapse() {
        const root =
            document.querySelector("main");

        if (!root) {
            return;
        }

        const collapsedCount =
            [
                consolePanel,
                memoryPanel,
            ].filter((panel) => (
                panel
                && panel.classList.contains("panel-collapsed")
            )).length;

        root.classList.remove(
            "panels-collapsed-1",
            "panels-collapsed-2"
        );

        if (collapsedCount > 0) {
            root.classList.add(
                `panels-collapsed-${collapsedCount}`
            );
        }
    }

    function togglePanelCollapseFromHeader(event, panel, handle, options = {}) {
        const ignoredTarget =
            options.ignoredTarget || null;

        if (
            !handle
            || !handle.contains(event.target)
            || !panel
            || (
                ignoredTarget
                && ignoredTarget.contains(event.target)
            )
        ) {
            return;
        }

        event.preventDefault();
        panel.classList.toggle("panel-collapsed");
        syncSceneShadeToPanelCollapse();
    }

    function getPanelResizeBounds(panel) {
        const parentRect =
            panel.parentElement.getBoundingClientRect();

        const panelRect =
            panel.getBoundingClientRect();

        const panelTop =
            panelRect.top - parentRect.top;

        const minHeight =
            Math.round(parentRect.height * 0.49);

        const maxHeight =
            Math.max(
                minHeight,
                parentRect.height - panelTop - PANEL_VIEWPORT_GAP
            );

        return {
            minHeight,
            maxHeight,
        };
    }

    function clampPanelResizeHeight(panel, nextHeight) {
        const bounds =
            getPanelResizeBounds(panel);

        return Math.max(
            bounds.minHeight,
            Math.min(
                nextHeight,
                bounds.maxHeight
            )
        );
    }

    function clampPanelGeometry(panel) {
        if (
            !panel
            || panel.classList.contains("panel-collapsed")
        ) {
            return;
        }

        const parentRect =
            panel.parentElement.getBoundingClientRect();

        const panelRect =
            panel.getBoundingClientRect();

        const currentLeft =
            panelRect.left - parentRect.left;

        const currentTop =
            panelRect.top - parentRect.top;

        const maxWidth =
            Math.max(
                PANEL_VIEWPORT_GAP,
                parentRect.width - (PANEL_VIEWPORT_GAP * 2)
            );

        const safeWidth =
            Math.min(
                panelRect.width,
                maxWidth
            );

        const maxLeft =
            Math.max(
                PANEL_VIEWPORT_GAP,
                parentRect.width - safeWidth - PANEL_VIEWPORT_GAP
            );

        const nextLeft =
            Math.max(
                PANEL_VIEWPORT_GAP,
                Math.min(
                    currentLeft,
                    maxLeft
                )
            );

        const minHeight =
            Math.round(parentRect.height * 0.49);

        const maxTop =
            Math.max(
                PANEL_VIEWPORT_GAP,
                parentRect.height - minHeight - PANEL_VIEWPORT_GAP
            );

        const nextTop =
            Math.max(
                PANEL_VIEWPORT_GAP,
                Math.min(
                    currentTop,
                    maxTop
                )
            );

        const maxHeight =
            Math.max(
                minHeight,
                parentRect.height - nextTop - PANEL_VIEWPORT_GAP
            );

        const nextHeight =
            Math.max(
                minHeight,
                Math.min(
                    panelRect.height,
                    maxHeight
                )
            );

        panel.style.left =
            `${nextLeft}px`;

        panel.style.top =
            `${nextTop}px`;

        panel.style.right =
            "auto";

        panel.style.height =
            `${nextHeight}px`;
    }

    function clampAllPanelGeometry() {
        clampPanelGeometry(
            consolePanel
        );

        clampPanelGeometry(
            memoryPanel
        );
    }

    function attachBottomResize(panel) {
        if (!panel) {
            return;
        }

        const resizeHandle =
            document.createElement("div");

        resizeHandle.className =
            "panel-bottom-resize-handle";

        resizeHandle.setAttribute(
            "aria-hidden",
            "true"
        );

        panel.appendChild(
            resizeHandle
        );

        let isResizing =
            false;

        let resizeStartY =
            0;

        let resizeStartHeight =
            0;

        resizeHandle.addEventListener("mousedown", (event) => {
            if (
                event.button !== 0
                || panel.classList.contains("panel-collapsed")
            ) {
                return;
            }

            event.preventDefault();
            event.stopPropagation();

            isResizing =
                true;

            resizeStartY =
                event.clientY;

            resizeStartHeight =
                panel.getBoundingClientRect().height;

            document.body.style.cursor =
                "ns-resize";

            document.body.style.userSelect =
                "none";
        });

        window.addEventListener("mousemove", (event) => {
            if (!isResizing) {
                return;
            }

            const nextHeight =
                resizeStartHeight
                + event.clientY
                - resizeStartY;

            panel.style.height =
                `${clampPanelResizeHeight(panel, nextHeight)}px`;
        });

        window.addEventListener("mouseup", () => {
            if (!isResizing) {
                return;
            }

            isResizing =
                false;

            document.body.style.cursor =
                "";

            document.body.style.userSelect =
                "";
        });
    }

    let isConsoleDragging = false;
    let consoleOffsetX = 0;
    let consoleOffsetY = 0;

    consoleDragHandle.addEventListener("mousedown", (event) => {
        if (event.detail > 1) {
            return;
        }

        isConsoleDragging = true;

        const rect = consolePanel.getBoundingClientRect();

        consoleOffsetX = event.clientX - rect.left;
        consoleOffsetY = event.clientY - rect.top;

        consolePanel.style.right = "auto";
        consolePanel.style.bottom = "auto";
        consolePanel.style.position = "absolute";

        document.body.style.userSelect = "none";
    });

    window.addEventListener("mousemove", (event) => {
        if (!isConsoleDragging) return;

        const parentRect = consolePanel.parentElement.getBoundingClientRect();
        const panelRect = consolePanel.getBoundingClientRect();

        let nextLeft = event.clientX - parentRect.left - consoleOffsetX;
        let nextTop = event.clientY - parentRect.top - consoleOffsetY;

        nextLeft = Math.max(
            PANEL_VIEWPORT_GAP,
            Math.min(
                nextLeft,
                parentRect.width - panelRect.width - PANEL_VIEWPORT_GAP
            )
        );

        nextTop = Math.max(
            PANEL_VIEWPORT_GAP,
            Math.min(
                nextTop,
                parentRect.height - panelRect.height - PANEL_VIEWPORT_GAP
            )
        );

        consolePanel.style.left = `${nextLeft}px`;
        consolePanel.style.top = `${nextTop}px`;
    });

    window.addEventListener("mouseup", () => {
        if (!isConsoleDragging) return;

        isConsoleDragging = false;
        document.body.style.userSelect = "";
    });

    consoleDragHandle.addEventListener("dblclick", (event) => {
        togglePanelCollapseFromHeader(
            event,
            consolePanel,
            consoleDragHandle
        );
    });






const memoryPanel = document.getElementById("settings-panel");
const memoryDragHandle = document.getElementById("memory-drag-handle");

let isMemoryDragging = false;
let memoryOffsetX = 0;
let memoryOffsetY = 0;

memoryDragHandle.addEventListener("mousedown", (event) => {
    if (event.detail > 1) {
        return;
    }

    isMemoryDragging = true;

    const rect = memoryPanel.getBoundingClientRect();

    memoryOffsetX = event.clientX - rect.left;
    memoryOffsetY = event.clientY - rect.top;

    document.body.style.userSelect = "none";
});

window.addEventListener("mousemove", (event) => {
    if (!isMemoryDragging) return;

    const parentRect = memoryPanel.parentElement.getBoundingClientRect();
    const panelRect = memoryPanel.getBoundingClientRect();

    let nextLeft =
        event.clientX - parentRect.left - memoryOffsetX;

    let nextTop =
        event.clientY - parentRect.top - memoryOffsetY;

    nextLeft = Math.max(
        PANEL_VIEWPORT_GAP,
        Math.min(
            nextLeft,
            parentRect.width - panelRect.width - PANEL_VIEWPORT_GAP
        )
    );

    nextTop = Math.max(
        PANEL_VIEWPORT_GAP,
        Math.min(
            nextTop,
            parentRect.height - panelRect.height - PANEL_VIEWPORT_GAP
        )
    );

    memoryPanel.style.left = `${nextLeft}px`;
    memoryPanel.style.top = `${nextTop}px`;
    memoryPanel.style.right = "auto";
});

window.addEventListener("mouseup", () => {
    isMemoryDragging = false;
    document.body.style.userSelect = "";
});

memoryDragHandle.addEventListener("dblclick", (event) => {
    togglePanelCollapseFromHeader(
        event,
        memoryPanel,
        memoryDragHandle,
        {
            ignoredTarget:
                document.getElementById("fact-check-trigger"),
        }
    );
});

attachBottomResize(
    consolePanel
);

attachBottomResize(
    memoryPanel
);

requestAnimationFrame(
    clampAllPanelGeometry
);

window.addEventListener(
    "resize",
    clampAllPanelGeometry
);
