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

const memoryLayersToggle =
  document.getElementById(
    "memory-layers-toggle"
  );

const websocketClientId =
  window.jinRuntimeSessionId
  || ((window.crypto && window.crypto.randomUUID)
    ? window.crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`);

const websocketReconnectBaseDelay = 700;
const websocketReconnectMaxDelay = 5000;
const websocketReconnectMaxAttempts = 3;

let websocketHasOpened = false;
let ws = null;
let websocketReconnectTimer = null;
let websocketReconnectAttempts = 0;
let websocketReconnectAwaitingFocus = false;
let websocketDisconnectedLogged = false;
let persistedSessionBootstrapSent = false;
let archivedSessionResumeSent = false;
let generationRunning = false;
let socketClientInitialized = false;

window.jinGenerationRunning = false;
window.JinSocketEventHandlers =
  window.JinSocketEventHandlers
  || Object.create(null);

function registerSocketMessageHandler(
  type,
  handler
) {

  const normalizedType =
    String(type || "").trim();

  if (
      !normalizedType
      || typeof handler !== "function"
  ) {
    return false;
  }

  window.JinSocketEventHandlers[normalizedType] =
    handler;

  return true;

}

window.registerSocketMessageHandler =
  registerSocketMessageHandler;

registerSocketMessageHandler(
  "attached_files_update",
  function (data) {
    if (window.JinFiles && typeof window.JinFiles.applySnapshot === "function") {
      window.JinFiles.applySnapshot(data || {});
    }
  }
);

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

  if (
      window.JinRuntime
      && window.JinRuntime.anonymousMode
      && typeof window.JinRuntime.anonymousMode.isEnabled === "function"
      && window.JinRuntime.anonymousMode.isEnabled()
  ) {
    params.set(
      "anonymous_mode",
      "1"
    );
  }

  return `ws://${window.location.host}/ws/chat?${params.toString()}`;

}

window.isJinGenerationRunning = function () {

  return Boolean(
    generationRunning
  );

};

function focusJinUserInput(
  options = {}
) {

  if (
    !userInput
    || generationRunning
    || document.visibilityState === "hidden"
  ) {
    return false;
  }

  try {
    userInput.focus({
      preventScroll: options.preventScroll !== false,
    });
  } catch (error) {
    userInput.focus();
  }

  return true;

}

window.focusJinUserInput =
  focusJinUserInput;

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

window.sendSocketMessage = sendSocketMessage;

