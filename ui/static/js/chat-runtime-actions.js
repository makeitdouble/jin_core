const deferredRuntimeActionsAfterResponse = [];
let runtimeActionRowCounter = 0;

const SCENE_SEARCH_RUNTIME_ACTION = "web_search";
let sceneSearchFadeTimer = null;

function getSceneRoot() {
  return document.querySelector("main");
}

function setSceneSearchScreenActive(active) {
  const sceneRoot = getSceneRoot();

  if (!sceneRoot) {
    return;
  }

  if (sceneSearchFadeTimer) {
    clearTimeout(sceneSearchFadeTimer);
    sceneSearchFadeTimer = null;
  }

  if (active) {
    sceneRoot.classList.add(
      "scene-searching"
    );
    return;
  }

  sceneRoot.classList.remove(
    "scene-searching"
  );
}

function syncSceneSearchScreenForRuntimeAction(
  action,
  active
) {
  if (
    String(action || "").toLowerCase()
    !== SCENE_SEARCH_RUNTIME_ACTION
  ) {
    return;
  }

  setSceneSearchScreenActive(
    active
  );
}

function formatRuntimeActionContextTitle(
  action,
  contextSnapshot
) {

  const actionName =
    String(
      action || "runtime_action"
    ).toUpperCase();

  const contextRole =
    String(
      (
        contextSnapshot
        && contextSnapshot.context_role
      )
      || "unknown"
    ).toUpperCase();

  return (
    `ACTION: ${actionName} `
    + `| CONTEXT: ${contextRole}`
  );

}

// RUNTIME ACTION

const runtimeActionGuardDecisionClasses = [
  "jin-runtime-action-guard-pending",
  "jin-runtime-action-guard-rejected",
  "jin-runtime-action-guard-continued",
];
const RUNTIME_ACTION_GUARD_CONFIRMATION_DELAY_MS = 0;
const RUNTIME_ACTION_GUARD_ANIMATION_DURATION_MS = 3200;
const RUNTIME_ACTION_GUARD_GEOMETRY_REFERENCE_WIDTH = 10;
const RUNTIME_ACTION_GUARD_GREEN_BASE_X = 1;
const RUNTIME_ACTION_GUARD_RED_BASE_X = -1;
const RUNTIME_ACTION_GUARD_GREEN_WIDTH_FACTOR = 0.006;
const RUNTIME_ACTION_GUARD_RED_WIDTH_FACTOR = -0.006;
const RUNTIME_ACTION_GUARD_BASE_PERSPECTIVE = 100;
const RUNTIME_ACTION_GUARD_GREEN_BASE_ROTATE_DEG = -1;
const RUNTIME_ACTION_GUARD_RED_BASE_ROTATE_DEG = 1;
const RUNTIME_ACTION_GUARD_BASE_Z = 10;
const RUNTIME_ACTION_GUARD_BASE_SCALE_X = 1.00;
const RUNTIME_ACTION_GUARD_MIN_MOTION_SCALE = 0.62;
const RUNTIME_ACTION_GUARD_MAX_MOTION_SCALE = 1.18;
const RUNTIME_ACTION_GUARD_MIN_ROTATION_SCALE = 2;
const RUNTIME_ACTION_GUARD_MAX_ROTATION_SCALE = 0.15;
const RUNTIME_ACTION_GUARD_MIN_ROTATION_WIDTH = 220;
const RUNTIME_ACTION_GUARD_MAX_ROTATION_WIDTH = 760;
const RUNTIME_ACTION_GUARD_MIN_ICON_GAP = 8;
let runtimeActionGuardGeometryFrame = null;

function resolveRuntimeActionGuardConfirmationDelayMs(
  confirmation = {}
) {

  const hasConfiguredDelay =
    Object.prototype.hasOwnProperty.call(
      confirmation,
      "timeoutMs"
    )
    || Object.prototype.hasOwnProperty.call(
      confirmation,
      "timeout_ms"
    );
  const configuredDelay =
    Number(
      hasConfiguredDelay
        ? (
          confirmation.timeoutMs
          ?? confirmation.timeout_ms
          ?? 0
        )
        : RUNTIME_ACTION_GUARD_CONFIRMATION_DELAY_MS
    );

  return Number.isFinite(
    configuredDelay
  ) && configuredDelay >= 0
    ? configuredDelay
    : RUNTIME_ACTION_GUARD_CONFIRMATION_DELAY_MS;

}

