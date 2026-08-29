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
  function toggleRuntimeAvatarMemoryLayers() {
    const avatar =
      window.JinRuntime
      && window.JinRuntime.avatar;

    if (
      avatar
      && typeof avatar.toggleMemoryLayers === "function"
    ) {
      avatar.toggleMemoryLayers();
    }
  }

  memoryLayersToggle.addEventListener(
    "click",
    (event) => {
      event.preventDefault();
      event.stopPropagation();

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

