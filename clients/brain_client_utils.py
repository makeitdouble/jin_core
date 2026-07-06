from app_settings import settings

from rules.assembler import (
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


import json
import re
from xml.etree import ElementTree

from rules.runtime import (
    RUNTIME_ACTION_APPEND_SKILL,
    RUNTIME_ACTION_ASSET_ACTION,
    RUNTIME_ACTION_CHECK_TODO,
    RUNTIME_ACTION_CREATE_TODO_LIST,
    RUNTIME_ACTION_CREATE_ACTIVE_MEMORY,
    RUNTIME_ACTION_LIST_SKILLS,
    RUNTIME_ACTION_REMOVE_SKILL,
    RUNTIME_ACTION_RESOLVE_TODO,
    RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT,
    RUNTIME_ACTION_SAVE_SESSION,
    RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY,
    RUNTIME_ACTION_WEB_SEARCH,
)
from runtime.behavior_contract import (
    should_execute_action_guard,
)
from utils.assets_service import (
    ensure_assets_tree,
    list_skills,
    load_skill,
    normalize_skill_name,
    run_asset_action,
)
from utils.runtime_actions import (
    build_runtime_action_id,
    collect_active_memory_slot_ids,
    extract_active_memory_resolve_slot_id,
    extract_search_query,
    extract_runtime_actions,
    generate_active_memory_slot_id,
    generate_active_memory_slot_key,
    get_create_active_memory_marker_fields,
    is_active_memory_record_paused,
    parse_delayed_memory_content_payload,
    refresh_active_memory_runtime_metadata,
)
from utils.session_actions_history import (
    build_asset_action_history_text,
    record_session_action_history,
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
    return should_execute_action_guard(
        "save_session",
        user_message
    )


def should_execute_save_delayed_memory(
    user_message: str,
) -> bool:
    return should_execute_action_guard(
        "save_delayed_memory",
        user_message
    )


def build_delayed_memory_report(
    context,
    payload: str,
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
        from datetime import datetime

        created_time = datetime.now().isoformat()

    enriched_report = {}

    for key, value in report.items():
        if not isinstance(
            value,
            dict,
        ):
            continue

        normalized_key = str(
            key
            or ""
        ).strip()

        if not normalized_key:
            continue

        enriched_report[normalized_key] = {
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
        }

    return enriched_report


def deduplicate_delayed_memory_report_keys(
    existing_reports: dict,
    report: dict,
) -> dict:

    if not isinstance(
        report,
        dict,
    ):
        return {}

    used_keys = set(
        existing_reports
        if isinstance(
            existing_reports,
            dict,
        )
        else {}
    )
    deduplicated_report = {}

    for key, value in report.items():
        next_key = key
        suffix = 2

        while (
            next_key in used_keys
            or next_key in deduplicated_report
        ):
            next_key = f"{key}_{suffix}"
            suffix += 1

        deduplicated_report[next_key] = value
        used_keys.add(
            next_key
        )

    return deduplicated_report



def split_active_memory_payload(
    payload: str,
) -> tuple[tuple[str, str], ...]:

    text = str(
        payload or ""
    ).strip()

    if not text:
        return ()

    marker_fields = get_create_active_memory_marker_fields()

    if not marker_fields:
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


async def resolve_active_memory_runtime_record(
    context,
    payload: str,
) -> tuple[bool, str]:

    if context is None:
        return (
            False,
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

    asset_results.append(
        result
    )


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
            f'Preview: "{preview}"'
        )

        if log_validator is not None:
            await log_validator(
                message
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

    action_context_snapshot = (
        dict(context_snapshot)
        if isinstance(context_snapshot, dict)
        else None
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
    resolve_active_memory_seen = False
    save_delayed_memory_seen = False
    list_skills_seen = False
    resolved_user_message = resolve_runtime_action_user_message(
        context,
        user_message,
    )
    skill_state_action_names = {
        RUNTIME_ACTION_APPEND_SKILL,
        RUNTIME_ACTION_REMOVE_SKILL,
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
            if action.name in skill_state_action_names
            or action.name in todo_action_names
        ]

    for action in actions:

        action_event_name = action.name.lower()

        if action.name == RUNTIME_ACTION_SAVE_SESSION:
            if not should_execute_save_session(
                resolved_user_message
            ):
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

            if not should_execute_save_delayed_memory(
                resolved_user_message
            ):
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

        if action.name == RUNTIME_ACTION_CREATE_ACTIVE_MEMORY:
            filtered_actions.append(
                action
            )
            continue

        if action.name == RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY:
            if resolve_active_memory_seen:
                continue

            if not extract_active_memory_resolve_slot_id(
                action.payload,
                existing_ids=collect_context_active_memory_slot_ids(
                    context
                ),
            ):
                continue

            resolve_active_memory_seen = True
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

    if not filtered_actions:
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

    for action in filtered_actions:

        action_event = {
            "name": action.name.lower(),
        }

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

        elif action.payload:
            action_event["payload"] = (
                action.payload
            )

        context.runtime_action_events.append(
            action_event
        )

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

    resolve_active_memory_count = sum(
        1
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY
    )

    save_delayed_memory_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT
    ]

    list_skill_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_LIST_SKILLS
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
            saved_asset_results.append(
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
            append_asset_runtime_result(
                context,
                result,
            )
            saved_asset_results.append(
                result
            )

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
                action_id = build_runtime_action_id(
                    result_action
                    or action_name,
                    first_asset_result_index
                    + result_index,
                )
                await emit(with_action_context({
                    "type": "runtime_action",
                    "action": action_name,
                    "id": action_id,
                    "text": text,
                    "asset_result": result,
                }))
                await emit({
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
                })

    skill_state_results = (
        appended_skill_results
        + removed_skill_results
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
        text = (
            f"Appended skill: {requested_skill}"
            if result_action == "append_skill"
            else f"Removed skill: {requested_skill}"
        )
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
                await emit(with_action_context({
                    "type": "runtime_action",
                    "action": result_action,
                    "id": action_id,
                    "text": text,
                    "skill_result": result,
                }))
                await emit({
                    "type": "runtime_action",
                    "action": result_action,
                    "id": action_id,
                    "status": "completed",
                    "text": text,
                    "skill_result": result,
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

    if create_active_memory_count:
        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] create_active_memory requested"
            )

        for active_memory_text in (
            action.payload
            for action in create_active_memory_actions
            if action.payload
        ):
            record_created = (
                await create_active_memory_runtime_record(
                    context,
                    active_memory_text,
                )
            )

            if record_created:
                created_active_memory_texts.append(
                    active_memory_text
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
            for active_memory_text in created_active_memory_texts:
                active_memory_line = (
                    getattr(context, "active_memory_records", []) or []
                )[-1] if getattr(context, "active_memory_records", []) else ""
                await emit(with_action_context({
                    "type": "runtime_action",
                    "action": "create_active_memory",
                    "text": f"Saving: {active_memory_text}",
                    "active_memory": active_memory_line,
                }))

    saved_delayed_memory_reports = []

    if save_delayed_memory_actions:
        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] save_delayed_memory requested"
            )

        for action in save_delayed_memory_actions:
            report = build_delayed_memory_report(
                context,
                action.payload,
            )

            if not report:
                continue

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
                await emit({
                    "type": "runtime_action",
                    "action": "save_delayed_memory_content",
                    "status": "completed",
                    "text": "Saving delayed memory",
                    "delayed_memory_report": report,
                })

    resolved_active_memory_count = 0

    if resolve_active_memory_count:
        active_memory_resolve_text = next(
            (
                action.payload
                for action in filtered_actions
                if action.name == RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY
                and action.payload
            ),
            "",
        )

        record_resolved, active_memory_id = (
            await resolve_active_memory_runtime_record(
                context,
                active_memory_resolve_text,
            )
        )

        if record_resolved:
            resolved_active_memory_count = 1

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

        if (
            emit is not None
            and record_resolved
        ):
            await emit(with_action_context({
                "type": "runtime_action",
                "action": "resolve_active_memory",
                "id": active_memory_id,
                "text": "Active memory resolved",
            }))

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