window.sendRuntimeMemoryDeleteSlot = function (payload) {
  const key = String(
    payload
    && payload.key || ""
  ).trim();

  if (!key) {
    return false;
  }

  return sendSocketMessage({
    type: "runtime_memory_delete_slot",
    key,
    line: String(
      payload
      && payload.line || ""
    ).trim(),
    index: Number(
      payload
      && payload.index || 0
    ),
  });
};

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

  if (
      websocketReconnectTimer
      || isWebSocketOpen()
      || (
          ws
          && ws.readyState === WebSocket.CONNECTING
      )
  ) {
    return;
  }

  if (
      websocketReconnectAttempts
      >= websocketReconnectMaxAttempts
  ) {
    websocketReconnectAwaitingFocus = true;
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

      if (
          isWebSocketOpen()
          || (
              ws
              && ws.readyState === WebSocket.CONNECTING
          )
      ) {
        return;
      }

      connectWebSocket();
    },
    delay
  );

}

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

  if (!active) {
    requestAnimationFrame(
      () => {
        focusJinUserInput({
          preventScroll: true,
        });
      }
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

function clearInterruptedRuntimeGlow() {

  if (window.cancelPanelGlows) {
    window.cancelPanelGlows();
  }

}

window.clearInterruptedRuntimeGlow =
  clearInterruptedRuntimeGlow;

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

  clearInterruptedRuntimeGlow();

  if (window.releaseActiveStreamAvatar) {
    window.releaseActiveStreamAvatar();
  }

  setGenerationState(
    false
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

function requestArchivedSessionResume(
  bootstrap
) {
  if (
      archivedSessionResumeSent
      || !bootstrap
  ) {
    return false;
  }

  const sourceSessionId =
    String(
      bootstrap.source_session_id
      || ""
    ).trim();

  if (!sourceSessionId) {
    return false;
  }

  const resumePayload = {
    type: "archived_session_resume",
    source_session_id: sourceSessionId,
  };

  if (
    window.JinPanels
    && typeof window.JinPanels.getRuntimeAvatarSnapshot === "function"
  ) {
    resumePayload.runtime_avatar =
      window.JinPanels.getRuntimeAvatarSnapshot();
  }

  const sent = sendSocketMessage(
    resumePayload
  );

  if (sent) {
    archivedSessionResumeSent = true;
    appendLog(
      "[SESSION]",
      `Restoring conversation flow from ${sourceSessionId}.`
    );
  }

  return sent;
}


function handleSocketMessage(event) {

  /** @type {SocketMessage} */
  let data;

  try {
    data = JSON.parse(
      event.data
    );
  } catch (error) {
    appendLog(
      "[ERROR]",
      "Invalid WebSocket message.",
      String(error && error.message || error || "")
    );

    return;
  }

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

  const handler =
    window.JinSocketEventHandlers[
      String(data.type || "")
    ];

  if (typeof handler === "function") {
    handler(
      data
    );
  }

}

async function handleSocketOpen() {

  window.jinWebSocketConnected = true;

  clearWebSocketReconnectTimer();

  websocketReconnectAttempts = 0;
  websocketReconnectAwaitingFocus = false;
  websocketDisconnectedLogged = false;

  const isSoftReconnect =
    websocketHasOpened;

  websocketHasOpened = true;

  appendLog(
    "[SYSTEM]",
    "WebSocket connected."
  );

  if (window.JinFiles && typeof window.JinFiles.syncContext === "function") {
    window.JinFiles.syncContext();
  }

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

    syncDelayedMemoryReportsToRuntime();
    if (typeof window.syncFactsMemoryToRuntime === "function") {
      window.syncFactsMemoryToRuntime();
    }
    if (typeof window.syncLongTermMemoryToRuntime === "function") {
      window.syncLongTermMemoryToRuntime();
    }

    return;
  }

  if (
      persistedSessionBootstrapSent
      || !window.getPersistedSessionBootstrap
  ) {
    syncDelayedMemoryReportsToRuntime();
    if (typeof window.syncFactsMemoryToRuntime === "function") {
      window.syncFactsMemoryToRuntime();
    }
    if (typeof window.syncLongTermMemoryToRuntime === "function") {
      window.syncLongTermMemoryToRuntime();
    }
    return;
  }

  if (window.jinArchivedSessionRestoreReady) {
    try {
      await window.jinArchivedSessionRestoreReady;
    } catch (error) {
      // Archived restore is optional. A failed restore falls back to normal boot.
    }
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
      "Browser session snapshot sent."
    );

    if (
        bootstrap.archived_session_restore === true
        && window.JinRuntime
        && window.JinRuntime.runtime
        && typeof window.JinRuntime.runtime.replaceLoadedDelayedMemoryReportIds
          === "function"
    ) {
      // A fresh websocket can publish its default delayed-memory load state
      // before the archived bootstrap is sent. Clear that transient state so
      // the following store sync cannot accidentally feed a report body into
      // the hidden restore turn. The backend keeps the archived ids staged.
      window.JinRuntime.runtime.replaceLoadedDelayedMemoryReportIds(
        [],
        { render: false }
      );
    }

    syncDelayedMemoryReportsToRuntime();
    if (typeof window.syncFactsMemoryToRuntime === "function") {
      window.syncFactsMemoryToRuntime();
    }
    if (typeof window.syncLongTermMemoryToRuntime === "function") {
      window.syncLongTermMemoryToRuntime();
    }

    // WebSocket messages are ordered: bootstrap -> memory/L4 sync -> hidden
    // restore tick. The first model turn therefore sees restored stores but the
    // context builder can intentionally suppress their heavy contents.
    requestArchivedSessionResume(
      bootstrap
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

  if (
      window.JinRuntime
      && window.JinRuntime.runtime
      && window.JinRuntime.runtime.getActiveMemoryRecords
  ) {
    sendSocketMessage({
      type: "active_memory_store_sync",
      active_memory_records:
        window.JinRuntime.runtime.getActiveMemoryRecords(),
    });
  }

  syncDelayedMemoryReportsToRuntime();
  if (typeof window.syncFactsMemoryToRuntime === "function") {
    window.syncFactsMemoryToRuntime();
  }
  if (typeof window.syncLongTermMemoryToRuntime === "function") {
    window.syncLongTermMemoryToRuntime();
  }

}

function handleSocketClose() {

  window.jinWebSocketConnected = false;

  clearInterruptedRuntimeGlow();

  if (window.releaseActiveStreamAvatar) {
    window.releaseActiveStreamAvatar();
  }

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
    return false;
  }

  const socket =
    new WebSocket(
      buildWebSocketUrl()
    );

  ws = socket;

  socket.onmessage =
    handleSocketMessage;

  socket.onopen = function () {
    if (ws !== socket) {
      return;
    }

    void handleSocketOpen();
  };

  socket.onclose = function () {
    if (ws !== socket) {
      return;
    }

    ws = null;
    handleSocketClose();
  };

  socket.onerror = function () {
    clearInterruptedRuntimeGlow();

    if (ws === socket) {
      socket.close();
    }
  };

  return true;

}

window.connectWebSocket = connectWebSocket;

function retryWebSocketOnFocus() {

  if (
      isWebSocketOpen()
      || (
          ws
          && ws.readyState === WebSocket.CONNECTING
      )
  ) {
    return;
  }

  if (!websocketReconnectAwaitingFocus) {
    return;
  }

  clearWebSocketReconnectTimer();
  websocketReconnectAttempts = 0;
  websocketReconnectAwaitingFocus = false;
  connectWebSocket();

}

window.addEventListener(
  "focus",
  retryWebSocketOnFocus
);

document.addEventListener(
  "visibilitychange",
  function () {
    if (!document.hidden) {
      retryWebSocketOnFocus();
    }
  }
);

async function initializeSocketClient() {

  if (socketClientInitialized) {
    return;
  }

  socketClientInitialized = true;

  if (
      window.JinRuntime
      && window.JinRuntime.anonymousMode
      && window.JinRuntime.anonymousMode.ready
  ) {
    try {
      await window.JinRuntime.anonymousMode.ready;
    } catch (error) {
      // Detection failure falls back to normal mode.
    }
  }

  if (typeof logOtherLatestRuntimeMemorySnapshots === "function") {
    logOtherLatestRuntimeMemorySnapshots();
  }

  if (typeof logActiveMemoryRecords === "function") {
    logActiveMemoryRecords();
  }

  if (typeof logFactsMemoryRecords === "function") {
    logFactsMemoryRecords();
  }

  // Archived restore owns the initial Runtime Memory page. Wait until the
  // RESTORE API has painted PREVIOUS_RUNTIME_STATE before opening the socket,
  // otherwise the server's brand-new-session L1 can race it and briefly/
  // permanently become page 0 or page 1. The restore promise always resolves
  // to payload/null, so a failed archive fetch still falls through to normal
  // websocket bootstrap instead of blocking the client.
  if (window.jinArchivedSessionRestoreReady) {
    try {
      await window.jinArchivedSessionRestoreReady;
    } catch (error) {
      // Normal websocket boot remains the fallback.
    }
  }

  connectWebSocket();

}

if (document.readyState === "loading") {
  document.addEventListener(
    "DOMContentLoaded",
    initializeSocketClient,
    { once: true }
  );
} else {
  window.setTimeout(
    initializeSocketClient,
    0
  );
}
