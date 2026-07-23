const l1SummarizerStreams =
  new Map();

function getL1SummarizerStreamState(
  streamId,
) {
  if (!l1SummarizerStreams.has(streamId)) {
    l1SummarizerStreams.set(
      streamId,
      {
        id: streamId,
        title: "L1 summarizer stream",
        status: "waiting",
        reasoning: "",
        answer: "",
        logDiv: null,
        button: null,
      }
    );
  }

  return l1SummarizerStreams.get(
    streamId
  );
}

function appendL1SummarizerStreamSection(
  parent,
  title,
) {
  const section =
    document.createElement("section");

  section.className =
    "mb-4 rounded border border-zinc-800 bg-black/20";

  const heading =
    document.createElement("div");

  heading.className =
    "border-b border-zinc-800 px-3 py-2 text-[10px] uppercase tracking-widest text-zinc-400";

  heading.textContent =
    title;

  const body =
    document.createElement("pre");

  body.className =
    "max-h-[34vh] overflow-auto whitespace-pre-wrap p-3 text-[12px] leading-relaxed text-zinc-200";

  body.style.overflowWrap =
    "anywhere";

  section.appendChild(
    heading
  );

  section.appendChild(
    body
  );

  parent.appendChild(
    section
  );

  return body;
}

function updateL1SummarizerStreamText(
  element,
  text,
  placeholder,
) {
  if (!element) {
    return;
  }

  const stickToBottom =
    element.scrollHeight
    - element.scrollTop
    - element.clientHeight
    < 32;

  element.textContent =
    text || placeholder;

  if (stickToBottom) {
    element.scrollTop =
      element.scrollHeight;
  }
}

function refreshL1SummarizerStreamModal(
  streamId,
) {
  if (
      traceModalL1StreamId !== streamId
      || !l1SummarizerStreams.has(streamId)
  ) {
    return;
  }

  const state =
    l1SummarizerStreams.get(streamId);

  updateL1SummarizerStreamText(
    traceModalL1StreamStatus,
    state.status,
    "waiting"
  );

  updateL1SummarizerStreamText(
    traceModalL1StreamReasoning,
    state.reasoning,
    "<waiting for reasoning>"
  );

  updateL1SummarizerStreamText(
    traceModalL1StreamAnswer,
    state.answer,
    "<waiting for answer>"
  );
}

function scheduleL1SummarizerStreamModalRefresh(
  streamId,
) {
  if (traceModalL1StreamId !== streamId) {
    return;
  }

  if (traceModalL1StreamFrame !== null) {
    return;
  }

  traceModalL1StreamFrame =
    requestAnimationFrame(
      function () {
        traceModalL1StreamFrame =
          null;

        refreshL1SummarizerStreamModal(
          streamId
        );
      }
    );
}

function showL1SummarizerStream(
  streamId,
) {
  ensureTraceModal();

  const state =
    getL1SummarizerStreamState(
      streamId
    );

  if (traceModalL1StreamFrame !== null) {
    cancelAnimationFrame(
      traceModalL1StreamFrame
    );

    traceModalL1StreamFrame =
      null;
  }

  traceModalL1StreamId =
    streamId;

  traceModalTitle.textContent =
    state.title;

  traceModalReason.textContent =
    "";

  traceModalReason.classList.add(
    "hidden"
  );

  traceModalContent.replaceChildren();

  traceModalL1StreamStatus =
    appendL1SummarizerStreamSection(
      traceModalContent,
      "Status"
    );

  traceModalL1StreamReasoning =
    appendL1SummarizerStreamSection(
      traceModalContent,
      "Reasoning content"
    );

  traceModalL1StreamAnswer =
    appendL1SummarizerStreamSection(
      traceModalContent,
      "Assistant content"
    );

  refreshL1SummarizerStreamModal(
    streamId
  );

  traceModal.classList.remove(
    "hidden"
  );

  traceModal.classList.add(
    "flex"
  );
}

function ensureL1SummarizerStreamButton(
  state,
) {
  if (
      state.button
      || !state.logDiv
  ) {
    return;
  }

  const payloadButton =
    Array.from(
      state.logDiv.querySelectorAll("button")
    ).find((button) => (
      button.textContent.trim().toLowerCase() === "payload"
    ));

  let actions =
    payloadButton
      ? payloadButton.parentElement
      : null;

  if (!actions) {
    actions =
      document.createElement("div");

    actions.className =
      "mt-2 flex flex-wrap items-center gap-2";

    state.logDiv.appendChild(
      actions
    );
  }

  const streamButton =
    document.createElement("button");

  streamButton.type =
    "button";

  streamButton.className =
    "mt-2 inline-flex items-center rounded border border-blue-500/20 px-2 py-1 text-[10px] uppercase tracking-wider text-blue-300 hover:bg-blue-500/10 transition";

  streamButton.textContent =
    "stream";

  streamButton.addEventListener(
    "click",
    function () {
      showL1SummarizerStream(
        state.id
      );
    }
  );

  actions.appendChild(
    streamButton
  );

  state.button =
    streamButton;
}

function registerL1SummarizerRequest(
  logDiv,
  message,
  meta,
) {
  const streamId =
    String(
      meta?.summarizer_stream_id
      || ""
    );

  if (
      !streamId
      || String(meta?.memory_level || "").toUpperCase() !== "L1"
      || String(meta?.memory_event || "") !== "summarizer_request"
  ) {
    return;
  }

  const state =
    getL1SummarizerStreamState(
      streamId
    );

  state.logDiv =
    logDiv;

  state.title =
    String(message || "L1 summarizer stream")
    .replace(/request$/i, "stream");

  if (state.status !== "waiting") {
    ensureL1SummarizerStreamButton(
      state
    );
  }
}

function handleL1SummarizerStreamEvent(
  meta,
) {
  const event =
    String(
      meta?.memory_event
      || ""
    );

  const streamId =
    String(
      meta?.summarizer_stream_id
      || ""
    );

  if (
      !streamId
      || String(meta?.memory_level || "").toUpperCase() !== "L1"
      || !event.startsWith("summarizer_stream_")
  ) {
    return false;
  }

  const state =
    getL1SummarizerStreamState(
      streamId
    );

  if (event === "summarizer_stream_start") {
    state.status =
      "streaming";
  } else if (event === "summarizer_stream_chunk") {
    const chunk =
      String(
        meta?.summarizer_stream_chunk
        || ""
      );

    if (meta?.summarizer_stream_kind === "thinking") {
      state.reasoning +=
        chunk;
    } else if (meta?.summarizer_stream_kind === "content") {
      state.answer +=
        chunk;
    }

    state.status =
      "streaming";
  } else if (event === "summarizer_stream_end") {
    state.status =
      "complete";
  } else if (event === "summarizer_stream_error") {
    state.status =
      "failed";
  }

  ensureL1SummarizerStreamButton(
    state
  );

  scheduleL1SummarizerStreamModalRefresh(
    streamId
  );

  return true;
}

