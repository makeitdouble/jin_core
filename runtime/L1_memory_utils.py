import re
import unicodedata
from datetime import (
    datetime,
    timezone,
)

from utils.time_utils import (
    format_utc_iso,
)

from runtime.L1_memory_rules import (
    DEFAULT_RUNTIME_MEMORY,
    EMPTY_ASSISTANT_REPLY_MEMORY_TEMPLATE,
    HOT_THRESHOLD,
    HOT_MEMORY_KEY_EXCLUDED_KEYS,
    INTERRUPTED_ASSISTANT_MEMORY_TEMPLATE,
    RUNTIME_RESPONSE_FEEDBACK_KEY,
    RUNTIME_USER_IDLE_KEY,
    STRENGTH_BOOST,
    STRENGTH_DECAY,
    STRENGTH_NEW_KEY,
    STRENGTH_PRESENCE_BOOST,
    STRENGTH_QUOTE_BOOST,
)
from rules.signal import (
    RUNTIME_RESPONSE_FEEDBACK_DISLIKED_VALUE,
    RUNTIME_RESPONSE_FEEDBACK_LIKED_VALUE,
    RUNTIME_RESPONSE_FEEDBACK_NEUTRAL_VALUE,
)
from runtime.memory_common import (
    change_ratio,
    log_memory_event,
    safe_call,
)

from utils.actions import (
    generate_short_runtime_id,
)
from utils.session_actions_history import (
    get_session_action_session_id,
    session_action_belongs_to_session,
)



RUNTIME_USER_MESSAGE_KEY = "user_message"

RUNTIME_RESPONSE_FEEDBACK_CLICK_COUNT_KEYS = {
    "disliked": "dislike_clicks_count",
    "neutral": "neutral_clicks_count",
    "liked": "like_clicks_count",
}

RUNTIME_MEMORY_KEY_PREFIX_RE = re.compile(
    r"^\s*-?\s*[A-Za-z][A-Za-z0-9_ #]{0,80}\s*:",
)

LEGACY_RUNTIME_MEMORY_SCORE_SUFFIX_RE = re.compile(
    r"\s*(?:\[\s*t\s*r\s*a\s*c\s*e\s*:\s*[^\]]*\]|\(\s*t\s*r\s*a\s*c\s*e\s*:\s*[^)]*\))\s*",
    re.IGNORECASE,
)

RUNTIME_MEMORY_QUOTE_COUNT_SUFFIX_RE = re.compile(
    (
        r"\s*\[\s*"
        r"(?:total_quotes_count|messages_quote_count)"
        r"\s*:\s*\d+\s*\]\s*"
    ),
    re.IGNORECASE,
)

RUNTIME_MEMORY_LIFECYCLE_SUFFIX_RE = re.compile(
    (
        r"\s*\[\s*"
        r"(?:created|updated)"
        r"\s*:\s*[^]]+?\s+ago\s*\]\s*"
    ),
    re.IGNORECASE,
)

RUNTIME_QUOTE_MIN_MATCH_CHARS = 24
RUNTIME_QUOTE_MIN_MATCH_TOKENS = 4
RUNTIME_QUOTE_MIN_RARE_TOKENS = 3

RUNTIME_QUOTE_STOP_WORDS = {
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
}


def _line_starts_runtime_memory_entry(
        line: str,
) -> bool:

    return bool(
        RUNTIME_MEMORY_KEY_PREFIX_RE.match(
            str(line or "")
        )
    )


def _escape_multiline_runtime_memory_entries(
        memory: str,
) -> list[str]:

    """Keep accidental multiline values attached to their owning key.

    L1 sometimes copies markdown/code/ascii into a value after a real
    ``key: value`` prefix.  Physical continuation lines must stay inside
    that value as escaped ``\n`` text; otherwise the generic parser turns
    every ascii line into a separate fallback runtime-memory entry.
    """

    escaped_lines: list[str] = []
    pending_line: str | None = None

    def flush_pending() -> None:
        nonlocal pending_line

        if pending_line is not None:
            escaped_lines.append(
                pending_line
            )
            pending_line = None

    for raw_line in (memory or "").splitlines():
        line = str(raw_line or "").strip().lstrip("-").strip()

        if not line:
            if pending_line is not None:
                pending_line += "\\n"
            continue

        if _line_starts_runtime_memory_entry(line):
            flush_pending()
            pending_line = line
            continue

        if pending_line is not None:
            pending_line += "\\n" + line
            continue

        escaped_lines.append(
            line
        )

    flush_pending()

    return escaped_lines


def _runtime_value_has_open_quote(
        value: str,
) -> bool:

    escaped = False
    quote_count = 0

    for char in str(value or ""):
        if escaped:
            escaped = False
            continue

        if char == "\\":
            escaped = True
            continue

        if char == '"':
            quote_count += 1

    return quote_count % 2 == 1


def _looks_like_user_message_fragment(
        line: str,
) -> bool:

    fragment = str(line or "").strip()

    if not fragment:
        return False

    if ":" in fragment:
        key, value = fragment.split(
            ":",
            1,
        )
        if normalize_memory_key(
                key
        ) != "note":
            return False
        fragment = value.strip()

    return (
        fragment.startswith('"')
        or fragment.startswith('\\"')
        or fragment.endswith('"')
        or fragment.endswith('\\"')
        or "\\n" in fragment
    )


def _line_has_memory_key(
        line: str,
        key: str,
) -> bool:

    stripped = str(line or "").strip().lstrip("-").strip()

    if ":" not in stripped:
        return False

    line_key, _ = stripped.split(
        ":",
        1,
    )

    return normalize_memory_key(
        line_key
    ) == normalize_memory_key(
        key
    )


def _join_multiline_user_message_entries(
        memory: str,
) -> list[str]:

    joined_lines: list[str] = []
    pending_line: str | None = None

    for raw_line in _escape_multiline_runtime_memory_entries(
            memory
    ):
        line = raw_line.strip().lstrip("-").strip()

        if not line:
            if pending_line is not None:
                pending_line += "\\n"
            continue

        if pending_line is not None:
            pending_line += "\\n" + line

            if not _runtime_value_has_open_quote(
                    pending_line.split(":", 1)[1]
            ):
                joined_lines.append(
                    pending_line
                )
                pending_line = None

            continue

        if ":" not in line:
            if (
                    joined_lines
                    and _line_has_memory_key(
                        joined_lines[-1],
                        RUNTIME_USER_MESSAGE_KEY,
                    )
                    and _looks_like_user_message_fragment(
                        line
                    )
            ):
                joined_lines[-1] = (
                    joined_lines[-1].rstrip()
                    + "\\n"
                    + line
                )
                continue

            joined_lines.append(
                raw_line
            )
            continue

        key, value = line.split(
            ":",
            1,
        )

        if (
                normalize_memory_key(key) == RUNTIME_USER_MESSAGE_KEY
                and _runtime_value_has_open_quote(value)
        ):
            pending_line = line
            continue

        joined_lines.append(
            raw_line
        )

    if pending_line is not None:
        joined_lines.append(
            pending_line
        )

    return joined_lines


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
        for line in _join_multiline_user_message_entries(
            memory
        )
    ]

    kept_lines = []
    removing_user_message_tail = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        current_key = stripped.split(":", 1)[0].strip().casefold()

        if current_key == target_key_normalized:
            removing_user_message_tail = (
                target_key_normalized == RUNTIME_USER_MESSAGE_KEY
            )
            continue

        if (
                removing_user_message_tail
                and _looks_like_user_message_fragment(
                    stripped
                )
        ):
            continue

        removing_user_message_tail = False

        kept_lines.append(stripped)

    return "\n".join(kept_lines).strip()