function clampRuntimeActionGuardValue(
  value,
  min,
  max
) {

  return Math.min(
    max,
    Math.max(
      min,
      value
    )
  );

}

function updateRuntimeActionGuardGeometry(
  row,
  label
) {

  if (
      !row
      || !label
  ) {
    return;
  }

  const labelRect =
    label.getBoundingClientRect();
  const icon =
    row.querySelector(
      ":scope > div:not(.jin-runtime-action-label), :scope > button"
    );
  const iconRect =
    icon
      ? icon.getBoundingClientRect()
      : null;

  const width =
    Math.max(
      0,
      Number(
        labelRect.width || 0
      )
    );
  const extraWidth =
    Math.max(
      0,
      width - RUNTIME_ACTION_GUARD_GEOMETRY_REFERENCE_WIDTH
    );
  const currentGap =
    iconRect
      ? labelRect.left - iconRect.right
      : RUNTIME_ACTION_GUARD_MIN_ICON_GAP;
  const gapCompensation =
    Math.max(
      0,
      RUNTIME_ACTION_GUARD_MIN_ICON_GAP - currentGap
    );
  const greenX =
    RUNTIME_ACTION_GUARD_GREEN_BASE_X
    + gapCompensation
    + (
      extraWidth
      * RUNTIME_ACTION_GUARD_GREEN_WIDTH_FACTOR
    );
  const redX =
    RUNTIME_ACTION_GUARD_RED_BASE_X
    + gapCompensation
    + (
      extraWidth
      * RUNTIME_ACTION_GUARD_RED_WIDTH_FACTOR
    );
  const rotationWidthSpan =
    Math.max(
      1,
      RUNTIME_ACTION_GUARD_MAX_ROTATION_WIDTH
      - RUNTIME_ACTION_GUARD_MIN_ROTATION_WIDTH
    );
  const rotationWidthProgress =
    clampRuntimeActionGuardValue(
      (
        width
        - RUNTIME_ACTION_GUARD_MIN_ROTATION_WIDTH
      )
      / rotationWidthSpan,
      0,
      1
    );
  const rotationScale =
    RUNTIME_ACTION_GUARD_MIN_ROTATION_SCALE
    + (
      rotationWidthProgress
      * (
        RUNTIME_ACTION_GUARD_MAX_ROTATION_SCALE
        - RUNTIME_ACTION_GUARD_MIN_ROTATION_SCALE
      )
    );
  const motionScale =
    clampRuntimeActionGuardValue(
      Math.sqrt(
        RUNTIME_ACTION_GUARD_GEOMETRY_REFERENCE_WIDTH
        / Math.max(
          width,
          1
        )
      ),
      RUNTIME_ACTION_GUARD_MIN_MOTION_SCALE,
      RUNTIME_ACTION_GUARD_MAX_MOTION_SCALE
    );
  const perspective =
    RUNTIME_ACTION_GUARD_BASE_PERSPECTIVE
    / motionScale;
  const greenRotate =
    RUNTIME_ACTION_GUARD_GREEN_BASE_ROTATE_DEG
    * rotationScale;
  const redRotate =
    RUNTIME_ACTION_GUARD_RED_BASE_ROTATE_DEG
    * rotationScale;
  const depthZ =
    RUNTIME_ACTION_GUARD_BASE_Z
    * motionScale;
  const scaleX =
    1
    + (
      (
        RUNTIME_ACTION_GUARD_BASE_SCALE_X
        - 1
      )
      * motionScale
    );

  label.style.setProperty(
    "--jin-runtime-action-guard-green-x",
    `${greenX.toFixed(2)}px`
  );
  label.style.setProperty(
    "--jin-runtime-action-guard-red-x",
    `${redX.toFixed(2)}px`
  );
  label.style.setProperty(
    "--jin-runtime-action-guard-perspective",
    `${perspective.toFixed(2)}px`
  );
  label.style.setProperty(
    "--jin-runtime-action-guard-green-rotate",
    `${greenRotate.toFixed(2)}deg`
  );
  label.style.setProperty(
    "--jin-runtime-action-guard-red-rotate",
    `${redRotate.toFixed(2)}deg`
  );
  label.style.setProperty(
    "--jin-runtime-action-guard-z",
    `${depthZ.toFixed(2)}px`
  );
  label.style.setProperty(
    "--jin-runtime-action-guard-scale-x",
    scaleX.toFixed(4)
  );

}

