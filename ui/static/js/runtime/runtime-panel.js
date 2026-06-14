(function () {
  "use strict";

  window.JinRuntime = window.JinRuntime || {};

  const TELEMETRY_FRAME_WARNING_MS = 12;
  const CONTEXT_PANEL_RENDER_THROTTLE_MS = 300;

  let initialized = false;
  let telemetryFrameScheduled = false;
  let contextPanelRenderTimer = null;

  let contextTabButtons = {};
  let contextRuntimePanel = null;

  const runtimePanelState = {
    activeTab: "service",
    useServiceAsBrain: false,
    runtimeStatus: {},
    fallbackRuntimes: {},
    liveRuntimes: [],
  };

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

    void summarizerTokenText;

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


  function setUseServiceAsBrain(enabled) {

    runtimePanelState.useServiceAsBrain =
      Boolean(enabled);

    renderContextPanel();

  }


  function setRuntimeStatusSnapshot(runtimeStatus) {

    runtimePanelState.runtimeStatus =
      runtimeStatus || {};

    renderContextPanel();

  }


  function setRuntimeConfigSnapshot(runtimeConfig) {

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

  }


  function updateRuntimePanelFromStatus(data) {

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

    setRuntimeStatusSnapshot(
      window
        .jinRuntimeConfig
        .runtimeStatus
    );

    setUseServiceAsBrain(
      window
        .jinRuntimeConfig
        .useServiceAsBrain
    );

    setRuntimeConfigSnapshot(
      window
        .jinRuntimeConfig
        .runtimeConfig
    );

  }


  function handleTelemetryMessage(data) {

    if (!data || data.type !== "telemetry") {
      return;
    }

    runtimePanelState.liveRuntimes =
      Object.values(
        data.runtime || {}
      );

    scheduleRuntimeTelemetryRender();

  }


  function init() {

    if (initialized) {
      return api;
    }

    initialized = true;

    const initialRuntimeConfig =
      readInitialRuntimeConfig();

    window.jinRuntimeConfig =
      initialRuntimeConfig;

    runtimePanelState.useServiceAsBrain = Boolean(
      initialRuntimeConfig.useServiceAsBrain
    );

    runtimePanelState.runtimeStatus = (
      initialRuntimeConfig.runtimeStatus
    ) || {};

    runtimePanelState.fallbackRuntimes = (
      initialRuntimeConfig.runtimeConfig
    ) || {};

    contextTabButtons = {
      service: document.getElementById(
        "service-context-tab"
      ),
      brain: document.getElementById(
        "brain-context-tab"
      ),
    };

    contextRuntimePanel =
      document.getElementById(
        "context-runtime-panel"
      );

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

    if (window.jinLatestStatus) {

      updateRuntimePanelFromStatus(
        window.jinLatestStatus
      );

    } else if (window.jinRuntimeConfig) {

      setRuntimeStatusSnapshot(
        window.jinRuntimeConfig.runtimeStatus || {}
      );

      setUseServiceAsBrain(
        window.jinRuntimeConfig.useServiceAsBrain
      );

      setRuntimeConfigSnapshot(
        window.jinRuntimeConfig.runtimeConfig || {}
      );

    } else {

      renderContextPanel();

    }

    return api;

  }

  const api = {
    init,
    findRuntimeByLabel,
    getRuntimeByLabel,
    getBrainRuntime,
    getSummarizerRuntime,
    getSelectedRuntime,
    handleTelemetryMessage,
    updateRuntimePanelFromStatus,
    flushRuntimeTelemetryRender,
    renderContextPanel,
    setUseServiceAsBrain,
    setRuntimeStatusSnapshot,
    setRuntimeConfigSnapshot,
  };

  window.JinRuntime.panel = api;

  window.handleTelemetryMessage = function (payload) {
    return api.handleTelemetryMessage(payload);
  };

  window.updateRuntimePanelFromStatus = function (status) {
    return api.updateRuntimePanelFromStatus(status);
  };

  window.flushRuntimeTelemetryRender = function (options) {
    return api.flushRuntimeTelemetryRender(options);
  };

  window.setUseServiceAsBrain = function (enabled) {
    return api.setUseServiceAsBrain(enabled);
  };

  window.setRuntimeStatusSnapshot = function (runtimeStatus) {
    return api.setRuntimeStatusSnapshot(runtimeStatus);
  };

  window.setRuntimeConfigSnapshot = function (runtimeConfig) {
    return api.setRuntimeConfigSnapshot(runtimeConfig);
  };

}());
