# =============================================================================
#  JIN BRAIN CONTEXT BUILDER
#  Builds the complete brain system context in one place.
# =============================================================================

from __future__ import annotations

from datetime import datetime
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
    "CAN_SAVE_DELAYED_MEMORY": True,
    "CAN_SAVE_ACTIVE_MEMORY": True,
    "CAN_RUNTIME_TODO": False,
    "CAN_CLEAN_TOOL_RESULTS": True,
    "CAN_IDLE": True,
    "CAN_JIN_COLOR": True,
    "CAN_JIN_SIZE": True,
    "CAN_JIN_POSITION": True,
    "CAN_JIN_SPEED": True,
    "CAN_UPDATE_L4_FACTS": True,
}

BRAIN_RUNTIME_ACTIONS = {
    "CAN_DEEP_WEB_SEARCH": True,
    "CAN_WEB_SEARCH": True,
    "CAN_USE_ASSETS": True,
    "CAN_SAVE_DELAYED_MEMORY": True,
    "CAN_SAVE_ACTIVE_MEMORY": True,
    "CAN_RUNTIME_TODO": False,
    "CAN_CLEAN_TOOL_RESULTS": True,
    "CAN_IDLE": True,
    "CAN_JIN_COLOR": True,
    "CAN_JIN_SIZE": True,
    "CAN_JIN_POSITION": True,
    "CAN_JIN_SPEED": True,
    "CAN_UPDATE_L4_FACTS": True,
}

LOADED_DELAYED_MEMORY_CONTEXT_FIELDS = (
    "title",
    "summary",
    "tags",
    "body",
    "attachments_ids",
)

