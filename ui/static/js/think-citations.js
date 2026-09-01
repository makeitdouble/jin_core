(function () {
  "use strict";

  const THINK_RULE_CITATIONS_ENDPOINT =
    "/api/debug/rule-citations";
  const THINK_RULE_WORKER_URL =
    "/static/js/think-rule-worker.js";
  const THINK_RUNTIME_CITATION_HIGHLIGHT_EVENT =
    "jin:think-runtime-citation-highlight";
  const MEMORY_REFERENCE_HIGHLIGHT_EVENT =
    "jin:memory-reference-highlight";
  const ACTIVE_MEMORY_RECORDS_CHANGED_EVENT =
    "jin:active-memory-records-changed";
  const buildCitationRecordIdentity =
    window.JinRuntime
    && typeof window.JinRuntime.buildCitationRecordIdentity === "function"
      ? window.JinRuntime.buildCitationRecordIdentity
      : () => "";

  let thinkRuleCitationWorker = null;
  let thinkRuleCitationRegistryPromise = null;
  let nextThinkRuntimeCitationIndex = 0;
  let latestThinkCitationTarget = null;
  let hoveredThinkCitationTarget = null;
  let latestPersistentMemoryReferenceText = "";
  let activeMemoryCitationRevision = 0;
  const activeThinkRuleCitationJobs = new Map();

  const ACTIVE_MEMORY_VALUE_MIN_RATIO = 0.25;
  const ACTIVE_MEMORY_VALUE_MIN_TOKENS = 4;
  const ACTIVE_MEMORY_VALUE_MIN_CHARS = 24;

  function normalizeActiveMemoryId(value) {
    const normalized =
      String(value || "").trim().toLowerCase();

    return /^[a-z0-9]{6}$/.test(normalized)
      ? normalized
      : "";
  }

  function normalizeDelayedMemoryId(value) {
    const normalized =
      String(value || "").trim().toLowerCase();

    return /^[a-z0-9]{6}$/.test(normalized)
      ? normalized
      : "";
  }

  function normalizeActiveMemoryKey(value) {
    const normalized =
      String(value || "").trim().toLowerCase();

    return /^active_memory(?:_\d+)?$/.test(normalized)
      ? normalized
      : "";
  }

  function extractActiveMemoryId(value) {
    const match = String(value || "").match(
      /\[\s*active_memory_id\s*:\s*([a-z0-9]{6})\s*\]/i
    );

    return match
      ? normalizeActiveMemoryId(match[1])
      : "";
  }

  function parseActiveMemoryMetadata(value) {
    const fields = new Map();
    const source = String(value || "");
    const pattern = /\[\s*([a-z][a-z0-9_.-]{0,31})\s*:\s*([^\]]*)\]/gi;
    let match = null;

    while ((match = pattern.exec(source)) !== null) {
      const key = String(match[1] || "").trim().toLowerCase();
      const fieldValue = String(match[2] || "")
        .replace(/\s+/g, " ")
        .trim();

      if (key && fieldValue && !fields.has(key)) {
        fields.set(key, fieldValue);
      }
    }

    return fields;
  }

  function stripActiveMemoryMetadata(value) {
    return String(value || "")
      .replace(/\s*\[\s*[a-z][a-z0-9_.-]{0,31}\s*:\s*[^\]]*\]\s*/gi, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function parseActiveMemoryCitationRecord(record, index) {
    const text = String(record || "").trim();
    const separatorIndex = text.indexOf(":");

    if (separatorIndex <= 0) {
      return null;
    }

    const key = text.slice(0, separatorIndex).trim();
    const normalizedKey = normalizeActiveMemoryKey(key);

    if (!normalizedKey) {
      return null;
    }

    const rawValue = text.slice(separatorIndex + 1).trim();
    const id = extractActiveMemoryId(rawValue);

    const metadata = parseActiveMemoryMetadata(rawValue);
    const visibleValue = stripActiveMemoryMetadata(rawValue);
    const conditions = String(
      metadata.get("conditions") || visibleValue
    ).replace(/\s+/g, " ").trim();
    const customTitle = String(
      metadata.get("title") || ""
    ).replace(/\s+/g, " ").trim();
    const slotMatch = key.match(/_(\d+)$/);
    const slotNumber = slotMatch
      ? Number(slotMatch[1])
      : index + 1;
    const runtimeOwnedMetadataKeys = new Set([
      "active_memory_id",
      "conditions",
      "status",
      "title",
      "creation_time",
      "created_at",
      "updated_at",
      "elapsed_time",
      "session_id",
      "message_id",
      "message_count",
    ]);
    const customMetadataAliases = [];

    metadata.forEach((fieldValue, fieldKey) => {
      if (runtimeOwnedMetadataKeys.has(fieldKey)) {
        return;
      }

      customMetadataAliases.push(fieldKey);

      const normalizedValue = String(fieldValue || "")
        .replace(/\s+/g, " ")
        .trim();

      if (normalizedValue.length >= 4) {
        customMetadataAliases.push(normalizedValue);
      }
    });

    return {
      id,
      key,
      rawValue,
      conditions,
      customTitle,
      displayTitles: [
        `Active memory #${slotNumber}`,
        `Active memory ${slotNumber}`,
        `active_memory[${slotNumber}]`,
        `active memory #${slotNumber}`,
      ],
      customMetadataAliases,
      text,
      normalizedKey,
      identity: id
        ? `active:${id}`
        : `active-key:${normalizedKey}`,
      index,
    };
  }

  function getActiveMemoryCitationRecords() {
    const runtimeApi =
      window.JinRuntime
      && window.JinRuntime.runtime;
    const records =
      runtimeApi
      && typeof runtimeApi.getActiveMemoryRecords === "function"
        ? runtimeApi.getActiveMemoryRecords()
        : [];

    return (Array.isArray(records) ? records : [])
      .map(parseActiveMemoryCitationRecord)
      .filter(Boolean);
  }

  function getDelayedMemoryCitationRecords() {
    const runtimeApi =
      window.JinRuntime
      && window.JinRuntime.runtime;
    const reports =
      runtimeApi
      && typeof runtimeApi.getDelayedMemoryReports === "function"
        ? runtimeApi.getDelayedMemoryReports()
        : {};

    if (
      !reports
      || typeof reports !== "object"
      || Array.isArray(reports)
    ) {
      return [];
    }

    return Object.entries(reports)
      .map(([storageKey, report]) => {
        if (
          !report
          || typeof report !== "object"
          || Array.isArray(report)
        ) {
          return null;
        }

        const id =
          normalizeDelayedMemoryId(report._storage_key)
          || normalizeDelayedMemoryId(report.id)
          || normalizeDelayedMemoryId(storageKey);

        if (!id) {
          return null;
        }

        const title =
          String(report.title || "")
            .replace(/\s+/g, " ")
            .trim();
        const summary =
          String(report.summary || "")
            .replace(/\s+/g, " ")
            .trim();

        return {
          id,
          title,
          summary,
          identity: `delayed:${id}`,
        };
      })
      .filter(Boolean);
  }

  function getCurrentActiveMemoryIds() {
    return new Set(
      getActiveMemoryCitationRecords()
        .map(record => record.id)
        .filter(Boolean)
    );
  }

  function getCurrentActiveMemoryKeys() {
    return new Set(
      getActiveMemoryCitationRecords()
        .map(record => record.normalizedKey || normalizeActiveMemoryKey(record.key))
        .filter(Boolean)
    );
  }

  function getMatchActiveMemoryId(match) {
    if (!match || match.sourceType !== "active") {
      return "";
    }

    return normalizeActiveMemoryId(
      match.activeMemoryId
      || extractActiveMemoryId(match.sourceLineText)
      || extractActiveMemoryId(match.titleText)
      || extractActiveMemoryId(match.sourceText)
    );
  }

  function getMatchActiveMemoryKey(match) {
    if (!match || match.sourceType !== "active") {
      return "";
    }

    return normalizeActiveMemoryKey(
      match.activeMemoryKey
      || match.sourceLineKey
      || match.constantName
    );
  }

  function filterLiveActiveMemoryMatches(matches) {
    const activeMemoryIds =
      getCurrentActiveMemoryIds();
    const activeMemoryKeys =
      getCurrentActiveMemoryKeys();

    return (Array.isArray(matches) ? matches : [])
      .filter((match) => {
        if (!match || match.sourceType !== "active") {
          return Boolean(match);
        }

        const activeMemoryId =
          getMatchActiveMemoryId(match);

        if (activeMemoryId) {
          return activeMemoryIds.has(activeMemoryId);
        }

        const activeMemoryKey =
          getMatchActiveMemoryKey(match);

        return Boolean(
          activeMemoryKey
          && activeMemoryKeys.has(activeMemoryKey)
        );
      });
  }

  function isThinkCitationDebugEnabled() {

    return Boolean(
      window.jinStreamDebug
      || window.jinDebugMode
    );

  }

  function updateThinkContentExpandedHeight(element) {

    if (
      typeof window.updateThinkExpandedHeight
        !== "function"
    ) {
      return;
    }

    window.updateThinkExpandedHeight(
      element
    );

  }

  function loadThinkRuleCitationRegistry() {

    if (thinkRuleCitationRegistryPromise) {
      return thinkRuleCitationRegistryPromise;
    }

    thinkRuleCitationRegistryPromise = fetch(
      THINK_RULE_CITATIONS_ENDPOINT,
      {
        cache: "no-store",
      }
    )
      .then((response) => {
        if (!response.ok) {
          throw new Error(
            `Rule citation registry failed: ${response.status}`
          );
        }

        return response.json();
      })
      .catch((error) => {
        if (isThinkCitationDebugEnabled()) {
          console.warn(
            "[think-rules] disabled",
            error
          );
        }

        return {
          enabled: false,
          fragments: [],
        };
      });

    return thinkRuleCitationRegistryPromise;

  }

  function getThinkRuleCitationWorker() {

    if (thinkRuleCitationWorker) {
      return thinkRuleCitationWorker;
    }

    if (!window.Worker) {
      return null;
    }

    thinkRuleCitationWorker =
      new Worker(
        THINK_RULE_WORKER_URL
      );

    thinkRuleCitationWorker.onmessage =
      handleThinkRuleWorkerMessage;

    thinkRuleCitationWorker.onerror = (event) => {
      if (isThinkCitationDebugEnabled()) {
        console.warn(
          "[think-rules] worker error",
          event.message
        );
      }
    };

    return thinkRuleCitationWorker;

  }

  function thinkRuleLevelRank(level) {

    if (level === "exact") {
      return 3;
    }

    if (level === "near") {
      return 2;
    }

    return 1;

  }

  function thinkCitationSourcePriority(match) {

    if (
      match
      && match.sourceType === "rule"
    ) {
      return 4;
    }

    if (
      match
      && match.sourceType === "runtime"
    ) {
      return 3;
    }

    if (
      match
      && match.sourceType === "active"
    ) {
      return 2;
    }

    if (
      match
      && match.sourceType === "delayed"
    ) {
      return 1;
    }

    if (
      match
      && match.sourceType === "lt"
    ) {
      return 1;
    }

    if (
      match
      && match.sourceType === "session"
    ) {
      return 0;
    }

    return -1;

  }

  function resolveThinkRuleOverlaps(matches) {

    const seen = new Set();
    const sorted = [...matches]
      .filter((match) => {
        if (
          !match
          || match.end <= match.start
        ) {
          return false;
        }

        const key = [
          match.start,
          match.end,
          match.level,
          match.constantName,
          match.sourceText,
        ].join("|");

        if (seen.has(key)) {
          return false;
        }

        seen.add(key);
        return true;
      })
      .sort((left, right) => {
        const priorityDelta =
          thinkCitationSourcePriority(
            right
          )
          - thinkCitationSourcePriority(
            left
          );

        if (priorityDelta) {
          return priorityDelta;
        }

        const levelDelta =
          thinkRuleLevelRank(
            right.level
          )
          - thinkRuleLevelRank(
            left.level
          );

        if (levelDelta) {
          return levelDelta;
        }

        if (right.score !== left.score) {
          return right.score - left.score;
        }

        return (
          (right.end - right.start)
          - (left.end - left.start)
        );
      });

    const selected = [];

    sorted.forEach((match) => {
      const overlaps =
        selected.some(
          (selectedMatch) => (
            match.start < selectedMatch.end
            && match.end > selectedMatch.start
          )
        );

      if (!overlaps) {
        selected.push(
          match
        );
      }
    });

    return selected.sort(
      (left, right) => left.start - right.start
    );

  }

  function buildThinkRuleTitle(
    match,
    matchedText
  ) {

    const score =
      Math.round(
        Number(
          match.score || 0
        ) * 100
      );

    const label =
      match.sourceType === "runtime"
        ? "RUNTIME"
        : match.sourceType === "active"
          ? "ACTIVE"
          : match.sourceType === "delayed"
            ? "DELAYED"
            : match.sourceType === "lt"
              ? "L-T"
            : match.sourceType === "session"
              ? "SESSION"
              : "RULE";

    return [
      `${label} - ${match.constantName || "unknown"} - ${match.level || "match"} - ${score}%`,
      `source: ${match.source || "rules"}`,
      `layer: ${match.layer || "base"}`,
      `matched: "${matchedText}"`,
      `${match.sourceType === "rule" ? "rule" : "memory"}: "${match.titleText || match.sourceText || ""}"`,
    ].join("\n");

  }

  function getThinkCitationClassName(match) {

    const sourceClass =
      match.sourceType === "runtime"
        ? "runtime"
        : match.sourceType === "active"
          ? "active"
          : match.sourceType === "delayed"
            ? "delayed"
            : match.sourceType === "lt"
              ? "lt"
            : match.sourceType === "session"
              ? "session"
              : "rule";

    return [
      "think-rule-hit",
      `think-citation-${sourceClass}`,
      match.level || "near",
    ].join(" ");

  }

  function splitThinkCitationTextFragments(text) {

    const runtimeModel =
      window.JinRuntime
      && window.JinRuntime.memoryModel;

    const lines =
      runtimeModel
      && typeof runtimeModel.splitMemoryTextLines === "function"
        ? runtimeModel.splitMemoryTextLines(
          text
        )
        : String(text || "")
          .replace(/\\n/g, "\n")
          .split(/\r?\n+/)
          .map(line => line.trim())
          .filter(Boolean);

    return lines
      .map((line) => {
        const cleanedLine =
          runtimeModel
          && typeof runtimeModel.stripRuntimeMemoryMeta === "function"
            ? runtimeModel.stripRuntimeMemoryMeta(
              line
            )
            : line;

        return String(cleanedLine || "").trim();
      })
      .filter(Boolean);

  }

  function buildMemoryCitationFragments(
    memoryText,
    options
  ) {

    const {
      source,
      sourceType,
      citationType,
      layer,
      idPrefix,
      defaultConstantName,
      sourceSnapshotIndex = null,
      sourceLineIdentity = "",
      activeMemoryId = "",
      activeMemoryKey = "",
      activeContiguousRatio = 0,
    } = options;

    const fragments = [];
    const seen = new Set();

    splitThinkCitationTextFragments(
      memoryText
    ).forEach((line, index) => {
      const separatorIndex =
        line.indexOf(":");
      const key =
        separatorIndex > 0
          ? line.slice(
            0,
            separatorIndex
          ).trim()
          : defaultConstantName;
      const value =
        separatorIndex > 0
          ? line.slice(
            separatorIndex + 1
          ).trim()
          : line;

      [
        line,
        value,
      ].forEach((sourceText, variantIndex) => {
        const normalized =
          sourceText
            .toLowerCase()
            .replace(/\s+/g, " ")
            .trim();

        if (
          !normalized
          || normalized.length < 24
          || seen.has(
            normalized
          )
        ) {
          return;
        }

        seen.add(
          normalized
        );

        fragments.push(
          {
            id: `${idPrefix}:${index}:${variantIndex}`,
            source,
            sourceType,
            citationType,
            layer,
            constantName: key || defaultConstantName,
            sourceText,
            titleText: line,
            sourceLineIndex: index,
            sourceSnapshotIndex,
            sourceLineKey: key || defaultConstantName,
            sourceLineText: line,
            sourceLineIdentity,
            activeMemoryId:
              normalizeActiveMemoryId(activeMemoryId),
            activeMemoryKey:
              normalizeActiveMemoryKey(activeMemoryKey),
            activeContiguousRatio:
              Number(activeContiguousRatio || 0),
            minScore: 0.72,
          }
        );
      });
    });

    return fragments;

  }

  function getRuntimeCitationSnapshot(
    snapshotIndex
  ) {

    const runtimeApi =
      window.JinRuntime
      && window.JinRuntime.runtime;

    if (
      runtimeApi
      && typeof runtimeApi.getRuntimeMemorySnapshot === "function"
    ) {
      return (
        runtimeApi.getRuntimeMemorySnapshot(
          snapshotIndex
        )
        || null
      );
    }

    const storage =
      window.JinRuntime
      && window.JinRuntime.storage;

    if (
      storage
      && typeof storage.readLatestRuntimeMemory === "function"
    ) {
      const latestRuntime =
        storage.readLatestRuntimeMemory();

      if (
        latestRuntime
        && latestRuntime.runtime_snapshot
      ) {
        return latestRuntime.runtime_snapshot;
      }

      return latestRuntime || null;
    }

    return null;

  }

  function getRuntimeCitationTextFromSnapshot(
    snapshot
  ) {

    return String(
      (
        snapshot
        && (
          snapshot.raw_memory
          || snapshot.runtime_memory
          || (
            snapshot.runtime_snapshot
            && snapshot.runtime_snapshot.raw_memory
          )
        )
      )
      || ""
    ).trim();

  }

  function buildRuntimeCitationFragments(
    snapshotIndex
  ) {

    const snapshot =
      getRuntimeCitationSnapshot(
        snapshotIndex
      );
    const runtimeMemory =
      getRuntimeCitationTextFromSnapshot(
        snapshot
      )
        .split(/\r?\n/)
        .filter((line) => {
          const separatorIndex = line.indexOf(":");
          const key = separatorIndex > 0
            ? line.slice(0, separatorIndex).trim()
            : "";

          // Active memory has its own live store and stable ids. Treat that
          // store as canonical so a mirrored L1 line cannot steal the match
          // or keep a resolved slot highlighted.
          return !/^active_memory(?:_\d+)?$/i.test(key);
        })
        .join("\n")
        .trim();

    if (!runtimeMemory) {
      return [];
    }

    return buildMemoryCitationFragments(
      runtimeMemory,
      {
        source: `runtimeSnapshot[${snapshotIndex}]`,
        sourceType: "runtime",
        citationType: "runtime_citation",
        layer: "runtime",
        idPrefix: `runtime:${snapshotIndex}`,
        defaultConstantName: "runtime_memory",
        sourceSnapshotIndex: snapshotIndex,
      }
    );

  }

  function buildActiveMemoryCitationFragments() {

    return getActiveMemoryCitationRecords()
      .flatMap((record) => {
        const fragments = [];
        const activeSourceId = record.id || record.normalizedKey || record.key;
        const base = {
          source: `activeMemory[${activeSourceId}]`,
          sourceType: "active",
          citationType: "active_memory_citation",
          layer: "active",
          constantName: record.key,
          titleText: record.customTitle || record.conditions || record.text,
          sourceLineKey: record.key,
          sourceLineText: record.text,
          sourceLineIdentity: record.identity,
          activeMemoryId: record.id,
          activeMemoryKey: record.normalizedKey || record.key,
          minScore: 0.72,
        };

        if (record.conditions) {
          fragments.push({
            ...base,
            id: `active:${activeSourceId}:conditions`,
            sourceText: record.conditions,
            activeContiguousRatio: ACTIVE_MEMORY_VALUE_MIN_RATIO,
          });
        }

        if (
          record.customTitle
          && normalizeThinkRuntimeCitationIdentity(record.customTitle)
            !== normalizeThinkRuntimeCitationIdentity(record.conditions)
        ) {
          fragments.push({
            ...base,
            id: `active:${activeSourceId}:title`,
            sourceText: record.customTitle,
            activeExactOnly: true,
          });
        }

        return fragments;
      });

  }

  function buildLTCitationFragments() {

    const ltMemory =
      window.JinRuntime
      && window.JinRuntime.ltMemory;

    if (
      !ltMemory
      || (
        typeof ltMemory.getFacts !== "function"
        && typeof ltMemory.getVisibleFacts !== "function"
      )
    ) {
      return [];
    }

    const facts =
      typeof ltMemory.getVisibleFacts === "function"
        ? ltMemory.getVisibleFacts()
        : ltMemory.getFacts();

    if (!Array.isArray(facts)) {
      return [];
    }

    return facts.flatMap((fact, index) => {
      if (
        !fact
        || typeof fact !== "object"
        || Array.isArray(fact)
      ) {
        return [];
      }

      const id =
        String(fact.id || "").trim();
      const key =
        String(fact.key || "").trim();
      const value =
        String(fact.value || fact.content || "").trim();
      const sourceLineIdentity =
        buildCitationRecordIdentity(
          id,
          key,
          value
        );

      if (!key || !value) {
        return [];
      }

      return buildMemoryCitationFragments(
        `${key}: ${value}`,
        {
          source: `ltFact[${id || index}]`,
          sourceType: "lt",
          citationType: "lt_citation",
          layer: "lt",
          idPrefix: `lt:${id || index}`,
          defaultConstantName: key,
          sourceLineIdentity,
        }
      );
    });

  }

  function buildActiveMemoryValueAnchors(value) {
    const words = String(value || "")
      .replace(/\s+/g, " ")
      .trim()
      .split(" ")
      .filter(Boolean);

    if (words.length < ACTIVE_MEMORY_VALUE_MIN_TOKENS) {
      return [];
    }

    const windowSize = Math.max(
      ACTIVE_MEMORY_VALUE_MIN_TOKENS,
      Math.ceil(words.length * ACTIVE_MEMORY_VALUE_MIN_RATIO)
    );
    const lastStart = Math.max(0, words.length - windowSize);
    const stride = Math.max(1, Math.floor(windowSize / 2));
    const starts = [];

    for (let start = 0; start <= lastStart; start += stride) {
      starts.push(start);
    }

    if (!starts.includes(lastStart)) {
      starts.push(lastStart);
    }

    return starts
      .slice(0, 9)
      .map(start => words.slice(start, start + windowSize).join(" "))
      .filter(phrase => phrase.length >= ACTIVE_MEMORY_VALUE_MIN_CHARS);
  }

  function getFastCitationTargetIdentity(candidate) {
    const activeMemoryId = normalizeActiveMemoryId(
      candidate && candidate.activeMemoryId
    );

    if (activeMemoryId) {
      return `active:${activeMemoryId}`;
    }

    const activeMemoryKey = normalizeActiveMemoryKey(
      candidate
      && (candidate.activeMemoryKey || candidate.sourceLineKey)
    );

    if (
      candidate
      && candidate.sourceType === "active"
      && activeMemoryKey
    ) {
      return `active-key:${activeMemoryKey}`;
    }

    const lineIdentity = normalizeThinkRuntimeCitationIdentity(
      candidate && candidate.sourceLineIdentity
    );

    if (lineIdentity) {
      return `line:${lineIdentity}`;
    }

    return [
      candidate && candidate.sourceType,
      candidate && candidate.source,
      candidate && candidate.sourceLineKey,
      candidate && candidate.sourceLineText,
    ].map(normalizeThinkRuntimeCitationIdentity).join("|");
  }

  function fastCitationSourcePriority(candidate) {
    if (candidate && candidate.sourceType === "active") return 3;
    if (candidate && candidate.sourceType === "runtime") return 2;
    if (candidate && candidate.sourceType === "delayed") return 1;
    if (candidate && candidate.sourceType === "lt") return 1;
    return 0;
  }

  function buildFastExactCitationCandidates(snapshotIndex) {
    const candidates = [];

    function add(alias, match, force = false, options = {}) {
      alias = String(alias || "").replace(/\s+/g, " ").trim();
      if (
        !alias
        || (
          !force
          && (
            alias.length < 4
            || /\s/.test(alias)
            || !/[0-9_.#-]/.test(alias)
          )
        )
      ) {
        return;
      }

      candidates.push({
        ...match,
        alias,
        aliasIdentity: alias.toLocaleLowerCase(),
        matchKind: options.matchKind || "token",
        score: 1,
        level: "exact",
        sourceText: options.sourceText || alias,
      });
    }

    function addLine(sourceType, source, lineText, options = {}) {
      lineText = String(lineText || "").trim();
      if (!lineText) return;
      const separatorIndex = lineText.indexOf(":");
      const key = separatorIndex > 0
        ? lineText.slice(0, separatorIndex).trim()
        : String(options.key || "").trim();
      const activeMemoryId = normalizeActiveMemoryId(
        options.activeMemoryId
        || extractActiveMemoryId(lineText)
      );
      const base = {
        source,
        sourceType,
        citationType: options.citationType,
        layer: options.layer,
        constantName: key || options.id || "memory",
        titleText: options.titleText || lineText,
        sourceLineKey: key,
        sourceLineText: lineText,
        sourceLineIdentity: options.identity || "",
        activeMemoryId,
        activeMemoryKey:
          sourceType === "active"
            ? normalizeActiveMemoryKey(options.activeMemoryKey || key)
            : "",
      };

      add(options.id, base, true);
      if (
        options.includeKeyAlias !== false
        && key.toLocaleLowerCase() !== "note"
      ) {
        add(key, base, true);
      }
      if (activeMemoryId) {
        add(activeMemoryId, base, true);
      }
      (Array.isArray(options.aliases) ? options.aliases : [])
        .forEach(alias => add(alias, base, true));
      (Array.isArray(options.valueAnchors) ? options.valueAnchors : [])
        .forEach(anchor => add(
          anchor,
          base,
          true,
          {
            matchKind: "phrase",
            sourceText: options.valueText || anchor,
          }
        ));
    }

    const activeRecords = getActiveMemoryCitationRecords();
    const activeIds = new Set(activeRecords.map(record => record.id));
    const activeKeys = new Set(
      activeRecords.map(record => record.key.toLocaleLowerCase())
    );

    const snapshot = getRuntimeCitationSnapshot(snapshotIndex);
    const snapshotLines = snapshot && Array.isArray(snapshot.lines) ? snapshot.lines : [];
    snapshotLines.forEach((line, index) => {
      const key = String(line && line.key || `runtime_memory_${index + 1}`).trim();
      const value = String(line && line.value || "").trim();
      const activeMemoryId = normalizeActiveMemoryId(
        line && line.active_memory_id
        || extractActiveMemoryId(value)
      );

      if (
        /^active_memory(?:_\d+)?$/i.test(key)
        || activeKeys.has(key.toLocaleLowerCase())
        || (activeMemoryId && activeIds.has(activeMemoryId))
      ) {
        return;
      }

      addLine("runtime", `runtimeSnapshot[${snapshotIndex}]`, `${key}: ${value}`, {
        id: line && line.id,
        layer: "runtime",
        citationType: "runtime_citation",
      });
    });

    activeRecords.forEach((record) => {
      const aliases = [
        ...record.displayTitles,
        record.customTitle,
        ...record.customMetadataAliases,
      ].filter(Boolean);

      const activeSourceId =
        record.id || record.normalizedKey || record.key;

      addLine("active", `activeMemory[${activeSourceId}]`, record.text, {
        id: record.id,
        activeMemoryId: record.id,
        activeMemoryKey: record.normalizedKey || record.key,
        identity: record.identity,
        aliases,
        valueAnchors: buildActiveMemoryValueAnchors(record.conditions),
        valueText: record.conditions,
        titleText: record.customTitle || record.conditions || record.text,
        layer: "active",
        citationType: "active_memory_citation",
      });
    });

    getDelayedMemoryCitationRecords().forEach((record) => {
      const lineText = [
        record.id,
        record.title,
        record.summary,
      ].filter(Boolean).join(": ");

      addLine(
        "delayed",
        `delayedMemory[${record.id}]`,
        lineText,
        {
          id: record.id,
          key: record.id,
          identity: record.identity,
          includeKeyAlias: false,
          titleText: record.title || lineText,
          layer: "delayed",
          citationType: "delayed_memory_citation",
        }
      );
    });

    const ltMemory = window.JinRuntime && window.JinRuntime.ltMemory;
    const facts = ltMemory && typeof ltMemory.getVisibleFacts === "function"
      ? ltMemory.getVisibleFacts()
      : ltMemory && typeof ltMemory.getFacts === "function"
        ? ltMemory.getFacts()
        : [];
    (Array.isArray(facts) ? facts : []).forEach((fact, index) => {
      if (!fact || typeof fact !== "object" || Array.isArray(fact)) return;
      const id = String(fact.id || "").trim();
      const key = String(fact.key || "").trim();
      const value = String(fact.value || fact.content || "").trim();
      if (!key || !value) return;
      addLine("lt", `ltFact[${id || index}]`, `${key}: ${value}`, {
        id,
        layer: "lt",
        citationType: "lt_citation",
        identity: buildCitationRecordIdentity(id, key, value),
      });
    });

    const byAlias = new Map();
    candidates.forEach((candidate) => {
      const list = byAlias.get(candidate.aliasIdentity) || [];
      list.push(candidate);
      byAlias.set(candidate.aliasIdentity, list);
    });

    const selected = [];
    byAlias.forEach((matches) => {
      const targetIdentities = new Set(
        matches.map(getFastCitationTargetIdentity).filter(Boolean)
      );

      // Ambiguous literal aliases are safer ignored than attached to the
      // wrong memory. Mirrored runtime/active copies of the same stable id
      // collapse to one target instead of cancelling each other out.
      if (targetIdentities.size !== 1) {
        return;
      }

      matches.sort((left, right) => (
        fastCitationSourcePriority(right)
        - fastCitationSourcePriority(left)
      ));
      selected.push(matches[0]);
    });

    return selected;
  }

  function isFastCitationCoreTokenCharacter(char) {
    if (!char) return false;
    if (/[0-9_]/.test(char)) return true;
    try {
      return /\p{L}/u.test(char);
    } catch (error) {
      return /[a-z]/i.test(char);
    }
  }

  function isFastCitationTokenJoiner(char) {
    return char === "." || char === "-";
  }

  function isFastCitationBoundaryBlocked(
    source,
    boundaryIndex,
    direction
  ) {
    const char = source[boundaryIndex] || "";

    if (isFastCitationCoreTokenCharacter(char)) {
      return true;
    }

    if (!isFastCitationTokenJoiner(char)) {
      return false;
    }

    const neighborIndex = direction === "before"
      ? boundaryIndex - 1
      : boundaryIndex + 1;

    // Dot/hyphen is part of a token only when it bridges two token chunks
    // (foo.bar / foo-bar). Sentence punctuation after an id (abc123.)
    // must remain a valid boundary.
    return isFastCitationCoreTokenCharacter(
      source[neighborIndex] || ""
    );
  }

  function isFastCitationObservedWholeToken(
    text,
    start,
    end,
    allowTerminalBoundary = false
  ) {
    const source = String(text || "");

    if (
      start > 0
      && isFastCitationBoundaryBlocked(source, start - 1, "before")
    ) {
      return false;
    }

    if (end < source.length) {
      return !isFastCitationBoundaryBlocked(source, end, "after");
    }

    return Boolean(
      allowTerminalBoundary
      && end === source.length
    );
  }

  function findFastExactCitationMatches(
    text,
    candidates,
    options = {}
  ) {
    const source = String(text || "");
    const haystack = source.toLocaleLowerCase();
    const allowTerminalBoundary = Boolean(
      options.allowTerminalBoundary
    );
    const scanStart = Math.max(
      0,
      Number(options.scanStart || 0)
    );
    const previousLength = Math.max(
      0,
      Number(options.previousLength || 0)
    );
    const requireNewText = Boolean(
      options.requireNewText
    );
    const matches = [];

    (Array.isArray(candidates) ? candidates : []).forEach((candidate) => {
      const needle = String(candidate && candidate.aliasIdentity || "");

      if (!needle) {
        return;
      }

      let index = haystack.indexOf(needle, scanStart);

      while (index >= 0) {
        const end = index + needle.length;
        const reachesNewText = Boolean(
          !requireNewText
          || source.length < previousLength
          // A token that ended exactly at the previous frame boundary was
          // intentionally deferred because its right boundary was unknown.
          // Once the next chunk arrives, re-admit that exact end position.
          || end >= previousLength
          || (allowTerminalBoundary && end === source.length)
        );

        if (
          reachesNewText
          && isFastCitationObservedWholeToken(
            source,
            index,
            end,
            allowTerminalBoundary
          )
        ) {
          matches.push({
            ...candidate,
            start: index,
            end,
          });
        }

        index = haystack.indexOf(
          needle,
          index + Math.max(1, needle.length)
        );
      }
    });

    return matches;
  }

  function mergeFastCitationMatches(
    existingMatches,
    incomingMatches
  ) {
    const merged = [];
    const seen = new Set();

    [
      ...(Array.isArray(existingMatches) ? existingMatches : []),
      ...(Array.isArray(incomingMatches) ? incomingMatches : []),
    ].forEach((match) => {
      if (!match) {
        return;
      }

      const key = [
        match.aliasIdentity,
        Number(match.start || 0),
        Number(match.end || 0),
        getFastCitationTargetIdentity(match),
      ].join("|");

      if (seen.has(key)) {
        return;
      }

      seen.add(key);
      merged.push(match);
    });

    return resolveThinkRuleOverlaps(merged);
  }

  function pruneUnstableFastCitationMatches(
    text,
    stream,
    allowTerminalBoundary = false
  ) {
    const currentMatches = Array.isArray(stream.__jinFastCitationMatches)
      ? stream.__jinFastCitationMatches
      : [];
    const stableMatches = currentMatches.filter(match => (
      match
      && isFastCitationObservedWholeToken(
        text,
        Number(match.start || 0),
        Number(match.end || 0),
        allowTerminalBoundary
      )
    ));

    if (stableMatches.length === currentMatches.length) {
      return false;
    }

    stream.__jinFastCitationMatches = stableMatches;
    stream.__jinFastCitationMatchKeys = new Set(
      stableMatches.map(match => (
        `${match.aliasIdentity}|${match.start}|${match.end}|${match.source}`
      ))
    );

    return true;
  }

  function ensureThinkRuntimeCitationIndex(stream) {
    if (Number.isInteger(stream && stream.runtimeCitationIndex)) {
      return stream.runtimeCitationIndex;
    }
    const index = nextThinkRuntimeCitationIndex++;
    if (stream) stream.runtimeCitationIndex = index;
    return index;
  }

  function buildFastCitationMatchesSignature(matches) {
    return (Array.isArray(matches) ? matches : [])
      .map(match => [
        match && match.aliasIdentity,
        Number(match && match.start || 0),
        Number(match && match.end || 0),
        getFastCitationTargetIdentity(match),
      ].join("|"))
      .sort()
      .join("||");
  }

  function updateStreamingRuntimeCitationHighlights(messageId, stream) {
    if (!stream || !stream.group || !stream.group.createdThinking || !stream.group.thinkContent || !stream.thinking) return;

    const thinkContent = stream.group.thinkContent;
    const thinkId = String(messageId);
    const text = String(stream.thinking || "");
    const runtimeCitationIndex = ensureThinkRuntimeCitationIndex(stream);

    const activeRevisionChanged =
      stream.__jinFastCitationActiveRevision !== activeMemoryCitationRevision;

    if (
      !Array.isArray(stream.__jinFastCitationCandidates)
      || activeRevisionChanged
    ) {
      stream.__jinFastCitationCandidates =
        buildFastExactCitationCandidates(runtimeCitationIndex);
      stream.__jinFastCitationMaxAliasLength =
        stream.__jinFastCitationCandidates.reduce(
          (max, candidate) => Math.max(max, candidate.alias.length),
          0
        );
      stream.__jinFastCitationActiveRevision =
        activeMemoryCitationRevision;

      if (!Array.isArray(stream.__jinFastCitationMatches)) {
        stream.__jinFastCitationMatches = [];
      }

      stream.__jinFastCitationMatches =
        filterLiveActiveMemoryMatches(
          stream.__jinFastCitationMatches
        );
      stream.__jinFastCitationScannedLength =
        activeRevisionChanged ? 0 : Number(stream.__jinFastCitationScannedLength || 0);
    }

    const previousLength = Number(stream.__jinFastCitationScannedLength || 0);
    const maxAliasLength = Number(stream.__jinFastCitationMaxAliasLength || 0);
    const allowTerminalBoundary = Boolean(
      stream.__jinFastCitationFinalizing
    );
    const removedUnstableMatch =
      pruneUnstableFastCitationMatches(
        text,
        stream,
        allowTerminalBoundary
      );
    const scanStart =
      activeRevisionChanged || text.length < previousLength
        ? 0
        : Math.max(0, previousLength - maxAliasLength - 1);
    const incomingMatches =
      findFastExactCitationMatches(
        text,
        stream.__jinFastCitationCandidates,
        {
          allowTerminalBoundary,
          scanStart,
          previousLength,
          requireNewText: !activeRevisionChanged,
        }
      );
    const previousMatchSignature =
      buildFastCitationMatchesSignature(
        stream.__jinFastCitationMatches
      );

    stream.__jinFastCitationMatches =
      mergeFastCitationMatches(
        stream.__jinFastCitationMatches,
        incomingMatches
      );
    stream.__jinFastCitationScannedLength = text.length;

    const matchesChanged =
      buildFastCitationMatchesSignature(
        stream.__jinFastCitationMatches
      ) !== previousMatchSignature;

    if (!matchesChanged && !removedUnstableMatch && !activeRevisionChanged) return;

    thinkContent.dataset.thinkId = thinkId;
    thinkContent.dataset.runtimeCitationIndex = String(runtimeCitationIndex);
    thinkContent.__jinThinkRawText = text;
    bindThinkCitationHover(thinkContent);
    latestThinkCitationTarget = thinkContent;
    renderThinkRuleHighlights({
      thinkId,
      element: thinkContent,
      text,
      runtimeCitationIndex,
      matches: [...stream.__jinFastCitationMatches],
      done: false,
    });
    syncAllThinkCitationHighlights();
  }

  function normalizeThinkRuntimeCitationIdentity(value) {

    const source = String(value || "");
    const normalized = source.normalize
      ? source.normalize("NFKC")
      : source;

    return normalized
      .toLowerCase()
      .replace(/\s+/g, " ")
      .trim();

  }

  function buildThinkRuntimeCitationHighlightState(matches) {

    const runtimeMatches =
      filterLiveActiveMemoryMatches(matches)
        .filter(match => (
          match
          && ["runtime", "active", "delayed", "lt"].includes(
            match.sourceType
          )
        ));
    const nonActiveMatches =
      runtimeMatches.filter(match => match.sourceType !== "active");
    const activeMemoryIds =
      Array.from(new Set(
        runtimeMatches
          .filter(match => match.sourceType === "active")
          .map(getMatchActiveMemoryId)
          .filter(Boolean)
      ));
    const activeMemoryKeys =
      Array.from(new Set(
        runtimeMatches
          .filter(match => match.sourceType === "active")
          .map(getMatchActiveMemoryKey)
          .filter(Boolean)
      ));

    const lineKeys =
      Array.from(new Set(
        nonActiveMatches
          .map(match => normalizeThinkRuntimeCitationIdentity(
            match.sourceLineKey
            || match.constantName
          ))
          .filter(Boolean)
      ));

    const lineIdentities =
      Array.from(new Set(
        nonActiveMatches
          .map(match => normalizeThinkRuntimeCitationIdentity(
            match.sourceLineIdentity
          ))
          .filter(Boolean)
      ));

    const lineTexts =
      Array.from(new Set(
        nonActiveMatches
          .map(match => normalizeThinkRuntimeCitationIdentity(
            match.sourceLineText
            || match.titleText
            || match.sourceText
          ))
          .filter(Boolean)
      ));

    if (
      !activeMemoryIds.length
      && !activeMemoryKeys.length
      && !lineIdentities.length
      && !lineKeys.length
      && !lineTexts.length
    ) {
      return null;
    }

    return {
      activeMemoryIds,
      activeMemoryKeys,
      lineIdentities,
      lineKeys,
      lineTexts,
    };

  }

  function dispatchThinkRuntimeCitationHighlight(
    thinkContent,
    active
  ) {

    if (!thinkContent) {
      return;
    }

    const state =
      active
        ? thinkContent.__jinRuntimeCitationHighlightState
        : null;
    const sourceId =
      String(thinkContent.dataset.thinkId || "unknown-think");

    window.dispatchEvent(
      new CustomEvent(
        THINK_RUNTIME_CITATION_HIGHLIGHT_EVENT,
        {
          detail: state
            ? {
              active: true,
              sourceId,
              activeMemoryIds: [...state.activeMemoryIds],
              activeMemoryKeys: [...state.activeMemoryKeys],
              lineIdentities: [...state.lineIdentities],
              lineKeys: [...state.lineKeys],
              lineTexts: [...state.lineTexts],
            }
            : {
              active: false,
              sourceId,
              activeMemoryIds: [],
              activeMemoryKeys: [],
              lineIdentities: [],
              lineKeys: [],
              lineTexts: [],
            },
        }
      )
    );

  }

  function shouldRevealThinkRuntimeCitations(thinkContent) {

    return Boolean(
      thinkContent
      && thinkContent.__jinRuntimeCitationHighlightState
    );

  }

  function hasThinkRuleHighlights(thinkContent) {

    return Boolean(
      thinkContent
      && thinkContent.__jinHasRuleHighlights
    );

  }

  function getActiveThinkCitationTarget() {

    return (
      hoveredThinkCitationTarget
      || latestThinkCitationTarget
    );

  }

  function buildThinkRuntimeCitationHighlightSignature(state) {
    if (!state) {
      return "";
    }

    return [
      [...state.activeMemoryIds].sort().join(","),
      [...state.activeMemoryKeys].sort().join(","),
      [...state.lineIdentities].sort().join(","),
      [...state.lineKeys].sort().join(","),
      [...state.lineTexts].sort().join(","),
    ].join("|");
  }

  function setThinkCitationElementActive(
    thinkContent,
    active
  ) {

    if (!thinkContent) {
      return;
    }

    const nextActive = Boolean(
      active
      && hasThinkRuleHighlights(
        thinkContent
      )
    );

    thinkContent.classList.toggle(
      "has-rule-highlights",
      nextActive
    );

    const runtimeActive = Boolean(
      nextActive
      && shouldRevealThinkRuntimeCitations(
        thinkContent
      )
    );

    const runtimeState =
      runtimeActive
        ? thinkContent.__jinRuntimeCitationHighlightState
        : null;
    const runtimeSignature =
      buildThinkRuntimeCitationHighlightSignature(
        runtimeState
      );
    const activeChanged =
      thinkContent.__jinRuntimeCitationHighlightActive
      !== runtimeActive;
    const stateChanged =
      thinkContent.__jinRuntimeCitationHighlightSignature
      !== runtimeSignature;

    if (!activeChanged && !stateChanged) {
      return;
    }

    thinkContent.__jinRuntimeCitationHighlightActive =
      runtimeActive;
    thinkContent.__jinRuntimeCitationHighlightSignature =
      runtimeSignature;

    dispatchThinkRuntimeCitationHighlight(
      thinkContent,
      runtimeActive
    );

  }

  function syncAllThinkCitationHighlights() {

    const activeTarget =
      getActiveThinkCitationTarget();

    document
      .querySelectorAll(
        ".jin-think-content"
      )
      .forEach((thinkContent) => {
        setThinkCitationElementActive(
          thinkContent,
          thinkContent === activeTarget
        );
      });

  }

  function dispatchPersistentMemoryReferenceOverride(text) {

    window.dispatchEvent(
      new CustomEvent(
        MEMORY_REFERENCE_HIGHLIGHT_EVENT,
        {
          detail: {
            source: "persistent",
            text: String(text || ""),
            active: Boolean(
              String(text || "")
            ),
            origin: "think-citation-hover",
          },
        }
      )
    );

  }

  function restoreLatestPersistentMemoryReference() {

    dispatchPersistentMemoryReferenceOverride(
      latestPersistentMemoryReferenceText
    );

  }

  function activateHoveredThinkCitation(thinkContent) {

    if (
      !thinkContent
      || thinkContent === latestThinkCitationTarget
    ) {
      return;
    }

    hoveredThinkCitationTarget =
      thinkContent;

    dispatchPersistentMemoryReferenceOverride(
      thinkContent.__jinThinkRawText
      || thinkContent.textContent
      || ""
    );

    syncAllThinkCitationHighlights();

  }

  function deactivateHoveredThinkCitation(thinkContent) {

    if (
      !thinkContent
      || hoveredThinkCitationTarget !== thinkContent
    ) {
      return;
    }

    hoveredThinkCitationTarget = null;

    restoreLatestPersistentMemoryReference();
    syncAllThinkCitationHighlights();

  }

  function bindThinkCitationHover(thinkContent) {

    if (
      !thinkContent
      || thinkContent.__jinCitationHoverBound
    ) {
      return;
    }

    thinkContent.__jinCitationHoverBound = true;

    thinkContent.addEventListener(
      "mouseenter",
      () => {
        activateHoveredThinkCitation(
          thinkContent
        );
      }
    );

    thinkContent.addEventListener(
      "mouseleave",
      () => {
        deactivateHoveredThinkCitation(
          thinkContent
        );
      }
    );

  }

  function handlePersistentMemoryReferenceHighlight(event) {

    const detail =
      event && event.detail || {};

    if (
      detail.source !== "persistent"
      || detail.origin === "think-citation-hover"
    ) {
      return;
    }

    latestPersistentMemoryReferenceText =
      detail.active === false
        ? ""
        : String(detail.text || "");

  }

  function resetThinkCitationHighlightTurn() {

    latestThinkCitationTarget = null;
    hoveredThinkCitationTarget = null;

    document
      .querySelectorAll(
        ".jin-think-content"
      )
      .forEach((thinkContent) => {
        setThinkCitationElementActive(
          thinkContent,
          false
        );
      });

  }

  function syncThinkRuntimeCitationHighlight(thinkContent) {

    setThinkCitationElementActive(
      thinkContent,
      thinkContent === getActiveThinkCitationTarget()
    );

  }

  function renderThinkRuleHighlights(job) {

    const element =
      job.element;

    if (
      !element
      || element.dataset.thinkId !== job.thinkId
    ) {
      return;
    }

    const text =
      job.text;
    const matches =
      resolveThinkRuleOverlaps(
        filterLiveActiveMemoryMatches(
          job.matches
        )
      );

    job.matches = matches;
    element.__jinThinkMatches = [...matches];

    if (!matches.length) {
      element.replaceChildren(
        document.createTextNode(text)
      );
      element.__jinHasRuleHighlights = false;
      element.__jinThinkTextNode = null;
      element.__jinRuntimeCitationHighlightState = null;

      updateThinkContentExpandedHeight(
        element
      );
      syncThinkRuntimeCitationHighlight(
        element
      );

      return false;
    }

    const fragment =
      document.createDocumentFragment();
    let cursor = 0;

    matches.forEach((match) => {
      const start = Math.max(
        0,
        Math.min(
          text.length,
          match.start
        )
      );
      const end = Math.max(
        start,
        Math.min(
          text.length,
          match.end
        )
      );

      if (start > cursor) {
        fragment.appendChild(
          document.createTextNode(
            text.slice(
              cursor,
              start
            )
          )
        );
      }

      const matchedText =
        text.slice(
          start,
          end
        );
      const span =
        document.createElement("span");

      span.className =
        getThinkCitationClassName(
          match
        );
      span.textContent =
        matchedText;
      span.title =
        buildThinkRuleTitle(
          match,
          matchedText
        );
      span.setAttribute(
        "aria-label",
        span.title
      );
      span.style.setProperty(
        "--think-match-score",
        String(
          Math.max(
            0,
            Math.min(
              1,
              Number(
                match.score || 0
              )
            )
          )
        )
      );

      fragment.appendChild(
        span
      );

      cursor = end;
    });

    if (cursor < text.length) {
      fragment.appendChild(
        document.createTextNode(
          text.slice(
            cursor
          )
        )
      );
    }

    element.replaceChildren(
      fragment
    );
    element.__jinHasRuleHighlights = true;
    element.__jinThinkTextNode = null;

    updateThinkContentExpandedHeight(
      element
    );

    element.__jinRuntimeCitationHighlightState =
      buildThinkRuntimeCitationHighlightState(
        matches
      );

    syncThinkRuntimeCitationHighlight(
      element
    );

    return true;

  }

  function refreshActiveMemoryCitationHighlights() {
    activeThinkRuleCitationJobs.forEach((job) => {
      job.matches = filterLiveActiveMemoryMatches(job.matches);
    });

    document
      .querySelectorAll(".jin-think-content")
      .forEach((thinkContent) => {
        if (!Array.isArray(thinkContent.__jinThinkMatches)) {
          return;
        }

        const thinkId =
          String(thinkContent.dataset.thinkId || "");
        const text = String(
          thinkContent.__jinThinkRawText
          || thinkContent.textContent
          || ""
        );

        if (!thinkId) {
          return;
        }

        renderThinkRuleHighlights({
          thinkId,
          element: thinkContent,
          text,
          matches: filterLiveActiveMemoryMatches(
            thinkContent.__jinThinkMatches
          ),
          done: true,
        });
      });

    syncAllThinkCitationHighlights();
  }

  function handleActiveMemoryRecordsChanged() {
    activeMemoryCitationRevision += 1;
    refreshActiveMemoryCitationHighlights();
  }

  function handleThinkRuleWorkerMessage(event) {

    const data =
      event.data
      || {};
    const thinkId =
      data.thinkId;
    const job =
      activeThinkRuleCitationJobs.get(
        thinkId
      );

    if (
      !job
      || !job.element
      || job.element.dataset.thinkId !== thinkId
    ) {
      return;
    }

    if (
      data.type === "ruleMatchesChunk"
    ) {
      job.matches = resolveThinkRuleOverlaps(
        [
          ...job.matches,
          ...(data.matches || []),
        ]
      );
      return;
    }

    if (
      data.type === "ruleMatchesDone"
    ) {
      job.done = true;
      renderThinkRuleHighlights(
        job
      );
      activeThinkRuleCitationJobs.delete(
        thinkId
      );
    }

  }

  function startThinkRuleCitationAnalysis(
    messageId,
    stream
  ) {

    if (
      !stream
      || !stream.group
      || !stream.group.createdThinking
      || !stream.group.thinkContent
      || !stream.thinking.trim()
    ) {
      return;
    }

    const thinkContent =
      stream.group.thinkContent;
    const thinkId =
      String(
        messageId
      );
    const text =
      stream.thinking;

    stream.__jinFastCitationFinalizing = true;
    try {
      updateStreamingRuntimeCitationHighlights(
        messageId,
        stream
      );
    } finally {
      stream.__jinFastCitationFinalizing = false;
    }
    const runtimeCitationIndex =
      ensureThinkRuntimeCitationIndex(
        stream
      );
    const finalFastCandidates =
      buildFastExactCitationCandidates(
        runtimeCitationIndex
      );
    const finalFastMatches =
      findFastExactCitationMatches(
        text,
        finalFastCandidates,
        {
          allowTerminalBoundary: true,
          scanStart: 0,
          previousLength: 0,
          requireNewText: false,
        }
      );

    stream.__jinFastCitationCandidates = finalFastCandidates;
    stream.__jinFastCitationActiveRevision = activeMemoryCitationRevision;
    stream.__jinFastCitationMatches =
      mergeFastCitationMatches(
        filterLiveActiveMemoryMatches(
          stream.__jinFastCitationMatches
        ),
        finalFastMatches
      );

    thinkContent.dataset.thinkId =
      thinkId;
    thinkContent.dataset.runtimeCitationIndex =
      String(
        runtimeCitationIndex
      );
    thinkContent.__jinThinkRawText =
      text;

    bindThinkCitationHover(
      thinkContent
    );

    latestThinkCitationTarget =
      thinkContent;

    if (thinkContent.__jinRuntimeCitationHighlightState) {
      thinkContent.__jinRuntimeCitationHighlightActive = false;
    }

    syncAllThinkCitationHighlights();

    activeThinkRuleCitationJobs.set(
      thinkId,
      {
        thinkId,
        element: thinkContent,
        text,
        runtimeCitationIndex,
        matches:
          Array.isArray(stream.__jinFastCitationMatches)
            ? [...stream.__jinFastCitationMatches]
            : [],
        done: false,
      }
    );

    loadThinkRuleCitationRegistry()
      .then((registry) => {
        const currentJob =
          activeThinkRuleCitationJobs.get(
            thinkId
          );

        if (
          !currentJob
          || !registry.enabled
          || !Array.isArray(
            registry.fragments
          )
          || thinkContent.dataset.thinkId !== thinkId
        ) {
          activeThinkRuleCitationJobs.delete(
            thinkId
          );
          return;
        }

        const fragments = [
          ...registry.fragments,
          ...buildRuntimeCitationFragments(
            currentJob.runtimeCitationIndex
          ),
          ...buildActiveMemoryCitationFragments(),
          // L-T deliberately does not enter fuzzy/semantic citation matching.
          // Its F-id and full key are already covered by the streaming exact
          // candidate path, which prevents incidental fact-value wording from
          // flashing the L-T panel/avatar.
        ];

        if (!fragments.length) {
          activeThinkRuleCitationJobs.delete(
            thinkId
          );
          return;
        }

        const worker =
          getThinkRuleCitationWorker();

        if (!worker) {
          activeThinkRuleCitationJobs.delete(
            thinkId
          );
          return;
        }

        worker.postMessage(
          {
            type: "analyzeThinkRules",
            thinkId,
            text,
            fragments,
          }
        );
      });

  }

  window.addEventListener(
    ACTIVE_MEMORY_RECORDS_CHANGED_EVENT,
    handleActiveMemoryRecordsChanged
  );

  window.addEventListener(
    MEMORY_REFERENCE_HIGHLIGHT_EVENT,
    handlePersistentMemoryReferenceHighlight
  );

  window.JinThinkCitations = {
    resetThinkCitationHighlightTurn,
    startThinkRuleCitationAnalysis,
    updateStreamingRuntimeCitationHighlights,
    syncThinkRuntimeCitationHighlight,
  };

})();
