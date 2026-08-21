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
    applyBootstrapSceneTintShift: notInitialized,
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
      keys: runtimeStorageKeys,
      removeBrowserMemory,
      readLatestRuntimeMemory,
      writeLatestSavedSessionSnapshot,
      readLatestSavedSessionSnapshot,
      writeLatestSavedRuntimeMemory,
      readLatestSavedRuntimeMemory,
      buildPersistedRuntimeSnapshot,
      setBootSourceRuntimeSessionId,
      cloneRuntimeMemoryToCurrentSession,
      readLatestPreviousRuntimeMemory,
      collectOtherLatestRuntimeMemorySnapshots,
      clearOtherLatestRuntimeMemorySnapshots,
      getSavedRuntimeMemoryFallback,
      getCurrentLatestRuntimeMemoryStorageKey,
      getCurrentRuntimeSessionId,
      activateFactsMemorySession,
      shouldIsolateAnonymousStorage,
      isAnonymousModeEnabled,
    } = storage;

    let pendingBootstrapRuntimeMemorySnapshot = null;
    let lastStableRuntimeMemorySnapshot = null;
    let persistedSessionBootstrapCleared = false;
    let hasUnsavedSessionActivity = false;
    const BOOTSTRAP_SCENE_TINT_SHIFT_MS = 2000;
    let bootstrapSceneTintShiftSequence = 0;

    function getCurrentSavedSessionId() {
      return String(
        getCurrentRuntimeSessionId()
        || ""
      ).trim();
    }

    function prefersReducedSceneTintMotion() {
      return Boolean(
        window.matchMedia
        && window.matchMedia(
          "(prefers-reduced-motion: reduce)"
        ).matches
      );
    }

    function applyBootstrapSceneTintShift(apply) {
      if (typeof apply !== "function") {
        return false;
      }

      bootstrapSceneTintShiftSequence += 1;
      const sequence =
        bootstrapSceneTintShiftSequence;

      const sceneMain =
        document.querySelector("main");
      const sceneTint =
        document.getElementById("scene-jin-tint");

      if (
          prefersReducedSceneTintMotion()
          || (!sceneMain && !sceneTint)
      ) {
        return Boolean(apply());
      }

      const root =
        document.documentElement;
      const previousRootDuration =
        root.style.getPropertyValue(
          "--scene-jin-tint-transition-duration"
        );
      const previousMain = sceneMain
        ? {
            transition: sceneMain.style.transition,
            backgroundColor: sceneMain.style.backgroundColor,
          }
        : null;
      const previousTint = sceneTint
        ? {
            transition: sceneTint.style.transition,
            backgroundColor: sceneTint.style.backgroundColor,
            opacity: sceneTint.style.opacity,
          }
        : null;

      if (sceneMain) {
        const style =
          window.getComputedStyle(sceneMain);
        sceneMain.style.transition = "none";
        sceneMain.style.backgroundColor =
          style.backgroundColor;
      }

      if (sceneTint) {
        const style =
          window.getComputedStyle(sceneTint);
        sceneTint.style.transition = "none";
        sceneTint.style.backgroundColor =
          style.backgroundColor;
        sceneTint.style.opacity =
          style.opacity;
      }

      if (sceneMain) {
        sceneMain.getBoundingClientRect();
      } else if (sceneTint) {
        sceneTint.getBoundingClientRect();
      }

      const applied =
        Boolean(apply());
      const rootStyle =
        window.getComputedStyle(root);
      const targetMainColor =
        rootStyle.getPropertyValue("--scene-base-color").trim();
      const targetTintColor =
        rootStyle.getPropertyValue("--jin-color").trim();
      const targetTintOpacity =
        rootStyle.getPropertyValue("--scene-jin-tint-alpha").trim();

      root.style.setProperty(
        "--scene-jin-tint-transition-duration",
        `${BOOTSTRAP_SCENE_TINT_SHIFT_MS}ms`
      );

      window.requestAnimationFrame(() => {
        window.requestAnimationFrame(() => {
          if (sceneMain && targetMainColor) {
            sceneMain.style.transition =
              previousMain.transition;
            sceneMain.style.backgroundColor =
              targetMainColor;
          }

          if (sceneTint && targetTintColor) {
            sceneTint.style.transition =
              previousTint.transition;
            sceneTint.style.backgroundColor =
              targetTintColor;
          }

          if (sceneTint && targetTintOpacity) {
            sceneTint.style.opacity =
              targetTintOpacity;
          }

          window.setTimeout(() => {
            if (sequence !== bootstrapSceneTintShiftSequence) {
              return;
            }

            if (previousRootDuration) {
              root.style.setProperty(
                "--scene-jin-tint-transition-duration",
                previousRootDuration
              );
            } else {
              root.style.removeProperty(
                "--scene-jin-tint-transition-duration"
              );
            }

            if (sceneMain) {
              sceneMain.style.transition =
                previousMain.transition;
              sceneMain.style.backgroundColor =
                previousMain.backgroundColor;
            }

            if (sceneTint) {
              sceneTint.style.transition =
                previousTint.transition;
              sceneTint.style.backgroundColor =
                previousTint.backgroundColor;
              sceneTint.style.opacity =
                previousTint.opacity;
            }
          }, BOOTSTRAP_SCENE_TINT_SHIFT_MS + 80);
        });
      });

      return applied;
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
        readLatestSavedSessionSnapshot();
      const sameSession = Boolean(
        previousCheckpoint
        && typeof previousCheckpoint === "object"
        && !Array.isArray(previousCheckpoint)
        && String(previousCheckpoint.session_id || "").trim()
          === currentSessionId
      );
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

      writeLatestSavedRuntimeMemory({
        ...currentRuntime,
        version: currentRuntime.version || 1,
        session_id: currentSessionId,
        previous_session_id: previousSessionId,
        saved_at: savedAt,
        runtime_snapshot:
          buildCheckpointRuntimeSnapshot(
            currentRuntime.runtime_snapshot
          ),
      });

      writeLatestSavedSessionSnapshot({
        version: 1,
        session_id: currentSessionId,
        previous_session_id: previousSessionId,
        saved_at: savedAt,
        loaded_memory_ids:
          sessionSnapshot.loaded_memory_ids,
        session_snapshot: sessionSnapshot,
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
        display_source: "saved_runtime_checkpoint",
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
        display_source: "saved_runtime_checkpoint",
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
          && cloneRuntimeMemoryToCurrentSession
      ) {
        // Materialize the inherited L1 immediately under this fresh runtime
        // session id. Its new saved_at makes this session the direct
        // predecessor for the next boot, while booted_from_session_id keeps
        // the one-hop lineage explicit.
        cloneRuntimeMemoryToCurrentSession({
          version: 1,
          session_id: bootstrap.source_session_id,
          runtime_memory: bootstrap.runtime_memory,
          runtime_memory_updates:
            bootstrap.runtime_memory_updates || 0,
          runtime_snapshot:
            bootstrap.runtime_snapshot || null,
        });

        // The fresh tab immediately becomes the new live checkpoint, even
        // before the user sends another message. This keeps last-saved lineage
        // one hop wide instead of leaving it pointed at the older source tab.
        persistLiveSessionCheckpoint(
          bootstrap
        );
      }

      if (
          bootstrap
          && bootstrap.room_state
          && typeof bootstrap.room_state === "object"
          && window.JinPanels
          && typeof window.JinPanels.applyRoomState === "function"
      ) {
        const applyRoomState = () => {
          return window.JinPanels.applyRoomState(
            bootstrap.room_state,
            { persist: false }
          );
        };
        const avatarState =
          bootstrap.room_state.avatar
          && typeof bootstrap.room_state.avatar === "object"
          && !Array.isArray(bootstrap.room_state.avatar)
            ? bootstrap.room_state.avatar
            : {};

        if (String(avatarState.color || "").trim()) {
          applyBootstrapSceneTintShift(applyRoomState);
        } else {
          applyRoomState();
        }
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

      const browserCheckpoint =
        readLatestSavedSessionSnapshot();
      const browserLatestSavedRuntimeMemory =
        readLatestSavedRuntimeMemory();
      const browserLatestRuntimeMemory =
        readLatestPreviousRuntimeMemory
          ? readLatestPreviousRuntimeMemory()
          : null;

      let runtimeMemory =
        (
          browserLatestSavedRuntimeMemory
          && typeof browserLatestSavedRuntimeMemory === "object"
          && !Array.isArray(browserLatestSavedRuntimeMemory)
          && String(
            browserLatestSavedRuntimeMemory.runtime_memory
            || ""
          ).trim()
        )
          ? browserLatestSavedRuntimeMemory
          : (
              browserLatestRuntimeMemory
              && String(
                browserLatestRuntimeMemory.runtime_memory
                || ""
              ).trim()
                ? browserLatestRuntimeMemory
                : null
            );

      if (!runtimeMemory) {
        const savedRuntimeFallback =
          getSavedRuntimeMemoryFallback();

        if (savedRuntimeFallback) {
          runtimeMemory =
            savedRuntimeFallback.latest_saved_runtime_memory
            || savedRuntimeFallback.runtime_memory
            || null;
        }
      }

      if (!runtimeMemory) {
        return null;
      }

      const runtimeText =
        String(
          runtimeMemory.runtime_memory
          || ""
        ).trim();

      if (!runtimeText) {
        return null;
      }

      let sourceSessionId =
        String(
          runtimeMemory.session_id
          || (
            runtimeMemory.runtime_snapshot
            && runtimeMemory.runtime_snapshot.session_id
          )
          || ""
        ).trim();

      const checkpointMatchesSource = Boolean(
        browserCheckpoint
        && typeof browserCheckpoint === "object"
        && !Array.isArray(browserCheckpoint)
        && (
          !sourceSessionId
          || String(browserCheckpoint.session_id || "").trim()
            === sourceSessionId
        )
      );
      const checkpoint =
        checkpointMatchesSource
          ? browserCheckpoint
          : null;

      if (!sourceSessionId && checkpoint) {
        sourceSessionId =
          String(checkpoint.session_id || "").trim();
      }

      const previousSessionId =
        String(
          (
            checkpoint
            && checkpoint.previous_session_id
          )
          || runtimeMemory.previous_session_id
          || runtimeMemory.booted_from_session_id
          || ""
        ).trim();
      const sessionSnapshot =
        (
          checkpoint
          && checkpoint.session_snapshot
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

      const runtimeDisplaySnapshot =
        buildRuntimeMemoryDisplaySnapshot({
          runtime_memory: runtimeText,
          runtime_memory_updates:
            Number(
              runtimeMemory.runtime_memory_updates
              || 0
            ),
          runtime_snapshot:
            runtimeMemory.runtime_snapshot || null,
          source_session_id: sourceSessionId || null,
          previous_session_id: previousSessionId || null,
        })
        || buildDefaultRuntimeMemorySnapshot();

      return {
        ...sessionSnapshot,
        type: "session_bootstrap",
        source_session_id: sourceSessionId || null,
        previous_session_id: previousSessionId || null,
        saved_at:
          String(
            runtimeMemory.saved_at
            || (checkpoint && checkpoint.saved_at)
            || ""
          ).trim(),
        loaded_memory_ids:
          Array.from(new Set([
            ...(
              checkpoint
              && Array.isArray(checkpoint.loaded_memory_ids)
                ? checkpoint.loaded_memory_ids
                : []
            ),
            ...(
              Array.isArray(sessionSnapshot.loaded_memory_ids)
                ? sessionSnapshot.loaded_memory_ids
                : []
            ),
          ]))
            .map(item => String(item || "").trim())
            .filter(Boolean),
        runtime_memory: runtimeText,
        runtime_memory_updates:
          Number(
            runtimeMemory.runtime_memory_updates
            || 0
          ),
        runtime_snapshot:
          runtimeMemory.runtime_snapshot || null,
        runtime_display_snapshot: runtimeDisplaySnapshot,
      };
    }

    function clearPersistedSessionBootstrap() {
      persistedSessionBootstrapCleared = true;
      hasUnsavedSessionActivity = false;

      if (
          (typeof shouldIsolateAnonymousStorage === "function"
            && shouldIsolateAnonymousStorage())
          || (typeof isAnonymousModeEnabled === "function"
            && isAnonymousModeEnabled())
      ) {
        return;
      }

      removeBrowserMemory(
        runtimeStorageKeys.latestSavedSessionSnapshotStorageKey
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

    session.persistLiveSessionCheckpoint = persistLiveSessionCheckpoint;
    session.getRuntimeMemoryForSoftReconnect = getRuntimeMemoryForSoftReconnect;
    session.getInitialRuntimeMemoryBootstrap = getInitialRuntimeMemoryBootstrap;
    session.isReconnectInitialRuntimeMemoryUpdate = isReconnectInitialRuntimeMemoryUpdate;
    session.isLatestRuntimeMemoryDuplicate = isLatestRuntimeMemoryDuplicate;
    session.isBootstrapRuntimeMemoryDuplicate = isBootstrapRuntimeMemoryDuplicate;
    session.applyBootstrapSceneTintShift = applyBootstrapSceneTintShift;
    session.applyBootstrapRuntimeMemoryUpdate = applyBootstrapRuntimeMemoryUpdate;
    session.rememberStableRuntimeSnapshot = rememberStableRuntimeSnapshot;

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
  }
}());
