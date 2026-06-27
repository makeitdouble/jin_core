const chatForm =
  document.getElementById("chat-form");

const userInput =
  document.getElementById("user-input");

const stopIndicator =
  document.getElementById("stop-indicator");

const sendButton =
  chatForm.querySelector(
    'button[type="submit"]'
  );

const factCheckTrigger =
  document.getElementById(
    "fact-check-trigger"
  );

const websocketClientId =
  window.jinRuntimeSessionId
  || ((window.crypto && window.crypto.randomUUID)
    ? window.crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`);

let websocketHasOpened = false;

function buildWebSocketUrl() {

  const params =
    new URLSearchParams({
      client_id: websocketClientId,
    });

  if (websocketHasOpened) {
    params.set(
      "resume",
      "soft"
    );
  }

  return `ws://${window.location.host}/ws/chat?${params.toString()}`;

}

const websocketReconnectBaseDelay = 700;
const websocketReconnectMaxDelay = 5000;

let ws = null;
let websocketReconnectTimer = null;
let websocketReconnectAttempts = 0;
let websocketDisconnectedLogged = false;
let persistedSessionBootstrapSent = false;
let latestRuntimeSnapshotsLogged = false;
let activeMemoryRecordsLogged = false;

const MEMORY_GLOW_CLASSES = [
  "memory-updating",
  "memory-pulse",
  "memory-fading",
  "memory-l2-updating",
  "memory-l2-pulse",
  "memory-l2-fading",
  "memory-l3-updating",
  "memory-l3-pulse",
  "memory-l3-fading",
];

const MEMORY_GLOW_STAGES = {
  l1: {
    active: "memory-updating",
    pulse: "memory-pulse",
    fading: "memory-fading",
  },
  l2: {
    active: "memory-l2-updating",
    pulse: "memory-l2-pulse",
    fading: "memory-l2-fading",
  },
  l3: {
    active: "memory-l3-updating",
    pulse: "memory-l3-pulse",
    fading: "memory-l3-fading",
  },
};

function buildLatestRuntimeSnapshotsDetails(
  snapshots
) {

  const lines = [
    "current_runtime_session_id: "
      + String(window.jinRuntimeSessionId || websocketClientId),
    "",
    "current_key: "
      + String(
        window.getCurrentLatestRuntimeMemoryStorageKey
          ? window.getCurrentLatestRuntimeMemoryStorageKey()
          : ""
      ),
  ];

  snapshots.forEach(
    function (
      snapshot,
      index,
    ) {
      const runtimeMemory =
        String(snapshot.runtime_memory || "")
          .replace(/\\n/g, "\n")
          .replace(
            /;\s+(?=[a-z][a-z0-9_]*\s*:)/g,
            "\n"
          )
          .split(/\r?\n+/)
          .map(function (line) {
            return line.trim();
          })
          .filter(Boolean);

      lines.push(
        "",
        `[ snapshot ${index + 1} ]`,
        "",
        `key: ${snapshot.key || ""}`,
        "",
        `key_session_id: ${snapshot.key_session_id || ""}`,
        "",
        `session_id: ${snapshot.session_id || ""}`,
        "",
        `saved_at: ${snapshot.saved_at || ""}`,
        "",
        `runtime_memory_updates: ${snapshot.runtime_memory_updates || 0}`
      );

      if (runtimeMemory.length) {
        lines.push(
          "",
          "runtime_memory:",
          "",
          runtimeMemory.join("\n\n")
        );
      }
    }
  );

  return lines.join("\n");

}

function logOtherLatestRuntimeMemorySnapshots() {

  if (
      latestRuntimeSnapshotsLogged
      || !window.getOtherLatestRuntimeMemorySnapshots
  ) {
    return;
  }

  const snapshots =
    window.getOtherLatestRuntimeMemorySnapshots();

  if (!snapshots.length) {
    return;
  }

  latestRuntimeSnapshotsLogged = true;

  appendLog(
    "[LATEST SNAPSHOTS]",
    `${snapshots.length} stale latest runtime snapshot`
      + `${snapshots.length === 1 ? "" : "s"} found.`,
    buildLatestRuntimeSnapshotsDetails(
      snapshots
    )
  );

}


