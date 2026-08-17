(function () {
  "use strict";

  window.JinRuntime = window.JinRuntime || {};

  const session = {
    init,
    persistSessionMemory: notInitialized,
    getRuntimeMemoryForSoftReconnect: notInitialized,
    getInitialRuntimeMemoryBootstrap: notInitialized,
    captureSessionSaveRuntimeSnapshot: notInitialized,
    isReconnectInitialRuntimeMemoryUpdate: notInitialized,
    isLatestRuntimeMemoryDuplicate: notInitialized,
    isBootstrapRuntimeMemoryDuplicate: notInitialized,
    applyBootstrapRuntimeMemoryUpdate: notInitialized,
    hasRestoredSessionMemorySnapshot: notInitialized,
    shouldIgnoreInitialSessionModeUpdate: notInitialized,
  };

  window.JinRuntime.session = session;

  function notInitialized() {
    throw new Error(
      "JinRuntime.session.init must be called before use"
    );
  }

  function init(deps) {
    if (!deps || typeof deps !== "object") {
      throw new Error(
        "JinRuntime.session.init requires dependencies"
      );
    }

    const {
      history,
      storage,
      memoryModel,
      feedback,
      runtimeMemoryCount,
      defaultRuntimeMemoryText,
      sessionStartedRuntimeMemoryText,
      getRuntimeMemoryDisplayMode,
      setRuntimeMemoryDisplayMode,
      getRestoredSessionMemorySnapshot,
      setRestoredSessionMemorySnapshot,
      renderRuntimeMemorySnapshot,
      persistRuntimeMemorySnapshot,
      attachFirstUserIdleToInitialRuntimeSnapshot,
      rememberStableRuntimeSnapshot: rememberStableRuntimeSnapshotCallback,
      getLoadedDelayedMemoryReportIds,
      getAppendedDelayedMemoryReportIds,
    } = deps;

    const {
      splitMemoryTextLines,
      parseRuntimeMemoryLine,
      removeRuntimeMemoryLineByKey,
      stripActiveMemoryRuntimeMemoryText,
    } = memoryModel;

    const {
      keys: runtimeStorageKeys,
      removeBrowserMemory,
      readLatestRuntimeMemory,
      writeLatestSavedSessionMemory,
      readLatestSavedSessionMemory,
      writeLatestSavedRuntimeMemory,
      readLatestSavedRuntimeMemory,
      buildPersistedRuntimeSnapshot,
      collectOtherLatestRuntimeMemorySnapshots,
      clearOtherLatestRuntimeMemorySnapshots,
      getSavedRuntimeMemoryFallback,
      getCurrentLatestRuntimeMemoryStorageKey,
      getCurrentRuntimeSessionId,
      getCurrentFactsMemorySessionId,
      activateFactsMemorySession,
    } = storage;

    let pendingBootstrapRuntimeMemorySnapshot = null;
    let lastStableRuntimeMemorySnapshot = null;
    let pendingSessionSaveRuntimeMemorySnapshot = null;
    let waitingForSessionSaveRuntimeSnapshot = false;
    let pendingSessionSaveSavedAt = "";
    let persistedSessionBootstrapCleared = false;
    let hasUnsavedSessionActivity = false;

    function getCurrentSavedSessionId() {
      return String(
        (
          getCurrentFactsMemorySessionId
          && getCurrentFactsMemorySessionId()
        )
        || getCurrentRuntimeSessionId()
        || ""
      ).trim();
    }

    function buildSessionSaveRuntimeSnapshot(snapshot) {
      const persistedSnapshot =
        buildPersistedRuntimeSnapshot(
          snapshot
        );

      return persistedSnapshot
        ? {
            ...persistedSnapshot,
            session_id:
              getCurrentSavedSessionId(),
          }
        : null;
    }

    function runtimeMemoryObjectFromSnapshot(snapshot) {
      const runtimeMemory =
        stripActiveMemoryRuntimeMemoryText(
          (
            snapshot
            && snapshot.raw_memory
            && snapshot.display_source !== "default_runtime_memory"
            && snapshot.raw_memory
          )
          || ""
        );

      if (!runtimeMemory.trim()) {
        return null;
      }

      return {
        runtime_memory: runtimeMemory.trim(),
        runtime_memory_updates:
          (
            snapshot
            && snapshot.runtime_memory_updates
          )
          || (
            runtimeMemoryCount
            && Number(runtimeMemoryCount.textContent || 0)
          )
          || 0,
        runtime_snapshot: buildPersistedRuntimeSnapshot({
          ...snapshot,
          raw_memory: runtimeMemory.trim(),
        }),
      };
    }

    function runtimeMemoryObjectFromPersistedRuntime(persisted) {
      if (!persisted || typeof persisted !== "object") {
        return null;
      }

      let runtimeMemory =
        stripActiveMemoryRuntimeMemoryText(
          persisted.runtime_memory || ""
        ).trim();

      runtimeMemory = removeRuntimeMemoryLineByKey(
        runtimeMemory,
        feedback.key
      );

      if (!runtimeMemory) {
        return null;
      }

      return {
        runtime_memory: runtimeMemory,
        runtime_memory_updates:
          Number(persisted.runtime_memory_updates || 0),
        runtime_snapshot:
          (
            persisted.runtime_snapshot
            && typeof persisted.runtime_snapshot === "object"
          )
            ? buildPersistedRuntimeSnapshot(
                persisted.runtime_snapshot
              )
            : null,
      };
    }

    function getRuntimeSnapshotSearchText(snapshot) {
      if (!snapshot || typeof snapshot !== "object") {
        return "";
      }

      const parts = [
        snapshot.raw_memory,
        snapshot.memory,
        snapshot.current_request,
        snapshot.user_query,
        snapshot.last_jin_response,
        snapshot.display_source,
      ];

      if (Array.isArray(snapshot.lines)) {
        snapshot.lines.forEach(line => {
          if (!line || typeof line !== "object") {
            return;
          }

          parts.push(
            line.key,
            line.value
          );
        });
      }

      return parts
        .filter(Boolean)
        .map(part => String(part))
        .join("\n")
        .toLowerCase();
    }

    function normalizeBehaviorContractSearchText(text) {
      return String(text || "")
        .toLowerCase()
        .replace(/ё/g, "е");
    }

    function getBehaviorContractActionGuardPhrases(name, key) {
      const contract = window.JIN_BEHAVIOR_CONTRACT;

      const guard =
        contract
        && contract.action_guards
        && contract.action_guards[name];

      const phrases =
        guard
        && guard[key];

      if (!Array.isArray(phrases)) {
        return [];
      }

      return phrases
        .filter(phrase => typeof phrase === "string");
    }

    function behaviorContractPhraseAppears(text, name, key) {
      const normalizedText =
        normalizeBehaviorContractSearchText(
          text
        );

      return getBehaviorContractActionGuardPhrases(
        name,
        key
      ).some(phrase => (
        normalizedText.includes(
          normalizeBehaviorContractSearchText(
            phrase
          )
        )
      ));
    }

    function runtimeTextLooksLikeOnlySessionSave(text) {
      const runtimeMemory =
        String(text || "").toLowerCase();

      if (!runtimeMemory.trim()) {
        return false;
      }

      const hasSessionWord =
        runtimeMemory.includes("session")
        || runtimeMemory.includes("сесси");

      const hasSaveWord =
        runtimeMemory.includes("save")
        || runtimeMemory.includes("saved")
        || runtimeMemory.includes("saving")
        || runtimeMemory.includes("remembering")
        || runtimeMemory.includes("save_session")
        || runtimeMemory.includes("сохран")
        || runtimeMemory.includes("запомн");

      return hasSessionWord && hasSaveWord;
    }

    function runtimeSnapshotHasConversationContext(snapshot) {
      if (!snapshot || typeof snapshot !== "object") {
        return false;
      }

      const usefulKeys = new Set([
        "active_task",
        "current_focus",
        "current_request",
        "focus",
        "last_jin_response",
        "topic",
        "user_inquiry",
        "user_request",
      ]);

      if (!Array.isArray(snapshot.lines)) {
        return false;
      }

      return snapshot.lines.some(line => {
        if (!line || typeof line !== "object") {
          return false;
        }

        const key =
          String(line.key || "")
            .trim()
            .toLowerCase();

        const value =
          String(line.value || "")
            .trim();

        if (!value || !usefulKeys.has(key)) {
          return false;
        }

        return !runtimeTextLooksLikeOnlySessionSave(
          value
        );
      });
    }

    function runtimeSnapshotLooksLikeSessionSaveResult(snapshot) {
      const runtimeMemory =
        getRuntimeSnapshotSearchText(
          snapshot
        );

      if (!runtimeMemory) {
        return false;
      }

      if (
          runtimeMemory.includes("session management")
          && runtimeMemory.includes("paused")
      ) {
        return false;
      }

      const hasSessionWord =
        runtimeMemory.includes("session")
        || runtimeMemory.includes("сесси");

      const hasSaveWord =
        runtimeMemory.includes("save")
        || runtimeMemory.includes("saved")
        || runtimeMemory.includes("saving")
        || runtimeMemory.includes("remembering")
        || runtimeMemory.includes("save_session")
        || runtimeMemory.includes("сохран");

      const hasRememberSessionTrigger =
        behaviorContractPhraseAppears(
          runtimeMemory,
          "save_session",
          "triggers"
        );

      const hasSaveResultPhrase = (
        runtimeMemory.includes("session saved")
        || runtimeMemory.includes("session state successfully saved")
        || runtimeMemory.includes("session state saved")
        || runtimeMemory.includes("current state is saved")
        || runtimeMemory.includes("state is saved")
        || runtimeMemory.includes("state saved")
        || runtimeMemory.includes("successfully saved")
        || runtimeMemory.includes("confirmed saving")
        || runtimeMemory.includes("confirmed saved")
        || runtimeMemory.includes("remembering this session")
        || runtimeMemory.includes("save_session")
        || hasRememberSessionTrigger
        || runtimeMemory.includes("сохраняю")
        || runtimeMemory.includes("сохранено")
        || runtimeMemory.includes("сессия сохран")
      );

      if (
          hasSaveResultPhrase
          || (
            hasSessionWord
            && hasSaveWord
          )
      ) {
        // Do not throw away a real L1 runtime page just because the last
        // turn also saved the session. The page after a save request may
        // still contain the useful current context: previous user request,
        // active task, and last non-save JIN response. Only pure save-status
        // pages should be treated as save chatter.
        return !runtimeSnapshotHasConversationContext(
          snapshot
        );
      }

      return false;
    }

    function isUsableStableRuntimeSnapshot(snapshot) {
      if (!snapshot || typeof snapshot !== "object") {
        return false;
      }

      const runtimeMemory =
        String(snapshot.raw_memory || "").trim();

      if (
          !runtimeMemory
          || runtimeMemory === defaultRuntimeMemoryText
          || snapshot.display_source === "default_runtime_memory"
          || snapshot.display_source === "browser_l3_restore_status"
          || snapshot.display_source === "l3_bootstrap_status"
      ) {
        return false;
      }

      if (runtimeSnapshotLooksLikeSessionSaveResult(snapshot)) {
        return false;
      }

      return true;
    }

    function rememberStableRuntimeSnapshot(snapshot) {
      if (!isUsableStableRuntimeSnapshot(snapshot)) {
        return;
      }

      lastStableRuntimeMemorySnapshot = {
        ...snapshot,
      };

      if (rememberStableRuntimeSnapshotCallback) {
        rememberStableRuntimeSnapshotCallback(
          snapshot
        );
      }
    }

    function getLatestStableRuntimeMemoryObject() {
      const snapshots =
        history.snapshots || [];

      for (let index = snapshots.length - 1; index >= 0; index -= 1) {
        const candidate = snapshots[index];

        if (!isUsableStableRuntimeSnapshot(candidate)) {
          continue;
        }

        const runtimeMemory =
          runtimeMemoryObjectFromSnapshot(candidate);

        if (runtimeMemory) {
          return runtimeMemory;
        }
      }

      const rememberedRuntimeMemory =
        runtimeMemoryObjectFromSnapshot(
          lastStableRuntimeMemorySnapshot
        );

      if (rememberedRuntimeMemory) {
        return rememberedRuntimeMemory;
      }

      const persistedRuntimeMemory =
        runtimeMemoryObjectFromPersistedRuntime(
          readLatestRuntimeMemory()
        );

      if (persistedRuntimeMemory) {
        return persistedRuntimeMemory;
      }

      return null;
    }

    function getRuntimeMemoryForSessionSave() {
      const pendingRuntimeMemory =
        runtimeMemoryObjectFromSnapshot(
          pendingSessionSaveRuntimeMemorySnapshot
        );

      if (pendingRuntimeMemory) {
        return pendingRuntimeMemory;
      }

      const stableRuntimeMemory =
        getLatestStableRuntimeMemoryObject();

      if (stableRuntimeMemory) {
        return stableRuntimeMemory;
      }

      return runtimeMemoryObjectFromPersistedRuntime(
        readLatestRuntimeMemory()
      );
    }

    function userMessageLooksLikeSessionSaveRequest(text) {
      const normalizedText =
        String(text || "").toLowerCase();

      if (!normalizedText.trim()) {
        return false;
      }

      const hasSessionWord =
        normalizedText.includes("session")
        || normalizedText.includes("сесси");

      const hasSaveWord =
        normalizedText.includes("save")
        || normalizedText.includes("remember")
        || normalizedText.includes("сохран")
        || normalizedText.includes("запомн");

      return hasSessionWord && hasSaveWord;
    }

    function prepareRuntimeMemoryForUserMessage(text) {
      if (!userMessageLooksLikeSessionSaveRequest(text)) {
        return;
      }

      pendingSessionSaveRuntimeMemorySnapshot = null;
      waitingForSessionSaveRuntimeSnapshot = true;
      pendingSessionSaveSavedAt = "";
    }

    function finishPendingSessionSaveRuntimeMemory() {
      if (
          !waitingForSessionSaveRuntimeSnapshot
          || !pendingSessionSaveRuntimeMemorySnapshot
          || !pendingSessionSaveSavedAt
      ) {
        return false;
      }

      const latestSavedRuntimeMemory =
        getRuntimeMemoryForSessionSave();

      if (!latestSavedRuntimeMemory) {
        return false;
      }

      writeLatestSavedRuntimeMemory({
        version: 1,
        explicit_save: true,
        session_id:
          getCurrentSavedSessionId(),
        saved_at:
          pendingSessionSaveSavedAt,
        runtime_memory:
          latestSavedRuntimeMemory.runtime_memory || "",
        runtime_memory_updates:
          latestSavedRuntimeMemory.runtime_memory_updates || 0,
        runtime_snapshot:
          buildSessionSaveRuntimeSnapshot(
            latestSavedRuntimeMemory.runtime_snapshot
          ),
      });

      pendingSessionSaveRuntimeMemorySnapshot = null;
      waitingForSessionSaveRuntimeSnapshot = false;
      pendingSessionSaveSavedAt = "";

      return true;
    }

    function persistSessionMemory(data) {
      if (
          !data
          || data.persist !== true
      ) {
        return;
      }

      const sessionMemory =
        (
          data.memory
          || ""
        ).trim();

      if (!sessionMemory) {
        return;
      }

      const savedAt =
        new Date().toISOString();

      // L3 is the authoritative session save result. Persist it immediately
      // instead of waiting for the follow-up L1 runtime snapshot.
      persistedSessionBootstrapCleared = false;
      hasUnsavedSessionActivity = false;
      waitingForSessionSaveRuntimeSnapshot = true;
      pendingSessionSaveSavedAt = savedAt;

      // Do not leave the previous session's runtime half paired with the new
      // L3 save while the follow-up L1 snapshot is still pending.
      removeBrowserMemory(
        runtimeStorageKeys.latestSavedRuntimeMemoryStorageKey
      );

      writeLatestSavedSessionMemory({
        version: 1,
        explicit_save: true,
        session_id:
          getCurrentSavedSessionId(),
        saved_at: savedAt,
        loaded_memory_ids:
          typeof getLoadedDelayedMemoryReportIds === "function"
            ? getLoadedDelayedMemoryReportIds()
            : [],
        session_memory: sessionMemory,
        session_memory_updates:
          data.updates || 0,
      });

      // If L1 happened to arrive before L3, finish the runtime half now.
      // In the normal flow this remains pending until the follow-up L1 update.
      finishPendingSessionSaveRuntimeMemory();
    }

    function getRuntimeMemoryForSoftReconnect() {
      return getRuntimeMemoryForSessionSave();
    }

    function captureSessionSaveRuntimeSnapshot(snapshot) {
      if (
          !waitingForSessionSaveRuntimeSnapshot
          || !snapshot
      ) {
        return;
      }

      pendingSessionSaveRuntimeMemorySnapshot = snapshot;
      finishPendingSessionSaveRuntimeMemory();
    }

    function getSoftReconnectRuntimeResume() {
      const runtimeMemory =
        getRuntimeMemoryForSoftReconnect();
      const sessionBootstrap =
        persistedSessionBootstrapCleared
          ? null
          : getPersistedSessionBootstrap();

      const runtimeText =
        (
          runtimeMemory
          && runtimeMemory.runtime_memory
          && String(runtimeMemory.runtime_memory).trim()
        ) || "";
      const sessionText =
        (
          sessionBootstrap
          && sessionBootstrap.session_memory
          && String(sessionBootstrap.session_memory).trim()
        ) || "";

      if (!runtimeText && !sessionText) {
        return null;
      }

      return {
        type: "runtime_resume",
        runtime_memory: runtimeText,
        runtime_memory_updates:
          (
            runtimeMemory
            && runtimeMemory.runtime_memory_updates
          ) || 0,
        runtime_snapshot:
          (
            runtimeMemory
            && runtimeMemory.runtime_snapshot
          ) || null,
        session_memory: sessionText,
        session_memory_source:
          (
            sessionBootstrap
            && sessionBootstrap.session_memory_source
          ) || "browser_soft_reconnect",
        session_memory_updates:
          (
            sessionBootstrap
            && sessionBootstrap.session_memory_updates
          ) || 0,
        loaded_memory_ids:
          typeof getLoadedDelayedMemoryReportIds === "function"
            ? getLoadedDelayedMemoryReportIds()
            : [],
      };
    }

    function getInitialRuntimeMemoryBootstrap() {
      // Page reload/new-tab bootstrap must only come from an explicit saved
      // session (`getPersistedSessionBootstrap`). The per-session
      // latestRuntimeMemory localStorage copy is a live reconnect cache, not a
      // restore point: after Save -> more messages -> refresh, replaying it
      // would skip the saved state and resurrect unsaved runtime facts.
      return null;
    }

    function hasTabCloseSessionBootstrap() {
      if (persistedSessionBootstrapCleared) {
        return false;
      }

      return hasUnsavedSessionActivity;
    }

    function isDefaultRuntimeMemoryText(text) {
      let normalized = String(text || "")
        .trim()
        .replace(/\s+/g, " ")
        .toLowerCase();

      if (normalized.startsWith("note:")) {
        normalized = normalized.slice(5).trim();
      }

      return normalized === String(defaultRuntimeMemoryText || "")
        .trim()
        .replace(/\s+/g, " ")
        .toLowerCase();
    }

    function isReconnectInitialRuntimeMemoryUpdate(data) {
      if (
          !data
          || !data.snapshot
      ) {
        return false;
      }

      if (Number(data.updates || 0) !== 0) {
        return false;
      }

      const archivedRestoreActive = Boolean(
        window.jinArchivedSessionBootstrap
        && window.jinArchivedSessionBootstrap.archived_session_restore === true
      );

      if (
          history.snapshots.length === 0
          && !archivedRestoreActive
      ) {
        return false;
      }

      const runtimeMemory =
        (
          data.snapshot.raw_memory
          || data.memory
          || ""
        ).trim();

      return isDefaultRuntimeMemoryText(
        runtimeMemory
      );
    }

    function stripArchivedRuntimeLifecycleMetadata(text) {
      return String(text || "")
        .replace(
          /\s*\[\s*(?:created|updated)\s*:\s*[^\]]*?\s+ago\s*\]\s*/gi,
          " "
        )
        .replace(/[ \t]+\n/g, "\n")
        .replace(/\n[ \t]+/g, "\n")
        .trim();
    }

    function normalizeRuntimeMemoryText(text) {
      return stripArchivedRuntimeLifecycleMetadata(
        String(text || "")
          .replace(/\\n/g, "\n")
          .replace(/\r\n/g, "\n")
      )
        .replace(
          /(session_status\s*:\s*Active;\s*last updated at\s*)[^\n]+/gi,
          "$1<bootstrap_time>"
        )
        .split("\n")
        .map(line => line.trim())
        .filter(Boolean)
        .join("\n");
    }

    function getRuntimeMemoryTextFromUpdate(data) {
      return normalizeRuntimeMemoryText(
        (
          data
          && data.snapshot
          && data.snapshot.raw_memory
        )
        || (
          data
          && data.memory
        )
        || ""
      );
    }

    function isLatestRuntimeMemoryDuplicate(data) {
      if (
          !data
          || data.type !== "runtime_memory_update"
          || !history.snapshots.length
      ) {
        return false;
      }

      if (data.replace_latest === true) {
        return false;
      }

      const latestSnapshot =
        history.snapshots[
          history.snapshots.length - 1
        ];

      const latestMemory = normalizeRuntimeMemoryText(
        latestSnapshot && latestSnapshot.raw_memory
      );

      const incomingMemory =
        getRuntimeMemoryTextFromUpdate(data);

      if (
          latestSnapshot
          && latestSnapshot.restored_from_session_save
          && Number(data.updates || 0) === 0
      ) {
        return true;
      }

      if (
          !latestMemory
          || !incomingMemory
          || latestMemory !== incomingMemory
      ) {
        return false;
      }

      // An exact text match against the restored baseline is never a new page.
      // The first real post-restore L1 update is allowed naturally because its
      // memory text changes. Treating an identical server echo as "real" was the
      // source of the duplicated page 0/page 1 restore snapshot race.
      if (latestSnapshot && latestSnapshot.restored_from_session_save) {
        return true;
      }

      const latestUpdates = Number(
        (
          latestSnapshot
          && latestSnapshot.runtime_memory_updates
        ) || 0
      );

      const incomingUpdates = Number(
        data.updates || 0
      );

      return incomingUpdates <= latestUpdates;
    }

    function isBootstrapRuntimeMemoryDuplicate(data) {
      if (
          !pendingBootstrapRuntimeMemorySnapshot
          || !data
          || data.type !== "runtime_memory_update"
      ) {
        return false;
      }

      const bootstrapMemory =
        normalizeRuntimeMemoryText(
          pendingBootstrapRuntimeMemorySnapshot.raw_memory
        );

      const incomingMemory =
        getRuntimeMemoryTextFromUpdate(
          data
        );

      if (
          !bootstrapMemory
          || !incomingMemory
          || bootstrapMemory !== incomingMemory
      ) {
        pendingBootstrapRuntimeMemorySnapshot = null;
        return false;
      }

      const bootstrapUpdates =
        Number(
          pendingBootstrapRuntimeMemorySnapshot.runtime_memory_updates || 0
        );

      const incomingUpdates =
        Number(data.updates || 0);

      if (
          incomingUpdates <= bootstrapUpdates
          || !hasUnsavedSessionActivity
      ) {
        pendingBootstrapRuntimeMemorySnapshot = null;
        return true;
      }

      pendingBootstrapRuntimeMemorySnapshot = null;
      return false;
    }

    function applyBootstrapRuntimeMemoryUpdate(data) {
      if (
          !pendingBootstrapRuntimeMemorySnapshot
          || !data
          || data.type !== "runtime_memory_update"
          || !data.snapshot
      ) {
        return false;
      }

      const bootstrapMemory = normalizeRuntimeMemoryText(
        pendingBootstrapRuntimeMemorySnapshot.raw_memory
      );
      const incomingMemory =
        getRuntimeMemoryTextFromUpdate(data);

      if (
          !bootstrapMemory
          || !incomingMemory
          || bootstrapMemory !== incomingMemory
      ) {
        return false;
      }

      // This is the authoritative server echo of PREVIOUS_RUNTIME_STATE. Replace
      // the provisional browser page in-place so lifecycle timestamps/strengths
      // are rebuilt as fresh values, but never append a second restore page.
      const restoredRuntimeSnapshot = {
        ...data.snapshot,
        index: 0,
        display_source: "saved_runtime_at_session_save",
        restored_from_session_save: true,
        runtime_memory_updates: Number(
          data.updates
          || data.snapshot.runtime_memory_updates
          || pendingBootstrapRuntimeMemorySnapshot.runtime_memory_updates
          || 0
        ),
      };

      pendingBootstrapRuntimeMemorySnapshot = null;
      setRuntimeMemoryDisplayMode("runtime");
      setRestoredSessionMemorySnapshot(null);

      if (window.stopMemoryGlow) {
        window.stopMemoryGlow();
      }

      history.snapshots = [
        restoredRuntimeSnapshot,
      ];
      history.index = 0;
      history.displayIndexOffset = 1;

      rememberStableRuntimeSnapshot(
        restoredRuntimeSnapshot
      );

      if (runtimeMemoryCount) {
        runtimeMemoryCount.textContent =
          String(restoredRuntimeSnapshot.runtime_memory_updates || 0);
      }

      renderRuntimeMemorySnapshot();

      return true;
    }

    function handleTabCloseSessionBootstrap(event) {
      if (!hasTabCloseSessionBootstrap()) {
        return undefined;
      }

      event.preventDefault();
      event.returnValue = "Are you sure?";

      return "Are you sure?";
    }

    function buildRuntimeMemoryDisplaySnapshot(data) {
      const isArchivedRestore = Boolean(
        data
        && data.archived_session_restore === true
      );

      let runtimeMemory =
        stripActiveMemoryRuntimeMemoryText(
          (
            data
            && (
              data.runtime_memory
              || data.memory
              || (
                data.runtime_snapshot
                && data.runtime_snapshot.raw_memory
              )
            )
          )
          || ""
        ).trim();

      if (isArchivedRestore) {
        runtimeMemory =
          stripArchivedRuntimeLifecycleMetadata(
            runtimeMemory
          );
      }

      if (!runtimeMemory) {
        return null;
      }

      const sourceSnapshot =
        (
          data
          && data.runtime_snapshot
          && typeof data.runtime_snapshot === "object"
        )
          ? data.runtime_snapshot
          : {};

      const restoredAt = new Date().toISOString();
      const parsedFreshLines =
        splitMemoryTextLines(runtimeMemory)
          .map(parseRuntimeMemoryLine)
          .map((line) => ({
            ...line,
            status: isArchivedRestore ? "new" : line.status,
            key_status: isArchivedRestore ? "new" : line.key_status,
            value_status: isArchivedRestore ? "new" : line.value_status,
            key_change_ratio: isArchivedRestore ? 1 : line.key_change_ratio,
            value_change_ratio: isArchivedRestore ? 1 : line.value_change_ratio,
            memory_lifecycle_status:
              isArchivedRestore ? "created" : line.memory_lifecycle_status,
            created_at:
              isArchivedRestore ? restoredAt : line.created_at,
            updated_at:
              isArchivedRestore ? "" : line.updated_at,
          }));

      return {
        ...sourceSnapshot,
        session_id:
          sourceSnapshot.session_id
          || "browser_restore",
        index: 0,
        display_source: "saved_runtime_at_session_save",
        raw_memory: runtimeMemory,
        lines:
          !isArchivedRestore
            && Array.isArray(sourceSnapshot.lines)
            && sourceSnapshot.raw_memory === runtimeMemory
            ? sourceSnapshot.lines
            : parsedFreshLines,
        restored_from_session_save: true,
        runtime_memory_updates:
          Number(
            (
              data
              && (
                data.runtime_memory_updates
                || data.updates
              )
            )
            || 0
          ),
      };
    }

    function buildDefaultRuntimeMemorySnapshot() {
      return {
        session_id: "browser_restore",
        index: 0,
        display_source: "default_runtime_memory",
        raw_memory: sessionStartedRuntimeMemoryText,
        lines: [
          {
            key: "session_status",
            value: "Session started",
            status: "same",
            key_status: "same",
            value_status: "same",
            key_change_ratio: 0,
            value_change_ratio: 0,
          },
        ],
        runtime_memory_updates: 0,
      };
    }

    function applyRuntimeMemoryDisplaySnapshot(snapshot) {
      const displaySnapshot =
        snapshot || buildDefaultRuntimeMemorySnapshot();

      setRuntimeMemoryDisplayMode("runtime");
      setRestoredSessionMemorySnapshot(null);
      pendingBootstrapRuntimeMemorySnapshot =
        displaySnapshot.restored_from_session_save
          ? displaySnapshot
          : null;
      history.snapshots = [displaySnapshot];
      history.index = 0;
      history.displayIndexOffset =
        displaySnapshot.restored_from_session_save
          ? 1
          : 0;

      rememberStableRuntimeSnapshot(
        displaySnapshot
      );

      if (runtimeMemoryCount) {
        runtimeMemoryCount.textContent =
          String(displaySnapshot.runtime_memory_updates || 0);
      }

      renderRuntimeMemorySnapshot();
    }

    function applyPersistedSessionBootstrap(bootstrap) {
      if (
          bootstrap
          && bootstrap.source_session_id
          && activateFactsMemorySession
      ) {
        // Continue boosting the original saved session facts in-place.
        // Never clone them into the transient tab/runtime session id.
        activateFactsMemorySession(
          bootstrap.source_session_id
        );

        if (
            typeof window.refreshFactsMemoryAppendButtons
            === "function"
        ) {
          window.refreshFactsMemoryAppendButtons();
        }
      }

      let snapshot =
        (
          bootstrap
          && bootstrap.runtime_display_snapshot
        )
        || buildRuntimeMemoryDisplaySnapshot(
          bootstrap || {}
        );

      // Archived restore must never manufacture "Session started" / "no history"
      // pages. PREVIOUS_RUNTIME_STATE is the only valid initial L1 baseline. If
      // an old archive genuinely has no such block, leave the panel empty and
      // let the next real L1 update create its first page.
      if (
          !snapshot
          && bootstrap
          && bootstrap.archived_session_restore === true
      ) {
        return;
      }

      snapshot = snapshot
        || buildDefaultRuntimeMemorySnapshot();

      applyRuntimeMemoryDisplaySnapshot(
        snapshot
      );
    }

    function getPersistedSessionBootstrap() {
      if (
        window.jinArchivedSessionBootstrap
        && typeof window.jinArchivedSessionBootstrap === "object"
      ) {
        return {
          ...window.jinArchivedSessionBootstrap,
        };
      }

      const savedRuntimeFallback =
        getSavedRuntimeMemoryFallback();

      const shouldUseBrowserMemory =
        !savedRuntimeFallback;

      const browserLatestSavedSessionMemory =
        shouldUseBrowserMemory
          ? readLatestSavedSessionMemory()
          : null;

      const sessionMemory =
        (
          savedRuntimeFallback
          && savedRuntimeFallback.session_memory
        )
        || (
          browserLatestSavedSessionMemory
          && browserLatestSavedSessionMemory.explicit_save === true
            ? browserLatestSavedSessionMemory
            : null
        );

      if (
          !sessionMemory
          || sessionMemory.explicit_save !== true
      ) {
        return null;
      }

      const sessionMemorySource =
        (
          savedRuntimeFallback
          && savedRuntimeFallback.session_memory
        )
          ? savedRuntimeFallback.source
          : (
              browserLatestSavedSessionMemory
              && browserLatestSavedSessionMemory.explicit_save === true
                ? "browser_localStorage"
                : "unknown"
            );

      const sessionText =
        (
          sessionMemory
          && sessionMemory.explicit_save === true
          && sessionMemory.session_memory
        )
        || "";

      const browserLatestSavedRuntimeMemory =
        shouldUseBrowserMemory
          ? readLatestSavedRuntimeMemory()
          : null;

      const latestSavedRuntimeMemory =
        (
          savedRuntimeFallback
          && savedRuntimeFallback.latest_saved_runtime_memory
        )
        || (
          browserLatestSavedRuntimeMemory
          && browserLatestSavedRuntimeMemory.explicit_save === true
            ? browserLatestSavedRuntimeMemory
            : null
        );

      const runtimeMemory =
        (
          latestSavedRuntimeMemory
          && latestSavedRuntimeMemory.explicit_save === true
        )
          ? latestSavedRuntimeMemory
          : null;

      const runtimeText =
        (
          runtimeMemory
          && runtimeMemory.runtime_memory
        )
        || "";

      if (!sessionText) {
        return null;
      }

      const runtimeDisplaySnapshot =
        buildRuntimeMemoryDisplaySnapshot({
          runtime_memory: runtimeText,
          runtime_memory_updates:
            (
              runtimeMemory
              && runtimeMemory.runtime_memory_updates
            )
            || 0,
          runtime_snapshot:
            (
              runtimeMemory
              && runtimeMemory.runtime_snapshot
            )
            || null,
        }) || buildDefaultRuntimeMemorySnapshot();

      const sourceSessionId =
        String(
          (
            sessionMemory
            && sessionMemory.session_id
          )
          || (
            runtimeMemory
            && runtimeMemory.session_id
          )
          || (
            runtimeMemory
            && runtimeMemory.runtime_snapshot
            && runtimeMemory.runtime_snapshot.session_id
          )
          || ""
        ).trim();

      return {
        type: "session_bootstrap",
        source_session_id: sourceSessionId,
        session_memory: sessionText,
        session_memory_source: sessionMemorySource,
        session_memory_updates:
          (
            sessionMemory
            && sessionMemory.session_memory_updates
          )
          || 0,
        loaded_memory_ids:
          Array.from(new Set([
            ...(
              sessionMemory
              && Array.isArray(sessionMemory.loaded_memory_ids)
                ? sessionMemory.loaded_memory_ids
                : []
            ),
            ...(
              (() => {
                const legacyLoadKey = "append" + "ed_memory_ids";
                return (
                  sessionMemory
                  && Array.isArray(sessionMemory[legacyLoadKey])
                    ? sessionMemory[legacyLoadKey]
                    : []
                );
              })()
            ),
          ]))
            .map(item => String(item || "").trim())
            .filter(Boolean),
        runtime_memory: runtimeText,
        runtime_memory_updates:
          (
            runtimeMemory
            && runtimeMemory.runtime_memory_updates
          )
          || 0,
        runtime_snapshot:
          (
            runtimeMemory
            && runtimeMemory.runtime_snapshot
          )
          || null,
        runtime_display_snapshot: runtimeDisplaySnapshot,
      };
    }

    function clearPersistedSessionBootstrap() {
      persistedSessionBootstrapCleared = true;
      hasUnsavedSessionActivity = false;

      removeBrowserMemory(
        runtimeStorageKeys.latestSavedSessionMemoryStorageKey
      );
      removeBrowserMemory(
        runtimeStorageKeys.latestSavedRuntimeMemoryStorageKey
      );
      removeBrowserMemory(
        getCurrentLatestRuntimeMemoryStorageKey()
      );
    }

    function markSessionActivityDirty() {
      persistedSessionBootstrapCleared = false;
      hasUnsavedSessionActivity = true;
    }

    function hasRestoredSessionMemorySnapshot() {
      return Boolean(
        getRestoredSessionMemorySnapshot()
      );
    }

    function shouldIgnoreInitialSessionModeUpdate(data) {
      return (
        getRuntimeMemoryDisplayMode() === "session"
        && hasRestoredSessionMemorySnapshot()
        && Number(data && data.updates || 0) === 0
      );
    }

    session.persistSessionMemory = persistSessionMemory;
    session.getRuntimeMemoryForSoftReconnect = getRuntimeMemoryForSoftReconnect;
    session.getInitialRuntimeMemoryBootstrap = getInitialRuntimeMemoryBootstrap;
    session.captureSessionSaveRuntimeSnapshot = captureSessionSaveRuntimeSnapshot;
    session.isReconnectInitialRuntimeMemoryUpdate = isReconnectInitialRuntimeMemoryUpdate;
    session.isLatestRuntimeMemoryDuplicate = isLatestRuntimeMemoryDuplicate;
    session.isBootstrapRuntimeMemoryDuplicate = isBootstrapRuntimeMemoryDuplicate;
    session.applyBootstrapRuntimeMemoryUpdate = applyBootstrapRuntimeMemoryUpdate;
    session.hasRestoredSessionMemorySnapshot = hasRestoredSessionMemorySnapshot;
    session.shouldIgnoreInitialSessionModeUpdate = shouldIgnoreInitialSessionModeUpdate;
    session.rememberStableRuntimeSnapshot = rememberStableRuntimeSnapshot;

    window.prepareRuntimeMemoryForUserMessage = prepareRuntimeMemoryForUserMessage;
    window.getSoftReconnectRuntimeResume = getSoftReconnectRuntimeResume;
    window.getInitialRuntimeMemoryBootstrap = getInitialRuntimeMemoryBootstrap;
    window.applyPersistedSessionBootstrap = applyPersistedSessionBootstrap;
    window.getPersistedSessionBootstrap = getPersistedSessionBootstrap;
    window.clearPersistedSessionBootstrap = clearPersistedSessionBootstrap;
    window.getCurrentLatestRuntimeMemoryStorageKey = function () {
      return getCurrentLatestRuntimeMemoryStorageKey();
    };
    window.getOtherLatestRuntimeMemorySnapshots = function () {
      return collectOtherLatestRuntimeMemorySnapshots();
    };
    window.clearOtherLatestRuntimeMemorySnapshots = function () {
      return clearOtherLatestRuntimeMemorySnapshots();
    };
    window.markSessionActivityDirty = markSessionActivityDirty;
    window.markSessionBootstrapActive = markSessionActivityDirty;

    window.addEventListener(
      "beforeunload",
      handleTabCloseSessionBootstrap
    );
  }
}());
