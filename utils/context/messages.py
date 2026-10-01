# Builds recent chat message and sequence origin context blocks.
import re
import time
from datetime import datetime
from math import isfinite
from xml.sax.saxutils import escape

from runtime.runtime_context import RECENT_MESSAGES_MAX_PAIRS

from .session_actions import (
    build_previous_chat_action_messages,
    format_session_action_age,
)


def normalize_recent_message_text(
    text: str,
) -> str:

    return str(
        text
        or ""
    ).replace(
        "\r\n",
        "\n",
    ).replace(
        "\r",
        "\n",
    ).replace(
        "\n",
        "\\n",
    ).strip()


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


def normalize_previous_chat_messages_block(
    value: str,
) -> str:

    text = str(
        value
        or ""
    ).strip()

    if not text:
        return ""

    # New prompts use one dialogue block for both ordinary chat history and
    # archived-session bootstrap. Accept the legacy restore wrapper so older
    # browser/archive checkpoints remain readable after the rename.
    text = re.sub(
        r"<OLD_SESSION_RESTORED_STATE(?P<attrs>\s+[^>]*)?>",
        lambda match: (
            "<PREVIOUS_CHAT_MESSAGES"
            + (match.group("attrs") or "")
            + ">"
        ),
        text,
        count=1,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"</OLD_SESSION_RESTORED_STATE>",
        "</PREVIOUS_CHAT_MESSAGES>",
        text,
        count=1,
        flags=re.IGNORECASE,
    )

    return text


def append_inflight_jin_messages_to_context(
    context_text: str,
    messages: list[dict] | None,
) -> str:

    text = normalize_previous_chat_messages_block(
        context_text
    )
    pending = [
        item
        for item in (
            messages
            or []
        )
        if isinstance(item, dict)
        and str(item.get("text", "") or "").strip()
    ]

    if not pending:
        return text

    if not text:
        text = "<PREVIOUS_CHAT_MESSAGES>\n</PREVIOUS_CHAT_MESSAGES>"

    closing_tag = "</PREVIOUS_CHAT_MESSAGES>"
    closing_index = text.rfind(
        closing_tag
    )
    if closing_index < 0:
        return text

    now = time.time()
    lines = []
    for item in pending:
        jin_text = normalize_recent_message_text(
            item.get(
                "text",
                "",
            )
        )
        if not jin_text:
            continue
        jin_text = append_context_message_age(
            jin_text,
            item.get(
                "created_at",
            ),
            now=now,
        )
        lines.append(
            f"<JIN>{escape(jin_text)}"
        )

    if not lines:
        return text

    prefix = text[:closing_index].rstrip()
    suffix = text[closing_index:]
    return (
        prefix
        + "\n"
        + "\n".join(lines)
        + "\n"
        + suffix
    )


def remember_current_sequence_jin_message(
    context,
    text: str,
    *,
    created_at: float | None = None,
) -> None:

    if context is None:
        return

    message_text = str(
        text
        or ""
    ).strip()
    if not message_text:
        return

    messages = getattr(
        context,
        "runtime_current_sequence_jin_messages",
        None,
    )
    if not isinstance(messages, list):
        messages = []
        context.runtime_current_sequence_jin_messages = messages

    messages.append({
        "text": message_text,
        "created_at": (
            float(created_at)
            if isinstance(created_at, (int, float))
            else time.time()
        ),
    })


def build_previous_chat_messages_context_text(
    recent_turns: list[dict] | None,
    *,
    extra_user_message: str = "",
    extra_user_created_at=None,
    context=None,
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

        from websocket.attachments import strip_attachment_source_text
        user_text = normalize_recent_message_text(
            strip_attachment_source_text(turn.get("user", ""))
        )
        jin_text = normalize_recent_message_text(
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

        action_messages = build_previous_chat_action_messages(
            context,
            turn.get("runtime_turn_id", ""),
        )
        for action_message in action_messages:
            action_text = normalize_recent_message_text(
                action_message.get("text", "")
            )
            if not action_text:
                continue
            action_text = append_context_message_age(
                action_text,
                action_message.get("created_at"),
                now=now,
            )
            lines.append(
                f"<JIN>{escape(action_text)}"
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

    from websocket.attachments import strip_attachment_source_text
    extra_user_text = normalize_recent_message_text(
        strip_attachment_source_text(extra_user_message)
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
    restored_dialog = str(
        getattr(
            context,
            "runtime_restored_session_dialog",
            "",
        )
        or ""
    ).strip() if context is not None else ""
    inflight_jin_messages = getattr(
        context,
        "runtime_current_sequence_jin_messages",
        [],
    ) if context is not None else []

    if restored_dialog:
        base_context = normalize_previous_chat_messages_block(
            restored_dialog
        )
    elif recent_turns or extra_user_message:
        base_context = build_previous_chat_messages_context_text(
            recent_turns,
            extra_user_message=extra_user_message,
            extra_user_created_at=getattr(
                context,
                "runtime_turn_started_at",
                None,
            ) if context is not None else None,
            context=context,
        )
    else:
        base_context = ""

    return append_inflight_jin_messages_to_context(
        base_context,
        inflight_jin_messages,
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
