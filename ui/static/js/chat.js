const chatHistory =
  document.getElementById(
    "chat-history"
  );
const chatInputShell =
  document.getElementById(
    "chat-input-shell"
  );

const streamMessages =
  new Map();

const STREAM_AVATAR_LEFT_PX = 54;
const STREAM_AVATAR_SIZE_PX = 28;
const STREAM_AVATAR_HANDOFF_MS = 260;
const STREAM_AVATAR_LAYOUT_TRACK_MS = 340;
let activeStreamAvatarStream = null;

const STREAM_FRAME_WARNING_MS = 12;
const STREAM_NEAR_BOTTOM_PX = 72;
const MEMORY_REFERENCE_HIGHLIGHT_EVENT =
  "jin:memory-reference-highlight";

let liveUserTurnAnchor = null;
let keepLiveUserTurnAtTop = false;
let expandedReasoningFollowStream = null;
let expandedReasoningFollowFrame = null;
let jinThinkCollapsedPreference = true;


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

  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

}

function renderChatTextHtml(text) {

  const source =
    String(
      text || ""
    );
  const markerPattern =
    /<(JIN_COLOR|JIN_SIZE)\s*>([\s\S]*?)<\/\1\s*>/gi;
  let rendered = "";
  let lastIndex = 0;
  let match = null;

  while ((match = markerPattern.exec(source)) !== null) {
    rendered += escapeHtml(
      source.slice(
        lastIndex,
        match.index
      )
    );
    if (
      String(match[1] || "").toUpperCase() === "JIN_COLOR"
      && window.JinResponseFormatter
      && typeof window.JinResponseFormatter.buildJinColorMarkerHtml === "function"
    ) {
      rendered += window.JinResponseFormatter.buildJinColorMarkerHtml(
        match[2]
      );
    } else if (
      String(match[1] || "").toUpperCase() === "JIN_SIZE"
      && window.JinResponseFormatter
      && typeof window.JinResponseFormatter.buildJinSizeMarkerHtml === "function"
    ) {
      rendered += window.JinResponseFormatter.buildJinSizeMarkerHtml(
        match[2]
      );
    } else {
      rendered += escapeHtml(
        match[0]
      );
    }
    lastIndex =
      markerPattern.lastIndex;
  }

  rendered += escapeHtml(
    source.slice(
      lastIndex
    )
  );

  return rendered;

}

function isJinMemoryReferenceRole(role) {
  return (
    role === "brain"
    || role === "service"
  );
}

function dispatchJinMemoryReferenceHighlight(
  source,
  text,
  active = true
) {
  window.dispatchEvent(
    new CustomEvent(
      MEMORY_REFERENCE_HIGHLIGHT_EVENT,
      {
        detail: {
          source,
          text: String(text || ""),
          active: Boolean(active),
        },
      }
    )
  );
}

function clearLatestJinMemoryReferenceText() {
  if (
    window.JinThinkCitations
    && typeof window.JinThinkCitations.resetThinkCitationHighlightTurn === "function"
  ) {
    window.JinThinkCitations.resetThinkCitationHighlightTurn();
  }

  dispatchJinMemoryReferenceHighlight(
    "persistent",
    "",
    false
  );
}

function setLatestJinMemoryReferenceText(
  role,
  text
) {
  if (!isJinMemoryReferenceRole(role)) {
    return;
  }

  dispatchJinMemoryReferenceHighlight(
    "persistent",
    text,
    true
  );
}

function shouldFormatChatRole(role) {

  return (
    role !== "user"
    && window.JinResponseFormatter
    && window.JinResponseFormatter.isEnabled
    && window.JinResponseFormatter.isEnabled()
  );

}

