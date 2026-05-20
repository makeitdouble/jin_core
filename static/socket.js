const ws = new WebSocket(
  `ws://${window.location.host}/ws/chat`
);

const chatForm =
  document.getElementById("chat-form");

const userInput =
  document.getElementById("user-input");


// AUTO HEIGHT

userInput.addEventListener("input", function () {

  this.style.height = "auto";
  this.style.height =
    this.scrollHeight + "px";

});


// CTRL + ENTER

userInput.addEventListener("keydown", function (e) {

  if (
    e.ctrlKey
    && e.key === "Enter"
  ) {

    e.preventDefault();

    chatForm.requestSubmit();

  }

});


// ROLE RESOLVER

function resolveMessageRole(data) {

  if (data.role) {
    return data.role.toLowerCase();
  }

  return "brain";

}


// WS MESSAGE

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
      data.message
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

    const details =
      data.details
        ? `\n${data.details}`
        : "";

    appendLog(
      "[ERROR]",
      `${data.message}${details}`
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
  // STREAM START
  // -----------------------------

  if (
    data.type
    === "message_start"
  ) {

    startStreamMessage(
      data.message_id,
      resolveMessageRole(data)
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

};


// SEND MESSAGE

chatForm.addEventListener(
  "submit",
  function (e) {

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

    ws.send(JSON.stringify({
      text: text
    }));

    userInput.value = "";

    userInput.style.height =
      "auto";

  }
);


// CONNECTION STATUS

ws.onopen = () =>
  appendLog(
    "[SYSTEM]",
    "WebSocket connected."
  );

ws.onclose = () =>
  appendLog(
    "[SYSTEM]",
    "WebSocket disconnected."
  );
