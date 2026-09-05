// --------------------------------------------------
// AUTO HEIGHT
// --------------------------------------------------

userInput.addEventListener(
  "input",
  function () {

    this.style.height =
      "auto";

    this.style.height =
      this.scrollHeight + "px";

  }
);


// --------------------------------------------------
// KEYBOARD
// --------------------------------------------------

userInput.addEventListener(
  "keydown",
  function (e) {

    if (e.key !== "Enter") {
      return;
    }

    // -----------------------------------------
    // CTRL+ENTER / SHIFT+ENTER
    // -----------------------------------------

    if (
      e.ctrlKey
      || e.shiftKey
    ) {

      e.preventDefault();

      const start =
        this.selectionStart;

      const end =
        this.selectionEnd;

      const value =
        this.value;

      this.value =
        value.substring(0, start)
        + "\n"
        + value.substring(end);

      this.selectionStart =
        this.selectionEnd =
          start + 1;

      this.dispatchEvent(
        new Event("input")
      );

      return;

    }

    // -----------------------------------------
    // NORMAL ENTER
    // -----------------------------------------

    e.preventDefault();

    // -----------------------------------------
    // STOP
    // -----------------------------------------

    if (generationRunning) {

      abortGeneration();

      return;

    }

    // -----------------------------------------
    // SEND
    // -----------------------------------------

    chatForm.requestSubmit();

  }
);

// --------------------------------------------------
// STOP AREA CLICK
// --------------------------------------------------

chatForm.addEventListener(
  "click",
  function (e) {

    if (!generationRunning) {
      focusChatInputFromFormPointer(
        e
      );

      return;
    }

    e.preventDefault();

    abortGeneration();

  }
);

function shouldFocusChatInputFromFormPointer(
  e
) {

  if (
    generationRunning
    || e.button !== 0
  ) {
    return false;
  }

  if (
    e.target
    && e.target.closest
    && e.target.closest(
        "button, label, input, textarea, select, a, [role='button']"
    )
  ) {
    return false;
  }

  return true;

}

function focusChatInputFromFormPointer(
  e
) {

  if (
    !shouldFocusChatInputFromFormPointer(
      e
    )
  ) {
    return false;
  }

  e.preventDefault();

  if (window.focusJinUserInput) {
    window.focusJinUserInput({
      preventScroll: true,
    });
  } else {
    userInput.focus({
      preventScroll: true,
    });
  }

  return true;

}

chatForm.addEventListener(
  "mousedown",
  focusChatInputFromFormPointer
);


// HIDDEN BUTTON CLICK
// --------------------------------------------------

if (sendButton) {

  sendButton.addEventListener(
    "click",
    function (e) {

      if (!generationRunning) {
        return;
      }

      e.preventDefault();

      abortGeneration();

    }
  );

}

// --------------------------------------------------
// SEND MESSAGE
// --------------------------------------------------

let pendingUserBatchCandidateRow = null;
let pendingUserBatchRow = null;
let pendingUserBatchId = "";

function rememberPendingUserBatchCandidate(
  messageRow
) {
  pendingUserBatchCandidateRow =
    messageRow || null;
}

function openPendingUserBatch(
  batchId
) {
  const normalizedBatchId =
    String(batchId || "").trim();

  if (
    !normalizedBatchId
    || !pendingUserBatchCandidateRow
  ) {
    return false;
  }

  pendingUserBatchId =
    normalizedBatchId;
  pendingUserBatchRow =
    pendingUserBatchCandidateRow;

  return true;
}

function isPendingUserBatchOpen() {
  return Boolean(
    pendingUserBatchId
    && pendingUserBatchRow
  );
}

function closePendingUserBatch(
  batchId = ""
) {
  const normalizedBatchId =
    String(batchId || "").trim();

  if (
    normalizedBatchId
    && pendingUserBatchId
    && normalizedBatchId !== pendingUserBatchId
  ) {
    return false;
  }

  pendingUserBatchCandidateRow = null;
  pendingUserBatchRow = null;
  pendingUserBatchId = "";

  return true;
}

window.openPendingUserBatch =
  openPendingUserBatch;
window.closePendingUserBatch =
  closePendingUserBatch;
window.clearPendingUserBatch =
  closePendingUserBatch;

function allModelRuntimesOffline() {

  const status =
    (
      window.jinRuntimeConfig
      && window.jinRuntimeConfig.runtimeStatus
    )
    || {};

  return (
    status.brain === false
  );

}

