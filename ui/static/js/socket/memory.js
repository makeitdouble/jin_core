let latestRuntimeSnapshotsLogged = false;
let activeMemoryRecordsLogged = false;
let factsMemoryRecordsLogged = false;

const MEMORY_GLOW_CLASSES = [
  "memory-updating",
  "memory-pulse",
  "memory-fading",
  "memory-l2-updating",
  "memory-l2-pulse",
  "memory-l2-fading",
  "memory-l3-updating",
  "memory-l3-pulse",
  "memory-l3-fading",
];

const MEMORY_GLOW_STAGES = {
  l1: {
    active: "memory-updating",
    pulse: "memory-pulse",
    fading: "memory-fading",
  },
  l2: {
    active: "memory-l2-updating",
    pulse: "memory-l2-pulse",
    fading: "memory-l2-fading",
  },
  l3: {
    active: "memory-l3-updating",
    pulse: "memory-l3-pulse",
    fading: "memory-l3-fading",
  },
};

function buildLatestRuntimeSnapshotsDetails(
  snapshots
) {

  const lines = [
    "current_runtime_session_id: "
      + String(window.jinRuntimeSessionId || websocketClientId),
    "",
    "current_key: "
      + String(
        window.getCurrentLatestRuntimeMemoryStorageKey
          ? window.getCurrentLatestRuntimeMemoryStorageKey()
          : ""
      ),
  ];

  snapshots.forEach(
    function (
      snapshot,
      index,
    ) {
      const runtimeMemory =
        String(snapshot.runtime_memory || "")
          .replace(/\\n/g, "\n")
          .replace(
            /;\s+(?=[a-z][a-z0-9_]*\s*:)/g,
            "\n"
          )
          .split(/\r?\n+/)
          .map(function (line) {
            return line.trim();
          })
          .filter(Boolean);

      lines.push(
        "",
        `[ snapshot ${index + 1} ]`,
        "",
        `key: ${snapshot.key || ""}`,
        "",
        `key_session_id: ${snapshot.key_session_id || ""}`,
        "",
        `session_id: ${snapshot.session_id || ""}`,
        "",
        `saved_at: ${snapshot.saved_at || ""}`,
        "",
        `runtime_memory_updates: ${snapshot.runtime_memory_updates || 0}`
      );

      if (runtimeMemory.length) {
        lines.push(
          "",
          "runtime_memory:",
          "",
          runtimeMemory.join("\n\n")
        );
      }
    }
  );

  return lines.join("\n");

}

function logOtherLatestRuntimeMemorySnapshots() {

  if (
      latestRuntimeSnapshotsLogged
      || !window.getOtherLatestRuntimeMemorySnapshots
  ) {
    return;
  }

  const snapshots =
    window.getOtherLatestRuntimeMemorySnapshots();

  if (!snapshots.length) {
    return;
  }

  latestRuntimeSnapshotsLogged = true;

  appendLog(
    "[LATEST SNAPSHOTS]",
    `${snapshots.length} stale latest runtime snapshot`
      + `${snapshots.length === 1 ? "" : "s"} found.`,
    buildLatestRuntimeSnapshotsDetails(
      snapshots
    )
  );

}


function getFactsMemoryRecordsForStartupLog() {

  const storage =
    window.JinRuntime
    && window.JinRuntime.storage;

  if (
      !storage
      || !storage.collectSessionSignalsRecords
  ) {
    return [];
  }

  return storage.collectSessionSignalsRecords();

}


function formatFactsMemoryTrace(
  value
) {

  const numericValue =
    Number(value);

  return Number.isFinite(numericValue)
    ? numericValue.toFixed(2)
    : "0.50";

}


function buildFactsMemoryDetails(
  record
) {

  const fields =
    record
    && record.signals
    && typeof record.signals === "object"
    && !Array.isArray(record.signals)
      ? record.signals
      : {};

  const lines = [];

  Object.entries(fields)
    .sort(function (left, right) {
      const traceDifference =
        Number(right[1] && right[1].max_trace || 0)
        - Number(left[1] && left[1].max_trace || 0);

      if (traceDifference) {
        return traceDifference;
      }

      return String(left[0] || "").localeCompare(
        String(right[0] || "")
      );
    })
    .forEach(function ([key, field]) {
      if (
          !field
          || typeof field !== "object"
          || Array.isArray(field)
      ) {
        return;
      }

      const content =
        String(field.content || "").trim();

      if (!content) {
        return;
      }

      if (lines.length) {
        lines.push("");
      }

      lines.push(
        `${key}: ${content}`,
        [
          `[ max_trace: ${formatFactsMemoryTrace(field.max_trace)} ]`,
          `[ diffs: ${Math.max(0, Math.trunc(Number(field.diffs || 0)))} ]`,
          `[ first_seen_turn: ${Math.max(0, Math.trunc(Number(field.first_seen_turn || 0)))} ]`,
          `[ last_seen_turn: ${Math.max(0, Math.trunc(Number(field.last_seen_turn || 0)))} ]`,
          `[ runtime_snapshot_id: ${String(field.runtime_snapshot_id || "").trim()} ]`,
        ].join(" ")
      );
    });

  return lines.join("\n");

}


