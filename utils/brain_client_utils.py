from app_settings import settings

from rules.brain_context_builder import (
    BRAIN_RUNTIME_ACTIONS,
    SERVICE_AS_BRAIN_RUNTIME_ACTIONS,
)


def get_brain_runtime_config():

    if settings.USE_SERVICE_AS_BRAIN:

        return {
            "runtime_id": (
                settings
                .SERVICE_MODEL_UID
            ),
            "label": "service",
            "context_window": (
                settings.SERVICE_CONTEXT_WINDOW
            ),
            "log_method": (
                "log_service_as_brain"
            ),
            "model_output_log_method": (
                "log_service_as_brain_output"
            ),
            "runtime_actions": (
                SERVICE_AS_BRAIN_RUNTIME_ACTIONS
            ),
        }

    return {
        "runtime_id": (
            settings
            .BRAIN_MODEL_UID
        ),
        "label": "brain",
        "context_window": (
            settings
            .BRAIN_CONTEXT_WINDOW
        ),
        "log_method": (
            "log_brain"
        ),
        "model_output_log_method": (
            "log_brain_output"
        ),
        "runtime_actions": (
            BRAIN_RUNTIME_ACTIONS
        ),
    }


import asyncio
import json
import re
import time
from copy import deepcopy
from datetime import datetime
from xml.etree import ElementTree

from contracts.rules_assembler import (
    RUNTIME_ACTION_APPEND_DELAYED_MEMORY,
    RUNTIME_ACTION_APPEND_SKILL,
    RUNTIME_ACTION_ASSET_ACTION,
    RUNTIME_ACTION_CHECK_TODO,
    RUNTIME_ACTION_CREATE_TODO_LIST,
    RUNTIME_ACTION_SAVE_ACTIVE_MEMORY,
    RUNTIME_ACTION_LIST_DELAYED_MEMORY,
    RUNTIME_ACTION_LIST_SKILLS,
    RUNTIME_ACTION_IDLE,
    RUNTIME_ACTION_JIN_COLOR,
    RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
    RUNTIME_ACTION_REMOVE_DELAYED_MEMORY,
    RUNTIME_ACTION_REMOVE_SKILL,
    RUNTIME_ACTION_RESOLVE_TODO,
    RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT,
    RUNTIME_ACTION_SAVE_SESSION,
    RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY,
    RUNTIME_ACTION_WEB_SEARCH,
    build_runtime_action_display_text,
    get_runtime_action_display_name,
    runtime_action_has_close_tag,
)
from rules.runtime import (
    ACTION_REJECTED_MISSING_TRIGGER_WORDS_MESSAGE,
    NO_ENTRIES_FOUND_MESSAGE,
)
from utils.assets_utils import (
    ensure_assets_tree,
    _parse_lenient_asset_payload,
)
from utils.python_skill_asset_utils import (
    run_context_asset_action,
)
from utils.skills_asset_utils import (
    list_skills,
    load_skill,
    normalize_skill_name,
)
from utils.actions import (
    build_runtime_action_id,
    collect_active_memory_slot_ids,
    extract_active_memory_resolve_slot_id,
    extract_search_query,
    extract_runtime_actions,
    generate_active_memory_slot_id,
    generate_active_memory_slot_key,
    generate_delayed_memory_report_id,
    get_save_active_memory_marker_fields,
    is_delayed_memory_report_id,
    is_active_memory_record_paused,
    parse_delayed_memory_content_payload,
    parse_idle_seconds,
    normalize_jin_color_payload,
    refresh_active_memory_runtime_metadata,
    strip_active_memory_runtime_metadata,
    strip_active_memory_managed_suffixes,
)
from utils.session_actions_history import (
    build_active_memory_resolve_failed_history_text,
    build_asset_action_history_text,
    build_asset_action_marker_text,
    record_session_action_history,
)
from utils.tool_results import (
    TOOL_RESULT_KIND_ASSET,
    TOOL_RESULT_KIND_ACTIVE_MEMORY,
    TOOL_RESULT_KIND_DELAYED_MEMORY,
    clear_runtime_tool_results,
    record_runtime_tool_result,
    remove_runtime_tool_results,
)
from utils.tool_results_context import (
    strip_tools_results_context,
)
from utils.runtime_todo import (
    apply_runtime_todo_action_result,
    attach_runtime_todo_item_to_result,
    build_runtime_todo_history_text,
    check_runtime_todo_item,
    create_runtime_todo,
    has_active_runtime_todo,
    mark_next_runtime_todo_item_resolved,
    normalize_file_exists_for_runtime_todo,
    parse_runtime_todo_item_id,
    resolve_runtime_todo_item,
)
from utils.runtime_action_abort import (
    mark_runtime_action_started,
    mark_runtime_actions_completed,
)


def should_execute_save_session(
    user_message: str,
) -> bool:
    from runtime.behavior_contract import (
        should_execute_action_guard,
    )

    return should_execute_action_guard(
        "save_session",
        user_message
    )


def should_prearm_save_session(
    user_message: str,
) -> bool:
    from runtime.behavior_contract import (
        should_prearm_action_guard,
    )

    return should_prearm_action_guard(
        "save_session",
        user_message
    )


def should_execute_save_delayed_memory(
    user_message: str,
) -> bool:
    from runtime.behavior_contract import (
        should_execute_action_guard,
    )

    return should_execute_action_guard(
        "save_delayed_memory",
        user_message
    )


