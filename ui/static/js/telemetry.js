function readInitialRuntimeConfig() {

  if (window.jinRuntimeConfig) {
    return window.jinRuntimeConfig;
  }

  const configTemplate =
    document.getElementById(
      "jin-runtime-config"
    );

  if (!configTemplate) {
    return {};
  }

  try {
    return JSON.parse(
      configTemplate.textContent || "{}"
    );
  } catch (error) {
    return {};
  }

}

/**
 * @typedef {Object} RuntimeInfo
 * @property {string=} label
 * @property {string=} model
 * @property {number=} used_tokens
 * @property {number=} context_tokens
 * @property {number=} total_tokens
 * @property {number=} max_tokens
 */

/**
 * @typedef {Object} RuntimeStatusPayload
 * @property {string} type
 * @property {Object<string, RuntimeInfo>=} runtime
 * @property {boolean=} brain
 * @property {boolean=} service
 * @property {boolean=} use_service_as_brain
 * @property {Object<string, RuntimeInfo>=} runtime_config
 */


const initialRuntimeConfig =
  readInitialRuntimeConfig();

window.jinRuntimeConfig =
  initialRuntimeConfig;

const runtimePanelState = {
  activeTab: "service",
  useServiceAsBrain: Boolean(
    initialRuntimeConfig.useServiceAsBrain
  ),
  runtimeStatus: (
    initialRuntimeConfig.runtimeStatus
  ) || {},
  fallbackRuntimes: (
    initialRuntimeConfig.runtimeConfig
  ) || {},
  liveRuntimes: [],
};

const TELEMETRY_FRAME_WARNING_MS = 12;
const CONTEXT_PANEL_RENDER_THROTTLE_MS = 300;
const SAVE_RUNTIME_PHEROMONE_STRENGTH = true;
const USER_IDLE_REFRESH_MS = 1000;
const USER_IDLE_TYPING_RESUME_DELAY_MS = 30000;

let userIdleStartedAt = Date.now();
let userIdleTimer = null;
let userIdleValueNode = null;
let userIdlePausedAt = null;
let userIdleResumeTimer = null;
let userIdleInputFreezeInstalled = false;

let telemetryFrameScheduled = false;
let contextPanelRenderTimer = null;

const contextTabButtons = {
  service: document.getElementById(
    "service-context-tab"
  ),
  brain: document.getElementById(
    "brain-context-tab"
  ),
};

const contextRuntimePanel =
  document.getElementById(
    "context-runtime-panel"
  );

const runtimeMemoryText =
  document.getElementById(
    "runtime-memory-text"
  );

const runtimeMemoryPanel =
    document.getElementById("settings-panel");

const runtimeMemoryCount =
  document.getElementById(
    "runtime-memory-count"
  );

const sessionMemoryStorageKey =
  "jin.sessionMemory.v1";

const runtimeMemoryStorageKey =
  "jin.runtimeMemory.latest.v1";

const sessionRuntimeMemoryStorageKey =
  "jin.sessionRuntimeMemory.v1";

const savedRuntimeFallbackPath =
  "/saved_runtime.txt";

const defaultRuntimeMemoryText =
  "This session has just begun. "
  + "You have no history with the user yet.";

const runtimeMemoryHistory = {
  snapshots: [],
  index: -1,
};

const pinnedRuntimeMemorySnapshotIndexes = new Set();

let runtimeMemoryDisplayMode = "runtime";
let restoredSessionMemorySnapshot = null;
let pendingBootstrapRuntimeMemorySnapshot = null;
let lastStableRuntimeMemorySnapshot = null;
let pendingSessionSaveRuntimeMemorySnapshot = null;

const runtimeDiffHistory = {
  diffs: [],
  stats: {},
  expanded: false,
};

function formatUserIdleDuration(ms) {
  const totalSeconds = Math.max(
      0,
      Math.floor(Number(ms || 0) / 1000)
  );

  if (totalSeconds < 60) {
    return `${totalSeconds}s`;
  }

  const totalMinutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;

  if (totalMinutes < 60) {
    return seconds
      ? `${totalMinutes}m ${seconds}s`
      : `${totalMinutes}m`;
  }

  const totalHours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;

  if (totalHours < 24) {
    return minutes
      ? `${totalHours}h ${minutes}m`
      : `${totalHours}h`;
  }

  const days = Math.floor(totalHours / 24);
  const hours = totalHours % 24;

  return hours
    ? `${days}d ${hours}h`
    : `${days}d`;
}

function getUserIdleElapsedMs() {
  const now =
      userIdlePausedAt !== null
        ? userIdlePausedAt
        : Date.now();

  return now - userIdleStartedAt;
}

function getUserIdleText() {
  return formatUserIdleDuration(
      getUserIdleElapsedMs()
  );
}

function updateUserIdleTimerText() {
  if (!userIdleValueNode) {
    return;
  }

  userIdleValueNode.textContent =
      ` ${getUserIdleText()}`;
}

function clearUserIdleResumeTimer() {
  if (!userIdleResumeTimer) {
    return;
  }

  clearTimeout(
      userIdleResumeTimer
  );

  userIdleResumeTimer = null;
}

function stopUserIdleTimer() {
  if (!userIdleTimer) {
    return;
  }

  clearInterval(
      userIdleTimer
  );

  userIdleTimer = null;
}

function ensureUserIdleTimer() {
  if (userIdlePausedAt !== null) {
    return;
  }

  if (userIdleTimer) {
    return;
  }

  userIdleTimer = setInterval(
      updateUserIdleTimerText,
      USER_IDLE_REFRESH_MS
  );
}

function isUserIdleChatInputFocused() {
  const input =
      document.getElementById(
        "user-input"
      );

  return Boolean(
      input
      && document.activeElement === input
  );
}

function resumeUserIdleTimer() {
  if (userIdlePausedAt === null) {
    ensureUserIdleTimer();
    return;
  }

  const frozenElapsed =
      Math.max(
        0,
        userIdlePausedAt - userIdleStartedAt
      );

  userIdleStartedAt =
      Date.now() - frozenElapsed;

  userIdlePausedAt = null;
  clearUserIdleResumeTimer();
  updateUserIdleTimerText();
  ensureUserIdleTimer();
}

function scheduleUserIdleResumeIfChatLostFocus() {
  clearUserIdleResumeTimer();

  if (userIdlePausedAt === null) {
    return;
  }

  userIdleResumeTimer = setTimeout(
      function () {
        userIdleResumeTimer = null;

        if (
            isUserIdleChatInputFocused()
            && document.hasFocus()
            && !document.hidden
        ) {
          return;
        }

        resumeUserIdleTimer();
      },
      USER_IDLE_TYPING_RESUME_DELAY_MS
  );
}

function pauseUserIdleTimerForTyping() {
  if (userIdlePausedAt === null) {
    userIdlePausedAt = Date.now();
  }

  stopUserIdleTimer();
  updateUserIdleTimerText();
  scheduleUserIdleResumeIfChatLostFocus();
}

function resetUserIdleTimer() {
  userIdleStartedAt = Date.now();
  userIdlePausedAt = null;
  clearUserIdleResumeTimer();
  updateUserIdleTimerText();
  ensureUserIdleTimer();
}

function installUserIdleInputFreeze() {
  if (userIdleInputFreezeInstalled) {
    return;
  }

  const input =
      document.getElementById(
        "user-input"
      );

  if (!input) {
    return;
  }

  userIdleInputFreezeInstalled = true;

  input.addEventListener(
      "input",
      pauseUserIdleTimerForTyping
  );

  input.addEventListener(
      "focus",
      function () {
        if (userIdlePausedAt !== null) {
          clearUserIdleResumeTimer();
        }
      }
  );

  input.addEventListener(
      "blur",
      scheduleUserIdleResumeIfChatLostFocus
  );

  window.addEventListener(
      "blur",
      scheduleUserIdleResumeIfChatLostFocus
  );

  document.addEventListener(
      "visibilitychange",
      function () {
        if (document.hidden) {
          scheduleUserIdleResumeIfChatLostFocus();
        }
      }
  );
}

window.jinResetUserIdleTimer =
    resetUserIdleTimer;

function getJinUserIdleContext() {
  const elapsedMs = Math.max(
      0,
      getUserIdleElapsedMs()
  );

  return {
    user_idle: formatUserIdleDuration(
        elapsedMs
    ),
    user_idle_seconds: Math.floor(
        elapsedMs / 1000
    ),
    user_idle_paused: userIdlePausedAt !== null,
  };
}

window.getJinUserIdleContext =
    getJinUserIdleContext;

window.jinWebSocketConnected = false;

let persistedSessionBootstrapCleared = false;
let hasUnsavedSessionActivity = false;

function isTelemetryDebugEnabled() {

  return Boolean(
    window.jinStreamDebug
    || window.jinDebugMode
  );

}


function telemetryNowMs() {

  return (
    window.performance
    && window.performance.now
  )
    ? window.performance.now()
    : Date.now();

}


