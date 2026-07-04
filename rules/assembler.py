# ─────────────────────────────────────────────
#  JIN PROMPT ASSEMBLER
#  Shows which blocks load and when.
# ─────────────────────────────────────────────

from __future__ import annotations

import re

from .identity import IDENTITY
from .signal import LOOP_RULES, EXTREME_LOW_DIFF_RULES, ZERO_DIFF_RULES, \
    LOW_DIFF_RULES, MIDDLE_DIFF_RULES, NORMAL_DIFF_RULES
from .runtime import (
    CREATE_ACTIVE_MEMORY_RULES,
    RESOLVE_ACTIVE_MEMORY_RULES,
    INTERNAL_ACTION_CREATE_ACTIVE_MEMORY_MARKER,
    INTERNAL_ACTION_ASSET_ACTION_MARKER,
    INTERNAL_ACTION_APPEND_SKILL_MARKER,
    INTERNAL_ACTION_LIST_SKILLS_MARKER,
    INTERNAL_ACTION_REMOVE_SKILL_MARKER,
    INTERNAL_ACTION_RESOLVE_ACTIVE_MEMORY_MARKER,
    INTERNAL_ACTION_SAVE_DELAYED_MEMORY_CONTENT_MARKER,
    INTERNAL_ACTION_SAVE_SESSION_MARKER,
    INTERNAL_ACTION_WEB_SEARCH_MARKER,
    RUNTIME_ACTION_CREATE_ACTIVE_MEMORY,
    RUNTIME_ACTION_ASSET_ACTION,
    RUNTIME_ACTION_APPEND_SKILL,
    RUNTIME_ACTION_LIST_SKILLS,
    RUNTIME_ACTION_REMOVE_SKILL,
    RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY,
    RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT,
    RUNTIME_ACTION_SAVE_SESSION,
    RUNTIME_ACTION_WEB_SEARCH,
    SAVE_SESSION_RULES,
    WEB_SEARCH_RULES,
    ASSETS_RULES,
    SKILL_ROUTING_RULES,
    RUNTIME_ACTIONS_RULES, SAVE_DELAYED_MEMORY_RULES, INTERNAL_ACTION_ROUTER_RULES
)


SERVICE_AS_BRAIN_RUNTIME_ACTIONS = {
    "CAN_WEB_SEARCH": True,
    "CAN_USE_ASSETS": True,
    "CAN_SAVE_SESSION": True,
    "CAN_SAVE_DELAYED_MEMORY": True,
    "CAN_SAVE_ACTIVE_MEMORY": True,
}

BRAIN_RUNTIME_ACTIONS = {
    "CAN_WEB_SEARCH": True,
    "CAN_USE_ASSETS": True,
    "CAN_SAVE_SESSION": True,
    "CAN_SAVE_DELAYED_MEMORY": True,
    "CAN_SAVE_ACTIVE_MEMORY": True,
}


ACTIVE_MEMORY_ENTRY_RE = re.compile(
    r"^\s*-?\s*active_memory(?:_\d+)?\s*:",
    re.IGNORECASE | re.MULTILINE,
)


def _action_enabled(
    enabled_actions: tuple[str, ...],
    *names: str,
) -> bool:
    return any(name in enabled_actions for name in names)


def get_enabled_runtime_actions(
    runtime_actions=None,
) -> tuple[str, ...]:

    enabled_actions = []

    action_flags = runtime_actions or {}

    for action_name, config_key in (
        (
            RUNTIME_ACTION_WEB_SEARCH,
            "CAN_WEB_SEARCH",
        ),
        (
            RUNTIME_ACTION_SAVE_SESSION,
            "CAN_SAVE_SESSION",
        ),
        (
            RUNTIME_ACTION_LIST_SKILLS,
            "CAN_USE_ASSETS",
        ),
        (
            RUNTIME_ACTION_APPEND_SKILL,
            "CAN_USE_ASSETS",
        ),
        (
            RUNTIME_ACTION_REMOVE_SKILL,
            "CAN_USE_ASSETS",
        ),
        (
            RUNTIME_ACTION_ASSET_ACTION,
            "CAN_USE_ASSETS",
        ),
        (
            RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT,
            "CAN_SAVE_DELAYED_MEMORY",
        ),
        (
            RUNTIME_ACTION_CREATE_ACTIVE_MEMORY,
            "CAN_SAVE_ACTIVE_MEMORY",
        ),
        (
            RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY,
            "CAN_SAVE_ACTIVE_MEMORY",
        ),
    ):

        if bool(
            action_flags.get(
                config_key,
                False,
            )
        ):
            enabled_actions.append(
                action_name
            )

    return tuple(
        enabled_actions
    )


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


