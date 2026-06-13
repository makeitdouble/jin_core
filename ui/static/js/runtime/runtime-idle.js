(function () {

  window.JinRuntime = window.JinRuntime || {};

  const USER_IDLE_REFRESH_MS = 1000;
  const USER_IDLE_TYPING_RESUME_DELAY_MS = 30000;

  let userIdleStartedAt = Date.now();
  let userIdleTimer = null;
  let userIdlePausedAt = null;
  let userIdleResumeTimer = null;
  let userIdleInputFreezeInstalled = false;

  let onIdleTextChanged = null;

  function formatUserIdleDuration(ms) {
    const totalSeconds = Math.max(
        0,
        Math.floor(Number(ms || 0) / 1000)
    );

    if (totalSeconds < 60) {
      return `${totalSeconds}s`;
    }

    const totalMinutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;

    if (totalMinutes < 60) {
      return seconds
        ? `${totalMinutes}m ${seconds}s`
        : `${totalMinutes}m`;
    }

    const totalHours = Math.floor(totalMinutes / 60);
    const minutes = totalMinutes % 60;

    if (totalHours < 24) {
      return minutes
        ? `${totalHours}h ${minutes}m`
        : `${totalHours}h`;
    }

    const days = Math.floor(totalHours / 24);
    const hours = totalHours % 24;

    return hours
      ? `${days}d ${hours}h`
      : `${days}d`;
  }


  function getElapsedMs() {
    const now =
        userIdlePausedAt !== null
          ? userIdlePausedAt
          : Date.now();

    return now - userIdleStartedAt;
  }


  function getText() {
    return formatUserIdleDuration(
        getElapsedMs()
    );
  }


  function emitIdleTextChanged() {
    if (!onIdleTextChanged) {
      return;
    }

    onIdleTextChanged(
      getText()
    );
  }


  function clearResumeTimer() {
    if (!userIdleResumeTimer) {
      return;
    }

    clearTimeout(
        userIdleResumeTimer
    );

    userIdleResumeTimer = null;
  }


  function stopTimer() {
    if (!userIdleTimer) {
      return;
    }

    clearInterval(
        userIdleTimer
    );

    userIdleTimer = null;
  }


  function ensureTimer() {
    if (userIdlePausedAt !== null) {
      return;
    }

    if (userIdleTimer) {
      return;
    }

    userIdleTimer = setInterval(
        emitIdleTextChanged,
        USER_IDLE_REFRESH_MS
    );
  }


  function isChatInputFocused() {
    const input =
        document.getElementById(
          "user-input"
        );

    return Boolean(
        input
        && document.activeElement === input
    );
  }


  function resume() {
    if (userIdlePausedAt === null) {
      ensureTimer();
      return;
    }

    const frozenElapsed =
        Math.max(
          0,
          userIdlePausedAt - userIdleStartedAt
        );

    userIdleStartedAt =
        Date.now() - frozenElapsed;

    userIdlePausedAt = null;
    clearResumeTimer();
    emitIdleTextChanged();
    ensureTimer();
  }


  function scheduleResumeIfChatLostFocus() {
    clearResumeTimer();

    if (userIdlePausedAt === null) {
      return;
    }

    userIdleResumeTimer = setTimeout(
        function () {
          userIdleResumeTimer = null;

          if (
              isChatInputFocused()
              && document.hasFocus()
              && !document.hidden
          ) {
            return;
          }

          resume();
        },
        USER_IDLE_TYPING_RESUME_DELAY_MS
    );
  }


  function markTypingStarted() {
    if (userIdlePausedAt === null) {
      userIdlePausedAt = Date.now();
    }

    stopTimer();
    emitIdleTextChanged();
    scheduleResumeIfChatLostFocus();
  }


  function markTypingStopped() {
    scheduleResumeIfChatLostFocus();
  }


  function resetForUserMessage() {
    userIdleStartedAt = Date.now();
    userIdlePausedAt = null;
    clearResumeTimer();
    emitIdleTextChanged();
    ensureTimer();
  }


  function freezeAtMs(
    elapsedMs
  ) {
    const now = Date.now();
    const frozenElapsedMs = Math.max(
        0,
        Number(elapsedMs || 0)
    );

    userIdleStartedAt = now - frozenElapsedMs;
    userIdlePausedAt = now;
    clearResumeTimer();
    stopTimer();
    emitIdleTextChanged();
  }


  function freezeAtSeconds(
    elapsedSeconds
  ) {
    freezeAtMs(
        Math.max(
          0,
          Number(elapsedSeconds || 0)
        ) * 1000
    );
  }


  function freezeAtZero() {
    freezeAtMs(
        0
    );
  }


  function installInputFreeze() {
    if (userIdleInputFreezeInstalled) {
      return;
    }

    const input =
        document.getElementById(
          "user-input"
        );

    if (!input) {
      return;
    }

    userIdleInputFreezeInstalled = true;

    input.addEventListener(
        "input",
        markTypingStarted
    );

    input.addEventListener(
        "focus",
        function () {
          if (userIdlePausedAt !== null) {
            clearResumeTimer();
          }
        }
    );

    input.addEventListener(
        "blur",
        markTypingStopped
    );

    window.addEventListener(
        "blur",
        markTypingStopped
    );

    document.addEventListener(
        "visibilitychange",
        function () {
          if (document.hidden) {
            markTypingStopped();
          }
        }
    );
  }


  function start() {
    installInputFreeze();
    emitIdleTextChanged();
    ensureTimer();
  }


  function stop() {
    clearResumeTimer();
    stopTimer();
  }


  function getContext() {
    const elapsedMs = Math.max(
        0,
        getElapsedMs()
    );

    return {
      user_idle: formatUserIdleDuration(
          elapsedMs
      ),
      user_idle_seconds: Math.floor(
          elapsedMs / 1000
      ),
      user_idle_paused: userIdlePausedAt !== null,
    };
  }


  function onSnapshotChanged() {
    emitIdleTextChanged();
  }


  function configure(
    options = {}
  ) {
    onIdleTextChanged =
      typeof options.onIdleTextChanged === "function"
        ? options.onIdleTextChanged
        : null;

    emitIdleTextChanged();
  }


  const idle = {
    configure,
    start,
    stop,
    resetForUserMessage,
    markTypingStarted,
    markTypingStopped,
    getContext,
    onSnapshotChanged,
    formatUserIdleDuration,
    getText,
    freezeAtMs,
    freezeAtSeconds,
    freezeAtZero,
  };

  window.JinRuntime.idle = idle;

  window.jinResetUserIdleTimer =
      resetForUserMessage;

  window.jinFreezeUserIdleTimerAtZero =
      freezeAtZero;

  window.jinFreezeUserIdleTimerAtSeconds =
      freezeAtSeconds;

  window.getJinUserIdleContext =
      getContext;

}());
