(function () {
  "use strict";

  const root =
    window.JinResponseFormatter
    || {};

  const markerPattern =
    /<(?:INTERNAL_ACTION_)?JIN_COLOR:\s*(#?(?:[0-9a-f]{6}|[0-9a-f]{3}))\s*\/?>/gi;

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
        `<JIN_COLOR: ${color}>`
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

    return escapedText
      .replace(
        /(\*\*|__)([\s\S]+?)\1/g,
        "<strong>$2</strong>"
      )
      .replace(
        /(^|[^\*])\*([^*\n]+)\*/g,
        "$1<em>$2</em>"
      )
      .replace(
        /(^|[^_])_([^_\n]+)_/g,
        "$1<em>$2</em>"
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
      rendered += buildChatJinColorMarkerHtml(
        match[1]
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
        && isBlockStart(lines[index])
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
  root.normalizeArrowTokens =
    normalizeArrowTokens;
  root.render =
    renderMarkdown;

  window.JinResponseFormatter =
    root;

}());
