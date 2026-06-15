const chatHistory =
  document.getElementById(
    "chat-history"
  );

const streamMessages =
  new Map();

const STREAM_FRAME_WARNING_MS = 12;
const STREAM_NEAR_BOTTOM_PX = 72;

let streamFrameScheduled = false;
const deferredRuntimeActionsAfterResponse = [];

const jinInputLoopState = {
  previousInput: "",
  repeatCount: 0,
};

const SCENE_SEARCH_RUNTIME_ACTION = "web_search";
let sceneSearchFadeTimer = null;

function getSceneRoot() {
  return document.querySelector("main");
}

function setSceneSearchScreenActive(active) {
  const sceneRoot = getSceneRoot();

  if (!sceneRoot) {
    return;
  }

  if (sceneSearchFadeTimer) {
    clearTimeout(sceneSearchFadeTimer);
    sceneSearchFadeTimer = null;
  }

  if (active) {
    sceneRoot.classList.add(
      "scene-searching"
    );
    return;
  }

  sceneRoot.classList.remove(
    "scene-searching"
  );
}

function syncSceneSearchScreenForRuntimeAction(
  action,
  active
) {
  if (
    String(action || "").toLowerCase()
    !== SCENE_SEARCH_RUNTIME_ACTION
  ) {
    return;
  }

  setSceneSearchScreenActive(
    active
  );
}

function normalizeJinLoopInput(text) {

  const raw = String(
    text
    || ""
  ).toLowerCase();

  const normalized = raw.normalize
    ? raw.normalize("NFKC")
    : raw;

  try {
    return normalized.replace(
      /[\p{P}\p{S}\s]+/gu,
      ""
    );
  } catch (error) {
    return normalized.replace(
      /[^a-zа-яёіїєґ0-9]+/gi,
      ""
    );
  }

}

function updateJinInputLoopCounter(text) {

  const normalizedInput =
    normalizeJinLoopInput(
      text
    );

  if (!normalizedInput) {
    jinInputLoopState.previousInput = "";
    jinInputLoopState.repeatCount = 0;

    return {
      repeatCount: 0,
      normalizedInput: "",
    };
  }

  if (
    normalizedInput
    === jinInputLoopState.previousInput
  ) {
    jinInputLoopState.repeatCount += 1;
  } else {
    jinInputLoopState.previousInput = normalizedInput;
    jinInputLoopState.repeatCount = 0;
  }

  return {
    repeatCount: jinInputLoopState.repeatCount,
    normalizedInput,
  };

}

/**
 * @typedef {Object} ContextSnapshot
 * @property {string=} system_prompt
 * @property {string=} user_prompt
 * @property {string=} context_role
 */


// ESCAPE HTML

function escapeHtml(text) {

  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

}

function isStreamDebugEnabled() {

  return Boolean(
    window.jinStreamDebug
    || window.jinDebugMode
  );

}


function nowMs() {

  return (
    window.performance
    && window.performance.now
  )
    ? window.performance.now()
    : Date.now();

}


function requestStreamFrame(callback) {

  if (window.requestAnimationFrame) {
    window.requestAnimationFrame(
      callback
    );

    return;
  }

  setTimeout(
    callback,
    16
  );

}


function shouldAutoScroll() {

  if (!chatHistory) {
    return false;
  }

  const distanceFromBottom =
    chatHistory.scrollHeight
    - chatHistory.scrollTop
    - chatHistory.clientHeight;

  return (
    distanceFromBottom
    <= STREAM_NEAR_BOTTOM_PX
  );

}


function appendTextNodeData(
  element,
  nodeKey,
  text
) {

  if (
    !element
    || !text
  ) {
    return null;
  }

  let textNode =
    element[nodeKey];

  if (!textNode) {
    textNode =
      document.createTextNode(
        ""
      );

    element.appendChild(
      textNode
    );

    element[nodeKey] =
      textNode;
  }

  textNode.appendData(
    text
  );

  return textNode;

}


function scheduleStreamFrameUpdate() {

  if (streamFrameScheduled) {
    return;
  }

  streamFrameScheduled = true;

  requestStreamFrame(
    flushStreamFrame
  );

}


