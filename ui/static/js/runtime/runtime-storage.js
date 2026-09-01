(function () {

  window.JinRuntime = window.JinRuntime || {};

  const liveRuntimeMemoryStorageKey =
    "jin.liveRuntimeMemory.v2";

  const sessionCheckpointStorageKey =
    "jin.sessionCheckpoint.v2";

  const legacyLatestSavedSessionSnapshotStorageKey =
    "jin.latestSavedSessionSnapshot.v1";

  // One-time compatibility read for checkpoints created before L3 removal.
  const legacyL3SavedSessionSnapshotStorageKey =
    "jin.latestSavedSessionMemory.v1";

  const retiredSavedSessionHistoryStorageKey =
    "jin.savedSessionMemoryHistory.v1";

  const runtimeSessionIdSessionStorageKey =
    "jin.runtimeSessionId.v1";

  const legacyLatestRuntimeMemoryStorageKeyPrefix =
    "jin.latestRuntimeMemory";

  const legacyLatestRuntimeMemoryStorageKeyVersion =
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
    "v2";

  let bootSourceRuntimeSessionId = null;
  let sessionCheckpointMigrationAttempted = false;
  let sessionCheckpointUserActivityAt = 0;

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

    const anonymousMode =
      window.JinRuntime
      && window.JinRuntime.anonymousMode;
    const anonymousSessionId =
      anonymousMode
      && typeof anonymousMode.getSessionId === "function"
        ? String(anonymousMode.getSessionId() || "").trim()
        : "";

    if (anonymousSessionId) {
      try {
        window.sessionStorage.setItem(
          runtimeSessionIdSessionStorageKey,
          anonymousSessionId
        );
      } catch (error) {
        // The runtime id still works even when browser storage is unavailable.
      }
      return anonymousSessionId;
    }

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

  window.jinRuntimeSessionId =
    runtimeSessionId;

  // sessionStorage can be copied into a new tab and survives reload. The live
  // FRAME is valid only inside this already-running page, so discard any copied
  // or reloaded value before bootstrap. Soft WebSocket reconnect does not
  // re-execute this module and keeps using the value written afterwards.
  removeSessionMemory(
    liveRuntimeMemoryStorageKey
  );

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


  function getLegacyLatestRuntimeMemoryStorageKey(
    runtimeSessionId
  ) {

    return `${legacyLatestRuntimeMemoryStorageKeyPrefix}`
      + `.${runtimeSessionId}`
      + `.${legacyLatestRuntimeMemoryStorageKeyVersion}`;

  }


  function isLegacyLatestRuntimeMemoryKey(
    key
  ) {

    const prefix =
      `${legacyLatestRuntimeMemoryStorageKeyPrefix}.`;

    const suffix =
      `.${legacyLatestRuntimeMemoryStorageKeyVersion}`;

    return (
      typeof key === "string"
      && key.startsWith(prefix)
      && key.endsWith(suffix)
      && key.length > prefix.length + suffix.length
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
    try {
      window.sessionStorage.setItem(
        runtimeSessionIdSessionStorageKey,
        runtimeSessionId
      );
    } catch (error) {
      // Browser memory is helpful, not required for chat.
    }

  }


  function shouldIsolateAnonymousStorage() {

    return Boolean(
      window.JinRuntime
      && window.JinRuntime.anonymousMode
      && typeof window.JinRuntime.anonymousMode.shouldIsolateStorage === "function"
      && window.JinRuntime.anonymousMode.shouldIsolateStorage()
    );

  }


  function isAnonymousModeEnabled() {

    return Boolean(
      window.JinRuntime
      && window.JinRuntime.anonymousMode
      && typeof window.JinRuntime.anonymousMode.isEnabled === "function"
      && window.JinRuntime.anonymousMode.isEnabled()
    );

  }


  function getActiveMemoryStorageKey() {

    return activeMemoryStorageKey;

  }


  function getDelayedMemoryReportsStorageKey() {

    return delayedMemoryReportsStorageKey;

  }


  function readAnonymousSessionSnapshot() {

    const anonymousMode =
      window.JinRuntime
      && window.JinRuntime.anonymousMode;

    return (
      anonymousMode
      && typeof anonymousMode.readSnapshot === "function"
    )
      ? anonymousMode.readSnapshot()
      : null;

  }


  function updateAnonymousSessionSnapshotField(
    field,
    value
  ) {

    const anonymousMode =
      window.JinRuntime
      && window.JinRuntime.anonymousMode;

    return Boolean(
      anonymousMode
      && typeof anonymousMode.updateSnapshotField === "function"
      && anonymousMode.updateSnapshotField(field, value)
    );

  }


  function readFactsStorageMemory(
    key
  ) {

    return shouldIsolateAnonymousStorage()
      ? readSessionMemory(key)
      : readBrowserMemory(key);

  }


  function writeFactsStorageMemory(
    key,
    value
  ) {

    if (shouldIsolateAnonymousStorage()) {
      writeSessionMemory(key, value);
      return;
    }

    writeBrowserMemory(key, value);

  }


  function removeFactsStorageMemory(
    key
  ) {

    if (shouldIsolateAnonymousStorage()) {
      removeSessionMemory(key);
      return;
    }

    removeBrowserMemory(key);

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
      return true;
    } catch (error) {
      console.warn("Failed to persist browser checkpoint", key, error);
      return false;
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


  function readSessionMemory(
    key
  ) {

    try {
      return JSON.parse(
        window.sessionStorage.getItem(
          key
        ) || "null"
      );
    } catch (error) {
      return null;
    }

  }


  function writeSessionMemory(
    key,
    value
  ) {

    try {
      window.sessionStorage.setItem(
        key,
        JSON.stringify(value)
      );
    } catch (error) {
      // Ephemeral runtime state is helpful, not required for chat.
    }

  }


  function removeSessionMemory(
    key
  ) {

    try {
      window.sessionStorage.removeItem(
        key
      );
    } catch (error) {
      // Ephemeral runtime state is helpful, not required for chat.
    }

  }


  // The old multi-checkpoint L3 history has no runtime meaning anymore.
  // Do not mutate the normal browser profile while anonymous detection is
  // pending or anonymous isolation is active.
  if (!shouldIsolateAnonymousStorage()) {
    removeBrowserMemory(
      retiredSavedSessionHistoryStorageKey
    );
  }


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
      readSessionMemory(
        liveRuntimeMemoryStorageKey
      )
    );

  }


  function writeLatestRuntimeMemory(
    value
  ) {

    const previousValue =
      sanitizeRuntimeMemoryRecord(
        readSessionMemory(
          liveRuntimeMemoryStorageKey
        )
      );

    value = sanitizeRuntimeMemoryRecord(value);

    if (
        value
        && typeof value === "object"
        && !Array.isArray(value)
        && previousValue
        && typeof previousValue === "object"
        && !Array.isArray(previousValue)
    ) {
      const previousCommittedAt =
        String(
          previousValue.conversation_committed_at
          || ""
        ).trim();

      if (
          previousCommittedAt
          && !String(
            value.conversation_committed_at
            || ""
          ).trim()
      ) {
        value.conversation_committed_at =
          previousCommittedAt;
      }

      if (
          previousValue.session_snapshot
          && typeof previousValue.session_snapshot === "object"
          && !Array.isArray(previousValue.session_snapshot)
          && !(
            value.session_snapshot
            && typeof value.session_snapshot === "object"
            && !Array.isArray(value.session_snapshot)
          )
      ) {
        value.session_snapshot = {
          ...previousValue.session_snapshot,
        };
      }
    }

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
      const snapshotSessionId =
        String(
          normalizedValue.runtime_snapshot.session_id
          || ""
        ).trim()
        || runtimeSessionId;

      normalizedValue.runtime_snapshot = {
        ...normalizedValue.runtime_snapshot,
        session_id: snapshotSessionId,
        booted_from_session_id:
          normalizedValue.booted_from_session_id,
        previous_session_id:
          normalizedValue.previous_session_id,
      };
    }

    writeSessionMemory(
      liveRuntimeMemoryStorageKey,
      normalizedValue
    );

    if (shouldIsolateAnonymousStorage()) {
      updateAnonymousSessionSnapshotField(
        "frame_memory",
        normalizedValue || ""
      );
    }

  }


  function normalizeLegacySavedSessionSnapshot(
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
        String(value.session_id || "").trim(),
      previous_session_id:
        String(value.previous_session_id || "").trim() || null,
      saved_at:
        String(value.saved_at || "").trim(),
      conversation_committed_at:
        String(value.conversation_committed_at || "").trim(),
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


  function normalizeSessionCheckpointRecord(
    value
  ) {

    if (
        !value
        || typeof value !== "object"
        || Array.isArray(value)
    ) {
      return null;
    }

    if (String(value.state || "").trim() === "cleared") {
      return {
        version: 2,
        state: "cleared",
        cleared_at:
          String(value.cleared_at || "").trim(),
      };
    }

    const sessionId =
      String(value.session_id || "").trim();

    if (!sessionId) {
      return null;
    }

    return sanitizeRuntimeMemoryRecord({
      version: 2,
      state: "checkpoint",
      session_id: sessionId,
      previous_session_id:
        String(value.previous_session_id || "").trim() || null,
      saved_at:
        String(value.saved_at || "").trim(),
      conversation_committed_at:
        String(value.conversation_committed_at || "").trim(),
      clear_barrier_at:
        String(value.clear_barrier_at || "").trim(),
      runtime_memory:
        String(value.runtime_memory || "").trim(),
      runtime_memory_updates:
        Number(value.runtime_memory_updates || 0),
      runtime_snapshot:
        (
          value.runtime_snapshot
          && typeof value.runtime_snapshot === "object"
          && !Array.isArray(value.runtime_snapshot)
        )
          ? {
              ...value.runtime_snapshot,
            }
          : null,
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
    });

  }


  function collectLegacyLatestRuntimeMemoryKeys(
    storageArea
  ) {

    const keys = [];

    try {
      for (let index = 0; index < storageArea.length; index += 1) {
        const key = storageArea.key(index);

        if (isLegacyLatestRuntimeMemoryKey(key)) {
          keys.push(key);
        }
      }
    } catch (error) {
      return [];
    }

    return keys;

  }


  function clearLegacyRuntimeStorage() {

    [
      legacyLatestSavedSessionSnapshotStorageKey,
      legacyL3SavedSessionSnapshotStorageKey,
      retiredSavedSessionHistoryStorageKey,
      latestSavedRuntimeMemoryStorageKey,
    ].forEach(removeBrowserMemory);

    try {
      collectLegacyLatestRuntimeMemoryKeys(
        window.localStorage
      ).forEach(removeBrowserMemory);
    } catch (error) {
      // Legacy cleanup is best-effort after the v2 checkpoint is safe.
    }

    try {
      collectLegacyLatestRuntimeMemoryKeys(
        window.sessionStorage
      ).forEach(removeSessionMemory);
    } catch (error) {
      // Legacy cleanup is best-effort after the v2 checkpoint is safe.
    }

  }


  function readLegacyRuntimeForSession(
    sessionId
  ) {

    const normalizedSessionId =
      String(sessionId || "").trim();

    if (!normalizedSessionId) {
      return null;
    }

    return sanitizeRuntimeMemoryRecord(
      readBrowserMemory(
        getLegacyLatestRuntimeMemoryStorageKey(
          normalizedSessionId
        )
      )
    );

  }


  function buildMigratedSessionCheckpoint() {

    const legacyCheckpoint =
      normalizeLegacySavedSessionSnapshot(
        readBrowserMemory(
          legacyLatestSavedSessionSnapshotStorageKey
        )
      )
      || normalizeLegacySavedSessionSnapshot(
        readBrowserMemory(
          legacyL3SavedSessionSnapshotStorageKey
        )
      );
    const latestSavedRuntime =
      sanitizeRuntimeMemoryRecord(
        readBrowserMemory(
          latestSavedRuntimeMemoryStorageKey
        )
      );
    const checkpointSessionId =
      String(
        legacyCheckpoint
        && legacyCheckpoint.session_id
        || ""
      ).trim();
    const latestSavedRuntimeSessionId =
      String(
        latestSavedRuntime
        && latestSavedRuntime.session_id
        || ""
      ).trim();
    const sourceSessionId =
      checkpointSessionId
      || latestSavedRuntimeSessionId;

    if (!sourceSessionId) {
      return null;
    }

    let runtimeRecord = null;

    if (
        latestSavedRuntime
        && latestSavedRuntimeSessionId === sourceSessionId
    ) {
      runtimeRecord = latestSavedRuntime;
    } else if (checkpointSessionId) {
      // This is the only legacy per-session lookup allowed. The common SAVE
      // remains the owner; orphan records never choose a session by freshness.
      runtimeRecord =
        readLegacyRuntimeForSession(
          checkpointSessionId
        );
    }

    const runtimeSessionSnapshot =
      (
        runtimeRecord
        && runtimeRecord.session_snapshot
        && typeof runtimeRecord.session_snapshot === "object"
        && !Array.isArray(runtimeRecord.session_snapshot)
      )
        ? runtimeRecord.session_snapshot
        : {};
    const checkpointSessionSnapshot =
      (
        legacyCheckpoint
        && legacyCheckpoint.session_snapshot
        && typeof legacyCheckpoint.session_snapshot === "object"
        && !Array.isArray(legacyCheckpoint.session_snapshot)
      )
        ? legacyCheckpoint.session_snapshot
        : {};

    return normalizeSessionCheckpointRecord({
      version: 2,
      state: "checkpoint",
      session_id: sourceSessionId,
      previous_session_id:
        String(
          legacyCheckpoint
          && legacyCheckpoint.previous_session_id
          || runtimeRecord
          && (
            runtimeRecord.previous_session_id
            || runtimeRecord.booted_from_session_id
          )
          || ""
        ).trim() || null,
      saved_at:
        String(
          legacyCheckpoint
          && legacyCheckpoint.saved_at
          || runtimeRecord
          && runtimeRecord.saved_at
          || ""
        ).trim(),
      conversation_committed_at:
        String(
          legacyCheckpoint
          && legacyCheckpoint.conversation_committed_at
          || runtimeRecord
          && runtimeRecord.conversation_committed_at
          || ""
        ).trim(),
      runtime_memory:
        String(
          runtimeRecord
          && runtimeRecord.runtime_memory
          || ""
        ).trim(),
      runtime_memory_updates:
        Number(
          runtimeRecord
          && runtimeRecord.runtime_memory_updates
          || 0
        ),
      runtime_snapshot:
        runtimeRecord
        && runtimeRecord.runtime_snapshot
        || null,
      session_snapshot: {
        ...runtimeSessionSnapshot,
        ...checkpointSessionSnapshot,
      },
    });

  }


  function ensureSessionCheckpointMigration() {

    if (shouldIsolateAnonymousStorage()) {
      return null;
    }

    const current =
      normalizeSessionCheckpointRecord(
        readBrowserMemory(
          sessionCheckpointStorageKey
        )
      );

    if (current) {
      if (!sessionCheckpointMigrationAttempted) {
        clearLegacyRuntimeStorage();
      }
      sessionCheckpointMigrationAttempted = true;
      return current;
    }

    if (sessionCheckpointMigrationAttempted) {
      return null;
    }

    sessionCheckpointMigrationAttempted = true;

    const migrated =
      buildMigratedSessionCheckpoint();

    if (migrated) {
      if (
          writeBrowserMemory(
            sessionCheckpointStorageKey,
            migrated
          )
      ) {
        clearLegacyRuntimeStorage();
        return migrated;
      }

      sessionCheckpointMigrationAttempted = false;
      return null;
    }

    const orphanLegacyKeys = [
      ...collectLegacyLatestRuntimeMemoryKeys(
        window.localStorage
      ),
      ...collectLegacyLatestRuntimeMemoryKeys(
        window.sessionStorage
      ),
    ];

    if (orphanLegacyKeys.length) {
      const cleared = {
        version: 2,
        state: "cleared",
        cleared_at: new Date().toISOString(),
      };

      if (
          writeBrowserMemory(
            sessionCheckpointStorageKey,
            cleared
          )
      ) {
        clearLegacyRuntimeStorage();
        return cleared;
      }

      sessionCheckpointMigrationAttempted = false;
    }

    return null;

  }


  function readSessionCheckpointRecord() {

    if (shouldIsolateAnonymousStorage()) {
      return null;
    }

    return ensureSessionCheckpointMigration();

  }


  function readSessionCheckpoint() {

    const checkpoint =
      readSessionCheckpointRecord();

    return (
        checkpoint
        && checkpoint.state === "checkpoint"
      )
      ? checkpoint
      : null;

  }


  function markSessionCheckpointUserActivity() {

    const checkpoint =
      shouldIsolateAnonymousStorage()
        ? null
        : normalizeSessionCheckpointRecord(
            readBrowserMemory(
              sessionCheckpointStorageKey
            )
          );
    const clearedAt =
      checkpoint
      && checkpoint.state === "cleared"
        ? Date.parse(
            String(checkpoint.cleared_at || "").trim()
          )
        : 0;

    sessionCheckpointUserActivityAt =
      Math.max(
        Date.now(),
        sessionCheckpointUserActivityAt + 1,
        Number.isFinite(clearedAt)
          ? clearedAt + 1
          : 1
      );

    return sessionCheckpointUserActivityAt;

  }


  function canOverwriteClearedCheckpoint(
    checkpoint
  ) {

    if (
        !checkpoint
        || checkpoint.state !== "cleared"
    ) {
      return true;
    }

    const clearedAt =
      Date.parse(
        String(checkpoint.cleared_at || "").trim()
      );

    return sessionCheckpointUserActivityAt > (
      Number.isFinite(clearedAt)
        ? clearedAt
        : 0
    );

  }


  function writeSessionCheckpoint(
    value
  ) {

    if (shouldIsolateAnonymousStorage()) {
      return false;
    }

    const existing =
      readSessionCheckpointRecord();

    if (!canOverwriteClearedCheckpoint(existing)) {
      return false;
    }

    const normalized =
      normalizeSessionCheckpointRecord(value);

    if (
        !normalized
        || normalized.state !== "checkpoint"
    ) {
      return false;
    }

    const clearBarrierAt =
      existing
      && existing.state === "cleared"
        ? String(existing.cleared_at || "").trim()
        : String(
            existing
            && existing.clear_barrier_at
            || ""
          ).trim();
    const clearBarrierTimestamp =
      Date.parse(clearBarrierAt);
    const changesCheckpointOwner = Boolean(
      existing
      && existing.state === "checkpoint"
      && String(existing.session_id || "").trim()
        !== String(normalized.session_id || "").trim()
    );

    if (
        changesCheckpointOwner
        && Number.isFinite(clearBarrierTimestamp)
        && sessionCheckpointUserActivityAt <= clearBarrierTimestamp
    ) {
      return false;
    }

    if (clearBarrierAt) {
      normalized.clear_barrier_at = clearBarrierAt;
    }

    return writeBrowserMemory(
      sessionCheckpointStorageKey,
      normalized
    );

  }


  function clearLiveRuntimeMemory() {

    removeSessionMemory(
      liveRuntimeMemoryStorageKey
    );

  }


  function clearSessionCheckpoint() {

    if (shouldIsolateAnonymousStorage()) {
      return false;
    }

    sessionCheckpointUserActivityAt = 0;

    const written = writeBrowserMemory(
      sessionCheckpointStorageKey,
      {
        version: 2,
        state: "cleared",
        cleared_at: new Date().toISOString(),
      }
    );

    if (!written) {
      return false;
    }

    clearLiveRuntimeMemory();
    clearLegacyRuntimeStorage();

    return true;

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

    if (shouldIsolateAnonymousStorage()) {
      const snapshot = readAnonymousSessionSnapshot();
      return normalizeActiveMemoryRecords(
        snapshot && snapshot.active_memory
      );
    }

    return normalizeActiveMemoryRecords(
      readBrowserMemory(
        getActiveMemoryStorageKey()
      )
    );

  }


  function writeActiveMemoryRecords(
    records
  ) {

    const normalized = normalizeActiveMemoryRecords(records);

    if (shouldIsolateAnonymousStorage()) {
      updateAnonymousSessionSnapshotField(
        "active_memory",
        normalized
      );
      return;
    }

    writeBrowserMemory(
      getActiveMemoryStorageKey(),
      normalized
    );

  }


  function clearActiveMemoryRecords() {

    if (shouldIsolateAnonymousStorage()) {
      updateAnonymousSessionSnapshotField(
        "active_memory",
        []
      );
      return [];
    }

    removeBrowserMemory(
      getActiveMemoryStorageKey()
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
            field.lt_content_hash || ""
          ).trim()
          || buildFactsMemoryContentHash(
            content
          );

        signals[normalizedKey] = {
          ...field,
          content,
          lt_status:
            normalizeFactsMemoryStatus(
              field.lt_status
            ),
          lt_content_hash: contentHash,
          lt_analyzed_at:
            normalizeFactsMemoryStatus(
              field.lt_status
            ) === "analyzed"
              ? String(field.lt_analyzed_at || "").trim()
              : "",
        };
        delete signals[normalizedKey].significance;
        delete signals[normalizedKey].metabolic_significance;
        delete signals[normalizedKey].significance_updated_at;
      }
    );

    return signals;

  }


  function collectFactsMemoryRecords() {

    const records = [];

    try {
      const factsStorage =
        shouldIsolateAnonymousStorage()
          ? window.sessionStorage
          : window.localStorage;

      for (let index = 0; index < factsStorage.length; index += 1) {
        const storageKey =
          factsStorage.key(index);

        if (!isFactsMemoryStorageKey(storageKey)) {
          continue;
        }

        const stored =
          readFactsStorageMemory(storageKey);

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
          writeFactsStorageMemory(
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

    writeFactsStorageMemory(
      targetStorageKey,
      signals
    );

    removeFactsStorageMemory(
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

    removeFactsStorageMemory(
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
            return signals[signalKey].lt_status === "analyzed";
          }
        )
    ) {
      return false;
    }

    removeFactsStorageMemory(
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
        ? readFactsStorageMemory(key)
        : null;

    const signals =
      normalizeFactsMemory(
        stored
      );

    if (
        key
        && isLegacyFactsMemoryValue(stored)
    ) {
      writeFactsStorageMemory(
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
      writeFactsStorageMemory(
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

    const rawReports = shouldIsolateAnonymousStorage()
      ? (readAnonymousSessionSnapshot() || {}).delayed_memory
      : readBrowserMemory(
          getDelayedMemoryReportsStorageKey()
        );
    const reports =
      normalizeDelayedMemoryReports(
        rawReports
      );

    if (shouldIsolateAnonymousStorage()) {
      if (JSON.stringify(rawReports || {}) !== JSON.stringify(reports)) {
        updateAnonymousSessionSnapshotField(
          "delayed_memory",
          reports
        );
      }
      return reports;
    }

    if (
        rawReports
        && typeof rawReports === "object"
        && !Array.isArray(rawReports)
        && JSON.stringify(rawReports) !== JSON.stringify(reports)
    ) {
      writeBrowserMemory(
        getDelayedMemoryReportsStorageKey(),
        reports
      );
    }

    return reports;

  }


  function writeDelayedMemoryReports(
    reports
  ) {

    const normalized = normalizeDelayedMemoryReports(
      reports
    );

    if (shouldIsolateAnonymousStorage()) {
      updateAnonymousSessionSnapshotField(
        "delayed_memory",
        normalized
      );
      return;
    }

    writeBrowserMemory(
      getDelayedMemoryReportsStorageKey(),
      normalized
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

    const snapshotSessionId =
      String(snapshot.session_id || "").trim()
      || runtimeSessionId;

    return {
      ...snapshot,
      session_id: snapshotSessionId,
      booted_from_session_id:
        bootSourceRuntimeSessionId,
      previous_session_id:
        bootSourceRuntimeSessionId,
      persisted_memory_scores: true,
    };

  }


  function hydrateLiveRuntimeMemoryFromCheckpoint(
    checkpoint
  ) {

    if (
        !checkpoint
        || typeof checkpoint !== "object"
        || Array.isArray(checkpoint)
        || !String(checkpoint.runtime_memory || "").trim()
    ) {
      return false;
    }

    const sourceSessionId =
      String(checkpoint.session_id || "").trim();

    setBootSourceRuntimeSessionId(
      sourceSessionId
    );

    writeLatestRuntimeMemory({
      version: 2,
      saved_at:
        String(checkpoint.saved_at || "").trim(),
      runtime_memory:
        checkpoint.runtime_memory || "",
      runtime_memory_updates:
        checkpoint.runtime_memory_updates || 0,
      runtime_snapshot:
        buildPersistedRuntimeSnapshot(
          checkpoint.runtime_snapshot
        ),
      cloned_from_session_id:
        sourceSessionId || null,
      previous_session_id:
        sourceSessionId || null,
      conversation_committed_at:
        String(
          checkpoint.conversation_committed_at || ""
        ).trim(),
    });

    return true;

  }


  const storage = {
    keys: {
      liveRuntimeMemoryStorageKey,
      sessionCheckpointStorageKey,
      runtimeSessionIdSessionStorageKey,
      activeMemoryStorageKey,
      delayedMemoryReportsStorageKey,
      factsMemoryStorageKeyPrefix,
      factsMemoryStorageKeyVersion,
    },
    getRuntimeSessionId,
    getCurrentRuntimeSessionId,
    getCurrentFactsMemorySessionId,
    setCurrentFactsMemorySessionId,
    setRuntimeSessionId,
    generateRuntimeSessionId,
    readBrowserMemory,
    writeBrowserMemory,
    removeBrowserMemory,
    readSessionMemory,
    writeSessionMemory,
    removeSessionMemory,
    isAnonymousModeEnabled,
    shouldIsolateAnonymousStorage,
    getActiveMemoryStorageKey,
    getDelayedMemoryReportsStorageKey,
    readLatestRuntimeMemory,
    writeLatestRuntimeMemory,
    readSessionCheckpoint,
    readSessionCheckpointRecord,
    writeSessionCheckpoint,
    clearSessionCheckpoint,
    clearLiveRuntimeMemory,
    markSessionCheckpointUserActivity,
    ensureSessionCheckpointMigration,
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
    hydrateLiveRuntimeMemoryFromCheckpoint,
  };

  window.JinRuntime.storage = storage;

}());