def _build_allowed_markers(
    enabled_actions: tuple[str, ...],
) -> str:
    markers: list[str] = []

    if _action_enabled(enabled_actions, RUNTIME_ACTION_WEB_SEARCH, "web_search"):
        markers.append(INTERNAL_ACTION_WEB_SEARCH_MARKER)

    if _action_enabled(enabled_actions, RUNTIME_ACTION_LIST_SKILLS, "list_skills"):
        markers.append(INTERNAL_ACTION_LIST_SKILLS_MARKER)

    if _action_enabled(enabled_actions, RUNTIME_ACTION_APPEND_SKILL, "append_skill"):
        markers.append(INTERNAL_ACTION_APPEND_SKILL_MARKER)

    if _action_enabled(enabled_actions, RUNTIME_ACTION_REMOVE_SKILL, "remove_skill"):
        markers.append(INTERNAL_ACTION_REMOVE_SKILL_MARKER)

    if _action_enabled(enabled_actions, RUNTIME_ACTION_ASSET_ACTION, "asset_action"):
        markers.append(INTERNAL_ACTION_ASSET_ACTION_MARKER)

    if _action_enabled(enabled_actions, RUNTIME_ACTION_SAVE_SESSION, "save_session"):
        markers.append(INTERNAL_ACTION_SAVE_SESSION_MARKER)

    if _action_enabled(enabled_actions, RUNTIME_ACTION_CREATE_ACTIVE_MEMORY, "create_active_memory"):
        markers.append(INTERNAL_ACTION_CREATE_ACTIVE_MEMORY_MARKER)

    if not markers:
        return ""

    return "\n".join(markers) + "."


def _append_resolve_active_memory_rules(
    instructions: list[str],
    enabled_actions: tuple[str, ...],
    context=None,
) -> None:
    if not _action_enabled(enabled_actions, RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY, "resolve_active_memory"):
        return

    if context is None:
        return

    memory_texts = [
        getattr(context, "runtime_memory", ""),
        getattr(context, "runtime_memory_stable", ""),
    ]

    active_records = getattr(
        context,
        "active_memory_records",
        None,
    )
    if active_records:
        memory_texts.extend(
            str(record or "")
            for record in active_records
        )

    if not any(
        ACTIVE_MEMORY_ENTRY_RE.search(str(memory_text or ""))
        for memory_text in memory_texts
    ):
        return
    instructions.append(RESOLVE_ACTIVE_MEMORY_RULES)

# ─────────────────────────────────────────────
# Runtime actions / runtime state
# ─────────────────────────────────────────────

def build_runtime_action_instructions(
    enabled_actions: tuple[str, ...],
    context=None,
) -> str:
    instructions: list[str] = [
        RUNTIME_ACTIONS_RULES
    ]

    if _action_enabled(enabled_actions, RUNTIME_ACTION_WEB_SEARCH, "web_search"):
        instructions.append(WEB_SEARCH_RULES)

    if _action_enabled(enabled_actions, RUNTIME_ACTION_LIST_SKILLS, "list_skills"):
        instructions.append(SKILL_ROUTING_RULES)

    if (
        _action_enabled(enabled_actions, RUNTIME_ACTION_LIST_SKILLS, "list_skills")
        or _action_enabled(enabled_actions, RUNTIME_ACTION_ASSET_ACTION, "asset_action")
    ):
        instructions.append(ASSETS_RULES)

    if _action_enabled(enabled_actions, RUNTIME_ACTION_SAVE_SESSION, "save_session"):
        instructions.append(SAVE_SESSION_RULES)

    if _action_enabled(enabled_actions, RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT, "save_delayed_memory_content"):
        instructions.append(SAVE_DELAYED_MEMORY_RULES)

    if _action_enabled(enabled_actions, RUNTIME_ACTION_CREATE_ACTIVE_MEMORY, "create_active_memory"):
        instructions.append(CREATE_ACTIVE_MEMORY_RULES)
        _append_resolve_active_memory_rules(
            instructions,
            enabled_actions,
            context,
        )

    if not enabled_actions:
        instructions = ["No runtime actions are currently enabled."]

    instructions.append(INTERNAL_ACTION_ROUTER_RULES)

    return "\n".join(instructions)


# ─────────────────────────────────────────────
# System prompt assembly
# ─────────────────────────────────────────────

def build_brain_system_prompt(
    context=None,
    runtime_actions=None,
    user_input: str = "",
    commit_active_memory_refresh: bool = False,
) -> str:

    from clients.brain_context_builder import (
        build_brain_runtime_context,
        build_brain_top_runtime_context,
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
        if tool_results_context
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
    )
    top_runtime_section = (
        f"{top_runtime_context}\n\n"
        if top_runtime_context
        else ""
    )

    prompt_prefix = (
        f"{top_runtime_section}"
        f"{session_actions_history_section}"
        f"{build_runtime_action_instructions(enabled_actions, context)}\n"
        "\n"
        f"{tool_results_section}"
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
