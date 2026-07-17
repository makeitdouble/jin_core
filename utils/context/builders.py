# Composes the top-level brain runtime context blocks from focused context helpers.
from .delayed_memory import (
    append_appended_delayed_memory,
)
from .memory import (
    append_L1_runtime_memory,
    append_L2_runtime_memory,
    append_L3_session_memory,
)
from .runtime_state import (
    append_current_runtime_todo,
    append_user_feedback,
    append_visible_session_state,
    append_zero_diff_alert,
    build_runtime_xml,
)
from .skills import (
    build_current_appended_skills_context,
)


def build_brain_top_runtime_context(
    context=None,
    runtime_actions=None,
    *,
    commit_active_memory_refresh: bool = False,
) -> str:

    parts = []

    append_user_feedback(
        parts,
        context,
    )
    append_L1_runtime_memory(
        parts,
        context,
        commit_active_memory_refresh=commit_active_memory_refresh,
    )
    parts.append(
        build_runtime_xml(
            context,
            runtime_actions,
        )
    )
    append_visible_session_state(
        parts,
        context,
    )
    append_current_runtime_todo(
        parts,
        context,
    )
    append_appended_delayed_memory(
        parts,
        context,
    )
    current_appended_skills_context = (
        build_current_appended_skills_context(
            context
        )
    )

    if current_appended_skills_context:
        parts.append(
            current_appended_skills_context
        )

    return "\n".join(
        parts
    )


def build_brain_runtime_context(
    context=None,
    runtime_actions=None,
    *,
    commit_active_memory_refresh: bool = False,
    include_top_runtime_context: bool = True,
) -> str:

    parts = []

    if include_top_runtime_context:
        append_user_feedback(
            parts,
            context,
        )
        append_L1_runtime_memory(
            parts,
            context,
            commit_active_memory_refresh=commit_active_memory_refresh,
        )

    if include_top_runtime_context:
        parts.append(
            build_runtime_xml(
                context,
                runtime_actions,
            )
        )
        append_visible_session_state(
            parts,
            context,
        )
    append_L3_session_memory(
        parts,
        context,
    )
    append_L2_runtime_memory(
        parts,
        context,
    )
    append_zero_diff_alert(
        parts,
        context,
    )

    return "\n".join(
        parts
    )
