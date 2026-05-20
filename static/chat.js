const chatHistory =
  document.getElementById("chat-history");


const streamMessages =
  new Map();


// ESCAPE HTML

function escapeHtml(text) {

  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

}


// ROLE CONFIG

function getRoleConfig(role) {

  switch (role) {

    case "user":
      return {
        avatar: "US",
        bgClass:
          "bg-slate-500 border-slate-400"
      };

    case "service":
      return {
        avatar: "SV",
        bgClass:
          "bg-emerald-950/70 border-emerald-700 shadow-[0_0_12px_rgba(16,185,129,0.08)]"
      };

    case "brain":
    default:
      return {
        avatar: "BR",
        bgClass:
          "bg-zinc-800 border-zinc-600 shadow-[0_0_12px_rgba(255,255,255,0.04)]"
      };

  }

}


// CREATE MESSAGE ELEMENT

function createMessageElement(role) {

  const config =
    getRoleConfig(role);

  const msgDiv =
    document.createElement("div");

  msgDiv.className =
    "flex items-start gap-3 max-w-3xl";

  const pre =
    document.createElement("pre");

  pre.className =
    "text-zinc-50 leading-relaxed whitespace-pre-wrap overflow-x-auto font-mono text-[13px]";

  const bubble =
    document.createElement("div");

  bubble.className =
    `${config.bgClass} px-4 py-3 rounded-xl border shadow-sm`;

  bubble.appendChild(pre);

  msgDiv.innerHTML = `
    <div class="h-6 w-6 rounded bg-zinc-800 border border-zinc-700 flex items-center justify-center text-[10px] text-zinc-400 shrink-0">
      ${config.avatar}
    </div>
  `;

  msgDiv.appendChild(
    bubble
  );

  chatHistory.appendChild(
    msgDiv
  );

  chatHistory.scrollTop =
    chatHistory.scrollHeight;

  return pre;

}


// NORMAL MESSAGE

function appendChatMessage(
  role,
  text
) {

  const pre =
    createMessageElement(role);

  pre.innerHTML =
    escapeHtml(text);

}


// STREAM START

function startStreamMessage(
  messageId,
  role
) {

  streamMessages.set(
    messageId,
    {
      role: role,
      element: null,
      text: "",
    }
  );

}


// STREAM CHUNK

function appendStreamChunk(
  messageId,
  chunk
) {

  const stream =
    streamMessages.get(
      messageId
    );

  if (!stream) {
    return;
  }


// CREATE MESSAGE ONLY
// AFTER FIRST CHUNK

  if (!stream.element) {

    stream.element =
      createMessageElement(
        stream.role
      );

  }


  stream.text += chunk;

  stream.element.innerHTML =
    escapeHtml(
      stream.text
    );

  chatHistory.scrollTop =
    chatHistory.scrollHeight;

}


// STREAM END

function finishStreamMessage(
  messageId
) {

  streamMessages.delete(
    messageId
  );

}


window.appendChatMessage =
  appendChatMessage;

window.startStreamMessage =
  startStreamMessage;

window.appendStreamChunk =
  appendStreamChunk;

window.finishStreamMessage =
  finishStreamMessage;
