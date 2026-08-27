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

function getInternalActionUpdateL4Message(data) {
  if (!data || typeof data !== "object") {
    return "";
  }

  const directMessage =
    String(data.message || "").trim();

  if (directMessage) {
    return directMessage;
  }

  const payloadCandidates = [
    data.payload,
    data.action_payload,
    data.runtime_action_payload,
  ];

  for (const candidate of payloadCandidates) {
    if (
      candidate === undefined
      || candidate === null
      || candidate === ""
    ) {
      continue;
    }

    let parsed = candidate;

    if (typeof candidate === "string") {
      const source = candidate.trim();

      if (!source) {
        continue;
      }

      if (source.startsWith("{")) {
        try {
          parsed = JSON.parse(source);
        } catch (_error) {
          parsed = source;
        }
      } else {
        parsed = source;
      }
    }

    if (
      parsed
      && typeof parsed === "object"
      && !Array.isArray(parsed)
    ) {
      const message =
        String(parsed.message || "").trim();

      if (message) {
        return message;
      }

      continue;
    }

    if (typeof parsed === "string") {
      const message =
        parsed.replace(/\s+/g, " ").trim();

      if (message) {
        return message;
      }
    }
  }

  return "";
}

function getInternalActionJinSizeHover(data) {
  if (!data || typeof data !== "object") {
    return "";
  }

  const source = String(
    data.size
    || data.payload
    || (
      Array.isArray(data.sizes)
        ? data.sizes[data.sizes.length - 1]
        : ""
    )
    || (
      data.width
        ? `w:${data.width} h:${data.height || data.width}`
        : ""
    )
  ).trim();
  const normalized =
    window.JinResponseFormatter
    && typeof window.JinResponseFormatter.normalizeJinSizeMarker === "function"
      ? window.JinResponseFormatter.normalizeJinSizeMarker(source)
      : "";

  if (!normalized) {
    return "";
  }

  const labeled = normalized.match(
    /^w:([^\s]+)\s+h:([^\s]+)$/i
  );
  const width = labeled ? labeled[1] : normalized;
  const height = labeled ? labeled[2] : normalized;

  return `width: ${width}\nheight: ${height}`;
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

function getInternalActionLogKey(
  actionName,
  data = {}
) {
  const normalizedActionName =
    normalizeInternalActionName(
      actionName
    );
  const keepActionInstanceSeparate = [
    "LOAD_SKILL",
    "LOAD_SKILLS",
    "UNLOAD_SKILL",
    "UNLOAD_SKILLS",
    "LOAD_DELAYED_MEMORY",
    "UNLOAD_DELAYED_MEMORY",
  ].includes(normalizedActionName);
  const instanceKey = keepActionInstanceSeparate
    ? String(
      data.id
      || data.runtime_action_id
      || ""
    ).trim()
    : "";

  return [
    String(
      typeof jinConversationTurnCounter === "undefined"
        ? 0
        : jinConversationTurnCounter
    ),
    normalizedActionName,
    instanceKey,
  ].join(":");
}

function findInternalActionLog(
  actionLogKey
) {
  return Array.from(
    consoleStream.querySelectorAll(
      '[data-log-kind="action"]'
    )
  ).find((entry) => (
    entry.dataset.actionLogKey
      === actionLogKey
  )) || null;
}

function renderInternalActionLogTitle(
  logDiv,
  actionName,
  markerCount,
  options = {}
) {
  const tagSpan =
    logDiv.querySelector(
      ":scope > .logger-tag"
    );

  if (!tagSpan) {
    return;
  }

  tagSpan.replaceChildren();

  const title =
    document.createElement("span");

  title.textContent =
    (
      `[ ACTION : ${prettifyInternalActionName(actionName)}`
      + (
        options.aborted === true
          ? ": ABORTED"
          : ""
      )
      + " ]"
    );

  tagSpan.appendChild(
    title
  );

  if (markerCount > 1) {
    const count =
      document.createElement("span");

    count.className =
      "ml-1 opacity-70";
    count.textContent =
      formatRuntimeActionCountLabel(
        markerCount
      );

    tagSpan.appendChild(
      count
    );
  }
}

function updateInternalActionLogMessage(
  logDiv,
  text,
  cancelledByUser,
  preserveExisting
) {
  let messageSpan =
    logDiv.querySelector(
      ":scope > .internal-action-log-message"
    );

  if (preserveExisting && messageSpan) {
    return;
  }

  if (!text) {
    if (!preserveExisting && messageSpan) {
      messageSpan.remove();
    }
    return;
  }

  if (!messageSpan) {
    messageSpan =
      document.createElement("span");
    messageSpan.className =
      "internal-action-log-message block mt-1 text-emerald-100/70";
    messageSpan.style.overflowWrap =
      "anywhere";
    logDiv.appendChild(
      messageSpan
    );
  }

  messageSpan.textContent =
    text;
  messageSpan.classList.toggle(
    "line-through",
    cancelledByUser
  );
  messageSpan.classList.toggle(
    "opacity-60",
    cancelledByUser
  );
}

function updateInternalActionLogPayload(
  logDiv,
  payload,
  title,
  preserveExisting
) {
  let actions =
    logDiv.querySelector(
      ":scope > .internal-action-log-actions"
    );

  if (preserveExisting && actions) {
    return;
  }

  if (payload === null) {
    if (!preserveExisting && actions) {
      actions.remove();
    }
    return;
  }

  if (!actions) {
    actions =
      document.createElement("div");
    actions.className =
      "internal-action-log-actions mt-2 flex flex-wrap items-center gap-2";
    logDiv.appendChild(
      actions
    );
  }

  actions.replaceChildren();

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
}

function log_internal_action(
  action,
  data = {}
) {
  const actionName =
    normalizeInternalActionName(
      action
    );

  if (!actionName) {
    return;
  }

  const title =
    `[ ACTION : ${prettifyInternalActionName(actionName)} ]`;
  const updateL4Message =
    actionName === "UPDATE_L4_FACTS"
      ? getInternalActionUpdateL4Message(
        data
      )
      : "";
  const jinSizeHover =
    actionName === "JIN_SIZE"
      ? getInternalActionJinSizeHover(
        data
      )
      : "";
  const text =
    updateL4Message
    || String(
      data.text || data.query || ""
    ).trim();
  const payload =
    getInternalActionPayload(
      data
    );
  const counterOnly =
    data.counter_only === true;
  const explicitMarkerCount = Math.max(
    0,
    Number.parseInt(
      data.marker_count || 0,
      10
    ) || 0
  );
  const suppressMarkerCount = [
    "LOAD_SKILL",
    "LOAD_SKILLS",
  ].includes(actionName);
  const cancelledByUser =
    String(data.status || "").toLowerCase() === "failed"
    && Boolean(
      data.confirmation_id
      || data.guard_confirmation_id
    )
    && /\bcancelled\s*$/i.test(text);
  const abortedByUser =
    String(data.status || "").toLowerCase() === "aborted";
  const actionLogKey =
    getInternalActionLogKey(
      actionName,
      data
    );
  let logDiv =
    findInternalActionLog(
      actionLogKey
    );

  if (!logDiv) {
    logDiv =
      document.createElement("div");
    logDiv.className =
      "mb-1 min-w-0 whitespace-pre-wrap break-words font-mono text-[12px] bg-emerald-500/5 p-2 rounded border border-emerald-500/10";
    logDiv.dataset.logKind =
      "action";
    logDiv.dataset.actionLogKey =
      actionLogKey;
    logDiv.dataset.actionMarkerCount =
      "0";
    logDiv.style.overflowWrap =
      "anywhere";

    const tagSpan =
      document.createElement("span");

    tagSpan.className =
      "text-emerald-300 font-bold logger-tag block";

    logDiv.appendChild(
      tagSpan
    );

    consoleStream.appendChild(
      logDiv
    );
  }

  if (updateL4Message || jinSizeHover) {
    logDiv.title =
      updateL4Message || jinSizeHover;
    logDiv.classList.add(
      "cursor-help"
    );
  } else {
    logDiv.removeAttribute(
      "title"
    );
    logDiv.classList.remove(
      "cursor-help"
    );
  }

  const currentMarkerCount = Math.max(
    0,
    Number.parseInt(
      logDiv.dataset.actionMarkerCount || "0",
      10
    ) || 0
  );
  const markerCount = Math.max(
    currentMarkerCount,
    suppressMarkerCount
      ? 0
      : explicitMarkerCount
  );

  logDiv.dataset.actionMarkerCount =
    String(markerCount);

  renderInternalActionLogTitle(
    logDiv,
    actionName,
    markerCount,
    {
      aborted:
        abortedByUser,
    }
  );

  const tagSpan =
    logDiv.querySelector(
      ":scope > .logger-tag"
    );

  if (tagSpan) {
    tagSpan.classList.toggle(
      "line-through",
      cancelledByUser
      || abortedByUser
    );
    tagSpan.classList.toggle(
      "opacity-60",
      cancelledByUser
      || abortedByUser
    );
  }

  updateInternalActionLogMessage(
    logDiv,
    text,
    cancelledByUser
    || abortedByUser,
    counterOnly
  );
  updateInternalActionLogPayload(
    logDiv,
    payload,
    title,
    counterOnly
  );

  consoleStream.scrollTop =
    consoleStream.scrollHeight;
}

function normalizeLatestModelOutputLogOrder(
  modelLog
) {
  if (!modelLog || !consoleStream) {
    return;
  }

  const entries = Array.from(
    consoleStream.children
  );
  const modelIndex =
    entries.indexOf(modelLog);

  if (modelIndex < 0) {
    return;
  }

  let userLog = null;

  for (let index = modelIndex - 1; index >= 0; index -= 1) {
    const candidate = entries[index];

    if (candidate.dataset.logKind === "user") {
      userLog = candidate;
      break;
    }
  }

  if (!userLog) {
    return;
  }

  const turnEntries = entries.slice(
    entries.indexOf(userLog) + 1
  ).filter((entry) => entry !== modelLog);
  const strippedMarkerLogs = turnEntries.filter(
    (entry) => (
      entry.dataset.logKind === "validator"
      && /runtime action marker stripped/i.test(
        entry.textContent || ""
      )
    )
  );
  const jinVisualActionLogs = turnEntries.filter(
    (entry) => {
      if (entry.dataset.logKind === "action") {
        return /(?:^|:)JIN_(?:SIZE|COLOR)(?::|$)/i.test(
          entry.dataset.actionLogKey || ""
        );
      }

      return /\[RUNTIME ACTION\]\s+jin_(?:size|color)\b/i.test(
        entry.textContent || ""
      );
    }
  );

  userLog.after(modelLog);

  let anchor = modelLog;

  strippedMarkerLogs.forEach((entry) => {
    anchor.after(entry);
    anchor = entry;
  });

  jinVisualActionLogs.forEach((entry) => {
    anchor.after(entry);
    anchor = entry;
  });
}

function getFactsMemoryStorage() {
  return (
    window.JinRuntime
    && window.JinRuntime.storage
  ) || null;
}

function setFactsMemoryAppendButtonVisible(
  appendButton,
  visible,
) {
  const isVisible =
    Boolean(visible);

  appendButton.hidden =
    !isVisible;

  appendButton.disabled =
    !isVisible;

  appendButton.setAttribute(
    "aria-hidden",
    isVisible ? "false" : "true"
  );

  if (isVisible) {
    appendButton.style.removeProperty(
      "display"
    );
  } else {
    // The button has an inline-flex utility class, which can override the
    // browser's default [hidden] rule. Force it out of layout immediately.
    appendButton.style.display =
      "none";
  }
}

function dismissFactsMemoryLogEntry(
  logDiv,
) {

  if (
      !logDiv
      || logDiv.dataset.factsMemoryDismissed === "true"
  ) {
    return false;
  }

  logDiv.dataset.factsMemoryDismissed =
    "true";

  logDiv.querySelectorAll("button").forEach(
    function (button) {
      button.disabled =
        true;
    }
  );

  dismissLogAfterClear(
    logDiv
  );

  return true;

}

function refreshFactsMemoryAppendButtons() {
  const storage =
    getFactsMemoryStorage();

  if (
      !storage
      || !storage.getCurrentFactsMemorySessionId
      || !storage.getSessionIdFromFactsMemoryStorageKey
      || !storage.hasFactsMemoryForSession
      || !storage.canAppendFactsMemoryByStorageKey
  ) {
    return;
  }

  const currentSessionId =
    String(
      storage.getCurrentFactsMemorySessionId()
      || ""
    ).trim();

  const currentSessionHasFacts =
    Boolean(
      currentSessionId
      && storage.hasFactsMemoryForSession(
        currentSessionId
      )
    );

  document.querySelectorAll(
    "[data-facts-memory-storage-key]"
  ).forEach(
    function (logDiv) {
      const appendButton =
        logDiv.querySelector(
          "[data-facts-memory-append]"
        );

      const storageKey =
        String(
          logDiv.dataset.factsMemoryStorageKey
          || ""
        ).trim();

      const sourceSessionId =
        String(
          storage.getSessionIdFromFactsMemoryStorageKey(
            storageKey
          )
          || ""
        ).trim();

      if (
          storageKey
          && sourceSessionId
          && !storage.hasFactsMemoryForSession(
            sourceSessionId
          )
      ) {
        dismissFactsMemoryLogEntry(
          logDiv
        );
        return;
      }

      if (!appendButton) {
        return;
      }

      const canAppend =
        Boolean(
          sourceSessionId
          && currentSessionId
          && sourceSessionId !== currentSessionId
          && !currentSessionHasFacts
          && storage.hasFactsMemoryForSession(
            sourceSessionId
          )
          && storage.canAppendFactsMemoryByStorageKey(
            storageKey
          )
        );

      setFactsMemoryAppendButtonVisible(
        appendButton,
        canAppend
      );
    }
  );
}

const l4SummarizerCards = {
  extraction: [],
  merge: [],
};

const l4DeletedFactCards =
  new Map();

const delayedDeletedReportCards =
  new Map();

const delayedUnlinkedFactCards =
  new Map();

const deletedFileCards =
  new Map();

function parseL4JsonPayload(details) {
  const text =
    String(details || "").trim();

  if (!text) {
    return null;
  }

  const direct =
    parseTraceJson(text);

  if (direct) {
    return direct;
  }

  const fenced =
    text.match(/```(?:json)?\s*([\s\S]*?)```/i);

  if (fenced) {
    const parsed =
      parseTraceJson(fenced[1].trim());

    if (parsed) {
      return parsed;
    }
  }

  const firstBrace =
    text.indexOf("{");
  const lastBrace =
    text.lastIndexOf("}");

  if (firstBrace >= 0 && lastBrace > firstBrace) {
    return parseTraceJson(
      text.slice(firstBrace, lastBrace + 1)
    );
  }

  return null;
}

function createNeutralMemoryLoggerCard(tag) {
  const logDiv =
    document.createElement("div");

  logDiv.className =
    "mb-1 min-w-0 whitespace-pre-wrap break-words font-mono text-[12px] bg-zinc-500/5 p-2 rounded border border-zinc-500/10";

  logDiv.style.overflowWrap =
    "anywhere";

  logDiv.dataset.logKind =
    "memory";

  const tagSpan =
    document.createElement("span");

  tagSpan.className =
    "text-zinc-400 font-bold logger-tag block";

  tagSpan.textContent =
    tag;

  logDiv.appendChild(tagSpan);
  consoleStream.appendChild(logDiv);
  consoleStream.scrollTop =
    consoleStream.scrollHeight;

  return logDiv;
}

function createL4LoggerCard(tag) {
  const logDiv =
    document.createElement("div");

  logDiv.className =
    "mb-1 min-w-0 whitespace-pre-wrap break-words font-mono text-[12px] bg-blue-500/5 p-2 rounded border border-blue-500/10";

  logDiv.style.overflowWrap =
    "anywhere";

  logDiv.dataset.logKind =
    "memory";

  const tagSpan =
    document.createElement("span");

  tagSpan.className =
    "text-blue-300 font-bold logger-tag block";

  tagSpan.textContent =
    tag;

  logDiv.appendChild(tagSpan);

  consoleStream.appendChild(logDiv);
  consoleStream.scrollTop =
    consoleStream.scrollHeight;

  return logDiv;
}

function createL4LoggerButton(
  label,
  tone = "blue",
) {
  const button =
    document.createElement("button");

  button.type =
    "button";

  button.textContent =
    label;

  setL4LoggerButtonTone(
    button,
    tone
  );

  return button;
}

function setL4LoggerButtonTone(
  button,
  tone,
) {
  button.className =
    tone === "muted"
      ? "inline-flex items-center rounded border border-zinc-600/40 px-2 py-1 text-[10px] uppercase tracking-wider text-zinc-400 hover:bg-zinc-700/30 transition"
      : "inline-flex items-center rounded border border-blue-500/20 px-2 py-1 text-[10px] uppercase tracking-wider text-blue-300 hover:bg-blue-500/10 transition";
}

function setL4LoggerButtonVisible(
  button,
  visible,
) {
  button.hidden = !visible;
  button.classList.toggle(
    "hidden",
    !visible
  );
}

function resolveL4SummarizerPhase(
  message,
  meta,
) {
  if (String(meta && meta.memory_level || "").toUpperCase() !== "L4") {
    return "";
  }

  const normalized =
    String(message || "").toLowerCase();

  if (normalized.startsWith("l4 extraction summarizer ")) {
    return "extraction";
  }

  if (normalized.startsWith("l4 merge summarizer ")) {
    return "merge";
  }

  return "";
}

function resolveL4SummarizerEvent(
  message,
  meta,
) {
  const event =
    String(meta && meta.memory_event || "").toLowerCase();

  if (event === "summarizer_request" || event === "summarizer_result") {
    return event;
  }

  const normalized =
    String(message || "").toLowerCase();

  if (normalized.endsWith("summarizer request")) {
    return "summarizer_request";
  }

  if (normalized.endsWith("summarizer result")) {
    return "summarizer_result";
  }

  return "";
}

function l4ResponseHasChanges(
  phase,
  payload,
) {
  if (!payload || typeof payload !== "object") {
    return true;
  }

  if (phase === "extraction" && Array.isArray(payload.facts)) {
    return payload.facts.length > 0;
  }

  if (phase === "merge" && Array.isArray(payload.operations)) {
    return payload.operations.length > 0;
  }

  return Object.keys(payload).length > 0;
}

function createL4SummarizerCard(
  phase,
  requestDetails = null,
) {
  const phaseLabel =
    phase.toUpperCase();

  const logDiv =
    createL4LoggerCard(
      `[MEMORY:L4:${phaseLabel}]`
    );

  const actions =
    document.createElement("div");

  actions.className =
    "mt-2 flex flex-wrap items-center gap-2";

  const requestButton =
    createL4LoggerButton(
      "request"
    );

  const responseButton =
    createL4LoggerButton(
      "response"
    );

  setL4LoggerButtonVisible(
    responseButton,
    false
  );

  const state = {
    logDiv,
    phase,
    requestDetails,
    responseSettled: false,
    responseReady: false,
    responseDetails: null,
    responsePayload: null,
    responseHasChanges: false,
    requestButton,
    responseButton,
  };

  setL4LoggerButtonVisible(
    requestButton,
    Boolean(requestDetails)
  );

  requestButton.addEventListener(
    "click",
    function () {
      if (!state.requestDetails) {
        return;
      }

      showTrace(
        state.requestDetails,
        `L4 ${phase} request`
      );
    }
  );

  responseButton.addEventListener(
    "click",
    function () {
      if (!state.responseReady) {
        return;
      }

      showTrace(
        JSON.stringify({
          kind: "l4_summarizer_response",
          phase,
          payload: state.responsePayload,
          raw: state.responseDetails,
          no_changes: !state.responseHasChanges,
        }),
        `L4 ${phase} response`
      );
    }
  );

  actions.appendChild(requestButton);
  actions.appendChild(responseButton);
  logDiv.appendChild(actions);

  l4SummarizerCards[phase].push(state);

  return state;
}

function handleL4SummarizerLog(
  message,
  details,
  meta,
) {
  const phase =
    resolveL4SummarizerPhase(
      message,
      meta
    );

  if (!phase) {
    return null;
  }

  const event =
    resolveL4SummarizerEvent(
      message,
      meta
    );

  if (event === "summarizer_request") {
    return createL4SummarizerCard(
      phase,
      details
    ).logDiv;
  }

  if (event !== "summarizer_result") {
    return null;
  }

  let state =
    [...l4SummarizerCards[phase]]
      .reverse()
      .find((candidate) => !candidate.responseSettled);

  if (!state) {
    state =
      createL4SummarizerCard(
        phase
      );
  }

  state.responseSettled =
    true;
  state.responseDetails =
    String(details ?? "");

  const responseText =
    state.responseDetails.trim();

  state.responseReady =
    Boolean(
      responseText
      && responseText !== "<empty>"
    );

  if (!state.responseReady) {
    state.responsePayload =
      null;
    state.responseHasChanges =
      false;

    setL4LoggerButtonVisible(
      state.responseButton,
      false
    );

    return state.logDiv;
  }

  state.responsePayload =
    parseL4JsonPayload(
      state.responseDetails
    );
  state.responseHasChanges =
    Boolean(state.responseDetails.trim())
    && l4ResponseHasChanges(
      phase,
      state.responsePayload
    );

  setL4LoggerButtonVisible(
    state.responseButton,
    true
  );

  setL4LoggerButtonTone(
    state.responseButton,
    state.responseHasChanges
      ? "blue"
      : "muted"
  );

  return state.logDiv;
}


function settleL4SummarizerCardForTerminalEvent(
  message,
  meta,
) {
  const event =
    String(meta && meta.memory_event || "").toLowerCase();

  if (!event.endsWith("_skipped") && !event.endsWith("_failed")) {
    return;
  }

  const phase =
    event.startsWith("extract_")
      ? "extraction"
      : event.startsWith("merge_")
      ? "merge"
      : resolveL4SummarizerPhase(
          message,
          meta
        );

  if (!phase || !l4SummarizerCards[phase]) {
    return;
  }

  const state =
    [...l4SummarizerCards[phase]]
      .reverse()
      .find((candidate) => !candidate.responseSettled);

  if (!state) {
    return;
  }

  state.responseSettled =
    true;
  state.responseReady =
    false;
  state.responseDetails =
    null;
  state.responsePayload =
    null;
  state.responseHasChanges =
    false;

  setL4LoggerButtonVisible(
    state.responseButton,
    false
  );
}

function resolveDeletedL4Fact(
  details,
  meta,
) {
  if (
      meta
      && meta.deleted_fact
      && typeof meta.deleted_fact === "object"
  ) {
    return meta.deleted_fact;
  }

  const payload =
    parseL4JsonPayload(details);

  if (
      payload
      && payload.fact
      && typeof payload.fact === "object"
  ) {
    return payload.fact;
  }

  return null;
}

function resolveDeletedL4FactNumber(fact) {
  const match =
    String(fact && fact.id || "")
      .trim()
      .match(/^F(\d+)$/i);

  if (!match) {
    return null;
  }

  const number = Number(match[1]);

  return Number.isSafeInteger(number)
    ? number
    : null;
}

function handleL4DeletedFactLog(
  tag,
  details,
  meta,
) {
  const isDeleted =
    String(meta && meta.memory_event || "").toLowerCase() === "fact_deleted"
    || String(tag || "").toUpperCase() === "[MEMORY:L4:DELETED]";

  if (!isDeleted) {
    return null;
  }

  const fact =
    resolveDeletedL4Fact(
      details,
      meta
    );

  if (!fact) {
    return null;
  }

  const logDiv =
    createL4LoggerCard(
      "[MEMORY:L4:DELETED]"
    );

  const key =
    document.createElement("span");

  key.className =
    "block mt-2 text-zinc-200 font-semibold";

  const factNumber =
    resolveDeletedL4FactNumber(fact);
  const factTitle =
    String(fact.key || fact.id || "L4 fact");

  key.textContent =
    factNumber !== null
      ? `${factNumber} · ${factTitle}`
      : factTitle;

  const value =
    document.createElement("span");

  value.className =
    "block mt-1 text-zinc-400";

  value.textContent =
    String(fact.value || "");

  logDiv.appendChild(key);

  if (value.textContent) {
    logDiv.appendChild(value);
  }

  const actions =
    document.createElement("div");

  actions.className =
    "mt-2 flex flex-wrap items-center gap-2";

  const payloadButton =
    createL4LoggerButton(
      "payload"
    );

  const restoreButton =
    createL4LoggerButton(
      "restore"
    );

  payloadButton.addEventListener(
    "click",
    function () {
      showTrace(
        JSON.stringify({
          kind: "l4_fact",
          fact,
        }),
        "L4 fact deleted"
      );
    }
  );

  restoreButton.addEventListener(
    "click",
    function () {
      const api =
        window.JINRuntimeL4Memory;

      if (!api || typeof api.requestFactRestore !== "function") {
        return;
      }

      const sent =
        api.requestFactRestore(
          fact
        );

      if (!sent) {
        restoreButton.textContent =
          "offline";

        window.setTimeout(
          function () {
            restoreButton.textContent =
              "restore";
          },
          1200
        );
        return;
      }

      restoreButton.disabled =
        true;
      restoreButton.textContent =
        "restoring";
      restoreButton.classList.add(
        "opacity-50"
      );

      l4DeletedFactCards.set(
        String(fact.id || ""),
        {
          logDiv,
          restoreButton,
        }
      );
    }
  );

  actions.appendChild(payloadButton);
  actions.appendChild(restoreButton);
  logDiv.appendChild(actions);

  return logDiv;
}

function handleL4MemoryRestoreResult(
  data
) {
  const factId =
    String(data && data.fact_id || "");

  const state =
    l4DeletedFactCards.get(
      factId
    );

  if (!state) {
    return;
  }

  l4DeletedFactCards.delete(
    factId
  );

  if (data && data.restored) {
    dismissLogAfterClear(
      state.logDiv
    );
    return;
  }

  state.restoreButton.disabled =
    false;
  state.restoreButton.textContent =
    "restore failed";
  state.restoreButton.classList.remove(
    "opacity-50"
  );

  window.setTimeout(
    function () {
      state.restoreButton.textContent =
        "restore";
    },
    1400
  );
}

function resolveDeletedFile(
  details,
  meta,
) {
  if (
      meta
      && meta.deleted_file
      && typeof meta.deleted_file === "object"
  ) {
    return meta.deleted_file;
  }

  const payload =
    parseL4JsonPayload(details);

  if (
      payload
      && payload.file
      && typeof payload.file === "object"
  ) {
    return payload.file;
  }

  return null;
}

function isDeletedFileImage(file) {
  const kind =
    String(file && file.kind || "")
      .trim()
      .toLowerCase();

  if (kind === "image") {
    return true;
  }

  const mimeType =
    String(
      file
      && (
        file.type
        || file.content_type
      )
      || ""
    )
      .trim()
      .toLowerCase();

  if (mimeType.startsWith("image/")) {
    return true;
  }

  const source =
    String(file && (file.url || file.context_path) || "")
      .trim()
      .toLowerCase();

  return /\.(png|jpe?g|webp|gif|bmp|svg)(?:$|[?#])/.test(
    source
  );
}

function formatDeletedFileInlineLabel(file, fileId) {
  const stableId =
    String(file && file.id || fileId || "")
      .trim();
  const name =
    String(file && file.name || "")
      .trim();

  return [
    stableId,
    name,
  ].filter(Boolean).join(" · ");
}

function bindDeletedFileInlinePreview(
  element,
  file,
) {
  if (
      !element
      || !file
      || !isDeletedFileImage(file)
      || typeof window.bindJinAttachmentHoverPreview !== "function"
  ) {
    return;
  }

  window.bindJinAttachmentHoverPreview(
    element,
    file,
    {
      hoverPreviewMaxPx: 100,
    }
  );

  const applyHoverState = (active) => {
    element.style.backgroundColor = active
      ? "rgba(59, 130, 246, 0.08)"
      : "transparent";
    element.style.borderColor = active
      ? "rgba(59, 130, 246, 0.18)"
      : "transparent";
  };

  element.style.cursor = "default";
  element.style.transition = "background-color 150ms ease, border-color 150ms ease";
  element.style.border = "1px solid transparent";
  element.style.borderRadius = "4px";
  element.style.padding = "2px 4px";
  element.style.marginLeft = "-4px";
  element.style.marginRight = "-4px";

  element.addEventListener(
    "mouseenter",
    function () {
      applyHoverState(true);
    }
  );

  element.addEventListener(
    "mouseleave",
    function () {
      applyHoverState(false);
    }
  );
}

function resolveUnpinnedMemory(
  details,
  meta,
) {
  if (
      meta
      && meta.unpinned_memory
      && typeof meta.unpinned_memory === "object"
  ) {
    return meta.unpinned_memory;
  }

  const payload =
    parseL4JsonPayload(details);

  return payload
    && typeof payload === "object"
    && !Array.isArray(payload)
      ? payload
      : null;
}

function handleMemoryUnpinnedLog(
  tag,
  details,
  meta,
) {
  const isUnpinned =
    String(meta && meta.memory_event || "").toLowerCase()
      === "memory_unpinned"
    || String(tag || "").toUpperCase()
      === "[MEMORY:UNPINNED]";

  if (!isUnpinned) {
    return null;
  }

  const payload =
    resolveUnpinnedMemory(
      details,
      meta
    );
  const kind =
    String(payload && payload.kind || "")
      .trim()
      .toLowerCase();
  const id =
    String(payload && payload.id || "")
      .trim()
      .toLowerCase();
  const label =
    String(payload && payload.label || id || "memory")
      .trim();

  if (!id || (kind !== "file" && kind !== "delayed")) {
    return null;
  }

  const logDiv =
    createNeutralMemoryLoggerCard(
      "[MEMORY:UNPINNED]"
    );
  const summary =
    document.createElement("span");

  summary.className =
    "block mt-2 text-zinc-300 font-semibold";
  summary.textContent =
    `unpinned · ${label}`;

  const actions =
    document.createElement("div");

  actions.className =
    "mt-2 flex flex-wrap items-center gap-2";

  const pinButton =
    createL4LoggerButton(
      "pin",
      "muted"
    );

  pinButton.addEventListener(
    "click",
    async function () {
      pinButton.disabled = true;

      let pinned = false;

      if (kind === "file") {
        const api =
          window.JinFiles;

        if (api && typeof api.setPinned === "function") {
          pinned = await api.setPinned(
            id,
            true,
            {log: false}
          );
        }
      } else {
        const api =
          window.JinRuntime
          && window.JinRuntime.runtime;

        if (api && typeof api.setDelayedMemoryReportPinned === "function") {
          pinned = api.setDelayedMemoryReportPinned(
            id,
            true,
            {log: false}
          );
        }
      }

      if (!pinned) {
        pinButton.disabled = false;
        pinButton.textContent = "pin failed";
        window.setTimeout(
          function () {
            pinButton.textContent = "pin";
          },
          1400
        );
        return;
      }

      dismissLogAfterClear(
        logDiv
      );
    }
  );

  logDiv.appendChild(
    summary
  );
  actions.appendChild(
    pinButton
  );
  logDiv.appendChild(
    actions
  );

  return logDiv;
}

function handleDeletedFileLog(
  tag,
  details,
  meta,
) {
  const isDeleted =
    String(meta && meta.memory_event || "").toLowerCase()
      === "file_deleted"
    || String(tag || "").toUpperCase()
      === "[MEMORY:FILES:DELETED]";

  if (!isDeleted) {
    return null;
  }

  const file =
    resolveDeletedFile(
      details,
      meta
    );
  const fileId =
    String(file && file.id || "")
      .trim()
      .toLowerCase();

  if (!file || !fileId) {
    return null;
  }

  const logDiv =
    createL4LoggerCard(
      "[MEMORY:FILES:DELETED]"
    );
  const summary =
    document.createElement("span");

  summary.className =
    "block mt-2 text-zinc-200 font-semibold";
  summary.textContent =
    formatDeletedFileInlineLabel(
      file,
      fileId
    )
    || "File";

  bindDeletedFileInlinePreview(
    summary,
    file
  );

  logDiv.appendChild(summary);

  const actions =
    document.createElement("div");
  actions.className =
    "mt-2 flex flex-wrap items-center gap-2";

  const payloadButton =
    createL4LoggerButton(
      "payload"
    );
  const restoreButton =
    createL4LoggerButton(
      "restore"
    );

  payloadButton.addEventListener(
    "click",
    function () {
      showTrace(
        JSON.stringify({
          kind: "file",
          file,
        }),
        "File deleted"
      );
    }
  );

  restoreButton.addEventListener(
    "click",
    async function () {
      const api = window.JinFiles;

      if (!api || typeof api.restoreDeletedFile !== "function") {
        return;
      }

      restoreButton.disabled = true;
      restoreButton.textContent = "restoring";
      restoreButton.classList.add(
        "opacity-50"
      );

      const restored =
        await api.restoreDeletedFile(
          fileId
        );

      if (!restored) {
        restoreButton.disabled = false;
        restoreButton.textContent = "restore failed";
        restoreButton.classList.remove(
          "opacity-50"
        );

        window.setTimeout(
          function () {
            restoreButton.textContent = "restore";
          },
          1400
        );
        return;
      }

      deletedFileCards.delete(
        fileId
      );
      dismissLogAfterClear(
        logDiv
      );
    }
  );

  deletedFileCards.set(
    fileId,
    {
      logDiv,
      restoreButton,
    }
  );

  actions.appendChild(payloadButton);
  actions.appendChild(restoreButton);
  logDiv.appendChild(actions);

  return logDiv;
}

function resolveDeletedDelayedMemoryReport(
  details,
  meta,
) {
  if (
      meta
      && meta.deleted_delayed_memory_report
      && typeof meta.deleted_delayed_memory_report === "object"
  ) {
    return meta.deleted_delayed_memory_report;
  }

  const payload =
    parseL4JsonPayload(details);

  if (
      payload
      && payload.report
      && typeof payload.report === "object"
  ) {
    return payload.report;
  }

  return null;
}

function getDelayedMemoryReportCardId(report) {
  return String(
    report
    && (
      report.id
      || report._storage_key
    )
    || ""
  ).trim().toLowerCase();
}

function handleDelayedMemoryDeletedReportLog(
  tag,
  details,
  meta,
) {
  const isDeleted =
    String(meta && meta.memory_event || "").toLowerCase()
      === "delayed_memory_deleted"
    || String(tag || "").toUpperCase()
      === "[MEMORY:DELAYED:DELETED]";

  if (!isDeleted) {
    return null;
  }

  const report =
    resolveDeletedDelayedMemoryReport(
      details,
      meta
    );
  const reportId =
    getDelayedMemoryReportCardId(
      report
    );

  if (!report || !reportId) {
    return null;
  }

  const logDiv =
    createL4LoggerCard(
      "[MEMORY:DELAYED:DELETED]"
    );

  const title =
    document.createElement("span");

  title.className =
    "block mt-2 text-zinc-200 font-semibold";

  title.textContent =
    String(report.title || reportId || "Delayed memory");

  const summary =
    document.createElement("span");

  summary.className =
    "block mt-1 text-zinc-400";

  summary.textContent =
    String(report.summary || "");

  logDiv.appendChild(title);

  if (summary.textContent) {
    logDiv.appendChild(summary);
  }

  const actions =
    document.createElement("div");

  actions.className =
    "mt-2 flex flex-wrap items-center gap-2";

  const payloadButton =
    createL4LoggerButton(
      "payload"
    );

  const restoreButton =
    createL4LoggerButton(
      "restore"
    );

  payloadButton.addEventListener(
    "click",
    function () {
      showTrace(
        JSON.stringify({
          kind: "delayed_memory_report",
          report,
        }),
        "Delayed memory deleted"
      );
    }
  );

  restoreButton.addEventListener(
    "click",
    function () {
      const api =
        window.JinRuntime
        && window.JinRuntime.runtime;

      if (!api || typeof api.restoreDelayedMemoryReport !== "function") {
        return;
      }

      const restored =
        api.restoreDelayedMemoryReport(
          reportId,
          report
        );

      if (!restored) {
        restoreButton.textContent =
          "restore failed";

        window.setTimeout(
          function () {
            restoreButton.textContent =
              "restore";
          },
          1400
        );
        return;
      }

      restoreButton.disabled =
        true;
      restoreButton.textContent =
        "restored";
      restoreButton.classList.add(
        "opacity-50"
      );

      delayedDeletedReportCards.delete(
        reportId
      );
      dismissLogAfterClear(
        logDiv
      );
    }
  );

  delayedDeletedReportCards.set(
    reportId,
    {
      logDiv,
      restoreButton,
    }
  );

  actions.appendChild(payloadButton);
  actions.appendChild(restoreButton);
  logDiv.appendChild(actions);

  return logDiv;
}

function resolveDelayedMemoryFactUnlink(
  details,
  meta,
) {
  if (
      meta
      && meta.delayed_memory_fact_unlink
      && typeof meta.delayed_memory_fact_unlink === "object"
  ) {
    return meta.delayed_memory_fact_unlink;
  }

  const payload =
    parseL4JsonPayload(details);

  if (
      payload
      && payload.kind === "delayed_memory_fact_unlink"
  ) {
    return payload;
  }

  return null;
}

function getDelayedMemoryFactUnlinkCardId(
  payload
) {
  return [
    payload && payload.report_id,
    payload && payload.fact_id,
  ]
    .map(value => String(value || "").trim())
    .filter(Boolean)
    .join(":");
}

function handleDelayedMemoryFactUnlinkedLog(
  tag,
  details,
  meta,
) {
  const isUnlinked =
    String(meta && meta.memory_event || "").toLowerCase()
      === "delayed_memory_fact_unlinked"
    || String(tag || "").toUpperCase()
      === "[MEMORY:DELAYED:FACT_UNLINKED]";

  if (!isUnlinked) {
    return null;
  }

  const payload =
    resolveDelayedMemoryFactUnlink(
      details,
      meta
    );
  const reportId =
    String(payload && payload.report_id || "")
      .trim()
      .toLowerCase();
  const factId =
    String(payload && payload.fact_id || "")
      .trim();
  const cardId =
    getDelayedMemoryFactUnlinkCardId(
      payload
    );

  if (!payload || !reportId || !factId || !cardId) {
    return null;
  }

  const logDiv =
    createL4LoggerCard(
      "[MEMORY:DELAYED:FACT_UNLINKED]"
    );

  const title =
    document.createElement("span");

  title.className =
    "block mt-2 text-zinc-200 font-semibold";

  title.textContent =
    `${factId} . ${String(
      payload.report
      && (
        payload.report.title
        || payload.report.id
      )
      || reportId
    )}`;

  const summary =
    document.createElement("span");

  summary.className =
    "block mt-1 text-zinc-400";

  const fact =
    payload.fact
    && typeof payload.fact === "object"
      ? payload.fact
      : null;

  summary.textContent =
    fact
      ? `${String(fact.key || factId)}: ${String(fact.value || "")}`
      : "Fact unlinked from delayed memory report.";

  logDiv.appendChild(
    title
  );

  if (summary.textContent) {
    logDiv.appendChild(
      summary
    );
  }

  const actions =
    document.createElement("div");

  actions.className =
    "mt-2 flex flex-wrap items-center gap-2";

  const payloadButton =
    createL4LoggerButton(
      "payload"
    );

  const restoreButton =
    createL4LoggerButton(
      "restore"
    );

  payloadButton.addEventListener(
    "click",
    function () {
      showTrace(
        JSON.stringify(
          payload,
          null,
          2
        ),
        "Delayed memory fact unlinked"
      );
    }
  );

  restoreButton.addEventListener(
    "click",
    function () {
      const api =
        window.JinRuntime
        && window.JinRuntime.runtime;

      if (!api || typeof api.linkDelayedMemoryReportFactId !== "function") {
        return;
      }

      const restored =
        api.linkDelayedMemoryReportFactId(
          reportId,
          factId,
          {
            anchor: Boolean(payload.was_anchor),
            log: false,
          }
        );

      if (!restored) {
        restoreButton.textContent =
          "restore failed";

        window.setTimeout(
          function () {
            restoreButton.textContent =
              "restore";
          },
          1400
        );
        return;
      }

      restoreButton.disabled =
        true;
      restoreButton.textContent =
        "restored";
      restoreButton.classList.add(
        "opacity-50"
      );

      delayedUnlinkedFactCards.delete(
        cardId
      );
      dismissLogAfterClear(
        logDiv
      );
    }
  );

  delayedUnlinkedFactCards.set(
    cardId,
    {
      logDiv,
      restoreButton,
    }
  );

  actions.appendChild(payloadButton);
  actions.appendChild(restoreButton);
  logDiv.appendChild(actions);

  return logDiv;
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

  settleL4SummarizerCardForTerminalEvent(
    normalized.message,
    meta
  );

  const l4SummarizerLog =
    handleL4SummarizerLog(
      normalized.message,
      normalized.details,
      meta
    );

  if (l4SummarizerLog) {
    return l4SummarizerLog;
  }

  const l4DeletedFactLog =
    handleL4DeletedFactLog(
      tag,
      normalized.details,
      meta
    );

  if (l4DeletedFactLog) {
    return l4DeletedFactLog;
  }

  const memoryUnpinnedLog =
    handleMemoryUnpinnedLog(
      tag,
      normalized.details,
      meta
    );

  if (memoryUnpinnedLog) {
    return memoryUnpinnedLog;
  }

  const deletedFileLog =
    handleDeletedFileLog(
      tag,
      normalized.details,
      meta
    );

  if (deletedFileLog) {
    return deletedFileLog;
  }

  const delayedMemoryFactUnlinkedLog =
    handleDelayedMemoryFactUnlinkedLog(
      tag,
      normalized.details,
      meta
    );

  if (delayedMemoryFactUnlinkedLog) {
    return delayedMemoryFactUnlinkedLog;
  }

  const delayedMemoryDeletedLog =
    handleDelayedMemoryDeletedReportLog(
      tag,
      normalized.details,
      meta
    );

  if (delayedMemoryDeletedLog) {
    return delayedMemoryDeletedLog;
  }

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

  const isL4Paused =
    normalizedTag === "[MEMORY:L4:PAUSED]";

  const isBrainOutput =
    normalizedTag === "[BRAIN]";

  const isServiceBrainOutput =
    normalizedTag === "[SERVICE]";

  const isModelOutput =
    isBrainOutput
    || isServiceBrainOutput;

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
  } else if (normalizedTag.includes("FACTS_MEMORY")) {
    logKind =
      "memory";
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

  if (isBrainOutput) {
    tagClass =
      "text-pink-400 font-bold";

    logDiv.classList.add(
      "font-mono",
      "text-[12px]",
      "bg-pink-500/5",
      "p-2",
      "rounded",
      "border",
      "border-pink-500/10",
    );
  }

  if (isServiceBrainOutput) {
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

  if (isL4Paused) {
    tagClass =
      "text-red-300 font-bold";

    logDiv.classList.remove(
      "bg-blue-500/5",
      "border-blue-500/10",
    );
    logDiv.classList.add(
      "font-mono",
      "text-[12px]",
      "bg-red-500/5",
      "p-2",
      "rounded",
      "border",
      "border-red-500/15",
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

  if (tag.includes("FACTS_MEMORY")) {
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
    isL4Paused
      ? "block mt-1 text-red-200/80"
      : "block mt-1 text-zinc-400";

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

    const isFactsMemory =
      tag.includes("FACTS_MEMORY");

    if (isFactsMemory) {
      logDiv.dataset.factsMemoryStorageKey =
        String(
          meta?.facts_memory_storage_key
          || ""
        ).trim();
    }

    const isUser =
      tag.includes("USER");

    const isJsonParseError =
      tag.includes("ERROR")
      && String(
        normalized.message
      ).includes(
        "[JSON PARSE ERROR]"
      );

    const isLmStudioError =
      tag.includes("ERROR")
      && (
        String(meta?.provider || "").toLowerCase()
          === "lm_studio"
        || String(normalized.message || "")
          .includes("[LM STUDIO ERROR]")
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
        ? (
            String(
              meta?.trace_reason
              || ""
            ).trim()
            || extractTraceReason(
                normalized.message,
                normalized.details
              )
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
      isBrainOutput
        ? "inline-flex items-center rounded border border-pink-500/20 px-2 py-1 text-[10px] uppercase tracking-wider text-pink-300 hover:bg-pink-500/10 transition"
        : isServiceBrainOutput
        ? "inline-flex items-center rounded border border-blue-500/20 px-2 py-1 text-[10px] uppercase tracking-wider text-blue-300 hover:bg-blue-500/10 transition"
        : isActiveMemory || isFactsMemory
        ? "inline-flex items-center rounded border border-zinc-600/40 px-2 py-1 text-[10px] uppercase tracking-wider text-zinc-300 hover:bg-zinc-700/40 transition"
        : isSummarizer
        ? "mt-2 inline-flex items-center rounded border border-blue-500/20 px-2 py-1 text-[10px] uppercase tracking-wider text-blue-300 hover:bg-blue-500/10 transition"
        : isSession || isLatestSnapshots
        ? "inline-flex items-center rounded border border-cyan-500/20 px-2 py-1 text-[10px] uppercase tracking-wider text-cyan-300 hover:bg-cyan-500/10 transition"
        : "mt-2 inline-flex items-center rounded border border-red-500/20 px-2 py-1 text-[10px] uppercase tracking-wider text-red-300 hover:bg-red-500/10 transition";

    traceButton.textContent =
      isModelOutput
        ? "payload"
        : isSession || isLatestSnapshots || isActiveMemory || isFactsMemory
        ? "show"
        : isSummarizer
        ? "payload"
        : isUser
        ? "payload"
        : isLmStudioError
        ? "payload"
        : isJsonParseError
        ? "payload"
        : "trace";

    traceButton.addEventListener(
      "click",
      function () {
        showTrace(
          isModelOutput
            ? String(normalized.details || "")
            : isUser
            ? formatUserPayloadTrace(
                parseTraceJson(normalized.details)
                || normalized.details
              )
            : prettifyTraceDetails(normalized.details),
          getTraceTitle(
            normalized.details,
            isLatestSnapshots
              ? "Latest snapshots"
              : isSession
              ? "Session bootstrap"
              : tag.includes("ACTIVE_MEMORY")
              ? "Active memory payload"
              : isFactsMemory
              ? `Facts memory · ${String(meta?.facts_memory_session_id || "session")}`
              : isBrainOutput
              ? "Brain output"
              : isServiceBrainOutput
              ? "Service as brain output"
              : isSummarizer
              ? normalized.message || "Summarizer payload"
              : isLmStudioError
              ? "LM Studio error payload"
              : isJsonParseError
              ? "Runtime stream payload"
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
        || isFactsMemory
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
          } else if (isFactsMemory) {
            const storage =
              window.JinRuntime
              && window.JinRuntime.storage;

            const storageKey =
              String(
                meta?.facts_memory_storage_key
                || ""
              ).trim();

            if (
                storage
                && storage.clearFactsMemoryByStorageKey
                && storageKey
            ) {
              storage.clearFactsMemoryByStorageKey(
                storageKey
              );

              if (
                  storage.getFactsMemoryStorageKey
                  && storageKey === storage.getFactsMemoryStorageKey()
                  && window.JinRuntime
                  && window.JinRuntime.runtime
                  && window.JinRuntime.runtime.renderRuntimeMemorySnapshot
              ) {
                window.JinRuntime.runtime.renderRuntimeMemorySnapshot();
              }
            }
          } else if (window.clearPersistedSessionBootstrap) {
            window.clearPersistedSessionBootstrap();
          }

          if (isFactsMemory) {
            refreshFactsMemoryAppendButtons();
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

    if (isFactsMemory) {
      const appendButton =
        document.createElement("button");

      appendButton.type =
        "button";

      appendButton.className =
        "inline-flex items-center rounded border border-cyan-500/20 px-2 py-1 text-[10px] uppercase tracking-wider text-cyan-300 hover:bg-cyan-500/10 transition";

      appendButton.textContent =
        "append";

      appendButton.dataset.factsMemoryAppend =
        "true";

      appendButton.addEventListener(
        "click",
        function () {
          const storage =
            getFactsMemoryStorage();

          const storageKey =
            String(
              logDiv.dataset.factsMemoryStorageKey
              || ""
            ).trim();

          const appended =
            storage
            && storage.appendFactsMemoryByStorageKey
            && storage.appendFactsMemoryByStorageKey(
              storageKey
            );

          if (!appended) {
            refreshFactsMemoryAppendButtons();
            return;
          }

          meta.facts_memory_session_id =
            appended.session_id || "";

          meta.facts_memory_storage_key =
            appended.storage_key || "";

          logDiv.dataset.factsMemoryStorageKey =
            meta.facts_memory_storage_key;

          normalized.message =
            String(normalized.message || "")
              .replace(
                /^session:\s*.*$/m,
                `session: ${meta.facts_memory_session_id}`
              );

          messageSpan.textContent =
            normalized.message;

          if (
              window.JinRuntime
              && window.JinRuntime.runtime
              && window.JinRuntime.runtime.renderRuntimeMemorySnapshot
          ) {
            window.JinRuntime.runtime.renderRuntimeMemorySnapshot();
          }

          refreshFactsMemoryAppendButtons();
        }
      );

      actions.appendChild(
        appendButton
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

  if (isModelOutput) {
    normalizeLatestModelOutputLogOrder(
      logDiv
    );
  }

  if (normalizedTag.includes("FACTS_MEMORY")) {
    refreshFactsMemoryAppendButtons();
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

window.handleL4LoggerMemoryRestoreResult =
  handleL4MemoryRestoreResult;

window.handleL4MemoryRestoreResult =
  handleL4MemoryRestoreResult;

window.refreshFactsMemoryAppendButtons =
  refreshFactsMemoryAppendButtons;

window.appendLog =
  appendLog;

window.log_user =
  log_user;

window.log_internal_action =
  log_internal_action;

