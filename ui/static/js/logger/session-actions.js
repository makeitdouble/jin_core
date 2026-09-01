const SESSION_ACTIONS_PREVIEW_LIMIT = 5;

const sessionActionsLogState = {
  mode: "",
  sequenceId: "",
  items: [],
  signature: "",
  logDiv: null,
  tagSpan: null,
  list: null,
  fullButton: null,
  bottomMoveStreamKey: "",
};

let sessionActionsModal = null;
let sessionActionsModalTitle = null;
let sessionActionsModalList = null;
let sessionActionsModalMode = "";
let sessionActionsModalSequenceId = "";
let sessionActionsModalItems = [];
let sessionActionsAgeTimer = null;
const pendingCancelledSessionActions = [];
const cancelledSessionActionPartKeys = new Set();

function normalizeSessionActionName(value) {
  return String(value || "")
    .trim()
    .toUpperCase();
}

function normalizeDeepSearchSessionActionDisplay(
  text,
  detail = "",
) {
  const normalizedText =
    String(text || "").trim();
  const normalizedDetail =
    String(detail || "").trim();
  const queryMatch =
    normalizedText.match(
      /^DEEP_WEB_SEARCH\s*:\s*(.+)$/i
    );

  if (!queryMatch) {
    return {
      text: normalizedText,
      detail: normalizedDetail,
    };
  }

  const query =
    String(queryMatch[1] || "").trim();

  return {
    text: "DEEP_WEB_SEARCH",
    detail: query || normalizedDetail,
  };
}

