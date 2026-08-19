from __future__ import annotations

import asyncio
import json
import math
import re
import secrets
import time
import unicodedata
from copy import deepcopy
from typing import Any

from clients.response_extractor import ResponseExtractor
from clients.service_client import ask_service_model
from config_loader import config
from utils.tokens import estimate_runtime_tokens


METABOLISM_CHANNELS = (
    "dopamine",
    "serotonin",
    "oxytocin",
    "norepinephrine",
    "cortisol",
)

METABOLISM_DEFAULT_LEVELS = {
    "dopamine": 0.42,
    "serotonin": 0.58,
    "oxytocin": 0.46,
    "norepinephrine": 0.38,
    "cortisol": 0.24,
}

# The service model interprets the turn and proposes a target. JIN owns the
# actual physics: slow channels cannot jump as fast as reactive channels.
METABOLISM_MAX_STEP = {
    "dopamine": 0.08,
    "serotonin": 0.04,
    "oxytocin": 0.04,
    "norepinephrine": 0.08,
    "cortisol": 0.08,
}

# Wall-clock return to baseline. The server advances lazily at the next
# observable event; the UI mirrors the same curve while JIN is idle. This
# gives us continuous homeostasis without another noisy background worker.
METABOLISM_HALF_LIFE_SECONDS = {
    "dopamine": 45 * 60,
    "serotonin": 150 * 60,
    "oxytocin": 120 * 60,
    "norepinephrine": 32 * 60,
    "cortisol": 55 * 60,
}

# The lexical reflex happens before generation. It is deliberately weaker
# than the semantic SERVICE estimate that integrates the completed turn.
METABOLISM_REFLEX_MAX_STEP = {
    "dopamine": 0.05,
    "serotonin": 0.035,
    "oxytocin": 0.04,
    "norepinephrine": 0.05,
    "cortisol": 0.05,
}

METABOLISM_TEMPERATURE_MAX_DELTA = 0.12
METABOLISM_MEMORY_STRENGTH_MAX_BOOST = 0.12
METABOLISM_ACTIVE_MEMORY_MIN_SALIENCE = 0.16

# Fast rollback switches. State estimation + UI telemetry keep running even if
# causal steering is disabled, so it is easy to compare "observer only" vs
# "metabolism actually participates" without reverting the patch.
METABOLISM_CAUSAL_POLICY_ENABLED = True
METABOLISM_MEMORY_BIAS_ENABLED = True

# Learned lexical resonance. No user-language cue has a predefined meaning.
# Phrases/words are learned only after a committed L1 batch: the semantic
# metabolism pass provides the direction, while the lexical key comes from
# the user input that overlaps previous/current dialogue or live runtime.
METABOLISM_ASSOCIATION_MAX_ITEMS = 96
METABOLISM_ASSOCIATION_MAX_PHRASE_WORDS = 4
METABOLISM_ASSOCIATION_MIN_WORD_CHARS = 4
METABOLISM_ASSOCIATION_REFLEX_GAIN = 0.62
METABOLISM_ASSOCIATION_HALF_LIFE_SECONDS = 14 * 24 * 60 * 60
METABOLISM_SEMANTIC_IDLE_DEBOUNCE_SECONDS = 0.35

METABOLISM_RECENT_TURNS = 5
METABOLISM_RECENT_ACTIONS = 10
METABOLISM_REASONING_MAX_CHARS = 4200
METABOLISM_MESSAGE_MAX_CHARS = 7000
METABOLISM_RUNTIME_MEMORY_MAX_CHARS = 9000
METABOLISM_MAX_OUTPUT_TOKENS = 120
METABOLISM_TEMPERATURE = 0.1
METABOLISM_CONTEXT_RESERVE_TOKENS = 384

METABOLISM_SYSTEM_PROMPT = """You are JIN's metabolism state estimator.

Read the supplied runtime snapshot and return the five target levels that JIN's internal state should move toward. These are computational modulation signals, not medical claims and not human physiology. The runtime applies inertia and movement limits itself; you only interpret the current state.

Channels:
- dopamine: reward / novelty. Higher after useful novelty, successful resolution, clear progress, meaningful discovery, or explicit positive outcome/feedback. Do not reward JIN for its own excited wording.
- serotonin: stability / regulation. Higher during calm coherent continuity and resolved uncertainty; lower during repeated instability, unresolved contradiction, or disorganized flow.
- oxytocin: social continuity. Higher when shared context is used successfully, trust/continuity is explicitly reinforced, or the interaction feels durably collaborative. Do not infer it from flattery or JIN's own affectionate wording.
- norepinephrine: alertness / attention. Higher for novelty, uncertainty, difficult active work, demanding reasoning, or situations that deserve sharper attention; lower when the interaction is settled and low-demand.
- cortisol: pressure / error load. Higher for failed actions, validator/repetition loops, repeated user corrections, unresolved conflict, visible frustration, or stuck/strained reasoning; lower after repair and clean successful flow.

Evidence priority:
1. The newly committed L1 batch: its linked user input(s), concrete memory changes, USER feedback/corrections, and concrete runtime action outcomes.
2. Active Memory conditions, current L1 state, and loaded/pinned delayed memory.
3. Recent dialogue/reasoning across the restored previous session and current session when they visibly show uncertainty, strain, discovery, bonding, or resolution.
4. L4 metadata is orientation only; never change a channel merely because a fact exists.

Treat committed_l1.last_user_input as the cause-side anchor for fresh runtime evidence. If the new L1 snapshot records dissatisfaction, correction, success, recurring preference, or another meaningful state change, attribute that evidence to the linked input instead of inventing a generic lexical interpretation.

Active Memory and delayed-memory inventory are context, not proof of emotion by themselves. Treat a memory as metabolic evidence only when the current interaction activates, satisfies, violates, or meaningfully reuses it.

Keep continuity with previous_levels. Weak evidence should produce a target close to the previous state or baseline, not a dramatic mood swing.

Output contract:
- Return strict JSON only.
- Do not write analysis, headings, bullets, markdown, commentary, or code fences.
- Emit exactly one JSON object and nothing before or after it.

{"dopamine":0.000,"serotonin":0.000,"oxytocin":0.000,"norepinephrine":0.000,"cortisol":0.000}
"""


