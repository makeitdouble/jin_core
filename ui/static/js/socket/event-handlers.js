function resolveMessageRole(
  data
) {

  if (data.role) {
    return data.role.toLowerCase();
  }

  return "brain";

}

function appendSessionBootstrapBoundary(
  chatHistory
) {

  if (!chatHistory) {
    return null;
  }

  const now = new Date();
  const months = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
  ];
  const weekdays = [
    "Sunday",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
  ];
  const labelText =
    `${now.getDate()} `
    + `${months[now.getMonth()]}, `
    + weekdays[now.getDay()];

  const divider =
    document.createElement("div");
  divider.className =
    "jin-session-restore-divider";
  divider.setAttribute(
    "role",
    "separator"
  );
  divider.setAttribute(
    "aria-label",
    `Current session: ${labelText}`
  );

  const label =
    document.createElement("span");
  label.className =
    "jin-session-restore-divider-label";
  label.textContent =
    labelText;

  divider.appendChild(
    label
  );
  chatHistory.appendChild(
    divider
  );

  return divider;

}

function handleSessionBootstrapChatTail(
  data
) {

  if (
      window.jinArchivedSessionRestorePayload
      || !data
      || !Array.isArray(data.turns)
  ) {
    return;
  }

  const chatHistory =
    document.getElementById(
      "chat-history"
    );

  if (!chatHistory) {
    return;
  }

  const existingMessages =
    chatHistory.querySelectorAll(
      ".jin-message-shell"
    );

  if (existingMessages.length) {
    return;
  }

  const turns = data.turns
    .filter(turn => (
      turn
      && typeof turn === "object"
      && String(turn.user || "").trim()
    ))
    .slice(-3);

  turns.forEach((turn, index) => {
    const userText =
      String(turn.user || "").trim();
    const jinText =
      String(turn.jin || "").trim();

    appendChatMessage(
      "user",
      userText
    );

    // Marker/action-only turns have no visible JIN answer. Keep the USER
    // bubble above the divider, but never manufacture an empty BR bubble.
    if (!jinText) {
      return;
    }

    const messageId =
      `bootstrap-tail-${String(
        data.source_session_id
        || "session"
      ).replace(/[^a-zA-Z0-9_.:-]/g, "_")}-${index}`;

    startStreamMessage(
      messageId,
      "brain",
      null
    );

    const reasoning =
      String(turn.reasoning || "").trim();

    if (reasoning) {
      appendThinkingChunk(
        messageId,
        reasoning
      );
    }

    appendStreamChunk(
      messageId,
      jinText
    );
    finishStreamMessage(
      messageId,
      { retryable: false }
    );
  });

  const divider =
    appendSessionBootstrapBoundary(
      chatHistory
    );

  if (
      divider
      && typeof window.activateLiveUserTurnViewport
        === "function"
  ) {
    window.activateLiveUserTurnViewport(
      divider
    );
  }

}


function handleSessionActionsUpdate(
  data
) {
  if (
      data
      && data.bootstrap_restore === true
      && data.current_jin_color
      && window.JinRuntime.avatar
      && typeof window.JinRuntime.avatar.setCenterColor === "function"
  ) {
    window.JinRuntime.avatar.setCenterColor(
      data.current_jin_color,
      {
        initialBootstrap: true,
        persist: true,
      }
    );
  }

  if (window.updateSessionActionsLog) {
    window.updateSessionActionsLog(
      data
    );
  }

}

function handleFactsMemoryStoreUpdate(
  data
) {

  if (
      window.JINRuntimeLTMemory
      && window.JINRuntimeLTMemory.applyFactsMemoryRecordsUpdate
  ) {
    window.JINRuntimeLTMemory.applyFactsMemoryRecordsUpdate(
      data
    );
  }

}

function handleLTMemoryUpdate(
  data
) {

  if (
      window.JINRuntimeLTMemory
      && window.JINRuntimeLTMemory.applyServerUpdate
  ) {
    window.JINRuntimeLTMemory.applyServerUpdate(
      data
    );
  }

}