function renderChatTextElement(
  element,
  text,
  options = {}
) {

  if (!element) {
    return;
  }

  const format =
    Boolean(
      options.format
    );

  element.classList.toggle(
    "jin-chat-markdown",
    format
  );
  element.dataset.memoryReferenceText =
    String(text || "");

  element.innerHTML =
    (
      format
      && window.JinResponseFormatter
      && window.JinResponseFormatter.render
    )
      ? window.JinResponseFormatter.render(
        text
      )
      : renderChatTextHtml(
        text
      );

  if (
    window.JinChatReferenceIds
    && typeof window.JinChatReferenceIds.decorate === "function"
  ) {
    window.JinChatReferenceIds.decorate(
      element
    );
  }

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

function getChatHistoryTopGap() {

  if (!chatHistory) {
    return 0;
  }

  const styles =
    window.getComputedStyle(
      chatHistory
    );

  return (
    Number.parseFloat(
      styles.paddingTop
    )
    || 0
  );

}

function getChatInputOverlaySpace() {

  if (!chatInputShell) {
    return 0;
  }

  return Math.ceil(
    chatInputShell.getBoundingClientRect().height
    || 0
  );

}


function updateChatInputOverlaySpace() {

  if (!chatHistory) {
    return;
  }

  const overlaySpace =
    getChatInputOverlaySpace();

  if (!overlaySpace) {
    chatHistory.style.removeProperty(
      "--chat-input-overlay-space"
    );
    return;
  }

  chatHistory.style.setProperty(
    "--chat-input-overlay-space",
    `${overlaySpace}px`
  );

}


function updateLiveUserTurnBottomSpace() {

  if (!chatHistory) {
    return;
  }

  updateChatInputOverlaySpace();

  if (
    !liveUserTurnAnchor
    || !liveUserTurnAnchor.isConnected
  ) {
    chatHistory.style.removeProperty(
      "--jin-live-turn-bottom-space"
    );

    return;
  }

  const metrics =
    getLiveUserTurnViewportMetrics();

  if (!metrics) {
    chatHistory.style.removeProperty(
      "--jin-live-turn-bottom-space"
    );

    return;
  }

  chatHistory.style.setProperty(
    "--jin-live-turn-bottom-space",
    `${Math.ceil(metrics.bottomSpace)}px`
  );

}


function getLiveUserTurnViewportMetrics() {

  if (
    !chatHistory
    || !liveUserTurnAnchor
    || !liveUserTurnAnchor.isConnected
  ) {
    return null;
  }

  const anchorRect =
    liveUserTurnAnchor.getBoundingClientRect();

  let tailBottom =
    anchorRect.bottom;

  let sibling =
    liveUserTurnAnchor.nextElementSibling;

  while (sibling) {
    if (!sibling.hidden) {
      const rect =
        sibling.getBoundingClientRect();

      tailBottom =
        Math.max(
          tailBottom,
          rect.bottom
        );
    }

    sibling =
      sibling.nextElementSibling;
  }

  const edgeGap =
    getChatHistoryTopGap();

  const occupiedHeight =
    Math.max(
      0,
      tailBottom - anchorRect.top
    );

  const availableHeight =
    Math.max(
      0,
      chatHistory.clientHeight
      - edgeGap
      - edgeGap
      - getChatInputOverlaySpace()
    );

  const bottomSpace =
    Math.max(
      0,
      availableHeight - occupiedHeight
    );

  return {
    anchorRect,
    bottomSpace,
    overflow:
      Math.max(
        0,
        occupiedHeight - availableHeight
      ),
  };

}


function liveUserTurnReachedViewportBottom() {

  if (
    !keepLiveUserTurnAtTop
    || !chatHistory
  ) {
    return false;
  }

  const metrics =
    getLiveUserTurnViewportMetrics();

  return Boolean(
    metrics
    && metrics.bottomSpace <= 1
  );

}


function scrollLiveUserTurnToTop() {

  if (
    !chatHistory
    || !liveUserTurnAnchor
    || !liveUserTurnAnchor.isConnected
  ) {
    return;
  }

  const metrics =
    getLiveUserTurnViewportMetrics();

  if (!metrics) {
    return;
  }

  updateLiveUserTurnBottomSpace();

  const historyRect =
    chatHistory.getBoundingClientRect();

  const anchorRect =
    metrics.anchorRect;

  const targetTop =
    chatHistory.scrollTop
    + anchorRect.top
    - historyRect.top
    - getChatHistoryTopGap();

  chatHistory.scrollTop =
    Math.max(
      0,
      targetTop + metrics.overflow
    );

}


function stopExpandedReasoningFollow(
  stream = null
) {

  if (
    stream
    && expandedReasoningFollowStream !== stream
  ) {
    return;
  }

  expandedReasoningFollowStream = null;

  if (expandedReasoningFollowFrame) {
    cancelAnimationFrame(
      expandedReasoningFollowFrame
    );
    expandedReasoningFollowFrame = null;
  }

}


function canFollowExpandedReasoning(
  stream
) {

  return Boolean(
    chatHistory
    && stream
    && stream.group
    && stream.runtimeAvatarReasoningActive
    && stream.group.createdThinking
    && !stream.group.createdAnswer
    && stream.group.thinkContent
    && stream.group.thinkContent.isConnected
    && !stream.group.thinkContent.classList.contains(
      "is-collapsed"
    )
    && stream.group.avatarSlot
    && stream.group.avatarSlot.isConnected
  );

}


function getExpandedReasoningFollowTarget(
  stream
) {

  if (!canFollowExpandedReasoning(stream)) {
    return null;
  }

  const historyRect =
    chatHistory.getBoundingClientRect();
  const avatarRect =
    stream.group.avatarSlot.getBoundingClientRect();
  const visibleBottom =
    historyRect.bottom
    - getChatInputOverlaySpace()
    - getChatHistoryTopGap();
  const overflow =
    avatarRect.bottom - visibleBottom;

  if (overflow <= 0.5) {
    return chatHistory.scrollTop;
  }

  const maxScrollTop =
    Math.max(
      0,
      chatHistory.scrollHeight
      - chatHistory.clientHeight
    );

  return Math.min(
    maxScrollTop,
    chatHistory.scrollTop + overflow
  );

}


function runExpandedReasoningFollowFrame() {

  expandedReasoningFollowFrame = null;

  const stream =
    expandedReasoningFollowStream;

  if (!canFollowExpandedReasoning(stream)) {
    stopExpandedReasoningFollow(
      stream
    );
    return;
  }

  updateLiveUserTurnBottomSpace();

  const targetTop =
    getExpandedReasoningFollowTarget(
      stream
    );

  if (targetTop === null) {
    stopExpandedReasoningFollow(
      stream
    );
    return;
  }

  const delta =
    targetTop - chatHistory.scrollTop;

  if (delta <= 0.5) {
    return;
  }

  chatHistory.scrollTop =
    Math.min(
      targetTop,
      chatHistory.scrollTop
      + Math.max(
        1,
        delta * 0.24
      )
    );

  if (
    targetTop - chatHistory.scrollTop
    > 0.5
  ) {
    expandedReasoningFollowFrame =
      requestAnimationFrame(
        runExpandedReasoningFollowFrame
      );
  }

}


function queueExpandedReasoningFollow() {

  if (
    expandedReasoningFollowFrame
    || !canFollowExpandedReasoning(
      expandedReasoningFollowStream
    )
  ) {
    return;
  }

  expandedReasoningFollowFrame =
    requestAnimationFrame(
      runExpandedReasoningFollowFrame
    );

}


function startExpandedReasoningFollow(
  stream
) {

  if (!canFollowExpandedReasoning(stream)) {
    return;
  }

  if (
    expandedReasoningFollowStream
    && expandedReasoningFollowStream !== stream
  ) {
    stopExpandedReasoningFollow();
  }

  expandedReasoningFollowStream =
    stream;

  // Manual expansion hands scroll ownership from the pinned USER row to the
  // live reasoning tail. From here the viewport follows the moving avatar
  // only when it reaches the usable bottom edge of the chat.
  keepLiveUserTurnAtTop = false;
  updateLiveUserTurnBottomSpace();
  queueExpandedReasoningFollow();

}


function releaseLiveUserTurnViewportControl() {

  releaseLiveUserTurnTopLock();
  stopExpandedReasoningFollow();

}


function prepareLiveUserTurnViewport() {

  stopExpandedReasoningFollow();
  liveUserTurnAnchor = null;
  keepLiveUserTurnAtTop = false;

  if (chatHistory) {
    chatHistory.style.removeProperty(
      "--jin-live-turn-bottom-space"
    );
  }

}


function activateLiveUserTurnViewport(
  messageRow
) {

  if (
    !chatHistory
    || !messageRow
  ) {
    return;
  }

  liveUserTurnAnchor =
    messageRow;
  keepLiveUserTurnAtTop =
    true;

  scrollLiveUserTurnToTop();

  requestAnimationFrame(
    () => {
      if (keepLiveUserTurnAtTop) {
        scrollLiveUserTurnToTop();
      } else {
        updateLiveUserTurnBottomSpace();
      }
    }
  );

}


function releaseLiveUserTurnTopLock() {

  keepLiveUserTurnAtTop = false;
  updateLiveUserTurnBottomSpace();

}


function syncLiveUserTurnViewportForLayoutChange() {

  if (
    !liveUserTurnAnchor
    || !liveUserTurnAnchor.isConnected
  ) {
    return;
  }

  // A reasoning max-height transition changes the visible tail height without
  // producing a stream frame. Keep the compensating bottom spacer in lockstep
  // so the browser never has to clamp chatHistory.scrollTop mid-collapse.
  if (keepLiveUserTurnAtTop) {
    scrollLiveUserTurnToTop();
    return;
  }

  updateLiveUserTurnBottomSpace();

  if (expandedReasoningFollowStream) {
    queueExpandedReasoningFollow();
  }

}


function scrollChatHistoryAfterAppend() {

  if (!chatHistory) {
    return;
  }

  updateLiveUserTurnBottomSpace();

  if (keepLiveUserTurnAtTop) {
    scrollLiveUserTurnToTop();
    return;
  }

  if (expandedReasoningFollowStream) {
    queueExpandedReasoningFollow();
    return;
  }

  chatHistory.scrollTop =
    chatHistory.scrollHeight;

}


function shouldAutoScroll() {

  if (!chatHistory) {
    return false;
  }

  if (keepLiveUserTurnAtTop) {
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


if (chatHistory) {
  chatHistory.addEventListener(
    "wheel",
    releaseLiveUserTurnViewportControl,
    { passive: true }
  );

  chatHistory.addEventListener(
    "touchstart",
    releaseLiveUserTurnViewportControl,
    { passive: true }
  );
}

window.addEventListener(
  "jin:generation-state-changed",
  (event) => {
    if (
      event.detail
      && event.detail.active === false
    ) {
      releaseLiveUserTurnViewportControl();
    }
  }
);

window.addEventListener(
  "resize",
  () => {
    updateChatInputOverlaySpace();
    updateLiveUserTurnBottomSpace();

    if (keepLiveUserTurnAtTop) {
      scrollLiveUserTurnToTop();
    } else if (expandedReasoningFollowStream) {
      queueExpandedReasoningFollow();
    }
  }
);

if (chatInputShell && typeof ResizeObserver !== "undefined") {
  const chatInputShellObserver =
    new ResizeObserver(() => {
      updateChatInputOverlaySpace();
      updateLiveUserTurnBottomSpace();

      if (keepLiveUserTurnAtTop) {
        scrollLiveUserTurnToTop();
      }
    });

  chatInputShellObserver.observe(
    chatInputShell
  );
}

updateChatInputOverlaySpace();


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

    let streamAvatarNeedsSync = false;

    if (stream.pendingThinking) {

      if (
        !stream.group.createdThinking
      ) {

        stream.group.wrapper.classList.remove(
          "is-awaiting-model"
        );

        stream.group.wrapper.appendChild(
          stream.group.thinkWrapper
        );

        stream.group.createdThinking =
          true;
        streamAvatarNeedsSync = true;

      }

      appendTextNodeData(
        stream.group.thinkContent,
        "__jinThinkTextNode",
        stream.pendingThinking
      );

      updateThinkExpandedHeight(
        stream.group.thinkContent
      );

      if (
        window.JinThinkCitations
        && typeof window.JinThinkCitations.updateStreamingRuntimeCitationHighlights === "function"
      ) {
        window.JinThinkCitations.updateStreamingRuntimeCitationHighlights(
          stream.messageId,
          stream
        );
      }

      stream.pendingThinking =
        "";
      streamAvatarNeedsSync = true;

    }

    if (stream.pendingAnswer) {

      if (
        !stream.group.createdAnswer
      ) {

        stopExpandedReasoningFollow(
          stream
        );

        stream.group.wrapper.classList.remove(
          "is-awaiting-model"
        );

        stream.group.wrapper.appendChild(
          stream.group.messageRow
        );

        stream.group.createdAnswer =
          true;
        streamAvatarNeedsSync = true;

      }

      renderChatTextElement(
        stream.group.answerContent,
        stream.answer,
        {
          format: shouldFormatChatRole(
            stream.role
          ),
        }
      );

      stream.pendingAnswer =
        "";
      streamAvatarNeedsSync = true;

    }

    if (streamAvatarNeedsSync) {
      syncStreamAvatarPosition(
        stream
      );
    }

  });

  updateLiveUserTurnBottomSpace();

  let liveTurnOverflowAutoscroll =
    false;

  if (
    !expandedReasoningFollowStream
    && liveUserTurnReachedViewportBottom()
  ) {
    releaseLiveUserTurnTopLock();
    liveTurnOverflowAutoscroll =
      true;
  }

  if (keepLiveUserTurnAtTop) {
    scrollLiveUserTurnToTop();
  } else if (expandedReasoningFollowStream) {
    queueExpandedReasoningFollow();
  } else if (
    (
      autoscroll
      || liveTurnOverflowAutoscroll
    )
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
        avatar: "U",
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

    case "brain":
    default:
      return {
        avatar: "J",
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

  scrollChatHistoryAfterAppend();

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
    const attachmentId =
      String(
        attachment && attachment.id
          ? attachment.id
          : ""
      ).trim().toLowerCase();

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

    let attachmentBound = false;
    const syncAttachmentAvailability = () => {
      // Plain/transient attachment objects keep the old behavior. A logged
      // persistent id, however, is authoritative: if that id no longer exists
      // in JIN Files, the historical chip stays visible as history but is dim
      // and inert instead of opening a broken empty modal.
      if (!attachmentId) {
        if (!attachmentBound) {
          bindJinAttachmentBubble(
            chip,
            attachment
          );
          attachmentBound = true;
        }
        chip.disabled = false;
        chip.style.opacity = "";
        chip.style.cursor = "";
        chip.removeAttribute("aria-disabled");
        return;
      }

      const filesApi = window.JinFiles;
      const storeReady = Boolean(
        filesApi
        && typeof filesApi.isLoaded === "function"
        && filesApi.isLoaded()
      );
      const record = filesApi
        && typeof filesApi.getFile === "function"
          ? filesApi.getFile(attachmentId)
          : null;
      const available = Boolean(record);

      if (available && !attachmentBound) {
        bindJinAttachmentBubble(
          chip,
          {
            ...attachment,
            ...record,
          }
        );
        attachmentBound = true;
      }

      // While the initial file snapshot is still in flight, keep the chip
      // conservatively disabled; jin:files-store-changed immediately resolves
      // it to available/missing once the authoritative store arrives.
      chip.disabled = !available;
      chip.style.opacity = available ? "" : (storeReady ? "0.35" : "0.5");
      chip.style.cursor = available ? "" : "default";
      chip.setAttribute(
        "aria-disabled",
        available ? "false" : "true"
      );
      chip.title = available
        ? label
        : (storeReady ? `${label} · file not found` : `${label} · loading file`);
    };

    syncAttachmentAvailability();
    if (attachmentId) {
      window.addEventListener(
        "jin:files-store-changed",
        syncAttachmentAvailability
      );
    }

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

  renderChatTextElement(
    pre,
    text,
    {
      format: shouldFormatChatRole(
        role
      ),
    }
  );

  const completedBubble = pre.closest(
    ".jin-chat-bubble"
  );
  if (
    completedBubble
    && window.markJinCompletedAnswerBubble
  ) {
    const visibleMessageText = String(
      pre.innerText
      || pre.textContent
      || text
      || ""
    ).trim();
    window.markJinCompletedAnswerBubble(
      completedBubble,
      visibleMessageText
    );
  }

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
  } else {
    setLatestJinMemoryReferenceText(
      role,
      text
    );
  }

  flushRuntimeActionsAfterResponse(
    role
  );

  return pre.closest(
    ".jin-message-shell"
  );

}
// CREATE STREAM GROUP

function setStreamAvatarProcessing(
  stream,
  active
) {

  const avatar =
    stream
    && stream.group
    && stream.group.avatar;

  if (!avatar) {
    return;
  }

  avatar.classList.toggle(
    "is-processing",
    Boolean(active)
  );
  avatar.classList.toggle(
    "is-settled",
    !active
  );

}

function disconnectStreamThinkResizeObserver(
  stream
) {

  const observer =
    stream
    && stream.group
    && stream.group.thinkResizeObserver;

  if (!observer) {
    return;
  }

  observer.disconnect();
  stream.group.thinkResizeObserver = null;

}

function syncStreamAvatarPosition(
  stream
) {

  if (
    !stream
    || !stream.group
    || !stream.group.avatarSlot
  ) {
    return;
  }

  const group = stream.group;
  const avatarSlot = group.avatarSlot;

  let left = STREAM_AVATAR_LEFT_PX;
  let top = 0;

  if (
    group.createdAnswer
    && group.messageRow
    && group.messageRow.isConnected
  ) {
    left =
      group.messageRow.offsetLeft
      + STREAM_AVATAR_LEFT_PX;
    top = group.messageRow.offsetTop;

    setStreamAvatarProcessing(
      stream,
      false
    );
    disconnectStreamThinkResizeObserver(
      stream
    );
  } else if (
    group.createdThinking
    && group.thinkWrapper
    && group.thinkContent
    && group.thinkWrapper.isConnected
  ) {
    left = STREAM_AVATAR_LEFT_PX;
    top = group.thinkWrapper.offsetTop;

    if (
      !group.thinkContent.classList.contains(
        "is-collapsed"
      )
    ) {
      top += Math.max(
        0,
        group.thinkContent.offsetHeight
        - STREAM_AVATAR_SIZE_PX
      );
    }
  }

  avatarSlot.style.left =
    `${Math.round(left)}px`;
  avatarSlot.style.top =
    `${Math.round(top)}px`;

}

function queueStreamAvatarPositionSync(
  stream
) {

  requestAnimationFrame(
    () => {
      syncStreamAvatarPosition(
        stream
      );
    }
  );

}

function trackStreamAvatarLayoutTransition(
  stream
) {

  if (
    !stream
    || !stream.group
  ) {
    return;
  }

  const group = stream.group;

  if (
    !group.avatarSlot
    && !(
      liveUserTurnAnchor
      && liveUserTurnAnchor.isConnected
    )
  ) {
    return;
  }

  const trackId =
    (group.avatarLayoutTrackId || 0) + 1;
  const startedAt = nowMs();

  group.avatarLayoutTrackId =
    trackId;

  const tick = () => {

    if (
      group.avatarLayoutTrackId !== trackId
    ) {
      return;
    }

    const avatarConnected =
      Boolean(
        group.avatarSlot
        && group.avatarSlot.isConnected
      );
    const liveTurnConnected =
      Boolean(
        liveUserTurnAnchor
        && liveUserTurnAnchor.isConnected
      );

    if (
      !avatarConnected
      && !liveTurnConnected
    ) {
      return;
    }

    if (avatarConnected) {
      syncStreamAvatarPosition(
        stream
      );
    }

    syncLiveUserTurnViewportForLayoutChange();

    if (
      nowMs() - startedAt
      < STREAM_AVATAR_LAYOUT_TRACK_MS
    ) {
      requestAnimationFrame(
        tick
      );
      return;
    }

    if (avatarConnected) {
      syncStreamAvatarPosition(
        stream
      );
    }

    syncLiveUserTurnViewportForLayoutChange();

  };

  requestAnimationFrame(
    tick
  );

}


function installStreamThinkResizeObserver(
  stream
) {

  if (
    !stream
    || !stream.group
    || !stream.group.thinkContent
    || typeof ResizeObserver !== "function"
  ) {
    return;
  }

  disconnectStreamThinkResizeObserver(
    stream
  );

  const observer = new ResizeObserver(
    () => {
      if (
        !stream.group.createdThinking
        || stream.group.createdAnswer
      ) {
        return;
      }

      queueStreamAvatarPositionSync(
        stream
      );

      if (
        expandedReasoningFollowStream === stream
      ) {
        queueExpandedReasoningFollow();
      }
    }
  );

  observer.observe(
    stream.group.thinkContent
  );
  stream.group.thinkResizeObserver =
    observer;

}

function animateStreamAvatarHandoff(
  stream,
  fromRect
) {

  const slot =
    stream
    && stream.group
    && stream.group.avatarSlot;

  if (
    !slot
    || !fromRect
    || !slot.isConnected
  ) {
    return;
  }

  syncStreamAvatarPosition(
    stream
  );

  const toRect =
    slot.getBoundingClientRect();
  const deltaX =
    fromRect.left - toRect.left;
  const deltaY =
    fromRect.top - toRect.top;

  if (
    Math.abs(deltaX) < 0.5
    && Math.abs(deltaY) < 0.5
  ) {
    return;
  }

  slot.style.transition = "none";
  slot.style.transform =
    `translate3d(${deltaX}px, ${deltaY}px, 0)`;

  // Force the origin transform to be painted before the handoff transition.
  slot.getBoundingClientRect();

  requestAnimationFrame(
    () => {
      slot.style.removeProperty(
        "transition"
      );
      slot.style.transform =
        "translate3d(0, 0, 0)";

      window.setTimeout(
        () => {
          if (slot.isConnected) {
            slot.style.removeProperty(
              "transform"
            );
          }
        },
        STREAM_AVATAR_HANDOFF_MS + 40
      );
    }
  );

}

function activateStreamAvatar(
  stream
) {

  const previous =
    activeStreamAvatarStream;
  let previousRect = null;

  if (
    previous
    && previous !== stream
    && previous.group
    && previous.group.avatarSlot
    && !previous.group.createdAnswer
  ) {
    previousRect =
      previous.group.avatarSlot.getBoundingClientRect();

    previous.group.avatarSlot.remove();
    previous.group.avatarSlot = null;
    previous.group.avatar = null;
    disconnectStreamThinkResizeObserver(
      previous
    );

    if (previous.group.wrapper) {
      previous.group.wrapper.classList.remove(
        "is-awaiting-model"
      );

      if (
        previous.group.wrapper.childElementCount === 0
      ) {
        previous.group.wrapper.remove();
      }
    }
  }

  activeStreamAvatarStream = stream;

  setStreamAvatarProcessing(
    stream,
    true
  );
  syncStreamAvatarPosition(
    stream
  );

  if (previousRect) {
    animateStreamAvatarHandoff(
      stream,
      previousRect
    );
  }

}

function releaseActiveStreamAvatar() {

  const stream =
    activeStreamAvatarStream;

  if (stream) {
    stopStreamRuntimeAvatarReasoning(
      stream
    );

    const group = stream.group || {};
    const hasVisibleStreamContent =
      Boolean(
        group.createdThinking
        || group.createdAnswer
      );

    if (!hasVisibleStreamContent) {
      disconnectStreamThinkResizeObserver(
        stream
      );

      if (group.avatarSlot) {
        group.avatarSlot.remove();
        group.avatarSlot = null;
        group.avatar = null;
      }

      if (group.wrapper) {
        group.wrapper.classList.remove(
          "is-awaiting-model"
        );

        if (group.wrapper.childElementCount === 0) {
          group.wrapper.remove();
        }
      }
    } else {
      setStreamAvatarProcessing(
        stream,
        false
      );
    }
  }

  activeStreamAvatarStream = null;

}

function scrollCollapsedThinkToLatest(
  thinkContent
) {

  if (
    !thinkContent
    || !thinkContent.classList.contains(
      "is-collapsed"
    )
  ) {
    return;
  }

  // The collapsed preview must land on the latest reasoning immediately.
  // A smooth inner scroll runs at the same time as the max-height collapse
  // and makes the whole interaction look like the chat is still moving.
  thinkContent.scrollTop =
    thinkContent.scrollHeight;

}

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

  scrollCollapsedThinkToLatest(
    thinkContent
  );

}