def remove_runtime_response_feedback_text(
        memory: str,
) -> str:

    return remove_runtime_memory_entry_text(
        memory or "",
        RUNTIME_RESPONSE_FEEDBACK_KEY,
    ).strip()


def build_runtime_response_feedback_value(
        feedback: dict,
) -> str:

    rating = feedback.get(
        "rating",
        "neutral",
    )

    if rating == "disliked":
        value = RUNTIME_RESPONSE_FEEDBACK_DISLIKED_VALUE
    elif rating == "liked":
        value = RUNTIME_RESPONSE_FEEDBACK_LIKED_VALUE
    else:
        value = RUNTIME_RESPONSE_FEEDBACK_NEUTRAL_VALUE

    clicks_count = feedback.get(
        "clicks_count",
    )

    if isinstance(
        clicks_count,
        int,
    ) and clicks_count > 0:
        clicks_count_key = RUNTIME_RESPONSE_FEEDBACK_CLICK_COUNT_KEYS.get(
            rating,
            "neutral_clicks_count",
        )

        return f"{value} [ {clicks_count_key}: {clicks_count} ]"

    return value


def strip_runtime_memory_line_metadata(
        value: str,
) -> str:

    cleaned = LEGACY_RUNTIME_MEMORY_SCORE_SUFFIX_RE.sub(
        " ",
        str(value or ""),
    )
    cleaned = RUNTIME_MEMORY_LIFECYCLE_SUFFIX_RE.sub(
        " ",
        cleaned,
    )
    cleaned = RUNTIME_MEMORY_QUOTE_COUNT_SUFFIX_RE.sub(
        " ",
        cleaned,
    )

    return cleaned.strip()


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


def format_runtime_memory_elapsed_seconds(
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
        total_seconds = 0

    return format_user_idle_seconds(
        total_seconds
    ) or "0s"


def get_runtime_memory_snapshot_datetime(
        context=None,
) -> datetime:

    override = getattr(
        context,
        "runtime_memory_snapshot_datetime",
        None,
    )

    if isinstance(
        override,
        datetime,
    ):
        if override.tzinfo is None:
            return override.replace(
                tzinfo=timezone.utc,
            )

        return override.astimezone(
            timezone.utc
        )

    if override:
        parsed = parse_runtime_memory_lifecycle_datetime(
            override
        )

        if parsed is not None:
            return parsed

    return datetime.now(
        timezone.utc
    ).replace(
        microsecond=0
    )


def format_runtime_memory_lifecycle_timestamp(
        value,
) -> str:

    parsed = parse_runtime_memory_lifecycle_datetime(
        value
    )

    if parsed is None:
        parsed = get_runtime_memory_snapshot_datetime()

    return format_utc_iso(parsed)


def format_runtime_memory_snapshot_timestamp(
        value,
) -> str:

    parsed = parse_runtime_memory_lifecycle_datetime(
        value
    )

    if parsed is None:
        parsed = get_runtime_memory_snapshot_datetime()

    return parsed.astimezone().replace(
        microsecond=0
    ).isoformat()


def parse_runtime_memory_lifecycle_datetime(
        value,
) -> datetime | None:

    if isinstance(
        value,
        datetime,
    ):
        parsed = value
    else:
        text = str(
            value or ""
        ).strip()

        if not text:
            return None

        try:
            parsed = datetime.fromisoformat(
                text.replace(
                    "Z",
                    "+00:00",
                )
            )
        except ValueError:
            return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc,
        )

    return parsed.astimezone(
        timezone.utc
    )


def get_runtime_memory_lifecycle_status(
        line: dict,
) -> str:

    status = str(
        line.get(
            "memory_lifecycle_status",
            "",
        )
        or ""
    ).strip().lower()

    if status in {
        "created",
        "updated",
    }:
        return status

    if line.get(
        "updated_at",
    ):
        return "updated"

    return "created"


def set_runtime_memory_line_lifecycle(
        line: dict,
        previous_line: dict | None,
        *,
        changed: bool,
        snapshot_time: datetime,
) -> None:

    snapshot_timestamp = format_runtime_memory_lifecycle_timestamp(
        snapshot_time
    )

    created_at = (
        previous_line.get(
            "created_at",
        )
        if isinstance(previous_line, dict)
        else None
    )
    if not created_at:
        created_at = snapshot_timestamp

    previous_status = (
        get_runtime_memory_lifecycle_status(
            previous_line
        )
        if isinstance(previous_line, dict)
        else "created"
    )
    previous_updated_at = (
        previous_line.get(
            "updated_at",
        )
        if isinstance(previous_line, dict)
        else None
    )

    if changed:
        line["memory_lifecycle_status"] = "updated"
        line["updated_at"] = snapshot_timestamp
    elif previous_status == "updated":
        line["memory_lifecycle_status"] = "updated"
        line["updated_at"] = (
            format_runtime_memory_lifecycle_timestamp(
                previous_updated_at
            )
            if previous_updated_at
            else snapshot_timestamp
        )
    else:
        line["memory_lifecycle_status"] = "created"
        line["updated_at"] = ""

    line["created_at"] = format_runtime_memory_lifecycle_timestamp(
        created_at
    )


def format_runtime_memory_lifecycle_suffix(
        line: dict,
        *,
        now: datetime | None = None,
) -> str:

    if not isinstance(
        line,
        dict,
    ):
        return ""

    status = get_runtime_memory_lifecycle_status(
        line
    )
    timestamp = line.get(
        "updated_at" if status == "updated" else "created_at",
    )
    parsed_timestamp = parse_runtime_memory_lifecycle_datetime(
        timestamp
    )

    if parsed_timestamp is None:
        return ""

    current_time = (
        now
        if isinstance(now, datetime)
        else get_runtime_memory_snapshot_datetime()
    )
    if current_time.tzinfo is None:
        current_time = current_time.replace(
            tzinfo=timezone.utc,
        )
    current_time = current_time.astimezone(
        timezone.utc
    )

    elapsed_seconds = max(
        0,
        int(
            (
                current_time
                - parsed_timestamp
            ).total_seconds()
        ),
    )

    return (
        f" [ {status}: "
        f"{format_runtime_memory_elapsed_seconds(elapsed_seconds)} ago ]"
    )


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


