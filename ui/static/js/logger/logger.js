const consoleStream =
  document.getElementById("console-stream");

function parseTraceJson(details) {
  try {
    return JSON.parse(
      String(details || "")
    );
  } catch (_error) {
    return null;
  }
}

function prettifyTraceDetails(details) {
  const text =
    String(details || "");

  if (!text.trim()) {
    return "";
  }

  try {
    return JSON.stringify(
      JSON.parse(text),
      null,
      2
    );
  } catch (_error) {
    return text;
  }
}

function extractTraceReason(
  message,
  details,
) {
  const text =
    String(
      details
      || message
      || ""
    );

  if (!text.trim()) {
    return "";
  }

  const parsed =
    parseTraceJson(text);

  if (
      parsed
      && typeof parsed === "object"
  ) {
    const structuredReason =
      String(
        parsed.summary
        || parsed.explanation
        || parsed.trace_reason
        || parsed.reason
        || ""
      ).trim();

    if (structuredReason) {
      return structuredReason;
    }
  }

  const likelyReasonMatch =
    text.match(
      /^Likely reason:\s*(.+)$/m
    );

  if (likelyReasonMatch) {
    return likelyReasonMatch[1].trim();
  }

  const httpStatusMatch =
    text.match(
      /HTTPStatusError:\s*(.+?)(?:\r?\n|$)/
    );

  if (httpStatusMatch) {
    return httpStatusMatch[1]
      .replace(
        /\s+for url '([^']+)'/,
        function (_match, url) {
          return ` for ${summarizeTraceUrl(url)}`;
        }
      )
      .trim();
  }

  const errorLines =
    Array.from(
      text.matchAll(
        /^([A-Za-z_][\w.]*Error|Exception):\s*(.+)$/gm
      )
    );

  if (errorLines.length) {
    const match =
      errorLines[errorLines.length - 1];

    return `${match[1]}: ${match[2]}`.trim();
  }

  const nonEmptyLines =
    text
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);

  return (
    nonEmptyLines[nonEmptyLines.length - 1]
    || ""
  );
}

function summarizeTraceUrl(url) {
  try {
    const parsed =
      new URL(url);

    return `${parsed.host}${parsed.pathname}`;
  } catch (_error) {
    return url;
  }
}

function splitInlineTrace(
  message,
  details,
) {
  if (details) {
    return {
      message,
      details,
    };
  }

  const text =
    String(message ?? "");

  const traceStart =
    text.indexOf(
      "Traceback (most recent call last):"
    );

  if (traceStart === -1) {
    return {
      message: text,
      details: null,
    };
  }

  const summary =
    text.slice(
      0,
      traceStart,
    ).trim()
    || "Traceback captured.";

  return {
    message: summary,
    details: text.slice(
      traceStart
    ),
  };
}

function parseValidatorLogPayload(
  message,
  details,
) {
  const payloadLines = [];
  const visibleLines = [];

  String(message || "")
    .split(/\r?\n/)
    .forEach((line) => {
      const payloadMatch =
        line.match(
          /^(Preview|Raw chunk|Safe chunk):\s*"([\s\S]*)"$/
        );

      if (payloadMatch) {
        payloadLines.push(
          `${payloadMatch[1]}:\n${payloadMatch[2]}`
        );
        return;
      }

      if (
          line.trim()
          && line.trim() !== "Payload available."
      ) {
        visibleLines.push(
          line
        );
      }
    });

  const explicitDetails =
    details !== null
    && details !== undefined
    && String(details).trim()
      ? String(details)
      : "";

  return {
    message: visibleLines.join("\n").trim(),
    payload: explicitDetails || payloadLines.join("\n\n").trim(),
  };
}


function findLiveFlowLog(
  flowId,
) {
  if (!flowId) {
    return null;
  }

  return consoleStream.querySelector(
    `[data-flow-id="${CSS.escape(flowId)}"]`
  );
}

