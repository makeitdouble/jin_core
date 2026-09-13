"""Small prompt-time budget for the visible L-T context projection.

This module intentionally does not change L-T storage or prompt ordering.
It only decides how many already-visible facts may stay in the current
LONG_TERM_MEMORY block, selecting survivors by ``last_mentioned_at``.
"""

from __future__ import annotations

from datetime import datetime, timezone
import math
import re


LT_CONTEXT_FULL_LOAD_USAGE = 0.50
LT_CONTEXT_MIN_LOAD_USAGE = 0.90

_LONG_TERM_MEMORY_BLOCK_RE = re.compile(
    r"(?P<open><LONG_TERM_MEMORY>\r?\n)"
    r"(?P<body>.*?)"
    r"(?P<close>\r?\n</LONG_TERM_MEMORY>)",
    re.DOTALL,
)
_LT_CONTEXT_FACT_ID_RE = re.compile(
    r"\[\s*id:\s*(F[1-9]\d*)\s*\]",
    re.IGNORECASE,
)


def calculate_lt_context_fact_limit(
    *,
    total_facts: int,
    used_tokens_without_lt: int,
    context_window: int,
) -> int:
    """Return a deliberately simple L-T fact count for the current window.

    <= 50% occupied without L-T -> keep everything.
    >= 90% occupied without L-T -> keep one freshest fact.
    Between those points -> linearly interpolate the fact count.
    """

    total = max(0, int(total_facts or 0))
    if total <= 1:
        return total

    window = max(0, int(context_window or 0))
    if window <= 0:
        # Unknown window: preserve the historical all-facts behavior.
        return total

    used = max(0, int(used_tokens_without_lt or 0))
    usage = used / window

    if usage <= LT_CONTEXT_FULL_LOAD_USAGE:
        return total
    if usage >= LT_CONTEXT_MIN_LOAD_USAGE:
        return 1

    span = LT_CONTEXT_MIN_LOAD_USAGE - LT_CONTEXT_FULL_LOAD_USAGE
    remaining = (LT_CONTEXT_MIN_LOAD_USAGE - usage) / span
    limit = math.ceil(
        1 + (total - 1) * remaining
    )
    return max(1, min(total, limit))


def split_long_term_memory_context(
    system_prompt: str,
) -> tuple[str, str, re.Match | None]:
    """Return prompt-without-L-T, current L-T block, and its regex match."""

    prompt = str(system_prompt or "")
    match = _LONG_TERM_MEMORY_BLOCK_RE.search(prompt)
    if match is None:
        return prompt, "", None

    block = match.group(0)
    without_block = (
        prompt[:match.start()]
        + prompt[match.end():]
    )
    return without_block, block, match


def get_lt_context_fact_ids(
    memory_block: str,
) -> list[str]:
    result = []
    seen = set()

    for match in _LT_CONTEXT_FACT_ID_RE.finditer(
        str(memory_block or "")
    ):
        fact_id = match.group(1).upper()
        if fact_id in seen:
            continue
        seen.add(fact_id)
        result.append(fact_id)

    return result


def _last_mentioned_sort_value(value) -> float:
    text = str(value or "").strip()
    if not text:
        return float("-inf")

    try:
        parsed = datetime.fromisoformat(
            text[:-1] + "+00:00"
            if text.endswith("Z")
            else text
        )
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError, OverflowError):
        return float("-inf")


def limit_long_term_memory_context(
    *,
    context,
    system_prompt: str,
    fact_limit: int,
) -> str:
    """Select freshest L-T survivors without changing their prompt order."""

    prompt = str(system_prompt or "")
    match = _LONG_TERM_MEMORY_BLOCK_RE.search(prompt)
    if match is None:
        return prompt

    fact_ids = get_lt_context_fact_ids(
        match.group(0)
    )
    total = len(fact_ids)
    limit = max(0, min(total, int(fact_limit or 0)))
    if limit <= 0:
        return (
            prompt[:match.start()]
            + prompt[match.end():]
        )
    if limit >= total:
        return prompt

    store = getattr(
        context,
        "runtime_long_term_memory_store",
        {},
    )
    facts = (
        store.get("facts", [])
        if isinstance(store, dict)
        else []
    )
    facts_by_id = {
        str(fact.get("id", "") or "").strip().upper(): fact
        for fact in facts or []
        if isinstance(fact, dict)
        and str(fact.get("id", "") or "").strip()
    }

    ranked = sorted(
        enumerate(fact_ids),
        key=lambda item: (
            -_last_mentioned_sort_value(
                facts_by_id.get(
                    item[1],
                    {},
                ).get("last_mentioned_at")
            ),
            item[0],
        ),
    )
    selected_ids = {
        fact_id
        for _index, fact_id in ranked[:limit]
    }

    kept_lines = []
    for line in match.group("body").splitlines():
        line_id_match = _LT_CONTEXT_FACT_ID_RE.search(line)
        if (
            line_id_match is not None
            and line_id_match.group(1).upper() not in selected_ids
        ):
            continue
        kept_lines.append(line)

    next_block = (
        match.group("open")
        + "\n".join(kept_lines)
        + match.group("close")
    )
    return (
        prompt[:match.start()]
        + next_block
        + prompt[match.end():]
    )
