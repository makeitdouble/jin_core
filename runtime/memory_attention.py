"""Prompt-only relevance ranking for JIN memory systems.

Memory attention is deliberately stateless: it does not call a model, mutate
memory records, persist scores, or steer Brain sampling.  It only builds the
current prompt projection for Active Memory, Delayed Memory and L-T.
"""

from __future__ import annotations

import re
from typing import Any


ACTIVE_MEMORY_MIN_RELEVANCE = 0.16
DELAYED_MEMORY_BUBBLE_THRESHOLD = 0.26
DELAYED_MEMORY_STRONG_BUBBLE_THRESHOLD = 0.42
MEMORY_RECENT_FACTS = 6
MEMORY_RECENT_USER_TURNS = 3


def _normalized_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def _signal_words(value: Any) -> list[str]:
    return [
        token
        for token in re.findall(
            r"[^\W_]{2,}",
            _normalized_text(value),
            flags=re.UNICODE,
        )
        if token
    ]


_MEMORY_LEXICAL_STOPWORDS = {
    # Keep this intentionally tiny. It only removes glue words that otherwise
    # create false relevance when the user says things like "это" / "this".
    "это", "эта", "этот", "эти", "того", "так", "там", "тут", "вот",
    "как", "что", "чтобы", "если", "или", "для", "при", "про", "она",
    "они", "оно", "его", "её", "уже", "ещё", "еще", "просто", "сейчас",
    "давай", "дальше", "продолжим", "продолжить", "поговорим", "снова",
    "опять", "this", "that", "these", "those", "with", "from", "into",
    "about", "have", "has", "had", "just", "then", "than", "when",
    "where", "what", "your", "you", "user", "jin",
}


def _memory_lexical_tokens(value: Any) -> set[str]:
    return {
        token
        for token in _signal_words(value)
        if len(token) >= 3 and token not in _MEMORY_LEXICAL_STOPWORDS
    }


def _memory_token_stem(token: str) -> str:
    token = str(token or "")
    if len(token) <= 5:
        return token
    # Cheap morphology bridge for inflected RU/EN words.
    return token[:5]


def _memory_phrase_ngrams(
    value: Any,
    *,
    size: int = 2,
) -> set[tuple[str, ...]]:
    words = [
        token
        for token in _signal_words(value)
        if len(token) >= 3 and token not in _MEMORY_LEXICAL_STOPWORDS
    ]
    if len(words) < size:
        return set()
    return {
        tuple(_memory_token_stem(token) for token in words[index:index + size])
        for index in range(len(words) - size + 1)
    }


def lexical_memory_match(query: Any, candidate: Any) -> float:
    """Return a cheap RU/EN lexical match in the 0..1 range."""

    query_tokens = _memory_lexical_tokens(query)
    candidate_tokens = _memory_lexical_tokens(candidate)
    if not query_tokens or not candidate_tokens:
        return 0.0

    exact_hits = len(query_tokens & candidate_tokens)
    query_stems = {_memory_token_stem(token) for token in query_tokens}
    candidate_stems = {_memory_token_stem(token) for token in candidate_tokens}
    stem_hits = len(query_stems & candidate_stems)

    # One meaningful keyword should still count inside a long user sentence.
    query_denominator = max(1, min(4, len(query_tokens)))
    exact_score = min(1.0, exact_hits / query_denominator)
    stem_score = min(1.0, stem_hits / query_denominator)
    candidate_denominator = max(1, min(6, len(candidate_tokens)))
    candidate_focus = min(1.0, stem_hits / candidate_denominator)

    query_bigrams = _memory_phrase_ngrams(query, size=2)
    candidate_bigrams = _memory_phrase_ngrams(candidate, size=2)
    phrase_score = 1.0 if query_bigrams & candidate_bigrams else 0.0

    return round(
        min(
            1.0,
            exact_score * 0.48
            + stem_score * 0.30
            + candidate_focus * 0.08
            + phrase_score * 0.14,
        ),
        4,
    )


def _lt_fact_numeric_sort_key(fact: dict) -> tuple:
    """Newest durable facts first; F ids are monotonic creation ids."""

    fact_id = str((fact or {}).get("id", "") or "").strip()
    match = re.fullmatch(r"F([1-9]\d*)", fact_id, flags=re.IGNORECASE)
    if match:
        return (0, -int(match.group(1)), "")
    return (1, 0, fact_id.casefold())