function flushStreamFrame() {

  const startedAt =
    nowMs();

  streamFrameScheduled = false;

  const autoscroll =
    shouldAutoScroll();

  streamMessages.forEach((stream) => {

    if (
      !stream.pendingThinking
      && !stream.pendingAnswer
    ) {
      return;
    }

    ensureStreamGroup(
      stream
    );

    if (stream.pendingThinking) {

      if (
        !stream.group.createdThinking
      ) {

        stream.group.wrapper.appendChild(
          stream.group.thinkWrapper
        );

        stream.group.createdThinking =
          true;

      }

      appendTextNodeData(
        stream.group.thinkContent,
        "__jinThinkTextNode",
        stream.pendingThinking
      );

      stream.pendingThinking =
        "";

    }

    if (stream.pendingAnswer) {

      if (
        !stream.group.createdAnswer
      ) {

        stream.group.wrapper.appendChild(
          stream.group.messageRow
        );

        stream.group.createdAnswer =
          true;

      }

      appendTextNodeData(
        stream.group.answerContent,
        "__jinAnswerTextNode",
        stream.pendingAnswer
      );

      stream.pendingAnswer =
        "";

    }

  });

  if (
    autoscroll
    && chatHistory
  ) {
    chatHistory.scrollTop =
      chatHistory.scrollHeight;
  }

  const elapsed =
    nowMs() - startedAt;

  if (
    isStreamDebugEnabled()
    && elapsed > STREAM_FRAME_WARNING_MS
  ) {
    console.warn(
      "[stream] frame update took",
      `${elapsed.toFixed(1)}ms`
    );
  }

}


// ROLE CONFIG

function getRoleConfig(role) {

  switch (role) {

    case "user":
      return {
        avatar: "US",
        bubbleClass:
          "jin-chat-bubble jin-chat-bubble-user",
        avatarClass:
          "jin-chat-avatar-user"
      };

    case "service":
      return {
        avatar: "SV",
        bubbleClass:
          "jin-chat-bubble jin-chat-bubble-service",
        avatarClass:
          "jin-chat-avatar-service"
      };
      
    case "translator":
      return {
        avatar: "TR",
        bubbleClass:
            "jin-chat-bubble jin-chat-bubble-translator",
        avatarClass:
            "jin-chat-avatar-translator"
      };

    case "brain":
    default:
      return {
        avatar: "BR",
        bubbleClass:
          "jin-chat-bubble jin-chat-bubble-brain",
        avatarClass:
          "jin-chat-avatar-brain"
      };

  }

}

function formatContextSnapshot(
  role,
  contextSnapshot
) {

  /** @type {ContextSnapshot|null} */
  const snapshot =
    contextSnapshot;

  if (!snapshot) {
    return "";
  }

  const systemPrompt =
    snapshot.system_prompt
    || "";

  const userPrompt =
    snapshot.user_prompt
    || "";

  return [
    "SYSTEM PROMPT",
    "-------------",
    systemPrompt || "(empty)",
    "",
    "USER PROMPT / CONTEXT PAYLOAD",
    "-----------------------------",
    userPrompt || "(empty)",
  ].join("\n");

}


function formatContextTitle(
  role,
  contextSnapshot
) {

  /** @type {ContextSnapshot|null} */
  const snapshot =
    contextSnapshot;

  const messageRole =
    String(
      role || "unknown"
    ).toUpperCase();

  const contextRole =
    String(
      (
        snapshot
        && snapshot.context_role
      )
      || role
      || "unknown"
    ).toUpperCase();

  return (
    `MESSAGE: ${messageRole} `
    + `| CONTEXT: ${contextRole}`
  );

}


function createAvatarElement(
  role,
  contextSnapshot = null
) {

  const config =
    getRoleConfig(role);

  const avatar =
    document.createElement(
      contextSnapshot
        ? "button"
        : "div"
    );

  if (contextSnapshot) {
    avatar.type =
      "button";

    avatar.title =
      "show current context";
  }

  avatar.className =
    `jin-chat-avatar ${config.avatarClass || ""}`;

  if (contextSnapshot) {
    avatar.className +=
      " cursor-help transition";
  }

  avatar.textContent =
    config.avatar;

  if (contextSnapshot) {
    avatar.addEventListener(
      "click",
      function () {
        const details =
          formatContextSnapshot(
            role,
            contextSnapshot
          );

        if (window.showTrace) {
          window.showTrace(
            details,
            formatContextTitle(
              role,
              contextSnapshot
            )
          );
        }
      }
    );
  }

  return avatar;

}


// CREATE NORMAL MESSAGE

