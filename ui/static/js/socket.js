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

const websocketReconnectBaseDelay = 700;
const websocketReconnectMaxDelay = 5000;

let websocketHasOpened = false;
let ws = null;
let websocketReconnectTimer = null;
let websocketReconnectAttempts = 0;
let websocketDisconnectedLogged = false;
let persistedSessionBootstrapSent = false;
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

    syncDelayedMemoryReportsToRuntime();

    return;
  }

  if (
      persistedSessionBootstrapSent
      || !window.getPersistedSessionBootstrap
  ) {
    syncDelayedMemoryReportsToRuntime();
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

    syncDelayedMemoryReportsToRuntime();

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

  syncDelayedMemoryReportsToRuntime();

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

window.connectWebSocket = connectWebSocket;

function initializeSocketClient() {

  if (socketClientInitialized) {
    return;
  }

  socketClientInitialized = true;

  if (typeof logOtherLatestRuntimeMemorySnapshots === "function") {
    logOtherLatestRuntimeMemorySnapshots();
  }

  if (typeof logActiveMemoryRecords === "function") {
    logActiveMemoryRecords();
  }

  if (typeof logFactsMemoryRecords === "function") {
    logFactsMemoryRecords();
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
