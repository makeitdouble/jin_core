(function () {
  "use strict";

  const root =
    window.JinResponseFormatter
    || {};

  const markerPattern =
    /<(JIN_COLOR|JIN_SIZE)\s*>([\s\S]*?)<\/\1\s*>/gi;

  function escapeHtml(text) {

    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");

  }

  function escapeAttribute(text) {

    return escapeHtml(text)
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");

  }

  function normalizeChatJinColorMarker(value) {

    const match =
      String(
        value || ""
      ).trim().match(
        /^#?([0-9a-f]{6}|[0-9a-f]{3})$/i
      );

    if (!match) {
      return "";
    }

    let hex =
      match[1].toLowerCase();

    if (hex.length === 3) {
      hex = hex
        .split("")
        .map((char) => char + char)
        .join("");
    }

    return `#${hex}`;

  }

  function buildChatJinColorMarkerHtml(color) {

    const normalizedColor =
      normalizeChatJinColorMarker(
        color
      );

    if (!normalizedColor) {
      return escapeHtml(
        `<JIN_COLOR> ${color} </JIN_COLOR>`
      );
    }

    return (
      `<span class="jin-chat-runtime-marker jin-chat-jin-color-marker" title="${normalizedColor}">`
      + `<span class="jin-chat-jin-color-swatch" style="--jin-chat-marker-color: ${normalizedColor}"></span>`
      + "<span>JIN_COLOR</span>"
      + "</span>"
    );

  }

  function isEnabled() {

    const runtimeConfig =
      window.jinRuntimeConfig
      || {};

    if (
      Object.prototype.hasOwnProperty.call(
        runtimeConfig,
        "formatResponse"
      )
    ) {
      return runtimeConfig.formatResponse !== false;
    }

    const latestStatus =
      window.jinLatestStatus
      || {};

    if (
      Object.prototype.hasOwnProperty.call(
        latestStatus,
        "format_response"
      )
    ) {
      return latestStatus.format_response !== false;
    }

    return true;

  }

  function normalizeArrowTokens(text) {

    return String(text || "")
      .replace(/\\\(\s*\\+Rightarrow\s*\\\)/g, "\u21D2")
      .replace(/\\\[\s*\\+Rightarrow\s*\\\]/g, "\u21D2")
      .replace(/\$\s*\\+Rightarrow\s*\$/g, "\u21D2")
      .replace(/\\+Rightarrow\b/g, "\u21D2")
      .replace(/\\\(\s*\\+Leftarrow\s*\\\)/g, "\u21D0")
      .replace(/\\\[\s*\\+Leftarrow\s*\\\]/g, "\u21D0")
      .replace(/\$\s*\\+Leftarrow\s*\$/g, "\u21D0")
      .replace(/\\+Leftarrow\b/g, "\u21D0")
      .replace(/\\\(\s*\\+Leftrightarrow\s*\\\)/g, "\u21D4")
      .replace(/\\\[\s*\\+Leftrightarrow\s*\\\]/g, "\u21D4")
      .replace(/\$\s*\\+Leftrightarrow\s*\$/g, "\u21D4")
      .replace(/\\+Leftrightarrow\b/g, "\u21D4")
      .replace(/\\\(\s*\\+rightarrow\s*\\\)/g, "\u2192")
      .replace(/\\\[\s*\\+rightarrow\s*\\\]/g, "\u2192")
      .replace(/\$\s*\\+rightarrow\s*\$/g, "\u2192")
      .replace(/\\+rightarrow\b/g, "\u2192")
      .replace(/\\+to\b/g, "\u2192")
      .replace(/\\\(\s*\\+leftarrow\s*\\\)/g, "\u2190")
      .replace(/\\\[\s*\\+leftarrow\s*\\\]/g, "\u2190")
      .replace(/\$\s*\\+leftarrow\s*\$/g, "\u2190")
      .replace(/\\+leftarrow\b/g, "\u2190")
      .replace(/\\+gets\b/g, "\u2190")
      .replace(/\\\(\s*\\+leftrightarrow\s*\\\)/g, "\u2194")
      .replace(/\\\[\s*\\+leftrightarrow\s*\\\]/g, "\u2194")
      .replace(/\$\s*\\+leftrightarrow\s*\$/g, "\u2194")
      .replace(/\\+leftrightarrow\b/g, "\u2194");

  }

  function renderLinks(escapedText) {

    return escapedText.replace(
      /\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g,
      function (_, label, url) {
        return (
          `<a class="jin-chat-link" href="${escapeAttribute(url)}" target="_blank" rel="noopener noreferrer">`
          + `${label}`
          + "</a>"
        );
      }
    );

  }

  function renderEmphasis(escapedText) {

    return String(escapedText || "")
      .replace(
        /\*\*\*((?:(?!\*\*\*)[^\n])+?)\*\*\*/g,
        "<strong><em>$1</em></strong>"
      )
      .replace(
        /(^|[^\p{L}\p{N}_])___((?:(?!___)[^\n])+?)___(?![\p{L}\p{N}_])/gu,
        "$1<strong><em>$2</em></strong>"
      )
      .replace(
        /\*\*((?:(?!\*\*)[^\n])+?)\*\*/g,
        "<strong>$1</strong>"
      )
      .replace(
        /(^|[^\p{L}\p{N}_])__((?:(?!__)[^\n])+?)__(?![\p{L}\p{N}_])/gu,
        "$1<strong>$2</strong>"
      )
      .replace(
        /(^|[^\*])\*([^*\n]+)\*/g,
        "$1<em>$2</em>"
      )
      .replace(
        /(^|[^\p{L}\p{N}_])_([^_\n]+)_(?![\p{L}\p{N}_])/gu,
        "$1<em>$2</em>"
      );

  }

  function normalizeChatJinSizeMarker(value) {

    const source =
      String(
        value || ""
      ).trim();

    if (!source) {
      return "";
    }

    const numberPattern =
      /^(\d+)(?:px)?$/i;
    const labeledPattern =
      /([wh])\s*:\s*(\d+)(?:px)?/gi;
    const labeled = {};
    const spans = [];
    let match = null;

    while ((match = labeledPattern.exec(source)) !== null) {
      const label =
        match[1].toLowerCase();
      const size =
        Number.parseInt(
          match[2],
          10
        );

      if (
        !Number.isFinite(size)
        || size <= 0
        || labeled[label]
      ) {
        return "";
      }

      labeled[label] = size;
      spans.push([
        match.index,
        labeledPattern.lastIndex,
      ]);
    }

    if (spans.length) {
      let cursor = 0;
      const remainder = [];

      spans.forEach(([start, end]) => {
        remainder.push(
          source.slice(cursor, start)
        );
        cursor = end;
      });

      remainder.push(
        source.slice(cursor)
      );

      if (remainder.join("").trim()) {
        return "";
      }

      const values =
        Object.values(labeled);

      if (values.length === 1) {
        return `${values[0]}px`;
      }

      if (
        labeled.w
        && labeled.h
      ) {
        return labeled.w === labeled.h
          ? `${labeled.w}px`
          : `w:${labeled.w}px h:${labeled.h}px`;
      }

      return "";
    }

    const parts =
      source.split(/\s+/);

    if (
      parts.length < 1
      || parts.length > 2
    ) {
      return "";
    }

    const numbers =
      parts.map((part) => {
        const numberMatch =
          part.match(numberPattern);

        if (!numberMatch) {
          return 0;
        }

        return Number.parseInt(
          numberMatch[1],
          10
        );
      });

    if (
      numbers.some((number) => (
        !Number.isFinite(number)
        || number <= 0
      ))
    ) {
      return "";
    }

    if (numbers.length === 1) {
      return `${numbers[0]}px`;
    }

    return numbers[0] === numbers[1]
      ? `${numbers[0]}px`
      : `w:${numbers[0]}px h:${numbers[1]}px`;

  }

  function buildChatJinSizeMarkerHtml(size) {

    const normalizedSize =
      normalizeChatJinSizeMarker(
        size
      );

    if (!normalizedSize) {
      return escapeHtml(
        `<JIN_SIZE> ${size} </JIN_SIZE>`
      );
    }

    return (
      `<span class="jin-chat-runtime-marker jin-chat-jin-size-marker" title="${escapeAttribute(normalizedSize)}">`
      + "<span>JIN_SIZE</span>"
      + `<span class="jin-chat-jin-size-value">${escapeHtml(normalizedSize)}</span>`
      + "</span>"
    );

  }

  function renderInlinePlain(text) {

    const source =
      normalizeArrowTokens(
        text
      );
    let rendered = "";
    let lastIndex = 0;
    let match = null;

    markerPattern.lastIndex = 0;

    while ((match = markerPattern.exec(source)) !== null) {
      rendered += renderEmphasis(
        renderLinks(
          escapeHtml(
            source.slice(
              lastIndex,
              match.index
            )
          )
        )
      );
      rendered += String(match[1] || "").toUpperCase() === "JIN_COLOR"
        ? buildChatJinColorMarkerHtml(
          match[2]
        )
        : buildChatJinSizeMarkerHtml(
          match[2]
        );
      lastIndex =
        markerPattern.lastIndex;
    }

    rendered += renderEmphasis(
      renderLinks(
        escapeHtml(
          source.slice(
            lastIndex
          )
        )
      )
    );

    return rendered;

  }

  function renderInlineMarkdown(text) {

    return String(text || "")
      .split(/(`[^`\n]*`)/g)
      .map((chunk) => {

        if (
          chunk.length >= 2
          && chunk[0] === "`"
          && chunk[chunk.length - 1] === "`"
        ) {
          return (
            "<code>"
            + escapeHtml(
              chunk.slice(
                1,
                -1
              )
            )
            + "</code>"
          );
        }

        return renderInlinePlain(
          chunk
        );

      })
      .join("");

  }

  function isBlank(line) {

    return !String(line || "").trim();

  }

  function isFenceStart(line) {

    return /^```/.test(
      String(line || "").trim()
    );

  }

  function isHeading(line) {

    return /^(#{1,6})\s+\S/.test(
      String(line || "")
    );

  }

  function isHorizontalRule(line) {

    return /^[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*$/.test(
      String(line || "")
    );

  }

  function getUnorderedListMatch(line) {

    return String(line || "").match(
      /^[ \t]*[-*+]\s+(.+)$/
    );

  }

  function getOrderedListMatch(line) {

    return String(line || "").match(
      /^[ \t]*\d+[.)]\s+(.+)$/
    );

  }

  function getBlockquoteMatch(line) {

    return String(line || "").match(
      /^[ \t]*>\s?(.*)$/
    );

  }

  function splitMarkdownTableRow(line) {

    let source =
      String(line || "").trim();

    if (!source.includes("|")) {
      return null;
    }

    if (source.startsWith("|")) {
      source = source.slice(1);
    }

    if (source.endsWith("|")) {
      source = source.slice(0, -1);
    }

    const cells = [];
    let cell = "";
    let escaped = false;
    let inCode = false;

    for (let index = 0; index < source.length; index += 1) {
      const char = source[index];

      if (escaped) {
        cell += char;
        escaped = false;
        continue;
      }

      if (char === "\\") {
        escaped = true;
        cell += char;
        continue;
      }

      if (char === "`") {
        inCode = !inCode;
        cell += char;
        continue;
      }

      if (char === "|" && !inCode) {
        cells.push(cell.trim());
        cell = "";
        continue;
      }

      cell += char;
    }

    cells.push(cell.trim());
    return cells;

  }

  function getTableStart(lines, startIndex) {

    if (startIndex + 1 >= lines.length) {
      return null;
    }

    const headerCells =
      splitMarkdownTableRow(lines[startIndex]);
    const delimiterCells =
      splitMarkdownTableRow(lines[startIndex + 1]);

    if (
      !headerCells
      || !delimiterCells
      || headerCells.length < 2
      || headerCells.length !== delimiterCells.length
      || delimiterCells.some((cell) => !/^:?-{3,}:?$/.test(cell))
    ) {
      return null;
    }

    return {
      headerCells,
      delimiterCells,
    };

  }

  function getTableAlignmentClass(delimiterCell) {

    const source = String(delimiterCell || "");

    if (source.startsWith(":") && source.endsWith(":")) {
      return "jin-chat-table-align-center";
    }

    if (source.endsWith(":")) {
      return "jin-chat-table-align-right";
    }

    return "";

  }

  function renderTableCells(cells, tag, alignmentClasses) {

    return cells.map((cell, index) => {
      const alignmentClass = alignmentClasses[index];
      const classAttribute = alignmentClass
        ? ` class="${alignmentClass}"`
        : "";

      return (
        `<${tag}${classAttribute}>`
        + renderInlineMarkdown(cell)
        + `</${tag}>`
      );
    }).join("");

  }

  function renderTable(lines, startIndex) {

    const tableStart = getTableStart(lines, startIndex);

    if (!tableStart) {
      return null;
    }

    const columnCount = tableStart.headerCells.length;
    const alignmentClasses =
      tableStart.delimiterCells.map(getTableAlignmentClass);
    const rows = [];
    let index = startIndex + 2;

    while (index < lines.length) {
      if (isBlank(lines[index])) {
        break;
      }

      const cells = splitMarkdownTableRow(lines[index]);

      if (!cells || cells.length !== columnCount) {
        break;
      }

      rows.push(
        "<tr>"
        + renderTableCells(cells, "td", alignmentClasses)
        + "</tr>"
      );
      index += 1;
    }

    return {
      html: (
        '<div class="jin-chat-table-wrap">'
        + '<table class="jin-chat-table">'
        + "<thead><tr>"
        + renderTableCells(tableStart.headerCells, "th", alignmentClasses)
        + "</tr></thead>"
        + `<tbody>${rows.join("")}</tbody>`
        + "</table>"
        + "</div>"
      ),
      nextIndex: index,
    };

  }

  function isBlockStart(line) {

    return (
      isBlank(line)
      || isFenceStart(line)
      || isHeading(line)
      || isHorizontalRule(line)
      || Boolean(getUnorderedListMatch(line))
      || Boolean(getOrderedListMatch(line))
      || Boolean(getBlockquoteMatch(line))
    );

  }

  function renderFence(lines, startIndex) {

    const firstLine =
      String(lines[startIndex] || "").trim();
    const language =
      firstLine.replace(/^```/, "").trim();
    const codeLines = [];
    let index =
      startIndex + 1;

    while (index < lines.length) {
      if (isFenceStart(lines[index])) {
        index += 1;
        break;
      }

      codeLines.push(
        lines[index]
      );
      index += 1;
    }

    const languageClass =
      language
        ? ` class="language-${escapeAttribute(language)}"`
        : "";

    return {
      html: (
        "<pre class=\"jin-chat-code-block\"><code"
        + languageClass
        + ">"
        + escapeHtml(
          codeLines.join("\n")
        )
        + "</code></pre>"
      ),
      nextIndex: index,
    };

  }

  function renderHeading(line) {

    const match =
      String(line || "").match(
        /^(#{1,6})\s+(.+)$/
      );
    const level =
      Math.min(
        match[1].length,
        4
      );

    return (
      `<h${level}>`
      + renderInlineMarkdown(
        match[2].trim()
      )
      + `</h${level}>`
    );

  }

  function renderList(lines, startIndex, ordered) {

    const tag =
      ordered
        ? "ol"
        : "ul";
    const items = [];
    let index =
      startIndex;

    while (index < lines.length) {
      const match =
        ordered
          ? getOrderedListMatch(lines[index])
          : getUnorderedListMatch(lines[index]);

      if (!match) {
        break;
      }

      items.push(
        "<li>"
        + renderInlineMarkdown(
          match[1].trim()
        )
        + "</li>"
      );

      index += 1;
    }

    return {
      html: (
        `<${tag}>`
        + items.join("")
        + `</${tag}>`
      ),
      nextIndex: index,
    };

  }

  function renderBlockquote(lines, startIndex) {

    const parts = [];
    let index =
      startIndex;

    while (index < lines.length) {
      const match =
        getBlockquoteMatch(
          lines[index]
        );

      if (!match) {
        break;
      }

      parts.push(
        match[1]
      );
      index += 1;
    }

    return {
      html: (
        "<blockquote>"
        + parts.map(renderInlineMarkdown).join("<br>")
        + "</blockquote>"
      ),
      nextIndex: index,
    };

  }

  function renderParagraph(lines, startIndex) {

    const parts = [];
    let index =
      startIndex;

    while (index < lines.length) {
      if (
        index !== startIndex
        && (
          isBlockStart(lines[index])
          || getTableStart(lines, index)
        )
      ) {
        break;
      }

      if (isBlank(lines[index])) {
        break;
      }

      parts.push(
        lines[index]
      );
      index += 1;
    }

    return {
      html: (
        "<p>"
        + parts.map(renderInlineMarkdown).join("<br>")
        + "</p>"
      ),
      nextIndex: index,
    };

  }

  function renderMarkdown(text) {

    const lines =
      String(text || "")
        .replace(/\r\n?/g, "\n")
        .split("\n");
    const blocks = [];
    let index = 0;

    while (index < lines.length) {
      if (isBlank(lines[index])) {
        index += 1;
        continue;
      }

      if (isFenceStart(lines[index])) {
        const result =
          renderFence(
            lines,
            index
          );
        blocks.push(
          result.html
        );
        index =
          result.nextIndex;
        continue;
      }

      const tableResult =
        renderTable(
          lines,
          index
        );

      if (tableResult) {
        blocks.push(
          tableResult.html
        );
        index =
          tableResult.nextIndex;
        continue;
      }

      if (isHeading(lines[index])) {
        blocks.push(
          renderHeading(
            lines[index]
          )
        );
        index += 1;
        continue;
      }

      if (isHorizontalRule(lines[index])) {
        blocks.push("<hr>");
        index += 1;
        continue;
      }

      if (getOrderedListMatch(lines[index])) {
        const result =
          renderList(
            lines,
            index,
            true
          );
        blocks.push(
          result.html
        );
        index =
          result.nextIndex;
        continue;
      }

      if (getUnorderedListMatch(lines[index])) {
        const result =
          renderList(
            lines,
            index,
            false
          );
        blocks.push(
          result.html
        );
        index =
          result.nextIndex;
        continue;
      }

      if (getBlockquoteMatch(lines[index])) {
        const result =
          renderBlockquote(
            lines,
            index
          );
        blocks.push(
          result.html
        );
        index =
          result.nextIndex;
        continue;
      }

      const result =
        renderParagraph(
          lines,
          index
        );
      blocks.push(
        result.html
      );
      index =
        result.nextIndex;
    }

    return blocks.join("");

  }

  root.isEnabled =
    isEnabled;
  root.normalizeJinColorMarker =
    normalizeChatJinColorMarker;
  root.buildJinColorMarkerHtml =
    buildChatJinColorMarkerHtml;
  root.normalizeJinSizeMarker =
    normalizeChatJinSizeMarker;
  root.buildJinSizeMarkerHtml =
    buildChatJinSizeMarkerHtml;
  root.normalizeArrowTokens =
    normalizeArrowTokens;
  root.render =
    renderMarkdown;

  window.JinResponseFormatter =
    root;

}());