window.updateThinkExpandedHeight =
  updateThinkExpandedHeight;

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
    "jin-stream-wrapper is-awaiting-model mx-auto w-full max-w-4xl";

  const avatarSlot =
    document.createElement("div");

  avatarSlot.className =
    "jin-stream-avatar-slot";

  const avatar =
    createAvatarElement(
      role,
      contextSnapshot
    );

  avatar.classList.add(
    "jin-stream-avatar",
    "is-processing"
  );

  avatarSlot.appendChild(
    avatar
  );
  wrapper.appendChild(
    avatarSlot
  );

  // THINKING

  const thinkWrapper =
    document.createElement("div");

  thinkWrapper.className =
    "jin-think-wrapper";

  const thinkContent =
    document.createElement("div");

  const initialThinkCollapsed =
    Boolean(
      jinThinkCollapsedPreference
    );

  thinkContent.className =
    initialThinkCollapsed
      ? "jin-think-content is-collapsed"
      : "jin-think-content";

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
    initialThinkCollapsed
      ? "false"
      : "true"
  );

  thinkContent.setAttribute(
    "aria-label",
    "Toggle thinking block"
  );

  let collapsed =
    initialThinkCollapsed;

  const setCollapsed = (nextCollapsed, options = {}) => {

    collapsed =
      nextCollapsed;

    if (options.persist === true) {
      jinThinkCollapsedPreference =
        collapsed;
    }

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

    if (
      typeof thinkContent.__jinExpandedReasoningFollow
      === "function"
    ) {
      thinkContent.__jinExpandedReasoningFollow(
        !collapsed
      );
    }

    syncLiveUserTurnViewportForLayoutChange();

    if (collapsed) {
      requestAnimationFrame(
        () => {
          scrollCollapsedThinkToLatest(
            thinkContent
          );
        }
      );
    }

    if (
      typeof thinkContent.__jinStreamAvatarSync
      === "function"
    ) {
      thinkContent.__jinStreamAvatarSync();
    }

  };

  let thinkClickStart = null;

  thinkContent.addEventListener(
    "mousedown",
    (event) => {
      if (event.button !== 0) {
        return;
      }

      thinkClickStart = {
        x: event.clientX,
        y: event.clientY,
      };
    }
  );

  thinkContent.addEventListener(
    "click",
    (event) => {
      const selection =
        typeof window.getSelection === "function"
          ? window.getSelection()
          : null;
      const pointerMoved =
        thinkClickStart
        && (
          Math.abs(event.clientX - thinkClickStart.x) > 3
          || Math.abs(event.clientY - thinkClickStart.y) > 3
        );
      const selectionTouchesThink =
        selection
        && !selection.isCollapsed
        && (
          (
            selection.anchorNode
            && thinkContent.contains(selection.anchorNode)
          )
          || (
            selection.focusNode
            && thinkContent.contains(selection.focusNode)
          )
        );

      thinkClickStart = null;

      if (
        pointerMoved
        || selectionTouchesThink
      ) {
        return;
      }

      setCollapsed(
        !collapsed,
        {
          persist: true,
        }
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
        !collapsed,
        {
          persist: true,
        }
      );

    }
  );

  thinkWrapper.appendChild(
    thinkContent
  );

  // ANSWER

  const messageRow =
    document.createElement("div");

  messageRow.className =
    "jin-message-row";

  const avatarSpacer =
    document.createElement("div");

  avatarSpacer.className =
    "jin-stream-avatar-spacer";
  avatarSpacer.setAttribute(
    "aria-hidden",
    "true"
  );

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
    avatarSpacer
  );

  messageRow.appendChild(
    bubble
  );

  chatHistory.appendChild(
    wrapper
  );

  scrollChatHistoryAfterAppend();

  return {
    wrapper,
    avatarSlot,
    avatar,
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

  stream.group.avatarSlot =
    realGroup.avatarSlot;

  stream.group.avatar =
    realGroup.avatar;

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

  stream.group.thinkContent.__jinStreamAvatarSync =
    () => {
      syncStreamAvatarPosition(
        stream
      );
      trackStreamAvatarLayoutTransition(
        stream
      );
    };

  stream.group.thinkContent.__jinExpandedReasoningFollow =
    (expanded) => {
      if (expanded) {
        startExpandedReasoningFollow(
          stream
        );
        return;
      }

      stopExpandedReasoningFollow(
        stream
      );
    };

  installStreamThinkResizeObserver(
    stream
  );

}


