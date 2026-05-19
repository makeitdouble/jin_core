const ws = new WebSocket(`ws://${window.location.host}/ws/chat`);

const chatForm =
  document.getElementById("chat-form");

const userInput =
  document.getElementById("user-input");


// AUTO HEIGHT

userInput.addEventListener("input", function () {

  this.style.height = "auto";
  this.style.height = this.scrollHeight + "px";

});


// CTRL + ENTER

userInput.addEventListener("keydown", function (e) {

  if (e.ctrlKey && e.key === "Enter") {

    e.preventDefault();
    chatForm.requestSubmit();

  }

});


// WS MESSAGE

ws.onmessage = function (event) {

  console.log("RAW WS:", event.data);

  const data = JSON.parse(event.data);

  console.log("PARSED WS:", data);

  handleTelemetryMessage(data);

  if (data.type === "log") {

    appendLog(data.tag, data.message);
    return;

  }

  if (data.type === "message") {

    const role =
      resolveMessageRole(data);

    appendChatMessage(
      role,
      data.text
    );

  }

};


// ROLE RESOLVER

function resolveMessageRole(data) {

  // backend explicit role
  if (data.role) {
    return data.role.toLowerCase();
  }

  // service-as-brain mode
  if (
    data.brain &&
    data.service &&
    data.brain.model === data.service.model
  ) {
    return "service";
  }

  return "brain";

}


// SEND MESSAGE

chatForm.addEventListener("submit", function (e) {

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
  userInput.style.height = "auto";

});


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

console.log("WS CONNECTED");