def build_runtime_memory_lifecycle_maps(
        context=None,
) -> tuple[dict[str, dict], dict[str, dict]]:

    snapshots = list(
        getattr(
            context,
            "runtime_memory_snapshots",
            [],
        )
        or []
    )

    if not snapshots:
        return {}, {}

    latest_lines = (
        snapshots[-1].get(
            "lines",
            [],
        )
        or []
    )

    by_identity = {}
    by_key = {}

    for line in latest_lines:
        if not isinstance(
            line,
            dict,
        ):
            continue

        identity = runtime_memory_line_identity(
            line
        )

        if identity:
            by_identity[identity] = line

        key = normalize_memory_key(
            line.get(
                "key",
                "",
            )
        )

        if key:
            by_key[key] = line

    return by_identity, by_key


def append_runtime_memory_lifecycle_suffixes(
        lines: list[str],
        context=None,
) -> list[str]:

    by_identity, by_key = build_runtime_memory_lifecycle_maps(
        context
    )

    if (
            not by_identity
            and not by_key
    ):
        return lines

    now = get_runtime_memory_snapshot_datetime(
        context
    )
    annotated_lines = []

    for raw_line in lines:
        parsed_lines = parse_runtime_memory_lines(
            raw_line
        )

        if len(parsed_lines) != 1:
            annotated_lines.append(
                raw_line
            )
            continue

        parsed_line = parsed_lines[0]
        source_line = (
            by_identity.get(
                runtime_memory_line_identity(
                    parsed_line
                )
            )
            or by_key.get(
                normalize_memory_key(
                    parsed_line.get(
                        "key",
                        "",
                    )
                )
            )
        )
        suffix = format_runtime_memory_lifecycle_suffix(
            source_line,
            now=now,
        )

        if not suffix:
            annotated_lines.append(
                raw_line
            )
            continue

        annotated_lines.append(
            (
                f"{parsed_line.get('key', 'note')}: "
                f"{parsed_line.get('value', '')}"
                f"{suffix}"
            ).strip()
        )

    return annotated_lines