function requestTelemetryFrame(callback) {

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


function renderLiveRuntimeTelemetry() {

  const serviceRuntime =
    getRuntimeByLabel(
      "service"
    );

  const brainRuntime =
    getBrainRuntime();

  updateChatHeader(
    serviceRuntime,
    brainRuntime
  );

  const selectedRuntime =
    isContextTabDisabled(
      runtimePanelState.activeTab
    )
      ? null
      : getSelectedRuntime();

  setContextPanelRuntime(
    selectedRuntime
  );

}


function flushRuntimeTelemetryFrame() {

  const startedAt =
    telemetryNowMs();

  telemetryFrameScheduled = false;

  renderLiveRuntimeTelemetry();

  const elapsed =
    telemetryNowMs() - startedAt;

  if (
    isTelemetryDebugEnabled()
    && elapsed > TELEMETRY_FRAME_WARNING_MS
  ) {
    console.warn(
      "[telemetry] frame update took",
      `${elapsed.toFixed(1)}ms`
    );
  }

}


function scheduleRuntimeTelemetryFrame() {

  if (telemetryFrameScheduled) {
    return;
  }

  telemetryFrameScheduled = true;

  requestTelemetryFrame(
    flushRuntimeTelemetryFrame
  );

}


function scheduleContextPanelRender(
  final = false
) {

  if (final) {
    if (contextPanelRenderTimer) {
      clearTimeout(
        contextPanelRenderTimer
      );

      contextPanelRenderTimer = null;
    }

    renderContextPanel();
    return;
  }

  if (contextPanelRenderTimer) {
    return;
  }

  contextPanelRenderTimer = setTimeout(
    function () {
      contextPanelRenderTimer = null;
      renderContextPanel();
    },
    CONTEXT_PANEL_RENDER_THROTTLE_MS
  );

}


function scheduleRuntimeTelemetryRender() {

  scheduleRuntimeTelemetryFrame();
  scheduleContextPanelRender();

}


function flushRuntimeTelemetryRender(
  options = {}
) {

  if (telemetryFrameScheduled) {
    flushRuntimeTelemetryFrame();
  }

  if (options.final) {
    scheduleContextPanelRender(
      true
    );
  }

}

function readBrowserMemory(
  key
) {

  try {
    return JSON.parse(
      window.localStorage.getItem(
        key
      ) || "null"
    );
  } catch (error) {
    return null;
  }

}


let savedRuntimeFileFallback = null;
let savedRuntimeFileFallbackLoaded = false;


function extractSavedRuntimeConstant(
  source,
  name
) {

  const normalizedSource =
    String(source || "").replace(
      /\r\n/g,
      "\n"
    );

  const markerIndex =
    normalizedSource.indexOf(
      name
    );

  if (markerIndex < 0) {
    return "";
  }

  const assignmentIndex =
    normalizedSource.indexOf(
      "=",
      markerIndex + name.length
    );

  if (assignmentIndex < 0) {
    return "";
  }

  const afterAssignment =
    normalizedSource.slice(
      assignmentIndex + 1
    );

  const openingMatch =
    afterAssignment.match(
      /["'`]/
    );

  if (!openingMatch) {
    return "";
  }

  const quote =
    openingMatch[0];

  const valueStart =
    assignmentIndex + 1 + openingMatch.index + 1;

  const closingIndex =
    normalizedSource.indexOf(
      `\n${quote}`,
      valueStart
    );

  if (closingIndex < 0) {
    return "";
  }

  return normalizedSource.slice(
    valueStart,
    closingIndex
  ).trim();

}


function parseSavedRuntimeText(
  source
) {

  const runtimeMemory =
    extractSavedRuntimeConstant(
      source,
      "SAVED_RUNTIME"
    );

  const sessionMemory =
    extractSavedRuntimeConstant(
      source,
      "SAVED_SESSION"
    );

  if (
      !runtimeMemory
      && !sessionMemory
  ) {
    return null;
  }

  return {
    runtime_memory: runtimeMemory,
    session_memory: sessionMemory,
    source: "saved_runtime_txt",
  };

}


function buildSavedRuntimeFallback(
  memory
) {

  if (!memory) {
    return null;
  }

  const runtimeMemory =
    (
      memory.runtime_memory
      && String(memory.runtime_memory).trim()
    )
    || "";

  const sessionMemory =
    (
      memory.session_memory
      && String(memory.session_memory).trim()
    )
    || "";

  if (
      !runtimeMemory
      && !sessionMemory
  ) {
    return null;
  }

  const source =
    memory.source || "saved_runtime_txt";

  const savedAt =
    new Date().toISOString();

  return {
    source: source,
    session_memory: sessionMemory
      ? {
          version: 1,
          explicit_save: true,
          saved_at: savedAt,
          session_memory: sessionMemory,
          session_event_snapshots: [],
          session_memory_updates: 1,
        }
      : null,
    session_runtime_memory: runtimeMemory
      ? {
          version: 1,
          explicit_save: true,
          saved_at: savedAt,
          runtime_memory: runtimeMemory,
          runtime_memory_updates: 1,
          runtime_snapshot: null,
        }
      : null,
    runtime_memory: runtimeMemory
      ? {
          version: 1,
          saved_at: savedAt,
          runtime_memory: runtimeMemory,
          runtime_memory_updates: 1,
          runtime_snapshot: null,
        }
      : null,
  };

}


function getSavedRuntimeMemoryFallback() {

  return buildSavedRuntimeFallback(
    savedRuntimeFileFallback
  );

}


async function loadSavedRuntimeMemoryFallback() {

  if (savedRuntimeFileFallbackLoaded) {
    return savedRuntimeFileFallback;
  }

  savedRuntimeFileFallbackLoaded = true;

  if (
      !window.fetch
      || !savedRuntimeFallbackPath
  ) {
    return null;
  }

  try {
    const response =
      await window.fetch(
        savedRuntimeFallbackPath,
        {
          cache: "no-store",
        }
      );

    if (!response.ok) {
      return null;
    }

    savedRuntimeFileFallback =
      parseSavedRuntimeText(
        await response.text()
      );
  } catch (error) {
    savedRuntimeFileFallback = null;
  }

  return savedRuntimeFileFallback;

}


window.jinSavedRuntimeFallbackReady =
  loadSavedRuntimeMemoryFallback();


function writeBrowserMemory(
  key,
  value
) {

  try {
    window.localStorage.setItem(
      key,
      JSON.stringify(value)
    );
  } catch (error) {
    // Browser memory is helpful, not required for chat.
  }

}


function buildPersistedRuntimeSnapshot(
  snapshot
) {

  if (
      !SAVE_RUNTIME_PHEROMONE_STRENGTH
      || !snapshot
      || typeof snapshot !== "object"
  ) {
    return null;
  }

  return {
    ...snapshot,
    persisted_pheromone_strength: true,
  };

}


function persistRuntimeMemorySnapshot(
  data
) {

  if (
      !data
      || !data.snapshot
  ) {
    return;
  }

  if (Number(data.updates || 0) <= 0) {
    return;
  }

  const runtimeMemory =
    (
      data.snapshot.raw_memory
      || data.memory
      || ""
    ).trim();

  if (!runtimeMemory) {
    return;
  }

  // A manual "save session" turn creates a temporary L1 page like
  // "session saved / remembering this session". That is not the actual
  // runtime state the user wanted to preserve. Keep the previous real L1
  // snapshot as Latest runtime instead of overwriting it with save chatter.
  if (runtimeSnapshotLooksLikeSessionSaveResult(data.snapshot)) {
    return;
  }

  const savedAt =
    new Date().toISOString();

  writeBrowserMemory(
    runtimeMemoryStorageKey,
    {
      version: 1,
      saved_at: savedAt,
      runtime_memory: runtimeMemory,
      runtime_memory_updates: data.updates || 0,
      runtime_snapshot: buildPersistedRuntimeSnapshot(
        data.snapshot
      ),
    }
  );

}


function runtimeMemoryObjectFromSnapshot(
  snapshot
) {

  const runtimeMemory =
    (
      snapshot
      && snapshot.raw_memory
      && snapshot.display_source !== "default_runtime_memory"
      && snapshot.raw_memory
    )
    || "";

  if (!runtimeMemory.trim()) {
    return null;
  }

  return {
    runtime_memory: runtimeMemory.trim(),
    runtime_memory_updates:
      (
        snapshot
        && snapshot.runtime_memory_updates
      )
      || (
        runtimeMemoryCount
        && Number(runtimeMemoryCount.textContent || 0)
      )
      || 0,
    runtime_snapshot: buildPersistedRuntimeSnapshot({
      ...snapshot,
      raw_memory: runtimeMemory.trim(),
    }),
  };

}


function runtimeMemoryObjectFromPersistedRuntime(
  persisted
) {

  if (!persisted || typeof persisted !== "object") {
    return null;
  }

  let runtimeMemory =
    String(persisted.runtime_memory || "").trim();

  runtimeMemory = removeRuntimeMemoryLineByKey(
    runtimeMemory,
    runtimeResponseFeedbackKey
  );

  if (!runtimeMemory) {
    return null;
  }

  return {
    runtime_memory: runtimeMemory,
    runtime_memory_updates:
      Number(persisted.runtime_memory_updates || 0),
    runtime_snapshot:
      (
        persisted.runtime_snapshot
        && typeof persisted.runtime_snapshot === "object"
      )
        ? buildPersistedRuntimeSnapshot(
            persisted.runtime_snapshot
          )
        : null,
  };

}


function isUsableStableRuntimeSnapshot(
  snapshot
) {

  if (!snapshot || typeof snapshot !== "object") {
    return false;
  }

  const runtimeMemory =
    String(snapshot.raw_memory || "").trim();

  if (
      !runtimeMemory
      || runtimeMemory === defaultRuntimeMemoryText
      || snapshot.display_source === "default_runtime_memory"
      || snapshot.display_source === "browser_l3_restore_status"
      || snapshot.display_source === "l3_bootstrap_status"
  ) {
    return false;
  }

  if (runtimeSnapshotLooksLikeSessionSaveResult(snapshot)) {
    return false;
  }

  return true;

}


function rememberStableRuntimeSnapshot(
  snapshot
) {

  if (!isUsableStableRuntimeSnapshot(snapshot)) {
    return;
  }

  lastStableRuntimeMemorySnapshot = {
    ...snapshot,
  };

}


function getLatestStableRuntimeMemoryObject() {

  const snapshots =
    runtimeMemoryHistory.snapshots || [];

  for (let index = snapshots.length - 1; index >= 0; index -= 1) {
    const candidate = snapshots[index];

    if (!isUsableStableRuntimeSnapshot(candidate)) {
      continue;
    }

    const runtimeMemory =
      runtimeMemoryObjectFromSnapshot(candidate);

    if (runtimeMemory) {
      return runtimeMemory;
    }
  }

  const rememberedRuntimeMemory =
    runtimeMemoryObjectFromSnapshot(
      lastStableRuntimeMemorySnapshot
    );

  if (rememberedRuntimeMemory) {
    return rememberedRuntimeMemory;
  }

  const persistedRuntimeMemory =
    runtimeMemoryObjectFromPersistedRuntime(
      readBrowserMemory(runtimeMemoryStorageKey)
    );

  if (persistedRuntimeMemory) {
    return persistedRuntimeMemory;
  }

  return null;

}


function getRuntimeSnapshotSearchText(
  snapshot
) {

  if (!snapshot || typeof snapshot !== "object") {
    return "";
  }

  const parts = [
    snapshot.raw_memory,
    snapshot.memory,
    snapshot.current_request,
    snapshot.user_query,
    snapshot.last_jin_response,
    snapshot.display_source,
  ];

  if (Array.isArray(snapshot.lines)) {
    snapshot.lines.forEach(line => {
      if (!line || typeof line !== "object") {
        return;
      }

      parts.push(
        line.key,
        line.value
      );
    });
  }

  return parts
    .filter(Boolean)
    .map(part => String(part))
    .join("\n")
    .toLowerCase();

}


function runtimeTextLooksLikeOnlySessionSave(
  text
) {

  const runtimeMemory =
    String(text || "").toLowerCase();

  if (!runtimeMemory.trim()) {
    return false;
  }

  const hasSessionWord =
    runtimeMemory.includes("session")
    || runtimeMemory.includes("сесси");

  const hasSaveWord =
    runtimeMemory.includes("save")
    || runtimeMemory.includes("saved")
    || runtimeMemory.includes("saving")
    || runtimeMemory.includes("remembering")
    || runtimeMemory.includes("remember_session")
    || runtimeMemory.includes("сохран")
    || runtimeMemory.includes("запомн");

  return hasSessionWord && hasSaveWord;

}


function runtimeSnapshotHasConversationContext(
  snapshot
) {

  if (!snapshot || typeof snapshot !== "object") {
    return false;
  }

  const usefulKeys = new Set([
    "active_task",
    "current_focus",
    "current_request",
    "focus",
    "last_jin_response",
    "topic",
    "user_inquiry",
    "user_request",
  ]);

  if (!Array.isArray(snapshot.lines)) {
    return false;
  }

  return snapshot.lines.some(line => {
    if (!line || typeof line !== "object") {
      return false;
    }

    const key =
      String(line.key || "")
        .trim()
        .toLowerCase();

    const value =
      String(line.value || "")
        .trim();

    if (!value || !usefulKeys.has(key)) {
      return false;
    }

    return !runtimeTextLooksLikeOnlySessionSave(
      value
    );
  });

}


function runtimeSnapshotLooksLikeSessionSaveResult(
  snapshot
) {

  const runtimeMemory =
    getRuntimeSnapshotSearchText(
      snapshot
    );

  if (!runtimeMemory) {
    return false;
  }

  const hasSessionWord =
    runtimeMemory.includes("session")
    || runtimeMemory.includes("сесси");

  const hasSaveWord =
    runtimeMemory.includes("save")
    || runtimeMemory.includes("saved")
    || runtimeMemory.includes("saving")
    || runtimeMemory.includes("remembering")
    || runtimeMemory.includes("remember_session")
    || runtimeMemory.includes("сохран");

  const hasSaveResultPhrase = (
    runtimeMemory.includes("session saved")
    || runtimeMemory.includes("session state successfully saved")
    || runtimeMemory.includes("session state saved")
    || runtimeMemory.includes("current state is saved")
    || runtimeMemory.includes("state is saved")
    || runtimeMemory.includes("state saved")
    || runtimeMemory.includes("successfully saved")
    || runtimeMemory.includes("confirmed saving")
    || runtimeMemory.includes("confirmed saved")
    || runtimeMemory.includes("remembering this session")
    || runtimeMemory.includes("remember_session")
    || runtimeMemory.includes("сохрани сессию")
    || runtimeMemory.includes("сохранить сессию")
    || runtimeMemory.includes("сохраняю")
    || runtimeMemory.includes("сохранено")
    || runtimeMemory.includes("сессия сохран")
  );

  if (
      hasSaveResultPhrase
      || (
        hasSessionWord
        && hasSaveWord
      )
  ) {
    // Do not throw away a real L1 runtime page just because the last
    // turn also saved the session. The page after `save session` may
    // still contain the useful current context: previous user request,
    // active task, and last non-save JIN response. Only pure save-status
    // pages should be treated as save chatter.
    return !runtimeSnapshotHasConversationContext(
      snapshot
    );
  }

  return false;

}


function getRuntimeMemoryForSessionSave() {

  const pendingRuntimeMemory =
    runtimeMemoryObjectFromSnapshot(
      pendingSessionSaveRuntimeMemorySnapshot
    );

  if (pendingRuntimeMemory) {
    return pendingRuntimeMemory;
  }

  const stableRuntimeMemory =
    getLatestStableRuntimeMemoryObject();

  if (stableRuntimeMemory) {
    return stableRuntimeMemory;
  }

  return runtimeMemoryObjectFromPersistedRuntime(
    readBrowserMemory(runtimeMemoryStorageKey)
  );

}


function userMessageLooksLikeSessionSaveRequest(
  text
) {

  const normalizedText =
    String(text || "").toLowerCase();

  if (!normalizedText.trim()) {
    return false;
  }

  const hasSessionWord =
    normalizedText.includes("session")
    || normalizedText.includes("сесси");

  const hasSaveWord =
    normalizedText.includes("save")
    || normalizedText.includes("remember")
    || normalizedText.includes("сохран")
    || normalizedText.includes("запомн");

  return hasSessionWord && hasSaveWord;

}


window.prepareRuntimeMemoryForUserMessage = function (
  text
) {

  if (!userMessageLooksLikeSessionSaveRequest(text)) {
    return;
  }

  const stableRuntimeMemory =
    getLatestStableRuntimeMemoryObject();

  pendingSessionSaveRuntimeMemorySnapshot =
    (
      stableRuntimeMemory
      && stableRuntimeMemory.runtime_snapshot
    )
    || lastStableRuntimeMemorySnapshot
    || null;

};


function persistSessionMemory(
  data
) {

  if (
      !data
      || data.persist !== true
  ) {
    return;
  }

  const sessionMemory =
    (
      data.memory
      || ""
    ).trim();

  const eventSnapshots =
    Array.isArray(data.event_snapshots)
      ? data.event_snapshots
      : [];

  if (!sessionMemory) {
    if (!eventSnapshots.length) {
      return;
    }
  }

  const sessionRuntimeMemory =
    getRuntimeMemoryForSessionSave();

  const savedAt =
    new Date().toISOString();

  persistedSessionBootstrapCleared = false;
  hasUnsavedSessionActivity = false;

  writeBrowserMemory(
    sessionMemoryStorageKey,
    {
      version: 1,
      explicit_save: true,
      saved_at: savedAt,
      session_memory: sessionMemory,
      session_event_snapshots: eventSnapshots,
      session_memory_updates:
        data.updates || 0,
    }
  );

  writeBrowserMemory(
    sessionRuntimeMemoryStorageKey,
    {
      version: 1,
      explicit_save: true,
      saved_at: savedAt,
      runtime_memory:
        (
          sessionRuntimeMemory
          && sessionRuntimeMemory.runtime_memory
        ) || "",
      runtime_memory_updates:
        (
          sessionRuntimeMemory
          && sessionRuntimeMemory.runtime_memory_updates
        ) || 0,
      runtime_snapshot:
        buildPersistedRuntimeSnapshot(
          sessionRuntimeMemory
          && sessionRuntimeMemory.runtime_snapshot
        ),
    }
  );

  pendingSessionSaveRuntimeMemorySnapshot = null;

}


function getRuntimeMemoryForSoftReconnect() {

  return getRuntimeMemoryForSessionSave();

}


window.getSoftReconnectRuntimeResume = function () {

  const runtimeMemory =
    getRuntimeMemoryForSoftReconnect();

  const runtimeText =
    (
      runtimeMemory
      && runtimeMemory.runtime_memory
      && String(runtimeMemory.runtime_memory).trim()
    ) || "";

  if (!runtimeText) {
    return null;
  }

  return {
    type: "runtime_resume",
    runtime_memory: runtimeText,
    runtime_memory_updates:
      (
        runtimeMemory
        && runtimeMemory.runtime_memory_updates
      ) || 0,
    runtime_snapshot:
      (
        runtimeMemory
        && runtimeMemory.runtime_snapshot
      ) || null,
  };

};


function hasTabCloseSessionBootstrap() {

  if (persistedSessionBootstrapCleared) {
    return false;
  }

  return hasUnsavedSessionActivity;

}


function isReconnectInitialRuntimeMemoryUpdate(
  data
) {

  if (
      !data
      || !data.snapshot
  ) {
    return false;
  }

  if (Number(data.updates || 0) !== 0) {
    return false;
  }

  if (runtimeMemoryHistory.snapshots.length === 0) {
    return false;
  }

  const runtimeMemory =
    (
      data.snapshot.raw_memory
      || data.memory
      || ""
    ).trim();

  return runtimeMemory === defaultRuntimeMemoryText;

}


function normalizeRuntimeMemoryText(
  text
) {

  return String(text || "")
    .replace(/\\n/g, "\n")
    .replace(/\r\n/g, "\n")
    .replace(
      /(session_status\s*:\s*Active;\s*last updated at\s*)[^\n]+/gi,
      "$1<bootstrap_time>"
    )
    .split("\n")
    .map(line => line.trim())
    .filter(Boolean)
    .join("\n");

}


function getRuntimeMemoryTextFromUpdate(
  data
) {

  return normalizeRuntimeMemoryText(
    (
      data
      && data.snapshot
      && data.snapshot.raw_memory
    )
    || (
      data
      && data.memory
    )
    || ""
  );

}


function isLatestRuntimeMemoryDuplicate(
  data
) {

  if (
      !data
      || data.type !== "runtime_memory_update"
      || !runtimeMemoryHistory.snapshots.length
  ) {
    return false;
  }

  const latestSnapshot =
    runtimeMemoryHistory.snapshots[
      runtimeMemoryHistory.snapshots.length - 1
    ];

  const latestMemory = normalizeRuntimeMemoryText(
    latestSnapshot && latestSnapshot.raw_memory
  );

  const incomingMemory =
    getRuntimeMemoryTextFromUpdate(data);

  if (
      !latestMemory
      || !incomingMemory
      || latestMemory !== incomingMemory
  ) {
    return false;
  }

  // If the latest snapshot was restored from a previous session its
  // runtime_memory_updates counter belongs to that old session. The server
  // resets its counter to 0 on every new connection, so the first real L1
  // update (updates=1) is always <= the old session counter (e.g. 3).
  // Without this guard every post-bootstrap L1 update is incorrectly treated
  // as a duplicate and dropped, leaving the panel stuck on the restore placeholder.
  if (latestSnapshot && latestSnapshot.restored_from_session_save) {
    return false;
  }

  const latestUpdates = Number(
    (
      latestSnapshot
      && latestSnapshot.runtime_memory_updates
    ) || 0
  );

  const incomingUpdates = Number(
    data.updates || 0
  );

  return incomingUpdates <= latestUpdates;

}


function isBootstrapRuntimeMemoryDuplicate(
  data
) {

  if (
      !pendingBootstrapRuntimeMemorySnapshot
      || !data
      || data.type !== "runtime_memory_update"
  ) {
    return false;
  }

  const bootstrapMemory =
    normalizeRuntimeMemoryText(
      pendingBootstrapRuntimeMemorySnapshot.raw_memory
    );

  const incomingMemory =
    getRuntimeMemoryTextFromUpdate(
      data
    );

  if (
      !bootstrapMemory
      || !incomingMemory
      || bootstrapMemory !== incomingMemory
  ) {
    pendingBootstrapRuntimeMemorySnapshot = null;
    return false;
  }

  const bootstrapUpdates =
    Number(
      pendingBootstrapRuntimeMemorySnapshot.runtime_memory_updates || 0
    );

  const incomingUpdates =
    Number(data.updates || 0);

  if (
      incomingUpdates <= bootstrapUpdates
      || !hasUnsavedSessionActivity
  ) {
    pendingBootstrapRuntimeMemorySnapshot = null;
    return true;
  }

  pendingBootstrapRuntimeMemorySnapshot = null;
  return false;

}


function applyBootstrapRuntimeMemoryUpdate(
  data
) {

  if (
      !pendingBootstrapRuntimeMemorySnapshot
      || !data
      || data.type !== "runtime_memory_update"
      || Number(data.updates || 0) !== 0
      || !data.snapshot
  ) {
    return false;
  }

  const incomingBootstrapMemory =
    getRuntimeMemoryTextFromUpdate(data);

  const pendingBootstrapMemory =
    normalizeRuntimeMemoryText(
      pendingBootstrapRuntimeMemorySnapshot.raw_memory
    );

  const incomingIsSameSavedRuntime = Boolean(
    incomingBootstrapMemory
    && pendingBootstrapMemory
    && incomingBootstrapMemory === pendingBootstrapMemory
  );

  const bootstrapSnapshot = {
    ...data.snapshot,
    index: 0,
    runtime_memory_updates:
      incomingIsSameSavedRuntime
        ? Number(
            pendingBootstrapRuntimeMemorySnapshot
              .runtime_memory_updates || 0
          )
        : Number(data.updates || 0),
    restored_from_session_save:
      incomingIsSameSavedRuntime
        ? true
        : data.snapshot.restored_from_session_save,
  };

  const savedRuntimeSnapshot = {
    ...pendingBootstrapRuntimeMemorySnapshot,
    index: 1,
  };

  pendingBootstrapRuntimeMemorySnapshot = null;
  runtimeMemoryDisplayMode = "runtime";
  restoredSessionMemorySnapshot = null;

  if (window.stopMemoryGlow) {
    window.stopMemoryGlow();
  }

  if (incomingIsSameSavedRuntime) {
    // On a hard page refresh the server can echo the saved runtime as its
    // initial L1 update. The UI has already rendered that saved runtime from
    // localStorage, so appending the server echo creates two identical runtime
    // pages: <0> and <1>. Treat that echo as confirmation and keep one page.
    runtimeMemoryHistory.snapshots = [
      bootstrapSnapshot,
    ];
    runtimeMemoryHistory.index = 0;
  } else {
    // Page 0 is the fresh browser/L3 restore status from the server.
    // Page 1 keeps the real runtime state saved with the session.
    runtimeMemoryHistory.snapshots = [
      bootstrapSnapshot,
      savedRuntimeSnapshot,
    ];
    runtimeMemoryHistory.index = 1;
  }

  if (runtimeMemoryCount) {
    runtimeMemoryCount.textContent =
      String(
        (
          incomingIsSameSavedRuntime
            ? bootstrapSnapshot.runtime_memory_updates
            : savedRuntimeSnapshot.runtime_memory_updates
        )
        || data.updates
        || 0
      );
  }

  renderRuntimeMemorySnapshot();

  return true;

}


function handleTabCloseSessionBootstrap(event) {

  if (!hasTabCloseSessionBootstrap()) {
    return undefined;
  }

  event.preventDefault();
  event.returnValue = "Are you sure?";

  return "Are you sure?";

}


function splitMemoryTextLines(text) {

  return String(text || "")
    .replace(/\\n/g, "\n")
    .split(/\r?\n+/)
    .map(line => line.trim())
    .filter(Boolean);

}


function parseRuntimeMemoryLine(line) {

  const separatorIndex =
    line.indexOf(":");

  if (separatorIndex <= 0) {
    return {
      key: "session memory",
      value: line,
      status: "same",
      key_status: "same",
      value_status: "same",
      key_change_ratio: 0,
      value_change_ratio: 0,
    };
  }

  return {
    key: line.slice(0, separatorIndex).trim(),
    value: line.slice(separatorIndex + 1).trim(),
    status: "same",
    key_status: "same",
    value_status: "same",
    key_change_ratio: 0,
    value_change_ratio: 0,
  };

}


const runtimeResponseFeedbackKey =
  "JIN_LAST_RESPONSE_USER_FEEDBACK";

const runtimeResponseFeedbackDislikedValue =
  "User disliked your last response. "
  + "Before answering, find and understand why it failed using context or memory, then start the next reply with a brief acknowledgement of that miss, then continue with a concrete corrected answer.";

const runtimeResponseFeedbackNeutralValue =
  "User gave neutral feedback to your last response. "
  + "Continue carefully without changing course too much.";

const runtimeResponseFeedbackLikedValue =
  "User liked your last response. "
  + "Keep the current direction.";

const runtimeResponseFeedbackRatings = {
  disliked: "disliked",
  neutral: "neutral",
  liked: "liked",
};

// UI buttons can still use visual button names. Convert them only at the
// browser event boundary. Runtime memory and server payloads stay canonical:
// disliked / neutral / liked.
const runtimeResponseFeedbackButtonRatings = {
  minus: "disliked",
  zero: "neutral",
  plus: "liked",
};

let pendingRuntimeResponseFeedback = null;
let runtimeResponseFeedbackCommitted = false;


const jinAnswerRatingL1Gate = {
  generation: 0,
  waiting: false,
  waitingGeneration: 0,
  readyGeneration: 0,
  baselineUpdates: 0,
  // All gate generations strictly below this value are permanently locked:
  // the user has already submitted a subsequent message, so retroactive
  // ratings for those turns must be silently dropped.
  lockedBelowGeneration: 0,
};

function getLatestRuntimeMemoryUpdatesForRatingGate() {

  const latestSnapshot =
    runtimeMemoryHistory.snapshots.length
      ? runtimeMemoryHistory.snapshots[
        runtimeMemoryHistory.snapshots.length - 1
      ]
      : null;

  if (latestSnapshot && latestSnapshot.restored_from_session_save) {
    return 0;
  }

  return Number(
    (
      latestSnapshot
      && latestSnapshot.runtime_memory_updates
    )
    || (
      runtimeMemoryCount
      && runtimeMemoryCount.textContent
    )
    || 0
  );

}

function markJinAnswerRatingL1ReadyFromRuntimeUpdate(
  data,
  snapshotIndex = null
) {

  if (!jinAnswerRatingL1Gate.waiting) {
    return;
  }

  const incomingUpdates = Number(
    data && data.updates || 0
  );

  if (incomingUpdates <= jinAnswerRatingL1Gate.baselineUpdates) {
    return;
  }

  jinAnswerRatingL1Gate.waiting = false;
  jinAnswerRatingL1Gate.readyGeneration =
    jinAnswerRatingL1Gate.waitingGeneration;
  runtimeResponseFeedbackCommitted = false;

  const rawSnapshotIndex =
    snapshotIndex === undefined
      ? null
      : snapshotIndex;

  const numericSnapshotIndex = Number(
    rawSnapshotIndex
  );

  const resolvedSnapshotIndex = (
    rawSnapshotIndex !== null
    && rawSnapshotIndex !== ""
    && Number.isInteger(numericSnapshotIndex)
  )
    ? numericSnapshotIndex
    : null;

  document
    .querySelectorAll(
      ".jin-chat-bubble-service[data-rating-gate-generation]"
    )
    .forEach((bubble) => {
      if (
          Number(bubble.dataset.ratingGateGeneration || 0)
          === jinAnswerRatingL1Gate.readyGeneration
      ) {
        bubble.dataset.ratingL1Ready = "true";

        if (resolvedSnapshotIndex !== null) {
          bubble.dataset.runtimeSnapshotIndex =
            String(resolvedSnapshotIndex);
        }

        bubble.classList.remove(
          "jin-rating-l1-waiting"
        );
      }
    });

  window.dispatchEvent(
    new CustomEvent(
      "jin:l1-rating-gate-ready",
      {
        detail: {
          generation: jinAnswerRatingL1Gate.readyGeneration,
          updates: incomingUpdates,
          snapshotIndex: resolvedSnapshotIndex,
        },
      }
    )
  );

}

window.startJinAnswerRatingL1GateForTurn = function () {

  jinAnswerRatingL1Gate.generation += 1;
  jinAnswerRatingL1Gate.waiting = true;
  jinAnswerRatingL1Gate.waitingGeneration =
    jinAnswerRatingL1Gate.generation;
  jinAnswerRatingL1Gate.baselineUpdates =
    getLatestRuntimeMemoryUpdatesForRatingGate();

  // Hard-lock every bubble that belongs to a generation older than the one
  // we are about to start.  This is the authoritative guard: the user has
  // just sent a new message, so rating any previous assistant turn is no
  // longer valid regardless of the committed/waiting state of the feedback
  // flags.
  jinAnswerRatingL1Gate.lockedBelowGeneration =
    jinAnswerRatingL1Gate.generation;

  if (typeof document !== "undefined") {
    document
      .querySelectorAll(
        ".jin-chat-bubble-service[data-rating-gate-generation]"
      )
      .forEach((bubble) => {
        const bubbleGen = Number(bubble.dataset.ratingGateGeneration || 0);
        if (bubbleGen < jinAnswerRatingL1Gate.lockedBelowGeneration) {
          bubble.classList.remove("jin-rating-selected-active");
          bubble.classList.add("jin-rating-committed");
          bubble.dataset.ratingCommitted = "true";
          bubble.dataset.ratingPastTurn = "true";
        }
      });
  }

  return {
    generation: jinAnswerRatingL1Gate.waitingGeneration,
    baselineUpdates: jinAnswerRatingL1Gate.baselineUpdates,
  };

};

window.getJinAnswerRatingL1GateState = function () {

  return {
    ...jinAnswerRatingL1Gate,
  };

};

window.isJinAnswerRatingReadyForGateGeneration = function (
  generation
) {

  const gateGeneration = Number(generation || 0);

  if (!gateGeneration) {
    return !jinAnswerRatingL1Gate.waiting;
  }

  return gateGeneration === jinAnswerRatingL1Gate.readyGeneration;

};

function normalizeRuntimeResponseFeedbackRating(
  rating
) {

  const rawRating =
    String(rating || "").trim().toLowerCase();

  return (
    runtimeResponseFeedbackRatings[rawRating]
    || runtimeResponseFeedbackButtonRatings[rawRating]
    || null
  );

}


function buildRuntimeResponseFeedbackValue(
  feedback
) {

  if (feedback.rating === "disliked") {
    return runtimeResponseFeedbackDislikedValue;
  }

  if (feedback.rating === "liked") {
    return runtimeResponseFeedbackLikedValue;
  }

  return runtimeResponseFeedbackNeutralValue;

}


function removeRuntimeMemoryLineByKey(
  memory,
  key
) {

  const normalizedKey =
    String(key || "").trim().toLowerCase();

  return String(memory || "")
    .split(/\r?\n/)
    .map(line => line.trim())
    .filter(Boolean)
    .filter((line) => {
      const lineKey =
        line.split(":", 1)[0].trim().toLowerCase();

      return lineKey !== normalizedKey;
    })
    .join("\n")
    .trim();

}


function upsertRuntimeMemoryLine(
  memory,
  key,
  value
) {

  const cleanedMemory =
    removeRuntimeMemoryLineByKey(
      memory,
      key
    );

  return (
    cleanedMemory
      ? `${cleanedMemory}\n${key}: ${value}`
      : `${key}: ${value}`
  ).trim();

}


// In-place rating mutation: rating clicks are part of the current L1 page,
// not a new runtime memory page.
function getCurrentRuntimeSnapshotForFeedbackMutation(
  feedback = null
) {

  if (!runtimeMemoryHistory.snapshots.length) {
    return null;
  }

  const rawSnapshotIndex = feedback
    ? (
      feedback.runtimeSnapshotIndex
      ?? feedback.snapshotIndex
      ?? null
    )
    : null;

  const explicitSnapshotIndex = Number(
    rawSnapshotIndex
  );

  if (
      rawSnapshotIndex !== null
      && rawSnapshotIndex !== ""
      && Number.isInteger(explicitSnapshotIndex)
  ) {
    const explicitSnapshot =
      runtimeMemoryHistory.snapshots[explicitSnapshotIndex];

    if (explicitSnapshot) {
      return explicitSnapshot;
    }
  }

  const current =
    runtimeMemoryHistory.snapshots[runtimeMemoryHistory.index];

  if (current && runtimeMemoryDisplayMode === "runtime") {
    return current;
  }

  return runtimeMemoryHistory.snapshots[
    runtimeMemoryHistory.snapshots.length - 1
  ];

}


function getRuntimeFeedbackLineIdentity(line) {

  const key =
    String(line && line.key || "")
      .trim()
      .toLowerCase();

  const value =
    String(line && line.value || "")
      .trim();

  return `${key}\u0000${value}`;

}


function buildPreviousRuntimeFeedbackLineMaps(snapshot) {

  const byIdentity = new Map();
  const byKey = new Map();

  (snapshot && snapshot.lines || [])
    .forEach((line) => {
      if (!line || !line.key) {
        return;
      }

      const key =
        String(line.key || "")
          .trim()
          .toLowerCase();

      if (!key) {
        return;
      }

      byKey.set(key, line);
      byIdentity.set(
        getRuntimeFeedbackLineIdentity(line),
        line
      );
    });

  return {
    byIdentity,
    byKey,
  };

}


function preserveRuntimeFeedbackLineDiff(
  parsed,
  previousMaps
) {

  if (!parsed || !parsed.key) {
    return parsed;
  }

  const key =
    String(parsed.key || "")
      .trim()
      .toLowerCase();

  if (key === runtimeResponseFeedbackKey.toLowerCase()) {
    return {
      ...parsed,
      status: "changed",
      key_status: "same",
      value_status: "changed",
      value_change_ratio: 1,
      strength: 1,
    };
  }

  const previousExact = previousMaps.byIdentity.get(
    getRuntimeFeedbackLineIdentity(parsed)
  );

  if (previousExact) {
    return {
      ...previousExact,
      key: parsed.key,
      value: parsed.value,
    };
  }

  const previousByKey = previousMaps.byKey.get(key);

  if (previousByKey) {
    return {
      ...parsed,
      status: previousByKey.status || parsed.status,
      key_status: previousByKey.key_status || parsed.key_status,
      value_status: previousByKey.value_status || parsed.value_status,
      key_change_ratio:
        previousByKey.key_change_ratio
        ?? parsed.key_change_ratio,
      value_change_ratio:
        previousByKey.value_change_ratio
        ?? parsed.value_change_ratio,
      strength:
        previousByKey.strength
        ?? parsed.strength,
    };
  }

  return parsed;

}


function rebuildRuntimeFeedbackSnapshotLines(
  snapshot,
  runtimeMemory
) {

  const previousMaps =
    buildPreviousRuntimeFeedbackLineMaps(snapshot);

  return splitMemoryTextLines(runtimeMemory)
    .map((line) => (
      preserveRuntimeFeedbackLineDiff(
        parseRuntimeMemoryLine(line),
        previousMaps
      )
    ));

}


function applyRuntimeResponseFeedbackToCurrentSnapshot(
  feedback
) {

  const snapshot =
    getCurrentRuntimeSnapshotForFeedbackMutation(
      feedback
    );

  if (!snapshot) {
    return null;
  }

  const currentMemory =
    String(snapshot.raw_memory || "").trim();

  if (!currentMemory) {
    return null;
  }

  let cleanedMemory =
    removeRuntimeMemoryLineByKey(
      currentMemory,
      runtimeResponseFeedbackKey
    );

  const nextMemory =
    feedback && feedback.rating
      ? upsertRuntimeMemoryLine(
        cleanedMemory,
        runtimeResponseFeedbackKey,
        buildRuntimeResponseFeedbackValue(feedback)
      )
      : cleanedMemory;

  snapshot.raw_memory = nextMemory;
  snapshot.lines = rebuildRuntimeFeedbackSnapshotLines(
    snapshot,
    nextMemory
  );
  snapshot.client_feedback = (
    feedback && feedback.rating
  )
    ? feedback
    : null;
  snapshot.local_feedback_mutation = Boolean(
    feedback && feedback.rating
  );

  runtimeMemoryDisplayMode = "runtime";
  runtimeMemoryHistory.index =
    runtimeMemoryHistory.snapshots.indexOf(snapshot);

  if (runtimeMemoryHistory.index < 0) {
    runtimeMemoryHistory.index =
      runtimeMemoryHistory.snapshots.length - 1;
  }

  // Feedback is a transient one-turn alert for the next JIN response.
  // Keep it visible in the current UI snapshot, but do not save it as
  // stable runtime memory and do not persist it to localStorage.
  renderRuntimeMemorySnapshot();

  return snapshot;

}


window.recordJinAnswerRating = function (
  detail
) {

  if (runtimeResponseFeedbackCommitted) {
    return null;
  }

  // Generation guard: reject ratings for bubbles that belong to a turn
  // older than the one currently awaiting a response.  The user already
  // submitted a newer message, so mutating an earlier snapshot would
  // inject stale feedback into the wrong memory slice.
  const incomingGeneration = Number(
    detail && detail.ratingGateGeneration || 0
  );
  if (
    incomingGeneration > 0
    && incomingGeneration < jinAnswerRatingL1Gate.lockedBelowGeneration
  ) {
    return null;
  }

  const rating =
    normalizeRuntimeResponseFeedbackRating(
      detail && detail.rating
    );

  if (!rating) {
    return null;
  }

  pendingRuntimeResponseFeedback = {
    rating,
    runtimeSnapshotIndex:
      detail && detail.runtimeSnapshotIndex !== undefined
        ? detail.runtimeSnapshotIndex
        : null,
  };

  return applyRuntimeResponseFeedbackToCurrentSnapshot(
    pendingRuntimeResponseFeedback
  );

};


window.clearJinAnswerRating = function (
  detail = null
) {

  if (runtimeResponseFeedbackCommitted) {
    return null;
  }

  pendingRuntimeResponseFeedback = null;

  return applyRuntimeResponseFeedbackToCurrentSnapshot({
    runtimeSnapshotIndex:
      detail && detail.runtimeSnapshotIndex !== undefined
        ? detail.runtimeSnapshotIndex
        : null,
  });

};


window.getJinAnswerRatingForRuntime = function () {

  return pendingRuntimeResponseFeedback
    ? { ...pendingRuntimeResponseFeedback }
    : null;

};


window.consumePendingLastResponseRating = function () {

  const value = pendingRuntimeResponseFeedback
    ? { ...pendingRuntimeResponseFeedback }
    : null;

  pendingRuntimeResponseFeedback = null;

  if (value) {
    runtimeResponseFeedbackCommitted = true;
  }

  return value;

};


function buildRuntimeMemoryDisplaySnapshot(
  data
) {

  const runtimeMemory =
    String(
      (
        data
        && (
          data.runtime_memory
          || data.memory
          || (
            data.runtime_snapshot
            && data.runtime_snapshot.raw_memory
          )
        )
      )
      || ""
    ).trim();

  if (!runtimeMemory) {
    return null;
  }

  const sourceSnapshot =
    (
      data
      && data.runtime_snapshot
      && typeof data.runtime_snapshot === "object"
    )
      ? data.runtime_snapshot
      : {};

  return {
    ...sourceSnapshot,
    session_id:
      sourceSnapshot.session_id
      || "browser_restore",
    index: 0,
    display_source: "saved_runtime_at_session_save",
    raw_memory: runtimeMemory,
    lines:
      Array.isArray(sourceSnapshot.lines)
        && sourceSnapshot.raw_memory === runtimeMemory
        ? sourceSnapshot.lines
        : splitMemoryTextLines(runtimeMemory)
          .map(parseRuntimeMemoryLine),
    restored_from_session_save: true,
    runtime_memory_updates:
      Number(
        (
          data
          && (
            data.runtime_memory_updates
            || data.updates
          )
        )
        || 0
      ),
  };

}


function buildDefaultRuntimeMemorySnapshot() {

  return {
    session_id: "browser_restore",
    index: 0,
    display_source: "default_runtime_memory",
    raw_memory: defaultRuntimeMemoryText,
    lines: [
      {
        key: "note",
        value: defaultRuntimeMemoryText,
        status: "same",
        key_status: "same",
        value_status: "same",
        key_change_ratio: 0,
        value_change_ratio: 0,
      },
    ],
    runtime_memory_updates: 0,
  };

}


function applyRuntimeMemoryDisplaySnapshot(snapshot) {

  const displaySnapshot =
    snapshot || buildDefaultRuntimeMemorySnapshot();

  runtimeMemoryDisplayMode = "runtime";
  restoredSessionMemorySnapshot = null;
  pendingBootstrapRuntimeMemorySnapshot =
    displaySnapshot.restored_from_session_save
      ? displaySnapshot
      : null;
  runtimeMemoryHistory.snapshots = [displaySnapshot];
  runtimeMemoryHistory.index = 0;

  rememberStableRuntimeSnapshot(
    displaySnapshot
  );

  if (runtimeMemoryCount) {
    runtimeMemoryCount.textContent =
      String(displaySnapshot.runtime_memory_updates || 0);
  }

  renderRuntimeMemorySnapshot();

}


window.applyPersistedSessionBootstrap = function (bootstrap) {

  const snapshot =
    (
      bootstrap
      && bootstrap.runtime_display_snapshot
    )
    || buildRuntimeMemoryDisplaySnapshot(
      bootstrap || {}
    )
    || buildDefaultRuntimeMemorySnapshot();

  applyRuntimeMemoryDisplaySnapshot(
    snapshot
  );

};

window.getPersistedSessionBootstrap = function () {

  const savedRuntimeFallback =
    getSavedRuntimeMemoryFallback();

  const browserSessionMemory =
    readBrowserMemory(
      sessionMemoryStorageKey
    );

  const sessionMemory =
    (
      savedRuntimeFallback
      && savedRuntimeFallback.session_memory
    )
    || (
      browserSessionMemory
      && browserSessionMemory.explicit_save === true
        ? browserSessionMemory
        : null
    );

  if (
      !sessionMemory
      || sessionMemory.explicit_save !== true
  ) {
    return null;
  }

  const sessionMemorySource =
    (
      savedRuntimeFallback
      && savedRuntimeFallback.session_memory
    )
      ? savedRuntimeFallback.source
      : (
          browserSessionMemory
          && browserSessionMemory.explicit_save === true
            ? "browser_localStorage"
            : "unknown"
        );

  const sessionText =
    (
      sessionMemory
      && sessionMemory.explicit_save === true
      && sessionMemory.session_memory
    )
    || "";

  const browserSessionRuntimeMemory =
    readBrowserMemory(
      sessionRuntimeMemoryStorageKey
    );

  const sessionRuntimeMemory =
    (
      savedRuntimeFallback
      && savedRuntimeFallback.session_runtime_memory
    )
    || (
      browserSessionRuntimeMemory
      && browserSessionRuntimeMemory.explicit_save === true
        ? browserSessionRuntimeMemory
        : null
    );

  const legacyEmbeddedRuntimeMemory =
    (
      sessionMemory
      && (
        sessionMemory.runtime_memory
        || sessionMemory.runtime_snapshot
      )
    )
      ? sessionMemory
      : null;

  const runtimeMemory =
    (
      sessionRuntimeMemory
      && sessionRuntimeMemory.explicit_save === true
    )
      ? sessionRuntimeMemory
      : legacyEmbeddedRuntimeMemory;

  const runtimeText =
    (
      runtimeMemory
      && runtimeMemory.runtime_memory
    )
    || "";

  const eventSnapshots =
    (
      sessionMemory
      && Array.isArray(
        sessionMemory.session_event_snapshots
      )
      && sessionMemory.session_event_snapshots
    )
    || [];

  if (
      !sessionText
      && !eventSnapshots.length
  ) {
    return null;
  }

  const runtimeDisplaySnapshot =
    buildRuntimeMemoryDisplaySnapshot({
      runtime_memory: runtimeText,
      runtime_memory_updates:
        (
          runtimeMemory
          && runtimeMemory.runtime_memory_updates
        )
        || 0,
      runtime_snapshot:
        (
          runtimeMemory
          && runtimeMemory.runtime_snapshot
        )
        || null,
    }) || buildDefaultRuntimeMemorySnapshot();

  return {
    type: "session_bootstrap",
    session_memory: sessionText,
    session_memory_source: sessionMemorySource,
    session_memory_updates:
      (
        sessionMemory
        && sessionMemory.session_memory_updates
      )
      || 0,
    session_event_snapshots: eventSnapshots,
    runtime_memory: runtimeText,
    runtime_memory_updates:
      (
        runtimeMemory
        && runtimeMemory.runtime_memory_updates
      )
      || 0,
    runtime_snapshot:
      (
        runtimeMemory
        && runtimeMemory.runtime_snapshot
      )
      || null,
    runtime_display_snapshot: runtimeDisplaySnapshot,
  };

};


window.clearPersistedSessionBootstrap = function () {

  persistedSessionBootstrapCleared = true;
  hasUnsavedSessionActivity = false;

  try {
    window.localStorage.removeItem(
      sessionMemoryStorageKey
    );
    window.localStorage.removeItem(
      sessionRuntimeMemoryStorageKey
    );
    window.localStorage.removeItem(
      runtimeMemoryStorageKey
    );
  } catch (error) {
    // Browser memory is helpful, not required for chat.
  }

};


window.markSessionActivityDirty = function () {

  persistedSessionBootstrapCleared = false;
  hasUnsavedSessionActivity = true;

};


window.markSessionBootstrapActive =
  window.markSessionActivityDirty;


window.addEventListener(
  "beforeunload",
  handleTabCloseSessionBootstrap
);

function findRuntimeByLabel(
  runtimes,
  label
) {

  return runtimes.find(
    runtime =>
      runtime
      && runtime.label === label
  );

}


function getRuntimeByLabel(label) {

  const liveRuntime =
    findRuntimeByLabel(
      runtimePanelState.liveRuntimes,
      label
    );

  if (liveRuntime) {
    return liveRuntime;
  }

  return (
    runtimePanelState.fallbackRuntimes[label]
    || null
  );

}


function getBrainRuntime() {

  return (
    getRuntimeByLabel("brain")
    || (
      runtimePanelState.useServiceAsBrain
        ? getRuntimeByLabel("service")
        : null
    )
  );

}


function getSummarizerRuntime() {

  return getRuntimeByLabel(
    "summarizer"
  );

}


function getSelectedRuntime() {

  if (runtimePanelState.activeTab === "brain") {
    return getBrainRuntime();
  }

  return getRuntimeByLabel("service");

}


function hasRuntimeStatus(role) {

  return typeof (
    runtimePanelState.runtimeStatus[role]
  ) === "boolean";

}


function isRuntimeOnline(role) {

  if (!hasRuntimeStatus(role)) {
    return false;
  }

  return Boolean(
    runtimePanelState.runtimeStatus[role]
  );

}


function isContextTabDisabled(role) {

  return !isRuntimeOnline(role);

}


function formatContextTokens(runtime) {

  /** @type {RuntimeInfo|null} */
  const runtimeInfo =
    runtime;

  if (!runtimeInfo) {
    return {
      used: 0,
      max: 0,
    };
  }

  return {
    used: runtimeInfo.used_tokens || 0,
    max: runtimeInfo.max_tokens || 0,
  };

}


function getContextBarCells(barElement) {

  const width =
    barElement
      ? barElement.clientWidth
      : 0;

  if (!width) {
    return 24;
  }

  return Math.max(
    12,
    Math.floor(width / 7) + 3
  );

}

function getContextPressureColor(percent) {

  const clamped =
      Math.max(
          0,
          Math.min(
              100,
              Number(percent || 0)
          )
      );

  const hue =
      150 - (
          clamped * 1.35
      );

  const saturation = 68;
  const lightness = 64;

  return `hsl(${hue}, ${saturation}%, ${lightness}%)`;

}

function buildContextLine(
  runtime,
  cells
) {

  /** @type {RuntimeInfo|null} */
  const runtimeInfo =
    runtime;

  const used =
    runtimeInfo
      ? Number(runtimeInfo.used_tokens || 0)
      : 0;

  const contextUsed =
    runtimeInfo
      ? Number(
          runtimeInfo.context_tokens
          || runtimeInfo.used_tokens
          || 0
        )
      : 0;

  const totalUsed =
    runtimeInfo
      ? Math.max(
          contextUsed,
          Number(
            runtimeInfo.total_tokens
            || runtimeInfo.used_tokens
            || 0
          )
        )
      : 0;

  const max =
    runtimeInfo
      ? Number(runtimeInfo.max_tokens || 0)
      : 0;

  const rawPercent =
    max > 0
      ? Math.min(
          100,
          (used / max) * 100
        )
      : 0;

  const percent =
    Math.round(rawPercent);

  const percentLabel =
    used > 0
    && rawPercent < 1
      ? "<1%"
      : `${percent}%`;

  const filled =
    Math.round(
      (rawPercent / 100) * cells
    );

  const contextPercent =
    max > 0
      ? Math.min(
          100,
          (contextUsed / max) * 100
        )
      : 0;

  const totalPercent =
    max > 0
      ? Math.min(
          100,
          (totalUsed / max) * 100
        )
      : 0;

  const contextFilled =
    Math.min(
      cells,
      Math.round(
        (contextPercent / 100) * cells
      )
    );

  const totalFilled =
    Math.min(
      cells,
      Math.round(
        (totalPercent / 100) * cells
      )
    );

  const secondaryFilled =
    Math.max(
      0,
      totalFilled - contextFilled
    );

  const bar =
    "|".repeat(filled)
    + ".".repeat(cells - filled);

  return {
    percent,
    bar: `[${bar}]`,
    contextFilled,
    secondaryFilled,
    emptyFilled:
      Math.max(
        0,
        cells - totalFilled
      ),
    contextPercent:
      Math.round(contextPercent),
    totalPercent:
      Math.round(totalPercent),
    contextUsed,
    totalUsed,
    max,
    percentLabel,
  };

}


function renderContextBar(
  barElement,
  contextLine,
  pressureColor
) {

  if (!barElement) {
    return;
  }

  const solid =
    "|".repeat(
      contextLine.contextFilled
    );

  const secondary =
    "|".repeat(
      contextLine.secondaryFilled
    );

  const empty =
    ".".repeat(
      contextLine.emptyFilled
    );

  barElement.innerHTML =
    "["
    + `<span style="color: ${pressureColor}; opacity: 1">${solid}</span>`
    + `<span style="color: ${pressureColor}; opacity: 0.55">${secondary}</span>`
    + `<span style="color: ${pressureColor}; opacity: 0.28">${empty}</span>`
    + "]";

}


function setTabClasses(role) {

  const button =
    contextTabButtons[role];

  if (!button) {
    return;
  }

  const isActive =
    runtimePanelState.activeTab === role;

  const isDisabled =
    isContextTabDisabled(role);

  button.disabled =
    isDisabled;

  button.setAttribute(
    "aria-selected",
    String(isActive)
  );

  button.setAttribute(
    "aria-disabled",
    String(isDisabled)
  );

  if (isDisabled) {
    const borderClass =
      role === "service"
        ? "border-r border-slate-500/70 "
        : "";

    button.className =
      "h-8 "
      + borderClass
      + "text-[11px] font-bold uppercase tracking-widest text-slate-500 cursor-not-allowed";

    return;
  }

  if (isActive && role === "service") {
    button.className =
      "h-8 border-r border-slate-500/70 bg-slate-600/70 text-[11px] font-bold uppercase tracking-widest text-zinc-50 transition";

    return;
  }

  if (isActive) {
    button.className =
      "h-8 bg-slate-600/70 text-[11px] font-bold uppercase tracking-widest text-zinc-50 transition";

    return;
  }

  if (role === "service") {
    button.className =
      "h-8 border-r border-slate-500/70 text-[11px] font-bold uppercase tracking-widest text-slate-300 transition hover:bg-slate-600/50 hover:text-zinc-50";

    return;
  }

  button.className =
    "h-8 text-[11px] font-bold uppercase tracking-widest text-slate-300 transition hover:bg-slate-600/50 hover:text-zinc-50";

}


function setContextPanelRuntime(runtime) {

  if (contextRuntimePanel) {
    contextRuntimePanel.classList.toggle(
      "hidden",
      !runtime
    );
  }

  const titleElement =
    document.getElementById(
      "context-panel-title"
    );

  const modelElement =
    document.getElementById(
      "context-panel-model"
    );

  const summaryElement =
    document.getElementById(
      "context-summary-tokens"
    );

  const summaryUsedElement =
    document.getElementById(
      "context-summary-used"
    );

  const summaryMaxElement =
    document.getElementById(
      "context-summary-max"
    );

  const lineElement =
    document.getElementById(
      "context-window-line"
    );

  const barElement =
    document.getElementById(
      "context-window-bar"
    );

  const percentElement =
    document.getElementById(
      "context-window-percent"
    );

  const summarizerLineElement =
    document.getElementById(
      "summarizer-window-line"
    );

  const summarizerBarElement =
    document.getElementById(
      "summarizer-window-bar"
    );

  const summarizerPercentElement =
    document.getElementById(
      "summarizer-window-percent"
    );

  const tokenText =
    formatContextTokens(runtime);

  const contextLine =
    buildContextLine(
      runtime,
      getContextBarCells(
        barElement
      )
    );

  const pressureColor =
      getContextPressureColor(
          Math.max(
            contextLine.percent,
            contextLine.totalPercent
          )
      );

  const summarizerRuntime =
    getSummarizerRuntime();

  const summarizerTokenText =
    formatContextTokens(
      summarizerRuntime
    );

  const summarizerLine =
    buildContextLine(
      summarizerRuntime,
      getContextBarCells(
        summarizerBarElement
      )
    );

  const summarizerPressureColor =
      getContextPressureColor(
          Math.max(
            summarizerLine.percent,
            summarizerLine.totalPercent
          )
      );

  if (titleElement) {
    titleElement.textContent =
      `STATUS`;
  }

  if (modelElement) {
    modelElement.textContent =
      `${runtime ? runtime.model : "unknown"}`;
  }

  if (summaryElement) {
    summaryElement.setAttribute(
      "aria-label",
      `${tokenText.used} / ${tokenText.max}`
    );
  }

  if (summaryUsedElement) {
    summaryUsedElement.textContent =
      `${tokenText.used}\u00a0/`;
  }

  if (summaryMaxElement) {
    summaryMaxElement.textContent =
      `${tokenText.max}`;
  }

  if (lineElement) {
    lineElement.title =
      `context: ${contextLine.contextUsed} / ${contextLine.max} `
      + `(${contextLine.contextPercent}%), total: `
      + `${contextLine.totalUsed} / ${contextLine.max} `
      + `(${contextLine.totalPercent}%)`;
  }

  renderContextBar(
    barElement,
    contextLine,
    pressureColor
  );

  if (percentElement) {
    percentElement.textContent =
      contextLine.percentLabel;
    percentElement.style.color =
        pressureColor;
  }

  if (summarizerLineElement) {
    summarizerLineElement.title =
      `context: ${summarizerLine.contextUsed} / ${summarizerLine.max} `
      + `(${summarizerLine.contextPercent}%), total: `
      + `${summarizerLine.totalUsed} / ${summarizerLine.max} `
      + `(${summarizerLine.totalPercent}%)`;
  }

  renderContextBar(
    summarizerBarElement,
    summarizerLine,
    summarizerPressureColor
  );

  if (summarizerPercentElement) {
    summarizerPercentElement.textContent =
      summarizerLine.percentLabel;
    summarizerPercentElement.style.color =
        summarizerPressureColor;
  }

}


function updateChatHeader(
  serviceRuntime,
  brainRuntime
) {

  const brainModelElement =
    document.getElementById(
      "brain-model"
    );

  const serviceModelElement =
    document.getElementById(
      "service-model"
    );

  if (
    brainRuntime
    && brainModelElement
  ) {

    brainModelElement.textContent =
      `BRAIN: ${brainRuntime.model}`;

  }

  if (
    serviceRuntime
    && serviceModelElement
  ) {

    serviceModelElement.textContent =
      `SERVICE: ${serviceRuntime.model}`;

  }

}


function renderRuntimeMemory(
  memory,
  updates
) {

  if (window.stopMemoryGlow) {
    window.stopMemoryGlow();
  }

  if (runtimeMemoryText) {
    runtimeMemoryText.textContent =
      (
        memory
        && memory.trim()
      )
        ? memory.trim()
        : "";
  }

  if (runtimeMemoryCount) {
    runtimeMemoryCount.textContent =
      String(
        updates || 0
      );
  }

}


function renderContextPanel() {

  if (isContextTabDisabled(
    runtimePanelState.activeTab
  )) {

    const fallbackTab =
      ["brain", "service"].find(
        role => !isContextTabDisabled(role)
      );

    if (fallbackTab) {
      runtimePanelState.activeTab =
        fallbackTab;
    }
  }

  setTabClasses("service");
  setTabClasses("brain");

  const selectedRuntime =
    isContextTabDisabled(
      runtimePanelState.activeTab
    )
      ? null
      : getSelectedRuntime();

  setContextPanelRuntime(selectedRuntime);

}


function selectContextTab(role) {

  if (isContextTabDisabled(role)) {
    return;
  }

  runtimePanelState.activeTab =
    role;

  renderContextPanel();

}


Object.entries(
  contextTabButtons
).forEach(
  ([role, button]) => {

    if (!button) {
      return;
    }

    button.addEventListener(
      "click",
      function () {
        selectContextTab(
          role
        );
      }
    );

  }
);


window.addEventListener(
  "resize",
  function () {
    renderContextPanel();
  }
);


window.setUseServiceAsBrain = function (enabled) {

  runtimePanelState.useServiceAsBrain =
    Boolean(enabled);

  renderContextPanel();

};


window.setRuntimeStatusSnapshot = function (runtimeStatus) {

  runtimePanelState.runtimeStatus =
    runtimeStatus || {};

  renderContextPanel();

};


window.setRuntimeConfigSnapshot = function (runtimeConfig) {

  runtimePanelState.fallbackRuntimes =
    runtimeConfig || {};

  const serviceRuntime =
    getRuntimeByLabel(
      "service"
    );

  const brainRuntime =
    getBrainRuntime();

  updateChatHeader(
    serviceRuntime,
    brainRuntime
  );

  renderContextPanel();

};


window.updateRuntimePanelFromStatus = function (data) {

  if (!data) {
    return;
  }

  window.jinRuntimeConfig = {
    useServiceAsBrain:
      Boolean(
        data.use_service_as_brain
      ),
    runtimeStatus: {
      brain: Boolean(data.brain),
      service: Boolean(data.service),
    },
    runtimeConfig:
      data.runtime_config || {},
  };

  window.setRuntimeStatusSnapshot(
    window
      .jinRuntimeConfig
      .runtimeStatus
  );

  window.setUseServiceAsBrain(
    window
      .jinRuntimeConfig
      .useServiceAsBrain
  );

  window.setRuntimeConfigSnapshot(
    window
      .jinRuntimeConfig
      .runtimeConfig
  );

};


window.handleTelemetryMessage = function (data) {

  if (data.type !== "telemetry") {
    return;
  }

  runtimePanelState.liveRuntimes =
    Object.values(
      data.runtime || {}
    );

  scheduleRuntimeTelemetryRender();

};

window.flushRuntimeTelemetryRender =
  flushRuntimeTelemetryRender;


window.handleRuntimeMemoryMessage = function (data) {

  if (!data) {
    return;
  }

  if (data.type === "runtime_l1_diff_update") {
    runtimeDiffHistory.diffs =
        data.diffs || [];

    runtimeDiffHistory.stats =
        data.stats || {};

    renderRuntimeDiffs();

    return;
  }

  if (data.type === "runtime_session_memory_update") {
    persistSessionMemory(
      data
    );

    if (
        data.persist === true
        && window.fadeRuntimeAction
    ) {
      window.fadeRuntimeAction(
        "remember_session"
      );
    }

    if (window.stopL3MemoryGlow) {
      window.stopL3MemoryGlow();
    }

    return;
  }

  if (data.type !== "runtime_memory_update") {
    return;
  }

  if (isReconnectInitialRuntimeMemoryUpdate(data)) {
    return;
  }

  if (isLatestRuntimeMemoryDuplicate(data)) {
    return;
  }

  if (applyBootstrapRuntimeMemoryUpdate(data)) {
    return;
  }

  if (isBootstrapRuntimeMemoryDuplicate(data)) {
    return;
  }

  if (
      runtimeMemoryDisplayMode === "session"
      && restoredSessionMemorySnapshot
      && Number(data.updates || 0) === 0
  ) {
    persistRuntimeMemorySnapshot(
      data
    );

    return;
  }

  runtimeMemoryDisplayMode = "runtime";

  if (window.stopMemoryGlow) {
    window.stopMemoryGlow();
  }

  if (runtimeMemoryCount) {
    runtimeMemoryCount.textContent =
        String(data.updates || 0);
  }

  if (data.snapshot) {
    const clientIndex = runtimeMemoryHistory.snapshots.length;
    const clientSnapshot = {
      ...data.snapshot,
      index: clientIndex,
    };

    // The server-side snapshot.index can restart after bootstrap/restore.
    // The right panel is client-side history, so display positions must follow
    // the actual array order instead of reusing a stale server index.
    runtimeMemoryHistory.snapshots.push(clientSnapshot);
    runtimeMemoryHistory.index =
        runtimeMemoryHistory.snapshots.length - 1;

    resetUserIdleTimer();

    rememberStableRuntimeSnapshot(
      clientSnapshot
    );

    markJinAnswerRatingL1ReadyFromRuntimeUpdate(
      data,
      clientIndex
    );
  } else {
    markJinAnswerRatingL1ReadyFromRuntimeUpdate(
      data
    );
  }

  persistRuntimeMemorySnapshot(
    data
  );

  renderRuntimeMemorySnapshot();

};


if (window.jinLatestStatus) {

  window.updateRuntimePanelFromStatus(
    window.jinLatestStatus
  );

} else if (window.jinRuntimeConfig) {

  window.setRuntimeStatusSnapshot(
    window.jinRuntimeConfig.runtimeStatus || {}
  );

  window.setUseServiceAsBrain(
    window.jinRuntimeConfig.useServiceAsBrain
  );

  window.setRuntimeConfigSnapshot(
    window.jinRuntimeConfig.runtimeConfig || {}
  );

} else {

  renderContextPanel();

}

const runtimeMemoryPosition =
    document.getElementById("runtime-memory-position");

const runtimeMemoryPrev =
    document.getElementById("runtime-memory-prev");

const runtimeMemoryNext =
    document.getElementById("runtime-memory-next");

const runtimeDiffToggle =
    document.getElementById("runtime-diff-toggle");

const runtimeDiffText =
    document.getElementById("runtime-diff-text");

const runtimeDiffCount =
    document.getElementById("runtime-diff-count");

const runtimeDiffAverage =
    document.getElementById("runtime-diff-average");

const runtimeDiffRange =
    document.getElementById("runtime-diff-range");

const runtimeDiffMax =
    document.getElementById("runtime-diff-max");


function formatRuntimeDiffNumber(value) {
  const number =
      Number(value || 0);

  return String(
      Number.isInteger(number)
        ? number
        : Number(number.toFixed(2))
  );
}


function renderRuntimeDiffs() {
  const stats =
      runtimeDiffHistory.stats || {};

  if (runtimeDiffCount) {
    runtimeDiffCount.textContent =
        formatRuntimeDiffNumber(stats.count);
  }

  if (runtimeDiffAverage) {
    runtimeDiffAverage.textContent =
        formatRuntimeDiffNumber(stats.average);
  }

  if (runtimeDiffRange) {
    runtimeDiffRange.textContent =
        formatRuntimeDiffNumber(stats.range);
  }

  if (runtimeDiffMax) {
    runtimeDiffMax.textContent =
        formatRuntimeDiffNumber(stats.max);
  }

  if (runtimeDiffToggle) {
    runtimeDiffToggle.textContent =
        runtimeDiffHistory.expanded
          ? "hide diffs"
          : "show diffs";
  }

  if (!runtimeDiffText) {
    return;
  }

  runtimeDiffText.classList.toggle(
      "hidden",
      !runtimeDiffHistory.expanded
  );

  runtimeDiffText.textContent =
      runtimeDiffHistory.diffs.length
        ? JSON.stringify(
            runtimeDiffHistory.diffs,
            null,
            2
          )
        : "[]";
}


function isCurrentRuntimeMemorySnapshotPinned() {
  return pinnedRuntimeMemorySnapshotIndexes.has(
      runtimeMemoryHistory.index
  );
}

function updateRuntimeMemoryPinGlow() {
  if (!runtimeMemoryPosition) {
    return;
  }

  runtimeMemoryPosition.classList.toggle(
      "runtime-memory-position-pinned",
      isCurrentRuntimeMemorySnapshotPinned()
  );
}

function renderRuntimeMemorySnapshot() {
  const snapshot =
      runtimeMemoryHistory.snapshots[
          runtimeMemoryHistory.index
          ];

  if (!snapshot) {
    runtimeMemoryText.textContent = "";
    runtimeMemoryPosition.textContent =
        "0";
    updateRuntimeMemoryArrows();
    updateRuntimeMemoryPinGlow();
    return;
  }

  renderRuntimeMemoryLines(
      snapshot,
      isCurrentRuntimeMemorySnapshotPinned()
  );

  runtimeMemoryPosition.textContent =
      String(
          typeof snapshot.index === "number"
            ? snapshot.index
            : runtimeMemoryHistory.index + 1
      );

  updateRuntimeMemoryArrows();
  updateRuntimeMemoryPinGlow();
}

function clampMemoryRatio(value) {
  const number =
      Number(value || 0);

  return Math.max(
      0,
      Math.min(1, number)
  );
}

function applyRuntimeMemoryFlash(
    element,
    status,
    kind,
    ratio,
    persist = false
) {
  if (!element) {
    return;
  }

  if (status === "new") {
    element.classList.add("flash-new");
  }

  if (status === "changed") {
    element.classList.add("flash-changed");

    if (kind === "value") {
      const normalized =
          clampMemoryRatio(ratio);

      element.style.setProperty(
          "--memory-change-alpha",
          String(
              0.55 + normalized * 0.41
          )
      );

      element.style.setProperty(
          "--memory-change-glow",
          String(
              0.10 + normalized * 0.28
          )
      );
    }
  }

  if (
      status !== "new"
      && status !== "changed"
  ) {
    return;
  }

  if (persist) {
    return;
  }

  setTimeout(() => {
    element.classList.remove(
        "flash-new",
        "flash-changed"
    );

    element.style.removeProperty(
        "--memory-change-alpha"
    );

    element.style.removeProperty(
        "--memory-change-glow"
    );
  }, 1500);
}

function formatRuntimeMemoryStrengthSuffix(line) {
  const strength =
      Number(line && line.strength);

  if (!Number.isFinite(strength)) {
    return "";
  }

  return ` (trace: ${strength.toFixed(2)})`;
}

function renderRuntimeMemoryLines(snapshot, persistGlow = false) {
  if (!runtimeMemoryText) {
    return;
  }

  runtimeMemoryText.innerHTML = "";
  runtimeMemoryText.classList.toggle(
      "runtime-memory-text-pinned",
      persistGlow
  );

  const lines =
      snapshot.lines || [];

  if (!lines.length) {
    runtimeMemoryText.textContent =
        `${(snapshot.raw_memory || "").trim()}\n`;

    appendUserIdleRuntimeMemoryLine();
    installUserIdleInputFreeze();

    return;
  }

  lines.forEach((line) => {
    const row =
        document.createElement("div");

    row.className =
        "runtime-memory-line";

    const key =
        line.key || "note";

    const value =
        line.value || "";

    const keyStatus =
        line.key_status || line.status || "same";

    const valueStatus =
        line.value_status || line.status || "same";

    const keySpan =
        document.createElement("span");

    keySpan.className =
        "runtime-memory-key";

    keySpan.textContent =
        `${key}:`;

    const valueSpan =
        document.createElement("span");

    valueSpan.className =
        "runtime-memory-value";

    valueSpan.textContent =
        ` ${value}${formatRuntimeMemoryStrengthSuffix(line)}`;

    row.appendChild(keySpan);
    row.appendChild(valueSpan);

    runtimeMemoryText.appendChild(row);

    applyRuntimeMemoryFlash(
        keySpan,
        keyStatus,
        "key",
        line.key_change_ratio,
        persistGlow
    );

    applyRuntimeMemoryFlash(
        valueSpan,
        valueStatus,
        "value",
        line.value_change_ratio,
        persistGlow
    );
  });

  appendUserIdleRuntimeMemoryLine();
  installUserIdleInputFreeze();
}

function appendUserIdleRuntimeMemoryLine() {
  if (!runtimeMemoryText) {
    return;
  }

  const row =
      document.createElement("div");

  row.className =
      "runtime-memory-line runtime-memory-user-idle";

  const keySpan =
      document.createElement("span");

  keySpan.className =
      "runtime-memory-key";

  keySpan.textContent =
      "user_idle:";

  const valueSpan =
      document.createElement("span");

  valueSpan.className =
      "runtime-memory-value";

  userIdleValueNode =
      valueSpan;

  row.appendChild(keySpan);
  row.appendChild(valueSpan);

  runtimeMemoryText.appendChild(row);
  updateUserIdleTimerText();
  ensureUserIdleTimer();
}

function updateRuntimeMemoryArrows() {
  const canGoPrev =
      runtimeMemoryHistory.index > 0;

  const canGoNext =
      runtimeMemoryHistory.index <
      runtimeMemoryHistory.snapshots.length - 1;

  runtimeMemoryPrev.disabled = !canGoPrev;
  runtimeMemoryNext.disabled = !canGoNext;

  runtimeMemoryPrev.classList.toggle("opacity-30", !canGoPrev);
  runtimeMemoryNext.classList.toggle("opacity-30", !canGoNext);

  runtimeMemoryPrev.classList.toggle("cursor-default", !canGoPrev);
  runtimeMemoryNext.classList.toggle("cursor-default", !canGoNext);
  runtimeMemoryPrev.classList.toggle("text-emerald-300", canGoPrev);
  runtimeMemoryNext.classList.toggle("text-emerald-300", canGoNext);

  runtimeMemoryPrev.classList.toggle("text-slate-600", !canGoPrev);
  runtimeMemoryNext.classList.toggle("text-slate-600", !canGoNext);
}

runtimeMemoryPrev?.addEventListener("click", () => {
  if (runtimeMemoryHistory.index <= 0) return;

  runtimeMemoryHistory.index -= 1;
  renderRuntimeMemorySnapshot();
});

runtimeMemoryNext?.addEventListener("click", () => {
  if (
      runtimeMemoryHistory.index >=
      runtimeMemoryHistory.snapshots.length - 1
  ) return;

  runtimeMemoryHistory.index += 1;
  renderRuntimeMemorySnapshot();
});

runtimeMemoryPosition?.addEventListener("click", () => {
  if (runtimeMemoryHistory.index < 0) {
    return;
  }

  const wasPinned =
      isCurrentRuntimeMemorySnapshotPinned();

  if (wasPinned) {
    pinnedRuntimeMemorySnapshotIndexes.delete(
        runtimeMemoryHistory.index
    );
  } else {
    pinnedRuntimeMemorySnapshotIndexes.add(
        runtimeMemoryHistory.index
    );
  }

  renderRuntimeMemorySnapshot();

  if (wasPinned && runtimeMemoryText) {
    runtimeMemoryText
        .querySelectorAll(
            ".flash-new, .flash-changed"
        )
        .forEach((element) => {
          element.classList.add(
              "runtime-memory-flash-off"
          );
          element.classList.remove(
              "flash-new",
              "flash-changed"
          );

          requestAnimationFrame(() => {
            element.classList.remove(
                "runtime-memory-flash-off"
            );
          });
        });
  }
});

runtimeMemoryPosition?.addEventListener("keydown", (event) => {
  if (
      event.key !== "Enter"
      && event.key !== " "
  ) {
    return;
  }

  event.preventDefault();
  runtimeMemoryPosition.click();
});

runtimeDiffToggle?.addEventListener("click", () => {
  runtimeDiffHistory.expanded =
      !runtimeDiffHistory.expanded;

  renderRuntimeDiffs();
});

renderRuntimeMemorySnapshot();
renderRuntimeDiffs();