function moveLogToBottomWithFlip(
  logDiv,
) {
  const firstRect =
    logDiv.getBoundingClientRect();

  consoleStream.appendChild(
    logDiv
  );

  const lastRect =
    logDiv.getBoundingClientRect();

  const deltaY =
    firstRect.top - lastRect.top;

  if (!deltaY) {
    return;
  }

  logDiv.style.transform =
    `translateY(${deltaY}px)`;

  logDiv.style.transition =
    "transform 0s";

  requestAnimationFrame(
    function () {
      logDiv.style.transition =
        "transform 180ms ease-out";

      logDiv.style.transform =
        "translateY(0)";
    }
  );
}

function dismissLogAfterClear(
  logDiv,
) {

  window.setTimeout(
    function () {
      const height =
        logDiv.offsetHeight;

      logDiv.style.maxHeight =
        `${height}px`;

      logDiv.style.overflow =
        "hidden";

      logDiv.style.transition =
        "opacity 160ms ease, transform 160ms ease, max-height 180ms ease, margin 180ms ease, padding 180ms ease";

      requestAnimationFrame(
        function () {
          logDiv.style.opacity =
            "0";
          logDiv.style.transform =
            "translateY(-4px)";
          logDiv.style.maxHeight =
            "0";
          logDiv.style.marginTop =
            "0";
          logDiv.style.marginBottom =
            "0";
          logDiv.style.paddingTop =
            "0";
          logDiv.style.paddingBottom =
            "0";
        }
      );

      window.setTimeout(
        function () {
          logDiv.remove();
        },
        190
      );
    },
    450
  );

}



