const storage =
  window.JinRuntime
  && window.JinRuntime.storage;

if (!storage) {
  throw new Error(
    "JinRuntime.storage must be loaded before telemetry.js"
  );
}

const memoryModel =
  window.JinRuntime
  && window.JinRuntime.memoryModel;

if (!memoryModel) {
  throw new Error(
    "JinRuntime.memoryModel must be loaded before telemetry.js"
  );
}

const idle =
  window.JinRuntime
  && window.JinRuntime.idle;

if (!idle) {
  throw new Error(
    "JinRuntime.idle must be loaded before telemetry.js"
  );
}


const feedback =
  window.JinRuntime
  && window.JinRuntime.feedback;

if (!feedback) {
  throw new Error(
    "JinRuntime.feedback must be loaded before telemetry.js"
  );
}

const session =
  window.JinRuntime
  && window.JinRuntime.session;

if (!session) {
  throw new Error(
    "JinRuntime.session must be loaded before telemetry.js"
  );
}

const panel =
  window.JinRuntime
  && window.JinRuntime.panel;

if (!panel) {
  throw new Error(
    "JinRuntime.panel must be loaded before telemetry.js"
  );
}

const {
  splitMemoryTextLines,
  stripMemoryTextMetaForDisplay,
  isUserIdleRuntimeMemoryLine,
  stripUserIdleRuntimeMemoryText,
  parseRuntimeMemoryLine,
  getUserIdleRuntimeMemoryLine,
  setRuntimeMemorySnapshotUserIdle,
  removeRuntimeMemoryLineByKey,
  upsertRuntimeMemoryLine,
  buildRuntimeMemoryValuePresentation,
} = memoryModel;

const {
  keys: runtimeStorageKeys,
  removeBrowserMemory,
  readLatestRuntimeMemory,
  writeLatestRuntimeMemory,
  readLatestSavedSessionMemory,
  writeLatestSavedSessionMemory,
  readLatestSavedRuntimeMemory,
  writeLatestSavedRuntimeMemory,
  buildPersistedRuntimeSnapshot,
  cloneBootRuntimeMemoryIfNeeded,
  collectOtherLatestRuntimeMemorySnapshots,
  clearOtherLatestRuntimeMemorySnapshots,
  getSavedRuntimeMemoryFallback,
} = storage;

let userIdleValueNode = null;

let telemetryFrameScheduled = false;
let contextPanelRenderTimer = null;

const contextTabButtons = {
  service: document.getElementById(
    "service-context-tab"
  ),
  brain: document.getElementById(
    "brain-context-tab"
  ),
};

const contextRuntimePanel =
  document.getElementById(
    "context-runtime-panel"
  );

const runtimeMemoryText =
  document.getElementById(
    "runtime-memory-text"
  );

const runtimeMemoryTitle =
  document.getElementById(
    "runtime-memory-title"
  );

const runtimeMemoryPanel =
    document.getElementById("settings-panel");

const runtimeMemoryCount =
  document.getElementById(
    "runtime-memory-count"
  );

const defaultRuntimeMemoryText =
  "This session has just begun. "
  + "You have no history with the user yet.";

const sessionStartedRuntimeMemoryText =
  "session_status: Session started";

const runtimeMemoryHistory = {
  snapshots: [],
  index: -1,
};

const pinnedRuntimeMemorySnapshotIndexes = new Set();

let runtimeMemoryDisplayMode = "runtime";
let restoredSessionMemorySnapshot = null;

const runtimeDiffHistory = {
  diffs: [],
  stats: {},
  expanded: false,
};

function getUserIdleText() {
  return idle.getText();
}

function updateUserIdleTimerText(
  text = getUserIdleText()
) {
  if (!userIdleValueNode) {
    return;
  }

  userIdleValueNode.textContent =
      ` ${text}`;

  updateRuntimeMemoryTitleMetrics(
      runtimeMemoryHistory.snapshots[
          runtimeMemoryHistory.index
      ]
  );
}

idle.configure({
  onIdleTextChanged(text) {
    updateUserIdleTimerText(
      text
    );
  },
});


