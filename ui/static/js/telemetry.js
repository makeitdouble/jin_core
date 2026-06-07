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

let runtimeMemoryDisplayMode = "runtime";
let restoredSessionMemorySnapshot = null;
let pendingBootstrapRuntimeMemorySnapshot = null;

const runtimeDiffHistory = {
  diffs: [],
  stats: {},
  expanded: false,
};

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

  writeBrowserMemory(
    runtimeMemoryStorageKey,
    {
      version: 1,
      saved_at: savedAt,
      runtime_memory: runtimeMemory,
      runtime_memory_updates: data.updates || 0,
      runtime_snapshot: data.snapshot,
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
    runtime_snapshot: {
      ...snapshot,
      raw_memory: runtimeMemory.trim(),
    },
  };

}


function runtimeSnapshotLooksLikeSessionSaveResult(
  snapshot
) {

  const runtimeMemory =
    String(
      (
        snapshot
        && snapshot.raw_memory
      )
      || ""
    ).toLowerCase();

  if (!runtimeMemory) {
    return false;
  }

  return (
    runtimeMemory.includes("save session")
    || runtimeMemory.includes("saving of the session")
    || runtimeMemory.includes("session initialized and confirmed saved")
    || runtimeMemory.includes("confirmed saved")
    || runtimeMemory.includes("remember_session")
    || runtimeMemory.includes("сохрани сессию")
    || runtimeMemory.includes("сохранить сессию")
  );

}


function getRuntimeMemoryForSessionSave() {

  const snapshots =
    runtimeMemoryHistory.snapshots;

  const latestIndex =
    snapshots.length - 1;

  const latestSnapshot =
    latestIndex >= 0
      ? snapshots[latestIndex]
      : null;

  const previousSnapshot =
    latestIndex > 0
      ? snapshots[latestIndex - 1]
      : null;

  const selectedSnapshot =
    (
      previousSnapshot
      && runtimeSnapshotLooksLikeSessionSaveResult(
        latestSnapshot
      )
    )
      ? previousSnapshot
      : latestSnapshot;

  const runtimeMemory =
    runtimeMemoryObjectFromSnapshot(
      selectedSnapshot
    );

  if (runtimeMemory) {
    return runtimeMemory;
  }

  return readBrowserMemory(
    runtimeMemoryStorageKey
  );

}


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
        (
          sessionRuntimeMemory
          && sessionRuntimeMemory.runtime_snapshot
        ) || null,
    }
  );

}


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
    index: 1,
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
    index: 1,
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
    runtimeMemoryHistory.snapshots.push(data.snapshot);
    runtimeMemoryHistory.index =
        runtimeMemoryHistory.snapshots.length - 1;
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
    return;
  }

  renderRuntimeMemoryLines(
      snapshot
  );

  runtimeMemoryPosition.textContent =
      String(
          typeof snapshot.index === "number"
            ? snapshot.index
            : runtimeMemoryHistory.index + 1
      );

  updateRuntimeMemoryArrows();
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
    ratio
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

function renderRuntimeMemoryLines(snapshot) {
  if (!runtimeMemoryText) {
    return;
  }

  runtimeMemoryText.innerHTML = "";

  const lines =
      snapshot.lines || [];

  if (!lines.length) {
    runtimeMemoryText.textContent =
        (snapshot.raw_memory || "").trim();

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
        ` ${value}`;

    row.appendChild(keySpan);
    row.appendChild(valueSpan);

    runtimeMemoryText.appendChild(row);

    applyRuntimeMemoryFlash(
        keySpan,
        keyStatus,
        "key",
        line.key_change_ratio
    );

    applyRuntimeMemoryFlash(
        valueSpan,
        valueStatus,
        "value",
        line.value_change_ratio
    );
  });
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

runtimeDiffToggle?.addEventListener("click", () => {
  runtimeDiffHistory.expanded =
      !runtimeDiffHistory.expanded;

  renderRuntimeDiffs();
});

renderRuntimeMemorySnapshot();
renderRuntimeDiffs();
