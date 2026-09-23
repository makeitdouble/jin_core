(function () {
  "use strict";

  const root = window.JinUiUtils || {};
  const MATRIX_START_PATTERN =
    /^[ \t]*(?:(?:[A-Za-z](?:_\{?[A-Za-z0-9]+\}?)?)\s*=\s*)?\\begin\{(matrix|pmatrix|bmatrix|Bmatrix|vmatrix|Vmatrix|smallmatrix)\}[ \t]*$/;

  function escapeHtml(text) {
    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function normalizeJinColor(value) {
    const match = String(value || "")
      .trim()
      .match(/^#?([0-9a-f]{3}|[0-9a-f]{6})$/i);

    if (!match) {
      return "";
    }

    let hex = match[1].toLowerCase();

    if (hex.length === 3) {
      hex = hex
        .split("")
        .map((char) => char + char)
        .join("");
    }

    return `#${hex}`;
  }

  function normalizeActiveMemoryId(value) {
    const normalized = String(value || "").trim();

    return /^AM-[a-z0-9]{6}$/.test(normalized)
      ? normalized
      : "";
  }

  function extractActiveMemoryId(value) {
    const match = String(value || "").match(
      /\[\s*id\s*:\s*(AM-[a-z0-9]{6})\s*\]/
    );

    return match
      ? normalizeActiveMemoryId(match[1])
      : "";
  }

  function isMatrixMathStart(line) {
    return MATRIX_START_PATTERN.test(
      String(line || "")
    );
  }

  function parseMatrixMathBlock(lines, startIndex) {
    const sourceLines = Array.isArray(lines) ? lines : [];
    const firstLine = String(sourceLines[startIndex] || "");
    const match = firstLine.match(MATRIX_START_PATTERN);

    if (!match) {
      return null;
    }

    const closing = `\\end{${match[1]}}`;
    const firstNonSpace = firstLine.search(/\S|$/);
    const mathLines = [
      firstLine.slice(firstNonSpace),
    ];
    let index = startIndex + 1;

    while (
      index < sourceLines.length
      && String(sourceLines[index] || "").trim() !== closing
    ) {
      mathLines.push(String(sourceLines[index] || ""));
      index += 1;
    }

    if (index >= sourceLines.length) {
      return null;
    }

    mathLines.push(
      String(sourceLines[index] || "").trim()
    );

    let nextIndex = index + 1;

    if (
      nextIndex < sourceLines.length
      && ["$$", "\\]"].includes(
        String(sourceLines[nextIndex] || "").trim()
      )
    ) {
      nextIndex += 1;
    }

    return {
      latex: mathLines.join("\n"),
      firstNonSpace,
      nextIndex,
    };
  }

  root.escapeHtml = escapeHtml;
  root.normalizeJinColor = normalizeJinColor;
  root.normalizeActiveMemoryId = normalizeActiveMemoryId;
  root.extractActiveMemoryId = extractActiveMemoryId;
  root.isMatrixMathStart = isMatrixMathStart;
  root.parseMatrixMathBlock = parseMatrixMathBlock;

  window.JinUiUtils = root;
}());
