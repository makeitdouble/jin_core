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
    DELAYED_MEMORY_ACTION_RULES,
    DELAYED_MEMORY_APPEND_MARKER,
    DELAYED_MEMORY_LIST_MARKER,
    DELAYED_MEMORY_REMOVE_MARKER,
    RESOLVE_ACTIVE_MEMORY_RULES,
    INTERNAL_ACTION_CREATE_ACTIVE_MEMORY_MARKER,
    INTERNAL_ACTION_ASSET_ACTION_MARKER,
    INTERNAL_ACTION_CHECK_TODO_MARKER,
    INTERNAL_ACTION_CREATE_TODO_LIST_MARKER,
    INTERNAL_ACTION_APPEND_SKILL_MARKER,
    INTERNAL_ACTION_LIST_SKILLS_MARKER,
    INTERNAL_ACTION_HIDE_SKILLS_MARKER,
    INTERNAL_ACTION_IDLE_MARKER,
    INTERNAL_ACTION_CLEAN_TOOL_RESULTS_MARKER,
    INTERNAL_ACTION_REMOVE_SKILL_MARKER,
    INTERNAL_ACTION_RESOLVE_ACTIVE_MEMORY_MARKER,
    INTERNAL_ACTION_RESOLVE_TODO_MARKER,
    INTERNAL_ACTION_SAVE_DELAYED_MEMORY_CONTENT_MARKER,
    INTERNAL_ACTION_SAVE_SESSION_MARKER,
    INTERNAL_ACTION_WEB_SEARCH_MARKER,
    RUNTIME_ACTION_CREATE_ACTIVE_MEMORY,
    RUNTIME_ACTION_APPEND_DELAYED_MEMORY,
    RUNTIME_ACTION_ASSET_ACTION,
    RUNTIME_ACTION_CHECK_TODO,
    RUNTIME_ACTION_CREATE_TODO_LIST,
    RUNTIME_ACTION_LIST_DELAYED_MEMORY,
    RUNTIME_ACTION_APPEND_SKILL,
    RUNTIME_ACTION_LIST_SKILLS,
    RUNTIME_ACTION_HIDE_SKILLS,
    RUNTIME_ACTION_IDLE,
    RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
    RUNTIME_ACTION_REMOVE_SKILL,
    RUNTIME_ACTION_REMOVE_DELAYED_MEMORY,
    RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY,
    RUNTIME_ACTION_RESOLVE_TODO,
    RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT,
    RUNTIME_ACTION_SAVE_SESSION,
    RUNTIME_ACTION_WEB_SEARCH,
    SAVE_SESSION_RULES,
    WEB_SEARCH_RULES,
    ASSETS_RULES,
    APPEND_REMOVE_SKILL_RULES,
    RUNTIME_TODO_RULES,
    SKILL_ROUTING_RULES,
    RUNTIME_ACTIONS_RULES, SAVE_DELAYED_MEMORY_RULES,
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
            RUNTIME_ACTION_HIDE_SKILLS,
            "CAN_USE_ASSETS",
        ),
        (
            RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
            "CAN_CLEAN_TOOL_RESULTS",
        ),
        (
            RUNTIME_ACTION_IDLE,
            "CAN_IDLE",
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
            RUNTIME_ACTION_CREATE_TODO_LIST,
            "CAN_RUNTIME_TODO",
        ),
        (
            RUNTIME_ACTION_RESOLVE_TODO,
            "CAN_RUNTIME_TODO",
        ),
        (
            RUNTIME_ACTION_CHECK_TODO,
            "CAN_RUNTIME_TODO",
        ),
        (
            RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT,
            "CAN_SAVE_DELAYED_MEMORY",
        ),
        (
            RUNTIME_ACTION_LIST_DELAYED_MEMORY,
            "CAN_SAVE_DELAYED_MEMORY",
        ),
        (
            RUNTIME_ACTION_APPEND_DELAYED_MEMORY,
            "CAN_SAVE_DELAYED_MEMORY",
        ),
        (
            RUNTIME_ACTION_REMOVE_DELAYED_MEMORY,
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


def _context_has_list_skills_tool_result(
    context=None,
) -> bool:

    visible_result = getattr(
        context,
        "runtime_visible_skills_result",
        {},
    )

    if (
        isinstance(
            visible_result,
            dict,
        )
        and visible_result.get(
            "action"
        ) == "list_skills"
    ):
        return True

    tool_result_entries = list(
        getattr(
            context,
            "runtime_tool_results",
            [],
        )
        or []
    )
    for entry in tool_result_entries:
        if not isinstance(
            entry,
            dict,
        ):
            continue

        result = entry.get(
            "result"
        )
        if (
            isinstance(
                result,
                dict,
            )
            and result.get(
                "action"
            ) == "list_skills"
        ):
            return True

    for result in (
        getattr(
            context,
            "runtime_asset_results",
            [],
        )
        or []
    ):
        if (
            isinstance(
                result,
                dict,
            )
            and result.get(
                "action"
            ) == "list_skills"
        ):
            return True

    return False


def _build_allowed_markers(
    enabled_actions: tuple[str, ...],
    context=None,
) -> str:
    markers: list[str] = []
    has_list_skills_result = _context_has_list_skills_tool_result(
        context
    )

    if _action_enabled(enabled_actions, RUNTIME_ACTION_WEB_SEARCH, "web_search"):
        markers.append(INTERNAL_ACTION_WEB_SEARCH_MARKER)

    if _action_enabled(
        enabled_actions,
        RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
        "clean_tool_results",
    ):
        markers.append(INTERNAL_ACTION_CLEAN_TOOL_RESULTS_MARKER)

    if _action_enabled(
        enabled_actions,
        RUNTIME_ACTION_IDLE,
        "idle",
    ):
        markers.append(INTERNAL_ACTION_IDLE_MARKER)

    if (
        _action_enabled(enabled_actions, RUNTIME_ACTION_LIST_SKILLS, "list_skills")
        and not has_list_skills_result
    ):
        markers.append(INTERNAL_ACTION_LIST_SKILLS_MARKER)

    if (
        _action_enabled(enabled_actions, RUNTIME_ACTION_HIDE_SKILLS, "hide_skills")
        and has_list_skills_result
    ):
        markers.append(INTERNAL_ACTION_HIDE_SKILLS_MARKER)

    if (
        _action_enabled(enabled_actions, RUNTIME_ACTION_APPEND_SKILL, "append_skill")
        and has_list_skills_result
    ):
        markers.append(INTERNAL_ACTION_APPEND_SKILL_MARKER)

    if (
        _action_enabled(enabled_actions, RUNTIME_ACTION_REMOVE_SKILL, "remove_skill")
        and has_list_skills_result
    ):
        markers.append(INTERNAL_ACTION_REMOVE_SKILL_MARKER)

    if _action_enabled(enabled_actions, RUNTIME_ACTION_ASSET_ACTION, "asset_action"):
        markers.append(INTERNAL_ACTION_ASSET_ACTION_MARKER)

    if _action_enabled(enabled_actions, RUNTIME_ACTION_CREATE_TODO_LIST, "create_todo_list"):
        markers.append(INTERNAL_ACTION_CREATE_TODO_LIST_MARKER)

    if _action_enabled(enabled_actions, RUNTIME_ACTION_RESOLVE_TODO, "resolve_todo"):
        markers.append(INTERNAL_ACTION_RESOLVE_TODO_MARKER)

    if _action_enabled(enabled_actions, RUNTIME_ACTION_CHECK_TODO, "check_todo"):
        markers.append(INTERNAL_ACTION_CHECK_TODO_MARKER)

    if _action_enabled(enabled_actions, RUNTIME_ACTION_SAVE_SESSION, "save_session"):
        markers.append(INTERNAL_ACTION_SAVE_SESSION_MARKER)

    if _action_enabled(enabled_actions, RUNTIME_ACTION_LIST_DELAYED_MEMORY, "list_delayed_memory"):
        markers.append(DELAYED_MEMORY_LIST_MARKER)

    if _action_enabled(enabled_actions, RUNTIME_ACTION_APPEND_DELAYED_MEMORY, "append_delayed_memory"):
        markers.append(DELAYED_MEMORY_APPEND_MARKER)

    if _action_enabled(enabled_actions, RUNTIME_ACTION_REMOVE_DELAYED_MEMORY, "remove_delayed_memory"):
        markers.append(DELAYED_MEMORY_REMOVE_MARKER)

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


def _context_has_delayed_memory_reports(
    context=None,
) -> bool:
    reports = getattr(
        context,
        "delayed_memory_reports",
        None,
    )
    return bool(
        isinstance(
            reports,
            dict,
        )
        and reports
    )

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
    has_list_skills_result = _context_has_list_skills_tool_result(
        context
    )

    if _action_enabled(enabled_actions, RUNTIME_ACTION_WEB_SEARCH, "web_search"):
        instructions.append(WEB_SEARCH_RULES)

    if (
        _action_enabled(enabled_actions, RUNTIME_ACTION_LIST_SKILLS, "list_skills")
        or _action_enabled(enabled_actions, RUNTIME_ACTION_ASSET_ACTION, "asset_action")
    ):
        instructions.append(ASSETS_RULES)

    if _action_enabled(enabled_actions, RUNTIME_ACTION_CREATE_TODO_LIST, "create_todo_list"):
        instructions.append(RUNTIME_TODO_RULES)

    if _action_enabled(enabled_actions, RUNTIME_ACTION_SAVE_SESSION, "save_session"):
        instructions.append(SAVE_SESSION_RULES)

    if _action_enabled(enabled_actions, RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT, "save_delayed_memory_content"):
        instructions.append(SAVE_DELAYED_MEMORY_RULES)

    if (
        _context_has_delayed_memory_reports(context)
        and (
            _action_enabled(enabled_actions, RUNTIME_ACTION_LIST_DELAYED_MEMORY, "list_delayed_memory")
            or _action_enabled(enabled_actions, RUNTIME_ACTION_APPEND_DELAYED_MEMORY, "append_delayed_memory")
            or _action_enabled(enabled_actions, RUNTIME_ACTION_REMOVE_DELAYED_MEMORY, "remove_delayed_memory")
        )
    ):
        instructions.append(DELAYED_MEMORY_ACTION_RULES)

    if _action_enabled(enabled_actions, RUNTIME_ACTION_CREATE_ACTIVE_MEMORY, "create_active_memory"):
        instructions.append(CREATE_ACTIVE_MEMORY_RULES)
        _append_resolve_active_memory_rules(
            instructions,
            enabled_actions,
            context,
        )

    if (
        _action_enabled(enabled_actions, RUNTIME_ACTION_LIST_SKILLS, "list_skills")
    ):
        instructions.append(SKILL_ROUTING_RULES)

    if (
        has_list_skills_result
        and (
            _action_enabled(enabled_actions, RUNTIME_ACTION_APPEND_SKILL, "append_skill")
            or _action_enabled(enabled_actions, RUNTIME_ACTION_REMOVE_SKILL, "remove_skill")
        )
    ):
        instructions.append(APPEND_REMOVE_SKILL_RULES)

    if not enabled_actions:
        instructions = ["No runtime actions are currently enabled."]

    return "\n".join(instructions)


# ─────────────────────────────────────────────
# System prompt assembly
# ─────────────────────────────────────────────

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