function updateRuntimeActionGuardGeometries(
  root = document
) {

  const scope =
    root instanceof Element
      ? root
      : document;

  scope
    .querySelectorAll(
      ".jin-runtime-action-guard-pending"
    )
    .forEach((row) => {
      updateRuntimeActionGuardGeometry(
        row,
        row.querySelector(
          ".jin-runtime-action-guard-label"
        )
      );
    });

}

function scheduleRuntimeActionGuardGeometryUpdate() {

  if (runtimeActionGuardGeometryFrame) {
    return;
  }

  runtimeActionGuardGeometryFrame =
    window.requestAnimationFrame(
      () => {
        runtimeActionGuardGeometryFrame = null;
        updateRuntimeActionGuardGeometries();
      }
    );

}

function normalizeRuntimeActionKeyPart(value) {

  return String(
    value || ""
  ).trim().toLowerCase();

}

function normalizeRuntimeActionColor(value) {

  const match =
    String(
      value || ""
    ).trim().match(
      /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i
    );

  if (!match) {
    return "";
  }

  let hex =
    match[1].toLowerCase();

  if (hex.length === 3) {
    hex = hex
      .split("")
      .map((char) => char + char)
      .join("");
  }

  return `#${hex}`;

}

function shouldAggregateRuntimeAction(
  _action,
  options = {}
) {

  return options.aggregateMarkers === true;

}

function readRuntimeActionAggregateColors(
  row
) {

  if (!row) {
    return [];
  }

  return String(
    row.dataset.runtimeActionColors || ""
  ).split(",").map(
    normalizeRuntimeActionColor
  ).filter(Boolean);

}

function applyRuntimeActionAggregateState(
  row,
  action,
  options = {}
) {

  if (
    !row
    || !shouldAggregateRuntimeAction(
      action,
      options
    )
  ) {
    return options;
  }

  const currentMarkerCount = Math.max(
    0,
    Number.parseInt(
      row.dataset.runtimeActionMarkerCount || "0",
      10
    ) || 0
  );
  const aggregateStatus = String(
    options.aggregateStatus || ""
  ).trim().toLowerCase();
  const completed = [
    "completed",
    "complete",
    "done",
  ].includes(
    aggregateStatus
  );
  const failed = [
    "failed",
    "blocked",
    "cancelled",
    "canceled",
    "interrupted",
  ].includes(
    aggregateStatus
  );
  const incomingColor =
    normalizeRuntimeActionColor(
      options.color
      || options.payload
      || options.detail
    );
  let storedColors =
    readRuntimeActionAggregateColors(
      row
    );
  let pendingColor =
    normalizeRuntimeActionColor(
      row.dataset.runtimeActionPendingColor
      || ""
    );
  let markerCount =
    currentMarkerCount;

  if (completed) {
    if (incomingColor) {
      storedColors.push(
        incomingColor
      );
    }

    if (pendingColor === incomingColor) {
      pendingColor = "";
    }

    markerCount = currentMarkerCount + 1;
  } else if (failed) {
    pendingColor = "";
  } else if (incomingColor) {
    pendingColor = incomingColor;
  }

  const displayColors = [
    ...storedColors,
  ];

  if (pendingColor) {
    displayColors.push(
      pendingColor
    );
  }

  const displayMarkerCount = Math.max(
    markerCount,
    markerCount + (
      pendingColor
        ? 1
        : 0
    )
  );

  row.dataset.runtimeActionMarkerCount =
    String(markerCount);
  row.dataset.runtimeActionColors =
    storedColors.join(",");

  if (pendingColor) {
    row.dataset.runtimeActionPendingColor =
      pendingColor;
  } else {
    delete row.dataset.runtimeActionPendingColor;
  }

  return {
    ...options,
    aggregateMarkers: true,
    markerCount: displayMarkerCount,
    colors: displayColors,
  };

}