function getActiveMemoryRecordsForStartupLog() {

  if (
      !window.JinRuntime
      || !window.JinRuntime.runtime
      || !window.JinRuntime.runtime.getActiveMemoryRecords
  ) {
    return [];
  }

  return window.JinRuntime.runtime.getActiveMemoryRecords();

}


function buildActiveMemoryDetails(
  records
) {

  const lines = [
    `count: ${records.length}`,
  ];

  records.forEach(
    function (
      record,
      index,
    ) {
      lines.push(
        "",
        `[ active memory ${index + 1} ]`,
        "",
        String(record || "")
      );
    }
  );

  return lines.join("\n");

}


function logActiveMemoryRecords() {

  if (activeMemoryRecordsLogged) {
    return;
  }

  const records =
    getActiveMemoryRecordsForStartupLog();

  if (!records.length) {
    return;
  }

  activeMemoryRecordsLogged = true;

  appendLog(
    "[ACTIVE_MEMORY]",
    `count: ${records.length}`,
    buildActiveMemoryDetails(
      records
    )
  );

}


function isMemoryLog(data) {
  return Boolean(
    data
    && (
        String(data.tag || "").includes("MEMORY:")
        || String(data.message || "").includes("[MEMORY]")
    )
  );
}

function memoryLogIncludes(data, text) {
  return Boolean(
    data
    && (
        String(data.message || "").includes(text)
        || String(data.message || "").includes(`[MEMORY] ${text}`)
        || String(data.message || "").includes(`[MEMORY:L1] ${text}`)
        || String(data.message || "").includes(`[MEMORY:L2] ${text}`)
        || String(data.message || "").includes(`[MEMORY:L3] ${text}`)
    )
  );
}

let activeMemoryGlowStage = "";
let memoryGlowPulseTimer = null;
let memoryGlowFadeTimer = null;

let factCheckGlowActive = false;
let factCheckGlowPulseTimer = null;
let factCheckGlowFadeTimer = null;

function getMemoryPanel() {
  return document.getElementById("settings-panel");
}

function clearFactCheckGlowTimers() {
  if (factCheckGlowPulseTimer) {
    clearTimeout(factCheckGlowPulseTimer);
    factCheckGlowPulseTimer = null;
  }

  if (factCheckGlowFadeTimer) {
    clearTimeout(factCheckGlowFadeTimer);
    factCheckGlowFadeTimer = null;
  }
}

function startFactCheckGlow() {
  const panel = getMemoryPanel();

  if (!panel) {
    return;
  }

  clearFactCheckGlowTimers();
  factCheckGlowActive = true;

  panel.classList.remove(
    "fact-check-fading"
  );

  panel.classList.add(
    "fact-check-running"
  );

  factCheckGlowPulseTimer = setTimeout(() => {
    if (
      !factCheckGlowActive
      || !panel.classList.contains("fact-check-running")
    ) {
      return;
    }

    panel.classList.add(
      "fact-check-pulse"
    );
  }, 900);
}

function stopFactCheckGlow() {
  const panel = getMemoryPanel();

  if (!panel) {
    return;
  }

  clearFactCheckGlowTimers();
  factCheckGlowActive = false;

  panel.classList.remove(
    "fact-check-pulse"
  );

  if (!panel.classList.contains("fact-check-running")) {
    return;
  }

  panel.classList.add(
    "fact-check-fading"
  );

  factCheckGlowFadeTimer = setTimeout(() => {
    if (factCheckGlowActive) {
      return;
    }

    panel.classList.remove(
      "fact-check-running",
      "fact-check-fading"
    );
  }, 1200);
}

