(function () {
  "use strict";

  window.JinRuntime = window.JinRuntime || {};

  const UPDATE_EVENT = "jin:metabolism-update";
  const CHANNELS = Object.freeze([
    "dopamine",
    "serotonin",
    "oxytocin",
    "norepinephrine",
    "cortisol",
  ]);
  const PALETTE = Object.freeze({
    dopamine: "#fbbf24",
    serotonin: "#60a5fa",
    oxytocin: "#f472b6",
    norepinephrine: "#f97316",
    cortisol: "#34d399",
  });
  const DEFAULTS = Object.freeze({
    dopamine: 0.42,
    serotonin: 0.58,
    oxytocin: 0.46,
    norepinephrine: 0.38,
    cortisol: 0.24,
  });
  const DEFAULT_HALF_LIVES_SECONDS = Object.freeze({
    dopamine: 45 * 60,
    serotonin: 150 * 60,
    oxytocin: 120 * 60,
    norepinephrine: 32 * 60,
    cortisol: 55 * 60,
  });

  // One-switch rollback for the only new avatar motion. Tint/aura and memory
  // salience remain independent, so this can be disabled without touching the
  // causal metabolism layer.
  const AMBIENT_BODY_MOTION_ENABLED = true;
  const IDLE_HOMEOSTASIS_TICK_MS = 30000;

  let state = { ...DEFAULTS };
  let authoritativeState = { ...DEFAULTS };
  let authoritativeAtMs = Date.now();
  let halfLivesSeconds = { ...DEFAULT_HALF_LIVES_SECONDS };
  let activeMemorySalience = {};

  function clamp(value, min, max) {
    const number = Number(value);
    const safe = Number.isFinite(number) ? number : 0;
    return Math.max(min, Math.min(max, safe));
  }

  function normalize(value) {
    const source =
      value && typeof value === "object" && !Array.isArray(value)
        ? value
        : {};

    return CHANNELS.reduce((result, channel) => {
      const fallback = DEFAULTS[channel];
      const raw = Number(source[channel]);
      result[channel] = clamp(
        Number.isFinite(raw) ? raw : fallback,
        0,
        1
      );
      return result;
    }, {});
  }

  function normalizeSalience(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      return {};
    }

    return Object.entries(value).reduce((result, [key, raw]) => {
      const id = String(key || "").trim().toLowerCase();
      const score = Number(raw);
      if (id && Number.isFinite(score)) {
        result[id] = clamp(score, 0, 1);
      }
      return result;
    }, {});
  }

  function normalizeHalfLives(value) {
    const source =
      value && typeof value === "object" && !Array.isArray(value)
        ? value
        : {};

    return CHANNELS.reduce((result, channel) => {
      const raw = Number(source[channel]);
      result[channel] =
        Number.isFinite(raw) && raw > 0
          ? raw
          : DEFAULT_HALF_LIVES_SECONDS[channel];
      return result;
    }, {});
  }

  function hexToRgb(color) {
    const normalized = String(color || "")
      .replace("#", "")
      .trim();

    if (!/^[0-9a-f]{6}$/i.test(normalized)) {
      return null;
    }

    return {
      r: parseInt(normalized.slice(0, 2), 16),
      g: parseInt(normalized.slice(2, 4), 16),
      b: parseInt(normalized.slice(4, 6), 16),
    };
  }

  function rgbToHex(rgb) {
    const part = value => clamp(Math.round(value), 0, 255)
      .toString(16)
      .padStart(2, "0");

    return `#${part(rgb.r)}${part(rgb.g)}${part(rgb.b)}`;
  }

  function mixHex(baseColor, tintColor, amount) {
    const base = hexToRgb(baseColor);
    const tint = hexToRgb(tintColor);

    if (!base || !tint) {
      return String(baseColor || tintColor || "#ffffff");
    }

    const weight = clamp(amount, 0, 1);

    return rgbToHex({
      r: base.r + (tint.r - base.r) * weight,
      g: base.g + (tint.g - base.g) * weight,
      b: base.b + (tint.b - base.b) * weight,
    });
  }

  function getDominantChannel() {
    return CHANNELS.reduce((winner, channel) => {
      return state[channel] > state[winner]
        ? channel
        : winner;
    }, CHANNELS[0]);
  }

  function getBlendedChemistryColor() {
    let total = 0;
    const blended = { r: 0, g: 0, b: 0 };

    CHANNELS.forEach(channel => {
      const rgb = hexToRgb(PALETTE[channel]);
      if (!rgb) {
        return;
      }

      // Every channel is always present, while elevated channels pull the
      // blend slightly harder. This keeps the tint alive without turning the
      // avatar into a mood lamp.
      const weight = 0.16 + clamp(state[channel], 0, 1) * 0.84;
      total += weight;
      blended.r += rgb.r * weight;
      blended.g += rgb.g * weight;
      blended.b += rgb.b * weight;
    });

    if (!total) {
      return PALETTE[getDominantChannel()];
    }

    return rgbToHex({
      r: blended.r / total,
      g: blended.g / total,
      b: blended.b / total,
    });
  }

  function tintColor(baseColor) {
    const averageDistance = CHANNELS.reduce((sum, channel) => {
      return sum + Math.abs(state[channel] - DEFAULTS[channel]);
    }, 0) / CHANNELS.length;

    const amount = clamp(0.032 + averageDistance * 0.16, 0.032, 0.085);

    return mixHex(
      baseColor,
      getBlendedChemistryColor(),
      amount
    );
  }

  function loggerTintPercent(channel) {
    const level = clamp(state[channel], 0, 1);
    return 4 + level * 11;
  }

  function auraTintPercent(channel) {
    const level = clamp(state[channel], 0, 1);
    return 7 + level * 10;
  }

  function getAmbientBodyScale() {
    if (!AMBIENT_BODY_MOTION_ENABLED) {
      return 0.90;
    }

    const factor = clamp(
      1
      + (state.oxytocin - DEFAULTS.oxytocin) * 0.035
      + (state.dopamine - DEFAULTS.dopamine) * 0.012
      - (state.cortisol - DEFAULTS.cortisol) * 0.014,
      0.985,
      1.018
    );

    return 0.90 * factor;
  }

  function getAmbientAvatarOpacity() {
    if (!AMBIENT_BODY_MOTION_ENABLED) {
      return 0.94;
    }

    return clamp(
      0.94
      + (state.serotonin - DEFAULTS.serotonin) * 0.026
      - (state.cortisol - DEFAULTS.cortisol) * 0.018,
      0.920,
      0.956
    );
  }

  function applyCssVariables() {
    const root = document.documentElement;

    CHANNELS.forEach(channel => {
      root.style.setProperty(
        `--jin-metabolism-${channel}`,
        `${loggerTintPercent(channel).toFixed(2)}%`
      );
      root.style.setProperty(
        `--jin-metabolism-${channel}-aura`,
        `${auraTintPercent(channel).toFixed(2)}%`
      );
    });

    root.style.setProperty(
      "--jin-avatar-metabolism-body-scale",
      getAmbientBodyScale().toFixed(5)
    );
    root.style.setProperty(
      "--jin-avatar-metabolism-opacity",
      getAmbientAvatarOpacity().toFixed(4)
    );
  }

  function getState() {
    return { ...state };
  }

  function getActiveMemorySalience(activeMemoryId) {
    const id = String(activeMemoryId || "").trim().toLowerCase();
    const value = Number(activeMemorySalience[id]);
    return Number.isFinite(value)
      ? clamp(value, 0, 1)
      : null;
  }

  function dispatchUpdate(source) {
    window.dispatchEvent(
      new CustomEvent(UPDATE_EVENT, {
        detail: {
          levels: getState(),
          dominant: getDominantChannel(),
          blendedColor: getBlendedChemistryColor(),
          activeMemorySalience: { ...activeMemorySalience },
          source: String(source || "server"),
        },
      })
    );
  }

  function applyServerUpdate(value) {
    const envelope =
      value && typeof value === "object" && value.levels
        ? value
        : { levels: value };

    authoritativeState = normalize(envelope.levels);
    state = { ...authoritativeState };
    activeMemorySalience = normalizeSalience(
      envelope.active_memory_salience || envelope.activeMemorySalience
    );
    halfLivesSeconds = normalizeHalfLives(
      envelope.half_lives_seconds || envelope.halfLivesSeconds
    );

    const serverTimestamp = Number(envelope.updated_at || envelope.updatedAt);
    authoritativeAtMs =
      Number.isFinite(serverTimestamp) && serverTimestamp > 0
        ? serverTimestamp * 1000
        : Date.now();

    applyCssVariables();
    dispatchUpdate("server");

    return getState();
  }

  function getIdleHomeostaticState(nowMs) {
    const elapsedSeconds = Math.max(
      0,
      (Number(nowMs || Date.now()) - authoritativeAtMs) / 1000
    );

    return CHANNELS.reduce((result, channel) => {
      const baseline = DEFAULTS[channel];
      const halfLife = Math.max(1, halfLivesSeconds[channel]);
      const factor = Math.pow(0.5, elapsedSeconds / halfLife);
      result[channel] = clamp(
        baseline + (authoritativeState[channel] - baseline) * factor,
        0,
        1
      );
      return result;
    }, {});
  }

  function applyIdleHomeostasis() {
    const next = getIdleHomeostaticState(Date.now());
    const changed = CHANNELS.some(channel => {
      return Math.abs(next[channel] - state[channel]) >= 0.0005;
    });

    if (!changed) {
      return;
    }

    state = next;
    applyCssVariables();
    dispatchUpdate("homeostasis");
  }

  state = normalize(state);
  authoritativeState = { ...state };
  applyCssVariables();

  window.setInterval(
    applyIdleHomeostasis,
    IDLE_HOMEOSTASIS_TICK_MS
  );

  window.JinRuntime.metabolism = {
    UPDATE_EVENT,
    CHANNELS,
    PALETTE,
    DEFAULTS,
    AMBIENT_BODY_MOTION_ENABLED,
    normalize,
    getState,
    getDominantChannel,
    getBlendedChemistryColor,
    getActiveMemorySalience,
    tintColor,
    loggerTintPercent,
    auraTintPercent,
    applyServerUpdate,
  };
})();
