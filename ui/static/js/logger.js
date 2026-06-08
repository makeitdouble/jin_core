const consoleStream =
  document.getElementById("console-stream");

let traceModal;
let traceModalContent;
let traceModalReason;
let traceModalTitle;

function ensureTraceModal() {
  if (traceModal) {
    return;
  }

  traceModal =
    document.createElement("div");

  traceModal.className =
    "fixed inset-0 z-50 hidden items-center justify-center bg-black/70 p-4";

  const panel =
    document.createElement("div");

  panel.className =
    "w-full max-w-5xl max-h-[86vh] rounded border border-zinc-700 bg-zinc-950 shadow-2xl flex flex-col";

  const header =
    document.createElement("div");

  header.className =
    "h-11 shrink-0 border-b border-zinc-800 px-4 flex items-center justify-between";

  traceModalTitle =
    document.createElement("div");

  traceModalTitle.className =
    "text-xs uppercase tracking-widest text-zinc-300";

  traceModalTitle.textContent =
    "Trace";

  const closeButton =
    document.createElement("button");

  closeButton.type =
    "button";

  closeButton.className =
    "text-xs text-zinc-400 hover:text-zinc-100 transition";

  closeButton.textContent =
    "close";

  traceModalReason =
    document.createElement("div");

  traceModalReason.className =
    "hidden border-b border-zinc-800 px-4 py-3 text-[12px] leading-relaxed text-red-200";

  traceModalReason.style.overflowWrap =
    "anywhere";

  traceModalContent =
    document.createElement("pre");

  traceModalContent.className =
    "min-h-0 flex-1 overflow-auto p-4 text-[12px] leading-relaxed text-zinc-200 whitespace-pre-wrap";

  traceModalContent.style.overflowWrap =
    "anywhere";

  header.appendChild(
    traceModalTitle
  );

  header.appendChild(
    closeButton
  );

  panel.appendChild(
    header
  );

  panel.appendChild(
    traceModalReason
  );

  panel.appendChild(
    traceModalContent
  );

  traceModal.appendChild(
    panel
  );

  document.body.appendChild(
    traceModal
  );

  function closeTraceModal() {
    traceModal.classList.add(
      "hidden"
    );

    traceModal.classList.remove(
      "flex"
    );
  }

  closeButton.addEventListener(
    "click",
    closeTraceModal
  );

  traceModal.addEventListener(
    "click",
    function (event) {
      if (event.target === traceModal) {
        closeTraceModal();
      }
    }
  );

  document.addEventListener(
    "keydown",
    function (event) {
      if (event.key === "Escape") {
        closeTraceModal();
      }
    }
  );
}

