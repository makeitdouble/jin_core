# Builds recent chat message and sequence origin context blocks.
import time
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

    if not isinstance(
        created_at,
        (int, float),
    ):
        return ""

    if created_at <= 0:
        return ""

    if now is None:
        now = time.time()

    return (
        f" ( {format_session_action_age(now - float(created_at))} ago )"
    )


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


def build_sequence_origin_request_context(
    user_message: str,
    *,
    created_at=None,
) -> str:

    text = str(
        user_message
        or ""
    ).strip()

    if not text:
        return ""

    text = append_context_message_age(
        text,
        created_at,
    )

    return (
        "<SEQUENCE_ORIGIN_REQUEST>\n"
        "\n!!! WARNING: THIS IS NOT CURRENT USER REQUEST! TREAT IT AS A PAST! !!!\n"
        f"{escape(text)}\n"
        "</SEQUENCE_ORIGIN_REQUEST>"
    )


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
