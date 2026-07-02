import json
from datetime import datetime
from xml.sax.saxutils import escape

from app_settings import (
    settings,
)
from rules.assembler import (
    build_conversation_activity_instruction,
    build_zero_diff_stall_instruction,
    get_enabled_runtime_actions,
)
from rules.runtime import (
    RUNTIME_ACTION_ASSET_ACTION,
    RUNTIME_ACTION_CREATE_ACTIVE_MEMORY,
    RUNTIME_ACTION_LIST_SKILLS,
    RUNTIME_ACTION_SAVE_SESSION,
    RUNTIME_ACTION_WEB_SEARCH,
)
from clients.brain_client_utils import (
    get_conversation_activity_diff,
    get_conversation_activity_percent,
    indent_xml,
    strip_empty_results_xml,
)
from runtime.runtime_context import (
    ContextContract,
    RECENT_MESSAGE_MAX_CHARS,
    RECENT_MESSAGES_MAX_PAIRS,
    format_user_feedback,
    format_session_state,
)
from runtime.L1_memory_utils import (
    build_runtime_memory_context_text,
    build_runtime_response_feedback_value,
    canonicalize_runtime_memory_text,
)
from utils.runtime_actions import (
    refresh_active_memory_runtime_metadata,
    is_active_memory_record_paused,
    remove_active_memory_entries,
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


def append_session_state(
    parts: list[str],
    context=None,
) -> None:

    if context is None:
        return

    parts.append(
        format_session_state(
            turn_number=getattr(context, "turn_number", 0),
            user_message_count=getattr(context, "user_message_count", 0),
            assistant_message_count=getattr(
                context,
                "assistant_message_count",
                0,
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
        "<PREVIOUS_SESSION_STATE priority=\"higher_than_runtime_memory\">\n"
        f"{indent_xml(escape(session_memory))}\n"
        "</PREVIOUS_SESSION_STATE>"
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

    if not session_event_snapshots:
        return

    parts.append(
        "<SESSION_EVENT_SNAPSHOTS priority=\"session_context\">\n"
        f"{indent_xml(escape(json.dumps(session_event_snapshots, ensure_ascii=False, indent=2)))}\n"
        "</SESSION_EVENT_SNAPSHOTS>"
    )


def append_L1_runtime_memory(
    parts: list[str],
    context=None,
    *,
    commit_active_memory_refresh: bool = False,
) -> None:

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

    if runtime_memory.strip():
        parts.append(
            "<RUNTIME_MEMORY>\n"
            f"{indent_xml(escape(canonicalize_runtime_memory_text(runtime_memory)))}\n"
            "</RUNTIME_MEMORY>"
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
        active_memory_refresh_turn = (
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
        active_memory_refresh_committed = (
            commit_active_memory_refresh
            and getattr(
                context,
                "runtime_active_memory_records_refresh_turn",
                None,
            )
            == active_memory_refresh_turn
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
                add_runtime_user_idle_to_elapsed=True,
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

        if not active_memory_context_text:
            return

        parts.append(
            "<ACTIVE_MEMORY priority=\"active_runtime_contracts\">\n"
            f"{indent_xml(escape(canonicalize_runtime_memory_text(active_memory_context_text)))}\n"
            "</ACTIVE_MEMORY>"
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


def crop_recent_message_text(
    text: str,
    max_chars: int = RECENT_MESSAGE_MAX_CHARS,
) -> str:

    cleaned = str(
        text
        or ""
    ).replace(
        "\r\n",
        "\n",
    ).replace(
        "\r",
        "\n",
    )

    cleaned = cleaned.replace(
        "\n",
        "\\n",
    ).strip()

    if max_chars <= 0:
        return ""

    if len(cleaned) <= max_chars:
        return cleaned

    if max_chars <= 3:
        return "." * max_chars

    return (
        cleaned[: max_chars - 3].rstrip()
        + "..."
    )


def build_recent_turns_context_text(
    recent_turns: list[dict] | None,
) -> str:

    turns = list(
        recent_turns
        or []
    )[-RECENT_MESSAGES_MAX_PAIRS:]

    lines = [
        "<recent_turns>",
    ]

    for turn in turns:
        if not isinstance(
            turn,
            dict,
        ):
            continue

        user_text = crop_recent_message_text(
            turn.get(
                "user",
                "",
            )
        )
        jin_text = crop_recent_message_text(
            turn.get(
                "jin",
                "",
            )
        )

        if user_text:
            lines.append(
                f"user: {user_text}"
            )

        if jin_text:
            lines.append(
                f"jin: {jin_text}"
            )

    lines.append(
        "</recent_turns>"
    )

    return "\n".join(
        lines
    )


def append_recent_turns(
    parts: list[str],
    context=None,
) -> None:

    if context is None:
        return

    recent_turns = getattr(
        context,
        "runtime_recent_turns",
        [],
    )

    if not recent_turns:
        return

    parts.append(
        build_recent_turns_context_text(
            recent_turns
        )
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


def append_asset_results(
    parts: list[str],
    context=None,
) -> None:

    if context is None:
        return

    asset_results = list(
        getattr(
            context,
            "runtime_asset_results",
            [],
        )
        or []
    )

    if not asset_results:
        return

    parts.append(
        '<TOOL_RESULTS type="internal_trusted_assets">\n'
        '    <TOOL_RESULT name="ASSETS">\n'
        f"{indent_xml(escape(json.dumps(asset_results[-5:], ensure_ascii=False, indent=2)))}\n"
        "    </TOOL_RESULT>\n"
        "</TOOL_RESULTS>"
    )


def build_brain_runtime_context(
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

    parts.append(
        build_runtime_xml(
            context,
            runtime_actions,
        )
    )

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
        commit_active_memory_refresh=commit_active_memory_refresh,
    )
    append_L2_runtime_memory(
        parts,
        context,
    )
    append_recent_turns(
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
    append_asset_results(
        parts,
        context,
    )

    return "\n".join(
        parts
    )
