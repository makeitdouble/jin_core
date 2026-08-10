let traceModal;
let traceModalContent;
let traceModalReason;
let traceModalTitle;
let traceModalL1StreamId = null;
let traceModalL1StreamStatus = null;
let traceModalL1StreamReasoning = null;
let traceModalL1StreamAnswer = null;
let traceModalL1StreamFrame = null;

function ensureTraceModal() {
  if (traceModal) {
    return;
  }

  traceModal =
    document.createElement("div");

  traceModal.className =
    "fixed inset-0 z-50 hidden items-center justify-center bg-black/70 p-4";

  const panel =
    document.createElement("div");

  panel.className =
    "delayed-memory-modal-panel w-full max-w-5xl max-h-[86vh] rounded border border-zinc-700 bg-zinc-950 shadow-2xl flex flex-col";

  const header =
    document.createElement("div");

  header.className =
    "h-11 shrink-0 border-b border-zinc-800 px-4 flex items-center justify-between";

  traceModalTitle =
    document.createElement("div");

  traceModalTitle.className =
    "text-xs uppercase tracking-widest text-zinc-300";

  traceModalTitle.textContent =
    "Trace";

  const closeButton =
    document.createElement("button");

  closeButton.type =
    "button";

  closeButton.className =
    "delayed-memory-modal-icon-button delayed-memory-modal-close";

  closeButton.setAttribute(
    "aria-label",
    "Close"
  );

  closeButton.textContent =
    "\u00d7";

  traceModalReason =
    document.createElement("div");

  traceModalReason.className =
    "hidden border-b border-zinc-800 px-4 py-3 text-[12px] leading-relaxed text-red-200";

  traceModalReason.style.overflowWrap =
    "anywhere";

  traceModalContent =
    document.createElement("div");

  traceModalContent.className =
    "delayed-memory-modal-content min-h-0 flex-1 overflow-auto p-4 text-[12px] leading-relaxed text-zinc-200";

  traceModalContent.style.overflowWrap =
    "anywhere";

  header.appendChild(
    traceModalTitle
  );

  header.appendChild(
    closeButton
  );

  panel.appendChild(
    header
  );

  panel.appendChild(
    traceModalReason
  );

  panel.appendChild(
    traceModalContent
  );

  traceModal.appendChild(
    panel
  );

  document.body.appendChild(
    traceModal
  );

  function closeTraceModal() {
    traceModal.classList.add(
      "hidden"
    );

    traceModal.classList.remove(
      "flex"
    );

    traceModalL1StreamId =
      null;

    traceModalL1StreamStatus =
      null;

    traceModalL1StreamReasoning =
      null;

    traceModalL1StreamAnswer =
      null;

    if (traceModalL1StreamFrame !== null) {
      cancelAnimationFrame(
        traceModalL1StreamFrame
      );

      traceModalL1StreamFrame =
        null;
    }
  }

  closeButton.addEventListener(
    "click",
    closeTraceModal
  );

  traceModal.addEventListener(
    "click",
    function (event) {
      if (event.target === traceModal) {
        closeTraceModal();
      }
    }
  );

  document.addEventListener(
    "keydown",
    function (event) {
      if (event.key === "Escape") {
        closeTraceModal();
      }
    }
  );
}


function appendTraceSection(
  parent,
  title,
  content,
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

  body.textContent =
    String(content || "").trim()
    || "<empty>";

  section.appendChild(
    heading
  );

  section.appendChild(
    body
  );

  parent.appendChild(
    section
  );
}

function normalizeTraceModalDisplayText(value) {
  if (value === null || typeof value === "undefined") {
    return "";
  }

  if (typeof value === "string") {
    return value.trim();
  }

  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }

  if (Array.isArray(value)) {
    return value
      .map((item) => normalizeTraceModalDisplayText(item))
      .filter(Boolean)
      .join(", ");
  }

  if (typeof value === "object") {
    try {
      return JSON.stringify(
        value,
        null,
        2
      );
    } catch (_error) {
      return String(value);
    }
  }

  return String(value);
}