if (memoryLayersToggle) {
  const ANONYMOUS_ROOM_LONG_PRESS_MS = 1500;
  const ANONYMOUS_ROOM_TAP_MAX_MS = 300;
  const ANONYMOUS_ROOM_MOVE_TOLERANCE_PX = 12;
  const ANONYMOUS_ROOM_HOLD_CLASS = "is-anonymous-room-hold";

  let anonymousRoomLongPressTimer = null;
  let anonymousRoomPointerId = null;
  let anonymousRoomPointerStartX = 0;
  let anonymousRoomPointerStartY = 0;
  let anonymousRoomPointerStartedAt = 0;
  let suppressNextMemoryLayersClick = false;
  let suppressNextMemoryLayersClickTimer = null;

  function runtimeAvatar() {
    return (
      window.JinRuntime
      && window.JinRuntime.avatar
    ) || null;
  }

  function toggleRuntimeAvatarMemoryLayers() {
    const avatar = runtimeAvatar();

    if (
      avatar
      && typeof avatar.toggleMemoryLayers === "function"
    ) {
      avatar.toggleMemoryLayers();
    }
  }

  function setAnonymousRoomHoldVisual(active) {
    const avatarRoot = document.getElementById("jin-runtime-avatar");
    const avatarShell = avatarRoot
      ? avatarRoot.closest(".jin-runtime-avatar-shell")
      : null;
    const nextActive = Boolean(active);

    if (avatarRoot) {
      avatarRoot.classList.toggle(
        ANONYMOUS_ROOM_HOLD_CLASS,
        nextActive
      );
    }

    if (avatarShell) {
      avatarShell.classList.toggle(
        ANONYMOUS_ROOM_HOLD_CLASS,
        nextActive
      );
    }
  }

  function clearAnonymousRoomLongPressTimer() {
    if (anonymousRoomLongPressTimer) {
      clearTimeout(anonymousRoomLongPressTimer);
      anonymousRoomLongPressTimer = null;
    }
  }

  function clearSuppressNextMemoryLayersClick() {
    suppressNextMemoryLayersClick = false;

    if (suppressNextMemoryLayersClickTimer) {
      clearTimeout(suppressNextMemoryLayersClickTimer);
      suppressNextMemoryLayersClickTimer = null;
    }
  }

  function armSuppressNextMemoryLayersClick(timeoutMs = 1200) {
    suppressNextMemoryLayersClick = true;

    if (suppressNextMemoryLayersClickTimer) {
      clearTimeout(suppressNextMemoryLayersClickTimer);
    }

    suppressNextMemoryLayersClickTimer = setTimeout(() => {
      suppressNextMemoryLayersClick = false;
      suppressNextMemoryLayersClickTimer = null;
    }, timeoutMs);
  }

  function cancelAnonymousRoomPointerHold({ suppressClick = false } = {}) {
    clearAnonymousRoomLongPressTimer();

    if (suppressClick) {
      armSuppressNextMemoryLayersClick();
    }

    anonymousRoomPointerId = null;
    anonymousRoomPointerStartedAt = 0;
    setAnonymousRoomHoldVisual(false);
  }

  function launchAnonymousRoomFromAvatar() {
    const anonymousMode =
      window.JinRuntime
      && window.JinRuntime.anonymousMode;

    armSuppressNextMemoryLayersClick(6000);
    anonymousRoomPointerId = null;
    anonymousRoomPointerStartedAt = 0;
    setAnonymousRoomHoldVisual(false);

    if (
      anonymousMode
      && typeof anonymousMode.openAnonymousWindow === "function"
    ) {
      anonymousMode.openAnonymousWindow();
    }

    // A completed long press normally produces one click on pointerup. The
    // suppression above keeps that synthetic click from toggling the rings.
  }

  memoryLayersToggle.addEventListener(
    "pointerdown",
    (event) => {
      if (event.button !== undefined && event.button !== 0) {
        return;
      }

      // A fresh pointerdown is a new gesture. If the anonymous tab stole
      // focus before the original long-press click was delivered, do not
      // let that stale one-shot suppression eat this new click.
      clearSuppressNextMemoryLayersClick();
      cancelAnonymousRoomPointerHold();
      anonymousRoomPointerId = event.pointerId;
      anonymousRoomPointerStartX = Number(event.clientX || 0);
      anonymousRoomPointerStartY = Number(event.clientY || 0);
      anonymousRoomPointerStartedAt = (
        typeof performance !== "undefined"
        && typeof performance.now === "function"
      )
        ? performance.now()
        : Date.now();

      if (typeof memoryLayersToggle.setPointerCapture === "function") {
        try {
          memoryLayersToggle.setPointerCapture(event.pointerId);
        } catch (error) {
          // Pointer capture is a robustness aid only; the hold still works
          // when the browser refuses capture for this pointer type.
        }
      }

      setAnonymousRoomHoldVisual(true);

      const heldPointerId = event.pointerId;
      anonymousRoomLongPressTimer = setTimeout(() => {
        anonymousRoomLongPressTimer = null;

        // The window is created only if the same pointer is still held after
        // the full 1.5-second fade. pointerup/cancel/move clear this id first.
        if (anonymousRoomPointerId !== heldPointerId) {
          return;
        }

        launchAnonymousRoomFromAvatar();
      }, ANONYMOUS_ROOM_LONG_PRESS_MS);
    }
  );

  memoryLayersToggle.addEventListener(
    "pointermove",
    (event) => {
      if (
        anonymousRoomPointerId === null
        || event.pointerId !== anonymousRoomPointerId
      ) {
        return;
      }

      const movedX = Number(event.clientX || 0) - anonymousRoomPointerStartX;
      const movedY = Number(event.clientY || 0) - anonymousRoomPointerStartY;

      if (
        Math.hypot(movedX, movedY)
        > ANONYMOUS_ROOM_MOVE_TOLERANCE_PX
      ) {
        cancelAnonymousRoomPointerHold({ suppressClick: true });
      }
    }
  );

  ["pointerup", "pointercancel", "lostpointercapture"].forEach(
    (eventName) => {
      memoryLayersToggle.addEventListener(
        eventName,
        (event) => {
          if (
            anonymousRoomPointerId !== null
            && event.pointerId !== anonymousRoomPointerId
          ) {
            return;
          }

          let suppressClick = false;

          if (
            eventName === "pointerup"
            && anonymousRoomPointerId !== null
            && anonymousRoomPointerStartedAt > 0
          ) {
            const now = (
              typeof performance !== "undefined"
              && typeof performance.now === "function"
            )
              ? performance.now()
              : Date.now();
            const heldMs = Math.max(
              0,
              now - anonymousRoomPointerStartedAt
            );

            // A quick press is still the normal avatar click. Once the user
            // has actually held it, releasing before 1.5 s cancels the
            // anonymous gesture instead of falling through into the click
            // handler and hiding the memory layers.
            suppressClick = heldMs > ANONYMOUS_ROOM_TAP_MAX_MS;
          }

          cancelAnonymousRoomPointerHold({ suppressClick });
        }
      );
    }
  );

  memoryLayersToggle.addEventListener(
    "click",
    (event) => {
      event.preventDefault();
      event.stopPropagation();

      if (suppressNextMemoryLayersClick) {
        clearSuppressNextMemoryLayersClick();
        return;
      }

      toggleRuntimeAvatarMemoryLayers();
    }
  );
}