function showTrace(
  details,
  title = "Trace",
  reason = null,
) {
  ensureTraceModal();

  traceModalTitle.textContent =
    title;

  if (reason) {
    traceModalReason.textContent =
      `Reason: ${reason}`;

    traceModalReason.classList.remove(
      "hidden"
    );
  } else {
    traceModalReason.textContent =
      "";

    traceModalReason.classList.add(
      "hidden"
    );
  }

  traceModalContent.textContent =
    String(details);

  traceModal.classList.remove(
    "hidden"
  );

  traceModal.classList.add(
    "flex"
  );
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

function appendLog(
  tag,
  message,
  details = null,
  meta = {},
) {
  const normalized =
    splitInlineTrace(
      message,
      details,
    );

  const flowId =
    meta?.flow_id;

  const existingFlowLog =
    tag === "[FLOW]"
      ? findLiveFlowLog(
          flowId
        )
      : null;

  const logDiv =
    existingFlowLog
    || document.createElement("div");

  logDiv.className =
    "mb-1 min-w-0 whitespace-pre-wrap break-words";

  logDiv.style.overflowWrap =
    "anywhere";

  if (flowId) {
    logDiv.dataset.flowId =
      flowId;
  }

  if (existingFlowLog) {
    logDiv.replaceChildren();
  }

  let tagClass =
    "text-zinc-500";

  if (tag.includes("BEFORE")) {
    tagClass =
      "text-amber-500";
  }

  if (tag.includes("BRAIN")) {
    tagClass =
      "text-pink-500";
  }

  if (tag.includes("SERVICE")) {
    tagClass =
      "text-blue-500";
  }

  if (tag.includes("SUMMARIZER")) {
    tagClass =
      "text-blue-400 font-bold";

    logDiv.classList.add(
      "font-mono",
      "text-[12px]",
      "bg-blue-500/5",
      "p-2",
      "rounded",
      "border",
      "border-blue-500/10",
    );
  }

  if (tag.includes("MEMORY:")) {
    tagClass =
      "text-blue-300 font-bold";

    logDiv.classList.add(
      "font-mono",
      "text-[12px]",
      "bg-blue-500/5",
      "p-2",
      "rounded",
      "border",
      "border-blue-500/10",
    );
  }

  if (tag.includes("SESSION")) {
    tagClass =
      "text-cyan-300 font-bold";

    logDiv.classList.add(
      "font-mono",
      "text-[12px]",
      "bg-cyan-500/5",
      "p-2",
      "rounded",
      "border",
      "border-cyan-500/10",
    );
  }

  if (tag.includes("AFTER")) {
    tagClass =
      "text-purple-500";
  }

  if (tag.includes("SYSTEM")) {
    tagClass =
      "text-emerald-500";
  }

  if (tag.includes("FLOW TELEMETRY")) {
    tagClass =
      "text-purple-400";
  }

  if (tag === "[FLOW]") {
    tagClass =
      "text-zinc-400";

    logDiv.classList.add(
      "font-mono",
      "text-[12px]",
      "bg-zinc-500/5",
      "p-2",
      "rounded",
      "border",
      "border-zinc-500/10",
    );
  }

  if (tag.includes("USER")) {
    tagClass =
      "text-sky-300 font-bold";
  }

  if (tag.includes("FLOW")) {
    tagClass =
      "text-purple-300 font-bold";
  }

  if (tag.includes("USAGE")) {
    tagClass =
      "text-zinc-300 font-bold";
  }

  if (tag.includes("ERROR")) {
    tagClass =
      "text-red-500 font-bold";

    logDiv.classList.add(
      "font-mono",
      "text-[12px]",
      "bg-red-500/5",
      "p-2",
      "rounded",
      "border",
      "border-red-500/10",
    );
  }

  const tagSpan =
    document.createElement("span");

  tagSpan.className =
    `${tagClass} block`;

  tagSpan.textContent =
    tag;

  logDiv.appendChild(
    tagSpan
  );

  const messageSpan =
    document.createElement("span");

  messageSpan.className =
    "block mt-1 text-zinc-400";

  messageSpan.style.overflowWrap =
    "anywhere";

  messageSpan.textContent =
    normalized.message;

  logDiv.appendChild(
    messageSpan
  );

  if (normalized.details) {
    const isSummarizer =
      tag.includes("SUMMARIZER")
      || tag.includes("MEMORY:");

    const isSession =
      tag.includes("SESSION");

    const isUser =
      tag.includes("USER");

    const isPatternResult =
      isSummarizer
      && String(
        normalized.message
      ).includes(
        "L2 pattern memory"
      );

    const shouldShowReason =
      tag.includes("ERROR")
      || (
          tag.includes("MEMORY:")
          && (
              String(normalized.message).includes("skipped")
              || String(normalized.message).includes("failed")
          )
      );

    const reason =
      shouldShowReason
        ? extractTraceReason(
            normalized.message,
            normalized.details
          )
        : "";

    const actions =
      document.createElement("div");

    actions.className =
      "mt-2 flex flex-wrap items-center gap-2";

    const traceButton =
      document.createElement("button");

    traceButton.type =
      "button";

    traceButton.className =
      isSummarizer
        ? "mt-2 inline-flex items-center rounded border border-blue-500/20 px-2 py-1 text-[10px] uppercase tracking-wider text-blue-300 hover:bg-blue-500/10 transition"
        : isSession
        ? "inline-flex items-center rounded border border-cyan-500/20 px-2 py-1 text-[10px] uppercase tracking-wider text-cyan-300 hover:bg-cyan-500/10 transition"
        : "mt-2 inline-flex items-center rounded border border-red-500/20 px-2 py-1 text-[10px] uppercase tracking-wider text-red-300 hover:bg-red-500/10 transition";

    traceButton.textContent =
      isPatternResult
        ? "patterns"
        : isSession
        ? "show"
        : isSummarizer
        ? "payload"
        : isUser
        ? "message"
        : "trace";

    traceButton.addEventListener(
      "click",
      function () {
        showTrace(
          normalized.details,
          isPatternResult
            ? "L2 pattern memory"
            : isSession
            ? "Session bootstrap"
            : isSummarizer
            ? "Summarizer payload"
            : "Trace",
          reason
        );
      }
    );

    actions.appendChild(
      traceButton
    );

    if (isSession) {
      const clearButton =
        document.createElement("button");

      clearButton.type =
        "button";

      clearButton.className =
        "inline-flex items-center rounded border border-zinc-600/40 px-2 py-1 text-[10px] uppercase tracking-wider text-zinc-300 hover:bg-zinc-700/40 transition";

      clearButton.textContent =
        "clear";

      clearButton.addEventListener(
        "click",
        function () {
          if (window.clearPersistedSessionBootstrap) {
            window.clearPersistedSessionBootstrap();
          }

          normalized.details = null;
          clearButton.disabled = true;
          clearButton.textContent = "cleared";
          traceButton.disabled = true;
          traceButton.classList.add("opacity-40");
        }
      );

      actions.appendChild(
        clearButton
      );
    }

    logDiv.appendChild(
      actions
    );
  }

  if (existingFlowLog) {
    moveLogToBottomWithFlip(
      logDiv
    );
  } else {
    consoleStream.appendChild(
      logDiv
    );
  }

  consoleStream.scrollTop =
    consoleStream.scrollHeight;
}

window.appendLog =
  appendLog;

window.showTrace =
  showTrace;


const consolePanel = document.getElementById("console-panel");
    const consoleDragHandle = document.getElementById("console-drag-handle");

    let isConsoleDragging = false;
    let consoleOffsetX = 0;
    let consoleOffsetY = 0;

    consoleDragHandle.addEventListener("mousedown", (event) => {
        isConsoleDragging = true;

        const rect = consolePanel.getBoundingClientRect();

        consoleOffsetX = event.clientX - rect.left;
        consoleOffsetY = event.clientY - rect.top;

        consolePanel.style.right = "auto";
        consolePanel.style.bottom = "auto";
        consolePanel.style.position = "absolute";

        document.body.style.userSelect = "none";
    });

    window.addEventListener("mousemove", (event) => {
        if (!isConsoleDragging) return;

        const parentRect = consolePanel.parentElement.getBoundingClientRect();
        const panelRect = consolePanel.getBoundingClientRect();

        let nextLeft = event.clientX - parentRect.left - consoleOffsetX;
        let nextTop = event.clientY - parentRect.top - consoleOffsetY;

        nextLeft = Math.max(8, Math.min(nextLeft, parentRect.width - panelRect.width - 8));
        nextTop = Math.max(8, Math.min(nextTop, parentRect.height - panelRect.height - 8));

        consolePanel.style.left = `${nextLeft}px`;
        consolePanel.style.top = `${nextTop}px`;
    });

    window.addEventListener("mouseup", () => {
        if (!isConsoleDragging) return;

        isConsoleDragging = false;
        document.body.style.userSelect = "";
    });






const memoryPanel = document.getElementById("settings-panel");
const memoryDragHandle = document.getElementById("memory-drag-handle");

let isMemoryDragging = false;
let memoryOffsetX = 0;
let memoryOffsetY = 0;

memoryDragHandle.addEventListener("mousedown", (event) => {
    isMemoryDragging = true;

    const rect = memoryPanel.getBoundingClientRect();

    memoryOffsetX = event.clientX - rect.left;
    memoryOffsetY = event.clientY - rect.top;

    document.body.style.userSelect = "none";
});

window.addEventListener("mousemove", (event) => {
    if (!isMemoryDragging) return;

    const parentRect = memoryPanel.parentElement.getBoundingClientRect();
    const panelRect = memoryPanel.getBoundingClientRect();

    let nextLeft =
        event.clientX - parentRect.left - memoryOffsetX;

    let nextTop =
        event.clientY - parentRect.top - memoryOffsetY;

    nextLeft = Math.max(
        8,
        Math.min(
            nextLeft,
            parentRect.width - panelRect.width - 8
        )
    );

    nextTop = Math.max(
        8,
        Math.min(
            nextTop,
            parentRect.height - panelRect.height - 8
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