feedback.init({
  memoryModel,
  getSnapshots() {
    return runtimeMemoryHistory.snapshots;
  },
  getCurrentIndex() {
    return runtimeMemoryHistory.index;
  },
  setCurrentIndex(index) {
    runtimeMemoryHistory.index = index;
  },
  getDisplayMode() {
    return runtimeMemoryDisplayMode;
  },
  setDisplayMode(mode) {
    runtimeMemoryDisplayMode = mode;
  },
  getRuntimeMemoryCountText() {
    return runtimeMemoryCount
      ? runtimeMemoryCount.textContent
      : "0";
  },
  renderRuntimeMemorySnapshot() {
    renderRuntimeMemorySnapshot();
  },
});

window.jinWebSocketConnected = false;


function persistRuntimeMemorySnapshot(
  data
) {

  if (
      !data
      || !data.snapshot
  ) {
    return;
  }

  if (Number(data.updates || 0) <= 0) {
    return;
  }

  const runtimeMemory =
    (
      data.snapshot.raw_memory
      || data.memory
      || ""
    ).trim();

  if (!runtimeMemory) {
    return;
  }

  const savedAt =
    new Date().toISOString();

  writeLatestRuntimeMemory({
    version: 1,
    session_id:
      storage.getCurrentRuntimeSessionId(),
    saved_at: savedAt,
    runtime_memory: runtimeMemory,
    runtime_memory_updates: data.updates || 0,
    runtime_snapshot: buildPersistedRuntimeSnapshot(
      data.snapshot
    ),
  });

}


window.freezeLatestRuntimeMemoryUserIdle = function (
  userIdleText
) {

  const latestSnapshot =
      runtimeMemoryHistory.snapshots[
        runtimeMemoryHistory.snapshots.length - 1
      ];

  setRuntimeMemorySnapshotUserIdle(
    latestSnapshot,
    userIdleText
  );

};


function runtimeMemoryTextIsDefaultNote(text) {

  const normalized =
      String(text || "")
        .trim()
        .replace(/\s+/g, " ")
        .toLowerCase();

  const defaultNormalized =
      defaultRuntimeMemoryText
        .trim()
        .replace(/\s+/g, " ")
        .toLowerCase();

  return (
      normalized === defaultNormalized
      || normalized === `note: ${defaultNormalized}`
  );

}


function attachFirstUserIdleToInitialRuntimeSnapshot(sourceSnapshot) {

  const firstSnapshot =
      runtimeMemoryHistory.snapshots[0];

  if (!firstSnapshot) {
    return;
  }

  if (getUserIdleRuntimeMemoryLine(firstSnapshot)) {
    return;
  }

  const firstRawMemory =
      String(firstSnapshot.raw_memory || "");

  if (!runtimeMemoryTextIsDefaultNote(firstRawMemory)) {
    return;
  }

  const userIdleLine =
      getUserIdleRuntimeMemoryLine(sourceSnapshot);

  if (!userIdleLine) {
    return;
  }

  const nextLine = {
    ...userIdleLine,
    status: "same",
    key_status: "same",
    value_status: "same",
  };

  firstSnapshot.lines = [
    ...(Array.isArray(firstSnapshot.lines)
      ? firstSnapshot.lines
      : splitMemoryTextLines(firstRawMemory)
        .map(parseRuntimeMemoryLine)),
    nextLine,
  ];

  firstSnapshot.raw_memory = [
    firstRawMemory.trim() || `note: ${defaultRuntimeMemoryText}`,
    `user_idle: ${nextLine.value || ""}`.trim(),
  ].filter(Boolean).join("\n");

}






session.init({
  history: runtimeMemoryHistory,
  storage,
  memoryModel,
  feedback,
  runtimeMemoryCount,
  defaultRuntimeMemoryText,
  sessionStartedRuntimeMemoryText,
  getRuntimeMemoryDisplayMode: () => runtimeMemoryDisplayMode,
  setRuntimeMemoryDisplayMode: (value) => {
    runtimeMemoryDisplayMode = value;
  },
  getRestoredSessionMemorySnapshot: () => restoredSessionMemorySnapshot,
  setRestoredSessionMemorySnapshot: (value) => {
    restoredSessionMemorySnapshot = value;
  },
  renderRuntimeMemorySnapshot,
  persistRuntimeMemorySnapshot,
  attachFirstUserIdleToInitialRuntimeSnapshot,
});