function clearMemoryGlowTimers() {
  if (memoryGlowPulseTimer) {
    clearTimeout(memoryGlowPulseTimer);
    memoryGlowPulseTimer = null;
  }

  if (memoryGlowFadeTimer) {
    clearTimeout(memoryGlowFadeTimer);
    memoryGlowFadeTimer = null;
  }
}

function clearMemoryGlowClasses(panel) {
  panel.classList.remove(
    ...MEMORY_GLOW_CLASSES
  );
}

function setMemoryGlowStage(stage) {
  const panel = getMemoryPanel();
  const config = MEMORY_GLOW_STAGES[stage];

  if (
    !panel
    || !config
  ) {
    return;
  }

  clearMemoryGlowTimers();
  clearMemoryGlowClasses(panel);

  activeMemoryGlowStage = stage;

  panel.classList.add(
    config.active
  );

  memoryGlowPulseTimer = setTimeout(() => {
    if (
      activeMemoryGlowStage !== stage
      || !panel.classList.contains(config.active)
    ) {
      return;
    }

    panel.classList.add(
      config.pulse
    );
  }, 2200);
}

function stopMemoryGlowStage(stage) {
  const panel = getMemoryPanel();
  const config = MEMORY_GLOW_STAGES[stage];

  if (
    !panel
    || !config
    || activeMemoryGlowStage !== stage
  ) {
    return;
  }

  clearMemoryGlowTimers();

  activeMemoryGlowStage = "";

  panel.classList.remove(
    config.pulse
  );

  panel.classList.add(
    config.fading
  );

  memoryGlowFadeTimer = setTimeout(() => {
    if (activeMemoryGlowStage) {
      return;
    }

    panel.classList.remove(
      config.active,
      config.fading
    );
  }, 1800);
}

function startMemoryGlow() {
  setMemoryGlowStage("l1");
}

function stopMemoryGlow() {
  stopMemoryGlowStage("l1");
}

function startL2MemoryGlow() {
  setMemoryGlowStage("l2");
}

function stopL2MemoryGlow() {
  stopMemoryGlowStage("l2");
}

function startL3MemoryGlow() {
  setMemoryGlowStage("l3");
}

function stopL3MemoryGlow() {
  stopMemoryGlowStage("l3");
}

window.startMemoryGlow = startMemoryGlow;
window.stopMemoryGlow = stopMemoryGlow;
window.startL2MemoryGlow = startL2MemoryGlow;
window.stopL2MemoryGlow = stopL2MemoryGlow;
window.startL3MemoryGlow = startL3MemoryGlow;
window.stopL3MemoryGlow = stopL3MemoryGlow;
window.startFactCheckGlow = startFactCheckGlow;
window.stopFactCheckGlow = stopFactCheckGlow;

// --------------------------------------------------
// STATE
// --------------------------------------------------

let generationRunning = false;

window.jinGenerationRunning = false;

window.isJinGenerationRunning = function () {

  return Boolean(
    generationRunning
  );

};


function isWebSocketOpen() {
  return (
    ws
    && ws.readyState === WebSocket.OPEN
  );
}

function sendSocketMessage(
  payload
) {

  if (!isWebSocketOpen()) {
    return false;
  }

  ws.send(
    JSON.stringify(
      payload
    )
  );

  return true;

}

function triggerManualFactCheck() {

  if (!isWebSocketOpen()) {
    connectWebSocket();

    appendLog(
      "[SYSTEM]",
      "WebSocket reconnecting. Fact check was not started."
    );

    return false;
  }

  appendLog(
    "[MEMORY:FACT_CHECK]",
    "manual fact check requested"
  );

  const sent = sendSocketMessage({
    type: "fact_check"
  });

  if (sent) {
    startFactCheckGlow();
  }

  return sent;

}

window.triggerManualFactCheck = triggerManualFactCheck;


function clearWebSocketReconnectTimer() {

  if (!websocketReconnectTimer) {
    return;
  }

  clearTimeout(
    websocketReconnectTimer
  );

  websocketReconnectTimer = null;

}

