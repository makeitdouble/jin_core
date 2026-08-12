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
    "CAN_DEEP_WEB_SEARCH": True,
    "CAN_WEB_SEARCH": True,
    "CAN_USE_ASSETS": True,
    "CAN_SAVE_SESSION": True,
    "CAN_SAVE_DELAYED_MEMORY": True,
    "CAN_SAVE_ACTIVE_MEMORY": True,
    "CAN_RUNTIME_TODO": False,
    "CAN_CLEAN_TOOL_RESULTS": True,
    "CAN_IDLE": True,
    "CAN_JIN_COLOR": True,
    "CAN_UPDATE_L4_FACTS": True,
}

BRAIN_RUNTIME_ACTIONS = {
    "CAN_DEEP_WEB_SEARCH": True,
    "CAN_WEB_SEARCH": True,
    "CAN_USE_ASSETS": True,
    "CAN_SAVE_SESSION": True,
    "CAN_SAVE_DELAYED_MEMORY": True,
    "CAN_SAVE_ACTIVE_MEMORY": True,
    "CAN_RUNTIME_TODO": False,
    "CAN_CLEAN_TOOL_RESULTS": True,
    "CAN_IDLE": True,
    "CAN_JIN_COLOR": True,
    "CAN_UPDATE_L4_FACTS": True,
}

LOADED_DELAYED_MEMORY_CONTEXT_FIELDS = (
    "title",
    "summary",
    "tags",
    "body",
)

PREVIOUS_REASONING_EDGE_PERCENT = 25
PREVIOUS_REASONING_MIN_CROP_CHARS = 1000
PREVIOUS_REASONING_SEPARATOR = ",,,"


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


def build_delayed_memory_inventory_context(
    context=None,
) -> str:

    from utils.delayed_memory_file_store import (
        delayed_memory_filename,
        normalize_delayed_memory_reports,
    )

    if context is None:
        return ""

    reports = normalize_delayed_memory_reports(
        getattr(
            context,
            "delayed_memory_reports",
            {},
        )
    )

    if not reports:
        return ""

    report_names = []

    for report_id, report in reports.items():
        try:
            filename = delayed_memory_filename(
                report_id,
                report.get(
                    "title",
                    "",
                ),
            )
        except (TypeError, ValueError):
            continue

        report_names.append(
            _append_delayed_memory_context_age(
                filename[:-5],
                report,
            )
        )

    if not report_names:
        return ""

    report_names.sort(
        key=str.casefold
    )

    return (
        "<DELAYED_MEMORY>\n"
        + "\n".join(report_names)
        + "\n</DELAYED_MEMORY>"
    )


def _format_delayed_memory_context_age_suffix(
    report: dict,
    *,
    now: float | None = None,
) -> str:

    from utils.context.messages import (
        format_context_message_age_suffix,
    )

    if not isinstance(
        report,
        dict,
    ):
        return ""

    return format_context_message_age_suffix(
        report.get(
            "created_time",
        )
        or report.get(
            "created_date",
        ),
        now=now,
    )


def _append_delayed_memory_context_age(
    text: str,
    report: dict,
    *,
    now: float | None = None,
) -> str:

    return (
        f"{text}{_format_delayed_memory_context_age_suffix(report, now=now)}"
    )


def build_loaded_delayed_memory_context(
    context=None,
) -> str:

    from utils.context.formatting import (
        format_tool_result_payload,
    )
    from utils.brain_client_utils import (
        include_pinned_delayed_memory_reports,
        indent_xml,
    )

    if context is None:
        return ""

    loaded_reports = include_pinned_delayed_memory_reports(
        context
    )

    if not loaded_reports:
        return ""

    blocks = []

    for report_id, report in loaded_reports.items():
        if not isinstance(
            report,
            dict,
        ):
            continue

        payload = {
            "id": report_id,
        }
        for field_name in LOADED_DELAYED_MEMORY_CONTEXT_FIELDS:
            if field_name in report:
                field_value = report[field_name]
                if field_name == "title":
                    field_value = _append_delayed_memory_context_age(
                        str(
                            field_value
                            or ""
                        ).strip(),
                        report,
                    )
                payload[field_name] = field_value

        blocks.append(
            "<LOADED_DELAYED_MEMORY>\n"
            f"{indent_xml(escape(format_tool_result_payload(payload)))}\n"
            "</LOADED_DELAYED_MEMORY>"
        )

    return "\n".join(
        blocks
    )


