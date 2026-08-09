const delayedMemoryClientFilterState = {
  pendingByMessageId: new Map(),
  activeMessageIds: new Set(),
};

const delayedMemoryTagPairs = [
  {
    open: "<SAVE_DELAYED_MEMORY_CONTENT>",
    close: "</SAVE_DELAYED_MEMORY_CONTENT>",
  },
];


function startDelayedMemoryRuntimeBubble(
  messageId
) {

  const key =
    String(messageId || "__default__");

  if (
      delayedMemoryClientFilterState.activeMessageIds.has(key)
  ) {
    return;
  }

  delayedMemoryClientFilterState.activeMessageIds.add(
    key
  );

  if (window.appendRuntimeAction) {
    window.appendRuntimeAction(
      "save_delayed_memory_content",
      "SAVE_DELAYED_MEMORY_CONTENT",
      {
        displayName: "SAVE_DELAYED_MEMORY_CONTENT",
        closeTag: true,
      }
    );
  }

}


function completeDelayedMemoryRuntimeBubble(
  messageId
) {

  const key =
    String(messageId || "__default__");

  delayedMemoryClientFilterState.activeMessageIds.delete(
    key
  );

  if (window.fadeRuntimeAction) {
    window.fadeRuntimeAction(
      "save_delayed_memory_content"
    );
  }

}


function generateDelayedMemoryReportId(
  existingReports
) {

  const alphabet =
    "abcdefghijklmnopqrstuvwxyz0123456789";
  const used =
    new Set(
      Object.keys(existingReports || {})
        .map(key => String(key || "").trim().toLowerCase())
        .filter(key => /^[a-z0-9]{6}$/.test(key))
    );

  for (let attempt = 0; attempt < 1000; attempt += 1) {
    let reportId = "";
    const randomValues =
      window.crypto && window.crypto.getRandomValues
        ? window.crypto.getRandomValues(new Uint8Array(6))
        : null;

    for (let index = 0; index < 6; index += 1) {
      const value =
        randomValues
          ? randomValues[index]
          : Math.floor(Math.random() * 256);

      reportId +=
        alphabet[value % alphabet.length];
    }

    if (!used.has(reportId)) {
      return reportId;
    }
  }

  return Math.random().toString(36).slice(2, 8).padEnd(6, "0");

}