function handleSocketLTMemoryRestoreResult(
  data
) {

  if (typeof window.handleLTLoggerMemoryRestoreResult === "function") {
    window.handleLTLoggerMemoryRestoreResult(
      data
    );
  }

}

function handleSocketError(
  data
) {

  if (window.clearInterruptedRuntimeGlow) {
    window.clearInterruptedRuntimeGlow();
  }

  setGenerationState(
    false
  );

  if (window.clearJinCompletedAnswerRetryCandidate) {
    window.clearJinCompletedAnswerRetryCandidate();
  }

  window.jinCurrentResponseRetryable = false;

  if (window.releaseActiveStreamAvatar) {
    window.releaseActiveStreamAvatar();
  }

  appendLog(
    "[ERROR]",
    data.message,
    data.details
  );

  stopFactCheckGlow();

}

function handleSocketChatMessage(
  data
) {

  const role =
    resolveMessageRole(data);

  let filteredText =
    filterDelayedMemoryContentFromChunk(
      data.message_id || "message",
      data.text
    );

  if (window.stripInternalActionMarkers) {
    filteredText = window.stripInternalActionMarkers(
      filteredText
    );
  }

  clearDelayedMemoryContentFilter(
    data.message_id || "message"
  );

  if (!String(filteredText || "").trim()) {
    return;
  }

  appendChatMessage(
    role,
    filteredText,
    data.context || null
  );

}

function handleThinkingChunk(
  data
) {

  appendThinkingChunk(
    data.message_id,
    data.chunk
  );

}

function handleAgentRuntimeStart(data) {
  window.jinCurrentResponseRetryable = Boolean(
    data && data.retryable_response
  );

  if (window.confirmJinLastResponseRetryStarted) {
    window.confirmJinLastResponseRetryStarted();
  }

  setGenerationState(
    true
  );
}

function withCurrentRoomState(sessionSnapshot) {
  const roomState =
    window.JinPanels
    && typeof window.JinPanels.getRoomState === "function"
      ? window.JinPanels.getRoomState(
          sessionSnapshot.room_state || null
        )
      : null;
  const avatarState =
    roomState
    && roomState.avatar
    && typeof roomState.avatar === "object"
      ? roomState.avatar
      : null;

  if (!avatarState) {
    return sessionSnapshot;
  }

  return {
    ...sessionSnapshot,
    room_state: roomState,
    current_jin_color: avatarState.color,
    current_jin_collapsed: Boolean(avatarState.collapsed),
    current_jin_speed: Number(
      avatarState.speed_px_per_second || 900
    ),
    current_window_size: {
      width: avatarState.window_width,
      height: avatarState.window_height,
    },
    ...(
      avatarState.geometry_known
        ? {
            current_jin_size: {
              width: avatarState.width,
              height: avatarState.height,
            },
            current_jin_position: {
              x: avatarState.x,
              y: avatarState.y,
            },
          }
        : {}
    ),
  };
}

function handleAgentRuntimeEnd(data) {

  const runtimeSession =
    window.JinRuntime
    && window.JinRuntime.session;

  if (
      data
      && data.session_snapshot
      && runtimeSession
      && typeof runtimeSession.persistLiveSessionCheckpoint === "function"
  ) {
    runtimeSession.persistLiveSessionCheckpoint({
      session_snapshot: withCurrentRoomState(
        data.session_snapshot
      ),
      completed_turn_commit: Boolean(
        data.completed_turn_commit === true
      ),
    });
  }

  if (data && data.retryable_response === true) {
    if (window.commitJinCompletedAnswerRetryCandidate) {
      window.commitJinCompletedAnswerRetryCandidate();
    }
  } else if (window.clearJinCompletedAnswerRetryCandidate) {
    window.clearJinCompletedAnswerRetryCandidate();
  }

  if (window.releaseActiveStreamAvatar) {
    window.releaseActiveStreamAvatar();
  }

  if (window.flushRuntimeTelemetryRender) {
    window.flushRuntimeTelemetryRender({
      final: true
    });
  }

  setGenerationState(
    false
  );

  window.jinCurrentResponseRetryable = false;
  window.jinActiveTurnUserIdleSeconds = 0;

  if (window.jinResetUserIdleTimer) {
    window.jinResetUserIdleTimer();
  }

}