function scheduleWebSocketReconnect() {

  if (websocketReconnectTimer) {
    return;
  }

  websocketReconnectAttempts += 1;

  const delay =
    Math.min(
      websocketReconnectMaxDelay,
      websocketReconnectBaseDelay
      * websocketReconnectAttempts
    );

  websocketReconnectTimer = setTimeout(
    function () {
      websocketReconnectTimer = null;
      connectWebSocket();
    },
    delay
  );

}

/**
 * @typedef {Object} SocketMessage
 * @property {string} type
 * @property {string=} role
 * @property {string=} text
 * @property {string=} message_id
 * @property {string=} chunk
 * @property {Object=} context
 * @property {string=} action
 * @property {string=} status
 * @property {string=} id
 * @property {string=} query
 * @property {*=} payload
 * @property {string=} tag
 * @property {string=} message
 * @property {string=} details
 */


// --------------------------------------------------
// BUTTON UI
// --------------------------------------------------

function setGenerationState(
  active
) {

  generationRunning =
    active;

  window.jinGenerationRunning =
    Boolean(active);

  if (typeof window.dispatchEvent === "function") {
    window.dispatchEvent(
      new CustomEvent(
        "jin:generation-state-changed",
        {
          detail: {
            active: Boolean(active),
          },
        }
      )
    );
  }

  userInput.readOnly =
    active;

  chatForm.setAttribute(
    "aria-busy",
    active
      ? "true"
      : "false"
  );

  chatForm.classList.toggle(
    "cursor-pointer",
    active
  );

  chatForm.classList.toggle(
    "border-red-400/80",
    active
  );

  chatForm.classList.toggle(
    "bg-red-950/35",
    active
  );

  chatForm.classList.toggle(
    "shadow-[0_0_0_1px_rgba(248,113,113,0.25)]",
    active
  );

  userInput.classList.toggle(
    "placeholder-red-200/70",
    active
  );

  userInput.classList.toggle(
    "text-red-100",
    active
  );

  userInput.classList.toggle(
    "cursor-pointer",
    active
  );

  userInput.classList.toggle(
    "caret-transparent",
    active
  );

  if (stopIndicator) {
    stopIndicator.classList.toggle(
      "hidden",
      !active
    );

    stopIndicator.classList.toggle(
      "flex",
      active
    );
  }

  if (!sendButton) {
    return;
  }

  if (active) {

    sendButton.innerHTML =
      "■";

    sendButton.classList.add(
      "bg-red-500/20",
      "hover:bg-red-500/30",
      "border-red-500/30",
      "text-red-200",
    );

  } else {

    sendButton.innerHTML =
      "⮞";

    sendButton.classList.remove(
      "bg-red-500/20",
      "hover:bg-red-500/30",
      "border-red-500/30",
      "text-red-200",
    );

  }

}


// --------------------------------------------------
// ABORT
// --------------------------------------------------

function abortGeneration() {

  if (!generationRunning) {
    return;
  }

  sendSocketMessage({
    type: "abort"
  });

  appendLog(
    "[SYSTEM]",
    "Generation aborted."
  );

  setGenerationState(
    false
  );

}


// --------------------------------------------------
// AUTO HEIGHT
// --------------------------------------------------

userInput.addEventListener(
  "input",
  function () {

    this.style.height =
      "auto";

    this.style.height =
      this.scrollHeight + "px";

  }
);


// --------------------------------------------------
// KEYBOARD
// --------------------------------------------------

