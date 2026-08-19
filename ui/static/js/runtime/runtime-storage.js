(function () {

  window.JinRuntime = window.JinRuntime || {};

  const latestSavedSessionSnapshotStorageKey =
    "jin.latestSavedSessionSnapshot.v1";

  // One-time compatibility read for checkpoints created before L3 removal.
  const legacyLatestSavedSessionSnapshotStorageKey =
    "jin.latestSavedSessionMemory.v1";

  const retiredSavedSessionHistoryStorageKey =
    "jin.savedSessionMemoryHistory.v1";

  const runtimeSessionIdSessionStorageKey =
    "jin.runtimeSessionId.v1";

  const latestRuntimeMemoryStorageKeyPrefix =
    "jin.latestRuntimeMemory";

  const latestRuntimeMemoryStorageKeyVersion =
    "v1";

  const latestSavedRuntimeMemoryStorageKey =
    "jin.latestSavedRuntimeMemory.v1";

  const activeMemoryStorageKey =
    "jin.activeMemory.v1";

  const delayedMemoryReportsStorageKey =
    "jin.delayedMemoryReports.v1";

  const factsMemoryStorageKeyPrefix =
    "jin.factsMemory";

  const factsMemoryStorageKeyVersion =
    "v1";

  const savedRuntimeFallbackPath =
    "/saved_runtime.txt";

  let clonedRuntimeSessionId = null;
  let bootSourceRuntimeSessionId = null;
  let savedRuntimeFileFallback = null;
  let savedRuntimeFileFallbackLoaded = false;

  function normalizeFactsMemoryStatus(
    value
  ) {

    const status =
      String(value || "")
        .trim()
        .toLowerCase();

    return (
        status === "analyzed"
        || status === "analized"
      )
      ? "analyzed"
      : "pending";

  }


  function buildFactsMemoryContentHash(
    value
  ) {

    const text =
      String(value || "")
        .replace(/\s+/g, " ")
        .trim();

    let hash = 5381;

    for (let index = 0; index < text.length; index += 1) {
      hash =
        ((hash << 5) + hash)
        ^ text.charCodeAt(index);
    }

    return `h${(hash >>> 0).toString(36)}`;

  }


  function generateRuntimeSessionId() {

    if (
        window.crypto
        && typeof window.crypto.randomUUID === "function"
    ) {
      return window.crypto.randomUUID();
    }

    return [
      "session",
      Date.now().toString(36),
      Math.random().toString(36).slice(2, 10),
    ].join("-");

  }


  function generateShortRuntimeId(
    existingIds
  ) {

    const alphabet =
      "abcdefghijklmnopqrstuvwxyz0123456789";
    const used =
      new Set(
        Array.from(existingIds || [])
          .map(id => String(id || "").trim().toLowerCase())
          .filter(id => /^[a-z0-9]{6}$/.test(id))
      );

    for (let attempt = 0; attempt < 1000; attempt += 1) {
      let id = "";
      const randomValues =
        window.crypto && window.crypto.getRandomValues
          ? window.crypto.getRandomValues(new Uint8Array(6))
          : null;

      for (let index = 0; index < 6; index += 1) {
        const value =
          randomValues
            ? randomValues[index]
            : Math.floor(Math.random() * 256);

        id +=
          alphabet[value % alphabet.length];
      }

      if (!used.has(id)) {
        return id;
      }
    }

    return Math.random().toString(36).slice(2, 8).padEnd(6, "0");

  }


  function createRuntimeSessionId() {

    try {
      const storedSessionId =
        String(
          window.sessionStorage.getItem(
            runtimeSessionIdSessionStorageKey
          ) || ""
        ).trim();

      if (storedSessionId) {
        const newRuntimeSessionId =
          generateRuntimeSessionId();

        clonedRuntimeSessionId = storedSessionId;

        window.sessionStorage.setItem(
          runtimeSessionIdSessionStorageKey,
          newRuntimeSessionId
        );

        return newRuntimeSessionId;
      }

      const newRuntimeSessionId =
        generateRuntimeSessionId();

      window.sessionStorage.setItem(
        runtimeSessionIdSessionStorageKey,
        newRuntimeSessionId
      );

      return newRuntimeSessionId;
    } catch (error) {
      return generateRuntimeSessionId();
    }

  }


  let runtimeSessionId =
    createRuntimeSessionId();

  // Facts restored from an explicit saved session must keep using the
  // original factsMemory bucket. The live WebSocket/runtime session may
  // have its own id, but that must not fork or duplicate restored facts.
  let factsMemorySessionId =
    runtimeSessionId;

  let latestRuntimeMemoryStorageKey =
    getLatestRuntimeMemoryStorageKey(
      runtimeSessionId
    );

  window.jinRuntimeSessionId =
    runtimeSessionId;

  function getRuntimeSessionId() {

    return runtimeSessionId;

  }


  function getCurrentRuntimeSessionId() {

    return runtimeSessionId;

  }


  function getCurrentFactsMemorySessionId() {

    return factsMemorySessionId;

  }


  function setCurrentFactsMemorySessionId(
    nextFactsMemorySessionId
  ) {

    const normalizedSessionId =
      String(nextFactsMemorySessionId || "").trim();

    factsMemorySessionId =
      normalizedSessionId || runtimeSessionId;

    return factsMemorySessionId;

  }


  function getLatestRuntimeMemoryStorageKey(
    runtimeSessionId
  ) {

    return `${latestRuntimeMemoryStorageKeyPrefix}`
      + `.${runtimeSessionId}`
      + `.${latestRuntimeMemoryStorageKeyVersion}`;

  }


  function getCurrentLatestRuntimeMemoryStorageKey() {

    return latestRuntimeMemoryStorageKey;

  }


  function isLatestRuntimeMemoryKey(
    key
  ) {

    const prefix =
      `${latestRuntimeMemoryStorageKeyPrefix}.`;

    const suffix =
      `.${latestRuntimeMemoryStorageKeyVersion}`;

    return (
      typeof key === "string"
      && key.startsWith(prefix)
      && key.endsWith(suffix)
      && key.length > prefix.length + suffix.length
    );

  }


  function getSessionIdFromLatestRuntimeMemoryKey(
    key
  ) {

    const prefix =
      `${latestRuntimeMemoryStorageKeyPrefix}.`;

    const suffix =
      `.${latestRuntimeMemoryStorageKeyVersion}`;

    if (
        typeof key !== "string"
        || !key.startsWith(prefix)
        || !key.endsWith(suffix)
    ) {
      return "";
    }

    return key.slice(
      prefix.length,
      key.length - suffix.length
    );

  }


  function setRuntimeSessionId(
    nextRuntimeSessionId
  ) {

    const normalizedRuntimeSessionId =
      String(nextRuntimeSessionId || "").trim();

    if (!normalizedRuntimeSessionId) {
      return;
    }

    runtimeSessionId = normalizedRuntimeSessionId;
    window.jinRuntimeSessionId =
      runtimeSessionId;
    latestRuntimeMemoryStorageKey =
      getLatestRuntimeMemoryStorageKey(
        runtimeSessionId
      );

    try {
      window.sessionStorage.setItem(
        runtimeSessionIdSessionStorageKey,
        runtimeSessionId
      );
    } catch (error) {
      // Browser memory is helpful, not required for chat.
    }

  }


  function readBrowserMemory(
    key
  ) {

    try {
      return JSON.parse(
        window.localStorage.getItem(
          key
        ) || "null"
      );
    } catch (error) {
      return null;
    }

  }


  function writeBrowserMemory(
    key,
    value
  ) {

    try {
      window.localStorage.setItem(
        key,
        JSON.stringify(value)
      );
    } catch (error) {
      // Browser memory is helpful, not required for chat.
    }

  }


  function removeBrowserMemory(
    key
  ) {

    try {
      window.localStorage.removeItem(
        key
      );
    } catch (error) {
      // Browser memory is helpful, not required for chat.
    }

  }


  // The old multi-checkpoint L3 history has no runtime meaning anymore.
  removeBrowserMemory(
    retiredSavedSessionHistoryStorageKey
  );


  function stripRetiredRuntimeMemoryEntries(
    value
  ) {

    return String(value || "")
      .split(/\r?\n/)
      .filter((line) => (
        !/^\s*(?:-\s*)?l2_pattern_evidence_\d+\s*:/i.test(line)
      ))
      .join("\n")
      .trim();

  }


  function sanitizeRuntimeMemoryRecord(
    value
  ) {

    if (
        !value
        || typeof value !== "object"
        || Array.isArray(value)
    ) {
      return value;
    }

    const sanitized = {
      ...value,
      runtime_memory:
        stripRetiredRuntimeMemoryEntries(
          value.runtime_memory || ""
        ),
    };

    if (
        value.runtime_snapshot
        && typeof value.runtime_snapshot === "object"
        && !Array.isArray(value.runtime_snapshot)
    ) {
      const snapshot = {
        ...value.runtime_snapshot,
        raw_memory:
          stripRetiredRuntimeMemoryEntries(
            value.runtime_snapshot.raw_memory || ""
          ),
      };

      if (Array.isArray(value.runtime_snapshot.lines)) {
        snapshot.lines =
          value.runtime_snapshot.lines.filter((line) => (
            !line
            || typeof line !== "object"
            || !/^l2_pattern_evidence_\d+$/i.test(
              String(line.key || "").trim()
            )
          ));
      }

      sanitized.runtime_snapshot = snapshot;
    }

    return sanitized;

  }

  function readLatestRuntimeMemory() {

    return sanitizeRuntimeMemoryRecord(
      readBrowserMemory(
        latestRuntimeMemoryStorageKey
      )
    );

  }


  function writeLatestRuntimeMemory(
    value
  ) {

    value = sanitizeRuntimeMemoryRecord(value);

    const normalizedValue =
      (
        value
        && typeof value === "object"
        && !Array.isArray(value)
      )
        ? {
            ...value,
            session_id: runtimeSessionId,
            booted_from_session_id:
              String(
                value.booted_from_session_id
                || bootSourceRuntimeSessionId
                || ""
              ).trim()
              || null,
            previous_session_id:
              String(
                value.previous_session_id
                || value.booted_from_session_id
                || bootSourceRuntimeSessionId
                || ""
              ).trim()
              || null,
          }
        : value;

    if (
        normalizedValue
        && normalizedValue.runtime_snapshot
        && typeof normalizedValue.runtime_snapshot === "object"
    ) {
      normalizedValue.runtime_snapshot = {
        ...normalizedValue.runtime_snapshot,
        session_id: runtimeSessionId,
        booted_from_session_id:
          normalizedValue.booted_from_session_id,
        previous_session_id:
          normalizedValue.previous_session_id,
      };
    }

    writeBrowserMemory(
      latestRuntimeMemoryStorageKey,
      normalizedValue
    );

  }


  function normalizeSavedSessionSnapshot(
    value
  ) {

    if (
        !value
        || typeof value !== "object"
        || Array.isArray(value)
    ) {
      return null;
    }

    return {
      version: Number(value.version || 1),
      session_id:
        String(value.session_id || runtimeSessionId || "").trim(),
      previous_session_id:
        String(value.previous_session_id || "").trim() || null,
      saved_at:
        String(value.saved_at || "").trim(),
      loaded_memory_ids:
        Array.isArray(value.loaded_memory_ids)
          ? value.loaded_memory_ids
              .map(item => String(item || "").trim())
              .filter(Boolean)
          : [],
      session_snapshot:
        (
          value.session_snapshot
          && typeof value.session_snapshot === "object"
          && !Array.isArray(value.session_snapshot)
        )
          ? {
              ...value.session_snapshot,
            }
          : {},
    };

  }


  function readLatestSavedSessionSnapshot() {

    const current =
      normalizeSavedSessionSnapshot(
        readBrowserMemory(
          latestSavedSessionSnapshotStorageKey
        )
      );

    if (current) {
      return current;
    }

    const legacy =
      normalizeSavedSessionSnapshot(
        readBrowserMemory(
          legacyLatestSavedSessionSnapshotStorageKey
        )
      );

    if (!legacy) {
      return null;
    }

    writeBrowserMemory(
      latestSavedSessionSnapshotStorageKey,
      legacy
    );
    removeBrowserMemory(
      legacyLatestSavedSessionSnapshotStorageKey
    );

    return legacy;

  }


  function writeLatestSavedSessionSnapshot(
    value
  ) {

    writeBrowserMemory(
      latestSavedSessionSnapshotStorageKey,
      normalizeSavedSessionSnapshot(value)
    );
    removeBrowserMemory(
      legacyLatestSavedSessionSnapshotStorageKey
    );

  }


  function readLatestSavedRuntimeMemory() {

    return sanitizeRuntimeMemoryRecord(
      readBrowserMemory(
        latestSavedRuntimeMemoryStorageKey
      )
    );

  }


  function normalizeActiveMemoryRecords(value) {

    const source =
      Array.isArray(value)
        ? value
        : String(value || "").split(/\r?\n/);

    const records = [];
    const seen = new Set();

    source.forEach(function (record) {
      const text = String(record || "").trim();

      if (!/^active_memory(?:_\d+)?\s*:/i.test(text)) {
        return;
      }

      if (seen.has(text)) {
        return;
      }

      seen.add(text);
      records.push(text);
    });

    return records;

  }


  function readActiveMemoryRecords() {

    return normalizeActiveMemoryRecords(
      readBrowserMemory(
        activeMemoryStorageKey
      )
    );

  }


  function writeActiveMemoryRecords(
    records
  ) {

    writeBrowserMemory(
      activeMemoryStorageKey,
      normalizeActiveMemoryRecords(records)
    );

  }


  function clearActiveMemoryRecords() {

    removeBrowserMemory(
      activeMemoryStorageKey
    );

    return [];

  }


  function appendActiveMemoryRecords(
    records
  ) {

    const current =
      readActiveMemoryRecords();

    writeActiveMemoryRecords(
      current.concat(
        normalizeActiveMemoryRecords(records)
      )
    );

    return readActiveMemoryRecords();

  }


  function replaceActiveMemoryRecordById(
    activeMemoryId,
    record
  ) {

    const needle =
      String(activeMemoryId || "")
        .trim()
        .toLowerCase();
    const nextRecord = String(record || "").trim();

    if (!needle || !nextRecord) {
      return readActiveMemoryRecords();
    }

    let replaced = false;
    const nextRecords = readActiveMemoryRecords()
      .map((currentRecord) => {
        const text = String(currentRecord || "");

        if (
          replaced
          || !text.toLowerCase().includes(needle)
        ) {
          return currentRecord;
        }

        replaced = true;
        return nextRecord;
      });

    if (!replaced) {
      nextRecords.push(nextRecord);
    }

    writeActiveMemoryRecords(nextRecords);
    return readActiveMemoryRecords();

  }


  function removeActiveMemoryRecordById(
    activeMemoryId
  ) {

    const needle =
      String(activeMemoryId || "")
        .trim()
        .toLowerCase();

    if (!needle) {
      return readActiveMemoryRecords();
    }

    const kept = readActiveMemoryRecords()
      .filter(record => !String(record).toLowerCase().includes(needle));

    writeActiveMemoryRecords(
      kept
    );

    return kept;

  }


  function getFactsMemoryStorageKey(
    sessionId = factsMemorySessionId
  ) {

    const normalizedSessionId =
      String(sessionId || "").trim();

    return normalizedSessionId
      ? `${factsMemoryStorageKeyPrefix}`
        + `.${normalizedSessionId}`
        + `.${factsMemoryStorageKeyVersion}`
      : "";

  }


  function isFactsMemoryStorageKey(
    key
  ) {

    const prefix =
      `${factsMemoryStorageKeyPrefix}.`;

    const suffix =
      `.${factsMemoryStorageKeyVersion}`;

    return (
      typeof key === "string"
      && key.startsWith(prefix)
      && key.endsWith(suffix)
      && key.length > prefix.length + suffix.length
    );

  }


  function getSessionIdFromFactsMemoryStorageKey(
    key
  ) {

    if (!isFactsMemoryStorageKey(key)) {
      return "";
    }

    const prefix =
      `${factsMemoryStorageKeyPrefix}.`;

    const suffix =
      `.${factsMemoryStorageKeyVersion}`;

    return key.slice(
      prefix.length,
      key.length - suffix.length
    );

  }


  function isLegacyFactsMemoryValue(
    value
  ) {

    return (
      value
      && typeof value === "object"
      && !Array.isArray(value)
      && Object.keys(value).length === 1
      && value.fields
      && typeof value.fields === "object"
      && !Array.isArray(value.fields)
    );

  }


  function normalizeFactsMemory(
    value
  ) {

    if (
        !value
        || typeof value !== "object"
        || Array.isArray(value)
    ) {
      return {};
    }

    const source =
      isLegacyFactsMemoryValue(value)
        ? value.fields
        : value;

    const signals = {};

    Object.entries(source).forEach(
      function ([fieldKey, field]) {
        const normalizedKey =
          String(fieldKey || "").trim();

        if (
            !normalizedKey
            || !field
            || typeof field !== "object"
            || Array.isArray(field)
        ) {
          return;
        }

        const content =
          String(
            field.content || field.value || ""
          ).trim();

        if (!content) {
          return;
        }

        const contentHash =
          String(
            field.l4_content_hash || ""
          ).trim()
          || buildFactsMemoryContentHash(
            content
          );

        signals[normalizedKey] = {
          ...field,
          content,
          l4_status:
            normalizeFactsMemoryStatus(
              field.l4_status
            ),
          l4_content_hash: contentHash,
          l4_analyzed_at:
            normalizeFactsMemoryStatus(
              field.l4_status
            ) === "analyzed"
              ? String(field.l4_analyzed_at || "").trim()
              : "",
        };
      }
    );

    return signals;

  }


  function collectFactsMemoryRecords() {

    const records = [];

    try {
      for (let index = 0; index < window.localStorage.length; index += 1) {
        const storageKey =
          window.localStorage.key(index);

        if (!isFactsMemoryStorageKey(storageKey)) {
          continue;
        }

        const stored =
          readBrowserMemory(storageKey);

        const signals =
          normalizeFactsMemory(
            stored
          );

        const signalCount =
          Object.keys(signals).length;

        if (!signalCount) {
          continue;
        }

        if (isLegacyFactsMemoryValue(stored)) {
          writeBrowserMemory(
            storageKey,
            signals
          );
        }

        records.push({
          storage_key: storageKey,
          session_id:
            getSessionIdFromFactsMemoryStorageKey(
              storageKey
            ),
          signal_count: signalCount,
          signals: {
            ...signals,
          },
        });
      }
    } catch (error) {
      return [];
    }

    return records.sort(
      function (left, right) {
        const leftIsCurrent =
          left.session_id === factsMemorySessionId;

        const rightIsCurrent =
          right.session_id === factsMemorySessionId;

        if (leftIsCurrent !== rightIsCurrent) {
          return leftIsCurrent ? -1 : 1;
        }

        return String(left.session_id || "").localeCompare(
          String(right.session_id || "")
        );
      }
    );

  }

  function hasFactsMemoryForSession(
    sessionId
  ) {

    return Object.keys(
      readFactsMemory(
        sessionId
      )
    ).length > 0;

  }


  function canAppendFactsMemoryByStorageKey(
    storageKey
  ) {

    const sourceSessionId =
      getSessionIdFromFactsMemoryStorageKey(
        storageKey
      );

    const currentSessionId =
      getCurrentFactsMemorySessionId();

    if (
        !sourceSessionId
        || !currentSessionId
        || sourceSessionId === currentSessionId
        || hasFactsMemoryForSession(currentSessionId)
    ) {
      return false;
    }

    return hasFactsMemoryForSession(
      sourceSessionId
    );

  }


  function appendFactsMemoryByStorageKey(
    storageKey
  ) {

    if (!canAppendFactsMemoryByStorageKey(storageKey)) {
      return null;
    }

    const sourceSessionId =
      getSessionIdFromFactsMemoryStorageKey(
        storageKey
      );

    const currentSessionId =
      getCurrentFactsMemorySessionId();

    const signals =
      readFactsMemory(
        sourceSessionId
      );

    const targetStorageKey =
      getFactsMemoryStorageKey(
        currentSessionId
      );

    writeBrowserMemory(
      targetStorageKey,
      signals
    );

    removeBrowserMemory(
      storageKey
    );

    return {
      storage_key: targetStorageKey,
      session_id: currentSessionId,
      signal_count: Object.keys(signals).length,
      signals: {
        ...signals,
      },
    };

  }


  function clearFactsMemoryByStorageKey(
    storageKey
  ) {

    if (!isFactsMemoryStorageKey(storageKey)) {
      return false;
    }

    removeBrowserMemory(
      storageKey
    );

    return true;

  }


  function clearFactsMemorySessionIfFullyAnalyzed(
    sessionId,
    value
  ) {

    const normalizedSessionId =
      String(sessionId || "").trim();

    const currentSessionId =
      String(getCurrentFactsMemorySessionId() || "").trim();

    if (
        !normalizedSessionId
        || normalizedSessionId === currentSessionId
    ) {
      return false;
    }

    const key =
      getFactsMemoryStorageKey(
        normalizedSessionId
      );

    if (!key) {
      return false;
    }

    const signals =
      value === undefined
        ? readFactsMemory(
            normalizedSessionId
          )
        : normalizeFactsMemory(
            value
          );

    const signalKeys =
      Object.keys(signals);

    if (
        !signalKeys.length
        || !signalKeys.every(
          function (signalKey) {
            return signals[signalKey].l4_status === "analyzed";
          }
        )
    ) {
      return false;
    }

    removeBrowserMemory(
      key
    );

    return true;

  }


  function readFactsMemory(
    sessionId = factsMemorySessionId
  ) {

    const key =
      getFactsMemoryStorageKey(
        sessionId
      );

    const stored =
      key
        ? readBrowserMemory(key)
        : null;

    const signals =
      normalizeFactsMemory(
        stored
      );

    if (
        key
        && isLegacyFactsMemoryValue(stored)
    ) {
      writeBrowserMemory(
        key,
        signals
      );
    }

    return signals;

  }


  function writeFactsMemory(
    value,
    sessionId = factsMemorySessionId
  ) {

    const key =
      getFactsMemoryStorageKey(
        sessionId
      );

    const signals =
      normalizeFactsMemory(
        value
      );

    if (key) {
      writeBrowserMemory(
        key,
        signals
      );
    }

    return signals;

  }


  function mergeFactsMemoryFields(
    current,
    source
  ) {

    if (!current) {
      return {
        ...source,
      };
    }

    return {
      ...current,
      ...source,
    };

  }


  function activateFactsMemorySession(
    sourceSessionId
  ) {

    setCurrentFactsMemorySessionId(
      sourceSessionId
    );

    return readFactsMemory();

  }


  function removeFactsMemoryField(
    fieldKey,
    sessionId = factsMemorySessionId
  ) {

    const key =
      String(fieldKey || "").trim();

    const signals =
      readFactsMemory(
        sessionId
      );

    if (key) {
      delete signals[
        key
      ];
    }

    return writeFactsMemory(
      signals,
      sessionId
    );

  }

  function normalizeLongTermFactIds(
    value
  ) {

    const source =
      Array.isArray(value)
        ? value
        : [value];
    const seen = new Set();
    const factIds = [];

    source.forEach(function (item) {
      if (Array.isArray(item)) {
        normalizeLongTermFactIds(item).forEach(function (factId) {
          if (!seen.has(factId)) {
            seen.add(factId);
            factIds.push(factId);
          }
        });
        return;
      }

      const text =
        String(item || "").trim();

      if (text.startsWith("[") && text.endsWith("]")) {
        try {
          const parsed = JSON.parse(text);

          if (Array.isArray(parsed)) {
            normalizeLongTermFactIds(parsed).forEach(function (factId) {
              if (!seen.has(factId)) {
                seen.add(factId);
                factIds.push(factId);
              }
            });
            return;
          }
        } catch (_error) {
          // Fall through to token parsing.
        }
      }

      text
        .split(/[\s,;]+/)
        .forEach(function (candidate) {
          const factId =
            String(candidate || "")
              .trim()
              .replace(/^["'\[]+|["'\]]+$/g, "")
              .toUpperCase();

          if (
              !/^F[1-9]\d*$/.test(factId)
              || seen.has(factId)
          ) {
            return;
          }

          seen.add(factId);
          factIds.push(factId);
        });
    });

    return factIds;

  }


  function sortLongTermFactIdsByNumber(
    factIds
  ) {

    return [...factIds].sort(function (left, right) {
      return Number(String(left).slice(1))
        - Number(String(right).slice(1));
    });

  }


  function readDelayedLoadMetadata(
    report,
    key,
    fallbackValue
  ) {
    if (
        report
        && Object.prototype.hasOwnProperty.call(report, key)
    ) {
      return report[key];
    }

    const legacyPrefix = "append" + "ed";
    const legacyKeys = {
      loaded_times: `${legacyPrefix}_times`,
      load_streak: "append_streak",
      last_loaded_date: `last_${legacyPrefix}_date`,
      last_loaded_session_id: `last_${legacyPrefix}_session_id`,
      all_loaded_session_ids: `all_${legacyPrefix}_session_ids`,
    };
    const legacyKey = legacyKeys[key];

    return legacyKey && report
      ? report[legacyKey]
      : fallbackValue;
  }

  function normalizeDelayedMemoryAttachmentIds(
    value
  ) {

    const source =
      Array.isArray(value)
        ? value
        : [value];
    const attachmentIds = [];
    const seen = new Set();

    source.flat(Infinity).forEach((item) => {
      String(item || "")
        .split(/[,;\s]+/)
        .map((id) => id.trim().replace(/^[\[\]"']+|[\[\]"']+$/g, "").toLowerCase())
        .filter(Boolean)
        .forEach((id) => {
          if (
              !/^[a-z0-9]{6}$/.test(id)
              || seen.has(id)
          ) {
            return;
          }

          seen.add(id);
          attachmentIds.push(id);
        });
    });

    return attachmentIds;
  }

  function normalizeDelayedMemoryTags(value) {
    const source = Array.isArray(value) ? value : [value];
    const candidates = [];
    const tags = [];
    const seen = new Set();

    function collect(item) {
      if (Array.isArray(item)) {
        item.flat(Infinity).forEach(collect);
        return;
      }

      const text = String(item || "").trim();
      if (!text) {
        return;
      }

      if (text.startsWith("[") && text.endsWith("]")) {
        try {
          const parsed = JSON.parse(text);
          if (Array.isArray(parsed)) {
            parsed.forEach(collect);
            return;
          }
        } catch (_error) {
          // Loose legacy bracket syntax is handled below.
        }
      }

      text.split(/[,;\r\n]+/)
        .map(part => part.trim())
        .filter(Boolean)
        .forEach((part) => {
          const bracketed = part.startsWith("[") && part.endsWith("]");
          const hashtagCount = (part.match(/(^|\s)#/g) || []).length;

          if (bracketed) {
            const inner = part.slice(1, -1).trim();
            if (inner && !/["']/.test(inner)) {
              candidates.push(...inner.split(/\s+/));
              return;
            }
          }

          if (hashtagCount >= 2) {
            candidates.push(...part.split(/\s+/));
            return;
          }

          candidates.push(part);
        });
    }

    source.forEach(collect);

    candidates.forEach((candidate) => {
      let tag = String(candidate || "").trim();
      tag = tag.replace(/^[\[\]{}()"']+|[\[\]{}()"']+$/g, "").trim();
      tag = tag.replace(/^#+|#+$/g, "").trim();
      tag = tag.replace(/^[\[\]{}()"']+|[\[\]{}()"']+$/g, "").trim();

      if (!tag) {
        return;
      }

      const key = tag.toLocaleLowerCase();
      if (seen.has(key)) {
        return;
      }

      seen.add(key);
      tags.push(tag);
    });

    return tags;
  }

  function normalizeDelayedMemoryReports(
    value
  ) {

    if (
        !value
        || typeof value !== "object"
        || Array.isArray(value)
    ) {
      return {};
    }

    const reports = {};
    const usedKeys = new Set();

    Object.entries(value).forEach(
      function ([key, report]) {
        let normalizedKey =
          String(key || "").trim().toLowerCase();

        if (
            !normalizedKey
            || !report
            || typeof report !== "object"
            || Array.isArray(report)
        ) {
          return;
        }

        const title =
          String(report.title || "").trim();

        if (!title) {
          return;
        }

        if (
            !/^[a-z0-9]{6}$/.test(normalizedKey)
            || usedKeys.has(normalizedKey)
        ) {
          normalizedKey =
            generateShortRuntimeId(
              usedKeys
            );
        }

        usedKeys.add(
          normalizedKey
        );

        const createdDate =
          String(
            report.created_date
            || report.created_time
            || ""
          ).trim()
          || new Date().toISOString();

        reports[normalizedKey] = {
          title,
          summary:
            String(report.summary || "").trim(),
          tags:
            normalizeDelayedMemoryTags(report.tags),
          body:
            String(report.body || "").trim(),
          pinned:
            Boolean(report.pinned),
          anchor_fact_ids:
            normalizeLongTermFactIds(
              report.anchor_fact_ids
            ),
          facts_ids:
            sortLongTermFactIdsByNumber(
              normalizeLongTermFactIds(
                [
                  // Anchors only affect highlighting. The full list keeps
                  // normal numeric F-id order instead of promoting anchors.
                  report.facts_ids,
                  report.anchor_fact_ids,
                  report.absorbed_fact_ids,
                  report.long_term_facts_ids,
                ]
              )
            ),
          attachments_ids:
            normalizeDelayedMemoryAttachmentIds(
              report.attachments_ids
            ),
          created_session_id:
            String(report.created_session_id || "").trim(),
          created_time:
            String(report.created_time || "").trim()
            || createdDate,
          created_date:
            createdDate,
          loaded_times:
            normalizeDelayedMemoryCounter(
              readDelayedLoadMetadata(
                report,
                "loaded_times",
                0
              )
            ),
          load_streak:
            normalizeDelayedMemoryCounter(
              readDelayedLoadMetadata(
                report,
                "load_streak",
                0
              )
            ),
          last_loaded_date:
            String(
              readDelayedLoadMetadata(
                report,
                "last_loaded_date",
                ""
              ) || ""
            ).trim(),
          last_loaded_session_id:
            String(
              readDelayedLoadMetadata(
                report,
                "last_loaded_session_id",
                ""
              ) || ""
            ).trim(),
          all_loaded_session_ids:
            normalizeDelayedMemorySessionIds(
              readDelayedLoadMetadata(
                report,
                "all_loaded_session_ids",
                []
              )
            ),
        };
      }
    );

    return reports;

  }


  function normalizeDelayedMemoryCounter(
    value
  ) {

    const numericValue =
      Number(value || 0);

    return Number.isFinite(numericValue)
      ? Math.max(
          Math.floor(numericValue),
          0
        )
      : 0;

  }


  function normalizeDelayedMemorySessionIds(
    value
  ) {

    const source =
      Array.isArray(value)
        ? value
        : [];
    const seen = new Set();
    const sessionIds = [];

    source.forEach(function (item) {
      const sessionId =
        String(item || "").trim();

      if (
          !sessionId
          || seen.has(sessionId)
      ) {
        return;
      }

      seen.add(sessionId);
      sessionIds.push(sessionId);
    });

    return sessionIds;

  }


  function readDelayedMemoryReports() {

    const rawReports =
      readBrowserMemory(
        delayedMemoryReportsStorageKey
      );
    const reports =
      normalizeDelayedMemoryReports(
        rawReports
      );

    if (
        rawReports
        && typeof rawReports === "object"
        && !Array.isArray(rawReports)
        && JSON.stringify(rawReports) !== JSON.stringify(reports)
    ) {
      writeBrowserMemory(
        delayedMemoryReportsStorageKey,
        reports
      );
    }

    return reports;

  }


  function writeDelayedMemoryReports(
    reports
  ) {

    writeBrowserMemory(
      delayedMemoryReportsStorageKey,
      normalizeDelayedMemoryReports(
        reports
      )
    );

  }


  function mergeDelayedMemoryReports(
    reports
  ) {

    const current =
      readDelayedMemoryReports();

    writeDelayedMemoryReports({
      ...current,
      ...normalizeDelayedMemoryReports(
        reports
      ),
    });

    return readDelayedMemoryReports();

  }


  function writeLatestSavedRuntimeMemory(
    value
  ) {

    value = sanitizeRuntimeMemoryRecord(value);

    const normalizedValue =
      (
        value
        && typeof value === "object"
        && !Array.isArray(value)
      )
        ? {
            ...value,
            session_id:
              String(value.session_id || runtimeSessionId || "").trim(),
            previous_session_id:
              String(
                value.previous_session_id
                || value.booted_from_session_id
                || bootSourceRuntimeSessionId
                || ""
              ).trim() || null,
          }
        : value;

    if (
        normalizedValue
        && normalizedValue.runtime_snapshot
        && typeof normalizedValue.runtime_snapshot === "object"
    ) {
      normalizedValue.runtime_snapshot = {
        ...normalizedValue.runtime_snapshot,
        session_id:
          normalizedValue.session_id || runtimeSessionId,
        previous_session_id:
          normalizedValue.previous_session_id,
      };
    }

    writeBrowserMemory(
      latestSavedRuntimeMemoryStorageKey,
      normalizedValue
    );

  }


  function setBootSourceRuntimeSessionId(
    sourceRuntimeSessionId
  ) {

    bootSourceRuntimeSessionId =
      String(sourceRuntimeSessionId || "").trim()
      || null;

    return bootSourceRuntimeSessionId;

  }



  function buildPersistedRuntimeSnapshot(
    snapshot
  ) {

    if (
        !snapshot
        || typeof snapshot !== "object"
    ) {
      return null;
    }

    return {
      ...snapshot,
      session_id: runtimeSessionId,
      booted_from_session_id:
        bootSourceRuntimeSessionId,
      previous_session_id:
        bootSourceRuntimeSessionId,
      persisted_memory_scores: true,
    };

  }


  function cloneRuntimeMemoryToCurrentSession(
    runtimeMemory
  ) {

    if (
        !runtimeMemory
        || typeof runtimeMemory !== "object"
        || readBrowserMemory(latestRuntimeMemoryStorageKey)
    ) {
      return;
    }

    setBootSourceRuntimeSessionId(
      runtimeMemory.session_id
    );

    writeLatestRuntimeMemory({
      version:
        runtimeMemory.version || 1,
      // This is a snapshot of the new session at boot time, not a copy of
      // the predecessor timestamp. That guarantees newest-by-saved_at
      // resolves to the direct previous session on the following boot.
      saved_at:
        new Date().toISOString(),
      runtime_memory:
        runtimeMemory.runtime_memory || "",
      runtime_memory_updates:
        runtimeMemory.runtime_memory_updates || 0,
      runtime_snapshot:
        buildPersistedRuntimeSnapshot(
          runtimeMemory.runtime_snapshot
        ),
      cloned_from_session_id:
        runtimeMemory.session_id || null,
      previous_session_id:
        runtimeMemory.session_id || null,
    });

  }


  function cloneRuntimeMemoryFromSessionId(
    sourceRuntimeSessionId
  ) {

    const normalizedSourceRuntimeSessionId =
      String(sourceRuntimeSessionId || "").trim();

    if (!normalizedSourceRuntimeSessionId) {
      return;
    }

    const sourceRuntimeMemory =
      readBrowserMemory(
        getLatestRuntimeMemoryStorageKey(
          normalizedSourceRuntimeSessionId
        )
      );

    cloneRuntimeMemoryToCurrentSession(
      sourceRuntimeMemory
    );

  }


  function cloneBootRuntimeMemoryIfNeeded() {

    if (!clonedRuntimeSessionId) {
      return;
    }

    // Do not copy live latestRuntimeMemory across a page reload. That cache is
    // only safe for in-page WebSocket reconnects. Saved session restore uses
    // latest saved checkpoint/latestSavedRuntimeMemory instead.
    clonedRuntimeSessionId = null;

  }


  function collectOtherLatestRuntimeMemorySnapshots() {

    const snapshots = [];

    try {
      for (
        let index = window.localStorage.length - 1;
        index >= 0;
        index -= 1
      ) {
        const key =
          window.localStorage.key(index);

        if (
            !isLatestRuntimeMemoryKey(key)
            || key === latestRuntimeMemoryStorageKey
        ) {
          continue;
        }

        const keySessionId =
          getSessionIdFromLatestRuntimeMemoryKey(
            key
          );

        if (keySessionId === runtimeSessionId) {
          continue;
        }

        const value =
          sanitizeRuntimeMemoryRecord(
            readBrowserMemory(
              key
            )
          );

        snapshots.push({
          key,
          key_session_id: keySessionId,
          session_id:
            (
              value
              && value.session_id
            )
            || keySessionId
            || null,
          saved_at:
            (
              value
              && value.saved_at
            )
            || null,
          runtime_memory_updates:
            (
              value
              && value.runtime_memory_updates
            )
            || 0,
          runtime_memory:
            (
              value
              && value.runtime_memory
            )
            || "",
          runtime_snapshot:
            (
              value
              && value.runtime_snapshot
              && typeof value.runtime_snapshot === "object"
            )
              ? value.runtime_snapshot
              : null,
          booted_from_session_id:
            (
              value
              && value.booted_from_session_id
            )
            || null,
          previous_session_id:
            (
              value
              && (
                value.previous_session_id
                || value.booted_from_session_id
              )
            )
            || null,
        });
      }
    } catch (error) {
      return [];
    }

    return snapshots.sort(
      function (
        left,
        right,
      ) {
        return String(
          right.saved_at || ""
        ).localeCompare(
          String(left.saved_at || "")
        );
      }
    );

  }


  function readLatestPreviousRuntimeMemory() {

    const snapshots =
      collectOtherLatestRuntimeMemorySnapshots();

    if (!snapshots.length) {
      return null;
    }

    const latest = snapshots[0];
    const value = readBrowserMemory(
      latest.key
    );

    if (
        !value
        || typeof value !== "object"
        || Array.isArray(value)
    ) {
      return null;
    }

    const sourceSessionId =
      String(
        value.session_id
        || latest.key_session_id
        || ""
      ).trim();

    if (!sourceSessionId) {
      return null;
    }

    return {
      ...value,
      session_id: sourceSessionId,
      storage_key: latest.key,
    };

  }


  function clearOtherLatestRuntimeMemorySnapshots() {

    const snapshots =
      collectOtherLatestRuntimeMemorySnapshots();

    try {
      snapshots.forEach(
        function (
          snapshot
        ) {
          if (
              snapshot
              && snapshot.key
              && snapshot.key !== latestRuntimeMemoryStorageKey
          ) {
            window.localStorage.removeItem(
              snapshot.key
            );
          }
        }
      );
    } catch (error) {
      // Browser memory cleanup is helpful, not required for chat.
    }

    return {
      cleared: snapshots.length,
      keys: snapshots.map(
        function (
          snapshot
        ) {
          return snapshot.key;
        }
      ),
    };

  }


  function extractSavedRuntimeConstant(
    source,
    name
  ) {

    const normalizedSource =
      String(source || "").replace(
        /\r\n/g,
        "\n"
      );

    const markerIndex =
      normalizedSource.indexOf(
        name
      );

    if (markerIndex < 0) {
      return "";
    }

    const assignmentIndex =
      normalizedSource.indexOf(
        "=",
        markerIndex + name.length
      );

    if (assignmentIndex < 0) {
      return "";
    }

    const afterAssignment =
      normalizedSource.slice(
        assignmentIndex + 1
      );

    const openingMatch =
      afterAssignment.match(
        /["'`]/
      );

    if (!openingMatch) {
      return "";
    }

    const quote =
      openingMatch[0];

    const valueStart =
      assignmentIndex + 1 + openingMatch.index + 1;

    const closingIndex =
      normalizedSource.indexOf(
        `\n${quote}`,
        valueStart
      );

    if (closingIndex < 0) {
      return "";
    }

    return normalizedSource.slice(
      valueStart,
      closingIndex
    ).trim();

  }


  function parseSavedRuntimeText(
    source
  ) {

    const runtimeMemory =
      extractSavedRuntimeConstant(
        source,
        "SAVED_RUNTIME"
      );

    if (!runtimeMemory) {
      return null;
    }

    return {
      runtime_memory: runtimeMemory,
      source: "saved_runtime_txt",
    };

  }


  function buildSavedRuntimeFallback(
    memory
  ) {

    if (!memory) {
      return null;
    }

    const runtimeMemory =
      (
        memory.runtime_memory
        && String(memory.runtime_memory).trim()
      )
      || "";

    if (!runtimeMemory) {
      return null;
    }

    const source =
      memory.source || "saved_runtime_txt";
    const savedAt =
      new Date().toISOString();

    return {
      source,
      latest_saved_runtime_memory: {
        version: 1,
        saved_at: savedAt,
        runtime_memory: runtimeMemory,
        runtime_memory_updates: 1,
        runtime_snapshot: null,
      },
      runtime_memory: {
        version: 1,
        saved_at: savedAt,
        runtime_memory: runtimeMemory,
        runtime_memory_updates: 1,
        runtime_snapshot: null,
      },
    };

  }


  function getSavedRuntimeMemoryFallback() {

    return buildSavedRuntimeFallback(
      savedRuntimeFileFallback
    );

  }


  async function loadSavedRuntimeMemoryFallback() {

    if (savedRuntimeFileFallbackLoaded) {
      return savedRuntimeFileFallback;
    }

    savedRuntimeFileFallbackLoaded = true;

    if (
        !window.fetch
        || !savedRuntimeFallbackPath
    ) {
      return null;
    }

    try {
      const response =
        await window.fetch(
          savedRuntimeFallbackPath,
          {
            cache: "no-store",
          }
        );

      if (!response.ok) {
        return null;
      }

      savedRuntimeFileFallback =
        parseSavedRuntimeText(
          await response.text()
        );
    } catch (error) {
      savedRuntimeFileFallback = null;
    }

    return savedRuntimeFileFallback;

  }


  const storage = {
    keys: {
      latestSavedSessionSnapshotStorageKey,
      runtimeSessionIdSessionStorageKey,
      latestRuntimeMemoryStorageKeyPrefix,
      latestRuntimeMemoryStorageKeyVersion,
      latestSavedRuntimeMemoryStorageKey,
      activeMemoryStorageKey,
      delayedMemoryReportsStorageKey,
      factsMemoryStorageKeyPrefix,
      factsMemoryStorageKeyVersion,
      savedRuntimeFallbackPath,
    },
    getRuntimeSessionId,
    getCurrentRuntimeSessionId,
    getCurrentFactsMemorySessionId,
    setCurrentFactsMemorySessionId,
    setRuntimeSessionId,
    generateRuntimeSessionId,
    getLatestRuntimeMemoryStorageKey,
    getCurrentLatestRuntimeMemoryStorageKey,
    isLatestRuntimeMemoryKey,
    getSessionIdFromLatestRuntimeMemoryKey,
    readBrowserMemory,
    writeBrowserMemory,
    removeBrowserMemory,
    readLatestRuntimeMemory,
    writeLatestRuntimeMemory,
    readLatestSavedSessionSnapshot,
    writeLatestSavedSessionSnapshot,
    readLatestSavedRuntimeMemory,
    writeLatestSavedRuntimeMemory,
    normalizeActiveMemoryRecords,
    readActiveMemoryRecords,
    writeActiveMemoryRecords,
    clearActiveMemoryRecords,
    appendActiveMemoryRecords,
    replaceActiveMemoryRecordById,
    removeActiveMemoryRecordById,
    getFactsMemoryStorageKey,
    isFactsMemoryStorageKey,
    getSessionIdFromFactsMemoryStorageKey,
    collectFactsMemoryRecords,
    hasFactsMemoryForSession,
    canAppendFactsMemoryByStorageKey,
    appendFactsMemoryByStorageKey,
    clearFactsMemoryByStorageKey,
    clearFactsMemorySessionIfFullyAnalyzed,
    readFactsMemory,
    writeFactsMemory,
    buildFactsMemoryContentHash,
    activateFactsMemorySession,
    removeFactsMemoryField,
    normalizeDelayedMemoryTags,
    normalizeDelayedMemoryReports,
    readDelayedMemoryReports,
    writeDelayedMemoryReports,
    mergeDelayedMemoryReports,
    setBootSourceRuntimeSessionId,
    buildPersistedRuntimeSnapshot,
    cloneRuntimeMemoryToCurrentSession,
    cloneRuntimeMemoryFromSessionId,
    cloneBootRuntimeMemoryIfNeeded,
    collectOtherLatestRuntimeMemorySnapshots,
    readLatestPreviousRuntimeMemory,
    clearOtherLatestRuntimeMemorySnapshots,
    extractSavedRuntimeConstant,
    parseSavedRuntimeText,
    buildSavedRuntimeFallback,
    getSavedRuntimeMemoryFallback,
    loadSavedRuntimeMemoryFallback,
  };

  window.JinRuntime.storage = storage;
  window.jinSavedRuntimeFallbackReady =
    loadSavedRuntimeMemoryFallback();

}());