function normalizeDelayedMemoryFactIds(
  value
) {

  const source =
    Array.isArray(value)
      ? value
      : [value];
  const seen = new Set();
  const candidates = [];

  source.forEach(function (item) {
    if (Array.isArray(item)) {
      normalizeDelayedMemoryFactIds(item).forEach(
        factId => candidates.push(factId)
      );
      return;
    }

    const text =
      String(item || "").trim();

    if (text.startsWith("[") && text.endsWith("]")) {
      try {
        const parsed = JSON.parse(text);

        if (Array.isArray(parsed)) {
          normalizeDelayedMemoryFactIds(parsed).forEach(
            factId => candidates.push(factId)
          );
          return;
        }
      } catch (_error) {
        // Fall through to token parsing.
      }
    }

    text.split(/[;,\s]+/).forEach(
      candidate => candidates.push(candidate)
    );
  });

  return candidates
    .map(item => String(item || "").trim().replace(/^["'\[]+|["'\]]+$/g, "").toUpperCase())
    .filter(
      factId => {
        if (!/^F[1-9]\d*$/.test(factId) || seen.has(factId)) {
          return false;
        }
        seen.add(factId);
        return true;
      }
    );

}

function parseDelayedMemoryReportPayload(
  payload
) {

  const text =
    String(payload || "")
      .replace(/\r\n/g, "\n")
      .trim();

  if (!text) {
    return {};
  }

  const fieldPattern =
    /^[^\S\r\n]*(title|summary|tags|body|anchor_fact_ids|facts_ids|absorbed_fact_ids|long_term_facts_ids)[^\S\r\n]*:[^\S\r\n]*(.*)$/gim;

  const matches = [];
  let match = fieldPattern.exec(text);

  while (match) {
    matches.push({
      name: String(match[1] || "").toLowerCase(),
      inline: String(match[2] || "").trim(),
      start: match.index,
      end: fieldPattern.lastIndex,
    });

    match = fieldPattern.exec(text);
  }

  if (!matches.length) {
    return {};
  }

  const fields = {};

  matches.forEach(
    function (
      field,
      index,
    ) {
      const nextStart =
        index + 1 < matches.length
          ? matches[index + 1].start
          : text.length;

      const blockValue =
        text.slice(
          field.end,
          nextStart
        ).replace(/^\n+|\n+$/g, "");

      fields[field.name] =
        field.name === "body"
          ? [field.inline, blockValue]
              .filter(Boolean)
              .join("\n")
              .trim()
          : [
              "anchor_fact_ids",
              "facts_ids",
              "absorbed_fact_ids",
              "long_term_facts_ids",
            ].includes(field.name)
            ? [field.inline, blockValue]
                .filter(Boolean)
                .join(" ")
                .trim()
            : field.inline;
    }
  );

  const title =
    String(fields.title || "").trim();

  if (!title) {
    return {};
  }

  const currentReports =
    window.JinRuntime
      && window.JinRuntime.runtime
      && window.JinRuntime.runtime.getDelayedMemoryReports
        ? window.JinRuntime.runtime.getDelayedMemoryReports()
        : {};
  const key =
    generateDelayedMemoryReportId(
      currentReports
    );

  const anchorFactIds =
    normalizeDelayedMemoryFactIds(
      fields.anchor_fact_ids
    );
  const factsIds =
    normalizeDelayedMemoryFactIds([
      ...anchorFactIds,
      ...normalizeDelayedMemoryFactIds(fields.facts_ids),
      ...normalizeDelayedMemoryFactIds(fields.absorbed_fact_ids),
      ...normalizeDelayedMemoryFactIds(fields.long_term_facts_ids),
    ]);

  return {
    [key]: {
      title,
      summary:
        String(fields.summary || "").trim(),
      tags:
        String(fields.tags || "")
          .split(",")
          .map(tag => tag.trim())
          .filter(Boolean),
      body:
        String(fields.body || "").trim(),
      anchor_fact_ids: anchorFactIds,
      facts_ids: factsIds,
      created_session_id:
        String(window.jinRuntimeSessionId || websocketClientId || "").trim(),
      created_time:
        new Date().toISOString(),
    },
  };

}


function appendDelayedMemoryReportFromClientFallback(
  payload
) {

  const report =
    parseDelayedMemoryReportPayload(
      payload
    );

  if (
      !Object.keys(report).length
      || !window.JinRuntime
      || !window.JinRuntime.runtime
      || !window.JinRuntime.runtime.appendDelayedMemoryReports
  ) {
    return false;
  }

  window.JinRuntime.runtime.appendDelayedMemoryReports(
    report
  );

  return true;

}


function filterDelayedMemoryContentFromChunk(
  messageId,
  chunk
) {

  const key =
    String(messageId || "__default__");

  let source =
    String(
      delayedMemoryClientFilterState.pendingByMessageId.get(key) || ""
    ) + String(chunk || "");

  let visible = "";

  while (source) {
    let matchedTags = null;
    let openIndex = -1;

    delayedMemoryTagPairs.forEach(
      function (tags) {
        const candidateIndex =
          source.indexOf(
            tags.open
          );

        if (
            candidateIndex >= 0
            && (openIndex < 0 || candidateIndex < openIndex)
        ) {
          openIndex = candidateIndex;
          matchedTags = tags;
        }
      }
    );

    if (openIndex < 0 || !matchedTags) {
      visible += source;
      source = "";
      break;
    }

    visible += source.slice(
      0,
      openIndex
    );

    startDelayedMemoryRuntimeBubble(
      key
    );

    const payloadStart =
      openIndex + matchedTags.open.length;

    const closeIndex =
      source.indexOf(
        matchedTags.close,
        payloadStart
      );

    if (closeIndex < 0) {
      delayedMemoryClientFilterState.pendingByMessageId.set(
        key,
        source.slice(openIndex)
      );

      return visible;
    }

    appendDelayedMemoryReportFromClientFallback(
      source.slice(
        payloadStart,
        closeIndex
      )
    );

    completeDelayedMemoryRuntimeBubble(
      key
    );

    source =
      source.slice(
        closeIndex + matchedTags.close.length
      );
  }

  delayedMemoryClientFilterState.pendingByMessageId.delete(
    key
  );

  return visible;

}


function clearDelayedMemoryContentFilter(
  messageId
) {

  const key =
    String(messageId || "__default__");

  delayedMemoryClientFilterState.pendingByMessageId.delete(
    key
  );

  delayedMemoryClientFilterState.activeMessageIds.delete(
    key
  );

}

function normalizeDelayedMemoryReportIds(value) {
  const source =
    Array.isArray(value)
      ? value
      : [value];
  const reportIds = [];
  const seen = new Set();

  source.forEach((item) => {
    const reportId =
      String(item || "").trim().toLowerCase();

    if (
        !/^[a-z0-9]{6}$/.test(reportId)
        || seen.has(reportId)
    ) {
      return;
    }

    seen.add(reportId);
    reportIds.push(reportId);
  });

  return reportIds;
}


function syncDelayedMemoryReportsToRuntime(options = {}) {
  if (
      !ws
      || ws.readyState !== WebSocket.OPEN
      || !window.JinRuntime
      || !window.JinRuntime.runtime
      || !window.JinRuntime.runtime.getDelayedMemoryReports
  ) {
    return;
  }

  const delayedMemoryReports =
    window.JinRuntime.runtime.getDelayedMemoryReports();
  const deletedReportIds =
    normalizeDelayedMemoryReportIds(
      options.deletedReportIds
      || options.deleted_delayed_memory_report_ids
      || []
    );

  if (
      !delayedMemoryReports
      || typeof delayedMemoryReports !== "object"
      || Array.isArray(delayedMemoryReports)
      || (
        !Object.keys(delayedMemoryReports).length
        && !deletedReportIds.length
      )
  ) {
    return false;
  }

  return sendSocketMessage({
    type: "delayed_memory_store_sync",
    delayed_memory_reports: delayedMemoryReports,
    deleted_delayed_memory_report_ids: deletedReportIds,
  });
}


window.syncDelayedMemoryReportsToRuntime =
  syncDelayedMemoryReportsToRuntime;


function handleDelayedMemoryStoreSnapshot(
  data
) {

  if (
      !data
      || !data.delayed_memory_reports
      || typeof data.delayed_memory_reports !== "object"
      || Array.isArray(data.delayed_memory_reports)
      || !window.JinRuntime
      || !window.JinRuntime.runtime
      || !window.JinRuntime.runtime.getDelayedMemoryReports
      || !window.JinRuntime.runtime.replaceDelayedMemoryReports
  ) {
    return;
  }

  const localReports =
    window.JinRuntime.runtime.getDelayedMemoryReports();

  window.JinRuntime.runtime.replaceDelayedMemoryReports({
    ...localReports,
    ...data.delayed_memory_reports,
  });

}


registerSocketMessageHandler(
  "delayed_memory_store_snapshot",
  handleDelayedMemoryStoreSnapshot
);