function createMessageElement(
  role,
  contextSnapshot = null
) {

  const config =
    getRoleConfig(role);

  const msgDiv =
    document.createElement("div");

  msgDiv.className =
    "jin-message-row jin-message-shell mx-auto w-full max-w-4xl";

  const pre =
    document.createElement("pre");

  pre.className =
    "jin-chat-pre";

  const bubble =
    document.createElement("div");

  bubble.className =
    config.bubbleClass;

  bubble.appendChild(pre);

  msgDiv.appendChild(
    createAvatarElement(
      role,
      contextSnapshot
    )
  );

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
  text,
  contextSnapshot = null
) {

  const pre =
    createMessageElement(
      role,
      contextSnapshot
    );

  pre.innerHTML =
    escapeHtml(text);

  flushRuntimeActionsAfterResponse(
    role
  );

}


// RUNTIME ACTION

function appendRuntimeAction(
  action,
  text,
  options = {}
) {

  const actionText =
    String(
      text || ""
    );

  if (!actionText.trim()) {
    return;
  }

  if (options.activateScene !== false) {
    syncSceneSearchScreenForRuntimeAction(
      action,
      true
    );
  }

  const row =
    document.createElement("div");

  row.className =
    "jin-message-row jin-runtime-action-row mx-auto w-full max-w-4xl text-xs text-cyan-100 transition duration-500";

  row.dataset.runtimeAction =
    action || "";

  const icon =
    document.createElement("div");

  icon.className =
    "h-6 w-6 rounded bg-cyan-950/70 border border-cyan-700 flex items-center justify-center text-[12px] shrink-0";

  icon.textContent =
    action === "web_search"
      ? "🔍"
      : "●";

  const label =
    document.createElement("div");

  label.className =
    "px-3 py-2 rounded-lg border border-cyan-700/70 bg-cyan-950/40 font-mono transition duration-500";

  label.textContent =
    actionText;

  row.appendChild(
    icon
  );

  row.appendChild(
    label
  );

  chatHistory.appendChild(
    row
  );

  chatHistory.scrollTop =
    chatHistory.scrollHeight;

}


function queueRuntimeActionAfterNextResponse(
  action,
  text
) {

  const actionText =
    String(
      text || ""
    );

  if (!actionText.trim()) {
    return;
  }

  deferredRuntimeActionsAfterResponse.push({
    action:
      action || "",
    text: actionText,
    completed: false,
  });

}


function isResponseRole(
  role
) {

  return ![
    "user",
    "system",
  ].includes(
    String(role || "").toLowerCase()
  );

}


function flushRuntimeActionsAfterResponse(
  role
) {

  if (
    !isResponseRole(role)
    || !deferredRuntimeActionsAfterResponse.length
  ) {
    return;
  }

  const actions =
    deferredRuntimeActionsAfterResponse.splice(0);

  actions.forEach((entry) => {
    appendRuntimeAction(
      entry.action,
      entry.text,
      {
        activateScene: !entry.completed,
      }
    );

    if (entry.completed) {
      fadeRuntimeAction(
        entry.action
      );
    }
  });

}


function fadeRuntimeAction(
  action
) {

  deferredRuntimeActionsAfterResponse.forEach((entry) => {
    if (entry.action === action) {
      entry.completed = true;
    }
  });

  syncSceneSearchScreenForRuntimeAction(
    action,
    false
  );

  const rows =
    chatHistory.querySelectorAll(
      `[data-runtime-action="${action}"]`
    );

  rows.forEach((row) => {
    row.classList.add(
      "opacity-45"
    );

    row
      .querySelectorAll("div")
      .forEach((element) => {
        element.classList.add(
          "border-zinc-700/50",
          "bg-zinc-900/30",
          "text-zinc-400"
        );
      });
  });

}


// CREATE STREAM GROUP

function createStreamGroup(
  role,
  contextSnapshot = null
) {

  const config =
    getRoleConfig(role);

  const wrapper =
    document.createElement("div");

  wrapper.className =
    "jin-stream-wrapper mx-auto w-full max-w-4xl space-y-3";

  // THINKING

  const thinkWrapper =
    document.createElement("div");

  thinkWrapper.className =
    "jin-think-wrapper";

  const thinkHeader =
    document.createElement("button");

  thinkHeader.className =
    "jin-think-header";

  thinkHeader.innerHTML =
    `▼ &lt;think&gt;`;

  const thinkContent =
    document.createElement("div");

  thinkContent.className =
    "jin-think-content";

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
    "jin-message-row";

  const pre =
    document.createElement("pre");

  pre.className =
    "jin-chat-pre";

  const bubble =
    document.createElement("div");

  bubble.className =
    config.bubbleClass;

  bubble.appendChild(pre);

  messageRow.appendChild(
    createAvatarElement(
      role,
      contextSnapshot
    )
  );

  messageRow.appendChild(
    bubble
  );

  chatHistory.appendChild(
    wrapper
  );

  chatHistory.scrollTop =
    chatHistory.scrollHeight;

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

  // already initialized

  if (
    stream.group.wrapper
    && stream.group.answerContent
    && stream.group.thinkContent
  ) {

    return;

  }

  const realGroup =
    createStreamGroup(
      stream.role,
      stream.context
    );

  stream.group.wrapper =
    realGroup.wrapper;

  stream.group.thinkWrapper =
    realGroup.thinkWrapper;

  stream.group.thinkContent =
    realGroup.thinkContent;

  stream.group.messageRow =
    realGroup.messageRow;

  stream.group.answerContent =
    realGroup.answerContent;

  stream.group.createdThinking =
    false;

  stream.group.createdAnswer =
    false;

}