panel.init();

window.handleRuntimeMemoryMessage = function (data) {

  if (!data) {
    return;
  }

  if (data.type === "runtime_l1_diff_update") {
    runtimeDiffHistory.diffs =
        data.diffs || [];

    runtimeDiffHistory.stats =
        data.stats || {};

    renderRuntimeDiffs();

    return;
  }

  if (data.type === "runtime_session_memory_update") {
    session.persistSessionMemory(
      data
    );

    if (
        data.persist === true
        && window.fadeRuntimeAction
    ) {
      window.fadeRuntimeAction(
        "remember_session"
      );
    }

    if (window.stopL3MemoryGlow) {
      window.stopL3MemoryGlow();
    }

    return;
  }

  if (data.type !== "runtime_memory_update") {
    return;
  }

  if (session.isReconnectInitialRuntimeMemoryUpdate(data)) {
    return;
  }

  if (session.isLatestRuntimeMemoryDuplicate(data)) {
    return;
  }

  if (session.applyBootstrapRuntimeMemoryUpdate(data)) {
    return;
  }

  if (session.isBootstrapRuntimeMemoryDuplicate(data)) {
    return;
  }

  if (
      session.shouldIgnoreInitialSessionModeUpdate(data)
  ) {
    persistRuntimeMemorySnapshot(
      data
    );

    return;
  }

  runtimeMemoryDisplayMode = "runtime";

  if (window.stopMemoryGlow) {
    window.stopMemoryGlow();
  }

  if (runtimeMemoryCount) {
    runtimeMemoryCount.textContent =
        String(data.updates || 0);
  }

  let clientSnapshot = null;

  if (data.snapshot) {
    if (
        data.replace_latest === true
        && runtimeMemoryHistory.snapshots.length
    ) {
      const clientIndex =
          runtimeMemoryHistory.snapshots.length - 1;

      clientSnapshot = {
        ...runtimeMemoryHistory.snapshots[clientIndex],
        ...data.snapshot,
        index: clientIndex,
      };

      runtimeMemoryHistory.snapshots[clientIndex] =
          clientSnapshot;
      runtimeMemoryHistory.index = clientIndex;

      session.rememberStableRuntimeSnapshot(
        clientSnapshot
      );
    } else {
      const clientIndex = runtimeMemoryHistory.snapshots.length;
      clientSnapshot = {
        ...data.snapshot,
        index: clientIndex,
      };

      attachFirstUserIdleToInitialRuntimeSnapshot(
        clientSnapshot
      );

      // The server-side snapshot.index can restart after bootstrap/restore.
      // The right panel is client-side history, so display positions must follow
      // the actual array order instead of reusing a stale server index.
      runtimeMemoryHistory.snapshots.push(clientSnapshot);
      runtimeMemoryHistory.index =
          runtimeMemoryHistory.snapshots.length - 1;

      if (window.jinGenerationRunning) {
        idle.freezeAtSeconds(
            window.jinActiveTurnUserIdleSeconds
        );
      }

      session.rememberStableRuntimeSnapshot(
        clientSnapshot
      );

      feedback.markL1ReadyFromRuntimeUpdate(
        data,
        clientIndex
      );
    }
  } else {
    feedback.markL1ReadyFromRuntimeUpdate(
      data
    );
  }

  persistRuntimeMemorySnapshot(
    data
  );

  session.captureSessionSaveRuntimeSnapshot(
    clientSnapshot
  );

  renderRuntimeMemorySnapshot();

};


const runtimeMemoryPosition =
    document.getElementById("runtime-memory-position");

const runtimeMemoryPrev =
    document.getElementById("runtime-memory-prev");

const runtimeMemoryNext =
    document.getElementById("runtime-memory-next");

const runtimeDiffToggle =
    document.getElementById("runtime-diff-toggle");

const runtimeDiffText =
    document.getElementById("runtime-diff-text");

const runtimeDiffCount =
    document.getElementById("runtime-diff-count");

const runtimeDiffAverage =
    document.getElementById("runtime-diff-average");

const runtimeDiffRange =
    document.getElementById("runtime-diff-range");