def build_action_missing_trigger_words_message(
    runtime_action: str,
    template: str,
) -> str:
    from runtime.behavior_contract import (
        get_action_guard_name_for_runtime_action,
        get_action_guard_triggers,
    )
    from utils.actions.common_action_utils import (
        format_runtime_trigger_words_message,
    )

    guard_name = get_action_guard_name_for_runtime_action(
        runtime_action
    )
    return format_runtime_trigger_words_message(
        template,
        get_action_guard_triggers(
            guard_name
        ),
    )


def build_delayed_memory_report(
    context,
    payload: str,
    existing_ids=None,
) -> dict:

    try:
        report = json.loads(
            str(
                payload
                or ""
            )
        )
    except json.JSONDecodeError:
        report = parse_delayed_memory_content_payload(
            payload
        )

    if not isinstance(
        report,
        dict,
    ):
        return {}

    created_session_id = str(
        getattr(
            context,
            "session_id",
            "",
        )
        or ""
    ).strip()
    created_time = str(
        getattr(
            context,
            "timestamp",
            "",
        )
        or ""
    ).strip()

    if not created_time:
        created_time = datetime.now().isoformat()

    used_ids = {
        str(report_id or "").strip().casefold()
        for report_id in (existing_ids or ())
        if is_delayed_memory_report_id(
            str(report_id or "").strip().casefold()
        )
    }
    enriched_report = {}

    for key, value in report.items():
        if not isinstance(
            value,
            dict,
        ):
            continue

        report_id = str(
            key
            or ""
        ).strip().casefold()

        if (
            not is_delayed_memory_report_id(
                report_id
            )
            or report_id in used_ids
        ):
            report_id = generate_delayed_memory_report_id(
                used_ids
            )

        used_ids.add(
            report_id
        )

        enriched_report[report_id] = {
            **value,
            "created_session_id": (
                str(
                    value.get(
                        "created_session_id",
                        "",
                    )
                    or ""
                ).strip()
                or created_session_id
            ),
            "created_time": (
                str(
                    value.get(
                        "created_time",
                        "",
                    )
                    or ""
                ).strip()
                or created_time
            ),
            "created_date": (
                str(
                    value.get(
                        "created_date",
                        "",
                    )
                    or value.get(
                        "created_time",
                        "",
                    )
                    or ""
                ).strip()
                or created_time
            ),
            "appended_times": int(
                normalize_delayed_memory_counter(
                    value.get(
                        "appended_times",
                        0,
                    )
                )
            ),
            "append_streak": int(
                normalize_delayed_memory_counter(
                    value.get(
                        "append_streak",
                        0,
                    )
                )
            ),
            "last_appended_date": str(
                value.get(
                    "last_appended_date",
                    "",
                )
                or ""
            ).strip(),
            "last_appended_session_id": str(
                value.get(
                    "last_appended_session_id",
                    "",
                )
                or ""
            ).strip(),
            "all_appended_session_ids": (
                normalize_delayed_memory_session_ids(
                    value.get(
                        "all_appended_session_ids",
                        [],
                    )
                )
            ),
        }

    return enriched_report


def normalize_delayed_memory_counter(
    value,
) -> int:

    try:
        return max(
            int(
                value
                or 0
            ),
            0,
        )
    except (TypeError, ValueError):
        return 0


def normalize_delayed_memory_session_ids(
    value,
) -> list[str]:

    source = (
        value
        if isinstance(
            value,
            list,
        )
        else []
    )
    session_ids = []
    seen = set()

    for item in source:
        session_id = str(
            item
            or ""
        ).strip()

        if (
            not session_id
            or session_id in seen
        ):
            continue

        seen.add(
            session_id
        )
        session_ids.append(
            session_id
        )

    return session_ids


def update_delayed_memory_append_metadata(
    context,
    report: dict,
) -> dict:

    if not isinstance(
        report,
        dict,
    ):
        return {}

    updated_report = dict(
        report
    )
    now = str(
        getattr(
            context,
            "timestamp",
            "",
        )
        or ""
    ).strip() or datetime.now().isoformat()
    session_id = str(
        getattr(
            context,
            "session_id",
            "",
        )
        or getattr(
            context,
            "runtime_session_id",
            "",
        )
        or ""
    ).strip()
    previous_last_session_id = str(
        updated_report.get(
            "last_appended_session_id",
            "",
        )
        or ""
    ).strip()
    appended_session_ids = normalize_delayed_memory_session_ids(
        updated_report.get(
            "all_appended_session_ids",
            [],
        )
    )

    if (
        session_id
        and session_id not in appended_session_ids
    ):
        appended_session_ids.append(
            session_id
        )

    updated_report["created_date"] = (
        str(
            updated_report.get(
                "created_date",
                "",
            )
            or updated_report.get(
                "created_time",
                "",
            )
            or ""
        ).strip()
        or now
    )
    updated_report["created_time"] = (
        str(
            updated_report.get(
                "created_time",
                "",
            )
            or ""
        ).strip()
        or updated_report["created_date"]
    )
    updated_report["appended_times"] = (
        normalize_delayed_memory_counter(
            updated_report.get(
                "appended_times",
                0,
            )
        )
        + 1
    )
    updated_report["append_streak"] = normalize_delayed_memory_counter(
        updated_report.get(
            "append_streak",
            0,
        )
    )

    if (
        session_id
        and (
            not previous_last_session_id
            or previous_last_session_id != session_id
        )
    ):
        updated_report["append_streak"] += 1

    updated_report["last_appended_date"] = now
    updated_report["last_appended_session_id"] = session_id
    updated_report["all_appended_session_ids"] = appended_session_ids

    return updated_report


