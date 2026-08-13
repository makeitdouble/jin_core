(function () {
  "use strict";

  const PANEL_INACTIVITY_MS = 30_000;
  const STARTUP_AUTO_COLLAPSE_MS = 5_000;
  const TRANSIENT_SCROLLBAR_HIDE_MS = 650;
  const INACTIVE_CLASS = "panel-inactive";
  const STARTUP_COLLAPSE_CLASS = "panel-startup-collapse-active";
  const TRANSIENT_SCROLLBAR_CLASS = "jin-scrollbar-active";
  const PANEL_IDS = [
    "console-panel",
    "memory-panel",
  ];
  const TRANSIENT_SCROLLBAR_SELECTORS = [
    "#chat-history",
  ];
  const SCROLL_KEYS = new Set([
    "ArrowDown",
    "ArrowLeft",
    "ArrowRight",
    "ArrowUp",
    "End",
    "Home",
    "PageDown",
    "PageUp",
    " ",
  ]);
  let startupAutoCollapseTimerId = null;
  let startupAutoCollapseCancelled = false;
  let startupFallbackCleanupTimerId = null;
  let startupFallbackPreviousDuration = null;
  const transientScrollbarElements = new Set();
  const transientScrollbarTimers = new WeakMap();

  function getPanels() {
    return PANEL_IDS
      .map((panelId) => document.getElementById(panelId))
      .filter(Boolean);
  }

  function markTransientScrollbarActive(element) {
    if (!element || !element.classList) {
      return;
    }

    const activeTimerId =
      transientScrollbarTimers.get(element);

    if (activeTimerId) {
      window.clearTimeout(activeTimerId);
    }

    element.classList.add(
      TRANSIENT_SCROLLBAR_CLASS
    );

    transientScrollbarTimers.set(
      element,
      window.setTimeout(
        () => {
          element.classList.remove(
            TRANSIENT_SCROLLBAR_CLASS
          );
          transientScrollbarTimers.delete(element);
        },
        TRANSIENT_SCROLLBAR_HIDE_MS
      )
    );
  }

  function markDocumentScrollbarActive() {
    markTransientScrollbarActive(
      document.documentElement
    );

    markTransientScrollbarActive(
      document.body
    );
  }

  function markKnownTransientScrollbarsActive() {
    transientScrollbarElements.forEach(
      markTransientScrollbarActive
    );
  }

  function bindTransientScrollbar(element) {
    if (!element) {
      return;
    }

    transientScrollbarElements.add(element);

    const markElementScrollbarActive = () => {
      markTransientScrollbarActive(element);
    };

    [
      "wheel",
      "touchmove",
      "scroll",
    ].forEach((eventName) => {
      element.addEventListener(
        eventName,
        markElementScrollbarActive,
        { passive: true }
      );
    });
  }

  function bindTransientScrollbars() {
    TRANSIENT_SCROLLBAR_SELECTORS.forEach((selector) => {
      document.querySelectorAll(selector)
        .forEach(bindTransientScrollbar);
    });

    document.addEventListener(
      "wheel",
      markKnownTransientScrollbarsActive,
      { passive: true }
    );

    document.addEventListener(
      "touchmove",
      markKnownTransientScrollbarsActive,
      { passive: true }
    );

    document.addEventListener(
      "keydown",
      (event) => {
        if (SCROLL_KEYS.has(event.key)) {
          markKnownTransientScrollbarsActive();
        }
      }
    );

    window.addEventListener(
      "scroll",
      markDocumentScrollbarActive,
      { passive: true }
    );
  }

  function clearStartupAutoCollapseTimer() {
    if (startupAutoCollapseTimerId === null) {
      return;
    }

    window.clearTimeout(startupAutoCollapseTimerId);
    startupAutoCollapseTimerId = null;
  }

  function clearStartupFallbackCleanupTimer() {
    if (startupFallbackCleanupTimerId === null) {
      return;
    }

    window.clearTimeout(startupFallbackCleanupTimerId);
    startupFallbackCleanupTimerId = null;
  }

  function restoreStartupFallbackDuration(root) {
    if (startupFallbackPreviousDuration === null) {
      return;
    }

    if (startupFallbackPreviousDuration) {
      root.style.setProperty(
        "--panel-collapse-duration",
        startupFallbackPreviousDuration
      );
    } else {
      root.style.removeProperty(
        "--panel-collapse-duration"
      );
    }

    startupFallbackPreviousDuration = null;
  }

  function cancelStartupAutoCollapse() {
    startupAutoCollapseCancelled = true;
    clearStartupAutoCollapseTimer();
  }

  function registerStartupPanelActivity() {
    cancelStartupAutoCollapse();
    cancelActiveStartupCollapseAnimation();
  }

  function isWindowActive() {
    return (
      document.visibilityState === "visible"
      && document.hasFocus()
    );
  }

  function isAnyPanelHovered() {
    return getPanels().some((panel) => {
      try {
        return panel.matches(":hover");
      } catch (_error) {
        return false;
      }
    });
  }

  function syncSceneShadeToPanelCollapse() {
    const root =
      document.querySelector("main");

    if (!root) {
      return;
    }

    const collapsedCount =
      getPanels().filter((panel) => (
        panel.classList.contains("panel-collapsed")
      )).length;

    root.classList.remove(
      "panels-collapsed-1",
      "panels-collapsed-2"
    );

    if (collapsedCount > 0) {
      root.classList.add(
        `panels-collapsed-${collapsedCount}`
      );
    }
  }

  function cancelActiveStartupCollapseAnimation() {
    if (
      window.JinPanels
      && typeof window.JinPanels.cancelStartupCollapseAnimation === "function"
      && window.JinPanels.cancelStartupCollapseAnimation()
    ) {
      return;
    }

    const root =
      document.querySelector("main");

    if (
      !root
      || !root.classList.contains(STARTUP_COLLAPSE_CLASS)
    ) {
      return;
    }

    clearStartupFallbackCleanupTimer();

    root.classList.remove(
      STARTUP_COLLAPSE_CLASS
    );

    restoreStartupFallbackDuration(root);

    getPanels().forEach((panel) => {
      panel.classList.remove("panel-collapsed");
    });
    syncSceneShadeToPanelCollapse();
  }

  function afterStartupCollapseArmed(callback) {
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(callback);
    });
  }

  function collapseStartupIdlePanels() {
    startupAutoCollapseTimerId = null;

    if (
      startupAutoCollapseCancelled
      || !isWindowActive()
      || isAnyPanelHovered()
    ) {
      cancelStartupAutoCollapse();
      return;
    }

    if (
      window.JinPanels
      && typeof window.JinPanels.collapseAllPanels === "function"
    ) {
      window.JinPanels.collapseAllPanels({
        startup: true,
      });
      return;
    }

    const root =
      document.querySelector("main");

    if (root) {
      const previousDuration =
        root.style.getPropertyValue(
          "--panel-collapse-duration"
        );

      const startupDuration =
        getComputedStyle(root)
          .getPropertyValue("--panel-startup-collapse-duration")
          .trim()
        || "5s";

      root.style.setProperty(
        "--panel-collapse-duration",
        startupDuration
      );

      root.classList.add(
        STARTUP_COLLAPSE_CLASS
      );

      root.getBoundingClientRect();

      startupFallbackPreviousDuration =
        previousDuration;

      clearStartupFallbackCleanupTimer();

      startupFallbackCleanupTimerId =
        window.setTimeout(
          () => {
            root.classList.remove(
              STARTUP_COLLAPSE_CLASS
            );

            restoreStartupFallbackDuration(root);
            startupFallbackCleanupTimerId = null;
          },
          STARTUP_AUTO_COLLAPSE_MS + 80
        );

      afterStartupCollapseArmed(() => {
        if (
          startupAutoCollapseCancelled
          || !root.classList.contains(STARTUP_COLLAPSE_CLASS)
        ) {
          return;
        }

        getPanels().forEach((panel) => {
          panel.classList.add("panel-collapsed");
        });
        syncSceneShadeToPanelCollapse();
      });
      return;
    }

    getPanels().forEach((panel) => {
      panel.classList.add("panel-collapsed");
    });
    syncSceneShadeToPanelCollapse();
  }

  function scheduleStartupAutoCollapse() {
    if (
      startupAutoCollapseCancelled
      || !isWindowActive()
      || isAnyPanelHovered()
    ) {
      cancelStartupAutoCollapse();
      return;
    }

    clearStartupAutoCollapseTimer();
    startupAutoCollapseTimerId =
      window.setTimeout(
        collapseStartupIdlePanels,
        STARTUP_AUTO_COLLAPSE_MS
      );
  }

  function bindStartupAutoCollapse() {
    if (document.readyState === "complete") {
      window.requestAnimationFrame(
        scheduleStartupAutoCollapse
      );
      return;
    }

    window.addEventListener(
      "load",
      scheduleStartupAutoCollapse,
      { once: true }
    );
  }

  function bindPanelInactivity(panel) {
    let timerId = null;
    let hovered = false;

    function clearTimer() {
      if (timerId === null) {
        return;
      }

      window.clearTimeout(timerId);
      timerId = null;
    }

    function wakePanel() {
      panel.classList.remove(INACTIVE_CLASS);
    }

    function scheduleFade() {
      clearTimer();

      if (hovered) {
        return;
      }

      timerId = window.setTimeout(() => {
        timerId = null;

        if (!hovered) {
          panel.classList.add(INACTIVE_CLASS);
        }
      }, PANEL_INACTIVITY_MS);
    }

    function registerActivity() {
      registerStartupPanelActivity();
      wakePanel();
      scheduleFade();
    }

    panel.addEventListener("mouseenter", () => {
      registerStartupPanelActivity();
      hovered = true;
      clearTimer();
      wakePanel();
    });

    panel.addEventListener("mouseleave", () => {
      hovered = false;
      scheduleFade();
    });

    [
      "pointerdown",
      "click",
      "wheel",
      "touchstart",
      "focusin",
      "keydown",
    ].forEach((eventName) => {
      panel.addEventListener(
        eventName,
        registerActivity,
        eventName === "wheel" || eventName === "touchstart"
          ? { passive: true }
          : false
      );
    });

    // Do not listen for `scroll` here. The data stream console scrolls
    // programmatically as new log entries arrive; treating that as activity
    // would keep the left panel awake forever. Wheel/touch/pointer/keyboard
    // events above cover actual user interaction.
    scheduleFade();
  }

  getPanels().forEach((panel) => {
    bindPanelInactivity(panel);
  });

  bindTransientScrollbars();

  window.addEventListener(
    "blur",
    cancelStartupAutoCollapse
  );

  document.addEventListener(
    "visibilitychange",
    () => {
      if (document.visibilityState !== "visible") {
        cancelStartupAutoCollapse();
      }
    }
  );

  bindStartupAutoCollapse();
})();