const runtimeDiffMax =
    document.getElementById("runtime-diff-max");


function formatRuntimeDiffNumber(value) {
  const number =
      Number(value || 0);

  return String(
      Number.isInteger(number)
        ? number
        : Number(number.toFixed(2))
  );
}


function renderRuntimeDiffs() {
  const stats =
      runtimeDiffHistory.stats || {};

  if (runtimeDiffCount) {
    runtimeDiffCount.textContent =
        formatRuntimeDiffNumber(stats.count);
  }

  if (runtimeDiffAverage) {
    runtimeDiffAverage.textContent =
        formatRuntimeDiffNumber(stats.average);
  }

  if (runtimeDiffRange) {
    runtimeDiffRange.textContent =
        formatRuntimeDiffNumber(stats.range);
  }

  if (runtimeDiffMax) {
    runtimeDiffMax.textContent =
        formatRuntimeDiffNumber(stats.max);
  }

  if (runtimeDiffToggle) {
    runtimeDiffToggle.textContent =
        runtimeDiffHistory.expanded
          ? "hide diffs"
          : "show diffs";
  }

  if (!runtimeDiffText) {
    return;
  }

  runtimeDiffText.classList.toggle(
      "hidden",
      !runtimeDiffHistory.expanded
  );

  runtimeDiffText.textContent =
      runtimeDiffHistory.diffs.length
        ? JSON.stringify(
            runtimeDiffHistory.diffs,
            null,
            2
          )
        : "[]";
}


function isCurrentRuntimeMemorySnapshotPinned() {
  return pinnedRuntimeMemorySnapshotIndexes.has(
      runtimeMemoryHistory.index
  );
}

function updateRuntimeMemoryPinGlow() {
  if (!runtimeMemoryPosition) {
    return;
  }

  runtimeMemoryPosition.classList.toggle(
      "runtime-memory-position-pinned",
      isCurrentRuntimeMemorySnapshotPinned()
  );
}

function estimateRuntimeMemoryTokens(text) {
  if (!text) {
    return 0;
  }

  return Math.max(
      1,
      Math.ceil(
          Array.from(text).length / 4
      )
  );
}

function getRuntimeMemorySnapshotMetricText(snapshot) {
  if (!snapshot || typeof snapshot !== "object") {
    return "";
  }

  const includeLiveUserIdle =
      isLatestRuntimeMemorySnapshot();

  const rawMemory =
      String(snapshot.raw_memory || "");

  if (rawMemory.trim()) {
    const stableMemory =
        includeLiveUserIdle
          ? stripUserIdleRuntimeMemoryText(rawMemory)
          : rawMemory;

    return [
      stableMemory.trim(),
      includeLiveUserIdle
        ? `user_idle: ${getUserIdleText()}`
        : "",
    ].filter(Boolean).join("\n");
  }

  if (!Array.isArray(snapshot.lines)) {
    return "";
  }

  const lines =
      snapshot.lines
      .filter((line) => (
          !includeLiveUserIdle
          || !isUserIdleRuntimeMemoryLine(line)
      ))
      .map((line) => {
        const key =
            line && line.key
              ? String(line.key)
              : "note";

        const value =
            line && line.value
              ? String(line.value)
              : "";

        return `${key}: ${value}`;
      })
      .filter(Boolean);

  if (includeLiveUserIdle) {
    lines.push(
        `user_idle: ${getUserIdleText()}`
    );
  }

  return lines.join("\n").trim();
}

function updateRuntimeMemoryTitleMetrics(snapshot) {
  if (!runtimeMemoryTitle) {
    return;
  }

  const metricText =
      getRuntimeMemorySnapshotMetricText(snapshot);

  const charCount =
      Array.from(metricText).length;

  const tokenCount =
      estimateRuntimeMemoryTokens(metricText);

  runtimeMemoryTitle.title =
      `${charCount} chars / ~${tokenCount} tokens`;
}

