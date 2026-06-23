(function () {
  "use strict";

  const root = window.JinRuntime = window.JinRuntime || {};

  const runtimeResponseFeedbackKey =
    "JIN_LAST_RESPONSE_USER_FEEDBACK";

  const runtimeResponseFeedbackDislikedValue =
    "User disliked your last response. "
    + "Before answering, find and understand why it failed using context or memory, then start the next reply with a brief acknowledgement of that miss, then continue with a concrete corrected answer.";

  const runtimeResponseFeedbackNeutralValue =
    "User gave neutral feedback to your last response. "
    + "Continue carefully without changing course too much.";

  const runtimeResponseFeedbackLikedValue =
    "User liked your last response. "
    + "Keep the current direction.";

  const runtimeResponseFeedbackRatings = {
    disliked: "disliked",
    neutral: "neutral",
    liked: "liked",
  };

  // UI buttons can still use visual button names. Convert them only at the
  // browser event boundary. Runtime memory and server payloads stay canonical:
  // disliked / neutral / liked.
  const runtimeResponseFeedbackButtonRatings = {
    minus: "disliked",
    zero: "neutral",
    plus: "liked",
  };

  let deps = null;
  let pendingRuntimeResponseFeedback = null;
  let runtimeResponseFeedbackCommitted = false;

  const jinAnswerRatingL1Gate = {
    generation: 0,
    waiting: false,
    waitingGeneration: 0,
    readyGeneration: 0,
    baselineUpdates: 0,
    // All gate generations strictly below this value are permanently locked:
    // the user has already submitted a subsequent message, so retroactive
    // ratings for those turns must be silently dropped.
    lockedBelowGeneration: 0,
  };

  function ensureDeps() {
    if (!deps) {
      throw new Error(
        "JinRuntime.feedback.init must be called before using feedback"
      );
    }
    return deps;
  }

  function init(nextDeps) {
    deps = nextDeps || {};
    return api;
  }

  function getLatestRuntimeMemoryUpdatesForRatingGate() {
    const runtimeDeps = ensureDeps();

    if (typeof runtimeDeps.getLatestRuntimeMemoryUpdates === "function") {
      return Number(
        runtimeDeps.getLatestRuntimeMemoryUpdates() || 0
      );
    }

    const snapshots = typeof runtimeDeps.getSnapshots === "function"
      ? runtimeDeps.getSnapshots()
      : [];

    const latestSnapshot = snapshots.length
      ? snapshots[snapshots.length - 1]
      : null;

    if (latestSnapshot && latestSnapshot.restored_from_session_save) {
      return 0;
    }

    return Number(
      (
        latestSnapshot
        && latestSnapshot.runtime_memory_updates
      )
      || (
        typeof runtimeDeps.getRuntimeMemoryCountText === "function"
          ? runtimeDeps.getRuntimeMemoryCountText()
          : 0
      )
      || 0
    );
  }

  function markL1ReadyFromRuntimeUpdate(
    data,
    snapshotIndex = null
  ) {
    if (!jinAnswerRatingL1Gate.waiting) {
      return;
    }

    const incomingUpdates = Number(
      data && data.updates || 0
    );

    if (incomingUpdates <= jinAnswerRatingL1Gate.baselineUpdates) {
      return;
    }

    jinAnswerRatingL1Gate.waiting = false;
    jinAnswerRatingL1Gate.readyGeneration =
      jinAnswerRatingL1Gate.waitingGeneration;
    runtimeResponseFeedbackCommitted = false;

    const rawSnapshotIndex =
      snapshotIndex === undefined
        ? null
        : snapshotIndex;

    const numericSnapshotIndex = Number(
      rawSnapshotIndex
    );

    const resolvedSnapshotIndex = (
      rawSnapshotIndex !== null
      && rawSnapshotIndex !== ""
      && Number.isInteger(numericSnapshotIndex)
    )
      ? numericSnapshotIndex
      : null;

    document
      .querySelectorAll(
        ".jin-chat-bubble-service[data-rating-gate-generation]"
      )
      .forEach((bubble) => {
        if (
            Number(bubble.dataset.ratingGateGeneration || 0)
            === jinAnswerRatingL1Gate.readyGeneration
        ) {
          bubble.dataset.ratingL1Ready = "true";

          if (resolvedSnapshotIndex !== null) {
            bubble.dataset.runtimeSnapshotIndex =
              String(resolvedSnapshotIndex);
          }

          bubble.classList.remove(
            "jin-rating-l1-waiting"
          );
        }
      });

    window.dispatchEvent(
      new CustomEvent(
        "jin:l1-rating-gate-ready",
        {
          detail: {
            generation: jinAnswerRatingL1Gate.readyGeneration,
            updates: incomingUpdates,
            snapshotIndex: resolvedSnapshotIndex,
          },
        }
      )
    );
  }

  function startL1GateForTurn() {
    jinAnswerRatingL1Gate.generation += 1;
    jinAnswerRatingL1Gate.waiting = true;
    jinAnswerRatingL1Gate.waitingGeneration =
      jinAnswerRatingL1Gate.generation;
    jinAnswerRatingL1Gate.baselineUpdates =
      getLatestRuntimeMemoryUpdatesForRatingGate();

    // Hard-lock every bubble that belongs to a generation older than the one
    // we are about to start. This is the authoritative guard: the user has
    // just sent a new message, so rating any previous assistant turn is no
    // longer valid regardless of the committed/waiting state of the feedback
    // flags.
    jinAnswerRatingL1Gate.lockedBelowGeneration =
      jinAnswerRatingL1Gate.generation;

    if (typeof document !== "undefined") {
      document
        .querySelectorAll(
          ".jin-chat-bubble-service[data-rating-gate-generation]"
        )
        .forEach((bubble) => {
          const bubbleGen = Number(
            bubble.dataset.ratingGateGeneration || 0
          );
          if (bubbleGen < jinAnswerRatingL1Gate.lockedBelowGeneration) {
            bubble.classList.remove("jin-rating-selected-active");
            bubble.classList.add("jin-rating-committed");
            bubble.dataset.ratingCommitted = "true";
            bubble.dataset.ratingPastTurn = "true";
          }
        });
    }

    return {
      generation: jinAnswerRatingL1Gate.waitingGeneration,
      baselineUpdates: jinAnswerRatingL1Gate.baselineUpdates,
    };
  }

  function getL1GateState() {
    return {
      ...jinAnswerRatingL1Gate,
    };
  }

  function isReadyForGateGeneration(generation) {
    const gateGeneration = Number(generation || 0);

    if (!gateGeneration) {
      return !jinAnswerRatingL1Gate.waiting;
    }

    return gateGeneration === jinAnswerRatingL1Gate.readyGeneration;
  }

  function normalizeRating(rating) {
    const rawRating =
      String(rating || "").trim().toLowerCase();

    return (
      runtimeResponseFeedbackRatings[rawRating]
      || runtimeResponseFeedbackButtonRatings[rawRating]
      || null
    );
  }

  function buildValue(feedback) {
    if (feedback.rating === "disliked") {
      return runtimeResponseFeedbackDislikedValue;
    }

    if (feedback.rating === "liked") {
      return runtimeResponseFeedbackLikedValue;
    }

    return runtimeResponseFeedbackNeutralValue;
  }

  // In-place rating mutation: rating clicks are part of the current L1 page,
  // not a new runtime memory page.
  function getLatestSnapshotIndexForMutation() {
    const runtimeDeps = ensureDeps();
    const snapshots = typeof runtimeDeps.getSnapshots === "function"
      ? runtimeDeps.getSnapshots()
      : [];

    return snapshots.length
      ? snapshots.length - 1
      : null;
  }

  function resolveFeedbackSnapshotIndex(detail) {
    const rawSnapshotIndex = detail
      ? (
        detail.runtimeSnapshotIndex
        ?? detail.snapshotIndex
        ?? null
      )
      : null;

    const incomingGeneration = Number(
      detail && detail.ratingGateGeneration || 0
    );

    // A rating click for the generation that has just become L1-ready must
    // always mutate the newest runtime snapshot. Bubble dataset values can be
    // stale when the hover zones were attached before the final L1-ready event
    // rewrote runtimeSnapshotIndex, so the server receives the right feedback
    // while the visible panel mutates the previous page. Prefer the current
    // runtime history tail for the active ready generation.
    if (
        incomingGeneration > 0
        && incomingGeneration === jinAnswerRatingL1Gate.readyGeneration
    ) {
      const latestSnapshotIndex = getLatestSnapshotIndexForMutation();

      if (latestSnapshotIndex !== null) {
        return latestSnapshotIndex;
      }
    }

    return rawSnapshotIndex;
  }

  function getCurrentSnapshotForMutation(feedback = null) {
    const runtimeDeps = ensureDeps();
    const snapshots = typeof runtimeDeps.getSnapshots === "function"
      ? runtimeDeps.getSnapshots()
      : [];

    if (!snapshots.length) {
      return null;
    }

    const rawSnapshotIndex = feedback
      ? (
        feedback.runtimeSnapshotIndex
        ?? feedback.snapshotIndex
        ?? null
      )
      : null;

    const explicitSnapshotIndex = Number(
      rawSnapshotIndex
    );

    if (
        rawSnapshotIndex !== null
        && rawSnapshotIndex !== ""
        && Number.isInteger(explicitSnapshotIndex)
    ) {
      const explicitSnapshot = snapshots[explicitSnapshotIndex];

      if (explicitSnapshot) {
        return explicitSnapshot;
      }
    }

    const currentIndex = typeof runtimeDeps.getCurrentIndex === "function"
      ? runtimeDeps.getCurrentIndex()
      : -1;
    const current = snapshots[currentIndex];
    const displayMode = typeof runtimeDeps.getDisplayMode === "function"
      ? runtimeDeps.getDisplayMode()
      : "runtime";

    if (current && displayMode === "runtime") {
      return current;
    }

    return snapshots[snapshots.length - 1];
  }

  function getLineIdentity(line) {
    const key =
      String(line && line.key || "")
        .trim()
        .toLowerCase();

    const value =
      String(line && line.value || "")
        .trim();

    return `${key}\u0000${value}`;
  }

  function buildPreviousLineMaps(snapshot) {
    const byIdentity = new Map();
    const byKey = new Map();

    (snapshot && snapshot.lines || [])
      .forEach((line) => {
        if (!line || !line.key) {
          return;
        }

        const key =
          String(line.key || "")
            .trim()
            .toLowerCase();

        if (!key) {
          return;
        }

        byKey.set(key, line);
        byIdentity.set(
          getLineIdentity(line),
          line
        );
      });

    return {
      byIdentity,
      byKey,
    };
  }

  function preserveLineDiff(
    parsed,
    previousMaps
  ) {
    if (!parsed || !parsed.key) {
      return parsed;
    }

    const key =
      String(parsed.key || "")
        .trim()
        .toLowerCase();

    if (key === runtimeResponseFeedbackKey.toLowerCase()) {
      return {
        ...parsed,
        status: "changed",
        key_status: "same",
        value_status: "changed",
        value_change_ratio: 1,
        strength: 1,
      };
    }

    const previousExact = previousMaps.byIdentity.get(
      getLineIdentity(parsed)
    );

    if (previousExact) {
      return {
        ...previousExact,
        key: parsed.key,
        value: parsed.value,
      };
    }

    const previousByKey = previousMaps.byKey.get(key);

    if (previousByKey) {
      return {
        ...parsed,
        status: previousByKey.status || parsed.status,
        key_status: previousByKey.key_status || parsed.key_status,
        value_status: previousByKey.value_status || parsed.value_status,
        key_change_ratio:
          previousByKey.key_change_ratio
          ?? parsed.key_change_ratio,
        value_change_ratio:
          previousByKey.value_change_ratio
          ?? parsed.value_change_ratio,
        strength:
          previousByKey.strength
          ?? parsed.strength,
      };
    }

    return parsed;
  }

  function rebuildSnapshotLines(
    snapshot,
    runtimeMemory
  ) {
    const runtimeDeps = ensureDeps();
    const memoryModel = runtimeDeps.memoryModel || {};
    const previousMaps =
      buildPreviousLineMaps(snapshot);

    return memoryModel.splitMemoryTextLines(runtimeMemory)
      .map((line) => (
        preserveLineDiff(
          memoryModel.parseRuntimeMemoryLine(line),
          previousMaps
        )
      ));
  }

  function applyToCurrentSnapshot(feedback) {
    const runtimeDeps = ensureDeps();
    const memoryModel = runtimeDeps.memoryModel || {};
    const snapshot =
      getCurrentSnapshotForMutation(
        feedback
      );

    if (!snapshot) {
      return null;
    }

    const currentMemory =
      String(snapshot.raw_memory || "").trim();

    if (!currentMemory) {
      return null;
    }

    const cleanedMemory =
      memoryModel.removeRuntimeMemoryLineByKey(
        currentMemory,
        runtimeResponseFeedbackKey
      );

    const nextMemory =
      feedback && feedback.rating
        ? memoryModel.upsertRuntimeMemoryLine(
          cleanedMemory,
          runtimeResponseFeedbackKey,
          buildValue(feedback)
        )
        : cleanedMemory;

    snapshot.raw_memory = nextMemory;
    snapshot.lines = rebuildSnapshotLines(
      snapshot,
      nextMemory
    );
    snapshot.client_feedback = (
      feedback && feedback.rating
    )
      ? feedback
      : null;
    snapshot.local_feedback_mutation = Boolean(
      feedback && feedback.rating
    );

    if (typeof runtimeDeps.setDisplayMode === "function") {
      runtimeDeps.setDisplayMode("runtime");
    }

    const snapshots = typeof runtimeDeps.getSnapshots === "function"
      ? runtimeDeps.getSnapshots()
      : [];
    let nextIndex = snapshots.indexOf(snapshot);

    if (nextIndex < 0) {
      nextIndex = snapshots.length - 1;
    }

    if (typeof runtimeDeps.setCurrentIndex === "function") {
      runtimeDeps.setCurrentIndex(nextIndex);
    }

    // Feedback is a transient one-turn alert for the next JIN response.
    // Keep it visible in the current UI snapshot, but do not save it as
    // stable runtime memory and do not persist it to localStorage.
    if (typeof runtimeDeps.renderRuntimeMemorySnapshot === "function") {
      runtimeDeps.renderRuntimeMemorySnapshot();
    }

    return snapshot;
  }

  function recordCurrentResponse(detail) {
    if (runtimeResponseFeedbackCommitted) {
      return null;
    }

    // Generation guard: reject ratings for bubbles that belong to a turn
    // older than the one currently awaiting a response. The user already
    // submitted a newer message, so mutating an earlier snapshot would
    // inject stale feedback into the wrong memory slice.
    const incomingGeneration = Number(
      detail && detail.ratingGateGeneration || 0
    );
    if (
      incomingGeneration > 0
      && incomingGeneration < jinAnswerRatingL1Gate.lockedBelowGeneration
    ) {
      return null;
    }

    const rating =
      normalizeRating(
        detail && detail.rating
      );

    if (!rating) {
      return null;
    }

    pendingRuntimeResponseFeedback = {
      rating,
      runtimeSnapshotIndex: resolveFeedbackSnapshotIndex(
        detail
      ),
    };

    return applyToCurrentSnapshot(
      pendingRuntimeResponseFeedback
    );
  }

  function clearPendingRating(detail = null) {
    if (runtimeResponseFeedbackCommitted) {
      return null;
    }

    pendingRuntimeResponseFeedback = null;

    return applyToCurrentSnapshot({
      runtimeSnapshotIndex: resolveFeedbackSnapshotIndex(
        detail
      ),
    });
  }

  function getPendingRating() {
    return pendingRuntimeResponseFeedback
      ? { ...pendingRuntimeResponseFeedback }
      : null;
  }

  function consumePendingLastResponseRating() {
    const value = pendingRuntimeResponseFeedback
      ? { ...pendingRuntimeResponseFeedback }
      : null;

    pendingRuntimeResponseFeedback = null;

    if (value) {
      runtimeResponseFeedbackCommitted = true;
    }

    return value;
  }

  const api = {
    init,
    key: runtimeResponseFeedbackKey,
    setPendingRating: recordCurrentResponse,
    recordCurrentResponse,
    clearPendingRating,
    getPendingRating,
    consumePendingLastResponseRating,
    markL1ReadyFromRuntimeUpdate,
    startL1GateForTurn,
    getL1GateState,
    isReadyForGateGeneration,
  };

  root.feedback = api;

  // Legacy window API. Keep old names until socket.js/status.js/templates stop
  // calling them directly.
  window.startJinAnswerRatingL1GateForTurn = function () {
    return api.startL1GateForTurn();
  };

  window.getJinAnswerRatingL1GateState = function () {
    return api.getL1GateState();
  };

  window.isJinAnswerRatingReadyForGateGeneration = function (generation) {
    return api.isReadyForGateGeneration(generation);
  };

  window.recordJinAnswerRating = function (detail) {
    return api.recordCurrentResponse(detail);
  };

  window.clearJinAnswerRating = function (detail) {
    return api.clearPendingRating(detail);
  };

  window.getJinAnswerRatingForRuntime = function () {
    return api.getPendingRating();
  };

  window.consumePendingLastResponseRating = function () {
    return api.consumePendingLastResponseRating();
  };
}());
