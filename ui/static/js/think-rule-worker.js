const MIN_MATCH_CHARS = 24;
const MIN_MATCH_TOKENS = 4;
const MIN_RARE_TOKENS = 3;
const MIN_CONSECUTIVE_TOKEN_MATCH = 3;
const FRAGMENT_BATCH_SIZE = 8;

const STOP_WORDS = new Set([
  "a",
  "an",
  "and",
  "are",
  "as",
  "at",
  "be",
  "by",
  "for",
  "from",
  "i",
  "if",
  "in",
  "into",
  "is",
  "it",
  "my",
  "not",
  "of",
  "on",
  "or",
  "that",
  "the",
  "this",
  "to",
  "use",
  "when",
  "with",
]);

function isLetterOrNumber(char) {
  try {
    return /[\p{L}\p{N}]/u.test(
      char
    );
  } catch (error) {
    return /[a-z0-9]/i.test(
      char
    );
  }
}

function normalizeWithMap(text) {
  const output = [];
  const map = [];

  function pushSpace(index) {
    if (!output.length) {
      return;
    }

    if (
      output[output.length - 1] === " "
    ) {
      return;
    }

    output.push(" ");
    map.push(index);
  }

  const source = String(
    text || ""
  );

  for (
    let index = 0;
    index < source.length;
    index += 1
  ) {
    const rawChar = source[index];
    const normalizedChars = rawChar.normalize
      ? rawChar.normalize("NFKC").toLowerCase()
      : rawChar.toLowerCase();

    for (const char of normalizedChars) {
      if (
        isLetterOrNumber(
          char
        )
      ) {
        output.push(
          char
        );
        map.push(
          index
        );
      } else {
        pushSpace(
          index
        );
      }
    }
  }

  while (
    output.length
    && output[output.length - 1] === " "
  ) {
    output.pop();
    map.pop();
  }

  return {
    text: output.join(""),
    map,
  };
}

function normalizeText(text) {
  return normalizeWithMap(
    text
  ).text;
}

function tokenizeNormalizedText(text) {
  if (!text) {
    return [];
  }

  return text
    .split(" ")
    .filter(Boolean);
}

function tokenizeOriginalText(text) {
  const normalized =
    normalizeWithMap(
      text
    );

  const tokens = [];
  let start = 0;

  while (
    start < normalized.text.length
  ) {
    while (
      normalized.text[start] === " "
    ) {
      start += 1;
    }

    if (
      start >= normalized.text.length
    ) {
      break;
    }

    let end = start;

    while (
      end < normalized.text.length
      && normalized.text[end] !== " "
    ) {
      end += 1;
    }

    tokens.push(
      {
        text: normalized.text.slice(
          start,
          end
        ),
        start: normalized.map[start],
        end: normalized.map[end - 1] + 1,
      }
    );

    start = end + 1;
  }

  return tokens;
}

function countRareTokens(tokens) {
  const seen = new Set();

  tokens.forEach((token) => {
    if (
      token.length >= 4
      && !STOP_WORDS.has(token)
    ) {
      seen.add(
        token
      );
    }
  });

  return seen.size;
}

function isUsablePhrase(tokens) {
  const phrase = tokens.join(" ");

  return (
    tokens.length >= MIN_MATCH_TOKENS
    && phrase.length >= MIN_MATCH_CHARS
    && countRareTokens(tokens) >= MIN_RARE_TOKENS
  );
}

function findAllNormalizedRanges(
  haystack,
  needle,
  originalText
) {
  const ranges = [];

  if (
    !haystack.text
    || !needle
  ) {
    return ranges;
  }

  let index = haystack.text.indexOf(
    needle
  );

  while (index !== -1) {
    const endIndex =
      index + needle.length - 1;

    ranges.push(
      expandMatchedRange(
        originalText,
        {
          start: haystack.map[index],
          end: haystack.map[endIndex] + 1,
        }
      )
    );

    index = haystack.text.indexOf(
      needle,
      index + Math.max(
        1,
        Math.floor(
          needle.length / 2
        )
      )
    );
  }

  return ranges;
}

function expandMatchedRange(
  text,
  range
) {
  const source =
    String(
      text || ""
    );

  let start =
    range.start;
  let end =
    range.end;

  const pairs = [
    ["<", ">"],
    ["`", "`"],
    ['"', '"'],
    ["'", "'"],
  ];

  let expanded = true;

  while (expanded) {
    expanded = false;

    for (const [left, right] of pairs) {
      if (
        start > 0
        && end < source.length
        && source[start - 1] === left
        && source[end] === right
      ) {
        start -= 1;
        end += 1;
        expanded = true;
      }
    }
  }

  return {
    start,
    end,
  };
}