function appendTraceModalField(
  parent,
  label,
  value,
) {
  const normalizedValue =
    normalizeTraceModalDisplayText(value);

  if (!normalizedValue) {
    return;
  }

  const row =
    document.createElement("div");

  row.className =
    "delayed-memory-modal-field";

  const key =
    document.createElement("div");

  key.className =
    "delayed-memory-modal-label";

  key.textContent =
    label;

  const text =
    document.createElement("div");

  text.className =
    "delayed-memory-modal-value";

  text.textContent =
    normalizedValue;

  row.appendChild(
    key
  );

  row.appendChild(
    text
  );

  parent.appendChild(
    row
  );
}

function appendTraceModalBody(
  parent,
  title,
  content,
) {
  const normalizedBody =
    normalizeTraceModalDisplayText(content);

  if (!normalizedBody) {
    return;
  }

  const section =
    document.createElement("section");

  section.className =
    "delayed-memory-modal-section";

  const heading =
    document.createElement("div");

  heading.className =
    "delayed-memory-modal-section-title";

  heading.textContent =
    title;

  const pre =
    document.createElement("pre");

  pre.className =
    "delayed-memory-modal-body";

  pre.textContent =
    normalizedBody;

  section.appendChild(
    heading
  );

  section.appendChild(
    pre
  );

  parent.appendChild(
    section
  );
}

function prettifyTraceFieldName(value) {
  return String(value || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, function (letter) {
      return letter.toUpperCase();
    });
}

function formatStructuredTraceValue(value) {
  if (value === null || typeof value === "undefined") {
    return "<empty>";
  }

  if (Array.isArray(value) || typeof value === "object") {
    try {
      return JSON.stringify(
        value,
        null,
        2
      );
    } catch (_error) {
      return String(value);
    }
  }

  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }

  const text = String(value);
  return text || "<empty>";
}

function appendStructuredTraceFields(
  parent,
  data,
  orderedKeys = [],
) {
  const source =
    data && typeof data === "object" && !Array.isArray(data)
      ? data
      : {};

  const fields =
    document.createElement("section");

  fields.className =
    "delayed-memory-modal-fields";

  const keys = [];
  const seen = new Set();

  orderedKeys.concat(Object.keys(source)).forEach((key) => {
    if (seen.has(key) || !Object.prototype.hasOwnProperty.call(source, key)) {
      return;
    }
    seen.add(key);
    keys.push(key);
  });

  keys.forEach((key) => {
    const row =
      document.createElement("div");

    row.className =
      "delayed-memory-modal-field";

    const label =
      document.createElement("div");

    label.className =
      "delayed-memory-modal-label";

    label.textContent =
      prettifyTraceFieldName(key);

    const value =
      document.createElement("div");

    value.className =
      "delayed-memory-modal-value";

    value.textContent =
      formatStructuredTraceValue(source[key]);

    row.appendChild(label);
    row.appendChild(value);
    fields.appendChild(row);
  });

  parent.appendChild(fields);
}

function renderL4FactTrace(parsed) {
  const fact =
    parsed && parsed.fact && typeof parsed.fact === "object"
      ? parsed.fact
      : {};

  appendStructuredTraceFields(
    traceModalContent,
    fact,
    [
      "id",
      "key",
      "value",
      "category",
      "mention_count",
      "created_at",
      "updated_at",
      "source_session_ids",
      "source_runtime_snapshot_ids",
      "source_keys",
      "source_fact_ids",
    ]
  );
}

