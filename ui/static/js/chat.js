const chatHistory =
  document.getElementById(
    "chat-history"
  );

const streamMessages =
  new Map();

const STREAM_FRAME_WARNING_MS = 12;
const STREAM_NEAR_BOTTOM_PX = 72;
const THINK_RULE_CITATIONS_ENDPOINT =
  "/api/debug/rule-citations";
const THINK_RULE_WORKER_URL =
  "/static/js/think-rule-worker.js?v=rule-citations-3";

let streamFrameScheduled = false;
let thinkRuleCitationWorker = null;
let thinkRuleCitationRegistryPromise = null;
let nextThinkRuntimeCitationIndex = 0;
const deferredRuntimeActionsAfterResponse = [];
const visibleRuntimeActionKeys = new Set();
const activeThinkRuleCitationJobs = new Map();

const jinInputLoopState = {
  previousInput: "",
  repeatCount: 0,
};

let jinConversationTurnCounter = 0;
window.jinConversationTurnCounter =
  jinConversationTurnCounter;

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

function loadThinkRuleCitationRegistry() {

  if (thinkRuleCitationRegistryPromise) {
    return thinkRuleCitationRegistryPromise;
  }

  thinkRuleCitationRegistryPromise = fetch(
    THINK_RULE_CITATIONS_ENDPOINT,
    {
      cache: "no-store",
    }
  )
    .then((response) => {
      if (!response.ok) {
        throw new Error(
          `Rule citation registry failed: ${response.status}`
        );
      }

      return response.json();
    })
    .catch((error) => {
      if (isStreamDebugEnabled()) {
        console.warn(
          "[think-rules] disabled",
          error
        );
      }

      return {
        enabled: false,
        fragments: [],
      };
    });

  return thinkRuleCitationRegistryPromise;

}

function getThinkRuleCitationWorker() {

  if (thinkRuleCitationWorker) {
    return thinkRuleCitationWorker;
  }

  if (!window.Worker) {
    return null;
  }

  thinkRuleCitationWorker =
    new Worker(
      THINK_RULE_WORKER_URL
    );

  thinkRuleCitationWorker.onmessage =
    handleThinkRuleWorkerMessage;

  thinkRuleCitationWorker.onerror = (event) => {
    if (isStreamDebugEnabled()) {
      console.warn(
        "[think-rules] worker error",
        event.message
      );
    }
  };

  return thinkRuleCitationWorker;

}

function thinkRuleLevelRank(level) {

  if (level === "exact") {
    return 3;
  }

  if (level === "near") {
    return 2;
  }

  return 1;

}

function thinkCitationSourcePriority(match) {

  if (
    match
    && match.sourceType === "rule"
  ) {
    return 2;
  }

  if (
    match
    && match.sourceType === "runtime"
  ) {
    return 1;
  }

  if (
    match
    && match.sourceType === "session"
  ) {
    return 0;
  }

  return -1;

}

function resolveThinkRuleOverlaps(matches) {

  const seen = new Set();
  const sorted = [...matches]
    .filter((match) => {
      if (
        !match
        || match.end <= match.start
      ) {
        return false;
      }

      const key = [
        match.start,
        match.end,
        match.level,
        match.constantName,
        match.sourceText,
      ].join("|");

      if (seen.has(key)) {
        return false;
      }

      seen.add(key);
      return true;
    })
    .sort((left, right) => {
      const priorityDelta =
        thinkCitationSourcePriority(
          right
        )
        - thinkCitationSourcePriority(
          left
        );

      if (priorityDelta) {
        return priorityDelta;
      }

      const levelDelta =
        thinkRuleLevelRank(
          right.level
        )
        - thinkRuleLevelRank(
          left.level
        );

      if (levelDelta) {
        return levelDelta;
      }

      if (right.score !== left.score) {
        return right.score - left.score;
      }

      return (
        (right.end - right.start)
        - (left.end - left.start)
      );
    });

  const selected = [];

  sorted.forEach((match) => {
    const overlaps =
      selected.some(
        (selectedMatch) => (
          match.start < selectedMatch.end
          && match.end > selectedMatch.start
        )
      );

    if (!overlaps) {
      selected.push(
        match
      );
    }
  });

  return selected.sort(
    (left, right) => left.start - right.start
  );

}