def record_appended_delayed_memory_id(
    context,
    report_id: str,
) -> None:

    normalized_report_id = str(
        report_id
        or ""
    ).strip().casefold()

    if not normalized_report_id:
        return

    appended_ids = getattr(
        context,
        "runtime_appended_delayed_memory_ids",
        None,
    )

    if not isinstance(
        appended_ids,
        list,
    ):
        appended_ids = []
        setattr(
            context,
            "runtime_appended_delayed_memory_ids",
            appended_ids,
        )

    if normalized_report_id not in appended_ids:
        appended_ids.append(
            normalized_report_id
        )


def deduplicate_delayed_memory_report_keys(
    existing_reports: dict,
    report: dict,
) -> dict:

    if not isinstance(
        report,
        dict,
    ):
        return {}

    used_keys = {
        str(report_id or "").strip().casefold()
        for report_id in (
            existing_reports
        if isinstance(
            existing_reports,
            dict,
        )
        else {}
        )
        if is_delayed_memory_report_id(
            str(report_id or "").strip().casefold()
        )
    }
    deduplicated_report = {}

    for key, value in report.items():
        next_key = str(
            key
            or ""
        ).strip().casefold()

        if (
            not is_delayed_memory_report_id(
                next_key
            )
            or next_key in used_keys
            or next_key in deduplicated_report
        ):
            next_key = generate_delayed_memory_report_id(
                used_keys.union(
                    deduplicated_report
                )
            )

        deduplicated_report[next_key] = value
        used_keys.add(
            next_key
        )

    return deduplicated_report



def split_active_memory_payload(
    payload: str,
) -> tuple[tuple[str, str], ...]:

    marker_fields = get_save_active_memory_marker_fields()

    if not marker_fields:
        return ()

    text = strip_active_memory_managed_suffixes(
        payload,
        extra_suffix_names=marker_fields,
    )

    if not text:
        return ()

    max_splits = max(
        len(marker_fields) - 1,
        0,
    )

    parts = [
        part.strip()
        for part in text.split(
            "|",
            max_splits,
        )
    ]

    while len(parts) < len(marker_fields):
        parts.append(
            ""
        )

    return tuple(
        (
            field,
            value,
        )
        for field, value in zip(
            marker_fields,
            parts,
        )
        if value
    )


def normalize_active_memory_runtime_payload(
    payload: str,
) -> str:

    return strip_active_memory_managed_suffixes(
        payload,
        extra_suffix_names=(
            get_save_active_memory_marker_fields()
        ),
    )


def build_active_memory_runtime_line(
    payload: str,
    *,
    existing_ids=None,
    slot_key: str = "active_memory_1",
) -> str:

    suffix_values = split_active_memory_payload(
        payload
    )

    if not suffix_values:
        return ""

    visible_value = suffix_values[0][1]
    suffix_text = " ".join(
        f"[ {field}: {field_value} ]"
        for field, field_value in suffix_values
    )
    active_memory_id = generate_active_memory_slot_id(
        existing_ids
    )
    value = (
        f"{visible_value} [ active_memory_id: {active_memory_id} ] "
        f"{suffix_text} [ status: pending ]"
    ).strip()

    slot_key = str(
        slot_key
        or "active_memory_1"
    ).strip()

    if not re.fullmatch(
        r"active_memory_\d+",
        slot_key,
        re.IGNORECASE,
    ):
        slot_key = "active_memory_1"

    return f"{slot_key}: {value}"


def normalize_active_memory_content_for_duplicate_check(
    memory: str,
) -> str:

    memory = strip_active_memory_runtime_metadata(
        memory
    )
    memory = re.sub(
        r"(?im)^\s*active_memory(?:_\d+)?\s*:\s*",
        "",
        memory,
    )
    memory = re.sub(
        (
            r"\s*\[\s*(?:active_memory_id|creation_time|"
            r"created_session_id|created_jin_message_number|"
            r"elapsed_time|elapsed_jin_message_number|status)"
            r"\s*:\s*[^\]]*\]\s*"
        ),
        " ",
        memory,
        flags=re.IGNORECASE,
    )

    return re.sub(
        r"\s+",
        " ",
        memory,
    ).strip().casefold()


def active_memory_duplicate_check_candidates(
    memory: str,
) -> tuple[str, ...]:

    candidates = []

    for value in (
        memory,
        *str(
            memory
            or ""
        ).splitlines(),
    ):
        normalized = normalize_active_memory_content_for_duplicate_check(
            value
        )

        if (
            normalized
            and normalized not in candidates
        ):
            candidates.append(
                normalized
            )

    return tuple(
        candidates
    )


def has_exact_active_memory_duplicate(
    context,
    active_memory_line: str,
) -> bool:

    candidate = normalize_active_memory_content_for_duplicate_check(
        active_memory_line
    )

    if not candidate:
        return False

    return any(
        candidate in active_memory_duplicate_check_candidates(
            existing_memory
        )
        for existing_memory in collect_context_active_memory_texts(
            context
        )
    )


def collect_context_active_memory_texts(
    context,
) -> tuple[str, ...]:

    active_records = getattr(
        context,
        "active_memory_records",
        None,
    )
    return (
        getattr(
            context,
            "runtime_memory",
            "",
        ),
        getattr(
            context,
            "runtime_memory_stable",
            "",
        ),
        "\n".join(
            str(record or "")
            for record in (active_records or ())
        ),
    )


def collect_context_active_memory_slot_ids(
    context,
) -> set[str]:

    return collect_active_memory_slot_ids(
        *collect_context_active_memory_texts(
            context
        )
    )


ACTIVE_MEMORY_RUNTIME_LINE_RE = re.compile(
    r"^\s*active_memory(?:_\d+)?\s*:",
    re.IGNORECASE,
)


