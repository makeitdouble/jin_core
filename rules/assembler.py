# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
#  JIN PROMPT ASSEMBLER
#  Shows which blocks load and when.
# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

from __future__ import annotations

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
}


def build_conditional_prompt_rules(
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


# Runtime action rules are assembled from contracts/rules_assembler.py.

# System prompt assembly
# в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ

def build_brain_system_prompt(
    context=None,
    runtime_actions=None,
    user_input: str = "",
    commit_active_memory_refresh: bool = False,
    include_runtime_action_instructions: bool = True,
    include_previous_chat_messages: bool = True,
) -> str:

    from utils.context.brain_context_builder import (
        build_brain_runtime_context,
        build_brain_top_runtime_context,
        build_previous_chat_messages_context,
        build_session_actions_history_context,
        build_tool_results_context,
    )

    enabled_actions = get_enabled_runtime_actions(
        runtime_actions
    )
    tool_results_context = build_tool_results_context(
        context
    )
    tool_results_section = (
        f"{tool_results_context}\n\n"
    )
    previous_chat_messages_context = (
        build_previous_chat_messages_context(
            context
        )
        if include_previous_chat_messages
        else ""
    )
    previous_chat_messages_section = (
        f"{previous_chat_messages_context}\n\n"
        if previous_chat_messages_context
        else ""
    )
    session_actions_history_context = (
        build_session_actions_history_context(
            context
        )
    )
    session_actions_history_section = (
        f"{session_actions_history_context}\n\n"
        if session_actions_history_context
        else ""
    )
    top_runtime_context = build_brain_top_runtime_context(
        context,
        runtime_actions,
        commit_active_memory_refresh=commit_active_memory_refresh,
    )
    top_runtime_section = (
        f"{top_runtime_context}\n\n"
        if top_runtime_context
        else ""
    )

    runtime_action_instructions_section = (
        f"{build_runtime_action_instructions(enabled_actions, context)}\n\n"
        if include_runtime_action_instructions
        else ""
    )

    prompt_prefix = (
        f"{tool_results_section}"
        f"{top_runtime_section}"
        f"{previous_chat_messages_section}"
        f"{session_actions_history_section}"
        f"{runtime_action_instructions_section}"
        f"{IDENTITY}"
        "\n"
        f"{build_conditional_prompt_rules(context)}"
        "\n"
    )

    runtime_context = build_brain_runtime_context(
        context,
        runtime_actions,
        commit_active_memory_refresh=commit_active_memory_refresh,
        include_top_runtime_context=False,
    )

    return (
        f"{prompt_prefix}"
        f"{runtime_context}"
    )


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