function buildMatch(
  fragment,
  range,
  score,
  level
) {
  return {
    start: range.start,
    end: range.end,
    score,
    level,
    constantName: fragment.constantName,
    source: fragment.source,
    sourceType: fragment.sourceType,
    citationType: fragment.citationType,
    layer: fragment.layer,
    sourceText: fragment.sourceText,
    titleText: fragment.titleText || fragment.sourceText,
  };
}

function sourcePriority(
  match
) {
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

  return 0;
}

function findExactMatches(
  fragment,
  thinkNormalized,
  originalText
) {
  const sourceTokens = tokenizeNormalizedText(
    normalizeText(
      fragment.sourceText
    )
  );

  if (
    !isUsablePhrase(
      sourceTokens
    )
  ) {
    return [];
  }

  const matches = [];
  const fullNeedle = sourceTokens.join(" ");
  const fullRanges = findAllNormalizedRanges(
    thinkNormalized,
    fullNeedle,
    originalText
  );

  fullRanges.forEach((range) => {
    matches.push(
      buildMatch(
        fragment,
        range,
        1,
        "exact"
      )
    );
  });

  const maxWindowSize = Math.min(
    14,
    sourceTokens.length - 1
  );

  for (
    let size = maxWindowSize;
    size >= MIN_MATCH_TOKENS;
    size -= 1
  ) {
    for (
      let start = 0;
      start <= sourceTokens.length - size;
      start += 1
    ) {
      const phraseTokens = sourceTokens.slice(
        start,
        start + size
      );

      if (
        !isUsablePhrase(
          phraseTokens
        )
      ) {
        continue;
      }

      const needle = phraseTokens.join(" ");
      const ranges = findAllNormalizedRanges(
        thinkNormalized,
        needle,
        originalText
      );

      ranges.forEach((range) => {
        matches.push(
          buildMatch(
            fragment,
            range,
            0.92,
            "exact"
          )
        );
      });
    }
  }

  return matches;
}

function tokenOverlapScore(
  sourceTokens,
  thinkTokens
) {
  const sourceCounts = new Map();

  sourceTokens.forEach((token) => {
    sourceCounts.set(
      token,
      (
        sourceCounts.get(
          token
        )
        || 0
      ) + 1
    );
  });

  let overlap = 0;
  let rareOverlap = 0;

  thinkTokens.forEach((token) => {
    const count =
      sourceCounts.get(
        token
      )
      || 0;

    if (!count) {
      return;
    }

    overlap += 1;

    if (
      token.length >= 4
      && !STOP_WORDS.has(token)
    ) {
      rareOverlap += 1;
    }

    if (count === 1) {
      sourceCounts.delete(
        token
      );
    } else {
      sourceCounts.set(
        token,
        count - 1
      );
    }
  });

  const score =
    overlap
    / Math.max(
      sourceTokens.length,
      thinkTokens.length
    );

  return {
    score,
    rareOverlap,
  };
}

function findBestConsecutiveTokenRun(
  sourceTokens,
  thinkTokens
) {
  let best = {
    sourceStart: 0,
    thinkStart: 0,
    length: 0,
  };

  for (
    let sourceStart = 0;
    sourceStart < sourceTokens.length;
    sourceStart += 1
  ) {
    for (
      let thinkStart = 0;
      thinkStart < thinkTokens.length;
      thinkStart += 1
    ) {
      let length = 0;

      while (
        sourceStart + length < sourceTokens.length
        && thinkStart + length < thinkTokens.length
        && sourceTokens[sourceStart + length]
          === thinkTokens[thinkStart + length]
      ) {
        length += 1;
      }

      if (
        length > best.length
      ) {
        best = {
          sourceStart,
          thinkStart,
          length,
        };
      }
    }
  }

  return best;
}

