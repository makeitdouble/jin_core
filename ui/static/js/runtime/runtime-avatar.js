(function () {
  "use strict";

  window.JinRuntime = window.JinRuntime || {};

  const SVG_NS = "http://www.w3.org/2000/svg";
  const AVATAR_EVENT = "jin:runtime-avatar-snapshot";
  const THINK_RUNTIME_CITATION_HIGHLIGHT_EVENT = "jin:think-runtime-citation-highlight";
  const MEMORY_ROW_AVATAR_HOVER_EVENT = "jin:memory-row-avatar-hover";
  const DELAYED_MEMORY_REPORT_ACTIVE_EVENT =
    "jin:delayed-memory-report-active";
  const MEMORY_REFERENCE_HIGHLIGHT_EVENT =
    "jin:memory-reference-highlight";

  const CENTER = 180;
  const INNER_RING_SCALE = 0.90;
  const MIN_RING_RADIUS = 48 * INNER_RING_SCALE;
  const MAX_RING_RADIUS = 160 * INNER_RING_SCALE;
  const INNER_DECORATION_MAX_RADIUS = 151;
  const STATIC_SCAFFOLD_RADII =
    [42, 61, 83, 108, 135, 162]
      .map(radius => radius * INNER_RING_SCALE);
  const STATIC_RADIAL_LINE_INNER_RADIUS = 38 * INNER_RING_SCALE;
  const STATIC_RADIAL_LINE_OUTER_RADIUS = 166 * INNER_RING_SCALE;
  const MEMORY_RING_LAYOUT = Object.freeze({
    l4: Object.freeze({
      radius: 168,
      strokeWidth: 1.05,
      minArcDegrees: 3.2,
      maxArcDegrees: 8.8,
      arcRatio: 0.42,
      arcTrimPixels: 4,
      startAngle: -6,
    }),
    delayed: Object.freeze({
      radius: 158,
      strokeWidth: 3.10,
      minArcDegrees: 3.4,
      maxArcDegrees: 9.4,
      arcRatio: 0.45,
      startAngle: -3,
    }),
    active: Object.freeze({
      radius: 178,
      strokeWidth: 1.35,
      minArcDegrees: 3.8,
      maxArcDegrees: 10.8,
      arcRatio: 0.48,
      startAngle: -9,
    }),
  });
  const FILE_RING_LAYOUT = Object.freeze({
    radius: 188,
    dotRadius: 2.7,
    baseColor: "#7ab8d8",
    glowColor: "#7ab8d8",
    startAngle: -12,
  });
  const MEMORY_SIGNAL_KIND_ORDER =
    Object.freeze(["delayed", "l4", "active"]);
  const SNAPSHOT_GLOW_CLEAR_DELAY_MS = 360;
  const INITIAL_BOOTSTRAP_COLOR_TRANSITION_MS = 2000;
  const DEFAULT_CENTER_COLOR_TRANSITION_MS = 333;
  const CENTER_COLOR_TRANSITION_RESET_BUFFER_MS = 80;
  const MEMORY_LAYERS_HIDDEN_CLASS = "is-memory-layers-hidden";
  const MEMORY_LAYERS_DORMANT_CLASS = "is-memory-layers-dormant";
  const MEMORY_LAYERS_FADE_MS = 420;
  const REASONING_MOTION_CLASS = "is-reasoning";
  const REASONING_WHISPER_CLASS = "is-reasoning-whispering";
  const REASONING_WHISPER_ANIMATION = "jin-avatar-reasoning-whisper";
  const REASONING_ROTATION_STOP_MS = 1080;
  const REASONING_ROTATION_RESUME_MS = 1480;
  const REASONING_LAYER_SETTLE_MS = 1180;

  // 0 = no scene recolor, 1 = current full-strength scene recolor.
  const JIN_SCENE_COLOR_INTENSITY = 0.40;

  // Add custom high-priority word groups here. A matching line paints its ring
  // with the supplied color and softly affects rings at neighbouring radii.
  const AGGRESSIVE_PALETTE = [
    [["angry", "aggressive"], "#ff0000"],
  ];

  const KEYWORD_PALETTE = [
    [["jin", "runtime"], "#22d9b5"],
    [["user"], "#9276d8"],
    [["memory"], "#e1a449"],
  ];

  const DEFAULT_RING_COLOR = "#28cfc7";
  const DEFAULT_CENTER_COLOR = "#1f4f8f";
  const ACCENT_RING_COLOR = "#5be8df";
  const AMBER_ACCENT = "#e3a64e";
  const ACTIVE_MEMORY_RING_COLOR = "#d7fff9";
  const DELAYED_MEMORY_RING_COLOR = "#7ab8d8";
  const L4_MEMORY_RING_COLOR = "#93c5fd";
  const FILE_RING_COLOR = DELAYED_MEMORY_RING_COLOR;
  const FILE_RING_ACTIVE_COLOR = "#efffff";

  const avatarRoot = document.getElementById("jin-runtime-avatar");
  const avatarShell = avatarRoot?.closest(".jin-runtime-avatar-shell") || null;
  const memoryLayersToggle = document.getElementById("memory-layers-toggle");
  const memoryPanel = document.getElementById("memory-panel");
  const normalizeRuntimeCitationIdentity =
    window.JinRuntime.normalizeCitationIdentity;
  const buildCitationRecordIdentity =
    typeof window.JinRuntime.buildCitationRecordIdentity === "function"
      ? window.JinRuntime.buildCitationRecordIdentity
      : () => "";
  const buildAvatarMemoryHoverId =
    typeof window.JinRuntime.buildAvatarMemoryHoverId === "function"
      ? window.JinRuntime.buildAvatarMemoryHoverId
      : () => "";
  const memoryReferenceHelpers =
    window.JinRuntime.memoryReferences || {};
  const containsMemoryReference =
    typeof memoryReferenceHelpers.contains === "function"
      ? memoryReferenceHelpers.contains
      : () => false;
  const normalizeMemoryReferenceAliases =
    typeof memoryReferenceHelpers.normalizeAliases === "function"
      ? memoryReferenceHelpers.normalizeAliases
      : aliases => (Array.isArray(aliases) ? aliases : []);
  const collectMemoryMetadataReferenceAliases =
    typeof memoryReferenceHelpers.collectMetadataAliases === "function"
      ? memoryReferenceHelpers.collectMetadataAliases
      : () => [];
  if (!avatarRoot) {
    return;
  }

  let centerColor = DEFAULT_CENTER_COLOR;
  let centerColorTransitionStyleTimer = null;
  let initialBootstrapColorPending = true;
  const reasoningMotionSources = new Set();
  const requestedAnimationPlaybackRates = new WeakMap();
  let avatarRotationAnimationsCache = null;
  let reasoningMotionActive = false;
  let reasoningWhisperActive = false;
  let avatarRotationPlaybackRate = 1;
  let reasoningRotationRampTimer = null;
  let reasoningMutationTimer = null;
  let reasoningLayerSettleTimer = null;
  let reasoningLayerSettleActive = false;
  let memoryLayersDormantTimer = null;
  const memoryReferenceHighlightState = {
    persistentText: "",
  };
  // Keep matching/link payload in JS. The SVG is a visual projection, not a
  // second serialized copy of runtime/L4/delayed/file state. WeakMap also
  // lets rebuilt rings release their payload together with detached nodes.
  const avatarNodeState = new WeakMap();

  function getAvatarNodeState(node, create = false) {
    if (!node) {
      return null;
    }

    let state = avatarNodeState.get(node) || null;

    if (!state && create) {
      state = Object.create(null);
      avatarNodeState.set(node, state);
    }

    return state;
  }

  function setAvatarNodeState(node, values) {
    if (!node || !values || typeof values !== "object") {
      return null;
    }

    const state = getAvatarNodeState(node, true);
    Object.assign(state, values);
    return state;
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, Number(value) || 0));
  }

  function degreesFromArcPixels(pixels, radius) {
    const normalizedPixels =
      Number(pixels || 0);
    const normalizedRadius =
      Number(radius || 0);

    if (
      normalizedPixels <= 0
      || normalizedRadius <= 0
    ) {
      return 0;
    }

    return (
      normalizedPixels
      / normalizedRadius
      * (180 / Math.PI)
    );
  }

  function getMemoryDashArcDegrees(layout, slotDegrees) {
    const baseArcDegrees =
      clamp(
        slotDegrees * layout.arcRatio,
        layout.minArcDegrees,
        layout.maxArcDegrees
      );
    const trimDegrees =
      degreesFromArcPixels(
        layout.arcTrimPixels,
        layout.radius
      );

    if (!trimDegrees) {
      return baseArcDegrees;
    }

    return Math.max(
      0.8,
      baseArcDegrees - trimDegrees
    );
  }

  function getMemoryDotRadius(layout) {
    const baseRadius =
      Math.max(layout.strokeWidth * 1.45, 1.35);

    return Math.max(baseRadius - 1, 0.6);
  }

  function setAvatarMemoryReferenceAliases(node, aliases) {
    if (!node) {
      return;
    }

    const normalizedAliases =
      normalizeMemoryReferenceAliases(aliases);
    const state = getAvatarNodeState(node, true);

    state.referenceAliases = normalizedAliases;
  }

  function getAvatarMemoryReferenceAliases(node) {
    const state = getAvatarNodeState(node);

    return normalizeMemoryReferenceAliases(
      state && state.referenceAliases
    );
  }

  function getAvatarMemoryReferenceDisplayKey(value) {
    const key = String(value || "").trim();
    const runtimeModel =
      window.JinRuntime
      && window.JinRuntime.memoryModel;

    if (
      !key
      || !runtimeModel
      || !runtimeModel.runtimeMemoryDisplay
      || typeof runtimeModel.runtimeMemoryDisplay.convertKeyToName !== "function"
    ) {
      return "";
    }

    return runtimeModel.runtimeMemoryDisplay.convertKeyToName(key);
  }

  function hashString(value) {
    let hash = 2166136261;

    for (const char of String(value || "")) {
      hash ^= char.codePointAt(0);
      hash = Math.imul(hash, 16777619);
    }

    return hash >>> 0;
  }

  function createRandom(seedValue) {
    let seed = hashString(seedValue) || 1;

    return function random() {
      seed += 0x6D2B79F5;
      let value = seed;
      value = Math.imul(value ^ (value >>> 15), value | 1);
      value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
      return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
    };
  }

  function createSvgElement(name, attributes = {}) {
    const node = document.createElementNS(SVG_NS, name);

    Object.entries(attributes).forEach(([key, value]) => {
      if (value === null || value === undefined) {
        return;
      }

      node.setAttribute(key, String(value));
    });

    return node;
  }

  function createReasoningMotionLayer(seedValue, intensity = 1) {
    const random = createRandom(`reasoning-motion:${seedValue}`);
    const strength = clamp(intensity, 0.08, 1);
    const frontBase = (0.016 + random() * 0.030) * strength;
    const backBase = (0.012 + random() * 0.024) * strength;
    const anisotropy = (0.002 + random() * 0.007) * strength;
    const drift = (0.25 + random() * 1.25) * strength;
    const duration = 3.6 + random() * 3.8;
    const delay = 0.10 + random() * 0.72;
    const frontX = 1 + frontBase + anisotropy;
    const frontY = 1 + frontBase - anisotropy;
    const backX = 1 - backBase - anisotropy * 0.72;
    const backY = 1 - backBase + anisotropy * 0.72;
    const motion = createSvgElement("g", {
      class: "jin-avatar-reasoning-motion",
    });
    const twitch = createSvgElement("g", {
      class: "jin-avatar-reasoning-twitch",
    });

    motion.style.setProperty(
      "--jin-avatar-whisper-front-x",
      frontX.toFixed(4)
    );
    motion.style.setProperty(
      "--jin-avatar-whisper-front-y",
      frontY.toFixed(4)
    );
    motion.style.setProperty(
      "--jin-avatar-whisper-back-x",
      backX.toFixed(4)
    );
    motion.style.setProperty(
      "--jin-avatar-whisper-back-y",
      backY.toFixed(4)
    );
    motion.style.setProperty(
      "--jin-avatar-whisper-drift-x",
      `${((random() - 0.5) * drift * 2).toFixed(3)}px`
    );
    motion.style.setProperty(
      "--jin-avatar-whisper-drift-y",
      `${((random() - 0.5) * drift * 2).toFixed(3)}px`
    );
    motion.style.setProperty(
      "--jin-avatar-whisper-return-x",
      `${((random() - 0.5) * drift * 1.3).toFixed(3)}px`
    );
    motion.style.setProperty(
      "--jin-avatar-whisper-return-y",
      `${((random() - 0.5) * drift * 1.3).toFixed(3)}px`
    );
    motion.style.setProperty(
      "--jin-avatar-whisper-duration",
      `${duration.toFixed(3)}s`
    );
    motion.style.setProperty(
      "--jin-avatar-whisper-delay",
      `${delay.toFixed(3)}s`
    );
    motion.style.setProperty(
      "--jin-avatar-whisper-depth-opacity",
      (1 - (0.018 + random() * 0.045) * strength).toFixed(3)
    );

    motion.appendChild(twitch);

    return {
      layer: motion,
      content: twitch,
    };
  }

  function invalidateAvatarRotationAnimationsCache() {
    avatarRotationAnimationsCache = null;
  }

  function getAvatarRotationAnimations() {
    if (avatarRotationAnimationsCache !== null) {
      return avatarRotationAnimationsCache;
    }

    const nodes = avatarRoot.querySelectorAll(
      ".jin-avatar-orbit, .jin-avatar-counter-orbit"
    );
    const animations = [];

    nodes.forEach((node) => {
      if (typeof node.getAnimations !== "function") {
        return;
      }

      node.getAnimations().forEach((animation) => {
        const animationName = String(animation.animationName || "");

        if (
          animationName === "jin-avatar-orbit-rotation"
          || animationName === "jin-avatar-counter-rotation"
        ) {
          animations.push(animation);
        }
      });
    });

    // Discover rotation handles once and reuse them for every frame of the
    // reasoning ramp. Orbit DOM rebuilds explicitly invalidate this cache,
    // so a replacement SVG is picked up on the next sync without rescanning
    // the whole avatar on every requestAnimationFrame.
    avatarRotationAnimationsCache = animations;
    return avatarRotationAnimationsCache;
  }

  function setAnimationPlaybackRate(animation, rate) {
    if (!animation) {
      return;
    }

    const nextRate = Math.max(0, Number(rate) || 0);
    const requestedRate = requestedAnimationPlaybackRates.get(animation);
    const currentRate = Number(animation.playbackRate);
    const previousRate = Number.isFinite(requestedRate)
      ? requestedRate
      : currentRate;

    // Do not enqueue a Web Animations update when the requested speed did not
    // actually change. In particular, reasoning starts from the current 1.0
    // orbit rate; touching every orbit with a redundant 1 -> 1 update created
    // a visible compositor stall before the deceleration began.
    if (
      Number.isFinite(previousRate)
      && Math.abs(previousRate - nextRate) < 0.0005
    ) {
      return;
    }

    requestedAnimationPlaybackRates.set(animation, nextRate);

    try {
      // Preserve the current visual phase while changing speed. In Chromium,
      // updatePlaybackRate() avoids a timing rebase at the full-stop boundary;
      // direct assignment remains the fallback for older implementations.
      if (typeof animation.updatePlaybackRate === "function") {
        animation.updatePlaybackRate(nextRate);
      } else {
        animation.playbackRate = nextRate;
      }
    } catch (error) {
      // A detached animation can disappear while the SVG is being rebuilt.
    }
  }
  function getAvatarRotationAnimation(node) {
    if (!node || typeof node.getAnimations !== "function") {
      return null;
    }

    return node.getAnimations().find((animation) => {
      const animationName = String(animation.animationName || "");

      return (
        animationName === "jin-avatar-orbit-rotation"
        || animationName === "jin-avatar-counter-rotation"
      );
    }) || null;
  }

  function normalizeAvatarRotationAngle(angle) {
    const normalized = Number(angle);

    if (!Number.isFinite(normalized)) {
      return null;
    }

    return ((normalized % 360) + 360) % 360;
  }

  function getAvatarRotationVisualAngle(node) {
    if (!node) {
      return null;
    }

    try {
      const transform = window.getComputedStyle(node).transform;

      if (!transform || transform === "none") {
        return 0;
      }

      const matrixMatch = transform.match(/^matrix\(([^)]+)\)$/);
      const matrix3dMatch = transform.match(/^matrix3d\(([^)]+)\)$/);
      const values = String(
        matrixMatch?.[1] || matrix3dMatch?.[1] || ""
      )
        .split(",")
        .map(value => Number(value.trim()));

      if (values.length < 2 || !values.every(Number.isFinite)) {
        return null;
      }

      return normalizeAvatarRotationAngle(
        Math.atan2(values[1], values[0]) * 180 / Math.PI
      );
    } catch (error) {
      return null;
    }
  }

  function captureAvatarRotationPhase(node) {
    const angle = getAvatarRotationVisualAngle(node);

    return angle === null
      ? null
      : { angle };
  }

  function captureAvatarRotationPhases(scope = avatarRoot) {
    const phases = new Map();

    scope
      .querySelectorAll(
        ".jin-avatar-orbit[data-avatar-rotation-key], .jin-avatar-counter-orbit[data-avatar-rotation-key]"
      )
      .forEach((node) => {
        const key = String(node.dataset.avatarRotationKey || "").trim();

        if (!key || phases.has(key)) {
          return;
        }

        const phase = captureAvatarRotationPhase(node);

        if (phase) {
          phases.set(key, phase);
        }
      });

    return phases;
  }

  function getAvatarRotationAnimationDirection(animation) {
    if (!animation) {
      return 1;
    }

    const animationName = String(animation.animationName || "");
    let direction = animationName === "jin-avatar-counter-rotation"
      ? -1
      : 1;

    try {
      const timing = animation.effect?.getTiming?.();

      if (timing && timing.direction === "reverse") {
        direction *= -1;
      }
    } catch (error) {
      // Keep the animation-name direction when timing is unavailable.
    }

    return direction;
  }

  function restoreAvatarRotationPhase(node, phase) {
    if (!node || !phase) {
      return false;
    }

    const animation = getAvatarRotationAnimation(node);
    const angle = normalizeAvatarRotationAngle(phase.angle);

    if (!animation || angle === null) {
      return false;
    }

    try {
      const timing = animation.effect?.getTiming?.();
      const duration = Number(timing && timing.duration);

      if (!Number.isFinite(duration) || duration <= 0) {
        return false;
      }

      const angleRatio = angle / 360;
      const progress = getAvatarRotationAnimationDirection(animation) >= 0
        ? angleRatio
        : ((1 - angleRatio) % 1);

      animation.currentTime = progress * duration;
      return true;
    } catch (error) {
      // The replacement animation can disappear during another immediate sync.
      return false;
    }
  }

  function restoreAvatarRotationPhases(phases, scope = avatarRoot) {
    if (!(phases instanceof Map) || !phases.size) {
      return;
    }

    scope
      .querySelectorAll(
        ".jin-avatar-orbit[data-avatar-rotation-key], .jin-avatar-counter-orbit[data-avatar-rotation-key]"
      )
      .forEach((node) => {
        const key = String(node.dataset.avatarRotationKey || "").trim();
        const phase = phases.get(key);

        if (phase) {
          restoreAvatarRotationPhase(node, phase);
        }
      });
  }

  function stopReasoningRotationRamp() {
    if (!reasoningRotationRampTimer) {
      return;
    }

    window.cancelAnimationFrame(reasoningRotationRampTimer);
    reasoningRotationRampTimer = null;
  }

  function setReasoningWhisperActive(active) {
    reasoningWhisperActive = Boolean(active);

    if (avatarShell) {
      avatarShell.classList.toggle(
        REASONING_WHISPER_CLASS,
        reasoningWhisperActive
      );
    }
  }

  function syncAvatarRotationPlaybackRate() {
    getAvatarRotationAnimations().forEach((animation) => {
      setAnimationPlaybackRate(
        animation,
        avatarRotationPlaybackRate
      );
    });
  }

  function rampAvatarRotationPlaybackRate(
    targetRate,
    durationMs,
    onComplete = null
  ) {
    stopReasoningRotationRamp();

    const target = clamp(targetRate, 0, 1);
    const duration = Math.max(0, Number(durationMs) || 0);
    const startRate = clamp(
      avatarRotationPlaybackRate,
      0,
      1
    );
    const complete = () => {
      if (typeof onComplete === "function") {
        onComplete();
      }
    };

    if (duration <= 0 || Math.abs(target - startRate) < 0.0005) {
      avatarRotationPlaybackRate = target;
      syncAvatarRotationPlaybackRate();
      complete();
      return;
    }

    // The original reasoning transition stayed continuous because the orbit
    // was allowed to paint before its speed changed. Keep that property: do
    // the ramp on paint-aligned frames instead of a 24 ms interval and avoid
    // a synchronous animation update burst in the class-switching task.
    const startedAt = window.performance && typeof window.performance.now === "function"
      ? window.performance.now()
      : Date.now();

    const apply = (frameTime) => {
      const now = Number.isFinite(Number(frameTime))
        ? Number(frameTime)
        : Date.now();
      const elapsed = Math.max(0, now - startedAt);
      const ratio = clamp(elapsed / duration, 0, 1);
      const eased = ratio * ratio * (3 - 2 * ratio);

      avatarRotationPlaybackRate =
        startRate + (target - startRate) * eased;
      syncAvatarRotationPlaybackRate();

      if (ratio >= 1) {
        reasoningRotationRampTimer = null;
        avatarRotationPlaybackRate = target;
        complete();
        return;
      }

      reasoningRotationRampTimer = window.requestAnimationFrame(apply);
    };

    reasoningRotationRampTimer = window.requestAnimationFrame(apply);
  }

  function clearReasoningLayerSettleStyles() {
    if (!reasoningLayerSettleActive && !reasoningLayerSettleTimer) {
      return;
    }

    if (reasoningLayerSettleTimer) {
      clearTimeout(reasoningLayerSettleTimer);
      reasoningLayerSettleTimer = null;
    }

    reasoningLayerSettleActive = false;

    avatarRoot
      .querySelectorAll(".jin-avatar-reasoning-motion")
      .forEach((layer) => {
        layer.style.removeProperty("animation");
        layer.style.removeProperty("transition");
        layer.style.removeProperty("transform");
        layer.style.removeProperty("opacity");
      });
  }

  function settleReasoningLayersToIdle() {
    const layers = Array.from(
      avatarRoot.querySelectorAll(".jin-avatar-reasoning-motion")
    );

    if (!layers.length) {
      reasoningLayerSettleActive = false;
      reasoningWhisperActive = false;
      if (avatarShell) {
        avatarShell.classList.remove(
          REASONING_MOTION_CLASS,
          REASONING_WHISPER_CLASS
        );
      }
      return;
    }

    reasoningLayerSettleActive = true;

    layers.forEach((layer) => {
      const computed = window.getComputedStyle(layer);
      const transform = computed.transform === "none"
        ? "matrix(1, 0, 0, 1, 0, 0)"
        : computed.transform;
      const opacity = computed.opacity || "1";

      layer.style.setProperty("animation", "none");
      layer.style.setProperty("transition", "none");
      layer.style.setProperty("transform", transform);
      layer.style.setProperty("opacity", opacity);
    });

    reasoningWhisperActive = false;

    if (avatarShell) {
      avatarShell.classList.remove(
        REASONING_MOTION_CLASS,
        REASONING_WHISPER_CLASS
      );
    }

    // Force the captured in-between whisper pose to become the transition start.
    void avatarRoot.getBoundingClientRect();

    layers.forEach((layer) => {
      layer.style.setProperty(
        "transition",
        `transform ${REASONING_LAYER_SETTLE_MS}ms cubic-bezier(0.16, 0.84, 0.22, 1), opacity 760ms ease-out`
      );
      layer.style.setProperty(
        "transform",
        "matrix(1, 0, 0, 1, 0, 0)"
      );
      layer.style.setProperty("opacity", "1");
    });

    reasoningLayerSettleTimer = setTimeout(() => {
      reasoningLayerSettleTimer = null;
      clearReasoningLayerSettleStyles();
    }, REASONING_LAYER_SETTLE_MS + 80);
  }

  function getReasoningWhisperAnimation(layer) {
    if (!layer || typeof layer.getAnimations !== "function") {
      return null;
    }

    return layer.getAnimations().find((animation) => (
      String(animation.animationName || "") === REASONING_WHISPER_ANIMATION
    )) || null;
  }

  function runReasoningUncertaintyMutation() {
    if (!reasoningMotionActive || !reasoningWhisperActive) {
      return;
    }

    const layers = Array.from(
      avatarRoot.querySelectorAll(".jin-avatar-reasoning-motion")
    );

    if (!layers.length) {
      return;
    }

    const layer = layers[Math.floor(Math.random() * layers.length)];
    const twitch = layer.querySelector(".jin-avatar-reasoning-twitch");
    const whisperAnimation = getReasoningWhisperAnimation(layer);

    if (
      twitch
      && typeof twitch.animate === "function"
      && Math.random() < 0.58
    ) {
      const dx = (Math.random() - 0.5) * 1.35;
      const dy = (Math.random() - 0.5) * 1.35;
      const scale = 1 + (Math.random() - 0.5) * 0.009;

      twitch.animate(
        [
          { transform: "translate(0px, 0px) scale(1)" },
          { transform: `translate(${dx.toFixed(3)}px, ${dy.toFixed(3)}px) scale(${scale.toFixed(4)})`, offset: 0.44 },
          { transform: "translate(0px, 0px) scale(1)" },
        ],
        {
          duration: 230 + Math.round(Math.random() * 260),
          easing: "cubic-bezier(0.22, 0.61, 0.36, 1)",
        }
      );
    }

    if (whisperAnimation && Math.random() < 0.72) {
      const temporaryRate = 0.76 + Math.random() * 0.54;
      setAnimationPlaybackRate(whisperAnimation, temporaryRate);

      setTimeout(() => {
        if (
          reasoningMotionActive
          && reasoningWhisperActive
          && layer.isConnected
          && getReasoningWhisperAnimation(layer) === whisperAnimation
        ) {
          setAnimationPlaybackRate(whisperAnimation, 1);
        }
      }, 520 + Math.round(Math.random() * 760));
    }
  }

  function scheduleReasoningUncertaintyMutation() {
    if (reasoningMutationTimer) {
      clearTimeout(reasoningMutationTimer);
      reasoningMutationTimer = null;
    }

    if (!reasoningMotionActive || !reasoningWhisperActive) {
      return;
    }

    reasoningMutationTimer = setTimeout(() => {
      reasoningMutationTimer = null;
      runReasoningUncertaintyMutation();
      scheduleReasoningUncertaintyMutation();
    }, 1900 + Math.round(Math.random() * 3100));
  }

  function activateReasoningMotion() {
    if (reasoningMotionActive) {
      return;
    }

    reasoningMotionActive = true;
    setReasoningWhisperActive(false);
    clearReasoningLayerSettleStyles();

    if (avatarShell) {
      avatarShell.classList.add(
        REASONING_MOTION_CLASS
      );
      avatarShell.dataset.motionMode = "reasoning";
    }

    rampAvatarRotationPlaybackRate(
      0,
      REASONING_ROTATION_STOP_MS,
      () => {
        if (!reasoningMotionActive) {
          return;
        }

        // Rotation has reached a true full stop. Hand off to the
        // reasoning whisper immediately in the same frame so there is no
        // blank paint between the stopped orbit and the pulse/depth motion.
        setReasoningWhisperActive(true);
        scheduleReasoningUncertaintyMutation();
      }
    );
  }

  function deactivateReasoningMotion() {
    if (!reasoningMotionActive) {
      return;
    }

    reasoningMotionActive = false;
    if (reasoningMutationTimer) {
      clearTimeout(reasoningMutationTimer);
      reasoningMutationTimer = null;
    }

    if (avatarShell) {
      delete avatarShell.dataset.motionMode;
    }

    if (reasoningWhisperActive) {
      settleReasoningLayersToIdle();
    } else {
      setReasoningWhisperActive(false);
      if (avatarShell) {
        avatarShell.classList.remove(REASONING_MOTION_CLASS);
      }
    }

    rampAvatarRotationPlaybackRate(
      1,
      REASONING_ROTATION_RESUME_MS
    );
  }

  function beginReasoningMotion(sourceId) {
    const key = String(sourceId || "default-reasoning");
    const wasEmpty = reasoningMotionSources.size === 0;

    reasoningMotionSources.add(key);

    if (wasEmpty) {
      activateReasoningMotion();
    }
  }

  function endReasoningMotion(sourceId) {
    const key = String(sourceId || "default-reasoning");

    reasoningMotionSources.delete(key);

    if (reasoningMotionSources.size === 0) {
      deactivateReasoningMotion();
    }
  }

  function clearReasoningMotion() {
    reasoningMotionSources.clear();
    deactivateReasoningMotion();
  }

  function normalizeL4FactIds(value) {
    const source =
      Array.isArray(value)
        ? value
        : [value];
    const factIds = [];
    const seen = new Set();

    source.forEach((item) => {
      if (Array.isArray(item)) {
        normalizeL4FactIds(item).forEach((factId) => {
          if (seen.has(factId)) {
            return;
          }

          seen.add(factId);
          factIds.push(factId);
        });
        return;
      }

      const text =
        String(item || "").trim();

      if (text.startsWith("[") && text.endsWith("]")) {
        try {
          const parsed = JSON.parse(text);

          if (Array.isArray(parsed)) {
            normalizeL4FactIds(parsed).forEach((factId) => {
              if (seen.has(factId)) {
                return;
              }

              seen.add(factId);
              factIds.push(factId);
            });
            return;
          }
        } catch (_error) {
          // Fall through to token parsing.
        }
      }

      text
        .split(/[\s,;]+/)
        .map(candidate => (
          String(candidate || "")
            .trim()
            .replace(/^["'\[]+|["'\]]+$/g, "")
            .toUpperCase()
        ))
        .forEach((candidate) => {
          if (
            !/^F[1-9]\d*$/.test(candidate)
            || seen.has(candidate)
          ) {
            return;
          }

          seen.add(candidate);
          factIds.push(candidate);
        });
    });

    return factIds;
  }

  function l4FactIdSetsIntersect(left, right) {
    if (!left || !right || !left.size || !right.size) {
      return false;
    }

    for (const factId of left) {
      if (right.has(factId)) {
        return true;
      }
    }

    return false;
  }


  function normalizeShortRuntimeIds(value) {
    const source = Array.isArray(value)
      ? value
      : [value];
    const ids = [];
    const seen = new Set();

    source.flat(Infinity).forEach((item) => {
      String(item || "")
        .split(/[\s,;]+/)
        .map((candidate) => (
          String(candidate || "")
            .trim()
            .replace(/^[\[\]"']+|[\[\]"']+$/g, "")
            .toLowerCase()
        ))
        .filter(Boolean)
        .forEach((candidate) => {
          if (!/^[a-z0-9]{6}$/.test(candidate) || seen.has(candidate)) {
            return;
          }

          seen.add(candidate);
          ids.push(candidate);
        });
    });

    return ids;
  }

  function shortRuntimeIdSetsIntersect(left, right) {
    if (!left || !right || !left.size || !right.size) {
      return false;
    }

    for (const id of left) {
      if (right.has(id)) {
        return true;
      }
    }

    return false;
  }

  function countOccurrences(text, words) {
    const source = String(text || "").toLowerCase();

    return (Array.isArray(words) ? words : [words])
      .map(word => String(word || "").trim().toLowerCase())
      .filter(Boolean)
      .reduce((count, word) => {
        let cursor = 0;
        let matches = 0;

        while (cursor < source.length) {
          const index = source.indexOf(word, cursor);

          if (index < 0) {
            break;
          }

          matches += 1;
          cursor = index + Math.max(1, word.length);
        }

        return count + matches;
      }, 0);
  }

  function hexToRgb(color) {
    const normalized = String(color || "").replace("#", "").trim();
    const expanded = normalized.length === 3
      ? normalized.split("").map(char => `${char}${char}`).join("")
      : normalized;

    if (!/^[0-9a-f]{6}$/i.test(expanded)) {
      return { r: 40, g: 207, b: 199 };
    }

    return {
      r: parseInt(expanded.slice(0, 2), 16),
      g: parseInt(expanded.slice(2, 4), 16),
      b: parseInt(expanded.slice(4, 6), 16),
    };
  }

  function rgbToHex(rgb) {
    const channel = value => Math.round(clamp(value, 0, 255))
      .toString(16)
      .padStart(2, "0");

    return `#${channel(rgb.r)}${channel(rgb.g)}${channel(rgb.b)}`;
  }

  function normalizeHexColor(color) {
    const normalized =
      String(color || "")
        .trim()
        .replace(/^#/, "");

    if (!/^([0-9a-f]{3}|[0-9a-f]{6})$/i.test(normalized)) {
      return "";
    }

    const expanded = normalized.length === 3
      ? normalized.split("").map(char => `${char}${char}`).join("")
      : normalized;

    return `#${expanded.toLowerCase()}`;
  }

  function mixColors(firstColor, secondColor, amount) {
    const first = hexToRgb(firstColor);
    const second = hexToRgb(secondColor);
    const ratio = clamp(amount, 0, 1);

    return rgbToHex({
      r: first.r + (second.r - first.r) * ratio,
      g: first.g + (second.g - first.g) * ratio,
      b: first.b + (second.b - first.b) * ratio,
    });
  }

  function blendWeightedColors(entries, fallback = DEFAULT_RING_COLOR) {
    const valid = entries.filter(entry => entry && entry.weight > 0);

    if (!valid.length) {
      return fallback;
    }

    const totalWeight = valid.reduce((sum, entry) => sum + entry.weight, 0);
    const blended = valid.reduce((result, entry) => {
      const rgb = hexToRgb(entry.color);
      result.r += rgb.r * entry.weight;
      result.g += rgb.g * entry.weight;
      result.b += rgb.b * entry.weight;
      return result;
    }, { r: 0, g: 0, b: 0 });

    return rgbToHex({
      r: blended.r / totalWeight,
      g: blended.g / totalWeight,
      b: blended.b / totalWeight,
    });
  }

  function normalizePalette(palette) {
    return (Array.isArray(palette) ? palette : [])
      .map((entry) => {
        if (Array.isArray(entry)) {
          return {
            words: Array.isArray(entry[0]) ? entry[0] : [entry[0]],
            color: entry[1],
          };
        }

        return {
          words: Array.isArray(entry && entry.words)
            ? entry.words
            : [entry && entry.words],
          color: entry && entry.color,
        };
      })
      .filter(entry => entry.words.some(Boolean) && entry.color);
  }

  const normalizedAggressivePalette = normalizePalette(AGGRESSIVE_PALETTE);
  const normalizedKeywordPalette = normalizePalette(KEYWORD_PALETTE);

  function parseRawMemory(rawMemory) {
    return String(rawMemory || "")
      .split(/\r?\n/)
      .map(line => line.trim())
      .filter(Boolean)
      .map((line) => {
        const separatorIndex = line.indexOf(":");

        if (separatorIndex <= 0) {
          return {
            key: "runtime_memory",
            value: line,
          };
        }

        return {
          key: line.slice(0, separatorIndex).trim(),
          value: line.slice(separatorIndex + 1).trim(),
        };
      });
  }

  function extractActiveMemoryId(value) {
    const match =
      String(value || "")
        .match(
          /\[\s*active_memory_id\s*:\s*([a-z0-9]{6})\s*\]/i
        );

    return match
      ? String(match[1] || "").trim().toLowerCase()
      : "";
  }

  function getActiveMemoryAvatarRecordStatus(value) {
    let source = String(value || "").trimEnd();

    while (source.endsWith("]")) {
      const match = source.match(
        /\[\s*([\w.-]+)\s*:\s*([^\[\]]*)\s*\]\s*$/
      );

      if (!match) {
        break;
      }

      if (String(match[1] || "").trim().toLowerCase() === "status") {
        return String(match[2] || "").trim().toLowerCase();
      }

      source = source.slice(0, match.index).trimEnd();
    }

    return "";
  }

  function getRuntimeChangeMarkerStatus(line) {
    const statuses = [
      line && line.status,
      line && line.key_status,
      line && line.value_status,
    ]
      .map(value => String(value || "").trim().toLowerCase())
      .filter(Boolean);

    if (statuses.includes("new")) {
      return "new";
    }

    if (
      statuses.includes("changed")
      || Math.max(
        Number(line && line.key_change_ratio || 0),
        Number(line && line.value_change_ratio || 0)
      ) > 0
    ) {
      return "changed";
    }

    return "";
  }

  function getRuntimeChangeMarkerIdentity(line, index) {
    const lineId = String(line && line.id || "").trim();

    if (lineId) {
      return `id:${lineId}`;
    }

    const activeMemoryId =
      String(line && line.active_memory_id || "").trim();

    if (activeMemoryId) {
      return `active:${activeMemoryId}`;
    }

    const key =
      normalizeRuntimeCitationIdentity(
        line && line.key || ""
      );
    const value =
      normalizeRuntimeCitationIdentity(
        line && line.value || ""
      );

    // Runtime memory may legitimately contain repeated keys (for example,
    // several `jin_fact` lines). A key-only identity collapses those lines
    // into one marker, so every sibling inherits the same change ratio.
    // Keep the concrete line text and source position in the fallback.
    return (key || value)
      ? `line:${index}:${key}␟${value}`
      : `line:${index}`;
  }

  function getSnapshotLines(snapshot) {
    const sourceLines = snapshot && Array.isArray(snapshot.lines)
      ? snapshot.lines
      : parseRawMemory(snapshot && snapshot.raw_memory);
    const activeMemoryIdsByKey = new Map(
      getActiveMemoryAvatarRecords()
        .filter(record => record && record.id && record.key)
        .map(record => [
          String(record.key).trim().toLowerCase(),
          String(record.id).trim().toLowerCase(),
        ])
    );

    return sourceLines
      .map((line, index) => {
        const key = String(line && line.key || `memory_${index + 1}`).trim();
        const value = String(line && line.value || "").trim();
        const text = `${key}: ${value}`.trim();
        const lineId =
          String(line && line.id || "").trim();
        const activeMemoryId =
          String(
            line && line.active_memory_id
            || extractActiveMemoryId(value)
            || extractActiveMemoryId(text)
            || activeMemoryIdsByKey.get(key.toLowerCase())
            || ""
          ).trim().toLowerCase();
        const status =
          String(line && line.status || "").trim().toLowerCase();
        const keyStatus =
          String(line && line.key_status || "").trim().toLowerCase();
        const valueStatus =
          String(line && line.value_status || "").trim().toLowerCase();

        return {
          id: lineId,
          activeMemoryId,
          key,
          value,
          text,
          status,
          keyStatus,
          valueStatus,
          changeMarkerIdentity:
            getRuntimeChangeMarkerIdentity(line, index),
          changeMarkerStatus:
            getRuntimeChangeMarkerStatus(line),
          avatarMemoryHoverId:
            buildAvatarMemoryHoverId(
              "runtime",
              lineId || `line-${index}`
            ),
          referenceAliases:
            normalizeMemoryReferenceAliases([
              key,
              getAvatarMemoryReferenceDisplayKey(key),
              lineId,
              activeMemoryId,
              ...collectMemoryMetadataReferenceAliases(value),
            ]),
          length: Array.from(text).length,
          changeRatio: Math.max(
            Number(line && line.key_change_ratio || 0),
            Number(line && line.value_change_ratio || 0)
          ),
        };
      })
      .filter(line => line.text);
  }

  function collectSnapshotChangeMarkers(snapshot) {
    const markers = new Map();

    getSnapshotLines(snapshot).forEach((line) => {
      if (!line.changeMarkerStatus) {
        return;
      }

      markers.set(
        line.changeMarkerIdentity,
        {
          status: line.changeMarkerStatus,
          ratio:
            line.changeMarkerStatus === "new"
              ? 1
              : clamp(line.changeRatio, 0, 1),
        }
      );
    });

    return markers;
  }

  function snapshotHasRuntimeChange(snapshot) {
    const totalDiff =
      Number(snapshot && snapshot.total_diff);

    if (Number.isFinite(totalDiff) && totalDiff > 0) {
      return true;
    }

    const patch =
      snapshot && snapshot.patch;

    if (!patch || typeof patch !== "object") {
      return false;
    }

    return ["added", "changed", "removed"]
      .some(key => (
        Array.isArray(patch[key])
        && patch[key].length > 0
      ));
  }

  function getSnapshotHistory() {
    const runtime = getRuntimeApi();

    if (
      !runtime
      || typeof runtime.getRuntimeMemorySnapshots !== "function"
    ) {
      return [];
    }

    const snapshots = runtime.getRuntimeMemorySnapshots();

    return Array.isArray(snapshots)
      ? snapshots
      : [];
  }

  function resolveRuntimeChangeMarkers(snapshot, snapshotIndex = null) {
    const directMarkers =
      collectSnapshotChangeMarkers(snapshot);

    if (
      directMarkers.size
      || snapshotHasRuntimeChange(snapshot)
    ) {
      return directMarkers;
    }

    const snapshots = getSnapshotHistory();

    if (!snapshots.length) {
      return directMarkers;
    }

    const requestedIndex =
      snapshotIndex !== null && snapshotIndex !== undefined
        ? Number(snapshotIndex)
        : Number(snapshot && snapshot.index);
    let resolvedIndex =
      Number.isInteger(requestedIndex)
        ? requestedIndex
        : snapshots.findIndex(candidate => candidate === snapshot);

    if (resolvedIndex < 0) {
      const runtimeMemoryId =
        String(snapshot && snapshot.runtime_memory_id || "").trim();

      if (runtimeMemoryId) {
        resolvedIndex =
          snapshots.findIndex(candidate => (
            String(
              candidate && candidate.runtime_memory_id || ""
            ).trim() === runtimeMemoryId
          ));
      }
    }

    if (resolvedIndex < 0) {
      resolvedIndex = snapshots.length - 1;
    }

    for (let index = resolvedIndex - 1; index >= 0; index -= 1) {
      const markers =
        collectSnapshotChangeMarkers(snapshots[index]);

      if (
        markers.size
        || snapshotHasRuntimeChange(snapshots[index])
      ) {
        return markers;
      }
    }

    return directMarkers;
  }

  function getSnapshotDiff(snapshot, lines) {
    const directDiff = Number(snapshot && snapshot.total_diff);

    if (Number.isFinite(directDiff)) {
      return clamp(directDiff, 0, 100);
    }

    if (!lines.length) {
      return 0;
    }

    const averageRatio = lines.reduce(
      (sum, line) => sum + clamp(line.changeRatio, 0, 1),
      0
    ) / lines.length;

    return clamp(averageRatio * 100, 0, 100);
  }

  function getPaletteColor(text, fallback) {
    const weighted = [{ color: fallback, weight: 1.75 }];

    normalizedKeywordPalette.forEach((entry) => {
      const count = countOccurrences(text, entry.words);

      if (count) {
        weighted.push({
          color: entry.color,
          weight: count * 1.35,
        });
      }
    });

    return blendWeightedColors(weighted, fallback);
  }

  function getAggressiveMatch(text) {
    let bestMatch = null;

    normalizedAggressivePalette.forEach((entry) => {
      const count = countOccurrences(text, entry.words);

      if (!count) {
        return;
      }

      if (!bestMatch || count > bestMatch.count) {
        bestMatch = {
          color: entry.color,
          count,
        };
      }
    });

    return bestMatch;
  }

  function computeRingRecords(lines, snapshotSeed, changeMarkers = new Map()) {
    const lengths = lines.map(line => line.length);
    const maxLength = Math.max(...lengths);
    const averageLength = lengths.reduce((sum, value) => sum + value, 0) / lengths.length;
    const variance = lengths.reduce(
      (sum, value) => sum + Math.pow(value - averageLength, 2),
      0
    ) / lengths.length;
    const deviation = Math.sqrt(variance);
    const radiusRange = MAX_RING_RADIUS - MIN_RING_RADIUS;

    const records = lines.map((line, index) => {
      const random = createRandom(`${snapshotSeed}:${line.key}:${line.value}:${index}`);
      const sourceOrderRatio =
        lines.length <= 1
          ? 0.5
          : 1 - index / (lines.length - 1);
      const radius = MIN_RING_RADIUS
        + sourceOrderRatio * radiusRange;

      return {
        ...line,
        index,
        random,
        radius: clamp(radius, MIN_RING_RADIUS, MAX_RING_RADIUS),
        isLong: line.length >= averageLength + Math.max(7, deviation * 0.62)
          || (line.length === maxLength && lines.length > 1),
        aggressive: getAggressiveMatch(line.text),
        changeMarker:
          changeMarkers.get(line.changeMarkerIdentity) || null,
      };
    });

    records.sort((first, second) => first.index - second.index);

    records.forEach((record, index) => {
      if (index === 0) {
        return;
      }

      const previous = records[index - 1];
      const maximumRadius = previous.radius - Math.max(1.7, 4.4 - records.length * 0.08);

      if (record.radius > maximumRadius) {
        record.radius = Math.max(MIN_RING_RADIUS, maximumRadius);
      }
    });

    return records;
  }

  function computeOverallColor(lines, records) {
    const completeText = lines.map(line => line.text).join("\n");
    let color = getPaletteColor(completeText, DEFAULT_RING_COLOR);

    const aggressiveCount = records.reduce(
      (sum, record) => sum + Number(record.aggressive && record.aggressive.count || 0),
      0
    );

    if (aggressiveCount >= 2) {
      const aggressiveColor = records.find(record => record.aggressive).aggressive.color;
      color = mixColors(color, aggressiveColor, Math.min(0.46, aggressiveCount * 0.08));
    }

    return color;
  }

  function getNeighbourAggressiveInfluence(record, records) {
    let strongest = null;

    records.forEach((candidate) => {
      if (!candidate.aggressive || candidate === record) {
        return;
      }

      const distance = Math.abs(candidate.radius - record.radius);
      const strength = clamp(1 - distance / 30, 0, 1) * 0.68;

      if (strength > 0 && (!strongest || strength > strongest.strength)) {
        strongest = {
          color: candidate.aggressive.color,
          strength,
        };
      }
    });

    return strongest;
  }

  function polarPoint(radius, degrees) {
    const radians = (degrees - 90) * Math.PI / 180;

    return {
      x: CENTER + Math.cos(radians) * radius,
      y: CENTER + Math.sin(radians) * radius,
    };
  }

  function describeArcPath(radius, startAngle, endAngle) {
    const start = polarPoint(radius, startAngle);
    const end = polarPoint(radius, endAngle);
    const arcDegrees = Math.abs(endAngle - startAngle);

    return [
      `M ${start.x.toFixed(3)} ${start.y.toFixed(3)}`,
      `A ${radius.toFixed(3)} ${radius.toFixed(3)} 0 ${arcDegrees > 180 ? 1 : 0} 1`,
      `${end.x.toFixed(3)} ${end.y.toFixed(3)}`,
    ].join(" ");
  }

  function getRuntimeApi() {
    return window.JinRuntime && window.JinRuntime.runtime
      ? window.JinRuntime.runtime
      : null;
  }

  function getActiveMemoryAvatarRecords() {
    const runtime = getRuntimeApi();
    const records =
      runtime && typeof runtime.getActiveMemoryRecords === "function"
        ? runtime.getActiveMemoryRecords()
        : [];

    return (Array.isArray(records) ? records : [])
      .map((record, index) => {
        const text = String(record || "").trim();

        if (!text) {
          return null;
        }

        const parsed = parseRawMemory(text)[0] || {
          key: `active_memory_${index + 1}`,
          value: text,
        };
        const key =
          String(parsed.key || `active_memory_${index + 1}`).trim();
        const value =
          String(parsed.value || text).trim();
        const activeMemoryId =
          extractActiveMemoryId(text);

        const paused =
          getActiveMemoryAvatarRecordStatus(value) === "paused";
        const lineText =
          `${key}: ${value}`.trim();

        if (!lineText) {
          return null;
        }

        return {
          id: activeMemoryId,
          index,
          key,
          value,
          paused,
          text: lineText,
          avatarMemoryHoverId:
            buildAvatarMemoryHoverId(
              "active",
              activeMemoryId
                || `record-${index}`
            ),
          referenceAliases:
            normalizeMemoryReferenceAliases([
              key,
              getAvatarMemoryReferenceDisplayKey(key),
              activeMemoryId,
              ...collectMemoryMetadataReferenceAliases(value),
            ]),
          citationText:
            normalizeRuntimeCitationIdentity(lineText),
        };
      })
      .filter(record => record && record.citationText);
  }

  function getDelayedMemoryAvatarRecords() {
    const runtime = getRuntimeApi();
    const reports =
      runtime && typeof runtime.getDelayedMemoryReports === "function"
        ? runtime.getDelayedMemoryReports()
        : {};

    if (
      !reports
      || typeof reports !== "object"
      || Array.isArray(reports)
    ) {
      return [];
    }

    return Object.entries(reports)
      .map(([key, report]) => {
        if (
          !report
          || typeof report !== "object"
          || Array.isArray(report)
        ) {
          return null;
        }

        const id =
          String(key || "").trim().toLowerCase();
        const title =
          String(report.title || "").trim();
        const summary =
          String(report.summary || "").trim();
        const anchorFactIds =
          normalizeL4FactIds(report.anchor_fact_ids);
        const factIds =
          normalizeL4FactIds(report.facts_ids);
        const linkedFactIds =
          normalizeL4FactIds([
            report.anchor_fact_ids,
            report.facts_ids,
            report.absorbed_fact_ids,
            report.long_term_facts_ids,
          ]);
        // Keep pin and explicit-load state separate. Both are direct DM
        // states for Tier 2 and both may act as secondary-link sources.
        const loaded =
          Boolean(
            runtime
            && typeof runtime.isDelayedMemoryReportLoaded === "function"
            && runtime.isDelayedMemoryReportLoaded(id)
          );

        if (!id || !title) {
          return null;
        }

        return {
          id,
          title,
          summary,
          pinned: Boolean(report.pinned),
          loaded,
          anchorFactIds,
          factIds,
          linkedFactIds,
          attachmentIds:
            normalizeShortRuntimeIds(
              report.attachments_ids
            ),
          avatarMemoryHoverId:
            buildAvatarMemoryHoverId(
              "delayed",
              id
            ),
          referenceAliases:
            normalizeMemoryReferenceAliases([
              id,
              report.id,
              title,
            ]),
        };
      })
      .filter(Boolean)
      .sort((left, right) => {
        return String(left.id || "").localeCompare(
          String(right.id || "")
        );
      });
  }

  function getL4MemoryAvatarRecords() {
    const l4Memory =
      window.JinRuntime && window.JinRuntime.l4Memory;
    const facts =
      l4Memory && typeof l4Memory.getFactsWithArchiveState === "function"
        ? l4Memory.getFactsWithArchiveState()
        : l4Memory && typeof l4Memory.getFacts === "function"
        ? l4Memory.getFacts()
        : [];

    return (Array.isArray(facts) ? facts : [])
      .map((fact) => {
        if (
          !fact
          || typeof fact !== "object"
          || Array.isArray(fact)
        ) {
          return null;
        }

        const id = String(fact.id || "").trim();
        const key = String(fact.key || "").trim();
        const value = String(fact.value || fact.content || "").trim();
        const lineText = `${key}: ${value}`.trim();
        const l4FactIds =
          normalizeL4FactIds([
            id,
            fact.source_fact_ids,
          ]);

        if (!id || !key || !value) {
          return null;
        }

        return {
          id,
          key,
          value,
          text: lineText,
          l4FactIds,
          archived:
            Boolean(
              fact.archived
              || fact.hidden_from_context
            ),
          avatarMemoryHoverId:
            buildAvatarMemoryHoverId(
              "l4",
              id
            ),
          citationIdentity:
            buildCitationRecordIdentity(
              id,
              key,
              value
            ),
          referenceAliases:
            normalizeMemoryReferenceAliases([
              id,
              key,
              getAvatarMemoryReferenceDisplayKey(key),
            ]),
        };
      })
      .filter(Boolean)
      .sort((left, right) => {
        return String(left.id || "").localeCompare(
          String(right.id || "")
        );
      });
  }


  function getPersistentFileAvatarRecords() {
    const filesApi = window.JinFiles;
    const delayedMemoryRecords = getDelayedMemoryAvatarRecords();
    const linkedReportIdsByFileId = new Map();
    const contextLinkedFileIds = new Set();

    delayedMemoryRecords.forEach((report) => {
      const attachmentIds = normalizeShortRuntimeIds(
        report && report.attachmentIds
      );

      if (!attachmentIds.length) {
        return;
      }

      attachmentIds.forEach((fileId) => {
        const current =
          linkedReportIdsByFileId.get(fileId)
          || new Set();

        current.add(report.id);
        linkedReportIdsByFileId.set(fileId, current);

        if (report.loaded) {
          contextLinkedFileIds.add(fileId);
        }
      });
    });

    const records =
      filesApi && typeof filesApi.getFiles === "function"
        ? filesApi.getFiles()
        : [];

    return (Array.isArray(records) ? records : [])
      .map((record) => {
        if (
          !record
          || typeof record !== "object"
          || Array.isArray(record)
        ) {
          return null;
        }

        const id =
          normalizeShortRuntimeIds(record.id)[0] || "";
        const name = String(record.name || "").trim();
        const storedName = String(record.stored_name || "").trim();
        const contextPath =
          String(
            record.context_path
            || (storedName ? `/assets/files/${storedName}` : "")
          ).trim();
        const linkedReportIds = Array.from(
          linkedReportIdsByFileId.get(id) || []
        ).sort((left, right) => left.localeCompare(right));
        const pinned = Boolean(record.pinned);
        const contextLinked =
          !pinned
          && contextLinkedFileIds.has(id);
        const contextLoaded = pinned;

        if (!id || !name) {
          return null;
        }

        return {
          id,
          name,
          storedName,
          contextPath,
          pinned,
          contextLoaded,
          contextLinked,
          linkedReportIds,
          avatarMemoryHoverId:
            buildAvatarMemoryHoverId(
              "file",
              id
            ),
          referenceAliases:
            normalizeMemoryReferenceAliases([
              id,
              name,
              storedName,
              contextPath,
              record.url,
              storedName ? storedName.replace(/^([a-z0-9]{6}_)/i, "") : "",
            ]),
        };
      })
      .filter(Boolean)
      .sort((left, right) => {
        // Keep each file on a stable angular slot. Pin/context state must only
        // change the dot appearance, never its position on the file ring.
        return String(left.id || "").localeCompare(
          String(right.id || "")
        );
      });
  }

  function appendMemoryDashSegment(parent, layout, options) {
    const arcDegrees =
      clamp(
        options.arcDegrees,
        0.8,
        layout.maxArcDegrees
      );
    const startAngle = options.angle - arcDegrees / 2;
    const endAngle = options.angle + arcDegrees / 2;
    const renderedColor = options.color;
    const isDot = Boolean(options.dot);
    const dotRadius =
      isDot
        ? getMemoryDotRadius(layout)
        : 0;
    const classNames = [
      "jin-avatar-memory-dash",
      `jin-avatar-memory-dash-${options.kind}`,
    ];

    if (options.pinned) {
      classNames.push("is-memory-pinned");
    }

    if (options.contextLoaded) {
      classNames.push("is-context-loaded");
    }

    if (options.archived) {
      classNames.push("is-memory-archived");
    }

    if (isDot) {
      classNames.push("is-memory-dot");
    }

    const dashGroup = createSvgElement("g", {
      class: classNames.join(" "),
      "data-avatar-memory-hover-id": options.avatarMemoryHoverId || null,
      "data-active-memory-id": options.activeMemoryId || null,
      "data-delayed-memory-id": options.delayedMemoryId || null,
      "data-l4-fact-id": options.l4FactId || null,
    });

    const nodeState = Object.create(null);

    if (options.citationKey) {
      nodeState.runtimeLineKey = options.citationKey;
    }
    if (options.citationText) {
      nodeState.runtimeLineText = options.citationText;
    }
    if (options.citationIdentity) {
      nodeState.runtimeLineIdentity = options.citationIdentity;
    }
    if (options.kind === "delayed") {
      nodeState.delayedMemoryFactIds =
        normalizeL4FactIds(options.delayedMemoryFactIds);
      nodeState.delayedMemoryAnchorFactIds =
        normalizeL4FactIds(options.delayedMemoryAnchorFactIds);
    }
    if (options.kind === "l4") {
      nodeState.l4FactIds =
        normalizeL4FactIds(options.l4FactIds);
      nodeState.avatarMemoryAngle = Number(options.angle);
    }

    setAvatarNodeState(dashGroup, nodeState);

    setAvatarMemoryReferenceAliases(
      dashGroup,
      options.referenceAliases
    );

    dashGroup.appendChild(createSvgElement("path", {
      class: isDot ? "jin-avatar-memory-dash-arc" : null,
      d: describeArcPath(layout.radius, startAngle, endAngle),
      fill: "none",
      stroke: renderedColor,
      "stroke-width": layout.strokeWidth,
      "stroke-opacity": options.opacity,
      "stroke-linecap": "round",
    }));

    if (isDot) {
      const dotPoint = polarPoint(layout.radius, options.angle);
      dashGroup.appendChild(createSvgElement("circle", {
        class: "jin-avatar-memory-dot",
        cx: dotPoint.x.toFixed(3),
        cy: dotPoint.y.toFixed(3),
        r: dotRadius.toFixed(2),
        fill: renderedColor,
        "fill-opacity": options.opacity,
      }));
    }

    parent.appendChild(dashGroup);
  }

  function setMemoryDashGlowVariables(
    dashGroup,
    glowColor,
    hoverWidth,
    dotRadius
  ) {
    const glowRgb = hexToRgb(glowColor);

    dashGroup.style.setProperty(
      "--jin-avatar-memory-glow-near",
      `rgba(${glowRgb.r},${glowRgb.g},${glowRgb.b},0.92)`
    );
    dashGroup.style.setProperty(
      "--jin-avatar-memory-glow-mid",
      `rgba(${glowRgb.r},${glowRgb.g},${glowRgb.b},0.54)`
    );
    dashGroup.style.setProperty(
      "--jin-avatar-memory-glow-far",
      `rgba(${glowRgb.r},${glowRgb.g},${glowRgb.b},0.24)`
    );
    dashGroup.style.setProperty(
      "--jin-avatar-memory-hover-width",
      `${Number(hoverWidth || 2).toFixed(2)}px`
    );

    if (dotRadius) {
      dashGroup.style.setProperty(
        "--jin-avatar-memory-dot-radius",
        `${Number(dotRadius).toFixed(2)}px`
      );
      dashGroup.style.setProperty(
        "--jin-avatar-memory-hover-dot-radius",
        `${Number(dotRadius + 0.85).toFixed(2)}px`
      );
      return;
    }

    dashGroup.style.removeProperty(
      "--jin-avatar-memory-dot-radius"
    );
    dashGroup.style.removeProperty(
      "--jin-avatar-memory-hover-dot-radius"
    );
  }

  function setFileDotGlowVariables(dotGroup, glowColor) {
    const glowRgb = hexToRgb(glowColor || FILE_RING_ACTIVE_COLOR);

    dotGroup.style.setProperty(
      "--jin-avatar-file-glow-near",
      `rgba(${glowRgb.r},${glowRgb.g},${glowRgb.b},0.98)`
    );
    dotGroup.style.setProperty(
      "--jin-avatar-file-glow-mid",
      `rgba(${glowRgb.r},${glowRgb.g},${glowRgb.b},0.62)`
    );
    dotGroup.style.setProperty(
      "--jin-avatar-file-glow-far",
      `rgba(${glowRgb.r},${glowRgb.g},${glowRgb.b},0.24)`
    );
  }

  function getMemoryRingAnimation(records, kind) {
    const seedText = records
      .map(record => (
        kind === "active"
          ? record.text
          : record.id
      ))
      .join("|");
    const random =
      createRandom(`memory-ring:${kind}:${seedText}`);
    const animationProfile = {
      active: [38, 72],
      delayed: [54, 112],
      l4: [46, 96],
    }[kind] || [54, 112];
    const [baseDuration, durationSpread] = animationProfile;

    return {
      duration: baseDuration + random() * durationSpread,
      direction: random() > 0.5 ? "normal" : "reverse",
    };
  }

  function getMemorySignalColors(kind, overallColor) {
    if (kind === "active") {
      return {
        color: mixColors(
          ACTIVE_MEMORY_RING_COLOR,
          overallColor,
          0.18
        ),
        glowColor: ACTIVE_MEMORY_RING_COLOR,
      };
    }

    if (kind === "l4") {
      return {
        color: mixColors(
          L4_MEMORY_RING_COLOR,
          overallColor,
          0.08
        ),
        glowColor: L4_MEMORY_RING_COLOR,
      };
    }

    const color =
      mixColors(DELAYED_MEMORY_RING_COLOR, overallColor, 0.12);

    return {
      color,
      glowColor: color,
    };
  }

  function appendMemorySignalRing(svg, records, layout, kind, overallColor) {
    if (!records.length) {
      return;
    }

    const animation =
      getMemoryRingAnimation(records, kind);
    const ring = createSvgElement("g", {
      class: [
        "jin-avatar-memory-ring",
        `jin-avatar-memory-ring-${kind}`,
        "jin-avatar-orbit",
      ].join(" "),
      "data-avatar-rotation-key": `memory:${kind}`,
      fill: "none",
      "pointer-events": "none",
      style: [
        `--jin-avatar-duration:${animation.duration.toFixed(2)}s`,
        `--jin-avatar-direction:${animation.direction}`,
        "--jin-avatar-play-state:running",
      ].join(";"),
    });
    const reasoningMotion = createReasoningMotionLayer(
      `memory-ring:${kind}:${records.length}`,
      kind === "delayed" ? 0.94 : 0.82
    );
    ring.appendChild(reasoningMotion.layer);
    const ringColors =
      getMemorySignalColors(kind, overallColor);
    const dotRadius =
      kind === "l4"
        ? getMemoryDotRadius(layout)
        : 0;

    setMemoryDashGlowVariables(
      ring,
      ringColors.glowColor,
      layout.strokeWidth + 0.75,
      dotRadius
    );
    if (kind === "l4") {
      ring.style.setProperty(
        "--jin-avatar-memory-dot-opacity",
        "0.26"
      );
    }
    const slotDegrees = 360 / records.length;
    const arcDegrees =
      getMemoryDashArcDegrees(
        layout,
        slotDegrees
      );

    records.forEach((record, index) => {
      const angle = layout.startAngle + slotDegrees * index;

      if (kind === "active") {
        if (record.paused) {
          return;
        }

        appendMemoryDashSegment(
          reasoningMotion.content,
          layout,
          {
            kind,
            angle,
            arcDegrees,
            color: ringColors.color,
            opacity: 0.76,
            avatarMemoryHoverId: record.avatarMemoryHoverId,
            activeMemoryId: record.id,
            citationKey:
              normalizeRuntimeCitationIdentity(record.key),
            referenceAliases: record.referenceAliases,
          }
        );
        return;
      }

      if (kind === "l4") {
        appendMemoryDashSegment(
          reasoningMotion.content,
          layout,
          {
            kind,
            angle,
            arcDegrees,
            color: ringColors.color,
            opacity: record.archived ? 0.26 : 0.52,
            archived: record.archived,
            dot: record.archived,
            avatarMemoryHoverId: record.avatarMemoryHoverId,
            citationKey:
              normalizeRuntimeCitationIdentity(record.key),
            citationIdentity: record.citationIdentity,
            l4FactId: record.id,
            l4FactIds: record.l4FactIds,
            referenceAliases: record.referenceAliases,
          }
        );
        return;
      }

      const pinned = Boolean(record.pinned);
      const contextLoaded = Boolean(record.loaded);
      const active = pinned || contextLoaded;
      // Delayed memory has one base hue. Direct state and references are
      // expressed only through the two CSS highlight tiers.
      appendMemoryDashSegment(
        reasoningMotion.content,
        layout,
        {
          kind,
          angle,
          arcDegrees,
          color: ringColors.color,
          opacity: active ? 0.82 : 0.36,
          pinned,
          contextLoaded,
          avatarMemoryHoverId: record.avatarMemoryHoverId,
          citationKey:
            normalizeRuntimeCitationIdentity(record.id),
          delayedMemoryId: record.id,
          delayedMemoryFactIds: record.linkedFactIds,
          delayedMemoryAnchorFactIds: record.anchorFactIds,
          referenceAliases: record.referenceAliases,
        }
      );
    });

    svg.appendChild(ring);
  }

  function appendFileSignalRing(svg, records) {
    if (!records.length) {
      return;
    }

    const random = createRandom(
      `file-ring:${records.map(record => record.id).join("|")}`
    );
    const duration = 92 + random() * 84;
    const direction = random() > 0.5 ? "normal" : "reverse";
    const ring = createSvgElement("g", {
      class: [
        "jin-avatar-file-ring",
        "jin-avatar-counter-orbit",
      ].join(" "),
      "data-avatar-rotation-key": "files",
      fill: "none",
      "pointer-events": "none",
      style: [
        `--jin-avatar-duration:${duration.toFixed(2)}s`,
        `--jin-avatar-direction:${direction}`,
        "--jin-avatar-play-state:running",
      ].join(";"),
    });
    const reasoningMotion = createReasoningMotionLayer(
      `file-ring:${records.map(record => record.id).join("|")}`,
      0.72
    );
    ring.appendChild(reasoningMotion.layer);
    const slotDegrees = 360 / records.length;

    records.forEach((record, index) => {
      const angle = FILE_RING_LAYOUT.startAngle + slotDegrees * index;
      const point = polarPoint(FILE_RING_LAYOUT.radius, angle);
      const opacity = record.pinned
        ? 0.96
        : 0.36;
      const color = record.pinned
        ? FILE_RING_ACTIVE_COLOR
        : FILE_RING_COLOR;
      const glowColor = record.pinned
        ? FILE_RING_ACTIVE_COLOR
        : FILE_RING_LAYOUT.glowColor;
      const dotGroup = createSvgElement("g", {
        class: "jin-avatar-file-dot",
        "data-avatar-memory-hover-id": record.avatarMemoryHoverId || null,
        "data-file-id": record.id,
      });

      setAvatarNodeState(
        dotGroup,
        {
          linkedDelayedMemoryIds:
            normalizeShortRuntimeIds(record.linkedReportIds),
          runtimeLineKey:
            normalizeRuntimeCitationIdentity(record.id),
          runtimeLineText:
            normalizeRuntimeCitationIdentity(
              [record.name, record.contextPath]
                .filter(Boolean)
                .join(" · ")
            ),
        }
      );

      if (record.pinned) {
        dotGroup.classList.add("is-memory-pinned");
      }

      if (record.contextLoaded) {
        dotGroup.classList.add("is-context-loaded");
      }

      if (record.contextLinked) {
        dotGroup.classList.add("is-delayed-memory-context-linked");
      }

      setAvatarMemoryReferenceAliases(
        dotGroup,
        record.referenceAliases
      );
      setFileDotGlowVariables(
        dotGroup,
        glowColor
      );
      dotGroup.appendChild(createSvgElement("circle", {
        class: "jin-avatar-file-dot-core",
        cx: point.x.toFixed(3),
        cy: point.y.toFixed(3),
        r: FILE_RING_LAYOUT.dotRadius,
        fill: color,
        "fill-opacity": opacity.toFixed(2),
      }));
      reasoningMotion.content.appendChild(dotGroup);
    });

    const centerNode = svg.querySelector(".jin-avatar-center");

    if (centerNode) {
      svg.insertBefore(ring, centerNode);
    } else {
      svg.appendChild(ring);
    }
  }

  function getMemorySignalRecords(kind) {
    if (kind === "active") {
      return getActiveMemoryAvatarRecords();
    }

    if (kind === "delayed") {
      return getDelayedMemoryAvatarRecords();
    }

    if (kind === "l4") {
      return getL4MemoryAvatarRecords();
    }

    return null;
  }

  function getMemorySignalInsertionReference(svg, kind) {
    const kindIndex =
      MEMORY_SIGNAL_KIND_ORDER.indexOf(kind);

    if (kindIndex < 0) {
      return null;
    }

    for (
      let index = kindIndex + 1;
      index < MEMORY_SIGNAL_KIND_ORDER.length;
      index += 1
    ) {
      const nextRing =
        svg.querySelector(
          `.jin-avatar-memory-ring-${MEMORY_SIGNAL_KIND_ORDER[index]}`
        );

      if (nextRing) {
        return nextRing;
      }
    }

    return svg.querySelector(".jin-avatar-center");
  }

  function applyAvatarReactiveGlows() {
    applyThinkRuntimeCitationGlow();
    applyMemoryReferenceGlow();
    applyMemoryRowAvatarHoverGlow();
  }

  function syncMemorySignalLayer(kind, options = {}) {
    const svg =
      avatarRoot.querySelector("svg");
    const layout =
      MEMORY_RING_LAYOUT[kind];
    const records =
      getMemorySignalRecords(kind);

    if (
      !svg
      || !layout
      || !Array.isArray(records)
    ) {
      return false;
    }

    const previousRing =
      svg.querySelector(`.jin-avatar-memory-ring-${kind}`);
    const previousRotationPhase =
      captureAvatarRotationPhase(previousRing);

    invalidateAvatarRotationAnimationsCache();

    svg.querySelectorAll(
      `.jin-avatar-memory-ring-${kind}`
    ).forEach(ring => ring.remove());

    if (records.length) {
      const temporaryParent =
        createSvgElement("g");

      appendMemorySignalRing(
        temporaryParent,
        records,
        layout,
        kind,
        avatarRoot.style
          .getPropertyValue("--jin-avatar-overall-color")
          .trim() || DEFAULT_RING_COLOR
      );

      const nextRing =
        temporaryParent.firstElementChild;

      if (!nextRing) {
        return false;
      }

      svg.insertBefore(
        nextRing,
        getMemorySignalInsertionReference(svg, kind)
      );
    }

    if (previousRotationPhase) {
      restoreAvatarRotationPhase(
        svg.querySelector(`.jin-avatar-memory-ring-${kind}`),
        previousRotationPhase
      );
    }

    syncAvatarRotationPlaybackRate();

    if (options.applyGlows !== false) {
      applyAvatarReactiveGlows();
    }

    return true;
  }

  function setDelayedMemoryDashPinned(reportId, pinned) {
    const delayedMemoryId =
      String(reportId || "").trim().toLowerCase();

    if (!/^[a-z0-9]{6}$/.test(delayedMemoryId)) {
      return false;
    }

    const dashGroup =
      avatarRoot.querySelector(
        `.jin-avatar-memory-dash-delayed[data-delayed-memory-id="${delayedMemoryId}"]`
      );

    if (!dashGroup) {
      return false;
    }

    const path =
      dashGroup.querySelector("path");
    const overallColor =
      avatarRoot.style.getPropertyValue("--jin-avatar-overall-color").trim()
      || DEFAULT_RING_COLOR;
    const nextPinned =
      Boolean(pinned);
    const nextContextLoaded =
      dashGroup.classList.contains("is-context-loaded");
    const nextActive =
      nextPinned || nextContextLoaded;
    const colors =
      getMemorySignalColors("delayed", overallColor);

    dashGroup.classList.toggle(
      "is-memory-pinned",
      nextPinned
    );
    setMemoryDashGlowVariables(
      dashGroup.closest(".jin-avatar-memory-ring-delayed") || dashGroup,
      colors.glowColor,
      MEMORY_RING_LAYOUT.delayed.strokeWidth + 0.75
    );

    if (path) {
      path.setAttribute(
        "stroke",
        colors.color
      );
      path.setAttribute(
        "stroke-opacity",
        nextActive ? "0.82" : "0.36"
      );
    }

    applyDelayedMemoryFactLinkGlow();

    return true;
  }

  function getMemoryDashNodesByDataset(svg, selector, datasetKey) {
    const nodesById = new Map();
    const nodes =
      Array.from(svg.querySelectorAll(selector));

    for (const node of nodes) {
      const id =
        String(
          node && node.dataset
            ? node.dataset[datasetKey]
            : ""
        ).trim();

      if (!id || nodesById.has(id)) {
        return null;
      }

      nodesById.set(id, node);
    }

    return {
      nodes,
      nodesById,
    };
  }

  function setL4MemoryDashArchivedState(dashGroup, archived) {
    if (!dashGroup) {
      return false;
    }

    const path =
      dashGroup.querySelector("path");

    if (!path) {
      return false;
    }

    const nextArchived =
      Boolean(archived);
    const nextOpacity =
      nextArchived ? 0.26 : 0.52;
    const overallColor =
      avatarRoot.style.getPropertyValue("--jin-avatar-overall-color").trim()
      || DEFAULT_RING_COLOR;
    const colors =
      getMemorySignalColors("l4", overallColor);
    const dotRadius =
      getMemoryDotRadius(MEMORY_RING_LAYOUT.l4);
    const state = getAvatarNodeState(dashGroup);
    const angle =
      Number(state && state.avatarMemoryAngle);

    if (nextArchived && !Number.isFinite(angle)) {
      return false;
    }

    dashGroup.classList.toggle(
      "is-memory-archived",
      nextArchived
    );
    dashGroup.classList.toggle(
      "is-memory-dot",
      nextArchived
    );

    setMemoryDashGlowVariables(
      dashGroup.closest(".jin-avatar-memory-ring-l4") || dashGroup,
      colors.glowColor,
      MEMORY_RING_LAYOUT.l4.strokeWidth + 0.75,
      dotRadius
    );

    path.classList.toggle(
      "jin-avatar-memory-dash-arc",
      nextArchived
    );
    path.setAttribute(
      "stroke",
      colors.color
    );
    path.setAttribute(
      "stroke-opacity",
      nextOpacity.toFixed(2)
    );

    if (!nextArchived) {
      dashGroup.querySelectorAll(".jin-avatar-memory-dot")
        .forEach(dot => dot.remove());
      return true;
    }

    const dotPoint =
      polarPoint(
        MEMORY_RING_LAYOUT.l4.radius,
        angle
      );
    let dot =
      dashGroup.querySelector(".jin-avatar-memory-dot");

    if (!dot) {
      dot = createSvgElement("circle", {
        class: "jin-avatar-memory-dot",
      });
      dashGroup.appendChild(dot);
    }

    dot.setAttribute("cx", dotPoint.x.toFixed(3));
    dot.setAttribute("cy", dotPoint.y.toFixed(3));
    dot.setAttribute("r", dotRadius.toFixed(2));
    dot.setAttribute("fill", colors.color);
    dot.setAttribute("fill-opacity", nextOpacity.toFixed(2));

    return true;
  }

  function syncDelayedMemoryDashState() {
    const svg =
      avatarRoot.querySelector("svg");

    if (!svg) {
      return false;
    }

    const delayedMemoryRecords =
      getDelayedMemoryAvatarRecords();
    const nodeLookup =
      getMemoryDashNodesByDataset(
        svg,
        ".jin-avatar-memory-dash-delayed",
        "delayedMemoryId"
      );

    if (
      !nodeLookup
      || nodeLookup.nodes.length !== delayedMemoryRecords.length
    ) {
      return false;
    }

    let synced = true;

    delayedMemoryRecords.forEach((record) => {
      const dashGroup =
        nodeLookup.nodesById.get(record.id);

      if (!dashGroup) {
        synced = false;
        return;
      }

      setAvatarNodeState(
        dashGroup,
        {
          delayedMemoryFactIds:
            normalizeL4FactIds(record.linkedFactIds),
          delayedMemoryAnchorFactIds:
            normalizeL4FactIds(record.anchorFactIds),
        }
      );
      setAvatarMemoryReferenceAliases(
        dashGroup,
        record.referenceAliases
      );
      dashGroup.classList.toggle(
        "is-context-loaded",
        Boolean(record.loaded)
      );

      if (
        !setDelayedMemoryDashPinned(
          record.id,
          Boolean(record.pinned),
          Boolean(record.appended)
        )
      ) {
        synced = false;
      }
    });

    return synced;
  }

  function syncL4MemoryArchiveState() {
    const svg =
      avatarRoot.querySelector("svg");

    if (!svg) {
      return false;
    }

    const l4MemoryRecords =
      getL4MemoryAvatarRecords();
    const nodeLookup =
      getMemoryDashNodesByDataset(
        svg,
        ".jin-avatar-memory-dash-l4",
        "l4FactId"
      );

    if (
      !nodeLookup
      || nodeLookup.nodes.length !== l4MemoryRecords.length
    ) {
      return false;
    }

    let synced = true;

    l4MemoryRecords.forEach((record) => {
      const dashGroup =
        nodeLookup.nodesById.get(record.id);

      if (!dashGroup) {
        synced = false;
        return;
      }

      setAvatarNodeState(
        dashGroup,
        {
          l4FactIds:
            normalizeL4FactIds(record.l4FactIds),
          runtimeLineKey:
            normalizeRuntimeCitationIdentity(record.key),
          runtimeLineIdentity:
            record.citationIdentity || "",
        }
      );
      setAvatarMemoryReferenceAliases(
        dashGroup,
        record.referenceAliases
      );

      if (
        !setL4MemoryDashArchivedState(
          dashGroup,
          record.archived
        )
      ) {
        synced = false;
      }
    });

    return synced;
  }

  function syncDelayedMemoryState() {
    const delayedSynced =
      syncDelayedMemoryDashState()
      || syncMemorySignalLayer(
        "delayed",
        { applyGlows: false }
      );
    const l4Synced =
      syncL4MemoryArchiveState()
      || syncMemorySignalLayer(
        "l4",
        { applyGlows: false }
      );

    if (!delayedSynced || !l4Synced) {
      return false;
    }

    syncFilesState();
    applyAvatarReactiveGlows();

    return true;
  }

  function syncActiveMemoryState() {
    return syncMemorySignalLayer("active");
  }

  function syncL4MemoryState() {
    return syncMemorySignalLayer("l4");
  }

  function syncFileSignalRingState(svg, records) {
    const ring = svg.querySelector(".jin-avatar-file-ring");

    if (!records.length) {
      return !ring;
    }

    if (!ring) {
      return false;
    }

    const dotGroups = Array.from(
      ring.querySelectorAll(".jin-avatar-file-dot")
    );

    if (dotGroups.length !== records.length) {
      return false;
    }

    const dotsById = new Map();

    for (const dotGroup of dotGroups) {
      const fileId = normalizeShortRuntimeIds(
        dotGroup && dotGroup.dataset
          ? dotGroup.dataset.fileId
          : ""
      )[0];

      if (!fileId || dotsById.has(fileId)) {
        return false;
      }

      dotsById.set(fileId, dotGroup);
    }

    for (const record of records) {
      const dotGroup = dotsById.get(record.id);

      if (!dotGroup) {
        return false;
      }

      const pinned = Boolean(record.pinned);
      const contextLoaded = Boolean(record.contextLoaded);
      const contextLinked = Boolean(record.contextLinked);
      const active = pinned || contextLoaded;
      const core = dotGroup.querySelector(
        ".jin-avatar-file-dot-core"
      );

      dotGroup.classList.toggle(
        "is-memory-pinned",
        pinned
      );
      dotGroup.classList.toggle(
        "is-context-loaded",
        contextLoaded
      );
      dotGroup.classList.toggle(
        "is-delayed-memory-context-linked",
        contextLinked
      );
      dotGroup.dataset.avatarMemoryHoverId =
        record.avatarMemoryHoverId || "";
      setAvatarNodeState(
        dotGroup,
        {
          linkedDelayedMemoryIds:
            normalizeShortRuntimeIds(record.linkedReportIds),
          runtimeLineKey:
            normalizeRuntimeCitationIdentity(record.id),
          runtimeLineText:
            normalizeRuntimeCitationIdentity(
              [record.name, record.contextPath]
                .filter(Boolean)
                .join(" · ")
            ),
        }
      );

      setAvatarMemoryReferenceAliases(
        dotGroup,
        record.referenceAliases
      );
      const baseColor =
        active
          ? FILE_RING_ACTIVE_COLOR
          : FILE_RING_COLOR;
      const glowColor =
        active
          ? FILE_RING_ACTIVE_COLOR
          : FILE_RING_LAYOUT.glowColor;
      setFileDotGlowVariables(
        dotGroup,
        glowColor
      );

      if (core) {
        core.setAttribute(
          "fill",
          baseColor
        );
        core.setAttribute(
          "fill-opacity",
          (pinned
            ? 0.96
            : 0.36
          ).toFixed(2)
        );
        core.setAttribute(
          "r",
          FILE_RING_LAYOUT.dotRadius
        );
      }
    }

    return true;
  }

  function syncFilesState(options = {}) {
    const svg = avatarRoot.querySelector("svg");

    if (!svg) {
      return false;
    }

    const records = getPersistentFileAvatarRecords();
    let previousRotationPhase = null;
    let fileRingRebuilt = false;

    // State-only changes stay in place so pinning cannot restart the rotating
    // ring animation. Rebuild only when the actual file set changes.
    if (!syncFileSignalRingState(svg, records)) {
      previousRotationPhase = captureAvatarRotationPhase(
        svg.querySelector(".jin-avatar-file-ring")
      );
      fileRingRebuilt = true;
      invalidateAvatarRotationAnimationsCache();

      svg.querySelectorAll(
        ".jin-avatar-file-ring"
      ).forEach((ring) => ring.remove());

      if (records.length) {
        appendFileSignalRing(svg, records);
      }
    }

    if (fileRingRebuilt && previousRotationPhase) {
      restoreAvatarRotationPhase(
        svg.querySelector(".jin-avatar-file-ring"),
        previousRotationPhase
      );
    }

    syncAvatarRotationPlaybackRate();

    if (options.applyGlows !== false) {
      applyAvatarReactiveGlows();
      applyDelayedMemoryFileLinkGlow();
    }

    return true;
  }

  function appendMemorySignalRings(
    svg,
    activeMemoryRecords,
    delayedMemoryRecords,
    l4MemoryRecords,
    overallColor
  ) {
    appendMemorySignalRing(
      svg,
      delayedMemoryRecords,
      MEMORY_RING_LAYOUT.delayed,
      "delayed",
      overallColor
    );
    appendMemorySignalRing(
      svg,
      l4MemoryRecords,
      MEMORY_RING_LAYOUT.l4,
      "l4",
      overallColor
    );
    appendMemorySignalRing(
      svg,
      activeMemoryRecords,
      MEMORY_RING_LAYOUT.active,
      "active",
      overallColor
    );
  }

  function appendFileRing(svg, fileRecords) {
    appendFileSignalRing(svg, fileRecords);
  }

  function appendDefs(svg, overallColor, currentCenterColor) {
    const defs = createSvgElement("defs");

    const halo = createSvgElement("radialGradient", {
      id: "jin-avatar-halo",
      cx: "50%",
      cy: "50%",
      r: "50%",
    });
    halo.appendChild(createSvgElement("stop", {
      offset: "0%",
      "stop-color": overallColor,
      "stop-opacity": "0.14",
    }));
    halo.appendChild(createSvgElement("stop", {
      offset: "46%",
      "stop-color": overallColor,
      "stop-opacity": "0.035",
    }));
    halo.appendChild(createSvgElement("stop", {
      offset: "100%",
      "stop-color": overallColor,
      "stop-opacity": "0",
    }));
    defs.appendChild(halo);

    const centerGlow = createSvgElement("radialGradient", {
      id: "jin-avatar-center-glow",
      cx: "50%",
      cy: "50%",
      r: "50%",
    });
    centerGlow.appendChild(createSvgElement("stop", {
      class: "jin-avatar-center-glow-stop",
      offset: "0%",
      "stop-color": currentCenterColor,
      "stop-opacity": "0.68",
    }));
    centerGlow.appendChild(createSvgElement("stop", {
      class: "jin-avatar-center-glow-stop",
      offset: "24%",
      "stop-color": currentCenterColor,
      "stop-opacity": "0.32",
    }));
    centerGlow.appendChild(createSvgElement("stop", {
      class: "jin-avatar-center-glow-stop",
      offset: "62%",
      "stop-color": currentCenterColor,
      "stop-opacity": "0.11",
    }));
    centerGlow.appendChild(createSvgElement("stop", {
      class: "jin-avatar-center-glow-stop",
      offset: "100%",
      "stop-color": currentCenterColor,
      "stop-opacity": "0",
    }));
    defs.appendChild(centerGlow);

    svg.appendChild(defs);
  }

  function appendStaticScaffold(svg, overallColor, currentCenterColor, diffPercent, random) {
    const scaffold = createSvgElement("g", {
      class: "jin-avatar-scaffold",
      fill: "none",
      "pointer-events": "none",
    });
    const reasoningMotion = createReasoningMotionLayer(
      `scaffold:${overallColor}:${currentCenterColor}`,
      0.34
    );
    scaffold.appendChild(reasoningMotion.layer);
    const scaffoldContent = reasoningMotion.content;
    const diffRatio =
      clamp(Number(diffPercent || 0) / 100, 0, 1);
    const rayEnergy =
      clamp(0.18 + diffRatio * 0.82, 0.18, 1);
    const rayCount = 16;
    const activeRayCount =
      Math.max(3, Math.min(7, 3 + Math.round(rayEnergy * 4)));
    const activeRayIndexes = new Set();

    while (
      activeRayIndexes.size < activeRayCount
      && activeRayIndexes.size < rayCount
    ) {
      activeRayIndexes.add(
        Math.floor(random() * rayCount)
      );
    }

    scaffoldContent.appendChild(createSvgElement("circle", {
      cx: CENTER,
      cy: CENTER,
      r: 168,
      fill: "url(#jin-avatar-halo)",
    }));

    STATIC_SCAFFOLD_RADII.forEach((radius, index) => {
      scaffoldContent.appendChild(createSvgElement("circle", {
        cx: CENTER,
        cy: CENTER,
        r: radius,
        stroke: index % 2 ? overallColor : ACCENT_RING_COLOR,
        "stroke-width": index % 3 === 0 ? 0.7 : 0.45,
        "stroke-opacity": index % 2 ? 0.10 : 0.065,
        "stroke-dasharray": index % 2 ? "1 5" : "8 11",
      }));
    });

    for (let index = 0; index < rayCount; index += 1) {
      const angle = index * 22.5 + (random() - 0.5) * 2;
      const inner = polarPoint(STATIC_RADIAL_LINE_INNER_RADIUS, angle);
      const outer = polarPoint(STATIC_RADIAL_LINE_OUTER_RADIUS, angle);
      const activeRay =
        activeRayIndexes.has(index);
      const visibilitySeed = random();
      const baseOpacity =
        activeRay
          ? 0.018 + rayEnergy * 0.022 + random() * 0.008
          : 0.002 + Math.pow(visibilitySeed, 3.2) * (0.012 + rayEnergy * 0.010);
      const softOpacity =
        baseOpacity + (
          activeRay
            ? 0.012 + rayEnergy * 0.016
            : Math.pow(random(), 2.5) * 0.008
        );
      const midOpacity =
        baseOpacity + (
          activeRay
            ? 0.026 + rayEnergy * 0.028 + random() * 0.008
            : Math.pow(random(), 3.3) * 0.012
        );
      const peakOpacity =
        activeRay
          ? baseOpacity + 0.050 + rayEnergy * 0.048 + random() * 0.010
          : baseOpacity + Math.pow(random(), 4.0) * 0.014;
      const durationSeconds =
        24 + random() * 24 + (1 - rayEnergy) * 8;
      const phaseRatio =
        (index / rayCount + random() * 0.22) % 1;
      const rayColor =
        mixColors(
          mixColors(currentCenterColor, overallColor, 0.36 + random() * 0.24),
          "#081018",
          activeRay
            ? 0.42 + (1 - rayEnergy) * 0.08
            : 0.54 + (1 - rayEnergy) * 0.10
        );

      scaffoldContent.appendChild(createSvgElement("line", {
        class: [
          "jin-avatar-scaffold-ray",
          "is-jin-avatar-ray-breathing",
        ].join(" "),
        x1: inner.x,
        y1: inner.y,
        x2: outer.x,
        y2: outer.y,
        stroke: rayColor,
        "stroke-width": activeRay ? 0.42 + random() * 0.34 : 0.30 + random() * 0.22,
        "stroke-opacity": "1",
        style: [
          `--jin-avatar-ray-base-opacity:${Math.min(activeRay ? 0.058 : 0.018, baseOpacity).toFixed(3)}`,
          `--jin-avatar-ray-soft-opacity:${Math.min(activeRay ? 0.088 : 0.026, softOpacity).toFixed(3)}`,
          `--jin-avatar-ray-mid-opacity:${Math.min(activeRay ? 0.118 : 0.038, midOpacity).toFixed(3)}`,
          `--jin-avatar-ray-peak-opacity:${Math.min(activeRay ? 0.165 : 0.050, peakOpacity).toFixed(3)}`,
          `--jin-avatar-ray-duration:${durationSeconds.toFixed(2)}s`,
          `--jin-avatar-ray-delay:${(-phaseRatio * durationSeconds).toFixed(2)}s`,
          "--jin-avatar-ray-play-state:running",
        ].join(";"),
      }));
    }

    svg.appendChild(scaffold);
  }

  function appendArcCircle(group, radius, color, width, opacity, startAngle, arcDegrees) {
    const circumference = 2 * Math.PI * radius;
    const arcLength = circumference * clamp(arcDegrees, 1, 359) / 360;

    group.appendChild(createSvgElement("circle", {
      cx: CENTER,
      cy: CENTER,
      r: radius,
      fill: "none",
      stroke: color,
      "stroke-width": width,
      "stroke-opacity": opacity,
      "stroke-linecap": "round",
      "stroke-dasharray": `${arcLength.toFixed(2)} ${(circumference - arcLength).toFixed(2)}`,
      transform: `rotate(${startAngle} ${CENTER} ${CENTER})`,
    }));
  }

  function appendLongFieldStripes(group, record, color) {
    const random = record.random;
    const stripeCount = Math.round(12 + random() * 24);
    const startAngle = random() * 360;
    const arcSpan = 24 + random() * 48;
    const stripeHeight = 5 + random() * 9;

    for (let index = 0; index < stripeCount; index += 1) {
      const ratio = stripeCount <= 1 ? 0 : index / (stripeCount - 1);
      const angle = startAngle + arcSpan * ratio;
      const innerRadius = record.radius - 1.5;
      const outerRadius = Math.min(
        INNER_DECORATION_MAX_RADIUS,
        record.radius + stripeHeight * (0.55 + random() * 0.45)
      );
      const inner = polarPoint(innerRadius, angle);
      const outer = polarPoint(outerRadius, angle);

      group.appendChild(createSvgElement("line", {
        x1: inner.x,
        y1: inner.y,
        x2: outer.x,
        y2: outer.y,
        stroke: color,
        "stroke-width": 0.75 + random() * 0.8,
        "stroke-opacity": 0.52 + random() * 0.34,
        "stroke-linecap": "round",
      }));
    }
  }

  function appendRuntimeChangeMarker(group, record, color) {
    const marker = record && record.changeMarker;

    if (!marker) {
      return;
    }

    const ratio =
      marker.status === "new"
        ? 1
        : clamp(marker.ratio, 0, 1);
    const isNew =
      marker.status === "new";
    const markerRadius = 6.2;
    const markerStrokeWidth = isNew ? 0 : 1.05;
    const markerFillGap = 0.7;
    const markerMaxInnerRadius = Math.max(
      0,
      markerRadius - markerStrokeWidth * 0.5 - markerFillGap
    );
    const markerInnerRadius = isNew
      ? markerRadius
      : Math.max(
        0,
        markerMaxInnerRadius * Math.sqrt(ratio)
      );
    const angle =
      (hashString(record.changeMarkerIdentity) % 36000) / 100;
    const point =
      polarPoint(record.radius, angle);
    const markerGroup = createSvgElement("g", {
      class:
        `jin-avatar-runtime-change-marker is-${isNew ? "new" : "changed"}`,
      "pointer-events": "none",
    });

    if (!isNew) {
      markerGroup.appendChild(createSvgElement("circle", {
        class: "jin-avatar-runtime-change-marker-ring",
        cx: point.x,
        cy: point.y,
        r: markerRadius,
        fill: "none",
        stroke: color,
        "stroke-width": markerStrokeWidth,
        "stroke-opacity": 0.92,
      }));
    }

    if (markerInnerRadius > 0.01) {
      markerGroup.appendChild(createSvgElement("circle", {
        class: "jin-avatar-runtime-change-marker-fill",
        cx: point.x,
        cy: point.y,
        r: markerInnerRadius.toFixed(2),
        fill: color,
        "fill-opacity": 0.94,
        stroke: "none",
      }));
    }

    group.appendChild(markerGroup);
  }

  function appendOrbit(svg, record, records, overallColor, diffPercent, options = {}) {
    const random = record.random;
    const ownBaseColor = getPaletteColor(record.text, overallColor);
    const neighbourAggressive = getNeighbourAggressiveInfluence(record, records);
    let ringColor = record.aggressive
      ? record.aggressive.color
      : ownBaseColor;

    if (!record.aggressive && neighbourAggressive) {
      ringColor = mixColors(
        ringColor,
        neighbourAggressive.color,
        neighbourAggressive.strength
      );
    }

    const ringRgb = hexToRgb(ringColor);
    const baseSpeed = 11 + random() * 36;
    const effectiveSpeed = baseSpeed * (diffPercent / 100);
    const duration = effectiveSpeed > 0.05 ? 360 / effectiveSpeed : 9999;
    const direction = random() > 0.5 ? "normal" : "reverse";
    const rotationKey = record.id
      ? `runtime:id:${record.id}`
      : record.activeMemoryId
        ? `runtime:active:${record.activeMemoryId}`
        : `runtime:index:${record.index}`;
    const orbitGroup = createSvgElement("g", {
      class: random() > 0.46 ? "jin-avatar-orbit" : "jin-avatar-counter-orbit",
      "data-avatar-rotation-key": rotationKey,
      style: [
        `--jin-avatar-duration:${duration.toFixed(2)}s`,
        `--jin-avatar-direction:${direction}`,
        `--jin-avatar-play-state:${effectiveSpeed > 0.05 ? "running" : "paused"}`,
        `--jin-avatar-cited-glow-near:rgba(${ringRgb.r},${ringRgb.g},${ringRgb.b},0.88)`,
        `--jin-avatar-cited-glow-mid:rgba(${ringRgb.r},${ringRgb.g},${ringRgb.b},0.54)`,
        `--jin-avatar-cited-glow-far:rgba(${ringRgb.r},${ringRgb.g},${ringRgb.b},0.24)`,
        `--jin-avatar-runtime-glow-near:rgba(${ringRgb.r},${ringRgb.g},${ringRgb.b},1)`,
        `--jin-avatar-runtime-glow-mid:rgba(${ringRgb.r},${ringRgb.g},${ringRgb.b},0.81)`,
        `--jin-avatar-runtime-glow-far:rgba(${ringRgb.r},${ringRgb.g},${ringRgb.b},0.36)`,
      ].join(";"),
    });

    if (record.changeMarker) {
      orbitGroup.classList.add("has-runtime-change-marker");
    }

    const shouldAnimate = Boolean(options.animate);
    const entryGroup = createSvgElement("g", shouldAnimate ? {
      class: "jin-avatar-orbit-entry",
      style: `--jin-avatar-entry-delay:${Number(options.entryDelay || 0).toFixed(3)}s`,
    } : {
      class: "jin-avatar-orbit-entry",
    });

    const reasoningMotion = createReasoningMotionLayer(
      `runtime-orbit:${record.index}:${record.key}`,
      0.88
    );

    orbitGroup.dataset.runtimeLineIndex = String(record.index);
    if (record.avatarMemoryHoverId) {
      orbitGroup.dataset.avatarMemoryHoverId =
        record.avatarMemoryHoverId;
    }
    setAvatarNodeState(
      orbitGroup,
      {
        runtimeLineKey:
          normalizeRuntimeCitationIdentity(record.key),
        runtimeLineText:
          normalizeRuntimeCitationIdentity(record.text),
      }
    );
    if (record.activeMemoryId) {
      orbitGroup.dataset.activeMemoryId =
        String(record.activeMemoryId).trim().toLowerCase();
    }
    setAvatarMemoryReferenceAliases(
      orbitGroup,
      record.referenceAliases
    );

    const strokeWidth = 0.48 + random() * 2.25;
    const circumference = 2 * Math.PI * record.radius;
    const dashLength = 1 + random() * Math.max(2, record.radius * 0.14);
    const gapLength = 2 + random() * Math.max(4, record.radius * 0.18);

    orbitGroup.appendChild(createSvgElement("circle", {
      cx: CENTER,
      cy: CENTER,
      r: record.radius,
      fill: "none",
      stroke: ringColor,
      "stroke-width": Math.max(0.45, strokeWidth * 0.42),
      "stroke-opacity": 0.13 + random() * 0.17,
      "stroke-dasharray": `${dashLength.toFixed(2)} ${gapLength.toFixed(2)}`,
      "stroke-linecap": "round",
    }));

    const arcCount = 1 + Math.floor(random() * 4);

    for (let index = 0; index < arcCount; index += 1) {
      appendArcCircle(
        orbitGroup,
        record.radius + (random() - 0.5) * 1.8,
        index === arcCount - 1 && random() > 0.68
          ? mixColors(ringColor, ACCENT_RING_COLOR, 0.44)
          : ringColor,
        Math.max(0.55, strokeWidth * (0.62 + random() * 0.64)),
        0.44 + random() * 0.42,
        random() * 360,
        12 + random() * 82
      );
    }

    if (/[!?]/.test(String(record.value || ""))) {
      appendLongFieldStripes(orbitGroup, record, ringColor);
    }

    appendRuntimeChangeMarker(
      orbitGroup,
      record,
      ringColor
    );

    reasoningMotion.content.appendChild(orbitGroup);
    entryGroup.appendChild(reasoningMotion.layer);
    svg.appendChild(entryGroup);
  }

  function appendCenter(svg, overallColor, currentCenterColor) {
    const center = createSvgElement("g", {
      class: "jin-avatar-center",
      "pointer-events": "none",
    });

    [24, 31, 39].forEach((radius, index) => {
      center.appendChild(createSvgElement("circle", {
        class: "jin-avatar-center-ring",
        cx: CENTER,
        cy: CENTER,
        r: radius,
        fill: "none",
        stroke: index === 1 ? "#f4f7f5" : overallColor,
        "stroke-width": index === 1 ? 0.52 : 0.75,
        "stroke-opacity": index === 1 ? 0.16 : 0.20,
        "stroke-dasharray": index === 2 ? "22 7 4 9" : null,
      }));
    });

    center.appendChild(createSvgElement("circle", {
      class: "jin-avatar-center-glow-fill",
      cx: CENTER,
      cy: CENTER,
      r: 58,
      fill: "url(#jin-avatar-center-glow)",
    }));

    center.appendChild(createSvgElement("circle", {
      class: "jin-avatar-center-soft",
      cx: CENTER,
      cy: CENTER,
      r: 8,
      fill: currentCenterColor,
      "fill-opacity": 0.34,
    }));

    center.appendChild(createSvgElement("circle", {
      class: "jin-avatar-center-core",
      cx: CENTER,
      cy: CENTER,
      r: 4.2,
      fill: mixColors(currentCenterColor, "#ffffff", 0.14),
      "fill-opacity": 0.86,
    }));

    center.appendChild(createSvgElement("circle", {
      class: "jin-avatar-center-point",
      cx: CENTER,
      cy: CENTER,
      r: 2.1,
      fill: currentCenterColor,
      "fill-opacity": 1,
    }));

    svg.appendChild(center);
  }

  let currentRenderedSnapshotIndex = null;
  const activeThinkRuntimeCitationSources = new Map();
  let memoryRowAvatarHoverState = null;
  let delayedMemoryReportActiveState = null;

  function normalizeAvatarMemoryFocusDetail(detail) {
    if (!detail || detail.active !== true) {
      return null;
    }

    const avatarMemoryHoverId =
      String(detail.avatarMemoryHoverId || "").trim();

    return avatarMemoryHoverId
      ? { avatarMemoryHoverId }
      : null;
  }

  function normalizeMemoryRowAvatarHoverDetail(detail) {
    return normalizeAvatarMemoryFocusDetail(detail);
  }

  function getActiveAvatarMemoryHoverIds() {
    return new Set([
      memoryRowAvatarHoverState
        ? memoryRowAvatarHoverState.avatarMemoryHoverId
        : "",
      delayedMemoryReportActiveState
        ? delayedMemoryReportActiveState.avatarMemoryHoverId
        : "",
    ].filter(Boolean));
  }

  function getAvatarDashFactIdSet(node, stateKey) {
    const state = getAvatarNodeState(node);

    return new Set(
      normalizeL4FactIds(
        state
          ? state[stateKey]
          : []
      )
    );
  }

  function getFocusedMemoryDashNodes(svg) {
    const hoverIds =
      getActiveAvatarMemoryHoverIds();

    if (!hoverIds.size) {
      return [];
    }

    return Array.from(
      svg.querySelectorAll(".jin-avatar-memory-dash")
    ).filter((node) => (
      hoverIds.has(node.dataset.avatarMemoryHoverId)
    ));
  }

  function collectDelayedMemoryLinkedL4FactIds(svg) {
    const factIds = new Set();

    Array.from(
      svg.querySelectorAll(
        ".jin-avatar-memory-dash-delayed.is-memory-pinned, "
        + ".jin-avatar-memory-dash-delayed.is-context-loaded"
      )
    ).forEach((node) => {
      getAvatarDashFactIdSet(
        node,
        "delayedMemoryFactIds"
      ).forEach(factId => factIds.add(factId));
    });

    getFocusedMemoryDashNodes(svg)
      .filter(node => (
        node.classList.contains(
          "jin-avatar-memory-dash-delayed"
        )
      ))
      .forEach((node) => {
        getAvatarDashFactIdSet(
          node,
          "delayedMemoryFactIds"
        ).forEach(factId => factIds.add(factId));
      });

    return factIds;
  }

  function collectHoveredL4FactIds(svg) {
    const factIds = new Set();

    getFocusedMemoryDashNodes(svg)
      .filter(node => (
        node.classList.contains(
          "jin-avatar-memory-dash-l4"
        )
      ))
      .forEach((node) => {
        getAvatarDashFactIdSet(
          node,
          "l4FactIds"
        ).forEach(factId => factIds.add(factId));
      });

    return factIds;
  }

  function getSecondaryLinkedDelayedMemoryReportIds() {
    const records = getDelayedMemoryAvatarRecords();
    const linkedReportIds = new Set();

    // Pin and explicit load are both direct DM states. Either one may expose
    // a softer cross-report anchor signal, but that secondary target must not
    // inherit the source report's direct L4 emphasis.
    records
      .filter(record => Boolean(
        record && (record.pinned || record.loaded)
      ))
      .forEach((sourceRecord) => {
        const hiddenFactIds = new Set(sourceRecord.factIds);

        sourceRecord.anchorFactIds.forEach((factId) => {
          hiddenFactIds.delete(factId);
        });

        if (!hiddenFactIds.size) {
          return;
        }

        records.forEach((targetRecord) => {
          if (
            !targetRecord
            || targetRecord.id === sourceRecord.id
          ) {
            return;
          }

          if (
            l4FactIdSetsIntersect(
              new Set(targetRecord.anchorFactIds),
              hiddenFactIds
            )
          ) {
            linkedReportIds.add(targetRecord.id);
          }
        });
      });

    return linkedReportIds;
  }

  function applyDelayedMemoryFactLinkGlow() {
    const svg = avatarRoot.querySelector("svg");

    if (!svg) {
      return;
    }

    const delayedLinkedFactIds =
      collectDelayedMemoryLinkedL4FactIds(svg);
    const hoveredL4FactIds =
      collectHoveredL4FactIds(svg);
    const secondaryLinkedReportIds =
      getSecondaryLinkedDelayedMemoryReportIds();

    Array.from(
      svg.querySelectorAll(".jin-avatar-memory-dash-l4")
    ).forEach((node) => {
      node.classList.toggle(
        "is-delayed-memory-linked-hit",
        l4FactIdSetsIntersect(
          getAvatarDashFactIdSet(node, "l4FactIds"),
          delayedLinkedFactIds
        )
      );
    });

    Array.from(
      svg.querySelectorAll(".jin-avatar-memory-dash-delayed")
    ).forEach((node) => {
      node.classList.toggle(
        "is-delayed-memory-linked-hit",
        l4FactIdSetsIntersect(
          getAvatarDashFactIdSet(
            node,
            "delayedMemoryAnchorFactIds"
          ),
          hoveredL4FactIds
        )
      );
      const delayedMemoryId =
        String(node.dataset.delayedMemoryId || "")
          .trim()
          .toLowerCase();

      node.classList.toggle(
        "is-delayed-memory-secondary-linked",
        secondaryLinkedReportIds.has(
          delayedMemoryId
        )
      );
      node.classList.remove(
        "is-delayed-memory-secondary-source"
      );
    });

  }


  function collectFocusedDelayedMemoryIds(svg) {
    const reportIds = new Set();

    getFocusedMemoryDashNodes(svg)
      .filter((node) => (
        node.classList.contains(
          "jin-avatar-memory-dash-delayed"
        )
      ))
      .forEach((node) => {
        normalizeShortRuntimeIds(
          node.dataset.delayedMemoryId
        ).forEach((reportId) => reportIds.add(reportId));
      });

    return reportIds;
  }

  function applyDelayedMemoryFileLinkGlow() {
    const svg = avatarRoot.querySelector("svg");

    if (!svg) {
      return;
    }

    const focusedDelayedIds =
      collectFocusedDelayedMemoryIds(svg);

    Array.from(
      svg.querySelectorAll(".jin-avatar-file-dot")
    ).forEach((node) => {
      const state = getAvatarNodeState(node);

      node.classList.toggle(
        "is-delayed-memory-linked-hit",
        shortRuntimeIdSetsIntersect(
          new Set(
            normalizeShortRuntimeIds(
              state && state.linkedDelayedMemoryIds
            )
          ),
          focusedDelayedIds
        )
      );
    });
  }

  function applyMemoryRowAvatarHoverGlow() {
    const svg = avatarRoot.querySelector("svg");

    if (!svg) {
      return;
    }

    const rowHoverIds = new Set([
      memoryRowAvatarHoverState
        ? memoryRowAvatarHoverState.avatarMemoryHoverId
        : "",
    ].filter(Boolean));
    const modalActiveIds = new Set([
      delayedMemoryReportActiveState
        ? delayedMemoryReportActiveState.avatarMemoryHoverId
        : "",
    ].filter(Boolean));
    const activeHoverIds =
      getActiveAvatarMemoryHoverIds();

    getAvatarPayloadNodes(svg).forEach((node) => {
      const hoverId =
        String(node.dataset.avatarMemoryHoverId || "");
      const matched = Boolean(
        hoverId
        && activeHoverIds.has(hoverId)
      );
      const rowHovered = Boolean(
        hoverId
        && rowHoverIds.has(hoverId)
      );
      const modalActive = Boolean(
        hoverId
        && modalActiveIds.has(hoverId)
      );

      node.classList.toggle(
        "is-memory-hover-hit",
        matched && rowHovered
      );
      node.classList.toggle(
        "is-memory-modal-active",
        matched && modalActive
      );
    });

    applyDelayedMemoryFactLinkGlow();
    applyDelayedMemoryFileLinkGlow();
  }

  function normalizeThinkRuntimeCitationHighlightDetail(detail) {
    if (!detail || detail.active !== true) {
      return null;
    }

    const sourceId =
      String(detail.sourceId || "unknown-think");
    const activeMemoryIds =
      new Set(
        normalizeShortRuntimeIds(
          detail.activeMemoryIds || []
        )
      );
    const activeMemoryKeys =
      new Set(
        (Array.isArray(detail.activeMemoryKeys) ? detail.activeMemoryKeys : [])
          .map(normalizeRuntimeCitationIdentity)
          .filter(key => /^active_memory(?:_\d+)?$/.test(key))
      );
    const lineIdentities =
      new Set(
        (Array.isArray(detail.lineIdentities) ? detail.lineIdentities : [])
          .map(normalizeRuntimeCitationIdentity)
          .filter(Boolean)
      );
    const lineKeys =
      new Set(
        (Array.isArray(detail.lineKeys) ? detail.lineKeys : [])
          .map(normalizeRuntimeCitationIdentity)
          .filter(Boolean)
      );
    const lineTexts =
      new Set(
        (Array.isArray(detail.lineTexts) ? detail.lineTexts : [])
          .map(normalizeRuntimeCitationIdentity)
          .filter(Boolean)
      );

    if (
      !activeMemoryIds.size
      && !activeMemoryKeys.size
      && !lineIdentities.size
      && !lineKeys.size
      && !lineTexts.size
    ) {
      return null;
    }

    return {
      sourceId,
      activeMemoryIds,
      activeMemoryKeys,
      lineIdentities,
      lineKeys,
      lineTexts,
    };
  }

  function getActiveThinkRuntimeCitationIdentitySets() {
    const activeMemoryIds = new Set();
    const activeMemoryKeys = new Set();
    const lineIdentities = new Set();
    const lineKeys = new Set();
    const lineTexts = new Set();

    activeThinkRuntimeCitationSources.forEach((state) => {
      state.activeMemoryIds.forEach(id => activeMemoryIds.add(id));
      state.activeMemoryKeys.forEach(key => activeMemoryKeys.add(key));
      state.lineIdentities.forEach(identity => lineIdentities.add(identity));
      state.lineKeys.forEach(key => lineKeys.add(key));
      state.lineTexts.forEach(line => lineTexts.add(line));
    });

    return {
      activeMemoryIds,
      activeMemoryKeys,
      lineIdentities,
      lineKeys,
      lineTexts,
    };
  }

  function getAvatarPayloadNodes(svg) {
    if (!svg) {
      return [];
    }

    return Array.from(
      svg.querySelectorAll(
        ".jin-avatar-orbit[data-runtime-line-index], "
        + ".jin-avatar-counter-orbit[data-runtime-line-index], "
        + ".jin-avatar-memory-dash, "
        + ".jin-avatar-file-dot"
      )
    );
  }

  function applyThinkRuntimeCitationGlow() {
    const svg = avatarRoot.querySelector("svg");

    if (!svg) {
      return;
    }

    const activeIdentities =
      getActiveThinkRuntimeCitationIdentitySets();

    const citationNodes = getAvatarPayloadNodes(svg);
    const lineKeyUsage = new Map();

    citationNodes.forEach((node) => {
      const state = getAvatarNodeState(node);
      const lineKey =
        normalizeRuntimeCitationIdentity(
          state && state.runtimeLineKey
        );

      if (!lineKey) {
        return;
      }

      lineKeyUsage.set(
        lineKey,
        Number(lineKeyUsage.get(lineKey) || 0) + 1
      );
    });

    citationNodes.forEach((orbitGroup) => {
      const state = getAvatarNodeState(orbitGroup);
      const lineIdentity =
        normalizeRuntimeCitationIdentity(
          state && state.runtimeLineIdentity
        );
      const activeMemoryId =
        normalizeShortRuntimeIds(
          orbitGroup.dataset.activeMemoryId
        )[0] || "";
      const lineKey =
        normalizeRuntimeCitationIdentity(
          state && state.runtimeLineKey
        );
      const lineText =
        normalizeRuntimeCitationIdentity(
          state && state.runtimeLineText
        );
      const exactTextMatch = Boolean(
        lineText
        && activeIdentities.lineTexts.has(lineText)
      );
      const uniqueKeyMatch = Boolean(
        lineKey
        && Number(lineKeyUsage.get(lineKey) || 0) === 1
        && activeIdentities.lineKeys.has(lineKey)
      );
      const activeMemoryNode =
        orbitGroup.classList.contains(
          "jin-avatar-memory-dash-active"
        );
      const cited =
        activeMemoryNode
          ? Boolean(
              activeMemoryId
                ? activeIdentities.activeMemoryIds.has(activeMemoryId)
                : (
                  lineKey
                  && activeIdentities.activeMemoryKeys.has(lineKey)
                )
            )
          : lineIdentity
            ? activeIdentities.lineIdentities.has(lineIdentity)
            : (exactTextMatch || uniqueKeyMatch);

      orbitGroup.classList.toggle(
        "is-runtime-cited",
        Boolean(cited)
      );
    });

  }

  function getActiveMemoryReferenceText() {
    return memoryReferenceHighlightState.persistentText || "";
  }

  function getAvatarMemoryReferenceTargetIdentity(node) {
    if (!node || !node.dataset) {
      return "";
    }

    const state = getAvatarNodeState(node);

    const activeMemoryId =
      normalizeShortRuntimeIds(
        node.dataset.activeMemoryId
      )[0] || "";

    if (activeMemoryId) {
      return `active:${activeMemoryId}`;
    }

    const delayedMemoryId =
      normalizeShortRuntimeIds(
        node.dataset.delayedMemoryId
      )[0] || "";

    if (delayedMemoryId) {
      return `delayed:${delayedMemoryId}`;
    }

    const l4FactId =
      String(node.dataset.l4FactId || "")
        .trim()
        .toUpperCase();

    if (l4FactId) {
      return `l4:${l4FactId}`;
    }

    const fileId =
      normalizeShortRuntimeIds(
        node.dataset.fileId
      )[0] || "";

    if (fileId) {
      return `file:${fileId}`;
    }

    const lineIdentity =
      normalizeRuntimeCitationIdentity(
        state && state.runtimeLineIdentity
      );

    if (lineIdentity) {
      return `line:${lineIdentity}`;
    }

    return [
      state && state.runtimeLineKey,
      state && state.runtimeLineText,
      node.dataset.avatarMemoryHoverId,
    ]
      .map(normalizeRuntimeCitationIdentity)
      .filter(Boolean)
      .join("|");
  }

  function buildAvatarMemoryReferenceAliasUsage(nodes) {
    const targetsByAlias = new Map();

    nodes.forEach((node) => {
      const targetIdentity =
        getAvatarMemoryReferenceTargetIdentity(node);

      if (!targetIdentity) {
        return;
      }

      getAvatarMemoryReferenceAliases(node).forEach((alias) => {
        const identity =
          normalizeRuntimeCitationIdentity(alias);

        if (!identity) {
          return;
        }

        const targets =
          targetsByAlias.get(identity) || new Set();

        targets.add(targetIdentity);
        targetsByAlias.set(identity, targets);
      });
    });

    const usage = new Map();
    targetsByAlias.forEach((targets, alias) => {
      usage.set(alias, targets.size);
    });

    return usage;
  }

  function applyMemoryReferenceGlow() {
    const svg = avatarRoot.querySelector("svg");

    if (!svg) {
      return;
    }

    const sourceText = getActiveMemoryReferenceText();
    const recordNodes = getAvatarPayloadNodes(svg);
    const aliasUsage =
      buildAvatarMemoryReferenceAliasUsage(recordNodes);
    const canonicalActiveMemoryIds = new Set(
      Array.from(
        svg.querySelectorAll(
          ".jin-avatar-memory-dash-active[data-active-memory-id]"
        )
      )
        .map(node => normalizeShortRuntimeIds(node.dataset.activeMemoryId)[0] || "")
        .filter(Boolean)
    );

    recordNodes.forEach((recordNode) => {
        const activeMemoryId =
          normalizeShortRuntimeIds(
            recordNode.dataset.activeMemoryId
          )[0] || "";
        const mirroredActiveRuntimeNode = Boolean(
          activeMemoryId
          && canonicalActiveMemoryIds.has(activeMemoryId)
          && !recordNode.classList.contains(
            "jin-avatar-memory-dash-active"
          )
        );
        // L4 is citation-gated: ambient/persistent text must not turn a
        // durable fact into a visual focus merely because its value shares
        // wording with the latest answer. Explicit reasoning citations still
        // use the structured THINK_RUNTIME_CITATION_HIGHLIGHT_EVENT path.
        const persistentReferenceEligible =
          !recordNode.classList.contains("jin-avatar-memory-dash-l4");
        const matched = Boolean(
          persistentReferenceEligible
          && !mirroredActiveRuntimeNode
          && sourceText
          && getAvatarMemoryReferenceAliases(recordNode)
            .some(alias => (
              Number(
                aliasUsage.get(
                  normalizeRuntimeCitationIdentity(alias)
                ) || 0
              ) === 1
              && containsMemoryReference(sourceText, alias)
            ))
        );

        recordNode.classList.toggle(
          "is-memory-reference-hit",
          matched
        );
      });

  }

  function handleMemoryReferenceHighlight(event) {
    const detail = event && event.detail || {};

    if (detail.source !== "persistent") {
      return;
    }

    memoryReferenceHighlightState.persistentText =
      detail.active === false
        ? ""
        : String(detail.text || "");

    // The newest JIN response replaces the previous turn's citation glow.
    activeThinkRuntimeCitationSources.clear();

    applyMemoryReferenceGlow();
    applyThinkRuntimeCitationGlow();
  }
  function buildRuntimeRenderSignature(
    snapshot,
    lines,
    snapshotIndex = null,
    seedNonce = 0
  ) {
    const normalizedSnapshotIndex =
      Number.isInteger(Number(snapshotIndex))
        ? Number(snapshotIndex)
        : "";

    return [
      snapshot && snapshot.runtime_memory_id,
      snapshot && snapshot.index,
      snapshot && snapshot.total_diff,
      snapshotHasRuntimeChange(snapshot) ? "changed" : "stable",
      normalizedSnapshotIndex,
      lines.map(line => [
        line.key,
        line.value,
        line.status,
        line.keyStatus,
        line.valueStatus,
        line.changeRatio,
      ].join("␟")).join("␞"),
      seedNonce,
    ].join("␝");
  }

  function buildAuxiliaryRenderSignatures(
    activeMemoryRecords = [],
    delayedMemoryRecords = [],
    l4MemoryRecords = [],
    fileRecords = []
  ) {
    return {
      active: activeMemoryRecords
        .map(record => record.text)
        .join("␞"),
      delayed: delayedMemoryRecords.map(record => [
        record.id,
        record.title,
        record.summary,
        record.pinned,
        record.loaded,
        record.anchorFactIds.join(","),
        record.factIds.join(","),
        record.linkedFactIds.join(","),
      ].join("␟")).join("␞"),
      l4: l4MemoryRecords.map(record => [
        record.id,
        record.key,
        record.value,
        record.archived ? "archived" : "visible",
        record.l4FactIds.join(","),
      ].join("␟")).join("␞"),
      files: fileRecords.map(record => [
        record.id,
        record.name,
        record.pinned ? "pinned" : "idle",
        record.contextLoaded ? "context" : "stored",
        record.linkedReportIds.join(","),
      ].join("␟")).join("␞"),
    };
  }

  let lastRuntimeRenderSignature = null;
  let lastAuxiliaryRenderSignatures = null;
  let avatarRefreshNonce = 0;
  let suppressedMemoryLayer = null;

  function auxiliaryRenderSignaturesEqual(first, second) {
    return Boolean(first && second)
      && first.active === second.active
      && first.delayed === second.delayed
      && first.l4 === second.l4
      && first.files === second.files;
  }

  function syncAuxiliaryAvatarLayers(
    nextSignatures,
    previousSignatures
  ) {
    let synced = true;

    const syncMemoryLayer = (key, kind) => {
      if (
        previousSignatures
        && nextSignatures[key] === previousSignatures[key]
      ) {
        return;
      }

      if (!syncMemorySignalLayer(kind, { applyGlows: false })) {
        synced = false;
      }
    };

    syncMemoryLayer("active", "active");
    syncMemoryLayer("delayed", "delayed");
    syncMemoryLayer("l4", "l4");

    if (
      !previousSignatures
      || nextSignatures.files !== previousSignatures.files
    ) {
      if (!syncFilesState({ applyGlows: false })) {
        synced = false;
      }
    }

    if (synced) {
      applyAvatarReactiveGlows();
    }

    return synced;
  }

  function keepReasoningMotionApplied() {
    if (!reasoningMotionActive) {
      return;
    }

    if (avatarShell) {
      avatarShell.classList.add(REASONING_MOTION_CLASS);
      avatarShell.classList.toggle(
        REASONING_WHISPER_CLASS,
        reasoningWhisperActive
      );
      avatarShell.dataset.motionMode = "reasoning";
    }

    // Preserve the in-flight reasoning deceleration across avatar sync/rebuilds.
    // Forcing rate 0 here can race the active ramp and cause a stop/resume jerk.
  }

  function renderAvatar(snapshot, options = {}) {
    const sourceLines = getSnapshotLines(snapshot);
    const lines = sourceLines.length ? sourceLines : [];
    const seedNonce =
      options.seedNonce !== undefined
        ? options.seedNonce
        : avatarRefreshNonce;
    const snapshotIndex =
      Number.isInteger(Number(options.snapshotIndex))
        ? Number(options.snapshotIndex)
        : null;
    const activeMemoryRecords = getActiveMemoryAvatarRecords();
    const delayedMemoryRecords = getDelayedMemoryAvatarRecords();
    const l4MemoryRecords = getL4MemoryAvatarRecords();
    const fileRecords = getPersistentFileAvatarRecords();
    const runtimeSignature =
      buildRuntimeRenderSignature(
        snapshot,
        lines,
        snapshotIndex,
        seedNonce
      );
    const auxiliarySignatures =
      buildAuxiliaryRenderSignatures(
        activeMemoryRecords,
        delayedMemoryRecords,
        l4MemoryRecords,
        fileRecords
      );
    const existingSvg =
      avatarRoot.querySelector("svg");
    const runtimeGeometryUnchanged =
      Boolean(existingSvg)
      && options.forceRebuild !== true
      && runtimeSignature === lastRuntimeRenderSignature;

    if (runtimeGeometryUnchanged) {
      let auxiliarySynced = true;

      if (
        !auxiliaryRenderSignaturesEqual(
          auxiliarySignatures,
          lastAuxiliaryRenderSignatures
        )
      ) {
        auxiliarySynced =
          syncAuxiliaryAvatarLayers(
            auxiliarySignatures,
            lastAuxiliaryRenderSignatures
          );
      } else {
        applyAvatarReactiveGlows();
      }

      if (auxiliarySynced) {
        keepReasoningMotionApplied();
        lastAuxiliaryRenderSignatures = auxiliarySignatures;
        return;
      }
    }

    const previousRotationPhases =
      captureAvatarRotationPhases();
    const seed = [
      snapshot && snapshot.runtime_memory_id,
      snapshot && snapshot.index,
      lines.map(line => line.text).join("|"),
      seedNonce,
    ].join(":");
    const random = createRandom(seed || "jin-avatar");
    const changeMarkers =
      resolveRuntimeChangeMarkers(
        snapshot,
        snapshotIndex
      );
    const records =
      lines.length
        ? computeRingRecords(
          lines,
          seed || "jin-avatar",
          changeMarkers
        )
        : [];
    const overallColor = lines.length
      ? computeOverallColor(lines, records)
      : DEFAULT_RING_COLOR;
    const diffPercent = lines.length
      ? getSnapshotDiff(snapshot, lines)
      : 0;
    const shouldAnimate =
      !reasoningMotionActive
      && Boolean(lastRuntimeRenderSignature)
      && runtimeSignature !== lastRuntimeRenderSignature;

    const svg = createSvgElement("svg", {
      viewBox: "0 0 360 360",
      role: "img",
      "aria-label": "Dynamic JIN runtime avatar",
      preserveAspectRatio: "xMidYMid meet",
    });

    appendDefs(svg, overallColor, centerColor);
    appendStaticScaffold(svg, overallColor, centerColor, diffPercent, random);

    records.forEach((record, index) => {
      appendOrbit(svg, record, records, overallColor, diffPercent, {
        animate: shouldAnimate,
        entryDelay: Math.min(0.32, index * 0.045),
      });
    });

    appendMemorySignalRings(
      svg,
      activeMemoryRecords,
      delayedMemoryRecords,
      l4MemoryRecords,
      overallColor
    );
    appendFileRing(
      svg,
      fileRecords
    );

    appendCenter(svg, overallColor, centerColor);

    invalidateAvatarRotationAnimationsCache();
    avatarRoot.replaceChildren(svg);
    currentRenderedSnapshotIndex = snapshotIndex;
    avatarRoot.dataset.diff = String(Math.round(diffPercent));
    if (currentRenderedSnapshotIndex !== null) {
      avatarRoot.dataset.snapshotIndex = String(currentRenderedSnapshotIndex);
    } else {
      delete avatarRoot.dataset.snapshotIndex;
    }
    avatarRoot.style.setProperty("--jin-avatar-overall-color", overallColor);
    avatarRoot.style.setProperty("--jin-avatar-center-color", centerColor);
    applyAvatarReactiveGlows();
    restoreAvatarRotationPhases(previousRotationPhases);
    syncAvatarRotationPlaybackRate();
    keepReasoningMotionApplied();

    lastRuntimeRenderSignature = runtimeSignature;
    lastAuxiliaryRenderSignatures = auxiliarySignatures;
  }

  function notifyRoomStateChanged(options = {}) {
    window.dispatchEvent(
      new CustomEvent(
        "jin:avatar-room-state-changed",
        {
          detail: {
            immediate: options.immediate === true,
          },
        }
      )
    );
  }

  function getCenterColor() {
    return centerColor;
  }

  function getMemoryLayersHidden() {
    return avatarRoot.classList.contains(
      MEMORY_LAYERS_HIDDEN_CLASS
    );
  }

  function applyCenterColor(color, options = {}) {
    const svg = avatarRoot.querySelector("svg");
    const overallColor =
      avatarRoot.style.getPropertyValue("--jin-avatar-overall-color").trim()
      || DEFAULT_RING_COLOR;

    centerColor = color;
    avatarRoot.style.setProperty("--jin-avatar-center-color", centerColor);

    const sceneColorIntensity = clamp(JIN_SCENE_COLOR_INTENSITY, 0, 1);
    document.documentElement.style.setProperty("--jin-color", centerColor);
    document.documentElement.style.setProperty(
      "--scene-base-color",
      mixColors("#09090b", centerColor, sceneColorIntensity)
    );
    document.documentElement.style.setProperty(
      "--scene-jin-tint-alpha",
      String(0.12 * sceneColorIntensity)
    );

    if (options.persist !== false) {
      notifyRoomStateChanged({ immediate: true });
    }

    if (!svg) {
      renderAvatar(getLatestSnapshot(), {
        seedNonce: avatarRefreshNonce,
        snapshotIndex: getLatestSnapshotIndex(),
      });
      return;
    }

    svg.querySelectorAll(".jin-avatar-center-glow-stop")
      .forEach(stop => stop.setAttribute("stop-color", centerColor));

    const soft = svg.querySelector(".jin-avatar-center-soft");
    if (soft) {
      soft.setAttribute(
        "fill",
        centerColor
      );
    }

    const core = svg.querySelector(".jin-avatar-center-core");
    if (core) {
      core.setAttribute(
        "fill",
        mixColors(centerColor, "#ffffff", 0.14)
      );
    }

    const point = svg.querySelector(".jin-avatar-center-point");
    if (point) {
      point.setAttribute("fill", centerColor);
    }
  }

  function prepareCenterColorTransition(durationMs) {
    const duration = Math.max(0, Number(durationMs) || 0);
    const rootStyle = document.documentElement.style;

    if (centerColorTransitionStyleTimer) {
      window.clearTimeout(centerColorTransitionStyleTimer);
      centerColorTransitionStyleTimer = null;
    }

    if (!duration) {
      avatarRoot.style.removeProperty(
        "--jin-avatar-center-color-transition-duration"
      );
      rootStyle.removeProperty(
        "--scene-jin-tint-transition-duration"
      );
      return 0;
    }

    const durationValue = `${duration}ms`;

    avatarRoot.style.setProperty(
      "--jin-avatar-center-color-transition-duration",
      durationValue
    );
    rootStyle.setProperty(
      "--scene-jin-tint-transition-duration",
      durationValue
    );

    // Commit the duration before changing either projection so avatar and
    // scene tint always share one transition.
    avatarRoot.getBoundingClientRect();

    centerColorTransitionStyleTimer = window.setTimeout(
      () => {
        avatarRoot.style.removeProperty(
          "--jin-avatar-center-color-transition-duration"
        );
        rootStyle.removeProperty(
          "--scene-jin-tint-transition-duration"
        );
        centerColorTransitionStyleTimer = null;
      },
      duration + CENTER_COLOR_TRANSITION_RESET_BUFFER_MS
    );

    return duration;
  }

  function setCenterColor(color, options = {}) {
    const normalizedColor = normalizeHexColor(color);
    const initialBootstrap = Boolean(
      options && options.initialBootstrap === true
    );
    const hasExplicitTransitionDuration = Boolean(
      options
      && Object.prototype.hasOwnProperty.call(
        options,
        "transitionDurationMs"
      )
    );
    const transitionDurationMs = hasExplicitTransitionDuration
      ? Math.max(
        0,
        Number(options.transitionDurationMs) || 0
      )
      : (
          initialBootstrap
          && initialBootstrapColorPending
            ? INITIAL_BOOTSTRAP_COLOR_TRANSITION_MS
            : DEFAULT_CENTER_COLOR_TRANSITION_MS
        );

    if (!normalizedColor) {
      return false;
    }

    if (initialBootstrap && initialBootstrapColorPending) {
      initialBootstrapColorPending = false;
    }

    if (normalizedColor === centerColor) {
      return true;
    }



    prepareCenterColorTransition(transitionDurationMs);
    applyCenterColor(normalizedColor, options);

    return true;
  }

  function syncMemoryLayersToggleLabel(hidden) {
    if (!memoryLayersToggle) {
      return;
    }

    const memoryLayersHidden =
      hidden === undefined
        ? avatarRoot.classList.contains(MEMORY_LAYERS_HIDDEN_CLASS)
        : Boolean(hidden);
    const label =
      memoryLayersHidden
        ? "show"
        : "hide";

    memoryLayersToggle.setAttribute("title", label);
    memoryLayersToggle.setAttribute("aria-label", label);
    memoryLayersToggle.setAttribute("alt", label);
    memoryLayersToggle.dataset.memoryLayersHidden =
      memoryLayersHidden ? "true" : "false";
  }

  function clearMemoryLayersDormantTimer() {
    if (!memoryLayersDormantTimer) {
      return;
    }

    clearTimeout(memoryLayersDormantTimer);
    memoryLayersDormantTimer = null;
  }

  function setMemoryLayersDormant(dormant) {
    const nextDormant = Boolean(dormant);
    const wasDormant = avatarRoot.classList.contains(
      MEMORY_LAYERS_DORMANT_CLASS
    );

    if (wasDormant !== nextDormant) {
      // Dormant mode removes CSS orbit animations with animation:none.
      // Showing the layers creates fresh Animation objects.
      invalidateAvatarRotationAnimationsCache();
    }

    avatarRoot.classList.toggle(
      MEMORY_LAYERS_DORMANT_CLASS,
      nextDormant
    );

    if (avatarShell) {
      avatarShell.classList.toggle(
        MEMORY_LAYERS_DORMANT_CLASS,
        nextDormant
      );
    }
  }

  function setMemoryLayersHidden(hidden) {
    const nextHidden = Boolean(hidden);

    clearMemoryLayersDormantTimer();

    if (!nextHidden) {
      // Recreate the visual layers while they are still fully transparent, then
      // let the existing opacity transitions handle the soft fade-in.
      setMemoryLayersDormant(false);
      avatarRoot.getBoundingClientRect();
      syncAvatarRotationPlaybackRate();
    }

    avatarRoot.classList.toggle(
      MEMORY_LAYERS_HIDDEN_CLASS,
      nextHidden
    );
    avatarRoot.dataset.memoryLayersHidden =
      nextHidden ? "true" : "false";

    if (avatarShell) {
      avatarShell.classList.toggle(
        MEMORY_LAYERS_HIDDEN_CLASS,
        nextHidden
      );
      avatarShell.dataset.memoryLayersHidden =
        nextHidden ? "true" : "false";
    }

    if (nextHidden) {
      memoryLayersDormantTimer = setTimeout(() => {
        memoryLayersDormantTimer = null;

        if (avatarRoot.classList.contains(MEMORY_LAYERS_HIDDEN_CLASS)) {
          setMemoryLayersDormant(true);
        }
      }, MEMORY_LAYERS_FADE_MS);
    }

    syncMemoryLayersToggleLabel(nextHidden);
    notifyRoomStateChanged();

    return nextHidden;
  }

  function toggleMemoryLayers() {
    return setMemoryLayersHidden(
      !avatarRoot.classList.contains(MEMORY_LAYERS_HIDDEN_CLASS)
    );
  }

  function reinitializeAvatar() {
    avatarRefreshNonce += 1;
    snapshotRenderSequence += 1;

    if (snapshotRenderTimer) {
      clearTimeout(snapshotRenderTimer);
      snapshotRenderTimer = null;
    }

    memoryLayerSuppressedForSnapshot = false;
    suppressedMemoryLayer = null;
    syncMemoryLayer();
    renderAvatar(getLatestSnapshot(), {
      seedNonce: avatarRefreshNonce,
      snapshotIndex: getLatestSnapshotIndex(),
    });
  }

  function repaintAvatar() {
    renderAvatar(getLatestSnapshot(), {
      seedNonce: avatarRefreshNonce,
      snapshotIndex: getLatestSnapshotIndex(),
      forceRebuild: true,
    });
  }

  function getLatestSnapshot() {
    const runtime = window.JinRuntime && window.JinRuntime.runtime;

    if (!runtime || typeof runtime.getRuntimeMemorySnapshots !== "function") {
      return null;
    }

    const snapshots = runtime.getRuntimeMemorySnapshots();

    return Array.isArray(snapshots) && snapshots.length
      ? snapshots[snapshots.length - 1]
      : null;
  }

  function getLatestSnapshotIndex() {
    const runtime = window.JinRuntime && window.JinRuntime.runtime;

    if (!runtime || typeof runtime.getRuntimeMemorySnapshots !== "function") {
      return null;
    }

    const snapshots = runtime.getRuntimeMemorySnapshots();

    return Array.isArray(snapshots) && snapshots.length
      ? snapshots.length - 1
      : null;
  }

  let memoryLayerSuppressedForSnapshot = false;
  let snapshotRenderTimer = null;
  let snapshotRenderSequence = 0;

  function resolveMemoryLayer() {
    if (!memoryPanel) {
      return null;
    }

    const classes = memoryPanel.classList;

    if (
      classes.contains("memory-l3-updating")
      || classes.contains("memory-l3-pulse")
      || classes.contains("memory-l3-fading")
    ) {
      return "l3";
    }

    if (
      classes.contains("memory-l2-updating")
      || classes.contains("memory-l2-pulse")
      || classes.contains("memory-l2-fading")
    ) {
      return "l2";
    }

    if (
      classes.contains("memory-updating")
      || classes.contains("memory-pulse")
      || classes.contains("memory-fading")
    ) {
      return "l1";
    }

    return null;
  }

  function syncMemoryLayer() {
    const nextLayer = resolveMemoryLayer();

    if (memoryLayerSuppressedForSnapshot) {
      if (!nextLayer) {
        memoryLayerSuppressedForSnapshot = false;
        suppressedMemoryLayer = null;
        delete avatarRoot.dataset.memoryLayer;
        return;
      }

      if (suppressedMemoryLayer && nextLayer !== suppressedMemoryLayer) {
        memoryLayerSuppressedForSnapshot = false;
        suppressedMemoryLayer = null;
        avatarRoot.dataset.memoryLayer = nextLayer;
        return;
      }

      delete avatarRoot.dataset.memoryLayer;
      return;
    }

    if (nextLayer) {
      avatarRoot.dataset.memoryLayer = nextLayer;
      return;
    }

    delete avatarRoot.dataset.memoryLayer;
  }

  function scheduleSnapshotRender(snapshot, snapshotIndex = null) {
    const resolvedSnapshot = snapshot || getLatestSnapshot();
    const activeLayer = resolveMemoryLayer();

    snapshotRenderSequence += 1;
    const sequence = snapshotRenderSequence;

    if (snapshotRenderTimer) {
      clearTimeout(snapshotRenderTimer);
      snapshotRenderTimer = null;
    }

    if (!activeLayer) {
      memoryLayerSuppressedForSnapshot = false;
      suppressedMemoryLayer = null;
      renderAvatar(resolvedSnapshot, {
        snapshotIndex,
      });
      return;
    }

    // Keep request-layer state suppressed while the snapshot swaps, so
    // the panel glow remains the only L1/L2/L3 request accent around updates.
    memoryLayerSuppressedForSnapshot = true;
    suppressedMemoryLayer = activeLayer;
    syncMemoryLayer();

    snapshotRenderTimer = setTimeout(() => {
      snapshotRenderTimer = null;

      if (sequence !== snapshotRenderSequence) {
        return;
      }

      renderAvatar(resolvedSnapshot, {
        snapshotIndex,
      });
      syncMemoryLayer();
    }, SNAPSHOT_GLOW_CLEAR_DELAY_MS);
  }

  window.addEventListener(AVATAR_EVENT, (event) => {
    const detail = event && event.detail;
    const snapshot = detail && detail.snapshot;
    const snapshotIndex = Number.isInteger(Number(detail && detail.index))
      ? Number(detail.index)
      : null;
    scheduleSnapshotRender(snapshot, snapshotIndex);
  });

  window.addEventListener(
    MEMORY_REFERENCE_HIGHLIGHT_EVENT,
    handleMemoryReferenceHighlight
  );

  window.addEventListener(MEMORY_ROW_AVATAR_HOVER_EVENT, (event) => {
    memoryRowAvatarHoverState =
      normalizeMemoryRowAvatarHoverDetail(
        event && event.detail || {}
      );

    applyMemoryRowAvatarHoverGlow();
  });

  window.addEventListener(DELAYED_MEMORY_REPORT_ACTIVE_EVENT, (event) => {
    delayedMemoryReportActiveState =
      normalizeAvatarMemoryFocusDetail(
        event && event.detail || {}
      );

    applyMemoryRowAvatarHoverGlow();
  });

  window.addEventListener("jin:files-store-changed", () => {
    syncFilesState();
  });

  window.addEventListener(THINK_RUNTIME_CITATION_HIGHLIGHT_EVENT, (event) => {
    const detail = event && event.detail || {};
    const sourceId =
      String(detail.sourceId || "unknown-think");
    const state =
      normalizeThinkRuntimeCitationHighlightDetail(detail);

    if (state) {
      activeThinkRuntimeCitationSources.set(
        sourceId,
        state
      );
    } else {
      activeThinkRuntimeCitationSources.delete(
        sourceId
      );
    }

    applyThinkRuntimeCitationGlow();
  });

  if (memoryPanel && typeof MutationObserver !== "undefined") {
    const observer = new MutationObserver(syncMemoryLayer);
    observer.observe(memoryPanel, {
      attributes: true,
      attributeFilter: ["class"],
    });
  }

  if (memoryLayersToggle) {
    syncMemoryLayersToggleLabel();

    memoryLayersToggle.addEventListener("mousedown", (event) => {
      event.stopPropagation();
    });

  }

  syncMemoryLayer();
  renderAvatar(getLatestSnapshot(), {
    snapshotIndex: getLatestSnapshotIndex(),
  });
  applyCenterColor(centerColor);

  window.JinRuntime.avatar = {
    render: renderAvatar,
    refresh: reinitializeAvatar,
    repaint: repaintAvatar,
    beginReasoning: beginReasoningMotion,
    endReasoning: endReasoningMotion,
    clearReasoning: clearReasoningMotion,
    getCenterColor,
    getMemoryLayersHidden,
    setCenterColor,
    setMemoryLayersHidden,
    toggleMemoryLayers,
    setDelayedMemoryPinned: setDelayedMemoryDashPinned,
    syncActiveMemoryState,
    syncDelayedMemoryState,
    syncL4MemoryState,
    syncFilesState,
    get aggressivePalette() {
      return AGGRESSIVE_PALETTE;
    },
    get keywordPalette() {
      return KEYWORD_PALETTE;
    },
  };
}());
