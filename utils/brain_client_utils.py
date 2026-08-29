from app_settings import settings

from rules.brain_context_builder import (
    BRAIN_RUNTIME_ACTIONS,
)
from runtime.state import BRAIN_RUNTIME_ID


def get_brain_runtime_config():

    return {
        "runtime_id": BRAIN_RUNTIME_ID,
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
    RUNTIME_ACTION_LOAD_DELAYED_MEMORY,
    RUNTIME_ACTION_LOAD_SKILL,
    RUNTIME_ACTION_ASSET_ACTION,
    RUNTIME_ACTION_CHECK_TODO,
    RUNTIME_ACTION_CREATE_TODO_LIST,
    RUNTIME_ACTION_SAVE_ACTIVE_MEMORY,
    RUNTIME_ACTION_JIN_COLOR,
    RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
    RUNTIME_ACTION_UNLOAD_DELAYED_MEMORY,
    RUNTIME_ACTION_UNLOAD_SKILL,
    RUNTIME_ACTION_RESOLVE_TODO,
    RUNTIME_ACTION_SAVE_DELAYED_MEMORY,
    RUNTIME_ACTION_DELETE_ACTIVE_MEMORY,
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
    load_skill,
    normalize_skill_name,
)
from utils.actions import (
    build_runtime_action_id,
    collect_active_memory_slot_ids,
    collect_active_memory_custom_fields,
    extract_active_memory_creation_custom_fields,
    get_active_memory_record_title,
    extract_active_memory_delete_slot_id,
    extract_search_query,
    extract_runtime_actions,
    generate_active_memory_slot_id,
    generate_active_memory_slot_key,
    generate_delayed_memory_report_id,
    get_save_active_memory_marker_fields,
    is_delayed_memory_report_id,
    is_active_memory_record_paused,
    normalize_active_memory_custom_field_name,
    normalize_active_memory_custom_field_value,
    parse_delayed_memory_payload,
    parse_update_active_memory_payload,
    normalize_jin_color_payload,
    normalize_delayed_memory_attachment_ids,
    normalize_delayed_memory_fact_ids,
    refresh_active_memory_runtime_metadata,
    strip_active_memory_runtime_metadata,
    strip_active_memory_managed_suffixes,
    set_active_memory_suffix_value,
)
from utils.actions.update_active_memory_utils import (
    parse_update_active_memory_payload_fields,
)
from utils.session_actions_history import (
    build_active_memory_delete_failed_history_text,
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


def get_runtime_l4_fact_ids(
    context,
) -> set[str]:

    store = getattr(
        context,
        "runtime_long_term_memory_store",
        {},
    )

    if not isinstance(store, dict):
        return set()

    fact_ids = set()

    for fact in store.get("facts", []) or []:
        if not isinstance(fact, dict):
            continue

        fact_id = str(
            fact.get(
                "id",
                "",
            )
            or ""
        ).strip().upper()

        if fact_id:
            fact_ids.add(fact_id)

    return fact_ids


def prune_missing_delayed_memory_fact_ids(
    context,
    report: dict,
) -> tuple[dict, list[str]]:

    if not isinstance(report, dict):
        return {}, []

    store = getattr(
        context,
        "runtime_long_term_memory_store",
        None,
    )

    # A missing/uninitialised L4 store must not erase delayed-memory links.
    # Once the store exists, its facts list is the source of truth.
    if (
        not isinstance(store, dict)
        or not isinstance(store.get("facts"), list)
    ):
        return dict(report), []

    anchor_fact_ids, facts_ids = normalize_delayed_memory_fact_ids(
        report.get("anchor_fact_ids", []),
        report.get("facts_ids", []),
        legacy_absorbed_fact_ids=report.get("absorbed_fact_ids", []),
        legacy_long_term_fact_ids=report.get("long_term_facts_ids", []),
    )
    available_fact_ids = get_runtime_l4_fact_ids(context)
    referenced_fact_ids = list(dict.fromkeys([
        *anchor_fact_ids,
        *facts_ids,
    ]))
    removed_fact_ids = [
        fact_id
        for fact_id in referenced_fact_ids
        if fact_id not in available_fact_ids
    ]
    clean_anchor_fact_ids = [
        fact_id
        for fact_id in anchor_fact_ids
        if fact_id in available_fact_ids
    ]
    clean_facts_ids = [
        fact_id
        for fact_id in facts_ids
        if fact_id in available_fact_ids
    ]
    clean_anchor_fact_ids, clean_facts_ids = normalize_delayed_memory_fact_ids(
        clean_anchor_fact_ids,
        clean_facts_ids,
    )

    updated_report = {
        **report,
        "anchor_fact_ids": clean_anchor_fact_ids,
        "facts_ids": clean_facts_ids,
    }
    updated_report.pop("absorbed_fact_ids", None)
    updated_report.pop("long_term_facts_ids", None)

    return updated_report, removed_fact_ids


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
        report = parse_delayed_memory_payload(
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

        requested_anchor_fact_ids, requested_facts_ids = (
            normalize_delayed_memory_fact_ids(
                value.get("anchor_fact_ids", []),
                value.get("facts_ids", []),
                legacy_absorbed_fact_ids=value.get("absorbed_fact_ids", []),
                legacy_long_term_fact_ids=value.get("long_term_facts_ids", []),
            )
        )
        available_l4_fact_ids = get_runtime_l4_fact_ids(
            context
        )
        anchor_fact_ids = [
            fact_id
            for fact_id in requested_anchor_fact_ids
            if fact_id in available_l4_fact_ids
        ]
        facts_ids = [
            fact_id
            for fact_id in requested_facts_ids
            if fact_id in available_l4_fact_ids
        ]
        anchor_fact_ids, facts_ids = normalize_delayed_memory_fact_ids(
            anchor_fact_ids,
            facts_ids,
        )
        from utils.attached_files_store import filter_existing_file_ids

        attachments_ids = filter_existing_file_ids(
            normalize_delayed_memory_attachment_ids(
                value.get("attachments_ids", [])
            )
        )

        enriched_report[report_id] = {
            **value,
            "anchor_fact_ids": anchor_fact_ids,
            "facts_ids": facts_ids,
            "attachments_ids": attachments_ids,
            "pinned": bool(value.get("pinned", False)),
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
            "loaded_times": int(
                normalize_delayed_memory_counter(
                    value.get(
                        "loaded_times",
                        0,
                    )
                )
            ),
            "load_streak": int(
                normalize_delayed_memory_counter(
                    value.get(
                        "load_streak",
                        0,
                    )
                )
            ),
            "last_loaded_date": str(
                value.get(
                    "last_loaded_date",
                    "",
                )
                or ""
            ).strip(),
            "last_loaded_session_id": str(
                value.get(
                    "last_loaded_session_id",
                    "",
                )
                or ""
            ).strip(),
            "all_loaded_session_ids": (
                normalize_delayed_memory_session_ids(
                    value.get(
                        "all_loaded_session_ids",
                        [],
                    )
                )
            ),
        }
        enriched_report[report_id].pop("absorbed_fact_ids", None)
        enriched_report[report_id].pop("long_term_facts_ids", None)

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


def refresh_delayed_memory_load_metadata(
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
            "last_loaded_session_id",
            "",
        )
        or ""
    ).strip()
    loaded_session_ids = normalize_delayed_memory_session_ids(
        updated_report.get(
            "all_loaded_session_ids",
            [],
        )
    )

    if (
        session_id
        and session_id not in loaded_session_ids
    ):
        loaded_session_ids.append(
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
    updated_report["loaded_times"] = (
        normalize_delayed_memory_counter(
            updated_report.get(
                "loaded_times",
                0,
            )
        )
        + 1
    )
    updated_report["load_streak"] = normalize_delayed_memory_counter(
        updated_report.get(
            "load_streak",
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
        updated_report["load_streak"] += 1

    updated_report["last_loaded_date"] = now
    updated_report["last_loaded_session_id"] = session_id
    updated_report["all_loaded_session_ids"] = loaded_session_ids

    return updated_report


def record_loaded_delayed_memory_id(
    context,
    report_id: str,
) -> None:

    normalized_report_id = str(
        report_id
        or ""
    ).strip().casefold()

    if not normalized_report_id:
        return

    loaded_ids = getattr(
        context,
        "runtime_loaded_delayed_memory_ids",
        None,
    )

    if not isinstance(
        loaded_ids,
        list,
    ):
        loaded_ids = []
        setattr(
            context,
            "runtime_loaded_delayed_memory_ids",
            loaded_ids,
        )

    if normalized_report_id not in loaded_ids:
        loaded_ids.append(
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

    raw_visible_value = suffix_values[0][1]

    json_payload = raw_visible_value.lstrip().startswith("{")

    if (
        not json_payload
        and collect_active_memory_custom_fields(raw_visible_value)
    ):
        return ""

    visible_value, custom_fields = (
        extract_active_memory_creation_custom_fields(
            raw_visible_value
        )
    )

    if not visible_value:
        return ""

    suffix_items = [
        (
            suffix_values[0][0],
            visible_value,
        ),
        *custom_fields,
    ]
    suffix_text = " ".join(
        f"[ {field}: {field_value} ]"
        for field, field_value in suffix_items
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
            r"elapsed_time|elapsed_jin_message_number|updated_at|status)"
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
UPDATE_ACTIVE_MEMORY_SLOT_KEY_RE = re.compile(
    r"^active_memory_[1-9]\d*$",
    re.IGNORECASE,
)

UPDATE_ACTIVE_MEMORY_SLOT_KEY_TOKEN_RE = re.compile(
    r"(?<![a-z0-9_])(active_memory_[1-9]\d*)(?![a-z0-9_])",
    re.IGNORECASE,
)

UPDATE_ACTIVE_MEMORY_OPEN_TAG_RE = re.compile(
    r"^\s*<\s*UPDATE_ACTIVE_MEMORY(?:\s*:\s*([^>]*?))?\s*>\s*$",
    re.IGNORECASE,
)

UPDATE_ACTIVE_MEMORY_CLOSE_TAG_RE = re.compile(
    r"^\s*</\s*UPDATE_ACTIVE_MEMORY\s*>\s*$",
    re.IGNORECASE,
)


def _collect_context_active_memory_sources(
    context,
) -> list[str]:

    active_records = getattr(
        context,
        "active_memory_records",
        None,
    )
    return [
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


def _extract_update_active_memory_slot_key(
    payload: str,
) -> str:

    for line in str(
        payload or ""
    ).splitlines():
        text = str(
            line or ""
        ).strip()

        if not text:
            continue

        match = UPDATE_ACTIVE_MEMORY_SLOT_KEY_TOKEN_RE.search(
            text
        )
        if match is None:
            return ""

        return match.group(
            1
        ).casefold()

    return ""


def _unwrap_update_active_memory_marker_payload(
    payload: str,
) -> str:

    attribute_payload = ""
    payload_lines = []
    did_read_first_line = False

    for line in str(
        payload or ""
    ).splitlines():
        text = str(
            line or ""
        ).strip()

        if not text:
            continue

        if not did_read_first_line:
            did_read_first_line = True
            match = UPDATE_ACTIVE_MEMORY_OPEN_TAG_RE.fullmatch(
                text
            )

            if match is not None:
                attribute_payload = str(
                    match.group(1)
                    or ""
                ).strip()
                continue

        if UPDATE_ACTIVE_MEMORY_CLOSE_TAG_RE.fullmatch(
            text
        ):
            continue

        payload_lines.append(
            text
        )

    return "\n".join(
        part
        for part in (
            attribute_payload,
            *payload_lines,
        )
        if part
    )


def _extract_update_active_memory_json_slot_key(
    payload: str,
) -> str:

    text = str(
        payload or ""
    ).strip()

    if not text.startswith("{"):
        return ""

    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return ""

    if not isinstance(
        data,
        dict,
    ):
        return ""

    candidate = str(
        data.get("active_memory_id")
        or data.get("id")
        or ""
    ).strip().casefold()

    if UPDATE_ACTIVE_MEMORY_SLOT_KEY_RE.fullmatch(
        candidate
    ):
        return candidate

    return ""


def _replace_update_active_memory_json_slot_key(
    payload: str,
    active_memory_id: str,
) -> str:

    text = str(
        payload or ""
    ).strip()

    if not text.startswith("{"):
        return ""

    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return ""

    if not isinstance(
        data,
        dict,
    ):
        return ""

    for key in (
        "active_memory_id",
        "id",
    ):
        candidate = str(
            data.get(key)
            or ""
        ).strip().casefold()

        if UPDATE_ACTIVE_MEMORY_SLOT_KEY_RE.fullmatch(
            candidate
        ):
            data[key] = active_memory_id
            return json.dumps(
                data,
                ensure_ascii=False,
            )

    return ""


def _find_active_memory_slot_record_by_key(
    context,
    active_memory_key: str,
) -> str:

    normalized_key = str(
        active_memory_key or ""
    ).strip().casefold()

    if not UPDATE_ACTIVE_MEMORY_SLOT_KEY_RE.fullmatch(
        normalized_key
    ):
        return ""

    for source in _collect_context_active_memory_sources(
        context
    ):
        for line in str(
            source or ""
        ).splitlines():
            key, separator, _ = str(
                line or ""
            ).partition(":")

            if (
                separator
                and key.strip().casefold() == normalized_key
                and ACTIVE_MEMORY_RUNTIME_LINE_RE.match(line)
                and not is_active_memory_record_paused(line)
            ):
                return line.strip()

    return ""


def normalize_update_active_memory_payload_reference(
    context,
    payload: str,
) -> tuple[str, str, str]:

    original_payload = _unwrap_update_active_memory_marker_payload(
        payload
    )
    slot_key = _extract_update_active_memory_slot_key(
        original_payload
    ) or _extract_update_active_memory_json_slot_key(
        original_payload
    )

    if not slot_key:
        return original_payload, "", ""

    slot_record = _find_active_memory_slot_record_by_key(
        context,
        slot_key,
    )
    active_memory_ids = sorted(
        collect_active_memory_slot_ids(
            slot_record
        )
    )
    active_memory_id = (
        active_memory_ids[0]
        if active_memory_ids
        else ""
    )

    if not active_memory_id:
        return original_payload, slot_key, ""

    json_payload = _replace_update_active_memory_json_slot_key(
        original_payload,
        active_memory_id,
    )
    if json_payload:
        return json_payload, slot_key, active_memory_id

    lines = []
    did_write_id = False

    for line in original_payload.splitlines():
        text = str(
            line or ""
        ).strip()

        if not text:
            continue

        if UPDATE_ACTIVE_MEMORY_CLOSE_TAG_RE.fullmatch(
            text
        ):
            continue

        if not did_write_id:
            lines.append(
                active_memory_id
            )
            did_write_id = True
            continue

        lines.append(
            text
        )

    return "\n".join(lines), slot_key, active_memory_id


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

    for source in _collect_context_active_memory_sources(
        context
    ):
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


def build_active_memory_delete_failure_result(
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
    requested_id = extract_active_memory_delete_slot_id(
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
        "Active memory was not deleted. "
        "Use an exact 6-character active_memory_id from <ACTIVE_MEMORY> "
        "and retry only for a record that is still pending."
    )

    result = {
        "ok": False,
        "action": "delete_active_memory",
        "error": normalized_error,
        "requested": requested,
        "detail": detail,
        "available_ids": available_ids,
    }

    if requested_id:
        result["id"] = requested_id

    return result


def queue_active_memory_delete_failure(
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
        "runtime_active_memory_delete_failures_pending",
        None,
    )

    if not isinstance(
        pending,
        list,
    ):
        pending = []
        setattr(
            context,
            "runtime_active_memory_delete_failures_pending",
            pending,
        )

    pending.append(
        dict(result)
    )


def flush_pending_active_memory_delete_failure_history(
    context,
) -> None:

    pending = getattr(
        context,
        "runtime_active_memory_delete_failures_pending",
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
            build_active_memory_delete_failed_history_text(
                result
            ),
        )

    pending.clear()


def _update_active_memory_line_fields(
    line: str,
    changes: tuple[tuple[str, str], ...],
    *,
    updated_at: str,
) -> tuple[str, tuple[dict, ...]]:

    text = str(line or "").strip()
    if ":" not in text:
        return text, ()

    key, value = text.split(":", 1)
    value = value.strip()
    allowed_fields = dict(
        collect_active_memory_custom_fields(
            value
        )
    )

    if not changes or any(
        field_name not in allowed_fields
        for field_name, _ in changes
    ):
        return text, ()

    change_results = []

    for field_name, field_value in changes:
        value, did_update, previous_value = set_active_memory_suffix_value(
            value,
            field_name,
            field_value,
            require_existing=True,
        )
        if not did_update:
            return text, ()

        change_results.append({
            "field": field_name,
            "before": previous_value,
            "after": field_value,
        })

    value, did_set_updated_at, _ = set_active_memory_suffix_value(
        value,
        "updated_at",
        updated_at,
        require_existing=False,
    )
    if not did_set_updated_at:
        return text, ()

    return (
        f"{key.strip()}: {value}".strip(),
        tuple(change_results),
    )


def _update_active_memory_slot_in_text(
    memory: str,
    active_memory_id: str,
    changes: tuple[tuple[str, str], ...],
    *,
    updated_at: str,
) -> tuple[str, bool]:

    lines = str(memory or "").splitlines()
    if not lines:
        return str(memory or ""), False

    updated_lines = []
    changed = False

    for line in lines:
        if (
            ACTIVE_MEMORY_RUNTIME_LINE_RE.match(line)
            and active_memory_id in collect_active_memory_slot_ids(line)
        ):
            updated_line, applied_changes = _update_active_memory_line_fields(
                line,
                changes,
                updated_at=updated_at,
            )
            if applied_changes:
                line = updated_line
                changed = True

        updated_lines.append(line)

    return "\n".join(updated_lines).strip(), changed


async def update_active_memory_runtime_record(
    context,
    payload: str,
) -> dict:

    result = {
        "ok": False,
        "action": "update_active_memory",
        "error": "invalid_update_active_memory_payload",
    }

    if context is None:
        return result

    normalized_payload, requested_reference, resolved_reference_id = (
        normalize_update_active_memory_payload_reference(
            context,
            payload,
        )
    )

    if requested_reference:
        result["requested_id"] = requested_reference

    if requested_reference and not resolved_reference_id:
        result["id"] = requested_reference
        result["error"] = "active_memory_not_found"
        return result

    active_memory_id, changes = parse_update_active_memory_payload(
        normalized_payload
    )
    (
        requested_active_memory_id,
        requested_changes,
    ) = parse_update_active_memory_payload_fields(
        normalized_payload
    )
    result["id"] = active_memory_id or requested_active_memory_id
    result["requested_changes"] = [
        {
            "field": field_name,
            "after": field_value,
        }
        for field_name, field_value in requested_changes
    ]

    if not active_memory_id or not changes:
        return result

    current_record = find_active_memory_slot_record(
        context,
        active_memory_id,
    )
    if not current_record:
        result["error"] = "active_memory_not_found"
        return result

    result["previous_title"] = get_active_memory_record_title(
        current_record
    )

    current_fields = dict(
        collect_active_memory_custom_fields(
            current_record
        )
    )
    result["available_fields"] = list(current_fields)

    requested_fields = [
        field_name
        for field_name, _ in changes
    ]
    unknown_fields = [
        field_name
        for field_name in requested_fields
        if field_name not in current_fields
    ]
    if unknown_fields:
        result["error"] = "active_memory_field_not_declared"
        result["unknown_fields"] = unknown_fields
        return result

    effective_changes = tuple(
        (field_name, field_value)
        for field_name, field_value in changes
        if current_fields.get(field_name) != field_value
    )
    if not effective_changes:
        result["error"] = "active_memory_update_no_changes"
        return result

    updated_at = str(
        getattr(
            context,
            "timestamp",
            "",
        )
        or datetime.now().isoformat()
    )
    updated_record, change_results = _update_active_memory_line_fields(
        current_record,
        effective_changes,
        updated_at=updated_at,
    )
    if not change_results:
        result["error"] = "active_memory_update_failed"
        return result

    for attr_name in (
        "runtime_memory",
        "runtime_memory_stable",
    ):
        current_memory = getattr(
            context,
            attr_name,
            "",
        )
        updated_memory, did_update = _update_active_memory_slot_in_text(
            current_memory,
            active_memory_id,
            effective_changes,
            updated_at=updated_at,
        )
        if did_update:
            setattr(
                context,
                attr_name,
                updated_memory,
            )

    records = list(
        getattr(
            context,
            "active_memory_records",
            [],
        )
        or []
    )
    records_changed = False

    for index, record in enumerate(records):
        if active_memory_id not in collect_active_memory_slot_ids(record):
            continue

        next_record, applied_changes = _update_active_memory_line_fields(
            record,
            effective_changes,
            updated_at=updated_at,
        )
        if not applied_changes:
            continue

        records[index] = next_record
        updated_record = next_record
        records_changed = True

    if records_changed:
        context.active_memory_records = records
        context.runtime_active_memory_records_dirty = True

    result.update({
        "ok": True,
        "error": "",
        "id": active_memory_id,
        "title": result["previous_title"],
        "record": updated_record,
        "changes": list(change_results),
        "updated_at": updated_at,
    })
    return result


async def delete_active_memory_runtime_record(
    context,
    payload: str,
) -> tuple[bool, str, str]:

    if context is None:
        return (
            False,
            "",
            "",
        )

    active_memory_id = extract_active_memory_delete_slot_id(
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

    deleted_record = find_active_memory_slot_record(
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
        deleted_record,
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


def record_delayed_memory_runtime_result(
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


def get_loaded_delayed_memory_reports(
    context,
) -> dict:

    loaded_reports = getattr(
        context,
        "runtime_loaded_delayed_memory",
        None,
    )

    if not isinstance(
        loaded_reports,
        dict,
    ):
        loaded_reports = {}

    legacy_report_id = str(
        loaded_reports.get(
            "id",
            "",
        )
        or ""
    ).strip().casefold()

    if (
        legacy_report_id
        and is_delayed_memory_report_id(
            legacy_report_id
        )
        and (
            "title" in loaded_reports
            or "body" in loaded_reports
            or "summary" in loaded_reports
        )
    ):
        loaded_reports = {
            legacy_report_id: {
                **loaded_reports,
                "id": legacy_report_id,
            },
        }
    else:
        normalized_reports = {}

        for report_id, report in loaded_reports.items():
            normalized_report_id = str(
                report_id
                or ""
            ).strip().casefold()

            if (
                not is_delayed_memory_report_id(
                    normalized_report_id
                )
                or not isinstance(
                    report,
                    dict,
                )
            ):
                continue

            normalized_reports[normalized_report_id] = {
                **report,
                "id": normalized_report_id,
            }

        loaded_reports = normalized_reports

    setattr(
        context,
        "runtime_loaded_delayed_memory",
        loaded_reports,
    )

    return loaded_reports


def set_loaded_delayed_memory_report(
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

    if not is_delayed_memory_report_id(
        report_id
    ):
        return False

    loaded_reports = get_loaded_delayed_memory_reports(
        context
    )

    if report_id in loaded_reports:
        return False

    loaded_reports[report_id] = {
        **report,
        "id": report_id,
    }

    return True


def clear_loaded_delayed_memory_report(
    context,
    report_id: str = "",
) -> bool:

    normalized_report_id = str(
        report_id
        or ""
    ).strip().casefold()

    if not is_delayed_memory_report_id(
        normalized_report_id
    ):
        return False

    saved_report = get_delayed_memory_reports(
        context
    ).get(normalized_report_id)

    if isinstance(saved_report, dict) and bool(saved_report.get("pinned", False)):
        return False

    loaded_reports = get_loaded_delayed_memory_reports(
        context
    )

    if normalized_report_id not in loaded_reports:
        return False

    del loaded_reports[normalized_report_id]

    loaded_ids = getattr(
        context,
        "runtime_loaded_delayed_memory_ids",
        None,
    )

    if isinstance(
        loaded_ids,
        list,
    ):
        loaded_ids[:] = [
            item
            for item in loaded_ids
            if str(item or "").strip().casefold()
            != normalized_report_id
        ]

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


def load_delayed_memory_report(
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
            action="load_delayed_memory",
            requested=report_id
            or payload,
            error=(
                "invalid_delayed_memory_id"
                if not report_id
                else "delayed_memory_not_found"
            ),
        )

    updated_report = refresh_delayed_memory_load_metadata(
        context,
        report,
    )
    updated_report, pruned_fact_ids = prune_missing_delayed_memory_fact_ids(
        context,
        updated_report,
    )
    reports[report_id] = updated_report

    loaded_reports = getattr(
        context,
        "runtime_loaded_delayed_memory",
        None,
    )
    if (
        isinstance(loaded_reports, dict)
        and report_id in loaded_reports
    ):
        loaded_reports[report_id] = {
            **updated_report,
            "id": report_id,
        }

    record_loaded_delayed_memory_id(
        context,
        report_id,
    )

    file_errors = []

    if bool(
        getattr(
            context,
            "delayed_memory_file_store_enabled",
            False,
        )
    ):
        from utils.delayed_memory_file_store import (
            persist_delayed_memory_reports,
        )

        file_errors = persist_delayed_memory_reports({
            report_id: updated_report,
        })

    return {
        "ok": True,
        "action": "load_delayed_memory",
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
        "pruned_fact_ids": pruned_fact_ids,
        "file_saved": not file_errors,
        "file_errors": file_errors,
    }


def include_pinned_delayed_memory_reports(
    context,
) -> dict:

    reports = getattr(
        context,
        "delayed_memory_reports",
        None,
    )
    loaded_reports = get_loaded_delayed_memory_reports(context)

    if not isinstance(reports, dict):
        return loaded_reports
    turn_id = str(
        getattr(context, "runtime_current_turn_id", "")
        or getattr(context, "runtime_message_id", "")
        or ""
    ).strip()
    touched_by_report = getattr(
        context,
        "runtime_pinned_delayed_memory_turns",
        None,
    )

    if not isinstance(touched_by_report, dict):
        touched_by_report = {}
        context.runtime_pinned_delayed_memory_turns = touched_by_report

    reports_to_persist = {}

    for report_id, report in reports.items():
        if not isinstance(report, dict) or not bool(report.get("pinned", False)):
            continue

        updated_report = report

        if turn_id and touched_by_report.get(report_id) != turn_id:
            updated_report = refresh_delayed_memory_load_metadata(
                context,
                report,
            )
            updated_report["pinned"] = True
            reports[report_id] = updated_report
            touched_by_report[report_id] = turn_id
            reports_to_persist[report_id] = updated_report

        loaded_reports[report_id] = {
            **updated_report,
            "id": report_id,
        }

    if reports_to_persist and bool(
        getattr(
            context,
            "delayed_memory_file_store_enabled",
            False,
        )
    ):
        from utils.delayed_memory_file_store import (
            persist_delayed_memory_reports,
        )

        persist_delayed_memory_reports(reports_to_persist)

    return loaded_reports


def unload_delayed_memory_report(
    context,
    payload: str,
) -> dict:

    report_id = normalize_delayed_memory_action_id(
        payload
    )

    if not report_id:
        return build_delayed_memory_failure_result(
            action="unload_delayed_memory",
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
            action="unload_delayed_memory",
            requested=report_id,
            error="delayed_memory_not_found",
        )

    if bool(report.get("pinned", False)):
        return build_delayed_memory_failure_result(
            action="unload_delayed_memory",
            requested=report_id,
            error="delayed_memory_pinned",
        )

    return {
        "ok": True,
        "action": "unload_delayed_memory",
        "id": report_id,
        "unloaded": bool(
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
        return "Delayed memory action"

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
            or "unknown"
        ).strip()

    failed = result.get("ok") is False

    if action == "load_delayed_memory":
        return (
            f"Load failed: {title}"
            if failed
            else f"Loading: {title}"
        )

    if action == "unload_delayed_memory":
        return (
            f"Unload failed: {title}"
            if failed
            else f"Unloading: {title}"
        )

    return "Delayed memory action"


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

    if action == "save_delayed_memory":
        return f"Delayed memory saved: {title}"

    if action == "load_delayed_memory":
        return f"Delayed memory loaded: {title}"

    if action == "unload_delayed_memory":
        return f"Delayed memory unloaded from context: {title}"

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
            "runtime_l1_diff_history",
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