def remove_active_memory_slot_from_text(
    memory: str,
    active_memory_id: str,
) -> tuple[str, bool]:

    active_memory_id = str(
        active_memory_id or ""
    ).strip().casefold()

    if not active_memory_id:
        return (
            memory or "",
            False,
        )

    removed = False
    kept_lines = []

    for line in str(
        memory or ""
    ).splitlines():
        if (
            ACTIVE_MEMORY_RUNTIME_LINE_RE.match(
                line
            )
            and active_memory_id in collect_active_memory_slot_ids(
                line
            )
        ):
            if is_active_memory_record_paused(
                line
            ):
                kept_lines.append(
                    line
                )
                continue

            removed = True
            continue

        kept_lines.append(
            line
        )

    if not removed:
        return (
            memory or "",
            False,
        )

    return (
        "\n".join(
            kept_lines
        ).strip(),
        True,
    )


def find_active_memory_slot_record(
    context,
    active_memory_id: str,
) -> str:

    normalized_id = str(
        active_memory_id or ""
    ).strip().casefold()

    if not normalized_id:
        return ""

    active_records = getattr(
        context,
        "active_memory_records",
        None,
    )
    sources = [
        *(active_records or ()),
        getattr(
            context,
            "runtime_memory",
            "",
        ),
        getattr(
            context,
            "runtime_memory_stable",
            "",
        ),
    ]

    for source in sources:
        for line in str(
            source or ""
        ).splitlines():
            if (
                ACTIVE_MEMORY_RUNTIME_LINE_RE.match(
                    line
                )
                and normalized_id in collect_active_memory_slot_ids(
                    line
                )
                and not is_active_memory_record_paused(
                    line
                )
            ):
                return line.strip()

    return ""


def build_active_memory_resolve_failure_result(
    context,
    payload: str,
    *,
    error: str = "",
) -> dict:

    requested = re.sub(
        r"\s+",
        " ",
        str(
            payload
            or ""
        ),
    ).strip()
    requested_id = extract_active_memory_resolve_slot_id(
        payload
    )
    available_ids = sorted(
        collect_context_active_memory_slot_ids(
            context
        )
    )
    normalized_error = str(
        error
        or (
            "active_memory_not_found"
            if requested_id
            else "invalid_active_memory_id"
        )
    ).strip()
    detail = (
        "Active memory was not resolved. "
        "Use an exact 6-character active_memory_id from <ACTIVE_MEMORY> "
        "and retry only for a record that is still pending."
    )

    result = {
        "ok": False,
        "action": "resolve_active_memory",
        "error": normalized_error,
        "requested": requested,
        "detail": detail,
        "available_ids": available_ids,
    }

    if requested_id:
        result["id"] = requested_id

    return result


def queue_active_memory_resolve_failure(
    context,
    result: dict,
) -> None:

    record_runtime_tool_result(
        context,
        TOOL_RESULT_KIND_ACTIVE_MEMORY,
        result,
    )

    pending = getattr(
        context,
        "runtime_active_memory_resolve_failures_pending",
        None,
    )

    if not isinstance(
        pending,
        list,
    ):
        pending = []
        setattr(
            context,
            "runtime_active_memory_resolve_failures_pending",
            pending,
        )

    pending.append(
        dict(result)
    )


def flush_pending_active_memory_resolve_failure_history(
    context,
) -> None:

    pending = getattr(
        context,
        "runtime_active_memory_resolve_failures_pending",
        None,
    )

    if not isinstance(
        pending,
        list,
    ) or not pending:
        return

    for result in pending:
        if not isinstance(
            result,
            dict,
        ):
            continue

        record_session_action_history(
            context,
            build_active_memory_resolve_failed_history_text(
                result
            ),
        )

    pending.clear()


async def resolve_active_memory_runtime_record(
    context,
    payload: str,
) -> tuple[bool, str, str]:

    if context is None:
        return (
            False,
            "",
            "",
        )

    active_memory_id = extract_active_memory_resolve_slot_id(
        payload,
        existing_ids=collect_context_active_memory_slot_ids(
            context
        ),
    )

    if not active_memory_id:
        return (
            False,
            "",
            "",
        )

    resolved_record = find_active_memory_slot_record(
        context,
        active_memory_id,
    )
    removed = False

    for attr_name in (
        "runtime_memory",
        "runtime_memory_stable",
    ):
        updated_memory, did_remove = remove_active_memory_slot_from_text(
            getattr(
                context,
                attr_name,
                "",
            ),
            active_memory_id,
        )

        if did_remove:
            setattr(
                context,
                attr_name,
                updated_memory,
            )
            removed = True

    records = getattr(
        context,
        "active_memory_records",
        None,
    )

    if records:
        kept_records = []

        for record in records:
            _, did_remove = remove_active_memory_slot_from_text(
                str(record or ""),
                active_memory_id,
            )

            if did_remove:
                removed = True
                continue

            kept_records.append(
                record
            )

        if len(kept_records) != len(records):
            setattr(
                context,
                "active_memory_records",
                kept_records,
            )

    return (
        removed,
        active_memory_id,
        resolved_record,
    )


