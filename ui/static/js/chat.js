const chatHistory =
  document.getElementById(
    "chat-history"
  );

const streamMessages =
  new Map();

const STREAM_FRAME_WARNING_MS = 12;
const STREAM_NEAR_BOTTOM_PX = 72;

function isChatRenderForeground() {

  const visible =
    document.visibilityState !== "hidden";

  let focused = true;

  if (typeof document.hasFocus === "function") {
    try {
      focused = document.hasFocus();
    } catch (error) {
      focused = true;
    }
  }

  return visible && focused;

}

function queueChatMicrotask(callback) {

  if (typeof window.queueMicrotask === "function") {
    window.queueMicrotask(
      callback
    );

    return;
  }

  Promise.resolve().then(
    callback
  );

}

let streamFrameScheduled = false;
const jinInputLoopState = {
  previousInput: "",
  repeatCount: 0,
};

let jinConversationTurnCounter = 0;
window.jinConversationTurnCounter =
  jinConversationTurnCounter;

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
      repeated: 0,
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

  const repeated =
    jinInputLoopState.repeatCount > 0
      ? jinInputLoopState.repeatCount + 1
      : 0;

  return {
    repeatCount: jinInputLoopState.repeatCount,
    repeated,
    normalizedInput,
  };

}

/**
 * @typedef {Object} ContextSnapshot
 * @property {string=} system_prompt
 * @property {string=} visible_system_prompt
 * @property {string=} user_prompt
 * @property {string=} context_role
 * @property {boolean=} hide_internal_action_rules
 * @property {boolean=} preserve_runtime_action_markers
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

  // requestAnimationFrame may stop completely while the browser window is
  // unfocused or occluded. In that state, flush in a microtask so websocket
  // events keep their DOM order and runtime action rows can update normally.
  if (!isChatRenderForeground()) {
    queueChatMicrotask(
      callback
    );

    return;
  }

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

      updateThinkExpandedHeight(
        stream.group.thinkContent
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


function flushStreamFrameForVisibilityChange() {

  if (!streamFrameScheduled) {
    return;
  }

  flushStreamFrame();

}

window.addEventListener(
  "blur",
  flushStreamFrameForVisibilityChange
);

window.addEventListener(
  "focus",
  flushStreamFrameForVisibilityChange
);

document.addEventListener(
  "visibilitychange",
  flushStreamFrameForVisibilityChange
);


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
          "jin-chat-bubble jin-chat-bubble-service jin-chat-bubble-rateable",
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
          "jin-chat-bubble jin-chat-bubble-brain jin-chat-bubble-rateable",
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

  const hideInternalActionRules =
    Boolean(
      snapshot.hide_internal_action_rules
    );

  const systemPrompt =
    (
      hideInternalActionRules
      && snapshot.visible_system_prompt
    )
    || snapshot.system_prompt
    || "";

  const userPrompt =
    snapshot.user_prompt
    || "";

  return [
    hideInternalActionRules
      ? "SYSTEM PROMPT (INTERNAL ACTION RULES HIDDEN)"
      : "SYSTEM PROMPT",
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

  msgDiv.dataset.role =
    role;

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

function createMessageAttachmentChips(
  attachments = []
) {
  if (!Array.isArray(attachments) || !attachments.length) {
    return null;
  }

  const container =
    document.createElement("div");

  container.className =
    "mt-3 flex flex-wrap gap-2";

  attachments.forEach((attachment) => {
    const chip =
      document.createElement("button");
    const label =
      formatAttachmentChipLabel(
        attachment
      );

    chip.type =
      "button";
    chip.className =
      "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded border border-sky-400/25 bg-sky-950/35 p-0 text-[18px] leading-none text-sky-100 transition hover:border-sky-300/50 hover:bg-sky-900/45";
    chip.textContent =
      getAttachmentChipEmoji(
        attachment
      );
    chip.setAttribute(
      "aria-label",
      label
    );

    bindJinAttachmentBubble(
      chip,
      attachment
    );

    container.appendChild(
      chip
    );
  });

  return container;
}

function appendChatMessage(
  role,
  text,
  contextSnapshot = null,
  attachments = []
) {

  const pre =
    createMessageElement(
      role,
      contextSnapshot
    );

  pre.innerHTML =
    escapeHtml(text);

  if (role === "user") {
    const chips =
      createMessageAttachmentChips(
        attachments
      );

    if (chips && pre.parentElement) {
      pre.parentElement.appendChild(
        chips
      );
    }
  }

  if (role === "user") {
    jinConversationTurnCounter += 1;
    window.jinConversationTurnCounter =
      jinConversationTurnCounter;
  }

  flushRuntimeActionsAfterResponse(
    role
  );

}
// CREATE STREAM GROUP

function updateThinkExpandedHeight(
  thinkContent
) {

  if (!thinkContent) {
    return;
  }

  thinkContent.style.setProperty(
    "--jin-think-expanded-height",
    `${thinkContent.scrollHeight}px`
  );

}

let thinkResizeFrame = null;

window.addEventListener(
  "resize",
  () => {

    if (thinkResizeFrame) {
      return;
    }

    thinkResizeFrame = requestAnimationFrame(
      () => {

        thinkResizeFrame = null;

        document
          .querySelectorAll(
            ".jin-think-content"
          )
          .forEach(
            updateThinkExpandedHeight
          );

      }
    );

  }
);

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

  const thinkContent =
    document.createElement("div");

  thinkContent.className =
    "jin-think-content";

  thinkContent.setAttribute(
    "role",
    "button"
  );

  thinkContent.setAttribute(
    "tabindex",
    "0"
  );

  thinkContent.setAttribute(
    "aria-expanded",
    "true"
  );

  thinkContent.setAttribute(
    "aria-label",
    "Toggle thinking block"
  );

  let collapsed = false;

  const setCollapsed = (nextCollapsed) => {

    collapsed =
      nextCollapsed;

    thinkContent.classList.toggle(
      "is-collapsed",
      collapsed
    );

    thinkContent.setAttribute(
      "aria-expanded",
      collapsed
        ? "false"
        : "true"
    );

  };

  thinkContent.addEventListener(
    "click",
    () => {
      setCollapsed(
        !collapsed
      );
    }
  );

  thinkContent.addEventListener(
    "keydown",
    (event) => {

      if (
        event.key !== "Enter"
        && event.key !== " "
      ) {
        return;
      }

      event.preventDefault();

      setCollapsed(
        !collapsed
      );

    }
  );

  [
    "mouseenter",
    "mouseleave",
  ].forEach((eventName) => {
    thinkContent.addEventListener(
      eventName,
      () => {
        window.JinThinkCitations.syncThinkRuntimeCitationHighlight(
          thinkContent
        );
      }
    );
  });

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

  stream.group.thinkContent.dataset.thinkId =
    stream.messageId;

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
      messageId,
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
      /(^|\n)[^\S\r\n]*<(?:INTERNAL_ACTION_)?SAVE_SESSION>[^\S\r\n]*(?=\n|$)/gi,
      "$1"
    )
    .replace(
      /(^|\n)[^\S\r\n]*<(?:INTERNAL_ACTION_)?WEB_SEARCH:[^>\n]*>[^\S\r\n]*(?=\n|$)/gi,
      "$1"
    )
    .replace(
      /(^|\n)[^\S\r\n]*<(?:INTERNAL_ACTION_)?LIST_SKILLS(?::[^>\n]*)?>[^\S\r\n]*(?=\n|$)/gi,
      "$1"
    )
    .replace(
      /(^|\n)[^\S\r\n]*<(?:INTERNAL_ACTION_)?APPEND_SKILLS?:[^>\n]*>[^\S\r\n]*(?=\n|$)/gi,
      "$1"
    )
    .replace(
      /(^|\n)[^\S\r\n]*<(?:INTERNAL_ACTION_)?REMOVE_SKILLS?:[^>\n]*>[^\S\r\n]*(?=\n|$)/gi,
      "$1"
    )
    .replace(
      /(^|\n)[^\S\r\n]*<(?:INTERNAL_ACTION_)?ASSET_ACTION>[\s\S]*?<\/(?:INTERNAL_ACTION_)?ASSET_ACTION>[^\S\r\n]*(?=\n|$)/gi,
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

  const preserveRuntimeActionMarkers =
    Boolean(
      stream.context
      && stream.context.preserve_runtime_action_markers
    );

  if (!preserveRuntimeActionMarkers) {
    chunk =
      stripInternalActionMarkers(
        chunk
      );
  }

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

    window.JinThinkCitations.startThinkRuleCitationAnalysis(
      messageId,
      stream
    );

  }

  streamMessages.delete(
    messageId
  );

}
window.normalizeJinLoopInput =
  normalizeJinLoopInput;

window.updateJinInputLoopCounter =
  updateJinInputLoopCounter;
window.appendChatMessage =
  appendChatMessage;
window.stripInternalActionMarkers =
  stripInternalActionMarkers;

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
