# =============================================================================
#  JIN BRAIN CONTEXT BUILDER
#  Builds the complete brain system context in one place.
# =============================================================================

from __future__ import annotations

from xml.sax.saxutils import escape

from .identity import IDENTITY
from .signal import LOOP_RULES, EXTREME_LOW_DIFF_RULES, ZERO_DIFF_RULES, \
    LOW_DIFF_RULES, MIDDLE_DIFF_RULES, NORMAL_DIFF_RULES
from contracts.rules_assembler import (
    build_runtime_action_instructions,
    get_enabled_runtime_actions,
)


SERVICE_AS_BRAIN_RUNTIME_ACTIONS = {
    "CAN_WEB_SEARCH": True,
    "CAN_USE_ASSETS": True,
    "CAN_SAVE_SESSION": True,
    "CAN_SAVE_DELAYED_MEMORY": True,
    "CAN_SAVE_ACTIVE_MEMORY": True,
    "CAN_RUNTIME_TODO": False,
    "CAN_CLEAN_TOOL_RESULTS": True,
    "CAN_IDLE": True,
    "CAN_JIN_COLOR": True,
}

BRAIN_RUNTIME_ACTIONS = {
    "CAN_WEB_SEARCH": True,
    "CAN_USE_ASSETS": True,
    "CAN_SAVE_SESSION": True,
    "CAN_SAVE_DELAYED_MEMORY": True,
    "CAN_SAVE_ACTIVE_MEMORY": True,
    "CAN_RUNTIME_TODO": False,
    "CAN_CLEAN_TOOL_RESULTS": True,
    "CAN_IDLE": True,
    "CAN_JIN_COLOR": True,
}


def build_loop_rules(
    context=None,
) -> str:

    if context is None:
        return ""

    pattern_counter = getattr(
        context,
        "runtime_pattern_counter",
        0,
    )

    try:
        if int(
            pattern_counter
        ) > 1:
            return LOOP_RULES
    except (
        TypeError,
        ValueError,
    ):
        return ""

    return ""


def _append_visible_session_state(
    parts: list[str],
    context=None,
) -> None:

    from runtime.runtime_context import (
        format_session_state,
    )
    from utils.context.runtime_state import (
        get_visible_assistant_message_count,
        get_visible_turn_count,
    )

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


def _append_user_feedback(
    parts: list[str],
    context=None,
) -> None:

    from runtime.L1_memory_utils import (
        build_runtime_response_feedback_value,
    )
    from runtime.runtime_context import (
        format_user_feedback,
    )

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


def _append_current_runtime_todo(
    parts: list[str],
    context=None,
) -> None:

    from utils.runtime_todo import (
        format_runtime_todo_xml,
    )

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


def _append_L1_runtime_memory(
    parts: list[str],
    context=None,
    *,
    commit_active_memory_refresh: bool = False,
) -> None:

    from runtime.L1_memory_utils import (
        build_runtime_memory_context_text,
        canonicalize_runtime_memory_text,
    )
    from utils.brain_client_utils import (
        indent_xml,
    )
    from utils.actions import (
        is_active_memory_record_paused,
        refresh_active_memory_runtime_metadata,
        remove_active_memory_entries,
    )

    if context is None:
        return

    raw_runtime_memory = remove_active_memory_entries(
        getattr(
            context,
            "runtime_memory",
            "",
        )
    )

    runtime_memory = build_runtime_memory_context_text(
        raw_runtime_memory,
        context,
    )

    stored_active_memory_records = [
        str(record or "").strip()
        for record in getattr(
            context,
            "active_memory_records",
            [],
        )
        if str(record or "").strip()
    ]

    if stored_active_memory_records:
        active_memory_refresh_base_turn = (
            getattr(
                context,
                "turn_number",
                0,
            ),
            getattr(
                context,
                "user_message_count",
                0,
            ),
        )
        active_memory_refresh_turn = (
            *active_memory_refresh_base_turn,
            getattr(
                context,
                "runtime_active_memory_refresh_tick",
                0,
            ),
        )
        previous_active_memory_refresh_turn = getattr(
            context,
            "runtime_active_memory_records_refresh_turn",
            None,
        )
        active_memory_refresh_committed = (
            commit_active_memory_refresh
            and previous_active_memory_refresh_turn
            == active_memory_refresh_turn
        )
        active_memory_idle_already_applied = (
            isinstance(
                previous_active_memory_refresh_turn,
                tuple,
            )
            and previous_active_memory_refresh_turn[:2]
            == active_memory_refresh_base_turn
        )
        previous_active_memory_text = "\n".join(
            stored_active_memory_records
        )
        active_memory_text = (
            previous_active_memory_text
            if active_memory_refresh_committed
            else refresh_active_memory_runtime_metadata(
                previous_active_memory_text,
                context=context,
                previous_memory=previous_active_memory_text,
                add_runtime_user_idle_to_elapsed=(
                    not active_memory_idle_already_applied
                ),
            )
        )

        if commit_active_memory_refresh:
            context.runtime_active_memory_records_refresh_turn = (
                active_memory_refresh_turn
            )
            refreshed_records = [
                line.strip()
                for line in active_memory_text.splitlines()
                if line.strip()
            ]

            if refreshed_records != stored_active_memory_records:
                context.active_memory_records = refreshed_records
                context.runtime_active_memory_records_dirty = True

        active_memory_context_text = "\n".join(
            line
            for line in active_memory_text.splitlines()
            if not is_active_memory_record_paused(
                line
            )
        ).strip()

        if active_memory_context_text:
            parts.append(
                "<ACTIVE_MEMORY priority=\"active_runtime_contracts\">\n"
                f"{indent_xml(escape(canonicalize_runtime_memory_text(active_memory_context_text)))}\n"
                "</ACTIVE_MEMORY>"
            )

    if runtime_memory.strip():
        parts.append(
            "<RUNTIME_MEMORY>\n"
            f"{indent_xml(escape(canonicalize_runtime_memory_text(runtime_memory)))}\n"
            "</RUNTIME_MEMORY>"
        )


