import json
import re
import time
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


def build_current_appended_skills_context(
    context=None,
) -> str:

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


def build_session_actions_history_context(
    context=None,
) -> str:

    if context is None:
        return ""

    history_items = list(
        getattr(
            context,
            "runtime_session_action_history",
            [],
        )
        or []
    )

    now = time.time()
    history = []

    for item in history_items:
        created_at = None

        if isinstance(
            item,
            dict,
        ):
            text = str(
                item.get(
                    "text",
                    "",
                )
                or ""
            ).strip()
            raw_created_at = item.get(
                "created_at"
            )
            if isinstance(
                raw_created_at,
                (int, float),
            ):
                created_at = float(
                    raw_created_at
                )
        else:
            text = str(
                item
                or ""
            ).strip()

        if not text:
            continue

        if created_at is not None:
            text = (
                f"{text} ( {format_session_action_age(now - created_at)} ago )"
            )

        history.append(
            text
        )

    if not history:
        return ""

    lines = [
        f"{index}. {item}"
        for index, item in enumerate(
            history,
            start=1,
        )
    ]

    return (
        "<SESSION_ACTIONS_HISTORY>\n"
        f"{indent_xml(escape(chr(10).join(lines)), spaces=4)}\n"
        "</SESSION_ACTIONS_HISTORY>"
    )


def format_session_action_age(
    elapsed_seconds,
) -> str:

    seconds = max(
        0,
        int(
            elapsed_seconds
        ),
    )

    if seconds < 60:
        return f"{seconds}s"

    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"

    hours = minutes // 60
    if hours < 24:
        return f"{hours}h"

    days = hours // 24
    return f"{days}d"


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


def build_brain_top_runtime_context(
    context=None,
    runtime_actions=None,
    *,
    commit_active_memory_refresh: bool = False,
) -> str:

    parts = []

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


def format_context_message_age_suffix(
    created_at,
    *,
    now: float | None = None,
) -> str:

    if not isinstance(
        created_at,
        (int, float),
    ):
        return ""

    if created_at <= 0:
        return ""

    if now is None:
        now = time.time()

    return (
        f" ( {format_session_action_age(now - float(created_at))} ago )"
    )


def append_context_message_age(
    text: str,
    created_at,
    *,
    now: float | None = None,
) -> str:

    suffix = format_context_message_age_suffix(
        created_at,
        now=now,
    )

    if not suffix:
        return text

    return f"{text}{suffix}"


def build_latest_user_request_context(
    user_message: str,
    *,
    created_at=None,
) -> str:

    text = str(
        user_message
        or ""
    ).strip()

    if not text:
        return ""

    text = append_context_message_age(
        text,
        created_at,
    )

    return (
        "<LATEST_USER_REQUEST>\n"
        "!!!this is not a current user prompt!!!"
        "!!!this is not a start message!!!"
        "!!!this is initial user request provided by follow up tick!!!"
        f"{escape(text)}\n"
        "</LATEST_USER_REQUEST>"
    )


def build_previous_chat_messages_context_text(
    recent_turns: list[dict] | None,
    *,
    extra_user_message: str = "",
    extra_user_created_at=None,
) -> str:

    turns = list(
        recent_turns
        or []
    )[-RECENT_MESSAGES_MAX_PAIRS:]

    lines = [
        "<PREVIOUS_CHAT_MESSAGES>",
    ]
    last_user_text = ""
    now = time.time()

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
            last_user_text = user_text
            user_text = append_context_message_age(
                user_text,
                turn.get(
                    "user_created_at",
                    turn.get(
                        "created_at",
                    ),
                ),
                now=now,
            )
            lines.append(
                f"<USER>{escape(user_text)}"
            )

        if jin_text:
            jin_text = append_context_message_age(
                jin_text,
                turn.get(
                    "jin_created_at",
                    turn.get(
                        "created_at",
                    ),
                ),
                now=now,
            )
            lines.append(
                f"<JIN>{escape(jin_text)}"
            )

    extra_user_text = crop_recent_message_text(
        extra_user_message
    )

    if (
            extra_user_text
            and extra_user_text != last_user_text
    ):
        extra_user_text = append_context_message_age(
            extra_user_text,
            extra_user_created_at,
            now=now,
        )
        lines.append(
            f"<USER>{escape(extra_user_text)}"
        )

    lines.append(
        "</PREVIOUS_CHAT_MESSAGES>"
    )

    return "\n".join(
        lines
    )