userInput.addEventListener(
  "keydown",
  function (e) {

    if (e.key !== "Enter") {
      return;
    }

    // -----------------------------------------
    // CTRL+ENTER / SHIFT+ENTER
    // -----------------------------------------

    if (
      e.ctrlKey
      || e.shiftKey
    ) {

      e.preventDefault();

      const start =
        this.selectionStart;

      const end =
        this.selectionEnd;

      const value =
        this.value;

      this.value =
        value.substring(0, start)
        + "\n"
        + value.substring(end);

      this.selectionStart =
        this.selectionEnd =
          start + 1;

      this.dispatchEvent(
        new Event("input")
      );

      return;

    }

    // -----------------------------------------
    // NORMAL ENTER
    // -----------------------------------------

    e.preventDefault();

    // -----------------------------------------
    // STOP
    // -----------------------------------------

    if (generationRunning) {

      abortGeneration();

      return;

    }

    // -----------------------------------------
    // SEND
    // -----------------------------------------

    chatForm.requestSubmit();

  }
);

// --------------------------------------------------
// STOP AREA CLICK
// --------------------------------------------------

chatForm.addEventListener(
  "click",
  function (e) {

    if (!generationRunning) {
      return;
    }

    e.preventDefault();

    abortGeneration();

  }
);


// HIDDEN BUTTON CLICK
// --------------------------------------------------

if (sendButton) {

  sendButton.addEventListener(
    "click",
    function (e) {

      if (!generationRunning) {
        return;
      }

      e.preventDefault();

      abortGeneration();

    }
  );

}


// ROLE RESOLVER

function resolveMessageRole(data) {

  if (data.role) {
    return data.role.toLowerCase();
  }

  return "brain";

}


// --------------------------------------------------
// WS MESSAGE
// --------------------------------------------------