chatForm.addEventListener(
  "submit",
  async function (e) {

    // -----------------------------------------
    // BLOCK SUBMIT WHEN STREAMING
    // -----------------------------------------

    if (generationRunning) {

      e.preventDefault();

      abortGeneration();

      return;

    }

    e.preventDefault();

    const text =
      userInput.value.trim();

    const hasAttachments =
      window.hasJinAttachments
        ? window.hasJinAttachments()
        : false;

    if (!text && !hasAttachments) {
      return;
    }

    if (allModelRuntimesOffline()) {

      appendLog(
        "[ERROR]",
        "All model runtimes are offline."
      );

      setGenerationState(
        false
      );

      return;

    }

    if (!isWebSocketOpen()) {

      connectWebSocket();

      appendLog(
        "[SYSTEM]",
        "WebSocket reconnecting. Try sending again in a moment."
      );

      return;

    }

    if (window.clearLatestJinMemoryReferenceText) {
      window.clearLatestJinMemoryReferenceText();
    }

    const attachments =
      window.prepareJinAttachments
        ? await window.prepareJinAttachments()
        : [];

    if (isPendingUserBatchOpen()) {
      const appendPayload = {
        text: text,
        append_to_pending_batch: true,
      };

      if (
        window.JinPanels
        && typeof window.JinPanels.getRuntimeAvatarSnapshot === "function"
      ) {
        appendPayload.runtime_avatar =
          window.JinPanels.getRuntimeAvatarSnapshot();
      }

      if (attachments.length) {
        appendPayload.attachments =
          attachments;
      }

      if (
          window.JinRuntime
          && window.JinRuntime.runtime
          && window.JinRuntime.runtime.getActiveMemoryRecords
      ) {
        appendPayload.active_memory_records =
          window.JinRuntime.runtime.getActiveMemoryRecords();
      }

      const sent =
        sendSocketMessage(appendPayload);

      if (!sent) {
        return;
      }

      if (window.appendToUserChatMessage) {
        window.appendToUserChatMessage(
          pendingUserBatchRow,
          text,
          attachments
        );
      }

      if (window.markSessionActivityDirty) {
        window.markSessionActivityDirty();
      }

      userInput.value = "";
      userInput.style.height =
        "auto";

      return;
    }

    if (window.startJinAnswerRatingL1GateForTurn) {
      window.startJinAnswerRatingL1GateForTurn();
    }

    if (window.prepareLiveUserTurnViewport) {
      window.prepareLiveUserTurnViewport();
    }

    const userMessageRow =
      appendChatMessage(
        "user",
        text,
        null,
        attachments
      );

    if (window.activateLiveUserTurnViewport) {
      window.activateLiveUserTurnViewport(
        userMessageRow
      );
    }

    // The server owns the transition into a real Brain turn. While a FRAME
    // update is still running this first message becomes an open pending batch,
    // so showing STOP here causes a brief false flash before that routing
    // decision arrives. pending_user_batch_commit / agent_runtime_start will
    // switch the input into STOP state at the actual Brain boundary.
    const pendingLastResponseRating =
      window.consumePendingLastResponseRating
        ? window.consumePendingLastResponseRating()
        : null;

    const payload = {
      text: text,
    };

    if (
      window.JinPanels
      && typeof window.JinPanels.getRuntimeAvatarSnapshot === "function"
    ) {
      payload.runtime_avatar =
        window.JinPanels.getRuntimeAvatarSnapshot();
    }

    if (attachments.length) {
      payload.attachments =
        attachments;
    }

    const inputLoopContext =
      window.updateJinInputLoopCounter
        ? window.updateJinInputLoopCounter(
            text
          )
        : null;

    if (inputLoopContext) {
      payload.runtime_pattern_counter =
        inputLoopContext.repeatCount;
      payload.runtime_repeated_input_count =
        inputLoopContext.repeated || 0;
    }

    const userIdleContext =
      window.getJinUserIdleContext
        ? window.getJinUserIdleContext()
        : null;

    if (userIdleContext) {
      payload.user_idle =
        userIdleContext.user_idle;
      payload.user_idle_seconds =
        userIdleContext.user_idle_seconds;
      payload.user_idle_paused =
        userIdleContext.user_idle_paused;

      if (window.freezeLatestRuntimeMemoryUserIdle) {
        window.freezeLatestRuntimeMemoryUserIdle(
          userIdleContext.user_idle
        );
      }
    }

    window.jinActiveTurnUserIdleSeconds =
      userIdleContext
        ? Number(userIdleContext.user_idle_seconds || 0)
        : 0;

    if (pendingLastResponseRating) {
      payload.pending_last_response_rating = pendingLastResponseRating;
    }

    if (
        window.JinRuntime
        && window.JinRuntime.runtime
        && window.JinRuntime.runtime.getActiveMemoryRecords
    ) {
      payload.active_memory_records =
        window.JinRuntime.runtime.getActiveMemoryRecords();
    }

    const sent =
      sendSocketMessage(payload);

    if (sent) {
      rememberPendingUserBatchCandidate(
        userMessageRow
      );
    }

    if (
        sent
        && window.markSessionActivityDirty
    ) {
      // Only a successfully emitted real USER move may replace a cleared
      // checkpoint tombstone. Retry/bootstrap/reconnect paths do not call this.
      window.markSessionActivityDirty();
    }

    if (window.jinFreezeUserIdleTimerAtSeconds) {
      window.jinFreezeUserIdleTimerAtSeconds(
        window.jinActiveTurnUserIdleSeconds
      );
    }

    userInput.value = "";

    userInput.style.height =
      "auto";

  }
);