def build_previous_chat_messages_context(
    context=None,
    *,
    extra_user_message: str = "",
) -> str:

    if context is None and not extra_user_message:
        return ""

    recent_turns = getattr(
        context,
        "runtime_recent_turns",
        [],
    ) if context is not None else []

    if not recent_turns and not extra_user_message:
        return ""

    return build_previous_chat_messages_context_text(
        recent_turns,
        extra_user_message=extra_user_message,
        extra_user_created_at=getattr(
            context,
            "runtime_turn_started_at",
            None,
        ) if context is not None else None,
    )


def append_previous_chat_messages(
    parts: list[str],
    context=None,
) -> None:

    previous_chat_messages_context = (
        build_previous_chat_messages_context(
            context
        )
    )

    if not previous_chat_messages_context:
        return

    parts.append(
        previous_chat_messages_context
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


def format_tool_result_payload(
    payload,
) -> str:

    formatted = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
    )

    lines = []

    for line in formatted.splitlines():
        indent = re.match(
            r"\s*",
            line,
        ).group(0)
        lines.append(
            line.replace(
                "\\n",
                "\n"
                + indent
                + "    ",
            )
        )

    return "\n".join(
        lines
    )


def _normalize_skill_status_name(
    name,
) -> str:

    normalized = str(
        name
        or ""
    ).strip()

    if normalized.lower().endswith(
        ".txt"
    ):
        normalized = normalized[:-4]

    normalized = re.sub(
        r"[^A-Za-z0-9]+",
        "_",
        normalized,
    ).strip(
        "_"
    ).lower()

    return re.sub(
        r"_+",
        "_",
        normalized,
    )


def _appended_skill_names(
    context=None,
) -> set[str]:

    appended_skills = list(
        getattr(
            context,
            "runtime_appended_skills",
            [],
        )
        or []
    )
    names = set()

    for skill in appended_skills:
        if isinstance(
            skill,
            dict,
        ):
            raw_name = skill.get(
                "name",
                "",
            )
        else:
            raw_name = skill

        name = _normalize_skill_status_name(
            raw_name
        )
        if name:
            names.add(
                name
            )

    return names


def format_list_skills_result(
    result: dict,
    context=None,
) -> str:

    lines = []

    skills = [
        skill
        for skill in result.get(
            "skills",
            [],
        )
        or []
        if isinstance(
            skill,
            dict,
        )
    ]

    if not skills:
        lines.append(
            "No skills found."
        )
        return "\n".join(
            lines
        )

    appended_names = _appended_skill_names(
        context
    )

    for index, skill in enumerate(
        skills,
        start=1,
    ):
        name = str(
            skill.get(
                "name",
                "",
            )
            or ""
        ).strip()

        if not name:
            name = "(unnamed skill)"

        status = ""
        if _normalize_skill_status_name(
            name
        ) in appended_names:
            status = " (appended)"

        path = str(
            skill.get(
                "path",
                "",
            )
            or ""
        ).strip()
        path_suffix = (
            f" - {path}"
            if path
            else ""
        )

        lines.append(
            f"{index}. {name}{status}{path_suffix}"
        )

    return "\n".join(
        lines
    )


def format_missing_skill_result(
    result: dict,
) -> str:

    requested = str(
        result.get(
            "requested",
            "",
        )
        or ""
    ).strip()

    if not requested:
        requested = "unknown"

    return (
        "You attempted to append a skill that does not exist: "
        f"{requested}"
    )


def format_asset_result_sections(
    payload,
    context=None,
) -> list[tuple[str, str]]:

    if not isinstance(
        payload,
        list,
    ):
        return [
            (
                "ASSETS",
                format_tool_result_payload(
                    payload
                ),
            ),
        ]

    sections = []
    pending_results = []
    latest_list_skills_index = None

    for index, result in enumerate(
        payload,
    ):
        if (
            isinstance(
                result,
                dict,
            )
            and result.get(
                "action"
            )
            == "list_skills"
        ):
            latest_list_skills_index = index

    def flush_pending_results() -> None:
        if not pending_results:
            return

        sections.append(
            (
                "ASSETS",
                format_tool_result_payload(
                    list(
                        pending_results
                    )
                ),
            )
        )
        pending_results.clear()

    for index, result in enumerate(
        payload,
    ):
        if (
            isinstance(
                result,
                dict,
            )
            and result.get(
                "action"
            )
            == "append_skill"
            and result.get("ok") is False
            and result.get("error") == "skill_not_found"
        ):
            flush_pending_results()
            sections.append(
                (
                    "SKILL_ERROR",
                    format_missing_skill_result(
                        result
                    ),
                )
            )
            continue

        if (
            isinstance(
                result,
                dict,
            )
            and result.get(
                "action"
            )
            == "list_skills"
        ):
            if index != latest_list_skills_index:
                continue

            flush_pending_results()
            sections.append(
                (
                    "SKILLS",
                    format_list_skills_result(
                        result,
                        context,
                    ),
                )
            )
            continue

        pending_results.append(
            result
        )

    flush_pending_results()

    return [
        section
        for section in sections
        if section[1]
    ]