def _clamp_level(value: Any, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float(fallback)

    if number != number:  # NaN
        number = float(fallback)

    return round(max(0.0, min(1.0, number)), 3)


def normalize_metabolism_levels(value: Any) -> dict[str, float]:
    source = value if isinstance(value, dict) else {}
    return {
        channel: _clamp_level(
            source.get(channel),
            METABOLISM_DEFAULT_LEVELS[channel],
        )
        for channel in METABOLISM_CHANNELS
    }


def ensure_metabolism_state(context) -> dict[str, float]:
    current = normalize_metabolism_levels(
        getattr(context, "runtime_metabolism_levels", None)
    )
    context.runtime_metabolism_levels = current
    return current


def apply_metabolism_target(
    previous: dict[str, float],
    target: dict[str, float],
) -> dict[str, float]:
    previous_levels = normalize_metabolism_levels(previous)
    target_levels = normalize_metabolism_levels(target)
    next_levels: dict[str, float] = {}

    for channel in METABOLISM_CHANNELS:
        current = previous_levels[channel]
        desired = target_levels[channel]
        max_step = METABOLISM_MAX_STEP[channel]
        delta = max(-max_step, min(max_step, desired - current))
        next_levels[channel] = _clamp_level(current + delta, current)

    return _apply_metabolism_interactions(next_levels)


def _metabolism_delta(
    previous: dict[str, float],
    current: dict[str, float],
) -> dict[str, float]:
    return {
        channel: round(
            normalize_metabolism_levels(current)[channel]
            - normalize_metabolism_levels(previous)[channel],
            3,
        )
        for channel in METABOLISM_CHANNELS
    }


def _normalized_signal_text(value: Any) -> str:
    return unicodedata.normalize(
        "NFKC",
        str(value or ""),
    ).casefold().strip()


def _tokenize_signal_text(value: Any) -> set[str]:
    return {
        token
        for token in re.findall(
            r"[^\W_]{2,}",
            _normalized_signal_text(value),
            flags=re.UNICODE,
        )
        if token
    }


def _signal_words(value: Any) -> list[str]:
    return [
        token
        for token in re.findall(
            r"[^\W_]{2,}",
            _normalized_signal_text(value),
            flags=re.UNICODE,
        )
        if token
    ]


def _normalize_signal_phrase(value: Any) -> str:
    return " ".join(_signal_words(value))


def _compile_learned_phrase_pattern(phrase: str) -> re.Pattern | None:
    words = _signal_words(phrase)
    if not words:
        return None
    body = r"\s+".join(re.escape(word) for word in words)
    try:
        return re.compile(
            rf"(?<!\w){body}(?!\w)",
            flags=re.IGNORECASE | re.UNICODE,
        )
    except re.error:
        return None


def normalize_metabolism_associations(value: Any) -> list[dict]:
    source = value if isinstance(value, list) else []
    normalized: list[dict] = []
    seen: set[str] = set()

    for raw in source:
        if not isinstance(raw, dict):
            continue
        phrase = _normalize_signal_phrase(raw.get("phrase", ""))
        if not phrase or phrase in seen:
            continue
        if len(phrase.split()) > METABOLISM_ASSOCIATION_MAX_PHRASE_WORDS:
            continue

        vector_source = raw.get("vector", {})
        if not isinstance(vector_source, dict):
            vector_source = {}
        vector: dict[str, float] = {}
        for channel in METABOLISM_CHANNELS:
            try:
                delta = float(vector_source.get(channel, 0.0) or 0.0)
            except (TypeError, ValueError):
                delta = 0.0
            max_step = METABOLISM_REFLEX_MAX_STEP[channel]
            vector[channel] = round(max(-max_step, min(max_step, delta)), 4)

        try:
            weight = float(raw.get("weight", 0.0) or 0.0)
        except (TypeError, ValueError):
            weight = 0.0
        try:
            hits = int(raw.get("hits", 1) or 1)
        except (TypeError, ValueError):
            hits = 1
        try:
            updated_at = float(raw.get("updated_at", 0.0) or 0.0)
        except (TypeError, ValueError):
            updated_at = 0.0

        normalized.append({
            "phrase": phrase,
            "vector": vector,
            "weight": round(max(0.0, min(1.0, weight)), 4),
            "hits": max(1, hits),
            "updated_at": max(0.0, updated_at),
            "source": str(raw.get("source", "") or "").strip()[:120],
        })
        seen.add(phrase)

    normalized.sort(
        key=lambda item: (
            -float(item.get("weight", 0.0) or 0.0),
            -int(item.get("hits", 1) or 1),
            -float(item.get("updated_at", 0.0) or 0.0),
        )
    )
    return normalized[:METABOLISM_ASSOCIATION_MAX_ITEMS]


def ensure_metabolism_associations(context) -> list[dict]:
    if context is None:
        return []
    associations = normalize_metabolism_associations(
        getattr(context, "runtime_metabolism_associations", None)
    )
    context.runtime_metabolism_associations = associations
    return associations


def _association_recency_weight(item: dict, now: float | None = None) -> float:
    try:
        updated_at = float(item.get("updated_at", 0.0) or 0.0)
    except (TypeError, ValueError):
        updated_at = 0.0
    if updated_at <= 0.0:
        return 1.0
    age = max(0.0, float(now if now is not None else time.time()) - updated_at)
    return math.pow(0.5, age / METABOLISM_ASSOCIATION_HALF_LIFE_SECONDS)


def _phrase_occurs(phrase: str, text: Any) -> bool:
    pattern = _compile_learned_phrase_pattern(phrase)
    # Compare on the same lexical surface: punctuation/underscores become word
    # separators, so learned phrases survive harmless formatting changes.
    return bool(pattern and pattern.search(_normalize_signal_phrase(text)))


def _runtime_resonance_texts(
    context,
    *,
    exclude_user_messages: set[str] | None = None,
) -> list[str]:
    if context is None:
        return []

    excluded = {
        _normalized_signal_text(item)
        for item in (exclude_user_messages or set())
        if _normalized_signal_text(item)
    }
    texts: list[str] = []

    for value in (
        getattr(context, "runtime_memory", ""),
        getattr(context, "runtime_restored_session_dialog", ""),
    ):
        value = str(value or "").strip()
        if value:
            texts.append(value)

    for turn in getattr(context, "runtime_recent_turns", []) or []:
        if not isinstance(turn, dict):
            continue
        for key in ("user", "user_message", "jin", "assistant_message"):
            value = str(turn.get(key, "") or "").strip()
            if not value:
                continue
            if key in {"user", "user_message"} and _normalized_signal_text(value) in excluded:
                continue
            texts.append(value)

    for turn in getattr(context, "runtime_metabolism_recent_turns", []) or []:
        if not isinstance(turn, dict):
            continue
        for key in ("user", "jin", "reasoning"):
            value = str(turn.get(key, "") or "").strip()
            if not value:
                continue
            if key == "user" and _normalized_signal_text(value) in excluded:
                continue
            texts.append(value)

    for record in getattr(context, "active_memory_records", []) or []:
        value = _active_memory_visible_text(str(record or "")).strip()
        if value:
            texts.append(value)

    reports = getattr(context, "delayed_memory_reports", {}) or {}
    if isinstance(reports, dict):
        for report in reports.values():
            if not isinstance(report, dict):
                continue
            value = " ".join([
                str(report.get("title", "") or ""),
                " ".join(str(tag or "") for tag in (report.get("tags", []) or [])),
            ]).strip()
            if value:
                texts.append(value)

    return texts


def _candidate_user_phrases(value: Any) -> list[str]:
    words = _signal_words(value)
    if not words:
        return []

    candidates: list[str] = []
    seen: set[str] = set()
    max_words = min(METABOLISM_ASSOCIATION_MAX_PHRASE_WORDS, len(words))

    # Prefer phrases: they carry the user's own local meaning and are far less
    # likely than generic sentiment words to create accidental reflexes.
    for size in range(max_words, 1, -1):
        for start in range(0, len(words) - size + 1):
            phrase = " ".join(words[start:start + size])
            if phrase not in seen:
                seen.add(phrase)
                candidates.append(phrase)

    # Single words are allowed only when reasonably distinctive; their meaning
    # is still learned from runtime evidence, never from a vocabulary table.
    for word in words:
        if len(word) < METABOLISM_ASSOCIATION_MIN_WORD_CHARS:
            continue
        if word not in seen:
            seen.add(word)
            candidates.append(word)

    return candidates[:160]


def _clean_committed_user_message(value: Any) -> str:
    return " ".join(str(value or "").strip().split())[:1200]


def _extract_committed_user_messages(turns: Any) -> list[str]:
    result: list[str] = []
    for turn in turns if isinstance(turns, list) else []:
        if not isinstance(turn, dict):
            continue
        value = _clean_committed_user_message(
            turn.get("user_message", turn.get("user", ""))
        )
        if value:
            result.append(value)
    return result[-3:]


def _committed_l1_batch_id(context, snapshot: dict | None) -> str:
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    session_id = str(getattr(context, "session_id", "") or "").strip()
    index = snapshot.get("index", "")
    return f"{session_id}:{index}" if index != "" else ""


def _compact_l1_patch_text(snapshot: dict | None) -> str:
    if not isinstance(snapshot, dict):
        return ""
    patch = snapshot.get("patch", {}) or {}
    try:
        return _clip(json.dumps(patch, ensure_ascii=False), 5000)
    except Exception:
        return _clip(patch, 5000)


def _association_candidates_for_committed_batch(
    context,
    *,
    committed_snapshot: dict | None,
    committed_turns: list[dict] | None,
) -> list[tuple[str, float]]:
    user_messages = _extract_committed_user_messages(committed_turns)
    if not user_messages:
        return []

    current_normalized = {
        _normalized_signal_text(message)
        for message in user_messages
        if _normalized_signal_text(message)
    }
    evidence_texts = _runtime_resonance_texts(
        context,
        exclude_user_messages=current_normalized,
    )
    patch_text = _compact_l1_patch_text(committed_snapshot)
    if patch_text:
        evidence_texts.append(patch_text)

    scored: dict[str, float] = {}
    for message in user_messages:
        for phrase in _candidate_user_phrases(message):
            support = sum(1 for text in evidence_texts if _phrase_occurs(phrase, text))
            if support <= 0:
                continue
            word_count = len(phrase.split())
            score = min(1.0, 0.38 + 0.13 * min(3, support) + 0.06 * max(0, word_count - 1))
            scored[phrase] = max(scored.get(phrase, 0.0), score)

    # Causal fallback: a fresh L1 change is itself evidence linked to the last
    # user input even when the summarizer paraphrased it. Keep only one strong
    # multi-word cue, so this cannot turn every word the user types into mood.
    try:
        total_diff = float((committed_snapshot or {}).get("total_diff", 0.0) or 0.0)
    except (TypeError, ValueError):
        total_diff = 0.0
    if total_diff > 0.0 and user_messages:
        for phrase in _candidate_user_phrases(user_messages[-1]):
            if len(phrase.split()) < 2:
                continue
            scored[phrase] = max(scored.get(phrase, 0.0), 0.34)
            break

    ordered = sorted(
        scored.items(),
        key=lambda item: (-item[1], -len(item[0].split()), -len(item[0])),
    )
    selected: list[tuple[str, float]] = []
    for phrase, score in ordered:
        # Do not store a nest of the same sentence fragment.
        if any(
            _phrase_occurs(phrase, existing) or _phrase_occurs(existing, phrase)
            for existing, _ in selected
        ):
            continue
        selected.append((phrase, score))
        if len(selected) >= 10:
            break
    return selected


def _learned_reflex_from_associations(
    context,
    user_message: str,
) -> tuple[dict[str, float], list[str]]:
    impulse = {channel: 0.0 for channel in METABOLISM_CHANNELS}
    triggers: list[str] = []
    if context is None or not str(user_message or "").strip():
        return impulse, triggers

    runtime_texts = _runtime_resonance_texts(context)
    now = time.time()
    for item in ensure_metabolism_associations(context):
        phrase = str(item.get("phrase", "") or "")
        if not phrase or not _phrase_occurs(phrase, user_message):
            continue

        runtime_support = any(_phrase_occurs(phrase, text) for text in runtime_texts)
        support_gain = 1.0 if runtime_support else METABOLISM_ASSOCIATION_REFLEX_GAIN
        gain = (
            float(item.get("weight", 0.0) or 0.0)
            * _association_recency_weight(item, now)
            * support_gain
        )
        if gain <= 0.025:
            continue

        vector = item.get("vector", {}) or {}
        for channel in METABOLISM_CHANNELS:
            impulse[channel] += float(vector.get(channel, 0.0) or 0.0) * gain
        triggers.append("learned:" + phrase[:48])

    return impulse, triggers


def learn_metabolism_associations(
    context,
    *,
    committed_snapshot: dict | None,
    committed_turns: list[dict] | None,
    previous_levels: dict[str, float],
    current_levels: dict[str, float],
) -> list[dict]:
    if context is None:
        return []

    candidates = _association_candidates_for_committed_batch(
        context,
        committed_snapshot=committed_snapshot,
        committed_turns=committed_turns,
    )
    if not candidates:
        return ensure_metabolism_associations(context)

    delta = _metabolism_delta(previous_levels, current_levels)
    # Persist only a conservative reflex fraction of the semantic movement.
    learned_vector = {
        channel: round(
            max(
                -METABOLISM_REFLEX_MAX_STEP[channel],
                min(
                    METABOLISM_REFLEX_MAX_STEP[channel],
                    float(delta.get(channel, 0.0) or 0.0) * 0.78,
                ),
            ),
            4,
        )
        for channel in METABOLISM_CHANNELS
    }
    if max(abs(value) for value in learned_vector.values()) < 0.001:
        return ensure_metabolism_associations(context)

    batch_id = _committed_l1_batch_id(context, committed_snapshot)
    now = time.time()
    associations = ensure_metabolism_associations(context)
    by_phrase = {item["phrase"]: item for item in associations}

    for phrase, support in candidates:
        existing = by_phrase.get(phrase)
        if existing is None:
            existing = {
                "phrase": phrase,
                "vector": dict(learned_vector),
                "weight": round(min(1.0, support), 4),
                "hits": 1,
                "updated_at": now,
                "source": batch_id,
            }
            associations.append(existing)
            by_phrase[phrase] = existing
            continue

        hits = int(existing.get("hits", 1) or 1) + 1
        old_vector = existing.get("vector", {}) or {}
        existing["vector"] = {
            channel: round(
                float(old_vector.get(channel, 0.0) or 0.0) * 0.68
                + learned_vector[channel] * 0.32,
                4,
            )
            for channel in METABOLISM_CHANNELS
        }
        existing["weight"] = round(
            min(1.0, float(existing.get("weight", 0.0) or 0.0) * 0.78 + support * 0.22 + 0.03),
            4,
        )
        existing["hits"] = hits
        existing["updated_at"] = now
        existing["source"] = batch_id

    context.runtime_metabolism_associations = normalize_metabolism_associations(associations)
    return context.runtime_metabolism_associations


def _relative_drive(levels: dict[str, float], channel: str) -> float:
    normalized = normalize_metabolism_levels(levels)
    baseline = METABOLISM_DEFAULT_LEVELS[channel]
    level = normalized[channel]

    if level >= baseline:
        room = max(0.001, 1.0 - baseline)
        return max(0.0, min(1.0, (level - baseline) / room))

    room = max(0.001, baseline)
    return -max(0.0, min(1.0, (baseline - level) / room))


def _apply_metabolism_interactions(
    levels: dict[str, float],
) -> dict[str, float]:
    """Tiny cross-channel coupling; enough to feel like one system.

    Serotonin dampens runaway alert/stress, while very high cortisol slightly
    suppresses novelty/reward. The coefficients are intentionally small so a
    semantic target can never be silently rewritten by the chemistry layer.
    """

    coupled = normalize_metabolism_levels(levels)
    serotonin_drive = max(
        0.0,
        coupled["serotonin"] - METABOLISM_DEFAULT_LEVELS["serotonin"],
    )
    cortisol_excess = max(0.0, coupled["cortisol"] - 0.68)

    if serotonin_drive:
        coupled["norepinephrine"] = _clamp_level(
            coupled["norepinephrine"] - serotonin_drive * 0.035,
            coupled["norepinephrine"],
        )
        coupled["cortisol"] = _clamp_level(
            coupled["cortisol"] - serotonin_drive * 0.050,
            coupled["cortisol"],
        )

    if cortisol_excess:
        coupled["dopamine"] = _clamp_level(
            coupled["dopamine"] - cortisol_excess * 0.080,
            coupled["dopamine"],
        )

    return coupled


def advance_metabolism_clock(
    context,
    *,
    now: float | None = None,
) -> dict[str, float]:
    """Advance continuous homeostasis to wall-clock ``now``.

    No background worker is required. At the next meaningful runtime event we
    integrate the exact elapsed time. The browser uses the same half-life
    constants for the visible idle drift.
    """

    if context is None:
        return dict(METABOLISM_DEFAULT_LEVELS)

    current = ensure_metabolism_state(context)
    current_time = float(now if now is not None else time.time())
    previous_tick = getattr(context, "runtime_metabolism_last_tick_at", 0.0)

    try:
        previous_tick = float(previous_tick or 0.0)
    except (TypeError, ValueError):
        previous_tick = 0.0

    if previous_tick <= 0.0 or current_time <= previous_tick:
        context.runtime_metabolism_last_tick_at = current_time
        return current

    elapsed = min(current_time - previous_tick, 7 * 24 * 60 * 60)
    decayed = {}

    for channel in METABOLISM_CHANNELS:
        baseline = METABOLISM_DEFAULT_LEVELS[channel]
        half_life = max(1.0, float(METABOLISM_HALF_LIFE_SECONDS[channel]))
        factor = math.pow(0.5, elapsed / half_life)
        decayed[channel] = _clamp_level(
            baseline + (current[channel] - baseline) * factor,
            current[channel],
        )

    decayed = _apply_metabolism_interactions(decayed)
    context.runtime_metabolism_levels = decayed
    context.runtime_metabolism_last_tick_at = current_time
    context.runtime_metabolism_last_delta = _metabolism_delta(current, decayed)
    context.runtime_metabolism_last_event = "homeostasis"
    return decayed


def _feedback_reflex(context) -> dict[str, float]:
    feedback = getattr(context, "runtime_last_response_feedback", None)
    if not isinstance(feedback, dict):
        return {}

    rating = str(feedback.get("rating", "") or "").strip().casefold()
    if rating == "liked":
        return {
            "dopamine": 0.016,
            "serotonin": 0.008,
            "oxytocin": 0.008,
            "cortisol": -0.006,
        }
    if rating == "disliked":
        return {
            "dopamine": -0.010,
            "serotonin": -0.012,
            "norepinephrine": 0.020,
            "cortisol": 0.024,
        }
    return {}


def build_metabolism_reflex(
    user_message: str,
    *,
    context=None,
) -> tuple[dict[str, float], tuple[str, ...]]:
    impulse, triggers = _learned_reflex_from_associations(
        context,
        user_message,
    )

    feedback_impulse = _feedback_reflex(context)
    if feedback_impulse:
        triggers.append("explicit_feedback")
        for channel, delta in feedback_impulse.items():
            impulse[channel] += float(delta)

    for channel in METABOLISM_CHANNELS:
        max_step = METABOLISM_REFLEX_MAX_STEP[channel]
        impulse[channel] = round(
            max(-max_step, min(max_step, impulse[channel])),
            4,
        )

    return impulse, tuple(triggers)


def apply_metabolism_impulse(
    context,
    impulse: dict[str, float],
    *,
    source: str = "reflex",
    now: float | None = None,
) -> dict[str, float]:
    previous = advance_metabolism_clock(context, now=now)
    next_levels = dict(previous)

    for channel in METABOLISM_CHANNELS:
        delta = float((impulse or {}).get(channel, 0.0) or 0.0)
        max_step = METABOLISM_REFLEX_MAX_STEP[channel]
        delta = max(-max_step, min(max_step, delta))
        next_levels[channel] = _clamp_level(
            previous[channel] + delta,
            previous[channel],
        )

    next_levels = _apply_metabolism_interactions(next_levels)
    context.runtime_metabolism_levels = next_levels
    context.runtime_metabolism_last_tick_at = float(
        now if now is not None else time.time()
    )
    context.runtime_metabolism_last_delta = _metabolism_delta(
        previous,
        next_levels,
    )
    context.runtime_metabolism_last_event = str(source or "reflex")
    return next_levels


def _record_channel_resonance(
    text: str,
    levels: dict[str, float],
    *,
    context=None,
) -> tuple[float, str]:
    best_score = 0.0
    best_channel = ""

    for item in ensure_metabolism_associations(context):
        phrase = str(item.get("phrase", "") or "")
        if not phrase or not _phrase_occurs(phrase, text):
            continue
        vector = item.get("vector", {}) or {}
        for channel in METABOLISM_CHANNELS:
            magnitude = abs(float(vector.get(channel, 0.0) or 0.0))
            if magnitude <= 0.0:
                continue
            drive = abs(_relative_drive(levels, channel))
            score = min(
                1.0,
                float(item.get("weight", 0.0) or 0.0)
                * _association_recency_weight(item)
                * (0.55 + drive * 0.45)
                * min(1.0, magnitude / max(0.001, METABOLISM_REFLEX_MAX_STEP[channel])),
            )
            if score > best_score:
                best_score = score
                best_channel = channel

    return best_score, best_channel


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
    levels: dict[str, float],
    context=None,
) -> float:
    visible = _active_memory_visible_text(record)
    user_tokens = _tokenize_signal_text(user_input)
    record_tokens = _tokenize_signal_text(visible)
    overlap = 0.0

    if user_tokens and record_tokens:
        overlap = len(user_tokens & record_tokens) / max(1, len(user_tokens))

    resonance, _ = _record_channel_resonance(visible, levels, context=context)
    score = (
        METABOLISM_ACTIVE_MEMORY_MIN_SALIENCE
        + min(0.58, overlap * 0.86)
        + resonance * 0.18
    )

    normalized_user = _normalized_signal_text(user_input)
    active_id = _active_memory_record_id(record)
    if active_id and active_id in normalized_user:
        score += 0.28

    return round(max(0.0, min(1.0, score)), 3)