function handleSocketMessage(event) {

  /** @type {SocketMessage} */
  const data = JSON.parse(
    event.data
  );

  if (window.handleTelemetryMessage) {
    window.handleTelemetryMessage(
      data
    );
  }

  if (window.handleRuntimeMemoryMessage) {
    window.handleRuntimeMemoryMessage(
      data
    );
  }

  if (
    data.type
    === "active_memory_records_update"
  ) {

    if (
        window.JinRuntime
        && window.JinRuntime.runtime
        && window.JinRuntime.runtime.replaceActiveMemoryRecords
    ) {
      window.JinRuntime.runtime.replaceActiveMemoryRecords(
        data.active_memory_records || []
      );
    }

    return;

  }

  if (data.type === "fact_check_state") {
    if (data.active) {
      startFactCheckGlow();
    } else {
      stopFactCheckGlow();
    }

    return;
  }

  if (data.type === "fact_check_update") {
    stopFactCheckGlow();
  }

  // -----------------------------
  // LOGS
  // -----------------------------

  if (data.type === "log") {

    if (
        data.tag === "[USER]"
        && window.log_user
    ) {
      let payload =
        data.details || data.message || "";

      try {
        payload = JSON.parse(
          payload
        );
      } catch (_error) {
        payload = {
          text: String(
            data.message || ""
          ),
        };
      }

      window.log_user(
        payload
      );

      return;
    }

    appendLog(
      data.tag,
      data.message,
      data.details,
      data
    );

    if (
        isMemoryLog(data)
        && memoryLogIncludes(data, "L1 summarizer request")
    ) {
      startMemoryGlow();
    }

    if (
        isMemoryLog(data)
        && memoryLogIncludes(data, "L2 summarizer request")
    ) {
      startL2MemoryGlow();
    }

    if (
        isMemoryLog(data)
        && memoryLogIncludes(data, "L3 session summarizer request")
    ) {
      startL3MemoryGlow();
    }

    if (
        isMemoryLog(data)
        && !memoryLogIncludes(data, "L2 memory")
        && !memoryLogIncludes(data, "L3 session memory")
        && (
            data.message.includes("updated")
            || data.message.includes("skipped")
            || data.message.includes("failed")
        )
    ) {
      stopMemoryGlow();
    }

    if (
        isMemoryLog(data)
        && memoryLogIncludes(data, "L2 memory")
        && (
            data.message.includes("updated")
            || data.message.includes("skipped")
            || data.message.includes("failed")
        )
    ) {
      stopL2MemoryGlow();
    }

    if (
        isMemoryLog(data)
        && memoryLogIncludes(data, "L3 session memory")
        && (
            data.message.includes("updated")
            || data.message.includes("skipped")
            || data.message.includes("failed")
        )
    ) {
      stopL3MemoryGlow();
    }

    return;

  }

  // -----------------------------
  // ERRORS
  // -----------------------------

  if (
    data.type === "error"
    || data.type === "fatal_error"
    || data.type === "websocket_error"
  ) {

    setGenerationState(
      false
    );

    appendLog(
      "[ERROR]",
      data.message,
      data.details
    );

    stopFactCheckGlow();

    return;

  }

  // -----------------------------
  // NORMAL MESSAGE
  // -----------------------------

  if (data.type === "message") {

    const role =
      resolveMessageRole(data);

    appendChatMessage(
      role,
      data.text,
      data.context || null
    );

    return;

  }

  // -----------------------------
  // RUNTIME ACTION
  // -----------------------------

  if (
    data.type
    === "runtime_action"
  ) {

    const action =
      String(
        data.action || ""
      ).toLowerCase();

    const status =
      String(
        data.status || ""
      ).toLowerCase();

    const text =
      String(
        data.text || ""
      );

    if (
      action === "create_active_memory"
      && data.active_memory
      && window.JinRuntime
      && window.JinRuntime.runtime
      && window.JinRuntime.runtime.appendActiveMemoryRecords
    ) {
      window.JinRuntime.runtime.appendActiveMemoryRecords([
        data.active_memory
      ]);

    }

    if (
      action === "resolve_active_memory"
      && data.id
      && window.JinRuntime
      && window.JinRuntime.runtime
      && window.JinRuntime.runtime.removeActiveMemoryRecordById
    ) {
      window.JinRuntime.runtime.removeActiveMemoryRecordById(
        data.id
      );
    }

    if (
      status === "completed"
      || status === "complete"
      || status === "done"
    ) {
      if (window.fadeRuntimeAction) {
        window.fadeRuntimeAction(
          action
        );
      }

      return;
    }

    if (!text.trim()) {
      return;
    }

    const appended = appendRuntimeAction(
      action,
      text,
      {
        id: data.id || "",
      }
    );

    if (
      appended
      && window.log_internal_action
    ) {
      window.log_internal_action(
        action,
        data
      );
    }

    return;

  }

  // -----------------------------
  // THINKING STREAM
  // -----------------------------

  if (
    data.type
    === "thinking_chunk"
  ) {

    appendThinkingChunk(
      data.message_id,
      data.chunk
    );

    return;

  }

  // -----------------------------
  // AGENT RUNTIME START
  // -----------------------------

  if (
    data.type
    === "agent_runtime_start"
  ) {

    setGenerationState(
      true
    );

    return;

  }

  // -----------------------------
  // AGENT RUNTIME END
  // -----------------------------

  if (
    data.type
    === "agent_runtime_end"
  ) {

    if (window.flushRuntimeTelemetryRender) {
      window.flushRuntimeTelemetryRender({
        final: true
      });
    }

    setGenerationState(
      false
    );

    window.jinActiveTurnUserIdleSeconds = 0;

    if (window.jinResetUserIdleTimer) {
      window.jinResetUserIdleTimer();
    }

    return;

  }

  // -----------------------------
  // STREAM START
  // -----------------------------

  if (
    data.type
    === "message_start"
  ) {

    setGenerationState(
      true
    );

    startStreamMessage(
      data.message_id,
      resolveMessageRole(data),
      data.context || null
    );

    return;

  }

  // -----------------------------
  // STREAM CHUNK
  // -----------------------------

  if (
    data.type
    === "message_chunk"
  ) {

    appendStreamChunk(
      data.message_id,
      data.chunk
    );

    return;

  }

  // -----------------------------
  // STREAM END
  // -----------------------------

  if (
    data.type
    === "message_end"
  ) {

    finishStreamMessage(
      data.message_id
    );

    if (window.flushRuntimeTelemetryRender) {
      window.flushRuntimeTelemetryRender({
        final: true
      });
    }

    return;

  }

  // -----------------------------
  // STREAM ERROR
  // -----------------------------

  if (
    data.type
    === "message_error"
  ) {

    setGenerationState(
      false
    );

    appendLog(
      "[VALIDATOR]",
      data.text
    );

    finishStreamMessage(
      data.message_id
    );

    if (window.flushRuntimeTelemetryRender) {
      window.flushRuntimeTelemetryRender({
        final: true
      });
    }

    return;

  }

}


