let activeFrameMemorySequence = null;

function createFrameMemorySequenceCard() {
  const logDiv = createLTLoggerCard("[MEMORY:FRAME]");
  logDiv.classList.add("jin-lt-sequence-card");
  const track = document.createElement("div");
  track.className = "jin-lt-sequence-track jin-frame-sequence-track";

  const extract = document.createElement("button");
  const apply = document.createElement("button");
  for (const step of [extract, apply]) {
    step.type = "button";
    step.className = "jin-lt-sequence-step";
    setLTSequenceStatus(step, "idle");
    setLTSequenceInspectable(step, false);
  }
  extract.textContent = "extract";
  apply.textContent = "apply";

  const arrow = document.createElement("span");
  arrow.className = "jin-lt-sequence-arrow";
  arrow.setAttribute("aria-hidden", "true");
  setLTSequenceStatus(arrow, "idle");

  const showButton = document.createElement("button");
  showButton.type = "button";
  showButton.className = "jin-lt-sequence-show";
  showButton.textContent = "show";
  showButton.disabled = true;

  const state = {
    logDiv, extract, arrow, apply, showButton,
    requestDetails: "", responseDetails: "", failureDetails: "", complete: false,
  };
  extract.addEventListener("click", () => {
    if (state.requestDetails) {
      showTrace(state.requestDetails, "FRAME SUMMARIZER REQUEST");
    }
  });
  const showResponse = () => {
    if (state.responseDetails) {
      showTrace(state.responseDetails, "FRAME SUMMARIZER RESPONSE");
    } else if (state.failureDetails) {
      showTrace(state.failureDetails, "FRAME SUMMARIZER FAILED");
    }
  };
  apply.addEventListener("click", showResponse);
  showButton.addEventListener("click", showResponse);
  track.append(extract, arrow, apply);
  logDiv.append(track, showButton);
  activeFrameMemorySequence = state;
  return state;
}

function handleFrameMemorySequenceLog(tag, message, details, meta) {
  // Keep the old wire-level name readable while the remaining runtime migrates.
  const level = String(meta?.memory_level || "").toUpperCase();
  if (!(["FRAME", "L1"].includes(level) || /\[MEMORY:(?:FRAME|L1)\]/i.test(tag))) {
    return undefined;
  }
  const event = String(meta?.memory_event || "");
  // Compatibility with already-running backends: never retain stream chunks.
  if (event.startsWith("summarizer_stream_")) {
    return null;
  }
  const request = event === "summarizer_request";
  const response = event === "summarizer_response";
  const failed = ["summarizer_failed", "summarizer_skipped", "summarizer_cancelled"].includes(event)
    || /runtime memory update (?:failed|skipped)$/i.test(message);
  if (!request && !response && !failed) {
    return undefined;
  }

  const state = request || !activeFrameMemorySequence || activeFrameMemorySequence.complete
    ? createFrameMemorySequenceCard()
    : activeFrameMemorySequence;
  if (request) {
    state.requestDetails = String(details || "");
    setLTSequenceStatus(state.extract, "pending");
    setLTSequenceInspectable(state.extract, Boolean(state.requestDetails));
  } else if (response) {
    const payload = parseTraceJson(details);
    if (!payload || payload.kind !== "summarizer_response") {
      state.failureDetails = String(details || "FRAME response details are unavailable.");
      setLTSequenceStatus(state.extract, "failed");
      setLTSequenceStatus(state.apply, "failed");
      setLTSequenceInspectable(state.apply, true);
    } else {
      state.responseDetails = String(details);
      for (const element of [state.extract, state.arrow, state.apply]) {
        setLTSequenceStatus(element, "success");
      }
      setLTSequenceInspectable(state.apply, true);
      state.showButton.disabled = false;
    }
    state.complete = true;
  } else {
    state.failureDetails = String(details || message || "FRAME update failed.");
    setLTSequenceStatus(state.extract, "failed");
    setLTSequenceStatus(state.apply, "failed");
    setLTSequenceInspectable(state.apply, true);
    state.complete = true;
  }
  moveLTSequenceToLatestLog(state);
  return state.logDiv;
}
