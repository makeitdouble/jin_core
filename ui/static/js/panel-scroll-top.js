(function () {
  "use strict";

  const SCROLL_THRESHOLD_PX = 300;
  const CONSOLE_SEAM_OVERLAP_PX = 2;
  const PANEL_CONFIGS = [
    {
      panelSelector: "#console-panel",
      scrollerSelector: "#console-stream",
    },
    {
      panelSelector: "#memory-panel",
      scrollerSelector: ".memory-scroll",
    },
  ];

  function createArrowButton() {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "panel-scroll-top-button";
    button.setAttribute("aria-label", "Scroll panel to top");
    button.setAttribute("title", "Scroll to top");
    button.tabIndex = -1;
    button.innerHTML = [
      '<svg viewBox="0 0 24 16" aria-hidden="true" focusable="false">',
      '<path d="M5.5 11.5 12 5l6.5 6.5"></path>',
      "</svg>",
    ].join("");
    return button;
  }

  function bindPanelScrollTop(config) {
    const panel = document.querySelector(config.panelSelector);
    const scroller = panel && panel.querySelector(config.scrollerSelector);

    if (!panel || !scroller) {
      return;
    }

    const affordance = document.createElement("div");
    affordance.className = "panel-scroll-top-affordance";
    affordance.setAttribute("aria-hidden", "true");

    const button = createArrowButton();
    affordance.appendChild(button);
    panel.appendChild(affordance);

    let suppressWhileReturning = false;
    let frameId = 0;

    function syncGeometry() {
      const panelRect = panel.getBoundingClientRect();
      const scrollerRect = scroller.getBoundingClientRect();

      const seamOverlap =
        panel.id === "console-panel" ? CONSOLE_SEAM_OVERLAP_PX : 0;
      const bottomOffset = Math.max(
        0,
        panelRect.bottom - scrollerRect.bottom - seamOverlap
      );

      affordance.style.setProperty(
        "--panel-scroll-top-bottom-offset",
        `${bottomOffset.toFixed(2)}px`
      );
    }

    function syncVisibility() {
      if (suppressWhileReturning && scroller.scrollTop <= SCROLL_THRESHOLD_PX) {
        suppressWhileReturning = false;
      }

      const canScroll = scroller.scrollHeight > scroller.clientHeight + 1;
      const panelExpanded = !panel.classList.contains("panel-collapsed");
      const shouldShow =
        panelExpanded &&
        canScroll &&
        scroller.scrollTop > SCROLL_THRESHOLD_PX &&
        !suppressWhileReturning;

      affordance.classList.toggle("is-visible", shouldShow);
      affordance.setAttribute("aria-hidden", shouldShow ? "false" : "true");
      button.tabIndex = shouldShow ? 0 : -1;
    }

    function scheduleSync() {
      if (frameId) {
        return;
      }

      frameId = window.requestAnimationFrame(() => {
        frameId = 0;
        syncGeometry();
        syncVisibility();
      });
    }

    scroller.addEventListener("scroll", scheduleSync, { passive: true });

    button.addEventListener("mouseenter", () => {
      affordance.classList.add("is-hovered");
    });
    button.addEventListener("mouseleave", () => {
      affordance.classList.remove("is-hovered");
    });
    button.addEventListener("focus", () => {
      affordance.classList.add("is-hovered");
    });
    button.addEventListener("blur", () => {
      affordance.classList.remove("is-hovered");
    });

    button.addEventListener("pointerdown", (event) => {
      event.stopPropagation();
    });

    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();

      suppressWhileReturning = true;
      affordance.classList.remove("is-visible", "is-hovered");
      affordance.setAttribute("aria-hidden", "true");
      button.tabIndex = -1;

      const reducedMotion =
        window.matchMedia &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches;

      scroller.scrollTo({
        top: 0,
        behavior: reducedMotion ? "auto" : "smooth",
      });
    });

    if (typeof ResizeObserver === "function") {
      const resizeObserver = new ResizeObserver(scheduleSync);
      resizeObserver.observe(panel);
      resizeObserver.observe(scroller);

      if (panel.id === "console-panel") {
        const delayed = document.getElementById("attached-delayed-memory");
        const files = document.getElementById("attached-files");
        if (delayed) {
          resizeObserver.observe(delayed);
        }
        if (files) {
          resizeObserver.observe(files);
        }
      }
    }

    const mutationObserver = new MutationObserver(scheduleSync);
    mutationObserver.observe(panel, {
      attributes: true,
      attributeFilter: ["class", "style"],
    });

    window.addEventListener("resize", scheduleSync, { passive: true });
    scheduleSync();
  }

  function init() {
    PANEL_CONFIGS.forEach(bindPanelScrollTop);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