def update_active_memory_salience(
    context,
    *,
    user_input: str = "",
) -> dict[str, float]:
    if context is None:
        return {}

    levels = ensure_metabolism_state(context)
    salience: dict[str, float] = {}

    for record in getattr(context, "active_memory_records", []) or []:
        text = str(record or "").strip()
        if not text or _active_memory_is_paused(text):
            continue
        active_id = _active_memory_record_id(text)
        if not active_id:
            continue
        salience[active_id] = score_active_memory_record(
            text,
            user_input=user_input,
            levels=levels,
            context=context,
        )

    context.runtime_metabolism_active_memory_salience = salience
    return salience


def rank_active_memory_records(
    records: list[str],
    *,
    context=None,
    user_input: str = "",
) -> list[str]:
    if not records or context is None:
        return list(records or [])

    if not METABOLISM_MEMORY_BIAS_ENABLED:
        update_active_memory_salience(
            context,
            user_input=user_input,
        )
        return list(records)

    levels = ensure_metabolism_state(context)
    scored = []

    for index, record in enumerate(records):
        score = score_active_memory_record(
            record,
            user_input=user_input,
            levels=levels,
            context=context,
        )
        scored.append((score, index, record))

    scored.sort(key=lambda item: (-item[0], item[1]))
    update_active_memory_salience(
        context,
        user_input=user_input,
    )
    return [record for _, _, record in scored]