async def save_active_memory_runtime_record(
    context,
    payload: str,
) -> bool:

    if context is None:
        return False

    active_memory_line = build_active_memory_runtime_line(
        payload,
        slot_key=generate_active_memory_slot_key(
            *collect_context_active_memory_texts(
                context
            )
        ),
        existing_ids=collect_context_active_memory_slot_ids(
            context
        ),
    )

    if not active_memory_line:
        return False

    if has_exact_active_memory_duplicate(
        context,
        active_memory_line,
    ):
        return False

    active_memory_line = refresh_active_memory_runtime_metadata(
        active_memory_line,
        previous_memory=active_memory_line,
        context=context,
    )

    active_records = getattr(
        context,
        "active_memory_records",
        None,
    )

    if active_records is None:
        active_records = []
        setattr(
            context,
            "active_memory_records",
            active_records,
        )

    if active_memory_line not in active_records:
        active_records.append(
            active_memory_line
        )

    return True


def resolve_runtime_action_user_message(
    context,
    user_message: str | None = None,
) -> str:

    if user_message:
        return user_message

    if context is None:
        return ""

    for attr_name in (
        "runtime_turn_user_message",
        "original_user_input",
        "user_input",
    ):

        value = getattr(
            context,
            attr_name,
            "",
        )

        if value:
            return value

    return ""


def build_runtime_action_marker_preview(
    marker: str,
    *,
    limit: int = 160,
) -> str:

    return (
        str(marker or "")
        .replace("\n", "\\n")
        .strip()
    )[:limit]


def build_runtime_action_event_display_fields(
    runtime_action: str,
    payload: str = "",
) -> dict:

    return {
        "display_name": get_runtime_action_display_name(
            runtime_action
        ),
        "close_tag": runtime_action_has_close_tag(
            runtime_action
        ),
        "text": build_runtime_action_display_text(
            runtime_action,
            payload,
        ),
    }


def parse_asset_action_payload(
        payload_text: str,
) -> dict:

    try:
        payload = json.loads(
            str(
                payload_text
                or ""
            ).strip()
        )
    except json.JSONDecodeError:
        payload = _parse_lenient_asset_payload(
            payload_text
        )

    if not isinstance(
        payload,
        dict,
    ):
        return {}

    return deepcopy(
        payload
    )


def build_pending_asset_action_preview(
        payload_text: str,
) -> dict:

    payload = parse_asset_action_payload(
        payload_text
    )

    if not payload:
        return {
            "action": "asset_action",
            "error": "invalid_payload",
        }

    action = str(
        payload.get(
            "action",
            "asset_action",
        )
        or "asset_action"
    ).strip()

    result = {
        "action": action,
    }

    if action in {
        "create_asset_file",
        "append_asset_file",
    }:
        path = str(
            payload.get(
                "path",
                "",
            )
            or ""
        ).strip().replace(
            "\\",
            "/",
        )
        if path:
            if not path.startswith("assets/"):
                path = f"assets/{path}"
            result["path"] = path

    if action in {
        "create_wildcard_file",
        "append_wildcard_file",
    }:
        path = str(
            payload.get(
                "path",
                "",
            )
            or ""
        ).strip().replace(
            "\\",
            "/",
        )
        if path:
            if not path.startswith("assets/wildcards/"):
                path = f"assets/wildcards/{path}"
            if not path.casefold().endswith(".txt"):
                path = f"{path}.txt"
            result["path"] = path

    if action == "generate_prompt_batch":
        path = str(
            payload.get(
                "path",
                "",
            )
            or payload.get(
                "output_file",
                "",
            )
            or ""
        ).strip().replace(
            "\\",
            "/",
        )
        if path:
            if not path.startswith("assets/"):
                path = f"assets/{path}"
            result["path"] = path

    if action == "run_document_reader":
        attachment = str(
            payload.get(
                "attachment",
                "",
            )
            or ""
        ).strip()
        raw_modes = payload.get(
            "modes"
        )
        modes = (
            [
                str(mode).strip()
                for mode in raw_modes
                if str(mode).strip()
            ]
            if isinstance(raw_modes, list)
            else []
        )
        mode = str(
            payload.get(
                "mode",
                "plain-mode.md",
            )
            or "plain-mode.md"
        ).strip()
        if attachment:
            result["path"] = attachment
        if modes:
            result["modes"] = modes
        else:
            result["mode"] = mode

    if action == "run_python_skill":
        skill = str(
            payload.get(
                "skill",
                "",
            )
            or ""
        ).strip()
        script = str(
            payload.get(
                "script",
                "",
            )
            or ""
        ).strip()
        if skill and script:
            result["path"] = f"{skill}/{script}"

    return result


def preserve_failed_asset_action_for_retry(
        context,
        result: dict,
        payload_text: str,
) -> None:

    if (
        not isinstance(
            result,
            dict,
        )
        or result.get("ok") is not False
    ):
        return

    payload = parse_asset_action_payload(
        payload_text
    )

    if payload:
        result["payload"] = payload

    if (
        result.get("error") != "file_exists"
        or not payload
    ):
        return

    context.runtime_asset_retry_results = [
        deepcopy(result)
    ]


def append_asset_runtime_result(
    context,
    result: dict,
) -> None:

    asset_results = getattr(
        context,
        "runtime_asset_results",
        None,
    )

    if not isinstance(
        asset_results,
        list,
    ):
        asset_results = []
        setattr(
            context,
            "runtime_asset_results",
            asset_results,
        )

    if isinstance(
        result,
        dict,
    ):
        runtime_turn_id = str(
            getattr(
                context,
                "runtime_current_turn_id",
                "",
            )
            or ""
        ).strip()
        if runtime_turn_id and not result.get(
            "runtime_turn_id"
        ):
            result["runtime_turn_id"] = runtime_turn_id

    asset_results.append(
        result
    )
    record_runtime_tool_result(
        context,
        TOOL_RESULT_KIND_ASSET,
        result,
    )