function appendRuntimeActionMarkerCount(
  label,
  count
) {

  const markerCount = Math.max(
    0,
    Number.parseInt(count || 0, 10) || 0
  );

  if (!label || markerCount < 1) {
    return;
  }

  const countLabel =
    document.createElement("span");

  countLabel.className =
    "jin-runtime-action-count";
  countLabel.textContent =
    `(${markerCount})`;

  label.appendChild(
    countLabel
  );

}

function normalizeRuntimeActionLabelText(text) {

  return String(
    text || ""
  ).replace(
    /^CONFIRM:\s*/i,
    ""
  ).trim();

}

function appendRuntimeActionConfirmPrefix(
  label
) {

  if (!label) {
    return;
  }

  const prefix =
    document.createElement("span");

  prefix.className =
    "jin-runtime-action-confirm-prefix";
  prefix.textContent =
    "CONFIRM:";

  label.appendChild(
    prefix
  );

}

function removeRuntimeActionConfirmPrefix(
  label
) {

  if (!label) {
    return;
  }

  label
    .querySelectorAll(
      ":scope > .jin-runtime-action-confirm-prefix"
    )
    .forEach((prefix) => {
      prefix.remove();
    });

}

function renderRuntimeActionLabel(
  label,
  action,
  text,
  options = {}
) {

  if (!label) {
    return;
  }

  label.replaceChildren();

  if (options.guardConfirmation) {
    appendRuntimeActionConfirmPrefix(
      label
    );
  }

  if (action === "jin_color") {
    const colors = Array.isArray(
      options.colors
    )
      ? options.colors
          .map(normalizeRuntimeActionColor)
          .filter(Boolean)
      : [
          normalizeRuntimeActionColor(
            options.color
            || options.payload
            || options.detail
          ),
        ].filter(Boolean);

    colors.forEach((color) => {
      const swatch =
        document.createElement("span");

      swatch.className =
        "jin-runtime-action-color-swatch";
      swatch.style.backgroundColor =
        color;
      swatch.style.color =
        color;
      swatch.title =
        color;

      label.appendChild(
        swatch
      );
    });

    const name =
      document.createElement("span");

    name.className =
      "jin-runtime-action-name";
    name.textContent =
      "JIN_COLOR";

    label.appendChild(
      name
    );
    appendRuntimeActionMarkerCount(
      label,
      options.markerCount
    );
    return;
  }

  const name =
    document.createElement("span");

  name.className =
    "jin-runtime-action-name";
  name.textContent =
    normalizeRuntimeActionLabelText(
      text
    );

  label.appendChild(
    name
  );

  if (options.aggregateMarkers) {
    appendRuntimeActionMarkerCount(
      label,
      options.markerCount
    );
  }

}

function buildRuntimeActionVisibleKey(
  action,
  options = {}
) {

  const actionName =
    normalizeRuntimeActionKeyPart(
      action
    );

  const actionId =
    normalizeRuntimeActionKeyPart(
      options.id
    );

  if (actionId) {
    return `${actionName}:${actionId}`;
  }

  runtimeActionRowCounter += 1;

  return `${jinConversationTurnCounter}:${actionName}:${runtimeActionRowCounter}`;

}

function clearRuntimeActionGuardConfirmation(
  row
) {

  if (!row) {
    return;
  }

  if (row._runtimeActionGuardTimer) {
    window.clearTimeout(
      row._runtimeActionGuardTimer
    );
    row._runtimeActionGuardTimer = null;
  }

  row.classList.remove(
    ...runtimeActionGuardDecisionClasses
  );

  const label =
    row.querySelector(
      ".jin-runtime-action-label"
    );

  if (!label) {
    return;
  }

  label.classList.remove(
    "jin-runtime-action-guard-label"
  );
  label.style.removeProperty(
    "--jin-runtime-action-guard-motion"
  );
  label.style.removeProperty(
    "--jin-runtime-action-guard-green-x"
  );
  label.style.removeProperty(
    "--jin-runtime-action-guard-red-x"
  );
  label.style.removeProperty(
    "--jin-runtime-action-guard-perspective"
  );
  label.style.removeProperty(
    "--jin-runtime-action-guard-green-rotate"
  );
  label.style.removeProperty(
    "--jin-runtime-action-guard-red-rotate"
  );
  label.style.removeProperty(
    "--jin-runtime-action-guard-z"
  );
  label.style.removeProperty(
    "--jin-runtime-action-guard-scale-x"
  );

  label
    .querySelectorAll(
      ":scope > .jin-runtime-action-guard-zones"
    )
    .forEach((zones) => {
      zones.remove();
    });

  delete row.dataset.runtimeActionGuardConfirmationId;
  delete row.dataset.runtimeActionGuardDecision;

}