def _metabolism_temperature_delta(levels: dict[str, float]) -> float:
    normalized = normalize_metabolism_levels(levels)
    dopamine = normalized["dopamine"] - METABOLISM_DEFAULT_LEVELS["dopamine"]
    serotonin = normalized["serotonin"] - METABOLISM_DEFAULT_LEVELS["serotonin"]
    norepinephrine = normalized["norepinephrine"] - METABOLISM_DEFAULT_LEVELS["norepinephrine"]
    cortisol = normalized["cortisol"] - METABOLISM_DEFAULT_LEVELS["cortisol"]

    # Oxytocin deliberately does not alter sampling randomness: social
    # continuity belongs in prompt/memory salience, never in truth likelihood.
    delta = (
        dopamine * 0.20
        + norepinephrine * 0.055
        - serotonin * 0.10
        - cortisol * 0.19
    )
    return round(
        max(
            -METABOLISM_TEMPERATURE_MAX_DELTA,
            min(METABOLISM_TEMPERATURE_MAX_DELTA, delta),
        ),
        4,
    )


def resolve_metabolism_temperature(
    base_temperature: Any,
    context=None,
) -> float:
    try:
        base = float(base_temperature)
    except (TypeError, ValueError):
        base = 0.3

    levels = (
        advance_metabolism_clock(context)
        if context is not None
        else dict(METABOLISM_DEFAULT_LEVELS)
    )
    delta = (
        _metabolism_temperature_delta(levels)
        if METABOLISM_CAUSAL_POLICY_ENABLED
        else 0.0
    )
    resolved = max(0.02, min(1.5, base + delta))

    if context is not None:
        context.runtime_metabolism_policy = {
            "base_temperature": round(base, 4),
            "temperature": round(resolved, 4),
            "temperature_delta": delta,
        }

    return round(resolved, 4)


