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

const storage =
  window.JinRuntime
  && window.JinRuntime.storage;

if (!storage) {
  throw new Error(
    "JinRuntime.storage must be loaded before telemetry.js"
  );
}

const memoryModel =
  window.JinRuntime
  && window.JinRuntime.memoryModel;

if (!memoryModel) {
  throw new Error(
    "JinRuntime.memoryModel must be loaded before telemetry.js"
  );
}

const idle =
  window.JinRuntime
  && window.JinRuntime.idle;

if (!idle) {
  throw new Error(
    "JinRuntime.idle must be loaded before telemetry.js"
  );
}


const feedback =
  window.JinRuntime
  && window.JinRuntime.feedback;

if (!feedback) {
  throw new Error(
    "JinRuntime.feedback must be loaded before telemetry.js"
  );
}

const {
  splitMemoryTextLines,
  stripMemoryTextMetaForDisplay,
  isUserIdleRuntimeMemoryLine,
  stripUserIdleRuntimeMemoryText,
  parseRuntimeMemoryLine,
  getUserIdleRuntimeMemoryLine,
  setRuntimeMemorySnapshotUserIdle,
  removeRuntimeMemoryLineByKey,
  upsertRuntimeMemoryLine,
  buildRuntimeMemoryValuePresentation,
} = memoryModel;

const {
  keys: runtimeStorageKeys,
  removeBrowserMemory,
  readLatestRuntimeMemory,
  writeLatestRuntimeMemory,
  readLatestSavedSessionMemory,
  writeLatestSavedSessionMemory,
  readLatestSavedRuntimeMemory,
  writeLatestSavedRuntimeMemory,
  buildPersistedRuntimeSnapshot,
  cloneBootRuntimeMemoryIfNeeded,
  collectOtherLatestRuntimeMemorySnapshots,
  clearOtherLatestRuntimeMemorySnapshots,
  getSavedRuntimeMemoryFallback,
} = storage;

let userIdleValueNode = null;

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

const runtimeMemoryTitle =
  document.getElementById(
    "runtime-memory-title"
  );

const runtimeMemoryPanel =
    document.getElementById("settings-panel");

const runtimeMemoryCount =
  document.getElementById(
    "runtime-memory-count"
  );

const defaultRuntimeMemoryText =
  "This session has just begun. "
  + "You have no history with the user yet.";

const sessionStartedRuntimeMemoryText =
  "session_status: Session started";

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
let waitingForSessionSaveRuntimeSnapshot = false;
let pendingSessionMemoryPersistData = null;

cloneBootRuntimeMemoryIfNeeded();

const runtimeDiffHistory = {
  diffs: [],
  stats: {},
  expanded: false,
};

function getUserIdleText() {
  return idle.getText();
}

function updateUserIdleTimerText(
  text = getUserIdleText()
) {
  if (!userIdleValueNode) {
    return;
  }

  userIdleValueNode.textContent =
      ` ${text}`;

  updateRuntimeMemoryTitleMetrics(
      runtimeMemoryHistory.snapshots[
          runtimeMemoryHistory.index
      ]
  );
}

idle.configure({
  onIdleTextChanged(text) {
    updateUserIdleTimerText(
      text
    );
  },
});


feedback.init({
  memoryModel,
  getSnapshots() {
    return runtimeMemoryHistory.snapshots;
  },
  getCurrentIndex() {
    return runtimeMemoryHistory.index;
  },
  setCurrentIndex(index) {
    runtimeMemoryHistory.index = index;
  },
  getDisplayMode() {
    return runtimeMemoryDisplayMode;
  },
  setDisplayMode(mode) {
    runtimeMemoryDisplayMode = mode;
  },
  getRuntimeMemoryCountText() {
    return runtimeMemoryCount
      ? runtimeMemoryCount.textContent
      : "0";
  },
  renderRuntimeMemorySnapshot() {
    renderRuntimeMemorySnapshot();
  },
});

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

  const savedAt =
    new Date().toISOString();

  writeLatestRuntimeMemory({
    version: 1,
    session_id:
      storage.getCurrentRuntimeSessionId(),
    saved_at: savedAt,
    runtime_memory: runtimeMemory,
    runtime_memory_updates: data.updates || 0,
    runtime_snapshot: buildPersistedRuntimeSnapshot(
      data.snapshot
    ),
  });

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
    feedback.key
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
      readLatestRuntimeMemory()
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