function settleRuntimeActionGuardConfirmation(
  row,
  decision
) {

  if (!row) {
    return;
  }

  if (row._runtimeActionGuardTimer) {
    window.clearTimeout(
      row._runtimeActionGuardTimer
    );
    row._runtimeActionGuardTimer = null;
  }

  row.classList.remove(
    "jin-runtime-action-guard-pending"
  );

  row.classList.add(
    decision === "reject"
      ? "jin-runtime-action-guard-rejected"
      : "jin-runtime-action-guard-continued"
  );

  row.dataset.runtimeActionGuardDecision =
    decision;

  row.classList.toggle(
    "jin-runtime-action-cancelled",
    decision === "reject"
  );

  if (decision === "reject") {
    row.dataset.runtimeActionCancelled =
      "true";
  } else {
    delete row.dataset.runtimeActionCancelled;
  }

  const zones =
    row.querySelector(
      ".jin-runtime-action-guard-zones"
    );

  if (zones) {
    zones.remove();
  }

  normalizeCompletedRuntimeActionLabel(
    row
  );

}

function bindRuntimeActionGuardConfirmation(
  row,
  label,
  action,
  options = {}
) {

  const confirmation =
    options.guardConfirmation || {};
  const confirmationId =
    String(
      confirmation.confirmationId
      || confirmation.confirmation_id
      || ""
    ).trim();

  if (
      !row
      || !label
      || !confirmationId
  ) {
    return;
  }

  row.classList.remove(
    "opacity-45",
    "jin-runtime-action-guard-rejected",
    "jin-runtime-action-guard-continued"
  );
  row.classList.add(
    "jin-runtime-action-guard-pending"
  );
  row.dataset.runtimeActionGuardConfirmationId =
    confirmationId;

  label.classList.add(
    "jin-runtime-action-guard-label"
  );
  label.style.setProperty(
    "--jin-runtime-action-guard-motion",
    `${RUNTIME_ACTION_GUARD_ANIMATION_DURATION_MS}ms`
  );
  updateRuntimeActionGuardGeometry(
    row,
    label
  );

  window.requestAnimationFrame(
    () => {
      updateRuntimeActionGuardGeometry(
        row,
        label
      );
    }
  );

  const timeoutMs =
    resolveRuntimeActionGuardConfirmationDelayMs(
      confirmation
    );

  if (
    label.querySelector(
      ":scope > .jin-runtime-action-guard-zones"
    )
  ) {
    return;
  }

  const zones =
    document.createElement("div");
  zones.className =
    "jin-runtime-action-guard-zones";
  zones.setAttribute(
    "aria-hidden",
    "true"
  );

  [
    [
      "reject",
      "jin-runtime-action-guard-zone jin-runtime-action-guard-zone-reject",
      "cancel this action",
    ],
    [
      "continue",
      "jin-runtime-action-guard-zone jin-runtime-action-guard-zone-continue",
      "continue this action",
    ],
  ].forEach(([decision, className, title]) => {
    const zone =
      document.createElement("button");
    zone.type =
      "button";
    zone.className =
      className;
    zone.title =
      title;
    zone.dataset.runtimeActionGuardDecision =
      decision;

    zone.addEventListener(
      "click",
      (event) => {
        event.preventDefault();
        event.stopPropagation();

        if (
          row.dataset.runtimeActionGuardDecision
        ) {
          return;
        }

        const sent =
          window.sendSocketMessage
            ? window.sendSocketMessage({
              type: "runtime_action_guard_confirmation",
              confirmation_id: confirmationId,
              action: action || "",
              id: options.id || "",
              guard: confirmation.guard || "",
              decision,
            })
            : false;

        if (!sent) {
          return;
        }

        settleRuntimeActionGuardConfirmation(
          row,
          decision
        );
      }
    );

    zones.appendChild(
      zone
    );
  });

  label.appendChild(
    zones
  );

  if (timeoutMs > 0) {
    if (row._runtimeActionGuardTimer) {
      window.clearTimeout(
        row._runtimeActionGuardTimer
      );
    }

    row._runtimeActionGuardTimer =
      window.setTimeout(
        () => {
          if (
            row.dataset.runtimeActionGuardDecision
          ) {
            return;
          }

          settleRuntimeActionGuardConfirmation(
            row,
            "continue"
          );
        },
        timeoutMs
      );
  }

}

