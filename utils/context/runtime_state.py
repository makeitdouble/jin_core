# Builds runtime state, feedback, todo, and activity alert context blocks.
from datetime import datetime
from xml.sax.saxutils import escape

from app_settings import (
    settings,
)
from clients.brain_client_utils import (
    get_conversation_activity_diff,
    get_conversation_activity_percent,
    indent_xml,
)
from rules.assembler import (
    build_conversation_activity_instruction,
    build_zero_diff_stall_instruction,
    get_enabled_runtime_actions,
)
from contracts.rules_assembler import (
    RUNTIME_ACTION_ASSET_ACTION,
    RUNTIME_ACTION_CREATE_ACTIVE_MEMORY,
    RUNTIME_ACTION_LIST_SKILLS,
    RUNTIME_ACTION_SAVE_SESSION,
    RUNTIME_ACTION_WEB_SEARCH,
)
from runtime.L1_memory_utils import (
    build_runtime_response_feedback_value,
)
from runtime.runtime_context import (
    ContextContract,
    format_session_state,
    format_user_feedback,
)
from utils.runtime_todo import (
    format_runtime_todo_xml,
)


def get_brain_runtime_mode() -> str:

    if settings.USE_SERVICE_AS_BRAIN:
        return "SERVICE as BRAIN"

    return "BRAIN"


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


def append_visible_session_state(
    parts: list[str],
    context=None,
) -> None:

    if context is None:
        return

    parts.append(
        format_session_state(
            turn_number=get_visible_turn_count(
                context
            ),
            user_message_count=getattr(context, "user_message_count", 0),
            assistant_message_count=get_visible_assistant_message_count(
                context
            ),
        )
    )


def append_user_feedback(
    parts: list[str],
    context=None,
) -> None:

    if context is None:
        return

    runtime_response_feedback = getattr(
        context,
        "runtime_last_response_feedback",
        None,
    )

    if not isinstance(
        runtime_response_feedback,
        dict,
    ):
        return

    user_feedback = build_runtime_response_feedback_value(
        runtime_response_feedback
    )

    if not user_feedback:
        return

    parts.append(
        format_user_feedback(
            user_feedback
        )
    )


def append_current_runtime_todo(
    parts: list[str],
    context=None,
) -> None:

    if context is None:
        return

    runtime_todo_xml = format_runtime_todo_xml(
        getattr(
            context,
            "runtime_todo",
            [],
        )
    )

    if not runtime_todo_xml:
        return

    parts.append(
        runtime_todo_xml
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


def append_zero_diff_alert(
    parts: list[str],
    context=None,
) -> None:

    if context is None:
        return

    zero_diff_alert = getattr(
        context,
        "runtime_zero_diff_alert",
        None,
    )

    if not zero_diff_alert:
        return

    alert_user_message = (
        zero_diff_alert.get(
            "user_message",
            "",
        )
        if isinstance(
            zero_diff_alert,
            dict,
        )
        else ""
    )
    alert_assistant_message = (
        zero_diff_alert.get(
            "assistant_message",
            "",
        )
        if isinstance(
            zero_diff_alert,
            dict,
        )
        else ""
    )
    alert_turn_number = (
        zero_diff_alert.get(
            "turn_number",
            0,
        )
        if isinstance(
            zero_diff_alert,
            dict,
        )
        else 0
    )

    parts.append(
        "<ZERO_DIFF_STALL_ALERT>\n"
        "    <INSTRUCTION>\n"
        f"        {build_zero_diff_stall_instruction()}\n"
        "    </INSTRUCTION>\n"
        f"    <TRIGGER_TURN>{alert_turn_number}</TRIGGER_TURN>\n"
        "    <TRIGGER_USER_MESSAGE>\n"
        f"{indent_xml(escape(alert_user_message))}\n"
        "    </TRIGGER_USER_MESSAGE>\n"
        "    <TRIGGER_JIN_RESPONSE>\n"
        f"{indent_xml(escape(alert_assistant_message))}\n"
        "    </TRIGGER_JIN_RESPONSE>\n"
        "</ZERO_DIFF_STALL_ALERT>"
    )
