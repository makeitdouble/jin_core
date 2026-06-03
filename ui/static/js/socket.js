const ws = new WebSocket(
  `ws://${window.location.host}/ws/chat`
);

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

function startMemoryGlow() {
  const panel = document.getElementById("settings-panel");
  if (!panel) return;

  panel.classList.add("memory-updating");

  setTimeout(() => {
    panel.classList.add("memory-pulse");
  }, 2000);
}

function stopMemoryGlow() {
  const panel = document.getElementById("settings-panel");
  if (!panel) return;

  panel.classList.remove("memory-pulse");
  panel.classList.add("memory-fading");

  setTimeout(() => {
    panel.classList.remove("memory-updating");
    panel.classList.remove("memory-fading");
  }, 2000);
}

function startL2MemoryGlow() {
  const panel = document.getElementById("settings-panel");
  if (!panel) return;

  panel.classList.add("memory-l2-updating");

  setTimeout(() => {
    panel.classList.add("memory-l2-pulse");
  }, 2000);
}

function stopL2MemoryGlow() {
  const panel = document.getElementById("settings-panel");
  if (!panel) return;

  panel.classList.remove("memory-l2-pulse");
  panel.classList.add("memory-l2-fading");

  setTimeout(() => {
    panel.classList.remove("memory-l2-updating");
    panel.classList.remove("memory-l2-fading");
  }, 2000);
}

function startL3MemoryGlow() {
  const panel = document.getElementById("settings-panel");
  if (!panel) return;

  panel.classList.add("memory-l3-updating");

  setTimeout(() => {
    panel.classList.add("memory-l3-pulse");
  }, 2000);
}

function stopL3MemoryGlow() {
  const panel = document.getElementById("settings-panel");
  if (!panel) return;

  panel.classList.remove("memory-l3-pulse");
  panel.classList.add("memory-l3-fading");

  setTimeout(() => {
    panel.classList.remove("memory-l3-updating");
    panel.classList.remove("memory-l3-fading");
  }, 2000);
}

// --------------------------------------------------
// STATE
// --------------------------------------------------

let generationRunning = false;

/**
 * @typedef {Object} SocketMessage
 * @property {string} type
 * @property {string=} role
 * @property {string=} text
 * @property {string=} message_id
 * @property {string=} chunk
 * @property {Object=} context
 * @property {string=} action
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

  ws.send(JSON.stringify({
    type: "abort"
  }));

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

ws.onmessage = function (event) {

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

  // -----------------------------
  // LOGS
  // -----------------------------

  if (data.type === "log") {

    appendLog(
      data.tag,
      data.message,
      data.details
    );

    if (
        data.tag === "[SYSTEM]" &&
        data.message === "[WS] agent runtime end"
    ) {
      startMemoryGlow();
    }

    if (
        data.tag === "[SUMMARIZER]" &&
        data.message
        && data.message.includes("[MEMORY] L2 summarizer request")
    ) {
      startL2MemoryGlow();
    }

    if (
        data.tag === "[SUMMARIZER]" &&
        data.message
        && data.message.includes("[MEMORY] L3 session summarizer request")
    ) {
      startL3MemoryGlow();
    }

    if (
        data.message
        && data.message.includes("[MEMORY]")
        && !data.message.includes("[MEMORY] L2 memory")
        && (
            data.message.includes("updated")
            || data.message.includes("skipped")
            || data.message.includes("failed")
        )
    ) {
      stopMemoryGlow();
    }

    if (
        data.message
        && data.message.includes("[MEMORY] L2 memory")
        && (
            data.message.includes("updated")
            || data.message.includes("skipped")
            || data.message.includes("failed")
        )
    ) {
      stopL2MemoryGlow();
    }

    if (
        data.message
        && data.message.includes("[MEMORY] L3 session memory")
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

    if (data.action === "remember_session") {
      startL3MemoryGlow();
    }

    appendRuntimeAction(
      data.action,
      data.text
    );

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

    setGenerationState(
      false
    );

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

    return;

  }

};


// --------------------------------------------------
// SEND MESSAGE
// --------------------------------------------------

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

    appendChatMessage(
      "user",
      text
    );

    setGenerationState(
      true
    );

    ws.send(JSON.stringify({
      text: text
    }));

    userInput.value = "";

    userInput.style.height =
      "auto";

  }
);


// --------------------------------------------------
// CONNECTION STATUS
// --------------------------------------------------

ws.onopen = () => {

  appendLog(
    "[SYSTEM]",
    "WebSocket connected."
  );

  if (!window.getPersistedSessionBootstrap) {
    return;
  }

  const bootstrap =
    window.getPersistedSessionBootstrap();

  if (!bootstrap) {
    return;
  }

  ws.send(
    JSON.stringify(
      bootstrap
    )
  );

  appendLog(
    "[SYSTEM]",
    "Browser session memory sent."
  );

};

ws.onclose = () => {

  setGenerationState(
    false
  );

  appendLog(
    "[SYSTEM]",
    "WebSocket disconnected."
  );

};
