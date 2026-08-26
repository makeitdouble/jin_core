# Builds runtime state, feedback, todo, and activity alert context blocks.
from datetime import datetime
from app_settings import (
    settings,
)
from utils.brain_client_utils import (
    get_conversation_activity_diff,
    get_conversation_activity_percent,
)
from rules.brain_context_builder import (
    build_conversation_activity_instruction,
    get_enabled_runtime_actions,
)
from contracts.rules_assembler import (
    RUNTIME_ACTION_ASSET_ACTION,
    RUNTIME_ACTION_SAVE_ACTIVE_MEMORY,
    RUNTIME_ACTION_WEB_SEARCH,
)
from rules.runtime import (
    ACTION_BLOCKED_TRIGGER_WORD_MESSAGE,
)
from runtime.runtime_context import (
    ContextContract,
    DEFAULT_JIN_COLOR,
)
from utils.actions import (
    format_jin_size_value,
    get_applied_jin_size,
    normalize_jin_size_dict,
    normalize_jin_color_payload,
    normalize_jin_position_dict,
    normalize_jin_speed_value,
    format_jin_speed_payload,
)


def format_runtime_blocked_trigger_word_message(
    blocked_trigger_word: str,
) -> str:

    return ACTION_BLOCKED_TRIGGER_WORD_MESSAGE.format(
        blocked_trigger_word=str(
            blocked_trigger_word
            or ""
        ).strip()
    )


def get_current_jin_color(
    context=None,
) -> str:

    current_color = DEFAULT_JIN_COLOR

    for event in getattr(
        context,
        "runtime_action_events",
        [],
    ) or []:
        if not isinstance(
            event,
            dict,
        ):
            continue

        event_name = str(
            event.get("name")
            or event.get("action")
            or ""
        ).strip().casefold()

        if event_name != "jin_color":
            continue

        color = normalize_jin_color_payload(
            event.get("color")
            or event.get("payload")
            or ""
        )

        if color:
            current_color = color

    return current_color


def format_current_jin_size(
    size,
) -> str:

    normalized_size = normalize_jin_size_dict(
        size
    )

    if not normalized_size:
        return ""

    return (
        "width: "
        f"{format_jin_size_value(normalized_size['width'])} "
        "height: "
        f"{format_jin_size_value(normalized_size['height'])}"
    )


def get_current_jin_size_context(
    context=None,
) -> str:

    if not bool(
        getattr(
            context,
            "runtime_avatar_panel_collapsed",
            False,
        )
    ):
        return ""

    size = normalize_jin_size_dict(
        getattr(
            context,
            "runtime_avatar_current_size",
            {},
        )
    )

    if not size:
        size = get_applied_jin_size(
            context
        )

    payload = format_current_jin_size(
        size
    )

    if not payload:
        return ""

    return payload


def format_current_jin_position(
    position,
) -> str:

    normalized = normalize_jin_position_dict(
        position
    )

    if not normalized:
        return ""

    return (
        f"x: {normalized['x']}px "
        f"y: {normalized['y']}px"
    )


def get_current_jin_position_context(
    context=None,
) -> str:

    if not bool(
        getattr(
            context,
            "runtime_avatar_panel_collapsed",
            False,
        )
    ):
        return ""

    return format_current_jin_position(
        getattr(
            context,
            "runtime_avatar_current_position",
            {},
        )
    )


def get_current_jin_speed_context(
    context=None,
) -> str:

    if not bool(
        getattr(
            context,
            "runtime_avatar_panel_collapsed",
            False,
        )
    ):
        return ""

    speed = normalize_jin_speed_value(
        getattr(
            context,
            "runtime_avatar_move_speed",
            900,
        )
    )

    return format_jin_speed_payload(
        speed if speed is not None else 900
    )


def get_current_window_size_context(
    context=None,
) -> str:

    if not bool(
        getattr(
            context,
            "runtime_avatar_panel_collapsed",
            False,
        )
    ):
        return ""

    window_size = getattr(
        context,
        "runtime_avatar_window_size",
        {},
    )

    if not isinstance(window_size, dict):
        return ""

    try:
        width = int(window_size.get("width") or 0)
        height = int(window_size.get("height") or 0)
    except (TypeError, ValueError):
        return ""

    if width <= 0 or height <= 0:
        return ""

    return f"width: {width}px height: {height}px"


def build_runtime_xml(
    context=None,
    runtime_actions=None,
) -> str:

    enabled_actions = get_enabled_runtime_actions(
        runtime_actions
    )
    conversation_activity_instruction = (
        get_conversation_activity_instruction(
            context
        )
    )
    now = datetime.now()

    return (
        ContextContract(
            user_input="",
            compressed_history="",
            system_state="ACTIVE",
            current_session_id=str(
                getattr(
                    context,
                    "session_id",
                    "",
                )
                or ""
            ).strip(),
            service_model_uid=settings.SERVICE_MODEL_UID,
            brain_model_uid=(
                settings.BRAIN_MODEL_UID
                if not settings.USE_SERVICE_AS_BRAIN
                else ""
            ),
            current_context_window=getattr(
                context,
                "runtime_current_context_window_text",
                "",
            ),
            jin_color=get_current_jin_color(
                context
            ),
            jin_size_context=get_current_jin_size_context(
                context
            ),
            jin_position_context=get_current_jin_position_context(
                context
            ),
            jin_speed_context=get_current_jin_speed_context(
                context
            ),
            window_size_context=get_current_window_size_context(
                context
            ),
            can_web_search=(
                RUNTIME_ACTION_WEB_SEARCH
                in enabled_actions
            ),
            can_use_assets=(
                RUNTIME_ACTION_ASSET_ACTION
                in enabled_actions
            ),
            can_save_active_memory=(
                RUNTIME_ACTION_SAVE_ACTIVE_MEMORY
                in enabled_actions
            ),
            timestamp=now.isoformat(),
            current_date=now.date().isoformat(),
            current_time=now.strftime("%H:%M:%S"),
            weekday=now.strftime("%A"),
            year=now.year,
            conversation_activity_instruction=(
                conversation_activity_instruction
            ),
        )
        .to_runtime_xml()
    )


def get_visible_assistant_message_count(
    context=None,
) -> int:

    if context is None:
        return 0

    assistant_message_count = int(
        getattr(
            context,
            "assistant_message_count",
            0,
        )
        or 0
    )
    user_message_count = int(
        getattr(
            context,
            "user_message_count",
            0,
        )
        or 0
    )
    pending_response_count = (
        1
        if user_message_count > assistant_message_count
        else 0
    )

    return (
        assistant_message_count
        + pending_response_count
    )


def get_visible_turn_count(
    context=None,
) -> int:

    if context is None:
        return 0

    turn_number = int(
        getattr(
            context,
            "turn_number",
            0,
        )
        or 0
    )
    user_message_count = int(
        getattr(
            context,
            "user_message_count",
            0,
        )
        or 0
    )

    return max(
        turn_number,
        user_message_count,
    )


def get_conversation_activity_instruction(
    context=None,
) -> str:

    conversation_activity_diff = get_conversation_activity_diff(
        context
    )

    if conversation_activity_diff is None:
        return ""

    activity_percent = get_conversation_activity_percent(
        conversation_activity_diff
    )

    if activity_percent >= 100:
        return ""

    activity_instruction = build_conversation_activity_instruction(
        activity_percent
    )

    return activity_instruction