function buildThinkRuleTitle(
  match,
  matchedText
) {

  const score =
    Math.round(
      Number(
        match.score || 0
      ) * 100
    );

  const label =
    match.sourceType === "runtime"
      ? "RUNTIME"
      : match.sourceType === "session"
        ? "SESSION"
        : "RULE";

  return [
    `${label} - ${match.constantName || "unknown"} - ${match.level || "match"} - ${score}%`,
    `source: ${match.source || "rules"}`,
    `layer: ${match.layer || "base"}`,
    `matched: "${matchedText}"`,
    `${match.sourceType === "rule" ? "rule" : "memory"}: "${match.titleText || match.sourceText || ""}"`,
  ].join("\n");

}

function getThinkCitationClassName(match) {

  const sourceClass =
    match.sourceType === "runtime"
      ? "runtime"
      : match.sourceType === "session"
        ? "session"
        : "rule";

  return [
    "think-rule-hit",
    `think-citation-${sourceClass}`,
    match.level || "near",
  ].join(" ");

}

function splitThinkCitationTextFragments(text) {

  const runtimeModel =
    window.JinRuntime
    && window.JinRuntime.memoryModel;

  const lines =
    runtimeModel
    && typeof runtimeModel.splitMemoryTextLines === "function"
      ? runtimeModel.splitMemoryTextLines(
        text
      )
      : String(text || "")
        .replace(/\\n/g, "\n")
        .split(/\r?\n+/)
        .map(line => line.trim())
        .filter(Boolean);

  return lines
    .map((line) => {
      const cleanedLine =
        runtimeModel
        && typeof runtimeModel.stripRuntimeMemoryMeta === "function"
          ? runtimeModel.stripRuntimeMemoryMeta(
            line
          )
          : line;

      return String(cleanedLine || "").trim();
    })
    .filter(Boolean);

}

function buildMemoryCitationFragments(
  memoryText,
  options
) {

  const {
    source,
    sourceType,
    citationType,
    layer,
    idPrefix,
    defaultConstantName,
  } = options;

  const fragments = [];
  const seen = new Set();

  splitThinkCitationTextFragments(
    memoryText
  ).forEach((line, index) => {
    const separatorIndex =
      line.indexOf(":");
    const key =
      separatorIndex > 0
        ? line.slice(
          0,
          separatorIndex
        ).trim()
        : defaultConstantName;
    const value =
      separatorIndex > 0
        ? line.slice(
          separatorIndex + 1
        ).trim()
        : line;

    [
      line,
      value,
    ].forEach((sourceText, variantIndex) => {
      const normalized =
        sourceText
          .toLowerCase()
          .replace(/\s+/g, " ")
          .trim();

      if (
        !normalized
        || normalized.length < 24
        || seen.has(
          normalized
        )
      ) {
        return;
      }

      seen.add(
        normalized
      );

      fragments.push(
        {
          id: `${idPrefix}:${index}:${variantIndex}`,
          source,
          sourceType,
          citationType,
          layer,
          constantName: key || defaultConstantName,
          sourceText,
          titleText: line,
          minScore: 0.72,
        }
      );
    });
  });

  return fragments;

}

function getRuntimeCitationSnapshot(
  snapshotIndex
) {

  const runtimeApi =
    window.JinRuntime
    && window.JinRuntime.runtime;

  if (
    runtimeApi
    && typeof runtimeApi.getRuntimeMemorySnapshot === "function"
  ) {
    return (
      runtimeApi.getRuntimeMemorySnapshot(
        snapshotIndex
      )
      || null
    );
  }

  const storage =
    window.JinRuntime
    && window.JinRuntime.storage;

  if (
    storage
    && typeof storage.readLatestRuntimeMemory === "function"
  ) {
    const latestRuntime =
      storage.readLatestRuntimeMemory();

    if (
      latestRuntime
      && latestRuntime.runtime_snapshot
    ) {
      return latestRuntime.runtime_snapshot;
    }

    return latestRuntime || null;
  }

  return null;

}

function getRuntimeCitationTextFromSnapshot(
  snapshot
) {

  return String(
    (
      snapshot
      && (
        snapshot.raw_memory
        || snapshot.runtime_memory
        || (
          snapshot.runtime_snapshot
          && snapshot.runtime_snapshot.raw_memory
        )
      )
    )
    || ""
  ).trim();

}

