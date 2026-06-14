import json
from datetime import datetime
from xml.sax.saxutils import escape

from bootstrap.brain_bootstrap import (
    build_conversation_activity_instruction,
    build_zero_diff_stall_instruction,
)
from clients.brain_client_utils import (
    get_conversation_activity_diff,
    get_conversation_activity_percent,
    get_enabled_runtime_actions,
    get_previous_think_context_block,
    indent_xml,
    strip_empty_results_xml,
)
from runtime.context_contract import (
    ContextContract,
    RUNTIME_ACTION_REMEMBER_EVENT,
    RUNTIME_ACTION_REMEMBER_SESSION,
    RUNTIME_ACTION_WEB_SEARCH,
)
from runtime.L1_memory_utils import (
    build_runtime_memory_context_text,
    canonicalize_runtime_memory_text,
)


def build_runtime_xml(
    context=None,
    runtime_actions=None,
) -> str:

    enabled_actions = get_enabled_runtime_actions(
        runtime_actions
    )
    now = datetime.now()

    return (
        ContextContract(
            user_input="",
            compressed_history="",
            system_state="ACTIVE",
            deep_thought_count=0,
            can_deep_thought=False,
            can_web_search=(
                RUNTIME_ACTION_WEB_SEARCH
                in enabled_actions
            ),
            can_remember_session=(
                RUNTIME_ACTION_REMEMBER_SESSION
                in enabled_actions
            ),
            can_remember_event=(
                RUNTIME_ACTION_REMEMBER_EVENT
                in enabled_actions
            ),
            timestamp=now.isoformat(),
            current_date=now.date().isoformat(),
            current_time=now.strftime("%H:%M:%S"),
            weekday=now.strftime("%A"),
            year=now.year,
        )
        .to_runtime_xml()
    )


def append_session_state(
    parts: list[str],
    context=None,
) -> None:

    if context is None:
        return

    parts.append(
        "<SESSION_STATE>\n"
        f"    <TURN_NUMBER>{getattr(context, 'turn_number', 0)}</TURN_NUMBER>\n"
        f"    <USER_MESSAGE_COUNT>{getattr(context, 'user_message_count', 0)}</USER_MESSAGE_COUNT>\n"
        f"    <ASSISTANT_MESSAGE_COUNT>{getattr(context, 'assistant_message_count', 0)}</ASSISTANT_MESSAGE_COUNT>\n"
        "</SESSION_STATE>"
    )


def append_L3_session_memory(
    parts: list[str],
    context=None,
) -> None:

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
        "<SESSION_MEMORY priority=\"higher_than_runtime_memory\">\n"
        f"{indent_xml(escape(session_memory))}\n"
        "</SESSION_MEMORY>"
    )


def append_session_event_snapshots(
    parts: list[str],
    context=None,
) -> None:

    session_event_snapshots = []

    if context is not None:
        session_event_snapshots = list(
            getattr(
                context,
                "runtime_session_event_snapshots",
                [],
            )
            or []
        )

    parts.append(
        "<SESSION_EVENT_SNAPSHOTS priority=\"session_context\">\n"
        f"{indent_xml(escape(json.dumps(session_event_snapshots, ensure_ascii=False, indent=2)))}\n"
        "</SESSION_EVENT_SNAPSHOTS>"
    )


def append_L1_runtime_memory(
    parts: list[str],
    context=None,
) -> None:

    if context is None:
        return

    runtime_memory = build_runtime_memory_context_text(
        getattr(
            context,
            "runtime_memory",
            "",
        ),
        context,
    )

    if not runtime_memory.strip():
        return

    parts.append(
        "<RUNTIME_MEMORY>\n"
        f"{indent_xml(escape(canonicalize_runtime_memory_text(runtime_memory)))}\n"
        "</RUNTIME_MEMORY>"
    )


def append_L2_runtime_memory(
    parts: list[str],
    context=None,
) -> None:

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


def append_conversation_activity(
    parts: list[str],
    context=None,
) -> None:

    conversation_activity_diff = get_conversation_activity_diff(
        context
    )

    if conversation_activity_diff is None:
        return

    activity_percent = get_conversation_activity_percent(
        conversation_activity_diff
    )
    activity_instruction = build_conversation_activity_instruction(
        activity_percent
    )

    parts.append(
        "<CONVERSATION_ACTIVITY>\n"
        f"    <PERCENT>{activity_percent}</PERCENT>\n"
        "    <INSTRUCTION>\n"
        f"{indent_xml(escape(activity_instruction))}\n"
        "    </INSTRUCTION>\n"
        "</CONVERSATION_ACTIVITY>"
    )


def append_previous_think(
    parts: list[str],
    context=None,
) -> None:

    previous_think_block = get_previous_think_context_block(
        context
    )

    if previous_think_block:
        parts.append(
            previous_think_block
        )


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


def append_tool_results(
    parts: list[str],
    context=None,
) -> None:

    if context is None:
        return

    search_result = getattr(
        context,
        "runtime_search_result",
        "",
    )

    if not search_result:
        return

    search_result = strip_empty_results_xml(
        search_result
    )
    search_result_id = getattr(
        context,
        "runtime_search_result_id",
        "",
    )

    tool_result_attrs = (
        'name="WEB_SEARCH"'
    )

    if search_result_id:
        tool_result_attrs = (
            f'{tool_result_attrs} '
            f'id="{escape(search_result_id)}"'
        )

    parts.append(
        '<TOOL_RESULTS type=\'external_untrusted_evidence\'>\n'
        f"    <TOOL_RESULT {tool_result_attrs}>\n"
        f"{indent_xml(search_result)}\n"
        "    </TOOL_RESULT>\n"
        "</TOOL_RESULTS>"
    )


def build_brain_runtime_context(
    context=None,
    runtime_actions=None,
) -> str:

    parts = [
        build_runtime_xml(
            context,
            runtime_actions,
        )
    ]

    append_session_state(
        parts,
        context,
    )
    append_L3_session_memory(
        parts,
        context,
    )
    append_session_event_snapshots(
        parts,
        context,
    )
    append_L1_runtime_memory(
        parts,
        context,
    )
    append_L2_runtime_memory(
        parts,
        context,
    )
    append_conversation_activity(
        parts,
        context,
    )
    append_previous_think(
        parts,
        context,
    )
    append_zero_diff_alert(
        parts,
        context,
    )
    append_tool_results(
        parts,
        context,
    )

    return "\n".join(
        parts
    )