def append_delayed_memory_runtime_result(
    context,
    result: dict,
) -> None:

    delayed_memory_results = getattr(
        context,
        "runtime_delayed_memory_results",
        None,
    )

    if not isinstance(
        delayed_memory_results,
        list,
    ):
        delayed_memory_results = []
        setattr(
            context,
            "runtime_delayed_memory_results",
            delayed_memory_results,
        )

    if isinstance(
        result,
        dict,
    ):
        runtime_turn_id = str(
            getattr(
                context,
                "runtime_current_turn_id",
                "",
            )
            or ""
        ).strip()
        if runtime_turn_id and not result.get(
            "runtime_turn_id"
        ):
            result["runtime_turn_id"] = runtime_turn_id

    recorded_result = record_runtime_tool_result(
        context,
        TOOL_RESULT_KIND_DELAYED_MEMORY,
        result,
    )
    if not recorded_result:
        return

    delayed_memory_results.append(
        result
    )


def clear_delayed_memory_runtime_results(
    context,
) -> None:

    delayed_memory_results = getattr(
        context,
        "runtime_delayed_memory_results",
        None,
    )

    if isinstance(
        delayed_memory_results,
        list,
    ):
        delayed_memory_results.clear()
        return

    setattr(
        context,
        "runtime_delayed_memory_results",
        [],
    )


def get_appended_delayed_memory_report(
    context,
) -> dict:

    appended_report = getattr(
        context,
        "runtime_appended_delayed_memory",
        None,
    )

    if not isinstance(
        appended_report,
        dict,
    ):
        appended_report = {}
        setattr(
            context,
            "runtime_appended_delayed_memory",
            appended_report,
        )

    return appended_report


def set_appended_delayed_memory_report(
    context,
    result: dict,
) -> bool:

    if (
        not isinstance(
            result,
            dict,
        )
        or result.get("ok") is False
    ):
        return False

    report = result.get(
        "report",
    )

    if not isinstance(
        report,
        dict,
    ):
        return False

    report_id = str(
        result.get(
            "id",
            "",
        )
        or report.get(
            "id",
            "",
        )
        or ""
    ).strip().casefold()

    if not report_id:
        return False

    current_report = get_appended_delayed_memory_report(
        context
    )
    current_id = str(
        current_report.get(
            "id",
            "",
        )
        or ""
    ).strip().casefold()

    if current_id == report_id:
        return False

    setattr(
        context,
        "runtime_appended_delayed_memory",
        {
            **report,
            "id": report_id,
        },
    )
    return True


def clear_appended_delayed_memory_report(
    context,
    report_id: str = "",
) -> bool:

    current_report = get_appended_delayed_memory_report(
        context
    )

    if not current_report:
        return False

    normalized_report_id = str(
        report_id
        or ""
    ).strip().casefold()

    current_id = str(
        current_report.get(
            "id",
            "",
        )
        or ""
    ).strip().casefold()

    if (
        normalized_report_id
        and current_id
        and normalized_report_id != current_id
    ):
        return False

    setattr(
        context,
        "runtime_appended_delayed_memory",
        {},
    )
    return True


def get_delayed_memory_reports(
    context,
) -> dict:

    delayed_memory_reports = getattr(
        context,
        "delayed_memory_reports",
        None,
    )

    if not isinstance(
        delayed_memory_reports,
        dict,
    ):
        delayed_memory_reports = {}
        setattr(
            context,
            "delayed_memory_reports",
            delayed_memory_reports,
        )

    return delayed_memory_reports


def normalize_delayed_memory_action_id(
    payload: str,
) -> str:

    report_id = str(
        payload
        or ""
    ).strip().casefold()

    if is_delayed_memory_report_id(
        report_id
    ):
        return report_id

    return ""


def build_delayed_memory_failure_result(
    *,
    action: str,
    requested: str,
    error: str,
) -> dict:

    return {
        "ok": False,
        "action": action,
        "requested": str(
            requested
            or ""
        ).strip(),
        "error": error,
        "failure": NO_ENTRIES_FOUND_MESSAGE,
    }


def list_delayed_memory_reports(
    context,
) -> dict:

    reports = get_delayed_memory_reports(
        context
    )

    return {
        "ok": True,
        "action": "list_delayed_memory",
        "reports": [
            {
                "id": report_id,
                "title": str(
                    report.get(
                        "title",
                        "",
                    )
                    or ""
                ).strip(),
            }
            for report_id, report in reports.items()
            if isinstance(
                report,
                dict,
            )
        ],
    }


def append_delayed_memory_report(
    context,
    payload: str,
) -> dict:

    report_id = normalize_delayed_memory_action_id(
        payload
    )
    reports = get_delayed_memory_reports(
        context
    )
    report = reports.get(
        report_id,
    )

    if not report_id or not isinstance(
        report,
        dict,
    ):
        return build_delayed_memory_failure_result(
            action="append_delayed_memory",
            requested=report_id
            or payload,
            error=(
                "invalid_delayed_memory_id"
                if not report_id
                else "delayed_memory_not_found"
            ),
        )

    updated_report = update_delayed_memory_append_metadata(
        context,
        report,
    )
    reports[report_id] = updated_report
    record_appended_delayed_memory_id(
        context,
        report_id,
    )

    return {
        "ok": True,
        "action": "append_delayed_memory",
        "id": report_id,
        "title": str(
            updated_report.get(
                "title",
                "",
            )
            or ""
        ).strip(),
        "report": {
            **updated_report,
            "id": report_id,
        },
    }


