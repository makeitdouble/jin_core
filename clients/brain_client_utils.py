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


import re
from xml.etree import ElementTree

from rules.loop_rules import (
    LOOP_RULES,
)
from rules.runtime import (
    RUNTIME_ACTION_CREATE_ACTIVE_MEMORY,
    RUNTIME_ACTION_SAVE_SESSION,
    RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY,
    RUNTIME_ACTION_WEB_SEARCH,
)
from runtime.behavior_contract import (
    should_execute_action_guard,
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
    refresh_active_memory_runtime_metadata,
)


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


def should_execute_save_session(
    user_message: str,
) -> bool:
    return should_execute_action_guard(
        "save_session",
        user_message
    )



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


async def apply_runtime_action_calls(
    context,
    actions,
    user_message: str | None = None,
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
    resolved_user_message = resolve_runtime_action_user_message(
        context,
        user_message,
    )

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

        accepted_action_names.add(
            action_event_name
        )
        filtered_actions.append(
            action
        )

    if not filtered_actions:
        return 0

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
            await emit({
                "type": "runtime_action",
                "action": "save_session",
                "text": "Saving session",
            })

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
                await emit({
                    "type": "runtime_action",
                    "action": "create_active_memory",
                    "text": f"Saving: {active_memory_text}",
                    "active_memory": active_memory_line,
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

            if log_runtime is not None:
                await log_runtime(
                    "[RUNTIME ACTION] "
                    f"active_memory record resolved: {active_memory_id}"
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

        if (
            emit is not None
            and record_resolved
        ):
            await emit({
                "type": "runtime_action",
                "action": "resolve_active_memory",
                "id": active_memory_id,
                "text": "Active memory resolved",
            })

    return (
        len(
            search_queries
        )
        + min(
            save_session_count,
            1,
        )
        + len(
            created_active_memory_texts
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


def has_loop_rule_signal(
    context=None,
) -> bool:

    if context is None:
        return False

    pattern_counter = getattr(
        context,
        "runtime_pattern_counter",
        0,
    )

    try:
        return int(
            pattern_counter
        ) > 1
    except (
        TypeError,
        ValueError,
    ):
        return False



def build_conditional_prompt_rules(
    context=None,
) -> str:

    rules = [
        ""
    ]

    if has_loop_rule_signal(
        context
    ):
        rules.append(
            LOOP_RULES
        )

    return "".join(
        rules
    )