PREVIOUS_REASONING_EDGE_PERCENT = 25
PREVIOUS_REASONING_LOOP_EDGE_PERCENT = 15
PREVIOUS_REASONING_MIN_CROP_CHARS = 1000
PREVIOUS_REASONING_CONTEXT_MIN_CROP_CHARS = (
    PREVIOUS_REASONING_MIN_CROP_CHARS
    + 1000
)
PREVIOUS_REASONING_SEPARATOR_TEMPLATE = (
    "---------------------------- CUTTED {chars} chars ----------------------------"
)


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
    user_input: str = "",
    commit_active_memory_refresh: bool = False,
) -> None:

    from runtime.L1_memory_utils import (
        build_runtime_memory_context_text,
        canonicalize_runtime_memory_text,
        format_runtime_memory_snapshot_timestamp,
        get_runtime_memory_snapshot_datetime,
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
        include_lifecycle_suffixes=True,
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

        active_memory_context_records = [
            line
            for line in active_memory_text.splitlines()
            if not is_active_memory_record_paused(
                line
            )
        ]

        # Metabolism changes attention, not the persistent record order. The
        # prompt gets a salience-ranked view while storage/UI stay canonical.
        try:
            from runtime.metabolism import rank_active_memory_records

            active_memory_context_records = rank_active_memory_records(
                active_memory_context_records,
                context=context,
                user_input=user_input,
            )
        except Exception:
            pass

        active_memory_context_text = "\n".join(
            active_memory_context_records
        ).strip()

        if active_memory_context_text:
            parts.append(
                "<ACTIVE_MEMORY priority=\"active_runtime_contracts\">\n"
                f"{indent_xml(escape(canonicalize_runtime_memory_text(active_memory_context_text)))}\n"
                "</ACTIVE_MEMORY>"
            )

    if runtime_memory.strip():
        snapshots = getattr(
            context,
            "runtime_memory_snapshots",
            [],
        )
        latest_snapshot = (
            snapshots[-1]
            if isinstance(snapshots, list) and snapshots
            else None
        )

        snapshot_timestamp = ""
        if isinstance(latest_snapshot, dict):
            snapshot_timestamp = str(
                latest_snapshot.get(
                    "timestamp",
                    "",
                )
                or ""
            ).strip()

            snapshot_created_at = latest_snapshot.get(
                "created_at",
            )
            if not snapshot_timestamp and snapshot_created_at:
                snapshot_timestamp = format_runtime_memory_snapshot_timestamp(
                    snapshot_created_at
                )

        if not snapshot_timestamp:
            snapshot_timestamp = format_runtime_memory_snapshot_timestamp(
                get_runtime_memory_snapshot_datetime(
                    context
                )
            )

        parts.append(
            f'<RUNTIME_MEMORY ts="{escape(snapshot_timestamp)}">\n'
            f"{indent_xml(escape(canonicalize_runtime_memory_text(runtime_memory)))}\n"
            "</RUNTIME_MEMORY>"
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
            (
                _delayed_memory_last_loaded_timestamp(
                    report,
                ),
                _append_delayed_memory_context_age(
                    filename[:-5],
                    report,
                ),
            )
        )

    if not report_names:
        return ""

    report_names.sort(
        key=lambda item: (
            -item[0],
            item[1].casefold(),
        )
    )

    return (
        "<DELAYED_MEMORY>\n"
        + "\n".join(
            report_name
            for _, report_name in report_names
        )
        + "\n</DELAYED_MEMORY>"
    )


def _delayed_memory_last_loaded_timestamp(
    report: dict,
) -> float:

    if not isinstance(
        report,
        dict,
    ):
        return 0.0

    value = str(
        report.get(
            "last_loaded_date",
            "",
        )
        or ""
    ).strip()

    if not value:
        return 0.0

    normalized = (
        value[:-1] + "+00:00"
        if value.endswith("Z")
        else value
    )

    try:
        return datetime.fromisoformat(
            normalized
        ).timestamp()
    except (
        TypeError,
        ValueError,
        OverflowError,
    ):
        return 0.0


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
                if field_name == "attachments_ids":
                    from utils.attached_files_store import filter_existing_file_ids

                    field_value = filter_existing_file_ids(
                        field_value
                    )
                    if not field_value:
                        continue
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


def build_session_restore_resource_metadata_context(
    context=None,
) -> str:

    if context is None:
        return ""

    delayed_items = getattr(
        context,
        "runtime_session_restore_delayed_memory_metadata",
        [],
    )
    file_items = getattr(
        context,
        "runtime_session_restore_attached_file_metadata",
        [],
    )

    lines = [
        "<RESTORED_SESSION_RESOURCES>",
        "The following resources were loaded in the archived session. "
        "Their contents are intentionally omitted on this restoration turn; "
        "only identity metadata is provided.",
    ]

    if isinstance(delayed_items, list) and delayed_items:
        lines.append("Delayed memory reports previously loaded:")
        for item in delayed_items:
            if not isinstance(item, dict):
                continue
            report_id = str(item.get("id", "") or "").strip()
            title = str(item.get("title", "") or report_id).strip()
            if report_id:
                lines.append(
                    f'- {escape(title)} [ id: {escape(report_id)} ]'
                )

    if isinstance(file_items, list) and file_items:
        lines.append("Files previously attached:")
        for item in file_items:
            if not isinstance(item, dict):
                continue
            file_id = str(item.get("id", "") or "").strip()
            title = str(item.get("title", "") or file_id).strip()
            if file_id:
                lines.append(
                    f'- {escape(title)} [ id: {escape(file_id)} ]'
                )

    lines.append("</RESTORED_SESSION_RESOURCES>")

    if len(lines) <= 3:
        return ""

    return "\n".join(lines)


def build_long_term_memory_context(
    context=None,
    user_input: str = "",
) -> str:

    if context is None:
        return ""

    from runtime.L4_memory import build_runtime_l4_memory_context

    restore_fact_ids = None
    if getattr(
        context,
        "runtime_session_restore_priming",
        False,
    ):
        restore_fact_ids = list(
            getattr(
                context,
                "runtime_session_restore_l4_fact_ids",
                [],
            )
            or []
        )

    return build_runtime_l4_memory_context(
        context=context,
        fact_ids=restore_fact_ids,
        user_input=user_input,
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

    cut_chars = len(cleaned) - edge_chars * 2

    return (
        cleaned[:edge_chars]
        + "\n"
        + PREVIOUS_REASONING_SEPARATOR_TEMPLATE.format(
            chars=cut_chars
        )
        + "\n"
        + cleaned[-edge_chars:]
    )


def _format_previous_reasoning_context(
    *,
    tag_name: str,
    reasoning: str,
    edge_percent: float,
    min_crop_chars: int = PREVIOUS_REASONING_MIN_CROP_CHARS,
    crop: bool = True,
) -> str:

    cropped_reasoning = (
        crop_previous_reasoning_text(
            reasoning,
            edge_percent=edge_percent,
            min_crop_chars=min_crop_chars,
        )
        if crop
        else str(
            reasoning
            or ""
        ).strip()
    )

    from utils.brain_client_utils import (
        indent_xml,
    )

    return (
        f"<{tag_name}>\n"
        + indent_xml(
            escape(
                cropped_reasoning
            ),
            spaces=4,
        )
        + f"\n</{tag_name}>"
    )


def build_previous_reasoning_context(
    context=None,
    *,
    include_turn_reasoning: bool = False,
    crop: bool = True,
) -> str:

    reasoning_parts = []
    seen_reasoning_parts = set()

    for attr_name in (
        "runtime_previous_reasoning_content",
        "runtime_turn_reasoning_content",
    ):
        if (
            attr_name == "runtime_turn_reasoning_content"
            and not include_turn_reasoning
        ):
            continue

        reasoning_part = str(
            getattr(
                context,
                attr_name,
                "",
            )
            if context is not None
            else ""
            or ""
        ).strip()

        if (
            not reasoning_part
            or reasoning_part in seen_reasoning_parts
        ):
            continue

        reasoning_parts.append(
            reasoning_part
        )
        seen_reasoning_parts.add(
            reasoning_part
        )

    return _format_previous_reasoning_context(
        tag_name="PREVIOUS_REASONING_CONTENT",
        reasoning="\n\n".join(
            reasoning_parts
        ),
        edge_percent=PREVIOUS_REASONING_EDGE_PERCENT,
        min_crop_chars=PREVIOUS_REASONING_CONTEXT_MIN_CROP_CHARS,
        crop=crop,
    )


def build_previous_reasoning_loop_context(
    context=None,
) -> str:

    if context is None:
        return ""

    loop_reasonings = getattr(
        context,
        "runtime_previous_reasoning_loop_contents",
        [],
    )

    if isinstance(
        loop_reasonings,
        str,
    ):
        loop_reasonings = [
            loop_reasonings,
        ]

    if not isinstance(
        loop_reasonings,
        list,
    ):
        return ""

    blocks = []

    for reasoning in loop_reasonings:
        if not str(
            reasoning
            or ""
        ).strip():
            continue

        blocks.append(
            _format_previous_reasoning_context(
                tag_name="PREVIOUS_REASONING_LOOP_CONTENT",
                reasoning=reasoning,
                edge_percent=PREVIOUS_REASONING_LOOP_EDGE_PERCENT,
            )
        )

    return "\n".join(
        blocks
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
    include_turn_reasoning: bool = False,
    crop_previous_reasoning: bool = True,
) -> str:

    from utils.context.current_concerns import (
        build_current_concerns_context,
    )
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
    from websocket.attachments import (
        build_attached_files_inventory_context,
    )

    prompt_parts = []
    runtime_context_parts = []
    restore_priming = bool(
        getattr(
            context,
            "runtime_session_restore_priming",
            False,
        )
    )

    if restore_priming:
        from .runtime import SESSION_RESTORE_MESSAGE

        # This must remain the first prompt block. It is a hidden restore tick,
        # not a user request.
        prompt_parts.append(
            SESSION_RESTORE_MESSAGE
        )

    enabled_actions = get_enabled_runtime_actions(
        runtime_actions
    )

    # Current concerns is an always-present live interrupt summary. Keep it
    # immediately above tool results so every normal prompt exposes the
    # current active-memory and pinned-resource pressure in one fixed place.
    prompt_parts.append(
        build_current_concerns_context(
            context
        )
    )

    # Tool results block: places recent tool/action outputs near the top.
    tool_results_context = build_tool_results_context(
        context
    )

    if tool_results_context:
        prompt_parts.append(
            tool_results_context
        )

    # Session actions history sits directly under tool results on ordinary
    # turns. Follow-up sequence prompts add CURRENT_REQUEST_FLOW beside it, so
    # the context window always exposes the relevant action trail in one
    # predictable place.
    session_actions_history_context = (
        build_session_actions_history_context(
            context
        )
    )

    if session_actions_history_context:
        prompt_parts.append(
            session_actions_history_context
        )

    # Persistent pinned files are a compact inventory between session actions
    # and delayed memory. Omit the block completely when no files are attached.
    if restore_priming:
        restored_resource_metadata_context = (
            build_session_restore_resource_metadata_context(
                context
            )
        )
        if restored_resource_metadata_context:
            prompt_parts.append(
                restored_resource_metadata_context
            )
    else:
        attached_files_context = build_attached_files_inventory_context(
            context
        )
        if attached_files_context:
            prompt_parts.append(
                attached_files_context
            )

        # Delayed memory inventory stays directly below attached files so available
        # reports are visible before the rest of the runtime state.
        delayed_memory_inventory_context = (
            build_delayed_memory_inventory_context(
                context
            )
        )

        if delayed_memory_inventory_context:
            prompt_parts.append(
                delayed_memory_inventory_context
            )

    # Skill inventory is always visible near the top of the prompt.
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

    # Silent metabolism block: the current state is allowed to modulate
    # attention/continuity but is never a conversational topic by default.
    try:
        from runtime.metabolism import build_metabolism_brain_context

        metabolism_context = build_metabolism_brain_context(
            context,
            user_input=user_input,
        )
        if metabolism_context:
            runtime_context_parts.append(
                metabolism_context
            )
    except Exception:
        pass

    # L1 memory block: includes active memory records and live runtime memory.
    _append_L1_runtime_memory(
        runtime_context_parts,
        context,
        user_input=user_input,
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

    # Loaded delayed memory block: pins the selected delayed memory report.
    loaded_delayed_memory_context = (
        build_loaded_delayed_memory_context(
            context
        )
        if not restore_priming
        else ""
    )

    if loaded_delayed_memory_context:
        runtime_context_parts.append(
            loaded_delayed_memory_context
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

    # Archived-session checkout gets one exact-dialogue priming turn before
    # falling back to the normal rolling recent-chat window. This preserves
    # the original conversational trajectory without permanently bloating
    # every subsequent prompt.
    restored_session_dialog = str(
        getattr(
            context,
            "runtime_restored_session_dialog",
            "",
        )
        or ""
    ).strip()

    if restored_session_dialog:
        prompt_parts.append(
            restored_session_dialog
        )
    else:
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

    # Previous reasoning block: a restore tick receives a one-shot raw dump of
    # the latest archived reasonings (newest first). Ordinary turns keep the
    # existing previous-reasoning behavior.
    restore_reasoning_dump = str(
        getattr(
            context,
            "runtime_session_restore_reasoning_dump",
            "",
        )
        or ""
    ).strip()

    if restore_priming and restore_reasoning_dump:
        prompt_parts.append(
            restore_reasoning_dump
        )
    else:
        previous_reasoning_loop_context = (
            build_previous_reasoning_loop_context(
                context
            )
        )

        if previous_reasoning_loop_context:
            prompt_parts.append(
                previous_reasoning_loop_context
            )
        elif (
            include_previous_reasoning
            and not getattr(
                context,
                "runtime_followup_tick_active",
                False,
            )
        ):
            prompt_parts.append(
                build_previous_reasoning_context(
                    context,
                    include_turn_reasoning=include_turn_reasoning,
                    crop=crop_previous_reasoning,
                )
            )

    # Restore priming is intentionally actionless: this hidden turn exists only
    # to re-establish conversational continuity. Normal action rules return on
    # the next user turn.
    if include_runtime_action_instructions and not restore_priming:
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

