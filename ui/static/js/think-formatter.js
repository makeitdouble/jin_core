(function () {
  "use strict";

  const root =
    window.JinThinkFormatter
    || {};

  const INLINE_TOKEN_PATTERN =
    /(`[^`\n]*`|\$\$[^$\n]+\$\$|\$[^$\n]+\$|\\\([^\n]*?\\\)|\\\[[^\n]*?\\\]|\*\*[^*\n]+\*\*|__[^_\n]+__|\*[^*\n]+\*|(?<![\p{L}\p{N}_])_[^_\n]+_(?![\p{L}\p{N}_]))/gu;

  const MATRIX_START_PATTERN =
    /^[ \t]*(?:(?:[A-Za-z](?:_\{?[A-Za-z0-9]+\}?)?)\s*=\s*)?\\begin\{(matrix|pmatrix|bmatrix|Bmatrix|vmatrix|Vmatrix|smallmatrix)\}[ \t]*$/;

  function appendMathContent(
    element,
    latex,
    displayMode,
    absoluteStart,
    decorations
  ) {

    const source =
      String(latex || "");
    const start =
      Number(absoluteStart || 0);
    const end =
      start + source.length;
    const hasDecoration =
      (Array.isArray(decorations) ? decorations : [])
        .some((decoration) => (
          Number(decoration.end) > start
          && Number(decoration.start) < end
        ));
    const katex =
      window.katex;

    if (
      !hasDecoration
      && katex
      && typeof katex.renderToString === "function"
    ) {
      try {
        element.innerHTML = katex.renderToString(
          source,
          {
            displayMode: Boolean(displayMode),
            throwOnError: false,
            strict: "ignore",
            trust: false,
          }
        );
        element.classList.add(
          "is-katex"
        );
        return;
      } catch (_error) {
        // Keep the readable raw formula below if KaTeX rejects it.
      }
    }

    appendDecoratedText(
      element,
      source,
      start,
      decorations
    );

  }

  function getIndentWidth(value) {

    return String(value || "")
      .replace(/\t/g, "    ")
      .length;

  }

  function getLineInfo(line) {

    const source =
      String(line || "");
    const unordered =
      source.match(
        /^([ \t]*)[-*+]\s+(.+)$/
      );

    if (unordered) {
      return {
        type: "unordered",
        indent: getIndentWidth(unordered[1]),
        marker: "•",
        content: unordered[2],
      };
    }

    const ordered =
      source.match(
        /^([ \t]*)(\d+)[.)]\s+(.+)$/
      );

    if (ordered) {
      return {
        type: "ordered",
        indent: getIndentWidth(ordered[1]),
        marker: ordered[2],
        content: ordered[3],
      };
    }

    const leading =
      source.match(/^([ \t]*)(.*)$/);

    return {
      type: "plain",
      indent: getIndentWidth(leading ? leading[1] : ""),
      marker: "",
      content: leading ? leading[2] : source,
    };

  }

  function getBaseListIndent(lines) {

    const indents = [];
    let inFence = false;

    lines.forEach(line => {
      if (isFenceStart(line)) {
        inFence = !inFence;
        return;
      }

      if (inFence) {
        return;
      }

      const info = getLineInfo(line);
      if (info.type === "unordered" || info.type === "ordered") {
        indents.push(info.indent);
      }
    });

    if (!indents.length) {
      return 0;
    }

    return Math.min(...indents);

  }

  function getVisualDepth(indent, baseIndent) {

    const relative =
      Math.max(
        0,
        Number(indent || 0) - Number(baseIndent || 0)
      );

    // Reasoning from local models tends to recurse in 4-space steps. Keep
    // only one quiet visual level: the structure survives, the staircase does not.
    return relative >= 4
      ? 1
      : 0;

  }

  function createDecorationSpan(decoration) {

    const span =
      document.createElement("span");

    span.className =
      String(decoration.className || "");

    if (decoration.title) {
      span.title =
        String(decoration.title);
    }

    if (decoration.ariaLabel) {
      span.setAttribute(
        "aria-label",
        String(decoration.ariaLabel)
      );
    }

    const score =
      Number(decoration.score);

    if (Number.isFinite(score)) {
      span.style.setProperty(
        "--think-match-score",
        String(
          Math.max(
            0,
            Math.min(1, score)
          )
        )
      );
    }

    return span;

  }

  function appendDecoratedText(
    parent,
    text,
    absoluteStart,
    decorations
  ) {

    const source =
      String(text || "");

    if (!source) {
      return;
    }

    const start =
      Number(absoluteStart || 0);
    const end =
      start + source.length;
    const relevant =
      (Array.isArray(decorations) ? decorations : [])
        .filter((decoration) => (
          Number(decoration.end) > start
          && Number(decoration.start) < end
        ))
        .sort((left, right) => (
          Number(left.start) - Number(right.start)
          || Number(left.end) - Number(right.end)
        ));

    if (!relevant.length) {
      parent.appendChild(
        document.createTextNode(source)
      );
      return;
    }

    let cursor = 0;

    relevant.forEach((decoration) => {
      const localStart =
        Math.max(
          cursor,
          Math.max(0, Number(decoration.start) - start)
        );
      const localEnd =
        Math.max(
          localStart,
          Math.min(source.length, Number(decoration.end) - start)
        );

      if (localStart > cursor) {
        parent.appendChild(
          document.createTextNode(
            source.slice(cursor, localStart)
          )
        );
      }

      if (localEnd > localStart) {
        const span =
          createDecorationSpan(decoration);

        span.appendChild(
          document.createTextNode(
            source.slice(localStart, localEnd)
          )
        );
        parent.appendChild(span);
      }

      cursor =
        Math.max(cursor, localEnd);
    });

    if (cursor < source.length) {
      parent.appendChild(
        document.createTextNode(
          source.slice(cursor)
        )
      );
    }

  }

  function appendInline(
    parent,
    text,
    absoluteStart,
    decorations
  ) {

    const source =
      String(text || "");
    let cursor = 0;
    let match = null;

    INLINE_TOKEN_PATTERN.lastIndex = 0;

    while ((match = INLINE_TOKEN_PATTERN.exec(source)) !== null) {
      const token =
        match[0];
      const tokenStart =
        match.index;

      if (tokenStart > cursor) {
        appendDecoratedText(
          parent,
          source.slice(cursor, tokenStart),
          absoluteStart + cursor,
          decorations
        );
      }

      let element = null;
      let inner = token;
      let innerOffset = 0;

      if (token.startsWith("`") && token.endsWith("`")) {
        element =
          document.createElement("code");
        element.className =
          "jin-think-inline-code";
        inner = token.slice(1, -1);
        innerOffset = 1;
      } else if (
        token.startsWith("$")
        && token.endsWith("$")
      ) {
        const delimiterLength =
          token.startsWith("$$")
            ? 2
            : 1;

        element =
          document.createElement("span");
        element.className =
          "jin-think-math";
        inner = token.slice(delimiterLength, -delimiterLength).trim();
        const firstNonSpace =
          token.slice(delimiterLength, -delimiterLength).search(/\S/);
        innerOffset =
          delimiterLength + Math.max(0, firstNonSpace);
      } else if (
        (
          token.startsWith("\\(")
          && token.endsWith("\\)")
        )
        || (
          token.startsWith("\\[")
          && token.endsWith("\\]")
        )
      ) {
        element =
          document.createElement("span");
        element.className =
          "jin-think-math";
        inner = token.slice(2, -2).trim();
        const firstNonSpace =
          token.slice(2, -2).search(/\S/);
        innerOffset =
          2 + Math.max(0, firstNonSpace);
      } else if (
        token.startsWith("**")
        && token.endsWith("**")
      ) {
        element =
          document.createElement("strong");
        element.className =
          "jin-think-strong";
        inner = token.slice(2, -2);
        innerOffset = 2;
      } else if (
        token.startsWith("__")
        && token.endsWith("__")
      ) {
        element =
          document.createElement("strong");
        element.className =
          "jin-think-strong";
        inner = token.slice(2, -2);
        innerOffset = 2;
      } else {
        element =
          document.createElement("em");
        element.className =
          "jin-think-emphasis";
        inner = token.slice(1, -1);
        innerOffset = 1;
      }

      if (element.className === "jin-think-math") {
        appendMathContent(
          element,
          inner,
          (
            token.startsWith("$$")
            || token.startsWith("\\[")
          ),
          absoluteStart + tokenStart + innerOffset,
          decorations
        );
      } else {
        appendDecoratedText(
          element,
          inner,
          absoluteStart + tokenStart + innerOffset,
          decorations
        );
      }
      parent.appendChild(element);

      cursor =
        tokenStart + token.length;
    }

    if (cursor < source.length) {
      appendDecoratedText(
        parent,
        source.slice(cursor),
        absoluteStart + cursor,
        decorations
      );
    }

  }

  function getLeadingLabel(content) {

    const source =
      String(content || "");
    const match =
      source.match(
        /^(\*\*|\*)([^*\n]{1,96}:)\1(?:\s+(.*)|\s*)$/
      );

    if (!match) {
      return null;
    }

    return {
      prefix: match[1],
      label: match[2],
      body: match[3] || "",
      labelStart: match[1].length,
      bodyStart: match[3]
        ? source.indexOf(match[3])
        : source.length,
    };

  }

  function appendLabeledContent(
    parent,
    content,
    absoluteStart,
    decorations
  ) {

    const label =
      getLeadingLabel(content);

    if (!label) {
      appendInline(
        parent,
        content,
        absoluteStart,
        decorations
      );
      return false;
    }

    const labelElement =
      document.createElement("span");

    labelElement.className =
      "jin-think-label";

    appendDecoratedText(
      labelElement,
      label.label,
      absoluteStart + label.labelStart,
      decorations
    );
    parent.appendChild(labelElement);

    if (label.body) {
      parent.appendChild(
        document.createTextNode(" ")
      );
      appendInline(
        parent,
        label.body,
        absoluteStart + label.bodyStart,
        decorations
      );
    }

    return !label.body;

  }

  function createLineElement(classNames) {

    const line =
      document.createElement("div");

    line.className =
      ["jin-think-line", ...classNames]
        .filter(Boolean)
        .join(" ");

    return line;

  }

  function isFenceStart(line) {

    return /^[ \t]*```/.test(
      String(line || "")
    );

  }

  function renderCodeFence(
    fragment,
    lines,
    starts,
    startIndex,
    decorations
  ) {

    const opening =
      String(lines[startIndex] || "");
    const language =
      opening.trim().replace(/^```/, "").trim();
    const codeLines = [];
    let index =
      startIndex + 1;

    while (index < lines.length && !isFenceStart(lines[index])) {
      codeLines.push(lines[index]);
      index += 1;
    }

    const pre =
      document.createElement("pre");
    const code =
      document.createElement("code");

    pre.className =
      "jin-think-code-block";

    if (language) {
      code.dataset.language =
        language;
    }

    const codeText =
      codeLines.join("\n");
    const codeStart =
      startIndex + 1 < starts.length
        ? starts[startIndex + 1]
        : starts[startIndex] + opening.length;

    appendDecoratedText(
      code,
      codeText,
      codeStart,
      decorations
    );
    pre.appendChild(code);
    fragment.appendChild(pre);

    if (index < lines.length) {
      index += 1;
    }

    return index;

  }

  function renderDisplayMath(
    fragment,
    lines,
    starts,
    startIndex,
    decorations
  ) {

    const trimmed =
      String(lines[startIndex] || "").trim();
    const isDollar =
      trimmed === "$$";
    const isBracket =
      trimmed === "\\[";

    if (!isDollar && !isBracket) {
      return null;
    }

    const closing =
      isDollar
        ? "$$"
        : "\\]";
    const mathLines = [];
    let index =
      startIndex + 1;

    while (
      index < lines.length
      && String(lines[index] || "").trim() !== closing
    ) {
      mathLines.push(lines[index].trim());
      index += 1;
    }

    if (index >= lines.length) {
      return null;
    }

    const math =
      createLineElement([
        "jin-think-math-block",
      ]);
    const mathText =
      mathLines.join(" ").trim();
    const mathStart =
      startIndex + 1 < starts.length
        ? starts[startIndex + 1]
          + String(lines[startIndex + 1] || "").search(/\S|$/)
        : starts[startIndex];

    appendMathContent(
      math,
      mathText,
      true,
      mathStart,
      decorations
    );
    fragment.appendChild(math);

    return index + 1;

  }

  function renderMatrixMath(
    fragment,
    lines,
    starts,
    startIndex,
    decorations
  ) {

    const firstLine =
      String(lines[startIndex] || "");
    const match =
      firstLine.match(
        MATRIX_START_PATTERN
      );

    if (!match) {
      return null;
    }

    const closing =
      `\\end{${match[1]}}`;
    const firstNonSpace =
      firstLine.search(/\S|$/);
    const mathLines = [
      firstLine.slice(firstNonSpace),
    ];
    let index =
      startIndex + 1;

    while (
      index < lines.length
      && String(lines[index] || "").trim() !== closing
    ) {
      mathLines.push(
        String(lines[index] || "")
      );
      index += 1;
    }

    if (index >= lines.length) {
      return null;
    }

    mathLines.push(
      String(lines[index] || "").trim()
    );

    const math =
      createLineElement([
        "jin-think-math-block",
        "jin-think-matrix-block",
      ]);

    appendMathContent(
      math,
      mathLines.join("\n"),
      true,
      starts[startIndex] + firstNonSpace,
      decorations
    );
    fragment.appendChild(math);

    let nextIndex =
      index + 1;

    if (
      nextIndex < lines.length
      && ["$$", "\\]"].includes(
        String(lines[nextIndex] || "").trim()
      )
    ) {
      nextIndex += 1;
    }

    return nextIndex;

  }

  function render(
    element,
    text,
    options = {}
  ) {

    if (!element) {
      return false;
    }

    const source =
      String(text || "")
        .replace(/\r\n?/g, "\n");
    const decorations =
      Array.isArray(options.decorations)
        ? options.decorations
        : [];
    const lines =
      source.split("\n");
    const starts = [];
    let offset = 0;

    lines.forEach((line) => {
      starts.push(offset);
      offset += line.length + 1;
    });

    const baseListIndent =
      getBaseListIndent(lines);
    const fragment =
      document.createDocumentFragment();
    let index = 0;
    let previousWasGap = true;
    let sectionIndent = null;

    while (index < lines.length) {
      const rawLine =
        String(lines[index] || "");
      const trimmed =
        rawLine.trim();

      if (!trimmed) {
        if (!previousWasGap && index < lines.length - 1) {
          const gap =
            document.createElement("div");

          gap.className =
            "jin-think-gap";
          gap.setAttribute(
            "aria-hidden",
            "true"
          );
          fragment.appendChild(gap);
          previousWasGap = true;
        }

        index += 1;
        continue;
      }

      if (isFenceStart(rawLine)) {
        index =
          renderCodeFence(
            fragment,
            lines,
            starts,
            index,
            decorations
          );
        previousWasGap = false;
        sectionIndent = null;
        continue;
      }

      const displayMathNext =
        renderDisplayMath(
          fragment,
          lines,
          starts,
          index,
          decorations
        );

      if (displayMathNext !== null) {
        index = displayMathNext;
        previousWasGap = false;
        sectionIndent = null;
        continue;
      }

      const matrixMathNext =
        renderMatrixMath(
          fragment,
          lines,
          starts,
          index,
          decorations
        );

      if (matrixMathNext !== null) {
        index = matrixMathNext;
        previousWasGap = false;
        sectionIndent = null;
        continue;
      }

      if (/^[ \t]*[-*+]\s*$/.test(rawLine)) {
        index += 1;
        continue;
      }

      const info =
        getLineInfo(rawLine);
      const contentOffsetInLine =
        Math.max(
          0,
          rawLine.indexOf(info.content)
        );
      const absoluteContentStart =
        starts[index] + contentOffsetInLine;
      const isSectionChild =
        sectionIndent !== null
        && info.indent > sectionIndent;

      if (
        sectionIndent !== null
        && info.indent <= sectionIndent
      ) {
        sectionIndent = null;
      }

      if (info.type === "unordered" || info.type === "ordered") {
        const depth =
          getVisualDepth(
            info.indent,
            baseListIndent
          );
        const line =
          createLineElement([
            "jin-think-list-item",
            info.type === "ordered"
              ? "is-ordered"
              : "is-unordered",
            depth > 0 || isSectionChild
              ? "is-nested"
              : "",
          ]);
        const marker =
          document.createElement("span");
        const body =
          document.createElement("span");

        marker.className =
          "jin-think-list-marker";
        marker.textContent =
          info.marker;
        marker.setAttribute(
          "aria-hidden",
          "true"
        );
        body.className =
          "jin-think-list-body";

        const labelOnly =
          appendLabeledContent(
            body,
            info.content,
            absoluteContentStart,
            decorations
          );

        if (labelOnly) {
          line.classList.add(
            "is-section-label"
          );
          sectionIndent =
            info.indent;
        }

        line.appendChild(marker);
        line.appendChild(body);
        fragment.appendChild(line);
        previousWasGap = false;
        index += 1;
        continue;
      }

      const heading =
        info.content.match(
          /^(#{1,6})\s+(.+)$/
        );

      if (heading) {
        const line =
          createLineElement([
            "jin-think-heading",
          ]);
        const headingOffset =
          info.content.indexOf(heading[2]);

        appendInline(
          line,
          heading[2],
          absoluteContentStart + headingOffset,
          decorations
        );
        fragment.appendChild(line);
        previousWasGap = false;
        index += 1;
        continue;
      }

      if (/^(?:-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
        const rule =
          document.createElement("div");

        rule.className =
          "jin-think-rule";
        rule.setAttribute(
          "aria-hidden",
          "true"
        );
        fragment.appendChild(rule);
        previousWasGap = false;
        index += 1;
        continue;
      }

      const quote =
        info.content.match(/^>\s?(.*)$/);

      if (quote) {
        const line =
          createLineElement([
            "jin-think-quote",
            isSectionChild
              ? "is-section-child"
              : "",
          ]);
        const quoteOffset =
          info.content.indexOf(quote[1]);

        appendInline(
          line,
          quote[1],
          absoluteContentStart + quoteOffset,
          decorations
        );
        fragment.appendChild(line);
        previousWasGap = false;
        index += 1;
        continue;
      }

      const line =
        createLineElement([
          isSectionChild
            ? "is-section-child"
            : "",
          info.indent > baseListIndent + 3
            ? "has-source-indent"
            : "",
        ]);
      const labelOnly =
        appendLabeledContent(
          line,
          info.content,
          absoluteContentStart,
          decorations
        );

      if (labelOnly) {
        line.classList.add(
          "jin-think-label-line"
        );
        sectionIndent =
          info.indent;
      }

      fragment.appendChild(line);
      previousWasGap = false;
      index += 1;
    }

    element.replaceChildren(fragment);
    element.classList.add(
      "is-structured"
    );
    element.__jinThinkStreamingFormatState =
      null;
    element.__jinThinkRawText =
      source;
    element.__jinThinkTextNode =
      null;

    return true;

  }

  function buildDecorationSignature(decorations) {

    return (Array.isArray(decorations) ? decorations : [])
      .map((decoration) => [
        Number(decoration.start || 0),
        Number(decoration.end || 0),
        String(decoration.className || ""),
        Number(decoration.score || 0),
      ].join(":"))
      .join("|");

  }

  function hasOpenCodeFence(text) {

    let open = false;

    String(text || "")
      .split("\n")
      .forEach((line) => {
        if (isFenceStart(line)) {
          open = !open;
        }
      });

    return open;

  }

  function renderStreaming(
    element,
    text,
    options = {}
  ) {

    if (!element) {
      return false;
    }

    const source =
      String(text || "")
        .replace(/\r\n?/g, "\n");
    const decorations =
      Array.isArray(options.decorations)
        ? options.decorations
        : [];
    const stableEnd =
      source.lastIndexOf("\n") + 1;
    const stableText =
      source.slice(0, stableEnd);
    const tailText =
      source.slice(stableEnd);
    const decorationSignature =
      buildDecorationSignature(
        decorations
      );

    // While a fenced block is open, the unfinished line belongs inside
    // <pre>. These blocks are rare, so favor correct live layout over
    // the cheap-tail optimization until the closing fence arrives.
    if (hasOpenCodeFence(source)) {
      return render(
        element,
        source,
        options
      );
    }

    const previous =
      element.__jinThinkStreamingFormatState;

    if (
      previous
      && previous.stableEnd === stableEnd
      && previous.decorationSignature === decorationSignature
      && previous.tailElement
    ) {
      previous.tailElement.replaceChildren();
      appendDecoratedText(
        previous.tailElement,
        tailText,
        stableEnd,
        decorations
      );
      element.__jinThinkRawText =
        source;
      element.__jinThinkTextNode =
        null;
      return true;
    }

    render(
      element,
      stableText,
      options
    );

    const tail =
      createLineElement([
        "jin-think-live-tail",
      ]);

    appendDecoratedText(
      tail,
      tailText,
      stableEnd,
      decorations
    );
    element.appendChild(tail);
    element.__jinThinkRawText =
      source;
    element.__jinThinkTextNode =
      null;
    element.__jinThinkStreamingFormatState = {
      stableEnd,
      decorationSignature,
      tailElement: tail,
    };

    return true;

  }

  root.render =
    render;

  root.renderStreaming =
    renderStreaming;

  window.JinThinkFormatter =
    root;

}());
