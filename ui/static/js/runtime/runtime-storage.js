(function () {

  window.JinRuntime = window.JinRuntime || {};

  const latestSavedSessionMemoryStorageKey =
    "jin.latestSavedSessionMemory.v1";

  const savedSessionMemoryHistoryStorageKey =
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


  function readLatestRuntimeMemory() {

    return readBrowserMemory(
      latestRuntimeMemoryStorageKey
    );

  }


  function writeLatestRuntimeMemory(
    value
  ) {

    writeBrowserMemory(
      latestRuntimeMemoryStorageKey,
      value
    );

  }


  function readLatestSavedSessionMemory() {

    return readBrowserMemory(
      latestSavedSessionMemoryStorageKey
    );

  }


  function writeLatestSavedSessionMemory(
    value
  ) {

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
          }
        : value;

    archiveLatestSavedSessionMemory();

    writeBrowserMemory(
      latestSavedSessionMemoryStorageKey,
      normalizedValue
    );

  }


  function readSavedSessionMemoryHistory() {

    const history =
      readBrowserMemory(
        savedSessionMemoryHistoryStorageKey
      );

    return Array.isArray(history)
      ? history.filter(
          item => item && typeof item === "object"
        )
      : [];

  }


  function writeSavedSessionMemoryHistory(
    history
  ) {

    writeBrowserMemory(
      savedSessionMemoryHistoryStorageKey,
      Array.isArray(history)
        ? history.filter(
            item => item && typeof item === "object"
          )
        : []
    );

  }


  function archiveLatestSavedSessionMemory() {

    const previous =
      readLatestSavedSessionMemory();

    if (
        !previous
        || typeof previous !== "object"
        || Array.isArray(previous)
    ) {
      return;
    }

    writeSavedSessionMemoryHistory(
      readSavedSessionMemoryHistory().concat([
        {
          ...previous,
          archived_at: new Date().toISOString(),
        },
      ])
    );

  }


  function readLatestSavedRuntimeMemory() {

    return readBrowserMemory(
      latestSavedRuntimeMemoryStorageKey
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
            Array.isArray(report.tags)
              ? report.tags
                  .map(tag => String(tag || "").trim())
                  .filter(Boolean)
              : String(report.tags || "")
                  .split(",")
                  .map(tag => tag.trim())
                  .filter(Boolean),
          body:
            String(report.body || "").trim(),
          pinned:
            Boolean(report.pinned),
          anchor_fact_ids:
            normalizeLongTermFactIds(
              report.anchor_fact_ids
            ),
          facts_ids:
            normalizeLongTermFactIds(
              [
                report.anchor_fact_ids,
                report.facts_ids,
                report.absorbed_fact_ids,
                report.long_term_facts_ids,
              ]
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

    writeBrowserMemory(
      latestSavedRuntimeMemoryStorageKey,
      value
    );

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
      persisted_pheromone_strength: true,
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

    writeBrowserMemory(
      latestRuntimeMemoryStorageKey,
      {
        version:
          runtimeMemory.version || 1,
        session_id: runtimeSessionId,
        saved_at:
          runtimeMemory.saved_at
          || new Date().toISOString(),
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
      }
    );

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
    // latestSavedSessionMemory/latestSavedRuntimeMemory instead.
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
          readBrowserMemory(
            key
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

    const sessionMemory =
      extractSavedRuntimeConstant(
        source,
        "SAVED_SESSION"
      );

    if (
        !runtimeMemory
        && !sessionMemory
    ) {
      return null;
    }

    return {
      runtime_memory: runtimeMemory,
      session_memory: sessionMemory,
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

    const sessionMemory =
      (
        memory.session_memory
        && String(memory.session_memory).trim()
      )
      || "";

    if (
        !runtimeMemory
        && !sessionMemory
    ) {
      return null;
    }

    const source =
      memory.source || "saved_runtime_txt";

    const savedAt =
      new Date().toISOString();

    return {
      source: source,
      session_memory: sessionMemory
        ? {
            version: 1,
            explicit_save: true,
            saved_at: savedAt,
            session_memory: sessionMemory,
            session_memory_updates: 1,
          }
        : null,
      latest_saved_runtime_memory: runtimeMemory
        ? {
            version: 1,
            explicit_save: true,
            saved_at: savedAt,
            runtime_memory: runtimeMemory,
            runtime_memory_updates: 1,
            runtime_snapshot: null,
          }
        : null,
      runtime_memory: runtimeMemory
        ? {
            version: 1,
            saved_at: savedAt,
            runtime_memory: runtimeMemory,
            runtime_memory_updates: 1,
            runtime_snapshot: null,
          }
        : null,
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
      latestSavedSessionMemoryStorageKey,
      savedSessionMemoryHistoryStorageKey,
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
    readLatestSavedSessionMemory,
    writeLatestSavedSessionMemory,
    readSavedSessionMemoryHistory,
    writeSavedSessionMemoryHistory,
    readLatestSavedRuntimeMemory,
    writeLatestSavedRuntimeMemory,
    normalizeActiveMemoryRecords,
    readActiveMemoryRecords,
    writeActiveMemoryRecords,
    clearActiveMemoryRecords,
    appendActiveMemoryRecords,
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
    normalizeDelayedMemoryReports,
    readDelayedMemoryReports,
    writeDelayedMemoryReports,
    mergeDelayedMemoryReports,
    buildPersistedRuntimeSnapshot,
    cloneRuntimeMemoryToCurrentSession,
    cloneRuntimeMemoryFromSessionId,
    cloneBootRuntimeMemoryIfNeeded,
    collectOtherLatestRuntimeMemorySnapshots,
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