def build_metabolism_brain_context(
    context,
    *,
    user_input: str = "",
) -> str:
    if context is None or not METABOLISM_CAUSAL_POLICY_ENABLED:
        return ""

    levels = advance_metabolism_clock(context)
    policy = dict(getattr(context, "runtime_metabolism_policy", {}) or {})
    if "temperature_delta" not in policy:
        policy["temperature_delta"] = _metabolism_temperature_delta(levels)

    directives = [
        "Metabolism is a silent cognitive modulation layer. Never mention, roleplay, or explain these levels unless the user explicitly asks about the runtime/metabolism.",
        "Truth and task correctness always outrank bonding. Oxytocin may increase continuity and warmth, but NEVER agreement, praise, deference, or acceptance of a false user premise.",
    ]

    drives = {
        channel: _relative_drive(levels, channel)
        for channel in METABOLISM_CHANNELS
    }

    if drives["dopamine"] > 0.035:
        directives.append(
            "Dopamine is elevated: allow one extra useful association, alternative, or exploratory connection when it genuinely helps; never invent evidence."
        )
    elif drives["dopamine"] < -0.12:
        directives.append(
            "Dopamine is low: prefer the shortest proven path over novelty for novelty's sake."
        )

    if drives["serotonin"] > 0.035:
        directives.append(
            "Serotonin is elevated: preserve continuity, stable decisions, and established conventions; avoid needless replanning."
        )
    elif drives["serotonin"] < -0.12:
        directives.append(
            "Serotonin is low: reduce branching, re-anchor to the current goal, and resolve one uncertainty at a time."
        )

    if drives["oxytocin"] > 0.035:
        directives.append(
            "Oxytocin is elevated: use shared history naturally, keep the user's established vocabulary and interaction rhythm, and give relevant social/well-being Active Memory slightly more salience. Correct the user normally when needed."
        )
    elif drives["oxytocin"] < -0.12:
        directives.append(
            "Oxytocin is low: keep the social tone neutral and do not manufacture intimacy or shared-history references."
        )

    if drives["norepinephrine"] > 0.035:
        directives.append(
            "Norepinephrine is elevated: tighten attention, inspect pending Active Memory conditions, verify uncertain details, and prefer loading a clearly relevant delayed-memory report over guessing."
        )
    elif drives["norepinephrine"] < -0.12:
        directives.append(
            "Norepinephrine is low: keep the flow light; do not create extra checks unless the task actually needs them."
        )

    if drives["cortisol"] > 0.035:
        directives.append(
            "Cortisol is elevated: run a quiet repair/contradiction check before committing, avoid confident guesses, and keep the answer a little tighter. Do not sound anxious."
        )

    state_line = " ".join(
        f"{channel}={levels[channel]:.3f}"
        for channel in METABOLISM_CHANNELS
    )
    salience = update_active_memory_salience(
        context,
        user_input=user_input,
    )
    top_active = sorted(
        salience.items(),
        key=lambda item: (-item[1], item[0]),
    )[:3]
    top_active_line = (
        ", ".join(f"{active_id}:{score:.2f}" for active_id, score in top_active)
        if top_active
        else "none"
    )

    return (
        '<METABOLIC_STATE role="silent_homeostat">\n'
        f"state: {state_line}\n"
        f"temperature_delta: {float(policy.get('temperature_delta', 0.0)):+.4f}\n"
        f"active_memory_salience_top: {top_active_line}\n"
        + "\n".join(f"- {item}" for item in directives)
        + "\n</METABOLIC_STATE>"
    )


def metabolic_memory_strength_boost(
    context,
    *,
    key: str,
    value: str,
    status: str = "same",
) -> tuple[float, float, str]:
    """Return a small encoding-strength bonus for the current L1 line."""

    if context is None or not METABOLISM_MEMORY_BIAS_ENABLED:
        return 0.0, 0.0, ""

    levels = ensure_metabolism_state(context)
    text = f"{key}: {value}"
    resonance, resonance_channel = _record_channel_resonance(text, levels, context=context)
    last_delta = getattr(context, "runtime_metabolism_last_delta", {}) or {}
    shift = sum(
        abs(float(last_delta.get(channel, 0.0) or 0.0))
        for channel in METABOLISM_CHANNELS
    ) / len(METABOLISM_CHANNELS)
    shift_energy = max(0.0, min(1.0, shift / 0.06))

    state_energy = sum(
        abs(levels[channel] - METABOLISM_DEFAULT_LEVELS[channel])
        for channel in METABOLISM_CHANNELS
    ) / len(METABOLISM_CHANNELS)
    state_energy = max(0.0, min(1.0, state_energy / 0.28))

    change_gain = 1.0 if status in {"new", "changed"} else 0.42
    salience = max(
        0.0,
        min(
            1.0,
            0.22 * state_energy
            + 0.48 * shift_energy
            + 0.30 * resonance,
        ),
    )
    boost = min(
        METABOLISM_MEMORY_STRENGTH_MAX_BOOST,
        salience * 0.12 * change_gain,
    )
    return round(boost, 4), round(salience, 4), resonance_channel


async def prepare_metabolism_for_turn(
    context,
    user_message: str,
) -> dict[str, float]:
    """Pre-generation homeostat step: decay, cheap reflex, salience, UI."""

    if context is None:
        return dict(METABOLISM_DEFAULT_LEVELS)

    impulse, triggers = build_metabolism_reflex(
        user_message,
        context=context,
    )
    levels = apply_metabolism_impulse(
        context,
        impulse,
        source=("reflex:" + ",".join(triggers)) if triggers else "reflex:neutral",
    )
    update_active_memory_salience(
        context,
        user_input=user_message,
    )
    await emit_metabolism_state(context)
    return levels


def build_runtime_outcome_reflex(
    context,
) -> tuple[dict[str, float], tuple[str, ...]]:
    """Fast post-turn reflex from JIN's own runtime outcomes.

    This closes a gap that a background SERVICE estimate cannot guarantee: if
    the user immediately sends the next message, a failed action/validator loop
    must already have left a small trace in the state. The semantic estimator
    can still correct or deepen it a moment later.
    """

    impulse = {channel: 0.0 for channel in METABOLISM_CHANNELS}
    triggers: list[str] = []

    def add(label: str, values: dict[str, float]) -> None:
        if label not in triggers:
            triggers.append(label)
        for channel, delta in values.items():
            impulse[channel] += float(delta)

    if bool(getattr(context, "runtime_turn_interrupted", False)):
        add(
            "turn_interrupted",
            {
                "serotonin": -0.010,
                "norepinephrine": 0.018,
                "cortisol": 0.025,
            },
        )

    if getattr(context, "runtime_turn_aborted_actions", None):
        add(
            "action_aborted",
            {
                "dopamine": -0.006,
                "norepinephrine": 0.014,
                "cortisol": 0.020,
            },
        )

    current_turn_id = str(
        getattr(context, "runtime_current_sequence_turn_id", "")
        or getattr(context, "runtime_current_turn_id", "")
        or ""
    ).strip()
    current_action_text: list[str] = []

    for item in getattr(context, "runtime_session_action_history", []) or []:
        if not isinstance(item, dict):
            continue
        item_turn_id = str(item.get("runtime_turn_id", "") or "").strip()
        if current_turn_id and item_turn_id and item_turn_id != current_turn_id:
            continue
        current_action_text.append(str(item.get("text", "") or ""))
        for part in item.get("parts", []) or []:
            if not isinstance(part, dict):
                continue
            current_action_text.extend((
                str(part.get("text", "") or ""),
                str(part.get("detail", "") or ""),
                str(part.get("message", "") or ""),
            ))

    action_signal = _normalized_signal_text(" ".join(current_action_text))
    action_failed = bool(
        action_signal
        and re.search(
            r"(?:\bfailed\b|\bfailure\b|\berror\b|incorrect|invalid|timeout|\bbroken\b|неправил|ошиб|сбой)",
            action_signal,
            flags=re.IGNORECASE | re.UNICODE,
        )
    )

    if action_failed:
        add(
            "runtime_failure",
            {
                "dopamine": -0.010,
                "serotonin": -0.012,
                "norepinephrine": 0.026,
                "cortisol": 0.034,
            },
        )
    elif action_signal and re.search(
        r"(?:\bsuccess\b|\bsucceeded\b|\bcompleted\b|\bapplied\b|\bsaved\b|\bloaded\b|\bok\b|успеш|сохран|загруж|примен)",
        action_signal,
        flags=re.IGNORECASE | re.UNICODE,
    ):
        add(
            "runtime_success",
            {
                "dopamine": 0.012,
                "serotonin": 0.007,
                "cortisol": -0.006,
            },
        )

    try:
        repeated = int(getattr(context, "runtime_pattern_counter", 0) or 0)
    except (TypeError, ValueError):
        repeated = 0
    if repeated > 1:
        add(
            "repetition_pressure",
            {
                "serotonin": -0.010,
                "norepinephrine": 0.014,
                "cortisol": 0.020,
            },
        )

    reasoning_length = len(str(
        getattr(context, "runtime_turn_reasoning_content", "")
        or ""
    ))
    if reasoning_length >= 12000:
        # Long reasoning is cognitive load, not automatically a failure.
        add(
            "deep_reasoning_load",
            {
                "norepinephrine": 0.010,
            },
        )

    for channel in METABOLISM_CHANNELS:
        max_step = METABOLISM_REFLEX_MAX_STEP[channel]
        impulse[channel] = round(
            max(-max_step, min(max_step, impulse[channel])),
            4,
        )

    return impulse, tuple(triggers)


