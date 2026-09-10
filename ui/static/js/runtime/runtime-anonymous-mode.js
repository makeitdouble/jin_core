(function () {
  "use strict";

  window.JinRuntime = window.JinRuntime || {};

  const ANONYMOUS_MODE_QUERY_PARAM = "anonymous_mode";
  const ANONYMOUS_SESSION_QUERY_PARAM = "anonymous_session_id";
  const ANONYMOUS_SESSION_SUFFIX = "_anon";
  const ANONYMOUS_SESSION_SUFFIXES = [
    ANONYMOUS_SESSION_SUFFIX,
    "-anon",
  ];
  const ANONYMOUS_SESSION_STORAGE_KEY = "jin.anonymousSession.v1";
  const TRUE_VALUES = new Set(["1", "true", "yes", "on"]);

  function cleanSessionId(value) {
    return String(value || "")
      .trim()
      .replace(/[^a-zA-Z0-9_.-]/g, "_")
      .replace(/^[._-]+|[._-]+$/g, "")
      .slice(0, 80);
  }

  function generateSessionId() {
    let base = "";

    if (
        window.crypto
        && typeof window.crypto.randomUUID === "function"
    ) {
      base = window.crypto.randomUUID();
    } else {
      const bytes = new Uint8Array(16);

      if (
          window.crypto
          && typeof window.crypto.getRandomValues === "function"
      ) {
        window.crypto.getRandomValues(bytes);
      } else {
        for (let index = 0; index < bytes.length; index += 1) {
          bytes[index] = Math.floor(Math.random() * 256);
        }
      }

      bytes[6] = (bytes[6] & 0x0f) | 0x40;
      bytes[8] = (bytes[8] & 0x3f) | 0x80;

      const hex = Array.from(
        bytes,
        value => value.toString(16).padStart(2, "0")
      ).join("");
      base = [
        hex.slice(0, 8),
        hex.slice(8, 12),
        hex.slice(12, 16),
        hex.slice(16, 20),
        hex.slice(20),
      ].join("-");
    }

    return `${base}${ANONYMOUS_SESSION_SUFFIX}`;
  }

  function normalizeAnonymousSessionId(value) {
    let sessionId = cleanSessionId(value);

    if (!sessionId) {
      return generateSessionId();
    }

    const normalized = sessionId.toLowerCase();
    let base = sessionId;

    const matchedSuffix = ANONYMOUS_SESSION_SUFFIXES.find(
      suffix => normalized.endsWith(suffix)
    );

    if (matchedSuffix) {
      base = sessionId.slice(0, -matchedSuffix.length);
    }

    const maxBaseLength = 80 - ANONYMOUS_SESSION_SUFFIX.length;
    sessionId = `${base.slice(0, maxBaseLength)}${ANONYMOUS_SESSION_SUFFIX}`;

    return sessionId;
  }

  function readExplicitRequest() {
    let params;

    try {
      params = new URLSearchParams(window.location.search || "");
    } catch (error) {
      return {
        enabled: false,
        sessionId: "",
      };
    }

    const enabled = TRUE_VALUES.has(
      String(params.get(ANONYMOUS_MODE_QUERY_PARAM) || "")
        .trim()
        .toLowerCase()
    );

    return {
      enabled,
      sessionId: enabled
        ? normalizeAnonymousSessionId(
            params.get(ANONYMOUS_SESSION_QUERY_PARAM)
          )
        : "",
    };
  }

  function emptyLongTermMemory() {
    return {
      version: 2,
      revision: 0,
      updated_at: "",
      facts: [],
      pending_facts: [],
      deleted_fact_ids: [],
      ignored_pending_fact_ids: [],
      next_fact_id: 1,
      next_pending_fact_id: 1,
    };
  }

  function createEmptySnapshot(sessionId) {
    return {
      version: 1,
      session_id: sessionId,
      created_at: new Date().toISOString(),
      frame_memory: "",
      active_memory: [],
      long_term_memory: emptyLongTermMemory(),
      delayed_memory: {},
    };
  }

  const request = readExplicitRequest();
  const state = {
    enabled: Boolean(request.enabled),
    sessionId: String(request.sessionId || ""),
  };

  function readSnapshot() {
    if (!state.enabled || !state.sessionId) {
      return null;
    }

    try {
      const parsed = JSON.parse(
        window.sessionStorage.getItem(
          ANONYMOUS_SESSION_STORAGE_KEY
        ) || "null"
      );

      if (
        parsed
        && typeof parsed === "object"
        && !Array.isArray(parsed)
        && String(parsed.session_id || "").trim() === state.sessionId
      ) {
        return parsed;
      }
    } catch (error) {
      // A corrupt ephemeral snapshot is equivalent to a fresh room.
    }

    const fresh = createEmptySnapshot(state.sessionId);
    writeSnapshot(fresh);
    return fresh;
  }

  function writeSnapshot(value) {
    if (!state.enabled || !state.sessionId) {
      return false;
    }

    const source = (
      value
      && typeof value === "object"
      && !Array.isArray(value)
    )
      ? value
      : {};
    const snapshot = {
      ...createEmptySnapshot(state.sessionId),
      ...source,
      version: 1,
      session_id: state.sessionId,
      active_memory: Array.isArray(source.active_memory)
        ? source.active_memory
        : [],
      long_term_memory: (
        source.long_term_memory
        && typeof source.long_term_memory === "object"
        && !Array.isArray(source.long_term_memory)
      )
        ? source.long_term_memory
        : emptyLongTermMemory(),
      delayed_memory: (
        source.delayed_memory
        && typeof source.delayed_memory === "object"
        && !Array.isArray(source.delayed_memory)
      )
        ? source.delayed_memory
        : {},
    };

    try {
      window.sessionStorage.setItem(
        ANONYMOUS_SESSION_STORAGE_KEY,
        JSON.stringify(snapshot)
      );
      return true;
    } catch (error) {
      return false;
    }
  }

  function updateSnapshotField(field, value) {
    const current = readSnapshot();
    if (!current) {
      return false;
    }

    return writeSnapshot({
      ...current,
      [field]: value,
    });
  }

  function isEnabled() {
    return Boolean(state.enabled);
  }

  function shouldIsolateStorage() {
    return isEnabled();
  }

  function getSessionId() {
    return state.enabled ? state.sessionId : "";
  }

  function buildAnonymousWindowUrl() {
    const sessionId = generateSessionId();
    const url = new URL(window.location.href);

    // Anonymous rooms are always fresh. Never inherit an archive restore link.
    url.searchParams.delete("restore_session");
    url.searchParams.set(ANONYMOUS_MODE_QUERY_PARAM, "1");
    url.searchParams.set(ANONYMOUS_SESSION_QUERY_PARAM, sessionId);

    return {
      sessionId,
      url: url.toString(),
    };
  }

  function openAnonymousWindow() {
    const target = buildAnonymousWindowUrl();
    const opened = window.open(target.url, "_blank");

    return {
      opened: Boolean(opened),
      sessionId: target.sessionId,
      url: target.url,
    };
  }

  if (state.enabled) {
    // If a browser copied sessionStorage from an opener, a mismatching id forces
    // a new empty memory room instead of cloning the parent anonymous room.
    const snapshot = readSnapshot();
    if (!snapshot || snapshot.session_id !== state.sessionId) {
      writeSnapshot(createEmptySnapshot(state.sessionId));
    }

    document.documentElement.classList.add("jin-anonymous-room");
  }

  const api = {
    ANONYMOUS_SESSION_SUFFIX,
    ANONYMOUS_SESSION_STORAGE_KEY,
    isEnabled,
    shouldIsolateStorage,
    getSessionId,
    readSnapshot,
    writeSnapshot,
    updateSnapshotField,
    createEmptySnapshot,
    buildAnonymousWindowUrl,
    openAnonymousWindow,
    ready: null,
  };

  api.ready = Promise.resolve(api);
  window.JinRuntime.anonymousMode = api;
}());