// STREAM START

function startStreamMessage(
  messageId,
  role,
  contextSnapshot = null
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
      context: contextSnapshot,
      group,
      thinking: "",
      answer: "",
      pendingThinking: "",
      pendingAnswer: "",
    }
  );

}


// THINKING CHUNK

function stripInternalActionMarkers(
  text
) {

  return String(text || "")
    .replace(
      /(^|\n)[^\S\r\n]*<INTERNAL_ACTION_(?:DEEP_THOUGHT|REMEMBER_SESSION|REMEMBER_EVENT)>[^\S\r\n]*(?=\n|$)/gi,
      "$1"
    )
    .replace(
      /(^|\n)[^\S\r\n]*<INTERNAL_ACTION_WEB_SEARCH:[^>\n]*>[^\S\r\n]*(?=\n|$)/gi,
      "$1"
    )
    .replace(
      /\n{3,}/g,
      "\n\n"
    );

}

function collapseAnswerMarkerGap(
  text
) {

  return String(text || "")
    .replace(
      /\n{3,}/g,
      "\n\n"
    );

}

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

  if (
    !stream.thinking
  ) {

    chunk =
      String(chunk || "").replace(
        /^\s+/,
        ""
      );

    if (!chunk) {
      return;
    }

  }

  stream.thinking += chunk;
  stream.pendingThinking += chunk;

  scheduleStreamFrameUpdate();

}


// ANSWER CHUNK

function appendStreamChunk(
  messageId,
  chunk
) {

  if (
    chunk === null
    || chunk === undefined
    || chunk === ""
  ) {
    return;
  }

  const stream =
    streamMessages.get(
      messageId
    );

  if (!stream) {
    return;
  }

  chunk =
    stripInternalActionMarkers(
      chunk
    );

  if (!stream.answer.trim()) {
    chunk =
      chunk.replace(
        /^\s+/,
        ""
      );
  }

  if (!chunk) {
    return;
  }

  stream.answer += chunk;
  stream.pendingAnswer += chunk;

  stream.answer =
    collapseAnswerMarkerGap(
      stream.answer
    );
  stream.pendingAnswer =
    collapseAnswerMarkerGap(
      stream.pendingAnswer
    );

  scheduleStreamFrameUpdate();

}


// STREAM END

function finishStreamMessage(
  messageId
) {

  const stream =
    streamMessages.get(
      messageId
    );

  if (stream) {

    flushStreamFrame();

    if (
      stream.group.createdAnswer
      && !stream.answer.trim()
      && stream.group.messageRow
    ) {
      stream.group.messageRow.remove();
    }

    if (
      stream.group.createdThinking
      && !stream.thinking.trim()
      && stream.group.thinkWrapper
    ) {
      stream.group.thinkWrapper.remove();
    }

    if (
      stream.group.wrapper
      && stream.group.wrapper.childElementCount === 0
    ) {
      stream.group.wrapper.remove();
    }

    if (stream.answer.trim()) {
      flushRuntimeActionsAfterResponse(
        stream.role
      );
    }

  }

  streamMessages.delete(
    messageId
  );

}


window.normalizeJinLoopInput =
  normalizeJinLoopInput;

window.updateJinInputLoopCounter =
  updateJinInputLoopCounter;

window.setSceneSearchScreenActive =
  setSceneSearchScreenActive;

window.appendChatMessage =
  appendChatMessage;

window.appendRuntimeAction =
  appendRuntimeAction;

window.queueRuntimeActionAfterNextResponse =
  queueRuntimeActionAfterNextResponse;

window.fadeRuntimeAction =
  fadeRuntimeAction;

window.startStreamMessage =
  startStreamMessage;

window.appendStreamChunk =
  appendStreamChunk;

window.finishStreamMessage =
  finishStreamMessage;

window.appendThinkingChunk =
  appendThinkingChunk;

window.flushStreamFrame =
  flushStreamFrame;