def format_delayed_memory_list_result(
    result: dict,
) -> str:

    reports = [
        report
        for report in result.get(
            "reports",
            [],
        )
        or []
        if isinstance(
            report,
            dict,
        )
    ]

    if not reports:
        return "No delayed memory reports saved."

    lines = []

    for index, report in enumerate(
        reports,
        start=1,
    ):
        title = str(
            report.get(
                "title",
                "",
            )
            or ""
        ).strip()

        if not title:
            title = "Untitled delayed memory"

        report_id = str(
            report.get(
                "id",
                "",
            )
            or ""
        ).strip()

        lines.append(
            f"{index}. {title} | id: {report_id}"
        )

    return "\n".join(
        lines
    )


def format_delayed_memory_report_result(
    result: dict,
) -> str:

    if result.get("ok") is False:
        return format_tool_result_payload(
            result
        )

    report = result.get(
        "report",
        {},
    )

    if not isinstance(
        report,
        dict,
    ):
        return format_tool_result_payload(
            result
        )

    return format_tool_result_payload(
        report
    )


def format_delayed_memory_result_sections(
    payload,
) -> list[tuple[str, str]]:

    sections = []

    for result in payload:
        if not isinstance(
            result,
            dict,
        ):
            continue

        action = str(
            result.get(
                "action",
                "",
            )
            or ""
        )

        if action == "list_delayed_memory":
            sections.append(
                (
                    "LIST_DELAYED_MEMORY",
                    format_delayed_memory_list_result(
                        result
                    ),
                )
            )
            continue

        if action == "remove_delayed_memory":
            sections.append(
                (
                    "REMOVE_DELAYED_MEMORY",
                    format_tool_result_payload(
                        result
                    ),
                )
            )

    return [
        section
        for section in sections
        if section[1]
    ]


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

    tool_result_blocks = []
    for name, payload in format_asset_result_sections(
        asset_results[-5:],
        context,
    ):
        tool_result_blocks.append(
            f'    <TOOL_RESULT name="{escape(name)}">\n'
            f"{indent_xml(escape(payload))}\n"
            "    </TOOL_RESULT>"
        )

    parts.append(
        '<TOOL_RESULTS>\n'
        f"{chr(10).join(tool_result_blocks)}\n"
        "</TOOL_RESULTS>"
    )


def append_delayed_memory_results(
    parts: list[str],
    context=None,
) -> None:

    if context is None:
        return

    delayed_memory_results = list(
        getattr(
            context,
            "runtime_delayed_memory_results",
            [],
        )
        or []
    )

    if not delayed_memory_results:
        return

    tool_result_blocks = []

    for name, payload in format_delayed_memory_result_sections(
        delayed_memory_results[-5:],
    ):
        tool_result_blocks.append(
            f'    <TOOL_RESULT name="{escape(name)}">\n'
            f"{indent_xml(escape(payload))}\n"
            "    </TOOL_RESULT>"
        )

    if not tool_result_blocks:
        return

    parts.append(
        '<TOOL_RESULTS type=\'delayed_memory\'>\n'
        f"{chr(10).join(tool_result_blocks)}\n"
        "</TOOL_RESULTS>"
    )


def build_appended_delayed_memory_context(
    context=None,
) -> str:

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


def append_appended_delayed_memory(
    parts: list[str],
    context=None,
) -> None:

    appended_delayed_memory_context = (
        build_appended_delayed_memory_context(
            context
        )
    )

    if appended_delayed_memory_context:
        parts.append(
            appended_delayed_memory_context
        )


def append_appended_skills(
    parts: list[str],
    context=None,
) -> None:

    if context is None:
        return

    appended_skills = list(
        getattr(
            context,
            "runtime_appended_skills",
            [],
        )
        or []
    )

    if not appended_skills:
        return

    parts.append(
        "<APPENDED_SKILLS_CONTENT>\n"
        f"{indent_xml(escape(format_tool_result_payload(appended_skills)))}\n"
        "</APPENDED_SKILLS_CONTENT>"
    )


def build_tool_results_context(
    context=None,
) -> str:

    parts = []

    append_tool_results(
        parts,
        context,
    )
    append_asset_results(
        parts,
        context,
    )
    append_delayed_memory_results(
        parts,
        context,
    )
    append_appended_skills(
        parts,
        context,
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
        append_L1_runtime_memory(
            parts,
            context,
            commit_active_memory_refresh=commit_active_memory_refresh,
        )

    append_user_feedback(
        parts,
        context,
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
    append_session_event_snapshots(
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