def _recent_user_memory_queries(context) -> list[str]:
    if context is None:
        return []

    result: list[str] = []
    seen: set[str] = set()
    for turn in reversed(getattr(context, "runtime_recent_turns", []) or []):
        if not isinstance(turn, dict):
            continue
        text = str(turn.get("user", turn.get("user_message", "")) or "").strip()
        normalized = _normalized_text(text)
        if not normalized or normalized in seen:
            continue
        result.append(text)
        seen.add(normalized)
        if len(result) >= MEMORY_RECENT_USER_TURNS:
            break
    return result


def _recent_lt_memory_queries(context) -> list[str]:
    if context is None:
        return []

    store = getattr(context, "runtime_long_term_memory_store", {})
    facts = store.get("facts", []) if isinstance(store, dict) else []
    normalized = [fact for fact in facts or [] if isinstance(fact, dict)]
    normalized.sort(key=_lt_fact_numeric_sort_key)

    result = []
    for fact in normalized[:MEMORY_RECENT_FACTS]:
        text = " ".join(
            part
            for part in (
                str(fact.get("key", "") or "").strip(),
                str(fact.get("value", "") or "").strip(),
            )
            if part
        )
        if text:
            result.append(text)
    return result


def memory_context_relevance(
    candidate: Any,
    *,
    user_input: str = "",
    context=None,
) -> float:
    """Blend the current query with a small recent-dialogue/L-T context tail."""

    current = lexical_memory_match(user_input, candidate)
    recent = max(
        (
            lexical_memory_match(query, candidate)
            for query in _recent_user_memory_queries(context)
        ),
        default=0.0,
    )
    recent_fact = max(
        (
            lexical_memory_match(query, candidate)
            for query in _recent_lt_memory_queries(context)
        ),
        default=0.0,
    )
    contextual_tail = min(1.0, recent * 0.24 + recent_fact * 0.30)
    return round(
        min(1.0, current + (1.0 - current) * contextual_tail),
        4,
    )


def _active_memory_record_id(record: str) -> str:
    try:
        from utils.actions.active_memory_utils import collect_active_memory_slot_ids

        ids = sorted(collect_active_memory_slot_ids(record))
        return ids[0] if ids else ""
    except Exception:
        return ""


def _active_memory_visible_text(record: str) -> str:
    try:
        from utils.actions.active_memory_utils import strip_active_memory_managed_suffixes

        return strip_active_memory_managed_suffixes(record)
    except Exception:
        return str(record or "").strip()


def _active_memory_is_paused(record: str) -> bool:
    try:
        from utils.actions.active_memory_utils import is_active_memory_record_paused

        return bool(is_active_memory_record_paused(record))
    except Exception:
        return False


def score_active_memory_record(
    record: str,
    *,
    user_input: str,
    context=None,
) -> float:
    relevance = memory_context_relevance(
        _active_memory_visible_text(record),
        user_input=user_input,
        context=context,
    )
    score = ACTIVE_MEMORY_MIN_RELEVANCE + min(0.74, relevance * 0.84)

    normalized_user = _normalized_text(user_input)
    active_id = _active_memory_record_id(record)
    if active_id and active_id.casefold() in normalized_user:
        score += 0.30

    return round(max(0.0, min(1.0, score)), 3)


def rank_active_memory_records(
    records: list[str],
    *,
    context=None,
    user_input: str = "",
) -> list[str]:
    """Return a relevance-ranked prompt view without touching stored records."""

    scored = []
    for index, record in enumerate(records or []):
        if _active_memory_is_paused(record):
            continue
        scored.append(
            (
                score_active_memory_record(
                    record,
                    user_input=user_input,
                    context=context,
                ),
                index,
                record,
            )
        )
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [record for _score, _index, record in scored]