function buildRuntimeCitationFragments(
  snapshotIndex
) {

  const snapshot =
    getRuntimeCitationSnapshot(
      snapshotIndex
    );
  const runtimeMemory =
    getRuntimeCitationTextFromSnapshot(
      snapshot
    );

  if (!runtimeMemory) {
    return [];
  }

  return buildMemoryCitationFragments(
    runtimeMemory,
    {
      source: `runtimeSnapshot[${snapshotIndex}]`,
      sourceType: "runtime",
      citationType: "runtime_citation",
      layer: "runtime",
      idPrefix: `runtime:${snapshotIndex}`,
      defaultConstantName: "runtime_memory",
    }
  );

}

function buildSessionCitationFragments() {

  const storage =
    window.JinRuntime
    && window.JinRuntime.storage;

  if (
    !storage
    || typeof storage.readLatestSavedSessionMemory !== "function"
  ) {
    return [];
  }

  const savedSession =
    storage.readLatestSavedSessionMemory();

  if (
    !savedSession
    || savedSession.explicit_save !== true
  ) {
    return [];
  }

  const sessionMemory =
    String(
      savedSession.session_memory || ""
    ).trim();

  if (!sessionMemory) {
    return [];
  }

  return buildMemoryCitationFragments(
    sessionMemory,
    {
      source: "latestSavedSessionMemory",
      sourceType: "session",
      citationType: "session_citation",
      layer: "session",
      idPrefix: "session",
      defaultConstantName: "session_memory",
    }
  );

}

function renderThinkRuleHighlights(job) {

  const element =
    job.element;

  if (
    !element
    || element.dataset.thinkId !== job.thinkId
  ) {
    return;
  }

  const text =
    job.text;
  const matches =
    resolveThinkRuleOverlaps(
      job.matches
    );

  if (!matches.length) {
    return false;
  }

  const fragment =
    document.createDocumentFragment();
  let cursor = 0;

  matches.forEach((match) => {
    const start = Math.max(
      0,
      Math.min(
        text.length,
        match.start
      )
    );
    const end = Math.max(
      start,
      Math.min(
        text.length,
        match.end
      )
    );

    if (start > cursor) {
      fragment.appendChild(
        document.createTextNode(
          text.slice(
            cursor,
            start
          )
        )
      );
    }

    const matchedText =
      text.slice(
        start,
        end
      );
    const span =
      document.createElement("span");

    span.className =
      getThinkCitationClassName(
        match
      );
    span.textContent =
      matchedText;
    span.title =
      buildThinkRuleTitle(
        match,
        matchedText
      );
    span.setAttribute(
      "aria-label",
      span.title
    );
    span.style.setProperty(
      "--think-match-score",
      String(
        Math.max(
          0,
          Math.min(
            1,
            Number(
              match.score || 0
            )
          )
        )
      )
    );

    fragment.appendChild(
      span
    );

    cursor = end;
  });

  if (cursor < text.length) {
    fragment.appendChild(
      document.createTextNode(
        text.slice(
          cursor
        )
      )
    );
  }

  element.replaceChildren(
    fragment
  );
  element.classList.add(
    "has-rule-highlights"
  );
  element.__jinThinkTextNode = null;

  updateThinkExpandedHeight(
    element
  );

  job.matches =
    matches;

  return true;

}

function pulseThinkRuleHighlights(job) {

  const element =
    job.element;

  if (
    !element
    || element.dataset.thinkId !== job.thinkId
  ) {
    return;
  }

  if (element.__jinThinkRulePulseTimer) {
    clearTimeout(
      element.__jinThinkRulePulseTimer
    );
  }

  element.classList.remove(
    "is-rule-highlight-revealing"
  );

  void element.offsetWidth;

  element.classList.add(
    "is-rule-highlight-revealing"
  );

  element.__jinThinkRulePulseTimer = setTimeout(
    () => {
      element.classList.remove(
        "is-rule-highlight-revealing"
      );
      element.__jinThinkRulePulseTimer = null;
    },
      5000
    );

}