def _append_L3_session_memory(
    parts: list[str],
    context=None,
) -> None:

    from utils.brain_client_utils import (
        indent_xml,
    )

    if context is None:
        return

    session_memory = getattr(
        context,
        "runtime_l3_session_memory",
        "",
    ) or getattr(
        context,
        "session_memory",
        "",
    )

    if not session_memory.strip():
        return

    parts.append(
        "<PREVIOUS_SESSION_STATE priority=\"higher_than_runtime_memory\">\n"
        f"{indent_xml(escape(session_memory))}\n"
        "</PREVIOUS_SESSION_STATE>"
    )


def _append_L2_runtime_memory(
    parts: list[str],
    context=None,
) -> None:

    from utils.brain_client_utils import (
        indent_xml,
    )

    if context is None:
        return

    runtime_l2_memory = getattr(
        context,
        "runtime_l2_memory",
        "",
    )

    if not runtime_l2_memory.strip():
        return

    parts.append(
        "<RUNTIME_PATTERN_MEMORY>\n"
        f"{indent_xml(escape(runtime_l2_memory))}\n"
        "</RUNTIME_PATTERN_MEMORY>"
    )


def _append_zero_diff_alert(
    parts: list[str],
    context=None,
) -> None:

    from utils.brain_client_utils import (
        indent_xml,
    )

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


def _build_current_appended_skills_context(
    context=None,
) -> str:

    from utils.brain_client_utils import (
        indent_xml,
    )

    if context is None:
        return ""

    appended_skills = list(
        getattr(
            context,
            "runtime_appended_skills",
            [],
        )
        or []
    )
    skill_names = []

    for skill in appended_skills:
        if isinstance(
            skill,
            dict,
        ):
            name = str(
                skill.get(
                    "name",
                    "",
                )
                or ""
            ).strip()
        else:
            name = str(
                skill
                or ""
            ).strip()

        if name:
            skill_names.append(
                name
            )

    if not skill_names:
        return ""

    lines = [
        f"{index}. {name}"
        for index, name in enumerate(
            skill_names,
            start=1,
        )
    ]

    return (
        "<CURRENT_APPENDED_SKILLS>\n"
        f"{indent_xml(escape(chr(10).join(lines)), spaces=4)}\n"
        "</CURRENT_APPENDED_SKILLS>"
    )


def build_appended_delayed_memory_context(
    context=None,
) -> str:

    from utils.context.formatting import (
        format_tool_result_payload,
    )
    from utils.brain_client_utils import (
        indent_xml,
    )

    if context is None:
        return ""

    appended_report = getattr(
        context,
        "runtime_appended_delayed_memory",
        {},
    )

    if not isinstance(
        appended_report,
        dict,
    ):
        return ""

    if not appended_report:
        return ""

    return (
        "<APPENDED_DELAYED_MEMORY>\n"
        f"{indent_xml(escape(format_tool_result_payload(appended_report)))}\n"
        "</APPENDED_DELAYED_MEMORY>"
    )