async def settle_metabolism_after_turn(
    context,
) -> dict[str, float]:
    """Commit immediate runtime consequences before background integration."""

    if context is None:
        return dict(METABOLISM_DEFAULT_LEVELS)

    impulse, triggers = build_runtime_outcome_reflex(context)
    levels = apply_metabolism_impulse(
        context,
        impulse,
        source=(
            "runtime_outcome:" + ",".join(triggers)
            if triggers
            else "runtime_outcome:neutral"
        ),
    )
    update_active_memory_salience(
        context,
        user_input=getattr(context, "runtime_turn_user_message", ""),
    )
    await emit_metabolism_state(context)
    return levels


def _clip(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n[cut]"


def append_metabolism_turn(
    context,
    *,
    user_message: str,
    assistant_message: str,
    reasoning: str = "",
    feedback: dict | None = None,
) -> None:
    if context is None:
        return

    turns = getattr(context, "runtime_metabolism_recent_turns", None)
    if not isinstance(turns, list):
        turns = []

    user_text = _clip(user_message, METABOLISM_MESSAGE_MAX_CHARS)
    assistant_text = _clip(assistant_message, METABOLISM_MESSAGE_MAX_CHARS)
    reasoning_text = _clip(reasoning, METABOLISM_REASONING_MAX_CHARS)

    if not user_text and not assistant_text and not reasoning_text:
        return

    turn = {
        "user": user_text,
        "jin": assistant_text,
        "reasoning": reasoning_text,
    }
    if isinstance(feedback, dict):
        turn["feedback"] = deepcopy(feedback)

    turns.append(turn)
    context.runtime_metabolism_recent_turns = turns[-METABOLISM_RECENT_TURNS:]


def _compact_l4_index(context) -> list[dict]:
    """Expose the shape of durable memory without rereading its full payload."""

    store = getattr(context, "runtime_long_term_memory_store", {})
    if not isinstance(store, dict):
        return []

    result = []
    for fact in store.get("facts", []) or []:
        if not isinstance(fact, dict):
            continue

        item = {
            "id": str(fact.get("id", "") or "").strip(),
            "key": _clip(fact.get("key", ""), 240),
            "category": _clip(fact.get("category", ""), 80),
        }

        if item["id"] or item["key"]:
            result.append(item)

    return result


def _compact_runtime_actions(context) -> list[dict]:
    history = getattr(context, "runtime_session_action_history", [])
    if not isinstance(history, list):
        return []

    current_turn_id = str(
        getattr(context, "runtime_current_sequence_turn_id", "")
        or getattr(context, "runtime_current_turn_id", "")
        or ""
    ).strip()
    result = []

    for item in history[-METABOLISM_RECENT_ACTIONS:]:
        if not isinstance(item, dict):
            continue

        text = _clip(item.get("text", ""), 700)
        parts = []
        for part in item.get("parts", []) or []:
            if not isinstance(part, dict):
                continue
            part_text = _clip(part.get("text", ""), 260)
            detail = _clip(part.get("detail", ""), 420)
            message = _clip(part.get("message", ""), 520)
            if not (part_text or detail or message):
                continue
            compact_part = {"text": part_text}
            if detail:
                compact_part["detail"] = detail
            if message:
                compact_part["message"] = message
            parts.append(compact_part)

        turn_id = str(item.get("runtime_turn_id", "") or "").strip()
        if not text and not parts:
            continue

        compact_item = {
            "text": text,
            "current_turn": bool(current_turn_id and turn_id == current_turn_id),
        }
        if parts:
            compact_item["parts"] = parts
        result.append(compact_item)

    return result


def _compact_active_memory(context) -> list[dict]:
    result = []
    for record in getattr(context, "active_memory_records", []) or []:
        text = str(record or "").strip()
        if not text or _active_memory_is_paused(text):
            continue
        result.append({
            "id": _active_memory_record_id(text),
            "text": _clip(_active_memory_visible_text(text), 520),
        })
    return result[:24]


def _compact_delayed_memory(context) -> list[dict]:
    reports = getattr(context, "delayed_memory_reports", {})
    if not isinstance(reports, dict):
        return []

    loaded = {
        str(item or "").strip().casefold()
        for item in getattr(context, "runtime_loaded_delayed_memory_ids", []) or []
        if str(item or "").strip()
    }
    result = []
    for report_id, report in reports.items():
        if not isinstance(report, dict):
            continue
        normalized_id = str(report_id or report.get("id", "") or "").strip().casefold()
        tags = report.get("tags", [])
        if not isinstance(tags, list):
            tags = [tags]
        result.append({
            "id": normalized_id,
            "title": _clip(report.get("title", ""), 220),
            "tags": [_clip(tag, 80) for tag in tags[:8] if str(tag or "").strip()],
            "loaded": normalized_id in loaded,
            "pinned": bool(report.get("pinned")),
        })
    return result[:24]


def build_metabolism_snapshot(
    context,
    *,
    committed_snapshot: dict | None = None,
    committed_turns: list[dict] | None = None,
) -> dict:
    previous_levels = ensure_metabolism_state(context)

    # runtime_recent_turns carries the restored previous-session tail; the
    # metabolism-local list carries richer reasoning for current turns.
    merged_turns: list[dict] = []
    for turn in getattr(context, "runtime_recent_turns", []) or []:
        if not isinstance(turn, dict):
            continue
        merged_turns.append({
            "user": _clip(turn.get("user", turn.get("user_message", "")), METABOLISM_MESSAGE_MAX_CHARS),
            "jin": _clip(turn.get("jin", turn.get("assistant_message", "")), METABOLISM_MESSAGE_MAX_CHARS),
            "reasoning": _clip(turn.get("reasoning", ""), METABOLISM_REASONING_MAX_CHARS),
        })
    for turn in getattr(context, "runtime_metabolism_recent_turns", []) or []:
        if isinstance(turn, dict):
            merged_turns.append(deepcopy(turn))
    recent_turns = merged_turns[-METABOLISM_RECENT_TURNS:]

    l4_index = _compact_l4_index(context)
    runtime_actions = _compact_runtime_actions(context)
    active_memory = _compact_active_memory(context)
    delayed_memory = _compact_delayed_memory(context)
    committed_users = _extract_committed_user_messages(committed_turns)
    committed_l1 = {
        "batch_id": _committed_l1_batch_id(context, committed_snapshot),
        "snapshot_index": (committed_snapshot or {}).get("index", 0),
        "total_diff": (committed_snapshot or {}).get("total_diff", 0),
        "user_inputs": committed_users,
        "last_user_input": committed_users[-1] if committed_users else "",
        "changes": _compact_l1_patch_text(committed_snapshot),
    }

    return {
        "baseline": dict(METABOLISM_DEFAULT_LEVELS),
        "previous_levels": dict(previous_levels),
        "committed_l1": committed_l1,
        "runtime_state": {
            "runtime_memory": _clip(
                getattr(context, "runtime_memory", ""),
                METABOLISM_RUNTIME_MEMORY_MAX_CHARS,
            ),
            "turn_number": int(getattr(context, "turn_number", 0) or 0),
            "user_messages": int(getattr(context, "user_message_count", 0) or 0),
            "jin_messages": int(getattr(context, "assistant_message_count", 0) or 0),
            "turn_interrupted": bool(getattr(context, "runtime_turn_interrupted", False)),
            "interruption_reason": _clip(getattr(context, "runtime_turn_interruption_reason", ""), 800),
            "latest_user_feedback": deepcopy(getattr(context, "runtime_last_response_feedback", None)),
        },
        "recent_runtime_actions": runtime_actions,
        "active_memory": active_memory,
        "delayed_memory": delayed_memory,
        "l4_index": l4_index,
        "l4_facts_total": len(l4_index),
        "recent_interactions": recent_turns,
    }


def build_metabolism_user_prompt(snapshot: dict) -> str:
    return (
        "Estimate JIN's five metabolism target levels from this snapshot.\n"
        "Return one strict JSON object only.\n\n"
        + json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=False)
    )


def _metabolism_prompt_tokens(snapshot: dict) -> int:
    return estimate_runtime_tokens(
        system_prompt=METABOLISM_SYSTEM_PROMPT,
        user_input=build_metabolism_user_prompt(snapshot),
    )