function renderRuntimeMemorySnapshot() {
  const snapshot =
      runtimeMemoryHistory.snapshots[
          runtimeMemoryHistory.index
          ];

  if (!snapshot) {
    runtimeMemoryText.textContent = "";
    runtimeMemoryPosition.textContent =
        "0";
    updateRuntimeMemoryTitleMetrics(null);
    updateRuntimeMemoryArrows();
    updateRuntimeMemoryPinGlow();
    return;
  }

  renderRuntimeMemoryLines(
      snapshot,
      isCurrentRuntimeMemorySnapshotPinned()
  );

  runtimeMemoryPosition.textContent =
      String(
          typeof snapshot.index === "number"
            ? snapshot.index
            : runtimeMemoryHistory.index + 1
      );

  updateRuntimeMemoryTitleMetrics(snapshot);
  updateRuntimeMemoryArrows();
  updateRuntimeMemoryPinGlow();
}

function isLatestRuntimeMemorySnapshot() {
  return (
      runtimeMemoryHistory.index >=
      runtimeMemoryHistory.snapshots.length - 1
  );
}

function clampMemoryRatio(value) {
  const number =
      Number(value || 0);

  return Math.max(
      0,
      Math.min(1, number)
  );
}

function applyRuntimeMemoryFlash(
    element,
    status,
    kind,
    ratio,
    persist = false
) {
  if (!element) {
    return;
  }

  if (status === "new") {
    element.classList.add("flash-new");
  }

  if (status === "changed") {
    element.classList.add("flash-changed");

    if (kind === "value") {
      const normalized =
          clampMemoryRatio(ratio);

      element.style.setProperty(
          "--memory-change-alpha",
          String(
              0.55 + normalized * 0.41
          )
      );

      element.style.setProperty(
          "--memory-change-glow",
          String(
              0.10 + normalized * 0.28
          )
      );
    }
  }

  if (
      status !== "new"
      && status !== "changed"
  ) {
    return;
  }

  if (persist) {
    return;
  }

  setTimeout(() => {
    element.classList.remove(
        "flash-new",
        "flash-changed"
    );

    element.style.removeProperty(
        "--memory-change-alpha"
    );

    element.style.removeProperty(
        "--memory-change-glow"
    );
  }, 1500);
}

function renderRuntimeMemoryLines(snapshot, persistGlow = false) {
  if (!runtimeMemoryText) {
    return;
  }

  runtimeMemoryText.innerHTML = "";
  runtimeMemoryText.classList.toggle(
      "runtime-memory-text-pinned",
      persistGlow
  );
  runtimeMemoryText.removeAttribute(
      "title"
  );

  const showLiveUserIdle =
      isLatestRuntimeMemorySnapshot();

  const lines =
      showLiveUserIdle
        ? (snapshot.lines || [])
          .filter(line => !isUserIdleRuntimeMemoryLine(line))
        : snapshot.lines || [];

  if (!lines.length) {
    const rawMemory =
        showLiveUserIdle
          ? stripUserIdleRuntimeMemoryText(snapshot.raw_memory || "")
          : snapshot.raw_memory || "";

    runtimeMemoryText.textContent =
        `${stripMemoryTextMetaForDisplay(rawMemory).trim()}\n`;

    if (rawMemory.trim()) {
      runtimeMemoryText.title =
          rawMemory.trim();
    }

    if (showLiveUserIdle) {
      appendUserIdleRuntimeMemoryLine();
    } else {
      userIdleValueNode = null;
    }

    idle.start();

    return;
  }

  lines.forEach((line) => {
    const row =
        document.createElement("div");

    row.className =
        "runtime-memory-line";

    const key =
        line.key || "note";

    const valuePresentation =
        buildRuntimeMemoryValuePresentation(line);

    const fullRawLine =
        `${key}: ${valuePresentation.raw}`;

    const keyStatus =
        line.key_status || line.status || "same";

    const valueStatus =
        line.value_status || line.status || "same";

    const keySpan =
        document.createElement("span");

    keySpan.className =
        "runtime-memory-key";

    keySpan.textContent =
        `${key}:`;

    const valueSpan =
        document.createElement("span");

    valueSpan.className =
        "runtime-memory-value";

    valueSpan.textContent =
        ` ${valuePresentation.text}`;

    row.title =
        fullRawLine;
    valueSpan.title =
        fullRawLine;

    row.appendChild(keySpan);
    row.appendChild(valueSpan);

    runtimeMemoryText.appendChild(row);

    applyRuntimeMemoryFlash(
        keySpan,
        keyStatus,
        "key",
        line.key_change_ratio,
        persistGlow
    );

    applyRuntimeMemoryFlash(
        valueSpan,
        valueStatus,
        "value",
        line.value_change_ratio,
        persistGlow
    );
  });

  if (showLiveUserIdle) {
    appendUserIdleRuntimeMemoryLine();
  } else {
    userIdleValueNode = null;
  }

  idle.start();
}