# Runtime action rules are assembled from contracts/rules_assembler.py.

# Brain context assembly
# -----------------------------------------------------------------------------

def build_brain_context(
    context=None,
    runtime_actions=None,
    user_input: str = "",
    commit_active_memory_refresh: bool = False,
    include_runtime_action_instructions: bool = True,
    include_previous_chat_messages: bool = True,
) -> str:

    from utils.context.messages import (
        build_previous_chat_messages_context,
    )
    from utils.context.runtime_state import (
        build_runtime_xml,
    )
    from utils.context.session_actions import (
        build_session_actions_history_context,
    )
    from utils.context.tool_results import (
        build_tool_results_context,
    )

    prompt_parts = []
    runtime_context_parts = []

    enabled_actions = get_enabled_runtime_actions(
        runtime_actions
    )

    # Tool results block: places recent tool/action outputs at the very top.
    tool_results_context = build_tool_results_context(
        context
    )

    if tool_results_context:
        prompt_parts.append(
            tool_results_context
        )

    # User feedback block: carries the latest explicit response feedback forward.
    _append_user_feedback(
        runtime_context_parts,
        context,
    )

    # L1 memory block: includes active memory records and live runtime memory.
    _append_L1_runtime_memory(
        runtime_context_parts,
        context,
        commit_active_memory_refresh=commit_active_memory_refresh,
    )

    # Runtime XML block: exposes trusted runtime variables and enabled actions.
    runtime_context_parts.append(
        build_runtime_xml(
            context,
            runtime_actions,
        )
    )

    # Visible session state block: records visible turn and message counters.
    _append_visible_session_state(
        runtime_context_parts,
        context,
    )

    # Current runtime todo block: keeps active task checklist state in view.
    _append_current_runtime_todo(
        runtime_context_parts,
        context,
    )

    # Appended delayed memory block: pins the selected delayed memory report.
    appended_delayed_memory_context = (
        build_appended_delayed_memory_context(
            context
        )
    )

    if appended_delayed_memory_context:
        runtime_context_parts.append(
            appended_delayed_memory_context
        )

    # Current appended skills block: lists skills already loaded this turn.
    current_appended_skills_context = (
        _build_current_appended_skills_context(
            context
        )
    )

    if current_appended_skills_context:
        runtime_context_parts.append(
            current_appended_skills_context
        )

    # L3 memory block: restores previous session state from prior turns.
    _append_L3_session_memory(
        runtime_context_parts,
        context,
    )

    # L2 memory block: adds slower pattern memory after session memory.
    _append_L2_runtime_memory(
        runtime_context_parts,
        context,
    )

    # Zero-diff alert block: warns the brain when a repeated answer stalled.
    _append_zero_diff_alert(
        runtime_context_parts,
        context,
    )

    if runtime_context_parts:
        prompt_parts.append(
            "\n".join(
                runtime_context_parts
            )
        )

    # Previous chat messages block: gives the brain the recent visible dialogue.
    previous_chat_messages_context = (
        build_previous_chat_messages_context(
            context
        )
        if include_previous_chat_messages
        else ""
    )

    if previous_chat_messages_context:
        prompt_parts.append(
            previous_chat_messages_context
        )

    # Session actions history block: keeps durable action breadcrumbs available.
    session_actions_history_context = (
        build_session_actions_history_context(
            context
        )
    )

    if session_actions_history_context:
        prompt_parts.append(
            session_actions_history_context
        )

    # Runtime action instructions block: describes the private action protocol.
    if include_runtime_action_instructions:
        prompt_parts.append(
            build_runtime_action_instructions(
                enabled_actions,
                context,
            )
        )

    # Identity block: anchors the brain persona and base behavior contract.
    prompt_parts.append(
        IDENTITY
    )

    # Loop rules block: adds turn-specific behavior guidance.
    prompt_parts.append(
        build_loop_rules(
            context
        )
    )

    return "\n\n".join(
        prompt_parts
    ) + "\n"


def build_conversation_activity_instruction(activity_percent: int) -> str:
    if activity_percent < 20:
        return (
           EXTREME_LOW_DIFF_RULES
        )

    if activity_percent <= 30:
        return (
            LOW_DIFF_RULES
        )

    if activity_percent <= 50:
        return (
            MIDDLE_DIFF_RULES
        )

    if activity_percent < 100:
        return (
            NORMAL_DIFF_RULES
        )

    return ""


def build_zero_diff_stall_instruction() -> str:
    return (
        ZERO_DIFF_RULES
    )

