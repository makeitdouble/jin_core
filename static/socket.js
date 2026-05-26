const ws = new WebSocket(
  `ws://${window.location.host}/ws/chat`
);

const chatForm =
  document.getElementById("chat-form");

const userInput =
  document.getElementById("user-input");

const sendButton =
  chatForm.querySelector(
    'button[type="submit"]'
  );


// --------------------------------------------------
// STATE
// --------------------------------------------------

let generationRunning = false;


// --------------------------------------------------
// BUTTON UI
// --------------------------------------------------

function setGenerationState(
  active
) {

  generationRunning =
    active;

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
// BUTTON CLICK
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

  const data = JSON.parse(
    event.data
  );

  handleTelemetryMessage(
    data
  );

  // -----------------------------
  // LOGS
  // -----------------------------

  if (data.type === "log") {

    appendLog(
      data.tag,
      data.message,
      data.details
    );

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

    setGenerationState(
      false
    );

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

ws.onopen = () =>
  appendLog(
    "[SYSTEM]",
    "WebSocket connected."
  );

ws.onclose = () => {

  setGenerationState(
    false
  );

  appendLog(
    "[SYSTEM]",
    "WebSocket disconnected."
  );

};
