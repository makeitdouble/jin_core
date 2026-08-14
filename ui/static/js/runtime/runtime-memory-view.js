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
  let isDelayedMemoryReportLoaded = null;
  let isDelayedMemoryReportAppended = null;
  let handleDelayedMemoryReportPinClick = null;
  let setDelayedMemoryReportPinned = null;
  let updateDelayedMemoryReportFields = null;
  let setDelayedMemoryReportAnchorFactIds = null;
  let linkDelayedMemoryReportFactId = null;
  let unlinkDelayedMemoryReportFactId = null;
  let deleteDelayedMemoryReport = null;
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
  const MEMORY_ROW_REORDER_TRANSITION_FALLBACK_MS = 230;
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
  let runtimeMemorySortTransitionSequence = 0;


  const pinnedRuntimeMemorySnapshotIndexes = new Set();

  const autoFlashedRuntimeMemorySnapshots = new WeakSet();


  let delayedMemoryModal = null;
  let delayedMemoryModalPanel = null;
  let delayedMemoryModalTitle = null;
  let delayedMemoryModalContent = null;
  let delayedMemoryModalPinButton = null;
  let delayedMemoryModalDeleteButton = null;
  let delayedMemoryModalReport = null;
  let delayedMemoryModalTitleEditor = null;
  let delayedMemoryModalSummaryEditor = null;
  let delayedMemoryModalBodyEditor = null;
  let delayedMemoryModalEditSaveTimer = null;
  let activeDelayedMemoryFactPicker = null;
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

  const memoryPanel =
      document.getElementById("memory-panel");

  const MEMORY_PANEL_COLLAPSE_SYNC_EVENT =
      "jin:memory-panel-collapse-sync";

  let pendingRuntimeMemoryRender = false;
  let memoryHighlightsSuspended = false;
  let memoryPanelVisibilityEventsBound = false;

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

  function isRuntimeMemoryPanelCollapsed() {
    return Boolean(
      memoryPanel
      && memoryPanel.classList.contains(
        "panel-collapsed"
      )
    );
  }

  function isRuntimeMemoryViewDomConnected() {
    return Boolean(
      runtimeMemoryText
      && runtimeMemoryText.isConnected
    );
  }

  function isRuntimeMemoryViewSuspended() {
    return (
      isRuntimeMemoryPanelCollapsed()
      || !isRuntimeMemoryViewDomConnected()
    );
  }

  function clearRuntimeMemoryHighlightClasses() {
    if (!runtimeMemoryText || !runtimeMemoryText.isConnected) {
      return;
    }

    runtimeMemoryText
      .querySelectorAll(
        [
          ".runtime-memory-reference-hit",
          ".runtime-memory-citation-hit",
          ".runtime-memory-external-hover-hit",
        ].join(", ")
      )
      .forEach((row) => {
        row.classList.remove(
          "runtime-memory-reference-hit",
          "runtime-memory-citation-hit",
          "runtime-memory-external-hover-hit"
        );
      });
  }

  function suspendRuntimeMemoryHighlights() {
    if (memoryHighlightsSuspended) {
      return;
    }

    clearRuntimeMemoryHighlightClasses();
    memoryHighlightsSuspended = true;
  }

  function getCurrentRuntimeAvatarSourceSnapshot() {
    if (
      !runtimeMemoryHistory
      || !Array.isArray(runtimeMemoryHistory.snapshots)
      || runtimeMemoryHistory.index < 0
    ) {
      return null;
    }

    return runtimeMemoryHistory.snapshots[
      runtimeMemoryHistory.index
    ] || null;
  }

  function handleRuntimeMemoryPanelVisibilityChange() {
    if (isRuntimeMemoryViewSuspended()) {
      suspendRuntimeMemoryHighlights();
      return;
    }

    memoryHighlightsSuspended = false;

    if (pendingRuntimeMemoryRender) {
      pendingRuntimeMemoryRender = false;
      renderRuntimeMemorySnapshot({
        animateSort: false,
        flashMode: "none",
      });
      return;
    }

    applyMemoryReferenceHighlights({
        animateSort: false,
    });
  }

  function bindRuntimeMemoryPanelVisibilityEvents() {
    if (memoryPanelVisibilityEventsBound) {
      return;
    }

    window.addEventListener(
      MEMORY_PANEL_COLLAPSE_SYNC_EVENT,
      handleRuntimeMemoryPanelVisibilityChange
    );

    if (memoryPanel && typeof MutationObserver !== "undefined") {
      const observer =
          new MutationObserver(
              handleRuntimeMemoryPanelVisibilityChange
          );

      observer.observe(
        memoryPanel,
        {
          attributes: true,
          attributeFilter: ["class"],
        }
      );
    }

    memoryPanelVisibilityEventsBound = true;
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

  function applyMemoryReferenceHighlights(options = {}) {
    if (!runtimeMemoryText) {
      return;
    }

    if (isRuntimeMemoryViewSuspended()) {
      suspendRuntimeMemoryHighlights();
      return;
    }

    memoryHighlightsSuspended = false;

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

    applyThinkMemoryCitationHighlights(options);
  }

  function shouldReduceRuntimeMemoryMotion() {
    return Boolean(
      typeof window.matchMedia === "function"
      && window.matchMedia("(prefers-reduced-motion: reduce)").matches
    );
  }

  function shouldAnimateHighlightedMemoryRowSort(rows) {
    return Boolean(
      Array.isArray(rows)
      && rows.length > 1
      && typeof window.requestAnimationFrame === "function"
      && !shouldReduceRuntimeMemoryMotion()
    );
  }

  function clearRuntimeMemoryRowSortTransition(row) {
    if (!row) {
      return;
    }

    const timer =
        Number(row.dataset.runtimeMemorySortTransitionTimer || 0);

    if (timer) {
      window.clearTimeout(timer);
      delete row.dataset.runtimeMemorySortTransitionTimer;
    }

    delete row.dataset.runtimeMemorySortTransitionToken;
    row.classList.remove(
        "runtime-memory-sort-transition"
    );
    row.style.removeProperty(
        "transform"
    );
    row.style.removeProperty(
        "transition"
    );
  }

  function captureRuntimeMemoryRowTops(rows) {
    const tops = new Map();

    rows.forEach((row) => {
      tops.set(
          row,
          row.getBoundingClientRect().top
      );
    });

    return tops;
  }

  function animateRuntimeMemoryRowReorder(rows, previousTops) {
    if (
        !runtimeMemoryText
        || !previousTops
        || !previousTops.size
    ) {
      return;
    }

    const movingRows = [];

    rows.forEach((row) => {
      const previousTop =
          previousTops.get(row);

      if (typeof previousTop !== "number") {
        return;
      }

      const deltaY =
          previousTop - row.getBoundingClientRect().top;

      if (Math.abs(deltaY) < 0.5) {
        return;
      }

      clearRuntimeMemoryRowSortTransition(row);
      row.style.transition =
          "none";
      row.style.transform =
          `translateY(${deltaY}px)`;
      movingRows.push(row);
    });

    if (!movingRows.length) {
      return;
    }

    void runtimeMemoryText.offsetHeight;

    window.requestAnimationFrame(() => {
      movingRows.forEach((row) => {
        runtimeMemorySortTransitionSequence += 1;
        const transitionToken =
            String(runtimeMemorySortTransitionSequence);

        row.dataset.runtimeMemorySortTransitionToken =
            transitionToken;
        row.style.removeProperty(
            "transition"
        );
        row.classList.add(
            "runtime-memory-sort-transition"
        );
        row.style.transform =
            "translateY(0)";

        const cleanup = (event) => {
          if (
              row.dataset.runtimeMemorySortTransitionToken
              !== transitionToken
          ) {
            return;
          }

          if (
              event
              && event.propertyName
              && event.propertyName !== "transform"
          ) {
            return;
          }

          clearRuntimeMemoryRowSortTransition(row);
        };

        row.addEventListener(
            "transitionend",
            cleanup,
            {
              once: true,
            }
        );

        row.dataset.runtimeMemorySortTransitionTimer =
            String(
                window.setTimeout(
                    cleanup,
                    MEMORY_ROW_REORDER_TRANSITION_FALLBACK_MS
                )
            );
      });
    });
  }

  function sortHighlightedMemoryRows(options = {}) {
    if (!runtimeMemoryText) {
      return;
    }

    if (isRuntimeMemoryViewSuspended()) {
      suspendRuntimeMemoryHighlights();
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
          || left.classList.contains("runtime-memory-citation-hit")
          || left.classList.contains("runtime-memory-context-loaded-hit");
        const rightHighlighted =
          right.classList.contains("runtime-memory-reference-hit")
          || right.classList.contains("runtime-memory-citation-hit")
          || right.classList.contains("runtime-memory-context-loaded-hit");

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

    const previousTops =
        options.animateSort !== false
        && shouldAnimateHighlightedMemoryRowSort(rows)
          ? captureRuntimeMemoryRowTops(rows)
          : null;

    sortedRows.forEach(
      row => runtimeMemoryText.appendChild(row)
    );

    const userIdleRow =
      runtimeMemoryText.querySelector(".runtime-memory-user-idle");

    if (userIdleRow) {
      runtimeMemoryText.appendChild(userIdleRow);
    }

    animateRuntimeMemoryRowReorder(
        sortedRows,
        previousTops
    );
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

  function applyThinkMemoryCitationHighlights(options = {}) {
    if (!runtimeMemoryText) {
      return;
    }

    if (isRuntimeMemoryViewSuspended()) {
      suspendRuntimeMemoryHighlights();
      return;
    }

    memoryHighlightsSuspended = false;

    const activeIdentities =
      getActiveThinkMemoryCitationIdentitySets();

    const citationRows = Array.from(
      runtimeMemoryText.querySelectorAll(
        "[data-runtime-memory-line-key]"
      )
    );
    const lineKeyUsage = new Map();

    citationRows.forEach((row) => {
      const lineKey =
        normalizeRuntimeCitationIdentity(
          row.dataset.runtimeMemoryLineKey
        );

      if (!lineKey) {
        return;
      }

      lineKeyUsage.set(
        lineKey,
        Number(lineKeyUsage.get(lineKey) || 0) + 1
      );
    });

    citationRows.forEach((row) => {
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
      const exactTextMatch = Boolean(
        lineText
        && activeIdentities.lineTexts.has(lineText)
      );
      const uniqueKeyMatch = Boolean(
        lineKey
        && Number(lineKeyUsage.get(lineKey) || 0) === 1
        && activeIdentities.lineKeys.has(lineKey)
      );
      const matched =
        lineIdentity
          ? activeIdentities.lineIdentities.has(lineIdentity)
          : (exactTextMatch || uniqueKeyMatch);

      row.classList.toggle(
        "runtime-memory-citation-hit",
        Boolean(matched)
      );
    });

    sortHighlightedMemoryRows(options);
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
              left.last_loaded_date
              || left.created_date
              || left.created_time
              || ""
            ) || 0;
          const rightDate =
            Date.parse(
              right.last_loaded_date
              || right.created_date
              || right.created_time
              || ""
            ) || 0;

          return rightDate - leftDate;
        });
  }

  function isDelayedMemoryReportInContext(report) {
    if (
        !report
        || typeof report !== "object"
        || Array.isArray(report)
    ) {
      return false;
    }

    if (Boolean(report.pinned)) {
      return true;
    }

    const reportId =
      normalizeDelayedMemoryReportId(
        report._storage_key || report.id
      );

    return Boolean(
      reportId
      && typeof isDelayedMemoryReportLoaded === "function"
      && isDelayedMemoryReportLoaded(reportId)
    );
  }

  function getContextLoadedDelayedMemoryFactIds() {
    const factIds = new Set();

    getDelayedMemoryReportRecords()
      .filter(isDelayedMemoryReportInContext)
      .forEach((report) => {
        normalizeDelayedMemoryFactIds([
          report.anchor_fact_ids,
          report.facts_ids,
          report.absorbed_fact_ids,
          report.long_term_facts_ids,
        ]).forEach(factId => factIds.add(factId));
      });

    return factIds;
  }

  function reportReferencesLongTermFactId(report, factId) {
    const normalizedFactId =
        normalizeDelayedMemoryFactId(factId);

    if (
        !normalizedFactId
        || !report
        || typeof report !== "object"
        || Array.isArray(report)
    ) {
      return false;
    }

    return normalizeDelayedMemoryFactIds([
      report.anchor_fact_ids,
      report.facts_ids,
      report.absorbed_fact_ids,
      report.long_term_facts_ids,
    ]).includes(normalizedFactId);
  }

  function getDelayedMemoryReportForLongTermFactId(factId) {
    const normalizedFactId =
        normalizeDelayedMemoryFactId(factId);

    if (!normalizedFactId) {
      return null;
    }

    return getDelayedMemoryReportRecords()
      .find(report => reportReferencesLongTermFactId(
        report,
        normalizedFactId
      )) || null;
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

  function getLongTermFactNumber(fact) {
    const match =
        String(fact && fact.id || "")
          .trim()
          .match(/^F(\d+)$/i);

    if (!match) {
      return null;
    }

    const number = Number(match[1]);

    return Number.isSafeInteger(number)
      ? number
      : null;
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
        const leftNumber =
            getLongTermFactNumber(left);
        const rightNumber =
            getLongTermFactNumber(right);

        if (
            leftNumber !== null
            || rightNumber !== null
        ) {
          if (leftNumber === null) {
            return 1;
          }

          if (rightNumber === null) {
            return -1;
          }

          const idDifference =
              rightNumber - leftNumber;

          if (idDifference) {
            return idDifference;
          }
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
            /\s*(\[[^\]]+\])/gi,
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

    if (isRuntimeMemoryViewSuspended()) {
      pendingRuntimeMemoryRender = true;
      suspendRuntimeMemoryHighlights();
      dispatchRuntimeAvatarSnapshot(
        getCurrentRuntimeAvatarSourceSnapshot()
      );
      return;
    }

    pendingRuntimeMemoryRender = false;
    memoryHighlightsSuspended = false;

    ensureRuntimeMemoryDisplayModeAvailable();
    updateRuntimeMemoryTitleState();
    const renderHighlightOptions = {
      animateSort: false,
    };

    if (getRuntimeMemoryDisplayMode() === "active") {
      renderActiveMemoryRecords();
      applyMemoryReferenceHighlights(renderHighlightOptions);
      return;
    }

    if (getRuntimeMemoryDisplayMode() === "delayed") {
      renderDelayedMemoryReports();
      applyMemoryReferenceHighlights(renderHighlightOptions);
      return;
    }

    if (getRuntimeMemoryDisplayMode() === "facts") {
      renderFactsMemoryFields();
      applyMemoryReferenceHighlights(renderHighlightOptions);
      return;
    }

    if (getRuntimeMemoryDisplayMode() === "long_term") {
      renderLongTermMemoryFacts();
      applyMemoryReferenceHighlights(renderHighlightOptions);
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
      applyMemoryReferenceHighlights(renderHighlightOptions);
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
    applyMemoryReferenceHighlights(renderHighlightOptions);
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

  function runtimeMemoryValueFontWeight(line) {
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
    if (flashMode === "none") {
      return false;
    }

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

  function setDelayedMemoryReportHover(
      reportId,
      active
  ) {
    const normalizedReportId =
        normalizeDelayedMemoryReportId(
            reportId
        );
    const reports =
        typeof getDelayedMemoryReports === "function"
          ? getDelayedMemoryReports()
          : {};
    const report =
        normalizedReportId
        && reports
        && typeof reports === "object"
        && !Array.isArray(reports)
        && reports[normalizedReportId]
        && typeof reports[normalizedReportId] === "object"
        && !Array.isArray(reports[normalizedReportId])
          ? {
              ...reports[normalizedReportId],
              _storage_key: normalizedReportId,
            }
          : null;

    if (isRuntimeMemoryViewSuspended()) {
      suspendRuntimeMemoryHighlights();

      if (!active || !report) {
        clearDelayedMemoryAvatarHover();
        return false;
      }

      dispatchDelayedMemoryAvatarHover(
          report,
          true
      );
      return true;
    }

    if (runtimeMemoryText) {
      runtimeMemoryText
        .querySelectorAll(
          ".runtime-memory-external-hover-hit"
        )
        .forEach((row) => {
          row.classList.remove(
            "runtime-memory-external-hover-hit"
          );
        });
    }

    if (!active || !report) {
      clearDelayedMemoryAvatarHover();
      return false;
    }

    dispatchDelayedMemoryAvatarHover(
        report,
        true
    );

    if (!runtimeMemoryText) {
      return true;
    }

    const delayedHoverId =
        buildAvatarMemoryHoverId(
            "delayed",
            normalizedReportId
        );
    const linkedFactHoverIds =
        new Set(
            normalizeDelayedMemoryFactIds([
              report.anchor_fact_ids,
              report.facts_ids,
              report.absorbed_fact_ids,
              report.long_term_facts_ids,
            ]).map((factId) => (
              buildAvatarMemoryHoverId(
                  "l4",
                  factId
              )
            )).filter(Boolean)
        );

    runtimeMemoryText
      .querySelectorAll(
        ".runtime-memory-line[data-avatar-memory-hover-id]"
      )
      .forEach((row) => {
        const hoverId =
            String(
                row.dataset.avatarMemoryHoverId || ""
            ).trim();

        row.classList.toggle(
          "runtime-memory-external-hover-hit",
          hoverId === delayedHoverId
          || linkedFactHoverIds.has(hoverId)
        );
      });

    return true;
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

      if (line && line.context_loaded === true) {
        row.classList.add(
            "runtime-memory-context-loaded-hit"
        );
      }

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

      if (String(valuePresentation.text || "").trim()) {
        row.classList.add(
            "runtime-memory-kv-row"
        );
      }

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

      if (options.interactiveLongTermMemory) {
        row.classList.add(
          "runtime-memory-l4-row"
        );

        const factNumber =
            line && Number.isSafeInteger(
              line.fact_number
            )
              ? line.fact_number
              : null;

        if (factNumber !== null) {
          const linkedDelayedMemoryReport =
              line && line.linked_delayed_memory_report;
          const numberSpan =
              linkedDelayedMemoryReport
                ? document.createElement("button")
                : document.createElement("span");
          const separatorSpan =
              document.createElement("span");

          numberSpan.className =
              "runtime-memory-fact-number";
          numberSpan.textContent =
              String(factNumber);

          if (linkedDelayedMemoryReport) {
            const reportTitle =
                String(
                    linkedDelayedMemoryReport.title
                    || linkedDelayedMemoryReport.summary
                    || linkedDelayedMemoryReport.id
                    || linkedDelayedMemoryReport._storage_key
                    || ""
                ).trim();

            numberSpan.type =
                "button";
            numberSpan.classList.add(
                "runtime-memory-fact-report-link"
            );
            numberSpan.title =
                reportTitle
                  ? `Open delayed memory report: ${reportTitle}`
                  : "Open delayed memory report";
            numberSpan.addEventListener("pointerdown", (event) => {
              event.stopPropagation();
            });
            numberSpan.addEventListener("click", (event) => {
              event.preventDefault();
              event.stopPropagation();
              openDelayedMemoryReportModal(
                  linkedDelayedMemoryReport
              );
            });
          }

          separatorSpan.className =
              "runtime-memory-fact-separator";
          separatorSpan.textContent =
              "·";

          row.appendChild(numberSpan);
          row.appendChild(separatorSpan);
        }
      }

      const valueSpan =
          document.createElement("span");

      valueSpan.className =
          "runtime-memory-value";

      valueSpan.textContent =
          ` ${valuePresentation.text}`;
      valueSpan.style.fontWeight =
          String(
              runtimeMemoryValueFontWeight(line)
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
        deleteTimer = null;

        if (!pointerDown) {
          return;
        }

        deleteCompleted = true;
        pointerDown = false;
        pointerId = null;

        // The same control can be reused after deletion (for example the
        // delayed-memory report modal delete button). Do not leave the
        // hold-to-delete opacity at zero after the timer completes.
        setRuntimeMemoryRowPressVisual(
            row,
            false
        );

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

        if (summary) {
          row.classList.add(
              "runtime-memory-kv-row"
          );
        }

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

        if (isDelayedMemoryReportInContext(report)) {
          row.classList.add(
              "runtime-memory-context-loaded-hit"
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

        const pinButton =
            document.createElement("button");
        pinButton.type = "button";
        pinButton.className =
            "delayed-memory-modal-icon-button delayed-memory-modal-pin runtime-memory-delayed-pin";
        pinButton.innerHTML =
            '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.7 3.3 20.7 9.3 18.6 11.4 16.9 9.7 13.7 12.9 14.4 15.7 12.9 17.2 9.4 13.7 5.3 17.8 4.2 16.7 8.3 12.6 4.8 9.1 6.3 7.6 9.1 8.3 12.3 5.1 10.6 3.4 12.7 1.3Z"/></svg>';
        syncDelayedMemoryPinButtonState(
          pinButton,
          report
        );

        const separatorSpan =
            document.createElement("span");
        separatorSpan.className =
            "runtime-memory-delayed-separator";
        separatorSpan.textContent = "·";

        pinButton.addEventListener(
          "pointerdown",
          (event) => {
            event.stopPropagation();
          }
        );

        pinButton.addEventListener(
          "click",
          (event) => {
            event.preventDefault();
            event.stopPropagation();

            if (!reportId) {
              return;
            }

            const changed =
                typeof handleDelayedMemoryReportPinClick === "function"
                  ? handleDelayedMemoryReportPinClick(reportId)
                  : (
                      typeof setDelayedMemoryReportPinned === "function"
                        ? setDelayedMemoryReportPinned(
                            reportId,
                            !Boolean(report.pinned)
                          )
                        : false
                    );

            if (!changed) {
              syncDelayedMemoryPinButtonState(
                pinButton,
                report
              );
            }
          }
        );

        row.appendChild(
            pinButton
        );
        row.appendChild(
            separatorSpan
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

  function trimDelayedMemoryFactPreview(
    value,
    limit = 20
  ) {
    const text =
        normalizeDelayedMemoryDisplayText(value);

    return text.length > limit
      ? text.slice(0, limit)
      : text;
  }

  function buildDelayedMemoryFactOptionLabel(
    factId,
    fact
  ) {
    const key =
        normalizeDelayedMemoryDisplayText(
            fact && fact.key
        )
        || "fact_key";
    const title =
        trimDelayedMemoryFactPreview(
            fact && (
              fact.value
              || fact.content
              || fact.title
            )
        )
        || "fact_title";

    return `${factId} . ${key}: ${title}`;
  }

  function matchesDelayedMemoryFactQuery(
    factId,
    fact,
    query
  ) {
    const normalizedQuery =
        normalizeDelayedMemoryDisplayText(query)
          .toLowerCase();

    if (!normalizedQuery) {
      return true;
    }

    return [
      factId,
      fact && fact.key,
      fact && fact.value,
      fact && fact.content,
      fact && fact.title,
    ].some((value) => (
      normalizeDelayedMemoryDisplayText(value)
        .toLowerCase()
        .includes(normalizedQuery)
    ));
  }

  function getDelayedMemoryFactOptions(
    factLookup,
    currentFactIds,
    query = ""
  ) {
    return getLongTermMemoryFactRecords()
      .map((fact) => {
        const factId =
            normalizeDelayedMemoryFactId(
                fact && fact.id
            );

        return factId
          ? {
            factId,
            fact,
          }
          : null;
      })
      .filter((entry) => (
        entry
        && !currentFactIds.has(entry.factId)
        && matchesDelayedMemoryFactQuery(
            entry.factId,
            entry.fact,
            query
        )
      ))
      .map((entry) => ({
        ...entry,
        title:
          buildDelayedMemoryFactIdTitle(
              entry.factId,
              factLookup
          ),
        label:
          buildDelayedMemoryFactOptionLabel(
              entry.factId,
              entry.fact
          ),
      }));
  }

  function linkFactToDelayedMemoryModal(
    factId
  ) {
    if (
        !delayedMemoryModalReport
        || typeof linkDelayedMemoryReportFactId !== "function"
    ) {
      return false;
    }

    const updatedReport =
        linkDelayedMemoryReportFactId(
            delayedMemoryModalReport._storage_key,
            factId
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

  function unlinkFactFromDelayedMemoryModal(
    factId
  ) {
    if (
        !delayedMemoryModalReport
        || typeof unlinkDelayedMemoryReportFactId !== "function"
    ) {
      return false;
    }

    const updatedReport =
        unlinkDelayedMemoryReportFactId(
            delayedMemoryModalReport._storage_key,
            factId
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

  function closeActiveDelayedMemoryFactPicker(options = {}) {
    if (
        !activeDelayedMemoryFactPicker
        || typeof activeDelayedMemoryFactPicker.close !== "function"
    ) {
      return;
    }

    activeDelayedMemoryFactPicker.close(options);
  }

  function appendDelayedMemoryFactPicker(
    container,
    factLookup,
    currentFactIds
  ) {

    const picker =
        document.createElement("div");

    picker.className =
        "delayed-memory-modal-fact-picker hidden";

    const input =
        document.createElement("input");

    input.type =
        "text";
    input.className =
        "delayed-memory-modal-fact-input";
    input.setAttribute(
        "aria-label",
        "Search facts"
    );
    input.setAttribute(
        "autocomplete",
        "off"
    );
    input.setAttribute(
        "spellcheck",
        "false"
    );

    const dropdown =
        document.createElement("div");

    dropdown.className =
        "delayed-memory-modal-fact-dropdown";

    function updatePickerInputWidth() {
      const queryLength =
          String(input.value || "").length;

      input.style.width =
          queryLength > 0
            ? `${Math.min(queryLength + 1, 28)}ch`
            : "";
    }

    function closePicker(options = {}) {
      picker.classList.add(
          "hidden"
      );
      container.classList.remove(
          "delayed-memory-modal-fact-ids-active"
      );
      input.value =
          "";
      updatePickerInputWidth();
      dropdown.innerHTML =
          "";

      if (options.blur !== false) {
        input.blur();
      }

      if (
          activeDelayedMemoryFactPicker
          && activeDelayedMemoryFactPicker.close === closePicker
      ) {
        activeDelayedMemoryFactPicker =
            null;
      }
    }

    function renderOptions() {
      dropdown.innerHTML =
          "";

      const options =
          getDelayedMemoryFactOptions(
              factLookup,
              currentFactIds,
              input.value
          );

      if (!options.length) {
        const empty =
            document.createElement("div");

        empty.className =
            "delayed-memory-modal-fact-empty";
        empty.textContent =
            "no facts";
        dropdown.appendChild(
            empty
        );
        return;
      }

      options.forEach((option) => {
        const optionButton =
            document.createElement("button");
        const id =
            document.createElement("span");
        const separator =
            document.createElement("span");
        const text =
            document.createElement("span");

        optionButton.type =
            "button";
        optionButton.className =
            "delayed-memory-modal-fact-option";
        optionButton.title =
            option.title;

        id.className =
            "delayed-memory-modal-fact-option-id";
        id.textContent =
            option.factId;

        separator.className =
            "delayed-memory-modal-fact-option-separator";
        separator.textContent =
            ".";

        text.className =
            "delayed-memory-modal-fact-option-text";
        text.textContent =
            option.label.replace(
                `${option.factId} . `,
                ""
            );

        optionButton.appendChild(
            id
        );
        optionButton.appendChild(
            separator
        );
        optionButton.appendChild(
            text
        );
        optionButton.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopPropagation();
          closePicker();
          linkFactToDelayedMemoryModal(
              option.factId
          );
        });

        dropdown.appendChild(
            optionButton
        );
      });
    }

    function openPicker() {
      if (
          activeDelayedMemoryFactPicker
          && activeDelayedMemoryFactPicker.close !== closePicker
      ) {
        closeActiveDelayedMemoryFactPicker();
      }

      activeDelayedMemoryFactPicker = {
        close: closePicker,
        container,
      };
      picker.classList.remove(
          "hidden"
      );
      container.classList.add(
          "delayed-memory-modal-fact-ids-active"
      );
      updatePickerInputWidth();
      renderOptions();
      input.focus({
        preventScroll: true,
      });
    }

    container.addEventListener("click", (event) => {
      const target =
          event.target;

      if (
          target
          && typeof target.closest === "function"
          && (
              target.closest(".delayed-memory-modal-fact-id")
              || target.closest(".delayed-memory-modal-fact-option")
          )
      ) {
        return;
      }

      openPicker();
    });

    input.addEventListener("input", () => {
      updatePickerInputWidth();
      renderOptions();
    });

    input.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        closePicker();
        return;
      }

      if (event.key !== "Enter") {
        return;
      }

      event.preventDefault();

      const typedFactId =
          normalizeDelayedMemoryFactId(
              input.value
          );
      const exactFactId =
          /^F[1-9]\d*$/.test(typedFactId)
            ? typedFactId
            : "";
      const options =
          getDelayedMemoryFactOptions(
              factLookup,
              currentFactIds,
              input.value
          );
      const nextFactId =
          exactFactId
          || (options[0] && options[0].factId)
          || "";

      if (nextFactId) {
        closePicker();
        linkFactToDelayedMemoryModal(
            nextFactId
        );
      }
    });

    picker.appendChild(
        input
    );
    picker.appendChild(
        dropdown
    );

    container.appendChild(
        picker
    );
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

    syncDelayedMemoryPinButtonState(
      delayedMemoryModalPinButton,
      report
    );
  }

  function isDelayedMemoryReportAutoAppended(report) {
    const reportId =
        getDelayedMemoryReportId(report);

    return Boolean(
      reportId
      && typeof isDelayedMemoryReportAppended === "function"
      && isDelayedMemoryReportAppended(reportId)
    );
  }

  function syncDelayedMemoryPinButtonState(
    button,
    report
  ) {
    if (!button) {
      return;
    }

    const pinned =
        Boolean(report && report.pinned);
    const appended =
        !pinned
        && isDelayedMemoryReportAutoAppended(report);

    button.classList.toggle(
        "delayed-memory-modal-pin-active",
        pinned
    );
    button.classList.toggle(
        "delayed-memory-modal-pin-appended",
        appended
    );
    button.setAttribute(
        "aria-pressed",
        pinned ? "true" : "false"
    );
    button.setAttribute(
        "aria-label",
        appended
          ? "Remove appended delayed memory"
          : (
              pinned
                ? "Unpin delayed memory"
                : "Pin delayed memory"
            )
    );
    button.title =
        appended
          ? "Remove appended delayed memory from next turn"
          : (
              pinned
                ? "Unpin delayed memory"
                : "Pin delayed memory"
            );
  }

  function clearDelayedMemoryModalEditSaveTimer() {
    if (!delayedMemoryModalEditSaveTimer) {
      return;
    }

    window.clearTimeout(
        delayedMemoryModalEditSaveTimer
    );
    delayedMemoryModalEditSaveTimer = null;
  }

  function readDelayedMemoryModalEditorText(editor) {
    return editor
      ? String(editor.innerText || "")
      : "";
  }

  function commitDelayedMemoryModalEdits(options = {}) {
    if (!delayedMemoryModalReport) {
      return false;
    }

    clearDelayedMemoryModalEditSaveTimer();

    let title =
        readDelayedMemoryModalEditorText(
            delayedMemoryModalTitleEditor
        ).trim();
    const summary =
        readDelayedMemoryModalEditorText(
            delayedMemoryModalSummaryEditor
        );
    const body =
        readDelayedMemoryModalEditorText(
            delayedMemoryModalBodyEditor
        );

    if (!title && options.finalizeTitle) {
      title = "undefined";

      if (delayedMemoryModalTitleEditor) {
        delayedMemoryModalTitleEditor.textContent =
            title;
      }
    }

    delayedMemoryModalReport = {
      ...delayedMemoryModalReport,
      title,
      summary,
      body,
    };

    if (delayedMemoryModalTitle) {
      delayedMemoryModalTitle.textContent =
          title || "Delayed memory";
    }

    if (
        !title
        || typeof updateDelayedMemoryReportFields !== "function"
    ) {
      return false;
    }

    const updatedReport =
        updateDelayedMemoryReportFields(
            delayedMemoryModalReport._storage_key,
            {
              title,
              summary,
              body,
            }
        );

    if (updatedReport) {
      delayedMemoryModalReport = {
        ...updatedReport,
      };
    }

    return updatedReport;
  }

  function scheduleDelayedMemoryModalEditSave() {
    if (!delayedMemoryModalReport) {
      return;
    }

    clearDelayedMemoryModalEditSaveTimer();

    delayedMemoryModalEditSaveTimer =
        window.setTimeout(
            () => {
              delayedMemoryModalEditSaveTimer = null;
              commitDelayedMemoryModalEdits();
            },
            250
        );
  }

  function bindDelayedMemoryModalEditor(
    editor,
    options = {}
  ) {
    if (!editor) {
      return;
    }

    editor.setAttribute(
        "contenteditable",
        "plaintext-only"
    );
    editor.setAttribute(
        "spellcheck",
        "false"
    );
    editor.classList.add(
        "delayed-memory-modal-editable"
    );

    editor.addEventListener("input", () => {
      if (options.title && delayedMemoryModalTitle) {
        delayedMemoryModalTitle.textContent =
            readDelayedMemoryModalEditorText(editor).trim()
            || "Delayed memory";
      }

      scheduleDelayedMemoryModalEditSave();
    });

    if (options.singleLine) {
      editor.addEventListener("keydown", (event) => {
        if (event.key !== "Enter") {
          return;
        }

        event.preventDefault();
        editor.blur();
      });
    }
  }

  function deleteDelayedMemoryModalReport() {
    if (
        !delayedMemoryModalReport
        || typeof deleteDelayedMemoryReport !== "function"
    ) {
      return;
    }

    const reportId =
        getDelayedMemoryReportId(
            delayedMemoryModalReport
        );

    const deleted =
        deleteDelayedMemoryReport(
            reportId
        );

    if (deleted !== false) {
      closeDelayedMemoryReportModal({
        save: false,
      });
    }
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


  function closeDelayedMemoryReportModal(options = {}) {
    if (!delayedMemoryModal) {
      return;
    }

    closeActiveDelayedMemoryFactPicker();

    if (options.save !== false) {
      commitDelayedMemoryModalEdits({
        finalizeTitle: true,
      });
    } else {
      clearDelayedMemoryModalEditSaveTimer();
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
    delayedMemoryModalTitleEditor = null;
    delayedMemoryModalSummaryEditor = null;
    delayedMemoryModalBodyEditor = null;
  }

  function ensureDelayedMemoryModal() {
    if (delayedMemoryModal) {
      return;
    }

    delayedMemoryModal =
        document.createElement("div");

    delayedMemoryModal.className =
        "delayed-memory-report-modal fixed inset-0 z-50 hidden items-center justify-center bg-black/70 p-4";

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

    delayedMemoryModalDeleteButton =
        document.createElement("button");

    delayedMemoryModalDeleteButton.type =
        "button";

    delayedMemoryModalDeleteButton.className =
        "delayed-memory-modal-icon-button delayed-memory-modal-delete";

    delayedMemoryModalDeleteButton.setAttribute(
        "aria-label",
        "Delete delayed memory"
    );

    delayedMemoryModalDeleteButton.title =
        "Hold to delete delayed memory";

    delayedMemoryModalDeleteButton.innerHTML =
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 3h6l1 2h4v2H4V5h4l1-2Zm1 6h2v9h-2V9Zm4 0h2v9h-2V9ZM7 9h2l.7 10h4.6L15 9h2l-.8 11.1A2 2 0 0 1 14.2 22H9.8a2 2 0 0 1-2-1.9L7 9Z"/></svg>';

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
        delayedMemoryModalDeleteButton
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
              || (
                typeof handleDelayedMemoryReportPinClick !== "function"
                && typeof setDelayedMemoryReportPinned !== "function"
              )
          ) {
            return;
          }

          const reportId =
              getDelayedMemoryReportId(
                delayedMemoryModalReport
              );
          const changed =
              typeof handleDelayedMemoryReportPinClick === "function"
                ? handleDelayedMemoryReportPinClick(reportId)
                : setDelayedMemoryReportPinned(
                    reportId,
                    !Boolean(delayedMemoryModalReport.pinned)
                  );

          if (!changed) {
            return;
          }

          delayedMemoryModalReport =
              resolveDelayedMemoryReportForModal(
                delayedMemoryModalReport
              );
          updateDelayedMemoryModalPinState(
              delayedMemoryModalReport
          );
        }
    );

    delayedMemoryModalDeleteButton.addEventListener(
        "click",
        (event) => {
          event.preventDefault();
          event.stopPropagation();
        }
    );

    configureRuntimeMemoryDeleteHold(
        delayedMemoryModalDeleteButton,
        deleteDelayedMemoryModalReport
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

    document.addEventListener("click", (event) => {
      if (
          !activeDelayedMemoryFactPicker
          || !activeDelayedMemoryFactPicker.container
      ) {
        return;
      }

      const target =
          event.target;

      if (
          target
          && typeof activeDelayedMemoryFactPicker.container.contains === "function"
          && activeDelayedMemoryFactPicker.container.contains(target)
      ) {
        return;
      }

      closeActiveDelayedMemoryFactPicker();
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

  function appendDelayedMemoryModalEditableField(
    parent,
    label,
    value,
    options = {}
  ) {
    const text =
        document.createElement("div");

    text.className =
        "delayed-memory-modal-value";

    text.textContent =
        normalizeDelayedMemoryDisplayText(value);

    bindDelayedMemoryModalEditor(
        text,
        options
    );

    appendDelayedMemoryModalFieldNode(
        parent,
        label,
        text
    );

    return text;
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

    if (
        !factIds.length
        && fieldName !== "facts_ids"
    ) {
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
    const currentFactIds =
        new Set(
            factIds
        );

    const list =
        document.createElement("div");

    list.className =
        "delayed-memory-modal-value delayed-memory-modal-fact-ids";

    if (!factIds.length) {
      const empty =
          document.createElement("span");

      empty.className =
          "delayed-memory-modal-fact-empty-inline";
      empty.textContent =
          "[]";
      list.appendChild(
          empty
      );
    }

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

      item.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();

        closeActiveDelayedMemoryFactPicker();

        if (item.dataset.delayedMemoryFactHoldDeleted === "true") {
          return;
        }

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
            item.dataset.delayedMemoryFactHoldDeleted =
                "true";
            unlinkFactFromDelayedMemoryModal(
                factId
            );
          }
      );

      list.appendChild(
          item
      );
    });

    if (fieldName === "facts_ids") {
      appendDelayedMemoryFactPicker(
          list,
          factLookup,
          currentFactIds
      );
    }

    appendDelayedMemoryModalFieldNode(
        parent,
        label,
        list
    );
  }

  function appendDelayedMemoryModalBody(parent, body) {
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
        normalizeDelayedMemoryDisplayText(body);

    bindDelayedMemoryModalEditor(
        pre
    );

    section.appendChild(
        heading
    );

    section.appendChild(
        pre
    );

    parent.appendChild(
        section
    );

    return pre;
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

    // This button is a single persistent DOM node reused for every report.
    // A completed hold from the previous report must never keep it faded out
    // when the next report is opened.
    if (delayedMemoryModalDeleteButton) {
      delayedMemoryModalDeleteButton.style.removeProperty(
          "transition-property"
      );
      delayedMemoryModalDeleteButton.style.removeProperty(
          "transition-timing-function"
      );
      delayedMemoryModalDeleteButton.style.removeProperty(
          "transition-duration"
      );
      delayedMemoryModalDeleteButton.style.removeProperty(
          "opacity"
      );
    }

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

    delayedMemoryModalTitleEditor =
        appendDelayedMemoryModalEditableField(
            fields,
            "Title",
            delayedMemoryModalReport.title,
            {
              title: true,
              singleLine: true,
            }
        );

    delayedMemoryModalSummaryEditor =
        appendDelayedMemoryModalEditableField(
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

    delayedMemoryModalBodyEditor =
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
    fact,
    contextLoadedFactIds = new Set()
  ) {

    const id =
      String(fact.id || "").trim();
    const key =
      String(fact.key || "").trim();
    const value =
      String(fact.value || "").trim();
    const linkedDelayedMemoryReport =
        getDelayedMemoryReportForLongTermFactId(id);

    return {
      id,
      key,
      fact_number:
        getLongTermFactNumber(fact),
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
      context_loaded:
        contextLoadedFactIds.has(
          normalizeDelayedMemoryFactId(id)
        ),
      linked_delayed_memory_report:
        linkedDelayedMemoryReport,
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

    const contextLoadedFactIds =
        getContextLoadedDelayedMemoryFactIds();

    const lines =
        records.map(
          fact => buildLongTermMemoryLine(
            fact,
            contextLoadedFactIds
          )
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
    isDelayedMemoryReportLoaded =
        options.isDelayedMemoryReportLoaded || null;
    isDelayedMemoryReportAppended =
        options.isDelayedMemoryReportAppended || null;
    handleDelayedMemoryReportPinClick =
        options.handleDelayedMemoryReportPinClick || null;
    setDelayedMemoryReportPinned = options.setDelayedMemoryReportPinned || null;
    updateDelayedMemoryReportFields =
        options.updateDelayedMemoryReportFields || null;
    setDelayedMemoryReportAnchorFactIds =
        options.setDelayedMemoryReportAnchorFactIds || null;
    linkDelayedMemoryReportFactId =
        options.linkDelayedMemoryReportFactId || null;
    unlinkDelayedMemoryReportFactId =
        options.unlinkDelayedMemoryReportFactId || null;
    deleteDelayedMemoryReport =
        options.deleteDelayedMemoryReport || null;
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
    bindRuntimeMemoryPanelVisibilityEvents();

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
    setDelayedMemoryReportHover,
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