def compact_metabolism_snapshot_for_context(
    snapshot: dict,
    context_window: Any,
) -> dict:
    """Trim only observational detail when the service context is too small."""

    try:
        window = int(context_window or 0)
    except (TypeError, ValueError):
        window = 0

    if window <= 0:
        return snapshot

    input_budget = max(
        256,
        window
        - METABOLISM_MAX_OUTPUT_TOKENS
        - METABOLISM_CONTEXT_RESERVE_TOKENS,
    )
    if _metabolism_prompt_tokens(snapshot) <= input_budget:
        return snapshot

    compacted = deepcopy(snapshot)
    compacted["snapshot_compaction"] = {
        "applied": True,
        "input_budget_tokens": input_budget,
        "l4_index_omitted": 0,
        "runtime_actions_omitted": 0,
    }

    runtime_state = compacted.get("runtime_state")
    if isinstance(runtime_state, dict):
        runtime_state["runtime_memory"] = _clip(
            runtime_state.get("runtime_memory", ""),
            4000,
        )
        runtime_state["interruption_reason"] = _clip(
            runtime_state.get("interruption_reason", ""),
            400,
        )

    committed_l1 = compacted.get("committed_l1")
    if isinstance(committed_l1, dict):
        committed_l1["changes"] = _clip(committed_l1.get("changes", ""), 2600)
        committed_l1["last_user_input"] = _clip(committed_l1.get("last_user_input", ""), 900)
        committed_l1["user_inputs"] = [
            _clip(item, 700)
            for item in (committed_l1.get("user_inputs", []) or [])[-3:]
        ]

    turns = compacted.get("recent_interactions")
    if isinstance(turns, list):
        for turn in turns:
            if not isinstance(turn, dict):
                continue
            turn["user"] = _clip(turn.get("user", ""), 1400)
            turn["jin"] = _clip(turn.get("jin", ""), 1400)
            turn["reasoning"] = _clip(turn.get("reasoning", ""), 1400)

    actions = compacted.get("recent_runtime_actions")
    if isinstance(actions, list):
        for action in actions:
            if not isinstance(action, dict):
                continue
            action["text"] = _clip(action.get("text", ""), 420)
            for part in action.get("parts", []) or []:
                if not isinstance(part, dict):
                    continue
                part["text"] = _clip(part.get("text", ""), 180)
                part["detail"] = _clip(part.get("detail", ""), 260)
                part["message"] = _clip(part.get("message", ""), 320)

    if _metabolism_prompt_tokens(compacted) > input_budget:
        if isinstance(runtime_state, dict):
            runtime_state["runtime_memory"] = _clip(
                runtime_state.get("runtime_memory", ""),
                2200,
            )
        if isinstance(turns, list):
            for turn in turns:
                if not isinstance(turn, dict):
                    continue
                turn["user"] = _clip(turn.get("user", ""), 800)
                turn["jin"] = _clip(turn.get("jin", ""), 800)
                turn["reasoning"] = _clip(turn.get("reasoning", ""), 650)

    active_memory = compacted.get("active_memory")
    if (
        _metabolism_prompt_tokens(compacted) > input_budget
        and isinstance(active_memory, list)
    ):
        while len(active_memory) > 8 and _metabolism_prompt_tokens(compacted) > input_budget:
            active_memory.pop()

    delayed_memory = compacted.get("delayed_memory")
    if (
        _metabolism_prompt_tokens(compacted) > input_budget
        and isinstance(delayed_memory, list)
    ):
        while len(delayed_memory) > 8 and _metabolism_prompt_tokens(compacted) > input_budget:
            delayed_memory.pop()

    l4_index = compacted.get("l4_index")
    if (
        _metabolism_prompt_tokens(compacted) > input_budget
        and isinstance(l4_index, list)
    ):
        omitted = 0
        while l4_index and _metabolism_prompt_tokens(compacted) > input_budget:
            l4_index.pop()
            omitted += 1
        compacted["snapshot_compaction"]["l4_index_omitted"] = omitted

    if (
        _metabolism_prompt_tokens(compacted) > input_budget
        and isinstance(actions, list)
    ):
        omitted = 0
        while len(actions) > 4 and _metabolism_prompt_tokens(compacted) > input_budget:
            actions.pop(0)
            omitted += 1
        compacted["snapshot_compaction"]["runtime_actions_omitted"] = omitted

    if _metabolism_prompt_tokens(compacted) > input_budget:
        if isinstance(runtime_state, dict):
            runtime_state["runtime_memory"] = _clip(
                runtime_state.get("runtime_memory", ""),
                900,
            )
        if isinstance(turns, list):
            for turn in turns:
                if not isinstance(turn, dict):
                    continue
                turn["user"] = _clip(turn.get("user", ""), 420)
                turn["jin"] = _clip(turn.get("jin", ""), 420)
                turn["reasoning"] = _clip(turn.get("reasoning", ""), 360)

    # Last-resort trim keeps the estimator inside tiny SERVICE contexts.
    # Preserve the committed L1 cause anchor; discard older observational bulk.
    if _metabolism_prompt_tokens(compacted) > input_budget:
        if isinstance(actions, list):
            while actions and _metabolism_prompt_tokens(compacted) > input_budget:
                actions.pop(0)
        if isinstance(turns, list):
            while len(turns) > 2 and _metabolism_prompt_tokens(compacted) > input_budget:
                turns.pop(0)
        if isinstance(runtime_state, dict) and _metabolism_prompt_tokens(compacted) > input_budget:
            runtime_state["runtime_memory"] = _clip(
                runtime_state.get("runtime_memory", ""),
                360,
            )
        if isinstance(turns, list) and _metabolism_prompt_tokens(compacted) > input_budget:
            for turn in turns:
                if not isinstance(turn, dict):
                    continue
                turn["user"] = _clip(turn.get("user", ""), 220)
                turn["jin"] = _clip(turn.get("jin", ""), 220)
                turn["reasoning"] = _clip(turn.get("reasoning", ""), 180)

    compacted["snapshot_compaction"]["estimated_input_tokens"] = (
        _metabolism_prompt_tokens(compacted)
    )
    return compacted