function appendL4ResponseGroup(
  title,
  value,
) {
  const section =
    document.createElement("section");

  section.className =
    "delayed-memory-modal-section";

  const heading =
    document.createElement("div");

  heading.className =
    "delayed-memory-modal-section-title";

  heading.textContent =
    title;

  section.appendChild(heading);
  traceModalContent.appendChild(section);

  if (value && typeof value === "object" && !Array.isArray(value)) {
    appendStructuredTraceFields(
      section,
      value
    );
    return;
  }

  appendTraceModalBody(
    section,
    "Value",
    value
  );
}

function renderL4SummarizerResponseTrace(parsed) {
  if (parsed.no_changes) {
    const empty =
      document.createElement("div");

    empty.className =
      "l4-trace-no-changes";

    empty.textContent =
      "No changes";

    traceModalContent.appendChild(empty);
    return;
  }

  const payload = parsed.payload;
  const phase = String(parsed.phase || "").toLowerCase();

  if (phase === "extraction" && payload && Array.isArray(payload.facts)) {
    payload.facts.forEach((fact, index) => {
      appendL4ResponseGroup(
        `Fact ${index + 1}`,
        fact
      );
    });
    return;
  }

  if (phase === "merge" && payload && Array.isArray(payload.operations)) {
    payload.operations.forEach((operation, index) => {
      const action =
        operation && operation.action
          ? ` · ${String(operation.action).toUpperCase()}`
          : "";

      appendL4ResponseGroup(
        `Operation ${index + 1}${action}`,
        operation
      );
    });
    return;
  }

  if (payload && typeof payload === "object" && !Array.isArray(payload)) {
    appendStructuredTraceFields(
      traceModalContent,
      payload
    );
    return;
  }

  appendTraceModalBody(
    traceModalContent,
    "Response",
    parsed.raw || payload || ""
  );
}

function renderL4SkipTrace(parsed) {
  appendTraceModalBody(
    traceModalContent,
    "What happened",
    parsed.summary || "The L4 model response was not usable."
  );

  const fields =
    document.createElement("section");

  fields.className =
    "delayed-memory-modal-fields";

  appendTraceModalField(
    fields,
    "Phase",
    parsed.phase
  );

  appendTraceModalField(
    fields,
    "Finish reason",
    parsed.finish_reason
  );

  appendTraceModalField(
    fields,
    "Limit reached",
    parsed.limit_type
  );

  appendTraceModalField(
    fields,
    "Model",
    parsed.model
  );

  appendTraceModalField(
    fields,
    "Context window",
    parsed.context_window_tokens
      ? `${parsed.context_window_tokens} tokens`
      : ""
  );

  appendTraceModalField(
    fields,
    "Requested max output",
    parsed.requested_max_output_tokens
      ? `${parsed.requested_max_output_tokens} tokens`
      : ""
  );

  appendTraceModalField(
    fields,
    "Effective max output",
    parsed.effective_max_output_tokens
      ? `${parsed.effective_max_output_tokens} tokens`
      : ""
  );

  appendTraceModalField(
    fields,
    "Prompt tokens",
    parsed.prompt_tokens
  );

  appendTraceModalField(
    fields,
    "Generated tokens",
    parsed.completion_tokens
  );

  appendTraceModalField(
    fields,
    "Total tokens",
    parsed.total_tokens
  );

  appendTraceModalField(
    fields,
    "Assistant response",
    parsed.assistant_content
  );

  appendTraceModalField(
    fields,
    "Reasoning generated",
    parsed.reasoning_generated
  );

  if (fields.childElementCount) {
    traceModalContent.appendChild(
      fields
    );
  }

  appendTraceModalBody(
    traceModalContent,
    "What JIN did",
    "The incomplete response was discarded. No L4 facts were merged or removed."
  );

  appendTraceModalBody(
    traceModalContent,
    "Retry behavior",
    parsed.retry_behavior
  );

  const pendingCount =
    Number(
      parsed.pending_count
      || parsed.selected_fields_count
      || 0
    );

  if (pendingCount) {
    appendTraceModalBody(
      traceModalContent,
      "Pending batch kept",
      `${pendingCount} item${pendingCount === 1 ? "" : "s"} remain pending.`
    );
  }

  if (
      Array.isArray(parsed.pending_ids)
      && parsed.pending_ids.length
  ) {
    appendTraceModalBody(
      traceModalContent,
      "Pending IDs",
      parsed.pending_ids.join("\n")
    );
  }
}