def score_delayed_memory_report(
    report: dict,
    *,
    report_id: str = "",
    user_input: str = "",
    context=None,
) -> float:
    if not isinstance(report, dict):
        return 0.0

    title = str(report.get("title", "") or "").strip()
    summary = str(report.get("summary", "") or "").strip()
    tags = report.get("tags", [])
    if not isinstance(tags, list):
        tags = [tags]
    tags_text = " ".join(
        str(tag or "").strip()
        for tag in tags
        if str(tag or "").strip()
    )

    title_score = (
        memory_context_relevance(title, user_input=user_input, context=context)
        if title
        else 0.0
    )
    summary_score = (
        memory_context_relevance(summary, user_input=user_input, context=context)
        if summary
        else 0.0
    )
    tags_score = (
        memory_context_relevance(tags_text, user_input=user_input, context=context)
        if tags_text
        else 0.0
    )
    score = max(title_score, summary_score * 0.88, tags_score * 0.72)

    normalized_user = _normalized_text(user_input)
    normalized_id = str(report_id or report.get("id", "") or "").strip().casefold()
    if normalized_id and normalized_id in normalized_user:
        score = max(score, 0.96)

    return round(max(0.0, min(1.0, score)), 3)


def delayed_memory_bubble_tier(score: float) -> int:
    try:
        value = float(score)
    except (TypeError, ValueError):
        value = 0.0

    if value >= DELAYED_MEMORY_STRONG_BUBBLE_THRESHOLD:
        return 2
    if value >= DELAYED_MEMORY_BUBBLE_THRESHOLD:
        return 1
    return 0


def score_lt_fact_context_focus(
    fact: dict,
    *,
    user_input: str,
    context=None,
) -> float:
    """Return prompt-only L-T relevance without mutating storage or UI order."""

    if not isinstance(fact, dict):
        return 0.0
    fact_text = " ".join(
        part
        for part in (
            str(fact.get("key", "") or "").strip(),
            str(fact.get("value", "") or "").strip(),
        )
        if part
    )
    if not fact_text:
        return 0.0
    current = lexical_memory_match(user_input, fact_text)
    recent = max(
        (
            lexical_memory_match(query, fact_text)
            for query in _recent_user_memory_queries(context)
        ),
        default=0.0,
    )
    # L-T facts must not become relevant by matching themselves through the
    # recent-L-T context tail. Only the current/recent USER dialogue may focus
    # the durable store.
    return round(
        min(1.0, current + (1.0 - current) * recent * 0.24),
        4,
    )


def _select_lt_focus(
    scored: list[tuple[float, int, dict]],
) -> list[tuple[float, int, dict]]:
    """Choose a coherent 1..3 fact cone instead of a fixed top-k."""

    ranked = sorted(scored, key=lambda item: (-item[0], item[1]))
    if not ranked or ranked[0][0] < 0.22:
        return []

    top_score = ranked[0][0]
    focused = [ranked[0]]
    if len(ranked) > 1 and ranked[1][0] >= max(0.20, top_score * 0.75):
        focused.append(ranked[1])
    if (
        len(focused) == 2
        and len(ranked) > 2
        and ranked[2][0] >= max(0.18, top_score * 0.61)
        and top_score >= 0.34
    ):
        focused.append(ranked[2])
    return focused


def rank_lt_facts_for_context(
    facts: list[dict],
    *,
    context=None,
    user_input: str = "",
) -> list[dict]:
    """Bubble 1..3 relevant facts above the canonical newest-first lane."""

    canonical = sorted(
        [fact for fact in (facts or []) if isinstance(fact, dict)],
        key=_lt_fact_numeric_sort_key,
    )
    if not canonical:
        if context is not None:
            context.runtime_memory_attention_lt_focus_ids = []
        return []

    focused_facts = []
    if str(user_input or "").strip():
        focused = _select_lt_focus([
            (
                score_lt_fact_context_focus(
                    fact,
                    user_input=user_input,
                    context=context,
                ),
                index,
                fact,
            )
            for index, fact in enumerate(canonical)
        ])
        focused_facts = [item[2] for item in focused]

    if context is not None:
        context.runtime_memory_attention_lt_focus_ids = [
            str(fact.get("id", "") or "").strip()
            for fact in focused_facts
            if str(fact.get("id", "") or "").strip()
        ]

    focused_object_ids = {id(fact) for fact in focused_facts}
    return [
        *focused_facts,
        *(fact for fact in canonical if id(fact) not in focused_object_ids),
    ]
