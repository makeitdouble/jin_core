const deferredRuntimeActionsAfterResponse = [];
let runtimeActionRowCounter = 0;

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
  active,
  options = {}
) {
  const sceneEffect =
    String(
      options.sceneEffect
      || options.scene_effect
      || ""
    ).trim().toLowerCase();

  if (sceneEffect !== "search") {
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
const RUNTIME_ACTION_SAVE_SESSION = "save_session";
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
let saveSessionPendingUntilL3Active = false;

function isSaveSessionRuntimeAction(
  action
) {

  return String(
    action || ""
  ).trim().toLowerCase() === RUNTIME_ACTION_SAVE_SESSION;

}

function setRuntimeActionPendingUntilL3(
  row,
  pending
) {

  if (!row) {
      return;
  }

  if (
      isSaveSessionRuntimeAction(
        row.dataset.runtimeAction
      )
      && pending
      && runtimeActionRowIsTerminal(
        row
      )
  ) {
    saveSessionPendingUntilL3Active = false;
    row.classList.remove(
      "jin-runtime-action-pending-l3"
    );
    delete row.dataset.runtimeActionPendingL3;
    return;
  }

  if (
      isSaveSessionRuntimeAction(
        row.dataset.runtimeAction
      )
  ) {
    saveSessionPendingUntilL3Active =
      Boolean(pending);
  }

  row.classList.toggle(
    "jin-runtime-action-pending-l3",
    pending
  );

  if (!pending) {
    delete row.dataset.runtimeActionPendingL3;
    if (
        isSaveSessionRuntimeAction(
          row.dataset.runtimeAction
        )
    ) {
      saveSessionPendingUntilL3Active = false;
    }
    return;
  }

  row.dataset.runtimeActionPendingL3 =
    "true";
  delete row.dataset.runtimeActionCompleted;
  delete row.dataset.runtimeActionCompletionDeferred;
  row.classList.remove(
    "opacity-45",
    ...runtimeActionGuardDecisionClasses
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

function runtimeActionRowIsTerminal(
  row
) {

  const text =
    String(
      row
        && row.textContent
        || ""
    ).toLowerCase();

  return (
    !row
    || row.dataset.runtimeActionCancelled === "true"
    || row.classList.contains(
      "jin-runtime-action-cancelled"
    )
    || /\baborted\b/.test(text)
    || /\bcancelled\b/.test(text)
  );

}

function activateRuntimeActionPendingUntilL3(
  action = RUNTIME_ACTION_SAVE_SESSION
) {

  const normalizedAction =
    String(action || "").trim().toLowerCase();

  if (
      normalizedAction !== RUNTIME_ACTION_SAVE_SESSION
  ) {
    return false;
  }

  const rows = Array.from(
    chatHistory.querySelectorAll(
      `[data-runtime-action="${RUNTIME_ACTION_SAVE_SESSION}"]`
    )
  ).filter((row) => (
    !runtimeActionRowIsTerminal(
      row
    )
  ));

  const currentTurn =
    String(jinConversationTurnCounter);
  const row =
    (
      rows.findLast
        ? rows.findLast((candidate) => (
          candidate.dataset.runtimeActionTurn === currentTurn
        ))
        : rows
            .slice()
            .reverse()
            .find((candidate) => (
              candidate.dataset.runtimeActionTurn === currentTurn
            ))
    )
    || rows[rows.length - 1]
    || null;

  if (!row) {
    saveSessionPendingUntilL3Active = false;
    return false;
  }

  setRuntimeActionPendingUntilL3(
    row,
    true
  );

  return true;

}

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

function runtimeActionRowMatchesRuntimeTurn(
  row,
  runtimeTurnId
) {

  const normalizedRuntimeTurnId =
    normalizeRuntimeActionKeyPart(
      runtimeTurnId
    );

  if (!normalizedRuntimeTurnId) {
    return true;
  }

  return normalizeRuntimeActionKeyPart(
    row
      && row.dataset.runtimeActionRuntimeTurn
  ) === normalizedRuntimeTurnId;

}

function runtimeActionRowMatchesMessage(
  row,
  runtimeMessageId
) {

  const normalizedRuntimeMessageId =
    normalizeRuntimeActionKeyPart(
      runtimeMessageId
    );

  if (!normalizedRuntimeMessageId) {
    return true;
  }

  return normalizeRuntimeActionKeyPart(
    row
      && row.dataset.runtimeActionRuntimeMessage
  ) === normalizedRuntimeMessageId;

}

function runtimeActionRowMatchesScope(
  row,
  runtimeTurnId,
  runtimeMessageId
) {

  return (
    runtimeActionRowMatchesRuntimeTurn(
      row,
      runtimeTurnId
    )
    && runtimeActionRowMatchesMessage(
      row,
      runtimeMessageId
    )
  );

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

function extractRuntimeActionColorFromText(text) {

  const match =
    String(
      text || ""
    ).match(
      /#?(?:[0-9a-f]{6}|[0-9a-f]{3})\b/i
    );

  return match
    ? normalizeRuntimeActionColor(
      match[0]
    )
    : "";

}

function shouldAggregateRuntimeAction(
  _action,
  options = {}
) {

  const markerCount = Math.max(
    0,
    Number.parseInt(
      options.markerCount || 0,
      10
    ) || 0
  );

  return (
    options.aggregateMarkers === true
    || options.counterOnly === true
    || markerCount > 0
  );

}

function hasActiveRuntimeActionCounter(
  action,
  runtimeTurnId = "",
  runtimeMessageId = ""
) {

  const normalizedAction =
    normalizeRuntimeActionKeyPart(
      action
    );

  if (!normalizedAction) {
    return false;
  }

  return Array.from(
    chatHistory.querySelectorAll(
      `.jin-runtime-action-row[data-runtime-action="${normalizedAction}"]`
    )
  ).some((row) => (
    row.dataset.runtimeActionTurn
      === String(jinConversationTurnCounter)
    && runtimeActionRowMatchesScope(
      row,
      runtimeTurnId,
      runtimeMessageId
    )
    && Math.max(
      0,
      Number.parseInt(
        row.dataset.runtimeActionMarkerCount || "0",
        10
      ) || 0
    ) > 0
  ));

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
  text = "",
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
  const explicitMarkerCount = Math.max(
    0,
    Number.parseInt(
      options.markerCount || 0,
      10
    ) || 0
  );
  const explicitColors = Array.isArray(
    options.colors
  )
    ? options.colors
        .map(normalizeRuntimeActionColor)
        .filter(Boolean)
    : [];
  const incomingColor =
    normalizeRuntimeActionColor(
      options.color
      || options.payload
      || options.detail
    )
    || extractRuntimeActionColorFromText(
      text
    );
  const markerCount = Math.max(
    currentMarkerCount,
    explicitMarkerCount
  );
  let storedColors =
    readRuntimeActionAggregateColors(
      row
    );

  if (explicitColors.length) {
    storedColors = explicitColors;
  } else if (
    incomingColor
    && options.counterOnly !== true
    && storedColors[storedColors.length - 1]
      !== incomingColor
  ) {
    storedColors.push(
      incomingColor
    );
  }

  if (markerCount > 0) {
    row.dataset.runtimeActionMarkerCount =
      String(markerCount);
  }

  if (storedColors.length) {
    row.dataset.runtimeActionColors =
      storedColors.join(",");
  } else {
    delete row.dataset.runtimeActionColors;
  }

  delete row.dataset.runtimeActionPendingColor;

  return {
    ...options,
    aggregateMarkers: true,
    markerCount,
    colors: storedColors,
  };

}

function syncRuntimeActionMarkerCount(
  label,
  count
) {

  if (!label) {
    return;
  }

  const markerCount = Math.max(
    0,
    Number.parseInt(count || 0, 10) || 0
  );
  const countLabels = Array.from(
    label.querySelectorAll(
      ":scope > .jin-runtime-action-count"
    )
  );
  let countLabel = countLabels.shift() || null;

  countLabels.forEach((duplicate) => {
    duplicate.remove();
  });

  if (markerCount <= 1) {
    if (countLabel) {
      countLabel.remove();
    }
    return;
  }

  if (!countLabel) {
    countLabel = document.createElement("span");
    countLabel.className =
      "jin-runtime-action-count";
    label.appendChild(
      countLabel
    );
  }

  countLabel.textContent =
    formatRuntimeActionCountLabel(
      markerCount
    );

}

function appendRuntimeActionMarkerCount(
  label,
  count
) {

  syncRuntimeActionMarkerCount(
    label,
    count
  );

}

function syncRuntimeActionCancelledState(
  row,
  cancelled
) {

  if (!row) {
    return;
  }

  if (cancelled === undefined) {
    return;
  }

  const isCancelled =
    Boolean(cancelled);

  row.classList.toggle(
    "jin-runtime-action-cancelled",
    isCancelled
  );

  row
    .querySelectorAll(
      ".jin-runtime-action-label"
    )
    .forEach((label) => {
      label.classList.toggle(
        "jin-runtime-action-label-cancelled",
        isCancelled
      );
    });

  if (isCancelled) {
    row.dataset.runtimeActionCancelled =
      "true";
    setRuntimeActionPendingUntilL3(
      row,
      false
    );
    row.classList.add(
      "opacity-45"
    );
  } else {
    delete row.dataset.runtimeActionCancelled;
  }

  row
    .querySelectorAll(
      ".jin-runtime-action-name"
    )
    .forEach((name) => {
      name.classList.toggle(
        "jin-runtime-action-name-cancelled",
        isCancelled
      );
    });

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
    const textColor =
      extractRuntimeActionColorFromText(
        text
      );
    const explicitColors = Array.isArray(
      options.colors
    )
      ? options.colors
          .map(normalizeRuntimeActionColor)
          .filter(Boolean)
      : [];
    const colors = explicitColors.length
      ? explicitColors
      : [
          normalizeRuntimeActionColor(
            options.color
            || options.payload
            || options.detail
          )
          || textColor,
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
      String(
        options.displayName
        || "JIN_COLOR"
      ).trim()
      || "JIN_COLOR";

    label.appendChild(
      name
    );

    const payloadColor =
      colors.length
        ? colors[colors.length - 1]
        : normalizeRuntimeActionColor(
          options.color
          || options.payload
          || options.detail
        )
        || textColor;

    if (payloadColor) {
      const payload =
        document.createElement("span");

      payload.className =
        "jin-runtime-action-payload";
      payload.textContent =
        `: ${payloadColor}`;

      label.appendChild(
        payload
      );
    }

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

  appendRuntimeActionMarkerCount(
    label,
    options.markerCount
  );

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
  const runtimeMessageId =
    normalizeRuntimeActionKeyPart(
      options.runtimeMessageId
    );

  if (actionId) {
    if (runtimeMessageId) {
      return `${actionName}:${runtimeMessageId}:${actionId}`;
    }

    return `${actionName}:${actionId}`;
  }

  runtimeActionRowCounter += 1;

  return `${jinConversationTurnCounter}:${actionName}:${runtimeActionRowCounter}`;

}

function removeDuplicateRuntimeActionRows(
  primaryRow,
  actionKey,
  options = {}
) {

  if (
      !primaryRow
      || !actionKey
  ) {
    return;
  }

  Array.from(
    chatHistory.querySelectorAll(
      `[data-runtime-action-key="${actionKey}"]`
    )
  ).forEach((row) => {
    if (
        row !== primaryRow
        && runtimeActionRowMatchesScope(
          row,
          options.runtimeTurnId,
          options.runtimeMessageId
        )
    ) {
      row.remove();
    }
  });

}

function removeLegacyRuntimeActionRows(
  primaryRow,
  action,
  options = {}
) {

  if (
      !primaryRow
      || !action
      || !options.id
      || !options.runtimeMessageId
  ) {
    return;
  }

  const legacyKey =
    buildRuntimeActionVisibleKey(
      action,
      {
        ...options,
        runtimeMessageId: "",
      }
    );

  Array.from(
    chatHistory.querySelectorAll(
      `[data-runtime-action-key="${legacyKey}"]`
    )
  ).forEach((row) => {
    if (
        row !== primaryRow
        && row.dataset.runtimeActionTurn
          === String(jinConversationTurnCounter)
        && !row.dataset.runtimeActionRuntimeMessage
    ) {
      row.remove();
    }
  });

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

  if (
      isSaveSessionRuntimeAction(
        row.dataset.runtimeAction
      )
      && decision === "continue"
  ) {
    setRuntimeActionPendingUntilL3(
      row,
      true
    );
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

  syncRuntimeActionCancelledState(
    row,
    decision === "reject"
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
    text,
    options
  );

  if (options.reviveExisting) {
    reviveRuntimeActionRow(
      row
    );
  }

  if (
    !options.preserveLabel
    || action === "jin_color"
  ) {
    renderRuntimeActionLabel(
      label,
      action,
      text,
      options
    );
    if (
        row.dataset.runtimeActionCancelled === "true"
        && options.cancelled !== false
    ) {
      syncRuntimeActionCancelledState(
        row,
        true
      );
    }
  } else {
    syncRuntimeActionMarkerCount(
      label,
      options.markerCount
    );
  }

  syncRuntimeActionCancelledState(
    row,
    options.cancelled
  );

  const pendingUntilL3 =
    Boolean(options.pendingUntilL3)
    || (
      isSaveSessionRuntimeAction(
        action
      )
      && saveSessionPendingUntilL3Active
      && options.cancelled !== true
      && options.forceCompletePendingL3 !== true
    )
    || (
      isSaveSessionRuntimeAction(
        action
      )
      && row.dataset.runtimeActionPendingL3 === "true"
      && options.cancelled !== true
      && options.forceCompletePendingL3 !== true
    );

  if (pendingUntilL3) {
    setRuntimeActionPendingUntilL3(
      row,
      true
    );
  } else if (
      options.completed
      || options.cancelled
      || options.forceCompletePendingL3
  ) {
    setRuntimeActionPendingUntilL3(
      row,
      false
    );
    delete row.dataset.runtimeActionCompletionDeferred;
  } else {
    row.classList.remove(
      "jin-runtime-action-pending-l3"
    );
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
    if (
      options.delayedMemoryReport
      || options.delayedMemoryReportId
      || options.counterOnly !== true
    ) {
      bindDelayedMemoryReportPreview(
        label,
        options.delayedMemoryReport || null,
        options.delayedMemoryReportId || ""
      );
    }
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
      row,
      options
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
  delete row.dataset.runtimeActionPendingL3;
  row.classList.remove(
    "opacity-45",
    "jin-runtime-action-cancelled",
    "jin-runtime-action-pending-l3"
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

  syncRuntimeActionCancelledState(
    row,
    false
  );

}

function markRuntimeActionRowCompleted(
  row,
  options = {}
) {

  if (!row) {
    return;
  }

  if (
      isSaveSessionRuntimeAction(
        row.dataset.runtimeAction
      )
      && options.forceCompletePendingL3 !== true
  ) {
    setRuntimeActionPendingUntilL3(
      row,
      true
    );
    row.dataset.runtimeActionCompletionDeferred =
      "true";
    row.classList.remove(
      "opacity-45"
    );
    return;
  }

  if (
      isSaveSessionRuntimeAction(
        row.dataset.runtimeAction
      )
  ) {
    saveSessionPendingUntilL3Active = false;
  }

  row.dataset.runtimeActionCompleted =
    "true";

  delete row.dataset.runtimeActionPendingL3;
  delete row.dataset.runtimeActionCompletionDeferred;
  row.classList.remove(
    "jin-runtime-action-pending-l3"
  );

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
          runtimeActionRowMatchesMessage(
            row,
            options.runtimeMessageId
          )
          && (
            options.reuseCompleted
            || row.dataset.runtimeActionCompleted !== "true"
          )
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
            (
              options.pendingUntilL3
              || row.dataset.runtimeActionCompleted !== "true"
            )
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
            (
              options.pendingUntilL3
              || row.dataset.runtimeActionCompleted !== "true"
            )
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
        && runtimeActionRowMatchesScope(
          row,
          options.runtimeTurnId,
          options.runtimeMessageId
        )
        && (
          options.reuseCompleted
          || row.dataset.runtimeActionCompleted !== "true"
        )
      ));
    }

    if (
        !existingRow
        && options.fallbackToLatestActive
        && action
    ) {
      const activeRows = Array.from(
        chatHistory.querySelectorAll(
          `.jin-runtime-action-row[data-runtime-action="${action}"]`
        )
      ).filter((row) => (
        row.dataset.runtimeActionTurn
          === String(jinConversationTurnCounter)
        && runtimeActionRowMatchesScope(
          row,
          options.runtimeTurnId,
          options.runtimeMessageId
        )
        && row.dataset.runtimeActionCompleted !== "true"
      ));

      existingRow =
        activeRows[activeRows.length - 1] || null;
    }

    if (
        !existingRow
        && options.pendingUntilL3
        && action
    ) {
      const pendingRows = Array.from(
        chatHistory.querySelectorAll(
          `.jin-runtime-action-row[data-runtime-action="${action}"]`
        )
      ).filter((row) => (
        row.dataset.runtimeActionCancelled !== "true"
      ));

      existingRow =
        pendingRows.findLast
          ? (
            pendingRows.findLast((row) => (
              row.dataset.runtimeActionTurn
                === String(jinConversationTurnCounter)
            ))
            || pendingRows[pendingRows.length - 1]
            || null
          )
          : (
            pendingRows
              .slice()
              .reverse()
              .find((row) => (
                row.dataset.runtimeActionTurn
                  === String(jinConversationTurnCounter)
              ))
            || pendingRows[pendingRows.length - 1]
            || null
          );
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
                (
                  options.reuseCompleted
                  || options.pendingUntilL3
                )
                && options.reviveCompleted !== false
              ),
          }
        )
    ) {
      if (options.id) {
        existingRow.dataset.runtimeActionKey =
          actionKey || "";
      }
      if (options.runtimeTurnId) {
        existingRow.dataset.runtimeActionRuntimeTurn =
          String(options.runtimeTurnId);
      }
      if (options.runtimeMessageId) {
        existingRow.dataset.runtimeActionRuntimeMessage =
          String(options.runtimeMessageId);
      }
      removeDuplicateRuntimeActionRows(
        existingRow,
        actionKey,
        options
      );
      removeLegacyRuntimeActionRows(
        existingRow,
        action,
        options
      );
      return true;
    }
  }

  if (options.counterOnly === true) {
    return false;
  }

  if (options.activateScene !== false) {
    syncSceneSearchScreenForRuntimeAction(
      action,
      true,
      options
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

  if (options.runtimeTurnId) {
    row.dataset.runtimeActionRuntimeTurn =
      String(options.runtimeTurnId);
  }

  if (options.runtimeMessageId) {
    row.dataset.runtimeActionRuntimeMessage =
      String(options.runtimeMessageId);
  }

  options = applyRuntimeActionAggregateState(
    row,
    action,
    actionText,
    options
  );

  if (options.completed) {
    row.dataset.runtimeActionCompleted =
      "true";
  }

  if (options.pendingUntilL3) {
    setRuntimeActionPendingUntilL3(
      row,
      true
    );
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

  syncRuntimeActionCancelledState(
    row,
    options.cancelled
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
    if (
      options.delayedMemoryReport
      || options.delayedMemoryReportId
      || options.counterOnly !== true
    ) {
      bindDelayedMemoryReportPreview(
        label,
        options.delayedMemoryReport || null,
        options.delayedMemoryReportId || ""
      );
    }
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
      row,
      options
    );
  }

  chatHistory.appendChild(
    row
  );

  removeDuplicateRuntimeActionRows(
    row,
    actionKey,
    options
  );
  removeLegacyRuntimeActionRows(
    row,
    action,
    options
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
    runtimeTurnId:
      options.runtimeTurnId || "",
    runtimeMessageId:
      options.runtimeMessageId || "",
    contextSnapshot:
      options.contextSnapshot || null,
    displayName:
      options.displayName || "",
    sceneEffect:
      options.sceneEffect || "",
    closeTag:
      options.closeTag === true,
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
        runtimeTurnId:
          entry.runtimeTurnId || "",
        runtimeMessageId:
          entry.runtimeMessageId || "",
        contextSnapshot:
          entry.contextSnapshot || null,
        displayName:
          entry.displayName || "",
        sceneEffect:
          entry.sceneEffect || "",
        closeTag:
          entry.closeTag === true,
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
        entry.action,
        {
          id: entry.id || "",
          runtimeTurnId:
            entry.runtimeTurnId || "",
          runtimeMessageId:
            entry.runtimeMessageId || "",
          sceneEffect:
            entry.sceneEffect || "",
        }
      );
    }
  });

}


function fadeRuntimeAction(
  action,
  options = {}
) {

  const keepSaveSessionPendingUntilL3 =
    isSaveSessionRuntimeAction(
      action
    )
    && options.forceCompletePendingL3 !== true
    && options.cancelled !== true;

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
    false,
    options
  );

  let rows =
    actionKey
      ? Array.from(
        chatHistory.querySelectorAll(
          `[data-runtime-action-key="${actionKey}"]`
        )
      )
      : Array.from(
        chatHistory.querySelectorAll(
          `[data-runtime-action="${action}"]`
        )
      );

  if (options.runtimeMessageId) {
    rows = rows.filter((row) => (
      runtimeActionRowMatchesScope(
        row,
        options.runtimeTurnId,
        options.runtimeMessageId
      )
    ));
  }

  if (
    !rows.length
    && options.fallbackToLatestActive
  ) {
    const activeRows = Array.from(
      chatHistory.querySelectorAll(
        `[data-runtime-action="${action}"]`
      )
    ).filter((row) => (
      row.dataset.runtimeActionTurn
        === String(jinConversationTurnCounter)
      && (
        !options.runtimeMessageId
        || runtimeActionRowMatchesScope(
          row,
          options.runtimeTurnId,
          options.runtimeMessageId
        )
      )
      && row.dataset.runtimeActionCompleted !== "true"
    ));

    const latestActiveRow =
      activeRows[activeRows.length - 1];

    rows = latestActiveRow
      ? [latestActiveRow]
      : [];
  }

  if (keepSaveSessionPendingUntilL3) {
    saveSessionPendingUntilL3Active = true;

    rows.forEach((row) => {
      setRuntimeActionPendingUntilL3(
        row,
        true
      );
    });

    return;
  }

  rows.forEach((row) => {
    markRuntimeActionRowCompleted(
      row,
      options
    );
  });

}