function isSummarizerRequestPayload(parsed) {
  return Boolean(
    parsed
    && typeof parsed === "object"
    && Array.isArray(parsed.messages)
    && parsed.messages.some((message) => {
      return (
        message
        && typeof message === "object"
        && typeof message.role === "string"
        && Object.prototype.hasOwnProperty.call(
          message,
          "content"
        )
      );
    })
  );
}

function renderSummarizerRequestTrace(
  parsed,
  title,
) {
  const fields =
    document.createElement("section");

  fields.className =
    "delayed-memory-modal-fields";

  appendTraceModalField(
    fields,
    "Title",
    title
  );

  appendTraceModalField(
    fields,
    "Model",
    parsed.model
  );

  appendTraceModalField(
    fields,
    "Temperature",
    parsed.temperature
  );

  appendTraceModalField(
    fields,
    "Max tokens",
    parsed.max_tokens
  );

  appendTraceModalField(
    fields,
    "Stream",
    parsed.stream
  );

  appendTraceModalField(
    fields,
    "Messages",
    parsed.messages.length
  );

  traceModalContent.appendChild(
    fields
  );

  parsed.messages.forEach((message, index) => {
    const role =
      normalizeTraceModalDisplayText(message.role)
      || `message ${index + 1}`;

    appendTraceModalBody(
      traceModalContent,
      `${role} message`,
      message.content
    );
  });

  const extra = {};

  Object.entries(parsed).forEach(([key, value]) => {
    if (
        [
          "model",
          "messages",
          "temperature",
          "max_tokens",
          "stream",
        ].includes(key)
    ) {
      return;
    }

    extra[key] = value;
  });

  if (Object.keys(extra).length) {
    appendTraceModalBody(
      traceModalContent,
      "Extra request options",
      extra
    );
  }
}

function formatEmbeddedSummarizerReasoning(details) {
  const text =
    String(details || "");

  const sectionMarker =
    "Summarizer response details:";

  const sectionIndex =
    text.indexOf(sectionMarker);

  if (sectionIndex < 0) {
    return text;
  }

  const jsonStart =
    text.indexOf(
      "{",
      sectionIndex + sectionMarker.length
    );

  if (jsonStart < 0) {
    return text;
  }

  const responseText =
    text.slice(jsonStart);

  const response =
    parseTraceJson(
      responseText.trim()
    );

  if (
      !response
      || response.kind !== "summarizer_response"
      || typeof response.reasoning_content !== "string"
      || !response.reasoning_content
  ) {
    return text;
  }

  const serializedReasoning =
    JSON.stringify(
      response.reasoning_content
    );

  const fieldText =
    `"reasoning_content": ${serializedReasoning}`;

  const fieldIndex =
    responseText.indexOf(fieldText);

  if (fieldIndex < 0) {
    return text;
  }

  const lineStart =
    responseText.lastIndexOf(
      "\n",
      fieldIndex
    ) + 1;

  const indent =
    responseText.slice(
      lineStart,
      fieldIndex
    );

  let fieldEnd =
    fieldIndex + fieldText.length;

  if (responseText[fieldEnd] === ",") {
    fieldEnd += 1;
  }

  const reasoning =
    response.reasoning_content.replace(
      /\r\n?/g,
      "\n"
    );

  const formattedField = [
    `"reasoning_content":`,
    `${indent}--------------------`,
    reasoning,
    "",
  ].join("\n");

  return (
    text.slice(0, jsonStart)
    + responseText.slice(0, fieldIndex)
    + formattedField
    + responseText.slice(fieldEnd)
  );
}