function updateRuntimeActionRow(
  row,
  action,
  text,
  options = {}
) {

  const label =
    row.querySelector(
      ".jin-runtime-action-label"
    );

  if (!label) {
    return false;
  }

  options = applyRuntimeActionAggregateState(
    row,
    action,
    options
  );

  if (options.reviveExisting) {
    reviveRuntimeActionRow(
      row
    );
  }

  if (!options.preserveLabel) {
    renderRuntimeActionLabel(
      label,
      action,
      text,
      options
    );
  }

  row.classList.toggle(
    "jin-runtime-action-cancelled",
    Boolean(options.cancelled)
  );

  if (options.cancelled) {
    row.dataset.runtimeActionCancelled =
      "true";
  } else if (options.reviveExisting) {
    delete row.dataset.runtimeActionCancelled;
  }

  const detail =
    String(
      options.detail || ""
    ).trim();

  if (detail) {
    label.title = detail;
    label.classList.add(
      "cursor-help"
    );
  } else {
    label.removeAttribute(
      "title"
    );
    label.classList.remove(
      "cursor-help"
    );
  }

  if (action === "asset_action") {
    bindAssetResultPreview(
      label,
      options.assetResult || null
    );
  }

  if (action === "save_delayed_memory_content") {
    bindDelayedMemoryReportPreview(
      label,
      options.delayedMemoryReport || null,
      options.delayedMemoryReportId || ""
    );
  }

  if (options.guardConfirmation) {
    bindRuntimeActionGuardConfirmation(
      row,
      label,
      action,
      options
    );
  } else {
    clearRuntimeActionGuardConfirmation(
      row
    );
  }

  if (options.completed) {
    markRuntimeActionRowCompleted(
      row
    );
  }

  return true;

}

function normalizeCompletedRuntimeActionLabel(
  row
) {

  const label =
    row
      ? row.querySelector(
        ".jin-runtime-action-label"
      )
      : null;

  if (!label) {
    return;
  }

  removeRuntimeActionConfirmPrefix(
    label
  );

  if (
      row.dataset.runtimeAction
      === "jin_color"
      || row.dataset.runtimeActionMarkerCount
  ) {
    return;
  }

  const normalizedText =
    normalizeRuntimeActionLabelText(
      label.textContent
    );

  if (!normalizedText) {
    return;
  }

  let name =
    label.querySelector(
      ":scope > .jin-runtime-action-name"
    );

  if (!name) {
    label.replaceChildren();
    name = document.createElement("span");
    name.className =
      "jin-runtime-action-name";
    label.appendChild(
      name
    );
  }

  name.textContent =
    normalizedText;

}

function reviveRuntimeActionRow(
  row
) {

  if (!row) {
    return;
  }

  delete row.dataset.runtimeActionCompleted;
  delete row.dataset.runtimeActionCancelled;
  row.classList.remove(
    "opacity-45",
    "jin-runtime-action-cancelled"
  );

  row
    .querySelectorAll("div, button")
    .forEach((element) => {
      element.classList.remove(
        "border-zinc-700/50",
        "bg-zinc-900/30",
        "text-zinc-400"
      );
    });

}

function markRuntimeActionRowCompleted(
  row
) {

  if (!row) {
    return;
  }

  row.dataset.runtimeActionCompleted =
    "true";

  clearRuntimeActionGuardConfirmation(
    row
  );

  normalizeCompletedRuntimeActionLabel(
    row
  );

  row.classList.add(
    "opacity-45"
  );

  row
    .querySelectorAll("div, button")
    .forEach((element) => {
      element.classList.add(
        "border-zinc-700/50",
        "bg-zinc-900/30",
        "text-zinc-400"
      );
    });

}

