(function () {
  "use strict";

  window.JinRuntime = window.JinRuntime || {};

const storage =
  window.JinRuntime
  && window.JinRuntime.storage;

if (!storage) {
  throw new Error(
    "JinRuntime.storage must be loaded before runtime.js"
  );
}

const memoryModel =
  window.JinRuntime
  && window.JinRuntime.memoryModel;

if (!memoryModel) {
  throw new Error(
    "JinRuntime.memoryModel must be loaded before runtime.js"
  );
}

const idle =
  window.JinRuntime
  && window.JinRuntime.idle;

if (!idle) {
  throw new Error(
    "JinRuntime.idle must be loaded before runtime.js"
  );
}


const feedback =
  window.JinRuntime
  && window.JinRuntime.feedback;

if (!feedback) {
  throw new Error(
    "JinRuntime.feedback must be loaded before runtime.js"
  );
}

const session =
  window.JinRuntime
  && window.JinRuntime.session;

if (!session) {
  throw new Error(
    "JinRuntime.session must be loaded before runtime.js"
  );
}

const panel =
  window.JinRuntime
  && window.JinRuntime.panel;

if (!panel) {
  throw new Error(
    "JinRuntime.panel must be loaded before runtime.js"
  );
}

const memoryView =
  window.JinRuntime
  && window.JinRuntime.memoryView;

if (!memoryView) {
  throw new Error(
    "JinRuntime.memoryView must be loaded before runtime.js"
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
  extractActiveMemoryRuntimeMemoryLines,
  stripActiveMemoryRuntimeMemoryText,
  isActiveMemoryRuntimeMemoryLine,
  normalizeRuntimeMemoryKey,
  stripRuntimeMemoryMeta,
  isJinResponseRuntimeMemoryKey,
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
  readActiveMemoryRecords,
  writeActiveMemoryRecords,
  clearActiveMemoryRecords,
  appendActiveMemoryRecords: appendStoredActiveMemoryRecords,
  removeActiveMemoryRecordById: removeStoredActiveMemoryRecordById,
  readDelayedMemoryReports,
  writeDelayedMemoryReports,
  appendDelayedMemoryReports: appendStoredDelayedMemoryReports,
  readSessionSignals,
  writeSessionSignals,
  removeSessionSignalField,
  getCurrentRuntimeSessionId,
  getCurrentSessionSignalsSessionId,
} = storage;

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
  displayIndexOffset: 0,
};

let runtimeMemoryDisplayMode = "runtime";
let restoredSessionMemorySnapshot = null;

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


function stripActiveMemoryFromRuntimeSnapshot(
  snapshot
) {

  if (!snapshot || typeof snapshot !== "object") {
    return snapshot;
  }

  const rawMemory =
    String(snapshot.raw_memory || "");

  const activeLines =
    extractActiveMemoryRuntimeMemoryLines(
      rawMemory
    );

  if (activeLines.length) {
    appendStoredActiveMemoryRecords(
      activeLines
    );
  }

  const nextSnapshot = {
    ...snapshot,
    raw_memory: stripActiveMemoryRuntimeMemoryText(
      rawMemory
    ),
  };

  if (Array.isArray(snapshot.lines)) {
    nextSnapshot.lines = snapshot.lines
      .filter(line => !isActiveMemoryRuntimeMemoryLine(line));
  }

  return nextSnapshot;

}


function buildRuntimeMemoryDisplaySnapshot(
  snapshot
) {

  return snapshot;

}


const SESSION_SIGNAL_EXCLUDED_KEYS = new Set([
  "user_message",
  "user_idle",
]);

const deletedSessionSignalKeys =
  new Set();


function getSessionSignalIdentity(
  key
) {

  return `${getCurrentSessionSignalsSessionId()}:${key}`;

}


function getRuntimeSnapshotDiffKeys(
  snapshot
) {

  const patch =
    snapshot && snapshot.patch || {};

  return new Set(
    [
      ...(
        Array.isArray(patch.added)
          ? patch.added
          : []
      ).map(entry => entry && entry.key),
      ...(
        Array.isArray(patch.changed)
          ? patch.changed
          : []
      ).map(entry => (
        entry
        && (
          entry.current_key
          || entry.key
        )
      )),
    ]
      .map(normalizeRuntimeMemoryKey)
      .filter(Boolean)
  );

}


function persistRuntimeSessionSignals(
  snapshot
) {

  if (
      !snapshot
      || !Array.isArray(snapshot.lines)
  ) {
    return;
  }

  const fields =
    readSessionSignals();

  const diffKeys =
    getRuntimeSnapshotDiffKeys(
      snapshot
    );

  const turnNumber =
    Math.max(
      0,
      Math.trunc(
        Number(
          snapshot.turn_number
          || snapshot.user_message_count
          || 0
        )
      )
    );

  const runtimeSnapshotId =
    String(
      snapshot.runtime_memory_id || ""
    ).trim();

  snapshot.lines.forEach(
    function (line) {
      const key =
        normalizeRuntimeMemoryKey(
          line && line.key
        );

      const content =
        String(
          stripRuntimeMemoryMeta(
            line && line.value || ""
          )
        ).trim();

      if (
          !key
          || !content
          || deletedSessionSignalKeys.has(
            getSessionSignalIdentity(key)
          )
          || SESSION_SIGNAL_EXCLUDED_KEYS.has(key)
          || isJinResponseRuntimeMemoryKey(key)
          || isActiveMemoryRuntimeMemoryLine(line)
      ) {
        return;
      }

      const rawTrace =
        Number(
          line.strength
        );

      const trace =
        Number.isFinite(rawTrace)
          ? Number(rawTrace.toFixed(4))
          : 0.5;

      const existing =
        fields[key];

      if (!existing) {
        fields[key] = {
          max_trace: trace,
          content,
          diffs: 1,
          first_seen_turn: turnNumber,
          last_seen_turn: turnNumber,
          runtime_snapshot_id: runtimeSnapshotId,
        };

        return;
      }

      const maxTrace =
        Number(existing.max_trace);

      const replacePeak =
        trace > maxTrace
        || (
          trace === maxTrace
          && content !== String(existing.content || "")
        );

      fields[key] = {
        ...existing,
        diffs:
          Math.max(
            0,
            Math.trunc(
              Number(existing.diffs || 0)
            )
          )
          + (
            diffKeys.has(key)
              ? 1
              : 0
          ),
        last_seen_turn:
          Math.max(
            Math.max(
              0,
              Math.trunc(
                Number(existing.last_seen_turn || 0)
              )
            ),
            turnNumber
          ),
        ...(replacePeak
          ? {
            max_trace: trace,
            content,
            runtime_snapshot_id: runtimeSnapshotId,
          }
          : {}),
      };
    }
  );

  writeSessionSignals(
    fields
  );

}


function getFactsMemoryFields() {

  return readSessionSignals();

}


function deleteFactsMemoryFieldAndRender(
  key
) {

  const normalizedKey =
    normalizeRuntimeMemoryKey(
      key
    );

  if (!normalizedKey) {
    return false;
  }

  deletedSessionSignalKeys.add(
    getSessionSignalIdentity(
      normalizedKey
    )
  );

  removeSessionSignalField(
    normalizedKey
  );

  renderRuntimeMemorySnapshot();
  return true;

}


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

  const persistedSnapshot =
    stripActiveMemoryFromRuntimeSnapshot(
      data.snapshot
    );

  const runtimeMemory =
    (
      persistedSnapshot.raw_memory
      || stripActiveMemoryRuntimeMemoryText(data.memory || "")
      || ""
    ).trim();

  if (!runtimeMemory) {
    return;
  }

  const savedAt =
    new Date().toISOString();

  // Session signals are a companion index for the persisted live runtime.
  // Keep them behind the exact same updates > 0 gate so bootstrap/reload
  // snapshots never create empty one-off sessionSignals records.
  persistRuntimeSessionSignals(
    persistedSnapshot
  );

  writeLatestRuntimeMemory({
    version: 1,
    session_id:
      storage.getCurrentRuntimeSessionId(),
    saved_at: savedAt,
    runtime_memory: runtimeMemory,
    runtime_memory_updates: data.updates || 0,
    runtime_snapshot: buildPersistedRuntimeSnapshot(
      persistedSnapshot
    ),
  });

}


window.freezeLatestRuntimeMemoryUserIdle = function (
  userIdleText
) {
  memoryView.freezeLatestRuntimeMemoryUserIdle(
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

memoryView.init({
  history: runtimeMemoryHistory,
  idle,
  memoryModel,
  buildDisplaySnapshot: buildRuntimeMemoryDisplaySnapshot,
  getActiveMemoryRecords: readActiveMemoryRecords,
  setActiveMemoryRecords: writeActiveMemoryRecords,
  deleteRuntimeMemoryLine: deleteRuntimeMemoryLineAndRender,
  getDelayedMemoryReports: readDelayedMemoryReports,
  getFactsMemoryFields,
  deleteFactsMemoryField: deleteFactsMemoryFieldAndRender,
  getDisplayMode: () => runtimeMemoryDisplayMode,
  setDisplayMode: (value) => {
    runtimeMemoryDisplayMode = value;
  },
});

function renderRuntimeMemorySnapshot() {
  memoryView.renderRuntimeMemorySnapshot();
}

function showLatestRuntimeMemorySnapshot() {
  if (
      memoryView
      && typeof memoryView.showLatestRuntimeMemorySnapshot === "function"
  ) {
    memoryView.showLatestRuntimeMemorySnapshot();
    return;
  }

  if (!runtimeMemoryHistory.snapshots.length) {
    runtimeMemoryHistory.index = -1;
    return;
  }

  runtimeMemoryHistory.index =
      runtimeMemoryHistory.snapshots.length - 1;
}

function renderRuntimeDiffs() {
  memoryView.renderDiffs();
}

function buildRuntimeMemoryLineText(line) {
  if (!line || typeof line !== "object") {
    return "";
  }

  const key =
      String(line.key || "").trim();

  if (!key) {
    return "";
  }

  return `${key}: ${String(line.value || "").trim()}`;
}

function rebuildRuntimeMemorySnapshotLines(
  snapshot,
  runtimeMemory
) {
  if (!snapshot || typeof snapshot !== "object") {
    return;
  }

  snapshot.lines = splitMemoryTextLines(
      runtimeMemory
    )
    .map(parseRuntimeMemoryLine)
    .map(memoryModel.resetRuntimeMemoryLineFlashState);
}

function getNextLocalRuntimeMemoryUpdateCount(snapshot) {
  return Math.max(
    Number(
      runtimeMemoryCount
      && runtimeMemoryCount.textContent || 0
    ),
    Number(
      snapshot
      && snapshot.runtime_memory_updates || 0
    ),
    0
  ) + 1;
}

function deleteRuntimeMemoryLineAndRender(
  index,
  line
) {
  const snapshot =
      runtimeMemoryHistory.snapshots[
        runtimeMemoryHistory.index
      ];

  if (
      !snapshot
      || runtimeMemoryHistory.index
          !== runtimeMemoryHistory.snapshots.length - 1
      || !line
      || !line.key
      || isUserIdleRuntimeMemoryLine(line)
      || isActiveMemoryRuntimeMemoryLine(line)
  ) {
    return false;
  }

  const key =
      String(line.key || "").trim();

  const currentMemory =
      String(snapshot.raw_memory || "").trim();

  const nextMemory =
      removeRuntimeMemoryLineByKey(
          currentMemory,
          key
      );

  if (nextMemory === currentMemory) {
    return false;
  }

  const nextUpdates =
      getNextLocalRuntimeMemoryUpdateCount(
          snapshot
      );

  snapshot.raw_memory = nextMemory;
  snapshot.runtime_memory_updates = nextUpdates;
  snapshot.local_runtime_memory_delete = true;
  snapshot.deleted_runtime_memory_line =
      buildRuntimeMemoryLineText(line);

  rebuildRuntimeMemorySnapshotLines(
      snapshot,
      nextMemory
  );

  if (runtimeMemoryCount) {
    runtimeMemoryCount.textContent =
        String(nextUpdates);
  }

  persistRuntimeMemorySnapshot({
    memory: nextMemory,
    updates: nextUpdates,
    snapshot,
  });

  if (
      window.sendRuntimeMemoryDeleteSlot
      && typeof window.sendRuntimeMemoryDeleteSlot === "function"
  ) {
    window.sendRuntimeMemoryDeleteSlot({
      key,
      line: buildRuntimeMemoryLineText(line),
      index: Number(index),
    });
  }

  renderRuntimeMemorySnapshot();
  return true;
}

function appendActiveMemoryRecordsAndRender(
  records
) {

  const nextRecords =
    appendStoredActiveMemoryRecords(
      records
    );

  showLatestRuntimeMemorySnapshot();
  renderRuntimeMemorySnapshot();

  return nextRecords;

}


function replaceActiveMemoryRecordsAndRender(
  records
) {

  writeActiveMemoryRecords(
    records
  );

  showLatestRuntimeMemorySnapshot();
  renderRuntimeMemorySnapshot();

  return readActiveMemoryRecords();

}


function removeActiveMemoryRecordByIdAndRender(
  activeMemoryId
) {

  const nextRecords =
    removeStoredActiveMemoryRecordById(
      activeMemoryId
    );

  showLatestRuntimeMemorySnapshot();
  renderRuntimeMemorySnapshot();

  return nextRecords;

}


function appendDelayedMemoryReports(
  reports
) {

  const nextReports =
    appendStoredDelayedMemoryReports(
      reports
    );

  renderRuntimeMemorySnapshot();

  return nextReports;

}

const ACTIVE_MEMORY_RUNTIME_ACTIONS_TO_SILENCE_ON_L1 = [
  "create_active_memory",
  "resolve_active_memory",
];

function silenceActiveMemoryRuntimeActionsAfterL1(
  data
) {

  if (!window.fadeRuntimeAction) {
    return;
  }

  const isRuntimeMemoryUpdate =
    data.type === "runtime_memory_update"
    && Number(data.updates || 0) > 0;

  const isRuntimeL1DiffUpdate =
    data.type === "runtime_l1_diff_update";

  if (
      !isRuntimeMemoryUpdate
      && !isRuntimeL1DiffUpdate
  ) {
    return;
  }

  ACTIVE_MEMORY_RUNTIME_ACTIONS_TO_SILENCE_ON_L1
    .forEach((action) => {
      window.fadeRuntimeAction(
        action
      );
    });

}

function handleRuntimeMemoryMessage(data) {

  if (!data) {
    return;
  }

  if (data.type === "runtime_l1_diff_update") {
    silenceActiveMemoryRuntimeActionsAfterL1(
      data
    );

    memoryView.setRuntimeDiffUpdate(
      data
    );

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
        "save_session"
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

  silenceActiveMemoryRuntimeActionsAfterL1(
    data
  );

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

      clientSnapshot = stripActiveMemoryFromRuntimeSnapshot({
        ...runtimeMemoryHistory.snapshots[clientIndex],
        ...data.snapshot,
        index: clientIndex,
      });

      runtimeMemoryHistory.snapshots[clientIndex] =
          clientSnapshot;
      runtimeMemoryHistory.index = clientIndex;

      session.rememberStableRuntimeSnapshot(
        clientSnapshot
      );
    } else {
      const clientIndex = runtimeMemoryHistory.snapshots.length;
      clientSnapshot = stripActiveMemoryFromRuntimeSnapshot({
        ...data.snapshot,
        index: clientIndex,
      });

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

}

window.JinRuntime.runtime = {
  init() {
    return true;
  },
  getRuntimeMemorySnapshots() {
    return runtimeMemoryHistory.snapshots;
  },
  getRuntimeMemorySnapshot(index) {
    const numericIndex =
      Number(index);

    if (
      !Number.isInteger(numericIndex)
      || numericIndex < 0
    ) {
      return null;
    }

    return runtimeMemoryHistory.snapshots[numericIndex] || null;
  },
  handleRuntimeMemoryMessage,
  renderRuntimeMemorySnapshot,
  showLatestRuntimeMemorySnapshot,
  renderDiffs: renderRuntimeDiffs,
  persistRuntimeMemorySnapshot,
  getActiveMemoryRecords: readActiveMemoryRecords,
  clearActiveMemoryRecords() {
    const records =
      clearActiveMemoryRecords();

    renderRuntimeMemorySnapshot();

    return records;
  },
  replaceActiveMemoryRecords: replaceActiveMemoryRecordsAndRender,
  appendActiveMemoryRecords: appendActiveMemoryRecordsAndRender,
  removeActiveMemoryRecordById: removeActiveMemoryRecordByIdAndRender,
  getDelayedMemoryReports: readDelayedMemoryReports,
  getFactsMemoryFields,
  deleteFactsMemoryField: deleteFactsMemoryFieldAndRender,
  replaceDelayedMemoryReports: writeDelayedMemoryReports,
  appendDelayedMemoryReports,
};

window.JinRuntime.init = function () {
  return true;
};

window.handleRuntimeMemoryMessage = function (data) {
  return handleRuntimeMemoryMessage(data);
};

}());