function contextElement(
  tag,
  className,
  text = null,
) {
  const element =
    document.createElement(tag);

  if (className) {
    element.className = className;
  }

  if (text !== null) {
    element.textContent = text;
  }

  return element;
}

function parseContextTraceSnapshot(details) {
  const text =
    String(details || "").replace(
      /\r\n?/g,
      "\n"
    );

  const header =
    text.match(
      /^SYSTEM PROMPT(?: \(INTERNAL ACTION RULES HIDDEN\))?\n-+\n/
    );
  const userMarker =
    /\nUSER PROMPT \/ CONTEXT PAYLOAD\n-+\n/;
  const user =
    userMarker.exec(text);

  if (!header || !user) {
    return null;
  }

  return {
    hiddenInternalActionRules:
      header[0].includes(
        "INTERNAL ACTION RULES HIDDEN"
      ),
    systemPrompt:
      text.slice(
        header[0].length,
        user.index
      ).trim(),
    userPrompt:
      text.slice(
        user.index + user[0].length
      ).trim(),
  };
}

function parseContextAttributes(raw) {
  const attributes = [];
  const pattern =
    /([A-Za-z_][\w.-]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s]+))/g;
  let match;

  while ((match = pattern.exec(String(raw || "")))) {
    attributes.push(
      `${match[1]}=${match[2] ?? match[3] ?? match[4] ?? ""}`
    );
  }

  return attributes;
}

function parseContextRuntimeActionMarkerTitle(
  line,
  nextLine,
) {
  if (
      !/^Follow-up:\s*(?:true|false)\s*$/i.test(
        String(nextLine || "").trim()
      )
  ) {
    return "";
  }

  const marker =
    String(line || "").trim();
  const match =
    marker.match(
      /^<([A-Z][A-Z0-9_]*)(?::[^>\n]*)?>(?:<\/\1>)?$/
    );

  return match ? match[1] : "";
}

function splitContextPlainText(text) {
  const blocks = [];
  let title = "SYSTEM RULES";
  let lines = [];

  const flush = () => {
    const content =
      lines.join("\n").trim();

    if (content) {
      blocks.push({
        title,
        content,
        attributes: [],
        xml: false,
      });
    }

    lines = [];
  };

  const sourceLines =
    String(text || "").split("\n");

  for (let i = 0; i < sourceLines.length; i += 1) {
    const line = sourceLines[i];
    const heading = line.trim();
    const markerTitle =
      parseContextRuntimeActionMarkerTitle(
        line,
        sourceLines[i + 1]
      );

    if (markerTitle) {
      flush();
      title = markerTitle;
      lines.push(line);

      for (i += 1; i < sourceLines.length; i += 1) {
        const actionLine = sourceLines[i];

        if (!actionLine.trim()) {
          break;
        }

        if (actionLine.trim() === `${markerTitle}:`) {
          continue;
        }

        lines.push(actionLine);
      }

      flush();
      title = "SYSTEM RULES";
      continue;
    }

    if (
        /^[A-Z][A-Z0-9 _/&()\-]{3,}:$/.test(heading)
    ) {
      flush();
      title = heading.slice(0, -1);
      continue;
    }

    lines.push(line);
  }

  flush();
  return blocks;
}