function logFactsMemoryRecords() {

  if (factsMemoryRecordsLogged) {
    return;
  }

  const records =
    getFactsMemoryRecordsForStartupLog();

  if (!records.length) {
    return;
  }

  factsMemoryRecordsLogged = true;

  records.forEach(
    function (record) {
      appendLog(
        "[FACTS_MEMORY]",
        `session: ${record.session_id || "unknown"}\n`
          + `fields: ${record.signal_count || 0}`,
        buildFactsMemoryDetails(
          record
        ),
        {
          facts_memory_session_id:
            record.session_id || "",
          facts_memory_storage_key:
            record.storage_key || "",
        }
      );
    }
  );

}


function getActiveMemoryRecordsForStartupLog() {

  if (
      !window.JinRuntime
      || !window.JinRuntime.runtime
      || !window.JinRuntime.runtime.getActiveMemoryRecords
  ) {
    return [];
  }

  return window.JinRuntime.runtime.getActiveMemoryRecords();

}


function buildActiveMemoryDetails(
  records
) {

  const lines = [
    `count: ${records.length}`,
  ];

  records.forEach(
    function (
      record,
      index,
    ) {
      lines.push(
        "",
        `[ active memory ${index + 1} ]`,
        "",
        String(record || "")
      );
    }
  );

  return lines.join("\n");

}


function findActiveMemoryRecordById(
  activeMemoryId
) {

  const needle =
    String(activeMemoryId || "")
      .trim()
      .toLowerCase();

  if (!needle) {
    return {
      record: "",
      index: -1,
    };
  }

  const records =
    getActiveMemoryRecordsForStartupLog();

  const index =
    records.findIndex(function (record) {
      return String(record || "")
        .toLowerCase()
        .includes(needle);
    });

  return {
    record:
      index >= 0
        ? String(records[index] || "")
        : "",
    index,
  };

}


function getActiveMemoryRecordSlotNumber(
  record,
  index
) {

  const match =
    String(record || "").match(
      /^\s*active_memory(?:_(\d+))?\s*:/i
    );

  if (
    match
    && match[1]
  ) {
    return match[1];
  }

  if (index >= 0) {
    return String(index + 1);
  }

  return "";

}


function getActiveMemoryRecordTitle(
  record
) {

  return String(record || "")
    .replace(
      /^\s*active_memory(?:_\d+)?\s*:\s*/i,
      ""
    )
    .replace(
      /\s*\[[^\]]+\]\s*/g,
      " "
    )
    .replace(
      /\s+/g,
      " "
    )
    .trim();

}


function buildResolveActiveMemoryRuntimeActionText(
  data,
  fallbackText
) {

  const match =
    findActiveMemoryRecordById(
      data && data.id
    );

  const title =
    getActiveMemoryRecordTitle(
      match.record
    );

  if (!title) {
    return String(fallbackText || "");
  }

  const slotNumber =
    getActiveMemoryRecordSlotNumber(
      match.record,
      match.index
    );

  return slotNumber
    ? `Resolved #${slotNumber} - ${title}`
    : `Resolved - ${title}`;

}


function logActiveMemoryRecords() {

  if (activeMemoryRecordsLogged) {
    return;
  }

  const records =
    getActiveMemoryRecordsForStartupLog();

  if (!records.length) {
    return;
  }

  activeMemoryRecordsLogged = true;

  appendLog(
    "[ACTIVE_MEMORY]",
    `count: ${records.length}`,
    buildActiveMemoryDetails(
      records
    )
  );

}


function isMemoryLog(data) {
  return Boolean(
    data
    && (
        String(data.tag || "").includes("MEMORY:")
        || String(data.message || "").includes("[MEMORY]")
    )
  );
}

