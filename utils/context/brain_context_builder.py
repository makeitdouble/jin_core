# Facade that re-exports the brain runtime context builder API from focused modules.
import time

from .formatting import (
    format_tool_result_payload,
)
from .runtime_state import (
    append_current_runtime_todo,
    append_user_feedback,
    append_visible_session_state,
    append_zero_diff_alert,
    build_runtime_xml,
    get_brain_runtime_mode,
    get_conversation_activity_instruction,
    get_visible_assistant_message_count,
    get_visible_turn_count,
)
from .skills import (
    _appended_skill_names,
    _normalize_skill_status_name,
    append_appended_skills,
    build_current_appended_skills_context,
    format_list_skills_result,
    format_missing_skill_result,
)
from .session_actions import (
    _is_current_sequence_action,
    _normalize_session_action_history_item,
    build_session_actions_history_context,
    format_session_action_age,
    strip_actions_history_context,
)
from .memory import (
    append_L1_runtime_memory,
    append_L2_runtime_memory,
    append_L3_session_memory,
)
from .messages import (
    append_context_message_age,
    append_previous_chat_messages,
    build_previous_chat_messages_context,
    build_previous_chat_messages_context_text,
    build_sequence_origin_request_context,
    crop_recent_message_text,
    format_context_message_age_suffix,
)
from .assets import (
    append_asset_results,
    format_asset_result_sections,
)
from .delayed_memory import (
    append_appended_delayed_memory,
    append_delayed_memory_results,
    build_appended_delayed_memory_context,
    format_delayed_memory_list_result,
    format_delayed_memory_report_result,
    format_delayed_memory_result_sections,
)
from .result_sections import (
    format_active_memory_result_sections,
    format_session_result_sections,
)
from .tool_results import (
    append_recorded_tool_results,
    append_tool_results,
    build_tool_results_context,
)
from .builders import (
    build_brain_runtime_context,
    build_brain_top_runtime_context,
)

__all__ = [
    "append_L1_runtime_memory",
    "append_L2_runtime_memory",
    "append_L3_session_memory",
    "append_appended_delayed_memory",
    "append_appended_skills",
    "append_asset_results",
    "append_context_message_age",
    "append_current_runtime_todo",
    "append_delayed_memory_results",
    "append_previous_chat_messages",
    "append_recorded_tool_results",
    "append_tool_results",
    "append_user_feedback",
    "append_visible_session_state",
    "append_zero_diff_alert",
    "build_appended_delayed_memory_context",
    "build_brain_runtime_context",
    "build_brain_top_runtime_context",
    "build_current_appended_skills_context",
    "build_previous_chat_messages_context",
    "build_previous_chat_messages_context_text",
    "build_runtime_xml",
    "build_sequence_origin_request_context",
    "build_session_actions_history_context",
    "build_tool_results_context",
    "crop_recent_message_text",
    "format_active_memory_result_sections",
    "format_asset_result_sections",
    "format_context_message_age_suffix",
    "format_delayed_memory_list_result",
    "format_delayed_memory_report_result",
    "format_delayed_memory_result_sections",
    "format_list_skills_result",
    "format_missing_skill_result",
    "format_session_action_age",
    "format_session_result_sections",
    "format_tool_result_payload",
    "get_brain_runtime_mode",
    "get_conversation_activity_instruction",
    "get_visible_assistant_message_count",
    "get_visible_turn_count",
    "strip_actions_history_context",
    "time",
]
