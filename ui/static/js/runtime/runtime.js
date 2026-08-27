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

const l4Memory =
  window.JINRuntimeL4Memory
  || (
    window.JinRuntime
    && window.JinRuntime.l4Memory
  )
  || null;

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

const DELAYED_MEMORY_STORE_CHANGED_EVENT =
  "jin:delayed-memory-store-changed";
const ACTIVE_MEMORY_RECORDS_CHANGED_EVENT =
  "jin:active-memory-records-changed";

function getActiveMemoryRecordIds(records) {
  return Array.from(
    new Set(
      (Array.isArray(records) ? records : [])
        .map((record) => {
          const match = String(record || "").match(
            /\[\s*active_memory_id\s*:\s*([a-z0-9]{6})\s*\]/i
          );

          return match
            ? String(match[1] || "").trim().toLowerCase()
            : "";
        })
        .filter(Boolean)
    )
  );
}

function dispatchActiveMemoryRecordsChanged(reason = "") {
  const records = readActiveMemoryRecords();

  window.dispatchEvent(
    new CustomEvent(
      ACTIVE_MEMORY_RECORDS_CHANGED_EVENT,
      {
        detail: {
          reason: String(reason || ""),
          records: [...records],
          ids: getActiveMemoryRecordIds(records),
        },
      }
    )
  );

  return records;
}