function memoryLogIncludes(data, text) {
  return Boolean(
    data
    && (
        String(data.message || "").includes(text)
        || String(data.message || "").includes(`[MEMORY] ${text}`)
        || String(data.message || "").includes(`[MEMORY:L1] ${text}`)
        || String(data.message || "").includes(`[MEMORY:L2] ${text}`)
        || String(data.message || "").includes(`[MEMORY:L3] ${text}`)
    )
  );
}

function memoryLogLevelIs(data, level) {
  const normalizedLevel = String(level || "").toUpperCase();

  return Boolean(
    data
    && (
      String(data.memory_level || "").toUpperCase() === normalizedLevel
      || String(data.tag || "").includes(`[MEMORY:${normalizedLevel}]`)
      || String(data.message || "").includes(`[MEMORY:${normalizedLevel}]`)
    )
  );
}

function memoryLogEventIs(data, event) {
  return Boolean(
    data
    && String(data.memory_event || "") === event
  );
}

function memoryLogMessageHasOutcome(data) {
  const message = String(data && data.message || "");

  return (
    message.includes("updated")
    || message.includes("skipped")
    || message.includes("failed")
  );
}

let activeMemoryGlowStage = "";
let memoryGlowPulseTimer = null;
let memoryGlowFadeTimer = null;

let factCheckGlowActive = false;
let factCheckGlowPulseTimer = null;
let factCheckGlowFadeTimer = null;

function getMemoryPanel() {
  return document.getElementById("settings-panel");
}

function clearFactCheckGlowTimers() {
  if (factCheckGlowPulseTimer) {
    clearTimeout(factCheckGlowPulseTimer);
    factCheckGlowPulseTimer = null;
  }

  if (factCheckGlowFadeTimer) {
    clearTimeout(factCheckGlowFadeTimer);
    factCheckGlowFadeTimer = null;
  }
}

function startFactCheckGlow() {
  const panel = getMemoryPanel();

  if (!panel) {
    return;
  }

  clearFactCheckGlowTimers();
  factCheckGlowActive = true;

  panel.classList.remove(
    "fact-check-fading"
  );

  panel.classList.add(
    "fact-check-running"
  );

  factCheckGlowPulseTimer = setTimeout(() => {
    if (
      !factCheckGlowActive
      || !panel.classList.contains("fact-check-running")
    ) {
      return;
    }

    panel.classList.add(
      "fact-check-pulse"
    );
  }, 900);
}

function stopFactCheckGlow() {
  const panel = getMemoryPanel();

  if (!panel) {
    return;
  }

  clearFactCheckGlowTimers();
  factCheckGlowActive = false;

  panel.classList.remove(
    "fact-check-pulse"
  );

  if (!panel.classList.contains("fact-check-running")) {
    return;
  }

  panel.classList.add(
    "fact-check-fading"
  );

  factCheckGlowFadeTimer = setTimeout(() => {
    if (factCheckGlowActive) {
      return;
    }

    panel.classList.remove(
      "fact-check-running",
      "fact-check-fading"
    );
  }, 1200);
}

function clearMemoryGlowTimers() {
  if (memoryGlowPulseTimer) {
    clearTimeout(memoryGlowPulseTimer);
    memoryGlowPulseTimer = null;
  }

  if (memoryGlowFadeTimer) {
    clearTimeout(memoryGlowFadeTimer);
    memoryGlowFadeTimer = null;
  }
}

function clearMemoryGlowClasses(panel) {
  panel.classList.remove(
    ...MEMORY_GLOW_CLASSES
  );
}

function setMemoryGlowStage(stage) {
  const panel = getMemoryPanel();
  const config = MEMORY_GLOW_STAGES[stage];

  if (
    !panel
    || !config
  ) {
    return;
  }

  clearMemoryGlowTimers();
  clearMemoryGlowClasses(panel);

  activeMemoryGlowStage = stage;

  panel.classList.add(
    config.active
  );

  memoryGlowPulseTimer = setTimeout(() => {
    if (
      activeMemoryGlowStage !== stage
      || !panel.classList.contains(config.active)
    ) {
      return;
    }

    panel.classList.add(
      config.pulse
    );
  }, 2200);
}