function appendRuntimeAction(
  action,
  text,
  options = {}
) {

  // A preceding reasoning/answer chunk can still be waiting for a paused RAF
  // when the browser is in the background. Flush it before inserting or
  // updating the action row, otherwise the row can jump above its reasoning.
  if (typeof window.flushStreamFrame === "function") {
    window.flushStreamFrame();
  }

  const actionText =
    String(
      text || ""
    );

  if (!actionText.trim()) {
    return false;
  }

  const shouldUpdateExisting =
    options.updateExisting !== false;

  const actionKey =
    buildRuntimeActionVisibleKey(
      action,
      options
    );

  if (shouldUpdateExisting) {
    const existingRows =
      options.id
        ? chatHistory.querySelectorAll(
          `[data-runtime-action-key="${actionKey}"]`
        )
        : [];

    let existingRow =
      Array.from(
        existingRows
      ).find((row) => {
        return (
          options.reuseCompleted
          || row.dataset.runtimeActionCompleted !== "true"
        );
      });

    const guardConfirmationId =
      String(
        options.guardConfirmationId
        || options.confirmationId
        || ""
      ).trim();

    if (
        !existingRow
        && guardConfirmationId
    ) {
      existingRow =
        Array.from(
          chatHistory.querySelectorAll(
            ".jin-runtime-action-row"
          )
        ).find((row) => {
          return (
            row.dataset.runtimeActionCompleted !== "true"
            && row.dataset.runtimeActionGuardConfirmationId
              === guardConfirmationId
          );
        });
    }

    if (
        !existingRow
        && action
    ) {
      existingRow =
        Array.from(
          chatHistory.querySelectorAll(
            `.jin-runtime-action-row[data-runtime-action="${action}"]`
          )
        ).find((row) => {
          return (
            row.dataset.runtimeActionCompleted !== "true"
            && Boolean(
              row.dataset.runtimeActionGuardConfirmationId
              || row.dataset.runtimeActionGuardDecision
            )
          );
        });
    }

    if (
        !existingRow
        && shouldAggregateRuntimeAction(
          action,
          options
        )
    ) {
      const rows = Array.from(
        chatHistory.querySelectorAll(
          `.jin-runtime-action-row[data-runtime-action="${action}"]`
        )
      ).reverse();

      existingRow = rows.find((row) => (
        row.dataset.runtimeActionTurn
          === String(jinConversationTurnCounter)
        && (
          options.reuseCompleted
          || row.dataset.runtimeActionCompleted !== "true"
        )
      ));
    }

    if (
        existingRow
        && updateRuntimeActionRow(
          existingRow,
          action,
          actionText,
          {
            ...options,
            reviveExisting:
              Boolean(
                options.reuseCompleted
              ),
          }
        )
    ) {
      return true;
    }
  }

  if (options.activateScene !== false) {
    syncSceneSearchScreenForRuntimeAction(
      action,
      true
    );
  }

  const row =
    document.createElement("div");

  row.className =
    "jin-message-row jin-runtime-action-row mx-auto w-full max-w-4xl text-xs text-cyan-100 transition duration-500";

  if (action === "jin_color") {
    row.classList.add(
      "jin-runtime-action-color-row"
    );
  }

  row.dataset.runtimeAction =
    action || "";

  row.dataset.runtimeActionKey =
    actionKey || "";
  row.dataset.runtimeActionTurn =
    String(jinConversationTurnCounter);

  options = applyRuntimeActionAggregateState(
    row,
    action,
    options
  );

  if (options.cancelled) {
    row.dataset.runtimeActionCancelled =
      "true";
    row.classList.add(
      "jin-runtime-action-cancelled"
    );
  }

  if (options.completed) {
    row.dataset.runtimeActionCompleted =
      "true";
  }

  const icon =
    document.createElement(
      options.contextSnapshot
        ? "button"
        : "div"
    );

  if (options.contextSnapshot) {
    icon.type =
      "button";
  }

  icon.className =
    "h-6 w-6 rounded bg-cyan-950/70 border border-cyan-700 flex items-center justify-center text-[12px] shrink-0";

  icon.textContent =
    action === "web_search"
      ? "🔍"
      : action === "list_skills"
        ? "📘"
        : action === "asset_action"
          ? "▣"
      : "●";

  if (options.contextSnapshot) {
    icon.className +=
      " cursor-help hover:bg-cyan-900/70 transition";

    icon.title =
      "show action context";

    icon.addEventListener(
      "click",
      function () {
        if (!window.showTrace) {
          return;
        }

        window.showTrace(
          formatContextSnapshot(
            "action",
            options.contextSnapshot
          ),
          formatRuntimeActionContextTitle(
            action,
            options.contextSnapshot
          )
        );
      }
    );
  }

  const label =
    document.createElement("div");

  label.className =
    "jin-runtime-action-label px-3 py-2 rounded-lg border border-cyan-700/70 bg-cyan-950/40 font-mono transition duration-500";

  renderRuntimeActionLabel(
    label,
    action,
    actionText,
    options
  );

  const detail =
    String(
      options.detail || ""
    ).trim();

  if (detail) {
    label.title = detail;
    label.classList.add(
      "cursor-help"
    );
  }

  if (action === "asset_action") {
    bindAssetResultPreview(
      label,
      options.assetResult || null
    );
  }

  if (action === "save_delayed_memory_content") {
    bindDelayedMemoryReportPreview(
      label,
      options.delayedMemoryReport || null,
      options.delayedMemoryReportId || ""
    );
  }

  if (options.guardConfirmation) {
    bindRuntimeActionGuardConfirmation(
      row,
      label,
      action,
      options
    );
  }

  row.appendChild(
    icon
  );

  row.appendChild(
    label
  );

  if (options.completed) {
    markRuntimeActionRowCompleted(
      row
    );
  }

  chatHistory.appendChild(
    row
  );

  chatHistory.scrollTop =
    chatHistory.scrollHeight;

  return true;

}

