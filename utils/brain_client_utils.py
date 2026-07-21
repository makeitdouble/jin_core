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
    RUNTIME_ACTION_CREATE_ACTIVE_MEMORY,
    RUNTIME_ACTION_LIST_DELAYED_MEMORY,
    RUNTIME_ACTION_LIST_SKILLS,
    RUNTIME_ACTION_HIDE_SKILLS,
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
)
from rules.runtime import (
    ACTION_REJECTED_MISSING_TRIGGER_WORDS_MESSAGE,
    NO_ENTRIES_FOUND_MESSAGE,
)
from utils.assets_service import (
    ensure_assets_tree,
    list_skills,
    load_skill,
    normalize_skill_name,
    _parse_lenient_asset_payload,
    run_asset_action,
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
    get_create_active_memory_marker_fields,
    is_delayed_memory_report_id,
    is_active_memory_record_paused,
    get_applied_jin_color,
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
    from utils.context.runtime_state import (
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

    marker_fields = get_create_active_memory_marker_fields()

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
            get_create_active_memory_marker_fields()
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


async def create_active_memory_runtime_record(
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
            getattr(
                context,
                "runtime_turn_attachments",
                [],
            )
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
) -> int:

    if (
        context is None
        or not actions
    ):
        return 0

    if not hasattr(
        context,
        "runtime_action_events",
    ):
        context.runtime_action_events = []

    if not hasattr(
        context,
        "runtime_search_calls",
    ):
        context.runtime_search_calls = []

    if not hasattr(
        context,
        "runtime_appended_skills",
    ):
        context.runtime_appended_skills = []

    if not hasattr(
        context,
        "runtime_visible_skills_result",
    ):
        context.runtime_visible_skills_result = {}

    action_context_snapshot = (
        dict(context_snapshot)
        if isinstance(context_snapshot, dict)
        else None
    )
    confirmed_action_ids = {
        int(action_id)
        for action_id in (confirmed_action_ids or ())
        if isinstance(
            action_id,
            int,
        )
    }
    rejected_action_ids = {
        int(action_id)
        for action_id in (rejected_action_ids or ())
        if isinstance(
            action_id,
            int,
        )
    }
    guard_confirmation_ids = (
        dict(guard_confirmation_ids)
        if isinstance(
            guard_confirmation_ids,
            dict,
        )
        else {}
    )
    action_display_ids = (
        dict(action_display_ids)
        if isinstance(
            action_display_ids,
            dict,
        )
        else {}
    )

    def with_action_context(payload: dict) -> dict:
        if not action_context_snapshot:
            return payload

        return {
            **payload,
            "context": action_context_snapshot,
        }

    ensure_assets_tree()

    search_action_count = sum(
        1
        for event in context.runtime_action_events
        if event.get("name") == "web_search"
    )

    accepted_action_names = set()

    search_calls = []
    filtered_actions = []
    rejected_action_events = {}
    rejected_active_memory_results = []
    search_query_seen = False
    save_session_seen = bool(
        getattr(
            context,
            "runtime_save_session_requested",
            False,
        )
    )
    save_session_action_emitted = bool(
        getattr(
            context,
            "runtime_save_session_action_emitted",
            False,
        )
    )
    resolve_active_memory_ids_seen = set()
    resolve_active_memory_failures_seen = set()
    save_delayed_memory_seen = False
    list_delayed_memory_seen = False
    list_skills_seen = False
    hide_skills_seen = False
    clean_tool_results_seen = False
    resolved_user_message = resolve_runtime_action_user_message(
        context,
        user_message,
    )
    skill_state_action_names = {
        RUNTIME_ACTION_APPEND_SKILL,
        RUNTIME_ACTION_REMOVE_SKILL,
    }
    skill_workflow_action_names = {
        *skill_state_action_names,
        RUNTIME_ACTION_LIST_SKILLS,
        RUNTIME_ACTION_HIDE_SKILLS,
        RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
        RUNTIME_ACTION_IDLE,
    }
    todo_action_names = {
        RUNTIME_ACTION_CREATE_TODO_LIST,
        RUNTIME_ACTION_RESOLVE_TODO,
        RUNTIME_ACTION_CHECK_TODO,
    }
    appended_skill_names = {
        normalize_skill_name(
            skill.get(
                "name",
                "",
            )
        )
        for skill in (
            getattr(
                context,
                "runtime_appended_skills",
                [],
            )
            or []
        )
        if isinstance(
            skill,
            dict,
        )
        and normalize_skill_name(
            skill.get(
                "name",
                "",
            )
        )
    }
    has_skill_state_action = any(
        action.name in skill_state_action_names
        for action in actions
    )
    current_jin_color = get_applied_jin_color(
        context
    )

    if (
        has_skill_state_action
        or getattr(
            context,
            "runtime_skill_state_barrier_active",
            False,
        )
    ):
        actions = [
            action
            for action in actions
            if action.name in skill_workflow_action_names
            or action.name in todo_action_names
        ]

    from runtime.behavior_contract import (
        get_action_guard_blocker_match,
        get_action_guard_name_for_runtime_action,
        should_pause_action_guard_for_confirmation,
    )

    for action in actions:

        jin_color = ""

        if action.name == RUNTIME_ACTION_JIN_COLOR:
            jin_color = normalize_jin_color_payload(
                action.payload
            )

            if (
                not jin_color
                or jin_color == current_jin_color
            ):
                continue

        action_event_name = action.name.lower()
        action_guard_confirmed = id(action) in confirmed_action_ids

        if id(action) in rejected_action_ids:
            rejected_action_events[id(action)] = {
                "status": "failed",
                "error": "user_rejected_runtime_action",
                "title": f"{action.name} cancelled",
                "confirmation_id": guard_confirmation_ids.get(
                    id(action),
                    "",
                ),
            }
            continue

        guard_name = get_action_guard_name_for_runtime_action(
            action.name
        )
        blocker_match = (
            get_action_guard_blocker_match(
                guard_name,
                resolved_user_message,
            )
            if guard_name
            else ""
        )

        if blocker_match:
            from utils.context.runtime_state import (
                format_runtime_blocked_trigger_word_message,
            )

            failure_followup_message = (
                format_runtime_blocked_trigger_word_message(
                    blocker_match
                )
            )
            rejected_action_events[id(action)] = {
                "status": "failed",
                "error": "behavior_contract_blocker_matched",
                "blocker": blocker_match,
                "failure_followup_message": failure_followup_message,
                "confirmation_id": guard_confirmation_ids.get(
                    id(action),
                    "",
                ),
            }
            continue

        if (
            guard_name
            and not action_guard_confirmed
            and should_pause_action_guard_for_confirmation(
                guard_name,
                resolved_user_message,
            )
        ):
            rejection_event = {
                "status": "failed",
                "error": "user_did_not_confirm_runtime_action",
                "failure_followup_message": (
                    build_action_missing_trigger_words_message(
                        action.name,
                        ACTION_REJECTED_MISSING_TRIGGER_WORDS_MESSAGE,
                    )
                ),
                "confirmation_id": guard_confirmation_ids.get(
                    id(action),
                    "",
                ),
            }

            if action.name == RUNTIME_ACTION_SAVE_SESSION:
                rejection_event["error"] = (
                    "user_did_not_explicitly_request_session_save"
                )

            elif (
                action.name
                == RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT
            ):
                rejected_report = build_delayed_memory_report(
                    context,
                    action.payload,
                )
                rejected_title = ""

                for report_value in rejected_report.values():
                    if isinstance(
                        report_value,
                        dict,
                    ):
                        rejected_title = str(
                            report_value.get(
                                "title",
                                "",
                            )
                            or ""
                        ).strip()

                    if rejected_title:
                        break

                context.runtime_delayed_memory_save_rejected_pending = True
                context.runtime_delayed_memory_save_rejected_title = (
                    rejected_title
                )
                rejection_event.update({
                    "error": (
                        "user_did_not_explicitly_request_report_save"
                    ),
                    "title": rejected_title,
                })
                save_delayed_memory_seen = True

            rejected_action_events[id(action)] = rejection_event
            continue

        if action.name == RUNTIME_ACTION_IDLE:
            seconds = parse_idle_seconds(
                action.payload
            )
            if seconds is None:
                continue

            # Every IDLE occurrence is an independent timer, including
            # repeated markers with the same payload in one model message.
            accepted_action_names.add(
                action_event_name
            )
            filtered_actions.append(
                action
            )
            continue

        if action.name == RUNTIME_ACTION_JIN_COLOR:
            current_jin_color = jin_color
            accepted_action_names.add(
                action_event_name
            )
            filtered_actions.append(
                action
            )
            continue

        if action.name == RUNTIME_ACTION_SAVE_SESSION:
            if getattr(
                context,
                "runtime_save_session_memory_committed_this_turn",
                False,
            ):
                # L3 already completed this turn. A SAVE_SESSION marker
                # repeated by the deferred follow-up must not start a second
                # memory pipeline.
                continue

            if save_session_seen:
                if not save_session_action_emitted:
                    save_session_action_emitted = True
                    accepted_action_names.add(
                        action_event_name
                    )
                    filtered_actions.append(
                        action
                    )

                continue

            save_session_seen = True
            save_session_action_emitted = True
            accepted_action_names.add(
                action_event_name
            )
            filtered_actions.append(
                action
            )
            continue

        if action.name == RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT:
            if save_delayed_memory_seen:
                continue

            if not build_delayed_memory_report(
                context,
                action.payload,
            ):
                continue

            save_delayed_memory_seen = True
            accepted_action_names.add(
                action_event_name
            )
            filtered_actions.append(
                action
            )
            continue

        if action.name == RUNTIME_ACTION_LIST_DELAYED_MEMORY:
            if list_delayed_memory_seen:
                continue

            list_delayed_memory_seen = True
            accepted_action_names.add(
                action_event_name
            )
            filtered_actions.append(
                action
            )
            continue

        if action.name == RUNTIME_ACTION_APPEND_DELAYED_MEMORY:
            accepted_action_names.add(
                action_event_name
            )
            filtered_actions.append(
                action
            )
            continue

        if action.name == RUNTIME_ACTION_REMOVE_DELAYED_MEMORY:
            accepted_action_names.add(
                action_event_name
            )
            filtered_actions.append(
                action
            )
            continue

        if action.name == RUNTIME_ACTION_CREATE_ACTIVE_MEMORY:
            active_memory_line = build_active_memory_runtime_line(
                action.payload,
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
                continue

            accepted_action_names.add(
                action_event_name
            )
            filtered_actions.append(
                action
            )
            continue

        if action.name == RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY:
            active_memory_id = extract_active_memory_resolve_slot_id(
                action.payload,
                existing_ids=collect_context_active_memory_slot_ids(
                    context
                ),
            )

            if not active_memory_id:
                failure_result = build_active_memory_resolve_failure_result(
                    context,
                    action.payload,
                )
                failure_key = str(
                    failure_result.get(
                        "id",
                        "",
                    )
                    or failure_result.get(
                        "requested",
                        "",
                    )
                    or "unknown"
                ).strip().casefold()

                if failure_key in resolve_active_memory_failures_seen:
                    continue

                resolve_active_memory_failures_seen.add(
                    failure_key
                )
                rejected_active_memory_results.append(
                    failure_result
                )
                rejected_action_events[id(action)] = {
                    "status": "failed",
                    "error": failure_result["error"],
                    "id": failure_result.get(
                        "id",
                        "",
                    ),
                    "requested": failure_result.get(
                        "requested",
                        "",
                    ),
                }
                continue

            if active_memory_id in resolve_active_memory_ids_seen:
                continue

            resolve_active_memory_ids_seen.add(
                active_memory_id
            )
            accepted_action_names.add(
                action_event_name
            )
            filtered_actions.append(
                action
            )
            continue

        if action.name in todo_action_names:
            accepted_action_names.add(
                action_event_name
            )
            filtered_actions.append(
                action
            )
            continue

        if action.name == RUNTIME_ACTION_WEB_SEARCH:
            query = extract_search_query(
                action.payload
            )

            if (
                not query
                or search_query_seen
                or getattr(
                    context,
                    "runtime_search_queries",
                    [],
                )
            ):
                continue

            search_query_seen = True

        if action.name == RUNTIME_ACTION_LIST_SKILLS:
            if list_skills_seen:
                continue

            list_skills_seen = True

        if action.name == RUNTIME_ACTION_HIDE_SKILLS:
            if hide_skills_seen:
                continue

            hide_skills_seen = True

        if action.name == RUNTIME_ACTION_CLEAN_TOOL_RESULTS:
            if clean_tool_results_seen:
                continue

            clean_tool_results_seen = True

        if action.name == RUNTIME_ACTION_APPEND_SKILL:
            requested_skill = normalize_skill_name(
                action.payload
            )
            if not requested_skill:
                continue

            if requested_skill in appended_skill_names:
                continue

            appended_skill_names.add(
                requested_skill
            )

        if action.name == RUNTIME_ACTION_REMOVE_SKILL:
            requested_skill = normalize_skill_name(
                action.payload
            )
            if not requested_skill:
                continue

            appended_skill_names.discard(
                requested_skill
            )

        accepted_action_names.add(
            action_event_name
        )
        filtered_actions.append(
            action
        )

    if (
        not filtered_actions
        and not rejected_action_events
    ):
        return 0

    runtime_todo_results = []
    runtime_todo_action_items = {}

    for action in filtered_actions:
        if action.name == RUNTIME_ACTION_CREATE_TODO_LIST:
            result = create_runtime_todo(
                context,
                action.payload,
            )
            runtime_todo_results.append(
                result
            )
            continue

        if action.name == RUNTIME_ACTION_RESOLVE_TODO:
            result = resolve_runtime_todo_item(
                context,
                parse_runtime_todo_item_id(
                    action.payload
                ),
            )
            runtime_todo_results.append(
                result
            )
            continue

        if action.name == RUNTIME_ACTION_CHECK_TODO:
            result = check_runtime_todo_item(
                context,
                parse_runtime_todo_item_id(
                    action.payload
                ),
            )
            runtime_todo_results.append(
                result
            )
            continue

        if has_active_runtime_todo(
            context
        ):
            todo_item = mark_next_runtime_todo_item_resolved(
                context
            )
            if todo_item is not None:
                runtime_todo_action_items[action] = dict(
                    todo_item
                )

    accepted_action_ids = {
        id(action)
        for action in filtered_actions
    }

    for action in actions:

        rejected_event = rejected_action_events.get(
            id(action)
        )

        if (
            id(action) not in accepted_action_ids
            and rejected_event is None
        ):
            continue

        action_event = {
            "name": action.name.lower(),
        }
        action_display_id = str(
            action_display_ids.get(
                id(action),
                "",
            )
            or ""
        ).strip()
        if action_display_id:
            action_event["id"] = action_display_id
        runtime_turn_id = str(
            getattr(
                context,
                "runtime_current_turn_id",
                "",
            )
            or ""
        ).strip()
        if runtime_turn_id:
            action_event["runtime_turn_id"] = runtime_turn_id

        query = ""

        if action.name == RUNTIME_ACTION_WEB_SEARCH:
            query = extract_search_query(
                action.payload
            )

        if action.name == RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY:
            active_memory_id = extract_active_memory_resolve_slot_id(
                action.payload,
                existing_ids=collect_context_active_memory_slot_ids(
                    context
                ),
            )
            if active_memory_id:
                action_event["id"] = active_memory_id

        if query:
            search_action_count += 1
            tool_call_id = build_runtime_action_id(
                action.name,
                search_action_count,
            )
            action_event["id"] = tool_call_id
            action_event["query"] = query
            search_calls.append({
                "id": tool_call_id,
                "query": query,
                "context": action_context_snapshot,
            })

        elif action.name == RUNTIME_ACTION_IDLE:
            idle_seconds = parse_idle_seconds(
                action.payload
            )
            if idle_seconds is not None:
                action_event["seconds"] = idle_seconds
                action_event["payload"] = f"{idle_seconds}s"
                action_event["deferred_follow_up"] = True

        elif action.name == RUNTIME_ACTION_JIN_COLOR:
            color = normalize_jin_color_payload(
                action.payload
            )
            if color:
                action_event["color"] = color
                action_event["payload"] = color

        elif action.payload:
            action_event_payload = action.payload

            if action.name == RUNTIME_ACTION_CREATE_ACTIVE_MEMORY:
                action_event_payload = (
                    normalize_active_memory_runtime_payload(
                        action.payload
                    )
                )

            if action_event_payload:
                action_event["payload"] = (
                    action_event_payload
                )

        if rejected_event is not None:
            action_event.update({
                key: value
                for key, value in rejected_event.items()
                if value
            })
            failure_followup_message = str(
                rejected_event.get(
                    "failure_followup_message",
                    "",
                )
                or ""
            ).strip()
            if failure_followup_message:
                messages = getattr(
                    context,
                    "runtime_action_failure_followup_messages",
                    None,
                )
                if not isinstance(
                    messages,
                    list,
                ):
                    messages = []
                    context.runtime_action_failure_followup_messages = (
                        messages
                    )
                messages.append(
                    failure_followup_message
                )

        context.runtime_action_events.append(
            action_event
        )

    if rejected_action_events:
        emitter = getattr(
            context,
            "emitter",
            None,
        )
        emit = getattr(
            emitter,
            "emit",
            None,
        )

        if emit is not None:
            for action in actions:
                rejected_event = rejected_action_events.get(
                    id(action)
                )
                if rejected_event is None:
                    continue
                if (
                    not rejected_event.get("confirmation_id")
                    and not rejected_event.get(
                        "failure_followup_message"
                    )
                    and rejected_event.get("error")
                    != "behavior_contract_blocker_matched"
                ):
                    continue

                payload = {
                    "type": "runtime_action",
                    "action": action.name.lower(),
                    "status": "failed",
                    "text": (
                        rejected_event.get("title")
                        or rejected_event.get("error")
                        or f"{action.name} blocked"
                    ),
                    "detail": rejected_event.get(
                        "failure_followup_message",
                        "",
                    ),
                }
                action_display_id = str(
                    action_display_ids.get(
                        id(action),
                        "",
                    )
                    or ""
                ).strip()
                if action_display_id:
                    payload["id"] = action_display_id

                if action.name == RUNTIME_ACTION_JIN_COLOR:
                    color = normalize_jin_color_payload(
                        action.payload
                    )
                    if color:
                        payload["color"] = color
                        payload["payload"] = color
                confirmation_id = str(
                    rejected_event.get(
                        "confirmation_id",
                        "",
                    )
                    or ""
                ).strip()
                if confirmation_id:
                    payload["confirmation_id"] = confirmation_id

                await emit(with_action_context(payload))

    if (
        not filtered_actions
        and not rejected_active_memory_results
        and not rejected_action_events
    ):
        return 0

    save_session_count = sum(
        1
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_SAVE_SESSION
    )

    create_active_memory_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_CREATE_ACTIVE_MEMORY
    ]
    create_active_memory_count = len(
        create_active_memory_actions
    )

    resolve_active_memory_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY
    ]
    resolve_active_memory_count = len(
        resolve_active_memory_actions
    )

    save_delayed_memory_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT
    ]

    list_delayed_memory_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_LIST_DELAYED_MEMORY
    ]

    append_delayed_memory_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_APPEND_DELAYED_MEMORY
    ]

    remove_delayed_memory_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_REMOVE_DELAYED_MEMORY
    ]

    list_skill_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_LIST_SKILLS
    ]

    hide_skill_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_HIDE_SKILLS
    ]

    clean_tool_result_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_CLEAN_TOOL_RESULTS
    ]

    idle_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_IDLE
    ]

    jin_color_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_JIN_COLOR
    ]

    append_skill_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_APPEND_SKILL
    ]

    remove_skill_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_REMOVE_SKILL
    ]

    asset_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_ASSET_ACTION
    ]

    search_queries = [
        query
        for query in (
            extract_search_query(
                action.payload
            )
            for action in filtered_actions
            if action.name == RUNTIME_ACTION_WEB_SEARCH
        )
        if query
    ]

    if search_queries:
        if not hasattr(
            context,
            "runtime_search_queries",
        ):
            context.runtime_search_queries = []

        context.runtime_search_queries.extend(
            search_queries
        )

        context.runtime_search_calls.extend(
            search_calls
        )

    logger = getattr(
        context,
        "logger",
        None,
    )
    log_runtime = getattr(
        logger,
        "log_runtime",
        None,
    )

    idle_records = []

    for action in idle_actions:
        seconds = parse_idle_seconds(
            action.payload
        )
        if seconds is None:
            continue

        idle_record = schedule_idle_followup(
            context,
            seconds=seconds,
            source_message=str(assistant_message or ""),
            user_message=resolved_user_message,
            context_snapshot=action_context_snapshot,
        )
        idle_records.append(idle_record)

        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] "
                f"idle scheduled for {seconds}s "
                f"id={idle_record['id']!r}"
            )

    if idle_records:
        emitter = getattr(
            context,
            "emitter",
            None,
        )
        emit = getattr(
            emitter,
            "emit",
            None,
        )

        if emit is not None:
            for idle_record in idle_records:
                idle_id = str(
                    idle_record.get(
                        "id",
                        "",
                    )
                    or ""
                )
                idle_payload = (
                    f"{int(idle_record.get('seconds', 0) or 0)}s"
                )
                await emit(with_action_context({
                    "type": "runtime_action",
                    "action": "idle",
                    "id": idle_id,
                    "status": "started",
                    "text": "IDLE",
                    "payload": idle_payload,
                    "detail": idle_payload,
                }))
                await emit(with_action_context({
                    "type": "runtime_action",
                    "action": "idle",
                    "id": idle_id,
                    "status": "completed",
                    "payload": idle_payload,
                    "detail": idle_payload,
                }))

    if jin_color_actions:
        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] "
                f"jin_color x{len(jin_color_actions)}"
            )

        emitter = getattr(
            context,
            "emitter",
            None,
        )
        emit = getattr(
            emitter,
            "emit",
            None,
        )

        if emit is not None:
            for action in jin_color_actions:
                color = normalize_jin_color_payload(
                    action.payload
                )
                if not color:
                    continue

                await emit(with_action_context({
                    "type": "runtime_action",
                    "action": "jin_color",
                    "id": str(
                        action_display_ids.get(
                            id(action),
                            "",
                        )
                        or ""
                    ).strip(),
                    "status": "completed",
                    "text": "JIN_COLOR",
                    "color": color,
                    "payload": color,
                }))

    if (
        log_runtime is not None
        and search_queries
    ):
        await log_runtime(
            "[RUNTIME ACTION] "
            f"search x{len(search_queries)}"
        )

    if runtime_todo_results:
        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] runtime_todo updated"
            )

        emitter = getattr(
            context,
            "emitter",
            None,
        )
        emit = getattr(
            emitter,
            "emit",
            None,
        )

        for result in runtime_todo_results:
            text = build_runtime_todo_history_text(
                result
            )
            record_session_action_history(
                context,
                text,
            )
            if emit is not None:
                await emit(with_action_context({
                    "type": "runtime_action",
                    "action": str(
                        result.get(
                            "action",
                            "runtime_todo",
                        )
                        or "runtime_todo"
                    ),
                    "status": "completed" if result.get("ok") else "blocked",
                    "text": text,
                    "runtime_todo_result": result,
                }))

    if clean_tool_result_actions:
        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] clean_tool_results requested"
            )

        clear_runtime_tool_results(
            context
        )

        emitter = getattr(
            context,
            "emitter",
            None,
        )
        emit = getattr(
            emitter,
            "emit",
            None,
        )

        if emit is not None:
            await emit(with_action_context({
                "type": "runtime_action",
                "action": "clean_tool_results",
                "status": "completed",
                "text": "Tool results cleared",
            }))

    if rejected_active_memory_results:
        emitter = getattr(
            context,
            "emitter",
            None,
        )
        emit = getattr(
            emitter,
            "emit",
            None,
        )

        for result in rejected_active_memory_results:
            queue_active_memory_resolve_failure(
                context,
                result,
            )

            if emit is None:
                continue

            await emit(with_action_context({
                "type": "runtime_action",
                "action": "resolve_active_memory",
                "id": result.get(
                    "id",
                    "",
                ),
                "status": "failed",
                "text": "Active memory resolve failed",
                "active_memory_result": result,
            }))

    saved_asset_results = []

    if list_skill_actions:
        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] list_skills requested"
            )

        for action in list_skill_actions:
            result = list_skills(
                action.payload
            )
            todo_item = apply_runtime_todo_action_result(
                context,
                runtime_todo_action_items.get(action),
                result,
            ) or runtime_todo_action_items.get(action)
            result = attach_runtime_todo_item_to_result(
                result,
                todo_item,
            )
            append_asset_runtime_result(
                context,
                result,
            )
            context.runtime_visible_skills_result = result
            saved_asset_results.append(
                result
            )

    hidden_skill_results = []

    if hide_skill_actions:
        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] hide_skills requested"
            )

        for action in hide_skill_actions:
            was_visible = bool(
                getattr(
                    context,
                    "runtime_visible_skills_result",
                    {},
                )
            )
            context.runtime_visible_skills_result = {}
            remove_runtime_tool_results(
                context,
                lambda entry: (
                    entry.get("kind") == TOOL_RESULT_KIND_ASSET
                    and isinstance(entry.get("result"), dict)
                    and entry["result"].get("action") == "list_skills"
                ),
            )

            for attribute_name in (
                "runtime_asset_results",
                "runtime_asset_retry_context",
                "runtime_asset_retry_results",
            ):
                results = getattr(
                    context,
                    attribute_name,
                    None,
                )
                if not isinstance(
                    results,
                    list,
                ):
                    continue

                results[:] = [
                    result
                    for result in results
                    if not (
                        isinstance(
                            result,
                            dict,
                        )
                        and result.get(
                            "action"
                        ) == "list_skills"
                    )
                ]

            result = {
                "ok": True,
                "action": "hide_skills",
                "hidden": was_visible,
            }
            todo_item = apply_runtime_todo_action_result(
                context,
                runtime_todo_action_items.get(action),
                result,
            ) or runtime_todo_action_items.get(action)
            result = attach_runtime_todo_item_to_result(
                result,
                todo_item,
            )
            hidden_skill_results.append(
                result
            )

    appended_skill_results = []

    if append_skill_actions:
        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] append_skill requested"
            )

        current_skills = list(
            getattr(
                context,
                "runtime_appended_skills",
                [],
            )
            or []
        )

        for action in append_skill_actions:
            result = load_skill(
                action.payload
            )
            skill = result.get(
                "skill",
            )

            if result.get("ok") and isinstance(skill, dict):
                skill_name = normalize_skill_name(
                    skill.get(
                        "name",
                        "",
                    )
                )
                current_skills = [
                    existing
                    for existing in current_skills
                    if normalize_skill_name(
                        existing.get(
                            "name",
                            "",
                        )
                    ) != skill_name
                ]
                current_skills.append(
                    skill
                )
                context.runtime_appended_skills = current_skills

            todo_item = apply_runtime_todo_action_result(
                context,
                runtime_todo_action_items.get(action),
                result,
            ) or runtime_todo_action_items.get(action)
            result = attach_runtime_todo_item_to_result(
                result,
                todo_item,
            )
            appended_skill_results.append(
                result
            )
            if (
                result.get("ok") is False
                and result.get("error") == "skill_not_found"
            ):
                append_asset_runtime_result(
                    context,
                    result,
                )

    removed_skill_results = []

    if remove_skill_actions:
        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] remove_skill requested"
            )

        current_skills = list(
            getattr(
                context,
                "runtime_appended_skills",
                [],
            )
            or []
        )

        for action in remove_skill_actions:
            requested = normalize_skill_name(
                action.payload
            )
            before_count = len(
                current_skills
            )
            current_skills = [
                skill
                for skill in current_skills
                if normalize_skill_name(
                    skill.get(
                        "name",
                        "",
                    )
                ) != requested
            ]
            context.runtime_appended_skills = current_skills
            removed_skill_results.append({
                "ok": True,
                "action": "remove_skill",
                "requested": requested,
                "removed": len(current_skills) < before_count,
            })

    if (
        appended_skill_results
        or removed_skill_results
    ):
        context.runtime_skill_state_barrier_active = True

    if asset_actions:
        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] asset_action requested"
            )

        for action in asset_actions:
            emitter = getattr(
                context,
                "emitter",
                None,
            )
            emit = getattr(
                emitter,
                "emit",
                None,
            )
            pending_result = build_pending_asset_action_preview(
                action.payload
            )
            pending_action = str(
                pending_result.get(
                    "action",
                    "asset_action",
                )
                or "asset_action"
            )
            pending_asset_action_ids = getattr(
                context,
                "runtime_pending_asset_action_ids",
                None,
            )
            pending_action_id = (
                pending_asset_action_ids.pop(0)
                if isinstance(
                    pending_asset_action_ids,
                    list,
                )
                and pending_asset_action_ids
                else build_runtime_action_id(
                    pending_action,
                    len(
                        getattr(
                            context,
                            "runtime_asset_results",
                            [],
                        )
                        or []
                    )
                    + 1,
                )
            )
            if emit is not None:
                await emit(with_action_context({
                    "type": "runtime_action",
                    "action": "asset_action",
                    "id": pending_action_id,
                    "status": "started",
                    "text": build_asset_action_history_text(
                        pending_result
                    ),
                }))

            result = run_asset_action(
                action.payload
            )
            result = normalize_file_exists_for_runtime_todo(
                result,
                context,
            )
            todo_item = apply_runtime_todo_action_result(
                context,
                runtime_todo_action_items.get(action),
                result,
            ) or runtime_todo_action_items.get(action)
            result = attach_runtime_todo_item_to_result(
                result,
                todo_item,
            )
            result["runtime_action_id"] = pending_action_id
            append_asset_runtime_result(
                context,
                result,
            )
            preserve_failed_asset_action_for_retry(
                context,
                result,
                action.payload,
            )
            saved_asset_results.append(
                result
            )

    delayed_memory_results = []

    if list_delayed_memory_actions:
        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] list_delayed_memory requested"
            )

        clear_delayed_memory_runtime_results(
            context
        )

        for action in list_delayed_memory_actions:
            result = list_delayed_memory_reports(
                context
            )
            append_delayed_memory_runtime_result(
                context,
                result,
            )
            delayed_memory_results.append(
                result
            )

    if append_delayed_memory_actions:
        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] append_delayed_memory requested"
            )

        clear_delayed_memory_runtime_results(
            context
        )

        for action in append_delayed_memory_actions:
            result = append_delayed_memory_report(
                context,
                action.payload,
            )
            did_append_delayed_memory = set_appended_delayed_memory_report(
                context,
                result,
            )
            if result.get("ok") is False:
                append_delayed_memory_runtime_result(
                    context,
                    result,
                )
            if did_append_delayed_memory:
                history_text = build_delayed_memory_history_text(
                    result
                )
                if history_text:
                    record_session_action_history(
                        context,
                        history_text,
                    )
            delayed_memory_results.append(
                result
            )

    if remove_delayed_memory_actions:
        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] remove_delayed_memory requested"
            )

        clear_delayed_memory_runtime_results(
            context
        )

        saved_reports_before_remove = deepcopy(
            get_delayed_memory_reports(
                context
            )
        )

        for action in remove_delayed_memory_actions:
            result = remove_delayed_memory_report(
                context,
                action.payload,
            )
            did_remove_delayed_memory = clear_appended_delayed_memory_report(
                context,
                result.get(
                    "id",
                    "",
                ),
            )
            result["detached"] = did_remove_delayed_memory
            if (
                result.get("ok") is not False
                and not did_remove_delayed_memory
            ):
                result = build_delayed_memory_failure_result(
                    action="remove_delayed_memory",
                    requested=result.get(
                        "id",
                        "",
                    ),
                    error="delayed_memory_not_appended",
                )
                result["detached"] = False
            append_delayed_memory_runtime_result(
                context,
                result,
            )
            if did_remove_delayed_memory:
                history_text = build_delayed_memory_history_text(
                    result
                )
                if history_text:
                    record_session_action_history(
                        context,
                        history_text,
                    )
            delayed_memory_results.append(
                result
            )

        if get_delayed_memory_reports(
            context
        ) != saved_reports_before_remove:
            setattr(
                context,
                "delayed_memory_reports",
                saved_reports_before_remove,
            )

    if delayed_memory_results:
        emitter = getattr(
            context,
            "emitter",
            None,
        )
        emit = getattr(
            emitter,
            "emit",
            None,
        )

        if emit is not None:
            first_delayed_result_index = max(
                len(
                    getattr(
                        context,
                        "runtime_delayed_memory_results",
                        [],
                    )
                )
                - len(
                    delayed_memory_results
                ),
                0,
            )

            for result_index, result in enumerate(
                delayed_memory_results,
                start=1,
            ):
                result_action = str(
                    result.get(
                        "action",
                        "delayed_memory",
                    )
                    or "delayed_memory"
                )
                action_id = build_runtime_action_id(
                    result_action,
                    first_delayed_result_index
                    + result_index,
                )
                await emit(with_action_context({
                    "type": "runtime_action",
                    "action": result_action,
                    "id": action_id,
                    "status": (
                        "completed"
                        if result.get("ok") is not False
                        else "failed"
                    ),
                    "text": build_delayed_memory_action_text(
                        result
                    ),
                    "delayed_memory_result": result,
                }))

    saved_asset_result_texts = [
        (
            result,
            build_asset_action_history_text(
                result
            ),
        )
        for result in saved_asset_results
    ]

    for _result, text in saved_asset_result_texts:
        record_session_action_history(
            context,
            text,
        )

    if saved_asset_result_texts:
        emitter = getattr(
            context,
            "emitter",
            None,
        )
        emit = getattr(
            emitter,
            "emit",
            None,
        )

        if emit is not None:
            first_asset_result_index = max(
                len(
                    getattr(
                        context,
                        "runtime_asset_results",
                        [],
                    )
                )
                - len(
                    saved_asset_results
                ),
                0,
            )

            for result_index, result in enumerate(
                saved_asset_results,
                start=1,
            ):
                result_action = str(
                    result.get(
                        "action",
                        "assets",
                    )
                    or "assets"
                )
                action_name = (
                    "list_skills"
                    if result_action == "list_skills"
                    else "asset_action"
                )
                text = (
                    saved_asset_result_texts[
                        result_index - 1
                    ][1]
                )
                action_id = (
                    result.get(
                        "runtime_action_id",
                        "",
                    )
                    or build_runtime_action_id(
                        result_action
                        or action_name,
                        first_asset_result_index
                        + result_index,
                    )
                )
                await emit(with_action_context({
                    "type": "runtime_action",
                    "action": action_name,
                    "id": action_id,
                    "status": (
                        "completed"
                        if result.get("ok")
                        else "failed"
                    ),
                    "text": text,
                    "asset_result": result,
                }))

    skill_state_results = (
        appended_skill_results
        + removed_skill_results
        + hidden_skill_results
    )

    skill_state_result_texts = []

    for result in skill_state_results:
        result_action = str(
            result.get(
                "action",
                "skill",
            )
            or "skill"
        )
        requested_skill = str(
            result.get(
                "requested",
                "",
            )
            or ""
        )
        if result_action == "append_skill":
            text = f"Appended skill: {requested_skill}"
        elif result_action == "remove_skill":
            text = f"Removed skill: {requested_skill}"
        else:
            text = "Hidden skills list"
        if (
            result_action == "append_skill"
            and result.get("ok") is False
            and result.get("error") == "skill_not_found"
        ):
            text = f"{text} ( does not exist )"

        skill_state_result_texts.append(
            (
                result,
                text,
            )
        )
        record_session_action_history(
            context,
            text,
        )

    if skill_state_results:
        emitter = getattr(
            context,
            "emitter",
            None,
        )
        emit = getattr(
            emitter,
            "emit",
            None,
        )

        if emit is not None:
            for result_index, (result, text) in enumerate(
                skill_state_result_texts,
                start=1,
            ):
                result_action = str(
                    result.get(
                        "action",
                        "skill",
                    )
                    or "skill"
                )
                action_id = build_runtime_action_id(
                    result_action,
                    len(context.runtime_action_events)
                    + result_index,
                )
                status = (
                    "completed"
                    if result.get("ok") is not False
                    else "failed"
                )
                payload = {
                    "type": "runtime_action",
                    "action": result_action,
                    "id": action_id,
                    "text": text,
                    "skill_result": result,
                }

                if status == "failed":
                    await emit(with_action_context({
                        **payload,
                        "status": status,
                    }))
                    continue

                await emit(with_action_context(
                    payload
                ))
                await emit({
                    **payload,
                    "status": status,
                })

    if save_session_count:
        context.runtime_save_session_armed = False
        context.runtime_save_session_requested = True
        context.runtime_save_session_action_emitted = True

        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] save_session requested"
            )

        emitter = getattr(
            context,
            "emitter",
            None,
        )
        emit = getattr(
            emitter,
            "emit",
            None,
        )

        if emit is not None:
            await emit(with_action_context({
                "type": "runtime_action",
                "action": "save_session",
                "text": "Saving session",
            }))

    created_active_memory_texts = []
    create_active_memory_results = []

    if create_active_memory_count:
        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] create_active_memory requested"
            )

        for active_memory_text in (
            normalize_active_memory_runtime_payload(
                action.payload
            )
            for action in create_active_memory_actions
            if action.payload
        ):
            if not active_memory_text:
                continue

            records_before = list(
                getattr(
                    context,
                    "active_memory_records",
                    [],
                )
                or []
            )
            record_created = (
                await create_active_memory_runtime_record(
                    context,
                    active_memory_text,
                )
            )
            records_after = list(
                getattr(
                    context,
                    "active_memory_records",
                    [],
                )
                or []
            )
            active_memory_line = (
                records_after[-1]
                if (
                    record_created
                    and len(records_after) > len(records_before)
                )
                else ""
            )

            create_active_memory_results.append(
                (
                    active_memory_text,
                    active_memory_line,
                )
            )

            if record_created:
                created_active_memory_texts.append(
                    active_memory_text
                )
                record_runtime_tool_result(
                    context,
                    TOOL_RESULT_KIND_ACTIVE_MEMORY,
                    {
                        "ok": True,
                        "action": "create_active_memory",
                        "destination": (
                            "active_memory_records -> <ACTIVE_MEMORY>"
                        ),
                        "content": active_memory_text,
                        "record": active_memory_line,
                    },
                )

            if (
                log_runtime is not None
                and record_created
            ):
                await log_runtime(
                    "[RUNTIME ACTION] active_memory record created"
                )

        if created_active_memory_texts:
            # Tells schedule_runtime_memory_update() that this turn is
            # meaningful for L1 even if the visible assistant text ends up
            # empty (e.g. the model was instructed to only emit the
            # marker and say nothing else).
            context.runtime_active_memory_created_this_turn = True

        emitter = getattr(
            context,
            "emitter",
            None,
        )
        emit = getattr(
            emitter,
            "emit",
            None,
        )

        if emit is not None:
            for active_memory_text, active_memory_line in create_active_memory_results:
                event = {
                    "type": "runtime_action",
                    "action": "create_active_memory",
                    "text": f"Saving: {active_memory_text}",
                }

                if active_memory_line:
                    event["active_memory"] = active_memory_line

                await emit(with_action_context(
                    event
                ))
                await emit(with_action_context({
                    "type": "runtime_action",
                    "action": "create_active_memory",
                    "status": "completed",
                }))

    saved_delayed_memory_reports = []

    if save_delayed_memory_actions:
        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] save_delayed_memory requested"
            )

        for action in save_delayed_memory_actions:
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

            report = build_delayed_memory_report(
                context,
                action.payload,
                existing_ids=delayed_memory_reports,
            )

            if not report:
                continue

            report = deduplicate_delayed_memory_report_keys(
                delayed_memory_reports,
                report,
            )

            delayed_memory_reports.update(
                report
            )

            saved_delayed_memory_reports.append(
                report
            )

            for report_id, report_value in report.items():
                if not isinstance(
                    report_value,
                    dict,
                ):
                    continue

                history_text = build_delayed_memory_history_text({
                    "ok": True,
                    "action": "save_delayed_memory_content",
                    "id": report_id,
                    "title": str(
                        report_value.get(
                            "title",
                            "",
                        )
                        or ""
                    ).strip(),
                    "report": {
                        **report_value,
                        "id": report_id,
                    },
                })
                if history_text:
                    record_session_action_history(
                        context,
                        history_text,
                    )

                saved_result = {
                    "ok": True,
                    "action": "save_delayed_memory_content",
                    "destination": (
                        "delayed_memory_reports (Delayed Memory storage)"
                    ),
                    "id": report_id,
                    "title": str(
                        report_value.get(
                            "title",
                            "",
                        )
                        or ""
                    ).strip(),
                    "report": {
                        **report_value,
                        "id": report_id,
                    },
                }
                record_runtime_tool_result(
                    context,
                    TOOL_RESULT_KIND_DELAYED_MEMORY,
                    saved_result,
                )

        emitter = getattr(
            context,
            "emitter",
            None,
        )
        emit = getattr(
            emitter,
            "emit",
            None,
        )

        if emit is not None:
            for report in saved_delayed_memory_reports:
                report_items = [
                    (
                        report_id,
                        report_value,
                    )
                    for report_id, report_value in report.items()
                    if isinstance(
                        report_value,
                        dict,
                    )
                ]
                report_id = (
                    report_items[0][0]
                    if report_items
                    else ""
                )
                report_title = (
                    str(
                        report_items[0][1].get(
                            "title",
                            "",
                        )
                        or ""
                    ).strip()
                    if report_items
                    else ""
                )
                pending_ids = getattr(
                    context,
                    "runtime_pending_delayed_memory_action_ids",
                    None,
                )
                action_id = (
                    pending_ids.pop(0)
                    if isinstance(
                        pending_ids,
                        list,
                    )
                    and pending_ids
                    else ""
                )

                if not action_id:
                    current_action_sequence = int(
                        getattr(
                            context,
                            "runtime_delayed_memory_action_sequence",
                            0,
                        )
                        or 0
                    )
                    save_action_event_count = len([
                        event
                        for event in getattr(
                            context,
                            "runtime_action_events",
                            [],
                        )
                        if isinstance(
                            event,
                            dict,
                        )
                        and event.get(
                            "name"
                        ) == "save_delayed_memory_content"
                    ])
                    action_sequence = max(
                        current_action_sequence + 1,
                        len(
                            getattr(
                                context,
                                "delayed_memory_reports",
                                {},
                            )
                            or {}
                        ),
                        save_action_event_count,
                    )
                    setattr(
                        context,
                        "runtime_delayed_memory_action_sequence",
                        action_sequence,
                    )
                    action_id = build_runtime_action_id(
                        RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT,
                        action_sequence,
                    )
                await emit(with_action_context({
                    "type": "runtime_action",
                    "action": "save_delayed_memory_content",
                    "id": action_id,
                    "status": "completed",
                    "text": (
                        f"Saved delayed memory: {report_title}"
                        if report_title
                        else "Delayed memory saved"
                    ),
                    "delayed_memory_report_id": report_id,
                    "delayed_memory_report": report,
                }))

    resolved_active_memory_count = 0

    if resolve_active_memory_count:
        emitter = getattr(
            context,
            "emitter",
            None,
        )
        emit = getattr(
            emitter,
            "emit",
            None,
        )

        for action in resolve_active_memory_actions:
            (
                record_resolved,
                active_memory_id,
                resolved_record,
            ) = (
                await resolve_active_memory_runtime_record(
                    context,
                    action.payload,
                )
            )

            if not record_resolved:
                failure_result = build_active_memory_resolve_failure_result(
                    context,
                    action.payload,
                    error="active_memory_not_resolved",
                )
                if active_memory_id:
                    failure_result["id"] = active_memory_id
                failure_result["detail"] = (
                    "Active memory was not resolved. The record may be paused "
                    "or may no longer exist. Do not claim that the action "
                    "completed."
                )
                queue_active_memory_resolve_failure(
                    context,
                    failure_result,
                )

                if emit is not None:
                    await emit(with_action_context({
                        "type": "runtime_action",
                        "action": "resolve_active_memory",
                        "id": active_memory_id,
                        "status": "failed",
                        "text": "Active memory resolve failed",
                        "active_memory_result": failure_result,
                    }))
                continue

            resolved_active_memory_count += 1
            record_runtime_tool_result(
                context,
                TOOL_RESULT_KIND_ACTIVE_MEMORY,
                {
                    "ok": True,
                    "action": "resolve_active_memory",
                    "destination": (
                        "active_memory_records -> <ACTIVE_MEMORY> "
                        "(resolved and removed)"
                    ),
                    "id": active_memory_id,
                    "content": (
                        normalize_active_memory_content_for_duplicate_check(
                            resolved_record
                        )
                    ),
                    "record": resolved_record,
                },
            )

            if emit is None:
                continue

            await emit(with_action_context({
                "type": "runtime_action",
                "action": "resolve_active_memory",
                "id": active_memory_id,
                "text": "Active memory resolved",
            }))
            await emit(with_action_context({
                "type": "runtime_action",
                "action": "resolve_active_memory",
                "id": active_memory_id,
                "status": "completed",
            }))

        if resolved_active_memory_count:
            context.runtime_active_memory_records_dirty = True

    return (
        len(
            search_queries
        )
        + len(
            saved_asset_results
        )
        + len(
            appended_skill_results
        )
        + len(
            removed_skill_results
        )
        + len(
            hidden_skill_results
        )
        + len(
            clean_tool_result_actions
        )
        + len(
            idle_records
        )
        + len(
            jin_color_actions
        )
        + min(
            save_session_count,
            1,
        )
        + len(
            created_active_memory_texts
        )
        + len(
            saved_delayed_memory_reports
        )
        + len(
            delayed_memory_results
        )
        + resolved_active_memory_count
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



