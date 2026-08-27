const consoleStream =
  document.getElementById("console-stream");
const attachedDelayedMemory =
  document.getElementById("attached-delayed-memory");

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
    const AVATAR_INSPECTOR_CLOSE_CLASS = "panel-avatar-inspector-closing";
    const COLLAPSED_AVATAR_MIN_PANEL_WIDTH = 96;
    const COLLAPSED_AVATAR_MIN_RUNTIME_SIZE = 96;
    const DEFAULT_JIN_AVATAR_SIZE = 333;
    const COLLAPSED_AVATAR_RESET_ANIMATION_MS = 320;
    const COLLAPSED_AVATAR_SIZE_ANIMATION_MS = 320;
    const ROOM_STATE_RESTORE_DELAY_MS = 1000;
    const ROOM_STATE_RESTORE_TINT_DURATION_MS = 2000;
    const DEFAULT_JIN_AVATAR_MOVE_SPEED = 900;
    const MIN_JIN_AVATAR_MOVE_SPEED = 1;
    const MAX_JIN_AVATAR_MOVE_SPEED = 100000;
    const MAX_JIN_AVATAR_MOVE_DURATION_MS = 60000;
    const COLLAPSED_AVATAR_RESET_EXPAND_DELAY_MS = 420;
    const COLLAPSED_AVATAR_RESET_GEOMETRY_EPSILON = 1;
    const COLLAPSED_AVATAR_RESIZE_EDGES = [
        "n",
        "s",
        "e",
        "w",
        "ne",
        "nw",
        "se",
        "sw",
    ];
    let startupCollapseClassTimer = null;
    let startupCollapseFrameId = null;
    let startupCollapsePreviousDuration = null;
    let collapsedAvatarResetTimer = null;
    let collapsedAvatarResetFrameId = null;
    let collapsedAvatarSizeFrameId = null;
    let collapsedAvatarPositionFrameId = null;
    let avatarInspectorCloseTimer = null;
    let pendingJinSize = null;
    let pendingJinPosition = null;
    let avatarInspectorWorldState = null;
    let jinAvatarMoveSpeed = DEFAULT_JIN_AVATAR_MOVE_SPEED;
    let roomStateRestoreSequence = 0;
    let roomStateRestoreDelayTimer = null;
    let roomStateRestoreFinishTimer = null;
    let roomStateRestoreTintTimer = null;
    let roomStateRestoreTintPreviousDuration = null;
    let roomStateRestoreInProgress = false;
    let roomStateRestoreShouldPersist = false;

    function clearCollapsedAvatarResetTimer() {
        if (collapsedAvatarResetTimer === null) {
            return;
        }

        window.clearTimeout(
            collapsedAvatarResetTimer
        );
        collapsedAvatarResetTimer = null;
    }

    function clearAvatarInspectorCloseTimer() {
        if (avatarInspectorCloseTimer === null) {
            return;
        }

        window.clearTimeout(
            avatarInspectorCloseTimer
        );
        avatarInspectorCloseTimer = null;
    }

    function cancelCollapsedAvatarResetFrame() {
        if (collapsedAvatarResetFrameId === null) {
            return;
        }

        window.cancelAnimationFrame(
            collapsedAvatarResetFrameId
        );
        collapsedAvatarResetFrameId = null;
    }

    function cancelCollapsedAvatarSizeFrame() {
        if (collapsedAvatarSizeFrameId === null) {
            return;
        }

        window.cancelAnimationFrame(
            collapsedAvatarSizeFrameId
        );
        collapsedAvatarSizeFrameId = null;

        if (memoryPanel) {
            memoryPanel.classList.remove(
                "panel-avatar-size-changing"
            );
        }
    }

    function cancelCollapsedAvatarPositionFrame() {
        if (collapsedAvatarPositionFrameId !== null) {
            window.cancelAnimationFrame(
                collapsedAvatarPositionFrameId
            );
            collapsedAvatarPositionFrameId = null;
        }

    }

    function getHeaderAutoHidePanelShift(panel) {
        const api =
            window.JinHeaderAutoHide;

        if (
            !api
            || typeof api.getPanelShift !== "function"
        ) {
            return 0;
        }

        const shift = Number(
            api.getPanelShift(panel)
        );

        return Number.isFinite(shift)
            ? shift
            : 0;
    }

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

    function clampNumber(value, min, max) {
        const safeMin =
            Math.min(
                min,
                max
            );

        const safeMax =
            Math.max(
                min,
                max
            );

        return Math.max(
            safeMin,
            Math.min(
                value,
                safeMax
            )
        );
    }

    function easeInOutCubic(progress) {
        return progress < 0.5
            ? 4 * Math.pow(
                progress,
                3
            )
            : 1 - Math.pow(
                -2 * progress + 2,
                3
            ) / 2;
    }

    function collapsedAvatarGeometryMatches(
        currentGeometry,
        targetGeometry
    ) {
        return [
            "left",
            "top",
            "width",
            "height",
        ].every((key) => (
            Math.abs(
                currentGeometry[key] - targetGeometry[key]
            ) <= COLLAPSED_AVATAR_RESET_GEOMETRY_EPSILON
        ));
    }

    function parseCssPixelValue(value, fallback) {
        const parsed =
            Number.parseFloat(
                String(value || "").trim()
            );

        return Number.isFinite(parsed)
            ? parsed
            : fallback;
    }

    function getRootCssPixelValue(propertyName, fallback) {
        return parseCssPixelValue(
            getComputedStyle(document.documentElement)
                .getPropertyValue(propertyName),
            fallback
        );
    }

    function normalizeJinSizeLength(value) {
        const source = String(value || "").trim();
        const match = source.match(
            /^([+]?(?:\d+(?:\.\d+)?|\.\d+))\s*(px|vw|vh|%)?$/i
        );

        if (!match) {
            return null;
        }

        const amount = Number.parseFloat(match[1]);

        if (!Number.isFinite(amount) || amount <= 0) {
            return null;
        }

        return {
            amount,
            unit: String(match[2] || "px").toLowerCase(),
        };
    }

    function getJinSizeViewportPixels() {
        const root = document.documentElement;
        const width = Number(
            window.innerWidth
            || (root && root.clientWidth)
            || 0
        );
        const height = Number(
            window.innerHeight
            || (root && root.clientHeight)
            || 0
        );

        return {
            width: Math.max(1, width),
            height: Math.max(1, height),
        };
    }

    function resolveJinSizeLengthPixels(value, axis) {
        const normalized = normalizeJinSizeLength(value);

        if (!normalized) {
            return Number.NaN;
        }

        const viewport = getJinSizeViewportPixels();
        let pixels = normalized.amount;

        if (normalized.unit === "vw") {
            pixels = viewport.width * normalized.amount / 100;
        } else if (normalized.unit === "vh") {
            pixels = viewport.height * normalized.amount / 100;
        } else if (normalized.unit === "%") {
            pixels = viewport[axis] * normalized.amount / 100;
        }

        return Math.round(pixels);
    }

    function normalizeJinSizePayload(value) {
        if (
            value
            && typeof value === "object"
        ) {
            const nestedPayload = String(
                value.size || value.payload || ""
            ).trim();

            if (nestedPayload) {
                const nestedSize = normalizeJinSizePayload(
                    nestedPayload
                );

                if (nestedSize) {
                    return nestedSize;
                }
            }

            const rawWidth = value.width ?? value.w;
            const rawHeight = value.height ?? value.h ?? rawWidth;
            const width = resolveJinSizeLengthPixels(
                rawWidth,
                "width"
            );
            const height = resolveJinSizeLengthPixels(
                rawHeight,
                "height"
            );

            if (
                Number.isFinite(width)
                && Number.isFinite(height)
                && width > 0
                && height > 0
            ) {
                return {
                    width,
                    height,
                };
            }
        }

        const source = String(value || "").trim();

        if (!source) {
            return null;
        }

        const length =
            "([+]?(?:\\d+(?:\\.\\d+)?|\\.\\d+)\\s*(?:px|vw|vh|%)?)";
        const single = source.match(
            new RegExp(`^${length}$`, "i")
        );
        const labeled = source.match(
            new RegExp(
                `^(?:w|width)\\s*:\\s*${length}\\s+`
                + `(?:h|height)\\s*:\\s*${length}$`,
                "i"
            )
        );
        const plain = source.match(
            new RegExp(`^${length}\\s+${length}$`, "i")
        );

        const rawWidth = single
            ? single[1]
            : (labeled ? labeled[1] : (plain ? plain[1] : ""));
        const rawHeight = single
            ? single[1]
            : (labeled ? labeled[2] : (plain ? plain[2] : ""));

        if (!rawWidth || !rawHeight) {
            return null;
        }

        const width = resolveJinSizeLengthPixels(
            rawWidth,
            "width"
        );
        const height = resolveJinSizeLengthPixels(
            rawHeight,
            "height"
        );

        if (
            !Number.isFinite(width)
            || !Number.isFinite(height)
            || width <= 0
            || height <= 0
        ) {
            return null;
        }

        return {
            width,
            height,
        };
    }

    function normalizeJinPositionPayload(value) {
        if (value && typeof value === "object") {
            const x = Number.parseInt(value.x, 10);
            const y = Number.parseInt(value.y, 10);

            if (
                Number.isFinite(x)
                && Number.isFinite(y)
            ) {
                return { x, y };
            }
        }

        const source = String(value || "").trim();

        if (!source) {
            return null;
        }

        const labeled = source.match(
            /^x\s*:\s*([+-]?\d+)(?:px)?\s+y\s*:\s*([+-]?\d+)(?:px)?$/i
        );

        if (labeled) {
            return {
                x: Number.parseInt(labeled[1], 10),
                y: Number.parseInt(labeled[2], 10),
            };
        }

        const plain = source.match(
            /^([+-]?\d+)(?:px)?\s+([+-]?\d+)(?:px)?$/i
        );

        if (!plain) {
            return null;
        }

        return {
            x: Number.parseInt(plain[1], 10),
            y: Number.parseInt(plain[2], 10),
        };
    }

    function normalizeJinSpeedPayload(value) {
        let speed = Number.NaN;

        if (typeof value === "number") {
            speed = value;
        } else {
            const source = String(value || "").trim();
            const match = source.match(
                /^(\d+(?:\.\d+)?)\s*(?:px\s*\/\s*s|pxps|px\s*\/\s*sec|px\s*\/\s*second)?$/i
            );

            if (match) {
                speed = Number.parseFloat(match[1]);
            }
        }

        if (!Number.isFinite(speed) || speed <= 0) {
            return null;
        }

        return Math.round(
            clampNumber(
                speed,
                MIN_JIN_AVATAR_MOVE_SPEED,
                MAX_JIN_AVATAR_MOVE_SPEED
            )
        );
    }

    function formatJinSizePayload(size) {
        const normalized =
            normalizeJinSizePayload(
                size
            );

        if (!normalized) {
            return "";
        }

        return normalized.width === normalized.height
            ? `${normalized.width}px`
            : `w:${normalized.width}px h:${normalized.height}px`;
    }

    function resolveCssLengthTermPixels(term, fallback) {
        const value =
            String(term || "").trim();

        if (!value) {
            return fallback;
        }

        const parsed =
            Number.parseFloat(value);

        if (!Number.isFinite(parsed)) {
            return fallback;
        }

        if (value.endsWith("px")) {
            return parsed;
        }

        if (value.endsWith("vh")) {
            return window.innerHeight * parsed / 100;
        }

        if (value.endsWith("vw")) {
            return window.innerWidth * parsed / 100;
        }

        if (value.endsWith("rem")) {
            return parsed * parseCssPixelValue(
                getComputedStyle(document.documentElement).fontSize,
                16
            );
        }

        return fallback;
    }

    function resolveCssLengthPixels(value, fallback) {
        const rawValue =
            String(value || "").trim();

        if (!rawValue) {
            return fallback;
        }

        const clampMatch =
            rawValue.match(
                /^clamp\((.+),(.+),(.+)\)$/i
            );

        if (clampMatch) {
            const min =
                resolveCssLengthTermPixels(
                    clampMatch[1],
                    fallback
                );

            const preferred =
                resolveCssLengthTermPixels(
                    clampMatch[2],
                    fallback
                );

            const max =
                resolveCssLengthTermPixels(
                    clampMatch[3],
                    fallback
                );

            return clampNumber(
                preferred,
                min,
                max
            );
        }

        const parsed =
            parseCssPixelValue(
                rawValue,
                Number.NaN
            );

        if (
            Number.isFinite(parsed)
            && rawValue.endsWith("px")
        ) {
            return parsed;
        }

        const probe =
            document.createElement("div");

        probe.style.position =
            "absolute";
        probe.style.visibility =
            "hidden";
        probe.style.pointerEvents =
            "none";
        probe.style.width =
            rawValue;
        probe.style.height =
            rawValue;

        document.body.appendChild(
            probe
        );

        const rect =
            probe.getBoundingClientRect();

        probe.remove();

        return rect.width > 0
            ? rect.width
            : fallback;
    }

    function getDefaultRuntimeAvatarSize() {
        const rawSize =
            getComputedStyle(document.documentElement)
                .getPropertyValue("--runtime-avatar-panel-size")
                .trim();

        const fallback =
            memoryDragHandle
                ? memoryDragHandle.getBoundingClientRect().height
                : 333;

        return resolveCssLengthPixels(
            rawSize,
            fallback
        );
    }

    function getDefaultPanelWidth() {
        const rawWidth =
            getComputedStyle(document.documentElement)
                .getPropertyValue("--memory-panel-width")
                .trim();

        return resolveCssLengthPixels(
            rawWidth,
            333
        );
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

        if (panel === memoryPanel) {
            clearAvatarInspectorCloseTimer();
            panel.classList.remove(AVATAR_INSPECTOR_CLOSE_CLASS);
        }

        if (collapsed) {
            const inspectorWorldState =
                panel === memoryPanel
                    ? takeAvatarWorldStateForInspectorClose()
                    : null;

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

            let pendingJinSizeResult =
                null;

            if (panel === memoryPanel) {
                if (inspectorWorldState) {
                    pendingJinSizeResult =
                        animateCollapsedAvatarWorldState(
                            panel,
                            inspectorWorldState
                        );
                } else {
                    pendingJinSizeResult =
                        applyPendingJinSizeToCollapsedAvatar(
                            panel
                        );

                    applyPendingJinPositionToCollapsedAvatar(
                        panel
                    );
                }
            }

            if (
                !pendingJinSizeResult
                || pendingJinSizeResult.animated !== true
            ) {
                clampPanelGeometry(panel);
            }

            syncCollapsedPanelBodies();

            return;
        }

        if (panel === memoryPanel) {
            cancelCollapsedAvatarSizeFrame();
            cancelCollapsedAvatarPositionFrame();
        }

        if (panel === consolePanel) {
            attachConsolePanelBody();
        }

        if (panel === memoryPanel) {
            attachMemoryPanelBody();
        }

        const expandedHeight =
            panel.dataset.expandedHeight || "";
        const expandFromCollapsed =
            Boolean(expandedHeight);

        panel.classList.remove(
            "panel-collapsed"
        );

        if (expandedHeight) {
            panel.style.height =
                expandedHeight;
        } else {
            panel.style.removeProperty(
                "height"
            );
        }

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

        clampPanelGeometry(
            panel,
            {
                expandFromCollapsed,
            }
        );
        syncCollapsedPanelBodies();

        if (panel === consolePanel && consoleStream) {
            window.requestAnimationFrame(() => {
                window.requestAnimationFrame(() => {
                    consoleStream.scrollTo({
                        top: consoleStream.scrollHeight,
                        behavior: "smooth",
                    });
                });
            });
        }
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

    function getCollapsedAvatarFrameHeight(panel) {
        const style =
            getComputedStyle(panel);

        return (
            parseCssPixelValue(
                style.borderTopWidth,
                0
            )
            + parseCssPixelValue(
                style.borderBottomWidth,
                0
            )
        );
    }

    function getCollapsedPanelHeight(panel) {
        if (panel === memoryPanel && memoryDragHandle) {
            return `${
                Math.round(
                    memoryDragHandle.getBoundingClientRect().height
                    + getCollapsedAvatarFrameHeight(panel)
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

    function getPanelCollapseDurationMs(panel) {
        if (!panel) {
            return 0;
        }

        return Math.max(
            0,
            parseCssDurationMs(
                getComputedStyle(panel)
                    .getPropertyValue("--panel-collapse-duration")
                    .trim()
            )
        );
    }

    function finishAvatarInspectorClose(panel) {
        if (
            !panel
            || !panel.classList.contains(AVATAR_INSPECTOR_CLOSE_CLASS)
        ) {
            return false;
        }

        clearAvatarInspectorCloseTimer();
        setPanelCollapsed(panel, true);
        syncSceneShadeToPanelCollapse();
        return true;
    }

    function collapseAvatarInspectorBeforeWorldRestore(panel) {
        if (
            panel !== memoryPanel
            || panel.classList.contains("panel-collapsed")
            || !avatarInspectorWorldState
        ) {
            return false;
        }

        if (panel.classList.contains(AVATAR_INSPECTOR_CLOSE_CLASS)) {
            return true;
        }

        finishStartupCollapseAnimation();
        clearAvatarInspectorCloseTimer();
        registerPanelRuntimeActivity(panel);
        panel.classList.add(AVATAR_INSPECTOR_CLOSE_CLASS);

        if (prefersReducedMotion()) {
            finishAvatarInspectorClose(panel);
            return true;
        }

        avatarInspectorCloseTimer = window.setTimeout(
            () => {
                finishAvatarInspectorClose(panel);
            },
            getPanelCollapseDurationMs(panel) + 24
        );

        return true;
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
                ? memoryPanel.querySelector(".memory-scroll")
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

    function isCollapsedMemoryAvatarPanel(panel) {
        return Boolean(
            panel
            && panel === memoryPanel
            && panel.classList.contains("panel-collapsed")
        );
    }

    function getCollapsedAvatarResizeBounds(panel) {
        const parentRect =
            panel.parentElement.getBoundingClientRect();

        const gap =
            getPanelGapPixels(panel);

        const frameHeight =
            getCollapsedAvatarFrameHeight(panel);

        const maxWidth =
            Math.max(
                1,
                parentRect.width - (gap * 2)
            );

        const maxHeight =
            Math.max(
                1,
                parentRect.height - (gap * 2)
            );

        const minWidth =
            Math.min(
                COLLAPSED_AVATAR_MIN_PANEL_WIDTH,
                maxWidth
            );

        const minHeight =
            Math.min(
                COLLAPSED_AVATAR_MIN_RUNTIME_SIZE + frameHeight,
                maxHeight
            );

        return {
            parentRect,
            gap,
            frameHeight,
            minWidth,
            minHeight,
            maxWidth,
            maxHeight,
        };
    }

    function applyCollapsedAvatarSize(panel, width, height) {
        const bounds =
            getCollapsedAvatarResizeBounds(panel);

        const nextWidth =
            Math.round(
                clampNumber(
                    width,
                    bounds.minWidth,
                    bounds.maxWidth
                )
            );

        const nextHeight =
            Math.round(
                clampNumber(
                    height,
                    bounds.minHeight,
                    bounds.maxHeight
                )
            );

        const runtimeAvatarSize =
            Math.max(
                1,
                nextHeight - bounds.frameHeight
            );

        panel.style.width =
            `${nextWidth}px`;

        panel.style.setProperty(
            "--runtime-avatar-panel-size",
            `${Math.round(runtimeAvatarSize)}px`
        );

        const collapsedHeight =
            `${nextHeight}px`;

        panel.style.height =
            collapsedHeight;
        panel.style.minHeight =
            collapsedHeight;
        panel.style.maxHeight =
            collapsedHeight;

        return {
            width: nextWidth,
            height: nextHeight,
            bounds,
        };
    }

    function applyJinSizeToCollapsedAvatar(panel, size) {
        const normalized =
            normalizeJinSizePayload(
                size
            );

        if (
            !normalized
            || !isCollapsedMemoryAvatarPanel(panel)
        ) {
            return null;
        }

        const bounds =
            getCollapsedAvatarResizeBounds(panel);

        const targetHeight =
            normalized.height + bounds.frameHeight;

        return animateCollapsedAvatarSize(
            panel,
            normalized.width,
            targetHeight
        );
    }

    function applyPendingJinSizeToCollapsedAvatar(panel) {
        if (
            !pendingJinSize
            || !isCollapsedMemoryAvatarPanel(panel)
        ) {
            return false;
        }

        const applied =
            applyJinSizeToCollapsedAvatar(
                panel,
                pendingJinSize
            );

        if (!applied) {
            return false;
        }

        pendingJinSize = null;

        return applied;
    }

    function setPendingJinSize(size) {
        const normalized =
            normalizeJinSizePayload(
                size
            );

        if (!normalized) {
            return false;
        }

        pendingJinSize = normalized;

        if (
            isCollapsedMemoryAvatarPanel(memoryPanel)
            && !avatarInspectorWorldState
        ) {
            return applyPendingJinSizeToCollapsedAvatar(
                memoryPanel
            );
        }

        return true;
    }

    function setJinMoveSpeed(speed) {
        const normalized = normalizeJinSpeedPayload(speed);

        if (normalized === null) {
            return false;
        }

        jinAvatarMoveSpeed = normalized;
        scheduleRoomStatePersist();
        return true;
    }

    function getJinMoveSpeed() {
        return jinAvatarMoveSpeed;
    }

    function resolveCollapsedAvatarPositionTarget(panel, position) {
        if (
            !panel
            || !panel.parentElement
        ) {
            return null;
        }

        const normalized = normalizeJinPositionPayload(position);

        if (!normalized) {
            return null;
        }

        const parentRect = panel.parentElement.getBoundingClientRect();
        const panelRect = panel.getBoundingClientRect();
        const gap = getPanelGapPixels(panel);
        const maxLeft = Math.max(
            gap,
            parentRect.width - panelRect.width - gap
        );
        const maxTop = Math.max(
            gap,
            parentRect.height - panelRect.height - gap
        );

        return {
            startLeft: panelRect.left - parentRect.left,
            startTop: panelRect.top - parentRect.top,
            targetLeft: clampNumber(
                normalized.x
                - parentRect.left
                - (panelRect.width / 2),
                gap,
                maxLeft
            ),
            targetTop: clampNumber(
                normalized.y
                - parentRect.top
                - (panelRect.height / 2),
                gap,
                maxTop
            ),
        };
    }

    function applyCollapsedAvatarPosition(panel, left, top) {
        if (!panel) {
            return;
        }

        setPanelFreeDock(panel);
        panel.style.left = `${Math.round(left)}px`;
        panel.style.top = `${Math.round(top)}px`;
        panel.style.right = "auto";
        panel.style.bottom = "auto";
    }

    function animateCollapsedAvatarPosition(panel, position) {
        if (!isCollapsedMemoryAvatarPanel(panel)) {
            return null;
        }

        const resolved = resolveCollapsedAvatarPositionTarget(
            panel,
            position
        );

        if (!resolved) {
            return null;
        }

        cancelCollapsedAvatarPositionFrame();
        cancelCollapsedAvatarResetFrame();
        clearCollapsedAvatarResetTimer();
        registerPanelRuntimeActivity(panel);

        const deltaX = resolved.targetLeft - resolved.startLeft;
        const deltaY = resolved.targetTop - resolved.startTop;
        const distance = Math.hypot(deltaX, deltaY);
        const speed = Math.max(
            MIN_JIN_AVATAR_MOVE_SPEED,
            Number(jinAvatarMoveSpeed) || DEFAULT_JIN_AVATAR_MOVE_SPEED
        );
        const duration = Math.min(
            MAX_JIN_AVATAR_MOVE_DURATION_MS,
            Math.max(16, distance / speed * 1000)
        );

        if (
            prefersReducedMotion()
            || distance < 1
            || duration <= 16
        ) {
            applyCollapsedAvatarPosition(
                panel,
                resolved.targetLeft,
                resolved.targetTop
            );

            return {
                animated: false,
                x: resolved.targetLeft,
                y: resolved.targetTop,
                speed,
            };
        }

        const startTime = window.performance.now();

        const animatePosition = (timestamp) => {
            const rawProgress = clampNumber(
                (timestamp - startTime) / duration,
                0,
                1
            );
            const progress =
                easeInOutCubic(rawProgress);

            applyCollapsedAvatarPosition(
                panel,
                resolved.startLeft + deltaX * progress,
                resolved.startTop + deltaY * progress
            );
            if (rawProgress < 1) {
                collapsedAvatarPositionFrameId =
                    window.requestAnimationFrame(
                        animatePosition
                    );
                return;
            }

            collapsedAvatarPositionFrameId = null;
        };

        collapsedAvatarPositionFrameId =
            window.requestAnimationFrame(
                animatePosition
            );

        return {
            animated: true,
            x: resolved.targetLeft,
            y: resolved.targetTop,
            speed,
            duration,
        };
    }

    function applyPendingJinPositionToCollapsedAvatar(panel) {
        if (
            !pendingJinPosition
            || !isCollapsedMemoryAvatarPanel(panel)
        ) {
            return false;
        }

        const applied = animateCollapsedAvatarPosition(
            panel,
            pendingJinPosition
        );

        if (!applied) {
            return false;
        }

        pendingJinPosition = null;
        return applied;
    }

    function setPendingJinPosition(position) {
        const normalized = normalizeJinPositionPayload(position);

        if (!normalized) {
            return false;
        }

        pendingJinPosition = normalized;

        if (
            isCollapsedMemoryAvatarPanel(memoryPanel)
            && !avatarInspectorWorldState
        ) {
            return applyPendingJinPositionToCollapsedAvatar(
                memoryPanel
            );
        }

        return true;
    }

    function captureCollapsedAvatarWorldState(panel) {
        if (!isCollapsedMemoryAvatarPanel(panel)) {
            return null;
        }

        const snapshot = getRuntimeAvatarSnapshot();

        if (!snapshot || snapshot.collapsed !== true) {
            return null;
        }

        return {
            size: {
                width: snapshot.width,
                height: snapshot.height,
            },
            position: {
                x: snapshot.x,
                y: snapshot.y,
            },
        };
    }

    function beginAvatarInspector(panel) {
        const worldState =
            captureCollapsedAvatarWorldState(panel);

        if (!worldState) {
            return false;
        }

        avatarInspectorWorldState = worldState;
        return true;
    }

    function takeAvatarWorldStateForInspectorClose() {
        if (!avatarInspectorWorldState) {
            return null;
        }

        const worldState = {
            size: pendingJinSize
                ? { ...pendingJinSize }
                : { ...avatarInspectorWorldState.size },
            position: pendingJinPosition
                ? { ...pendingJinPosition }
                : { ...avatarInspectorWorldState.position },
        };

        pendingJinSize = null;
        pendingJinPosition = null;
        avatarInspectorWorldState = null;

        return worldState;
    }

    function getRuntimeAvatarSnapshot() {
        const collapsed =
            Boolean(
                memoryPanel
                && memoryPanel.classList.contains(
                    "panel-collapsed"
                )
            );

        if (
            collapsed
            && memoryPanel
        ) {
            const rect =
                memoryPanel.getBoundingClientRect();
            const runtimeHeight =
                Math.max(
                    1,
                    Math.round(
                        rect.height
                        - getCollapsedAvatarFrameHeight(
                            memoryPanel
                        )
                    )
                );

            const headerShift =
                getHeaderAutoHidePanelShift(
                    memoryPanel
                );

            return {
                collapsed: true,
                width: Math.max(
                    1,
                    Math.round(rect.width)
                ),
                height: runtimeHeight,
                size: formatJinSizePayload({
                    width: Math.max(
                        1,
                        Math.round(rect.width)
                    ),
                    height: runtimeHeight,
                }),
                x: Math.round(
                    rect.left + (rect.width / 2)
                ),
                y: Math.round(
                    rect.top
                    + (rect.height / 2)
                    - headerShift
                ),
                speed_px_per_second: getJinMoveSpeed(),
                window_width: Math.max(1, Math.round(window.innerWidth)),
                window_height: Math.max(1, Math.round(window.innerHeight)),
            };
        }

        const rect = memoryPanel
            ? memoryPanel.getBoundingClientRect()
            : null;
        const headerShift =
            getHeaderAutoHidePanelShift(
                memoryPanel
            );

        return {
            collapsed: false,
            width: DEFAULT_JIN_AVATAR_SIZE,
            height: DEFAULT_JIN_AVATAR_SIZE,
            size: `${DEFAULT_JIN_AVATAR_SIZE}px`,
            x: rect
                ? Math.round(rect.left + (rect.width / 2))
                : 0,
            y: rect
                ? Math.round(
                    rect.top
                    + (rect.height / 2)
                    - headerShift
                )
                : 0,
            speed_px_per_second: getJinMoveSpeed(),
            window_width: Math.max(1, Math.round(window.innerWidth)),
            window_height: Math.max(1, Math.round(window.innerHeight)),
        };
    }

    function clampCollapsedAvatarSizeToViewport(panel) {
        if (
            !isCollapsedMemoryAvatarPanel(panel)
            || !panel.parentElement
        ) {
            return null;
        }

        const panelRect =
            panel.getBoundingClientRect();

        const styledHeight =
            parseCssPixelValue(
                panel.style.height,
                Number.NaN
            );

        return applyCollapsedAvatarSize(
            panel,
            panelRect.width,
            Number.isFinite(styledHeight)
                ? styledHeight
                : panelRect.height
        );
    }

    function applyCollapsedAvatarGeometry(panel, geometry) {
        const size =
            applyCollapsedAvatarSize(
                panel,
                geometry.width,
                geometry.height
            );

        const bounds =
            size.bounds;

        const maxLeft =
            Math.max(
                bounds.gap,
                bounds.parentRect.width - size.width - bounds.gap
            );

        const maxTop =
            Math.max(
                bounds.gap,
                bounds.parentRect.height - size.height - bounds.gap
            );

        panel.style.left =
            `${
                Math.round(
                    clampNumber(
                        geometry.left,
                        bounds.gap,
                        maxLeft
                    )
                )
            }px`;

        panel.style.top =
            `${
                Math.round(
                    clampNumber(
                        geometry.top,
                        bounds.gap,
                        maxTop
                    )
                )
            }px`;

        panel.style.right =
            "auto";

        panel.style.bottom =
            "auto";
    }

    function getCollapsedAvatarCurrentGeometry(panel) {
        const parentRect =
            panel.parentElement.getBoundingClientRect();

        const panelRect =
            panel.getBoundingClientRect();

        return {
            left:
                panelRect.left - parentRect.left,
            top:
                panelRect.top - parentRect.top,
            width:
                panelRect.width,
            height:
                panelRect.height,
        };
    }

    function resolveCollapsedAvatarSizeTargetGeometry(
        panel,
        width,
        height
    ) {
        const bounds =
            getCollapsedAvatarResizeBounds(panel);

        const currentGeometry =
            getCollapsedAvatarCurrentGeometry(panel);

        const targetWidth =
            Math.round(
                clampNumber(
                    width,
                    bounds.minWidth,
                    bounds.maxWidth
                )
            );

        const targetHeight =
            Math.round(
                clampNumber(
                    height,
                    bounds.minHeight,
                    bounds.maxHeight
                )
            );

        const maxLeft =
            Math.max(
                bounds.gap,
                bounds.parentRect.width - targetWidth - bounds.gap
            );

        const maxTop =
            Math.max(
                bounds.gap,
                bounds.parentRect.height - targetHeight - bounds.gap
            );

        const dock =
            getPanelDock(panel);

        let targetLeft =
            currentGeometry.left;

        if (dock === "right") {
            targetLeft =
                maxLeft;
        } else if (dock === "left") {
            targetLeft =
                bounds.gap;
        } else {
            targetLeft =
                clampNumber(
                    currentGeometry.left,
                    bounds.gap,
                    maxLeft
                );
        }

        const targetTop =
            clampNumber(
                currentGeometry.top,
                bounds.gap,
                maxTop
            );

        return {
            bounds,
            currentGeometry,
            targetGeometry: {
                left:
                    Math.round(targetLeft),
                top:
                    Math.round(targetTop),
                width:
                    targetWidth,
                height:
                    targetHeight,
            },
        };
    }

    function prefersReducedMotion() {
        return Boolean(
            window.matchMedia
            && window.matchMedia(
                "(prefers-reduced-motion: reduce)"
            ).matches
        );
    }

    function registerPanelRuntimeActivity(panel) {
        if (!panel) {
            return;
        }

        panel.dispatchEvent(
            new CustomEvent(
                "jin:panel-activity"
            )
        );

        panel.classList.remove(
            "panel-inactive"
        );
    }

    function resolveCollapsedAvatarWorldTargetGeometry(panel, worldState) {
        const size = normalizeJinSizePayload(
            worldState && worldState.size
        );
        const position = normalizeJinPositionPayload(
            worldState && worldState.position
        );

        if (!size || !position || !panel.parentElement) {
            return null;
        }

        const bounds = getCollapsedAvatarResizeBounds(panel);
        const currentGeometry = getCollapsedAvatarCurrentGeometry(panel);
        const targetWidth = Math.round(
            clampNumber(size.width, bounds.minWidth, bounds.maxWidth)
        );
        const targetHeight = Math.round(
            clampNumber(
                size.height + bounds.frameHeight,
                bounds.minHeight,
                bounds.maxHeight
            )
        );
        const maxLeft = Math.max(
            bounds.gap,
            bounds.parentRect.width - targetWidth - bounds.gap
        );
        const maxTop = Math.max(
            bounds.gap,
            bounds.parentRect.height - targetHeight - bounds.gap
        );

        return {
            currentGeometry,
            targetGeometry: {
                left: Math.round(
                    clampNumber(
                        position.x
                        - bounds.parentRect.left
                        - (targetWidth / 2),
                        bounds.gap,
                        maxLeft
                    )
                ),
                top: Math.round(
                    clampNumber(
                        position.y
                        - bounds.parentRect.top
                        - (targetHeight / 2),
                        bounds.gap,
                        maxTop
                    )
                ),
                width: targetWidth,
                height: targetHeight,
            },
        };
    }

    function animateCollapsedAvatarWorldState(panel, worldState) {
        const resolved = resolveCollapsedAvatarWorldTargetGeometry(
            panel,
            worldState
        );

        if (!resolved) {
            return null;
        }

        const startGeometry = resolved.currentGeometry;
        const targetGeometry = resolved.targetGeometry;

        cancelCollapsedAvatarSizeFrame();
        cancelCollapsedAvatarPositionFrame();
        cancelCollapsedAvatarResetFrame();
        clearCollapsedAvatarResetTimer();
        registerPanelRuntimeActivity(panel);
        setPanelFreeDock(panel);

        panel.style.left = `${Math.round(startGeometry.left)}px`;
        panel.style.top = `${Math.round(startGeometry.top)}px`;
        panel.style.right = "auto";
        panel.style.bottom = "auto";

        if (
            prefersReducedMotion()
            || collapsedAvatarGeometryMatches(startGeometry, targetGeometry)
        ) {
            applyCollapsedAvatarGeometry(panel, targetGeometry);
            return { animated: false };
        }

        panel.classList.add("panel-avatar-size-changing");

        const startTime = window.performance.now();
        const animateWorldState = (timestamp) => {
            const rawProgress = clampNumber(
                (timestamp - startTime) / COLLAPSED_AVATAR_SIZE_ANIMATION_MS,
                0,
                1
            );
            const progress = easeInOutCubic(rawProgress);

            applyCollapsedAvatarGeometry(
                panel,
                {
                    left: startGeometry.left
                        + (targetGeometry.left - startGeometry.left) * progress,
                    top: startGeometry.top
                        + (targetGeometry.top - startGeometry.top) * progress,
                    width: startGeometry.width
                        + (targetGeometry.width - startGeometry.width) * progress,
                    height: startGeometry.height
                        + (targetGeometry.height - startGeometry.height) * progress,
                }
            );

            if (rawProgress < 1) {
                collapsedAvatarSizeFrameId = window.requestAnimationFrame(
                    animateWorldState
                );
                return;
            }

            collapsedAvatarSizeFrameId = null;
            applyCollapsedAvatarGeometry(panel, targetGeometry);
            panel.classList.remove("panel-avatar-size-changing");
        };

        collapsedAvatarSizeFrameId = window.requestAnimationFrame(
            animateWorldState
        );

        return { animated: true };
    }

    function animateCollapsedAvatarSize(panel, width, height) {
        const resolved =
            resolveCollapsedAvatarSizeTargetGeometry(
                panel,
                width,
                height
            );

        const startGeometry =
            resolved.currentGeometry;

        const targetGeometry =
            resolved.targetGeometry;

        cancelCollapsedAvatarSizeFrame();
        cancelCollapsedAvatarResetFrame();
        clearCollapsedAvatarResetTimer();
        registerPanelRuntimeActivity(panel);

        setPanelFreeDock(panel);

        panel.style.left =
            `${Math.round(startGeometry.left)}px`;
        panel.style.top =
            `${Math.round(startGeometry.top)}px`;
        panel.style.right =
            "auto";
        panel.style.bottom =
            "auto";

        if (
            prefersReducedMotion()
            || collapsedAvatarGeometryMatches(
                startGeometry,
                targetGeometry
            )
        ) {
            applyCollapsedAvatarGeometry(
                panel,
                targetGeometry
            );

            return {
                animated: false,
                duration: 0,
                bounds:
                    resolved.bounds,
                width:
                    targetGeometry.width,
                height:
                    targetGeometry.height,
            };        }

        panel.classList.add(
            "panel-avatar-size-changing"
        );

        const startTime =
            window.performance.now();

        const animateSize = (timestamp) => {
            const elapsed =
                timestamp - startTime;

            const rawProgress =
                clampNumber(
                    elapsed / COLLAPSED_AVATAR_SIZE_ANIMATION_MS,
                    0,
                    1
                );

            const progress =
                easeInOutCubic(rawProgress);

            applyCollapsedAvatarGeometry(
                panel,
                {
                    left:
                        startGeometry.left
                        + (
                            targetGeometry.left
                            - startGeometry.left
                        ) * progress,
                    top:
                        startGeometry.top
                        + (
                            targetGeometry.top
                            - startGeometry.top
                        ) * progress,
                    width:
                        startGeometry.width
                        + (
                            targetGeometry.width
                            - startGeometry.width
                        ) * progress,
                    height:
                        startGeometry.height
                        + (
                            targetGeometry.height
                            - startGeometry.height
                        ) * progress,
                }
            );

            if (rawProgress < 1) {
                collapsedAvatarSizeFrameId =
                    window.requestAnimationFrame(
                        animateSize
                    );
                return;
            }

            collapsedAvatarSizeFrameId =
                null;

            applyCollapsedAvatarGeometry(
                panel,
                targetGeometry
            );

            panel.classList.remove(
                "panel-avatar-size-changing"
            );
        };

        collapsedAvatarSizeFrameId =
            window.requestAnimationFrame(
                animateSize
            );

        return {
            animated: true,
            duration:
                COLLAPSED_AVATAR_SIZE_ANIMATION_MS,
            bounds:
                resolved.bounds,
            width:
                targetGeometry.width,
            height:
                targetGeometry.height,
        };    }

    function clampCollapsedAvatarGeometry(panel) {
        const size =
            clampCollapsedAvatarSizeToViewport(panel);

        if (!size) {
            return;
        }

        const bounds =
            size.bounds;

        const dock =
            getPanelDock(panel);

        if (dock === "right") {
            panel.style.left =
                "auto";
            panel.style.right =
                `${bounds.gap}px`;
            panel.style.top =
                `${bounds.gap}px`;
            panel.style.bottom =
                "auto";
            return;
        }

        if (dock === "left") {
            panel.style.left =
                `${bounds.gap}px`;
            panel.style.right =
                "auto";
            panel.style.top =
                `${bounds.gap}px`;
            panel.style.bottom =
                "auto";
            return;
        }

        const panelRect =
            panel.getBoundingClientRect();

        const currentLeft =
            panelRect.left - bounds.parentRect.left;

        const currentTop =
            panelRect.top - bounds.parentRect.top;

        applyCollapsedAvatarGeometry(
            panel,
            {
                left: currentLeft,
                top: currentTop,
                width: size.width,
                height: size.height,
            }
        );
    }

    function resetCollapsedAvatarToDefault(panel) {
        if (
            !isCollapsedMemoryAvatarPanel(panel)
            || !panel.parentElement
        ) {
            return false;
        }

        const parentRect =
            panel.parentElement.getBoundingClientRect();

        const panelRect =
            panel.getBoundingClientRect();

        const centerX =
            panelRect.left - parentRect.left + (panelRect.width / 2);

        const centerY =
            panelRect.top - parentRect.top + (panelRect.height / 2);

        cancelCollapsedAvatarSizeFrame();
        cancelCollapsedAvatarResetFrame();

        const defaultRuntimeAvatarSize =
            getDefaultRuntimeAvatarSize();

        const defaultCollapsedHeight =
            defaultRuntimeAvatarSize
            + getCollapsedAvatarFrameHeight(panel);

        const bounds =
            getCollapsedAvatarResizeBounds(panel);

        const targetWidth =
            clampNumber(
                getDefaultPanelWidth(),
                bounds.minWidth,
                bounds.maxWidth
            );

        setPanelFreeDock(panel);

        const targetHeight =
            clampNumber(
                defaultCollapsedHeight,
                bounds.minHeight,
                bounds.maxHeight
            );

        const maxLeft =
            Math.max(
                bounds.gap,
                parentRect.width - targetWidth - bounds.gap
            );

        const maxTop =
            Math.max(
                bounds.gap,
                parentRect.height - targetHeight - bounds.gap
            );

        const targetLeft =
            clampNumber(
                centerX - (targetWidth / 2),
                bounds.gap,
                maxLeft
            );

        const targetTop =
            clampNumber(
                centerY - (targetHeight / 2),
                bounds.gap,
                maxTop
            );

        panel.style.right =
            "auto";

        panel.style.bottom =
            "auto";

        const startGeometry = {
            left: panelRect.left - parentRect.left,
            top: panelRect.top - parentRect.top,
            width: panelRect.width,
            height: panelRect.height,
        };

        const targetGeometry = {
            left: targetLeft,
            top: targetTop,
            width: targetWidth,
            height: targetHeight,
        };

        if (
            collapsedAvatarGeometryMatches(
                startGeometry,
                targetGeometry
            )
        ) {
            applyCollapsedAvatarGeometry(
                panel,
                targetGeometry
            );
            return false;
        }

        panel.classList.add(
            "panel-avatar-resetting"
        );

        const startTime =
            window.performance.now();

        const animateReset = (timestamp) => {
            const elapsed =
                timestamp - startTime;

            const rawProgress =
                clampNumber(
                    elapsed / COLLAPSED_AVATAR_RESET_ANIMATION_MS,
                    0,
                    1
                );

            const progress =
                easeInOutCubic(rawProgress);

            applyCollapsedAvatarGeometry(
                panel,
                {
                    left:
                        startGeometry.left
                        + (
                            targetGeometry.left
                            - startGeometry.left
                        ) * progress,
                    top:
                        startGeometry.top
                        + (
                            targetGeometry.top
                            - startGeometry.top
                        ) * progress,
                    width:
                        startGeometry.width
                        + (
                            targetGeometry.width
                            - startGeometry.width
                        ) * progress,
                    height:
                        startGeometry.height
                        + (
                            targetGeometry.height
                            - startGeometry.height
                        ) * progress,
                }
            );

            if (rawProgress < 1) {
                collapsedAvatarResetFrameId =
                    window.requestAnimationFrame(
                        animateReset
                    );
                return;
            }

            collapsedAvatarResetFrameId =
                null;
        };

        collapsedAvatarResetFrameId =
            window.requestAnimationFrame(
                animateReset
            );

        return true;
    }

    function finishCollapsedAvatarResetAndExpand(panel) {
        if (!panel) {
            return;
        }

        clearCollapsedAvatarResetTimer();

        const bounds =
            panel.parentElement
                ? getCollapsedAvatarResizeBounds(panel)
                : null;

        const defaultWidth =
            getDefaultPanelWidth();

        cancelCollapsedAvatarResetFrame();

        if (
            !bounds
            || defaultWidth <= bounds.maxWidth
        ) {
            panel.style.removeProperty(
                "width"
            );
        }

        panel.style.removeProperty(
            "--runtime-avatar-panel-size"
        );

        panel.classList.remove(
            "panel-avatar-resetting"
        );

        setPanelCollapsed(
            panel,
            false
        );
        syncSceneShadeToPanelCollapse();
    }

    function getCollapsedAvatarResizeCursor(edge) {
        if (
            edge === "n"
            || edge === "s"
        ) {
            return "ns-resize";
        }

        if (
            edge === "e"
            || edge === "w"
        ) {
            return "ew-resize";
        }

        if (
            edge === "ne"
            || edge === "sw"
        ) {
            return "nesw-resize";
        }

        return "nwse-resize";
    }

    function resolveCollapsedAvatarResizeGeometry(panel, state, event) {
        const bounds =
            getCollapsedAvatarResizeBounds(panel);

        const dx =
            event.clientX - state.startX;

        const dy =
            event.clientY - state.startY;

        const resizeNorth =
            state.edge.includes("n");

        const resizeSouth =
            state.edge.includes("s");

        const resizeEast =
            state.edge.includes("e");

        const resizeWest =
            state.edge.includes("w");

        let nextLeft =
            state.startLeft;

        let nextTop =
            state.startTop;

        let nextWidth =
            state.startWidth;

        let nextHeight =
            state.startHeight;

        if (resizeEast) {
            const maxWidth =
                bounds.parentRect.width - bounds.gap - state.startLeft;

            nextWidth =
                clampNumber(
                    state.startWidth + dx,
                    bounds.minWidth,
                    Math.min(
                        bounds.maxWidth,
                        maxWidth
                    )
                );
        }

        if (resizeWest) {
            const maxWidth =
                state.startRight - bounds.gap;

            nextWidth =
                clampNumber(
                    state.startWidth - dx,
                    bounds.minWidth,
                    Math.min(
                        bounds.maxWidth,
                        maxWidth
                    )
                );

            nextLeft =
                state.startRight - nextWidth;
        }

        if (resizeSouth) {
            const maxHeight =
                bounds.parentRect.height - bounds.gap - state.startTop;

            nextHeight =
                clampNumber(
                    state.startHeight + dy,
                    bounds.minHeight,
                    Math.min(
                        bounds.maxHeight,
                        maxHeight
                    )
                );
        }

        if (resizeNorth) {
            const maxHeight =
                state.startBottom - bounds.gap;

            nextHeight =
                clampNumber(
                    state.startHeight - dy,
                    bounds.minHeight,
                    Math.min(
                        bounds.maxHeight,
                        maxHeight
                    )
                );

            nextTop =
                state.startBottom - nextHeight;
        }

        return {
            left: nextLeft,
            top: nextTop,
            width: nextWidth,
            height: nextHeight,
        };
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

    function clampFreePanelGeometry(panel, options = {}) {
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

        const maxExpandedHeight =
            Math.max(
                minHeight,
                parentRect.height - (PANEL_VIEWPORT_GAP * 2)
            );

        const maxTop =
            Math.max(
                PANEL_VIEWPORT_GAP,
                parentRect.height - PANEL_VIEWPORT_GAP
            );

        const nextTop =
            Math.max(
                PANEL_VIEWPORT_GAP,
                Math.min(
                    currentTop,
                    maxTop
                )
            );

        const availableHeight =
            Math.max(
                0,
                parentRect.height - nextTop - PANEL_VIEWPORT_GAP
            );

        const targetHeight =
            options.expandFromCollapsed
                ? availableHeight
                : Math.max(
                    minHeight,
                    Math.min(
                        panelRect.height,
                        maxExpandedHeight,
                        availableHeight
                    )
                );

        panel.style.left =
            `${nextLeft}px`;

        panel.style.top =
            `${nextTop}px`;

        panel.style.right =
            "auto";

        panel.style.height =
            `${targetHeight}px`;
    }

    function clampPanelGeometry(panel, options = {}) {
        if (!panel) {
            return;
        }

        if (isCollapsedMemoryAvatarPanel(panel)) {
            clampCollapsedAvatarGeometry(panel);
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

        clampFreePanelGeometry(
            panel,
            options
        );
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

    function attachCollapsedAvatarResize(panel) {
        if (panel !== memoryPanel) {
            return;
        }

        let resizeState =
            null;

        function finishResize(event) {
            if (!resizeState) {
                return;
            }

            if (
                event
                && resizeState.handle.releasePointerCapture
            ) {
                try {
                    resizeState.handle.releasePointerCapture(
                        resizeState.pointerId
                    );
                } catch (_error) {
                    // Pointer capture may already be released by the browser.
                }
            }

            resizeState =
                null;

            panel.classList.remove(
                "panel-avatar-resizing",
                "panel-resizing"
            );

            document.body.style.cursor =
                "";

            document.body.style.userSelect =
                "";
        }

        function handleResizeMove(event) {
            if (
                !resizeState
                || event.pointerId !== resizeState.pointerId
            ) {
                return;
            }

            event.preventDefault();

            applyCollapsedAvatarGeometry(
                panel,
                resolveCollapsedAvatarResizeGeometry(
                    panel,
                    resizeState,
                    event
                )
            );
        }

        COLLAPSED_AVATAR_RESIZE_EDGES.forEach((edge) => {
            const resizeHandle =
                document.createElement("div");

            resizeHandle.className =
                "panel-avatar-resize-handle";

            resizeHandle.dataset.panelAvatarResizeEdge =
                edge;

            resizeHandle.setAttribute(
                "aria-hidden",
                "true"
            );

            panel.appendChild(
                resizeHandle
            );

            resizeHandle.addEventListener("pointerdown", (event) => {
                if (
                    event.pointerType === "mouse"
                    && event.button !== 0
                ) {
                    return;
                }

                if (!isCollapsedMemoryAvatarPanel(panel)) {
                    return;
                }

                event.preventDefault();
                event.stopPropagation();

                finishStartupCollapseAnimation();
                cancelCollapsedAvatarSizeFrame();
                setPanelFreeDock(panel);

                const parentRect =
                    panel.parentElement.getBoundingClientRect();

                const panelRect =
                    panel.getBoundingClientRect();

                const startLeft =
                    panelRect.left - parentRect.left;

                const startTop =
                    panelRect.top - parentRect.top;

                resizeState = {
                    edge,
                    handle: resizeHandle,
                    pointerId: event.pointerId,
                    startX: event.clientX,
                    startY: event.clientY,
                    startLeft,
                    startTop,
                    startWidth: panelRect.width,
                    startHeight: panelRect.height,
                    startRight: startLeft + panelRect.width,
                    startBottom: startTop + panelRect.height,
                };

                panel.style.left =
                    `${Math.round(startLeft)}px`;
                panel.style.top =
                    `${Math.round(startTop)}px`;
                panel.style.right =
                    "auto";
                panel.style.bottom =
                    "auto";

                panel.classList.add(
                    "panel-avatar-resizing",
                    "panel-resizing"
                );

                document.body.style.cursor =
                    getCollapsedAvatarResizeCursor(edge);

                document.body.style.userSelect =
                    "none";

                if (resizeHandle.setPointerCapture) {
                    resizeHandle.setPointerCapture(
                        event.pointerId
                    );
                }
            });
        });

        window.addEventListener(
            "pointermove",
            handleResizeMove
        );

        window.addEventListener(
            "pointerup",
            finishResize
        );

        window.addEventListener(
            "pointercancel",
            finishResize
        );
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

    consoleDragHandle.addEventListener("click", (event) => {
        if (
            consoleHasMoved
            || event.detail > 1
        ) {
            consoleHasMoved = false;
            return;
        }

        togglePanelCollapseFromHeader(
            event,
            consolePanel,
            consoleDragHandle
        );
    });






const memoryPanel = document.getElementById("memory-panel");
const memoryDragHandle = document.getElementById("memory-drag-handle");
const memoryPanelDragSpacer = document.getElementById("memory-panel-drag-spacer");
const consoleStreamPlaceholder =
    document.createComment(
        "console-stream detached while console panel is collapsed"
    );
const memoryPanelScrollBody =
    memoryPanel
        ? memoryPanel.querySelector(".memory-scroll")
        : null;
const memoryPanelScrollPlaceholder =
    document.createComment(
        "memory-scroll detached while memory panel is collapsed"
    );
const MEMORY_PANEL_COLLAPSE_SYNC_EVENT =
    "jin:memory-panel-collapse-sync";
let consoleStreamDetachTimer = null;
let memoryPanelScrollDetachTimer = null;
const ROOM_STATE_PERSIST_DELAY_MS = 160;
let roomStatePersistTimer = null;
let roomStatePersistenceEnabled = false;
let applyingRoomState = false;
let roomStateColorReconcilePending = false;

function isRoomStateObject(value) {
    return Boolean(
        value
        && typeof value === "object"
        && !Array.isArray(value)
    );
}

function finiteRoomNumber(value) {
    const number = Number(value);
    return Number.isFinite(number)
        ? number
        : null;
}

function capturePanelRoomState(panel) {
    if (!panel || !panel.parentElement) {
        return null;
    }

    const parentRect =
        panel.parentElement.getBoundingClientRect();
    const rect =
        panel.getBoundingClientRect();
    const headerShift =
        getHeaderAutoHidePanelShift(panel);

    return {
        collapsed:
            panel.classList.contains("panel-collapsed"),
        dock: getPanelDock(panel),
        left: Math.round(rect.left - parentRect.left),
        top: Math.round(
            rect.top
            - parentRect.top
            - headerShift
        ),
        width: Math.max(1, Math.round(rect.width)),
        height: Math.max(1, Math.round(rect.height)),
    };
}

function getRoomState(previousState = null) {
    const previousAvatar =
        previousState
        && isRoomStateObject(previousState.avatar)
            ? previousState.avatar
            : {};
    const avatarApi =
        window.JinRuntime
        && window.JinRuntime.avatar;
    const avatarSnapshot =
        getRuntimeAvatarSnapshot();
    const avatarCollapsed =
        Boolean(
            memoryPanel
            && memoryPanel.classList.contains("panel-collapsed")
        );

    let width = null;
    let height = null;
    let x = null;
    let y = null;

    if (avatarCollapsed && avatarSnapshot) {
        width = finiteRoomNumber(avatarSnapshot.width);
        height = finiteRoomNumber(avatarSnapshot.height);
        x = finiteRoomNumber(avatarSnapshot.x);
        y = finiteRoomNumber(avatarSnapshot.y);
    } else {
        width = finiteRoomNumber(previousAvatar.width);
        height = finiteRoomNumber(previousAvatar.height);
        x = finiteRoomNumber(previousAvatar.x);
        y = finiteRoomNumber(previousAvatar.y);
    }

    const geometryKnown =
        width !== null
        && height !== null
        && x !== null
        && y !== null;

    return {
        version: 1,
        saved_at: new Date().toISOString(),
        console_panel:
            capturePanelRoomState(consolePanel),
        memory_panel:
            capturePanelRoomState(memoryPanel),
        avatar: {
            collapsed: avatarCollapsed,
            color:
                avatarApi
                && typeof avatarApi.getCenterColor === "function"
                    ? String(avatarApi.getCenterColor() || "").trim()
                    : "",
            memory_layers_hidden:
                avatarApi
                && typeof avatarApi.getMemoryLayersHidden === "function"
                    ? Boolean(avatarApi.getMemoryLayersHidden())
                    : false,
            geometry_known: geometryKnown,
            width: geometryKnown ? Math.round(width) : null,
            height: geometryKnown ? Math.round(height) : null,
            x: geometryKnown ? Math.round(x) : null,
            y: geometryKnown ? Math.round(y) : null,
            speed_px_per_second: getJinMoveSpeed(),
            window_width: Math.max(1, Math.round(window.innerWidth)),
            window_height: Math.max(1, Math.round(window.innerHeight)),
        },
    };
}

function applyPanelRoomState(panel, state) {
    if (!panel || !isRoomStateObject(state)) {
        return false;
    }

    const dock = String(state.dock || "").trim();
    const left = finiteRoomNumber(state.left);
    const top = finiteRoomNumber(state.top);
    const width = finiteRoomNumber(state.width);
    const height = finiteRoomNumber(state.height);

    setPanelCollapsed(
        panel,
        Boolean(state.collapsed)
    );

    if (dock === PANEL_DOCK_FREE) {
        setPanelFreeDock(panel);
    } else if (dock === getDefaultPanelDock(panel)) {
        delete panel.dataset.panelDock;
    }

    if (
        dock === PANEL_DOCK_FREE
        && left !== null
        && top !== null
    ) {
        panel.style.position = "absolute";
        panel.style.left = `${Math.round(left)}px`;
        panel.style.top = `${Math.round(top)}px`;
        panel.style.right = "auto";
        panel.style.bottom = "auto";
    }

    if (
        width !== null
        && width > 0
        && dock === PANEL_DOCK_FREE
    ) {
        panel.style.width = `${Math.round(width)}px`;
    }

    if (
        height !== null
        && height > 0
        && !panel.classList.contains("panel-collapsed")
        && dock === PANEL_DOCK_FREE
    ) {
        panel.style.height = `${Math.round(height)}px`;
    }

    clampPanelGeometry(panel);
    return true;
}

function applyAvatarRoomGeometry(avatarState) {
    if (
        !isRoomStateObject(avatarState)
        || avatarState.geometry_known !== true
    ) {
        return false;
    }

    const size = normalizeJinSizePayload({
        width: avatarState.width,
        height: avatarState.height,
    });
    const position = normalizeJinPositionPayload({
        x: avatarState.x,
        y: avatarState.y,
    });

    if (!size || !position) {
        return false;
    }

    if (isCollapsedMemoryAvatarPanel(memoryPanel)) {
        const bounds =
            getCollapsedAvatarResizeBounds(memoryPanel);

        applyCollapsedAvatarSize(
            memoryPanel,
            size.width,
            size.height + bounds.frameHeight
        );

        const parentRect =
            memoryPanel.parentElement.getBoundingClientRect();
        const panelRect =
            memoryPanel.getBoundingClientRect();

        applyCollapsedAvatarPosition(
            memoryPanel,
            position.x - parentRect.left - (panelRect.width / 2),
            position.y - parentRect.top - (panelRect.height / 2)
        );
        clampCollapsedAvatarGeometry(memoryPanel);
        pendingJinSize = null;
        pendingJinPosition = null;
        avatarInspectorWorldState = null;
        return true;
    }

    avatarInspectorWorldState = {
        size: {
            width: size.width,
            height: size.height,
        },
        position: {
            x: position.x,
            y: position.y,
        },
    };
    return true;
}

function clearRoomStateRestoreTimers() {
    if (roomStateRestoreDelayTimer !== null) {
        window.clearTimeout(roomStateRestoreDelayTimer);
        roomStateRestoreDelayTimer = null;
    }

    if (roomStateRestoreFinishTimer !== null) {
        window.clearTimeout(roomStateRestoreFinishTimer);
        roomStateRestoreFinishTimer = null;
    }
}

function clearRoomStateTintTransition() {
    const tint = document.getElementById("scene-jin-tint");

    if (roomStateRestoreTintTimer !== null) {
        window.clearTimeout(roomStateRestoreTintTimer);
        roomStateRestoreTintTimer = null;
    }

    if (tint && roomStateRestoreTintPreviousDuration !== null) {
        if (roomStateRestoreTintPreviousDuration) {
            tint.style.transitionDuration =
                roomStateRestoreTintPreviousDuration;
        } else {
            tint.style.removeProperty("transition-duration");
        }
    }

    roomStateRestoreTintPreviousDuration = null;
}

function beginRoomStateTintTransition(sequence) {
    const tint = document.getElementById("scene-jin-tint");

    clearRoomStateTintTransition();

    if (!tint) {
        return;
    }

    roomStateRestoreTintPreviousDuration =
        tint.style.transitionDuration;
    tint.style.transitionDuration =
        `${ROOM_STATE_RESTORE_TINT_DURATION_MS}ms`;
    tint.getBoundingClientRect();

    roomStateRestoreTintTimer = window.setTimeout(
        () => {
            if (sequence !== roomStateRestoreSequence) {
                return;
            }

            clearRoomStateTintTransition();
        },
        ROOM_STATE_RESTORE_TINT_DURATION_MS + 80
    );
}

function finishRoomStateRestore(sequence) {
    if (sequence !== roomStateRestoreSequence) {
        return;
    }

    roomStateRestoreFinishTimer = null;
    roomStateRestoreInProgress = false;

    if (
        roomStateRestoreShouldPersist
        || roomStateColorReconcilePending
    ) {
        scheduleRoomStatePersist();
    }
}

function clickPanelForRoomRestore(panel, handle) {
    if (
        !panel
        || !handle
        || panel.classList.contains("panel-collapsed")
    ) {
        return false;
    }

    handle.click();
    return true;
}

function scheduleRoomStateCollapse(
    sequence,
    consoleCollapsed,
    memoryCollapsed
) {
    roomStateRestoreDelayTimer = window.setTimeout(
        () => {
            roomStateRestoreDelayTimer = null;

            if (sequence !== roomStateRestoreSequence) {
                return;
            }

            if (consoleCollapsed) {
                clickPanelForRoomRestore(
                    consolePanel,
                    consoleDragHandle
                );
            }

            if (memoryCollapsed) {
                clickPanelForRoomRestore(
                    memoryPanel,
                    memoryDragHandle
                );
            }

            const finishDelay = Math.max(
                consoleCollapsed
                    ? getPanelCollapseDurationMs(consolePanel)
                    : 0,
                memoryCollapsed
                    ? getPanelCollapseDurationMs(memoryPanel)
                        + COLLAPSED_AVATAR_SIZE_ANIMATION_MS
                        + 80
                    : 0
            );

            roomStateRestoreFinishTimer = window.setTimeout(
                () => finishRoomStateRestore(sequence),
                finishDelay + 80
            );
        },
        ROOM_STATE_RESTORE_DELAY_MS
    );
}

function applyRoomState(roomState, options = {}) {
    if (!isRoomStateObject(roomState)) {
        return false;
    }

    const avatarState =
        isRoomStateObject(roomState.avatar)
            ? roomState.avatar
            : {};
    const avatarApi =
        window.JinRuntime
        && window.JinRuntime.avatar;
    const animateRestore =
        options.animateRestore !== false
        && !prefersReducedMotion();
    const animateTint =
        animateRestore
        && options.animateTint !== false;

    roomStateRestoreSequence += 1;
    const sequence = roomStateRestoreSequence;

    clearRoomStateRestoreTimers();
    roomStateRestoreInProgress = animateRestore;
    roomStateRestoreShouldPersist =
        options.persist !== false;

    applyingRoomState = true;

    try {
        [consolePanel, memoryPanel]
            .filter(Boolean)
            .forEach(registerPanelRuntimeActivity);
        finishStartupCollapseAnimation();

        if (animateTint) {
            beginRoomStateTintTransition(sequence);
        } else {
            clearRoomStateTintTransition();
        }

        if (
            avatarState.color
            && avatarApi
            && typeof avatarApi.setCenterColor === "function"
        ) {
            avatarApi.setCenterColor(
                avatarState.color,
                {
                    initialBootstrap:
                        options.initialBootstrapColor === true,
                    persist: options.persist !== false,
                }
            );
        }

        if (finiteRoomNumber(avatarState.speed_px_per_second) > 0) {
            setJinMoveSpeed(
                avatarState.speed_px_per_second
            );
        }

        if (
            avatarApi
            && typeof avatarApi.setMemoryLayersHidden === "function"
            && Object.prototype.hasOwnProperty.call(
                avatarState,
                "memory_layers_hidden"
            )
        ) {
            avatarApi.setMemoryLayersHidden(
                Boolean(avatarState.memory_layers_hidden)
            );
        }

        if (!animateRestore) {
            withoutPanelTransitions(() => {
                applyPanelRoomState(
                    consolePanel,
                    roomState.console_panel
                );

                const memoryApplied =
                    applyPanelRoomState(
                        memoryPanel,
                        roomState.memory_panel
                    );

                if (
                    !memoryApplied
                    && Object.prototype.hasOwnProperty.call(
                        avatarState,
                        "collapsed"
                    )
                ) {
                    setPanelCollapsed(
                        memoryPanel,
                        Boolean(avatarState.collapsed)
                    );
                }

                applyAvatarRoomGeometry(avatarState);
                syncCollapsedPanelBodies();
                syncSceneShadeToPanelCollapse();
            });
        } else {
            const consoleState =
                isRoomStateObject(roomState.console_panel)
                    ? roomState.console_panel
                    : null;
            const memoryState =
                isRoomStateObject(roomState.memory_panel)
                    ? roomState.memory_panel
                    : null;
            const consoleCollapsed =
                Boolean(consoleState && consoleState.collapsed);
            const memoryCollapsed =
                memoryState
                    ? Boolean(memoryState.collapsed)
                    : Boolean(avatarState.collapsed);

            withoutPanelTransitions(() => {
                if (consoleState) {
                    applyPanelRoomState(
                        consolePanel,
                        consoleState
                    );

                    if (consoleCollapsed) {
                        setPanelCollapsed(consolePanel, false);
                    }
                } else {
                    setPanelCollapsed(consolePanel, false);
                }

                setPanelCollapsed(memoryPanel, false);

                if (!memoryCollapsed) {
                    applyPanelRoomState(
                        memoryPanel,
                        memoryState
                    );
                }

                applyAvatarRoomGeometry(avatarState);
                syncCollapsedPanelBodies();
                syncSceneShadeToPanelCollapse();
            });

            scheduleRoomStateCollapse(
                sequence,
                consoleCollapsed,
                memoryCollapsed
            );
        }
    } finally {
        applyingRoomState = false;
    }

    if (!animateRestore && options.persist !== false) {
        scheduleRoomStatePersist();
    }

    return true;
}

function persistRoomStateNow(options = {}) {
    if (options.reconcileCurrentColor === true) {
        roomStateColorReconcilePending = true;
    }

    const reconcileCurrentColor =
        roomStateColorReconcilePending;

    if (
        !roomStatePersistenceEnabled
        || applyingRoomState
        || roomStateRestoreInProgress
    ) {
        return false;
    }

    const storage =
        window.JinRuntime
        && window.JinRuntime.storage;

    if (
        !storage
        || typeof storage.readLatestSavedSessionSnapshot !== "function"
        || typeof storage.writeLatestSavedSessionSnapshot !== "function"
        || (
            typeof storage.shouldIsolateAnonymousStorage === "function"
            && storage.shouldIsolateAnonymousStorage()
        )
    ) {
        return false;
    }

    const checkpoint =
        storage.readLatestSavedSessionSnapshot();

    if (
        !checkpoint
        || !isRoomStateObject(checkpoint.session_snapshot)
    ) {
        return false;
    }

    const currentSessionId =
        typeof storage.getCurrentRuntimeSessionId === "function"
            ? String(
                storage.getCurrentRuntimeSessionId()
                || ""
            ).trim()
            : "";
    const checkpointSessionId =
        String(checkpoint.session_id || "").trim();

    // Room/avatar writes are field-local. They may update the current
    // session checkpoint, but they never decide that a freshly opened tab
    // became a new conversation. JIN_COLOR is the one synchronous exception:
    // reconcile the room into the existing common checkpoint even before the
    // full turn promotes this runtime session. This keeps the checkpoint's
    // session id, lineage and saved_at untouched while preventing an older
    // color from being replayed on every reload.
    if (
        currentSessionId
        && checkpointSessionId
        && currentSessionId !== checkpointSessionId
        && !reconcileCurrentColor
    ) {
        return false;
    }

    const previousRoomState =
        isRoomStateObject(
            checkpoint.session_snapshot.room_state
        )
            ? checkpoint.session_snapshot.room_state
            : null;
    const roomState = getRoomState(previousRoomState);
    const avatar = roomState.avatar;
    const sessionSnapshot = {
        ...checkpoint.session_snapshot,
        room_state: roomState,
        current_jin_collapsed:
            Boolean(avatar.collapsed),
        current_jin_speed:
            Number(avatar.speed_px_per_second || 900),
        current_window_size: {
            width: avatar.window_width,
            height: avatar.window_height,
        },
    };

    if (avatar.color) {
        sessionSnapshot.current_jin_color = avatar.color;
    }

    if (avatar.geometry_known) {
        sessionSnapshot.current_jin_size = {
            width: avatar.width,
            height: avatar.height,
        };
        sessionSnapshot.current_jin_position = {
            x: avatar.x,
            y: avatar.y,
        };
    }

    const written = storage.writeLatestSavedSessionSnapshot({
        ...checkpoint,
        session_snapshot: sessionSnapshot,
    });

    if (written && reconcileCurrentColor) {
        roomStateColorReconcilePending = false;
    }

    return written;
}

function scheduleRoomStatePersist() {
    if (
        !roomStatePersistenceEnabled
        || applyingRoomState
        || roomStateRestoreInProgress
    ) {
        return;
    }

    if (roomStatePersistTimer !== null) {
        window.clearTimeout(roomStatePersistTimer);
    }

    roomStatePersistTimer = window.setTimeout(
        () => {
            roomStatePersistTimer = null;
            persistRoomStateNow();
        },
        ROOM_STATE_PERSIST_DELAY_MS
    );
}

function getStoredRoomState() {
    const storage =
        window.JinRuntime
        && window.JinRuntime.storage;

    if (
        !storage
        || typeof storage.readLatestSavedSessionSnapshot !== "function"
    ) {
        return null;
    }

    const checkpoint =
        storage.readLatestSavedSessionSnapshot();

    if (
        !checkpoint
        || !isRoomStateObject(checkpoint.session_snapshot)
    ) {
        return null;
    }

    const requestedSessionId =
        String(
            new URLSearchParams(window.location.search)
                .get("restore_session")
            || ""
        ).trim();

    if (
        requestedSessionId
        && String(checkpoint.session_id || "").trim()
            !== requestedSessionId
    ) {
        return null;
    }

    const snapshot = checkpoint.session_snapshot;

    if (isRoomStateObject(snapshot.room_state)) {
        const roomState = {
            ...snapshot.room_state,
        };
        const color =
            String(
                snapshot.current_jin_color
                || (
                    roomState.avatar
                    && roomState.avatar.color
                )
                || ""
            ).trim();

        if (isRoomStateObject(roomState.avatar)) {
            roomState.avatar = {
                ...roomState.avatar,
            };

            if (color) {
                roomState.avatar.color = color;
            }
        } else if (color) {
            roomState.avatar = {
                color,
            };
        }

        return roomState;
    }

    if (
        !isRoomStateObject(snapshot.current_jin_size)
        || !isRoomStateObject(snapshot.current_jin_position)
    ) {
        return null;
    }

    return {
        version: 1,
        avatar: {
            collapsed:
                Object.prototype.hasOwnProperty.call(
                    snapshot,
                    "current_jin_collapsed"
                )
                    ? Boolean(snapshot.current_jin_collapsed)
                    : true,
            color:
                String(snapshot.current_jin_color || "").trim(),
            memory_layers_hidden: false,
            geometry_known: true,
            width: snapshot.current_jin_size.width,
            height: snapshot.current_jin_size.height,
            x: snapshot.current_jin_position.x,
            y: snapshot.current_jin_position.y,
            speed_px_per_second:
                Number(snapshot.current_jin_speed || 900),
        },
    };
}

function enableRoomStatePersistence(scheduleInitialPersist = true) {
    roomStatePersistenceEnabled = true;

    if (scheduleInitialPersist) {
        scheduleRoomStatePersist();
    }
}

function initRoomStatePersistence() {
    if (typeof MutationObserver !== "undefined") {
        const observer = new MutationObserver(
            scheduleRoomStatePersist
        );

        [consolePanel, memoryPanel]
            .filter(Boolean)
            .forEach((panel) => {
                observer.observe(panel, {
                    attributes: true,
                    attributeFilter: [
                        "style",
                        "data-panel-dock",
                    ],
                });
            });
    }

    window.addEventListener(
        "jin:avatar-room-state-changed",
        (event) => {
            if (event.detail && event.detail.immediate === true) {
                persistRoomStateNow({
                    reconcileCurrentColor: true,
                });
                return;
            }
            scheduleRoomStatePersist();
        }
    );
    window.addEventListener(
        "beforeunload",
        persistRoomStateNow
    );

    const storedRoomState = getStoredRoomState();

    if (storedRoomState) {
        applyRoomState(
            storedRoomState,
            {
                persist: false,
                animateTint: false,
                initialBootstrapColor: true,
            }
        );

        enableRoomStatePersistence(false);
        return;
    }

    const enableAfterRestore = () => {
        Promise.resolve(
            window.jinArchivedSessionRestoreReady
        )
            .catch(() => null)
            .finally(enableRoomStatePersistence);
    };

    if (document.readyState === "complete") {
        enableAfterRestore();
    } else {
        window.addEventListener(
            "load",
            enableAfterRestore,
            { once: true }
        );
    }
}

function clearConsoleStreamDetachTimer() {
    if (consoleStreamDetachTimer === null) {
        return;
    }

    window.clearTimeout(
        consoleStreamDetachTimer
    );
    consoleStreamDetachTimer = null;
}

function detachConsolePanelBody() {
    clearConsoleStreamDetachTimer();

    if (
        !consolePanel
        || !consoleStream
        || consoleStream.parentNode !== consolePanel
    ) {
        return;
    }

    consolePanel.insertBefore(
        consoleStreamPlaceholder,
        consoleStream
    );
    consolePanel.removeChild(
        consoleStream
    );
}

function attachConsolePanelBody() {
    clearConsoleStreamDetachTimer();

    if (
        !consolePanel
        || !consoleStream
    ) {
        return;
    }

    if (consoleStream.parentNode === consolePanel) {
        return;
    }

    if (consoleStreamPlaceholder.parentNode === consolePanel) {
        consolePanel.insertBefore(
            consoleStream,
            consoleStreamPlaceholder
        );
        consolePanel.removeChild(
            consoleStreamPlaceholder
        );
    } else {
        consolePanel.appendChild(
            consoleStream
        );
    }
}

function getPanelBodyDetachDelayMs(panel) {
    if (!panel) {
        return 0;
    }

    const duration =
        getComputedStyle(panel)
            .getPropertyValue("--panel-collapse-duration")
            .trim();

    return Math.max(
        0,
        parseCssDurationMs(duration)
    ) + 100;
}

function scheduleConsolePanelBodyDetach() {
    clearConsoleStreamDetachTimer();

    if (
        !consolePanel
        || !consoleStream
        || !consolePanel.classList.contains("panel-collapsed")
    ) {
        attachConsolePanelBody();
        return;
    }

    consoleStreamDetachTimer =
        window.setTimeout(
            detachConsolePanelBody,
            getPanelBodyDetachDelayMs(consolePanel)
        );
}

function syncConsolePanelBodyMount() {
    if (
        !consolePanel
        || !consoleStream
    ) {
        return;
    }

    if (consolePanel.classList.contains("panel-collapsed")) {
        scheduleConsolePanelBodyDetach();
    } else {
        attachConsolePanelBody();
    }
}

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
    return getPanelBodyDetachDelayMs(
        memoryPanel
    );
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

function syncCollapsedPanelBodies() {
    syncConsolePanelBodyMount();
    syncMemoryPanelBodyMount();
}

if (consolePanel && typeof MutationObserver !== "undefined") {
    const consolePanelBodyObserver =
        new MutationObserver(
            syncConsolePanelBodyMount
        );

    consolePanelBodyObserver.observe(
        consolePanel,
        {
            attributes: true,
            attributeFilter: ["class"],
        }
    );
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

syncCollapsedPanelBodies();

function expandConsolePanelForContextAttachment() {
    if (!consolePanel) {
        return false;
    }

    const needsExpand =
        consolePanel.classList.contains("panel-collapsed")
        || Boolean(consolePanel.dataset.expandedHeight);

    // An attachment is explicit activity: do not let an in-flight startup
    // collapse finish after the file arrives and fold the console back up.
    finishStartupCollapseAnimation();

    if (!needsExpand) {
        return false;
    }

    setPanelCollapsed(consolePanel, false);
    syncSceneShadeToPanelCollapse();
    return true;
}

function delayedMemoryPlaquePinSvg() {
    return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.7 3.3 20.7 9.3 18.6 11.4 16.9 9.7 13.7 12.9 14.4 15.7 12.9 17.2 9.4 13.7 5.3 17.8 4.2 16.7 8.3 12.6 4.8 9.1 6.3 7.6 9.1 8.3 12.3 5.1 10.6 3.4 12.7 1.3Z"/></svg>';
}

function getConsoleAttachedDelayedMemoryRecords() {
    const runtime =
        window.JinRuntime
        && window.JinRuntime.runtime;
    if (
        !runtime
        || typeof runtime.getDelayedMemoryReports !== "function"
    ) {
        return [];
    }

    const reports = runtime.getDelayedMemoryReports() || {};
    const loadedIds = new Set(
        typeof runtime.getLoadedDelayedMemoryReportIds === "function"
            ? runtime.getLoadedDelayedMemoryReportIds()
            : []
    );

    return Object.entries(reports)
        .filter(([, report]) => (
            report
            && typeof report === "object"
            && !Array.isArray(report)
        ))
        .map(([storageKey, report]) => {
            const reportId = String(
                report.id
                || report._storage_key
                || storageKey
                || ""
            ).trim().toLowerCase();

            return {
                reportId,
                report,
                attached:
                    Boolean(report.pinned)
                    || loadedIds.has(reportId),
            };
        })
        .filter((item) => item.reportId && item.attached);
}

function unloadConsoleDelayedMemoryReport(reportId) {
    const runtime =
        window.JinRuntime
        && window.JinRuntime.runtime;
    const normalizedId = String(reportId || "").trim().toLowerCase();
    if (!runtime || !normalizedId) {
        return false;
    }

    const reports =
        typeof runtime.getDelayedMemoryReports === "function"
            ? runtime.getDelayedMemoryReports()
            : {};
    const report = reports && reports[normalizedId];
    if (!report) {
        return false;
    }

    if (
        Boolean(report.pinned)
        && typeof runtime.setDelayedMemoryReportPinned === "function"
    ) {
        runtime.setDelayedMemoryReportPinned(normalizedId, false);
    }

    if (
        typeof runtime.isDelayedMemoryReportLoaded === "function"
        && runtime.isDelayedMemoryReportLoaded(normalizedId)
        && typeof runtime.markDelayedMemoryReportLoaded === "function"
    ) {
        runtime.markDelayedMemoryReportLoaded(
            normalizedId,
            false,
            {
                sync: true,
                suppressNextTurn: true,
            }
        );
    }

    return true;
}

function openConsoleDelayedMemoryReport(report) {
    const memoryView =
        window.JinRuntime
        && window.JinRuntime.memoryView;

    if (
        !report
        || !memoryView
        || typeof memoryView.openDelayedMemoryReportModal !== "function"
    ) {
        return false;
    }

    memoryView.openDelayedMemoryReportModal(report);
    return true;
}

function renderAttachedDelayedMemoryPlaque() {
    if (!attachedDelayedMemory) {
        return;
    }

    const records = getConsoleAttachedDelayedMemoryRecords();
    attachedDelayedMemory.replaceChildren();
    attachedDelayedMemory.classList.toggle(
        "hidden",
        records.length === 0
    );

    if (!records.length) {
        return;
    }

    const title = document.createElement("div");
    title.className = "jin-attached-files-title";
    title.textContent = "[ LOADED_DELAYED_MEMORY ]";
    attachedDelayedMemory.appendChild(title);

    const list = document.createElement("div");
    list.className = "jin-attached-files-list";

    records.forEach(({reportId, report}) => {
        const row = document.createElement("div");
        row.className =
            "jin-attached-files-row runtime-memory-delayed-row-pinned";
        row.dataset.reportId = reportId;

        const pin = document.createElement("button");
        pin.type = "button";
        pin.className =
            "delayed-memory-modal-icon-button delayed-memory-modal-pin runtime-memory-delayed-pin is-pinned";
        pin.innerHTML = delayedMemoryPlaquePinSvg();
        pin.title = `Unload delayed memory ${reportId}`;
        pin.setAttribute(
            "aria-label",
            `Unload delayed memory ${reportId}`
        );
        pin.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            unloadConsoleDelayedMemoryReport(reportId);
        });

        const name = document.createElement("span");
        name.className =
            "jin-attached-files-name jin-attached-delayed-memory-name";
        name.textContent = String(report.title || reportId);
        name.title = String(report.title || reportId);
        name.setAttribute("role", "button");
        name.tabIndex = 0;

        const openReport = (event) => {
            event.preventDefault();
            event.stopPropagation();
            openConsoleDelayedMemoryReport(report);
        };

        name.addEventListener("click", openReport);
        name.addEventListener("keydown", (event) => {
            if (event.key !== "Enter" && event.key !== " ") {
                return;
            }
            openReport(event);
        });

        row.append(pin, name);
        list.appendChild(row);
    });

    attachedDelayedMemory.appendChild(list);
}

window.addEventListener(
    "jin:delayed-memory-store-changed",
    (event) => {
        renderAttachedDelayedMemoryPlaque();
        const reason = String(
            event && event.detail && event.detail.reason || ""
        );
        if (
            reason === "load"
            || reason === "load-state"
            || reason === "pin"
        ) {
            if (getConsoleAttachedDelayedMemoryRecords().length) {
                expandConsolePanelForContextAttachment();
            }
        }
    }
);

renderAttachedDelayedMemoryPlaque();

window.JinPanels =
    Object.assign(
        window.JinPanels || {},
        {
            collapseAllPanels,
            expandConsolePanelForContextAttachment,
            cancelStartupCollapseAnimation,
            applyRoomState,
            getRoomState,
            getRuntimeAvatarSnapshot,
            getJinMoveSpeed,
            persistRoomStateNow,
            refreshCollapsedPanelHeights,
            setJinMoveSpeed,
            setPendingJinPosition,
            setPendingJinSize,
            syncCollapsedPanelBodies,
            syncConsolePanelBodyMount,
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

function beginMemoryPanelDrag(event) {
    if (event.detail > 1) {
        return;
    }

    cancelCollapsedAvatarSizeFrame();
    cancelCollapsedAvatarPositionFrame();

    isMemoryDragging = true;

    const rect = memoryPanel.getBoundingClientRect();

    memoryOffsetX = event.clientX - rect.left;
    memoryOffsetY = event.clientY - rect.top;
    memoryDragStartX = event.clientX;
    memoryDragStartY = event.clientY;
    memoryHasMoved = false;

    document.body.style.userSelect = "none";
}

memoryDragHandle.addEventListener("mousedown", beginMemoryPanelDrag);

if (memoryPanelDragSpacer) {
    memoryPanelDragSpacer.addEventListener(
        "mousedown",
        beginMemoryPanelDrag
    );
}

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
        pendingJinPosition = null;
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

memoryDragHandle.addEventListener("click", (event) => {
    if (memoryPanel.classList.contains(AVATAR_INSPECTOR_CLOSE_CLASS)) {
        event.preventDefault();
        return;
    }

    const collapsedAvatar =
        isCollapsedMemoryAvatarPanel(memoryPanel);
    const avatarResetting =
        memoryPanel.classList.contains("panel-avatar-resetting");

    if (
        memoryHasMoved
        || avatarResetting
        || (event.detail > 1 && !collapsedAvatar)
    ) {
        memoryHasMoved = false;
        return;
    }

    const memoryLayersToggle =
        document.getElementById("memory-layers-toggle");

    if (
        memoryLayersToggle
        && memoryLayersToggle.contains(event.target)
    ) {
        return;
    }

    if (collapsedAvatar) {
        event.preventDefault();
        finishStartupCollapseAnimation();

        clearCollapsedAvatarResetTimer();

        beginAvatarInspector(memoryPanel);

        const avatarResetStarted =
            resetCollapsedAvatarToDefault(memoryPanel);

        if (!avatarResetStarted) {
            finishCollapsedAvatarResetAndExpand(memoryPanel);
            return;
        }

        syncSceneShadeToPanelCollapse();

        collapsedAvatarResetTimer =
            window.setTimeout(
                () => {
                    finishCollapsedAvatarResetAndExpand(memoryPanel);
                },
                COLLAPSED_AVATAR_RESET_EXPAND_DELAY_MS
            );

        return;
    }

    if (collapseAvatarInspectorBeforeWorldRestore(memoryPanel)) {
        event.preventDefault();
        return;
    }

    togglePanelCollapseFromHeader(
        event,
        memoryPanel,
        memoryDragHandle,
        {
            ignoredTarget: memoryLayersToggle,
        }
    );
});

attachBottomResize(
    consolePanel
);

attachBottomResize(
    memoryPanel
);

attachCollapsedAvatarResize(
    memoryPanel
);

requestAnimationFrame(
    clampAllPanelGeometry
);

window.addEventListener(
    "resize",
    () => {
        cancelCollapsedAvatarPositionFrame();
        clampAllPanelGeometry();
        refreshCollapsedPanelHeights();
        scheduleRoomStatePersist();
    }
);

initRoomStatePersistence();
