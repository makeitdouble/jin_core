const SESSION_ACTIONS_PREVIEW_LIMIT = 5;

const sessionActionsLogState = {
  mode: "",
  sequenceId: "",
  items: [],
  signature: "",
  logDiv: null,
  tagSpan: null,
  list: null,
  actions: null,
  fullButton: null,
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

          const text =
            String(part.text || "").trim();

          if (!text) {
            return null;
          }

          const detail =
            String(part.detail || "").trim();

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
        parts: normalizeSessionActionParts(
          item.parts,
          text
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

    if (part.count > 0) {
      const count =
        document.createElement("span");

      count.textContent =
        `(${part.count})`;
      count.className =
        "ml-1 opacity-70";

      action.appendChild(
        count
      );
    }

    if (part.detail) {
      action.title =
        part.detail;

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
    ? "[ SEQUENCE ]"
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
    "text-xs text-zinc-400 hover:text-zinc-100 transition";

  closeButton.textContent =
    "close";

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

  sessionActionsModal.addEventListener(
    "click",
    function (event) {
      if (event.target === sessionActionsModal) {
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

  const list =
    document.createElement("div");

  list.className =
    "mt-1 text-zinc-400 space-y-1";

  const actions =
    document.createElement("div");

  actions.className =
    "mt-2 flex flex-wrap items-center gap-2 hidden";

  const fullButton =
    document.createElement("button");

  fullButton.type =
    "button";

  fullButton.className =
    "inline-flex items-center rounded border border-zinc-600/40 px-2 py-1 text-[10px] uppercase tracking-wider text-zinc-300 hover:bg-zinc-700/40 transition";

  fullButton.textContent =
    "full";

  fullButton.addEventListener(
    "click",
    showSessionActionsModal
  );

  actions.appendChild(
    fullButton
  );

  logDiv.appendChild(
    tagSpan
  );

  logDiv.appendChild(
    list
  );

  logDiv.appendChild(
    actions
  );

  sessionActionsLogState.logDiv =
    logDiv;

  sessionActionsLogState.tagSpan =
    tagSpan;

  sessionActionsLogState.list =
    list;

  sessionActionsLogState.actions =
    actions;

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
      .slice(
        previewStartIndex
      )
      .map(
        (item, index) => buildSessionActionRow(
          item,
          previewStartIndex + index
        )
      )
  );

  sessionActionsLogState.actions.classList.toggle(
    "hidden",
    items.length <= SESSION_ACTIONS_PREVIEW_LIMIT
  );

  if (wasConnected) {
    moveLogToBottomWithFlip(
      logDiv
    );
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
      (Date.now() / 1000) - 2,
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