function parseContextBlocks(text) {
  const source =
    String(text || "").replace(
      /\r\n?/g,
      "\n"
    );
  const lines = source.split("\n");
  const blocks = [];
  let plain = [];

  const flushPlain = () => {
    const content =
      plain.join("\n").trim();

    if (content) {
      blocks.push(
        ...splitContextPlainText(content)
      );
    }

    plain = [];
  };

  for (let i = 0; i < lines.length; i += 1) {
    const markerTitle =
      parseContextRuntimeActionMarkerTitle(
        lines[i],
        lines[i + 1]
      );

    if (markerTitle) {
      plain.push(lines[i]);

      for (i += 1; i < lines.length; i += 1) {
        plain.push(lines[i]);

        if (!lines[i].trim()) {
          break;
        }
      }

      continue;
    }

    const open =
      lines[i].match(
        /^\s*<([A-Za-z][\w.-]*)(\s+[^>]*)?>\s*$/
      );

    if (!open) {
      plain.push(lines[i]);
      continue;
    }

    const closeText =
      `</${open[1]}>`;
    let close = -1;

    for (let j = i + 1; j < lines.length; j += 1) {
      if (lines[j].trim() === closeText) {
        close = j;
        break;
      }
    }

    if (close < 0) {
      plain.push(lines[i]);
      continue;
    }

    flushPlain();
    blocks.push({
      title: open[1],
      attributes:
        parseContextAttributes(open[2]),
      content:
        lines.slice(i + 1, close)
          .join("\n")
          .trim(),
      xml: true,
    });
    i = close;
  }

  flushPlain();
  return blocks;
}

function contextBadge(text, attribute = false) {
  return contextElement(
    "span",
    attribute
      ? "jin-context-badge jin-context-badge-attribute"
      : "jin-context-badge",
    text
  );
}

function parseContextRows(content) {
  const lines =
    String(content || "")
      .split("\n")
      .filter((line) => line.trim());

  const chat = lines.map((line) => {
    const match =
      line.match(
        /^\s*<(USER|JIN|SERVICE|BRAIN)>([\s\S]*?)(?:<\/\1>)?\s*$/
      );

    return match
      ? {
          kind: "chat",
          key: match[1],
          value: match[2].trim(),
        }
      : null;
  });

  if (chat.length && chat.every(Boolean)) {
    return chat;
  }

  const tags = lines.map((line) => {
    const match =
      line.match(
        /^\s*<([A-Za-z][\w.-]*)>([\s\S]*?)<\/\1>\s*$/
      );

    return match
      ? {
          kind: "kv",
          key: match[1],
          value: match[2].trim(),
        }
      : null;
  });

  if (tags.length && tags.every(Boolean)) {
    return tags;
  }

  const fields = lines
    .map((line) => {
      const match =
        line.match(
          /^\s*([^:]{1,90}):\s*(.*)$/
        );

      return match
        ? {
            kind: "kv",
            key: match[1].trim(),
            value: match[2].trim(),
          }
        : null;
    })
    .filter(Boolean);

  if (
      fields.length >= 2
      && fields.length / Math.max(lines.length, 1) >= 0.7
  ) {
    return fields;
  }

  return [];
}

function renderContextBody(parent, content) {
  const text =
    String(content || "").trim();

  if (!text) {
    parent.appendChild(
      contextElement(
        "div",
        "jin-context-empty",
        "EMPTY"
      )
    );
    return;
  }

  const rows =
    parseContextRows(text);

  if (rows.length) {
    const list =
      contextElement(
        "div",
        "jin-context-kv-list"
      );

    rows.forEach((row) => {
      const item =
        contextElement(
          "div",
          row.kind === "chat"
            ? `jin-context-chat-row jin-context-chat-${row.key.toLowerCase()}`
            : "jin-context-kv-row"
        );

      item.appendChild(
        contextElement(
          "div",
          row.kind === "chat"
            ? "jin-context-chat-role"
            : "jin-context-kv-key",
          row.key
        )
      );
      item.appendChild(
        contextElement(
          "div",
          row.kind === "chat"
            ? "jin-context-chat-content"
            : "jin-context-kv-value",
          row.value || "<empty>"
        )
      );
      list.appendChild(item);
    });

    parent.appendChild(list);
    return;
  }

  const lines =
    text.split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
  const simpleList =
    lines.length > 1
    && lines.length <= 40
    && lines.every((line) => (
      /^\d+[.)]\s+/.test(line)
      || /^[A-Za-z0-9_#.-]+(?:\s+.*)?$/.test(line)
    ));

  if (simpleList) {
    const list =
      contextElement(
        "div",
        "jin-context-line-list"
      );

    lines.forEach((line) => {
      list.appendChild(
        contextElement(
          "div",
          "jin-context-line-item",
          line
        )
      );
    });

    parent.appendChild(list);
    return;
  }

  parent.appendChild(
    contextElement(
      "pre",
      "jin-context-raw",
      text
    )
  );
}

