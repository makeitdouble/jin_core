(function () {
  "use strict";

  window.JinRuntime = window.JinRuntime || {};

  const TELEMETRY_FRAME_WARNING_MS = 12;
  const CONTEXT_PANEL_RENDER_THROTTLE_MS = 300;

  const SCENE_CONTEXT_PRESSURE_MIDDLE_THRESHOLD = 50;
  const SCENE_CONTEXT_PRESSURE_CLUTTERED_THRESHOLD = 100;
  const SCENE_CONTEXT_PRESSURE_CLEAR_THRESHOLD = 100;
  const SCENE_CONTEXT_PRESSURE_MIDDLE_TURNS = 3;
  const SCENE_CONTEXT_PRESSURE_CLUTTERED_TURNS = 3;
  const SCENE_CONTEXT_PRESSURE_CLEAR_TURNS = 2;
  const SCENE_CONTEXT_PRESSURE_COMMIT_DELAY_MS = 420;

  const sceneContextPressureState = {
    promt_context_presure: 0,
    L1_memory_context_presure: 0,
    middleTurns: 0,
    highTurns: 0,
    lowTurns: 0,
    desiredStage: null,
    visibleStage: null,
    pendingKey: "",
    pendingTurnKey: "",
    pendingSample: null,
    committedKey: "",
    committedTurnKey: "",
    commitTimer: null,
    imageState: {
      middle: "unknown",
      cluttered: "unknown",
    },
  };

  const SCENE_CONTEXT_PRESSURE_IMAGES = {
    middle: "static/images/states/middle.png",
    cluttered: "static/images/states/cluttered.png",
  };

  let initialized = false;
  let telemetryFrameScheduled = false;
  let contextPanelRenderTimer = null;

  let contextRuntimePanel = null;
  let contextPanelResizeObserver = null;

  const runtimePanelState = {
    fallbackRuntimes: {},
    liveRuntimes: [],
  };

  function readInitialRuntimeConfig() {

    return window.jinRuntimeConfig || {};

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


  function getRuntimeUsageAmount(runtime) {

    if (!runtime) {
      return 0;
    }

    return Math.max(
      Number(runtime.used_tokens || 0),
      Number(runtime.context_tokens || 0),
      Number(runtime.total_tokens || 0)
    );

  }


  function getServiceRuntime() {
    return getRuntimeByLabel("service");

  }


  function getBrainRuntime() {
    return getRuntimeByLabel("brain");
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

  function getSceneRoot() {

    return document.querySelector(
      "main"
    );

  }


  function clearSceneContextPressureTimer() {

    if (!sceneContextPressureState.commitTimer) {
      return;
    }

    clearTimeout(
      sceneContextPressureState.commitTimer
    );

    sceneContextPressureState.commitTimer = null;

  }


  function clampContextPressure(value) {

    const number = Number(value);

    if (!Number.isFinite(number)) {
      return 0;
    }

    return Math.max(
      0,
      Math.round(number)
    );

  }


  function getSceneContextPressureTurnKey() {

    const counter = Number(
      window.jinConversationTurnCounter || 0
    );

    if (Number.isFinite(counter) && counter > 0) {
      return `turn:${counter}`;
    }

    return "turn:0";

  }


  function getContextLinePressure(contextLine) {

    if (!contextLine) {
      return 0;
    }

    return clampContextPressure(
      Math.max(
        Number(contextLine.percent || 0),
        Number(contextLine.totalPercent || 0)
      )
    );

  }


  function clearSceneContextPressureStage() {

    const sceneRoot =
      getSceneRoot();

    if (!sceneRoot) {
      return;
    }

    sceneContextPressureState.desiredStage = null;
    sceneContextPressureState.visibleStage = null;

    sceneRoot.classList.remove(
      "scene-clutter-middle",
      "scene-cluttered"
    );

  }


  function applyLoadedSceneContextPressureStage(stage) {

    const sceneRoot =
      getSceneRoot();

    const imageUrl =
      SCENE_CONTEXT_PRESSURE_IMAGES[stage];

    if (
      !sceneRoot
      || !imageUrl
    ) {
      return;
    }

    sceneRoot.classList.toggle(
      "scene-clutter-middle",
      stage === "middle"
    );

    sceneRoot.classList.toggle(
      "scene-cluttered",
      stage === "cluttered"
    );

    sceneContextPressureState.visibleStage =
      stage;

  }


  function ensureSceneContextPressureImage(
    stage,
    callback
  ) {

    const imageUrl =
      SCENE_CONTEXT_PRESSURE_IMAGES[stage];

    if (!imageUrl) {
      callback(false);
      return;
    }

    const currentState =
      sceneContextPressureState.imageState[stage];

    if (currentState === "loaded") {
      callback(true);
      return;
    }

    if (currentState === "missing") {
      callback(false);
      return;
    }

    sceneContextPressureState.imageState[stage] =
      "loading";

    const image =
      new Image();

    image.onload = function () {
      sceneContextPressureState.imageState[stage] =
        "loaded";

      callback(true);
    };

    image.onerror = function () {
      sceneContextPressureState.imageState[stage] =
        "missing";

      callback(false);
    };

    image.src = imageUrl;

  }


  function setSceneContextPressureStage(stage) {

    if (!stage) {
      clearSceneContextPressureStage();
      return;
    }

    sceneContextPressureState.desiredStage =
      stage;

    ensureSceneContextPressureImage(
      stage,
      function (loaded) {
        if (
          sceneContextPressureState.desiredStage
          !== stage
        ) {
          return;
        }

        if (loaded) {
          applyLoadedSceneContextPressureStage(
            stage
          );
          return;
        }

        if (stage === "cluttered") {
          setSceneContextPressureStage(
            "middle"
          );
          return;
        }

        clearSceneContextPressureStage();
      }
    );

  }


  function publishSceneContextPressureState() {

    window.jinSceneContextPressure = {
      promt_context_presure:
        sceneContextPressureState.promt_context_presure,
      L1_memory_context_presure:
        sceneContextPressureState.L1_memory_context_presure,
      middleTurns:
        sceneContextPressureState.middleTurns,
      highTurns:
        sceneContextPressureState.highTurns,
      lowTurns:
        sceneContextPressureState.lowTurns,
      stage:
        sceneContextPressureState.visibleStage,
    };

  }


  function commitSceneContextPressureSample(sample) {

    if (!sample) {
      return;
    }

    const key =
      `${sample.promptPressure}:${sample.l1Pressure}`;

    const turnKey =
      sample.turnKey || "turn:0";

    if (
      turnKey
      && turnKey === sceneContextPressureState.committedTurnKey
      && key === sceneContextPressureState.committedKey
    ) {
      return;
    }

    sceneContextPressureState.committedKey =
      key;

    sceneContextPressureState.committedTurnKey =
      turnKey;

    sceneContextPressureState.promt_context_presure =
      sample.promptPressure;

    sceneContextPressureState.L1_memory_context_presure =
      sample.l1Pressure;

    const bothMiddleHigh =
      sample.promptPressure > SCENE_CONTEXT_PRESSURE_MIDDLE_THRESHOLD
      && sample.l1Pressure > SCENE_CONTEXT_PRESSURE_MIDDLE_THRESHOLD;

    const bothClutteredHigh =
      sample.promptPressure > SCENE_CONTEXT_PRESSURE_CLUTTERED_THRESHOLD
      && sample.l1Pressure > SCENE_CONTEXT_PRESSURE_CLUTTERED_THRESHOLD;

    const bothClearLow =
      sample.promptPressure < SCENE_CONTEXT_PRESSURE_CLEAR_THRESHOLD
      && sample.l1Pressure < SCENE_CONTEXT_PRESSURE_CLEAR_THRESHOLD;

    if (bothMiddleHigh) {
      sceneContextPressureState.middleTurns += 1;
    } else {
      sceneContextPressureState.middleTurns = 0;
    }

    if (bothClutteredHigh) {
      sceneContextPressureState.highTurns += 1;
      sceneContextPressureState.lowTurns = 0;
    } else {
      sceneContextPressureState.highTurns = 0;

      if (bothClearLow) {
        sceneContextPressureState.lowTurns += 1;
      } else {
        sceneContextPressureState.lowTurns = 0;
      }
    }

    if (
      sceneContextPressureState.lowTurns
      >= SCENE_CONTEXT_PRESSURE_CLEAR_TURNS
    ) {
      setSceneContextPressureStage(null);
    } else if (
      sceneContextPressureState.highTurns
      >= SCENE_CONTEXT_PRESSURE_CLUTTERED_TURNS
    ) {
      setSceneContextPressureStage(
        "cluttered"
      );
    } else if (
      sceneContextPressureState.middleTurns
      >= SCENE_CONTEXT_PRESSURE_MIDDLE_TURNS
    ) {
      setSceneContextPressureStage(
        "middle"
      );
    }

    publishSceneContextPressureState();

  }


  function scheduleSceneContextPressureSample(
    promptPressure,
    l1Pressure
  ) {

    const sample = {
      promptPressure:
        clampContextPressure(promptPressure),
      l1Pressure:
        clampContextPressure(l1Pressure),
      turnKey:
        getSceneContextPressureTurnKey(),
    };

    if (
      sample.promptPressure <= 0
      && sample.l1Pressure <= 0
    ) {
      return;
    }

    const key =
      `${sample.promptPressure}:${sample.l1Pressure}`;

    const turnKey =
      sample.turnKey || "turn:0";

    if (
      key === sceneContextPressureState.pendingKey
      && turnKey === sceneContextPressureState.pendingTurnKey
    ) {
      return;
    }

    if (
      key === sceneContextPressureState.committedKey
      && turnKey === sceneContextPressureState.committedTurnKey
    ) {
      return;
    }

    sceneContextPressureState.pendingKey =
      key;

    sceneContextPressureState.pendingTurnKey =
      turnKey;

    sceneContextPressureState.pendingSample =
      sample;

    clearSceneContextPressureTimer();

    sceneContextPressureState.commitTimer =
      setTimeout(
        function () {
          sceneContextPressureState.commitTimer = null;

          commitSceneContextPressureSample(
            sceneContextPressureState.pendingSample
          );
        },
        SCENE_CONTEXT_PRESSURE_COMMIT_DELAY_MS
      );

  }


  function updateSceneContextPressureFromLines(
    promptContextLine,
    l1ContextLine
  ) {

    scheduleSceneContextPressureSample(
      getContextLinePressure(
        promptContextLine
      ),
      getContextLinePressure(
        l1ContextLine
      )
    );

  }


  function buildContextLine(
    runtime,
    cells
  ) {

    const runtimeInfo =
      runtime;

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
        ? getRuntimeUsageAmount(
            runtimeInfo
          )
        : 0;

    // Drive the visible counter/percentage from the live total. During
    // reasoning the prompt baseline stays fixed, but total usage keeps
    // increasing chunk by chunk.
    const used = totalUsed;

    const max =
      runtimeInfo
        ? Number(runtimeInfo.max_tokens || 0)
        : 0;

    const rawPercent =
      max > 0
        ? (used / max) * 100
        : 0;

    const visiblePercent =
      Math.min(
        100,
        rawPercent
      );

    const percent =
      Math.round(rawPercent);

    const percentLabel =
      used > 0
      && rawPercent < 1
        ? "<1%"
        : `${percent}%`;

    const filled =
      Math.round(
        (visiblePercent / 100) * cells
      );

    const contextPercent =
      max > 0
        ? (contextUsed / max) * 100
        : 0;

    const totalPercent =
      max > 0
        ? (totalUsed / max) * 100
        : 0;

    const visibleContextPercent =
      Math.min(
        100,
        contextPercent
      );

    const visibleTotalPercent =
      Math.min(
        100,
        totalPercent
      );

    const contextFilled =
      Math.min(
        cells,
        Math.round(
          (visibleContextPercent / 100) * cells
        )
      );

    const totalFilled =
      Math.min(
        cells,
        Math.round(
          (visibleTotalPercent / 100) * cells
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

    const displayPercent =
      Math.max(
        Number(contextLine.percent || 0),
        Number(contextLine.totalPercent || 0)
      );

    const contextScale =
      Math.max(
        0,
        Number(contextLine.contextPercent || 0) / 100
      );

    const totalScale =
      Math.max(
        contextScale,
        Math.max(
          0,
          Number(contextLine.totalPercent || 0) / 100
        )
      );

    const displayScale =
      Math.max(
        totalScale,
        Math.max(
          0,
          displayPercent / 100
        )
      );

    barElement.classList.add(
      "context-window-bar-visual"
    );

    barElement.style.setProperty(
      "--win95-context-scale",
      String(contextScale)
    );

    barElement.style.setProperty(
      "--win95-context-fill",
      `${Math.min(100, contextScale * 100)}%`
    );

    barElement.style.setProperty(
      "--win95-context-total-scale",
      String(totalScale)
    );

    barElement.style.setProperty(
      "--win95-context-total-fill",
      `${Math.min(100, displayScale * 100)}%`
    );

    barElement.innerHTML =
      "["
      + `<span style="color: ${pressureColor}; opacity: 1">${solid}</span>`
      + `<span style="color: ${pressureColor}; opacity: 0.55">${secondary}</span>`
      + `<span style="color: ${pressureColor}; opacity: 0.28">${empty}</span>`
      + "]";

  }


  function setContextPanelRuntimes(
    brainRuntime,
    serviceRuntime
  ) {

    if (contextRuntimePanel) {
      contextRuntimePanel.classList.toggle(
        "hidden",
        !brainRuntime && !serviceRuntime
      );
    }

    const brainLineElement =
      document.getElementById(
        "brain-context-window-line"
      );
    const brainBarElement =
      document.getElementById(
        "brain-context-window-bar"
      );
    const brainPercentElement =
      document.getElementById(
        "brain-context-window-percent"
      );
    const serviceLineElement =
      document.getElementById(
        "service-context-window-line"
      );
    const serviceBarElement =
      document.getElementById(
        "service-context-window-bar"
      );
    const servicePercentElement =
      document.getElementById(
        "service-context-window-percent"
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

    const brainLine = buildContextLine(
      brainRuntime,
      getContextBarCells(brainBarElement)
    );
    const serviceLine = buildContextLine(
      serviceRuntime,
      getContextBarCells(serviceBarElement)
    );

    if (summaryElement) {
      summaryElement.setAttribute(
        "aria-label",
        `${brainLine.totalUsed} / ${brainLine.max}`
      );
    }

    if (summaryUsedElement) {
      summaryUsedElement.textContent =
        `${brainLine.totalUsed}\u00a0/`;
    }

    if (summaryMaxElement) {
      summaryMaxElement.textContent =
        `${brainLine.max}`;
    }

    function renderRuntimeLine(
      role,
      runtime,
      line,
      lineElement,
      barElement,
      percentElement
    ) {
      const pressureColor = getContextPressureColor(
        Math.max(
          line.percent,
          line.totalPercent
        )
      );

      if (lineElement) {
        lineElement.title =
          role.toUpperCase()
          + " · "
          + (runtime ? runtime.model : "unknown")
          + " · context: "
          + line.contextUsed
          + " / "
          + line.max
          + " ("
          + line.contextPercent
          + "%), total: "
          + line.totalUsed
          + " / "
          + line.max
          + " ("
          + line.totalPercent
          + "%)";
        lineElement.setAttribute(
          "aria-label",
          lineElement.title
        );
      }

      renderContextBar(
        barElement,
        line,
        pressureColor
      );

      if (percentElement) {
        percentElement.textContent =
          line.percentLabel;
        percentElement.style.color =
          pressureColor;
      }
    }

    renderRuntimeLine(
      "brain",
      brainRuntime,
      brainLine,
      brainLineElement,
      brainBarElement,
      brainPercentElement
    );
    renderRuntimeLine(
      "service",
      serviceRuntime,
      serviceLine,
      serviceLineElement,
      serviceBarElement,
      servicePercentElement
    );

    updateSceneContextPressureFromLines(
      brainLine,
      serviceLine
    );

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
      getServiceRuntime();

    const brainRuntime =
      getBrainRuntime();

    updateChatHeader(
      serviceRuntime,
      brainRuntime
    );

    setContextPanelRuntimes(
      brainRuntime,
      serviceRuntime
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
    setContextPanelRuntimes(
      getBrainRuntime(),
      getServiceRuntime()
    );
  }


  function setRuntimeConfigSnapshot(runtimeConfig) {

    runtimePanelState.fallbackRuntimes =
      runtimeConfig || {};

    const serviceRuntime =
      getServiceRuntime();

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
      serviceConfigured:
        Boolean(data.service_configured),
      formatResponse:
        data.format_response !== false,
      runtimeStatus: {
        brain: Boolean(data.brain),
        service: Boolean(data.service),
      },
      runtimeConfig:
        data.runtime_config || {},
    };

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

    runtimePanelState.fallbackRuntimes = (
      initialRuntimeConfig.runtimeConfig
    ) || {};

    contextRuntimePanel =
      document.getElementById(
        "context-runtime-panel"
      );

    if (
      contextRuntimePanel
      && typeof window.ResizeObserver === "function"
    ) {
      contextPanelResizeObserver =
        new window.ResizeObserver(
          function () {
            scheduleRuntimeTelemetryFrame();
          }
        );

      contextPanelResizeObserver.observe(
        contextRuntimePanel
      );
    }

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
    getServiceRuntime,
    getBrainRuntime,
    handleTelemetryMessage,
    updateRuntimePanelFromStatus,
    flushRuntimeTelemetryRender,
    renderContextPanel,
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

  window.setRuntimeConfigSnapshot = function (runtimeConfig) {
    return api.setRuntimeConfigSnapshot(runtimeConfig);
  };

}());