function appendUserIdleRuntimeMemoryLine() {
  if (!runtimeMemoryText) {
    return;
  }

  const row =
      document.createElement("div");

  row.className =
      "runtime-memory-line runtime-memory-user-idle";

  const keySpan =
      document.createElement("span");

  keySpan.className =
      "runtime-memory-key";

  keySpan.textContent =
      "user_idle:";

  const valueSpan =
      document.createElement("span");

  valueSpan.className =
      "runtime-memory-value";

  userIdleValueNode =
      valueSpan;

  row.appendChild(keySpan);
  row.appendChild(valueSpan);

  runtimeMemoryText.appendChild(row);
  idle.onSnapshotChanged();
  idle.start();
}

function updateRuntimeMemoryArrows() {
  const canGoPrev =
      runtimeMemoryHistory.index > 0;

  const canGoNext =
      runtimeMemoryHistory.index <
      runtimeMemoryHistory.snapshots.length - 1;

  runtimeMemoryPrev.disabled = !canGoPrev;
  runtimeMemoryNext.disabled = !canGoNext;

  runtimeMemoryPrev.classList.toggle("opacity-30", !canGoPrev);
  runtimeMemoryNext.classList.toggle("opacity-30", !canGoNext);

  runtimeMemoryPrev.classList.toggle("cursor-default", !canGoPrev);
  runtimeMemoryNext.classList.toggle("cursor-default", !canGoNext);
  runtimeMemoryPrev.classList.toggle("text-emerald-300", canGoPrev);
  runtimeMemoryNext.classList.toggle("text-emerald-300", canGoNext);

  runtimeMemoryPrev.classList.toggle("text-slate-600", !canGoPrev);
  runtimeMemoryNext.classList.toggle("text-slate-600", !canGoNext);
}

runtimeMemoryPrev?.addEventListener("click", () => {
  if (runtimeMemoryHistory.index <= 0) return;

  runtimeMemoryHistory.index -= 1;
  renderRuntimeMemorySnapshot();
});

runtimeMemoryNext?.addEventListener("click", () => {
  if (
      runtimeMemoryHistory.index >=
      runtimeMemoryHistory.snapshots.length - 1
  ) return;

  runtimeMemoryHistory.index += 1;
  renderRuntimeMemorySnapshot();
});

runtimeMemoryPosition?.addEventListener("click", () => {
  if (runtimeMemoryHistory.index < 0) {
    return;
  }

  const wasPinned =
      isCurrentRuntimeMemorySnapshotPinned();

  if (wasPinned) {
    pinnedRuntimeMemorySnapshotIndexes.delete(
        runtimeMemoryHistory.index
    );
  } else {
    pinnedRuntimeMemorySnapshotIndexes.add(
        runtimeMemoryHistory.index
    );
  }

  renderRuntimeMemorySnapshot();

  if (wasPinned && runtimeMemoryText) {
    runtimeMemoryText
        .querySelectorAll(
            ".flash-new, .flash-changed"
        )
        .forEach((element) => {
          element.classList.add(
              "runtime-memory-flash-off"
          );
          element.classList.remove(
              "flash-new",
              "flash-changed"
          );

          requestAnimationFrame(() => {
            element.classList.remove(
                "runtime-memory-flash-off"
            );
          });
        });
  }
});

runtimeMemoryPosition?.addEventListener("keydown", (event) => {
  if (
      event.key !== "Enter"
      && event.key !== " "
  ) {
    return;
  }

  event.preventDefault();
  runtimeMemoryPosition.click();
});

runtimeDiffToggle?.addEventListener("click", () => {
  runtimeDiffHistory.expanded =
      !runtimeDiffHistory.expanded;

  renderRuntimeDiffs();
});

renderRuntimeMemorySnapshot();
renderRuntimeDiffs();