const consolePanel = document.getElementById("console-panel");
    const consoleDragHandle = document.getElementById("console-drag-handle");
    const PANEL_VIEWPORT_GAP = 8;
    const PANEL_DOCK_FREE = "free";
    const STARTUP_COLLAPSE_CLASS = "panel-startup-collapse-active";
    let startupCollapseClassTimer = null;
    let startupCollapseFrameId = null;
    let startupCollapsePreviousDuration = null;

    function getDefaultPanelDock(panel) {
        if (panel === consolePanel) {
            return "left";
        }

        if (panel === memoryPanel) {
            return "right";
        }

        return PANEL_DOCK_FREE;
    }

    function getPanelDock(panel) {
        return (
            panel.dataset.panelDock
            || getDefaultPanelDock(panel)
        );
    }

    function setPanelFreeDock(panel) {
        panel.dataset.panelDock =
            PANEL_DOCK_FREE;
    }

    function getPanelGapPixels(panel) {
        const root =
            panel.parentElement
            || document.documentElement;

        const rawGap =
            getComputedStyle(root)
                .getPropertyValue("--panel-gap")
                .trim();

        const parsedGap =
            Number.parseFloat(rawGap);

        return Number.isFinite(parsedGap)
            ? parsedGap
            : PANEL_VIEWPORT_GAP;
    }

    function syncSceneShadeToPanelCollapse() {
        const root =
            document.querySelector("main");

        if (!root) {
            return;
        }

        const collapsedCount =
            [
                consolePanel,
                memoryPanel,
            ].filter((panel) => (
                panel
                && panel.classList.contains("panel-collapsed")
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

    function togglePanelCollapseFromHeader(event, panel, handle, options = {}) {
        const ignoredTarget =
            options.ignoredTarget || null;
        const isCollapsed =
            panel
            && panel.classList.contains("panel-collapsed");

        if (
            !handle
            || !handle.contains(event.target)
            || !panel
            || (
                ignoredTarget
                && ignoredTarget.contains(event.target)
                && !isCollapsed
            )
        ) {
            return;
        }

        event.preventDefault();
        finishStartupCollapseAnimation();
        setPanelCollapsed(
            panel,
            !panel.classList.contains("panel-collapsed")
        );
        syncSceneShadeToPanelCollapse();
    }

    function setPanelCollapsed(panel, collapsed) {
        if (!panel) {
            return;
        }

        if (collapsed) {
            if (!panel.classList.contains("panel-collapsed")) {
                panel.dataset.expandedHeight =
                    panel.style.height
                    || `${Math.round(panel.getBoundingClientRect().height)}px`;
                panel.dataset.expandedMinHeight =
                    panel.style.minHeight || "";
                panel.dataset.expandedMaxHeight =
                    panel.style.maxHeight || "";
            }

            panel.classList.add(
                "panel-collapsed"
            );

            const collapsedHeight =
                getCollapsedPanelHeight(panel);

            panel.style.height =
                collapsedHeight;
            panel.style.minHeight =
                collapsedHeight;
            panel.style.maxHeight =
                collapsedHeight;

            clampPanelGeometry(panel);
            syncMemoryPanelBodyMount();

            return;
        }

        if (panel === memoryPanel) {
            attachMemoryPanelBody();
        }

        panel.classList.remove(
            "panel-collapsed"
        );

        panel.style.removeProperty(
            "height"
        );
        delete panel.dataset.expandedHeight;

        restorePanelDimension(
            panel,
            "minHeight",
            "expandedMinHeight"
        );

        restorePanelDimension(
            panel,
            "maxHeight",
            "expandedMaxHeight"
        );

        clampPanelGeometry(panel);
        syncMemoryPanelBodyMount();
    }

    function restorePanelDimension(panel, styleName, datasetName) {
        if (panel.dataset[datasetName]) {
            panel.style[styleName] =
                panel.dataset[datasetName];
        } else {
            panel.style[styleName] =
                "";
        }

        delete panel.dataset[datasetName];
    }

    function getPanelFrameHeight(panel) {
        return Math.max(
            0,
            panel.offsetHeight - panel.clientHeight
        );
    }

    function getCollapsedPanelHeight(panel) {
        if (panel === memoryPanel && memoryDragHandle) {
            return `${
                Math.round(
                    memoryDragHandle.getBoundingClientRect().height
                    + getPanelFrameHeight(panel)
                )
            }px`;
        }

        const collapsedTitleHeight =
            getComputedStyle(panel)
                .getPropertyValue("--panel-collapsed-title-height")
                .trim();

        return collapsedTitleHeight || "40px";
    }

    function refreshCollapsedPanelHeights() {
        [
            consolePanel,
            memoryPanel,
        ].forEach((panel) => {
            if (
                panel
                && panel.classList.contains("panel-collapsed")
            ) {
                panel.style.height =
                    getCollapsedPanelHeight(panel);
                panel.style.minHeight =
                    panel.style.height;
                panel.style.maxHeight =
                    panel.style.height;
            }
        });
    }

    function getPanelRoot() {
        return document.querySelector("main");
    }

    function parseCssDurationMs(duration) {
        const value =
            String(duration || "").trim();

        if (!value) {
            return 0;
        }

        if (value.endsWith("ms")) {
            return Number.parseFloat(value) || 0;
        }

        if (value.endsWith("s")) {
            return (Number.parseFloat(value) || 0) * 1000;
        }

        return Number.parseFloat(value) || 0;
    }

    function beginStartupCollapseAnimation() {
        const root =
            getPanelRoot();

        if (!root) {
            return;
        }

        if (startupCollapseClassTimer !== null) {
            window.clearTimeout(
                startupCollapseClassTimer
            );
        }

        const duration =
            getComputedStyle(root)
                .getPropertyValue("--panel-startup-collapse-duration")
                .trim()
            || "5s";

        if (startupCollapsePreviousDuration === null) {
            startupCollapsePreviousDuration =
                root.style.getPropertyValue(
                    "--panel-collapse-duration"
                );
        }

        root.style.setProperty(
            "--panel-collapse-duration",
            duration
        );

        root.classList.add(
            STARTUP_COLLAPSE_CLASS
        );

        root.getBoundingClientRect();

        const durationMs =
            parseCssDurationMs(
                duration
            );

        startupCollapseClassTimer =
            window.setTimeout(
                finishStartupCollapseAnimation,
                Math.max(0, durationMs) + 80
            );
    }

    function finishStartupCollapseAnimation() {
        cancelStartupCollapseFrame();

        if (startupCollapseClassTimer !== null) {
            window.clearTimeout(
                startupCollapseClassTimer
            );

            startupCollapseClassTimer = null;
        }

        const root =
            getPanelRoot();

        if (root) {
            root.classList.remove(
                STARTUP_COLLAPSE_CLASS
            );

            if (startupCollapsePreviousDuration !== null) {
                if (startupCollapsePreviousDuration) {
                    root.style.setProperty(
                        "--panel-collapse-duration",
                        startupCollapsePreviousDuration
                    );
                } else {
                    root.style.removeProperty(
                        "--panel-collapse-duration"
                    );
                }

                startupCollapsePreviousDuration = null;
            }
        }
    }

    function isStartupCollapseAnimationActive() {
        const root =
            getPanelRoot();

        return Boolean(
            startupCollapseFrameId !== null
            || startupCollapseClassTimer !== null
            || (
                root
                && root.classList.contains(
                    STARTUP_COLLAPSE_CLASS
                )
            )
        );
    }

    function cancelStartupCollapseFrame() {
        if (startupCollapseFrameId === null) {
            return;
        }

        window.cancelAnimationFrame(
            startupCollapseFrameId
        );

        startupCollapseFrameId = null;
    }

    function getPanelTransitionElements() {
        return [
            consolePanel,
            consoleStream,
            memoryPanel,
            memoryPanel
                ? memoryPanel.querySelector(".settings-scroll")
                : null,
        ].filter(Boolean);
    }

    function withoutPanelTransitions(callback) {
        const elements =
            getPanelTransitionElements();

        const previousTransitions =
            elements.map((element) => ({
                element,
                transition:
                    element.style.transition,
            }));

        elements.forEach((element) => {
            element.style.transition =
                "none";
        });

        callback();

        elements.forEach((element) => {
            element.getBoundingClientRect();
        });

        window.requestAnimationFrame(() => {
            previousTransitions.forEach((entry) => {
                if (entry.transition) {
                    entry.element.style.transition =
                        entry.transition;
                } else {
                    entry.element.style.removeProperty(
                        "transition"
                    );
                }
            });
        });
    }

    function expandPanelAfterStartupCancel(panel) {
        if (
            !panel
            || (
                !panel.classList.contains("panel-collapsed")
                && !panel.dataset.expandedHeight
            )
        ) {
            return;
        }

        setPanelCollapsed(
            panel,
            false
        );
    }

    function cancelStartupCollapseAnimation() {
        if (!isStartupCollapseAnimationActive()) {
            return false;
        }

        finishStartupCollapseAnimation();

        withoutPanelTransitions(() => {
            [
                consolePanel,
                memoryPanel,
            ].forEach(
                expandPanelAfterStartupCancel
            );

            syncSceneShadeToPanelCollapse();
        });

        return true;
    }

    function collapsePanelsNow() {
        [
            consolePanel,
            memoryPanel,
        ].forEach((panel) => {
            setPanelCollapsed(
                panel,
                true
            );
        });

        syncSceneShadeToPanelCollapse();
    }

    function collapseAllPanels(options = {}) {
        if (options.startup) {
            beginStartupCollapseAnimation();
            cancelStartupCollapseFrame();

            startupCollapseFrameId =
                window.requestAnimationFrame(
                    function () {
                        startupCollapseFrameId =
                            window.requestAnimationFrame(
                                function () {
                                    startupCollapseFrameId = null;
                                    collapsePanelsNow();
                                }
                            );
                    }
                );

            return;
        }

        finishStartupCollapseAnimation();
        collapsePanelsNow();
    }

    function getPanelResizeBounds(panel) {
        const parentRect =
            panel.parentElement.getBoundingClientRect();

        const panelRect =
            panel.getBoundingClientRect();

        const panelTop =
            panelRect.top - parentRect.top;

        const minHeight =
            Math.round(parentRect.height * 0.49);

        const maxHeight =
            Math.max(
                minHeight,
                parentRect.height - panelTop - PANEL_VIEWPORT_GAP
            );

        return {
            minHeight,
            maxHeight,
        };
    }

    function clampPanelResizeHeight(panel, nextHeight) {
        const bounds =
            getPanelResizeBounds(panel);

        return Math.max(
            bounds.minHeight,
            Math.min(
                nextHeight,
                bounds.maxHeight
            )
        );
    }

    function clampDockedPanelGeometry(panel, dock) {
        const parentRect =
            panel.parentElement.getBoundingClientRect();

        const panelRect =
            panel.getBoundingClientRect();

        const gap =
            getPanelGapPixels(panel);

        const nextTop =
            gap;

        panel.style.top =
            `${nextTop}px`;

        if (dock === "right") {
            panel.style.left =
                "auto";
            panel.style.right =
                `${gap}px`;
        } else {
            panel.style.left =
                `${gap}px`;
            panel.style.right =
                "auto";
        }

        if (panel.classList.contains("panel-collapsed")) {
            return;
        }

        const nextHeight =
            Math.max(
                0,
                parentRect.height - nextTop - gap
            );

        panel.style.height =
            `${nextHeight}px`;
    }

    function clampFreePanelGeometry(panel) {
        const parentRect =
            panel.parentElement.getBoundingClientRect();

        const panelRect =
            panel.getBoundingClientRect();

        const currentLeft =
            panelRect.left - parentRect.left;

        const currentTop =
            panelRect.top - parentRect.top;

        const maxWidth =
            Math.max(
                PANEL_VIEWPORT_GAP,
                parentRect.width - (PANEL_VIEWPORT_GAP * 2)
            );

        const safeWidth =
            Math.min(
                panelRect.width,
                maxWidth
            );

        const maxLeft =
            Math.max(
                PANEL_VIEWPORT_GAP,
                parentRect.width - safeWidth - PANEL_VIEWPORT_GAP
            );

        const nextLeft =
            Math.max(
                PANEL_VIEWPORT_GAP,
                Math.min(
                    currentLeft,
                    maxLeft
                )
            );

        if (panel.classList.contains("panel-collapsed")) {
            const maxTop =
                Math.max(
                    PANEL_VIEWPORT_GAP,
                    parentRect.height - panelRect.height - PANEL_VIEWPORT_GAP
                );

            const nextTop =
                Math.max(
                    PANEL_VIEWPORT_GAP,
                    Math.min(
                        currentTop,
                        maxTop
                    )
                );

            panel.style.left =
                `${nextLeft}px`;

            panel.style.top =
                `${nextTop}px`;

            panel.style.right =
                "auto";

            return;
        }

        const minHeight =
            Math.round(parentRect.height * 0.49);

        const maxTop =
            Math.max(
                PANEL_VIEWPORT_GAP,
                parentRect.height - minHeight - PANEL_VIEWPORT_GAP
            );

        const nextTop =
            Math.max(
                PANEL_VIEWPORT_GAP,
                Math.min(
                    currentTop,
                    maxTop
                )
            );

        const maxHeight =
            Math.max(
                minHeight,
                parentRect.height - nextTop - PANEL_VIEWPORT_GAP
            );

        const nextHeight =
            Math.max(
                minHeight,
                Math.min(
                    panelRect.height,
                    maxHeight
                )
            );

        panel.style.left =
            `${nextLeft}px`;

        panel.style.top =
            `${nextTop}px`;

        panel.style.right =
            "auto";

        panel.style.height =
            `${nextHeight}px`;
    }

    function clampPanelGeometry(panel) {
        if (!panel) {
            return;
        }

        const dock =
            getPanelDock(panel);

        if (dock !== PANEL_DOCK_FREE) {
            clampDockedPanelGeometry(
                panel,
                dock
            );
            return;
        }

        clampFreePanelGeometry(panel);
    }

    function clampAllPanelGeometry() {
        clampPanelGeometry(
            consolePanel
        );

        clampPanelGeometry(
            memoryPanel
        );
    }

    function attachBottomResize(panel) {
        if (!panel) {
            return;
        }

        const resizeHandle =
            document.createElement("div");

        resizeHandle.className =
            "panel-bottom-resize-handle";

        resizeHandle.setAttribute(
            "aria-hidden",
            "true"
        );

        panel.appendChild(
            resizeHandle
        );

        let isResizing =
            false;

        let resizeStartY =
            0;

        let resizeStartHeight =
            0;

        resizeHandle.addEventListener("mousedown", (event) => {
            if (
                event.button !== 0
                || panel.classList.contains("panel-collapsed")
            ) {
                return;
            }

            event.preventDefault();
            event.stopPropagation();

            isResizing =
                true;

            panel.classList.add(
                "panel-resizing"
            );

            resizeStartY =
                event.clientY;

            resizeStartHeight =
                panel.getBoundingClientRect().height;

            document.body.style.cursor =
                "ns-resize";

            document.body.style.userSelect =
                "none";
        });

        window.addEventListener("mousemove", (event) => {
            if (!isResizing) {
                return;
            }

            const nextHeight =
                resizeStartHeight
                + event.clientY
                - resizeStartY;

            panel.style.height =
                `${clampPanelResizeHeight(panel, nextHeight)}px`;
        });

        window.addEventListener("mouseup", () => {
            if (!isResizing) {
                return;
            }

            isResizing =
                false;

            panel.classList.remove(
                "panel-resizing"
            );

            document.body.style.cursor =
                "";

            document.body.style.userSelect =
                "";
        });
    }

    let isConsoleDragging = false;
    let consoleOffsetX = 0;
    let consoleOffsetY = 0;
    let consoleDragStartX = 0;
    let consoleDragStartY = 0;
    let consoleHasMoved = false;

    consoleDragHandle.addEventListener("mousedown", (event) => {
        if (event.detail > 1) {
            return;
        }

        isConsoleDragging = true;

        const rect = consolePanel.getBoundingClientRect();

        consoleOffsetX = event.clientX - rect.left;
        consoleOffsetY = event.clientY - rect.top;
        consoleDragStartX = event.clientX;
        consoleDragStartY = event.clientY;
        consoleHasMoved = false;

        consolePanel.style.right = "auto";
        consolePanel.style.bottom = "auto";
        consolePanel.style.position = "absolute";

        document.body.style.userSelect = "none";
    });

    window.addEventListener("mousemove", (event) => {
        if (!isConsoleDragging) return;

        if (
            !consoleHasMoved
            && (
                Math.abs(event.clientX - consoleDragStartX) > 2
                || Math.abs(event.clientY - consoleDragStartY) > 2
            )
        ) {
            consoleHasMoved = true;
            setPanelFreeDock(consolePanel);
        }

        const parentRect = consolePanel.parentElement.getBoundingClientRect();
        const panelRect = consolePanel.getBoundingClientRect();

        let nextLeft = event.clientX - parentRect.left - consoleOffsetX;
        let nextTop = event.clientY - parentRect.top - consoleOffsetY;

        nextLeft = Math.max(
            PANEL_VIEWPORT_GAP,
            Math.min(
                nextLeft,
                parentRect.width - panelRect.width - PANEL_VIEWPORT_GAP
            )
        );

        nextTop = Math.max(
            PANEL_VIEWPORT_GAP,
            Math.min(
                nextTop,
                parentRect.height - panelRect.height - PANEL_VIEWPORT_GAP
            )
        );

        consolePanel.style.left = `${nextLeft}px`;
        consolePanel.style.top = `${nextTop}px`;
    });

    window.addEventListener("mouseup", () => {
        if (!isConsoleDragging) return;

        isConsoleDragging = false;
        document.body.style.userSelect = "";
    });

    consoleDragHandle.addEventListener("dblclick", (event) => {
        togglePanelCollapseFromHeader(
            event,
            consolePanel,
            consoleDragHandle
        );
    });






const memoryPanel = document.getElementById("settings-panel");
const memoryDragHandle = document.getElementById("memory-drag-handle");
const memoryPanelScrollBody =
    memoryPanel
        ? memoryPanel.querySelector(".settings-scroll")
        : null;
const memoryPanelScrollPlaceholder =
    document.createComment(
        "settings-scroll detached while memory panel is collapsed"
    );
const MEMORY_PANEL_COLLAPSE_SYNC_EVENT =
    "jin:memory-panel-collapse-sync";
let memoryPanelScrollDetachTimer = null;

function dispatchMemoryPanelCollapseSync() {
    window.dispatchEvent(
        new CustomEvent(
            MEMORY_PANEL_COLLAPSE_SYNC_EVENT,
            {
                detail: {
                    collapsed: Boolean(
                        memoryPanel
                        && memoryPanel.classList.contains(
                            "panel-collapsed"
                        )
                    ),
                    bodyMounted: Boolean(
                        memoryPanelScrollBody
                        && memoryPanelScrollBody.isConnected
                    ),
                },
            }
        )
    );
}

function clearMemoryPanelScrollDetachTimer() {
    if (memoryPanelScrollDetachTimer === null) {
        return;
    }

    window.clearTimeout(
        memoryPanelScrollDetachTimer
    );
    memoryPanelScrollDetachTimer = null;
}

function detachMemoryPanelBody() {
    clearMemoryPanelScrollDetachTimer();

    if (
        !memoryPanel
        || !memoryPanelScrollBody
        || memoryPanelScrollBody.parentNode !== memoryPanel
    ) {
        dispatchMemoryPanelCollapseSync();
        return;
    }

    memoryPanel.insertBefore(
        memoryPanelScrollPlaceholder,
        memoryPanelScrollBody
    );
    memoryPanel.removeChild(
        memoryPanelScrollBody
    );
    dispatchMemoryPanelCollapseSync();
}

function attachMemoryPanelBody() {
    clearMemoryPanelScrollDetachTimer();

    if (
        !memoryPanel
        || !memoryPanelScrollBody
    ) {
        dispatchMemoryPanelCollapseSync();
        return;
    }

    if (memoryPanelScrollBody.parentNode === memoryPanel) {
        dispatchMemoryPanelCollapseSync();
        return;
    }

    if (memoryPanelScrollPlaceholder.parentNode === memoryPanel) {
        memoryPanel.insertBefore(
            memoryPanelScrollBody,
            memoryPanelScrollPlaceholder
        );
        memoryPanel.removeChild(
            memoryPanelScrollPlaceholder
        );
    } else {
        memoryPanel.appendChild(
            memoryPanelScrollBody
        );
    }

    dispatchMemoryPanelCollapseSync();
}

function getMemoryPanelScrollDetachDelayMs() {
    if (!memoryPanel) {
        return 0;
    }

    const duration =
        getComputedStyle(memoryPanel)
            .getPropertyValue("--panel-collapse-duration")
            .trim();

    return Math.max(
        0,
        parseCssDurationMs(duration)
    ) + 100;
}

function scheduleMemoryPanelBodyDetach() {
    clearMemoryPanelScrollDetachTimer();

    if (
        !memoryPanel
        || !memoryPanelScrollBody
        || !memoryPanel.classList.contains("panel-collapsed")
    ) {
        attachMemoryPanelBody();
        return;
    }

    memoryPanelScrollDetachTimer =
        window.setTimeout(
            detachMemoryPanelBody,
            getMemoryPanelScrollDetachDelayMs()
        );
}

function syncMemoryPanelBodyMount() {
    if (
        !memoryPanel
        || !memoryPanelScrollBody
    ) {
        dispatchMemoryPanelCollapseSync();
        return;
    }

    if (memoryPanel.classList.contains("panel-collapsed")) {
        scheduleMemoryPanelBodyDetach();
    } else {
        attachMemoryPanelBody();
    }
}

if (memoryPanel && typeof MutationObserver !== "undefined") {
    const memoryPanelBodyObserver =
        new MutationObserver(
            syncMemoryPanelBodyMount
        );

    memoryPanelBodyObserver.observe(
        memoryPanel,
        {
            attributes: true,
            attributeFilter: ["class"],
        }
    );
}

syncMemoryPanelBodyMount();

window.JinPanels =
    Object.assign(
        window.JinPanels || {},
        {
            collapseAllPanels,
            cancelStartupCollapseAnimation,
            refreshCollapsedPanelHeights,
            syncMemoryPanelBodyMount,
            syncSceneShadeToPanelCollapse,
        }
    );

let isMemoryDragging = false;
let memoryOffsetX = 0;
let memoryOffsetY = 0;
let memoryDragStartX = 0;
let memoryDragStartY = 0;
let memoryHasMoved = false;

memoryDragHandle.addEventListener("mousedown", (event) => {
    if (event.detail > 1) {
        return;
    }

    isMemoryDragging = true;

    const rect = memoryPanel.getBoundingClientRect();

    memoryOffsetX = event.clientX - rect.left;
    memoryOffsetY = event.clientY - rect.top;
    memoryDragStartX = event.clientX;
    memoryDragStartY = event.clientY;
    memoryHasMoved = false;

    document.body.style.userSelect = "none";
});

window.addEventListener("mousemove", (event) => {
    if (!isMemoryDragging) return;

    if (
        !memoryHasMoved
        && (
            Math.abs(event.clientX - memoryDragStartX) > 2
            || Math.abs(event.clientY - memoryDragStartY) > 2
        )
    ) {
        memoryHasMoved = true;
        setPanelFreeDock(memoryPanel);
    }

    const parentRect = memoryPanel.parentElement.getBoundingClientRect();
    const panelRect = memoryPanel.getBoundingClientRect();

    let nextLeft =
        event.clientX - parentRect.left - memoryOffsetX;

    let nextTop =
        event.clientY - parentRect.top - memoryOffsetY;

    nextLeft = Math.max(
        PANEL_VIEWPORT_GAP,
        Math.min(
            nextLeft,
            parentRect.width - panelRect.width - PANEL_VIEWPORT_GAP
        )
    );

    nextTop = Math.max(
        PANEL_VIEWPORT_GAP,
        Math.min(
            nextTop,
            parentRect.height - panelRect.height - PANEL_VIEWPORT_GAP
        )
    );

    memoryPanel.style.left = `${nextLeft}px`;
    memoryPanel.style.top = `${nextTop}px`;
    memoryPanel.style.right = "auto";
});

window.addEventListener("mouseup", () => {
    isMemoryDragging = false;
    document.body.style.userSelect = "";
});

memoryDragHandle.addEventListener("dblclick", (event) => {
    togglePanelCollapseFromHeader(
        event,
        memoryPanel,
        memoryDragHandle,
        {
            ignoredTarget:
                document.getElementById("memory-layers-toggle"),
        }
    );
});

attachBottomResize(
    consolePanel
);

attachBottomResize(
    memoryPanel
);

requestAnimationFrame(
    clampAllPanelGeometry
);

window.addEventListener(
    "resize",
    () => {
        clampAllPanelGeometry();
        refreshCollapsedPanelHeights();
    }
);