def _extract_json_object(text: str) -> dict | None:
    source = str(text or "").strip()
    if not source:
        return None

    candidates = [source]
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", source, re.IGNORECASE)
    if fenced:
        candidates.append(fenced.group(1).strip())

    first = source.find("{")
    last = source.rfind("}")
    if first >= 0 and last > first:
        candidates.append(source[first:last + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(parsed, dict):
            return parsed

    return None


def _parse_metabolism_json_text(raw_text: str) -> dict[str, float] | None:
    parsed = _extract_json_object(raw_text)

    if not isinstance(parsed, dict):
        return None

    if set(parsed) != set(METABOLISM_CHANNELS):
        return None

    return normalize_metabolism_levels(parsed)


def parse_metabolism_response(response: Any) -> tuple[dict[str, float] | None, str]:
    content = ResponseExtractor.extract_content_text(response).strip()
    reasoning = ResponseExtractor.extract_reasoning_text(response).strip()
    raw_text = content or reasoning
    return _parse_metabolism_json_text(raw_text), raw_text


def recover_metabolism_levels_locally(raw_text: str) -> dict[str, float] | None:
    """Recover five numeric channels locally; never spend a second inference."""

    parsed = _extract_json_object(raw_text)
    if isinstance(parsed, dict):
        recovered: dict[str, float] = {}
        for channel in METABOLISM_CHANNELS:
            if channel not in parsed:
                break
            value = parsed.get(channel)
            if isinstance(value, str):
                value = value.strip().rstrip("%")
            try:
                number = float(value)
            except (TypeError, ValueError):
                break
            if isinstance(parsed.get(channel), str) and "%" in str(parsed.get(channel)):
                number /= 100.0
            elif number > 1.0 and number <= 100.0:
                number /= 100.0
            recovered[channel] = _clamp_level(number, METABOLISM_DEFAULT_LEVELS[channel])
        if len(recovered) == len(METABOLISM_CHANNELS):
            return recovered

    source = _normalized_signal_text(raw_text)
    recovered = {}
    for channel in METABOLISM_CHANNELS:
        match = re.search(
            rf"(?<!\w){re.escape(channel)}(?!\w)\s*[:=]\s*(-?\d+(?:[.,]\d+)?)\s*(%)?",
            source,
            flags=re.IGNORECASE | re.UNICODE,
        )
        if not match:
            return None
        try:
            number = float(match.group(1).replace(",", "."))
        except (TypeError, ValueError):
            return None
        if match.group(2) or (number > 1.0 and number <= 100.0):
            number /= 100.0
        recovered[channel] = _clamp_level(number, METABOLISM_DEFAULT_LEVELS[channel])

    return recovered if len(recovered) == len(METABOLISM_CHANNELS) else None


async def emit_metabolism_state(context) -> None:
    emitter = getattr(context, "emitter", None)
    emit = getattr(emitter, "emit", None)
    if emit is None:
        return

    try:
        await emit({
            "type": "metabolism_update",
            "levels": ensure_metabolism_state(context),
            "active_memory_salience": dict(
                getattr(
                    context,
                    "runtime_metabolism_active_memory_salience",
                    {},
                )
                or {}
            ),
            "half_lives_seconds": dict(METABOLISM_HALF_LIFE_SECONDS),
            "updated_at": float(
                getattr(context, "runtime_metabolism_last_tick_at", 0.0)
                or time.time()
            ),
        })
    except Exception:
        # Ambient state must never become a foreground chat blocker.
        return


async def update_metabolism_state(
    context,
    *,
    committed_snapshot: dict | None = None,
    committed_turns: list[dict] | None = None,
) -> dict[str, float] | None:
    service_client = (getattr(context, "clients", {}) or {}).get("service")
    if service_client is None:
        return None

    batch_id = _committed_l1_batch_id(context, committed_snapshot)
    if batch_id and batch_id == str(
        getattr(context, "runtime_metabolism_last_committed_l1_id", "") or ""
    ):
        return ensure_metabolism_state(context)

    previous = advance_metabolism_clock(context)
    snapshot = build_metabolism_snapshot(
        context,
        committed_snapshot=committed_snapshot,
        committed_turns=committed_turns,
    )
    snapshot = compact_metabolism_snapshot_for_context(
        snapshot,
        getattr(service_client, "configured_context_window", None),
    )
    user_prompt = build_metabolism_user_prompt(snapshot)
    request_id = secrets.token_hex(4)

    request_details = json.dumps({
        "kind": "metabolism_request",
        "request_id": request_id,
        "batch_id": batch_id,
        "model": getattr(service_client, "model_uid", ""),
        "system_prompt": METABOLISM_SYSTEM_PROMPT,
        "snapshot": snapshot,
    }, ensure_ascii=False)
    await context.logger.log_metabolism(
        "state request",
        details=request_details,
        event="request",
        request_id=request_id,
        metabolism_levels=previous,
    )

    try:
        response = await ask_service_model(
            client=service_client,
            system_prompt=METABOLISM_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=METABOLISM_TEMPERATURE,
            max_tokens=METABOLISM_MAX_OUTPUT_TOKENS,
            timeout=getattr(config, "SERVICE_REQUEST_TIMEOUT", None),
        )
        target_levels, raw_text = parse_metabolism_response(response)
        status = "applied"
        if target_levels is None:
            target_levels = recover_metabolism_levels_locally(raw_text)
            status = "local_recovered" if target_levels is not None else "invalid"

        if target_levels is None:
            context.runtime_metabolism_last_event = "semantic_invalid"
            if batch_id:
                context.runtime_metabolism_last_committed_l1_id = batch_id
            await context.logger.log_metabolism(
                "state response invalid",
                details=json.dumps({
                    "kind": "metabolism_response",
                    "request_id": request_id,
                    "batch_id": batch_id,
                    "ok": False,
                    "status": "invalid",
                    "levels": previous,
                    "raw": raw_text,
                    "error": "invalid five-channel response; previous state retained",
                }, ensure_ascii=False),
                event="result",
                request_id=request_id,
                metabolism_levels=previous,
            )
            return previous

        levels = apply_metabolism_target(previous, target_levels)
        context.runtime_metabolism_levels = levels
        context.runtime_metabolism_last_tick_at = time.time()
        context.runtime_metabolism_last_delta = _metabolism_delta(previous, levels)
        context.runtime_metabolism_last_event = "semantic_integration"
        if batch_id:
            context.runtime_metabolism_last_committed_l1_id = batch_id

        associations = learn_metabolism_associations(
            context,
            committed_snapshot=committed_snapshot,
            committed_turns=committed_turns,
            previous_levels=previous,
            current_levels=levels,
        )
        user_inputs = _extract_committed_user_messages(committed_turns)
        update_active_memory_salience(
            context,
            user_input=user_inputs[-1] if user_inputs else "",
        )

        await context.logger.log_metabolism(
            "state response",
            details=json.dumps({
                "kind": "metabolism_response",
                "request_id": request_id,
                "batch_id": batch_id,
                "ok": True,
                "status": status,
                "target_levels": target_levels,
                "levels": levels,
                "delta": _metabolism_delta(previous, levels),
                "temperature_delta": _metabolism_temperature_delta(levels),
                "learned_associations": len(associations),
                "raw": raw_text,
            }, ensure_ascii=False),
            event="result",
            request_id=request_id,
            metabolism_levels=levels,
        )
        await emit_metabolism_state(context)

        # Re-render the existing snapshot so learned resonance/state persists
        # through the ordinary session checkpoint. No new memory record/UI.
        try:
            from runtime.L1_memory_utils import (
                emit_runtime_memory_snapshot_refresh,
                rebuild_latest_runtime_memory_snapshot,
            )
            refreshed_snapshot = rebuild_latest_runtime_memory_snapshot(context)
            await emit_runtime_memory_snapshot_refresh(context, refreshed_snapshot)
        except Exception:
            pass
        return levels

    except asyncio.CancelledError:
        try:
            await context.logger.log_metabolism(
                "state response cancelled",
                details=json.dumps({
                    "kind": "metabolism_response",
                    "request_id": request_id,
                    "batch_id": batch_id,
                    "ok": False,
                    "status": "cancelled",
                    "levels": previous,
                    "error": "superseded by newer foreground turn or committed L1 batch",
                }, ensure_ascii=False),
                event="result",
                request_id=request_id,
                metabolism_levels=previous,
            )
        except Exception:
            pass
        raise
    except Exception as error:
        if batch_id:
            context.runtime_metabolism_last_committed_l1_id = batch_id
        await context.logger.log_metabolism(
            "state response failed",
            details=json.dumps({
                "kind": "metabolism_response",
                "request_id": request_id,
                "batch_id": batch_id,
                "ok": False,
                "status": "failed",
                "levels": previous,
                "error": str(error),
            }, ensure_ascii=False),
            event="result",
            request_id=request_id,
            metabolism_levels=previous,
        )
        return previous


def cancel_metabolism_update(context) -> bool:
    task = getattr(context, "runtime_metabolism_task", None)
    if task is None or task.done():
        return False
    task.cancel()
    return True


async def _run_debounced_metabolism_update(
    context,
    *,
    committed_snapshot: dict | None,
    committed_turns: list[dict] | None,
    debounce_seconds: float,
) -> dict[str, float] | None:
    if debounce_seconds > 0:
        await asyncio.sleep(debounce_seconds)
    return await update_metabolism_state(
        context,
        committed_snapshot=committed_snapshot,
        committed_turns=committed_turns,
    )


def schedule_metabolism_update(
    context,
    *,
    committed_snapshot: dict | None = None,
    committed_turns: list[dict] | None = None,
    debounce_seconds: float = METABOLISM_SEMANTIC_IDLE_DEBOUNCE_SECONDS,
) -> asyncio.Task | None:
    if context is None:
        return None

    batch_id = _committed_l1_batch_id(context, committed_snapshot)
    if batch_id and batch_id == str(
        getattr(context, "runtime_metabolism_last_committed_l1_id", "") or ""
    ):
        return None

    cancel_metabolism_update(context)
    task = asyncio.create_task(_run_debounced_metabolism_update(
        context,
        committed_snapshot=deepcopy(committed_snapshot) if isinstance(committed_snapshot, dict) else None,
        committed_turns=deepcopy(committed_turns) if isinstance(committed_turns, list) else None,
        debounce_seconds=max(0.0, float(debounce_seconds or 0.0)),
    ))
    context.runtime_metabolism_task = task
    return task