def build_long_term_memory_context(
    context=None,
    user_input: str = "",
) -> str:

    if context is None:
        return ""

    from runtime.L4_memory import build_runtime_l4_memory_context

    return build_runtime_l4_memory_context(
        context=context,
    )


def crop_previous_reasoning_text(
    reasoning: str,
    edge_percent: float = PREVIOUS_REASONING_EDGE_PERCENT,
    min_crop_chars: int = PREVIOUS_REASONING_MIN_CROP_CHARS,
) -> str:

    cleaned = str(
        reasoning
        or ""
    ).strip()

    if not cleaned:
        return ""

    if len(cleaned) <= min_crop_chars:
        return cleaned

    try:
        percent = float(edge_percent)
    except (
        TypeError,
        ValueError,
    ):
        percent = PREVIOUS_REASONING_EDGE_PERCENT

    if percent <= 0:
        return ""

    edge_chars = int(
        len(cleaned)
        * percent
        / 100
    )

    if edge_chars <= 0:
        return ""

    if len(cleaned) <= edge_chars * 2:
        return cleaned

    return (
        cleaned[:edge_chars]
        + "\n"
        + PREVIOUS_REASONING_SEPARATOR
        + "\n"
        + cleaned[-edge_chars:]
    )


def build_previous_reasoning_context(
    context=None,
) -> str:

    reasoning = crop_previous_reasoning_text(
        (
            getattr(
                context,
                "runtime_previous_reasoning_content",
                "",
            )
            if context is not None
            else ""
        )
    )

    from utils.brain_client_utils import (
        indent_xml,
    )

    return (
        "<PREVIOUS_JIN_RESPONSE_REASONING>\n"
        + indent_xml(
            escape(
                reasoning
            ),
            spaces=4,
        )
        + "\n</PREVIOUS_JIN_RESPONSE_REASONING>"
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
    include_previous_reasoning: bool = True,
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
        build_loaded_skills_content_context,
        build_tool_results_context,
    )
    from utils.context.skills import (
        build_skills_inventory_context,
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

    # Skill inventory is always visible directly below tool results.
    # The inventory is context state, not a runtime action.
    prompt_parts.append(
        build_skills_inventory_context(
            context
        )
    )

    loaded_skills_content_context = (
        build_loaded_skills_content_context(
            context
        )
    )
    if loaded_skills_content_context:
        prompt_parts.append(
            loaded_skills_content_context
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

    # Delayed memory inventory block: exposes every available report directly
    # below CURRENT_SESSION_STATE, so no separate list action is needed.
    delayed_memory_inventory_context = (
        build_delayed_memory_inventory_context(
            context
        )
    )

    if delayed_memory_inventory_context:
        runtime_context_parts.append(
            delayed_memory_inventory_context
        )

    # Current runtime todo block: keeps active task checklist state in view.
    _append_current_runtime_todo(
        runtime_context_parts,
        context,
    )

    # Loaded delayed memory block: pins the selected delayed memory report.
    loaded_delayed_memory_context = (
        build_loaded_delayed_memory_context(
            context
        )
    )

    if loaded_delayed_memory_context:
        runtime_context_parts.append(
            loaded_delayed_memory_context
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

    # L4 memory block: always-on canonical facts that survive sessions.
    long_term_memory_context = build_long_term_memory_context(
        context,
        user_input=user_input,
    )

    if long_term_memory_context:
        runtime_context_parts.append(
            long_term_memory_context
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

    # Previous reasoning block: carries a compact edge slice from the last
    # ordinary chat turn, but stays out of follow-up ticks.
    previous_reasoning_context = (
        build_previous_reasoning_context(
            context
        )
        if (
            include_previous_reasoning
            and not getattr(
                context,
                "runtime_followup_tick_active",
                False,
            )
        )
        else ""
    )

    if include_previous_reasoning and not getattr(
        context,
        "runtime_followup_tick_active",
        False,
    ):
        prompt_parts.append(
            previous_reasoning_context
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