function dispatchDelayedMemoryStoreChanged(
  reason = "",
  reportId = ""
) {
  window.dispatchEvent(
    new CustomEvent(
      DELAYED_MEMORY_STORE_CHANGED_EVENT,
      {
        detail: {
          reason: String(reason || ""),
          reportId:
            normalizeRuntimeDelayedMemoryReportId(
              reportId
            ),
        },
      }
    )
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
  replaceActiveMemoryRecordById: replaceStoredActiveMemoryRecordById,
  removeActiveMemoryRecordById: removeStoredActiveMemoryRecordById,
  normalizeDelayedMemoryReports,
  readDelayedMemoryReports,
  writeDelayedMemoryReports,
  mergeDelayedMemoryReports: mergeStoredDelayedMemoryReports,
  readFactsMemory,
  writeFactsMemory,
  removeFactsMemoryField,
  getCurrentRuntimeSessionId,
  getCurrentFactsMemorySessionId,
} = storage;

const runtimeMemoryCount =
  document.getElementById(
    "runtime-memory-count"
  );

const defaultRuntimeMemoryText =
  "This session has just begun.";

const sessionStartedRuntimeMemoryText =
  "session_status: Session started";

const runtimeMemoryHistory = {
  snapshots: [],
  index: -1,
  displayIndexOffset: 0,
};

let runtimeMemoryDisplayMode = "runtime";
const loadedDelayedMemoryReportIds = new Set();

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


const FACTS_MEMORY_EXCLUDED_KEYS = new Set([
  "user_message",
  "user_idle",
]);

const FACTS_MEMORY_EXCLUDED_KEY_PATTERNS = [
  /^l4_fact_?f?[1-9]\d*$/i,
];

function isFactsMemoryExcludedKey(
  key
) {

  const normalizedKey =
    normalizeRuntimeMemoryKey(
      key
    );

  return (
      FACTS_MEMORY_EXCLUDED_KEYS.has(
        normalizedKey
      )
      || FACTS_MEMORY_EXCLUDED_KEY_PATTERNS.some(
        pattern => pattern.test(normalizedKey)
      )
  );

}

const deletedFactsMemoryKeys =
  new Set();


function getFactsMemoryIdentity(
  key
) {

  return `${getCurrentFactsMemorySessionId()}:${key}`;

}


function persistRuntimeFactsMemory(
  snapshot
) {

  if (
      !snapshot
      || !Array.isArray(snapshot.lines)
  ) {
    return;
  }

  const fields =
    readFactsMemory();

  const runtimeSnapshotId =
    String(
      snapshot.runtime_memory_id || ""
    ).trim();

  const sessionId =
    String(
      storage.getCurrentFactsMemorySessionId
        ? storage.getCurrentFactsMemorySessionId()
        : ""
    ).trim();

  snapshot.lines.forEach(
    function (line) {
      const key =
        normalizeRuntimeMemoryKey(
          line && line.key
        );

      if (
          key
          && isFactsMemoryExcludedKey(key)
      ) {
        delete fields[key];
        return;
      }

      const content =
        String(
          stripRuntimeMemoryMeta(
            line && line.value || ""
          )
        ).trim();

      if (
          !key
          || !content
          || deletedFactsMemoryKeys.has(
            getFactsMemoryIdentity(key)
          )
          || isJinResponseRuntimeMemoryKey(key)
          || isActiveMemoryRuntimeMemoryLine(line)
      ) {
        return;
      }

      const existing =
        fields[key];
      const contentHash =
        storage.buildFactsMemoryContentHash
          ? storage.buildFactsMemoryContentHash(
              content
            )
          : content;
      if (!existing) {
        fields[key] = {
          content,
          runtime_snapshot_id: runtimeSnapshotId,
          session_id: sessionId,
          l4_status: "pending",
          l4_content_hash: contentHash,
          l4_analyzed_at: "",
        };

        return;
      }

      const previousHash =
        String(
          existing.l4_content_hash || ""
        ).trim();
      const contentChanged =
        previousHash !== contentHash
        || String(existing.content || "").trim() !== content;

      fields[key] = {
        ...existing,
        content,
        runtime_snapshot_id: runtimeSnapshotId,
        session_id: sessionId,
        l4_status: contentChanged
          ? "pending"
          : (
              existing.l4_status === "analyzed"
                ? "analyzed"
                : "pending"
            ),
        l4_content_hash: contentHash,
        l4_analyzed_at: contentChanged
          ? ""
          : String(existing.l4_analyzed_at || "").trim(),
      };
      delete fields[key].significance;
      delete fields[key].metabolic_significance;
      delete fields[key].significance_updated_at;
    }
  );

  writeFactsMemory(
    fields
  );

}


function getFactsMemoryFields() {

  return readFactsMemory();

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

  deletedFactsMemoryKeys.add(
    getFactsMemoryIdentity(
      normalizedKey
    )
  );

  removeFactsMemoryField(
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
    if (
        session
        && typeof session.persistLiveSessionCheckpoint === "function"
    ) {
      session.persistLiveSessionCheckpoint(
        data
      );
    }

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

  // Facts memory is a companion index for the persisted live runtime.
  // Keep them behind the exact same updates > 0 gate so bootstrap/reload
  // snapshots never create empty one-off factsMemory records.
  persistRuntimeFactsMemory(
    persistedSnapshot
  );

  // Facts Memory still originates in the browser profile, but scheduling no
  // longer does. Hand fresh pending fields to the backend immediately; from
  // this point L4 consolidation is driven entirely by the server scheduler.
  if (typeof window.syncFactsMemoryToRuntime === "function") {
    window.syncFactsMemoryToRuntime();
  }

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

  if (
      session
      && typeof session.persistLiveSessionCheckpoint === "function"
  ) {
    session.persistLiveSessionCheckpoint(
      data
    );
  }

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
  setRuntimeMemoryDisplayMode: (value) => {
    runtimeMemoryDisplayMode = value;
  },
  renderRuntimeMemorySnapshot,
  persistRuntimeMemorySnapshot,
  attachFirstUserIdleToInitialRuntimeSnapshot,
  getLoadedDelayedMemoryReportIds,
});

panel.init();

memoryView.init({
  history: runtimeMemoryHistory,
  idle,
  memoryModel,
  buildDisplaySnapshot: buildRuntimeMemoryDisplaySnapshot,
  getActiveMemoryRecords: readActiveMemoryRecords,
  setActiveMemoryRecords: writeActiveMemoryRecordsAndRefresh,
  deleteRuntimeMemoryLine: deleteRuntimeMemoryLineAndRender,
  getDelayedMemoryReports: readDelayedMemoryReports,
  isDelayedMemoryReportLoaded,
  handleDelayedMemoryReportPinClick,
  setDelayedMemoryReportPinned,
  updateDelayedMemoryReportFields,
  setDelayedMemoryReportAnchorFactIds,
  linkDelayedMemoryReportFactId,
  linkDelayedMemoryReportFactIds,
  unlinkDelayedMemoryReportFactId,
  deleteDelayedMemoryReport: deleteDelayedMemoryReportAndRender,
  removeLongTermFactIdFromDelayedMemoryReports,
  getFactsMemoryFields,
  deleteFactsMemoryField: deleteFactsMemoryFieldAndRender,
  getLongTermMemoryFacts: getVisibleLongTermMemoryFacts,
  deleteLongTermMemoryFact: deleteLongTermMemoryFactAndRender,
  getDisplayMode: () => runtimeMemoryDisplayMode,
  setDisplayMode: (value) => {
    runtimeMemoryDisplayMode = value;
  },
});

function renderRuntimeMemorySnapshot() {
  memoryView.renderRuntimeMemorySnapshot();
}

function refreshRuntimeAvatar() {
  const avatar =
      window.JinRuntime
      && window.JinRuntime.avatar;

  if (
      avatar
      && typeof avatar.refresh === "function"
  ) {
    avatar.refresh();
  }
}

function getVisibleLongTermMemoryFacts() {
  if (
      l4Memory
      && typeof l4Memory.getVisibleFacts === "function"
  ) {
    return l4Memory.getVisibleFacts();
  }

  return l4Memory && typeof l4Memory.getFacts === "function"
    ? l4Memory.getFacts()
    : [];
}

function setDelayedMemoryPinnedOnAvatar(
  reportId,
  pinned
) {
  const avatar =
      window.JinRuntime
      && window.JinRuntime.avatar;

  if (
      avatar
      && typeof avatar.setDelayedMemoryPinned === "function"
  ) {
    return avatar.setDelayedMemoryPinned(
      reportId,
      pinned
    );
  }

  return false;
}

function syncDelayedMemoryStateToAvatar() {
  const avatar =
      window.JinRuntime
      && window.JinRuntime.avatar;

  if (
      avatar
      && typeof avatar.syncDelayedMemoryState === "function"
  ) {
    return avatar.syncDelayedMemoryState();
  }

  return false;
}

function normalizeRuntimeDelayedMemoryReportId(value) {
  const reportId =
      String(value || "").trim().toLowerCase();

  return /^[a-z0-9]{6}$/.test(reportId)
    ? reportId
    : "";
}

function normalizeRuntimeDelayedMemoryAttachmentIds(value) {
  const source = Array.isArray(value) ? value : [value];
  const ids = [];
  const seen = new Set();

  source.flat(Infinity).forEach((item) => {
    String(item || "")
      .split(/[,;\s]+/)
      .map((id) => id.trim().replace(/^[\[\]"']+|[\[\]"']+$/g, "").toLowerCase())
      .filter(Boolean)
      .forEach((id) => {
        if (!/^[a-z0-9]{6}$/.test(id) || seen.has(id)) {
          return;
        }
        seen.add(id);
        ids.push(id);
      });
  });

  return ids;
}

function syncDelayedMemoryReportsToServer(
  options = {}
) {
  if (typeof window.syncDelayedMemoryReportsToRuntime !== "function") {
    return false;
  }

  return window.syncDelayedMemoryReportsToRuntime(
    options
  );
}

function getLoadedDelayedMemoryReportIds() {
  return Array.from(loadedDelayedMemoryReportIds)
    .sort();
}

function replaceLoadedDelayedMemoryReportIds(
  reportIds,
  options = {}
) {
  const nextIds = new Set(
    (Array.isArray(reportIds) ? reportIds : [])
      .map(normalizeRuntimeDelayedMemoryReportId)
      .filter(Boolean)
  );
  const changed =
    nextIds.size !== loadedDelayedMemoryReportIds.size
    || Array.from(nextIds).some(
      reportId => !loadedDelayedMemoryReportIds.has(reportId)
    );

  if (!changed) {
    return getLoadedDelayedMemoryReportIds();
  }

  loadedDelayedMemoryReportIds.clear();
  nextIds.forEach(
    reportId => loadedDelayedMemoryReportIds.add(reportId)
  );

  if (options.render !== false) {
    renderRuntimeMemorySnapshot();

    if (!syncDelayedMemoryStateToAvatar()) {
      refreshRuntimeAvatar();
    }
  }

  dispatchDelayedMemoryStoreChanged(
    "load-state",
    ""
  );

  return getLoadedDelayedMemoryReportIds();
}

function isDelayedMemoryReportLoaded(reportId) {
  const normalizedId =
      normalizeRuntimeDelayedMemoryReportId(reportId);

  return Boolean(
    normalizedId
    && loadedDelayedMemoryReportIds.has(normalizedId)
  );
}

function markDelayedMemoryReportLoaded(
  reportId,
  loaded = true,
  options = {}
) {
  const normalizedId =
      normalizeRuntimeDelayedMemoryReportId(reportId);

  if (!normalizedId) {
    return false;
  }

  const wasLoaded =
      loadedDelayedMemoryReportIds.has(normalizedId);

  if (loaded) {
    loadedDelayedMemoryReportIds.add(normalizedId);
  } else {
    loadedDelayedMemoryReportIds.delete(normalizedId);
  }

  if (
      wasLoaded === loadedDelayedMemoryReportIds.has(normalizedId)
      && options.forceRender !== true
  ) {
    return true;
  }

  renderRuntimeMemorySnapshot();

  if (!syncDelayedMemoryStateToAvatar()) {
    refreshRuntimeAvatar();
  }

  dispatchDelayedMemoryStoreChanged(
    loaded ? "load" : "unload",
    normalizedId
  );

  if (options.sync === true) {
    syncDelayedMemoryReportsToServer({
      suppressedAutoLoadIds:
        options.suppressNextTurn === true
          ? [normalizedId]
          : [],
    });
  }

  return true;
}

function handleDelayedMemoryReportPinClick(reportId) {
  const normalizedId =
      normalizeRuntimeDelayedMemoryReportId(reportId);
  const report =
      normalizedId
      ? readDelayedMemoryReports()[normalizedId]
      : null;

  if (
      !normalizedId
      || !report
      || typeof report !== "object"
      || Array.isArray(report)
  ) {
    return false;
  }

  const pinned = Boolean(report.pinned);
  const loaded =
      isDelayedMemoryReportLoaded(normalizedId);

  if (!pinned && loaded) {
    markDelayedMemoryReportLoaded(
      normalizedId,
      false,
      {
        sync: true,
        suppressNextTurn: true,
      }
    );


    return {
      action: "unload",
      pinned: false,
      reportId: normalizedId,
    };
  }

  const nextPinned = !pinned;
  const changed = setDelayedMemoryReportPinned(
    normalizedId,
    nextPinned
  );

  if (!changed) {
    return false;
  }

  return {
    action: nextPinned ? "pin" : "unpin",
    pinned: nextPinned,
    reportId: normalizedId,
  };
}

function buildDeletedDelayedMemoryReportPayload(
  reportId,
  report
) {
  const normalizedId =
      normalizeRuntimeDelayedMemoryReportId(reportId);

  if (
      !normalizedId
      || !report
      || typeof report !== "object"
      || Array.isArray(report)
  ) {
    return null;
  }

  return {
    ...report,
    id: normalizedId,
    _storage_key: normalizedId,
    _restore_meta: {
      was_loaded:
        isDelayedMemoryReportLoaded(normalizedId)
        || Boolean(report.pinned),
    },
  };
}

function logDeletedDelayedMemoryReport(
  reportId,
  report
) {
  const deletedReport =
      buildDeletedDelayedMemoryReportPayload(
        reportId,
        report
      );

  if (
      !deletedReport
      || typeof window.appendLog !== "function"
  ) {
    return;
  }

  window.appendLog(
    "[MEMORY:DELAYED:DELETED]",
    "Delayed memory deleted",
    JSON.stringify(
      {
        kind: "delayed_memory_report",
        report: deletedReport,
      },
      null,
      2
    ),
    {
      memory_event: "delayed_memory_deleted",
      deleted_delayed_memory_report: deletedReport,
    }
  );
}

function syncActiveMemoryStateToAvatar() {
  const avatar =
      window.JinRuntime
      && window.JinRuntime.avatar;

  if (
      avatar
      && typeof avatar.syncActiveMemoryState === "function"
  ) {
    return avatar.syncActiveMemoryState();
  }

  return false;
}

function writeActiveMemoryRecordsAndRefresh(
  records
) {
  writeActiveMemoryRecords(
    records
  );

  if (!syncActiveMemoryStateToAvatar()) {
    refreshRuntimeAvatar();
  }

  return dispatchActiveMemoryRecordsChanged(
    "replace-from-memory-view"
  );
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

  if (!syncActiveMemoryStateToAvatar()) {
    refreshRuntimeAvatar();
  }

  dispatchActiveMemoryRecordsChanged(
    "append"
  );

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

  if (!syncActiveMemoryStateToAvatar()) {
    refreshRuntimeAvatar();
  }

  return dispatchActiveMemoryRecordsChanged(
    "replace"
  );

}


function replaceActiveMemoryRecordByIdAndRender(
  activeMemoryId,
  record
) {

  const nextRecords =
    replaceStoredActiveMemoryRecordById(
      activeMemoryId,
      record
    );

  showLatestRuntimeMemorySnapshot();
  renderRuntimeMemorySnapshot();

  if (!syncActiveMemoryStateToAvatar()) {
    refreshRuntimeAvatar();
  }

  dispatchActiveMemoryRecordsChanged(
    "update"
  );

  return nextRecords;

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

  if (!syncActiveMemoryStateToAvatar()) {
    refreshRuntimeAvatar();
  }

  dispatchActiveMemoryRecordsChanged(
    "remove"
  );

  return nextRecords;

}


function updateDelayedMemoryReportFields(
  reportId,
  fields = {}
) {

  const normalizedId =
    normalizeRuntimeDelayedMemoryReportId(
      reportId
    );
  const reports =
    readDelayedMemoryReports();
  const report =
    reports[normalizedId];

  if (
      !normalizedId
      || !report
      || typeof report !== "object"
      || Array.isArray(report)
  ) {
    return false;
  }

  const nextTitle =
    Object.prototype.hasOwnProperty.call(fields, "title")
      ? String(fields.title || "").trim() || "undefined"
      : String(report.title || "").trim() || "undefined";
  const nextSummary =
    Object.prototype.hasOwnProperty.call(fields, "summary")
      ? String(fields.summary || "")
      : String(report.summary || "");
  const nextBody =
    Object.prototype.hasOwnProperty.call(fields, "body")
      ? String(fields.body || "")
      : String(report.body || "");
  const normalizeTags = (value) => {
    const storage =
        window.JinRuntime
        && window.JinRuntime.storage;

    if (storage && typeof storage.normalizeDelayedMemoryTags === "function") {
      return storage.normalizeDelayedMemoryTags(value);
    }

    return (Array.isArray(value) ? value : [value])
      .flat(Infinity)
      .map(tag => String(tag || "").trim())
      .filter(Boolean);
  };
  const currentTags =
    normalizeTags(report.tags);
  const nextTags =
    Object.prototype.hasOwnProperty.call(fields, "tags")
      ? normalizeTags(fields.tags)
      : currentTags;
  const currentAttachmentIds =
    normalizeRuntimeDelayedMemoryAttachmentIds(
      report.attachments_ids
    );
  const nextAttachmentIds =
    Object.prototype.hasOwnProperty.call(fields, "attachments_ids")
      ? normalizeRuntimeDelayedMemoryAttachmentIds(
          fields.attachments_ids
        )
      : currentAttachmentIds;
  const attachmentsChanged =
    nextAttachmentIds.join("|") !== currentAttachmentIds.join("|");

  reports[normalizedId] = {
    ...report,
    title: nextTitle,
    summary: nextSummary,
    tags: nextTags,
    body: nextBody,
    attachments_ids: nextAttachmentIds,
  };

  writeDelayedMemoryReports(
    reports
  );

  if (
      runtimeMemoryDisplayMode === "delayed"
      || (attachmentsChanged && runtimeMemoryDisplayMode === "files")
  ) {
    renderRuntimeMemorySnapshot();
  }

  if (
      attachmentsChanged
      && !syncDelayedMemoryStateToAvatar()
  ) {
    refreshRuntimeAvatar();
  }

  syncDelayedMemoryReportsToServer();

  dispatchDelayedMemoryStoreChanged(
    "update",
    normalizedId
  );

  const updatedReport =
    readDelayedMemoryReports()[normalizedId];

  return updatedReport
    ? {
      ...updatedReport,
      _storage_key: normalizedId,
    }
    : false;

}


function setDelayedMemoryReportPinned(
  reportId,
  pinned,
  options = {}
) {

  const normalizedId =
    String(reportId || "").trim().toLowerCase();
  const reports =
    readDelayedMemoryReports();
  const report =
    reports[normalizedId];

  if (
      !/^[a-z0-9]{6}$/.test(normalizedId)
      || !report
      || typeof report !== "object"
      || Array.isArray(report)
  ) {
    return false;
  }

  reports[normalizedId] = {
    ...report,
    pinned: Boolean(pinned),
    last_loaded_date:
      Boolean(pinned)
        ? new Date().toISOString()
        : String(report.last_loaded_date || "").trim(),
  };

  writeDelayedMemoryReports(
    reports
  );

  if (runtimeMemoryDisplayMode === "delayed") {
    renderRuntimeMemorySnapshot();
  }

  // Pin state affects more than the delayed-memory dash itself: it also
  // controls linked L4/attachment highlights. Re-sync the whole delayed
  // avatar state so unpinning cannot leave stale context-loaded classes.
  if (!syncDelayedMemoryStateToAvatar()) {
    refreshRuntimeAvatar();
  }

  if (typeof window.syncDelayedMemoryReportsToRuntime === "function") {
    window.syncDelayedMemoryReportsToRuntime();
  }

  if (typeof window.syncDelayedMemoryReportPreviewState === "function") {
    window.syncDelayedMemoryReportPreviewState(
      normalizedId,
      pinned
    );
  }

  dispatchDelayedMemoryStoreChanged(
    "pin",
    normalizedId
  );

  if (
      Boolean(report.pinned)
      && !Boolean(pinned)
      && options.log !== false
      && typeof window.appendLog === "function"
  ) {
    const unpinnedMemory = {
      kind: "delayed",
      id: normalizedId,
      label: String(report.title || report.id || normalizedId),
    };

    window.appendLog(
      "[MEMORY:UNPINNED]",
      "Delayed memory unpinned",
      JSON.stringify(unpinnedMemory, null, 2),
      {
        memory_event: "memory_unpinned",
        unpinned_memory: unpinnedMemory,
      }
    );
  }

  return true;

}


function setDelayedMemoryReportAnchorFactIds(
  reportId,
  anchorFactIds
) {

  const normalizedId =
    String(reportId || "").trim().toLowerCase();
  const reports =
    readDelayedMemoryReports();
  const report =
    reports[normalizedId];

  if (
      !/^[a-z0-9]{6}$/.test(normalizedId)
      || !report
      || typeof report !== "object"
      || Array.isArray(report)
  ) {
    return false;
  }

  reports[normalizedId] = {
    ...report,
    anchor_fact_ids:
      Array.isArray(anchorFactIds)
        ? anchorFactIds
        : [],
  };

  writeDelayedMemoryReports(
    reports
  );

  const updatedReports =
    readDelayedMemoryReports();
  const updatedReport =
    updatedReports[normalizedId];

  renderRuntimeMemorySnapshot();

  if (!syncDelayedMemoryStateToAvatar()) {
    refreshRuntimeAvatar();
  }

  if (typeof window.syncDelayedMemoryReportsToRuntime === "function") {
    window.syncDelayedMemoryReportsToRuntime();
  }

  return updatedReport
    ? {
      ...updatedReport,
      _storage_key: normalizedId,
    }
    : false;

}

function normalizeRuntimeLongTermFactIds(
  value
) {

  const source =
    Array.isArray(value)
      ? value
      : [value];
  const seen =
    new Set();
  const factIds = [];

  source.forEach((item) => {
    if (Array.isArray(item)) {
      normalizeRuntimeLongTermFactIds(item)
        .forEach((factId) => {
          if (seen.has(factId)) {
            return;
          }

          seen.add(factId);
          factIds.push(factId);
        });
      return;
    }

    const text =
      String(item || "").trim();

    if (text.startsWith("[") && text.endsWith("]")) {
      try {
        const parsed =
          JSON.parse(text);

        if (Array.isArray(parsed)) {
          normalizeRuntimeLongTermFactIds(parsed)
            .forEach((factId) => {
              if (seen.has(factId)) {
                return;
              }

              seen.add(factId);
              factIds.push(factId);
            });
          return;
        }
      } catch (_error) {
        // Fall through to token parsing.
      }
    }

    const tokens =
      text.match(/\bF[1-9]\d*\b/gi);

    if (tokens && tokens.length) {
      tokens.forEach((token) => {
        const normalizedFactId =
          normalizeLongTermFactId(token);

        if (
            !normalizedFactId
            || seen.has(normalizedFactId)
        ) {
          return;
        }

        seen.add(normalizedFactId);
        factIds.push(normalizedFactId);
      });
      return;
    }

    const normalizedFactId =
      normalizeLongTermFactId(item);

    if (
        !normalizedFactId
        || seen.has(normalizedFactId)
    ) {
      return;
    }

    seen.add(normalizedFactId);
    factIds.push(normalizedFactId);
  });

  return factIds;

}

function getRuntimeLongTermFactIdNumber(
  factId
) {

  const match =
    String(factId || "").match(/^F([1-9]\d*)$/);

  return match
    ? Number(match[1])
    : Number.POSITIVE_INFINITY;

}

function sortRuntimeLongTermFactIds(
  factIds
) {

  return [...factIds].sort((left, right) => {
    const leftNumber =
      getRuntimeLongTermFactIdNumber(left);
    const rightNumber =
      getRuntimeLongTermFactIdNumber(right);

    if (leftNumber !== rightNumber) {
      return leftNumber - rightNumber;
    }

    return String(left).localeCompare(
      String(right)
    );
  });

}

function findLongTermMemoryFact(
  factId
) {

  const normalizedFactId =
    normalizeLongTermFactId(factId);
  const facts =
    l4Memory && typeof l4Memory.getFacts === "function"
      ? l4Memory.getFacts()
      : getVisibleLongTermMemoryFacts();

  return (Array.isArray(facts) ? facts : [])
    .find((fact) => (
      normalizeLongTermFactId(fact && fact.id)
      === normalizedFactId
    )) || null;

}

function writeDelayedMemoryFactLinksAndRender(
  reportId,
  reports,
  reason
) {

  writeDelayedMemoryReports(
    reports
  );

  if (runtimeMemoryDisplayMode === "delayed") {
    renderRuntimeMemorySnapshot();
  }

  if (!syncDelayedMemoryStateToAvatar()) {
    refreshRuntimeAvatar();
  }

  syncDelayedMemoryReportsToServer();

  dispatchDelayedMemoryStoreChanged(
    reason,
    reportId
  );

  const updatedReport =
    readDelayedMemoryReports()[reportId];

  return updatedReport
    ? {
      ...updatedReport,
      _storage_key: reportId,
    }
    : false;

}

function logUnlinkedDelayedMemoryReportFact(
  reportId,
  report,
  factId,
  wasAnchor
) {

  if (typeof window.appendLog !== "function") {
    return;
  }

  const fact =
    findLongTermMemoryFact(
      factId
    );
  const payload = {
    kind: "delayed_memory_fact_unlink",
    report_id: reportId,
    fact_id: factId,
    was_anchor: Boolean(wasAnchor),
    report: {
      id: reportId,
      _storage_key: reportId,
      title: String(report && report.title || ""),
      summary: String(report && report.summary || ""),
    },
    fact: fact
      ? {
        ...fact,
      }
      : null,
  };

  window.appendLog(
    "[MEMORY:DELAYED:FACT_UNLINKED]",
    "Delayed memory fact unlinked",
    JSON.stringify(
      payload,
      null,
      2
    ),
    {
      memory_event: "delayed_memory_fact_unlinked",
      delayed_memory_fact_unlink: payload,
    }
  );

}

function linkDelayedMemoryReportFactId(
  reportId,
  factId,
  options = {}
) {

  return linkDelayedMemoryReportFactIds(
    reportId,
    [factId],
    options
  );

}

function linkDelayedMemoryReportFactIds(
  reportId,
  requestedFactIds,
  options = {}
) {

  const normalizedId =
    normalizeRuntimeDelayedMemoryReportId(
      reportId
    );
  const normalizedFactIds =
    normalizeRuntimeLongTermFactIds(
      requestedFactIds
    ).filter((factId) => (
      Boolean(findLongTermMemoryFact(factId))
    ));
  const reports =
    readDelayedMemoryReports();
  const report =
    reports[normalizedId];

  if (
      !normalizedId
      || !normalizedFactIds.length
      || !report
      || typeof report !== "object"
      || Array.isArray(report)
  ) {
    return false;
  }

  const currentFactIds =
    normalizeRuntimeLongTermFactIds(
      report.facts_ids
    );
  const anchorFactIds =
    normalizeRuntimeLongTermFactIds(
      report.anchor_fact_ids
    );
  const shouldAnchor =
    Boolean(options && options.anchor);
  const requestedFactIdSet =
    new Set(normalizedFactIds);
  const nextFactIds =
    normalizeRuntimeLongTermFactIds([
      currentFactIds.filter(
        factId => !requestedFactIdSet.has(factId)
      ),
      normalizedFactIds,
    ]);
  const nextAnchorFactIds =
    shouldAnchor
      ? sortRuntimeLongTermFactIds(
        normalizeRuntimeLongTermFactIds([
          ...anchorFactIds,
          ...normalizedFactIds,
        ])
      )
      : anchorFactIds;
  const factsChanged =
    nextFactIds.length !== currentFactIds.length
    || nextFactIds.some(
      (factId, index) => factId !== currentFactIds[index]
    );
  const anchorsChanged =
    nextAnchorFactIds.length !== anchorFactIds.length
    || nextAnchorFactIds.some(
      (factId, index) => factId !== anchorFactIds[index]
    );

  if (
      !factsChanged
      && !anchorsChanged
  ) {
    return {
      ...report,
      _storage_key: normalizedId,
    };
  }

  reports[normalizedId] = {
    ...report,
    facts_ids: nextFactIds,
    anchor_fact_ids: nextAnchorFactIds,
  };

  return writeDelayedMemoryFactLinksAndRender(
    normalizedId,
    reports,
    "fact_link"
  );

}

function unlinkDelayedMemoryReportFactId(
  reportId,
  factId,
  options = {}
) {

  const normalizedId =
    normalizeRuntimeDelayedMemoryReportId(
      reportId
    );
  const normalizedFactId =
    normalizeLongTermFactId(
      factId
    );
  const reports =
    readDelayedMemoryReports();
  const report =
    reports[normalizedId];

  if (
      !normalizedId
      || !normalizedFactId
      || !report
      || typeof report !== "object"
      || Array.isArray(report)
  ) {
    return false;
  }

  const factIds =
    normalizeRuntimeLongTermFactIds(
      report.facts_ids
    );
  const anchorFactIds =
    normalizeRuntimeLongTermFactIds(
      report.anchor_fact_ids
    );
  const absorbedFactIds =
    normalizeRuntimeLongTermFactIds(
      report.absorbed_fact_ids
    );
  const longTermFactIds =
    normalizeRuntimeLongTermFactIds(
      report.long_term_facts_ids
    );
  const nextFactIds =
    factIds.filter(item => item !== normalizedFactId);
  const nextAnchorFactIds =
    anchorFactIds.filter(item => item !== normalizedFactId);
  const nextAbsorbedFactIds =
    absorbedFactIds.filter(item => item !== normalizedFactId);
  const nextLongTermFactIds =
    longTermFactIds.filter(item => item !== normalizedFactId);
  const changed =
    nextFactIds.length !== factIds.length
    || nextAnchorFactIds.length !== anchorFactIds.length
    || nextAbsorbedFactIds.length !== absorbedFactIds.length
    || nextLongTermFactIds.length !== longTermFactIds.length;

  if (!changed) {
    return {
      ...report,
      _storage_key: normalizedId,
    };
  }

  const updatedReport = {
    ...report,
    facts_ids: nextFactIds,
    anchor_fact_ids: nextAnchorFactIds,
  };

  if (nextAbsorbedFactIds.length) {
    updatedReport.absorbed_fact_ids =
      nextAbsorbedFactIds;
  } else {
    delete updatedReport.absorbed_fact_ids;
  }

  if (nextLongTermFactIds.length) {
    updatedReport.long_term_facts_ids =
      nextLongTermFactIds;
  } else {
    delete updatedReport.long_term_facts_ids;
  }

  reports[normalizedId] =
    updatedReport;

  const result =
    writeDelayedMemoryFactLinksAndRender(
      normalizedId,
      reports,
      "fact_unlink"
    );

  if (!options || options.log !== false) {
    logUnlinkedDelayedMemoryReportFact(
      normalizedId,
      report,
      normalizedFactId,
      anchorFactIds.includes(normalizedFactId)
    );
  }

  return result;

}

function deleteDelayedMemoryReportAndRender(
  reportId
) {

  const normalizedId =
    normalizeRuntimeDelayedMemoryReportId(
      reportId
    );
  const reports =
    readDelayedMemoryReports();
  const report =
    reports[normalizedId];

  if (
      !normalizedId
      || !report
      || typeof report !== "object"
      || Array.isArray(report)
  ) {
    return false;
  }

  const deletedReport =
    buildDeletedDelayedMemoryReportPayload(
      normalizedId,
      report
    );

  delete reports[normalizedId];

  writeDelayedMemoryReports(
    reports
  );

  loadedDelayedMemoryReportIds.delete(
    normalizedId
  );

  renderRuntimeMemorySnapshot();

  if (!syncDelayedMemoryStateToAvatar()) {
    refreshRuntimeAvatar();
  }

  syncDelayedMemoryReportsToServer({
    deletedReportIds: [
      normalizedId,
    ],
  });

  logDeletedDelayedMemoryReport(
    normalizedId,
    report
  );

  dispatchDelayedMemoryStoreChanged(
    "delete",
    normalizedId
  );

  return {
    id: normalizedId,
    report: deletedReport,
  };

}

function restoreDelayedMemoryReportAndRender(
  reportId,
  report
) {

  const normalizedId =
    normalizeRuntimeDelayedMemoryReportId(
      reportId
      || (
        report
        && typeof report === "object"
        && !Array.isArray(report)
          ? report.id || report._storage_key
          : ""
      )
    );

  if (
      !normalizedId
      || !report
      || typeof report !== "object"
      || Array.isArray(report)
  ) {
    return false;
  }

  const restoreMeta =
    report._restore_meta
    && typeof report._restore_meta === "object"
    && !Array.isArray(report._restore_meta)
      ? report._restore_meta
      : {};
  const cleanReport = {
    ...report,
  };

  delete cleanReport.id;
  delete cleanReport._storage_key;
  delete cleanReport._restore_meta;

  writeDelayedMemoryReports({
    ...readDelayedMemoryReports(),
    [normalizedId]: cleanReport,
  });

  if (
      restoreMeta.was_loaded
      || Boolean(cleanReport.pinned)
  ) {
    loadedDelayedMemoryReportIds.add(
      normalizedId
    );
  }

  renderRuntimeMemorySnapshot();

  if (!syncDelayedMemoryStateToAvatar()) {
    refreshRuntimeAvatar();
  }

  syncDelayedMemoryReportsToServer();

  dispatchDelayedMemoryStoreChanged(
    "restore",
    normalizedId
  );

  return {
    id: normalizedId,
    report: readDelayedMemoryReports()[normalizedId],
  };

}


function normalizeLongTermFactId(
  value
) {

  const match =
    String(value || "").trim().match(/^F([1-9]\d*)$/i);

  return match
    ? `F${Number(match[1])}`
    : "";

}


function withoutLongTermFactId(
  values,
  factId
) {

  const source =
    Array.isArray(values)
      ? values
      : [];

  return source.filter((value) => (
    normalizeLongTermFactId(value) !== factId
  ));

}


function removeLongTermFactIdFromDelayedMemoryReports(
  factId
) {

  const normalizedFactId =
    normalizeLongTermFactId(factId);

  if (!normalizedFactId) {
    return false;
  }

  const reports =
    readDelayedMemoryReports();
  let changed = false;

  Object.entries(reports).forEach(([reportId, report]) => {
    if (
        !report
        || typeof report !== "object"
        || Array.isArray(report)
    ) {
      return;
    }

    const nextAnchorFactIds =
      withoutLongTermFactId(
        report.anchor_fact_ids,
        normalizedFactId
      );
    const nextFactIds =
      withoutLongTermFactId(
        report.facts_ids,
        normalizedFactId
      );

    if (
        nextAnchorFactIds.length === (report.anchor_fact_ids || []).length
        && nextFactIds.length === (report.facts_ids || []).length
        && !report.absorbed_fact_ids
        && !report.long_term_facts_ids
    ) {
      return;
    }

    const updatedReport = {
      ...report,
      anchor_fact_ids: nextAnchorFactIds,
      facts_ids: nextFactIds,
    };
    delete updatedReport.absorbed_fact_ids;
    delete updatedReport.long_term_facts_ids;
    reports[reportId] = updatedReport;
    changed = true;
  });

  if (!changed) {
    return false;
  }

  writeDelayedMemoryReports(
    reports
  );

  if (runtimeMemoryDisplayMode === "delayed") {
    renderRuntimeMemorySnapshot();
  }

  if (!syncDelayedMemoryStateToAvatar()) {
    refreshRuntimeAvatar();
  }

  if (typeof window.syncDelayedMemoryReportsToRuntime === "function") {
    window.syncDelayedMemoryReportsToRuntime();
  }

  return true;

}


function deleteLongTermMemoryFactAndRender(
  factId
) {

  const deleted =
    l4Memory && l4Memory.requestFactDelete
      ? l4Memory.requestFactDelete(factId)
      : false;

  if (deleted !== false) {
    removeLongTermFactIdFromDelayedMemoryReports(
      factId
    );
  }

  return deleted;

}


function mergeDelayedMemoryReports(
  reports
) {

  const nextReports =
    mergeStoredDelayedMemoryReports(
      reports
    );

  renderRuntimeMemorySnapshot();

  if (!syncDelayedMemoryStateToAvatar()) {
    refreshRuntimeAvatar();
  }

  dispatchDelayedMemoryStoreChanged(
    "merge"
  );

  return nextReports;

}

function buildDelayedMemoryReportsSignature(
  reports
) {

  const normalizedReports =
    normalizeDelayedMemoryReports(
      reports
    );

  return JSON.stringify(
    Object.keys(normalizedReports)
      .sort()
      .map(
        reportId => [
          reportId,
          normalizedReports[reportId],
        ]
      )
  );

}

function replaceDelayedMemoryReportsAndRender(
  reports
) {
  const currentReports =
    readDelayedMemoryReports();
  const nextReports =
    normalizeDelayedMemoryReports(
      reports
    );

  if (
      buildDelayedMemoryReportsSignature(currentReports)
      === buildDelayedMemoryReportsSignature(nextReports)
  ) {
    return currentReports;
  }

  writeDelayedMemoryReports(
    nextReports
  );
  renderRuntimeMemorySnapshot();

  dispatchDelayedMemoryStoreChanged(
    "replace"
  );

  if (syncDelayedMemoryStateToAvatar()) {
    return readDelayedMemoryReports();
  }

  refreshRuntimeAvatar();

  return readDelayedMemoryReports();
}

const ACTIVE_MEMORY_RUNTIME_ACTIONS_TO_SILENCE_ON_L1 = [
  "save_active_memory",
  "update_active_memory",
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

  if (data.type !== "runtime_memory_update") {
    return;
  }

  if (session.isReconnectInitialRuntimeMemoryUpdate(data)) {
    return;
  }

  if (session.isLatestRuntimeMemoryDuplicate(data)) {
    session.persistLiveSessionCheckpoint(
      data
    );
    return;
  }

  if (session.applyBootstrapRuntimeMemoryUpdate(data)) {
    return;
  }

  if (session.isBootstrapRuntimeMemoryDuplicate(data)) {
    session.persistLiveSessionCheckpoint(
      data
    );
    return;
  }

  silenceActiveMemoryRuntimeActionsAfterL1(
    data
  );

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

    if (!syncActiveMemoryStateToAvatar()) {
      refreshRuntimeAvatar();
    }

    dispatchActiveMemoryRecordsChanged(
      "clear"
    );

    return records;
  },
  replaceActiveMemoryRecords: replaceActiveMemoryRecordsAndRender,
  appendActiveMemoryRecords: appendActiveMemoryRecordsAndRender,
  replaceActiveMemoryRecordById: replaceActiveMemoryRecordByIdAndRender,
  removeActiveMemoryRecordById: removeActiveMemoryRecordByIdAndRender,
  getDelayedMemoryReports: readDelayedMemoryReports,
  getLoadedDelayedMemoryReportIds,
  replaceLoadedDelayedMemoryReportIds,
  isDelayedMemoryReportLoaded,
  markDelayedMemoryReportLoaded,
  handleDelayedMemoryReportPinClick,
  setDelayedMemoryReportPinned,
  updateDelayedMemoryReportFields,
  setDelayedMemoryReportAnchorFactIds,
  linkDelayedMemoryReportFactId,
  linkDelayedMemoryReportFactIds,
  unlinkDelayedMemoryReportFactId,
  deleteDelayedMemoryReport: deleteDelayedMemoryReportAndRender,
  restoreDelayedMemoryReport: restoreDelayedMemoryReportAndRender,
  getFactsMemoryFields,
  deleteFactsMemoryField: deleteFactsMemoryFieldAndRender,
  getLongTermMemoryFacts() {
    return getVisibleLongTermMemoryFacts();
  },
  deleteLongTermMemoryFact(factId) {
    return deleteLongTermMemoryFactAndRender(factId);
  },
  replaceDelayedMemoryReports: replaceDelayedMemoryReportsAndRender,
  mergeDelayedMemoryReports,
};

window.JinRuntime.init = function () {
  return true;
};

window.handleRuntimeMemoryMessage = function (data) {
  return handleRuntimeMemoryMessage(data);
};

}());