function appendContextCard(
  parent,
  block,
) {
  const card =
    contextElement(
      "section",
      `jin-context-card ${block.xml ? "jin-context-card-xml" : "jin-context-card-plain"}`
    );
  const header =
    contextElement(
      "div",
      "jin-context-card-header"
    );
  const heading =
    contextElement(
      "div",
      "jin-context-card-heading"
    );
  const meta =
    contextElement(
      "div",
      "jin-context-card-meta"
    );
  const body =
    contextElement(
      "div",
      "jin-context-card-body"
    );

  header.title =
    "Double-click to collapse / expand";
  header.tabIndex = 0;
  header.setAttribute("role", "button");
  header.setAttribute("aria-expanded", "true");

  heading.appendChild(
    contextElement(
      "span",
      "jin-context-card-chevron",
      "▾"
    )
  );
  heading.appendChild(
    contextElement(
      "div",
      "jin-context-card-title",
      block.title
    )
  );

  block.attributes.forEach((attribute) => {
    meta.appendChild(
      contextBadge(attribute, true)
    );
  });
  meta.appendChild(
    contextBadge(
      `${String(block.content || "").split("\n").filter((line) => line.trim()).length} lines`
    )
  );

  const toggle = () => {
    const collapsed =
      card.classList.toggle(
        "is-collapsed"
      );

    header.setAttribute(
      "aria-expanded",
      collapsed ? "false" : "true"
    );
  };

  header.addEventListener(
    "dblclick",
    toggle
  );
  header.addEventListener(
    "keydown",
    function (event) {
      if (
          event.key !== "Enter"
          && event.key !== " "
      ) {
        return;
      }

      event.preventDefault();
      toggle();
    }
  );

  header.appendChild(heading);
  header.appendChild(meta);
  card.appendChild(header);
  card.appendChild(body);
  renderContextBody(body, block.content);
  parent.appendChild(card);
}

function renderContextSnapshotTrace(snapshot) {
  const blocks =
    parseContextBlocks(
      snapshot.systemPrompt
    );
  const overview =
    contextElement(
      "div",
      "jin-context-overview"
    );
  const badges =
    contextElement(
      "div",
      "jin-context-overview-badges"
    );

  overview.appendChild(
    contextElement(
      "div",
      "jin-context-overview-title",
      "CONTEXT WINDOW"
    )
  );
  badges.appendChild(
    contextBadge(`${blocks.length} blocks`)
  );
  badges.appendChild(
    contextBadge(
      `${snapshot.systemPrompt.length.toLocaleString()} system chars`
    )
  );
  if (snapshot.hiddenInternalActionRules) {
    badges.appendChild(
      contextBadge("internal rules hidden")
    );
  }
  overview.appendChild(badges);
  traceModalContent.appendChild(overview);

  const stack =
    contextElement(
      "div",
      "jin-context-stack"
    );

  blocks.forEach((block) => {
    appendContextCard(stack, block);
  });

  appendContextCard(
    stack,
    {
      title: "USER PROMPT / CONTEXT PAYLOAD",
      content:
        snapshot.userPrompt || "<empty>",
      attributes: [],
      xml: false,
    }
  );
  stack.lastElementChild.classList.add(
    "jin-context-card-user"
  );

  traceModalContent.appendChild(stack);
}

