(function () {
  "use strict";

  window.JinRuntime = window.JinRuntime || {};

  function readAnonymousModeConfig() {
    const template = document.getElementById(
      "jin-runtime-config"
    );

    if (!template) {
      return {};
    }

    try {
      const payload = JSON.parse(
        template.textContent || "{}"
      );
      const anonymousMode = payload && payload.anonymousMode;
      return anonymousMode && typeof anonymousMode === "object"
        ? anonymousMode
        : {};
    } catch (error) {
      return {};
    }
  }

  const anonymousModeConfig = readAnonymousModeConfig();

  // Values come from config.py/config.example.py through the page bootstrap.
  // Keep the previous defaults if an older/custom template does not expose
  // the new fields yet.
  const ENABLE_DEFAULT_ANONYMOUS_MODE =
    anonymousModeConfig.ENABLE_DEFAULT_ANONYMOUS_MODE !== false;

  const ENABLE_GLOBAL_ANONYMOUS_MODE =
    anonymousModeConfig.ENABLE_GLOBAL_ANONYMOUS_MODE === true;

  const CHROMIUM_PRIVATE_HEADROOM_THRESHOLD_BYTES =
    9.5 * 1024 * 1024 * 1024;

  const state = {
    ready: false,
    detectedIncognito: false,
    detectionSource: "pending",
  };

  function isChromiumFamily() {
    const userAgent = String(
      (window.navigator && window.navigator.userAgent) || ""
    );

    return /(?:Chrome|Chromium|Edg|OPR)\//i.test(userAgent);
  }

  function isFirefoxFamily() {
    return /Firefox\//i.test(
      String((window.navigator && window.navigator.userAgent) || "")
    );
  }

  function isSafariFamily() {
    const userAgent = String(
      (window.navigator && window.navigator.userAgent) || ""
    );

    return (
      /Safari\//i.test(userAgent)
      && !/(?:Chrome|Chromium|CriOS|Edg|OPR)\//i.test(userAgent)
    );
  }

  async function detectChromiumIncognito() {
    const storage = window.navigator && window.navigator.storage;

    if (!storage || typeof storage.estimate !== "function") {
      return null;
    }

    try {
      const estimate = await storage.estimate();
      const quota = Number(estimate && estimate.quota);
      const usage = Number(estimate && estimate.usage) || 0;

      if (!Number.isFinite(quota) || quota <= 0) {
        return null;
      }

      const headroom = Math.max(0, quota - usage);

      return {
        isPrivate:
          headroom < CHROMIUM_PRIVATE_HEADROOM_THRESHOLD_BYTES,
        source: "chromium-storage-headroom",
      };
    } catch (error) {
      return null;
    }
  }

  async function detectOpfsPrivateMode() {
    const storage = window.navigator && window.navigator.storage;

    if (!storage || typeof storage.getDirectory !== "function") {
      return null;
    }

    try {
      await storage.getDirectory();
      return {
        isPrivate: false,
        source: "opfs",
      };
    } catch (error) {
      return {
        isPrivate: true,
        source: "opfs",
      };
    }
  }

  function detectLegacyChromiumPrivateMode() {
    return new Promise((resolve) => {
      const requestFileSystem =
        window.webkitRequestFileSystem
        || window.RequestFileSystem;

      if (typeof requestFileSystem !== "function") {
        resolve(null);
        return;
      }

      try {
        requestFileSystem(
          window.TEMPORARY || 0,
          1,
          function () {
            resolve({
              isPrivate: false,
              source: "legacy-filesystem",
            });
          },
          function () {
            resolve({
              isPrivate: true,
              source: "legacy-filesystem",
            });
          }
        );
      } catch (error) {
        resolve(null);
      }
    });
  }

  async function detectIncognitoMode() {
    if (!ENABLE_DEFAULT_ANONYMOUS_MODE) {
      return {
        isPrivate: false,
        source: "disabled",
      };
    }

    if (isChromiumFamily()) {
      const chromiumResult = await detectChromiumIncognito();
      if (chromiumResult) {
        return chromiumResult;
      }

      const legacyResult = await detectLegacyChromiumPrivateMode();
      if (legacyResult) {
        return legacyResult;
      }
    }

    if (isFirefoxFamily() || isSafariFamily()) {
      const opfsResult = await detectOpfsPrivateMode();
      if (opfsResult) {
        return opfsResult;
      }
    }

    return {
      isPrivate: false,
      source: "unsupported",
    };
  }

  function isEnabled() {
    return Boolean(
      ENABLE_GLOBAL_ANONYMOUS_MODE
      || (
        ENABLE_DEFAULT_ANONYMOUS_MODE
        && state.ready
        && state.detectedIncognito
      )
    );
  }

  // Storage reads are conservative while asynchronous private-mode detection
  // is still pending. This prevents normal-profile history from flashing into
  // a real incognito boot before the detector resolves.
  function shouldIsolateStorage() {
    return Boolean(
      ENABLE_GLOBAL_ANONYMOUS_MODE
      || (
        ENABLE_DEFAULT_ANONYMOUS_MODE
        && (
          !state.ready
          || state.detectedIncognito
        )
      )
    );
  }

  const api = {
    ENABLE_DEFAULT_ANONYMOUS_MODE,
    ENABLE_GLOBAL_ANONYMOUS_MODE,
    isEnabled,
    shouldIsolateStorage,
    isDetectedIncognito: function () {
      return Boolean(state.detectedIncognito);
    },
    getDetectionSource: function () {
      return state.detectionSource;
    },
    ready: null,
  };

  api.ready = detectIncognitoMode()
    .then((result) => {
      state.detectedIncognito = Boolean(
        result && result.isPrivate
      );
      state.detectionSource = String(
        (result && result.source) || "unknown"
      );
      state.ready = true;
      return api;
    })
    .catch(() => {
      state.detectedIncognito = false;
      state.detectionSource = "failed";
      state.ready = true;
      return api;
    });

  window.JinRuntime.anonymousMode = api;
}());
