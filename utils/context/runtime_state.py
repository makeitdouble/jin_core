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
    RUNTIME_ACTION_CREATE_ACTIVE_MEMORY,
    RUNTIME_ACTION_LIST_SKILLS,
    RUNTIME_ACTION_SAVE_SESSION,
    RUNTIME_ACTION_WEB_SEARCH,
)
from rules.runtime import (
    ACTION_BLOCKED_TRIGGER_WORD_MESSAGE,
)
from runtime.runtime_context import (
    ContextContract,
    DEFAULT_JIN_COLOR,
)
from utils.runtime_actions import (
    normalize_jin_color_payload,
)


def format_runtime_trigger_words_message(
    template: str,
    trigger_words,
) -> str:

    return template.format(
        trigger_words=", ".join(
            str(
                trigger_word
                or ""
            ).strip()
            for trigger_word in trigger_words
            if str(
                trigger_word
                or ""
            ).strip()
        )
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


def get_brain_runtime_mode() -> str:

    if settings.USE_SERVICE_AS_BRAIN:
        return "SERVICE as BRAIN"

    return "BRAIN"


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
            runtime_mode=get_brain_runtime_mode(),
            service_model_uid=settings.SERVICE_MODEL_UID,
            brain_model_uid=settings.BRAIN_MODEL_UID,
            jin_color=get_current_jin_color(
                context
            ),
            can_web_search=(
                RUNTIME_ACTION_WEB_SEARCH
                in enabled_actions
            ),
            can_use_assets=(
                RUNTIME_ACTION_LIST_SKILLS
                in enabled_actions
                or RUNTIME_ACTION_ASSET_ACTION
                in enabled_actions
            ),
            can_save_session=(
                RUNTIME_ACTION_SAVE_SESSION
                in enabled_actions
            ),
            can_create_active_memory=(
                RUNTIME_ACTION_CREATE_ACTIVE_MEMORY
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
    runtime_action_count = len(
        getattr(
            context,
            "runtime_action_events",
            [],
        )
        or []
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
        + runtime_action_count
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