function handleThinkRuleWorkerMessage(event) {

  const data =
    event.data
    || {};
  const thinkId =
    data.thinkId;
  const job =
    activeThinkRuleCitationJobs.get(
      thinkId
    );

  if (
    !job
    || !job.element
    || job.element.dataset.thinkId !== thinkId
  ) {
    return;
  }

  if (
    data.type === "ruleMatchesChunk"
  ) {
    job.matches = resolveThinkRuleOverlaps(
      [
        ...job.matches,
        ...(data.matches || []),
      ]
    );
    return;
  }

  if (
    data.type === "ruleMatchesDone"
  ) {
    job.done = true;
    if (
      renderThinkRuleHighlights(
        job
      )
    ) {
      requestAnimationFrame(
        () => pulseThinkRuleHighlights(
          job
        )
      );
    }
    activeThinkRuleCitationJobs.delete(
      thinkId
    );
  }

}

function startThinkRuleCitationAnalysis(
  messageId,
  stream
) {

  if (
    !stream
    || !stream.group
    || !stream.group.createdThinking
    || !stream.group.thinkContent
    || !stream.thinking.trim()
  ) {
    return;
  }

  const thinkContent =
    stream.group.thinkContent;
  const thinkId =
    String(
      messageId
    );
  const text =
    stream.thinking;
  const runtimeCitationIndex =
    Number.isInteger(
      stream.runtimeCitationIndex
    )
      ? stream.runtimeCitationIndex
      : nextThinkRuntimeCitationIndex++;

  stream.runtimeCitationIndex =
    runtimeCitationIndex;

  thinkContent.dataset.thinkId =
    thinkId;
  thinkContent.dataset.runtimeCitationIndex =
    String(
      runtimeCitationIndex
    );
  thinkContent.__jinThinkRawText =
    text;

  activeThinkRuleCitationJobs.set(
    thinkId,
    {
      thinkId,
      element: thinkContent,
      text,
      runtimeCitationIndex,
      matches: [],
      done: false,
    }
  );

  loadThinkRuleCitationRegistry()
    .then((registry) => {
      const currentJob =
        activeThinkRuleCitationJobs.get(
          thinkId
        );

      if (
        !currentJob
        || !registry.enabled
        || !Array.isArray(
          registry.fragments
        )
        || thinkContent.dataset.thinkId !== thinkId
      ) {
        activeThinkRuleCitationJobs.delete(
          thinkId
        );
        return;
      }

      const fragments = [
        ...registry.fragments,
        ...buildRuntimeCitationFragments(
          currentJob.runtimeCitationIndex
        ),
        ...buildSessionCitationFragments(),
      ];

      if (!fragments.length) {
        activeThinkRuleCitationJobs.delete(
          thinkId
        );
        return;
      }

      const worker =
        getThinkRuleCitationWorker();

      if (!worker) {
        activeThinkRuleCitationJobs.delete(
          thinkId
        );
        return;
      }

      worker.postMessage(
        {
          type: "analyzeThinkRules",
          thinkId,
          text,
          fragments,
        }
      );
    });

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

  if (role === "user") {
    jinConversationTurnCounter += 1;
    window.jinConversationTurnCounter =
      jinConversationTurnCounter;
  }

  flushRuntimeActionsAfterResponse(
    role
  );

}


// RUNTIME ACTION

function normalizeRuntimeActionKeyPart(value) {

  return String(
    value || ""
  ).trim().toLowerCase();

}

function buildRuntimeActionVisibleKey(
  action,
  options = {}
) {

  const actionName =
    normalizeRuntimeActionKeyPart(
      action
    );

  const actionId =
    normalizeRuntimeActionKeyPart(
      options.id
    );

  if (actionId) {
    return `${actionName}:${actionId}`;
  }

  return `${jinConversationTurnCounter}:${actionName}`;

}

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
    return false;
  }

  const actionKey =
    buildRuntimeActionVisibleKey(
      action,
      options
    );

  if (
    actionKey
    && visibleRuntimeActionKeys.has(
      actionKey
    )
  ) {
    return false;
  }

  if (actionKey) {
    visibleRuntimeActionKeys.add(
      actionKey
    );
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

  row.dataset.runtimeActionKey =
    actionKey || "";

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

  return true;

}


function queueRuntimeActionAfterNextResponse(
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

  deferredRuntimeActionsAfterResponse.push({
    action:
      action || "",
    text: actionText,
    id: options.id || "",
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
        id: entry.id || "",
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
      /(^|\n)[^\S\r\n]*<INTERNAL_ACTION_(?:DEEP_THOUGHT|SAVE_SESSION|REMEMBER_EVENT)>[^\S\r\n]*(?=\n|$)/gi,
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

    startThinkRuleCitationAnalysis(
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
