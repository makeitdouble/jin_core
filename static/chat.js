const chatHistory =
  document.getElementById(
    "chat-history"
  );

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


// CREATE NORMAL MESSAGE

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


// CREATE STREAM GROUP

function createStreamGroup(
  role
) {

  const config =
    getRoleConfig(role);

  const wrapper =
    document.createElement("div");

  wrapper.className =
    "space-y-3 max-w-4xl";

  // THINKING

  const thinkWrapper =
    document.createElement("div");

  thinkWrapper.className =
    "space-y-2";

  const thinkHeader =
    document.createElement("button");

  thinkHeader.className =
    "text-xs text-zinc-300 flex items-center gap-2 hover:text-zinc-100 transition";

  thinkHeader.innerHTML =
    `▼ &lt;think&gt;`;

  const thinkContent =
    document.createElement("div");

  thinkContent.className =
    "border-l border-slate-500 pl-4 text-xs text-zinc-300 italic leading-relaxed whitespace-pre-wrap";

  let collapsed = false;

  thinkHeader.onclick = () => {

    collapsed =
      !collapsed;

    thinkContent.style.display =
      collapsed
        ? "none"
        : "block";

    thinkHeader.innerHTML =
      collapsed
        ? `▶ &lt;think&gt;`
        : `▼ &lt;think&gt;`;

  };

  thinkWrapper.appendChild(
    thinkHeader
  );

  thinkWrapper.appendChild(
    thinkContent
  );

  // ANSWER

  const messageRow =
    document.createElement("div");

  messageRow.className =
    "flex items-start gap-3";

  const pre =
    document.createElement("pre");

  pre.className =
    "text-zinc-50 leading-relaxed whitespace-pre-wrap overflow-x-auto font-mono text-[13px]";

  const bubble =
    document.createElement("div");

  bubble.className =
    `${config.bgClass} px-4 py-3 rounded-xl border shadow-sm`;

  bubble.appendChild(pre);

  messageRow.innerHTML = `
    <div class="h-6 w-6 rounded bg-zinc-800 border border-zinc-700 flex items-center justify-center text-[10px] text-zinc-400 shrink-0">
      ${config.avatar}
    </div>
  `;

  messageRow.appendChild(
    bubble
  );

  chatHistory.appendChild(
    wrapper
  );

  return {
    wrapper,
    thinkWrapper,
    thinkContent,
    messageRow,
    answerContent: pre,
  };

}


// ENSURE STREAM GROUP

function ensureStreamGroup(
  stream
) {

  if (stream.group.wrapper) {
    return;
  }

  const realGroup =
    createStreamGroup(
      stream.role
    );

  stream.group = {
    ...stream.group,
    ...realGroup,
  };

}


// STREAM START

function startStreamMessage(
  messageId,
  role
) {

  const group = {
    createdThinking: false,
    createdAnswer: false,
    wrapper: null,
    thinkWrapper: null,
    thinkContent: null,
    messageRow: null,
    answerContent: null,
  };

  streamMessages.set(
    messageId,
    {
      role,
      group,
      thinking: "",
      answer: "",
    }
  );

}


// THINKING CHUNK

function appendThinkingChunk(
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

  ensureStreamGroup(
    stream
  );

  if (
    !stream.group.createdThinking
  ) {

    stream.group.wrapper.appendChild(
      stream.group.thinkWrapper
    );

    stream.group.createdThinking =
      true;

  }

  stream.thinking += chunk;

  stream.group.thinkContent.innerHTML =
    escapeHtml(
      stream.thinking
    );

  chatHistory.scrollTop =
    chatHistory.scrollHeight;

}


// ANSWER CHUNK

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

  ensureStreamGroup(
    stream
  );

  if (
    !stream.group.createdAnswer
  ) {

    stream.group.wrapper.appendChild(
      stream.group.messageRow
    );

    stream.group.createdAnswer =
      true;

  }

  stream.answer += chunk;

  stream.group.answerContent.innerHTML =
    escapeHtml(
      stream.answer
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

window.appendThinkingChunk =
  appendThinkingChunk;