function normalizeBehaviorContractSearchText(
  text
) {

  return String(text || "")
    .toLowerCase()
    .replace(/ё/g, "е");

}


function getBehaviorContractActionGuardPhrases(
  name,
  key
) {

  const contract =
    window.JIN_BEHAVIOR_CONTRACT;

  const guard =
    contract
    && contract.action_guards
    && contract.action_guards[name];

  const phrases =
    guard
    && guard[key];

  if (!Array.isArray(phrases)) {
    return [];
  }

  return phrases
    .filter(phrase => typeof phrase === "string");

}


function behaviorContractPhraseAppears(
  text,
  name,
  key
) {

  const normalizedText =
    normalizeBehaviorContractSearchText(
      text
    );

  return getBehaviorContractActionGuardPhrases(
    name,
    key
  ).some(phrase => (
    normalizedText.includes(
      normalizeBehaviorContractSearchText(
        phrase
      )
    )
  ));

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

  if (
      runtimeMemory.includes("session management")
      && runtimeMemory.includes("paused")
  ) {
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

  const hasRememberSessionTrigger =
    behaviorContractPhraseAppears(
      runtimeMemory,
      "remember_session",
      "triggers"
    );

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
    || hasRememberSessionTrigger
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
    // turn also saved the session. The page after a save request may
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
    readLatestRuntimeMemory()
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

  pendingSessionSaveRuntimeMemorySnapshot = null;
  waitingForSessionSaveRuntimeSnapshot = true;
  pendingSessionMemoryPersistData = null;

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

  if (
      waitingForSessionSaveRuntimeSnapshot
      && !pendingSessionSaveRuntimeMemorySnapshot
  ) {
    pendingSessionMemoryPersistData = data;
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

  const latestSavedRuntimeMemory =
    getRuntimeMemoryForSessionSave();

  const savedAt =
    new Date().toISOString();

  persistedSessionBootstrapCleared = false;
  hasUnsavedSessionActivity = false;

  writeLatestSavedSessionMemory({
    version: 1,
    explicit_save: true,
    saved_at: savedAt,
    session_memory: sessionMemory,
    session_event_snapshots: eventSnapshots,
    session_memory_updates:
      data.updates || 0,
  });

  writeLatestSavedRuntimeMemory({
    version: 1,
    explicit_save: true,
    saved_at: savedAt,
    runtime_memory:
      (
        latestSavedRuntimeMemory
        && latestSavedRuntimeMemory.runtime_memory
      ) || "",
    runtime_memory_updates:
      (
        latestSavedRuntimeMemory
        && latestSavedRuntimeMemory.runtime_memory_updates
      ) || 0,
    runtime_snapshot:
      buildPersistedRuntimeSnapshot(
        latestSavedRuntimeMemory
        && latestSavedRuntimeMemory.runtime_snapshot
      ),
  });

  pendingSessionSaveRuntimeMemorySnapshot = null;
  waitingForSessionSaveRuntimeSnapshot = false;
  pendingSessionMemoryPersistData = null;

}


function getRuntimeMemoryForSoftReconnect() {

  return getRuntimeMemoryForSessionSave();

}


function captureSessionSaveRuntimeSnapshot(
  snapshot
) {

  if (
      !waitingForSessionSaveRuntimeSnapshot
      || !snapshot
  ) {
    return;
  }

  pendingSessionSaveRuntimeMemorySnapshot = snapshot;

  if (pendingSessionMemoryPersistData) {
    const data = pendingSessionMemoryPersistData;
    pendingSessionMemoryPersistData = null;
    persistSessionMemory(
      data
    );
  }

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

  if (data.replace_latest === true) {
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
      latestSnapshot
      && latestSnapshot.restored_from_session_save
      && Number(data.updates || 0) === 0
  ) {
    return true;
  }

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

  const savedRuntimeSnapshot = {
    ...pendingBootstrapRuntimeMemorySnapshot,
    index: 0,
  };

  pendingBootstrapRuntimeMemorySnapshot = null;
  runtimeMemoryDisplayMode = "runtime";
  restoredSessionMemorySnapshot = null;

  if (window.stopMemoryGlow) {
    window.stopMemoryGlow();
  }

  // During persisted-session restore, page 0 must stay the saved runtime from
  // browser memory. Server updates=0 messages are bootstrap chatter/echoes.
  runtimeMemoryHistory.snapshots = [
    savedRuntimeSnapshot,
  ];
  runtimeMemoryHistory.index = 0;

  if (runtimeMemoryCount) {
    runtimeMemoryCount.textContent =
      String(savedRuntimeSnapshot.runtime_memory_updates || 0);
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


window.freezeLatestRuntimeMemoryUserIdle = function (
  userIdleText
) {

  const latestSnapshot =
      runtimeMemoryHistory.snapshots[
        runtimeMemoryHistory.snapshots.length - 1
      ];

  setRuntimeMemorySnapshotUserIdle(
    latestSnapshot,
    userIdleText
  );

};


function runtimeMemoryTextIsDefaultNote(text) {

  const normalized =
      String(text || "")
        .trim()
        .replace(/\s+/g, " ")
        .toLowerCase();

  const defaultNormalized =
      defaultRuntimeMemoryText
        .trim()
        .replace(/\s+/g, " ")
        .toLowerCase();

  return (
      normalized === defaultNormalized
      || normalized === `note: ${defaultNormalized}`
  );

}


function attachFirstUserIdleToInitialRuntimeSnapshot(sourceSnapshot) {

  const firstSnapshot =
      runtimeMemoryHistory.snapshots[0];

  if (!firstSnapshot) {
    return;
  }

  if (getUserIdleRuntimeMemoryLine(firstSnapshot)) {
    return;
  }

  const firstRawMemory =
      String(firstSnapshot.raw_memory || "");

  if (!runtimeMemoryTextIsDefaultNote(firstRawMemory)) {
    return;
  }

  const userIdleLine =
      getUserIdleRuntimeMemoryLine(sourceSnapshot);

  if (!userIdleLine) {
    return;
  }

  const nextLine = {
    ...userIdleLine,
    status: "same",
    key_status: "same",
    value_status: "same",
  };

  firstSnapshot.lines = [
    ...(Array.isArray(firstSnapshot.lines)
      ? firstSnapshot.lines
      : splitMemoryTextLines(firstRawMemory)
        .map(parseRuntimeMemoryLine)),
    nextLine,
  ];

  firstSnapshot.raw_memory = [
    firstRawMemory.trim() || `note: ${defaultRuntimeMemoryText}`,
    `user_idle: ${nextLine.value || ""}`.trim(),
  ].filter(Boolean).join("\n");

}




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
    raw_memory: sessionStartedRuntimeMemoryText,
    lines: [
      {
        key: "session_status",
        value: "Session started",
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

  const shouldUseBrowserMemory =
    !savedRuntimeFallback;

  const browserLatestSavedSessionMemory =
    shouldUseBrowserMemory
      ? readLatestSavedSessionMemory()
      : null;

  const sessionMemory =
    (
      savedRuntimeFallback
      && savedRuntimeFallback.session_memory
    )
    || (
      browserLatestSavedSessionMemory
      && browserLatestSavedSessionMemory.explicit_save === true
        ? browserLatestSavedSessionMemory
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
          browserLatestSavedSessionMemory
          && browserLatestSavedSessionMemory.explicit_save === true
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

  const browserLatestSavedRuntimeMemory =
    shouldUseBrowserMemory
      ? readLatestSavedRuntimeMemory()
      : null;

  const latestSavedRuntimeMemory =
    (
      savedRuntimeFallback
      && savedRuntimeFallback.latest_saved_runtime_memory
    )
    || (
      browserLatestSavedRuntimeMemory
      && browserLatestSavedRuntimeMemory.explicit_save === true
        ? browserLatestSavedRuntimeMemory
        : null
    );

  const runtimeMemory =
    (
      latestSavedRuntimeMemory
      && latestSavedRuntimeMemory.explicit_save === true
    )
      ? latestSavedRuntimeMemory
      : null;

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

  removeBrowserMemory(
    runtimeStorageKeys.latestSavedSessionMemoryStorageKey
  );
  removeBrowserMemory(
    runtimeStorageKeys.latestSavedRuntimeMemoryStorageKey
  );
  removeBrowserMemory(
    storage.getCurrentLatestRuntimeMemoryStorageKey()
  );

};

window.getCurrentLatestRuntimeMemoryStorageKey = function () {

  return storage.getCurrentLatestRuntimeMemoryStorageKey();

};


window.getOtherLatestRuntimeMemorySnapshots = function () {

  return collectOtherLatestRuntimeMemorySnapshots();

};


window.clearOtherLatestRuntimeMemorySnapshots = function () {

  return clearOtherLatestRuntimeMemorySnapshots();

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

  let clientSnapshot = null;

  if (data.snapshot) {
    if (
        data.replace_latest === true
        && runtimeMemoryHistory.snapshots.length
    ) {
      const clientIndex =
          runtimeMemoryHistory.snapshots.length - 1;

      clientSnapshot = {
        ...runtimeMemoryHistory.snapshots[clientIndex],
        ...data.snapshot,
        index: clientIndex,
      };

      runtimeMemoryHistory.snapshots[clientIndex] =
          clientSnapshot;
      runtimeMemoryHistory.index = clientIndex;

      rememberStableRuntimeSnapshot(
        clientSnapshot
      );
    } else {
      const clientIndex = runtimeMemoryHistory.snapshots.length;
      clientSnapshot = {
        ...data.snapshot,
        index: clientIndex,
      };

      attachFirstUserIdleToInitialRuntimeSnapshot(
        clientSnapshot
      );

      // The server-side snapshot.index can restart after bootstrap/restore.
      // The right panel is client-side history, so display positions must follow
      // the actual array order instead of reusing a stale server index.
      runtimeMemoryHistory.snapshots.push(clientSnapshot);
      runtimeMemoryHistory.index =
          runtimeMemoryHistory.snapshots.length - 1;

      if (window.jinGenerationRunning) {
        idle.freezeAtSeconds(
            window.jinActiveTurnUserIdleSeconds
        );
      }

      rememberStableRuntimeSnapshot(
        clientSnapshot
      );

      feedback.markL1ReadyFromRuntimeUpdate(
        data,
        clientIndex
      );
    }
  } else {
    feedback.markL1ReadyFromRuntimeUpdate(
      data
    );
  }

  persistRuntimeMemorySnapshot(
    data
  );

  captureSessionSaveRuntimeSnapshot(
    clientSnapshot
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

function estimateRuntimeMemoryTokens(text) {
  if (!text) {
    return 0;
  }

  return Math.max(
      1,
      Math.ceil(
          Array.from(text).length / 4
      )
  );
}

function getRuntimeMemorySnapshotMetricText(snapshot) {
  if (!snapshot || typeof snapshot !== "object") {
    return "";
  }

  const includeLiveUserIdle =
      isLatestRuntimeMemorySnapshot();

  const rawMemory =
      String(snapshot.raw_memory || "");

  if (rawMemory.trim()) {
    const stableMemory =
        includeLiveUserIdle
          ? stripUserIdleRuntimeMemoryText(rawMemory)
          : rawMemory;

    return [
      stableMemory.trim(),
      includeLiveUserIdle
        ? `user_idle: ${getUserIdleText()}`
        : "",
    ].filter(Boolean).join("\n");
  }

  if (!Array.isArray(snapshot.lines)) {
    return "";
  }

  const lines =
      snapshot.lines
      .filter((line) => (
          !includeLiveUserIdle
          || !isUserIdleRuntimeMemoryLine(line)
      ))
      .map((line) => {
        const key =
            line && line.key
              ? String(line.key)
              : "note";

        const value =
            line && line.value
              ? String(line.value)
              : "";

        return `${key}: ${value}`;
      })
      .filter(Boolean);

  if (includeLiveUserIdle) {
    lines.push(
        `user_idle: ${getUserIdleText()}`
    );
  }

  return lines.join("\n").trim();
}

function updateRuntimeMemoryTitleMetrics(snapshot) {
  if (!runtimeMemoryTitle) {
    return;
  }

  const metricText =
      getRuntimeMemorySnapshotMetricText(snapshot);

  const charCount =
      Array.from(metricText).length;

  const tokenCount =
      estimateRuntimeMemoryTokens(metricText);

  runtimeMemoryTitle.title =
      `${charCount} chars / ~${tokenCount} tokens`;
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
    updateRuntimeMemoryTitleMetrics(null);
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

  updateRuntimeMemoryTitleMetrics(snapshot);
  updateRuntimeMemoryArrows();
  updateRuntimeMemoryPinGlow();
}

function isLatestRuntimeMemorySnapshot() {
  return (
      runtimeMemoryHistory.index >=
      runtimeMemoryHistory.snapshots.length - 1
  );
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

function renderRuntimeMemoryLines(snapshot, persistGlow = false) {
  if (!runtimeMemoryText) {
    return;
  }

  runtimeMemoryText.innerHTML = "";
  runtimeMemoryText.classList.toggle(
      "runtime-memory-text-pinned",
      persistGlow
  );
  runtimeMemoryText.removeAttribute(
      "title"
  );

  const showLiveUserIdle =
      isLatestRuntimeMemorySnapshot();

  const lines =
      showLiveUserIdle
        ? (snapshot.lines || [])
          .filter(line => !isUserIdleRuntimeMemoryLine(line))
        : snapshot.lines || [];

  if (!lines.length) {
    const rawMemory =
        showLiveUserIdle
          ? stripUserIdleRuntimeMemoryText(snapshot.raw_memory || "")
          : snapshot.raw_memory || "";

    runtimeMemoryText.textContent =
        `${stripMemoryTextMetaForDisplay(rawMemory).trim()}\n`;

    if (rawMemory.trim()) {
      runtimeMemoryText.title =
          rawMemory.trim();
    }

    if (showLiveUserIdle) {
      appendUserIdleRuntimeMemoryLine();
    } else {
      userIdleValueNode = null;
    }

    idle.start();

    return;
  }

  lines.forEach((line) => {
    const row =
        document.createElement("div");

    row.className =
        "runtime-memory-line";

    const key =
        line.key || "note";

    const valuePresentation =
        buildRuntimeMemoryValuePresentation(line);

    const fullRawLine =
        `${key}: ${valuePresentation.raw}`;

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
        ` ${valuePresentation.text}`;

    row.title =
        fullRawLine;
    valueSpan.title =
        fullRawLine;

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

  if (showLiveUserIdle) {
    appendUserIdleRuntimeMemoryLine();
  } else {
    userIdleValueNode = null;
  }

  idle.start();
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
  idle.onSnapshotChanged();
  idle.start();
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
