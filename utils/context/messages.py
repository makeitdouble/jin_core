# Builds recent chat message and sequence origin context blocks.
import time
from datetime import datetime
from math import isfinite
from xml.sax.saxutils import escape

from runtime.runtime_context import (
    RECENT_MESSAGE_MAX_CHARS,
    RECENT_MESSAGES_MAX_PAIRS,
)

from .session_actions import (
    format_session_action_age,
)


def crop_recent_message_text(
    text: str,
    max_chars: int = RECENT_MESSAGE_MAX_CHARS,
) -> str:

    cleaned = str(
        text
        or ""
    ).replace(
        "\r\n",
        "\n",
    ).replace(
        "\r",
        "\n",
    )

    cleaned = cleaned.replace(
        "\n",
        "\\n",
    ).strip()

    if max_chars <= 0:
        return ""

    if len(cleaned) <= max_chars:
        return cleaned

    if max_chars <= 3:
        return "." * max_chars

    return (
        cleaned[: max_chars - 3].rstrip()
        + "..."
    )


def format_context_message_age_suffix(
    created_at,
    *,
    now: float | None = None,
) -> str:

    timestamp = parse_context_timestamp(
        created_at
    )

    if timestamp is None:
        return ""

    if timestamp <= 0:
        return ""

    if now is None:
        now = time.time()

    return (
        f" ( {format_session_action_age(now - timestamp)} ago )"
    )


def parse_context_timestamp(
    value,
) -> float | None:

    if isinstance(
        value,
        (int, float),
    ):
        timestamp = float(
            value
        )
        return timestamp if isfinite(timestamp) else None

    text = str(
        value
        or ""
    ).strip()

    if not text:
        return None

    try:
        timestamp = float(
            text
        )
        return timestamp if isfinite(timestamp) else None
    except ValueError:
        pass

    normalized = text
    if normalized.endswith(
        "Z"
    ):
        normalized = (
            normalized[:-1]
            + "+00:00"
        )

    try:
        timestamp = datetime.fromisoformat(
            normalized
        ).timestamp()
        return timestamp if isfinite(timestamp) else None
    except ValueError:
        return None


def append_context_message_age(
    text: str,
    created_at,
    *,
    now: float | None = None,
) -> str:

    suffix = format_context_message_age_suffix(
        created_at,
        now=now,
    )

    if not suffix:
        return text

    return f"{text}{suffix}"


def build_previous_chat_messages_context_text(
    recent_turns: list[dict] | None,
    *,
    extra_user_message: str = "",
    extra_user_created_at=None,
) -> str:

    turns = list(
        recent_turns
        or []
    )[-RECENT_MESSAGES_MAX_PAIRS:]

    lines = [
        "<PREVIOUS_CHAT_MESSAGES>",
    ]
    last_user_text = ""
    now = time.time()

    for turn in turns:
        if not isinstance(
            turn,
            dict,
        ):
            continue

        user_text = crop_recent_message_text(
            turn.get(
                "user",
                "",
            )
        )
        jin_text = crop_recent_message_text(
            turn.get(
                "jin",
                "",
            )
        )

        if user_text:
            last_user_text = user_text
            user_text = append_context_message_age(
                user_text,
                turn.get(
                    "user_created_at",
                    turn.get(
                        "created_at",
                    ),
                ),
                now=now,
            )
            lines.append(
                f"<USER>{escape(user_text)}"
            )

        if jin_text:
            jin_text = append_context_message_age(
                jin_text,
                turn.get(
                    "jin_created_at",
                    turn.get(
                        "created_at",
                    ),
                ),
                now=now,
            )
            lines.append(
                f"<JIN>{escape(jin_text)}"
            )

    extra_user_text = crop_recent_message_text(
        extra_user_message
    )

    if (
            extra_user_text
            and extra_user_text != last_user_text
    ):
        extra_user_text = append_context_message_age(
            extra_user_text,
            extra_user_created_at,
            now=now,
        )
        lines.append(
            f"<USER>{escape(extra_user_text)}"
        )

    lines.append(
        "</PREVIOUS_CHAT_MESSAGES>"
    )

    return "\n".join(
        lines
    )


def build_previous_chat_messages_context(
    context=None,
    *,
    extra_user_message: str = "",
) -> str:

    if context is None and not extra_user_message:
        return ""

    recent_turns = getattr(
        context,
        "runtime_recent_turns",
        [],
    ) if context is not None else []

    if not recent_turns and not extra_user_message:
        return ""

    return build_previous_chat_messages_context_text(
        recent_turns,
        extra_user_message=extra_user_message,
        extra_user_created_at=getattr(
            context,
            "runtime_turn_started_at",
            None,
        ) if context is not None else None,
    )


def append_previous_chat_messages(
    parts: list[str],
    context=None,
) -> None:

    previous_chat_messages_context = (
        build_previous_chat_messages_context(
            context
        )
    )

    if not previous_chat_messages_context:
        return

    parts.append(
        previous_chat_messages_context
    )
