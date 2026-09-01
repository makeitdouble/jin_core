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
  const ANONYMOUS_ROOM_MOVE_TOLERANCE_PX = 12;
  const ANONYMOUS_ROOM_HOLD_CLASS = "is-anonymous-room-hold";

  let anonymousRoomLongPressTimer = null;
  let anonymousRoomPointerId = null;
  let anonymousRoomPointerStartX = 0;
  let anonymousRoomPointerStartY = 0;
  let suppressNextMemoryLayersClick = false;

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

  function cancelAnonymousRoomPointerHold() {
    clearAnonymousRoomLongPressTimer();
    anonymousRoomPointerId = null;
    setAnonymousRoomHoldVisual(false);
  }

  function launchAnonymousRoomFromAvatar() {
    const anonymousMode =
      window.JinRuntime
      && window.JinRuntime.anonymousMode;

    suppressNextMemoryLayersClick = true;
    anonymousRoomPointerId = null;
    setAnonymousRoomHoldVisual(false);

    if (
      anonymousMode
      && typeof anonymousMode.openAnonymousWindow === "function"
    ) {
      anonymousMode.openAnonymousWindow();
    }

    // A completed long press normally produces one click on pointerup. Do not
    // let that click toggle the rings after the anonymous-room gesture.
    setTimeout(() => {
      suppressNextMemoryLayersClick = false;
    }, 6000);
  }

  memoryLayersToggle.addEventListener(
    "pointerdown",
    (event) => {
      if (event.button !== undefined && event.button !== 0) {
        return;
      }

      cancelAnonymousRoomPointerHold();
      anonymousRoomPointerId = event.pointerId;
      anonymousRoomPointerStartX = Number(event.clientX || 0);
      anonymousRoomPointerStartY = Number(event.clientY || 0);

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
        cancelAnonymousRoomPointerHold();
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

          cancelAnonymousRoomPointerHold();
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
        suppressNextMemoryLayersClick = false;
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

    setGenerationState(
      true
    );

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

