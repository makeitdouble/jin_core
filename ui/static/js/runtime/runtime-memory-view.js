(function () {
  window.JinRuntime = window.JinRuntime || {};

  let runtimeMemoryHistory = null;
  let idle = null;
  let memoryModel = null;
  let initialized = false;
  let userIdleValueNode = null;
  let buildDisplaySnapshot = null;
  let getActiveMemoryRecords = null;
  let setActiveMemoryRecords = null;
  let deleteRuntimeMemoryLine = null;
  let getDelayedMemoryReports = null;
  let getFactsMemoryFields = null;
  let deleteFactsMemoryField = null;
  let getDisplayMode = null;
  let setDisplayMode = null;

  const ACTIVE_MEMORY_PAUSE_HOLD_MS = 500;
  const MEMORY_DELETE_HOLD_MS = 1500;
  const THINK_RUNTIME_CITATION_HOVER_EVENT = "jin:think-runtime-citation-hover";
  const RUNTIME_MEMORY_LINE_HOVER_SOURCE_ID = "runtime-memory-line-hover";

  const pinnedRuntimeMemorySnapshotIndexes = new Set();

  const autoFlashedRuntimeMemorySnapshots = new WeakSet();


  let delayedMemoryModal = null;
  let delayedMemoryModalPanel = null;
  let delayedMemoryModalTitle = null;
  let delayedMemoryModalContent = null;

  const runtimeDiffHistory = {
    diffs: [],
    stats: {},
    expanded: false,
  };

  const runtimeMemoryText =
      document.getElementById("runtime-memory-text");

  const runtimeMemoryTitle =
      document.getElementById("runtime-memory-title");

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

  function requireRuntimeMemoryHistory() {
    if (!runtimeMemoryHistory) {
      throw new Error(
        "JinRuntime.memoryView.init() must be called before use"
      );
    }
  }

  function getUserIdleText() {
    return idle ? idle.getText() : "0s";
  }

  function getRuntimeMemoryDisplayMode() {
    return typeof getDisplayMode === "function"
      ? getDisplayMode()
      : "runtime";
  }

  function setRuntimeMemoryDisplayMode(mode) {
    if (typeof setDisplayMode === "function") {
      setDisplayMode(mode);
    }
  }

  function getRuntimeMemorySnapshotDisplayIndex(snapshot) {
    if (typeof snapshot.index !== "number") {
      return runtimeMemoryHistory.index + 1;
    }

    return snapshot.index
      + Number(runtimeMemoryHistory.displayIndexOffset || 0);
  }

  function getActiveMemoryRecordTexts() {
    return typeof getActiveMemoryRecords === "function"
      ? getActiveMemoryRecords()
      : [];
  }

  function getDelayedMemoryReportRecords() {
    const reports =
        typeof getDelayedMemoryReports === "function"
          ? getDelayedMemoryReports()
          : {};

    if (
        !reports
        || typeof reports !== "object"
        || Array.isArray(reports)
    ) {
      return [];
    }

    return Object.entries(reports)
        .map(([key, report]) => {
          if (
              !report
              || typeof report !== "object"
              || Array.isArray(report)
          ) {
            return null;
          }

          return {
            _storage_key: key,
            ...report,
          };
        })
        .filter(Boolean);
  }

  function setActiveMemoryRecordTexts(records) {
    if (typeof setActiveMemoryRecords === "function") {
      setActiveMemoryRecords(
          records
      );
    }
  }

  function getFactsMemoryFieldRecords() {
    const fields =
        typeof getFactsMemoryFields === "function"
          ? getFactsMemoryFields()
          : {};

    if (
        !fields
        || typeof fields !== "object"
        || Array.isArray(fields)
    ) {
      return [];
    }

    return Object.entries(fields)
      .map(([key, field]) => {
        if (
            !field
            || typeof field !== "object"
            || Array.isArray(field)
        ) {
          return null;
        }

        const content =
            String(field.content || "").trim();

        if (!content) {
          return null;
        }

        return {
          key,
          ...field,
          content,
        };
      })
      .filter(Boolean)
      .sort((left, right) => {
        const traceDifference =
            Number(right.max_trace || 0)
            - Number(left.max_trace || 0);

        if (traceDifference) {
          return traceDifference;
        }

        return String(left.key || "").localeCompare(
            String(right.key || "")
        );
      });
  }

  function getAvailableRuntimeMemoryDisplayModes() {
    const modes = [
      "runtime",
    ];

    if (getActiveMemoryRecordTexts().length > 0) {
      modes.push(
          "active"
      );
    }

    if (getDelayedMemoryReportRecords().length > 0) {
      modes.push(
          "delayed"
      );
    }

    if (getFactsMemoryFieldRecords().length > 0) {
      modes.push(
          "facts"
      );
    }

    return modes;
  }

  function ensureRuntimeMemoryDisplayModeAvailable() {
    const modes =
        getAvailableRuntimeMemoryDisplayModes();

    const displayMode =
        getRuntimeMemoryDisplayMode();

    if (modes.includes(displayMode)) {
      return displayMode;
    }

    setRuntimeMemoryDisplayMode(
        "runtime"
    );

    return "runtime";
  }

  function updateRuntimeMemoryTitleState() {
    if (!runtimeMemoryTitle) {
      return;
    }

    const modes =
        getAvailableRuntimeMemoryDisplayModes();

    const currentMode =
        getRuntimeMemoryDisplayMode();

    const displayMode =
        modes.includes(currentMode)
          ? currentMode
          : "runtime";

    runtimeMemoryTitle.textContent =
        displayMode === "active"
          ? "[ active memory ]"
          : displayMode === "delayed"
            ? "[ delayed memory ]"
            : displayMode === "facts"
              ? "[ facts memory ]"
              : "[ runtime memory ]";

    const hasAlternativeMemory =
        modes.length > 1;

    runtimeMemoryTitle.classList.toggle(
        "runtime-memory-title-clickable",
        hasAlternativeMemory
    );

    if (hasAlternativeMemory) {
      runtimeMemoryTitle.setAttribute(
          "role",
          "button"
      );

      runtimeMemoryTitle.setAttribute(
          "tabindex",
          "0"
      );
      return;
    }

    runtimeMemoryTitle.removeAttribute(
        "role"
    );

    runtimeMemoryTitle.removeAttribute(
        "tabindex"
    );
  }

  function updateUserIdleTimerText(
    text = getUserIdleText()
  ) {
    requireRuntimeMemoryHistory();

    if (!userIdleValueNode) {
      return;
    }

    userIdleValueNode.textContent =
        ` ${text}`;

    updateRuntimeMemoryTitleMetrics(
        getDisplayRuntimeMemorySnapshot(
            runtimeMemoryHistory.snapshots[
                runtimeMemoryHistory.index
            ]
        )
    );
  }

  function freezeLatestRuntimeMemoryUserIdle(userIdleText) {
    requireRuntimeMemoryHistory();

    const latestSnapshot =
        runtimeMemoryHistory.snapshots[
          runtimeMemoryHistory.snapshots.length - 1
        ];

    memoryModel.setRuntimeMemorySnapshotUserIdle(
      latestSnapshot,
      userIdleText
    );
  }

  function getDisplayRuntimeMemorySnapshot(
    snapshot
  ) {

    if (!snapshot || typeof snapshot !== "object") {
      return snapshot;
    }

    if (typeof buildDisplaySnapshot !== "function") {
      return snapshot;
    }

    const displaySnapshot =
        buildDisplaySnapshot(
          snapshot
        );

    return (
        displaySnapshot
        && typeof displaySnapshot === "object"
    )
      ? displaySnapshot
      : snapshot;

  }

  function formatRuntimeDiffNumber(value) {
    const number =
        Number(value || 0);

    return String(
        Number.isInteger(number)
          ? number
        : Number(number.toFixed(2))
    );
  }

  function formatRuntimeMemoryHoverTitle(text) {
    const raw =
        String(text || "").trim();

    if (!raw) {
      return "";
    }

    return raw
        .split(/\r?\n/)
        .map((line) => {
          const trimmed =
              String(line || "").trim();

          if (!trimmed) {
            return "";
          }

          const parts = [];
          let lastIndex = 0;

          trimmed.replace(
            /\s*(\[[^\]]+\]|\(\s*trace\s*:[^)]+\))/gi,
            (match, suffix, offset) => {
              if (!parts.length) {
                const body =
                    trimmed.slice(0, offset).trim();

                if (body) {
                  parts.push(body);
                }
              }

              parts.push(
                  String(suffix || "").trim()
              );
              lastIndex =
                  offset + match.length;

              return match;
            }
          );

          if (!parts.length) {
            return trimmed;
          }

          const tail =
              trimmed.slice(lastIndex).trim();

          if (tail) {
            parts.push(tail);
          }

          return parts.join("\n");
        })
        .join("\n");
  }

  function setRuntimeDiffUpdate(data) {
    runtimeDiffHistory.diffs =
        data && data.diffs || [];

    runtimeDiffHistory.stats =
        data && data.stats || {};

    renderRuntimeDiffs();
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
    requireRuntimeMemoryHistory();

    return pinnedRuntimeMemorySnapshotIndexes.has(
        runtimeMemoryHistory.index
    );
  }

  function updateRuntimeMemoryPinGlow() {
    if (!runtimeMemoryPosition) {
      return;
    }

    if (getRuntimeMemoryDisplayMode() !== "runtime") {
      runtimeMemoryPosition.classList.remove(
          "runtime-memory-position-pinned"
      );
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
            ? memoryModel.stripUserIdleRuntimeMemoryText(rawMemory)
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
            || !memoryModel.isUserIdleRuntimeMemoryLine(line)
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

  function updateRuntimeMemoryTitleMetricsFromText(text) {
    if (!runtimeMemoryTitle) {
      return;
    }

    const metricText =
        String(text || "").trim();

    const charCount =
        Array.from(metricText).length;

    const tokenCount =
        estimateRuntimeMemoryTokens(metricText);

    runtimeMemoryTitle.title =
        `${charCount} chars / ~${tokenCount} tokens`;
  }

  function clampRuntimeMemoryHistoryIndex() {
    requireRuntimeMemoryHistory();

    const snapshotCount =
        runtimeMemoryHistory.snapshots.length;

    if (!snapshotCount) {
      runtimeMemoryHistory.index = -1;
      return;
    }

    if (runtimeMemoryHistory.index < 0) {
      runtimeMemoryHistory.index = 0;
      return;
    }

    if (runtimeMemoryHistory.index >= snapshotCount) {
      runtimeMemoryHistory.index = snapshotCount - 1;
    }
  }

  function showLatestRuntimeMemorySnapshot() {
    requireRuntimeMemoryHistory();

    if (!runtimeMemoryHistory.snapshots.length) {
      runtimeMemoryHistory.index = -1;
      return;
    }

    runtimeMemoryHistory.index =
        runtimeMemoryHistory.snapshots.length - 1;
  }

  function dispatchRuntimeAvatarSnapshot(snapshot) {
    window.dispatchEvent(
      new CustomEvent("jin:runtime-avatar-snapshot", {
        detail: {
          snapshot: snapshot || null,
          index: runtimeMemoryHistory
            ? runtimeMemoryHistory.index
            : -1,
          count: runtimeMemoryHistory
            ? runtimeMemoryHistory.snapshots.length
            : 0,
        },
      })
    );
  }

  function renderRuntimeMemorySnapshot(options = {}) {
    requireRuntimeMemoryHistory();
    clearRuntimeMemoryLineAvatarHover();
    clampRuntimeMemoryHistoryIndex();
    ensureRuntimeMemoryDisplayModeAvailable();
    updateRuntimeMemoryTitleState();

    if (getRuntimeMemoryDisplayMode() === "active") {
      renderActiveMemoryRecords();
      return;
    }

    if (getRuntimeMemoryDisplayMode() === "delayed") {
      renderDelayedMemoryReports();
      return;
    }

    if (getRuntimeMemoryDisplayMode() === "facts") {
      renderFactsMemoryFields();
      return;
    }

    const sourceSnapshot =
        runtimeMemoryHistory.snapshots[
            runtimeMemoryHistory.index
            ];

    if (!sourceSnapshot) {
      if (runtimeMemoryText) {
        runtimeMemoryText.textContent = "";
      }

      if (runtimeMemoryPosition) {
        runtimeMemoryPosition.textContent =
            "0";
      }

      updateRuntimeMemoryTitleMetrics(null);
      updateRuntimeMemoryArrows();
      updateRuntimeMemoryPinGlow();
      updateRuntimeMemoryTitleState();
      dispatchRuntimeAvatarSnapshot(null);
      return;
    }

    const snapshot =
        getDisplayRuntimeMemorySnapshot(
            sourceSnapshot
        );

    const persistGlow =
        isCurrentRuntimeMemorySnapshotPinned();

    const flashMode =
        options && options.flashMode || "auto";

    const applyFlash =
        shouldApplyRuntimeMemoryFlash(
            sourceSnapshot,
            flashMode,
            persistGlow
        );

    renderRuntimeMemoryLines(
        snapshot,
        persistGlow,
        {
          applyFlash,
        }
    );

    if (runtimeMemoryPosition) {
      runtimeMemoryPosition.textContent =
          String(
              getRuntimeMemorySnapshotDisplayIndex(snapshot)
          );
    }

    updateRuntimeMemoryTitleMetrics(snapshot);
    updateRuntimeMemoryArrows();
    updateRuntimeMemoryPinGlow();
    updateRuntimeMemoryTitleState();
    dispatchRuntimeAvatarSnapshot(sourceSnapshot);
  }

  function isLatestRuntimeMemorySnapshot() {
    requireRuntimeMemoryHistory();

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

  function runtimeMemoryTraceFontWeight(line) {
    const strength =
        Number(line && line.strength);

    if (!Number.isFinite(strength)) {
      return 400;
    }

    const normalized =
        clampMemoryRatio(strength);
    const eased =
        Math.sqrt(
            Math.max(
                0,
                normalized - 0.5
            ) / 0.5
        );

    return Math.round(
        Math.max(
            400,
            Math.min(
                500,
                400 + eased * 100
            )
        )
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

  function runtimeMemoryLineHasFlashStatus(line) {
    if (!line || typeof line !== "object") {
      return false;
    }

    return [
      line.status,
      line.key_status,
      line.value_status,
    ].some((status) => (
      status === "new"
      || status === "changed"
    ));
  }

  function runtimeMemorySnapshotHasFlashStatus(snapshot) {
    return Boolean(
        snapshot
        && Array.isArray(snapshot.lines)
        && snapshot.lines.some(runtimeMemoryLineHasFlashStatus)
    );
  }

  function shouldApplyRuntimeMemoryFlash(
      sourceSnapshot,
      flashMode,
      persistGlow
  ) {
    if (persistGlow || flashMode === "replay") {
      return true;
    }

    if (
        !sourceSnapshot
        || typeof sourceSnapshot !== "object"
        || !runtimeMemorySnapshotHasFlashStatus(sourceSnapshot)
    ) {
      return true;
    }

    if (autoFlashedRuntimeMemorySnapshots.has(sourceSnapshot)) {
      return false;
    }

    autoFlashedRuntimeMemorySnapshots.add(sourceSnapshot);
    return true;
  }

  function normalizeRuntimeCitationIdentity(value) {
    const source = String(value || "");
    const normalized = source.normalize
      ? source.normalize("NFKC")
      : source;

    return normalized
      .toLowerCase()
      .replace(/\s+/g, " ")
      .trim();
  }

  function dispatchRuntimeMemoryLineAvatarHover(
      row,
      active
  ) {
    const lineKey =
        row
          ? normalizeRuntimeCitationIdentity(
              row.dataset.runtimeMemoryLineKey
            )
          : "";
    const lineText =
        row
          ? normalizeRuntimeCitationIdentity(
              row.dataset.runtimeMemoryLineText
            )
          : "";

    window.dispatchEvent(
      new CustomEvent(
        THINK_RUNTIME_CITATION_HOVER_EVENT,
        {
          detail: active && (lineKey || lineText)
            ? {
              active: true,
              sourceId: RUNTIME_MEMORY_LINE_HOVER_SOURCE_ID,
              lineKeys: lineKey ? [lineKey] : [],
              lineTexts: lineText ? [lineText] : [],
            }
            : {
              active: false,
              sourceId: RUNTIME_MEMORY_LINE_HOVER_SOURCE_ID,
              lineKeys: [],
              lineTexts: [],
            },
        }
      )
    );
  }

  function clearRuntimeMemoryLineAvatarHover() {
    dispatchRuntimeMemoryLineAvatarHover(
      null,
      false
    );
  }

  function renderRuntimeMemoryLines(
      snapshot,
      persistGlow = false,
      options = {}
  ) {
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
            .filter(line => !memoryModel.isUserIdleRuntimeMemoryLine(line))
          : snapshot.lines || [];

    if (!lines.length) {
      const rawMemory =
          showLiveUserIdle
            ? memoryModel.stripUserIdleRuntimeMemoryText(snapshot.raw_memory || "")
            : snapshot.raw_memory || "";

      runtimeMemoryText.textContent =
          `${memoryModel.stripMemoryTextMetaForDisplay(rawMemory).trim()}\n`;

      if (rawMemory.trim()) {
        runtimeMemoryText.title =
            formatRuntimeMemoryHoverTitle(rawMemory);
      }

      if (showLiveUserIdle) {
        appendUserIdleRuntimeMemoryLine();
      } else {
        userIdleValueNode = null;
      }

      idle.start();

      return;
    }

    appendRuntimeMemoryLineRows(
        lines,
        persistGlow,
        {
          applyFlash: options.applyFlash !== false,
          interactiveRuntimeMemory: showLiveUserIdle,
        }
    );

    if (showLiveUserIdle) {
      appendUserIdleRuntimeMemoryLine();
    } else {
      userIdleValueNode = null;
    }

    idle.start();
  }

  function appendRuntimeMemoryLineRows(
      lines,
      persistGlow = false,
      options = {}
  ) {
    lines.forEach((line, index) => {
      const row =
          document.createElement("div");

      row.className =
          "runtime-memory-line";

      row.dataset.runtimeMemoryLineIndex =
          String(index);
      row.dataset.runtimeMemoryLineKey =
          normalizeRuntimeCitationIdentity(
            line.key || "note"
          );
      row.dataset.runtimeMemoryLineText =
          normalizeRuntimeCitationIdentity(
            `${line.key || "note"}: ${line.value || ""}`
          );

      row.addEventListener(
        "mouseenter",
        () => {
          dispatchRuntimeMemoryLineAvatarHover(
            row,
            true
          );
        }
      );

      row.addEventListener(
        "mouseleave",
        () => {
          dispatchRuntimeMemoryLineAvatarHover(
            row,
            false
          );
        }
      );

      const key =
          line.key || "note";

      const valuePresentation =
          memoryModel.buildRuntimeMemoryValuePresentation(line);

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
          `${memoryModel.runtimeMemoryDisplay.convertKeyToName(key) || key}:`;

      const valueSpan =
          document.createElement("span");

      valueSpan.className =
          "runtime-memory-value";

      valueSpan.textContent =
          ` ${valuePresentation.text}`;
      valueSpan.style.fontWeight =
          String(
              runtimeMemoryTraceFontWeight(line)
          );

      const hoverTitle =
          formatRuntimeMemoryHoverTitle(fullRawLine);

      row.title =
          hoverTitle;
      valueSpan.title =
          hoverTitle;

      row.appendChild(keySpan);
      row.appendChild(valueSpan);

      if (options.interactiveActiveMemory) {
        configureActiveMemoryRow(
            row,
            index,
            line
        );
      } else if (options.interactiveFactsMemory) {
        configureFactsMemoryRow(
            row,
            line
        );
      } else if (options.interactiveRuntimeMemory) {
        configureRuntimeMemoryRow(
            row,
            index,
            line
        );
      }

      runtimeMemoryText.appendChild(row);

      if (options.applyFlash !== false) {
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
      }
    });

  }

  function getRuntimeMemoryLineStatus(line) {
    const parsed =
        memoryModel.splitMemoryMeta(
            line && line.value || ""
        );

    const statusTag =
        parsed.tags.find((tag) => (
          memoryModel.normalizeRuntimeMemoryKey(tag.key) === "status"
        ));

    return String(
        statusTag && statusTag.value || ""
    )
      .trim()
      .toLowerCase();
  }

  function updateActiveMemoryRecordStatus(index, status) {
    const records =
        getActiveMemoryRecordTexts();

    if (
        index < 0
        || index >= records.length
    ) {
      return false;
    }

    const nextRecords =
        records.map((record, recordIndex) => (
          recordIndex === index
            ? memoryModel.setRuntimeMemoryLineMetaValue(
                record,
                "status",
                status
            )
            : record
        ));

    setActiveMemoryRecordTexts(
        nextRecords
    );
    renderRuntimeMemorySnapshot();
    return true;
  }

  function deleteActiveMemoryRecord(index) {
    const records =
        getActiveMemoryRecordTexts();

    if (
        index < 0
        || index >= records.length
    ) {
      return false;
    }

    setActiveMemoryRecordTexts(
        records.filter((_, recordIndex) => (
          recordIndex !== index
        ))
    );
    renderRuntimeMemorySnapshot();
    return true;
  }

  function setMemoryRowPressVisual(row, active, durationMs, opacity) {
    if (!row) {
      return;
    }

    row.style.transitionProperty =
        "opacity";
    row.style.transitionTimingFunction =
        active
          ? "linear"
          : "ease";
    row.style.transitionDuration =
        active
          ? `${durationMs}ms`
          : "160ms";
    row.style.opacity =
        active
          ? String(opacity)
          : "";
  }

  function setActiveMemoryRowPressVisual(row, active) {
    setMemoryRowPressVisual(
        row,
        active,
        MEMORY_DELETE_HOLD_MS,
        0
    );
  }

  function setRuntimeMemoryRowPressVisual(row, active) {
    setMemoryRowPressVisual(
        row,
        active,
        MEMORY_DELETE_HOLD_MS,
        0
    );
  }

  function configureActiveMemoryRow(
      row,
      index,
      line
  ) {
    if (!row) {
      return;
    }

    row.classList.add(
        "runtime-memory-active-row"
    );

    const status =
        getRuntimeMemoryLineStatus(
            line
        );

    row.dataset.activeMemoryStatus =
        status || "pending";

    let pauseTimer = null;
    let deleteTimer = null;
    let pauseReached = false;
    let deleteCompleted = false;
    let pointerDown = false;
    let pointerId = null;
    let startedPaused = false;

    function clearHoldTimers() {
      if (pauseTimer) {
        clearTimeout(
            pauseTimer
        );
        pauseTimer = null;
      }

      if (deleteTimer) {
        clearTimeout(
            deleteTimer
        );
        deleteTimer = null;
      }
    }

    function cancelPendingHold() {
      clearHoldTimers();
      pointerDown = false;

      if (!deleteCompleted) {
        setActiveMemoryRowPressVisual(
            row,
            false
        );
      }

      pauseReached = false;
      deleteCompleted = false;
      startedPaused = false;
      pointerId = null;
    }

    row.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) {
        return;
      }

      pointerDown = true;
      pauseReached = false;
      deleteCompleted = false;
      pointerId = event.pointerId;
      startedPaused = (
        row.dataset.activeMemoryStatus === "paused"
      );

      setActiveMemoryRowPressVisual(
          row,
          true
      );

      clearHoldTimers();
      pauseTimer = setTimeout(() => {
        if (!pointerDown) {
          return;
        }

        pauseReached = true;
      }, ACTIVE_MEMORY_PAUSE_HOLD_MS);

      deleteTimer = setTimeout(() => {
        if (!pointerDown) {
          return;
        }

        deleteCompleted = true;
        pointerDown = false;
        deleteActiveMemoryRecord(
            index
        );
      }, MEMORY_DELETE_HOLD_MS);
    });

    row.addEventListener("pointerup", (event) => {
      if (!pointerDown) {
        return;
      }

      if (
          pointerId !== null
          && event.pointerId !== pointerId
      ) {
        return;
      }

      if (deleteCompleted) {
        cancelPendingHold();
        return;
      }

      if (startedPaused) {
        updateActiveMemoryRecordStatus(
            index,
            "pending"
        );
        cancelPendingHold();
        return;
      }

      if (pauseReached) {
        updateActiveMemoryRecordStatus(
            index,
            "paused"
        );
        cancelPendingHold();
        return;
      }

      cancelPendingHold();
    });

    row.addEventListener(
        "pointercancel",
        cancelPendingHold
    );
    row.addEventListener(
        "pointerleave",
        cancelPendingHold
    );
  }

  function configureRuntimeMemoryRow(
      row,
      index,
      line
  ) {
    if (
        !row
        || !line
        || memoryModel.isUserIdleRuntimeMemoryLine(line)
        || memoryModel.isActiveMemoryRuntimeMemoryLine(line)
    ) {
      return;
    }

    row.classList.add(
        "runtime-memory-removable-row"
    );

    let deleteTimer = null;
    let deleteCompleted = false;
    let pointerDown = false;
    let pointerId = null;

    function clearDeleteTimer() {
      if (!deleteTimer) {
        return;
      }

      clearTimeout(
          deleteTimer
      );
      deleteTimer = null;
    }

    function cancelPendingDelete() {
      clearDeleteTimer();
      pointerDown = false;

      if (!deleteCompleted) {
        setRuntimeMemoryRowPressVisual(
            row,
            false
        );
      }

      deleteCompleted = false;
      pointerId = null;
    }

    row.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) {
        return;
      }

      pointerDown = true;
      deleteCompleted = false;
      pointerId = event.pointerId;

      setRuntimeMemoryRowPressVisual(
          row,
          true
      );

      clearDeleteTimer();
      deleteTimer = setTimeout(() => {
        if (!pointerDown) {
          return;
        }

        deleteCompleted = true;
        pointerDown = false;

        if (typeof deleteRuntimeMemoryLine === "function") {
          deleteRuntimeMemoryLine(
              index,
              line
          );
        }
      }, MEMORY_DELETE_HOLD_MS);
    });

    row.addEventListener("pointerup", (event) => {
      if (!pointerDown) {
        return;
      }

      if (
          pointerId !== null
          && event.pointerId !== pointerId
      ) {
        return;
      }

      cancelPendingDelete();
    });

    row.addEventListener(
        "pointercancel",
        cancelPendingDelete
    );
    row.addEventListener(
        "pointerleave",
        cancelPendingDelete
    );
  }

  function configureFactsMemoryRow(
      row,
      line
  ) {
    if (
        !row
        || !line
        || !line.key
    ) {
      return;
    }

    row.classList.add(
        "runtime-memory-removable-row"
    );

    let deleteTimer = null;
    let deleteCompleted = false;
    let pointerDown = false;
    let pointerId = null;

    function clearDeleteTimer() {
      if (!deleteTimer) {
        return;
      }

      clearTimeout(
          deleteTimer
      );
      deleteTimer = null;
    }

    function cancelPendingDelete() {
      clearDeleteTimer();
      pointerDown = false;

      if (!deleteCompleted) {
        setRuntimeMemoryRowPressVisual(
            row,
            false
        );
      }

      deleteCompleted = false;
      pointerId = null;
    }

    row.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) {
        return;
      }

      pointerDown = true;
      deleteCompleted = false;
      pointerId = event.pointerId;

      setRuntimeMemoryRowPressVisual(
          row,
          true
      );

      clearDeleteTimer();
      deleteTimer = setTimeout(() => {
        if (!pointerDown) {
          return;
        }

        deleteCompleted = true;
        pointerDown = false;

        if (typeof deleteFactsMemoryField === "function") {
          deleteFactsMemoryField(
              line.key
          );
        }
      }, MEMORY_DELETE_HOLD_MS);
    });

    row.addEventListener("pointerup", (event) => {
      if (!pointerDown) {
        return;
      }

      if (
          pointerId !== null
          && event.pointerId !== pointerId
      ) {
        return;
      }

      cancelPendingDelete();
    });

    row.addEventListener(
        "pointercancel",
        cancelPendingDelete
    );

    row.addEventListener(
        "pointerleave",
        cancelPendingDelete
    );
  }


  function renderDelayedMemoryReports() {
    const reports =
        getDelayedMemoryReportRecords();


    if (runtimeMemoryText) {
      runtimeMemoryText.innerHTML = "";
      runtimeMemoryText.classList.remove(
          "runtime-memory-text-pinned"
      );
      runtimeMemoryText.removeAttribute(
          "title"
      );

      reports.forEach((report) => {
        const title =
            String(report.title || "").trim();

        const summary =
            String(report.summary || "").trim();

        const row =
            document.createElement("div");

        row.className =
            "runtime-memory-line runtime-memory-delayed-row";

        row.setAttribute(
            "role",
            "button"
        );

        row.setAttribute(
            "tabindex",
            "0"
        );

        const keySpan =
            document.createElement("span");

        keySpan.className =
            "runtime-memory-key";

        keySpan.textContent =
            `${title}:`;

        const valueSpan =
            document.createElement("span");

        valueSpan.className =
            "runtime-memory-value";

        valueSpan.textContent =
            ` ${summary}`;

        row.title =
            `${title}: ${summary}`.trim();
        valueSpan.title =
            row.title;

        row.appendChild(
            keySpan
        );
        row.appendChild(
            valueSpan
        );

        row.addEventListener("click", () => {
          openDelayedMemoryReportModal(
              report
          );
        });

        row.addEventListener("keydown", (event) => {
          if (
              event.key !== "Enter"
              && event.key !== " "
          ) {
            return;
          }

          event.preventDefault();
          openDelayedMemoryReportModal(
              report
          );
        });

        runtimeMemoryText.appendChild(
            row
        );
      });
    }

    if (runtimeMemoryPosition) {
      runtimeMemoryPosition.textContent =
          String(reports.length);
    }

    userIdleValueNode = null;
    idle.stop();
    updateRuntimeMemoryTitleMetrics(null);
    updateRuntimeMemoryArrows();
    updateRuntimeMemoryPinGlow();
    updateRuntimeMemoryTitleState();
  }

  function normalizeDelayedMemoryDisplayText(value) {
    return String(value || "")
        .replace(/\r\n/g, "\n")
        .replace(/\\r\\n/g, "\n")
        .replace(/\\n/g, "\n")
        .replace(/\\t/g, "  ")
        .trim();
  }

  function padDelayedMemoryDatePart(value) {
    return String(value).padStart(
        2,
        "0"
    );
  }

  function formatDelayedMemoryTime(value) {
    const raw =
        normalizeDelayedMemoryDisplayText(value);

    if (!raw) {
      return "";
    }

    const date =
        new Date(raw);

    if (Number.isNaN(date.getTime())) {
      return raw;
    }

    const year =
        date.getFullYear();

    const month =
        padDelayedMemoryDatePart(
            date.getMonth() + 1
        );

    const day =
        padDelayedMemoryDatePart(
            date.getDate()
        );

    const hours =
        padDelayedMemoryDatePart(
            date.getHours()
        );

    const minutes =
        padDelayedMemoryDatePart(
            date.getMinutes()
        );

    const weekday =
        new Intl.DateTimeFormat(
            "en-US",
            {
              weekday: "long",
            }
        ).format(date);

    return `${year}-${month}-${day} ${hours}:${minutes}, ${weekday}`;
  }

  function closeDelayedMemoryReportModal() {
    if (!delayedMemoryModal) {
      return;
    }

    delayedMemoryModal.classList.add(
        "hidden"
    );

    delayedMemoryModal.classList.remove(
        "flex"
    );
  }

  function ensureDelayedMemoryModal() {
    if (delayedMemoryModal) {
      return;
    }

    delayedMemoryModal =
        document.createElement("div");

    delayedMemoryModal.className =
        "fixed inset-0 z-50 hidden items-center justify-center bg-black/70 p-4";

    delayedMemoryModalPanel =
        document.createElement("div");

    delayedMemoryModalPanel.className =
        "delayed-memory-modal-panel w-full max-w-4xl max-h-[86vh] rounded border border-zinc-700 bg-zinc-950 shadow-2xl flex flex-col";

    const header =
        document.createElement("div");

    header.className =
        "h-11 shrink-0 border-b border-zinc-800 px-4 flex items-center justify-between gap-4";

    delayedMemoryModalTitle =
        document.createElement("div");

    delayedMemoryModalTitle.className =
        "min-w-0 truncate text-xs uppercase tracking-widest text-zinc-300";

    const closeButton =
        document.createElement("button");

    closeButton.type =
        "button";

    closeButton.className =
        "text-xs text-zinc-400 hover:text-zinc-100 transition";

    closeButton.textContent =
        "close";

    delayedMemoryModalContent =
        document.createElement("div");

    delayedMemoryModalContent.className =
        "delayed-memory-modal-content min-h-0 flex-1 overflow-auto p-4 text-[12px] leading-relaxed text-zinc-200";

    header.appendChild(
        delayedMemoryModalTitle
    );

    header.appendChild(
        closeButton
    );

    delayedMemoryModalPanel.appendChild(
        header
    );

    delayedMemoryModalPanel.appendChild(
        delayedMemoryModalContent
    );

    delayedMemoryModal.appendChild(
        delayedMemoryModalPanel
    );

    document.body.appendChild(
        delayedMemoryModal
    );

    closeButton.addEventListener(
        "click",
        closeDelayedMemoryReportModal
    );

    delayedMemoryModal.addEventListener("click", (event) => {
      if (event.target === delayedMemoryModal) {
        closeDelayedMemoryReportModal();
      }
    });

    document.addEventListener("keydown", (event) => {
      if (
          event.key === "Escape"
          && delayedMemoryModal
          && !delayedMemoryModal.classList.contains("hidden")
      ) {
        closeDelayedMemoryReportModal();
      }
    });
  }

  function appendDelayedMemoryModalField(parent, label, value) {
    const normalizedValue =
        Array.isArray(value)
          ? value
              .map((item) => normalizeDelayedMemoryDisplayText(item))
              .filter(Boolean)
              .join(", ")
          : normalizeDelayedMemoryDisplayText(value);

    if (!normalizedValue) {
      return;
    }

    const row =
        document.createElement("div");

    row.className =
        "delayed-memory-modal-field";

    const key =
        document.createElement("div");

    key.className =
        "delayed-memory-modal-label";

    key.textContent =
        label;

    const text =
        document.createElement("div");

    text.className =
        "delayed-memory-modal-value";

    text.textContent =
        normalizedValue;

    row.appendChild(
        key
    );

    row.appendChild(
        text
    );

    parent.appendChild(
        row
    );
  }

  function appendDelayedMemoryModalBody(parent, body) {
    const normalizedBody =
        normalizeDelayedMemoryDisplayText(body);

    if (!normalizedBody) {
      return;
    }

    const section =
        document.createElement("section");

    section.className =
        "delayed-memory-modal-section";

    const heading =
        document.createElement("div");

    heading.className =
        "delayed-memory-modal-section-title";

    heading.textContent =
        "Body";

    const pre =
        document.createElement("pre");

    pre.className =
        "delayed-memory-modal-body";

    pre.textContent =
        normalizedBody;

    section.appendChild(
        heading
    );

    section.appendChild(
        pre
    );

    parent.appendChild(
        section
    );
  }

  function appendDelayedMemoryModalExtraFields(parent, report) {
    const shownKeys =
        new Set([
          "_storage_key",
          "title",
          "summary",
          "created_time",
          "created_session_id",
          "tags",
          "body",
        ]);

    Object.entries(report || {}).forEach(([key, value]) => {
      if (
          shownKeys.has(key)
          || value === null
          || typeof value === "undefined"
      ) {
        return;
      }

      const normalizedValue =
          typeof value === "object"
            ? JSON.stringify(
                value,
                null,
                2
              )
            : value;

      appendDelayedMemoryModalField(
          parent,
          key,
          normalizedValue
      );
    });
  }

  function openDelayedMemoryReportModal(report) {
    ensureDelayedMemoryModal();

    delayedMemoryModalTitle.textContent =
        normalizeDelayedMemoryDisplayText(report.title)
        || "Delayed memory";

    delayedMemoryModalContent.innerHTML = "";

    const fields =
        document.createElement("section");

    fields.className =
        "delayed-memory-modal-fields";

    appendDelayedMemoryModalField(
        fields,
        "Title",
        report.title
    );

    appendDelayedMemoryModalField(
        fields,
        "Summary",
        report.summary
    );

    appendDelayedMemoryModalField(
        fields,
        "Time",
        formatDelayedMemoryTime(
            report.created_time
        )
    );

    appendDelayedMemoryModalField(
        fields,
        "Tags",
        report.tags
    );

    appendDelayedMemoryModalField(
        fields,
        "ID",
        report._storage_key
    );

    appendDelayedMemoryModalField(
        fields,
        "Session",
        report.created_session_id
    );

    appendDelayedMemoryModalExtraFields(
        fields,
        report
    );

    delayedMemoryModalContent.appendChild(
        fields
    );

    appendDelayedMemoryModalBody(
        delayedMemoryModalContent,
        report.body
    );

    delayedMemoryModal.classList.remove(
        "hidden"
    );

    delayedMemoryModal.classList.add(
        "flex"
    );
  }

  function formatFactsMemoryTrace(value) {
    const trace =
        Number(value);

    return Number.isFinite(trace)
      ? trace.toFixed(2)
      : "0.50";
  }


  function buildFactsMemoryLine(record) {
    const content =
        String(record.content || "").trim();

    return {
      key: String(record.key || "").trim(),
      value: memoryModel.appendProperties(
          content,
          [
            `max_trace: ${formatFactsMemoryTrace(record.max_trace)}`,
            `diffs: ${Math.max(0, Math.trunc(Number(record.diffs || 0)))}`,
            `first_seen_turn: ${Math.max(0, Math.trunc(Number(record.first_seen_turn || 0)))}`,
            `last_seen_turn: ${Math.max(0, Math.trunc(Number(record.last_seen_turn || 0)))}`,
            `runtime_snapshot_id: ${String(record.runtime_snapshot_id || "").trim()}`,
          ]
      ),
      status: "same",
      key_status: "same",
      value_status: "same",
      key_change_ratio: 0,
      value_change_ratio: 0,
    };
  }


  function renderFactsMemoryFields() {
    const records =
        getFactsMemoryFieldRecords();

    const lines =
        records.map(
          buildFactsMemoryLine
        );

    if (runtimeMemoryText) {
      runtimeMemoryText.innerHTML = "";
      runtimeMemoryText.classList.remove(
          "runtime-memory-text-pinned"
      );
      runtimeMemoryText.removeAttribute(
          "title"
      );

      appendRuntimeMemoryLineRows(
          lines,
          false,
          {
            applyFlash: false,
            interactiveFactsMemory: true,
          }
      );
    }

    if (runtimeMemoryPosition) {
      runtimeMemoryPosition.textContent =
          String(records.length);
    }

    userIdleValueNode = null;
    idle.stop();

    updateRuntimeMemoryTitleMetricsFromText(
        lines
          .map(line => `${line.key}: ${line.value}`)
          .join("\n")
    );

    updateRuntimeMemoryArrows();
    updateRuntimeMemoryPinGlow();
    updateRuntimeMemoryTitleState();
  }


  function renderActiveMemoryRecords() {
    const records =
        getActiveMemoryRecordTexts();

    if (runtimeMemoryText) {
      runtimeMemoryText.innerHTML = "";
      runtimeMemoryText.classList.remove(
          "runtime-memory-text-pinned"
      );
      runtimeMemoryText.removeAttribute(
          "title"
      );

      appendRuntimeMemoryLineRows(
          records.map(memoryModel.parseRuntimeMemoryLine),
          false,
          {
            interactiveActiveMemory: true,
          }
      );
    }

    if (runtimeMemoryPosition) {
      runtimeMemoryPosition.textContent =
          String(records.length);
    }

    userIdleValueNode = null;
    idle.stop();

    updateRuntimeMemoryTitleMetricsFromText(
        records.join("\n")
    );
    updateRuntimeMemoryArrows();
    updateRuntimeMemoryPinGlow();
    updateRuntimeMemoryTitleState();
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
        `${memoryModel.runtimeMemoryDisplay.convertKeyToName("user_idle")}:`;

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
    requireRuntimeMemoryHistory();

    if (!runtimeMemoryPrev || !runtimeMemoryNext) {
      return;
    }

    if (getRuntimeMemoryDisplayMode() !== "runtime") {
      runtimeMemoryPrev.disabled = true;
      runtimeMemoryNext.disabled = true;

      runtimeMemoryPrev.classList.add(
          "opacity-30",
          "cursor-default",
          "text-slate-600"
      );
      runtimeMemoryNext.classList.add(
          "opacity-30",
          "cursor-default",
          "text-slate-600"
      );

      runtimeMemoryPrev.classList.remove("text-emerald-300");
      runtimeMemoryNext.classList.remove("text-emerald-300");
      return;
    }

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

  function toggleRuntimeMemoryDisplayMode() {
    const modes =
        getAvailableRuntimeMemoryDisplayModes();

    if (modes.length <= 1) {
      return;
    }

    const currentMode =
        getRuntimeMemoryDisplayMode();

    const currentIndex =
        modes.indexOf(currentMode);

    setRuntimeMemoryDisplayMode(
        modes[
            (currentIndex + 1) % modes.length
        ]
    );

    renderRuntimeMemorySnapshot();
  }

  function bindRuntimeMemoryNavigation() {
    if (initialized) {
      return;
    }

    runtimeMemoryPrev?.addEventListener("click", () => {
      requireRuntimeMemoryHistory();

      if (runtimeMemoryHistory.index <= 0) return;

      runtimeMemoryHistory.index -= 1;
      renderRuntimeMemorySnapshot({
        flashMode: "replay",
      });
    });

    runtimeMemoryNext?.addEventListener("click", () => {
      requireRuntimeMemoryHistory();

      if (
          runtimeMemoryHistory.index >=
          runtimeMemoryHistory.snapshots.length - 1
      ) return;

      runtimeMemoryHistory.index += 1;
      renderRuntimeMemorySnapshot({
        flashMode: "replay",
      });
    });

    runtimeMemoryPosition?.addEventListener("click", () => {
      requireRuntimeMemoryHistory();

      if (getRuntimeMemoryDisplayMode() !== "runtime") {
        return;
      }

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

      renderRuntimeMemorySnapshot({
        flashMode: "replay",
      });

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

    runtimeMemoryTitle?.addEventListener("click", () => {
      toggleRuntimeMemoryDisplayMode();
    });

    runtimeMemoryTitle?.addEventListener("keydown", (event) => {
      if (
          event.key !== "Enter"
          && event.key !== " "
      ) {
        return;
      }

      event.preventDefault();
      toggleRuntimeMemoryDisplayMode();
    });

    runtimeDiffToggle?.addEventListener("click", () => {
      runtimeDiffHistory.expanded =
          !runtimeDiffHistory.expanded;

      renderRuntimeDiffs();
    });

    initialized = true;
  }

  function init(options = {}) {
    runtimeMemoryHistory = options.history;
    idle = options.idle;
    memoryModel = options.memoryModel;
    buildDisplaySnapshot = options.buildDisplaySnapshot || null;
    getActiveMemoryRecords = options.getActiveMemoryRecords || null;
    setActiveMemoryRecords = options.setActiveMemoryRecords || null;
    deleteRuntimeMemoryLine = options.deleteRuntimeMemoryLine || null;
    getDelayedMemoryReports = options.getDelayedMemoryReports || null;
    getFactsMemoryFields = options.getFactsMemoryFields || null;
    deleteFactsMemoryField = options.deleteFactsMemoryField || null;
    getDisplayMode = options.getDisplayMode || null;
    setDisplayMode = options.setDisplayMode || null;

    if (!runtimeMemoryHistory) {
      throw new Error(
        "JinRuntime.memoryView.init() requires history"
      );
    }

    if (!idle) {
      throw new Error(
        "JinRuntime.memoryView.init() requires idle"
      );
    }

    if (!memoryModel) {
      throw new Error(
        "JinRuntime.memoryView.init() requires memoryModel"
      );
    }

    idle.configure({
      onIdleTextChanged(text) {
        updateUserIdleTimerText(
          text
        );
      },
    });

    bindRuntimeMemoryNavigation();
    renderRuntimeMemorySnapshot();
    renderRuntimeDiffs();
  }

  window.JinRuntime.memoryView = {
    init,
    openDelayedMemoryReportModal,
    render: renderRuntimeMemorySnapshot,
    renderRuntimeMemorySnapshot,
    renderDiffs: renderRuntimeDiffs,
    setRuntimeDiffUpdate,
    updateUserIdleTimerText,
    freezeLatestRuntimeMemoryUserIdle,
    showLatestRuntimeMemorySnapshot,
    isLatestRuntimeMemorySnapshot,
    updateTitleMetrics: updateRuntimeMemoryTitleMetrics,
  };
})();