function getRuntimeAvatarMotionController() {

  return (
    window.JinRuntime
    && window.JinRuntime.avatar
  ) || null;

}

function startStreamRuntimeAvatarReasoning(
  stream
) {

  if (
    !stream
    || stream.runtimeAvatarReasoningActive
  ) {
    return;
  }

  const avatar =
    getRuntimeAvatarMotionController();

  stream.runtimeAvatarReasoningActive = true;

  if (
    avatar
    && typeof avatar.beginReasoning === "function"
  ) {
    avatar.beginReasoning(
      stream.messageId
    );
  }

}

function stopStreamRuntimeAvatarReasoning(
  stream
) {

  if (
    !stream
    || !stream.runtimeAvatarReasoningActive
  ) {
    return;
  }

  stream.runtimeAvatarReasoningActive = false;

  const avatar =
    getRuntimeAvatarMotionController();

  if (
    avatar
    && typeof avatar.endReasoning === "function"
  ) {
    avatar.endReasoning(
      stream.messageId
    );
  }

}

function markStreamAnswerPhase(
  messageId
) {

  const stream =
    streamMessages.get(
      messageId
    );

  if (!stream) {
    return false;
  }

  return true;
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
    avatarSlot: null,
    avatar: null,
    thinkResizeObserver: null,
    thinkWrapper: null,
    thinkContent: null,
    messageRow: null,
    answerContent: null,
  };

  const stream = {
    role,
    messageId,
    context: contextSnapshot,
    group,
    thinking: "",
    answer: "",
    pendingThinking: "",
    pendingAnswer: "",
    runtimeAvatarReasoningActive: false,
  };

  streamMessages.set(
    messageId,
    stream
  );

  // Reserve the response position before the first visible chunk. Runtime
  // action rows emitted at the start of a stream will then stay below the
  // response while its content continues to grow.
  ensureStreamGroup(
    stream
  );

  activateStreamAvatar(
    stream
  );

}


