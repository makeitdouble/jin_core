(function () {
  "use strict";

  const PANEL_INACTIVITY_MS = 30_000;
  const INACTIVE_CLASS = "panel-inactive";
  const PANEL_IDS = [
    "console-panel",
    "settings-panel",
  ];

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
      wakePanel();
      scheduleFade();
    }

    panel.addEventListener("mouseenter", () => {
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

  PANEL_IDS.forEach((panelId) => {
    const panel = document.getElementById(panelId);

    if (panel) {
      bindPanelInactivity(panel);
    }
  });
})();
