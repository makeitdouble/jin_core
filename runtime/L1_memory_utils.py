import json
import re
from difflib import SequenceMatcher

from runtime.L1_memory_rules import (
    DEFAULT_RUNTIME_MEMORY,
    DURABLE_FLOOR,
    DURABLE_MEMORY_KEY_TOKENS,
    DURABLE_MEMORY_NEGATION_MARKERS,
    GENERIC_MEMORY_MATCH_KEYS,
    GENERIC_MEMORY_VALUE_SIMILARITY_MIN,
    HOT_THRESHOLD,
    HOT_TRACE_EXCLUDED_KEYS,
    INTERRUPTED_ASSISTANT_MEMORY_TEMPLATE,
    REPEATABLE_RUNTIME_MEMORY_KEY_FAMILIES,
    RUNTIME_MEMORY_CONFIRMATION_SUFFIX_PATTERN,
    RUNTIME_MEMORY_NUMBERED_KEY_PATTERN,
    RUNTIME_MEMORY_PLACEHOLDER_VALUES,
    RUNTIME_MEMORY_REPEATED_SLOT_SUFFIX_PATTERN,
    RUNTIME_RESPONSE_FEEDBACK_KEY,
    RUNTIME_USER_IDLE_KEY,
    STRENGTH_BOOST,
    STRENGTH_DECAY,
    STRENGTH_NEW_KEY,
    STRENGTH_PRESENCE_BOOST,
)
from runtime.L2_memory_utils import (
    extract_runtime_l2_pattern_evidence_lines,
)
from runtime.memory_common import (
    change_ratio,
)



CONFIRMATION_SUFFIX_RE = re.compile(
    RUNTIME_MEMORY_CONFIRMATION_SUFFIX_PATTERN,
    re.IGNORECASE,
)


REPEATED_SLOT_SUFFIX_RE = re.compile(
    RUNTIME_MEMORY_REPEATED_SLOT_SUFFIX_PATTERN,
    re.IGNORECASE,
)

NUMBERED_MEMORY_KEY_RE = re.compile(
    RUNTIME_MEMORY_NUMBERED_KEY_PATTERN,
)

RUNTIME_USER_MESSAGE_KEY = "user_message"
RUNTIME_LAST_JIN_RESPONSE_KEY = "last_jin_response"
RUNTIME_LAST_JIN_RESPONSE_FALLBACK_LIMIT = 180


def _split_repeated_user_message_metadata(
        value: str,
) -> tuple[str, str]:

    text = str(value or "")
    stripped = text.strip()

    if not stripped.startswith('"'):
        return text, ""

    match = REPEATED_SLOT_SUFFIX_RE.search(
        stripped
    )

    if (
            not match
            or match.end() != len(stripped)
    ):
        return text, ""

    body = stripped[:match.start()].strip()
    metadata = stripped[match.start():match.end()].strip()

    return body, metadata


