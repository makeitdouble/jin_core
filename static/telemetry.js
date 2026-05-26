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


const initialRuntimeConfig =
  readInitialRuntimeConfig();

window.jinRuntimeConfig =
  initialRuntimeConfig;

const runtimePanelState = {
  activeTab: "service",
  useServiceAsBrain: Boolean(
    initialRuntimeConfig.useServiceAsBrain
  ),
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


function formatContextTokens(runtime) {

  if (!runtime) {
    return "0 / 0 ctx";
  }

  return `${runtime.used_tokens || 0} / `
    + `${runtime.max_tokens || 0} ctx`;

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
    Math.floor(width / 7) - 2
  );

}


function buildContextLine(
  runtime,
  cells
) {

  const used =
    runtime
      ? Number(runtime.used_tokens || 0)
      : 0;

  const max =
    runtime
      ? Number(runtime.max_tokens || 0)
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
    role === "brain"
    && runtimePanelState.useServiceAsBrain;

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
    button.className =
      "h-8 text-[11px] font-bold uppercase tracking-widest text-slate-500 cursor-not-allowed";

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
  }

  if (percentElement) {
    percentElement.textContent =
      contextLine.percentLabel;
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


function renderContextPanel() {

  if (
    runtimePanelState.useServiceAsBrain
    && runtimePanelState.activeTab === "brain"
  ) {
    runtimePanelState.activeTab =
      "service";
  }

  setTabClasses("service");
  setTabClasses("brain");

  setContextPanelRuntime(
    getSelectedRuntime()
  );

}


function selectContextTab(role) {

  if (
    role === "brain"
    && runtimePanelState.useServiceAsBrain
  ) {
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
    runtimeConfig:
      data.runtime_config || {},
  };

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


if (window.jinLatestStatus) {

  window.updateRuntimePanelFromStatus(
    window.jinLatestStatus
  );

} else if (window.jinRuntimeConfig) {

  window.setUseServiceAsBrain(
    window.jinRuntimeConfig.useServiceAsBrain
  );

  window.setRuntimeConfigSnapshot(
    window.jinRuntimeConfig.runtimeConfig || {}
  );

} else {

  renderContextPanel();

}