window.addEventListener(
  "resize",
  scheduleRuntimeActionGuardGeometryUpdate
);

window.requestAnimationFrame(
  () => {
    updateRuntimeActionGuardGeometries();
  }
);


function queueRuntimeActionAfterNextResponse(
  action,
  text,
  options = {}
) {

  const actionText =
    String(
      text || ""
    );

  if (!actionText.trim()) {
    return;
  }

  deferredRuntimeActionsAfterResponse.push({
    action:
      action || "",
    text: actionText,
    id: options.id || "",
    contextSnapshot:
      options.contextSnapshot || null,
    assetResult:
      options.assetResult || null,
    detail:
      options.detail || "",
    completed: false,
  });

}


function isResponseRole(
  role
) {

  return ![
    "user",
    "system",
  ].includes(
    String(role || "").toLowerCase()
  );

}


function flushRuntimeActionsAfterResponse(
  role
) {

  if (
    !isResponseRole(role)
    || !deferredRuntimeActionsAfterResponse.length
  ) {
    return;
  }

  const actions =
    deferredRuntimeActionsAfterResponse.splice(0);

  actions.forEach((entry) => {
    appendRuntimeAction(
      entry.action,
      entry.text,
      {
        id: entry.id || "",
        contextSnapshot:
          entry.contextSnapshot || null,
        assetResult:
          entry.assetResult || null,
        detail:
          entry.detail || "",
        completed:
          entry.completed,
        activateScene: !entry.completed,
      }
    );

    if (entry.completed) {
      fadeRuntimeAction(
        entry.action
      );
    }
  });

}


function fadeRuntimeAction(
  action,
  options = {}
) {

  const actionKey =
    options.id
      ? buildRuntimeActionVisibleKey(
        action,
        options
      )
      : "";

  deferredRuntimeActionsAfterResponse.forEach((entry) => {
    if (
      entry.action === action
      && (
        !options.id
        || entry.id === options.id
      )
    ) {
      entry.completed = true;
    }
  });

  syncSceneSearchScreenForRuntimeAction(
    action,
    false
  );

  const rows =
    actionKey
      ? chatHistory.querySelectorAll(
        `[data-runtime-action-key="${actionKey}"]`
      )
      : chatHistory.querySelectorAll(
        `[data-runtime-action="${action}"]`
      );

  rows.forEach((row) => {
    markRuntimeActionRowCompleted(
      row
    );
  });

}

window.setSceneSearchScreenActive =
  setSceneSearchScreenActive;

window.appendRuntimeAction =
  appendRuntimeAction;

window.queueRuntimeActionAfterNextResponse =
  queueRuntimeActionAfterNextResponse;

window.fadeRuntimeAction =
  fadeRuntimeAction;