def remove_delayed_memory_report(
    context,
    payload: str,
) -> dict:

    report_id = normalize_delayed_memory_action_id(
        payload
    )

    if not report_id:
        return build_delayed_memory_failure_result(
            action="remove_delayed_memory",
            requested=payload,
            error="invalid_delayed_memory_id",
        )

    reports = get_delayed_memory_reports(
        context
    )
    report = (
        reports.get(
            report_id,
        )
        if report_id
        else None
    )

    if not isinstance(
        report,
        dict,
    ):
        return build_delayed_memory_failure_result(
            action="remove_delayed_memory",
            requested=report_id,
            error="delayed_memory_not_found",
        )

    return {
        "ok": True,
        "action": "remove_delayed_memory",
        "id": report_id,
        "detached": bool(
            report_id
        ),
        "title": (
            str(
                report.get(
                    "title",
                    "",
                )
                or ""
            ).strip()
            if isinstance(
                report,
                dict,
            )
            else ""
        ),
    }


def build_delayed_memory_action_text(
    result: dict,
) -> str:

    if not isinstance(
        result,
        dict,
    ):
        return "Delayed memory updated"

    action = str(
        result.get(
            "action",
            "",
        )
        or ""
    )

    if action == "list_delayed_memory":
        return "Listing delayed memory"

    title = str(
        result.get(
            "title",
            "",
        )
        or ""
    ).strip()

    report = result.get(
        "report",
    )

    if (
        not title
        and isinstance(
            report,
            dict,
        )
    ):
        title = str(
            report.get(
                "title",
                "",
            )
            or ""
        ).strip()

    if not title:
        title = str(
            result.get(
                "id",
                "",
            )
            or result.get(
                "requested",
                "",
            )
            or "unknown"
        ).strip()

    if action == "append_delayed_memory":
        return f"Appending: {title}"

    if action == "remove_delayed_memory":
        return f"Removing: {title}"

    return "Delayed memory updated"


def build_delayed_memory_history_text(
    result: dict,
) -> str:

    if not isinstance(
        result,
        dict,
    ):
        return ""

    if result.get("ok") is False:
        return ""

    action = str(
        result.get(
            "action",
            "",
        )
        or ""
    )

    title = str(
        result.get(
            "title",
            "",
        )
        or ""
    ).strip()

    report = result.get(
        "report",
    )

    if (
        not title
        and isinstance(
            report,
            dict,
        )
    ):
        title = str(
            report.get(
                "title",
                "",
            )
            or ""
        ).strip()

    if not title:
        title = str(
            result.get(
                "id",
                "",
            )
            or result.get(
                "requested",
                "",
            )
            or ""
        ).strip()

    if not title:
        return ""

    if action == "save_delayed_memory_content":
        return f"Delayed memory saved: {title}"

    if action == "append_delayed_memory":
        return f"Delayed memory appended: {title}"

    if action == "remove_delayed_memory":
        return f"Delayed memory removed from context: {title}"

    return ""


async def log_runtime_action_marker_removals(
    context,
    result,
    *,
    source: str = "brain content",
) -> None:

    removed_markers = tuple(
        getattr(
            result,
            "removed_markers",
            (),
        )
        or ()
    )

    if not removed_markers:
        return

    logger = getattr(
        context,
        "logger",
        None,
    )

    if logger is None:
        return

    log_validator = getattr(
        logger,
        "log_validator",
        None,
    )
    log_runtime = getattr(
        logger,
        "log_runtime",
        None,
    )

    for marker in removed_markers:
        preview = build_runtime_action_marker_preview(
            marker
        )

        message = (
            "Runtime action marker stripped.\n"
            f"Source: {source}\n"
            "Payload available."
        )

        if log_validator is not None:
            await log_validator(
                message,
                details=marker,
            )
            continue

        if log_runtime is not None:
            await log_runtime(
                message
            )


def _track_background_task(
    context,
    task: asyncio.Task,
) -> None:

    tasks = getattr(
        context,
        "background_tasks",
        None,
    )

    if not isinstance(tasks, set):
        tasks = set()
        setattr(
            context,
            "background_tasks",
            tasks,
        )

    tasks.add(task)
    task.add_done_callback(
        tasks.discard
    )


async def _enqueue_idle_followup_after_delay(
    context,
    record: dict,
) -> None:

    seconds = max(
        0,
        int(record.get("seconds", 0) or 0),
    )

    await asyncio.sleep(seconds)

    scheduled_generation = int(
        record.get(
            "tool_results_generation",
            0,
        )
        or 0
    )
    current_generation = int(
        getattr(
            context,
            "runtime_tool_results_generation",
            0,
        )
        or 0
    )
    context_snapshot = deepcopy(
        record.get(
            "context_snapshot",
            {},
        )
    )
    if not isinstance(
        context_snapshot,
        dict,
    ):
        context_snapshot = {}

    if scheduled_generation != current_generation:
        context_snapshot["system_prompt"] = (
            strip_tools_results_context(
                context_snapshot.get(
                    "system_prompt",
                    "",
                )
            )
        )

    record = {
        **record,
        "context_snapshot": context_snapshot,
        "tool_results_generation": current_generation,
        "fired_at": time.time(),
    }
    queue = getattr(
        context,
        "runtime_pending_requests_queue",
        None,
    )

    if queue is not None:
        await queue.put({
            "type": "idle_followup",
            "idle_followup": record,
        })
        return

    pending = getattr(
        context,
        "runtime_pending_idle_followups",
        None,
    )
    if not isinstance(pending, list):
        pending = []
        setattr(
            context,
            "runtime_pending_idle_followups",
            pending,
        )

    pending.append(record)