function renderTraceDetails(
  details,
  title = "Trace",
) {
  traceModalContent.replaceChildren();

  const contextSnapshot =
    parseContextTraceSnapshot(details);

  traceModal.classList.toggle(
    "jin-context-trace-modal",
    Boolean(contextSnapshot)
  );

  if (contextSnapshot) {
    renderContextSnapshotTrace(
      contextSnapshot
    );

    return;
  }

  const parsed =
    parseTraceJson(details);

  if (
      parsed
      && parsed.kind === "l4_fact"
  ) {
    renderL4FactTrace(
      parsed
    );

    return;
  }

  if (
      parsed
      && parsed.kind === "l4_summarizer_response"
  ) {
    renderL4SummarizerResponseTrace(
      parsed
    );

    return;
  }

  if (
      parsed
      && parsed.kind === "l4_skip"
  ) {
    renderL4SkipTrace(
      parsed
    );

    return;
  }

  if (
      parsed
      && parsed.kind === "user_payload_trace"
  ) {
    renderUserPayloadTrace(
      parsed
    );

    return;
  }

  if (isSummarizerRequestPayload(parsed)) {
    renderSummarizerRequestTrace(
      parsed,
      title
    );

    return;
  }

  if (
      parsed
      && parsed.kind === "summarizer_response"
  ) {
    const meta = {
      model: parsed.model || "",
      finish_reason: parsed.finish_reason || "",
      allow_reasoning_fallback: Boolean(parsed.allow_reasoning_fallback),
      used_reasoning_fallback: Boolean(parsed.used_reasoning_fallback),
      usage: parsed.usage || {},
    };

    appendTraceSection(
      traceModalContent,
      "Meta",
      JSON.stringify(
        meta,
        null,
        2
      )
    );

    appendTraceSection(
      traceModalContent,
      "Assistant content",
      parsed.content || ""
    );

    appendTraceSection(
      traceModalContent,
      "Reasoning content",
      parsed.reasoning_content || ""
    );

    appendTraceSection(
      traceModalContent,
      "Extracted L1 memory text",
      parsed.extracted_memory || ""
    );

    appendTraceSection(
      traceModalContent,
      "Raw message",
      JSON.stringify(
        parsed.message || {},
        null,
        2
      )
    );

    return;
  }

  const pre =
    document.createElement("pre");

  pre.className =
    "whitespace-pre-wrap text-[12px] leading-relaxed text-zinc-200";

  pre.style.overflowWrap =
    "anywhere";

  pre.textContent =
    formatEmbeddedSummarizerReasoning(
      details
    );

  traceModalContent.appendChild(
    pre
  );
}

function getTraceTitle(
  details,
  fallbackTitle,
) {
  const parsed =
    parseTraceJson(details);

  if (
      parsed
      && parsed.kind === "summarizer_response"
  ) {
    return "Summarizer response";
  }

  if (isSummarizerRequestPayload(parsed)) {
    return fallbackTitle || "Summarizer request";
  }

  return fallbackTitle;
}

function showTrace(
  details,
  title = "Trace",
  reason = null,
) {
  ensureTraceModal();

  traceModalL1StreamId =
    null;

  traceModalL1StreamStatus =
    null;

  traceModalL1StreamReasoning =
    null;

  traceModalL1StreamAnswer =
    null;

  if (traceModalL1StreamFrame !== null) {
    cancelAnimationFrame(
      traceModalL1StreamFrame
    );

    traceModalL1StreamFrame =
      null;
  }

  traceModalTitle.textContent =
    title;

  if (reason) {
    traceModalReason.textContent =
      `Reason: ${reason}`;

    traceModalReason.classList.remove(
      "hidden"
    );
  } else {
    traceModalReason.textContent =
      "";

    traceModalReason.classList.add(
      "hidden"
    );
  }

  renderTraceDetails(
    details,
    title
  );

  traceModal.classList.remove(
    "hidden"
  );

  traceModal.classList.add(
    "flex"
  );
}



window.showTrace =
  showTrace;