function stopMemoryGlowStage(stage) {
  const panel = getMemoryPanel();
  const config = MEMORY_GLOW_STAGES[stage];

  if (
    !panel
    || !config
    || activeMemoryGlowStage !== stage
  ) {
    return;
  }

  clearMemoryGlowTimers();

  activeMemoryGlowStage = "";

  panel.classList.remove(
    config.pulse
  );

  panel.classList.add(
    config.fading
  );

  memoryGlowFadeTimer = setTimeout(() => {
    if (activeMemoryGlowStage) {
      return;
    }

    panel.classList.remove(
      config.active,
      config.fading
    );
  }, 1800);
}

function startMemoryGlow() {
  setMemoryGlowStage("l1");
}

function stopMemoryGlow() {
  stopMemoryGlowStage("l1");
}

function startL2MemoryGlow() {
  setMemoryGlowStage("l2");
}

function stopL2MemoryGlow() {
  stopMemoryGlowStage("l2");
}

function startL3MemoryGlow() {
  setMemoryGlowStage("l3");
}

function stopL3MemoryGlow() {
  stopMemoryGlowStage("l3");
}

window.startMemoryGlow = startMemoryGlow;
window.stopMemoryGlow = stopMemoryGlow;
window.startL2MemoryGlow = startL2MemoryGlow;
window.stopL2MemoryGlow = stopL2MemoryGlow;
window.startL3MemoryGlow = startL3MemoryGlow;
window.stopL3MemoryGlow = stopL3MemoryGlow;
window.startFactCheckGlow = startFactCheckGlow;
window.stopFactCheckGlow = stopFactCheckGlow;

function handleActiveMemoryRecordsUpdate(
  data
) {

  if (
      window.JinRuntime
      && window.JinRuntime.runtime
      && window.JinRuntime.runtime.replaceActiveMemoryRecords
  ) {
    window.JinRuntime.runtime.replaceActiveMemoryRecords(
      data.active_memory_records || []
    );
  }

}

function handleFactCheckState(
  data
) {

  if (data.active) {
    startFactCheckGlow();
  } else {
    stopFactCheckGlow();
  }

}

function handleFactCheckUpdate() {
  stopFactCheckGlow();
}

function handleSocketLog(
  data
) {

  if (
      data.tag === "[USER]"
      && window.log_user
  ) {
    let payload =
      data.details || data.message || "";

    try {
      payload = JSON.parse(
        payload
      );
    } catch (_error) {
      payload = {
        text: String(
          data.message || ""
        ),
      };
    }

    window.log_user(
      payload
    );

    return;
  }

  appendLog(
    data.tag,
    data.message,
    data.details,
    data
  );

  if (
      isMemoryLog(data)
      && memoryLogLevelIs(data, "L1")
      && (
          memoryLogEventIs(data, "summarizer_request")
          || memoryLogIncludes(data, "L1 summarizer request")
      )
  ) {
    startMemoryGlow();
  }

  if (
      isMemoryLog(data)
      && memoryLogLevelIs(data, "L2")
      && (
          memoryLogEventIs(data, "summarizer_request")
          || memoryLogIncludes(data, "L2 summarizer request")
      )
  ) {
    startL2MemoryGlow();
  }

  if (
      isMemoryLog(data)
      && memoryLogLevelIs(data, "L3")
      && (
          memoryLogEventIs(data, "summarizer_request")
          || memoryLogIncludes(data, "L3 session summarizer request")
      )
  ) {
    startL3MemoryGlow();
  }

  if (
      isMemoryLog(data)
      && memoryLogLevelIs(data, "L1")
      && (
          memoryLogEventIs(data, "summarizer_result")
          || memoryLogMessageHasOutcome(data)
      )
  ) {
    stopMemoryGlow();
  }

  if (
      isMemoryLog(data)
      && memoryLogLevelIs(data, "L2")
      && (
          memoryLogEventIs(data, "summarizer_result")
          || memoryLogMessageHasOutcome(data)
      )
  ) {
    stopL2MemoryGlow();
  }

  if (
      isMemoryLog(data)
      && memoryLogLevelIs(data, "L3")
      && (
          memoryLogEventIs(data, "summarizer_result")
          || memoryLogMessageHasOutcome(data)
      )
  ) {
    stopL3MemoryGlow();
  }

}

registerSocketMessageHandler(
  "active_memory_records_update",
  handleActiveMemoryRecordsUpdate
);

registerSocketMessageHandler(
  "fact_check_state",
  handleFactCheckState
);

registerSocketMessageHandler(
  "fact_check_update",
  handleFactCheckUpdate
);

registerSocketMessageHandler(
  "log",
  handleSocketLog
);