function clearPendingRuntimeActionGlow(
  action = "",
) {

  const normalizedAction =
    String(action || "").trim().toLowerCase();

  const selector =
    normalizedAction
      ? `.jin-runtime-action-row[data-runtime-action="${normalizedAction}"]`
      : ".jin-runtime-action-row";

  if (
      !normalizedAction
      || normalizedAction === RUNTIME_ACTION_SAVE_SESSION
  ) {
    saveSessionPendingUntilL3Active = false;
  }

  Array.from(
    chatHistory.querySelectorAll(
      selector
    )
  ).forEach((row) => {
    delete row.dataset.runtimeActionPendingL3;
    row.classList.remove(
      "jin-runtime-action-pending-l3"
    );
  });

}

window.setSceneSearchScreenActive =
  setSceneSearchScreenActive;

window.appendRuntimeAction =
  appendRuntimeAction;

window.hasActiveRuntimeActionCounter =
  hasActiveRuntimeActionCounter;

window.queueRuntimeActionAfterNextResponse =
  queueRuntimeActionAfterNextResponse;

window.fadeRuntimeAction =
  fadeRuntimeAction;

window.clearPendingRuntimeActionGlow =
  clearPendingRuntimeActionGlow;

window.activateRuntimeActionPendingUntilL3 =
  activateRuntimeActionPendingUntilL3;