function isLikelyStructuredLabelRange(
  text
) {
  return /(?:^|[\s*"`])[_A-Z0-9]{3,}(?:_[A-Z0-9]+)+\s*:/u.test(
    text
  );
}

function findTokenWindowMatches(
  fragment,
  thinkTokens,
  originalText
) {
  const sourceTokens = tokenizeNormalizedText(
    normalizeText(
      fragment.sourceText
    )
  );

  const matches = [];
  const maxSourceWindow = Math.min(
    14,
    sourceTokens.length
  );

  for (
    let sourceSize = maxSourceWindow;
    sourceSize >= MIN_MATCH_TOKENS;
    sourceSize -= 1
  ) {
    for (
      let sourceStart = 0;
      sourceStart <= sourceTokens.length - sourceSize;
      sourceStart += 1
    ) {
      const sourceWindow = sourceTokens.slice(
        sourceStart,
        sourceStart + sourceSize
      );

      if (
        !isUsablePhrase(
          sourceWindow
        )
      ) {
        continue;
      }

      const minThinkSize = Math.max(
        MIN_MATCH_TOKENS,
        sourceSize - 1
      );
      const maxThinkSize = Math.min(
        thinkTokens.length,
        sourceSize + 1
      );

      for (
        let thinkSize = maxThinkSize;
        thinkSize >= minThinkSize;
        thinkSize -= 1
      ) {
        for (
          let thinkStart = 0;
          thinkStart <= thinkTokens.length - thinkSize;
          thinkStart += 1
        ) {
          const thinkWindow = thinkTokens.slice(
            thinkStart,
            thinkStart + thinkSize
          );
          const thinkWindowTokens = thinkWindow.map(
            (token) => token.text
          );
          const result = tokenOverlapScore(
            sourceWindow,
            thinkWindowTokens
          );
          const bestRun = findBestConsecutiveTokenRun(
            sourceWindow,
            thinkWindowTokens
          );

          if (
            result.score < 0.72
            || result.rareOverlap < MIN_RARE_TOKENS
            || bestRun.length < MIN_CONSECUTIVE_TOKEN_MATCH
          ) {
            continue;
          }

          const runStartToken =
            thinkWindow[bestRun.thinkStart];
          const runEndToken =
            thinkWindow[
              bestRun.thinkStart
              + bestRun.length
              - 1
            ];
          const matchedOriginalText =
            originalText.slice(
              runStartToken.start,
              runEndToken.end
            );

          if (
            isLikelyStructuredLabelRange(
              matchedOriginalText
            )
          ) {
            continue;
          }

          const level =
            result.score >= 0.82
              ? "near"
              : "compressed";

          matches.push(
            buildMatch(
              fragment,
              expandMatchedRange(
                originalText,
                {
                  start: runStartToken.start,
                  end: runEndToken.end,
                }
              ),
              Number(
                result.score.toFixed(
                  2
                )
              ),
              level
            )
          );
        }
      }
    }
  }

  return matches;
}

function levelRank(level) {
  if (level === "exact") {
    return 3;
  }

  if (level === "near") {
    return 2;
  }

  return 1;
}

function resolveOverlaps(matches) {
  const sorted = [...matches].sort(
    (left, right) => {
      const priorityDelta =
        sourcePriority(
          right
        )
        - sourcePriority(
          left
        );

      if (priorityDelta) {
        return priorityDelta;
      }

      const levelDelta =
        levelRank(
          right.level
        )
        - levelRank(
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
    }
  );

  const selected = [];

  sorted.forEach((match) => {
    if (
      match.end <= match.start
      || selected.some(
        (selectedMatch) => (
          match.start < selectedMatch.end
          && match.end > selectedMatch.start
        )
      )
    ) {
      return;
    }

    selected.push(
      match
    );
  });

  return selected.sort(
    (left, right) => left.start - right.start
  );
}

function analyzeThinkRules(
  payload
) {
  const {
    thinkId,
    text,
    fragments,
  } = payload;

  const thinkNormalized =
    normalizeWithMap(
      text
    );
  const thinkTokens =
    tokenizeOriginalText(
      text
    );

  let index = 0;

  function processBatch() {
    const batchMatches = [];
    const end = Math.min(
      index + FRAGMENT_BATCH_SIZE,
      fragments.length
    );

    for (
      ;
      index < end;
      index += 1
    ) {
      const fragment =
        fragments[index];

      batchMatches.push(
        ...findExactMatches(
          fragment,
          thinkNormalized,
          text
        )
      );

      batchMatches.push(
        ...findTokenWindowMatches(
          fragment,
          thinkTokens,
          text
        )
      );
    }

    const resolvedMatches =
      resolveOverlaps(
        batchMatches
      );

    if (resolvedMatches.length) {
      self.postMessage(
        {
          type: "ruleMatchesChunk",
          thinkId,
          matches: resolvedMatches,
        }
      );
    }

    if (
      index < fragments.length
    ) {
      setTimeout(
        processBatch,
        0
      );
      return;
    }

    self.postMessage(
      {
        type: "ruleMatchesDone",
        thinkId,
      }
    );
  }

  processBatch();
}

self.onmessage = (event) => {
  const data =
    event.data
    || {};

  if (
    data.type !== "analyzeThinkRules"
  ) {
    return;
  }

  analyzeThinkRules(
    data
  );
};
