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

function getInternalActionLogKey(
  actionName,
  data = {}
) {
  const normalizedActionName =
    normalizeInternalActionName(
      actionName
    );
  const keepSkillMarkerSeparate = [
    "APPEND_SKILL",
    "APPEND_SKILLS",
    "REMOVE_SKILL",
    "REMOVE_SKILLS",
  ].includes(normalizedActionName);
  const instanceKey = keepSkillMarkerSeparate
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
  const text =
    String(
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
    "APPEND_SKILL",
    "APPEND_SKILLS",
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

      if (!appendButton) {
        return;
      }

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
        : isPatternResult
        ? "patterns"
        : isSession || isLatestSnapshots || isActiveMemory || isFactsMemory
        ? "show"
        : isSummarizer
        ? "payload"
        : isUser
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
            isPatternResult
              ? "L2 pattern memory"
              : isLatestSnapshots
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

window.refreshFactsMemoryAppendButtons =
  refreshFactsMemoryAppendButtons;

window.appendLog =
  appendLog;

window.log_user =
  log_user;

window.log_internal_action =
  log_internal_action;