def quote_runtime_user_message_value(
        user_message: str,
) -> str:

    body, metadata = _split_repeated_user_message_metadata(
        user_message
    )

    quote_value = body

    if metadata and body.startswith('"'):
        try:
            parsed_body = json.loads(
                body
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed_body = None

        if isinstance(
                parsed_body,
                str,
        ):
            quote_value = parsed_body

    quoted = json.dumps(
        str(quote_value),
        ensure_ascii=False,
    )

    if metadata:
        return f"{quoted} {metadata}"

    return quoted


def find_runtime_memory_entry_value(
        memory: str,
        key: str,
) -> str:

    target_key = normalize_memory_key(
        key
    )

    for line in parse_runtime_memory_lines(
            memory
    ):
        if (
                normalize_memory_key(
                    line.get(
                        "key",
                        "",
                    )
                )
                == target_key
        ):
            return (
                line.get(
                    "value",
                    "",
                )
                or ""
            ).strip()

    return ""


def build_last_jin_response_fallback(
        assistant_message: str,
) -> str:

    compact = re.sub(
        r"\s+",
        " ",
        str(assistant_message or ""),
    ).strip()

    if not compact:
        compact = "No complete assistant answer was delivered."

    if len(compact) <= RUNTIME_LAST_JIN_RESPONSE_FALLBACK_LIMIT:
        return compact

    return (
        compact[:RUNTIME_LAST_JIN_RESPONSE_FALLBACK_LIMIT - 3]
        .rstrip()
        + "..."
    )


def enforce_runtime_turn_fields(
        memory: str,
        *,
        user_message: str,
        assistant_message: str,
        previous_memory: str = "",
) -> str:

    updated_memory = upsert_runtime_memory_entry_text(
        memory,
        RUNTIME_USER_MESSAGE_KEY,
        quote_runtime_user_message_value(
            user_message
        ),
    )

    previous_last_jin_response = find_runtime_memory_entry_value(
        previous_memory,
        RUNTIME_LAST_JIN_RESPONSE_KEY,
    )
    candidate_last_jin_response = find_runtime_memory_entry_value(
        updated_memory,
        RUNTIME_LAST_JIN_RESPONSE_KEY,
    )

    if (
            not candidate_last_jin_response
            or (
                previous_last_jin_response
                and candidate_last_jin_response == previous_last_jin_response
            )
    ):
        updated_memory = upsert_runtime_memory_entry_text(
            updated_memory,
            RUNTIME_LAST_JIN_RESPONSE_KEY,
            build_last_jin_response_fallback(
                assistant_message
            ),
        )

    return updated_memory

def strip_runtime_memory_repeated_suffix(
        value: str,
) -> str:

    cleaned = REPEATED_SLOT_SUFFIX_RE.sub(
        " ",
        value or "",
    )

    return re.sub(
        r"\s+",
        " ",
        cleaned,
    ).strip()


def normalize_runtime_memory_key_family(
        key: str,
) -> str:

    cleaned_key = (
        key
        or ""
    ).strip()

    match = NUMBERED_MEMORY_KEY_RE.match(
        cleaned_key
    )

    if not match:
        return cleaned_key.casefold()

    return (
        match.group("family")
        or cleaned_key
    ).strip().casefold()


def is_runtime_memory_repeatable_key_family(
        key: str,
) -> bool:

    family = normalize_runtime_memory_key_family(
        key
    )
    normalized_family = family.replace(
        "-",
        "_",
    ).replace(
        " ",
        "_",
    )

    normalized_allowed = {
        allowed.replace(
            "-",
            "_",
        ).replace(
            " ",
            "_",
        )
        for allowed in REPEATABLE_RUNTIME_MEMORY_KEY_FAMILIES
    }

    return normalized_family in normalized_allowed


def normalize_runtime_memory_slot_text(
        value: str,
) -> str:

    cleaned = strip_runtime_memory_repeated_suffix(
        value
    )
    cleaned = strip_runtime_memory_confirmation_suffix(
        cleaned
    )

    cleaned = cleaned.casefold()
    cleaned = re.sub(
        r"[^0-9a-zа-яё]+",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )

    return re.sub(
        r"\s+",
        " ",
        cleaned,
    ).strip()


def runtime_memory_slot_similarity(
        left: str,
        right: str,
) -> float:

    left_text = normalize_runtime_memory_slot_text(
        left
    )
    right_text = normalize_runtime_memory_slot_text(
        right
    )

    if not left_text and not right_text:
        return 1.0

    if not left_text or not right_text:
        return 0.0

    left_tokens = {
        token
        for token in left_text.split()
        if len(token) >= 3
    }
    right_tokens = {
        token
        for token in right_text.split()
        if len(token) >= 3
    }

    token_score = 0.0

    if left_tokens and right_tokens:
        token_score = (
            len(left_tokens & right_tokens)
            / max(
                1,
                min(
                    len(left_tokens),
                    len(right_tokens),
                ),
            )
        )

    from difflib import SequenceMatcher

    sequence_score = SequenceMatcher(
        None,
        left_text,
        right_text,
    ).ratio()

    return max(
        token_score,
        sequence_score,
    )



def strip_runtime_memory_confirmation_suffix(
        value: str,
) -> str:

    return CONFIRMATION_SUFFIX_RE.sub(
        "",
        value or "",
    ).strip()


def is_runtime_memory_placeholder_value(
        value: str,
) -> bool:

    cleaned = strip_runtime_memory_confirmation_suffix(
        value
    )

    cleaned = cleaned.strip().strip(".。;；")

    return cleaned.lower() in RUNTIME_MEMORY_PLACEHOLDER_VALUES


def remove_runtime_memory_placeholder_lines(
        memory: str,
) -> str:

    lines = []

    for raw_line in (memory or "").splitlines():
        line = raw_line.strip()

        if not line:
            continue

        if ":" not in line:
            lines.append(
                raw_line
            )
            continue

        _, value = line.split(
            ":",
            1,
        )

        if is_runtime_memory_placeholder_value(
            value
        ):
            continue

        lines.append(
            raw_line
        )

    return "\n".join(
        lines
    ).strip()

def remove_runtime_memory_entry_text(
        memory: str,
        key: str,
) -> str:

    target_key = str(key or "").strip()
    if not target_key:
        return memory or ""

    target_key_normalized = target_key.casefold()

    lines = [
        line.rstrip()
        for line in str(memory or "").splitlines()
    ]

    kept_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        current_key = stripped.split(":", 1)[0].strip().casefold()

        if current_key == target_key_normalized:
            continue

        kept_lines.append(stripped)

    return "\n".join(kept_lines).strip()


def upsert_runtime_memory_entry_text(
        memory: str,
        key: str,
        value: str,
) -> str:

    target_key = str(key or "").strip()
    if not target_key:
        return memory or ""

    target_key_normalized = target_key.casefold()
    replacement = f"{target_key}: {str(value or '').strip()}"

    lines = [
        line.rstrip()
        for line in str(memory or "").splitlines()
    ]

    updated_lines = []
    replaced = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        current_key = stripped.split(":", 1)[0].strip().casefold()

        if current_key == target_key_normalized:
            if not replaced:
                updated_lines.append(replacement)
                replaced = True
            continue

        updated_lines.append(stripped)

    if not replaced:
        updated_lines.append(replacement)

    return "\n".join(updated_lines).strip()


def remove_runtime_response_feedback_text(
        memory: str,
) -> str:

    return remove_runtime_memory_entry_text(
        memory or "",
        RUNTIME_RESPONSE_FEEDBACK_KEY,
    ).strip()


def canonicalize_runtime_memory_entry(
        key: str,
        value: str,
) -> tuple[str, str]:

    return (
        key.strip(),
        value.strip(),
    )


def canonicalize_runtime_memory_key(
        key: str,
) -> str:

    canonical_key, _ = canonicalize_runtime_memory_entry(
        key,
        "",
    )

    return canonical_key


def canonicalize_runtime_memory_text(
        memory: str,
) -> str:

    canonical_lines = []

    for raw_line in (memory or "").splitlines():
        line = raw_line.strip()

        if not line:
            continue

        prefix = ""

        while line.startswith("-"):
            prefix += "- "
            line = line[1:].strip()

        if ":" not in line:
            canonical_lines.append(
                f"{prefix}{line}"
            )
            continue

        key, value = line.split(
            ":",
            1,
        )

        canonical_key, canonical_value = canonicalize_runtime_memory_entry(
            key,
            value,
        )

        canonical_lines.append(
            f"{prefix}{canonical_key}: {canonical_value}"
        )

    return "\n".join(
        canonical_lines
    )


def format_user_idle_seconds(
        seconds,
) -> str:

    try:
        total_seconds = max(
            0,
            int(seconds),
        )
    except (
            TypeError,
            ValueError,
    ):
        return ""

    if total_seconds < 60:
        return f"{total_seconds}s"

    total_minutes, remainder_seconds = divmod(
        total_seconds,
        60,
    )

    if total_minutes < 60:
        if remainder_seconds:
            return f"{total_minutes}m {remainder_seconds}s"

        return f"{total_minutes}m"

    total_hours, remainder_minutes = divmod(
        total_minutes,
        60,
    )

    if total_hours < 24:
        if remainder_minutes:
            return f"{total_hours}h {remainder_minutes}m"

        return f"{total_hours}h"

    days, remainder_hours = divmod(
        total_hours,
        24,
    )

    if remainder_hours:
        return f"{days}d {remainder_hours}h"

    return f"{days}d"


def get_user_idle_context_text(
        context=None,
) -> str:

    if context is None:
        return ""

    seconds = getattr(
        context,
        "runtime_user_idle_seconds",
        None,
    )

    formatted = format_user_idle_seconds(
        seconds,
    )

    if not formatted:
        return ""

    if getattr(
        context,
        "runtime_user_idle_paused",
        False,
    ):
        return f"{formatted}"

    return formatted


def remove_runtime_user_idle_lines(
        memory: str,
) -> str:

    lines = []

    for raw_line in (memory or "").splitlines():
        line = raw_line.strip()

        if not line:
            continue

        if ":" in line:
            key, _ = line.split(
                ":",
                1,
            )

            if (
                    canonicalize_runtime_memory_key(key)
                    == RUNTIME_USER_IDLE_KEY
            ):
                continue

        lines.append(
            raw_line
        )

    return "\n".join(
        lines
    )

def build_runtime_memory_context_text(
        memory: str,
        context=None,
) -> str:

    durable_memory = remove_runtime_user_idle_lines(
        memory
    ).strip()

    memory_text = canonicalize_runtime_memory_text(
        durable_memory or DEFAULT_RUNTIME_MEMORY
    )

    lines = []

    for raw_line in memory_text.splitlines():
        line = raw_line.strip()

        if not line:
            continue

        if line == DEFAULT_RUNTIME_MEMORY:
            line = f"note: {line}"

        lines.append(
            line
        )

    if context is not None:
        for evidence_line in extract_runtime_l2_pattern_evidence_lines(
                getattr(
                    context,
                    "runtime_l2_memory",
                    "",
                )
        ):
            if evidence_line not in lines:
                lines.append(
                    evidence_line
                )

    user_idle_text = get_user_idle_context_text(
        context
    )

    if user_idle_text:
        lines.append(
            f"{RUNTIME_USER_IDLE_KEY}: {user_idle_text}"
        )

    return "\n".join(
        lines
    )

def build_runtime_memory_user_prompt(
        *,
        current_memory: str,
        user_message: str,
        assistant_message: str,
        strength_zones: dict | None = None,
) -> str:

    hot_traces = ""
    if strength_zones:
        hot = ", ".join(strength_zones.get("hot", [])) or "none"
        hot_traces = (
            f"hot_traces: {hot}\n\n"
        )

    return (
        "Current runtime memory:\n"
        f"{current_memory.strip() or DEFAULT_RUNTIME_MEMORY}\n\n"
        f"{hot_traces}"
        "Latest user message:\n"
        f"{user_message.strip()}\n\n"
        "Latest JIN answer:\n"
        f"{assistant_message.strip()}\n\n"
        "Rewrite the runtime memory now as atomic bullet lines."
    )


def build_runtime_memory_batch_user_prompt(
        *,
        current_memory: str,
        turns: list[dict],
        strength_zones: dict | None = None,
) -> str:

    lines = [
        "Current runtime memory:",
        current_memory.strip() or DEFAULT_RUNTIME_MEMORY,
        "",
    ]

    if strength_zones:
        hot = ", ".join(strength_zones.get("hot", [])) or "none"
        lines.extend([
            f"hot_traces: {hot}",
            "",
        ])

    lines.extend([
        "New completed turns since that memory snapshot:",
    ])

    for index, turn in enumerate(
            turns,
            start=1,
    ):
        lines.extend([
            "",
            "Turn {index}".format(
                index=index,
            ),
            "Latest user message:",
            (
                turn.get(
                    "user_message",
                    "",
                )
                .strip()
            ),
            "",
            "Latest JIN answer:",
            (
                turn.get(
                    "assistant_message",
                    "",
                )
                .strip()
            ),
        ])

    lines.extend([
        "",
        "Rewrite the runtime memory now as atomic bullet lines.",
        "Use the current memory as the last stable snapshot.",
        "Integrate all new completed turns in order.",
    ])

    return "\n".join(
        lines
    )


def build_interrupted_assistant_message(
        *,
        user_message: str,
        assistant_message: str,
) -> str:

    partial_text = assistant_message.strip()

    if not partial_text:
        partial_text = "No complete assistant answer was delivered."

    return INTERRUPTED_ASSISTANT_MEMORY_TEMPLATE.format(
        user_message=user_message.strip(),
        assistant_message=partial_text,
    )


def parse_runtime_memory_lines(memory: str) -> list[dict]:
    lines = []

    for raw_line in (memory or "").splitlines():
        line = raw_line.strip().lstrip("-").strip()

        if not line:
            continue

        if ":" in line:
            key, value = line.split(":", 1)
        else:
            key, value = "note", line

        key, value = canonicalize_runtime_memory_entry(
            key,
            value,
        )

        lines.append({
            "key": key,
            "value": value,
            "status": "same",
        })

    return lines

def normalize_memory_key(
        key: str,
) -> str:

    return (
        key
        .strip()
        .lower()
    )


def is_durable_memory_key(
        key: str,
) -> bool:

    normalized_key = normalize_memory_key(
        key
    )

    return any(
        token in normalized_key
        for token in DURABLE_MEMORY_KEY_TOKENS
    )


def compute_line_strength(
        prev_strength: float | None,
        change_ratio_val: float,
        is_durable: bool,
        is_new: bool,
) -> float:
    if is_new:
        raw = STRENGTH_NEW_KEY
    else:
        raw = (
            (prev_strength or 0.0) * STRENGTH_DECAY
            + STRENGTH_PRESENCE_BOOST
            + change_ratio_val * STRENGTH_BOOST
        )

    floor = DURABLE_FLOOR if is_durable else 0.0

    return round(
        min(
            1.0,
            max(
                floor,
                raw,
            ),
        ),
        4,
    )


def get_strength_zones(
        lines: list[dict],
) -> dict:
    hot = []
    excluded_hot_trace_keys = {
        normalize_memory_key(
            key
        )
        for key in HOT_TRACE_EXCLUDED_KEYS
    }

    for line in lines:
        key = line.get("key", "")
        strength = line.get("strength", 0.0)
        if strength >= HOT_THRESHOLD:
            if normalize_memory_key(
                key
            ) in excluded_hot_trace_keys:
                continue
            hot.append(key)

    return {
        "hot": hot,
    }


def build_strength_map(
        lines: list[dict],
) -> dict[str, float]:
    return {
        line.get("key", ""): line.get("strength", 0.0)
        for line in lines
        if line.get("key")
    }


def has_durable_fact_negation(
        value: str,
) -> bool:

    normalized_value = (
        value
        or ""
    ).strip().lower()

    return any(
        marker in normalized_value
        for marker in DURABLE_MEMORY_NEGATION_MARKERS
    )


def durable_memory_line_text(
        line: dict,
) -> str:

    key = (
        line.get(
            "key",
            "",
        )
        or ""
    ).strip()

    value = (
        line.get(
            "value",
            "",
        )
        or ""
    ).strip()

    if not key:
        return value

    return f"{key}: {value}"


def repeatable_runtime_memory_values_are_same_slot(
        left: str,
        right: str,
) -> bool:

    left_text = normalize_runtime_memory_slot_text(
        left
    )
    right_text = normalize_runtime_memory_slot_text(
        right
    )

    if not left_text or not right_text:
        return False

    left_tokens = {
        token
        for token in left_text.split()
        if len(token) >= 3
    }
    right_tokens = {
        token
        for token in right_text.split()
        if len(token) >= 3
    }

    if left_tokens and right_tokens:
        overlap = len(
            left_tokens & right_tokens
        )
        coverage = overlap / max(
            1,
            max(
                len(left_tokens),
                len(right_tokens),
            ),
        )

        if coverage >= 0.75:
            return True

    shorter = min(
        len(left_text),
        len(right_text),
    )
    longer = max(
        len(left_text),
        len(right_text),
    )

    if not longer:
        return False

    length_ratio = shorter / longer

    return (
        length_ratio >= 0.75
        and runtime_memory_slot_similarity(
            left,
            right,
        ) >= 0.90
    )

def normalize_generic_memory_key(
        key: str,
) -> str:

    return (
        normalize_memory_key(
            key
        )
        .replace(
            "_",
            " ",
        )
        .replace(
            "-",
            " ",
        )
    )


def is_generic_memory_match_key(
        key: str,
) -> bool:

    return normalize_generic_memory_key(
        key
    ) in GENERIC_MEMORY_MATCH_KEYS


def memory_value_similarity(
        previous: str,
        current: str,
) -> float:

    previous = (
        previous
        or ""
    ).strip()
    current = (
        current
        or ""
    ).strip()

    if not previous and not current:
        return 1.0

    if not previous or not current:
        return 0.0

    return round(
        SequenceMatcher(
            None,
            previous.lower(),
            current.lower(),
        ).ratio(),
        3,
    )


def should_match_previous_memory_line(
        *,
        key: str,
        value: str,
        previous_line: dict | None,
) -> bool:

    if previous_line is None:
        return False

    previous_key = previous_line.get(
        "key",
        "",
    )

    if not (
            is_generic_memory_match_key(
                key
            )
            or is_generic_memory_match_key(
                previous_key
            )
    ):
        return True

    similarity = memory_value_similarity(
        previous_line.get(
            "value",
            "",
        ),
        value,
    )

    return similarity >= GENERIC_MEMORY_VALUE_SIMILARITY_MIN


def find_best_previous_line(
        key: str,
        previous_lines: list[dict],
        value: str = "",
) -> dict | None:

    normalized_key = normalize_memory_key(
        key
    )

    best_line = None
    best_score = 0.0

    for previous_line in previous_lines:

        previous_key = normalize_memory_key(
            previous_line.get(
                "key",
                ""
            )
        )

        if not previous_key:
            continue

        score = SequenceMatcher(
            None,
            previous_key,
            normalized_key,
        ).ratio()

        if score > best_score:
            best_score = score
            best_line = previous_line

    if (
            best_score >= 0.58
            and should_match_previous_memory_line(
                key=key,
                value=value,
                previous_line=best_line,
            )
    ):
        return best_line

    return None

def apply_runtime_memory_diff(
        current_lines: list[dict],
        previous_snapshot: dict | None,
) -> list[dict]:

    if not previous_snapshot:
        for line in current_lines:
            line["key_status"] = "new"
            line["value_status"] = "new"
            line["key_change_ratio"] = 1.0
            line["value_change_ratio"] = 1.0
            line["status"] = "new"
            line["strength"] = compute_line_strength(
                prev_strength=None,
                change_ratio_val=1.0,
                is_durable=is_durable_memory_key(
                    line.get("key", "")
                ),
                is_new=True,
            )

        return current_lines

    previous_lines = (
            previous_snapshot.get(
                "lines",
                []
            )
            or []
    )

    previous_by_normalized_key = {}

    for previous_line in previous_lines:
        normalized_key = normalize_memory_key(
            previous_line.get(
                "key",
                ""
            )
        )

        if normalized_key:
            previous_by_normalized_key[normalized_key] = previous_line

    for line in current_lines:

        key = (
                line.get(
                    "key",
                    ""
                )
                or ""
        ).strip()

        value = (
                line.get(
                    "value",
                    ""
                )
                or ""
        ).strip()

        normalized_key = normalize_memory_key(
            key
        )

        previous_line = previous_by_normalized_key.get(
            normalized_key
        )

        if not should_match_previous_memory_line(
                key=key,
                value=value,
                previous_line=previous_line,
        ):
            previous_line = None

        if previous_line is None:
            previous_line = find_best_previous_line(
                key,
                previous_lines,
                value=value,
            )

        # -----------------------------------------
        # EXACT KEY NOT FOUND
        # -----------------------------------------

        if previous_line is None:
            line["key_status"] = "new"
            line["value_status"] = "new"
            line["key_change_ratio"] = 1.0
            line["value_change_ratio"] = 1.0
            line["status"] = "new"
            line["strength"] = compute_line_strength(
                prev_strength=None,
                change_ratio_val=1.0,
                is_durable=is_durable_memory_key(key),
                is_new=True,
            )

            continue

        previous_key = (
                previous_line.get(
                    "key",
                    ""
                )
                or ""
        ).strip()

        previous_value = (
                previous_line.get(
                    "value",
                    ""
                )
                or ""
        ).strip()

        key_delta = change_ratio(
            previous_key,
            key,
        )

        value_delta = change_ratio(
            previous_value,
            value,
        )

        line["key_change_ratio"] = key_delta
        line["value_change_ratio"] = value_delta

        line["key_status"] = (
            "changed"
            if key_delta > 0
            else "same"
        )

        line["value_status"] = (
            "changed"
            if value_delta > 0
            else "same"
        )

        if (
                line["key_status"] == "changed"
                or line["value_status"] == "changed"
        ):
            line["status"] = "changed"

        else:
            line["status"] = "same"

        line["strength"] = compute_line_strength(
            prev_strength=previous_line.get("strength"),
            change_ratio_val=max(key_delta, value_delta),
            is_durable=is_durable_memory_key(key),
            is_new=False,
        )

    return current_lines


def build_runtime_memory_patch(
        current_lines: list[dict],
        previous_snapshot: dict | None,
) -> dict:

    patch = {
        "added": [],
        "changed": [],
        "removed": [],
    }
    total_diff = 0

    if not previous_snapshot:
        for line in current_lines:
            patch["added"].append({
                "key": line.get(
                    "key",
                    "",
                ),
                "value": line.get(
                    "value",
                    "",
                ),
                "strength": line.get(
                    "strength",
                    0.0,
                ),
            })
            total_diff += 30

        return {
            "patch": patch,
            "total_diff": total_diff,
        }

    previous_lines = (
            previous_snapshot.get(
                "lines",
                [],
            )
            or []
    )

    previous_by_normalized_key = {}

    for previous_line in previous_lines:
        normalized_key = normalize_memory_key(
            previous_line.get(
                "key",
                "",
            )
        )

        if normalized_key:
            previous_by_normalized_key[normalized_key] = previous_line

    matched_previous_ids = set()

    for line in current_lines:

        key = (
                line.get(
                    "key",
                    "",
                )
                or ""
        ).strip()

        value = (
                line.get(
                    "value",
                    "",
                )
                or ""
        ).strip()

        normalized_key = normalize_memory_key(
            key
        )

        previous_line = previous_by_normalized_key.get(
            normalized_key
        )

        if not should_match_previous_memory_line(
                key=key,
                value=value,
                previous_line=previous_line,
        ):
            previous_line = None

        if previous_line is None:
            previous_line = find_best_previous_line(
                key,
                previous_lines,
                value=value,
            )

        if previous_line is None:
            patch["added"].append({
                "key": key,
                "value": line.get(
                    "value",
                    "",
                ),
                "strength": line.get(
                    "strength",
                    0.0,
                ),
            })
            total_diff += 30
            continue

        matched_previous_ids.add(
            id(previous_line)
        )

        key_delta = line.get(
            "key_change_ratio",
            0,
        )
        value_delta = line.get(
            "value_change_ratio",
            0,
        )

        if key_delta or value_delta:
            patch["changed"].append({
                "previous_key": previous_line.get(
                    "key",
                    "",
                ),
                "previous_value": previous_line.get(
                    "value",
                    "",
                ),
                "current_key": key,
                "current_value": line.get(
                    "value",
                    "",
                ),
                "key_change_ratio": key_delta,
                "value_change_ratio": value_delta,
                "previous_strength": previous_line.get(
                    "strength",
                    0.0,
                ),
                "current_strength": line.get(
                    "strength",
                    0.0,
                ),
            })
            total_diff += round(
                (
                    key_delta
                    + value_delta
                )
                * 50,
                2,
            )

    for previous_line in previous_lines:
        if id(previous_line) in matched_previous_ids:
            continue

        patch["removed"].append({
            "key": previous_line.get(
                "key",
                "",
            ),
            "value": previous_line.get(
                "value",
                "",
            ),
            "strength": previous_line.get(
                "strength",
                0.0,
            ),
        })
        total_diff += 20

    return {
        "patch": patch,
        "total_diff": total_diff,
    }



COUNTDOWN_MEMORY_KEY_RE = re.compile(
    r"^countdown_contract(?:_\d+)?$",
    re.IGNORECASE,
)

COUNTDOWN_SUFFIX_RE = re.compile(
    r"\[\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*([^\]]*)\]"
)

COUNTDOWN_LEGACY_FIELD_RE = re.compile(
    r"\s*;\s*(?:current|remaining|current_time|status)\s*:\s*[^;\[]*",
    re.IGNORECASE,
)

COUNTDOWN_LEGACY_ANCHOR_RE = re.compile(
    r"\s*;\s*(created_at|created_user_message_count|count_from|count_to|due_user_message_count|due_at|trigger)\s*:\s*([^;\[]*)",
    re.IGNORECASE,
)


def is_countdown_memory_key(key: str) -> bool:

    return bool(
        COUNTDOWN_MEMORY_KEY_RE.match(
            str(key or "").strip()
        )
    )


def parse_countdown_suffixes(value: str) -> dict[str, str]:

    return {
        match.group(1).strip().casefold(): match.group(2).strip()
        for match in COUNTDOWN_SUFFIX_RE.finditer(value or "")
    }


def strip_countdown_suffixes(value: str) -> str:

    without_suffixes = COUNTDOWN_SUFFIX_RE.sub(
        "",
        value or "",
    )

    without_legacy_runtime = COUNTDOWN_LEGACY_FIELD_RE.sub(
        "",
        without_suffixes,
    )

    return re.sub(
        r"\s+",
        " ",
        without_legacy_runtime,
    ).strip().strip(";").strip()


def _parse_int(value) -> int | None:

    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _extract_legacy_countdown_fields(value: str) -> dict[str, str]:

    fields = {}

    for match in COUNTDOWN_LEGACY_ANCHOR_RE.finditer(value or ""):
        key = match.group(1).strip().casefold()
        fields[key] = match.group(2).strip()

    return fields


def _countdown_suffix_text(suffixes: dict[str, str]) -> str:

    ordered_keys = (
        "created_at",
        "created_user_message_count",
        "count_from",
        "count_to",
        "due_user_message_count",
        "current",
        "remaining",
        "due_at",
        "current_time",
        "trigger",
        "completed",
        "cancelled",
    )

    parts = []
    emitted = set()

    for key in ordered_keys:
        value = suffixes.get(key)
        if value is None or str(value).strip() == "":
            continue
        parts.append(f"[{key}: {str(value).strip()}]")
        emitted.add(key)

    for key, value in suffixes.items():
        if key in emitted or key == "status":
            continue
        if str(value).strip() == "":
            continue
        parts.append(f"[{key}: {str(value).strip()}]")

    return " ".join(parts)


def update_countdown_contract_line(
        *,
        key: str,
        value: str,
        current_user_message_count=None,
        current_timestamp: str = "",
) -> str | None:

    if not is_countdown_memory_key(key):
        return f"{key}: {value}".strip()

    suffixes = parse_countdown_suffixes(value)
    legacy_fields = _extract_legacy_countdown_fields(value)

    for legacy_key, legacy_value in legacy_fields.items():
        suffixes.setdefault(
            legacy_key,
            legacy_value,
        )

    suffixes.pop(
        "status",
        None,
    )

    if (
            "completed" in suffixes
            or "cancelled" in suffixes
    ):
        return None

    body = strip_countdown_suffixes(value)

    current_count = _parse_int(
        current_user_message_count
    )

    count_to = _parse_int(
        suffixes.get("count_to")
        or suffixes.get("due_user_message_count")
    )

    if count_to is not None:
        if current_count is not None:
            suffixes["current"] = str(current_count)
            suffixes["remaining"] = str(
                max(
                    count_to - current_count,
                    0,
                )
            )
        suffixes.setdefault(
            "due_user_message_count",
            str(count_to),
        )

    due_at = suffixes.get(
        "due_at"
    )

    if due_at and current_timestamp:
        suffixes["current_time"] = str(current_timestamp)

    rendered_suffixes = _countdown_suffix_text(
        suffixes
    )

    if rendered_suffixes:
        return f"{key}: {body} {rendered_suffixes}".strip()

    return f"{key}: {body}".strip()


def refresh_countdown_contracts(
        memory: str,
        context=None,
) -> str:

    current_user_message_count = getattr(
        context,
        "user_message_count",
        None,
    ) if context is not None else None

    current_timestamp = str(
        getattr(
            context,
            "timestamp",
            "",
        )
        or ""
    )

    updated_lines = []

    for raw_line in str(memory or "").splitlines():
        line = raw_line.strip().lstrip("-").strip()

        if not line:
            continue

        if ":" not in line:
            updated_lines.append(line)
            continue

        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()

        if not is_countdown_memory_key(key):
            updated_lines.append(line)
            continue

        updated_line = update_countdown_contract_line(
            key=key,
            value=value,
            current_user_message_count=current_user_message_count,
            current_timestamp=current_timestamp,
        )

        if updated_line:
            updated_lines.append(updated_line)

    return "\n".join(updated_lines).strip()

def build_runtime_memory_snapshot(
        context,
        memory: str,
) -> dict:

    snapshots = getattr(
        context,
        "runtime_memory_snapshots",
        [],
    )

    previous_snapshot = (
        snapshots[-1]
        if snapshots
        else None
    )

    display_memory = build_runtime_memory_context_text(
        memory,
        context,
    )

    lines = parse_runtime_memory_lines(
        display_memory
    )

    lines = apply_runtime_memory_diff(
        lines,
        previous_snapshot,
    )

    patch_details = build_runtime_memory_patch(
        lines,
        previous_snapshot,
    )

    return {
        "session_id": getattr(context, "session_id", ""),
        "index": len(snapshots),
        "raw_memory": display_memory,
        "lines": lines,
        "patch": patch_details["patch"],
        "total_diff": patch_details["total_diff"],
    }
