(function () {
  "use strict";

  window.JinRuntime = window.JinRuntime || {};

  const session = {
    init,
    persistLiveSessionCheckpoint: notInitialized,
    getRuntimeMemoryForSoftReconnect: notInitialized,
    getInitialRuntimeMemoryBootstrap: notInitialized,
    isReconnectInitialRuntimeMemoryUpdate: notInitialized,
    isLatestRuntimeMemoryDuplicate: notInitialized,
    isBootstrapRuntimeMemoryDuplicate: notInitialized,
    applyBootstrapRuntimeMemoryUpdate: notInitialized,
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
      setRuntimeMemoryDisplayMode,
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
      readLatestRuntimeMemory,
      writeLatestRuntimeMemory,
      writeSessionCheckpoint,
      readSessionCheckpoint,
      clearSessionCheckpoint,
      markSessionCheckpointUserActivity,
      buildPersistedRuntimeSnapshot,
      setBootSourceRuntimeSessionId,
      hydrateLiveRuntimeMemoryFromCheckpoint,
      getCurrentRuntimeSessionId,
      activateFactsMemorySession,
      shouldIsolateAnonymousStorage,
      isAnonymousModeEnabled,
    } = storage;

    let pendingBootstrapRuntimeMemorySnapshot = null;
    let lastStableRuntimeMemorySnapshot = null;
    let hasUnsavedSessionActivity = false;

    function getCurrentSavedSessionId() {
      return String(
        getCurrentRuntimeSessionId()
        || ""
      ).trim();
    }

    function normalizeLiveSessionSnapshot(
      data,
      fallbackSnapshot = null
    ) {
      const source =
        (
          data
          && data.session_snapshot
          && typeof data.session_snapshot === "object"
          && !Array.isArray(data.session_snapshot)
        )
          ? {
              ...data.session_snapshot,
            }
          : (
              fallbackSnapshot
              && typeof fallbackSnapshot === "object"
              && !Array.isArray(fallbackSnapshot)
                ? {
                    ...fallbackSnapshot,
                  }
                : {}
            );

      const runtimeSnapshotSource =
        (
          data
          && data.snapshot
          && typeof data.snapshot === "object"
          && !Array.isArray(data.snapshot)
        )
          ? data.snapshot
          : (
              data
              && data.runtime_snapshot
              && typeof data.runtime_snapshot === "object"
              && !Array.isArray(data.runtime_snapshot)
                ? data.runtime_snapshot
                : {}
            );
      const runtimeSnapshot = runtimeSnapshotSource;

      const loadedMemoryIds =
        typeof getLoadedDelayedMemoryReportIds === "function"
          ? getLoadedDelayedMemoryReportIds()
          : (
              Array.isArray(source.loaded_memory_ids)
                ? source.loaded_memory_ids
                : (
                    data
                    && Array.isArray(data.loaded_memory_ids)
                      ? data.loaded_memory_ids
                      : []
                  )
            );

      return {
        ...source,
        recent_turns:
          Array.isArray(source.recent_turns)
            ? source.recent_turns
            : (
                data
                && Array.isArray(data.recent_turns)
                  ? data.recent_turns
                  : []
              ),
        previous_reasoning:
          String(
            source.previous_reasoning
            || (data && data.previous_reasoning)
            || ""
          ),
        session_actions:
          Array.isArray(source.session_actions)
            ? source.session_actions
            : (
                data
                && Array.isArray(data.session_actions)
                  ? data.session_actions
                  : []
              ),
        tool_results:
          Array.isArray(source.tool_results)
            ? source.tool_results
            : (
                data
                && Array.isArray(data.tool_results)
                  ? data.tool_results
                  : []
              ),
        loaded_memory_ids:
          Array.from(new Set(
            loadedMemoryIds
              .map(item => String(item || "").trim())
              .filter(Boolean)
          )),
        attached_file_ids:
          (
            Array.isArray(source.attached_file_ids)
              ? source.attached_file_ids
              : (
                  data
                  && Array.isArray(data.attached_file_ids)
                    ? data.attached_file_ids
                    : []
                )
          )
            .map(item => String(item || "").trim())
            .filter(Boolean),
        active_memory_records:
          Array.isArray(source.active_memory_records)
            ? source.active_memory_records
            : (
                data
                && Array.isArray(data.active_memory_records)
                  ? data.active_memory_records
                  : []
              ),
        runtime_turn_counter:
          Number(
            source.runtime_turn_counter
            || (data && data.runtime_turn_counter)
            || runtimeSnapshot.runtime_turn_counter
            || 0
          ),
        turn_number:
          Number(
            source.turn_number
            || (data && data.turn_number)
            || runtimeSnapshot.turn_number
            || 0
          ),
        user_message_count:
          Number(
            source.user_message_count
            || (data && data.user_message_count)
            || runtimeSnapshot.user_message_count
            || 0
          ),
        assistant_message_count:
          Number(
            source.assistant_message_count
            || (data && data.assistant_message_count)
            || runtimeSnapshot.assistant_message_count
            || 0
          ),
        current_session_user_message_count:
          Number(
            Object.prototype.hasOwnProperty.call(
              source,
              "current_session_user_message_count"
            )
              ? source.current_session_user_message_count
              : (
                  data
                  && Object.prototype.hasOwnProperty.call(
                    data,
                    "current_session_user_message_count"
                  )
                    ? data.current_session_user_message_count
                    : (runtimeSnapshot.current_session_user_message_count || 0)
                )
          ),
        current_session_assistant_message_count:
          Number(
            Object.prototype.hasOwnProperty.call(
              source,
              "current_session_assistant_message_count"
            )
              ? source.current_session_assistant_message_count
              : (
                  data
                  && Object.prototype.hasOwnProperty.call(
                    data,
                    "current_session_assistant_message_count"
                  )
                    ? data.current_session_assistant_message_count
                    : (runtimeSnapshot.current_session_assistant_message_count || 0)
                )
          ),
        current_jin_color:
          String(
            source.current_jin_color
            || (data && data.current_jin_color)
            || ""
          ).trim(),
        current_jin_size:
          (
            source.current_jin_size
            && typeof source.current_jin_size === "object"
            && !Array.isArray(source.current_jin_size)
          )
            ? {
                ...source.current_jin_size,
              }
            : (
                data
                && data.current_jin_size
                && typeof data.current_jin_size === "object"
                && !Array.isArray(data.current_jin_size)
                  ? {
                      ...data.current_jin_size,
                    }
                  : null
              ),
        current_jin_position:
          (
            source.current_jin_position
            && typeof source.current_jin_position === "object"
            && !Array.isArray(source.current_jin_position)
          )
            ? {
                ...source.current_jin_position,
              }
            : (
                data
                && data.current_jin_position
                && typeof data.current_jin_position === "object"
                && !Array.isArray(data.current_jin_position)
                  ? {
                      ...data.current_jin_position,
                    }
                  : null
              ),
        current_jin_collapsed:
          Object.prototype.hasOwnProperty.call(
            source,
            "current_jin_collapsed"
          )
            ? Boolean(source.current_jin_collapsed)
            : Boolean(
                data
                && data.current_jin_collapsed
              ),
        current_jin_speed:
          Number(
            source.current_jin_speed
            || (data && data.current_jin_speed)
            || 900
          ),
        current_window_size:
          (
            source.current_window_size
            && typeof source.current_window_size === "object"
            && !Array.isArray(source.current_window_size)
          )
            ? {
                ...source.current_window_size,
              }
            : (
                data
                && data.current_window_size
                && typeof data.current_window_size === "object"
                && !Array.isArray(data.current_window_size)
                  ? {
                      ...data.current_window_size,
                    }
                  : null
              ),
        room_state:
          (
            source.room_state
            && typeof source.room_state === "object"
            && !Array.isArray(source.room_state)
          )
            ? {
                ...source.room_state,
              }
            : (
                data
                && data.room_state
                && typeof data.room_state === "object"
                && !Array.isArray(data.room_state)
                  ? {
                      ...data.room_state,
                    }
                  : (
                      fallbackSnapshot
                      && fallbackSnapshot.room_state
                      && typeof fallbackSnapshot.room_state === "object"
                      && !Array.isArray(fallbackSnapshot.room_state)
                        ? {
                            ...fallbackSnapshot.room_state,
                          }
                        : null
                    )
              ),
      };
    }

    function persistLiveSessionCheckpoint(data) {
      if (
          (typeof shouldIsolateAnonymousStorage === "function"
            && shouldIsolateAnonymousStorage())
          || (typeof isAnonymousModeEnabled === "function"
            && isAnonymousModeEnabled())
      ) {
        return false;
      }

      const currentRuntime =
        readLatestRuntimeMemory();

      if (
          !currentRuntime
          || typeof currentRuntime !== "object"
          || Array.isArray(currentRuntime)
          || !String(currentRuntime.runtime_memory || "").trim()
      ) {
        return false;
      }

      const currentSessionId =
        getCurrentSavedSessionId();
      const savedAt =
        new Date().toISOString();
      const previousCheckpoint =
        readSessionCheckpoint();
      const sameSession = Boolean(
        previousCheckpoint
        && typeof previousCheckpoint === "object"
        && !Array.isArray(previousCheckpoint)
        && String(previousCheckpoint.session_id || "").trim()
          === currentSessionId
      );
      const completedTurnCommit = Boolean(
        data
        && data.completed_turn_commit === true
      );
      const sessionMoved = Boolean(
        hasUnsavedSessionActivity
        || completedTurnCommit
      );

      // Opening/reloading a tab creates a runtime id, not a new conversation.
      // The common checkpoint switches to this session only after a real move.
      // A user send marks activity immediately; completedTurnCommit is only a
      // server-side fallback for paths that reached us without that UI mark.
      if (
          previousCheckpoint
          && !sameSession
          && !sessionMoved
      ) {
        return false;
      }
      const previousSessionId =
        String(
          currentRuntime.previous_session_id
          || currentRuntime.booted_from_session_id
          || (
            !sameSession
            && previousCheckpoint
            && previousCheckpoint.session_id
          )
          || ""
        ).trim() || null;
      const previousSessionSnapshot =
        (
          sameSession
          && previousCheckpoint.session_snapshot
          && typeof previousCheckpoint.session_snapshot === "object"
          && !Array.isArray(previousCheckpoint.session_snapshot)
        )
          ? previousCheckpoint.session_snapshot
          : null;
      const sessionSnapshot =
        normalizeLiveSessionSnapshot(
          data || {},
          previousSessionSnapshot
        );
      const previousConversationCommittedAt =
        String(
          currentRuntime.conversation_committed_at
          || (
            sameSession
            && previousCheckpoint
            && previousCheckpoint.conversation_committed_at
          )
          || ""
        ).trim();
      const conversationCommittedAt =
        completedTurnCommit
          ? savedAt
          : previousConversationCommittedAt;

      // Keep completed-turn time separate from session movement. A USER-only
      // interrupted session may already be the latest checkpoint, but this
      // timestamp still advances only after a completed visible turn.
      if (completedTurnCommit) {
        writeLatestRuntimeMemory({
          ...currentRuntime,
          version: currentRuntime.version || 1,
          session_id: currentSessionId,
          previous_session_id: previousSessionId,
          conversation_committed_at: conversationCommittedAt,
          session_snapshot: sessionSnapshot,
          runtime_snapshot:
            buildCheckpointRuntimeSnapshot(
              currentRuntime.runtime_snapshot
            ),
        });
      }

      const checkpointWritten =
        writeSessionCheckpoint({
          version: 2,
          state: "checkpoint",
          session_id: currentSessionId,
          previous_session_id: previousSessionId,
          saved_at: savedAt,
          conversation_committed_at: conversationCommittedAt,
          runtime_memory:
            currentRuntime.runtime_memory,
          runtime_memory_updates:
            Number(currentRuntime.runtime_memory_updates || 0),
          runtime_snapshot:
            buildCheckpointRuntimeSnapshot(
              currentRuntime.runtime_snapshot
            ),
          session_snapshot: sessionSnapshot,
        });

      if (checkpointWritten) {
        // The move is now represented by a full current-session checkpoint.
        // Clear the dirty bit so a late background echo from this tab cannot
        // later rewind a newer session that has already moved.
        hasUnsavedSessionActivity = false;
      }

      return Boolean(checkpointWritten);
    }

    function clearPersistedToolResultsCheckpoint() {
      if (
          (typeof shouldIsolateAnonymousStorage === "function"
            && shouldIsolateAnonymousStorage())
          || (typeof isAnonymousModeEnabled === "function"
            && isAnonymousModeEnabled())
      ) {
        return false;
      }

      const previousCheckpoint =
        readSessionCheckpoint();

      if (
          !previousCheckpoint
          || typeof previousCheckpoint !== "object"
          || Array.isArray(previousCheckpoint)
      ) {
        return false;
      }

      const previousSessionSnapshot =
        (
          previousCheckpoint.session_snapshot
          && typeof previousCheckpoint.session_snapshot === "object"
          && !Array.isArray(previousCheckpoint.session_snapshot)
        )
          ? previousCheckpoint.session_snapshot
          : {};

      // CLEAN_TOOL_RESULTS mutates only one bootstrap field. Preserve the
      // checkpoint timestamp/lineage verbatim: advancing saved_at here makes
      // the browser checkpoint look newer than the raw chat-log tail, which
      // suppresses archive enrichment for dialogue/reasoning/actions/files.
      writeSessionCheckpoint({
        ...previousCheckpoint,
        session_snapshot: {
          ...previousSessionSnapshot,
          tool_results: [],
          tool_results_cleared_at: new Date().toISOString(),
        },
      });

      return true;
    }


    function buildCheckpointRuntimeSnapshot(snapshot) {
      const persistedSnapshot =
        buildPersistedRuntimeSnapshot(
          snapshot
        );

      return persistedSnapshot
        ? {
            ...persistedSnapshot,
            session_id:
              String(
                persistedSnapshot.session_id
                || ""
              ).trim()
              || getCurrentSavedSessionId(),
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

    function isUsableStableRuntimeSnapshot(snapshot) {
      if (!snapshot || typeof snapshot !== "object") {
        return false;
      }

      const runtimeMemory =
        String(snapshot.raw_memory || "").trim();

      return Boolean(
        runtimeMemory
        && runtimeMemory !== defaultRuntimeMemoryText
        && snapshot.display_source !== "default_runtime_memory"
      );
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

    function getRuntimeMemoryForSoftReconnect() {
      return getLatestStableRuntimeMemoryObject()
        || runtimeMemoryObjectFromPersistedRuntime(
          readLatestRuntimeMemory()
        );
    }

    function getSoftReconnectRuntimeResume() {
      const runtimeMemory =
        getRuntimeMemoryForSoftReconnect();

      const runtimeText =
        String(
          runtimeMemory
          && runtimeMemory.runtime_memory
          || ""
        ).trim();

      if (!runtimeText) {
        return null;
      }

      const persistedRuntime =
        readLatestRuntimeMemory();
      const sourceSessionId =
        String(
          persistedRuntime
          && persistedRuntime.session_id
          || ""
        ).trim();
      const previousSessionId =
        String(
          persistedRuntime
          && (
            persistedRuntime.previous_session_id
            || persistedRuntime.booted_from_session_id
          )
          || ""
        ).trim();

      return {
        type: "runtime_resume",
        frame_memory_index: Math.max(
          0,
          Number(history.index || 0)
            + Number(history.displayIndexOffset || 0)
        ),
        source_session_id: sourceSessionId || null,
        previous_session_id: previousSessionId || null,
        runtime_memory: runtimeText,
        runtime_memory_updates:
          Number(
            runtimeMemory.runtime_memory_updates
            || 0
          ),
        runtime_snapshot:
          runtimeMemory.runtime_snapshot || null,
        loaded_memory_ids:
          typeof getLoadedDelayedMemoryReportIds === "function"
            ? getLoadedDelayedMemoryReportIds()
            : [],
      };
    }

    function getInitialRuntimeMemoryBootstrap() {
      // Full page/new-tab continuity is resolved in
      // getPersistedSessionBootstrap(), which follows the continuously updated
      // last-saved pair and keeps its source_session_id lineage.
      return null;
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
          && latestSnapshot.restored_from_checkpoint
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
      if (latestSnapshot && latestSnapshot.restored_from_checkpoint) {
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
      // the provisional browser page in-place, preserving the saved lifecycle
      // timestamps/strengths instead of rebasing them to the restore moment.
      const restoredRuntimeSnapshot = {
        ...data.snapshot,
        index: 0,
        display_source: "session_checkpoint",
        restored_from_checkpoint: true,
        runtime_memory_updates: Number(
          data.updates
          || data.snapshot.runtime_memory_updates
          || pendingBootstrapRuntimeMemorySnapshot.runtime_memory_updates
          || 0
        ),
      };

      pendingBootstrapRuntimeMemorySnapshot = null;
      setRuntimeMemoryDisplayMode("runtime");

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

    function buildRuntimeMemoryDisplaySnapshot(data) {
      const isArchivedRestore = Boolean(
        data
        && data.archived_session_restore === true
      );

      const sourceSnapshot =
        (
          data
          && data.runtime_snapshot
          && typeof data.runtime_snapshot === "object"
          && !Array.isArray(data.runtime_snapshot)
        )
          ? data.runtime_snapshot
          : {};

      const snapshotRuntimeMemory =
        stripActiveMemoryRuntimeMemoryText(
          sourceSnapshot.raw_memory || ""
        ).trim();

      let runtimeMemory =
        stripActiveMemoryRuntimeMemoryText(
          (
            data
            && (
              data.runtime_memory
              || data.memory
              || snapshotRuntimeMemory
            )
          )
          || ""
        ).trim();

      if (isArchivedRestore) {
        if (snapshotRuntimeMemory) {
          // The persisted snapshot is authoritative for lifecycle history.
          // Use the exact raw memory it was built from so its timestamp and
          // per-line created_at/updated_at values remain valid.
          runtimeMemory = snapshotRuntimeMemory;
        } else {
          // Old log-only archives contain relative "created/updated ... ago"
          // display suffixes but no absolute timestamps. Strip the suffixes;
          // never manufacture fresh lifecycle timestamps during restore.
          runtimeMemory =
            stripArchivedRuntimeLifecycleMetadata(
              runtimeMemory
            );
        }
      }

      if (!runtimeMemory) {
        return null;
      }

      const parsedLines =
        splitMemoryTextLines(runtimeMemory)
          .map(parseRuntimeMemoryLine);
      const sourceSnapshotMatches = Boolean(
        Array.isArray(sourceSnapshot.lines)
        && sourceSnapshot.lines.length
        && stripActiveMemoryRuntimeMemoryText(
          sourceSnapshot.raw_memory || ""
        ).trim() === runtimeMemory
      );

      return {
        ...sourceSnapshot,
        session_id:
          sourceSnapshot.session_id
          || (data && data.source_session_id)
          || (data && data.previous_session_id)
          || "browser_restore",
        index: 0,
        display_source: "session_checkpoint",
        raw_memory: runtimeMemory,
        lines:
          sourceSnapshotMatches
            ? sourceSnapshot.lines.map(line => ({ ...line }))
            : parsedLines,
        restored_from_checkpoint: true,
        runtime_memory_updates:
          Number(
            (
              data
              && (
                data.runtime_memory_updates
                || data.updates
              )
            )
            || sourceSnapshot.runtime_memory_updates
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
      pendingBootstrapRuntimeMemorySnapshot =
        displaySnapshot.restored_from_checkpoint
          ? displaySnapshot
          : null;
      history.snapshots = [displaySnapshot];
      history.index = 0;
      history.displayIndexOffset =
        displaySnapshot.restored_from_checkpoint
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
          (typeof shouldIsolateAnonymousStorage === "function"
            && shouldIsolateAnonymousStorage())
          || (typeof isAnonymousModeEnabled === "function"
            && isAnonymousModeEnabled())
      ) {
        return;
      }

      if (
          bootstrap
          && bootstrap.source_session_id
          && setBootSourceRuntimeSessionId
      ) {
        setBootSourceRuntimeSessionId(
          bootstrap.source_session_id
        );
      }

      if (
          bootstrap
          && bootstrap.source_session_id
          && String(bootstrap.runtime_memory || "").trim()
          && hydrateLiveRuntimeMemoryFromCheckpoint
      ) {
        // Materialize inherited L1 only in this page's ephemeral live cache.
        // Opening a tab does not create another durable per-session record and
        // does not advance the common conversation checkpoint.
        hydrateLiveRuntimeMemoryFromCheckpoint({
          version: 2,
          session_id: bootstrap.source_session_id,
          previous_session_id:
            bootstrap.previous_session_id || null,
          saved_at:
            String(bootstrap.saved_at || "").trim(),
          conversation_committed_at:
            String(
              bootstrap.conversation_committed_at || ""
            ).trim(),
          runtime_memory: bootstrap.runtime_memory,
          runtime_memory_updates:
            bootstrap.runtime_memory_updates || 0,
          runtime_snapshot:
            bootstrap.runtime_snapshot || null,
        });
      }

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
          (typeof shouldIsolateAnonymousStorage === "function"
            && shouldIsolateAnonymousStorage())
          || (typeof isAnonymousModeEnabled === "function"
            && isAnonymousModeEnabled())
      ) {
        return null;
      }

      if (
        window.jinArchivedSessionBootstrap
        && typeof window.jinArchivedSessionBootstrap === "object"
      ) {
        return {
          ...window.jinArchivedSessionBootstrap,
        };
      }

      const checkpoint =
        readSessionCheckpoint();

      if (!checkpoint) {
        return null;
      }

      const sourceSessionId =
        String(checkpoint.session_id || "").trim();

      const previousSessionId =
        String(
          checkpoint.previous_session_id
          || ""
        ).trim();
      const sessionSnapshot =
        (
          checkpoint.session_snapshot
          && typeof checkpoint.session_snapshot === "object"
          && !Array.isArray(checkpoint.session_snapshot)
        )
          ? {
              ...checkpoint.session_snapshot,
            }
          : {};

      if (
          sourceSessionId
          && setBootSourceRuntimeSessionId
      ) {
        setBootSourceRuntimeSessionId(
          sourceSessionId
        );
      }

      const runtimeText =
        String(checkpoint.runtime_memory || "").trim();
      const runtimeDisplaySnapshot = runtimeText
        ? buildRuntimeMemoryDisplaySnapshot({
            runtime_memory: runtimeText,
            runtime_memory_updates:
              Number(checkpoint.runtime_memory_updates || 0),
            runtime_snapshot:
              checkpoint.runtime_snapshot || null,
            source_session_id: sourceSessionId || null,
            previous_session_id: previousSessionId || null,
          })
        : null;

      return {
        ...sessionSnapshot,
        type: "session_bootstrap",
        source_session_id: sourceSessionId || null,
        previous_session_id: previousSessionId || null,
        conversation_committed_at:
          String(
            checkpoint.conversation_committed_at || ""
          ).trim(),
        saved_at:
          String(checkpoint.saved_at || "").trim(),
        loaded_memory_ids:
          Array.from(new Set(
            Array.isArray(sessionSnapshot.loaded_memory_ids)
              ? sessionSnapshot.loaded_memory_ids
              : []
          ))
            .map(item => String(item || "").trim())
            .filter(Boolean),
        runtime_memory: runtimeText,
        runtime_memory_updates:
          Number(checkpoint.runtime_memory_updates || 0),
        frame_memory_index: runtimeText ? 1 : 0,
        runtime_snapshot:
          checkpoint.runtime_snapshot || null,
        runtime_display_snapshot: runtimeDisplaySnapshot,
      };
    }

    function clearPersistedSessionBootstrap() {
      hasUnsavedSessionActivity = false;

      if (
          (typeof shouldIsolateAnonymousStorage === "function"
            && shouldIsolateAnonymousStorage())
          || (typeof isAnonymousModeEnabled === "function"
            && isAnonymousModeEnabled())
      ) {
        return;
      }

      clearSessionCheckpoint();
    }

    function markSessionActivityDirty() {
      markSessionCheckpointUserActivity();
      hasUnsavedSessionActivity = true;
    }

    session.persistLiveSessionCheckpoint = persistLiveSessionCheckpoint;
    session.clearPersistedToolResultsCheckpoint = clearPersistedToolResultsCheckpoint;
    session.getRuntimeMemoryForSoftReconnect = getRuntimeMemoryForSoftReconnect;
    session.getInitialRuntimeMemoryBootstrap = getInitialRuntimeMemoryBootstrap;
    session.isReconnectInitialRuntimeMemoryUpdate = isReconnectInitialRuntimeMemoryUpdate;
    session.isLatestRuntimeMemoryDuplicate = isLatestRuntimeMemoryDuplicate;
    session.isBootstrapRuntimeMemoryDuplicate = isBootstrapRuntimeMemoryDuplicate;
    session.applyBootstrapRuntimeMemoryUpdate = applyBootstrapRuntimeMemoryUpdate;
    session.rememberStableRuntimeSnapshot = rememberStableRuntimeSnapshot;

    window.getSoftReconnectRuntimeResume = getSoftReconnectRuntimeResume;
    window.getInitialRuntimeMemoryBootstrap = getInitialRuntimeMemoryBootstrap;
    window.applyPersistedSessionBootstrap = applyPersistedSessionBootstrap;
    window.getPersistedSessionBootstrap = getPersistedSessionBootstrap;
    window.clearPersistedSessionBootstrap = clearPersistedSessionBootstrap;
    window.markSessionActivityDirty = markSessionActivityDirty;
  }
}());
