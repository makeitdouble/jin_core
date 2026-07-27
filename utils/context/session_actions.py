# Builds session action history and current sequence context blocks.
import re
import time
from xml.sax.saxutils import escape

from utils.brain_client_utils import (
    indent_xml,
)
from utils.session_actions_history import (
    PAYLOAD_DISTINCT_SESSION_ACTIONS,
    format_session_action_display_parts,
    get_current_action_sequence_started_at,
    get_current_action_sequence_turn_id,
)


def _normalize_session_action_history_item(
    item,
) -> dict:

    created_at = None
    runtime_turn_id = ""

    if isinstance(
        item,
        dict,
    ):
        text = str(
            item.get(
                "text",
                "",
            )
            or ""
        ).strip()
        raw_created_at = item.get(
            "created_at"
        )
        if isinstance(
            raw_created_at,
            (int, float),
        ):
            created_at = float(
                raw_created_at
            )
        runtime_turn_id = str(
            item.get(
                "runtime_turn_id",
                "",
            )
            or ""
        ).strip()
        parts = item.get(
            "parts",
            [],
        )
    else:
        text = str(
            item
            or ""
        ).strip()
        parts = []

    return {
        "text": text,
        "parts": parts,
        "created_at": created_at,
        "runtime_turn_id": runtime_turn_id,
    }


def _is_current_sequence_action(
    item: dict,
    *,
    current_turn_id: str,
    turn_started_at,
) -> bool:

    item_turn_id = str(
        item.get(
            "runtime_turn_id",
            "",
        )
        or ""
    ).strip()

    if (
        current_turn_id
        and item_turn_id
        and item_turn_id != current_turn_id
    ):
        return False

    created_at = item.get(
        "created_at"
    )

    if (
        isinstance(
            created_at,
            (int, float),
        )
        and isinstance(
            turn_started_at,
            (int, float),
        )
    ):
        return float(created_at) >= float(turn_started_at)

    return bool(
        current_turn_id
        and item_turn_id == current_turn_id
    )


def _format_memory_action_context_part(
    part: dict,
) -> str:

    action = str(
        part.get(
            "text",
            "",
        )
        or ""
    ).strip()
    normalized_action = action.upper()
    detail = str(
        part.get(
            "detail",
            "",
        )
        or ""
    ).strip()
    part_id = str(
        part.get(
            "id",
            "",
        )
        or ""
    ).strip()

    if normalized_action not in PAYLOAD_DISTINCT_SESSION_ACTIONS:
        return ""

    if (
        not part_id
        and not detail
    ):
        return ""

    if part_id and detail and part_id != detail:
        detail_label = (
            "title"
            if "DELAYED_MEMORY" in normalized_action
            else "content"
        )
        return (
            f"{action} - id: {part_id}; "
            f"{detail_label}: {detail}"
        )

    if normalized_action in {
        "SAVE_ACTIVE_MEMORY",
        "SAVE_DELAYED_MEMORY_CONTENT",
    }:
        if detail:
            return f"{action} - {detail}"

        return action

    if normalized_action in {
        "RESOLVE_ACTIVE_MEMORY",
        "REMOVE_DELAYED_MEMORY",
    }:
        resolved_id = part_id or detail

        if resolved_id:
            return f"{action} - id: {resolved_id}"

    if detail:
        return f"{action} - {detail}"

    return action


def _format_session_action_context_parts(
    parts,
    *,
    fallback_text: str,
) -> str:

    context_parts = []

    for part in parts or []:
        memory_part = _format_memory_action_context_part(
            part
        )

        if memory_part:
            context_parts.append(
                memory_part
            )
            continue

        formatted = format_session_action_display_parts(
            [
                part,
            ],
        )

        if formatted:
            context_parts.append(
                formatted
            )

    if context_parts:
        return ", ".join(
            context_parts
        )

    return str(
        fallback_text
        or ""
    ).strip()


def build_session_actions_history_context(
    context=None,
    *,
    current_sequence: bool = False,
) -> str:

    if context is None:
        return ""

    history_items = [
        _normalize_session_action_history_item(
            item
        )
        for item in list(
            getattr(
                context,
                "runtime_session_action_history",
                [],
            )
            or []
        )
    ]
    history_items = [
        item
        for item in history_items
        if item["text"]
    ]

    if current_sequence:
        current_turn_id = get_current_action_sequence_turn_id(
            context
        )
        turn_started_at = get_current_action_sequence_started_at(
            context
        )
        history_items = [
            item
            for item in history_items
            if _is_current_sequence_action(
                item,
                current_turn_id=current_turn_id,
                turn_started_at=turn_started_at,
            )
        ]

    if not history_items:
        return ""

    now = time.time()
    sequence_turn_ids = {
        str(
            turn_id
            or ""
        ).strip()
        for turn_id in (
            getattr(
                context,
                "runtime_action_sequence_turn_ids",
                [],
            )
            or []
        )
        if str(
            turn_id
            or ""
        ).strip()
    }
    lines = []
    action_index = 0
    open_sequence_turn_id = ""

    if current_sequence:
        lines.append(
            "--- Sequence started ---"
        )

    for item in history_items:
        runtime_turn_id = item[
            "runtime_turn_id"
        ]
        item_is_sequence = (
            not current_sequence
            and runtime_turn_id in sequence_turn_ids
        )

        if item_is_sequence:
            if open_sequence_turn_id != runtime_turn_id:
                if open_sequence_turn_id:
                    lines.append(
                        "--- Sequence ended ---"
                    )
                lines.append(
                    "--- Sequence started ---"
                )
                open_sequence_turn_id = runtime_turn_id
        elif open_sequence_turn_id:
            lines.append(
                "--- Sequence ended ---"
            )
            open_sequence_turn_id = ""

        text = _format_session_action_context_parts(
            item.get(
                "parts",
                [],
            ),
            fallback_text=item[
                "text"
            ],
        )
        created_at = item.get(
            "created_at"
        )
        if created_at is not None:
            text = (
                f"{text} ( {format_session_action_age(now - created_at)} ago )"
            )

        action_index += 1
        if current_sequence:
            lines.append(
                f"Step {action_index} - {text}"
            )
        else:
            lines.append(
                f"{action_index}. {text}"
            )

    if open_sequence_turn_id:
        lines.append(
            "--- Sequence ended ---"
        )

    tag_name = (
        "CURRENT_SEQUENCE"
        if current_sequence
        else "SESSION_ACTIONS_HISTORY"
    )

    return (
        f"<{tag_name}>\n"
        f"{indent_xml(escape(chr(10).join(lines)), spaces=4)}\n"
        f"</{tag_name}>"
    )


def strip_actions_history_context(
    system_prompt: str,
) -> str:

    prompt = str(
        system_prompt
        or ""
    )

    for tag_name in (
        "SESSION_ACTIONS_HISTORY",
        "CURRENT_SEQUENCE",
        "CURRENT_ACTIONS_HISTORY",
        "SEQUENCE_ORIGIN_REQUEST",
        "PREVIOUS_CHAT_MESSAGES",
    ):
        prompt = re.sub(
            rf"(?:^|\n)<{tag_name}>.*?</{tag_name}>\n*",
            "\n",
            prompt,
            flags=re.DOTALL,
        )

    return prompt.strip()


def format_session_action_age(
    elapsed_seconds,
) -> str:

    seconds = max(
        1,
        int(
            elapsed_seconds
        ),
    )

    if seconds < 60:
        return f"{seconds}s"

    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"

    hours = minutes // 60
    if hours < 24:
        return f"{hours}h"

    days = hours // 24
    return f"{days}d"