// --------------------------------------------------
// SEND MESSAGE
// --------------------------------------------------

function allModelRuntimesOffline() {

  const status =
    (
      window.jinRuntimeConfig
      && window.jinRuntimeConfig.runtimeStatus
    )
    || {};

  return (
    status.brain === false
    && status.service === false
  );

}

if (factCheckTrigger) {
  factCheckTrigger.addEventListener(
    "click",
    (event) => {
      event.preventDefault();
      event.stopPropagation();
      triggerManualFactCheck();
    }
  );
}

chatForm.addEventListener(
  "submit",
  function (e) {

    // -----------------------------------------
    // BLOCK SUBMIT WHEN STREAMING
    // -----------------------------------------

    if (generationRunning) {

      e.preventDefault();

      abortGeneration();

      return;

    }

    e.preventDefault();

    const text =
      userInput.value.trim();

    if (!text) {
      return;
    }

    if (allModelRuntimesOffline()) {

      appendLog(
        "[ERROR]",
        "All model runtimes are offline."
      );

      setGenerationState(
        false
      );

      return;

    }

    if (!isWebSocketOpen()) {

      connectWebSocket();

      appendLog(
        "[SYSTEM]",
        "WebSocket reconnecting. Try sending again in a moment."
      );

      return;

    }

    if (window.prepareRuntimeMemoryForUserMessage) {
      window.prepareRuntimeMemoryForUserMessage(
        text
      );
    }

    if (window.startJinAnswerRatingL1GateForTurn) {
      window.startJinAnswerRatingL1GateForTurn();
    }

    appendChatMessage(
      "user",
      text
    );

    if (window.markSessionActivityDirty) {
      window.markSessionActivityDirty();
    }

    setGenerationState(
      true
    );

    const pendingLastResponseRating =
      window.consumePendingLastResponseRating
        ? window.consumePendingLastResponseRating()
        : null;

    const payload = {
      text: text,
    };

    const inputLoopContext =
      window.updateJinInputLoopCounter
        ? window.updateJinInputLoopCounter(
            text
          )
        : null;

    if (inputLoopContext) {
      payload.runtime_pattern_counter =
        inputLoopContext.repeatCount;
      payload.runtime_repeated_input_count =
        inputLoopContext.repeated || 0;
    }

    const userIdleContext =
      window.getJinUserIdleContext
        ? window.getJinUserIdleContext()
        : null;

    if (userIdleContext) {
      payload.user_idle =
        userIdleContext.user_idle;
      payload.user_idle_seconds =
        userIdleContext.user_idle_seconds;
      payload.user_idle_paused =
        userIdleContext.user_idle_paused;

      if (window.freezeLatestRuntimeMemoryUserIdle) {
        window.freezeLatestRuntimeMemoryUserIdle(
          userIdleContext.user_idle
        );
      }
    }

    window.jinActiveTurnUserIdleSeconds =
      userIdleContext
        ? Number(userIdleContext.user_idle_seconds || 0)
        : 0;

    if (pendingLastResponseRating) {
      payload.pending_last_response_rating = pendingLastResponseRating;
    }

    if (
        window.JinRuntime
        && window.JinRuntime.runtime
        && window.JinRuntime.runtime.getActiveMemoryRecords
    ) {
      payload.active_memory_records =
        window.JinRuntime.runtime.getActiveMemoryRecords();
    }

    sendSocketMessage(payload);

    if (window.jinFreezeUserIdleTimerAtSeconds) {
      window.jinFreezeUserIdleTimerAtSeconds(
        window.jinActiveTurnUserIdleSeconds
      );
    }

    userInput.value = "";

    userInput.style.height =
      "auto";

  }
);


