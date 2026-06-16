import re

from runtime.L1_memory_rules import (
    DEFAULT_RUNTIME_MEMORY,
    RUNTIME_USER_IDLE_KEY,
)
from runtime.L2_memory_utils import (
    extract_runtime_l2_pattern_evidence_lines,
)



PLACEHOLDER_MEMORY_VALUES = {
    "",
    "n/a",
    "na",
    "none",
    "null",
    "nil",
    "unknown",
    "not applicable",
    "not_applicable",
    "no",
    "нет",
    "неизвестно",
    "не применимо",
}

CONFIRMATION_SUFFIX_RE = re.compile(
    r"\s*\(confirmed:\s*[^)]*\)\s*$",
    re.IGNORECASE,
)


REPEATED_SLOT_SUFFIX_RE = re.compile(
    r"\s*\[ repeated:\s*(\d+)\s*\]\s*",
    re.IGNORECASE,
)

NUMBERED_MEMORY_KEY_RE = re.compile(
    r"^(?P<family>.+?)(?:_(?P<index>\d+))?$",
)


REPEATABLE_RUNTIME_MEMORY_KEY_FAMILIES = {
    "offered_choices",
    "offered choice",
    "offered choices",
    "offered_option",
    "offered option",
    "offered_options",
    "offered options",
    "pending_choice",
    "pending choice",
    "pending_choices",
    "pending choices",
    "open_reference",
    "open reference",
    "open_references",
    "open references",
    "user_fact",
    "user fact",
    "jin_fact",
    "jin fact",
    "decision",
    "constraint",
    "current_task",
    "current task",
}

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

    return cleaned.lower() in PLACEHOLDER_MEMORY_VALUES


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

def canonicalize_runtime_memory_entry(
        key: str,
        value: str,
) -> tuple[str, str]:

    cleaned_key = key.strip()
    cleaned_value = value.strip()

    legacy_purpose_map = {
        "memory token": (
            "stored_memory",
            "future recall test",
        ),
    }

    purpose_entry = legacy_purpose_map.get(
        cleaned_key.lower()
    )

    if purpose_entry is None:
        return cleaned_key, cleaned_value

    canonical_key, purpose = purpose_entry

    return (
        canonical_key,
        f"{cleaned_value} (purpose: {purpose})",
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
            f"Turn {index}",
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
        partial_text = (
            "No complete assistant answer was delivered."
        )

    return (
        "JIN response was interrupted by the user and is incomplete. "
        "Do not treat this turn as resolved.\n\n"
        "Interrupted user topic/request:\n"
        f"{user_message.strip()}\n\n"
        "Partial JIN text before interruption:\n"
        f"{partial_text}"
    )
