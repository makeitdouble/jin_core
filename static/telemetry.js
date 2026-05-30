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

const runtimeMemoryCount =
  document.getElementById(
    "runtime-memory-count"
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
    return "0 / 0";
  }

  return `${runtimeInfo.used_tokens || 0} / `
    + `${runtimeInfo.max_tokens || 0}`;

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

  const bar =
    "|".repeat(filled)
    + ".".repeat(cells - filled);

  return {
    percent,
    bar: `[${bar}]`,
    percentLabel,
  };

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
          contextLine.percent
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
    summaryElement.textContent =
      tokenText;
  }

  if (lineElement) {
    lineElement.title =
      `${tokenText} (${contextLine.percent}%)`;
  }

  if (barElement) {
    barElement.textContent =
      contextLine.bar;
    barElement.style.color =
        pressureColor;
  }

  if (percentElement) {
    percentElement.textContent =
      contextLine.percentLabel;
    percentElement.style.color =
        pressureColor;
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

  if (runtimeMemoryText) {
    runtimeMemoryText.textContent =
      (
        memory
        && memory.trim()
      )
        ? memory.trim()
        : "No runtime memory yet.";
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


window.handleRuntimeMemoryMessage = function (data) {

  if (
    !data
    || data.type !== "runtime_memory_update"
  ) {
    return;
  }

  renderRuntimeMemory(
    data.memory || "",
    data.updates || 0
  );

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