def build_runtime_memory_context_text(
        memory: str,
        context=None,
        *,
        include_lifecycle_suffixes: bool = False,
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

    user_idle_text = get_user_idle_context_text(
        context
    )

    if user_idle_text:
        lines.append(
            f"{RUNTIME_USER_IDLE_KEY}: {user_idle_text}"
        )

    if include_lifecycle_suffixes:
        lines = append_runtime_memory_lifecycle_suffixes(
            lines,
            context,
        )

    return "\n".join(
        lines
    )



def is_default_runtime_memory_line(
        line: str,
) -> bool:

    cleaned = (
        line
        or ""
    ).strip()

    if not cleaned:
        return False

    if cleaned == DEFAULT_RUNTIME_MEMORY:
        return True

    if ":" not in cleaned:
        return False

    key, value = cleaned.split(
        ":",
        1,
    )

    return (
        key.strip().casefold() == "note"
        and value.strip() == DEFAULT_RUNTIME_MEMORY
    )


def remove_default_runtime_memory_lines(
        memory: str,
) -> str:

    lines = []

    for raw_line in (memory or "").splitlines():
        if is_default_runtime_memory_line(
            raw_line
        ):
            continue

        lines.append(
            raw_line
        )

    return "\n".join(
        lines
    ).strip()


def build_l1_current_memory_prompt_block(
        current_memory: str,
) -> str:

    memory_text = remove_default_runtime_memory_lines(
        current_memory
    ).strip()

    if not memory_text:
        return ""

    return (
        "Current runtime memory:\n"
        f"{memory_text}\n\n"
    )

def build_runtime_memory_user_prompt(
        *,
        current_memory: str,
        user_message: str,
        assistant_message: str,
        strength_zones: dict | None = None,
) -> str:

    return (
        build_l1_current_memory_prompt_block(
            current_memory
        )
        + "Latest user message:\n"
        + f"{user_message.strip()}\n\n"
        + "Latest JIN answer:\n"
        + f"{assistant_message.strip()}\n\n"
    )


def build_runtime_memory_batch_user_prompt(
        *,
        current_memory: str,
        turns: list[dict],
        strength_zones: dict | None = None,
) -> str:

    lines = []

    current_memory_text = remove_default_runtime_memory_lines(
        current_memory
    ).strip()

    if current_memory_text:
        lines.extend([
            "Current runtime memory:",
            current_memory_text,
            "",
        ])

    for index, turn in enumerate(
            turns,
            start=1,
    ):
        lines.extend([
            "",
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


    return "\n".join(
        lines
    )


def build_interrupted_assistant_message(
        *,
        user_message: str,
        assistant_message: str,
        interruption_reason: str = "",
        interruption_quote: str = "",
        aborted_actions=None,
) -> str:

    partial_text = assistant_message.strip()

    if not partial_text:
        partial_text = "No complete assistant answer was delivered."

    interruption_reason = interruption_reason.strip()
    interruption_quote = interruption_quote.strip()
    aborted_action_lines = format_aborted_runtime_action_lines(
        aborted_actions
    )

    if interruption_reason:
        lines = [
            "JIN response was interrupted before completion. "
            "Do not treat this turn as resolved.",
            "",
            "Interruption reason:",
            interruption_reason,
        ]

        if interruption_quote:
            lines.extend([
                "",
                "Looped text quote:",
                f'"{interruption_quote}"',
            ])

        lines.extend([
            "",
            "Interrupted user topic/request:",
            user_message.strip(),
            "",
            "Partial JIN text before interruption:",
            partial_text,
        ])

        if aborted_action_lines:
            lines.extend([
                "",
                "Aborted runtime actions:",
                *aborted_action_lines,
            ])

        return "\n".join(
            lines
        )

    message = INTERRUPTED_ASSISTANT_MEMORY_TEMPLATE.format(
        user_message=user_message.strip(),
        assistant_message=partial_text,
    )

    if aborted_action_lines:
        message = "\n".join([
            message,
            "",
            "Aborted runtime actions:",
            *aborted_action_lines,
        ])

    return message


def format_aborted_runtime_action_lines(
        aborted_actions,
) -> list[str]:

    lines = []

    for action in aborted_actions or ():
        if isinstance(
            action,
            dict,
        ):
            name = str(
                action.get("name")
                or action.get("display_name")
                or action.get("action")
                or ""
            ).strip()
        else:
            name = str(
                action
                or ""
            ).strip()

        if not name:
            continue

        lines.append(
            f"{name}: ABORTED"
        )

    return lines


def build_empty_assistant_message(
        *,
        user_message: str,
) -> str:

    return EMPTY_ASSISTANT_REPLY_MEMORY_TEMPLATE.format(
        user_message=user_message.strip(),
    )


COMPOUND_RUNTIME_MEMORY_KEY_BOUNDARY_RE = re.compile(
    r"(?P<delimiter>;|[.!?。！？])\s+"
    r"(?=(?:[A-Za-z][A-Za-z0-9]*_+[A-Za-z0-9_]*|active_memory(?:_\d+)?)\s*:)",
)


def _split_compound_runtime_memory_line(
        line: str,
) -> list[str]:

    pieces = []
    start = 0

    for match in COMPOUND_RUNTIME_MEMORY_KEY_BOUNDARY_RE.finditer(
            str(line or "")
    ):
        delimiter = match.group("delimiter")
        end = (
            match.start()
            if delimiter == ";"
            else match.start() + len(delimiter)
        )

        piece = line[start:end].strip()
        if piece:
            pieces.append(piece)

        start = match.end()

    tail = str(line or "")[start:].strip()
    if tail:
        pieces.append(tail)

    return pieces


def normalize_compound_runtime_memory_lines(
        memory: str,
) -> str:

    """Split L1-glued memory entries into separate lines.

    Examples:
        "jin_identity: hi; user_name: Sergey"
        -> "jin_identity: hi\nuser_name: Sergey"

        "active_topic: Drawing. user_intent: Asked to draw"
        -> "active_topic: Drawing.\nuser_intent: Asked to draw"
    """

    normalized_lines = []

    for raw_line in _escape_multiline_runtime_memory_entries(
            memory
    ):
        line = str(raw_line or "")

        if not line.strip():
            normalized_lines.append(line)
            continue

        normalized_lines.extend(
            _split_compound_runtime_memory_line(line)
        )

    return "\n".join(
        normalized_lines
    ).strip()


def parse_runtime_memory_lines(memory: str) -> list[dict]:
    lines = []

    for raw_line in _join_multiline_user_message_entries(
            memory
    ):
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
        value = strip_runtime_memory_line_metadata(
            value
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


def compute_line_strength(
        prev_strength: float | None,
        change_ratio_val: float,
        is_new: bool,
        quote_boost: float = 0.0,
) -> float:
    if is_new:
        raw = STRENGTH_NEW_KEY
    else:
        raw = (
            (prev_strength or 0.0) * STRENGTH_DECAY
            + STRENGTH_PRESENCE_BOOST
            + change_ratio_val * STRENGTH_BOOST
        )

    raw += max(
        0.0,
        float(
            quote_boost or 0.0
        ),
    )

    return round(
        min(
            1.0,
            max(
                0.0,
                raw,
            ),
        ),
        4,
    )


def runtime_memory_line_identity(
        line: dict,
) -> str:

    key = str(
        line.get(
            "key",
            "",
        )
        or ""
    ).strip()
    value = str(
        line.get(
            "value",
            "",
        )
        or ""
    ).strip()

    if not key and not value:
        return ""

    return f"{key}\0{value}"


def _normalize_runtime_quote_text(
        text: str,
) -> str:

    normalized = unicodedata.normalize(
        "NFKC",
        str(text or ""),
    ).lower()
    output = []

    for char in normalized:
        if char.isalnum():
            output.append(
                char
            )
            continue

        if (
                output
                and output[-1] != " "
        ):
            output.append(
                " "
            )

    while (
            output
            and output[-1] == " "
    ):
        output.pop()

    return "".join(
        output
    )


def _runtime_quote_tokens(
        text: str,
) -> list[str]:

    return [
        token
        for token in _normalize_runtime_quote_text(
            text
        ).split(" ")
        if token
    ]


def _runtime_quote_rare_token_count(
        tokens: list[str],
) -> int:

    return len({
        token
        for token in tokens
        if (
                len(token) >= 4
                and token not in RUNTIME_QUOTE_STOP_WORDS
        )
    })


def _runtime_quote_phrase_is_usable(
        tokens: list[str],
) -> bool:

    phrase = " ".join(
        tokens
    )

    return (
            len(tokens) >= RUNTIME_QUOTE_MIN_MATCH_TOKENS
            and len(phrase) >= RUNTIME_QUOTE_MIN_MATCH_CHARS
            and _runtime_quote_rare_token_count(
                tokens
            ) >= RUNTIME_QUOTE_MIN_RARE_TOKENS
    )


def runtime_memory_line_was_quoted(
        *,
        line: dict,
        normalized_reasoning: str,
) -> bool:

    key = str(
        line.get(
            "key",
            "",
        )
        or "note"
    ).strip()
    value = str(
        line.get(
            "value",
            "",
        )
        or ""
    ).strip()

    candidates = [
        f"{key}: {value}",
        value,
    ]

    for candidate in candidates:
        source_tokens = _runtime_quote_tokens(
            candidate
        )

        if not _runtime_quote_phrase_is_usable(
            source_tokens
        ):
            continue

        full_phrase = " ".join(
            source_tokens
        )

        if full_phrase in normalized_reasoning:
            return True

        max_window_size = min(
            14,
            len(source_tokens) - 1,
        )

        for size in range(
                max_window_size,
                RUNTIME_QUOTE_MIN_MATCH_TOKENS - 1,
                -1,
        ):
            for start in range(
                    0,
                    len(source_tokens) - size + 1,
            ):
                phrase_tokens = source_tokens[
                    start:start + size
                ]

                if not _runtime_quote_phrase_is_usable(
                    phrase_tokens
                ):
                    continue

                if (
                        " ".join(
                            phrase_tokens
                        )
                        in normalized_reasoning
                ):
                    return True

    return False


def _runtime_memory_quote_response_id(
        context,
) -> str:

    return str(
        getattr(
            context,
            "runtime_current_turn_id",
            "",
        )
        or getattr(
            context,
            "runtime_current_sequence_turn_id",
            "",
        )
        or getattr(
            context,
            "assistant_message_count",
            0,
        )
        or getattr(
            context,
            "turn_number",
            0,
        )
        or "current"
    )


def ensure_runtime_memory_quote_history(
        context,
) -> dict:

    history = getattr(
        context,
        "runtime_memory_quote_history",
        None,
    )

    if not isinstance(
            history,
            dict,
    ):
        history = {}
        context.runtime_memory_quote_history = history

    return history


def _runtime_memory_quote_stats(
        context,
        identity: str,
) -> dict:

    history = ensure_runtime_memory_quote_history(
        context
    )
    stats = history.get(
        identity,
    )

    if not isinstance(
            stats,
            dict,
    ):
        stats = {}
        history[identity] = stats

    stats["total_quotes_count"] = int(
        stats.get(
            "total_quotes_count",
            0,
        )
        or 0
    )
    stats["messages_quote_count"] = int(
        stats.get(
            "messages_quote_count",
            0,
        )
        or 0
    )

    return stats


def collect_runtime_memory_reasoning_quote_identities(
        *,
        memory: str,
        reasoning: str,
        context=None,
) -> set[str]:

    normalized_reasoning = _normalize_runtime_quote_text(
        reasoning
    )

    if not normalized_reasoning:
        return set()

    display_memory = build_runtime_memory_context_text(
        memory,
        context,
    )
    lines = parse_runtime_memory_lines(
        display_memory
    )
    identities = set()

    for line in lines:
        identity = runtime_memory_line_identity(
            line
        )

        if (
                identity
                and runtime_memory_line_was_quoted(
                    line=line,
                    normalized_reasoning=normalized_reasoning,
                )
        ):
            identities.add(
                identity
            )

    return identities


def record_runtime_memory_reasoning_quotes(
        context,
        reasoning: str,
        *,
        memory: str | None = None,
        response_id: str | None = None,
) -> dict:

    cited_identities = collect_runtime_memory_reasoning_quote_identities(
        memory=(
            getattr(
                context,
                "runtime_memory",
                "",
            )
            if memory is None
            else memory
        ),
        reasoning=reasoning,
        context=context,
    )

    if not cited_identities:
        context.runtime_memory_pending_quote_identities = set()
        return {
            "quoted_line_count": 0,
            "quoted_identities": [],
        }

    response_key = str(
        response_id
        or _runtime_memory_quote_response_id(
            context
        )
    )
    history = ensure_runtime_memory_quote_history(
        context
    )

    for identity in cited_identities:
        stats = _runtime_memory_quote_stats(
            context,
            identity,
        )
        last_response_id = str(
            stats.get(
                "last_response_id",
                "",
            )
            or ""
        )

        if last_response_id == response_key:
            continue

        stats["total_quotes_count"] += 1
        stats["messages_quote_count"] += 1
        stats["last_response_id"] = response_key

    context.runtime_memory_quote_history = history
    context.runtime_memory_pending_quote_identities = set(
        cited_identities
    )

    return {
        "quoted_line_count": len(
            cited_identities
        ),
        "quoted_identities": sorted(
            cited_identities
        ),
    }


def apply_runtime_memory_quote_stats(
        line: dict,
        context,
        *,
        pending_quote_identities: set[str] | None = None,
) -> float:

    identity = runtime_memory_line_identity(
        line
    )

    if not identity or context is None:
        line["total_quotes_count"] = 0
        line["messages_quote_count"] = 0
        line["quote_boost"] = 0.0
        return 0.0

    stats = ensure_runtime_memory_quote_history(
        context
    ).get(
        identity,
        {},
    )

    line["total_quotes_count"] = int(
        stats.get(
            "total_quotes_count",
            0,
        )
        or 0
    )
    line["messages_quote_count"] = int(
        stats.get(
            "messages_quote_count",
            0,
        )
        or 0
    )

    quote_boost = (
        STRENGTH_QUOTE_BOOST
        if (
                pending_quote_identities
                and identity in pending_quote_identities
        )
        else 0.0
    )
    line["quote_boost"] = quote_boost

    return quote_boost


def format_runtime_memory_quote_suffix(
        line: dict,
) -> str:

    total_quotes_count = int(
        line.get(
            "total_quotes_count",
            0,
        )
        or 0
    )
    messages_quote_count = int(
        line.get(
            "messages_quote_count",
            0,
        )
        or 0
    )

    if (
            total_quotes_count <= 0
            and messages_quote_count <= 0
    ):
        return ""

    return (
        f" [ total_quotes_count: {total_quotes_count} ]"
        f" [ messages_quote_count: {messages_quote_count} ]"
    )


def format_runtime_memory_status_suffix(
        line: dict,
        *,
        now: datetime | None = None,
) -> str:

    return format_runtime_memory_lifecycle_suffix(
        line,
        now=now,
    )


def build_runtime_memory_annotated_text(
        lines: list[dict],
        *,
        now: datetime | None = None,
) -> str:

    annotated_lines = []

    for line in lines:
        key = str(
            line.get(
                "key",
                "note",
            )
            or "note"
        ).strip()
        value = str(
            line.get(
                "value",
                "",
            )
            or ""
        ).strip()

        annotated_lines.append(
            (
                f"{key}: {value}"
                f"{format_runtime_memory_status_suffix(line, now=now)}"
                f"{format_runtime_memory_quote_suffix(line)}"
            ).strip()
        )

    return "\n".join(
        annotated_lines
    ).strip()


def get_strength_zones(
        lines: list[dict],
) -> dict:
    hot = []
    excluded_hot_memory_keys = {
        normalize_memory_key(
            key
        )
        for key in HOT_MEMORY_KEY_EXCLUDED_KEYS
    }

    for line in lines:
        key = line.get("key", "")
        strength = line.get("strength", 0.0)
        if strength >= HOT_THRESHOLD:
            if normalize_memory_key(
                key
            ) in excluded_hot_memory_keys:
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


def runtime_memory_line_text(
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


def apply_runtime_memory_diff(
        current_lines: list[dict],
        previous_snapshot: dict | None,
        context=None,
        pending_quote_identities: set[str] | None = None,
        snapshot_time: datetime | None = None,
) -> list[dict]:

    snapshot_time = (
        snapshot_time
        if isinstance(snapshot_time, datetime)
        else get_runtime_memory_snapshot_datetime(context)
    )

    if not previous_snapshot:
        for line in current_lines:
            quote_boost = apply_runtime_memory_quote_stats(
                line,
                context,
                pending_quote_identities=pending_quote_identities,
            )
            line["key_status"] = "new"
            line["value_status"] = "new"
            line["key_change_ratio"] = 1.0
            line["value_change_ratio"] = 1.0
            line["status"] = "new"
            set_runtime_memory_line_lifecycle(
                line,
                None,
                changed=False,
                snapshot_time=snapshot_time,
            )
            line["strength"] = compute_line_strength(
                prev_strength=None,
                change_ratio_val=1.0,
                is_new=True,
                quote_boost=quote_boost,
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
    previous_by_identity = {}

    for previous_line in previous_lines:
        normalized_key = normalize_memory_key(
            previous_line.get(
                "key",
                ""
            )
        )

        if normalized_key:
            previous_by_normalized_key[normalized_key] = previous_line

        identity = runtime_memory_line_identity(
            previous_line
        )

        if identity:
            previous_by_identity[identity] = previous_line

    for line in current_lines:
        quote_boost = apply_runtime_memory_quote_stats(
            line,
            context,
            pending_quote_identities=pending_quote_identities,
        )

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
        current_identity = runtime_memory_line_identity(
            line
        )
        exact_previous_line = previous_by_identity.get(
            current_identity
        )

        previous_line = (
            exact_previous_line
            or previous_by_normalized_key.get(
                normalized_key
            )
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
            set_runtime_memory_line_lifecycle(
                line,
                None,
                changed=False,
                snapshot_time=snapshot_time,
            )
            line["strength"] = compute_line_strength(
                prev_strength=None,
                change_ratio_val=1.0,
                is_new=True,
                quote_boost=quote_boost,
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
            lifecycle_changed = True

        else:
            line["status"] = "same"
            lifecycle_changed = False

        set_runtime_memory_line_lifecycle(
            line,
            previous_line,
            changed=lifecycle_changed,
            snapshot_time=snapshot_time,
        )

        exact_identity_match = (
                exact_previous_line is not None
                and exact_previous_line is previous_line
        )

        line["strength"] = compute_line_strength(
            prev_strength=(
                previous_line.get("strength")
                if exact_identity_match
                else None
            ),
            change_ratio_val=(
                max(key_delta, value_delta)
                if exact_identity_match
                else 1.0
            ),
            is_new=not exact_identity_match,
            quote_boost=quote_boost,
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
                "total_quotes_count": line.get(
                    "total_quotes_count",
                    0,
                ),
                "messages_quote_count": line.get(
                    "messages_quote_count",
                    0,
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
    previous_by_identity = {}

    for previous_line in previous_lines:
        normalized_key = normalize_memory_key(
            previous_line.get(
                "key",
                "",
            )
        )

        if normalized_key:
            previous_by_normalized_key[normalized_key] = previous_line

        identity = runtime_memory_line_identity(
            previous_line
        )

        if identity:
            previous_by_identity[identity] = previous_line

    matched_previous_ids = set()

    for line in current_lines:

        key = (
                line.get(
                    "key",
                    "",
                )
                or ""
        ).strip()

        normalized_key = normalize_memory_key(
            key
        )

        previous_line = previous_by_identity.get(
            runtime_memory_line_identity(
                line
            )
        ) or previous_by_normalized_key.get(
            normalized_key
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
                "total_quotes_count": line.get(
                    "total_quotes_count",
                    0,
                ),
                "messages_quote_count": line.get(
                    "messages_quote_count",
                    0,
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
                "previous_total_quotes_count": previous_line.get(
                    "total_quotes_count",
                    0,
                ),
                "previous_messages_quote_count": previous_line.get(
                    "messages_quote_count",
                    0,
                ),
                "current_total_quotes_count": line.get(
                    "total_quotes_count",
                    0,
                ),
                "current_messages_quote_count": line.get(
                    "messages_quote_count",
                    0,
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
            "total_quotes_count": previous_line.get(
                "total_quotes_count",
                0,
            ),
            "messages_quote_count": previous_line.get(
                "messages_quote_count",
                0,
            ),
        })
        total_diff += 20

    return {
        "patch": patch,
        "total_diff": total_diff,
    }

def build_runtime_memory_snapshot(
        context,
        memory: str,
) -> dict:

    snapshot_time = get_runtime_memory_snapshot_datetime(
        context
    )
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

    pending_quote_identities = getattr(
        context,
        "runtime_memory_pending_quote_identities",
        set(),
    )

    lines = apply_runtime_memory_diff(
        lines,
        previous_snapshot,
        context=context,
        pending_quote_identities=pending_quote_identities,
        snapshot_time=snapshot_time,
    )

    patch_details = build_runtime_memory_patch(
        lines,
        previous_snapshot,
    )

    existing_runtime_memory_ids = [
        snapshot.get("runtime_memory_id", "")
        for snapshot in snapshots
        if isinstance(snapshot, dict)
    ]

    return {
        "session_id": getattr(context, "session_id", ""),
        "runtime_memory_id": generate_short_runtime_id(
            existing_runtime_memory_ids
        ),
        "index": len(snapshots),
        "turn_number": getattr(context, "turn_number", 0),
        "runtime_turn_counter": getattr(
            context,
            "runtime_turn_counter",
            0,
        ),
        "user_message_count": getattr(context, "user_message_count", 0),
        "assistant_message_count": getattr(
            context,
            "assistant_message_count",
            0,
        ),
        # Keep the causal L1 revision inside the snapshot itself. The browser
        # prefers its newest in-memory snapshot during a soft reconnect; if
        # this field is missing it falls back to zero and the backend can
        # replay an already committed crash-recovery journal after restart.
        "runtime_memory_updates": getattr(
            context,
            "runtime_memory_updates",
            0,
        ),
        "current_session_user_message_count": getattr(
            context,
            "current_session_user_message_count",
            0,
        ),
        "current_session_assistant_message_count": getattr(
            context,
            "current_session_assistant_message_count",
            0,
        ),
        "created_at": format_runtime_memory_lifecycle_timestamp(
            snapshot_time
        ),
        "timestamp": format_runtime_memory_snapshot_timestamp(
            snapshot_time
        ),
        "raw_memory": display_memory,
        "annotated_memory": build_runtime_memory_annotated_text(
            lines,
            now=snapshot_time,
        ),
        "lines": lines,
        "patch": patch_details["patch"],
        "total_diff": patch_details["total_diff"],
    }


def build_runtime_session_checkpoint(
    context,
) -> dict:

    def _dict_list(value, *, limit: int | None = None) -> list[dict]:
        source = value if isinstance(value, list) else []
        if limit is not None:
            source = source[-limit:]
        return [
            dict(item)
            for item in source
            if isinstance(item, dict)
        ]

    reasoning = str(
        getattr(
            context,
            "runtime_turn_reasoning_content",
            "",
        )
        or getattr(
            context,
            "runtime_previous_reasoning_content",
            "",
        )
        or ""
    ).strip()

    loaded_memory_ids = [
        str(item or "").strip()
        for item in getattr(
            context,
            "runtime_loaded_delayed_memory_ids",
            [],
        ) or []
        if str(item or "").strip()
    ]

    attached_file_ids = [
        str(item or "").strip()
        for item in getattr(
            context,
            "runtime_attached_file_ids",
            [],
        ) or []
        if str(item or "").strip()
    ]

    active_memory_records = [
        str(item or "").strip()
        for item in getattr(
            context,
            "active_memory_records",
            [],
        ) or []
        if str(item or "").strip()
    ]

    current_size = getattr(
        context,
        "runtime_avatar_current_size",
        {},
    )

    current_session_id = get_session_action_session_id(
        context
    )
    session_action_history = [
        item
        for item in getattr(
            context,
            "runtime_session_action_history",
            [],
        ) or []
        if session_action_belongs_to_session(
            item,
            current_session_id,
        )
    ]
    runtime_tool_results = []
    created_ats = getattr(
        context,
        "runtime_tool_result_created_ats",
        [],
    )
    if not isinstance(
        created_ats,
        list,
    ):
        created_ats = []

    for index, item in enumerate(
        getattr(
            context,
            "runtime_tool_results",
            [],
        )
        or []
    ):
        if not isinstance(
            item,
            dict,
        ):
            continue

        kind = str(
            item.get(
                "kind",
                "",
            )
            or ""
        ).strip()
        if not kind:
            continue

        result = item.get(
            "result"
        )
        if isinstance(
            result,
            str,
        ):
            result = result[:32000]

        restored_item = {
            "kind": kind,
            "result": result,
        }
        result_id = str(
            item.get(
                "id",
                "",
            )
            or ""
        ).strip()
        if result_id:
            restored_item["id"] = result_id

        created_at = item.get(
            "created_at",
            None,
        )
        if created_at is None and index < len(
            created_ats
        ):
            created_at = created_ats[index]

        try:
            created_at_float = float(
                created_at
                or 0
            )
        except (
            TypeError,
            ValueError,
        ):
            created_at_float = 0.0

        if created_at_float > 0:
            restored_item["created_at"] = created_at_float

        runtime_tool_results.append(
            restored_item
        )

    from utils.context.files import select_file_tool_results
    runtime_tool_results = select_file_tool_results(runtime_tool_results, 20)

    return {
        "session_id": str(
            getattr(
                context,
                "session_id",
                "",
            )
            or ""
        ).strip(),
        "previous_session_id": str(
            getattr(
                context,
                "previous_session_id",
                "",
            )
            or ""
        ).strip(),
        "recent_turns": _dict_list(
            getattr(
                context,
                "runtime_recent_turns",
                [],
            ),
            limit=3,
        ),
        "previous_reasoning": reasoning,
        "session_actions": _dict_list(
            session_action_history,
            limit=200,
        ),
        "tool_results": runtime_tool_results,
        "runtime_turn_counter": int(
            getattr(
                context,
                "runtime_turn_counter",
                0,
            )
            or 0
        ),
        "turn_number": int(
            getattr(
                context,
                "turn_number",
                0,
            )
            or 0
        ),
        "user_message_count": int(
            getattr(
                context,
                "user_message_count",
                0,
            )
            or 0
        ),
        "assistant_message_count": int(
            getattr(
                context,
                "assistant_message_count",
                0,
            )
            or 0
        ),
        "current_session_user_message_count": int(
            getattr(
                context,
                "current_session_user_message_count",
                0,
            )
            or 0
        ),
        "current_session_assistant_message_count": int(
            getattr(
                context,
                "current_session_assistant_message_count",
                0,
            )
            or 0
        ),
        "runtime_memory_updates": int(
            getattr(
                context,
                "runtime_memory_updates",
                0,
            )
            or 0
        ),
        "loaded_memory_ids": loaded_memory_ids,
        "attached_file_ids": attached_file_ids,
        "active_memory_records": active_memory_records,
        "current_jin_color": str(
            getattr(
                context,
                "jin_color",
                "",
            )
            or ""
        ).strip(),
        "current_jin_size": (
            dict(current_size)
            if isinstance(current_size, dict)
            else None
        ),
        "current_jin_position": (
            dict(
                getattr(
                    context,
                    "runtime_avatar_current_position",
                    {},
                )
                or {}
            )
        ),
        "current_jin_collapsed": bool(
            getattr(
                context,
                "runtime_avatar_panel_collapsed",
                False,
            )
        ),
        "current_jin_speed": int(
            getattr(
                context,
                "runtime_avatar_move_speed",
                900,
            )
            or 900
        ),
        "current_window_size": (
            dict(
                getattr(
                    context,
                    "runtime_avatar_window_size",
                    {},
                )
                or {}
            )
        ),
    }


# Runtime L1 memory emit/update helpers.
def _average_diff(values: list[float]) -> float:
    if not values:
        return 0

    return round(
        sum(values) / len(values),
        2,
    )


def _diff_value_range(values: list[float]) -> float:
    if not values:
        return 0

    return round(
        max(values) - min(values),
        2,
    )


def _format_diff_value(value: float) -> str:
    return (
        f"{value:.2f}"
        .rstrip("0")
        .rstrip(".")
    )


def _runtime_l1_patch_total_diff(patch: dict) -> float:
    total_diff = 0

    total_diff += 30 * len(
        patch.get("added", []) or []
    )
    total_diff += 20 * len(
        patch.get("removed", []) or []
    )

    for entry in patch.get("changed", []) or []:
        total_diff += round(
            (
                entry.get("key_change_ratio", 0)
                + entry.get("value_change_ratio", 0)
            )
            * 50,
            2,
        )

    return total_diff


def _compact_runtime_user_message(
        value,
        *,
        limit: int = 240,
) -> str:
    text = " ".join(
        str(value or "").strip().split()
    )

    if len(text) <= limit:
        return text

    return text[:limit].rstrip()


async def record_runtime_l1_diff(
        context,
        snapshot: dict,
        turns: list[dict] | None = None,
) -> None:
    patch = snapshot.get("patch", {}) or {}
    total_diff = (
        _runtime_l1_patch_total_diff(patch)
        if patch
        else snapshot.get("total_diff", 0)
    )
    context.runtime_conversation_activity_diff = total_diff

    observed_turns = list(turns or [])
    observed_user_messages = [
        _compact_runtime_user_message(
            turn.get("user_message", "")
        )
        for turn in observed_turns
        if _compact_runtime_user_message(
            turn.get("user_message", "")
        )
    ]
    latest_user_message = (
        observed_user_messages[-1]
        if observed_user_messages
        else ""
    )
    user_turn_count = int(
        getattr(context, "user_message_count", 0)
        or 0
    )

    diff_entry = {
        "turn_number": user_turn_count,
        "snapshot_index": snapshot.get("index", 0),
        "total_diff": total_diff,
        "changes": patch,
        "user_message": latest_user_message,
        "user_messages": observed_user_messages[-3:],
    }

    if not hasattr(context, "runtime_l1_diff_history"):
        context.runtime_l1_diff_history = []

    context.runtime_l1_diff_history.append({
        **diff_entry,
        "history_index": len(context.runtime_l1_diff_history),
    })

    if total_diff == 0:
        latest_turn = (
            observed_turns[-1]
            if observed_turns
            else {}
        )
        context.runtime_zero_diff_alert = {
            "turn_number": user_turn_count,
            "user_message": latest_turn.get("user_message", ""),
            "assistant_message": latest_turn.get("assistant_message", ""),
            "reason": "Previous FRAME memory update produced total_diff 0.",
        }

    await log_memory_event(
        context,
        level="FRAME",
        message=(
            "FRAME diff "
            f"+{_format_diff_value(total_diff)}"
        ),
        details=getattr(
            context,
            "runtime_l1_last_summarizer_response_details",
            None,
        ),
        fallback_channel="service",
        event="summarizer_response",
    )

    await emit_runtime_l1_diff_update(context)


async def log_runtime_frame_snapshot(context, snapshot: dict) -> None:
    from utils.chat_log import save_frame_snapshot

    try:
        save_frame_snapshot(context, snapshot)
    except Exception as error:
        await log_memory_event(
            context,
            level="L1",
            message="FRAME log save failed",
            details=str(error),
            fallback_channel="error",
        )


async def emit_runtime_memory_update(
        context,
) -> dict:

    emitter = getattr(
        context,
        "emitter",
        None,
    )

    memory = getattr(context, "runtime_memory", "")
    display_memory = build_runtime_memory_context_text(
        memory,
        context,
    )

    if not hasattr(
        context,
        "runtime_memory_snapshots",
    ):
        context.runtime_memory_snapshots = []

    snapshot = build_runtime_memory_snapshot(context, memory)

    context.runtime_memory_snapshots.append(snapshot)
    context.runtime_memory_snapshot_index = snapshot["index"]
    await log_runtime_frame_snapshot(context, snapshot)
    context.runtime_memory_pending_quote_identities = set()

    emit = getattr(
        emitter,
        "emit",
        None,
    )

    await safe_call(
        emit,
        {
            "type": "runtime_memory_update",
            "memory": display_memory,
            "updates": getattr(context, "runtime_memory_updates", 0),
            "snapshot": snapshot,
            "session_snapshot": build_runtime_session_checkpoint(
                context
            ),
            "snapshots_count": len(context.runtime_memory_snapshots),
            "snapshot_index": context.runtime_memory_snapshot_index,
        },
    )

    return snapshot


def build_runtime_l1_diff_stats(
        diff_history: list[dict],
) -> dict:

    values = [
        item.get(
            "total_diff",
            0,
        )
        for item in diff_history
    ]

    return {
        "count": len(values),
        "average": _average_diff(values),
        "range": _diff_value_range(values),
        "min": min(values) if values else 0,
        "max": max(values) if values else 0,
    }




def rebuild_latest_runtime_memory_snapshot(
        context,
) -> dict | None:

    snapshots = getattr(
        context,
        "runtime_memory_snapshots",
        [],
    )

    if not snapshots:
        return None

    latest_snapshot = snapshots[-1]
    snapshot_time = get_runtime_memory_snapshot_datetime(
        context
    )
    previous_snapshot = (
        snapshots[-2]
        if len(snapshots) > 1
        else None
    )

    display_memory = build_runtime_memory_context_text(
        getattr(
            context,
            "runtime_memory",
            "",
        ),
        context,
    )

    lines = parse_runtime_memory_lines(
        display_memory
    )

    lines = apply_runtime_memory_diff(
        lines,
        previous_snapshot,
        context=context,
        pending_quote_identities=getattr(
            context,
            "runtime_memory_pending_quote_identities",
            set(),
        ),
        snapshot_time=snapshot_time,
    )

    patch_details = build_runtime_memory_patch(
        lines,
        previous_snapshot,
    )

    refreshed_snapshot = {
        **latest_snapshot,
        "created_at": latest_snapshot.get(
            "created_at",
        ) or format_runtime_memory_lifecycle_timestamp(
            snapshot_time
        ),
        "timestamp": latest_snapshot.get(
            "timestamp",
        ) or format_runtime_memory_snapshot_timestamp(
            latest_snapshot.get(
                "created_at",
            ) or snapshot_time
        ),
        "raw_memory": display_memory,
        "annotated_memory": build_runtime_memory_annotated_text(
            lines,
            now=snapshot_time,
        ),
        "lines": lines,
        "patch": patch_details["patch"],
        "total_diff": patch_details["total_diff"],
    }

    snapshots[-1] = refreshed_snapshot
    context.runtime_memory_snapshots = snapshots
    context.runtime_memory_snapshot_index = refreshed_snapshot["index"]

    return refreshed_snapshot


async def emit_runtime_memory_snapshot_refresh(
        context,
        snapshot: dict | None,
) -> None:

    if snapshot is None:
        return

    await log_runtime_frame_snapshot(context, snapshot)
    emitter = getattr(
        context,
        "emitter",
        None,
    )

    emit = getattr(
        emitter,
        "emit",
        None,
    )

    await safe_call(
        emit,
        {
            "type": "runtime_memory_update",
            "memory": snapshot.get(
                "raw_memory",
                "",
            ),
            "updates": getattr(
                context,
                "runtime_memory_updates",
                0,
            ),
            "snapshot": snapshot,
            "session_snapshot": build_runtime_session_checkpoint(
                context
            ),
            "snapshots_count": len(
                getattr(
                    context,
                    "runtime_memory_snapshots",
                    [],
                )
                or []
            ),
            "snapshot_index": getattr(
                context,
                "runtime_memory_snapshot_index",
                snapshot.get(
                    "index",
                    0,
                ),
            ),
            "replace_latest": True,
        },
    )

async def emit_runtime_l1_diff_update(
        context,
) -> None:

    emitter = getattr(
        context,
        "emitter",
        None,
    )

    emit = getattr(
        emitter,
        "emit",
        None,
    )

    history = list(
        getattr(
            context,
            "runtime_l1_diff_history",
            [],
        )
        or []
    )

    snapshots = list(
        getattr(
            context,
            "runtime_memory_snapshots",
            [],
        )
        or []
    )
    latest_lines = (
        snapshots[-1].get("lines", [])
        if snapshots
        else []
    )

    await safe_call(
        emit,
        {
            "type": "runtime_l1_diff_update",
            "diffs": history,
            "stats": build_runtime_l1_diff_stats(
                history
            ),
            "strength_map": build_strength_map(
                latest_lines
            ),
            "strength_zones": get_strength_zones(
                latest_lines
            ),
        },
    )


async def emit_runtime_action_completed(
        context,
        *,
        action: str,
) -> None:

    from utils.runtime_action_abort import (
        mark_runtime_action_completed,
    )

    mark_runtime_action_completed(
        context,
        action=action,
    )

    emitter = getattr(
        context,
        "emitter",
        None,
    )

    emit = getattr(
        emitter,
        "emit",
        None,
    )

    await safe_call(
        emit,
        {
            "type": "runtime_action",
            "action": action,
            "status": "completed",
        },
    )