async function handleSocketOpen() {

  window.jinWebSocketConnected = true;

  clearWebSocketReconnectTimer();

  websocketReconnectAttempts = 0;
  websocketDisconnectedLogged = false;

  const isSoftReconnect =
    websocketHasOpened;

  websocketHasOpened = true;

  appendLog(
    "[SYSTEM]",
    "WebSocket connected."
  );

  if (isSoftReconnect) {
    if (window.getSoftReconnectRuntimeResume) {
      const runtimeResume =
        window.getSoftReconnectRuntimeResume();

      if (runtimeResume) {
        if (
            window.JinRuntime
            && window.JinRuntime.runtime
            && window.JinRuntime.runtime.getActiveMemoryRecords
        ) {
          runtimeResume.active_memory_records =
            window.JinRuntime.runtime.getActiveMemoryRecords();
        }

        sendSocketMessage(
          runtimeResume
        );
      }
    }

    return;
  }

  if (
      persistedSessionBootstrapSent
      || !window.getPersistedSessionBootstrap
  ) {
    return;
  }

  if (window.jinSavedRuntimeFallbackReady) {
    try {
      await window.jinSavedRuntimeFallbackReady;
    } catch (error) {
      // File fallback is optional. Browser memory still works.
    }
  }

  if (
      !ws
      || ws.readyState !== WebSocket.OPEN
  ) {
    return;
  }

  const bootstrap =
    window.getPersistedSessionBootstrap();

  if (bootstrap) {
    if (
        window.JinRuntime
        && window.JinRuntime.runtime
        && window.JinRuntime.runtime.getActiveMemoryRecords
    ) {
      bootstrap.active_memory_records =
        window.JinRuntime.runtime.getActiveMemoryRecords();
    }

    sendSocketMessage(
      bootstrap
    );

    if (window.applyPersistedSessionBootstrap) {
      window.applyPersistedSessionBootstrap(
        bootstrap
      );
    }

    persistedSessionBootstrapSent = true;

    appendLog(
      "[SYSTEM]",
      "Browser session memory sent."
    );

    return;
  }

  if (window.getInitialRuntimeMemoryBootstrap) {
    const runtimeBootstrap =
      window.getInitialRuntimeMemoryBootstrap();

    if (runtimeBootstrap) {
      if (
          window.JinRuntime
          && window.JinRuntime.runtime
          && window.JinRuntime.runtime.getActiveMemoryRecords
      ) {
        runtimeBootstrap.active_memory_records =
          window.JinRuntime.runtime.getActiveMemoryRecords();
      }

      sendSocketMessage(
        runtimeBootstrap
      );

      appendLog(
        "[SYSTEM]",
        "Latest runtime memory sent."
      );
    }
  }

}


function handleSocketClose() {

  window.jinWebSocketConnected = false;

  setGenerationState(
    false
  );

  if (!websocketDisconnectedLogged) {
    websocketDisconnectedLogged = true;

    appendLog(
      "[SYSTEM]",
      "WebSocket disconnected. Reconnecting..."
    );
  }

  scheduleWebSocketReconnect();

}


function connectWebSocket() {

  if (
      ws
      && (
          ws.readyState === WebSocket.OPEN
          || ws.readyState === WebSocket.CONNECTING
      )
  ) {
    return;
  }

  ws =
    new WebSocket(
      buildWebSocketUrl()
    );

  ws.onmessage =
    handleSocketMessage;

  ws.onopen =
    handleSocketOpen;

  ws.onclose =
    handleSocketClose;

  ws.onerror = function () {
    if (ws) {
      ws.close();
    }
  };

}


logOtherLatestRuntimeMemorySnapshots();
logActiveMemoryRecords();
connectWebSocket();