function handleMessageStart(
  data
) {

  setGenerationState(
    true
  );

  startStreamMessage(
    data.message_id,
    resolveMessageRole(data),
    data.context || null
  );

}

function handleMessageChunk(
  data
) {

  if (window.markStreamAnswerPhase) {
    window.markStreamAnswerPhase(
      data.message_id
    );
  }

  const filteredChunk =
    filterDelayedMemoryContentFromChunk(
      data.message_id,
      data.chunk
    );

  if (!filteredChunk) {
    return;
  }

  appendStreamChunk(
    data.message_id,
    filteredChunk
  );

}

function handleMessageEnd(
  data
) {

  const runtimeSession =
    window.JinRuntime
    && window.JinRuntime.session;

  if (
      data
      && data.session_snapshot
      && runtimeSession
      && typeof runtimeSession.persistLiveSessionCheckpoint === "function"
  ) {
    runtimeSession.persistLiveSessionCheckpoint({
      session_snapshot: withCurrentRoomState(
        data.session_snapshot
      ),
      completed_turn_commit: Boolean(
        data.completed_turn_commit === true
      ),
    });
  }

  clearDelayedMemoryContentFilter(
    data.message_id
  );

  finishStreamMessage(
    data.message_id,
    {
      retryCandidate: Boolean(
        window.jinCurrentResponseRetryable
      )
    }
  );

  if (window.flushRuntimeTelemetryRender) {
    window.flushRuntimeTelemetryRender({
      final: true
    });
  }

}

function handleMessageError(
  data
) {

  clearDelayedMemoryContentFilter(
    data.message_id
  );

  setGenerationState(
    false
  );

  if (!data.suppress_log) {
    appendLog(
      data.log_tag || "[VALIDATOR]",
      data.text
    );
  }

  finishStreamMessage(
    data.message_id,
    { retryable: false }
  );

  if (window.clearJinCompletedAnswerRetryCandidate) {
    window.clearJinCompletedAnswerRetryCandidate();
  }

  window.jinCurrentResponseRetryable = false;

  if (window.flushRuntimeTelemetryRender) {
    window.flushRuntimeTelemetryRender({
      final: true
    });
  }

}

function handleRetryLastResponseRejected(
  data
) {
  setGenerationState(
    false
  );

  if (window.restoreJinDeletedRetryBubble) {
    window.restoreJinDeletedRetryBubble();
  }

  appendLog(
    "[RETRY]",
    `Retry rejected: ${String(data && data.reason || "unavailable")}`
  );
}


registerSocketMessageHandler(
  "retry_last_response_rejected",
  handleRetryLastResponseRejected
);

registerSocketMessageHandler(
  "session_bootstrap_chat_tail",
  handleSessionBootstrapChatTail
);

registerSocketMessageHandler(
  "session_actions_update",
  handleSessionActionsUpdate
);

registerSocketMessageHandler(
  "facts_memory_store_update",
  handleFactsMemoryStoreUpdate
);

registerSocketMessageHandler(
  "lt_memory_update",
  handleLTMemoryUpdate
);

registerSocketMessageHandler(
  "lt_memory_restore_result",
  handleSocketLTMemoryRestoreResult
);

[
  "error",
  "fatal_error",
  "websocket_error",
].forEach(function (type) {
  registerSocketMessageHandler(
    type,
    handleSocketError
  );
});

registerSocketMessageHandler(
  "message",
  handleSocketChatMessage
);

registerSocketMessageHandler(
  "thinking_chunk",
  handleThinkingChunk
);

registerSocketMessageHandler(
  "agent_runtime_start",
  handleAgentRuntimeStart
);

registerSocketMessageHandler(
  "agent_runtime_end",
  handleAgentRuntimeEnd
);

registerSocketMessageHandler(
  "message_start",
  handleMessageStart
);

registerSocketMessageHandler(
  "message_chunk",
  handleMessageChunk
);

registerSocketMessageHandler(
  "message_end",
  handleMessageEnd
);

registerSocketMessageHandler(
  "message_error",
  handleMessageError
);