def schedule_idle_followup(
    context,
    *,
    seconds: int,
    source_message: str,
    user_message: str,
    context_snapshot: dict | None,
) -> dict:

    sequence = int(
        getattr(
            context,
            "runtime_idle_action_sequence",
            0,
        )
        or 0
    ) + 1
    context.runtime_idle_action_sequence = sequence

    scheduled_at = time.time()
    sequence_turn_id = str(
        getattr(
            context,
            "runtime_current_sequence_turn_id",
            "",
        )
        or getattr(
            context,
            "runtime_current_turn_id",
            "",
        )
        or ""
    ).strip()
    sequence_started_at = getattr(
        context,
        "runtime_current_sequence_started_at",
        None,
    )
    if not isinstance(
        sequence_started_at,
        (int, float),
    ) or sequence_started_at <= 0:
        sequence_started_at = getattr(
            context,
            "runtime_turn_started_at",
            scheduled_at,
        )
    if not isinstance(
        sequence_started_at,
        (int, float),
    ) or sequence_started_at <= 0:
        sequence_started_at = scheduled_at
    current_attachments = getattr(
        context,
        "runtime_turn_attachments",
        [],
    )
    sequence_attachment_turn_id = str(
        getattr(
            context,
            "runtime_current_sequence_attachments_turn_id",
            "",
        )
        or ""
    ).strip()
    sequence_attachments = getattr(
        context,
        "runtime_current_sequence_attachments",
        [],
    )
    if (
        not current_attachments
        and sequence_attachment_turn_id == sequence_turn_id
    ):
        current_attachments = sequence_attachments

    record = {
        "id": build_runtime_action_id(
            RUNTIME_ACTION_IDLE,
            sequence,
        ),
        "action": "idle",
        "seconds": seconds,
        "scheduled_at": scheduled_at,
        "due_at": scheduled_at + seconds,
        "source_message": str(source_message or ""),
        "origin_user_request": str(user_message or ""),
        "sequence_turn_id": sequence_turn_id,
        "sequence_started_at": float(sequence_started_at),
        "context_snapshot": deepcopy(context_snapshot)
        if isinstance(context_snapshot, dict)
        else {},
        "tool_results_generation": int(
            getattr(
                context,
                "runtime_tool_results_generation",
                0,
            )
            or 0
        ),
        "attachments": deepcopy(
            current_attachments
            or []
        ),
    }

    task = asyncio.create_task(
        _enqueue_idle_followup_after_delay(
            context,
            record,
        )
    )
    _track_background_task(
        context,
        task,
    )

    return record


async def apply_runtime_action_calls(
    context,
    actions,
    user_message: str | None = None,
    context_snapshot: dict | None = None,
    assistant_message: str | None = None,
    confirmed_action_ids=None,
    rejected_action_ids=None,
    guard_confirmation_ids=None,
    action_display_ids=None,
    runtime_message_id: str = "",
) -> int:
    from utils.actions.dispatcher import (
        apply_runtime_action_calls as _apply_runtime_action_calls,
    )

    return await _apply_runtime_action_calls(
        context,
        actions,
        user_message=user_message,
        context_snapshot=context_snapshot,
        assistant_message=assistant_message,
        confirmed_action_ids=confirmed_action_ids,
        rejected_action_ids=rejected_action_ids,
        guard_confirmation_ids=guard_confirmation_ids,
        action_display_ids=action_display_ids,
        runtime_message_id=runtime_message_id,
    )


def indent_xml(
    value: str,
    *,
    spaces: int = 8,
) -> str:

    prefix = " " * spaces
    lines = (
        value
        or ""
    ).strip().splitlines()

    return "\n".join(
        f"{prefix}{line}"
        for line in lines
    )


def strip_empty_results_xml(
    value: str,
) -> str:

    source = (
        value
        or ""
    ).strip()

    if not source:
        return ""

    try:
        root = ElementTree.fromstring(
            source
        )

    except ElementTree.ParseError:
        return source

    def prune_empty_results(
        element,
    ) -> None:

        for child in list(
            element
        ):
            prune_empty_results(
                child
            )

            if child.tag != "RESULTS":
                continue

            if list(
                child
            ):
                continue

            if (
                child.text
                and child.text.strip()
            ):
                continue

            element.remove(
                child
            )

    prune_empty_results(
        root
    )

    return ElementTree.tostring(
        root,
        encoding="unicode",
        short_empty_elements=False,
    )


def get_conversation_activity_diff(
    context=None,
) -> float | None:

    if context is None:
        return None

    recorded_diff = getattr(
        context,
        "runtime_conversation_activity_diff",
        None,
    )

    if recorded_diff is not None:
        try:
            return float(
                recorded_diff
            )
        except (
            TypeError,
            ValueError,
        ):
            pass

    patch_sources = (
        getattr(
            context,
            "runtime_l2_pending_patches",
            None,
        )
        or getattr(
            context,
            "runtime_memory_snapshots",
            None,
        )
        or []
    )

    for patch in reversed(
        patch_sources
    ):

        if not isinstance(
            patch,
            dict,
        ):
            continue

        total_diff = patch.get(
            "total_diff",
        )

        if total_diff is None:
            continue

        try:
            return float(
                total_diff
            )
        except (
            TypeError,
            ValueError,
        ):
            continue

    return None


def get_conversation_activity_percent(
    diff: float,
) -> int:

    return max(
        0,
        min(
            100,
            int(
                round(
                    diff
                )
            ),
        ),
    )


def has_zero_diff_stall_alert(
    context=None,
) -> bool:

    if context is None:
        return False

    return bool(
        getattr(
            context,
            "runtime_zero_diff_alert",
            None,
        )
    )



