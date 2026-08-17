(function () {
  "use strict";

  const SCROLL_THRESHOLD_PX = 300;
  const SCROLL_REVEAL_DURATION_MS = 3000;
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
      '<path d="M12 3.5 20 12H4z"></path>',
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

    const shadow = document.createElement("div");
    shadow.className = "panel-scroll-top-shadow";
    shadow.setAttribute("aria-hidden", "true");

    const affordance = document.createElement("div");
    affordance.className = "panel-scroll-top-affordance";
    affordance.setAttribute("aria-hidden", "true");

    const button = createArrowButton();
    affordance.appendChild(button);

    const delayed = panel.id === "console-panel"
      ? document.getElementById("attached-delayed-memory")
      : null;
    const shadowAnchor = delayed || panel.querySelector(config.scrollerSelector) || panel.firstElementChild;
    panel.insertBefore(shadow, shadowAnchor);
    panel.appendChild(affordance);

    let suppressWhileReturning = false;
    let revealFromScroll = false;
    let revealTimerId = 0;
    let frameId = 0;

    function clearRevealTimer() {
      if (!revealTimerId) {
        return;
      }
      window.clearTimeout(revealTimerId);
      revealTimerId = 0;
    }

    function syncGeometry() {
      const panelRect = panel.getBoundingClientRect();
      const scrollerRect = scroller.getBoundingClientRect();

      const seamOverlap =
        panel.id === "console-panel" ? CONSOLE_SEAM_OVERLAP_PX : 0;
      const bottomOffset = Math.max(
        0,
        panelRect.bottom - scrollerRect.bottom - seamOverlap
      );

      const bottomOffsetValue = `${bottomOffset.toFixed(2)}px`;
      shadow.style.setProperty(
        "--panel-scroll-top-bottom-offset",
        bottomOffsetValue
      );
      affordance.style.setProperty(
        "--panel-scroll-top-bottom-offset",
        bottomOffsetValue
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
        !suppressWhileReturning &&
        revealFromScroll;

      shadow.classList.toggle("is-visible", shouldShow);
      affordance.classList.toggle("is-visible", shouldShow);
      shadow.setAttribute("aria-hidden", shouldShow ? "false" : "true");
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

    function revealTemporarily() {
      revealFromScroll = true;
      clearRevealTimer();

      revealTimerId = window.setTimeout(() => {
        revealTimerId = 0;
        revealFromScroll = false;
        syncVisibility();
      }, SCROLL_REVEAL_DURATION_MS);
    }

    function holdRevealWhileHovered() {
      revealFromScroll = true;
      clearRevealTimer();
      syncVisibility();
    }

    function releaseHoverReveal() {
      shadow.classList.remove("is-hovered");
      affordance.classList.remove("is-hovered");

      if (suppressWhileReturning || scroller.scrollTop <= SCROLL_THRESHOLD_PX) {
        syncVisibility();
        return;
      }

      revealTemporarily();
      syncVisibility();
    }

    scroller.addEventListener("scroll", () => {
      if (!suppressWhileReturning) {
        revealTemporarily();
      }
      scheduleSync();
    }, { passive: true });

    button.addEventListener("mouseenter", () => {
      shadow.classList.add("is-hovered");
      affordance.classList.add("is-hovered");
      holdRevealWhileHovered();
    });
    button.addEventListener("mouseleave", () => {
      releaseHoverReveal();
    });
    button.addEventListener("focus", () => {
      shadow.classList.add("is-hovered");
      affordance.classList.add("is-hovered");
      holdRevealWhileHovered();
    });
    button.addEventListener("blur", () => {
      releaseHoverReveal();
    });

    button.addEventListener("pointerdown", (event) => {
      event.stopPropagation();
    });

    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();

      suppressWhileReturning = true;
      revealFromScroll = false;
      clearRevealTimer();
      shadow.classList.remove("is-visible", "is-hovered");
      affordance.classList.remove("is-visible", "is-hovered");
      shadow.setAttribute("aria-hidden", "true");
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
        const delayedPlaque = document.getElementById("attached-delayed-memory");
        const filesPlaque = document.getElementById("attached-files");
        if (delayedPlaque) {
          resizeObserver.observe(delayedPlaque);
        }
        if (filesPlaque) {
          resizeObserver.observe(filesPlaque);
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
