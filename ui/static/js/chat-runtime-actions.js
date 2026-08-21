const deferredRuntimeActionsAfterResponse = [];
let runtimeActionRowCounter = 0;

let sceneSearchFadeTimer = null;
const activeSceneSearchRuntimeActions = new Set();

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

function buildSceneSearchRuntimeActionKey(
  action,
  options = {}
) {

  const normalizedAction =
    String(
      action || "runtime_action"
    ).trim().toLowerCase()
    || "runtime_action";
  const id =
    String(
      options.id || ""
    ).trim();

  if (id) {
    return `${normalizedAction}:${id}`;
  }

  const runtimeMessageId =
    String(
      options.runtimeMessageId
      || options.runtime_message_id
      || ""
    ).trim();
  const runtimeTurnId =
    String(
      options.runtimeTurnId
      || options.runtime_turn_id
      || ""
    ).trim();
  const parentId =
    String(
      options.deepSearchParentId
      || options.deep_search_parent_id
      || ""
    ).trim();

  return [
    normalizedAction,
    id,
    runtimeMessageId,
    runtimeTurnId,
    parentId,
  ].join(":");

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

  const key =
    buildSceneSearchRuntimeActionKey(
      action,
      options
    );

  if (active) {
    activeSceneSearchRuntimeActions.add(
      key
    );
  } else {
    activeSceneSearchRuntimeActions.delete(
      key
    );
  }

  setSceneSearchScreenActive(
    activeSceneSearchRuntimeActions.size > 0
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
const RUNTIME_ACTION_ICON_SVG_NS =
  "http://www.w3.org/2000/svg";
const runtimeActionIconDefinitions = {
  web_search: {
    title: "web search",
    tone: "search",
    svg: '<circle cx="10.5" cy="10.5" r="5.25"></circle><path d="m15 15 4 4"></path>',
  },
  deep_web_search: {
    title: "deep web search",
    tone: "search",
    svg: '<circle cx="10.5" cy="10.5" r="5.25"></circle><path d="m15 15 4 4"></path><path d="M5.5 10.5h10"></path><path d="M10.5 5.5c1.5 1.6 2.25 3.25 2.25 5s-.75 3.4-2.25 5"></path><path d="M10.5 5.5c-1.5 1.6-2.25 3.25-2.25 5s.75 3.4 2.25 5"></path>',
  },
  save_delayed_memory_content: {
    title: "save delayed memory",
    tone: "save",
    svg: '<path d="M5 4h11l3 3v13H5z"></path><path d="M8 4v6h7V4"></path><path d="M8 16h8"></path>',
  },
  load_delayed_memory: {
    title: "load delayed memory",
    tone: "memory",
    svg: '<path d="M5 5h14v14H5z"></path><path d="M8 8h8"></path><path d="M12 8v8"></path><path d="m9 13 3 3 3-3"></path>',
  },
  unload_delayed_memory: {
    title: "unload delayed memory",
    tone: "delete",
    svg: '<path d="M9 4h6l1 2h4"></path><path d="M4 6h16"></path><path d="m7 9 .7 10h8.6L17 9"></path><path d="M10 11v5"></path><path d="M14 11v5"></path>',
  },
  save_active_memory: {
    title: "save active memory",
    tone: "memory",
    svg: '<path d="M7 5h10v15l-5-3-5 3z"></path><path d="M12 8v5"></path><path d="M9.5 10.5h5"></path>',
  },
  update_active_memory: {
    title: "update active memory",
    tone: "memory",
    svg: '<path d="M7 5h10v15l-5-3-5 3z"></path><path d="M9 10h6"></path><path d="m13 8 2 2-2 2"></path>',
  },
  resolve_active_memory: {
    title: "resolve active memory",
    tone: "resolve",
    svg: '<circle cx="12" cy="12" r="7"></circle><path d="m8.5 12.3 2.2 2.2 4.8-5"></path>',
  },
  clean_tool_results: {
    title: "clean tool results",
    tone: "clean",
    svg: '<path d="M14 4 5 13"></path><path d="m11 7 6 6"></path><path d="m3 18 4-4 3 3-4 4H3z"></path><path d="M13.5 14.5 17 18"></path>',
  },
  load_skill: {
    title: "load skill",
    tone: "skill",
    svg: '<path d="M8 4h8v5H8z"></path><path d="M6 12h12v8H6z"></path><path d="M12 9v3"></path><path d="M10 16h4"></path>',
  },
  unload_skill: {
    title: "unload skill",
    tone: "delete",
    svg: '<path d="M8 4h8v5H8z"></path><path d="M6 12h12v8H6z"></path><path d="M10 16h4"></path><path d="m5 5 14 14"></path>',
  },
  asset_action: {
    title: "asset action",
    tone: "asset",
    svg: '<path d="m12 3 8 4.5v9L12 21l-8-4.5v-9z"></path><path d="M4 7.5 12 12l8-4.5"></path><path d="M12 12v9"></path>',
  },
  create_todo_list: {
    title: "create todo list",
    tone: "todo",
    svg: '<path d="M8 6h11"></path><path d="M8 12h11"></path><path d="M8 18h7"></path><path d="M4 6h.01"></path><path d="M4 12h.01"></path><path d="M4 18h.01"></path><path d="M18 16v4"></path><path d="M16 18h4"></path>',
  },
  resolve_todo: {
    title: "resolve todo",
    tone: "resolve",
    svg: '<path d="M5 5h14v14H5z"></path><path d="m8.5 12.2 2.2 2.3 4.8-5"></path>',
  },
  check_todo: {
    title: "check todo",
    tone: "todo",
    svg: '<path d="M8 4h8l2 3v13H6V7z"></path><path d="M9 12h4"></path><path d="M9 16h6"></path><path d="m14 5 2 2"></path>',
  },
  idle: {
    title: "idle",
    tone: "idle",
    svg: '<path d="M17 14.5A7 7 0 0 1 9.5 5a7.5 7.5 0 1 0 7.5 9.5z"></path>',
  },
  jin_color: {
    title: "jin color",
    tone: "color",
    svg: '<path d="M12 3C8 7.2 6 10.4 6 13.5A6 6 0 0 0 18 13.5C18 10.4 16 7.2 12 3z"></path><path d="M9.5 14.5c.7 1 1.6 1.5 2.5 1.5s1.8-.5 2.5-1.5"></path>',
  },
  jin_size: {
    title: "jin size",
    tone: "size",
    svg: '<path d="M4 8V4h4"></path><path d="M20 8V4h-4"></path><path d="M4 16v4h4"></path><path d="M20 16v4h-4"></path>',
  },
  update_l4_facts: {
    title: "update L4 facts",
    tone: "update",
    svg: '<ellipse cx="12" cy="6" rx="6" ry="3"></ellipse><path d="M6 6v6c0 1.7 2.7 3 6 3s6-1.3 6-3V6"></path><path d="M6 12v3c0 1.7 2.7 3 6 3 1.3 0 2.4-.2 3.4-.6"></path><path d="m16 16 2 2 3-4"></path>',
  },
};
let runtimeActionGuardGeometryFrame = null;

function normalizeRuntimeActionIconName(
  action
) {

  return String(
    action || ""
  ).trim().toLowerCase();

}

function getRuntimeActionIconDefinition(
  action
) {

  const actionName =
    normalizeRuntimeActionIconName(
      action
    );

  return (
    runtimeActionIconDefinitions[actionName]
    || {
      title: "runtime action",
      tone: "default",
      svg: '<circle cx="12" cy="12" r="6"></circle><path d="M12 9v3"></path><path d="M12 15h.01"></path>',
    }
  );

}

function appendRuntimeActionIconGlyph(
  icon,
  action
) {

  if (!icon) {
    return null;
  }

  const definition =
    getRuntimeActionIconDefinition(
      action
    );
  const svg =
    document.createElementNS(
      RUNTIME_ACTION_ICON_SVG_NS,
      "svg"
    );

  icon.classList.add(
    "jin-runtime-action-icon",
    `jin-runtime-action-icon-${definition.tone}`
  );
  icon.dataset.runtimeActionIcon =
    normalizeRuntimeActionIconName(
      action
    ) || "runtime_action";

  svg.setAttribute(
    "viewBox",
    "0 0 24 24"
  );
  svg.setAttribute(
    "aria-hidden",
    "true"
  );
  svg.setAttribute(
    "focusable",
    "false"
  );
  svg.setAttribute(
    "fill",
    "none"
  );
  svg.setAttribute(
    "stroke",
    "currentColor"
  );
  svg.setAttribute(
    "stroke-width",
    "1.8"
  );
  svg.setAttribute(
    "stroke-linecap",
    "round"
  );
  svg.setAttribute(
    "stroke-linejoin",
    "round"
  );
  svg.innerHTML =
    definition.svg;

  icon.replaceChildren(
    svg
  );

  return definition;

}

function canPreviewAssetResult(
  assetResult
) {

  return Boolean(
    assetResult
    && assetResult.ok === true
  );

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

function runtimeActionBooleanOption(
  options,
  camelName,
  snakeName
) {

  return (
    options[camelName] === true
    || options[snakeName] === true
  );

}

function normalizeRuntimeActionDataValue(
  value
) {

  return String(
    value || ""
  ).trim();

}

function isDeepSearchParentRuntimeAction(
  action,
  options = {}
) {

  const normalizedAction =
    String(
      action || ""
    ).trim().toLowerCase();

  return (
    normalizedAction === "deep_web_search"
    || runtimeActionBooleanOption(
      options,
      "deepSearchParent",
      "deep_search_parent"
    )
  );

}

function isDeepSearchChildRuntimeAction(
  action,
  options = {}
) {

  const normalizedAction =
    String(
      action || ""
    ).trim().toLowerCase();

  return (
    normalizedAction === "web_search"
    && runtimeActionBooleanOption(
      options,
      "deepSearchChild",
      "deep_search_child"
    )
  );

}

function isDeepSearchRuntimeActionRow(
  action,
  options = {}
) {

  return (
    isDeepSearchParentRuntimeAction(
      action,
      options
    )
    || isDeepSearchChildRuntimeAction(
      action,
      options
    )
  );

}

function readDeepSearchGroupId(
  row
) {

  if (!row) {
    return "";
  }

  return normalizeRuntimeActionDataValue(
    row.dataset.runtimeActionDeepSearchGroup
  );

}

function findDeepSearchGroupRows(
  groupId
) {

  const normalizedGroupId =
    normalizeRuntimeActionDataValue(
      groupId
    );

  if (!normalizedGroupId) {
    return [];
  }

  return Array.from(
    chatHistory.querySelectorAll(
      ".jin-runtime-action-deep-search-parent,"
      + ".jin-runtime-action-deep-search-child"
    )
  ).filter((row) => (
    readDeepSearchGroupId(
      row
    ) === normalizedGroupId
  ));

}

function setDeepSearchStackExpanded(
  row,
  expanded
) {

  const groupRows = findDeepSearchGroupRows(
    readDeepSearchGroupId(
      row
    )
  );

  groupRows.forEach((groupRow) => {
    groupRow.classList.toggle(
      "jin-runtime-action-deep-search-stack-expanded",
      expanded
    );
  });

}

function bindDeepSearchStackHover(
  row
) {

  if (
      !row
      || row.dataset.runtimeActionDeepSearchHoverBound === "true"
  ) {
    return;
  }

  row.dataset.runtimeActionDeepSearchHoverBound =
    "true";

  row.addEventListener(
    "mouseenter",
    () => {
      setDeepSearchStackExpanded(
        row,
        true
      );
    }
  );

  row.addEventListener(
    "mouseleave",
    (event) => {
      const nextRow =
        event.relatedTarget
        && event.relatedTarget.closest
          ? event.relatedTarget.closest(
            ".jin-runtime-action-row"
          )
          : null;

      if (
          nextRow
          && readDeepSearchGroupId(
            nextRow
          ) === readDeepSearchGroupId(
            row
          )
      ) {
        return;
      }

      setDeepSearchStackExpanded(
        row,
        false
      );
    }
  );

}

function syncDeepSearchChildStack(
  row
) {

  const groupId =
    readDeepSearchGroupId(
      row
    );

  if (!groupId) {
    return;
  }

  findDeepSearchGroupRows(
    groupId
  ).filter((groupRow) => (
    groupRow.classList.contains(
      "jin-runtime-action-deep-search-child"
    )
  )).forEach((childRow, index) => {
    childRow.dataset.runtimeActionDeepSearchIndex =
      String(index + 1);
    childRow.style.setProperty(
      "--jin-deep-search-stack-order",
      String(index)
    );
    childRow.style.setProperty(
      "--jin-deep-search-stack-z",
      String(30 - index)
    );
  });

}

function insertRuntimeActionRow(
  row,
  action,
  options = {}
) {

  if (row) {
    // Every newly materialized runtime-action bubble uses the same 250ms
    // accelerating drop-in motion, regardless of action type.
    row.classList.add(
      "jin-runtime-action-enter"
    );
  }

  if (
      !row
      || !isDeepSearchChildRuntimeAction(
        action,
        options
      )
  ) {
    chatHistory.appendChild(
      row
    );
    return;
  }

  const groupId =
    readDeepSearchGroupId(
      row
    );
  const groupRows =
    findDeepSearchGroupRows(
      groupId
    );
  const parentRow =
    groupRows.find((groupRow) => (
      groupRow.classList.contains(
        "jin-runtime-action-deep-search-parent"
      )
    ));
  const firstChildRow =
    groupRows.find((groupRow) => (
      groupRow.classList.contains(
        "jin-runtime-action-deep-search-child"
      )
    ));

  if (
      parentRow
      && parentRow.parentElement === chatHistory
  ) {
    parentRow.insertAdjacentElement(
      "afterend",
      row
    );
  } else if (
      firstChildRow
      && firstChildRow.parentElement === chatHistory
  ) {
    chatHistory.insertBefore(
      row,
      firstChildRow
    );
  } else {
    chatHistory.appendChild(
      row
    );
  }

  syncDeepSearchChildStack(
    row
  );

}

function syncRuntimeActionSearchState(
  row,
  action,
  options = {}
) {

  if (!row) {
    return;
  }

  const isDeepSearch =
    isDeepSearchRuntimeActionRow(
      action,
      options
    );
  const isDeepSearchParent =
    isDeepSearchParentRuntimeAction(
      action,
      options
    );
  const isDeepSearchChild =
    isDeepSearchChildRuntimeAction(
      action,
      options
    );

  if (!isDeepSearch) {
    delete row.dataset.runtimeActionDeepSearch;
    delete row.dataset.runtimeActionDeepSearchGroup;
    delete row.dataset.runtimeActionDeepSearchParent;
    delete row.dataset.runtimeActionDeepSearchObjective;
    delete row.dataset.runtimeActionStatus;
    row.classList.remove(
      "jin-runtime-action-deep-search",
      "jin-runtime-action-deep-search-parent",
      "jin-runtime-action-deep-search-child",
      "jin-runtime-action-deep-search-stack-expanded"
    );
    return;
  }

  const status =
    String(
      options.status || ""
    ).trim().toLowerCase();

  if (status) {
    row.dataset.runtimeActionStatus =
      status;
  } else {
    delete row.dataset.runtimeActionStatus;
  }

  row.dataset.runtimeActionDeepSearch =
    "true";
  row.classList.add(
    "jin-runtime-action-deep-search"
  );
  row.classList.toggle(
    "jin-runtime-action-deep-search-parent",
    isDeepSearchParent
  );
  row.classList.toggle(
    "jin-runtime-action-deep-search-child",
    isDeepSearchChild
  );

  const parentId =
    normalizeRuntimeActionDataValue(
      options.deepSearchParentId
      || options.deep_search_parent_id
    );
  const objective =
    normalizeRuntimeActionDataValue(
      options.deepSearchObjective
      || options.deep_search_objective
      || options.query
      || options.detail
    );
  const ownId =
    normalizeRuntimeActionDataValue(
      row.dataset.runtimeActionId
      || options.id
    );
  const groupId =
    parentId
    || (
      isDeepSearchParent
        ? ownId
        : ""
    )
    || (
      objective
        ? `objective:${objective}`
        : ""
    );

  if (groupId) {
    row.dataset.runtimeActionDeepSearchGroup =
      groupId;
  }

  if (parentId) {
    row.dataset.runtimeActionDeepSearchParent =
      parentId;
  }

  if (objective) {
    row.dataset.runtimeActionDeepSearchObjective =
      objective;
  }

  if (isDeepSearchChild) {
    row
      .querySelectorAll(
        ":scope > .jin-runtime-action-icon"
      )
      .forEach((icon) => {
        icon.remove();
      });
    bindDeepSearchStackHover(
      row
    );
    syncDeepSearchChildStack(
      row
    );
    return;
  }

  if (isDeepSearchParent) {
    bindDeepSearchStackHover(
      row
    );
  }

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

function normalizeRuntimeActionSize(value) {

  if (
    value
    && typeof value === "object"
  ) {
    const width =
      Number.parseInt(
        value.width || value.w || 0,
        10
      );
    const height =
      Number.parseInt(
        value.height || value.h || width || 0,
        10
      );

    if (
      Number.isFinite(width)
      && Number.isFinite(height)
      && width > 0
      && height > 0
    ) {
      return width === height
        ? `${width}px`
        : `w:${width}px h:${height}px`;
    }
  }

  if (
    window.JinResponseFormatter
    && typeof window.JinResponseFormatter.normalizeJinSizeMarker === "function"
  ) {
    return window.JinResponseFormatter.normalizeJinSizeMarker(
      value
    );
  }

  const text =
    String(
      value || ""
    ).trim();
  const single =
    text.match(/^(\d+)(?:px)?$/i);

  if (single) {
    return `${Number.parseInt(single[1], 10)}px`;
  }

  const pair =
    text.match(/^(\d+)(?:px)?\s+(\d+)(?:px)?$/i);

  if (pair) {
    const width =
      Number.parseInt(pair[1], 10);
    const height =
      Number.parseInt(pair[2], 10);

    return width === height
      ? `${width}px`
      : `w:${width}px h:${height}px`;
  }

  const labeled =
    text.match(/^w\s*:\s*(\d+)(?:px)?\s+h\s*:\s*(\d+)(?:px)?$/i);

  if (labeled) {
    const width =
      Number.parseInt(labeled[1], 10);
    const height =
      Number.parseInt(labeled[2], 10);

    return width === height
      ? `${width}px`
      : `w:${width}px h:${height}px`;
  }

  return "";

}

function readRuntimeActionAggregateSizes(
  row
) {

  if (!row) {
    return [];
  }

  return String(
    row.dataset.runtimeActionSizes || ""
  ).split(",").map(
    normalizeRuntimeActionSize
  ).filter(Boolean);

}

function shouldAggregateRuntimeAction(
  action,
  options = {}
) {

  if (action === "jin_color") {
    return false;
  }

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
  const explicitSizes = Array.isArray(
    options.sizes
  )
    ? options.sizes
        .map(normalizeRuntimeActionSize)
        .filter(Boolean)
    : [];
  const incomingSize =
    normalizeRuntimeActionSize(
      options.size
      || (
        action === "jin_size"
          ? options.payload || options.detail || text
          : ""
      )
    );
  const markerCount = Math.max(
    currentMarkerCount,
    explicitMarkerCount
  );
  let storedColors =
    readRuntimeActionAggregateColors(
      row
    );
  let storedSizes =
    readRuntimeActionAggregateSizes(
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

  if (explicitSizes.length) {
    storedSizes = explicitSizes;
  } else if (
    incomingSize
    && options.counterOnly !== true
    && storedSizes[storedSizes.length - 1]
      !== incomingSize
  ) {
    storedSizes.push(
      incomingSize
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

  if (storedSizes.length) {
    row.dataset.runtimeActionSizes =
      storedSizes.join(",");
  } else {
    delete row.dataset.runtimeActionSizes;
  }

  delete row.dataset.runtimeActionPendingColor;

  return {
    ...options,
    aggregateMarkers: true,
    markerCount,
    colors: storedColors,
    sizes: storedSizes,
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
    const color =
      normalizeRuntimeActionColor(
        options.color
        || options.payload
        || options.detail
      )
      || textColor
      || explicitColors[explicitColors.length - 1]
      || "";

    if (color) {
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
    }

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

    if (color) {
      const payload =
        document.createElement("span");

      payload.className =
        "jin-runtime-action-payload";
      payload.textContent =
        `: ${color}`;

      label.appendChild(
        payload
      );
    }

    return;
  }

  if (action === "jin_size") {
    const explicitSizes = Array.isArray(
      options.sizes
    )
      ? options.sizes
          .map(normalizeRuntimeActionSize)
          .filter(Boolean)
      : [];
    const sizes = explicitSizes.length
      ? explicitSizes
      : [
          normalizeRuntimeActionSize(
            options.size
            || options.payload
            || options.detail
            || text
          ),
        ].filter(Boolean);

    const name =
      document.createElement("span");

    name.className =
      "jin-runtime-action-name";
    name.textContent =
      String(
        options.displayName
        || "JIN_SIZE"
      ).trim()
      || "JIN_SIZE";

    label.appendChild(
      name
    );

    const payloadSize =
      sizes.length
        ? sizes[sizes.length - 1]
        : normalizeRuntimeActionSize(
          options.size
          || options.payload
          || options.detail
          || text
        );

    if (payloadSize) {
      const payload =
        document.createElement("span");

      payload.className =
        "jin-runtime-action-payload";
      payload.textContent =
        `: ${payloadSize}`;

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

function runtimeActionRowMatchesId(
  row,
  action,
  id
) {

  const normalizedAction =
    normalizeRuntimeActionKeyPart(
      action
    );
  const normalizedId =
    normalizeRuntimeActionKeyPart(
      id
    );

  if (
      !row
      || !normalizedAction
      || !normalizedId
      || normalizeRuntimeActionKeyPart(
        row.dataset.runtimeAction
      ) !== normalizedAction
  ) {
    return false;
  }

  const rowId =
    normalizeRuntimeActionKeyPart(
      row.dataset.runtimeActionId
    );

  if (rowId === normalizedId) {
    return true;
  }

  const rowKey =
    normalizeRuntimeActionKeyPart(
      row.dataset.runtimeActionKey
    );

  return (
    rowKey === `${normalizedAction}:${normalizedId}`
    || rowKey.endsWith(
      `:${normalizedId}`
    )
  );

}

function isGenericAssetActionRow(
  row
) {

  if (
      !row
      || normalizeRuntimeActionKeyPart(
        row.dataset.runtimeAction
      ) !== "asset_action"
  ) {
    return false;
  }

  const text =
    String(
      (
        row.querySelector(
          ".jin-runtime-action-label"
        )
        || row
      ).textContent || ""
    ).trim().toUpperCase();

  return (
    text === "ASSET_ACTION"
    || text === "ACTION: ASSET_ACTION"
  );

}

function removeOrphanedAssetActionRows(
  primaryRow,
  action
) {

  if (
      !primaryRow
      || normalizeRuntimeActionKeyPart(
        action
      ) !== "asset_action"
      || isGenericAssetActionRow(
        primaryRow
      )
  ) {
    return;
  }

  Array.from(
    chatHistory.querySelectorAll(
      `.jin-runtime-action-row[data-runtime-action="asset_action"]`
    )
  ).forEach((row) => {
    if (
        row !== primaryRow
        && row.dataset.runtimeActionTurn
          === primaryRow.dataset.runtimeActionTurn
        && row.dataset.runtimeActionCompleted !== "true"
        && isGenericAssetActionRow(
          row
        )
    ) {
      row.remove();
    }
  });

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
              retry_user_message:
                String(
                  confirmation.retryUserMessage
                  || confirmation.retry_user_message
                  || ""
                ),
              retry_attempt:
                Number(
                  confirmation.retryAttempt
                  || confirmation.retry_attempt
                  || 1
                ),
              retry_context_snapshot:
                confirmation.retryContextSnapshot
                || confirmation.retry_context_snapshot
                || null,
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

  syncRuntimeActionSearchState(
    row,
    action,
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
      canPreviewAssetResult(
        options.assetResult
      )
        ? options.assetResult
        : null
    );
  }

  if (
      action === "attach_file"
      && typeof window.bindRuntimeActionAttachmentPreview === "function"
  ) {
    window.bindRuntimeActionAttachmentPreview(
      label,
      options.attachmentResult || null,
      options.id || ""
    );
  }

  if (
    [
      "save_delayed_memory_content",
      "load_delayed_memory",
    ].includes(action)
  ) {
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

    if (
        !existingRow
        && options.id
        && action
    ) {
      existingRow =
        Array.from(
          chatHistory.querySelectorAll(
            `.jin-runtime-action-row[data-runtime-action="${action}"]`
          )
        ).find((row) => {
          return (
            runtimeActionRowMatchesId(
              row,
              action,
              options.id
            )
            && (
              options.reuseCompleted
              || row.dataset.runtimeActionCompleted !== "true"
            )
          );
        });
    }

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
        && (
          action === "asset_action"
          || runtimeActionRowMatchesScope(
            row,
            options.runtimeTurnId,
            options.runtimeMessageId
          )
        )
        && row.dataset.runtimeActionCompleted !== "true"
      ));

      existingRow =
        activeRows[activeRows.length - 1] || null;
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
                && options.reviveCompleted !== false
              ),
          }
        )
    ) {
      if (options.activateScene !== false) {
        syncSceneSearchScreenForRuntimeAction(
          action,
          !options.completed,
          options
        );
      }

      if (options.id) {
        existingRow.dataset.runtimeActionKey =
          actionKey || "";
        existingRow.dataset.runtimeActionId =
          String(options.id);
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
      removeOrphanedAssetActionRows(
        existingRow,
        action
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
    "jin-message-row jin-runtime-action-row jin-runtime-action-enter mx-auto w-full max-w-4xl text-xs text-cyan-100 transition duration-500";

  if (action === "jin_color") {
    row.classList.add(
      "jin-runtime-action-color-row"
    );
  }

  if (action === "jin_size") {
    row.classList.add(
      "jin-runtime-action-size-row"
    );
  }

  row.dataset.runtimeAction =
    action || "";

  row.dataset.runtimeActionKey =
    actionKey || "";
  row.dataset.runtimeActionTurn =
    String(jinConversationTurnCounter);

  if (options.id) {
    row.dataset.runtimeActionId =
      String(options.id);
  }

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

  const omitIcon =
    isDeepSearchChildRuntimeAction(
      action,
      options
    );
  let icon = null;

  if (!omitIcon) {
    icon = document.createElement(
      options.contextSnapshot
        ? "button"
        : "div"
    );

    if (options.contextSnapshot) {
      icon.type =
        "button";
    }

    icon.className =
      "h-6 w-6 rounded bg-cyan-950/70 border border-cyan-700 flex items-center justify-center shrink-0";

    const iconDefinition =
      appendRuntimeActionIconGlyph(
        icon,
        action
      );

    if (options.contextSnapshot) {
      icon.className +=
        " cursor-help hover:bg-cyan-900/70 transition";

      icon.title =
        "show action context";
      icon.setAttribute(
        "aria-label",
        `show action context: ${iconDefinition.title}`
      );

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
    } else {
      icon.title =
        iconDefinition.title;
      icon.setAttribute(
        "aria-hidden",
        "true"
      );
    }
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

  syncRuntimeActionSearchState(
    row,
    action,
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
      canPreviewAssetResult(
        options.assetResult
      )
        ? options.assetResult
        : null
    );
  }

  if (
      action === "attach_file"
      && typeof window.bindRuntimeActionAttachmentPreview === "function"
  ) {
    window.bindRuntimeActionAttachmentPreview(
      label,
      options.attachmentResult || null,
      options.id || ""
    );
  }

  if (
    [
      "save_delayed_memory_content",
      "load_delayed_memory",
    ].includes(action)
  ) {
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

  if (icon) {
    row.appendChild(
      icon
    );
  }

  row.appendChild(
    label
  );

  if (options.completed) {
    markRuntimeActionRowCompleted(
      row,
      options
    );
  }

  insertRuntimeActionRow(
    row,
    action,
    options
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
  removeOrphanedAssetActionRows(
    row,
    action
  );

  if (window.scrollChatHistoryAfterAppend) {
    window.scrollChatHistoryAfterAppend();
  } else {
    chatHistory.scrollTop =
      chatHistory.scrollHeight;
  }

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
    attachmentResult:
      options.attachmentResult || null,
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
        attachmentResult:
          entry.attachmentResult || null,
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
        action === "asset_action"
        ||
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

  rows.forEach((row) => {
    markRuntimeActionRowCompleted(
      row,
      options
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

