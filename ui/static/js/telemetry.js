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

const session =
  window.JinRuntime
  && window.JinRuntime.session;

if (!session) {
  throw new Error(
    "JinRuntime.session must be loaded before telemetry.js"
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






session.init({
  history: runtimeMemoryHistory,
  storage,
  memoryModel,
  feedback,
  runtimeMemoryCount,
  defaultRuntimeMemoryText,
  sessionStartedRuntimeMemoryText,
  getRuntimeMemoryDisplayMode: () => runtimeMemoryDisplayMode,
  setRuntimeMemoryDisplayMode: (value) => {
    runtimeMemoryDisplayMode = value;
  },
  getRestoredSessionMemorySnapshot: () => restoredSessionMemorySnapshot,
  setRestoredSessionMemorySnapshot: (value) => {
    restoredSessionMemorySnapshot = value;
  },
  renderRuntimeMemorySnapshot,
  persistRuntimeMemorySnapshot,
  attachFirstUserIdleToInitialRuntimeSnapshot,
});

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
    session.persistSessionMemory(
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

  if (session.isReconnectInitialRuntimeMemoryUpdate(data)) {
    return;
  }

  if (session.isLatestRuntimeMemoryDuplicate(data)) {
    return;
  }

  if (session.applyBootstrapRuntimeMemoryUpdate(data)) {
    return;
  }

  if (session.isBootstrapRuntimeMemoryDuplicate(data)) {
    return;
  }

  if (
      session.shouldIgnoreInitialSessionModeUpdate(data)
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

      session.rememberStableRuntimeSnapshot(
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

      session.rememberStableRuntimeSnapshot(
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

  session.captureSessionSaveRuntimeSnapshot(
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
