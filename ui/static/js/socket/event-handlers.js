function resolveMessageRole(
  data
) {

  if (data.role) {
    return data.role.toLowerCase();
  }

  return "brain";

}

function handleSessionActionsUpdate(
  data
) {

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
      window.JINRuntimeL4Memory
      && window.JINRuntimeL4Memory.applyFactsMemoryRecordsUpdate
  ) {
    window.JINRuntimeL4Memory.applyFactsMemoryRecordsUpdate(
      data
    );
  }

}

function handleL4MemoryUpdate(
  data
) {

  if (
      window.JINRuntimeL4Memory
      && window.JINRuntimeL4Memory.applyServerUpdate
  ) {
    window.JINRuntimeL4Memory.applyServerUpdate(
      data
    );
  }

}

function handleSocketL4MemoryRestoreResult(
  data
) {

  if (typeof window.handleL4LoggerMemoryRestoreResult === "function") {
    window.handleL4LoggerMemoryRestoreResult(
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

function handleAgentRuntimeStart() {
  setGenerationState(
    true
  );
}

function handleAgentRuntimeEnd() {

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

  clearDelayedMemoryContentFilter(
    data.message_id
  );

  finishStreamMessage(
    data.message_id
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
    data.message_id
  );

  if (window.flushRuntimeTelemetryRender) {
    window.flushRuntimeTelemetryRender({
      final: true
    });
  }

}

registerSocketMessageHandler(
  "session_actions_update",
  handleSessionActionsUpdate
);

registerSocketMessageHandler(
  "facts_memory_store_update",
  handleFactsMemoryStoreUpdate
);

registerSocketMessageHandler(
  "l4_memory_update",
  handleL4MemoryUpdate
);

registerSocketMessageHandler(
  "l4_memory_restore_result",
  handleSocketL4MemoryRestoreResult
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
