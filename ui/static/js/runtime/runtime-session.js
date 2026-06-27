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
    } = storage;

    let pendingBootstrapRuntimeMemorySnapshot = null;
    let lastStableRuntimeMemorySnapshot = null;
    let pendingSessionSaveRuntimeMemorySnapshot = null;
    let waitingForSessionSaveRuntimeSnapshot = false;
    let pendingSessionMemoryPersistData = null;
    let persistedSessionBootstrapCleared = false;
    let hasUnsavedSessionActivity = false;

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
      pendingSessionMemoryPersistData = null;
    }

    function persistSessionMemory(data) {
      if (
          !data
          || data.persist !== true
      ) {
        return;
      }

      if (
          waitingForSessionSaveRuntimeSnapshot
          && !pendingSessionSaveRuntimeMemorySnapshot
      ) {
        pendingSessionMemoryPersistData = data;
        return;
      }

      const sessionMemory =
        (
          data.memory
          || ""
        ).trim();

      const eventSnapshots =
        Array.isArray(data.event_snapshots)
          ? data.event_snapshots
          : [];

      if (!sessionMemory) {
        if (!eventSnapshots.length) {
          return;
        }
      }

      const latestSavedRuntimeMemory =
        getRuntimeMemoryForSessionSave();

      const savedAt =
        new Date().toISOString();

      persistedSessionBootstrapCleared = false;
      hasUnsavedSessionActivity = false;

      writeLatestSavedSessionMemory({
        version: 1,
        explicit_save: true,
        saved_at: savedAt,
        session_memory: sessionMemory,
        session_event_snapshots: eventSnapshots,
        session_memory_updates:
          data.updates || 0,
      });

      writeLatestSavedRuntimeMemory({
        version: 1,
        explicit_save: true,
        saved_at: savedAt,
        runtime_memory:
          (
            latestSavedRuntimeMemory
            && latestSavedRuntimeMemory.runtime_memory
          ) || "",
        runtime_memory_updates:
          (
            latestSavedRuntimeMemory
            && latestSavedRuntimeMemory.runtime_memory_updates
          ) || 0,
        runtime_snapshot:
          buildPersistedRuntimeSnapshot(
            latestSavedRuntimeMemory
            && latestSavedRuntimeMemory.runtime_snapshot
          ),
      });

      pendingSessionSaveRuntimeMemorySnapshot = null;
      waitingForSessionSaveRuntimeSnapshot = false;
      pendingSessionMemoryPersistData = null;
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

      if (pendingSessionMemoryPersistData) {
        const data = pendingSessionMemoryPersistData;
        pendingSessionMemoryPersistData = null;
        persistSessionMemory(
          data
        );
      }
    }

    function getSoftReconnectRuntimeResume() {
      const runtimeMemory =
        getRuntimeMemoryForSoftReconnect();

      const runtimeText =
        (
          runtimeMemory
          && runtimeMemory.runtime_memory
          && String(runtimeMemory.runtime_memory).trim()
        ) || "";

      if (!runtimeText) {
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

      if (history.snapshots.length === 0) {
        return false;
      }

      const runtimeMemory =
        (
          data.snapshot.raw_memory
          || data.memory
          || ""
        ).trim();

      return runtimeMemory === defaultRuntimeMemoryText;
    }

    function normalizeRuntimeMemoryText(text) {
      return String(text || "")
        .replace(/\\n/g, "\n")
        .replace(/\r\n/g, "\n")
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

      // If the latest snapshot was restored from a previous session its
      // runtime_memory_updates counter belongs to that old session. The server
      // resets its counter to 0 on every new connection, so the first real L1
      // update (updates=1) is always <= the old session counter (e.g. 3).
      // Without this guard every post-bootstrap L1 update is incorrectly treated
      // as a duplicate and dropped, leaving the panel stuck on the restore placeholder.
      if (latestSnapshot && latestSnapshot.restored_from_session_save) {
        return false;
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
          || Number(data.updates || 0) !== 0
          || !data.snapshot
      ) {
        return false;
      }

      const savedRuntimeSnapshot = {
        ...pendingBootstrapRuntimeMemorySnapshot,
        index: 0,
      };

      pendingBootstrapRuntimeMemorySnapshot = null;
      setRuntimeMemoryDisplayMode("runtime");
      setRestoredSessionMemorySnapshot(null);

      if (window.stopMemoryGlow) {
        window.stopMemoryGlow();
      }

      // During persisted-session restore, page 0 must stay the saved runtime from
      // browser memory. Server updates=0 messages are bootstrap chatter/echoes.
      history.snapshots = [
        savedRuntimeSnapshot,
      ];
      history.index = 0;

      if (runtimeMemoryCount) {
        runtimeMemoryCount.textContent =
          String(savedRuntimeSnapshot.runtime_memory_updates || 0);
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
      const runtimeMemory =
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

      return {
        ...sourceSnapshot,
        session_id:
          sourceSnapshot.session_id
          || "browser_restore",
        index: 0,
        display_source: "saved_runtime_at_session_save",
        raw_memory: runtimeMemory,
        lines:
          Array.isArray(sourceSnapshot.lines)
            && sourceSnapshot.raw_memory === runtimeMemory
            ? sourceSnapshot.lines
            : splitMemoryTextLines(runtimeMemory)
              .map(parseRuntimeMemoryLine),
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
      const snapshot =
        (
          bootstrap
          && bootstrap.runtime_display_snapshot
        )
        || buildRuntimeMemoryDisplaySnapshot(
          bootstrap || {}
        )
        || buildDefaultRuntimeMemorySnapshot();

      applyRuntimeMemoryDisplaySnapshot(
        snapshot
      );
    }

    function getPersistedSessionBootstrap() {
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

      const eventSnapshots =
        (
          sessionMemory
          && Array.isArray(
            sessionMemory.session_event_snapshots
          )
          && sessionMemory.session_event_snapshots
        )
        || [];

      if (
          !sessionText
          && !eventSnapshots.length
      ) {
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

      return {
        type: "session_bootstrap",
        session_memory: sessionText,
        session_memory_source: sessionMemorySource,
        session_memory_updates:
          (
            sessionMemory
            && sessionMemory.session_memory_updates
          )
          || 0,
        session_event_snapshots: eventSnapshots,
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