// THINKING CHUNK

function stripInternalActionMarkers(
  text
) {

  return String(text || "")
    .replace(
      /(^|\n)[^\S\r\n]*<WEB_SEARCH:[^>\n]*>[^\S\r\n]*(?=\n|$)/gi,
      "$1"
    )
    .replace(
      /(^|\n)[^\S\r\n]*<JIN_SIZE\s*>[\s\S]*?<\/JIN_SIZE\s*>[^\S\r\n]*(?=\n|$)/gi,
      "$1"
    )
    .replace(
      /(^|\n)[^\S\r\n]*<DEEP_WEB_SEARCH(?:\s*:\s*[^>\n]*)?>[\s\S]*?<\/DEEP_WEB_SEARCH>[^\S\r\n]*(?=\n|$)/gi,
      "$1"
    )
    .replace(
      /(^|\n)[^\S\r\n]*<DEEP_WEB_SEARCH(?:\s*:\s*[^>\n]*)?>[^\S\r\n]*(?=\n|$)/gi,
      "$1"
    )
    .replace(
      /(^|\n)[^\S\r\n]*<\/DEEP_WEB_SEARCH>[^\S\r\n]*(?=\n|$)/gi,
      "$1"
    )
    .replace(
      /(^|\n)[^\S\r\n]*<LOAD_SKILLS?:[^>\n]*>[^\S\r\n]*(?=\n|$)/gi,
      "$1"
    )
    .replace(
      /(^|\n)[^\S\r\n]*<UNLOAD_SKILLS?:[^>\n]*>[^\S\r\n]*(?=\n|$)/gi,
      "$1"
    )
    .replace(
      /(^|\n)[^\S\r\n]*<ASSET_ACTION>([\s\S]*?)<\/ASSET_ACTION>[^\S\r\n]*(?=\n|$)/gi,
      (fullMatch, lineStart, payload) => (
        String(payload || "").trim()
          ? lineStart
          : fullMatch
      )
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

  startStreamRuntimeAvatarReasoning(
    stream
  );

  stream.thinking += chunk;
  stream.pendingThinking += chunk;

  scheduleStreamFrameUpdate();

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

  if (
    chunk === null
    || chunk === undefined
    || chunk === ""
  ) {
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

  startStreamRuntimeAvatarReasoning(
    stream
  );

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
  messageId,
  options = {}
) {

  const stream =
    streamMessages.get(
      messageId
    );

  if (stream) {

    stopStreamRuntimeAvatarReasoning(
      stream
    );

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
      && !stream.thinking.trim()
      && !stream.answer.trim()
    ) {
      disconnectStreamThinkResizeObserver(
        stream
      );

      if (stream.group.avatarSlot) {
        stream.group.avatarSlot.remove();
        stream.group.avatarSlot = null;
        stream.group.avatar = null;
      }

      stream.group.wrapper.classList.remove(
        "is-awaiting-model"
      );
    }

    if (
      stream.group.wrapper
      && stream.group.wrapper.childElementCount === 0
    ) {
      stream.group.wrapper.remove();
    }

    const memoryReferenceText =
      [
        stream.thinking,
        stream.answer,
      ]
        .map(value => String(value || "").trim())
        .filter(Boolean)
        .join("\n");

    if (memoryReferenceText) {
      setLatestJinMemoryReferenceText(
        stream.role,
        memoryReferenceText
      );
    }

    if (stream.answer.trim()) {
      flushRuntimeActionsAfterResponse(
        stream.role
      );

      const answerBubble = (
        stream.group.answerContent
        && stream.group.answerContent.closest
      )
        ? stream.group.answerContent.closest(".jin-chat-bubble")
        : null;

      if (
        answerBubble
        && window.markJinCompletedAnswerBubble
      ) {
        const visibleAnswerText = String(
          stream.group.answerContent.innerText
          || stream.group.answerContent.textContent
          || stream.answer
          || ""
        ).trim();
        window.markJinCompletedAnswerBubble(
          answerBubble,
          visibleAnswerText
        );
      }
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
window.clearLatestJinMemoryReferenceText =
  clearLatestJinMemoryReferenceText;
window.markStreamAnswerPhase =
  markStreamAnswerPhase;
window.prepareLiveUserTurnViewport =
  prepareLiveUserTurnViewport;
window.activateLiveUserTurnViewport =
  activateLiveUserTurnViewport;
window.updateLiveUserTurnBottomSpace =
  updateLiveUserTurnBottomSpace;
window.scrollChatHistoryAfterAppend =
  scrollChatHistoryAfterAppend;
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
window.releaseActiveStreamAvatar =
  releaseActiveStreamAvatar;
window.syncStreamAvatarPosition =
  syncStreamAvatarPosition;
