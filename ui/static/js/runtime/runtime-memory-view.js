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
  let getDisplayMode = null;
  let setDisplayMode = null;

  const ACTIVE_MEMORY_PAUSE_HOLD_MS = 500;

  const pinnedRuntimeMemorySnapshotIndexes = new Set();

  const autoFlashedRuntimeMemorySnapshots = new WeakSet();

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

  function getActiveMemoryRecordTexts() {
    return typeof getActiveMemoryRecords === "function"
      ? getActiveMemoryRecords()
      : [];
  }

  function setActiveMemoryRecordTexts(records) {
    if (typeof setActiveMemoryRecords === "function") {
      setActiveMemoryRecords(
          records
      );
    }
  }

  function updateRuntimeMemoryTitleState() {
    if (!runtimeMemoryTitle) {
      return;
    }

    const hasActiveMemory =
        getActiveMemoryRecordTexts().length > 0;

    const isActiveMode =
        getRuntimeMemoryDisplayMode() === "active";

    runtimeMemoryTitle.textContent =
        isActiveMode
          ? "[ active memory ]"
          : "[ runtime memory ]";

    runtimeMemoryTitle.classList.toggle(
        "runtime-memory-title-clickable",
        hasActiveMemory
    );

    if (hasActiveMemory) {
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

    if (getRuntimeMemoryDisplayMode() === "active") {
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

  function renderRuntimeMemorySnapshot(options = {}) {
    requireRuntimeMemoryHistory();
    clampRuntimeMemoryHistoryIndex();
    updateRuntimeMemoryTitleState();

    if (getRuntimeMemoryDisplayMode() === "active") {
      renderActiveMemoryRecords();
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
              typeof snapshot.index === "number"
                ? snapshot.index
                : runtimeMemoryHistory.index + 1
          );
    }

    updateRuntimeMemoryTitleMetrics(snapshot);
    updateRuntimeMemoryArrows();
    updateRuntimeMemoryPinGlow();
    updateRuntimeMemoryTitleState();
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
      return;
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
  }

  function setActiveMemoryRowPressVisual(row, active) {
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
          ? `${ACTIVE_MEMORY_PAUSE_HOLD_MS}ms`
          : "160ms";
    row.style.opacity =
        active
          ? "0.5"
          : "";
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

    let holdTimer = null;
    let holdCompleted = false;
    let pointerDown = false;
    let pointerId = null;

    function clearHoldTimer() {
      if (!holdTimer) {
        return;
      }

      clearTimeout(
          holdTimer
      );
      holdTimer = null;
    }

    function cancelPendingHold() {
      clearHoldTimer();
      pointerDown = false;

      if (!holdCompleted) {
        setActiveMemoryRowPressVisual(
            row,
            false
        );
      }

      holdCompleted = false;
      pointerId = null;
    }

    row.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) {
        return;
      }

      pointerDown = true;
      holdCompleted = false;
      pointerId = event.pointerId;

      if (
          row.dataset.activeMemoryStatus
          === "paused"
      ) {
        return;
      }

      setActiveMemoryRowPressVisual(
          row,
          true
      );

      clearHoldTimer();
      holdTimer = setTimeout(() => {
        if (!pointerDown) {
          return;
        }

        holdCompleted = true;
        updateActiveMemoryRecordStatus(
            index,
            "paused"
        );
      }, ACTIVE_MEMORY_PAUSE_HOLD_MS);
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

      if (
          row.dataset.activeMemoryStatus
          === "paused"
      ) {
        updateActiveMemoryRecordStatus(
            index,
            "pending"
        );
        cancelPendingHold();
        return;
      }

      if (!holdCompleted) {
        cancelPendingHold();
        return;
      }

      pointerDown = false;
      pointerId = null;
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

  function renderActiveMemoryRecords() {
    const records =
        getActiveMemoryRecordTexts();

    if (!records.length) {
      setRuntimeMemoryDisplayMode(
          "runtime"
      );
      renderRuntimeMemorySnapshot();
      return;
    }

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

    if (getRuntimeMemoryDisplayMode() === "active") {
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
    if (!getActiveMemoryRecordTexts().length) {
      return;
    }

    setRuntimeMemoryDisplayMode(
        getRuntimeMemoryDisplayMode() === "active"
          ? "runtime"
          : "active"
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

      if (getRuntimeMemoryDisplayMode() === "active") {
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