function normalizeSessionActionColor(value) {
  const match = String(value || "")
    .trim()
    .match(/^#?([0-9a-f]{3}|[0-9a-f]{6})$/i);

  if (!match) {
    return "";
  }

  let hex = match[1].toLowerCase();

  if (hex.length === 3) {
    hex = hex
      .split("")
      .map((char) => char + char)
      .join("");
  }

  return `#${hex}`;
}

function buildSessionActionPartKey(
  item,
  part,
  partIndex,
) {
  return [
    String(item.createdAt || 0),
    String(partIndex),
    normalizeSessionActionName(part.text),
    String(part.id || ""),
    (part.colors || []).join(","),
  ].join("|");
}

function sessionActionPartMatchesCancellation(
  part,
  cancellation,
) {
  const normalizedText =
    normalizeSessionActionName(part.text);
  const actionName =
    cancellation.actionName;

  if (
    normalizedText !== actionName
    && !normalizedText.startsWith(`${actionName} `)
    && !normalizedText.startsWith(`${actionName}:`)
  ) {
    return false;
  }

  return (
    !cancellation.color
    || (part.colors || []).includes(
      cancellation.color
    )
  );
}

function applyCancelledSessionActions(
  items,
) {
  items.forEach((item) => {
    item.parts.forEach((part, partIndex) => {
      const partKey =
        buildSessionActionPartKey(
          item,
          part,
          partIndex
        );

      if (part.cancelled) {
        cancelledSessionActionPartKeys.add(
          partKey
        );
      } else if (
        cancelledSessionActionPartKeys.has(
          partKey
        )
      ) {
        part.cancelled = true;
      }
    });
  });

  while (pendingCancelledSessionActions.length) {
    const cancellation =
      pendingCancelledSessionActions[0];
    let matched = false;

    for (
      let itemIndex = items.length - 1;
      itemIndex >= 0 && !matched;
      itemIndex -= 1
    ) {
      const item = items[itemIndex];

      if (
        item.createdAt
        && item.createdAt < cancellation.createdAfter
      ) {
        continue;
      }

      for (
        let partIndex = item.parts.length - 1;
        partIndex >= 0;
        partIndex -= 1
      ) {
        const part = item.parts[partIndex];

        if (
          !sessionActionPartMatchesCancellation(
            part,
            cancellation
          )
        ) {
          continue;
        }

        if (!part.cancelled) {
          part.cancelled = true;
          cancelledSessionActionPartKeys.add(
            buildSessionActionPartKey(
              item,
              part,
              partIndex
            )
          );
        }

        matched = true;
        break;
      }
    }

    if (!matched) {
      break;
    }

    pendingCancelledSessionActions.shift();
  }

  return items;
}

function normalizeSessionActionParts(
  parts,
  fallbackText,
) {
  const normalizedParts = Array.isArray(parts)
    ? parts
        .map((part) => {
          if (!part || typeof part !== "object") {
            return null;
          }

          let text =
            String(part.text || "").trim();

          if (!text) {
            return null;
          }

          let detail =
            String(part.detail || "").trim();

          ({ text, detail } =
            normalizeDeepSearchSessionActionDisplay(
              text,
              detail
            ));

          const message =
            String(part.message || "").trim();

          const contextDetail =
            String(part.context_detail || "").trim();

          const id =
            String(part.id || "").trim();

          const colors = Array.isArray(part.colors)
            ? part.colors
                .map((color) =>
                  String(color || "").trim().toLowerCase()
                )
                .filter((color) => (
                  /^#[0-9a-f]{6}$/.test(color)
                ))
            : [];

          const count = Math.max(
            0,
            Number.parseInt(
              part.count || 0,
              10
            ) || 0
          );

          return {
            text,
            detail,
            message,
            contextDetail,
            id,
            colors,
            count,
            cancelled:
              Boolean(part.cancelled),
          };
        })
        .filter(Boolean)
    : [];

  if (normalizedParts.length) {
    return normalizedParts;
  }

  const text =
    String(fallbackText || "").trim();

  if (!text) {
    return [];
  }

  const deepSearchDisplay =
    normalizeDeepSearchSessionActionDisplay(
      text
    );

  if (
    deepSearchDisplay.text === "DEEP_WEB_SEARCH"
    && deepSearchDisplay.detail
  ) {
    return [{
      text: deepSearchDisplay.text,
      detail: deepSearchDisplay.detail,
      message: "",
      id: "",
      colors: [],
      count: 0,
      cancelled: false,
    }];
  }

  const detailSeparator =
    " - ";

  const detailSeparatorIndex =
    text.indexOf(
      detailSeparator
    );

  if (detailSeparatorIndex < 0) {
    return [{
      text,
      detail: "",
      message: "",
      id: "",
      colors: [],
      count: 0,
      cancelled: false,
    }];
  }

  const visibleText =
    text.slice(
      0,
      detailSeparatorIndex
    ).trim();

  const detail =
    text.slice(
      detailSeparatorIndex
      + detailSeparator.length
    ).trim();

  return [{
    text: visibleText || text,
    detail: visibleText ? detail : "",
    message: "",
    id: "",
    colors: [],
    count: 0,
    cancelled: false,
  }];
}

function normalizeSessionActionItems(
  items,
) {
  if (!Array.isArray(items)) {
    return [];
  }

  const normalizedItems = items
    .map((item) => {
      if (!item || typeof item !== "object") {
        return null;
      }

      const text =
        String(item.text || "").trim();

      if (!text) {
        return null;
      }

      const createdAt =
        Number(item.created_at || 0);

      return {
        text,
        parts: expandSessionActionDisplayParts(
          normalizeSessionActionParts(
            item.parts,
            text
          )
        ),
        createdAt:
          Number.isFinite(createdAt)
            ? createdAt
            : 0,
      };
    })
    .filter(Boolean);

  return applyCancelledSessionActions(
    normalizedItems
  );
}

function formatSessionActionAge(
  createdAt,
) {
  const timestamp =
    Number(createdAt || 0);

  if (!Number.isFinite(timestamp) || timestamp <= 0) {
    return "now";
  }

  const seconds = Math.max(
    0,
    Math.floor(
      (Date.now() / 1000) - timestamp
    )
  );

  if (seconds < 60) {
    return `${seconds}s ago`;
  }

  const minutes =
    Math.floor(seconds / 60);

  if (minutes < 60) {
    return `${minutes}m ago`;
  }

  const hours =
    Math.floor(minutes / 60);

  return `${hours}h ago`;
}

function refreshSessionActionAges() {
  document
    .querySelectorAll("[data-session-action-created-at]")
    .forEach((node) => {
      node.textContent =
        formatSessionActionAge(
          node.dataset.sessionActionCreatedAt
        );
    });
}

function ensureSessionActionsAgeTimer() {
  if (sessionActionsAgeTimer !== null) {
    return;
  }

  sessionActionsAgeTimer =
    window.setInterval(
      refreshSessionActionAges,
      1000
    );
}

function buildSessionActionColorSwatches(
  colors,
) {
  const swatches =
    document.createElement("span");

  swatches.className =
    "session-action-color-swatches";

  colors.forEach((color) => {
    const swatch =
      document.createElement("span");

    swatch.className =
      "session-action-color-swatch";

    swatch.style.setProperty(
      "--session-action-color",
      color
    );

    swatch.title =
      color;

    swatches.appendChild(
      swatch
    );
  });

  return swatches;
}


function expandSessionActionDisplayParts(
  parts,
) {
  return parts.flatMap((part) => {
    if (
      normalizeSessionActionName(part.text)
        !== "JIN_COLOR"
    ) {
      return [part];
    }

    if (!part.colors.length) {
      return [{
        ...part,
        count: 0,
      }];
    }

    return part.colors.map((color) => ({
      ...part,
      colors: [color],
      count: 0,
      detail: color,
    }));
  });
}


function buildSessionActionRow(
  item,
  index,
) {
  const row =
    document.createElement("div");

  row.className =
    "min-w-0 whitespace-pre-wrap break-words";

  row.style.overflowWrap =
    "anywhere";

  const prefix =
    document.createElement("span");

  prefix.textContent =
    `${index + 1}. `;

  row.appendChild(
    prefix
  );

  const parts =
    normalizeSessionActionParts(
      item.parts,
      item.text
    );

  parts.forEach((part, partIndex) => {
    const action =
      document.createElement("span");

    action.className =
      "align-middle";

    if (part.colors.length) {
      action.appendChild(
        buildSessionActionColorSwatches(
          part.colors
        )
      );
    }

    const actionName =
      document.createElement("span");

    actionName.textContent =
      part.text;

    if (part.cancelled) {
      actionName.classList.add(
        "line-through",
        "decoration-1",
        "opacity-60"
      );
    }

    action.appendChild(
      actionName
    );

    const normalizedActionName =
      normalizeSessionActionName(
        part.text
      );
    const isAttachmentAction = (
      normalizedActionName === "ATTACH_FILE"
      || normalizedActionName === "DETACH_FILE"
    );

    if (isAttachmentAction && part.detail) {
      const attachmentName =
        document.createElement("span");

      attachmentName.textContent =
        `: ${part.detail}`;

      action.appendChild(
        attachmentName
      );
    }

    if (isAttachmentAction && part.id) {
      const attachmentId =
        document.createElement("span");

      attachmentId.textContent =
        ` [ id: ${part.id} ]`;
      attachmentId.className =
        "opacity-70";

      action.appendChild(
        attachmentId
      );
    }

    const isUpdateLTFactsAction =
      normalizedActionName === "UPDATE_LT_FACTS";

    if (part.message && !isUpdateLTFactsAction) {
      const message =
        document.createElement("span");

      message.textContent =
        `: ${part.message}`;

      action.appendChild(
        message
      );
    }

    if (part.count > 1) {
      const count =
        document.createElement("span");

      count.textContent =
        formatRuntimeActionCountLabel(
          part.count
        );
      count.className =
        "ml-1 opacity-70";

      action.appendChild(
        count
      );
    }

    const isDeepWebSearchAction =
      normalizedActionName === "DEEP_WEB_SEARCH"
      || normalizedActionName.startsWith(
        "DEEP_WEB_SEARCH "
      );

    const hoverText =
      part.message
      || part.detail
      || (
        isDeepWebSearchAction
          ? part.contextDetail
          : ""
      );

    if (hoverText) {
      action.title =
        hoverText;

      action.classList.add(
        "cursor-help"
      );
    }

    row.appendChild(
      action
    );

    if (partIndex < parts.length - 1) {
      row.appendChild(
        document.createTextNode(", ")
      );
    }
  });

  row.appendChild(
    document.createTextNode(" (")
  );

  const age =
    document.createElement("span");

  age.dataset.sessionActionCreatedAt =
    String(item.createdAt || 0);

  age.textContent =
    formatSessionActionAge(
      item.createdAt
    );

  row.appendChild(
    age
  );

  row.appendChild(
    document.createTextNode(")")
  );

  return row;
}


function getSessionActionsTitle(
  mode,
) {
  return mode === "sequence"
    ? "[ CURRENT REQUEST ]"
    : "[ SESSION ACTIONS ]";
}

function ensureSessionActionsModal() {
  if (sessionActionsModal) {
    return;
  }

  sessionActionsModal =
    document.createElement("div");

  sessionActionsModal.className =
    "fixed inset-0 z-50 hidden items-center justify-center bg-black/70 p-4";

  const panel =
    document.createElement("div");

  panel.className =
    "w-full max-w-3xl max-h-[86vh] rounded border border-zinc-700 bg-zinc-950 shadow-2xl flex flex-col";

  const header =
    document.createElement("div");

  header.className =
    "h-11 shrink-0 border-b border-zinc-800 px-4 flex items-center justify-between";

  sessionActionsModalTitle =
    document.createElement("div");

  sessionActionsModalTitle.className =
    "font-mono text-xs font-bold text-zinc-300";

  const closeButton =
    document.createElement("button");

  closeButton.type =
    "button";

  closeButton.className =
    "delayed-memory-modal-icon-button delayed-memory-modal-close";

  closeButton.setAttribute(
    "aria-label",
    "Close"
  );

  closeButton.textContent =
    "\u00d7";

  sessionActionsModalList =
    document.createElement("div");

  sessionActionsModalList.className =
    "min-h-0 flex-1 overflow-auto p-4 font-mono text-[12px] leading-relaxed text-zinc-300 space-y-1";

  header.appendChild(
    sessionActionsModalTitle
  );

  header.appendChild(
    closeButton
  );

  panel.appendChild(
    header
  );

  panel.appendChild(
    sessionActionsModalList
  );

  sessionActionsModal.appendChild(
    panel
  );

  document.body.appendChild(
    sessionActionsModal
  );

  function closeSessionActionsModal() {
    sessionActionsModal.classList.add(
      "hidden"
    );

    sessionActionsModal.classList.remove(
      "flex"
    );
  }

  closeButton.addEventListener(
    "click",
    closeSessionActionsModal
  );

  let sessionActionsModalBackdropPointerDown = false;

  sessionActionsModal.addEventListener(
    "pointerdown",
    function (event) {
      sessionActionsModalBackdropPointerDown =
        event.target === sessionActionsModal;
    }
  );

  sessionActionsModal.addEventListener(
    "click",
    function (event) {
      const shouldClose =
        event.target === sessionActionsModal
        && sessionActionsModalBackdropPointerDown;

      sessionActionsModalBackdropPointerDown = false;

      if (shouldClose) {
        closeSessionActionsModal();
      }
    }
  );

  document.addEventListener(
    "keydown",
    function (event) {
      if (
        event.key === "Escape"
        && !sessionActionsModal.classList.contains("hidden")
      ) {
        closeSessionActionsModal();
      }
    }
  );
}

function sessionActionItemMatches(
  left,
  right,
) {
  return Boolean(
    left
    && right
    && left.text === right.text
    && left.createdAt === right.createdAt
    && JSON.stringify(left.parts)
      === JSON.stringify(right.parts)
  );
}

function syncSessionActionsModal(
  mode,
  sequenceId,
  items,
) {
  if (!sessionActionsModal) {
    return;
  }

  sessionActionsModalTitle.textContent =
    getSessionActionsTitle(
      mode
    );

  const sameStream = (
    sessionActionsModalMode === mode
    && sessionActionsModalSequenceId === sequenceId
  );

  const canAppend = (
    sameStream
    && sessionActionsModalItems.length <= items.length
    && sessionActionsModalItems.every(
      (item, index) => sessionActionItemMatches(
        item,
        items[index]
      )
    )
  );

  if (!canAppend) {
    sessionActionsModalList.replaceChildren();
    sessionActionsModalItems = [];
  }

  for (
    let index = sessionActionsModalItems.length;
    index < items.length;
    index += 1
  ) {
    sessionActionsModalList.appendChild(
      buildSessionActionRow(
        items[index],
        index
      )
    );
  }

  sessionActionsModalMode =
    mode;

  sessionActionsModalSequenceId =
    sequenceId;

  sessionActionsModalItems =
    items.map((item) => ({
      ...item,
      parts: item.parts.map((part) => ({
        ...part,
      })),
    }));

  sessionActionsModalList.scrollTop =
    sessionActionsModalList.scrollHeight;
}

function showSessionActionsModal() {
  ensureSessionActionsModal();

  syncSessionActionsModal(
    sessionActionsLogState.mode,
    sessionActionsLogState.sequenceId,
    sessionActionsLogState.items
  );

  sessionActionsModal.classList.remove(
    "hidden"
  );

  sessionActionsModal.classList.add(
    "flex"
  );
}

function ensureSessionActionsLog() {
  if (sessionActionsLogState.logDiv) {
    return sessionActionsLogState.logDiv;
  }

  const logDiv =
    document.createElement("div");

  logDiv.className =
    "mb-1 min-w-0 whitespace-pre-wrap break-words font-mono text-[12px] bg-zinc-500/5 p-2 rounded border border-zinc-500/10";

  logDiv.style.overflowWrap =
    "anywhere";

  logDiv.dataset.logKind =
    "session-actions";

  const tagSpan =
    document.createElement("span");

  tagSpan.className =
    "text-zinc-300 font-bold logger-tag block";

  const header =
    document.createElement("div");

  header.className =
    "jin-attached-files-header";

  const list =
    document.createElement("div");

  list.className =
    "mt-1 text-zinc-400 space-y-1";

  const fullButton =
    document.createElement("button");

  fullButton.type =
    "button";

  fullButton.className =
    "jin-attached-files-attach-button hidden";

  fullButton.textContent =
    "FULL";

  fullButton.setAttribute(
    "aria-label",
    "Show full session actions"
  );

  fullButton.addEventListener(
    "click",
    showSessionActionsModal
  );

  header.appendChild(
    tagSpan
  );

  header.appendChild(
    fullButton
  );

  logDiv.appendChild(
    header
  );

  logDiv.appendChild(
    list
  );

  sessionActionsLogState.logDiv =
    logDiv;

  sessionActionsLogState.tagSpan =
    tagSpan;

  sessionActionsLogState.list =
    list;

  sessionActionsLogState.fullButton =
    fullButton;

  return logDiv;
}

function updateSessionActionsLog(
  payload = {},
) {
  const mode =
    String(payload.mode || "").toLowerCase() === "sequence"
      ? "sequence"
      : "session_actions";

  const sequenceId =
    String(payload.sequence_id || "");

  const items =
    normalizeSessionActionItems(
      payload.items
    );

  if (!items.length) {
    return;
  }

  const streamKey =
    `${mode}:${sequenceId || items[0].createdAt || ""}`;

  const signature =
    JSON.stringify({
      mode,
      sequenceId,
      items,
    });

  if (signature === sessionActionsLogState.signature) {
    return;
  }

  const logDiv =
    ensureSessionActionsLog();

  const wasConnected =
    logDiv.isConnected;
  const shouldAnimateBottomMove =
    wasConnected
    && sessionActionsLogState.bottomMoveStreamKey
      !== streamKey;

  sessionActionsLogState.mode =
    mode;

  sessionActionsLogState.sequenceId =
    sequenceId;

  sessionActionsLogState.items =
    items;

  sessionActionsLogState.signature =
    signature;

  sessionActionsLogState.tagSpan.textContent =
    getSessionActionsTitle(
      mode
    );

  const previewStartIndex =
    Math.max(
      0,
      items.length - SESSION_ACTIONS_PREVIEW_LIMIT
    );

  sessionActionsLogState.list.replaceChildren(
    ...items
      .map((item, index) => ({ item, index }))
      .slice(
        previewStartIndex
      )
      .map(({ item, index }) =>
        buildSessionActionRow(
          item,
          index
        )
      )
  );

  sessionActionsLogState.fullButton.classList.toggle(
    "hidden",
    items.length <= SESSION_ACTIONS_PREVIEW_LIMIT
  );

  if (wasConnected) {
    if (shouldAnimateBottomMove) {
      moveLogToBottomWithFlip(
        logDiv
      );

      sessionActionsLogState.bottomMoveStreamKey =
        streamKey;
    } else {
      consoleStream.appendChild(
        logDiv
      );
    }
  } else {
    consoleStream.appendChild(
      logDiv
    );
  }

  syncSessionActionsModal(
    mode,
    sequenceId,
    items
  );

  ensureSessionActionsAgeTimer();
  refreshSessionActionAges();

  consoleStream.scrollTop =
    consoleStream.scrollHeight;
}

window.updateSessionActionsLog =
  updateSessionActionsLog;

function markSessionActionCancelled(
  actionName,
  color = "",
  options = {},
) {
  const normalizedName =
    normalizeSessionActionName(
      actionName
    );

  if (!normalizedName) {
    return;
  }

  pendingCancelledSessionActions.push({
    actionName: normalizedName,
    color: normalizeSessionActionColor(
      color
    ),
    createdAfter:
      Number.isFinite(
        Number(options.createdAfter)
      )
        ? Number(options.createdAfter)
        : (Date.now() / 1000) - 2,
  });

  if (!sessionActionsLogState.items.length) {
    return;
  }

  const payloadItems =
    sessionActionsLogState.items.map((item) => ({
      text: item.text,
      created_at: item.createdAt,
      parts: item.parts.map((part) => ({
        text: part.text,
        detail: part.detail,
        message: part.message,
        context_detail: part.contextDetail,
        id: part.id,
        colors: part.colors,
        count: part.count,
        cancelled: part.cancelled,
      })),
    }));

  sessionActionsLogState.signature =
    "";

  updateSessionActionsLog({
    mode: sessionActionsLogState.mode,
    sequence_id: sessionActionsLogState.sequenceId,
    items: payloadItems,
  });
}

window.markSessionActionCancelled =
  markSessionActionCancelled;

