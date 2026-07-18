(function () {

  window.JinRuntime = window.JinRuntime || {};

  function splitCompoundRuntimeMemoryLine(line) {

    const source =
        String(line || "");

    const boundaryRe =
        /(;|[.!?。！？])\s+(?=(?:[A-Za-z][A-Za-z0-9]*_+[A-Za-z0-9_]*|active_memory(?:_\d+)?)\s*:)/g;

    const pieces = [];
    let start = 0;
    let match = null;

    while ((match = boundaryRe.exec(source)) !== null) {
      const delimiter =
          match[1];

      const end =
          delimiter === ";"
            ? match.index
            : match.index + delimiter.length;

      const piece =
          source.slice(start, end).trim();

      if (piece) {
        pieces.push(piece);
      }

      start =
          boundaryRe.lastIndex;
    }

    const tail =
        source.slice(start).trim();

    if (tail) {
      pieces.push(tail);
    }

    return pieces;

  }



  function lineStartsRuntimeMemoryEntry(line) {

    return /^\s*-?\s*[A-Za-z][A-Za-z0-9_ #]{0,80}\s*:/.test(
        String(line || "")
    );

  }


  function escapeMultilineRuntimeMemoryTextLines(text) {

    const escapedLines = [];
    let pendingLine = null;

    const flushPending = () => {
      if (pendingLine !== null) {
        escapedLines.push(pendingLine);
        pendingLine = null;
      }
    };

    String(text || "")
      .split(/\r?\n/)
      .forEach((rawLine) => {
        const line =
            String(rawLine || "").trim().replace(/^-+/, "").trim();

        if (!line) {
          if (pendingLine !== null) {
            pendingLine += "\\n";
          }
          return;
        }

        if (lineStartsRuntimeMemoryEntry(line)) {
          flushPending();
          pendingLine = line;
          return;
        }

        if (pendingLine !== null) {
          pendingLine += `\\n${line}`;
          return;
        }

        escapedLines.push(line);
      });

    flushPending();

    return escapedLines;

  }

  function splitMemoryTextLines(text) {

    return escapeMultilineRuntimeMemoryTextLines(text)
      .flatMap(splitCompoundRuntimeMemoryLine)
      .map(line => line.trim())
      .filter(Boolean);

  }


  function appendProperties(
    value,
    properties = []
  ) {

    const normalizedProperties =
        (Array.isArray(properties)
          ? properties
          : [properties])
          .map(property => String(property || "").trim())
          .filter(Boolean)
          .map((property) => {
            if (
                property.startsWith("[")
                && property.endsWith("]")
            ) {
              return property;
            }

            return `[${property}]`;
          });

    return [
      String(value || "").trimEnd(),
      ...normalizedProperties,
    ].filter(Boolean).join(" ");

  }


  function splitMemoryMeta(value) {

    const raw =
        String(value || "");

    const tags = [];
    let text = raw;

    while (true) {
      const tag =
          extractTrailingMemoryMetaTag(
              text
          );

      if (!tag) {
        break;
      }

      tags.unshift({
        key: tag.key,
        value: tag.value,
        raw: tag.raw,
      });

      text =
          tag.text;
    }

    return {
      text,
      tags,
      raw,
    };

  }


  function extractTrailingMemoryMetaTag(value) {

    const source =
        String(value || "");

    let end = source.length - 1;

    while (
        end >= 0
        && /\s/.test(source.charAt(end))
    ) {
      end -= 1;
    }

    if (
        end < 0
        || source.charAt(end) !== "]"
    ) {
      return null;
    }

    let depth = 0;
    let start = -1;

    for (let index = end; index >= 0; index -= 1) {
      const char =
          source.charAt(index);

      if (char === "]") {
        depth += 1;
      } else if (char === "[") {
        depth -= 1;

        if (depth === 0) {
          start = index;
          break;
        }
      }
    }

    if (start < 0) {
      return null;
    }

    const body =
        source.slice(
            start + 1,
            end
        );

    const match =
        body.match(/^\s*([\w.-]+)\s*:\s*([\s\S]*)\s*$/);

    if (!match) {
      return null;
    }

    return {
      key: match[1],
      value: match[2].trim(),
      raw: source.slice(
          start,
          end + 1
      ).trim(),
      text: source.slice(
          0,
          start
      ).trimEnd(),
    };

  }


  function memoryMetaHasTag(
    parsed,
    key
  ) {

    const normalizedKey =
        String(key || "").trim().toLowerCase();

    return Boolean(
        parsed
        && Array.isArray(parsed.tags)
        && parsed.tags.some(
          tag => String(tag.key || "").toLowerCase() === normalizedKey
        )
    );

  }


  function setMemoryMetaValue(
    value,
    key,
    nextValue
  ) {

    const parsed =
        splitMemoryMeta(
            value
        );

    const normalizedKey =
        normalizeRuntimeMemoryKey(
            key
        );

    if (!normalizedKey) {
      return String(value || "");
    }

    let updated = false;
    const nextTags =
        parsed.tags.map((tag) => {
          if (
              normalizeRuntimeMemoryKey(tag.key)
              !== normalizedKey
          ) {
            return tag.raw;
          }

          updated = true;

          return `[ ${tag.key}: ${String(nextValue || "").trim()} ]`;
        });

    if (!updated) {
      nextTags.push(
          `[ ${key}: ${String(nextValue || "").trim()} ]`
      );
    }

    return appendProperties(
        parsed.text,
        nextTags
    );

  }


  function setRuntimeMemoryLineMetaValue(
    line,
    key,
    nextValue
  ) {

    const parsedLine =
        typeof line === "object"
          ? line
          : parseRuntimeMemoryLine(
              String(line || "")
          );

    const lineKey =
        parsedLine && parsedLine.key
          ? String(parsedLine.key)
          : "";

    if (!lineKey) {
      return String(line || "");
    }

    return `${lineKey}: ${setMemoryMetaValue(
        parsedLine.value || "",
        key,
        nextValue
    )}`;

  }


  // Removes bracket metadata from a runtime memory value for panel text, e.g. "Book [status: pending]" -> "Book".
  function stripMemoryMetaForDisplay(value) {

    return splitMemoryMeta(value).text;

  }


  // Removes bracket metadata from every runtime memory line for plain fallback rendering, e.g. "note: hi [trace: 0.50]" -> "note: hi".
  function stripMemoryTextMetaForDisplay(text) {

    return splitMemoryTextLines(text)
      .map(stripMemoryMetaForDisplay)
      .join("\n");

  }


  function normalizeRuntimeMemoryKey(key) {

    return String(key || "")
      .trim()
      .replace(/\s+/g, "_")
      .toLowerCase();

  }


  // Keeps known product acronyms uppercase in readable UI labels, e.g. "Last jin response" -> "Last JIN response".
  function normalizeDisplayLabelAcronyms(label) {

    return String(label || "")
      .replace(/\bjin\b/gi, "JIN");

  }


  // Converts a runtime memory key into a readable UI label, e.g. "user_name" -> "User name", "user_fact_1" -> "User fact #1", and "last_jin_response" -> "Last JIN response".
  function convertKeyToName(key) {

    const raw =
        String(key || "").trim();

    if (!raw) {
      return "";
    }

    const match =
        raw.match(/^(.*?)(?:[_\s]+)(\d+)$/);

    const base =
        (match ? match[1] : raw)
          .replace(/_/g, " ")
          .replace(/\s+/g, " ")
          .trim()
          .toLowerCase();

    if (!base) {
      return match ? `#${match[2]}` : "";
    }

    const label =
        normalizeDisplayLabelAcronyms(
            base.charAt(0).toUpperCase() + base.slice(1)
        );

    return match
      ? `${label} #${match[2]}`
      : label;

  }


  function isUserIdleRuntimeMemoryKey(key) {

    return normalizeRuntimeMemoryKey(key) === "user_idle";

  }


  function isActiveMemoryRuntimeMemoryKey(key) {

    return /^active_memory(?:_\d+)?$/.test(
        normalizeRuntimeMemoryKey(key)
    );

  }


  function isActiveMemoryRuntimeMemoryLine(line) {

    if (!line) {
      return false;
    }

    if (typeof line === "object") {
      return isActiveMemoryRuntimeMemoryKey(line.key);
    }

    const separatorIndex =
        String(line).indexOf(":");

    if (separatorIndex <= 0) {
      return false;
    }

    return isActiveMemoryRuntimeMemoryKey(
        String(line).slice(0, separatorIndex)
    );

  }


  function extractActiveMemoryRuntimeMemoryLines(text) {

    return splitMemoryTextLines(text)
      .filter(line => isActiveMemoryRuntimeMemoryLine(line));

  }


  function stripActiveMemoryRuntimeMemoryText(text) {

    return splitMemoryTextLines(text)
      .filter(line => !isActiveMemoryRuntimeMemoryLine(line))
      .join("\n");

  }


  function isUserIdleRuntimeMemoryLine(line) {

    if (!line) {
      return false;
    }

    if (typeof line === "object") {
      return isUserIdleRuntimeMemoryKey(line.key);
    }

    const separatorIndex =
        String(line).indexOf(":");

    if (separatorIndex <= 0) {
      return false;
    }

    return isUserIdleRuntimeMemoryKey(
        String(line).slice(0, separatorIndex)
    );

  }


  function stripUserIdleRuntimeMemoryText(text) {

    return splitMemoryTextLines(text)
      .filter(line => !isUserIdleRuntimeMemoryLine(line))
      .join("\n");

  }


  function parseRuntimeMemoryLine(line) {

    const separatorIndex =
      line.indexOf(":");

    if (separatorIndex <= 0) {
      return {
        key: "session memory",
        value: line,
        status: "same",
        key_status: "same",
        value_status: "same",
        key_change_ratio: 0,
        value_change_ratio: 0,
      };
    }

    return {
      key: line.slice(0, separatorIndex).trim(),
      value: line.slice(separatorIndex + 1).trim(),
      status: "same",
      key_status: "same",
      value_status: "same",
      key_change_ratio: 0,
      value_change_ratio: 0,
    };

  }


  function getUserIdleRuntimeMemoryLine(snapshot) {

    if (
        snapshot
        && Array.isArray(snapshot.lines)
    ) {
      return snapshot.lines.find(
          line => isUserIdleRuntimeMemoryLine(line)
      ) || null;
    }

    const rawLine =
        splitMemoryTextLines(
            snapshot && snapshot.raw_memory
        ).find(
            line => isUserIdleRuntimeMemoryLine(line)
        );

    return rawLine ? parseRuntimeMemoryLine(rawLine) : null;

  }


  function setRuntimeMemorySnapshotUserIdle(
    snapshot,
    userIdleText
  ) {

    if (!snapshot || typeof snapshot !== "object") {
      return;
    }

    const value =
        String(userIdleText || "").trim();

    if (!value) {
      return;
    }

    const rawLine =
        `user_idle: ${value}`;

    const rawMemory =
        String(snapshot.raw_memory || "");

    if (rawMemory.trim()) {
      const userIdleLinePattern =
          /^(\s*user_idle\s*:).*$/im;

      snapshot.raw_memory =
          userIdleLinePattern.test(rawMemory)
            ? rawMemory.replace(
                userIdleLinePattern,
                rawLine
              )
            : `${rawMemory.trimEnd()}\n${rawLine}`;
    } else {
      snapshot.raw_memory = rawLine;
    }

    if (!Array.isArray(snapshot.lines)) {
      return;
    }

    let replaced = false;

    snapshot.lines = snapshot.lines.map((line) => {
      if (!isUserIdleRuntimeMemoryLine(line)) {
        return line;
      }

      replaced = true;

      return {
        ...line,
        key: "user_idle",
        value,
      };
    });

    if (!replaced) {
      snapshot.lines.push(
        parseRuntimeMemoryLine(rawLine)
      );
    }

  }


  function resetRuntimeMemoryLineFlashState(line) {

    if (!line || typeof line !== "object") {
      return line;
    }

    return {
      ...line,
      status: "same",
      key_status: "same",
      value_status: "same",
      key_change_ratio: 0,
      value_change_ratio: 0,
    };

  }


  function consumeRuntimeMemorySnapshotFlash(snapshot) {

    if (!snapshot || typeof snapshot !== "object") {
      return snapshot;
    }

    if (!Array.isArray(snapshot.lines)) {
      return snapshot;
    }

    snapshot.lines = snapshot.lines.map(
      resetRuntimeMemoryLineFlashState
    );

    return snapshot;

  }


  function removeRuntimeMemoryLineByKey(
    memory,
    key
  ) {

    const normalizedKey =
      String(key || "").trim().toLowerCase();

    return String(memory || "")
      .split(/\r?\n/)
      .map(line => line.trim())
      .filter(Boolean)
      .filter((line) => {
        const lineKey =
          line.split(":", 1)[0].trim().toLowerCase();

        return lineKey !== normalizedKey;
      })
      .join("\n")
      .trim();

  }


  function upsertRuntimeMemoryLine(
    memory,
    key,
    value
  ) {

    const cleanedMemory =
      removeRuntimeMemoryLineByKey(
        memory,
        key
      );

    return (
      cleanedMemory
        ? `${cleanedMemory}\n${key}: ${value}`
        : `${key}: ${value}`
    ).trim();

  }


  function formatRuntimeMemoryStrengthProperties(line) {

    const strength =
        Number(line && line.strength);

    if (!Number.isFinite(strength)) {
      return [];
    }

    return [`trace: ${strength.toFixed(2)}`];

  }


  function formatRuntimeMemoryQuoteCountProperties(line) {

    const totalQuotes =
        Number(line && line.total_quotes_count);

    const messagesQuotes =
        Number(line && line.messages_quote_count);

    if (
        (!Number.isFinite(totalQuotes) || totalQuotes <= 0)
        && (!Number.isFinite(messagesQuotes) || messagesQuotes <= 0)
    ) {
      return [];
    }

    return [
      `total_quotes_count: ${Math.max(0, Math.trunc(totalQuotes || 0))}`,
      `messages_quote_count: ${Math.max(0, Math.trunc(messagesQuotes || 0))}`,
    ];

  }


  // Builds the UI value presentation while keeping raw hover data, e.g. value "Book" with strength 0.5 -> text "Book", raw "Book [trace: 0.50]".
  function buildRuntimeMemoryValuePresentation(line) {

    const value =
        line && line.value || "";

    const displayValue =
        String(value || "").replace(/\\n/g, " ↵ ");

    const parsedValue =
        splitMemoryMeta(value);

    const strengthProperties =
        memoryMetaHasTag(parsedValue, "trace")
          ? []
          : formatRuntimeMemoryStrengthProperties(line);
    const quoteCountProperties =
        [
          "total_quotes_count",
          "messages_quote_count",
        ].some(tag => memoryMetaHasTag(parsedValue, tag))
          ? []
          : formatRuntimeMemoryQuoteCountProperties(line);

    const rawValue =
        appendProperties(
          displayValue,
          [
            ...strengthProperties,
            ...quoteCountProperties,
          ]
        );

    const presentation =
        splitMemoryMeta(rawValue);

    if (
        normalizeRuntimeMemoryKey(line && line.key) === "user_message"
    ) {
      presentation.text =
          formatUserMessageValueForDisplay(
              displayValue
          );
    } else if (
        isJinResponseRuntimeMemoryKey(line && line.key)
    ) {
      presentation.text =
          formatJinResponseValueForDisplay(
              presentation.text
          );
    }

    return presentation;

  }


  // Splits repeated metadata from a quoted user message, e.g. "\"hi\" [repeated: 2]" -> quote + metadata parts.
  function splitUserMessageRepeatedMetadata(value) {

    const raw =
        String(value || "");

    if (!raw.trimStart().startsWith("\"")) {
      return {
        quote: raw,
        metadata: "",
      };
    }

    const match =
        raw.match(/\s*(\[\s*repeated\s*:\s*\d+\s*\])\s*$/i);

    if (!match) {
      return {
        quote: raw,
        metadata: "",
      };
    }

    return {
      quote: raw.slice(0, match.index).trimEnd(),
      metadata: match[1],
    };

  }


  // Parses a JSON-quoted user message for display truncation, e.g. "\"hello\"" -> "hello".
  function parseQuotedUserMessage(value) {

    const trimmed =
        String(value || "").trim();

    if (!trimmed.startsWith("\"")) {
      return null;
    }

    try {
      const parsed =
          JSON.parse(trimmed);

      return typeof parsed === "string"
        ? parsed
        : null;
    } catch (_error) {
      return null;
    }

  }


  // Re-quotes a displayed user message after safe truncation, e.g. "hello" -> "\"hello\"".
  function quoteUserMessageForDisplay(value) {

    return JSON.stringify(
        value
    );

  }


  // Truncates long displayed user messages, e.g. 60 characters -> first 50 characters plus "...".
  function truncateUserMessageQuote(value) {

    const chars =
        Array.from(String(value || ""));

    if (chars.length <= 50) {
      return String(value || "");
    }

    return `${chars.slice(0, 50).join("")}...`;

  }


  // Formats user_message values for compact UI display, e.g. a long quoted message keeps quotes, truncates text, and preserves [repeated: N].
  function formatUserMessageValueForDisplay(value) {

    const parts =
        splitUserMessageRepeatedMetadata(value);

    const parsedQuote =
        parseQuotedUserMessage(
            parts.quote
        );

    const quoteText =
        parsedQuote === null
          ? truncateUserMessageQuote(parts.quote)
          : quoteUserMessageForDisplay(
              truncateUserMessageQuote(parsedQuote)
          );

    return [
      quoteText,
      parts.metadata,
    ].filter(Boolean).join(" ");

  }

  // Checks whether a runtime memory key contains a JIN answer value for compact UI display, e.g. "last_jin_response" -> true.
  function isJinResponseRuntimeMemoryKey(key) {

    return [
      "last_jin_response",
      "latest_jin_response",
      "last_jin_answer",
      "latest_jin_answer",
    ].includes(
        normalizeRuntimeMemoryKey(key)
    );

  }


  // Truncates long displayed JIN answers for the runtime memory panel, e.g. 120 characters -> first 80 characters plus "...".
  function truncateJinResponseForDisplay(value) {

    const chars =
        Array.from(String(value || ""));

    if (chars.length <= 80) {
      return String(value || "");
    }

    return `${chars.slice(0, 80).join("").trimEnd()}...`;

  }


  // Formats JIN response values for compact UI display, e.g. a long last_jin_response is shortened while raw hover data stays full.
  function formatJinResponseValueForDisplay(value) {

    return truncateJinResponseForDisplay(
        value
    );

  }


  // Aggregates deterministic UI-only runtime memory string formatters, e.g. raw keys and values stay intact in data/title while panel text uses readable labels.
  const runtimeMemoryDisplay = {
    stripMemoryMetaForDisplay,
    stripMemoryTextMetaForDisplay,
    normalizeDisplayLabelAcronyms,
    convertKeyToName,
    buildRuntimeMemoryValuePresentation,
    formatUserMessageValueForDisplay,
    isJinResponseRuntimeMemoryKey,
    truncateJinResponseForDisplay,
    formatJinResponseValueForDisplay,
  };


  window.JinRuntime.memoryModel = {
    splitCompoundRuntimeMemoryLine,
    splitMemoryTextLines,
    appendProperties,
    splitMemoryMeta,
    memoryMetaHasTag,
    setMemoryMetaValue,
    setRuntimeMemoryLineMetaValue,
    normalizeDisplayLabelAcronyms,
    convertKeyToName,
    stripMemoryMetaForDisplay,
    stripRuntimeMemoryMeta: stripMemoryMetaForDisplay,
    stripMemoryTextMetaForDisplay,
    normalizeRuntimeMemoryKey,
    isActiveMemoryRuntimeMemoryKey,
    isActiveMemoryRuntimeMemoryLine,
    extractActiveMemoryRuntimeMemoryLines,
    stripActiveMemoryRuntimeMemoryText,
    isUserIdleRuntimeMemoryKey,
    isUserIdleRuntimeMemoryLine,
    stripUserIdleRuntimeMemoryText,
    parseRuntimeMemoryLine,
    getUserIdleRuntimeMemoryLine,
    setRuntimeMemorySnapshotUserIdle,
    resetRuntimeMemoryLineFlashState,
    consumeRuntimeMemorySnapshotFlash,
    removeRuntimeMemoryLineByKey,
    upsertRuntimeMemoryLine,
    formatRuntimeMemoryStrengthProperties,
    buildRuntimeMemoryValuePresentation,
    formatUserMessageValueForDisplay,
    runtimeMemoryDisplay,
    isJinResponseRuntimeMemoryKey,
    truncateJinResponseForDisplay,
    formatJinResponseValueForDisplay,
  };

}());
