(function () {

  window.JinRuntime = window.JinRuntime || {};

  function splitMemoryTextLines(text) {

    return String(text || "")
      .replace(/\\n/g, "\n")
      .replace(
        /;\s+(?=[a-z][a-z0-9_]*\s*:)/g,
        "\n"
      )
      .split(/\r?\n+/)
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

    const tagRe =
        /\s*\[\s*([\w.-]+)\s*:\s*([^\]]*)\]\s*$/;

    while (true) {
      const match =
          text.match(tagRe);

      if (!match) {
        break;
      }

      tags.unshift({
        key: match[1],
        value: match[2].trim(),
        raw: match[0].trim(),
      });

      text =
          text.slice(0, match.index).trimEnd();
    }

    return {
      text,
      tags,
      raw,
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


  function stripMemoryMetaForDisplay(value) {

    return splitMemoryMeta(value).text;

  }


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


  function isUserIdleRuntimeMemoryKey(key) {

    return normalizeRuntimeMemoryKey(key) === "user_idle";

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


  function buildRuntimeMemoryValuePresentation(line) {

    const value =
        line && line.value || "";

    const parsedValue =
        splitMemoryMeta(value);

    const strengthProperties =
        memoryMetaHasTag(parsedValue, "trace")
          ? []
          : formatRuntimeMemoryStrengthProperties(line);

    const rawValue =
        appendProperties(
          value,
          strengthProperties
        );

    return splitMemoryMeta(rawValue);

  }


  window.JinRuntime.memoryModel = {
    splitMemoryTextLines,
    appendProperties,
    splitMemoryMeta,
    memoryMetaHasTag,
    stripMemoryMetaForDisplay,
    stripRuntimeMemoryMeta: stripMemoryMetaForDisplay,
    stripMemoryTextMetaForDisplay,
    normalizeRuntimeMemoryKey,
    isUserIdleRuntimeMemoryKey,
    isUserIdleRuntimeMemoryLine,
    stripUserIdleRuntimeMemoryText,
    parseRuntimeMemoryLine,
    getUserIdleRuntimeMemoryLine,
    setRuntimeMemorySnapshotUserIdle,
    removeRuntimeMemoryLineByKey,
    upsertRuntimeMemoryLine,
    formatRuntimeMemoryStrengthProperties,
    buildRuntimeMemoryValuePresentation,
  };

}());
