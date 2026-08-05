(function () {
  "use strict";

  window.JinRuntime = window.JinRuntime || {};

  const SVG_NS = "http://www.w3.org/2000/svg";
  const AVATAR_EVENT = "jin:runtime-avatar-snapshot";
  const THINK_RUNTIME_CITATION_HOVER_EVENT = "jin:think-runtime-citation-hover";
  const MEMORY_REFERENCE_HIGHLIGHT_EVENT =
    "jin:memory-reference-highlight";
  const MEMORY_REFERENCE_ALIAS_DATASET_KEY =
    "memoryReferenceAliases";

  const CENTER = 180;
  const INNER_RING_SCALE = 0.90;
  const MIN_RING_RADIUS = 48 * INNER_RING_SCALE;
  const MAX_RING_RADIUS = 160 * INNER_RING_SCALE;
  const INNER_DECORATION_MAX_RADIUS = 151;
  const STATIC_SCAFFOLD_RADII =
    [42, 61, 83, 108, 135, 162]
      .map(radius => radius * INNER_RING_SCALE);
  const STATIC_RADIAL_LINE_INNER_RADIUS = 38 * INNER_RING_SCALE;
  const STATIC_RADIAL_LINE_OUTER_RADIUS = 166 * INNER_RING_SCALE;
  const MEMORY_RING_LAYOUT = Object.freeze({
    delayed: Object.freeze({
      radius: 158,
      strokeWidth: 1.05,
      minArcDegrees: 3.2,
      maxArcDegrees: 8.8,
      arcRatio: 0.42,
      startAngle: -6,
    }),
    active: Object.freeze({
      radius: 169,
      strokeWidth: 1.35,
      minArcDegrees: 3.8,
      maxArcDegrees: 10.8,
      arcRatio: 0.48,
      startAngle: -9,
    }),
  });
  const SNAPSHOT_GLOW_CLEAR_DELAY_MS = 360;
  const CENTER_COLOR_STEP_MS = 120;

  // 0 = no scene recolor, 1 = current full-strength scene recolor.
  const JIN_SCENE_COLOR_INTENSITY = 0.40;

  // Add custom high-priority word groups here. A matching line paints its ring
  // with the supplied color and softly affects rings at neighbouring radii.
  const AGGRESSIVE_PALETTE = [
    [["angry", "aggressive"], "#ff0000"],
  ];

  const KEYWORD_PALETTE = [
    [["jin", "runtime"], "#22d9b5"],
    [["user"], "#9276d8"],
    [["memory"], "#e1a449"],
  ];

  const PENDING_NODE_PALETTE = [
    "#e3b95b",
    "#a58ae8",
    "#70a9dc",
    "#65c99a",
  ];

  const DEFAULT_RING_COLOR = "#28cfc7";
  const DEFAULT_CENTER_COLOR = "#1f4f8f";
  const ACCENT_RING_COLOR = "#5be8df";
  const AMBER_ACCENT = "#e3a64e";
  const ACTIVE_MEMORY_RING_COLOR = "#d7fff9";
  const DELAYED_MEMORY_RING_COLOR = "#7ab8d8";
  const PINNED_DELAYED_MEMORY_RING_COLOR = "#efffff";

  const avatarRoot = document.getElementById("jin-runtime-avatar");
  const factCheckTrigger = document.getElementById("fact-check-trigger");
  const settingsPanel = document.getElementById("settings-panel");
  const normalizeRuntimeCitationIdentity =
    window.JinRuntime.normalizeCitationIdentity;
  const memoryReferenceHelpers =
    window.JinRuntime.memoryReferences || {};
  const containsMemoryReference =
    typeof memoryReferenceHelpers.contains === "function"
      ? memoryReferenceHelpers.contains
      : () => false;
  const normalizeMemoryReferenceAliases =
    typeof memoryReferenceHelpers.normalizeAliases === "function"
      ? memoryReferenceHelpers.normalizeAliases
      : aliases => (Array.isArray(aliases) ? aliases : []);
  const collectMemoryMetadataReferenceAliases =
    typeof memoryReferenceHelpers.collectMetadataAliases === "function"
      ? memoryReferenceHelpers.collectMetadataAliases
      : () => [];

  if (!avatarRoot) {
    return;
  }

  let centerColor = DEFAULT_CENTER_COLOR;
  let centerColorTransitionQueue = [];
  let centerColorTransitionTimer = null;
  const memoryReferenceHighlightState = {
    persistentText: "",
    hoverText: "",
  };

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, Number(value) || 0));
  }

  function setAvatarMemoryReferenceAliases(node, aliases) {
    if (!node) {
      return;
    }

    const normalizedAliases =
      normalizeMemoryReferenceAliases(aliases);

    if (!normalizedAliases.length) {
      delete node.dataset[MEMORY_REFERENCE_ALIAS_DATASET_KEY];
      return;
    }

    node.dataset[MEMORY_REFERENCE_ALIAS_DATASET_KEY] =
      JSON.stringify(normalizedAliases);
  }

  function getAvatarMemoryReferenceAliases(node) {
    if (!node || !node.dataset) {
      return [];
    }

    const raw = node.dataset[MEMORY_REFERENCE_ALIAS_DATASET_KEY];

    if (!raw) {
      return [];
    }

    try {
      return normalizeMemoryReferenceAliases(JSON.parse(raw));
    } catch (error) {
      return [];
    }
  }

  function hashString(value) {
    let hash = 2166136261;

    for (const char of String(value || "")) {
      hash ^= char.codePointAt(0);
      hash = Math.imul(hash, 16777619);
    }

    return hash >>> 0;
  }

  function createRandom(seedValue) {
    let seed = hashString(seedValue) || 1;

    return function random() {
      seed += 0x6D2B79F5;
      let value = seed;
      value = Math.imul(value ^ (value >>> 15), value | 1);
      value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
      return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
    };
  }

  function createSvgElement(name, attributes = {}) {
    const node = document.createElementNS(SVG_NS, name);

    Object.entries(attributes).forEach(([key, value]) => {
      if (value === null || value === undefined) {
        return;
      }

      node.setAttribute(key, String(value));
    });

    return node;
  }

  function appendTitle(node, text) {
    const title = createSvgElement("title");
    title.textContent = String(text || "");
    node.appendChild(title);
  }

  function countOccurrences(text, words) {
    const source = String(text || "").toLowerCase();

    return (Array.isArray(words) ? words : [words])
      .map(word => String(word || "").trim().toLowerCase())
      .filter(Boolean)
      .reduce((count, word) => {
        let cursor = 0;
        let matches = 0;

        while (cursor < source.length) {
          const index = source.indexOf(word, cursor);

          if (index < 0) {
            break;
          }

          matches += 1;
          cursor = index + Math.max(1, word.length);
        }

        return count + matches;
      }, 0);
  }

  function hexToRgb(color) {
    const normalized = String(color || "").replace("#", "").trim();
    const expanded = normalized.length === 3
      ? normalized.split("").map(char => `${char}${char}`).join("")
      : normalized;

    if (!/^[0-9a-f]{6}$/i.test(expanded)) {
      return { r: 40, g: 207, b: 199 };
    }

    return {
      r: parseInt(expanded.slice(0, 2), 16),
      g: parseInt(expanded.slice(2, 4), 16),
      b: parseInt(expanded.slice(4, 6), 16),
    };
  }

  function rgbToHex(rgb) {
    const channel = value => Math.round(clamp(value, 0, 255))
      .toString(16)
      .padStart(2, "0");

    return `#${channel(rgb.r)}${channel(rgb.g)}${channel(rgb.b)}`;
  }

  function normalizeHexColor(color) {
    const normalized =
      String(color || "")
        .trim()
        .replace(/^#/, "");

    if (!/^([0-9a-f]{3}|[0-9a-f]{6})$/i.test(normalized)) {
      return "";
    }

    const expanded = normalized.length === 3
      ? normalized.split("").map(char => `${char}${char}`).join("")
      : normalized;

    return `#${expanded.toLowerCase()}`;
  }

  function mixColors(firstColor, secondColor, amount) {
    const first = hexToRgb(firstColor);
    const second = hexToRgb(secondColor);
    const ratio = clamp(amount, 0, 1);

    return rgbToHex({
      r: first.r + (second.r - first.r) * ratio,
      g: first.g + (second.g - first.g) * ratio,
      b: first.b + (second.b - first.b) * ratio,
    });
  }

  function blendWeightedColors(entries, fallback = DEFAULT_RING_COLOR) {
    const valid = entries.filter(entry => entry && entry.weight > 0);

    if (!valid.length) {
      return fallback;
    }

    const totalWeight = valid.reduce((sum, entry) => sum + entry.weight, 0);
    const blended = valid.reduce((result, entry) => {
      const rgb = hexToRgb(entry.color);
      result.r += rgb.r * entry.weight;
      result.g += rgb.g * entry.weight;
      result.b += rgb.b * entry.weight;
      return result;
    }, { r: 0, g: 0, b: 0 });

    return rgbToHex({
      r: blended.r / totalWeight,
      g: blended.g / totalWeight,
      b: blended.b / totalWeight,
    });
  }

  function normalizePalette(palette) {
    return (Array.isArray(palette) ? palette : [])
      .map((entry) => {
        if (Array.isArray(entry)) {
          return {
            words: Array.isArray(entry[0]) ? entry[0] : [entry[0]],
            color: entry[1],
          };
        }

        return {
          words: Array.isArray(entry && entry.words)
            ? entry.words
            : [entry && entry.words],
          color: entry && entry.color,
        };
      })
      .filter(entry => entry.words.some(Boolean) && entry.color);
  }

  const normalizedAggressivePalette = normalizePalette(AGGRESSIVE_PALETTE);
  const normalizedKeywordPalette = normalizePalette(KEYWORD_PALETTE);

  function parseRawMemory(rawMemory) {
    return String(rawMemory || "")
      .split(/\r?\n/)
      .map(line => line.trim())
      .filter(Boolean)
      .map((line) => {
        const separatorIndex = line.indexOf(":");

        if (separatorIndex <= 0) {
          return {
            key: "runtime_memory",
            value: line,
          };
        }

        return {
          key: line.slice(0, separatorIndex).trim(),
          value: line.slice(separatorIndex + 1).trim(),
        };
      });
  }

  function getSnapshotLines(snapshot) {
    const sourceLines = snapshot && Array.isArray(snapshot.lines)
      ? snapshot.lines
      : parseRawMemory(snapshot && snapshot.raw_memory);

    return sourceLines
      .map((line, index) => {
        const key = String(line && line.key || `memory_${index + 1}`).trim();
        const value = String(line && line.value || "").trim();
        const text = `${key}: ${value}`.trim();

        return {
          key,
          value,
          text,
          referenceAliases:
            normalizeMemoryReferenceAliases([
              key,
              line && line.id,
              line && line.active_memory_id,
              ...collectMemoryMetadataReferenceAliases(value),
            ]),
          length: Array.from(text).length,
          changeRatio: Math.max(
            Number(line && line.key_change_ratio || 0),
            Number(line && line.value_change_ratio || 0)
          ),
        };
      })
      .filter(line => line.text);
  }

  function getSnapshotDiff(snapshot, lines) {
    const directDiff = Number(snapshot && snapshot.total_diff);

    if (Number.isFinite(directDiff)) {
      return clamp(directDiff, 0, 100);
    }

    if (!lines.length) {
      return 0;
    }

    const averageRatio = lines.reduce(
      (sum, line) => sum + clamp(line.changeRatio, 0, 1),
      0
    ) / lines.length;

    return clamp(averageRatio * 100, 0, 100);
  }

  function getPaletteColor(text, fallback) {
    const weighted = [{ color: fallback, weight: 1.75 }];

    normalizedKeywordPalette.forEach((entry) => {
      const count = countOccurrences(text, entry.words);

      if (count) {
        weighted.push({
          color: entry.color,
          weight: count * 1.35,
        });
      }
    });

    return blendWeightedColors(weighted, fallback);
  }

  function getAggressiveMatch(text) {
    let bestMatch = null;

    normalizedAggressivePalette.forEach((entry) => {
      const count = countOccurrences(text, entry.words);

      if (!count) {
        return;
      }

      if (!bestMatch || count > bestMatch.count) {
        bestMatch = {
          color: entry.color,
          count,
        };
      }
    });

    return bestMatch;
  }

  function computeRingRecords(lines, snapshotSeed) {
    const lengths = lines.map(line => line.length);
    const minLength = Math.min(...lengths);
    const maxLength = Math.max(...lengths);
    const averageLength = lengths.reduce((sum, value) => sum + value, 0) / lengths.length;
    const variance = lengths.reduce(
      (sum, value) => sum + Math.pow(value - averageLength, 2),
      0
    ) / lengths.length;
    const deviation = Math.sqrt(variance);
    const lengthRange = Math.max(1, maxLength - minLength);

    const records = lines.map((line, index) => {
      const random = createRandom(`${snapshotSeed}:${line.key}:${line.value}:${index}`);
      const normalizedLength = (line.length - minLength) / lengthRange;
      const radius = MIN_RING_RADIUS
        + normalizedLength * (MAX_RING_RADIUS - MIN_RING_RADIUS)
        + (random() - 0.5) * 2.6;

      return {
        ...line,
        index,
        random,
        radius: clamp(radius, MIN_RING_RADIUS, MAX_RING_RADIUS),
        isLong: line.length >= averageLength + Math.max(7, deviation * 0.62)
          || (line.length === maxLength && lines.length > 1),
        aggressive: getAggressiveMatch(line.text),
      };
    });

    records.sort((first, second) => first.radius - second.radius);

    records.forEach((record, index) => {
      if (index === 0) {
        return;
      }

      const previous = records[index - 1];
      const minimumRadius = previous.radius + Math.max(1.7, 4.4 - records.length * 0.08);

      if (record.radius < minimumRadius) {
        record.radius = Math.min(MAX_RING_RADIUS, minimumRadius);
      }
    });

    return records;
  }

  function computeOverallColor(lines, records) {
    const completeText = lines.map(line => line.text).join("\n");
    let color = getPaletteColor(completeText, DEFAULT_RING_COLOR);

    const aggressiveCount = records.reduce(
      (sum, record) => sum + Number(record.aggressive && record.aggressive.count || 0),
      0
    );

    if (aggressiveCount >= 2) {
      const aggressiveColor = records.find(record => record.aggressive).aggressive.color;
      color = mixColors(color, aggressiveColor, Math.min(0.46, aggressiveCount * 0.08));
    }

    return color;
  }

  function getNeighbourAggressiveInfluence(record, records) {
    let strongest = null;

    records.forEach((candidate) => {
      if (!candidate.aggressive || candidate === record) {
        return;
      }

      const distance = Math.abs(candidate.radius - record.radius);
      const strength = clamp(1 - distance / 30, 0, 1) * 0.68;

      if (strength > 0 && (!strongest || strength > strongest.strength)) {
        strongest = {
          color: candidate.aggressive.color,
          strength,
        };
      }
    });

    return strongest;
  }

  function polarPoint(radius, degrees) {
    const radians = (degrees - 90) * Math.PI / 180;

    return {
      x: CENTER + Math.cos(radians) * radius,
      y: CENTER + Math.sin(radians) * radius,
    };
  }

  function describeArcPath(radius, startAngle, endAngle) {
    const start = polarPoint(radius, startAngle);
    const end = polarPoint(radius, endAngle);
    const arcDegrees = Math.abs(endAngle - startAngle);

    return [
      `M ${start.x.toFixed(3)} ${start.y.toFixed(3)}`,
      `A ${radius.toFixed(3)} ${radius.toFixed(3)} 0 ${arcDegrees > 180 ? 1 : 0} 1`,
      `${end.x.toFixed(3)} ${end.y.toFixed(3)}`,
    ].join(" ");
  }

  function getRuntimeApi() {
    return window.JinRuntime && window.JinRuntime.runtime
      ? window.JinRuntime.runtime
      : null;
  }

  function getActiveMemoryAvatarRecords() {
    const runtime = getRuntimeApi();
    const records =
      runtime && typeof runtime.getActiveMemoryRecords === "function"
        ? runtime.getActiveMemoryRecords()
        : [];

    return (Array.isArray(records) ? records : [])
      .map((record, index) => {
        const text = String(record || "").trim();

        if (!text) {
          return null;
        }

        const parsed = parseRawMemory(text)[0] || {
          key: `active_memory_${index + 1}`,
          value: text,
        };
        const key =
          String(parsed.key || `active_memory_${index + 1}`).trim();
        const value =
          String(parsed.value || text).trim();
        const lineText =
          `${key}: ${value}`.trim();

        if (!lineText) {
          return null;
        }

        return {
          index,
          key,
          value,
          text: lineText,
          referenceAliases:
            normalizeMemoryReferenceAliases([
              key,
              ...collectMemoryMetadataReferenceAliases(value),
            ]),
          citationText:
            normalizeRuntimeCitationIdentity(lineText),
        };
      })
      .filter(record => record && record.citationText);
  }

  function getDelayedMemoryAvatarRecords() {
    const runtime = getRuntimeApi();
    const reports =
      runtime && typeof runtime.getDelayedMemoryReports === "function"
        ? runtime.getDelayedMemoryReports()
        : {};

    if (
      !reports
      || typeof reports !== "object"
      || Array.isArray(reports)
    ) {
      return [];
    }

    return Object.entries(reports)
      .map(([key, report]) => {
        if (
          !report
          || typeof report !== "object"
          || Array.isArray(report)
        ) {
          return null;
        }

        const id =
          String(key || "").trim().toLowerCase();
        const title =
          String(report.title || "").trim();
        const summary =
          String(report.summary || "").trim();

        if (!id || !title) {
          return null;
        }

        return {
          id,
          title,
          summary,
          pinned: Boolean(report.pinned),
          referenceAliases:
            normalizeMemoryReferenceAliases([
              id,
              report.id,
            ]),
        };
      })
      .filter(Boolean)
      .sort((left, right) => {
        return String(left.id || "").localeCompare(
          String(right.id || "")
        );
      });
  }

  function appendMemoryDashSegment(parent, layout, options) {
    const arcDegrees =
      clamp(
        options.arcDegrees,
        layout.minArcDegrees,
        layout.maxArcDegrees
      );
    const startAngle = options.angle - arcDegrees / 2;
    const endAngle = options.angle + arcDegrees / 2;
    const color = options.color;
    const glowColor = options.glowColor || color;
    const classNames = [
      "jin-avatar-memory-dash",
      `jin-avatar-memory-dash-${options.kind}`,
    ];

    if (options.pinned) {
      classNames.push("is-memory-pinned");
    }

    const dashGroup = createSvgElement("g", {
      class: classNames.join(" "),
      "data-runtime-line-key": options.citationKey || null,
      "data-runtime-line-text": options.citationText || null,
      "data-delayed-memory-id": options.delayedMemoryId || null,
    });

    setAvatarMemoryReferenceAliases(
      dashGroup,
      options.referenceAliases
    );

    setMemoryDashGlowVariables(
      dashGroup,
      glowColor,
      layout.strokeWidth + 0.75
    );

    appendTitle(
      dashGroup,
      options.title
    );

    dashGroup.appendChild(createSvgElement("path", {
      d: describeArcPath(layout.radius, startAngle, endAngle),
      fill: "none",
      stroke: color,
      "stroke-width": layout.strokeWidth,
      "stroke-opacity": options.opacity,
      "stroke-linecap": "round",
    }));

    parent.appendChild(dashGroup);
  }

  function setMemoryDashGlowVariables(dashGroup, glowColor, hoverWidth) {
    const glowRgb = hexToRgb(glowColor);

    dashGroup.style.setProperty(
      "--jin-avatar-memory-glow-near",
      `rgba(${glowRgb.r},${glowRgb.g},${glowRgb.b},0.92)`
    );
    dashGroup.style.setProperty(
      "--jin-avatar-memory-glow-mid",
      `rgba(${glowRgb.r},${glowRgb.g},${glowRgb.b},0.54)`
    );
    dashGroup.style.setProperty(
      "--jin-avatar-memory-glow-far",
      `rgba(${glowRgb.r},${glowRgb.g},${glowRgb.b},0.24)`
    );
    dashGroup.style.setProperty(
      "--jin-avatar-memory-hover-width",
      `${Number(hoverWidth || 2).toFixed(2)}px`
    );
  }

  function getMemoryRingAnimation(records, kind) {
    const seedText = records
      .map(record => (
        kind === "active"
          ? record.text
          : record.id
      ))
      .join("|");
    const random =
      createRandom(`memory-ring:${kind}:${seedText}`);
    const baseDuration =
      kind === "active"
        ? 38
        : 54;
    const durationSpread =
      kind === "active"
        ? 72
        : 112;

    return {
      duration: baseDuration + random() * durationSpread,
      direction: random() > 0.5 ? "normal" : "reverse",
    };
  }

  function appendMemorySignalRing(svg, records, layout, kind, overallColor) {
    if (!records.length) {
      return;
    }

    const animation =
      getMemoryRingAnimation(records, kind);
    const ring = createSvgElement("g", {
      class: [
        "jin-avatar-memory-ring",
        `jin-avatar-memory-ring-${kind}`,
        "jin-avatar-orbit",
      ].join(" "),
      fill: "none",
      "pointer-events": "none",
      style: [
        `--jin-avatar-duration:${animation.duration.toFixed(2)}s`,
        `--jin-avatar-direction:${animation.direction}`,
        "--jin-avatar-play-state:running",
      ].join(";"),
    });
    const slotDegrees = 360 / records.length;
    const arcDegrees =
      clamp(
        slotDegrees * layout.arcRatio,
        layout.minArcDegrees,
        layout.maxArcDegrees
      );

    records.forEach((record, index) => {
      const angle = layout.startAngle + slotDegrees * index;

      if (kind === "active") {
        const color =
          mixColors(
            ACTIVE_MEMORY_RING_COLOR,
            overallColor,
            0.18
          );

        appendMemoryDashSegment(
          ring,
          layout,
          {
            kind,
            angle,
            arcDegrees,
            color,
            glowColor: ACTIVE_MEMORY_RING_COLOR,
            opacity: 0.76,
            citationKey:
              normalizeRuntimeCitationIdentity(record.key),
            citationText: record.citationText,
            referenceAliases: record.referenceAliases,
            title: `Active memory ${index + 1}: ${record.value || record.text}`,
          }
        );
        return;
      }

      const pinned = Boolean(record.pinned);
      const color = pinned
        ? PINNED_DELAYED_MEMORY_RING_COLOR
        : mixColors(DELAYED_MEMORY_RING_COLOR, overallColor, 0.12);

      appendMemoryDashSegment(
        ring,
        layout,
        {
          kind,
          angle,
          arcDegrees,
          color,
          glowColor: pinned
            ? PINNED_DELAYED_MEMORY_RING_COLOR
            : color,
          opacity: pinned ? 0.82 : 0.36,
          pinned,
          citationKey:
            normalizeRuntimeCitationIdentity(record.id),
          delayedMemoryId: record.id,
          referenceAliases: record.referenceAliases,
          title: `${record.title}${record.summary ? `: ${record.summary}` : ""}`,
        }
      );
    });

    svg.appendChild(ring);
  }

  function setDelayedMemoryDashPinned(reportId, pinned) {
    const delayedMemoryId =
      String(reportId || "").trim().toLowerCase();

    if (!/^[a-z0-9]{6}$/.test(delayedMemoryId)) {
      return false;
    }

    const dashGroup =
      avatarRoot.querySelector(
        `.jin-avatar-memory-dash-delayed[data-delayed-memory-id="${delayedMemoryId}"]`
      );

    if (!dashGroup) {
      return false;
    }

    const path =
      dashGroup.querySelector("path");
    const overallColor =
      avatarRoot.style.getPropertyValue("--jin-avatar-overall-color").trim()
      || DEFAULT_RING_COLOR;
    const nextPinned =
      Boolean(pinned);
    const nextColor =
      nextPinned
        ? PINNED_DELAYED_MEMORY_RING_COLOR
        : mixColors(DELAYED_MEMORY_RING_COLOR, overallColor, 0.12);

    dashGroup.classList.toggle(
      "is-memory-pinned",
      nextPinned
    );
    setMemoryDashGlowVariables(
      dashGroup,
      nextPinned
        ? PINNED_DELAYED_MEMORY_RING_COLOR
        : nextColor,
      MEMORY_RING_LAYOUT.delayed.strokeWidth + 0.75
    );

    if (path) {
      path.setAttribute(
        "stroke",
        nextColor
      );
      path.setAttribute(
        "stroke-opacity",
        nextPinned ? "0.82" : "0.36"
      );
    }

    return true;
  }

  function appendMemorySignalRings(
    svg,
    activeMemoryRecords,
    delayedMemoryRecords,
    overallColor
  ) {
    appendMemorySignalRing(
      svg,
      delayedMemoryRecords,
      MEMORY_RING_LAYOUT.delayed,
      "delayed",
      overallColor
    );
    appendMemorySignalRing(
      svg,
      activeMemoryRecords,
      MEMORY_RING_LAYOUT.active,
      "active",
      overallColor
    );
  }

  function appendDefs(svg, overallColor, currentCenterColor) {
    const defs = createSvgElement("defs");

    const softGlow = createSvgElement("filter", {
      id: "jin-avatar-soft-glow",
      x: "-80%",
      y: "-80%",
      width: "260%",
      height: "260%",
    });
    softGlow.appendChild(createSvgElement("feGaussianBlur", {
      stdDeviation: "2.8",
      result: "blur",
    }));
    const softMerge = createSvgElement("feMerge");
    softMerge.appendChild(createSvgElement("feMergeNode", { in: "blur" }));
    softMerge.appendChild(createSvgElement("feMergeNode", { in: "SourceGraphic" }));
    softGlow.appendChild(softMerge);
    defs.appendChild(softGlow);

    const strongGlow = createSvgElement("filter", {
      id: "jin-avatar-strong-glow",
      x: "-120%",
      y: "-120%",
      width: "340%",
      height: "340%",
    });
    strongGlow.appendChild(createSvgElement("feGaussianBlur", {
      stdDeviation: "7.5",
      result: "blur",
    }));
    const strongMerge = createSvgElement("feMerge");
    strongMerge.appendChild(createSvgElement("feMergeNode", { in: "blur" }));
    strongMerge.appendChild(createSvgElement("feMergeNode", { in: "SourceGraphic" }));
    strongGlow.appendChild(strongMerge);
    defs.appendChild(strongGlow);

    const halo = createSvgElement("radialGradient", {
      id: "jin-avatar-halo",
      cx: "50%",
      cy: "50%",
      r: "50%",
    });
    halo.appendChild(createSvgElement("stop", {
      offset: "0%",
      "stop-color": overallColor,
      "stop-opacity": "0.14",
    }));
    halo.appendChild(createSvgElement("stop", {
      offset: "46%",
      "stop-color": overallColor,
      "stop-opacity": "0.035",
    }));
    halo.appendChild(createSvgElement("stop", {
      offset: "100%",
      "stop-color": overallColor,
      "stop-opacity": "0",
    }));
    defs.appendChild(halo);

    const centerGlow = createSvgElement("radialGradient", {
      id: "jin-avatar-center-glow",
      cx: "50%",
      cy: "50%",
      r: "50%",
    });
    centerGlow.appendChild(createSvgElement("stop", {
      class: "jin-avatar-center-glow-stop",
      offset: "0%",
      "stop-color": currentCenterColor,
      "stop-opacity": "0.68",
    }));
    centerGlow.appendChild(createSvgElement("stop", {
      class: "jin-avatar-center-glow-stop",
      offset: "24%",
      "stop-color": currentCenterColor,
      "stop-opacity": "0.32",
    }));
    centerGlow.appendChild(createSvgElement("stop", {
      class: "jin-avatar-center-glow-stop",
      offset: "62%",
      "stop-color": currentCenterColor,
      "stop-opacity": "0.11",
    }));
    centerGlow.appendChild(createSvgElement("stop", {
      class: "jin-avatar-center-glow-stop",
      offset: "100%",
      "stop-color": currentCenterColor,
      "stop-opacity": "0",
    }));
    defs.appendChild(centerGlow);

    svg.appendChild(defs);
  }

  function appendStaticScaffold(svg, overallColor, random) {
    const scaffold = createSvgElement("g", {
      fill: "none",
      "pointer-events": "none",
    });

    scaffold.appendChild(createSvgElement("circle", {
      cx: CENTER,
      cy: CENTER,
      r: 168,
      fill: "url(#jin-avatar-halo)",
    }));

    STATIC_SCAFFOLD_RADII.forEach((radius, index) => {
      scaffold.appendChild(createSvgElement("circle", {
        cx: CENTER,
        cy: CENTER,
        r: radius,
        stroke: index % 2 ? overallColor : ACCENT_RING_COLOR,
        "stroke-width": index % 3 === 0 ? 0.7 : 0.45,
        "stroke-opacity": index % 2 ? 0.10 : 0.065,
        "stroke-dasharray": index % 2 ? "1 5" : "8 11",
      }));
    });

    for (let index = 0; index < 16; index += 1) {
      const angle = index * 22.5 + (random() - 0.5) * 2;
      const inner = polarPoint(STATIC_RADIAL_LINE_INNER_RADIUS, angle);
      const outer = polarPoint(STATIC_RADIAL_LINE_OUTER_RADIUS, angle);

      scaffold.appendChild(createSvgElement("line", {
        x1: inner.x,
        y1: inner.y,
        x2: outer.x,
        y2: outer.y,
        stroke: index % 5 === 0 ? AMBER_ACCENT : overallColor,
        "stroke-width": index % 4 === 0 ? 0.7 : 0.35,
        "stroke-opacity": index % 5 === 0 ? 0.13 : 0.055,
      }));
    }

    svg.appendChild(scaffold);
  }

  function appendArcCircle(group, radius, color, width, opacity, startAngle, arcDegrees) {
    const circumference = 2 * Math.PI * radius;
    const arcLength = circumference * clamp(arcDegrees, 1, 359) / 360;

    group.appendChild(createSvgElement("circle", {
      cx: CENTER,
      cy: CENTER,
      r: radius,
      fill: "none",
      stroke: color,
      "stroke-width": width,
      "stroke-opacity": opacity,
      "stroke-linecap": "round",
      "stroke-dasharray": `${arcLength.toFixed(2)} ${(circumference - arcLength).toFixed(2)}`,
      transform: `rotate(${startAngle} ${CENTER} ${CENTER})`,
    }));
  }

  function appendLongFieldStripes(group, record, color) {
    const random = record.random;
    const stripeCount = Math.round(12 + random() * 24);
    const startAngle = random() * 360;
    const arcSpan = 24 + random() * 48;
    const stripeHeight = 5 + random() * 9;

    for (let index = 0; index < stripeCount; index += 1) {
      const ratio = stripeCount <= 1 ? 0 : index / (stripeCount - 1);
      const angle = startAngle + arcSpan * ratio;
      const innerRadius = record.radius - 1.5;
      const outerRadius = Math.min(
        INNER_DECORATION_MAX_RADIUS,
        record.radius + stripeHeight * (0.55 + random() * 0.45)
      );
      const inner = polarPoint(innerRadius, angle);
      const outer = polarPoint(outerRadius, angle);

      group.appendChild(createSvgElement("line", {
        x1: inner.x,
        y1: inner.y,
        x2: outer.x,
        y2: outer.y,
        stroke: color,
        "stroke-width": 0.75 + random() * 0.8,
        "stroke-opacity": 0.52 + random() * 0.34,
        "stroke-linecap": "round",
      }));
    }
  }

  function appendPendingNodes(group, record) {
    const pendingCount = countOccurrences(record.text, [
      "pending",
      "pending choice",
      "pending_choices",
      "pending value",
      "pending_value",
    ]);

    if (!pendingCount) {
      return;
    }

    const random = record.random;
    const nodeCount = clamp(2 + pendingCount, 2, 6);
    const startAngle = random() * 360;

    for (let index = 0; index < nodeCount; index += 1) {
      const angle = startAngle + index * (15 + random() * 24);
      const nodeRadius =
        clamp(
          record.radius + (random() - 0.5) * 8,
          MIN_RING_RADIUS,
          INNER_DECORATION_MAX_RADIUS - 6
        );
      const point = polarPoint(nodeRadius, angle);
      const color = PENDING_NODE_PALETTE[index % PENDING_NODE_PALETTE.length];

      group.appendChild(createSvgElement("circle", {
        cx: point.x,
        cy: point.y,
        r: 4.2 + random() * 1.6,
        fill: "none",
        stroke: color,
        "stroke-width": 0.55,
        "stroke-opacity": 0.34,
      }));

      group.appendChild(createSvgElement("circle", {
        cx: point.x,
        cy: point.y,
        r: 1.15 + random() * 0.85,
        fill: color,
        "fill-opacity": 0.92,
        filter: "url(#jin-avatar-soft-glow)",
      }));
    }
  }

  function appendOrbit(svg, record, records, overallColor, diffPercent, options = {}) {
    const random = record.random;
    const ownBaseColor = getPaletteColor(record.text, overallColor);
    const neighbourAggressive = getNeighbourAggressiveInfluence(record, records);
    let ringColor = record.aggressive
      ? record.aggressive.color
      : ownBaseColor;

    if (!record.aggressive && neighbourAggressive) {
      ringColor = mixColors(
        ringColor,
        neighbourAggressive.color,
        neighbourAggressive.strength
      );
    }

    const ringRgb = hexToRgb(ringColor);
    const baseSpeed = 11 + random() * 36;
    const effectiveSpeed = baseSpeed * (diffPercent / 100);
    const duration = effectiveSpeed > 0.05 ? 360 / effectiveSpeed : 9999;
    const direction = random() > 0.5 ? "normal" : "reverse";
    const orbitGroup = createSvgElement("g", {
      class: random() > 0.46 ? "jin-avatar-orbit" : "jin-avatar-counter-orbit",
      style: [
        `--jin-avatar-duration:${duration.toFixed(2)}s`,
        `--jin-avatar-direction:${direction}`,
        `--jin-avatar-play-state:${effectiveSpeed > 0.05 ? "running" : "paused"}`,
        `--jin-avatar-cited-glow-near:rgba(${ringRgb.r},${ringRgb.g},${ringRgb.b},0.88)`,
        `--jin-avatar-cited-glow-mid:rgba(${ringRgb.r},${ringRgb.g},${ringRgb.b},0.54)`,
        `--jin-avatar-cited-glow-far:rgba(${ringRgb.r},${ringRgb.g},${ringRgb.b},0.24)`,
      ].join(";"),
    });
    const shouldAnimate = Boolean(options.animate);
    const entryGroup = createSvgElement("g", shouldAnimate ? {
      class: "jin-avatar-orbit-entry",
      style: `--jin-avatar-entry-delay:${Number(options.entryDelay || 0).toFixed(3)}s`,
    } : {
      class: "jin-avatar-orbit-entry",
    });

    orbitGroup.dataset.runtimeLineIndex = String(record.index);
    orbitGroup.dataset.runtimeLineKey =
      normalizeRuntimeCitationIdentity(record.key);
    orbitGroup.dataset.runtimeLineText =
      normalizeRuntimeCitationIdentity(record.text);
    setAvatarMemoryReferenceAliases(
      orbitGroup,
      record.referenceAliases
    );

    appendTitle(
      orbitGroup,
      `${record.key} · ${record.length} chars · ${Math.round(diffPercent)}% diff`
    );

    const strokeWidth = 0.48 + random() * 2.25;
    const circumference = 2 * Math.PI * record.radius;
    const dashLength = 1 + random() * Math.max(2, record.radius * 0.14);
    const gapLength = 2 + random() * Math.max(4, record.radius * 0.18);

    orbitGroup.appendChild(createSvgElement("circle", {
      cx: CENTER,
      cy: CENTER,
      r: record.radius,
      fill: "none",
      stroke: ringColor,
      "stroke-width": Math.max(0.45, strokeWidth * 0.42),
      "stroke-opacity": 0.13 + random() * 0.17,
      "stroke-dasharray": `${dashLength.toFixed(2)} ${gapLength.toFixed(2)}`,
      "stroke-linecap": "round",
    }));

    const arcCount = 1 + Math.floor(random() * 4);

    for (let index = 0; index < arcCount; index += 1) {
      appendArcCircle(
        orbitGroup,
        record.radius + (random() - 0.5) * 1.8,
        index === arcCount - 1 && random() > 0.68
          ? mixColors(ringColor, ACCENT_RING_COLOR, 0.44)
          : ringColor,
        Math.max(0.55, strokeWidth * (0.62 + random() * 0.64)),
        0.44 + random() * 0.42,
        random() * 360,
        12 + random() * 82
      );
    }

    if (record.isLong) {
      appendLongFieldStripes(orbitGroup, record, ringColor);
    }

    appendPendingNodes(orbitGroup, record);

    if (random() > 0.28) {
      const nodeAngle = random() * 360;
      const nodePoint = polarPoint(record.radius, nodeAngle);
      const nodeColor = random() > 0.76 ? AMBER_ACCENT : ringColor;

      orbitGroup.appendChild(createSvgElement("circle", {
        cx: nodePoint.x,
        cy: nodePoint.y,
        r: 4.1 + random() * 2.3,
        fill: "#071014",
        stroke: nodeColor,
        "stroke-width": 0.65 + random() * 0.8,
        "stroke-opacity": 0.7,
      }));

      orbitGroup.appendChild(createSvgElement("circle", {
        cx: nodePoint.x,
        cy: nodePoint.y,
        r: 1.1 + random() * 1.15,
        fill: nodeColor,
        "fill-opacity": 0.95,
        filter: "url(#jin-avatar-soft-glow)",
      }));
    }

    entryGroup.appendChild(orbitGroup);
    svg.appendChild(entryGroup);
  }

  function appendCenter(svg, overallColor, currentCenterColor) {
    const center = createSvgElement("g", {
      "pointer-events": "none",
    });

    [24, 31, 39].forEach((radius, index) => {
      center.appendChild(createSvgElement("circle", {
        cx: CENTER,
        cy: CENTER,
        r: radius,
        fill: "none",
        stroke: index === 1 ? "#f4f7f5" : overallColor,
        "stroke-width": index === 1 ? 0.52 : 0.75,
        "stroke-opacity": index === 1 ? 0.16 : 0.20,
        "stroke-dasharray": index === 2 ? "22 7 4 9" : null,
      }));
    });

    center.appendChild(createSvgElement("circle", {
      class: "jin-avatar-center-glow-fill",
      cx: CENTER,
      cy: CENTER,
      r: 58,
      fill: "url(#jin-avatar-center-glow)",
    }));

    center.appendChild(createSvgElement("circle", {
      class: "jin-avatar-center-soft",
      cx: CENTER,
      cy: CENTER,
      r: 8,
      fill: currentCenterColor,
      "fill-opacity": 0.34,
    }));

    center.appendChild(createSvgElement("circle", {
      class: "jin-avatar-center-core",
      cx: CENTER,
      cy: CENTER,
      r: 4.2,
      fill: mixColors(currentCenterColor, "#ffffff", 0.14),
      "fill-opacity": 0.86,
    }));

    center.appendChild(createSvgElement("circle", {
      class: "jin-avatar-center-point",
      cx: CENTER,
      cy: CENTER,
      r: 2.1,
      fill: currentCenterColor,
      "fill-opacity": 1,
    }));

    svg.appendChild(center);
  }

  let currentRenderedSnapshotIndex = null;
  const activeThinkRuntimeCitationSources = new Map();

  function normalizeThinkRuntimeCitationHoverDetail(detail) {
    if (!detail || detail.active !== true) {
      return null;
    }

    const sourceId =
      String(detail.sourceId || "unknown-think");
    const lineKeys =
      new Set(
        (Array.isArray(detail.lineKeys) ? detail.lineKeys : [])
          .map(normalizeRuntimeCitationIdentity)
          .filter(Boolean)
      );
    const lineTexts =
      new Set(
        (Array.isArray(detail.lineTexts) ? detail.lineTexts : [])
          .map(normalizeRuntimeCitationIdentity)
          .filter(Boolean)
      );

    if (!lineKeys.size && !lineTexts.size) {
      return null;
    }

    return {
      sourceId,
      lineKeys,
      lineTexts,
    };
  }

  function getActiveThinkRuntimeCitationIdentitySets() {
    const lineKeys = new Set();
    const lineTexts = new Set();

    activeThinkRuntimeCitationSources.forEach((state) => {
      state.lineKeys.forEach(key => lineKeys.add(key));
      state.lineTexts.forEach(line => lineTexts.add(line));
    });

    return {
      lineKeys,
      lineTexts,
    };
  }

  function applyThinkRuntimeCitationGlow() {
    const svg = avatarRoot.querySelector("svg");

    if (!svg) {
      return;
    }

    const activeIdentities =
      getActiveThinkRuntimeCitationIdentitySets();

    Array.from(
      svg.querySelectorAll(
        ".jin-avatar-orbit[data-runtime-line-key], .jin-avatar-counter-orbit[data-runtime-line-key], .jin-avatar-memory-dash"
      )
    ).forEach((orbitGroup) => {
      const lineKey =
        normalizeRuntimeCitationIdentity(
          orbitGroup.dataset.runtimeLineKey
        );
      const lineText =
        normalizeRuntimeCitationIdentity(
          orbitGroup.dataset.runtimeLineText
        );
      const cited =
        (lineKey && activeIdentities.lineKeys.has(lineKey))
        || (lineText && activeIdentities.lineTexts.has(lineText));

      orbitGroup.classList.toggle(
        "is-runtime-cited",
        Boolean(cited)
      );
    });
  }

  function getActiveMemoryReferenceText() {
    return (
      memoryReferenceHighlightState.hoverText
      || memoryReferenceHighlightState.persistentText
      || ""
    );
  }

  function applyMemoryReferenceGlow() {
    const svg = avatarRoot.querySelector("svg");

    if (!svg) {
      return;
    }

    const sourceText = getActiveMemoryReferenceText();

    svg.querySelectorAll("[data-memory-reference-aliases]")
      .forEach((recordNode) => {
        const matched = Boolean(
          sourceText
          && getAvatarMemoryReferenceAliases(recordNode)
            .some(alias => containsMemoryReference(sourceText, alias))
        );

        recordNode.classList.toggle(
          "is-memory-reference-hit",
          matched
        );
      });
  }

  function handleMemoryReferenceHighlight(event) {
    const detail = event && event.detail || {};
    const source = detail.source === "hover"
      ? "hover"
      : "persistent";
    const stateKey = source === "hover"
      ? "hoverText"
      : "persistentText";

    memoryReferenceHighlightState[stateKey] =
      detail.active === false
        ? ""
        : String(detail.text || "");

    applyMemoryReferenceGlow();
  }

  function buildRenderSignature(
    snapshot,
    lines,
    activeMemoryRecords = [],
    delayedMemoryRecords = []
  ) {
    return [
      snapshot && snapshot.runtime_memory_id,
      snapshot && snapshot.index,
      snapshot && snapshot.total_diff,
      lines.map(line => [line.key, line.value, line.status, line.key_status, line.value_status].join("␟")).join("␞"),
      activeMemoryRecords.map(record => record.text).join("␞"),
      delayedMemoryRecords.map(record => [record.id, record.title, record.summary, record.pinned].join("␟")).join("␞"),
    ].join("␝");
  }

  let lastRenderSignature = null;
  let avatarRefreshNonce = 0;
  let suppressedMemoryLayer = null;

  function renderAvatar(snapshot, options = {}) {
    const sourceLines = getSnapshotLines(snapshot);
    const lines = sourceLines.length ? sourceLines : [];
    const seed = [
      snapshot && snapshot.runtime_memory_id,
      snapshot && snapshot.index,
      lines.map(line => line.text).join("|"),
      options.seedNonce || avatarRefreshNonce,
    ].join(":");
    const random = createRandom(seed || "jin-avatar");
    const records = lines.length ? computeRingRecords(lines, seed || "jin-avatar") : [];
    const activeMemoryRecords = getActiveMemoryAvatarRecords();
    const delayedMemoryRecords = getDelayedMemoryAvatarRecords();
    const overallColor = lines.length
      ? computeOverallColor(lines, records)
      : DEFAULT_RING_COLOR;
    const diffPercent = lines.length
      ? getSnapshotDiff(snapshot, lines)
      : 0;
    const signature =
      buildRenderSignature(
        snapshot,
        lines,
        activeMemoryRecords,
        delayedMemoryRecords
      ) + `:${options.seedNonce || avatarRefreshNonce}`;
    const shouldAnimate = Boolean(lastRenderSignature) && signature !== lastRenderSignature;

    const svg = createSvgElement("svg", {
      viewBox: "0 0 360 360",
      role: "img",
      "aria-label": "Dynamic JIN runtime avatar",
      preserveAspectRatio: "xMidYMid meet",
    });

    appendDefs(svg, overallColor, centerColor);
    appendStaticScaffold(svg, overallColor, random);

    records.forEach((record, index) => {
      appendOrbit(svg, record, records, overallColor, diffPercent, {
        animate: shouldAnimate,
        entryDelay: Math.min(0.32, index * 0.045),
      });
    });

    appendMemorySignalRings(
      svg,
      activeMemoryRecords,
      delayedMemoryRecords,
      overallColor
    );

    appendCenter(svg, overallColor, centerColor);

    avatarRoot.replaceChildren(svg);
    currentRenderedSnapshotIndex = Number.isInteger(Number(options.snapshotIndex))
      ? Number(options.snapshotIndex)
      : null;
    avatarRoot.dataset.diff = String(Math.round(diffPercent));
    if (currentRenderedSnapshotIndex !== null) {
      avatarRoot.dataset.snapshotIndex = String(currentRenderedSnapshotIndex);
    } else {
      delete avatarRoot.dataset.snapshotIndex;
    }
    avatarRoot.style.setProperty("--jin-avatar-overall-color", overallColor);
    avatarRoot.style.setProperty("--jin-avatar-center-color", centerColor);
    applyThinkRuntimeCitationGlow();
    applyMemoryReferenceGlow();
    lastRenderSignature = signature;
  }

  function applyCenterColor(color) {
    const svg = avatarRoot.querySelector("svg");
    const overallColor =
      avatarRoot.style.getPropertyValue("--jin-avatar-overall-color").trim()
      || DEFAULT_RING_COLOR;

    centerColor = color;
    avatarRoot.style.setProperty("--jin-avatar-center-color", centerColor);

    const sceneColorIntensity = clamp(JIN_SCENE_COLOR_INTENSITY, 0, 1);
    document.documentElement.style.setProperty("--jin-color", centerColor);
    document.documentElement.style.setProperty(
      "--scene-base-color",
      mixColors("#09090b", centerColor, sceneColorIntensity)
    );
    document.documentElement.style.setProperty(
      "--scene-jin-tint-alpha",
      String(0.12 * sceneColorIntensity)
    );

    if (!svg) {
      renderAvatar(getLatestSnapshot(), {
        seedNonce: avatarRefreshNonce,
        snapshotIndex: getLatestSnapshotIndex(),
      });
      return;
    }

    svg.querySelectorAll(".jin-avatar-center-glow-stop")
      .forEach(stop => stop.setAttribute("stop-color", centerColor));

    const soft = svg.querySelector(".jin-avatar-center-soft");
    if (soft) {
      soft.setAttribute(
        "fill",
        centerColor
      );
    }

    const core = svg.querySelector(".jin-avatar-center-core");
    if (core) {
      core.setAttribute(
        "fill",
        mixColors(centerColor, "#ffffff", 0.14)
      );
    }

    const point = svg.querySelector(".jin-avatar-center-point");
    if (point) {
      point.setAttribute("fill", centerColor);
    }
  }

  function processCenterColorQueue() {
    const nextColor = centerColorTransitionQueue.shift();

    if (!nextColor) {
      centerColorTransitionTimer = null;
      return;
    }

    applyCenterColor(nextColor);

    centerColorTransitionTimer =
      setTimeout(processCenterColorQueue, CENTER_COLOR_STEP_MS);
  }

  function setCenterColor(color) {
    const normalizedColor = normalizeHexColor(color);

    if (!normalizedColor) {
      return false;
    }

    if (
      normalizedColor === centerColor
      && centerColorTransitionQueue.length === 0
    ) {
      return true;
    }

    centerColorTransitionQueue.push(normalizedColor);

    if (!centerColorTransitionTimer) {
      processCenterColorQueue();
    }

    return true;
  }

  function reinitializeAvatar() {
    avatarRefreshNonce += 1;
    snapshotRenderSequence += 1;

    if (snapshotRenderTimer) {
      clearTimeout(snapshotRenderTimer);
      snapshotRenderTimer = null;
    }

    memoryLayerSuppressedForSnapshot = false;
    suppressedMemoryLayer = null;
    syncMemoryLayer();
    renderAvatar(getLatestSnapshot(), {
      seedNonce: avatarRefreshNonce,
      snapshotIndex: getLatestSnapshotIndex(),
    });
  }

  function getLatestSnapshot() {
    const runtime = window.JinRuntime && window.JinRuntime.runtime;

    if (!runtime || typeof runtime.getRuntimeMemorySnapshots !== "function") {
      return null;
    }

    const snapshots = runtime.getRuntimeMemorySnapshots();

    return Array.isArray(snapshots) && snapshots.length
      ? snapshots[snapshots.length - 1]
      : null;
  }

  function getLatestSnapshotIndex() {
    const runtime = window.JinRuntime && window.JinRuntime.runtime;

    if (!runtime || typeof runtime.getRuntimeMemorySnapshots !== "function") {
      return null;
    }

    const snapshots = runtime.getRuntimeMemorySnapshots();

    return Array.isArray(snapshots) && snapshots.length
      ? snapshots.length - 1
      : null;
  }

  let memoryLayerSuppressedForSnapshot = false;
  let snapshotRenderTimer = null;
  let snapshotRenderSequence = 0;

  function resolveMemoryLayer() {
    if (!settingsPanel) {
      return null;
    }

    const classes = settingsPanel.classList;

    if (
      classes.contains("memory-l3-updating")
      || classes.contains("memory-l3-pulse")
      || classes.contains("memory-l3-fading")
    ) {
      return "l3";
    }

    if (
      classes.contains("memory-l2-updating")
      || classes.contains("memory-l2-pulse")
      || classes.contains("memory-l2-fading")
    ) {
      return "l2";
    }

    if (
      classes.contains("memory-updating")
      || classes.contains("memory-pulse")
      || classes.contains("memory-fading")
    ) {
      return "l1";
    }

    return null;
  }

  function syncMemoryLayer() {
    const nextLayer = resolveMemoryLayer();

    if (memoryLayerSuppressedForSnapshot) {
      if (!nextLayer) {
        memoryLayerSuppressedForSnapshot = false;
        suppressedMemoryLayer = null;
        delete avatarRoot.dataset.memoryLayer;
        return;
      }

      if (suppressedMemoryLayer && nextLayer !== suppressedMemoryLayer) {
        memoryLayerSuppressedForSnapshot = false;
        suppressedMemoryLayer = null;
        avatarRoot.dataset.memoryLayer = nextLayer;
        return;
      }

      delete avatarRoot.dataset.memoryLayer;
      return;
    }

    if (nextLayer) {
      avatarRoot.dataset.memoryLayer = nextLayer;
      return;
    }

    delete avatarRoot.dataset.memoryLayer;
  }

  function scheduleSnapshotRender(snapshot, snapshotIndex = null) {
    const resolvedSnapshot = snapshot || getLatestSnapshot();
    const activeLayer = resolveMemoryLayer();

    snapshotRenderSequence += 1;
    const sequence = snapshotRenderSequence;

    if (snapshotRenderTimer) {
      clearTimeout(snapshotRenderTimer);
      snapshotRenderTimer = null;
    }

    if (!activeLayer) {
      memoryLayerSuppressedForSnapshot = false;
      suppressedMemoryLayer = null;
      renderAvatar(resolvedSnapshot, {
        snapshotIndex,
      });
      return;
    }

    // Keep request-layer state suppressed while the snapshot swaps, so
    // the panel glow remains the only L1/L2/L3 request accent around updates.
    memoryLayerSuppressedForSnapshot = true;
    suppressedMemoryLayer = activeLayer;
    syncMemoryLayer();

    snapshotRenderTimer = setTimeout(() => {
      snapshotRenderTimer = null;

      if (sequence !== snapshotRenderSequence) {
        return;
      }

      renderAvatar(resolvedSnapshot, {
        snapshotIndex,
      });
      syncMemoryLayer();
    }, SNAPSHOT_GLOW_CLEAR_DELAY_MS);
  }

  window.addEventListener(AVATAR_EVENT, (event) => {
    const detail = event && event.detail;
    const snapshot = detail && detail.snapshot;
    const snapshotIndex = Number.isInteger(Number(detail && detail.index))
      ? Number(detail.index)
      : null;
    scheduleSnapshotRender(snapshot, snapshotIndex);
  });

  window.addEventListener(
    MEMORY_REFERENCE_HIGHLIGHT_EVENT,
    handleMemoryReferenceHighlight
  );

  window.addEventListener(THINK_RUNTIME_CITATION_HOVER_EVENT, (event) => {
    const detail = event && event.detail || {};
    const sourceId =
      String(detail.sourceId || "unknown-think");
    const state =
      normalizeThinkRuntimeCitationHoverDetail(detail);

    if (state) {
      activeThinkRuntimeCitationSources.set(
        sourceId,
        state
      );
    } else {
      activeThinkRuntimeCitationSources.delete(
        sourceId
      );
    }

    applyThinkRuntimeCitationGlow();
  });

  if (settingsPanel && typeof MutationObserver !== "undefined") {
    const observer = new MutationObserver(syncMemoryLayer);
    observer.observe(settingsPanel, {
      attributes: true,
      attributeFilter: ["class"],
    });
  }

  if (factCheckTrigger) {
    factCheckTrigger.addEventListener("mousedown", (event) => {
      event.stopPropagation();
    });

  }

  syncMemoryLayer();
  renderAvatar(getLatestSnapshot(), {
    snapshotIndex: getLatestSnapshotIndex(),
  });
  applyCenterColor(centerColor);

  window.JinRuntime.avatar = {
    render: renderAvatar,
    refresh: reinitializeAvatar,
    setCenterColor,
    setDelayedMemoryPinned: setDelayedMemoryDashPinned,
    get aggressivePalette() {
      return AGGRESSIVE_PALETTE;
    },
    get keywordPalette() {
      return KEYWORD_PALETTE;
    },
  };
}());
