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
  let setDelayedMemoryReportPinned = null;
  let setDelayedMemoryReportAnchorFactIds = null;
  let getFactsMemoryFields = null;
  let deleteFactsMemoryField = null;
  let getLongTermMemoryFacts = null;
  let deleteLongTermMemoryFact = null;
  let getDisplayMode = null;
  let setDisplayMode = null;

  const ACTIVE_MEMORY_PAUSE_HOLD_MS = 500;
  const MEMORY_DELETE_HOLD_MS = 1500;
  const THINK_RUNTIME_CITATION_HIGHLIGHT_EVENT = "jin:think-runtime-citation-highlight";
  const MEMORY_ROW_AVATAR_HOVER_EVENT = "jin:memory-row-avatar-hover";
  const DELAYED_MEMORY_REPORT_ACTIVE_EVENT =
      "jin:delayed-memory-report-active";
  const normalizeRuntimeCitationIdentity =
      window.JinRuntime.normalizeCitationIdentity;
  const buildCitationRecordIdentity =
      typeof window.JinRuntime.buildCitationRecordIdentity === "function"
        ? window.JinRuntime.buildCitationRecordIdentity
        : () => "";
  const buildAvatarMemoryHoverId =
      typeof window.JinRuntime.buildAvatarMemoryHoverId === "function"
        ? window.JinRuntime.buildAvatarMemoryHoverId
        : () => "";
  const MEMORY_REFERENCE_HIGHLIGHT_EVENT =
      "jin:memory-reference-highlight";
  const MEMORY_REFERENCE_ALIAS_DATASET_KEY =
      "memoryReferenceAliases";
  const memoryReferenceHighlightState = {
    persistentText: "",
  };
  const activeThinkMemoryCitationSources = new Map();
  let memoryReferenceEventsBound = false;


  const pinnedRuntimeMemorySnapshotIndexes = new Set();

  const autoFlashedRuntimeMemorySnapshots = new WeakSet();


  let delayedMemoryModal = null;
  let delayedMemoryModalPanel = null;
  let delayedMemoryModalTitle = null;
  let delayedMemoryModalContent = null;
  let delayedMemoryModalPinButton = null;
  let delayedMemoryModalReport = null;
  let activeDelayedMemoryReportId = "";

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

  function normalizeMemoryReferenceSearchText(value) {
    const raw = String(value || "");

    try {
      return raw
        .normalize("NFKC")
        .toLocaleLowerCase();
    } catch (error) {
      return raw.toLocaleLowerCase();
    }
  }

  function isMemoryReferenceTokenCharacter(character) {
    const value = String(character || "");

    if (!value) {
      return false;
    }

    return (
      /[0-9_.-]/.test(value)
      || value.toLocaleLowerCase()
        !== value.toLocaleUpperCase()
    );
  }

  function containsMemoryReference(text, reference) {
    const haystack =
        normalizeMemoryReferenceSearchText(text);
    const needle =
        normalizeMemoryReferenceSearchText(reference).trim();

    if (!haystack || !needle) {
      return false;
    }

    let index = haystack.indexOf(needle);

    while (index >= 0) {
      const before =
          index > 0
            ? haystack[index - 1]
            : "";
      const afterIndex =
          index + needle.length;
      const after =
          afterIndex < haystack.length
            ? haystack[afterIndex]
            : "";

      if (
          !isMemoryReferenceTokenCharacter(before)
          && !isMemoryReferenceTokenCharacter(after)
      ) {
        return true;
      }

      index = haystack.indexOf(
          needle,
          index + 1
      );
    }

    return false;
  }

  function normalizeMemoryReferenceAliases(aliases) {
    const seen = new Set();

    return (Array.isArray(aliases) ? aliases : [])
      .map(alias => String(alias || "").trim())
      .filter((alias) => {
        if (!alias) {
          return false;
        }

        const identity =
            normalizeMemoryReferenceSearchText(alias);

        if (!identity || seen.has(identity)) {
          return false;
        }

        seen.add(identity);
        return true;
      });
  }

  function collectMemoryMetadataReferenceAliases(value) {
    const aliases = [];
    const text = String(value || "");
    const pattern =
        /\[\s*([a-z0-9_.-]*id)\s*:\s*([^\]]+?)\s*\]/gi;
    let match = null;

    while ((match = pattern.exec(text)) !== null) {
      const field =
          String(match[1] || "")
            .trim()
            .toLocaleLowerCase();

      if (
          field !== "id"
          && !field.endsWith("_id")
      ) {
        continue;
      }

      String(match[2] || "")
        .split(/\s*,\s*/)
        .map(item => item.trim())
        .filter(Boolean)
        .forEach(item => aliases.push(item));
    }

    return aliases;
  }

  function extractActiveMemoryId(value) {
    const match =
        String(value || "")
          .match(
            /\[\s*active_memory_id\s*:\s*([a-z0-9]{6})\s*\]/i
          );

    return match
      ? String(match[1] || "").trim().toLowerCase()
      : "";
  }

  function collectMemoryRecordReferenceAliases(record) {
    if (!record || typeof record !== "object") {
      return [];
    }

    const key =
      String(record.key || "").trim();
    const displayKey =
      key
      && memoryModel
      && memoryModel.runtimeMemoryDisplay
      && typeof memoryModel.runtimeMemoryDisplay.convertKeyToName === "function"
        ? memoryModel.runtimeMemoryDisplay.convertKeyToName(key)
        : "";

    return normalizeMemoryReferenceAliases([
      key,
      displayKey,
      record.title,
      record.name,
      record.id,
      record._storage_key,
      record.active_memory_id,
      ...collectMemoryMetadataReferenceAliases(
        record.value
      ),
    ]);
  }

  window.JinRuntime.memoryReferences = Object.freeze({
    contains: containsMemoryReference,
    normalizeAliases: normalizeMemoryReferenceAliases,
    collectMetadataAliases: collectMemoryMetadataReferenceAliases,
  });

  function setMemoryReferenceAliases(row, aliases) {
    if (!row) {
      return;
    }

    const normalizedAliases =
        normalizeMemoryReferenceAliases(aliases);

    if (!normalizedAliases.length) {
      delete row.dataset[
        MEMORY_REFERENCE_ALIAS_DATASET_KEY
      ];
      return;
    }

    row.dataset[
      MEMORY_REFERENCE_ALIAS_DATASET_KEY
    ] = JSON.stringify(normalizedAliases);
  }

  function getMemoryReferenceAliases(row) {
    if (!row || !row.dataset) {
      return [];
    }

    const raw = row.dataset[
      MEMORY_REFERENCE_ALIAS_DATASET_KEY
    ];

    if (!raw) {
      return [];
    }

    try {
      return normalizeMemoryReferenceAliases(
        JSON.parse(raw)
      );
    } catch (error) {
      return [];
    }
  }

  function getActiveMemoryReferenceText() {
    return memoryReferenceHighlightState.persistentText || "";
  }

  function buildMemoryReferenceAliasUsage(rows) {
    const usage = new Map();

    rows.forEach((row) => {
      getMemoryReferenceAliases(row).forEach((alias) => {
        const identity =
            normalizeMemoryReferenceSearchText(alias).trim();

        if (!identity) {
          return;
        }

        usage.set(
          identity,
          Number(usage.get(identity) || 0) + 1
        );
      });
    });

    return usage;
  }

  function applyMemoryReferenceHighlights() {
    if (!runtimeMemoryText) {
      return;
    }

    const sourceText =
        getActiveMemoryReferenceText();
    const rows = Array.from(
      runtimeMemoryText.querySelectorAll(
        `[data-memory-reference-aliases]`
      )
    );
    const aliasUsage =
        buildMemoryReferenceAliasUsage(rows);

    rows.forEach((row) => {
        const matched = Boolean(
          sourceText
          && getMemoryReferenceAliases(row)
            .some(alias => (
              Number(
                aliasUsage.get(
                  normalizeMemoryReferenceSearchText(alias).trim()
                ) || 0
              ) === 1
              &&
              containsMemoryReference(
                sourceText,
                alias
              )
            ))
        );

        row.classList.toggle(
          "runtime-memory-reference-hit",
          matched
        );
      });

    applyThinkMemoryCitationHighlights();
  }

  function sortHighlightedMemoryRows() {
    if (!runtimeMemoryText) {
      return;
    }

    const rows = Array.from(
      runtimeMemoryText.querySelectorAll(
        ".runtime-memory-line:not(.runtime-memory-user-idle)"
      )
    );

    if (rows.length < 2) {
      return;
    }

    rows.forEach((row, index) => {
      if (row.dataset.memoryHighlightSortIndex === undefined) {
        row.dataset.memoryHighlightSortIndex = String(index);
      }
    });

    const sortedRows = rows
      .slice()
      .sort((left, right) => {
        const leftHighlighted =
          left.classList.contains("runtime-memory-reference-hit")
          || left.classList.contains("runtime-memory-citation-hit");
        const rightHighlighted =
          right.classList.contains("runtime-memory-reference-hit")
          || right.classList.contains("runtime-memory-citation-hit");

        if (leftHighlighted !== rightHighlighted) {
          return leftHighlighted ? -1 : 1;
        }

        return (
          Number(left.dataset.memoryHighlightSortIndex || 0)
          - Number(right.dataset.memoryHighlightSortIndex || 0)
        );
      });

    const orderChanged = sortedRows.some(
      (row, index) => row !== rows[index]
    );

    if (!orderChanged) {
      return;
    }

    sortedRows.forEach(
      row => runtimeMemoryText.appendChild(row)
    );

    const userIdleRow =
      runtimeMemoryText.querySelector(".runtime-memory-user-idle");

    if (userIdleRow) {
      runtimeMemoryText.appendChild(userIdleRow);
    }
  }

  function getActiveThinkMemoryCitationIdentitySets() {
    const lineIdentities = new Set();
    const lineKeys = new Set();
    const lineTexts = new Set();

    activeThinkMemoryCitationSources.forEach((state) => {
      state.lineIdentities.forEach(identity => lineIdentities.add(identity));
      state.lineKeys.forEach(key => lineKeys.add(key));
      state.lineTexts.forEach(text => lineTexts.add(text));
    });

    return {
      lineIdentities,
      lineKeys,
      lineTexts,
    };
  }

  function applyThinkMemoryCitationHighlights() {
    if (!runtimeMemoryText) {
      return;
    }

    const activeIdentities =
      getActiveThinkMemoryCitationIdentitySets();

    runtimeMemoryText
      .querySelectorAll(
        "[data-runtime-memory-line-key]"
      )
      .forEach((row) => {
        const lineIdentity =
          normalizeRuntimeCitationIdentity(
            row.dataset.runtimeMemoryLineIdentity
          );
        const lineKey =
          normalizeRuntimeCitationIdentity(
            row.dataset.runtimeMemoryLineKey
          );
        const lineText =
          normalizeRuntimeCitationIdentity(
            row.dataset.runtimeMemoryLineText
          );
        const matched =
          lineIdentity
            ? activeIdentities.lineIdentities.has(lineIdentity)
            : (
              (lineKey && activeIdentities.lineKeys.has(lineKey))
              || (lineText && activeIdentities.lineTexts.has(lineText))
            );

        row.classList.toggle(
          "runtime-memory-citation-hit",
          Boolean(matched)
        );
      });

    sortHighlightedMemoryRows();
  }

  function handleThinkMemoryCitationHighlight(event) {
    const detail = event && event.detail || {};
    const sourceId =
      String(detail.sourceId || "unknown-memory-citation");

    if (detail.active !== true) {
      activeThinkMemoryCitationSources.delete(sourceId);
      applyThinkMemoryCitationHighlights();
      return;
    }

    const lineIdentities = new Set(
      (Array.isArray(detail.lineIdentities) ? detail.lineIdentities : [])
        .map(normalizeRuntimeCitationIdentity)
        .filter(Boolean)
    );
    const lineKeys = new Set(
      (Array.isArray(detail.lineKeys) ? detail.lineKeys : [])
        .map(normalizeRuntimeCitationIdentity)
        .filter(Boolean)
    );
    const lineTexts = new Set(
      (Array.isArray(detail.lineTexts) ? detail.lineTexts : [])
        .map(normalizeRuntimeCitationIdentity)
        .filter(Boolean)
    );

    if (
      !lineIdentities.size
      && !lineKeys.size
      && !lineTexts.size
    ) {
      activeThinkMemoryCitationSources.delete(sourceId);
    } else {
      activeThinkMemoryCitationSources.set(
        sourceId,
        { lineIdentities, lineKeys, lineTexts }
      );
    }

    applyThinkMemoryCitationHighlights();
  }

  function handleMemoryReferenceHighlight(event) {
    const detail = event && event.detail || {};

    if (detail.source !== "persistent") {
      return;
    }

    memoryReferenceHighlightState.persistentText =
        detail.active === false
          ? ""
          : String(detail.text || "");

    // A new JIN response owns the citation state for the turn.
    // Drop structured hits from the previous response before the new
    // reasoning analysis publishes its own exact runtime-line matches.
    activeThinkMemoryCitationSources.clear();

    applyMemoryReferenceHighlights();
  }
  function bindMemoryReferenceHighlightEvents() {
    if (memoryReferenceEventsBound) {
      return;
    }

    window.addEventListener(
      MEMORY_REFERENCE_HIGHLIGHT_EVENT,
      handleMemoryReferenceHighlight
    );
    window.addEventListener(
      THINK_RUNTIME_CITATION_HIGHLIGHT_EVENT,
      handleThinkMemoryCitationHighlight
    );

    memoryReferenceEventsBound = true;
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
        .filter(Boolean)
        .sort((left, right) => {
          const pinDelta =
            Number(Boolean(right.pinned))
            - Number(Boolean(left.pinned));

          if (pinDelta) {
            return pinDelta;
          }

          const leftDate =
            Date.parse(
              left.last_appended_date
              || left.created_date
              || left.created_time
              || ""
            ) || 0;
          const rightDate =
            Date.parse(
              right.last_appended_date
              || right.created_date
              || right.created_time
              || ""
            ) || 0;

          return rightDate - leftDate;
        });
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
        const l4Status =
            String(field.l4_status || "pending")
              .trim()
              .toLocaleLowerCase();


        if (
            !content
            || l4Status === "analyzed"
        ) {
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

  function getLongTermMemoryFactRecords() {
    const facts =
        typeof getLongTermMemoryFacts === "function"
          ? getLongTermMemoryFacts()
          : [];

    if (!Array.isArray(facts)) {
      return [];
    }

    return facts
      .filter(fact => (
        fact
        && typeof fact === "object"
        && !Array.isArray(fact)
        && String(fact.key || "").trim()
        && String(fact.value || "").trim()
      ))
      .sort((left, right) => {
        const updatedDifference =
            String(right.updated_at || "").localeCompare(
              String(left.updated_at || "")
            );

        if (updatedDifference) {
          return updatedDifference;
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

    if (getLongTermMemoryFactRecords().length > 0) {
      modes.push(
          "long_term"
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
              : displayMode === "long_term"
                ? "[ long term memory ]"
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

  let lastRuntimeAvatarSnapshotDispatchSignature = null;

  function buildRuntimeAvatarSnapshotDispatchSignature(snapshot) {
    if (!snapshot || typeof snapshot !== "object") {
      return "empty";
    }

    const lines = Array.isArray(snapshot.lines)
      ? snapshot.lines
      : [];

    return JSON.stringify({
      runtime_memory_id: snapshot.runtime_memory_id || null,
      index: runtimeMemoryHistory
        ? runtimeMemoryHistory.index
        : -1,
      total_diff: snapshot.total_diff || 0,
      raw_memory: String(snapshot.raw_memory || ""),
      lines: lines.map(line => ({
        id: line && line.id || "",
        active_memory_id: line && line.active_memory_id || "",
        key: line && line.key || "",
        value: line && line.value || "",
        status: line && line.status || "",
        key_status: line && line.key_status || "",
        value_status: line && line.value_status || "",
        key_change_ratio: Number(line && line.key_change_ratio || 0),
        value_change_ratio: Number(line && line.value_change_ratio || 0),
      })),
    });
  }

  function dispatchRuntimeAvatarSnapshot(snapshot) {
    const signature =
        buildRuntimeAvatarSnapshotDispatchSignature(snapshot);

    if (signature === lastRuntimeAvatarSnapshotDispatchSignature) {
      return;
    }

    lastRuntimeAvatarSnapshotDispatchSignature = signature;

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
    clearDelayedMemoryAvatarHover();
    clampRuntimeMemoryHistoryIndex();
    ensureRuntimeMemoryDisplayModeAvailable();
    updateRuntimeMemoryTitleState();

    if (getRuntimeMemoryDisplayMode() === "active") {
      renderActiveMemoryRecords();
      applyMemoryReferenceHighlights();
      return;
    }

    if (getRuntimeMemoryDisplayMode() === "delayed") {
      renderDelayedMemoryReports();
      applyMemoryReferenceHighlights();
      return;
    }

    if (getRuntimeMemoryDisplayMode() === "facts") {
      renderFactsMemoryFields();
      applyMemoryReferenceHighlights();
      return;
    }

    if (getRuntimeMemoryDisplayMode() === "long_term") {
      renderLongTermMemoryFacts();
      applyMemoryReferenceHighlights();
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
      applyMemoryReferenceHighlights();
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
    applyMemoryReferenceHighlights();
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

  function dispatchMemoryRowAvatarHover(detail) {
    window.dispatchEvent(
      new CustomEvent(
        MEMORY_ROW_AVATAR_HOVER_EVENT,
        {
          detail: detail || {
            active: false,
          },
        }
      )
    );
  }

  function dispatchDelayedMemoryReportAvatarHighlight(
      report,
      active
  ) {
    const avatarMemoryHoverId =
        buildAvatarMemoryHoverId(
          "delayed",
          report && report._storage_key
        );

    window.dispatchEvent(
      new CustomEvent(
        DELAYED_MEMORY_REPORT_ACTIVE_EVENT,
        {
          detail: active && avatarMemoryHoverId
            ? {
              active: true,
              avatarMemoryHoverId,
            }
            : {
              active: false,
            },
        }
      )
    );
  }

  function dispatchRuntimeMemoryLineAvatarHover(
      row,
      active
  ) {
    const avatarMemoryHoverId =
        row
          ? String(row.dataset.avatarMemoryHoverId || "").trim()
          : "";

    dispatchMemoryRowAvatarHover(
      active && avatarMemoryHoverId
        ? {
          active: true,
          avatarMemoryHoverId,
        }
        : {
          active: false,
        }
    );
  }

  function dispatchLongTermFactAvatarHover(
      factId,
      active
  ) {
    const avatarMemoryHoverId =
        buildAvatarMemoryHoverId(
          "l4",
          factId
        );

    dispatchMemoryRowAvatarHover(
      active && avatarMemoryHoverId
        ? {
          active: true,
          avatarMemoryHoverId,
        }
        : {
          active: false,
        }
    );
  }

  function clearRuntimeMemoryLineAvatarHover() {
    dispatchRuntimeMemoryLineAvatarHover(
      null,
      false
    );
  }

  function dispatchDelayedMemoryAvatarHover(
      report,
      active
  ) {
    const avatarMemoryHoverId =
        buildAvatarMemoryHoverId(
          "delayed",
          report && report._storage_key
        );

    dispatchMemoryRowAvatarHover(
      active && avatarMemoryHoverId
        ? {
          active: true,
          avatarMemoryHoverId,
        }
        : {
          active: false,
        }
    );
  }

  function clearDelayedMemoryAvatarHover() {
    dispatchMemoryRowAvatarHover({
      active: false,
    });
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

    const sourceLines =
        (snapshot.lines || [])
          .map((line, sourceIndex) => ({
            ...line,
            avatar_memory_hover_id:
              buildAvatarMemoryHoverId(
                "runtime",
                line && line.id || `line-${sourceIndex}`
              ),
          }));
    const lines =
        showLiveUserIdle
          ? sourceLines
            .filter(line => !memoryModel.isUserIdleRuntimeMemoryLine(line))
          : sourceLines;

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
      row.dataset.memoryHighlightSortIndex =
          String(index);
      const avatarMemoryHoverId =
          String(
            line && line.avatar_memory_hover_id || ""
          ).trim();

      if (avatarMemoryHoverId) {
        row.dataset.avatarMemoryHoverId =
            avatarMemoryHoverId;
      }
      const lineIdentity =
          normalizeRuntimeCitationIdentity(
            line.citation_identity
          );

      if (lineIdentity) {
        row.dataset.runtimeMemoryLineIdentity =
            lineIdentity;
      }
      row.dataset.runtimeMemoryLineKey =
          normalizeRuntimeCitationIdentity(
            line.key || "note"
          );
      row.dataset.runtimeMemoryLineText =
          normalizeRuntimeCitationIdentity(
            `${line.key || "note"}: ${line.value || ""}`
          );
      setMemoryReferenceAliases(
        row,
        collectMemoryRecordReferenceAliases(line)
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
      } else if (options.interactiveLongTermMemory) {
        configureLongTermMemoryRow(
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

    configureRuntimeMemoryDeleteHold(
        row,
        () => {
          if (typeof deleteRuntimeMemoryLine === "function") {
            deleteRuntimeMemoryLine(
                index,
                line
            );
          }
        }
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

    configureRuntimeMemoryDeleteHold(
        row,
        () => {
          if (typeof deleteFactsMemoryField === "function") {
            deleteFactsMemoryField(
                line.key
            );
          }
        }
    );
  }

  function configureLongTermMemoryRow(
    row,
    line
  ) {
    if (
        !row
        || !line
        || !line.id
    ) {
      return;
    }

    configureRuntimeMemoryDeleteHold(
        row,
        () => {
          if (typeof deleteLongTermMemoryFact === "function") {
            deleteLongTermMemoryFact(
                line.id
            );
          }
        }
    );
  }

  function configureRuntimeMemoryDeleteHold(
      row,
      onDelete
  ) {
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

        if (typeof onDelete === "function") {
          onDelete();
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

      reports.forEach((report, index) => {
        const title =
            String(report.title || "").trim();

        const summary =
            String(report.summary || "").trim();

        const row =
            document.createElement("div");

        row.className =
            "runtime-memory-line runtime-memory-delayed-row";
        row.dataset.memoryHighlightSortIndex =
            String(index);

        const reportId =
            normalizeDelayedMemoryReportId(
                report._storage_key
            );

        if (
            reportId
            && reportId === activeDelayedMemoryReportId
        ) {
          row.classList.add(
              "runtime-memory-delayed-row-active"
          );
        }

        if (Boolean(report.pinned)) {
          row.classList.add(
              "runtime-memory-delayed-row-pinned"
          );
        }

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
        row.dataset.delayedMemoryId =
            normalizeRuntimeCitationIdentity(
              reportId || report._storage_key
            );
        row.dataset.avatarMemoryHoverId =
            buildAvatarMemoryHoverId(
              "delayed",
              reportId || report._storage_key
            );
        setMemoryReferenceAliases(
          row,
          collectMemoryRecordReferenceAliases(
            report
          )
        );

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

        row.addEventListener("mouseenter", () => {
          dispatchDelayedMemoryAvatarHover(
              report,
              true
          );
        });

        row.addEventListener("mouseleave", () => {
          dispatchDelayedMemoryAvatarHover(
              report,
              false
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

  function normalizeDelayedMemoryTooltipText(value) {
    return normalizeDelayedMemoryDisplayText(value)
        .replace(/\s+/g, " ");
  }

  function normalizeDelayedMemoryFactId(value) {
    const raw =
        normalizeDelayedMemoryDisplayText(value)
          .replace(/^["']|["']$/g, "");

    const match =
        raw.match(/^F([1-9]\d*)$/i);

    return match
      ? `F${match[1]}`
      : raw;
  }

  function normalizeDelayedMemoryFactIds(value) {
    const candidates =
        Array.isArray(value)
          ? value
          : normalizeDelayedMemoryDisplayText(value)
              .match(/\bF[1-9]\d*\b/gi) || [];

    const seen =
        new Set();

    return candidates
      .map(item => normalizeDelayedMemoryFactId(item))
      .filter((factId) => {
        if (!factId || seen.has(factId)) {
          return false;
        }

        seen.add(factId);
        return true;
      });
  }

  function getDelayedMemoryFactIdNumber(factId) {
    const match =
        String(factId || "").match(/^F([1-9]\d*)$/);

    return match
      ? Number(match[1])
      : Number.POSITIVE_INFINITY;
  }

  function sortDelayedMemoryFactIdsByNumber(factIds) {
    return [...factIds].sort((left, right) => {
      const leftNumber =
          getDelayedMemoryFactIdNumber(left);
      const rightNumber =
          getDelayedMemoryFactIdNumber(right);

      if (leftNumber !== rightNumber) {
        return leftNumber - rightNumber;
      }

      return String(left).localeCompare(
          String(right)
      );
    });
  }

  function isDelayedMemoryFactIdField(key) {
    return [
      "anchor_fact_ids",
      "facts_ids",
      "absorbed_fact_ids",
      "long_term_facts_ids",
    ].includes(
        String(key || "").trim()
    );
  }

  function appendDelayedMemoryFactLookupEntry(
    lookup,
    fact
  ) {
    if (
        !fact
        || typeof fact !== "object"
        || Array.isArray(fact)
    ) {
      return;
    }

    const factId =
        normalizeDelayedMemoryFactId(fact.id);

    if (factId && !lookup.has(factId)) {
      lookup.set(
          factId,
          fact
      );
    }

    (Array.isArray(fact.source_fact_ids) ? fact.source_fact_ids : [])
      .forEach((sourceFactId) => {
        const normalizedSourceId =
            normalizeDelayedMemoryFactId(sourceFactId);

        if (normalizedSourceId && !lookup.has(normalizedSourceId)) {
          lookup.set(
              normalizedSourceId,
              fact
          );
        }
      });
  }

  function getDelayedMemoryFactLookup() {
    const lookup =
        new Map();

    getLongTermMemoryFactRecords()
      .forEach(fact => appendDelayedMemoryFactLookupEntry(
          lookup,
          fact
      ));

    const l4Memory =
        window.JinRuntime
        && window.JinRuntime.l4Memory;

    const allFacts =
        l4Memory && typeof l4Memory.getFacts === "function"
          ? l4Memory.getFacts()
          : [];

    (Array.isArray(allFacts) ? allFacts : [])
      .forEach(fact => appendDelayedMemoryFactLookupEntry(
          lookup,
          fact
      ));

    return lookup;
  }

  function buildDelayedMemoryFactIdTitle(
    factId,
    factLookup
  ) {
    const fact =
        factLookup.get(factId);

    if (!fact) {
      return `Fact ${factId}`;
    }

    const key =
        normalizeDelayedMemoryTooltipText(fact.key);
    const value =
        normalizeDelayedMemoryTooltipText(
            fact.value || fact.content
        );

    if (key && value) {
      return `${key}: ${value}`;
    }

    return key || value || `Fact ${factId}`;
  }

  function removeDelayedMemoryFactIdFromModal(factId) {
    const normalizedFactId =
        normalizeDelayedMemoryFactId(factId);

    if (
        !normalizedFactId
        || !delayedMemoryModalContent
    ) {
      return;
    }

    Array.from(
        delayedMemoryModalContent.querySelectorAll(
            ".delayed-memory-modal-fact-id"
        )
    ).forEach((item) => {
      if (item.dataset.delayedMemoryFactId !== normalizedFactId) {
        return;
      }

      const list =
          item.closest(
              ".delayed-memory-modal-fact-ids"
          );
      const row =
          item.closest(
              ".delayed-memory-modal-field"
          );

      item.remove();

      if (list && list.childElementCount < 1 && row) {
        row.remove();
      }
    });
  }

  function setDelayedMemoryModalAnchorFactId(
    factId,
    anchor
  ) {
    const normalizedFactId =
        normalizeDelayedMemoryFactId(factId);

    if (
        !normalizedFactId
        || !delayedMemoryModalReport
        || typeof setDelayedMemoryReportAnchorFactIds !== "function"
    ) {
      return false;
    }

    const currentAnchorIds =
        new Set(
            normalizeDelayedMemoryFactIds(
                delayedMemoryModalReport.anchor_fact_ids
            )
        );
    const hadAnchor =
        currentAnchorIds.has(normalizedFactId);

    if (anchor) {
      currentAnchorIds.add(normalizedFactId);
    } else {
      currentAnchorIds.delete(normalizedFactId);
    }

    if (hadAnchor === currentAnchorIds.has(normalizedFactId)) {
      return false;
    }

    const nextAnchorIds =
        sortDelayedMemoryFactIdsByNumber(
            Array.from(currentAnchorIds)
        );
    const updatedReport =
        setDelayedMemoryReportAnchorFactIds(
            delayedMemoryModalReport._storage_key,
            nextAnchorIds
        );

    if (
        !updatedReport
        || typeof updatedReport !== "object"
        || Array.isArray(updatedReport)
    ) {
      return false;
    }

    openDelayedMemoryReportModal(
        updatedReport
    );

    return true;
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

  function normalizeDelayedMemoryReportId(value) {
    return String(value || "").trim().toLowerCase();
  }

  function isDelayedMemoryReportId(value) {
    return /^[a-z0-9]{6}$/.test(
        normalizeDelayedMemoryReportId(value)
    );
  }

  function getDelayedMemoryReportId(report) {
    if (
        !report
        || typeof report !== "object"
        || Array.isArray(report)
    ) {
      return "";
    }

    const candidates = [
      report._storage_key,
      report.id,
    ];

    for (const candidate of candidates) {
      const reportId =
          normalizeDelayedMemoryReportId(candidate);

      if (isDelayedMemoryReportId(reportId)) {
        return reportId;
      }
    }

    return "";
  }

  function resolveDelayedMemoryReportForModal(report) {
    if (
        !report
        || typeof report !== "object"
        || Array.isArray(report)
    ) {
      return null;
    }

    const reportId =
        getDelayedMemoryReportId(report);
    const reports =
        typeof getDelayedMemoryReports === "function"
          ? getDelayedMemoryReports()
          : null;
    const storedReport =
        reportId
        && reports
        && typeof reports === "object"
        && !Array.isArray(reports)
        && reports[reportId]
        && typeof reports[reportId] === "object"
        && !Array.isArray(reports[reportId])
          ? reports[reportId]
          : null;

    if (storedReport) {
      return {
        ...storedReport,
        _storage_key: reportId,
      };
    }

    return {
      ...report,
      _storage_key:
        reportId
        || normalizeDelayedMemoryReportId(
            report._storage_key
            || report.id
        ),
    };
  }

  function updateDelayedMemoryModalPinState(report) {
    if (!delayedMemoryModalPinButton) {
      return;
    }

    const pinned =
        Boolean(report && report.pinned);

    delayedMemoryModalPinButton.classList.toggle(
        "delayed-memory-modal-pin-active",
        pinned
    );
    delayedMemoryModalPinButton.setAttribute(
        "aria-pressed",
        pinned ? "true" : "false"
    );
    delayedMemoryModalPinButton.title =
        pinned ? "Unpin delayed memory" : "Pin delayed memory";
  }

  function setActiveDelayedMemoryReportRow(
    reportId
  ) {
    const nextId =
        normalizeDelayedMemoryReportId(reportId);

    activeDelayedMemoryReportId =
        isDelayedMemoryReportId(nextId)
          ? nextId
          : "";

    if (!runtimeMemoryText) {
      return;
    }

    Array.from(
        runtimeMemoryText.querySelectorAll(
            ".runtime-memory-delayed-row"
        )
    ).forEach((row) => {
      row.classList.toggle(
          "runtime-memory-delayed-row-active",
          Boolean(
              activeDelayedMemoryReportId
              && normalizeDelayedMemoryReportId(
                  row.dataset.delayedMemoryId
              ) === activeDelayedMemoryReportId
          )
      );
    });
  }


  function closeDelayedMemoryReportModal() {
    if (!delayedMemoryModal) {
      return;
    }

    dispatchDelayedMemoryReportAvatarHighlight(
        delayedMemoryModalReport,
        false
    );
    setActiveDelayedMemoryReportRow(
        ""
    );

    delayedMemoryModal.classList.add(
        "hidden"
    );

    delayedMemoryModal.classList.remove(
        "flex"
    );
    delayedMemoryModalReport = null;
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

    const headerActions =
        document.createElement("div");

    headerActions.className =
        "delayed-memory-modal-actions";

    delayedMemoryModalPinButton =
        document.createElement("button");

    delayedMemoryModalPinButton.type =
        "button";

    delayedMemoryModalPinButton.className =
        "delayed-memory-modal-icon-button delayed-memory-modal-pin";

    delayedMemoryModalPinButton.setAttribute(
        "aria-label",
        "Pin delayed memory"
    );

    delayedMemoryModalPinButton.setAttribute(
        "aria-pressed",
        "false"
    );

    delayedMemoryModalPinButton.innerHTML =
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.7 3.3 20.7 9.3 18.6 11.4 16.9 9.7 13.7 12.9 14.4 15.7 12.9 17.2 9.4 13.7 5.3 17.8 4.2 16.7 8.3 12.6 4.8 9.1 6.3 7.6 9.1 8.3 12.3 5.1 10.6 3.4 12.7 1.3Z"/></svg>';

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
        "×";

    delayedMemoryModalContent =
        document.createElement("div");

    delayedMemoryModalContent.className =
        "delayed-memory-modal-content min-h-0 flex-1 overflow-auto p-4 text-[12px] leading-relaxed text-zinc-200";

    header.appendChild(
        delayedMemoryModalTitle
    );

    headerActions.appendChild(
        delayedMemoryModalPinButton
    );

    headerActions.appendChild(
        closeButton
    );

    header.appendChild(
        headerActions
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

    delayedMemoryModalPinButton.addEventListener(
        "click",
        () => {
          if (
              !delayedMemoryModalReport
              || typeof setDelayedMemoryReportPinned !== "function"
          ) {
            return;
          }

          const nextPinned =
              !Boolean(delayedMemoryModalReport.pinned);
          const changed =
              setDelayedMemoryReportPinned(
                  delayedMemoryModalReport._storage_key,
                  nextPinned
              );

          if (!changed) {
            return;
          }

          delayedMemoryModalReport = {
            ...delayedMemoryModalReport,
            pinned: nextPinned,
          };
          updateDelayedMemoryModalPinState(
              delayedMemoryModalReport
          );
        }
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

  function appendDelayedMemoryModalFieldNode(
    parent,
    label,
    valueNode
  ) {
    if (!valueNode) {
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

    row.appendChild(
        key
    );

    row.appendChild(
        valueNode
    );

    parent.appendChild(
        row
    );
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

    const text =
        document.createElement("div");

    text.className =
        "delayed-memory-modal-value";

    text.textContent =
        normalizedValue;

    appendDelayedMemoryModalFieldNode(
        parent,
        label,
        text
    );
  }

  function appendDelayedMemoryFactIdField(
    parent,
    label,
    value,
    anchorFactIds = new Set()
  ) {
    const fieldName =
        String(label || "").trim();
    const normalizedFactIds =
        normalizeDelayedMemoryFactIds(value);
    const factIds =
        fieldName === "facts_ids"
          ? sortDelayedMemoryFactIdsByNumber(normalizedFactIds)
          : normalizedFactIds;

    if (!factIds.length) {
      if (Array.isArray(value) && value.length < 1) {
        appendDelayedMemoryModalField(
            parent,
            label,
            "[]"
        );
      }

      return;
    }

    const factLookup =
        getDelayedMemoryFactLookup();

    const list =
        document.createElement("div");

    list.className =
        "delayed-memory-modal-value delayed-memory-modal-fact-ids";

    factIds.forEach((factId) => {
      const item =
          document.createElement("span");
      const isAnchorFactId =
          anchorFactIds.has(factId);

      const title =
          buildDelayedMemoryFactIdTitle(
              factId,
              factLookup
          );

      item.className =
          "delayed-memory-modal-fact-id";
      item.classList.toggle(
          "delayed-memory-modal-fact-id-anchor",
          isAnchorFactId
      );
      item.textContent =
          factId;
      item.title =
          title;
      item.dataset.delayedMemoryFactId =
          factId;
      item.setAttribute(
          "aria-label",
          `${factId}: ${title}`
      );
      item.setAttribute(
          "tabindex",
          "0"
      );

      item.addEventListener("mouseenter", () => {
        dispatchLongTermFactAvatarHover(
            factId,
            true
        );
      });

      item.addEventListener("mouseleave", () => {
        dispatchLongTermFactAvatarHover(
            factId,
            false
        );
      });

      item.addEventListener("focus", () => {
        dispatchLongTermFactAvatarHover(
            factId,
            true
        );
      });

      item.addEventListener("blur", () => {
        dispatchLongTermFactAvatarHover(
            factId,
            false
        );
      });

      item.addEventListener("dblclick", (event) => {
        event.preventDefault();
        event.stopPropagation();

        setDelayedMemoryModalAnchorFactId(
            factId,
            fieldName === "anchor_fact_ids"
              ? false
              : !isAnchorFactId
        );
      });

      configureRuntimeMemoryDeleteHold(
          item,
          () => {
            if (typeof deleteLongTermMemoryFact !== "function") {
              return;
            }

            const deleted =
                deleteLongTermMemoryFact(
                    factId
                );

            if (deleted !== false) {
              removeDelayedMemoryFactIdFromModal(
                  factId
              );
            }
          }
      );

      list.appendChild(
          item
      );
    });

    appendDelayedMemoryModalFieldNode(
        parent,
        label,
        list
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
    const anchorFactIds =
        new Set(
            normalizeDelayedMemoryFactIds(
                report && report.anchor_fact_ids
            )
        );

    const shownKeys =
        new Set([
          "_storage_key",
          "title",
          "summary",
          "created_time",
          "created_session_id",
          "tags",
          "body",
          "pinned",
        ]);

    Object.entries(report || {}).forEach(([key, value]) => {
      if (
          shownKeys.has(key)
          || value === null
          || typeof value === "undefined"
      ) {
        return;
      }

      if (isDelayedMemoryFactIdField(key)) {
        appendDelayedMemoryFactIdField(
            parent,
            key,
            value,
            anchorFactIds
        );
        return;
      }

      const normalizedValue =
          Array.isArray(value) && value.length < 1
            ? "[]"
            : typeof value === "object"
            && !Array.isArray(value)
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
    const resolvedReport =
        resolveDelayedMemoryReportForModal(report);

    if (!resolvedReport) {
      return;
    }

    delayedMemoryModalReport = {
      ...resolvedReport,
    };
    setActiveDelayedMemoryReportRow(
        delayedMemoryModalReport._storage_key
    );
    updateDelayedMemoryModalPinState(
        delayedMemoryModalReport
    );

    delayedMemoryModalTitle.textContent =
        normalizeDelayedMemoryDisplayText(delayedMemoryModalReport.title)
        || "Delayed memory";

    delayedMemoryModalContent.innerHTML = "";

    const fields =
        document.createElement("section");

    fields.className =
        "delayed-memory-modal-fields";

    appendDelayedMemoryModalField(
        fields,
        "Title",
        delayedMemoryModalReport.title
    );

    appendDelayedMemoryModalField(
        fields,
        "Summary",
        delayedMemoryModalReport.summary
    );

    appendDelayedMemoryModalField(
        fields,
        "Time",
        formatDelayedMemoryTime(
            delayedMemoryModalReport.created_time
        )
    );

    appendDelayedMemoryModalField(
        fields,
        "Tags",
        delayedMemoryModalReport.tags
    );

    appendDelayedMemoryModalField(
        fields,
        "ID",
        delayedMemoryModalReport._storage_key
    );

    appendDelayedMemoryModalField(
        fields,
        "Session",
        delayedMemoryModalReport.created_session_id
    );

    appendDelayedMemoryModalExtraFields(
        fields,
        delayedMemoryModalReport
    );

    delayedMemoryModalContent.appendChild(
        fields
    );

    appendDelayedMemoryModalBody(
        delayedMemoryModalContent,
        delayedMemoryModalReport.body
    );

    delayedMemoryModal.classList.remove(
        "hidden"
    );

    delayedMemoryModal.classList.add(
        "flex"
    );

    dispatchDelayedMemoryReportAvatarHighlight(
        delayedMemoryModalReport,
        true
    );
  }

  function buildFactsMemoryLine(record) {
    const content =
        String(record.content || "").trim();

    return {
      key: String(record.key || "").trim(),
      value: memoryModel.appendProperties(
          content,
          [
            `runtime_snapshot_id: ${String(record.runtime_snapshot_id || "").trim()}`,
            `session_id: ${String(record.session_id || "").trim()}`,
            `l4_status: ${String(record.l4_status || "pending").trim()}`,
            `l4_content_hash: ${String(record.l4_content_hash || "").trim()}`,
            `l4_analyzed_at: ${String(record.l4_analyzed_at || "").trim()}`,
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


  function formatLongTermFactMetadata(
    fact
  ) {

    const entries = [];

    [
      "id",
      "category",
      "mention_count",
      "source_session_ids",
      "source_runtime_snapshot_ids",
      "source_keys",
      "source_fact_ids",
      "created_at",
      "updated_at",
    ].forEach((key) => {
      let value =
        fact[key];

      if (Array.isArray(value)) {
        value =
          value
            .map(item => String(item || "").trim())
            .filter(Boolean)
            .join(", ");
      }

      if (
          value === undefined
          || value === null
          || String(value).trim() === ""
      ) {
        return;
      }

      if (typeof value === "number") {
        value =
          value.toFixed(2).replace(/\.00$/, "");
      }

      entries.push(
        `${key}: ${value}`
      );
    });

    return entries;

  }


  function buildLongTermMemoryLine(
    fact
  ) {

    const id =
      String(fact.id || "").trim();
    const key =
      String(fact.key || "").trim();
    const value =
      String(fact.value || "").trim();

    return {
      id,
      key,
      value: memoryModel.appendProperties(
          value,
          formatLongTermFactMetadata(fact)
      ),
      avatar_memory_hover_id:
        buildAvatarMemoryHoverId(
          "l4",
          id
        ),
      citation_identity:
        buildCitationRecordIdentity(
          id,
          key,
          value
        ),
      status: "same",
      key_status: "same",
      value_status: "same",
      key_change_ratio: 0,
      value_change_ratio: 0,
    };

  }


  function renderLongTermMemoryFacts() {
    const records =
        getLongTermMemoryFactRecords();

    const lines =
        records.map(
          buildLongTermMemoryLine
        );

    if (runtimeMemoryText) {
      runtimeMemoryText.innerHTML = "";
      runtimeMemoryText.classList.remove(
          "runtime-memory-text-pinned"
      );
      runtimeMemoryText.removeAttribute(
          "title"
      );

      if (!lines.length) {
        runtimeMemoryText.textContent =
          "No long-term facts stored.";
      } else {
        appendRuntimeMemoryLineRows(
            lines,
            false,
            {
              applyFlash: false,
              interactiveLongTermMemory: true,
            }
        );
      }
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
          records.map((record, index) => ({
            ...memoryModel.parseRuntimeMemoryLine(record),
            avatar_memory_hover_id:
              buildAvatarMemoryHoverId(
                "active",
                extractActiveMemoryId(record)
                  || `record-${index}`
              ),
          })),
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
    setDelayedMemoryReportPinned = options.setDelayedMemoryReportPinned || null;
    setDelayedMemoryReportAnchorFactIds =
        options.setDelayedMemoryReportAnchorFactIds || null;
    getFactsMemoryFields = options.getFactsMemoryFields || null;
    deleteFactsMemoryField = options.deleteFactsMemoryField || null;
    getLongTermMemoryFacts = options.getLongTermMemoryFacts || null;
    deleteLongTermMemoryFact = options.deleteLongTermMemoryFact || null;
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

    bindMemoryReferenceHighlightEvents();

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
