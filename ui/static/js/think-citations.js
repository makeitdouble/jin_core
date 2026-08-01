(function () {
  "use strict";

  const THINK_RULE_CITATIONS_ENDPOINT =
    "/api/debug/rule-citations";
  const THINK_RULE_WORKER_URL =
    "/static/js/think-rule-worker.js?v=rule-citations-4";
  const THINK_RUNTIME_CITATION_HOVER_EVENT =
    "jin:think-runtime-citation-hover";

  let thinkRuleCitationWorker = null;
  let thinkRuleCitationRegistryPromise = null;
  let nextThinkRuntimeCitationIndex = 0;
  const activeThinkRuleCitationJobs = new Map();

  function isThinkCitationDebugEnabled() {

    return Boolean(
      window.jinStreamDebug
      || window.jinDebugMode
    );

  }

  function updateThinkContentExpandedHeight(element) {

    if (
      typeof window.updateThinkExpandedHeight
        !== "function"
    ) {
      return;
    }

    window.updateThinkExpandedHeight(
      element
    );

  }

  function loadThinkRuleCitationRegistry() {

    if (thinkRuleCitationRegistryPromise) {
      return thinkRuleCitationRegistryPromise;
    }

    thinkRuleCitationRegistryPromise = fetch(
      THINK_RULE_CITATIONS_ENDPOINT,
      {
        cache: "no-store",
      }
    )
      .then((response) => {
        if (!response.ok) {
          throw new Error(
            `Rule citation registry failed: ${response.status}`
          );
        }

        return response.json();
      })
      .catch((error) => {
        if (isThinkCitationDebugEnabled()) {
          console.warn(
            "[think-rules] disabled",
            error
          );
        }

        return {
          enabled: false,
          fragments: [],
        };
      });

    return thinkRuleCitationRegistryPromise;

  }

  function getThinkRuleCitationWorker() {

    if (thinkRuleCitationWorker) {
      return thinkRuleCitationWorker;
    }

    if (!window.Worker) {
      return null;
    }

    thinkRuleCitationWorker =
      new Worker(
        THINK_RULE_WORKER_URL
      );

    thinkRuleCitationWorker.onmessage =
      handleThinkRuleWorkerMessage;

    thinkRuleCitationWorker.onerror = (event) => {
      if (isThinkCitationDebugEnabled()) {
        console.warn(
          "[think-rules] worker error",
          event.message
        );
      }
    };

    return thinkRuleCitationWorker;

  }

  function thinkRuleLevelRank(level) {

    if (level === "exact") {
      return 3;
    }

    if (level === "near") {
      return 2;
    }

    return 1;

  }

  function thinkCitationSourcePriority(match) {

    if (
      match
      && match.sourceType === "rule"
    ) {
      return 2;
    }

    if (
      match
      && match.sourceType === "runtime"
    ) {
      return 1;
    }

    if (
      match
      && match.sourceType === "session"
    ) {
      return 0;
    }

    return -1;

  }

  function resolveThinkRuleOverlaps(matches) {

    const seen = new Set();
    const sorted = [...matches]
      .filter((match) => {
        if (
          !match
          || match.end <= match.start
        ) {
          return false;
        }

        const key = [
          match.start,
          match.end,
          match.level,
          match.constantName,
          match.sourceText,
        ].join("|");

        if (seen.has(key)) {
          return false;
        }

        seen.add(key);
        return true;
      })
      .sort((left, right) => {
        const priorityDelta =
          thinkCitationSourcePriority(
            right
          )
          - thinkCitationSourcePriority(
            left
          );

        if (priorityDelta) {
          return priorityDelta;
        }

        const levelDelta =
          thinkRuleLevelRank(
            right.level
          )
          - thinkRuleLevelRank(
            left.level
          );

        if (levelDelta) {
          return levelDelta;
        }

        if (right.score !== left.score) {
          return right.score - left.score;
        }

        return (
          (right.end - right.start)
          - (left.end - left.start)
        );
      });

    const selected = [];

    sorted.forEach((match) => {
      const overlaps =
        selected.some(
          (selectedMatch) => (
            match.start < selectedMatch.end
            && match.end > selectedMatch.start
          )
        );

      if (!overlaps) {
        selected.push(
          match
        );
      }
    });

    return selected.sort(
      (left, right) => left.start - right.start
    );

  }

  function buildThinkRuleTitle(
    match,
    matchedText
  ) {

    const score =
      Math.round(
        Number(
          match.score || 0
        ) * 100
      );

    const label =
      match.sourceType === "runtime"
        ? "RUNTIME"
        : match.sourceType === "session"
          ? "SESSION"
          : "RULE";

    return [
      `${label} - ${match.constantName || "unknown"} - ${match.level || "match"} - ${score}%`,
      `source: ${match.source || "rules"}`,
      `layer: ${match.layer || "base"}`,
      `matched: "${matchedText}"`,
      `${match.sourceType === "rule" ? "rule" : "memory"}: "${match.titleText || match.sourceText || ""}"`,
    ].join("\n");

  }

  function getThinkCitationClassName(match) {

    const sourceClass =
      match.sourceType === "runtime"
        ? "runtime"
        : match.sourceType === "session"
          ? "session"
          : "rule";

    return [
      "think-rule-hit",
      `think-citation-${sourceClass}`,
      match.level || "near",
    ].join(" ");

  }

  function splitThinkCitationTextFragments(text) {

    const runtimeModel =
      window.JinRuntime
      && window.JinRuntime.memoryModel;

    const lines =
      runtimeModel
      && typeof runtimeModel.splitMemoryTextLines === "function"
        ? runtimeModel.splitMemoryTextLines(
          text
        )
        : String(text || "")
          .replace(/\\n/g, "\n")
          .split(/\r?\n+/)
          .map(line => line.trim())
          .filter(Boolean);

    return lines
      .map((line) => {
        const cleanedLine =
          runtimeModel
          && typeof runtimeModel.stripRuntimeMemoryMeta === "function"
            ? runtimeModel.stripRuntimeMemoryMeta(
              line
            )
            : line;

        return String(cleanedLine || "").trim();
      })
      .filter(Boolean);

  }

  function buildMemoryCitationFragments(
    memoryText,
    options
  ) {

    const {
      source,
      sourceType,
      citationType,
      layer,
      idPrefix,
      defaultConstantName,
      sourceSnapshotIndex = null,
    } = options;

    const fragments = [];
    const seen = new Set();

    splitThinkCitationTextFragments(
      memoryText
    ).forEach((line, index) => {
      const separatorIndex =
        line.indexOf(":");
      const key =
        separatorIndex > 0
          ? line.slice(
            0,
            separatorIndex
          ).trim()
          : defaultConstantName;
      const value =
        separatorIndex > 0
          ? line.slice(
            separatorIndex + 1
          ).trim()
          : line;

      [
        line,
        value,
      ].forEach((sourceText, variantIndex) => {
        const normalized =
          sourceText
            .toLowerCase()
            .replace(/\s+/g, " ")
            .trim();

        if (
          !normalized
          || normalized.length < 24
          || seen.has(
            normalized
          )
        ) {
          return;
        }

        seen.add(
          normalized
        );

        fragments.push(
          {
            id: `${idPrefix}:${index}:${variantIndex}`,
            source,
            sourceType,
            citationType,
            layer,
            constantName: key || defaultConstantName,
            sourceText,
            titleText: line,
            sourceLineIndex: index,
            sourceSnapshotIndex,
            sourceLineKey: key || defaultConstantName,
            sourceLineText: line,
            minScore: 0.72,
          }
        );
      });
    });

    return fragments;

  }

  function getRuntimeCitationSnapshot(
    snapshotIndex
  ) {

    const runtimeApi =
      window.JinRuntime
      && window.JinRuntime.runtime;

    if (
      runtimeApi
      && typeof runtimeApi.getRuntimeMemorySnapshot === "function"
    ) {
      return (
        runtimeApi.getRuntimeMemorySnapshot(
          snapshotIndex
        )
        || null
      );
    }

    const storage =
      window.JinRuntime
      && window.JinRuntime.storage;

    if (
      storage
      && typeof storage.readLatestRuntimeMemory === "function"
    ) {
      const latestRuntime =
        storage.readLatestRuntimeMemory();

      if (
        latestRuntime
        && latestRuntime.runtime_snapshot
      ) {
        return latestRuntime.runtime_snapshot;
      }

      return latestRuntime || null;
    }

    return null;

  }

  function getRuntimeCitationTextFromSnapshot(
    snapshot
  ) {

    return String(
      (
        snapshot
        && (
          snapshot.raw_memory
          || snapshot.runtime_memory
          || (
            snapshot.runtime_snapshot
            && snapshot.runtime_snapshot.raw_memory
          )
        )
      )
      || ""
    ).trim();

  }

  function buildRuntimeCitationFragments(
    snapshotIndex
  ) {

    const snapshot =
      getRuntimeCitationSnapshot(
        snapshotIndex
      );
    const runtimeMemory =
      getRuntimeCitationTextFromSnapshot(
        snapshot
      );

    if (!runtimeMemory) {
      return [];
    }

    return buildMemoryCitationFragments(
      runtimeMemory,
      {
        source: `runtimeSnapshot[${snapshotIndex}]`,
        sourceType: "runtime",
        citationType: "runtime_citation",
        layer: "runtime",
        idPrefix: `runtime:${snapshotIndex}`,
        defaultConstantName: "runtime_memory",
        sourceSnapshotIndex: snapshotIndex,
      }
    );

  }

  function buildSessionCitationFragments() {

    const storage =
      window.JinRuntime
      && window.JinRuntime.storage;

    if (
      !storage
      || typeof storage.readLatestSavedSessionMemory !== "function"
    ) {
      return [];
    }

    const savedSession =
      storage.readLatestSavedSessionMemory();

    if (
      !savedSession
      || savedSession.explicit_save !== true
    ) {
      return [];
    }

    const sessionMemory =
      String(
        savedSession.session_memory || ""
      ).trim();

    if (!sessionMemory) {
      return [];
    }

    return buildMemoryCitationFragments(
      sessionMemory,
      {
        source: "latestSavedSessionMemory",
        sourceType: "session",
        citationType: "session_citation",
        layer: "session",
        idPrefix: "session",
        defaultConstantName: "session_memory",
      }
    );

  }

  function normalizeThinkRuntimeCitationIdentity(value) {

    const source = String(value || "");
    const normalized = source.normalize
      ? source.normalize("NFKC")
      : source;

    return normalized
      .toLowerCase()
      .replace(/\s+/g, " ")
      .trim();

  }

  function buildThinkRuntimeCitationHoverState(matches) {

    const runtimeMatches =
      (Array.isArray(matches) ? matches : [])
        .filter(match => match && match.sourceType === "runtime");

    const lineKeys =
      Array.from(new Set(
        runtimeMatches
          .map(match => normalizeThinkRuntimeCitationIdentity(
            match.sourceLineKey
            || match.constantName
          ))
          .filter(Boolean)
      ));

    const lineTexts =
      Array.from(new Set(
        runtimeMatches
          .map(match => normalizeThinkRuntimeCitationIdentity(
            match.sourceLineText
            || match.titleText
            || match.sourceText
          ))
          .filter(Boolean)
      ));

    if (!lineKeys.length && !lineTexts.length) {
      return null;
    }

    return {
      lineKeys,
      lineTexts,
    };

  }

  function dispatchThinkRuntimeCitationHover(
    thinkContent,
    active
  ) {

    if (!thinkContent) {
      return;
    }

    const state =
      active
        ? thinkContent.__jinRuntimeCitationHoverState
        : null;
    const sourceId =
      String(thinkContent.dataset.thinkId || "unknown-think");

    window.dispatchEvent(
      new CustomEvent(
        THINK_RUNTIME_CITATION_HOVER_EVENT,
        {
          detail: state
            ? {
              active: true,
              sourceId,
              lineKeys: [...state.lineKeys],
              lineTexts: [...state.lineTexts],
            }
            : {
              active: false,
              sourceId,
              lineKeys: [],
              lineTexts: [],
            },
        }
      )
    );

  }

  function shouldRevealThinkRuntimeCitations(thinkContent) {

    if (
      !thinkContent
      || !thinkContent.__jinRuntimeCitationHoverState
    ) {
      return false;
    }

    const hovered =
      typeof thinkContent.matches === "function"
      && thinkContent.matches(":hover");
    const autoRevealing =
      thinkContent.classList.contains(
        "is-rule-highlight-revealing"
      );

    return hovered || autoRevealing;

  }

  function syncThinkRuntimeCitationHighlight(thinkContent) {

    dispatchThinkRuntimeCitationHover(
      thinkContent,
      shouldRevealThinkRuntimeCitations(
        thinkContent
      )
    );

  }

  function renderThinkRuleHighlights(job) {

    const element =
      job.element;

    if (
      !element
      || element.dataset.thinkId !== job.thinkId
    ) {
      return;
    }

    const text =
      job.text;
    const matches =
      resolveThinkRuleOverlaps(
        job.matches
      );

    if (!matches.length) {
      return false;
    }

    const fragment =
      document.createDocumentFragment();
    let cursor = 0;

    matches.forEach((match) => {
      const start = Math.max(
        0,
        Math.min(
          text.length,
          match.start
        )
      );
      const end = Math.max(
        start,
        Math.min(
          text.length,
          match.end
        )
      );

      if (start > cursor) {
        fragment.appendChild(
          document.createTextNode(
            text.slice(
              cursor,
              start
            )
          )
        );
      }

      const matchedText =
        text.slice(
          start,
          end
        );
      const span =
        document.createElement("span");

      span.className =
        getThinkCitationClassName(
          match
        );
      span.textContent =
        matchedText;
      span.title =
        buildThinkRuleTitle(
          match,
          matchedText
        );
      span.setAttribute(
        "aria-label",
        span.title
      );
      span.style.setProperty(
        "--think-match-score",
        String(
          Math.max(
            0,
            Math.min(
              1,
              Number(
                match.score || 0
              )
            )
          )
        )
      );

      fragment.appendChild(
        span
      );

      cursor = end;
    });

    if (cursor < text.length) {
      fragment.appendChild(
        document.createTextNode(
          text.slice(
            cursor
          )
        )
      );
    }

    element.replaceChildren(
      fragment
    );
    element.classList.add(
      "has-rule-highlights"
    );
    element.__jinThinkTextNode = null;

    updateThinkContentExpandedHeight(
      element
    );

    job.matches =
      matches;

    element.__jinRuntimeCitationHoverState =
      buildThinkRuntimeCitationHoverState(
        matches
      );

    syncThinkRuntimeCitationHighlight(
      element
    );

    return true;

  }

  function pulseThinkRuleHighlights(job) {

    const element =
      job.element;

    if (
      !element
      || element.dataset.thinkId !== job.thinkId
    ) {
      return;
    }

    if (element.__jinThinkRulePulseTimer) {
      clearTimeout(
        element.__jinThinkRulePulseTimer
      );
    }

    element.classList.remove(
      "is-rule-highlight-revealing"
    );

    void element.offsetWidth;

    element.classList.add(
      "is-rule-highlight-revealing"
    );

    syncThinkRuntimeCitationHighlight(
      element
    );

    element.__jinThinkRulePulseTimer = setTimeout(
      () => {
        element.classList.remove(
          "is-rule-highlight-revealing"
        );
        element.__jinThinkRulePulseTimer = null;

        syncThinkRuntimeCitationHighlight(
          element
        );
      },
        5000
      );

  }

  function handleThinkRuleWorkerMessage(event) {

    const data =
      event.data
      || {};
    const thinkId =
      data.thinkId;
    const job =
      activeThinkRuleCitationJobs.get(
        thinkId
      );

    if (
      !job
      || !job.element
      || job.element.dataset.thinkId !== thinkId
    ) {
      return;
    }

    if (
      data.type === "ruleMatchesChunk"
    ) {
      job.matches = resolveThinkRuleOverlaps(
        [
          ...job.matches,
          ...(data.matches || []),
        ]
      );
      return;
    }

    if (
      data.type === "ruleMatchesDone"
    ) {
      job.done = true;
      if (
        renderThinkRuleHighlights(
          job
        )
      ) {
        requestAnimationFrame(
          () => pulseThinkRuleHighlights(
            job
          )
        );
      }
      activeThinkRuleCitationJobs.delete(
        thinkId
      );
    }

  }

  function startThinkRuleCitationAnalysis(
    messageId,
    stream
  ) {

    if (
      !stream
      || !stream.group
      || !stream.group.createdThinking
      || !stream.group.thinkContent
      || !stream.thinking.trim()
    ) {
      return;
    }

    const thinkContent =
      stream.group.thinkContent;
    const thinkId =
      String(
        messageId
      );
    const text =
      stream.thinking;
    const runtimeCitationIndex =
      Number.isInteger(
        stream.runtimeCitationIndex
      )
        ? stream.runtimeCitationIndex
        : nextThinkRuntimeCitationIndex++;

    stream.runtimeCitationIndex =
      runtimeCitationIndex;

    thinkContent.dataset.thinkId =
      thinkId;
    thinkContent.dataset.runtimeCitationIndex =
      String(
        runtimeCitationIndex
      );
    thinkContent.__jinThinkRawText =
      text;

    activeThinkRuleCitationJobs.set(
      thinkId,
      {
        thinkId,
        element: thinkContent,
        text,
        runtimeCitationIndex,
        matches: [],
        done: false,
      }
    );

    loadThinkRuleCitationRegistry()
      .then((registry) => {
        const currentJob =
          activeThinkRuleCitationJobs.get(
            thinkId
          );

        if (
          !currentJob
          || !registry.enabled
          || !Array.isArray(
            registry.fragments
          )
          || thinkContent.dataset.thinkId !== thinkId
        ) {
          activeThinkRuleCitationJobs.delete(
            thinkId
          );
          return;
        }

        const fragments = [
          ...registry.fragments,
          ...buildRuntimeCitationFragments(
            currentJob.runtimeCitationIndex
          ),
          ...buildSessionCitationFragments(),
        ];

        if (!fragments.length) {
          activeThinkRuleCitationJobs.delete(
            thinkId
          );
          return;
        }

        const worker =
          getThinkRuleCitationWorker();

        if (!worker) {
          activeThinkRuleCitationJobs.delete(
            thinkId
          );
          return;
        }

        worker.postMessage(
          {
            type: "analyzeThinkRules",
            thinkId,
            text,
            fragments,
          }
        );
      });

  }

  window.JinThinkCitations = {
    startThinkRuleCitationAnalysis,
    syncThinkRuntimeCitationHighlight,
  };

})();
