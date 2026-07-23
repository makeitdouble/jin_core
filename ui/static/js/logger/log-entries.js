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
      isActiveMemory || isFactsMemory
        ? "inline-flex items-center rounded border border-zinc-600/40 px-2 py-1 text-[10px] uppercase tracking-wider text-zinc-300 hover:bg-zinc-700/40 transition"
        : isSummarizer
        ? "mt-2 inline-flex items-center rounded border border-blue-500/20 px-2 py-1 text-[10px] uppercase tracking-wider text-blue-300 hover:bg-blue-500/10 transition"
        : isSession || isLatestSnapshots
        ? "inline-flex items-center rounded border border-cyan-500/20 px-2 py-1 text-[10px] uppercase tracking-wider text-cyan-300 hover:bg-cyan-500/10 transition"
        : "mt-2 inline-flex items-center rounded border border-red-500/20 px-2 py-1 text-[10px] uppercase tracking-wider text-red-300 hover:bg-red-500/10 transition";

    traceButton.textContent =
      isPatternResult
        ? "patterns"
        : isSession || isLatestSnapshots || isActiveMemory || isFactsMemory
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
              : isFactsMemory
              ? `Facts memory · ${String(meta?.facts_memory_session_id || "session")}`
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
                && storage.clearSessionSignalsByStorageKey
                && storageKey
            ) {
              storage.clearSessionSignalsByStorageKey(
                storageKey
              );

              if (
                  storage.getSessionSignalsStorageKey
                  && storageKey === storage.getSessionSignalsStorageKey()
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

