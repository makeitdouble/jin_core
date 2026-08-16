import re

from fastapi import WebSocket

from .logger import WebSocketLogger

from runtime.runtime_context import RuntimeContext, RuntimeEmitter
from runtime.L1_memory import (
    build_runtime_memory_snapshot,
    parse_runtime_memory_lines,
)
from runtime.L1_memory_utils import (
    build_runtime_memory_context_text,
    canonicalize_runtime_memory_key,
    emit_runtime_l1_diff_update,
    emit_runtime_memory_snapshot_refresh,
    emit_runtime_session_memory_update,
    rebuild_latest_runtime_memory_snapshot,
    remove_runtime_user_idle_lines,
)
from runtime.L3_memory_utils import parse_l3_session_snapshot_metadata
from runtime.telemetry import send_telemetry
from utils.actions import (
    is_active_memory_key,
    is_delayed_memory_report_id,
    refresh_active_memory_runtime_metadata,
    remove_active_memory_entries,
)
from utils.chat_log import (
    resume_chat_log_session,
)
from utils.delayed_memory_file_store import (
    load_delayed_memory_reports_from_files,
    merge_delayed_memory_reports,
    normalize_delayed_memory_reports,
)


MAX_BOOTSTRAP_MEMORY_CHARS = 12000
MAX_RESUME_CLIENT_ID_CHARS = 80
RESUME_CLIENT_ID_RE = re.compile(
    r"[^a-zA-Z0-9_.:-]"
)


ACTIVE_MEMORY_LINE_RE = re.compile(
    r"^\s*active_memory(?:_\d+)?\s*:",
    re.IGNORECASE,
)


def clean_active_memory_records(value) -> list[str]:

    records = []

    if isinstance(value, list):
        candidates = value
    else:
        candidates = str(value or "").splitlines()

    seen = set()

    for candidate in candidates:
        line = clean_bootstrap_memory(
            str(candidate or ""),
            limit=2000,
        )

        if not ACTIVE_MEMORY_LINE_RE.match(line):
            continue

        if line in seen:
            continue

        seen.add(line)
        records.append(line)

    return records


def apply_active_memory_records(
    context,
    message_data: dict,
) -> None:

    records = clean_active_memory_records(
        message_data.get(
            "active_memory_records",
            [],
        )
    )

    context.active_memory_records = records


def active_memory_records_text(context) -> str:

    return "\n".join(
        str(record or "").strip()
        for record in getattr(
            context,
            "active_memory_records",
            [],
        )
        if str(record or "").strip()
    )


def clean_delayed_memory_reports(value) -> dict:

    return normalize_delayed_memory_reports(
        value
    )


def clean_deleted_delayed_memory_report_ids(value) -> list[str]:

    source = value if isinstance(value, list) else [value]
    report_ids = []
    seen = set()

    for item in source:
        report_id = str(
            item
            or ""
        ).strip().casefold()

        if (
            not report_id
            or report_id in seen
            or not is_delayed_memory_report_id(
                report_id
            )
        ):
            continue

        seen.add(
            report_id
        )
        report_ids.append(
            report_id
        )

    return report_ids


def clean_loaded_delayed_memory_report_ids(value) -> list[str]:

    source = value if isinstance(value, list) else [value]
    report_ids = []
    seen = set()

    for item in source:
        report_id = str(
            item
            or ""
        ).strip().casefold()

        if (
            not report_id
            or report_id in seen
            or not is_delayed_memory_report_id(
                report_id
            )
        ):
            continue

        seen.add(report_id)
        report_ids.append(report_id)

    return report_ids


def apply_loaded_delayed_memory_ids(
    context,
    message_data: dict,
) -> list[str]:

    if "loaded_delayed_memory_ids" in message_data:
        raw_ids = message_data.get(
            "loaded_delayed_memory_ids",
            [],
        )
    elif "loaded_memory_ids" in message_data:
        raw_ids = message_data.get(
            "loaded_memory_ids",
            [],
        )
    else:
        return list(
            getattr(
                context,
                "runtime_loaded_delayed_memory_ids",
                [],
            )
            or []
        )

    requested_ids = clean_loaded_delayed_memory_report_ids(
        raw_ids
    )
    reports = getattr(
        context,
        "delayed_memory_reports",
        {},
    )
    reports = reports if isinstance(reports, dict) else {}
    loaded_reports = {}
    loaded_ids = []

    for report_id in requested_ids:
        report = reports.get(report_id)

        if not isinstance(report, dict):
            continue

        loaded_ids.append(report_id)
        loaded_reports[report_id] = {
            **report,
            "id": report_id,
        }

    context.runtime_loaded_delayed_memory = loaded_reports
    context.runtime_loaded_delayed_memory_ids = loaded_ids

    from runtime.L4_memory import (
        refresh_runtime_l4_archived_fact_ids,
    )

    refresh_runtime_l4_archived_fact_ids(
        context
    )

    return loaded_ids


def get_context_loaded_delayed_memory_ids(
    context,
) -> list[str]:

    loaded_reports = getattr(
        context,
        "runtime_loaded_delayed_memory",
        {},
    )

    if not isinstance(loaded_reports, dict):
        return []

    return clean_loaded_delayed_memory_report_ids(
        list(loaded_reports.keys())
    )


def apply_suppressed_delayed_memory_auto_load_ids(
    context,
    message_data: dict,
) -> list[str]:

    # Accept the old key only as a one-way migration path. Runtime state and
    # outgoing protocol use LOAD terminology exclusively.
    raw_ids = message_data.get(
        "suppressed_delayed_memory_auto_load_ids",
        message_data.get(
            "suppressed_delayed_memory_" + "append_ids",
            getattr(
                context,
                "runtime_suppressed_delayed_memory_auto_load_ids",
                [],
            ),
        ),
    )

    report_ids = clean_loaded_delayed_memory_report_ids(
        raw_ids
    )
    reports = getattr(
        context,
        "delayed_memory_reports",
        {},
    )
    reports = reports if isinstance(reports, dict) else {}
    report_ids = [
        report_id
        for report_id in report_ids
        if report_id in reports
    ]

    context.runtime_suppressed_delayed_memory_auto_load_ids = report_ids

    return report_ids


def apply_delayed_memory_reports(
    context,
    message_data: dict,
) -> list[str]:

    deleted_report_ids = clean_deleted_delayed_memory_report_ids(
        message_data.get(
            "deleted_delayed_memory_report_ids",
            [],
        )
    )

    if (
        "delayed_memory_reports" not in message_data
        and not deleted_report_ids
    ):
        return []

    incoming_reports = clean_delayed_memory_reports(
        message_data.get(
            "delayed_memory_reports",
            {},
        )
    )
    existing_reports = clean_delayed_memory_reports(
        getattr(
            context,
            "delayed_memory_reports",
            {},
        )
    )

    for report_id in deleted_report_ids:
        existing_reports.pop(
            report_id,
            None,
        )

    context.delayed_memory_reports = {
        **existing_reports,
        **incoming_reports,
    }

    loaded_reports = getattr(
        context,
        "runtime_loaded_delayed_memory",
        None,
    )

    if isinstance(
        loaded_reports,
        dict,
    ):
        for report_id in deleted_report_ids:
            loaded_reports.pop(
                report_id,
                None,
            )

    loaded_ids = getattr(
        context,
        "runtime_loaded_delayed_memory_ids",
        None,
    )

    if isinstance(
        loaded_ids,
        list,
    ):
        deleted_report_id_set = set(
            deleted_report_ids
        )
        loaded_ids[:] = [
            report_id
            for report_id in loaded_ids
            if str(report_id or "").strip().casefold()
            not in deleted_report_id_set
        ]

    from runtime.L4_memory import (
        refresh_runtime_l4_archived_fact_ids,
    )

    refresh_runtime_l4_archived_fact_ids(
        context
    )

    return deleted_report_ids


def hydrate_delayed_memory_reports_from_files(
    context,
) -> None:

    file_reports, warnings = (
        load_delayed_memory_reports_from_files()
    )
    current_reports = clean_delayed_memory_reports(
        getattr(
            context,
            "delayed_memory_reports",
            {},
        )
    )

    context.delayed_memory_reports = merge_delayed_memory_reports(
        current_reports,
        file_reports,
    )

    from runtime.L4_memory import (
        refresh_runtime_l4_archived_fact_ids,
    )

    refresh_runtime_l4_archived_fact_ids(
        context
    )

    if warnings:
        current_warnings = getattr(
            context,
            "runtime_delayed_memory_file_warnings",
            None,
        )

        if not isinstance(
            current_warnings,
            list,
        ):
            current_warnings = []
            context.runtime_delayed_memory_file_warnings = (
                current_warnings
            )

        current_warnings.extend(
            warning
            for warning in warnings
            if warning not in current_warnings
        )


def remove_runtime_memory_slot_by_key(
        memory: str,
        key: str,
) -> tuple[str, bool]:

    normalized_key = canonicalize_runtime_memory_key(
        str(key or "")
    )

    if not normalized_key:
        return str(memory or "").strip(), False

    kept_lines = []
    removed = False

    for raw_line in str(memory or "").splitlines():
        line = raw_line.strip().lstrip("-").strip()

        if not line:
            continue

        if ":" not in line:
            kept_lines.append(raw_line)
            continue

        line_key, _ = line.split(":", 1)

        if (
                canonicalize_runtime_memory_key(line_key)
                == normalized_key
        ):
            removed = True
            continue

        kept_lines.append(raw_line)

    return "\n".join(
        line.strip()
        for line in kept_lines
        if str(line).strip()
    ).strip(), removed


async def apply_runtime_memory_slot_delete(
        context,
        message_data: dict,
) -> bool:

    key = str(
        message_data.get("key", "")
    ).strip()

    normalized_key = canonicalize_runtime_memory_key(
        key
    )

    if (
            not normalized_key
            or normalized_key == "user_idle"
            or is_active_memory_key(normalized_key)
    ):
        return False

    current_memory = str(
        getattr(
            context,
            "runtime_memory",
            "",
        )
        or ""
    )

    next_memory, removed = remove_runtime_memory_slot_by_key(
        current_memory,
        key,
    )

    if not removed or next_memory == current_memory.strip():
        return False

    context.runtime_memory = next_memory
    context.runtime_memory_stable = next_memory
    context.runtime_memory_updates = int(
        getattr(
            context,
            "runtime_memory_updates",
            0,
        )
        or 0
    ) + 1

    snapshot = rebuild_latest_runtime_memory_snapshot(
        context
    )

    if snapshot is None:
        snapshot = build_runtime_memory_snapshot(
            context,
            context.runtime_memory,
        )
        context.runtime_memory_snapshots = [snapshot]
        context.runtime_memory_snapshot_index = snapshot.get(
            "index",
            0,
        )

    snapshot["runtime_memory_updates"] = (
        context.runtime_memory_updates
    )
    snapshot["local_runtime_memory_delete"] = True
    snapshot["deleted_runtime_memory_key"] = normalized_key

    await emit_runtime_memory_snapshot_refresh(
        context,
        snapshot,
    )
    await emit_runtime_l1_diff_update(
        context
    )

    await context.logger.log_system(
        f"[RUNTIME MEMORY] slot deleted: {normalized_key}"
    )

    return True


def clean_bootstrap_memory(
    value,
    *,
    limit: int = MAX_BOOTSTRAP_MEMORY_CHARS,
) -> str:

    if not isinstance(
        value,
        str,
    ):
        return ""

    cleaned = value.replace(
        "\x00",
        "",
    ).strip()

    if len(cleaned) <= limit:
        return cleaned

    return cleaned[-limit:].strip()


def clean_bootstrap_runtime_memory(
    value,
    *,
    limit: int = MAX_BOOTSTRAP_MEMORY_CHARS,
) -> str:

    return remove_active_memory_entries(
        remove_runtime_user_idle_lines(
            clean_bootstrap_memory(
                value,
                limit=limit,
            )
        )
    ).strip()




def normalize_resume_client_id(
    value,
) -> str:

    if not isinstance(
        value,
        str,
    ):
        return ""

    cleaned = RESUME_CLIENT_ID_RE.sub(
        "",
        value,
    ).strip()

    return cleaned[:MAX_RESUME_CLIENT_ID_CHARS]


def is_soft_resume_request(
    websocket: WebSocket,
) -> bool:

    return (
        websocket.query_params.get(
            "resume",
            "",
        ) == "soft"
    )


def get_resume_context_store(
    websocket: WebSocket,
) -> dict:

    store = getattr(
        websocket.app.state,
        "websocket_runtime_contexts",
        None,
    )

    if store is None:
        store = {}
        websocket.app.state.websocket_runtime_contexts = store

    return store


def attach_websocket_to_context(
    context: RuntimeContext,
    websocket: WebSocket,
    logger: WebSocketLogger,
):

    context.websocket = websocket
    context.emitter = RuntimeEmitter(
        websocket
    )
    context.logger = logger
    context.clients = websocket.app.state.clients


def hydrate_attached_files_from_store(context) -> None:
    from utils.attached_files_store import (
        get_pinned_file_ids,
        hydrate_attachment_ids,
    )

    file_ids = get_pinned_file_ids()
    attachments = hydrate_attachment_ids(file_ids)
    context.runtime_attached_file_ids = list(file_ids)
    context.runtime_turn_attachments = list(attachments)
    context.runtime_current_sequence_attachments = list(attachments)


def get_or_create_connection_context(
    websocket: WebSocket,
    logger: WebSocketLogger,
) -> tuple[RuntimeContext, bool]:

    client_id = normalize_resume_client_id(
        websocket.query_params.get(
            "client_id",
            "",
        )
    )

    if not client_id:
        context = RuntimeContext(
            websocket=websocket,
            emitter=RuntimeEmitter(
                websocket
            ),
            logger=logger,
            clients=websocket.app.state.clients,
        )
        hydrate_delayed_memory_reports_from_files(
            context
        )
        hydrate_attached_files_from_store(
            context
        )

        return context, False

    store = get_resume_context_store(
        websocket
    )

    existing_context = store.get(
        client_id
    )

    if isinstance(
        existing_context,
        RuntimeContext,
    ):
        attach_websocket_to_context(
            existing_context,
            websocket,
            logger,
        )
        existing_context.session_id = client_id
        hydrate_delayed_memory_reports_from_files(
            existing_context
        )
        hydrate_attached_files_from_store(
            existing_context
        )
        return existing_context, True

    context = RuntimeContext(
        websocket=websocket,
        emitter=RuntimeEmitter(
            websocket
        ),
        logger=logger,
        clients=websocket.app.state.clients,
        session_id=client_id,
    )
    resume_chat_log_session(
        context
    )
    hydrate_delayed_memory_reports_from_files(
        context
    )
    hydrate_attached_files_from_store(
        context
    )

    store[client_id] = context

    return context, False


def ensure_initial_runtime_snapshot(
    context: RuntimeContext,
):

    if getattr(
        context,
        "runtime_memory_snapshots",
        [],
    ):
        return

    initial_snapshot = build_runtime_memory_snapshot(
        context,
        context.runtime_memory,
    )

    context.runtime_memory_snapshots.append(
        initial_snapshot
    )

    context.runtime_memory_snapshot_index = 0


def runtime_snapshot_has_user_idle(
    snapshot,
) -> bool:

    if not isinstance(
        snapshot,
        dict,
    ):
        return False

    for line in snapshot.get(
        "lines",
        [],
    ) or []:
        if not isinstance(
            line,
            dict,
        ):
            continue

        key = str(
            line.get(
                "key",
                "",
            )
            or ""
        ).strip().lower()

        if key == "user_idle":
            return True

    return any(
        raw_line.strip().lower().startswith(
            "user_idle:"
        )
        for raw_line in str(
            snapshot.get(
                "raw_memory",
                "",
            )
            or ""
        ).splitlines()
    )


def attach_user_idle_to_initial_runtime_snapshot(
    context,
):

    if getattr(
        context,
        "user_message_count",
        0,
    ) != 0:
        return

    snapshots = getattr(
        context,
        "runtime_memory_snapshots",
        [],
    )

    if not snapshots:
        return

    initial_snapshot = snapshots[0]

    if runtime_snapshot_has_user_idle(
        initial_snapshot
    ):
        return

    raw_memory = str(
        initial_snapshot.get(
            "raw_memory",
            "",
        )
        or ""
    )

    if not is_default_runtime_memory_text(
        raw_memory
    ):
        return

    display_memory = build_runtime_memory_context_text(
        getattr(
            context,
            "runtime_memory",
            "",
        ),
        context,
    )

    if "user_idle:" not in display_memory:
        return

    initial_snapshot["raw_memory"] = display_memory
    initial_snapshot["lines"] = parse_runtime_memory_lines(
        display_memory
    )




def parse_bootstrap_counter(
    value,
) -> int:

    try:
        return max(
            0,
            int(
                value
                or 0
            ),
        )
    except (
        TypeError,
        ValueError,
    ):
        return 0


def runtime_snapshot_has_pheromone_strength(
    snapshot: dict,
) -> bool:

    if not isinstance(
        snapshot,
        dict,
    ):
        return False

    lines = snapshot.get(
        "lines",
        [],
    )

    if not isinstance(
        lines,
        list,
    ):
        return False

    return any(
        isinstance(line, dict)
        and line.get("strength") is not None
        for line in lines
    )


def build_restored_runtime_pheromone_snapshot(
    runtime_snapshot: dict,
    runtime_memory: str,
    *,
    index: int = 0,
) -> dict | None:

    if not runtime_snapshot_has_pheromone_strength(
        runtime_snapshot
    ):
        return None

    snapshot_memory = clean_bootstrap_memory(
        runtime_snapshot.get(
            "raw_memory",
            "",
        )
    )

    if snapshot_memory != runtime_memory:
        return None

    lines = [
        line
        for line in runtime_snapshot.get(
            "lines",
            [],
        )
        if isinstance(
            line,
            dict,
        )
    ]

    if not lines:
        return None

    return {
        **runtime_snapshot,
        "index": index,
        "raw_memory": runtime_memory,
        "lines": lines,
        "display_source": "restored_runtime_pheromone_snapshot",
        "restored_pheromone_strength": True,
    }


def build_l3_bootstrap_runtime_memory(
    *,
    session_memory_updates: int,
) -> str:

    return (
        "session status: Restored from saved L3 session memory; browser L1 runtime snapshot was stale and was ignored.\n"
        "current context: Use restored session_memory as the source of truth until new L1 runtime facts are created.\n"
        f"session memory source: browser restore; L3 updates restored: {session_memory_updates}.\n"
        "last_jin_response: Browser session restore completed; awaiting the user's next message."
    )


def should_ignore_bootstrap_runtime_memory(
    *,
    session_memory: str,
    runtime_memory: str,
    session_memory_updates: int,
    runtime_memory_updates: int,
    runtime_memory_is_snapshot_fallback: bool = False,
) -> bool:

    if not (
        session_memory
        and runtime_memory
    ):
        return False

    # Only reject L1 during browser/L3 bootstrap when it was inferred from an
    # unconfirmed runtime_snapshot.raw_memory fallback. An explicitly persisted
    # session runtime is the exact L1 state saved with the session, so it must
    # survive bootstrap even if its L1 counter is lower than the L3 counter.
    if not runtime_memory_is_snapshot_fallback:
        return False

    if runtime_memory_updates == 0:
        return True

    if (
        session_memory_updates > 0
        and runtime_memory_updates < session_memory_updates
    ):
        return True

    return False


async def emit_current_runtime_memory(
    context,
):

    snapshots = getattr(
        context,
        "runtime_memory_snapshots",
        [],
    )

    if snapshots:
        snapshot_index = max(
            0,
            min(
                getattr(
                    context,
                    "runtime_memory_snapshot_index",
                    0,
                ),
                len(snapshots) - 1,
            ),
        )
        snapshot = snapshots[snapshot_index]
    else:
        snapshot = build_runtime_memory_snapshot(
            context,
            context.runtime_memory,
        )

    await context.emitter.emit({
        "type": "runtime_memory_update",
        "memory": snapshot.get(
            "raw_memory",
            context.runtime_memory,
        ),
        "updates": getattr(
            context,
            "runtime_memory_updates",
            0,
        ),
        "snapshot": snapshot,
        "snapshots_count": len(
            snapshots
        ) or 1,
        "snapshot_index": snapshot.get(
            "index",
            0,
        ),
    })



def is_default_runtime_memory_text(
    value: str,
) -> bool:

    text = str(
        value
        or ""
    ).strip()

    if ":" in text:
        key, candidate = text.split(
            ":",
            1,
        )

        if key.strip().lower() == "note":
            text = candidate.strip()

    normalized = " ".join(
        text.split()
    ).lower()

    return normalized == (
        "this session has just begun. "
        "you have no history with the user yet."
    ).lower()


ACTIVE_MEMORY_JIN_MESSAGE_COUNTER_RE = re.compile(
    (
        r"\[\s*"
        r"(?P<name>created_jin_message_number|elapsed_jin_message_number)"
        r"\s*:\s*(?P<value>-?\d+)"
        r"\s*\]"
    ),
    re.IGNORECASE,
)


def _parse_runtime_int_value(
    value,
) -> int | None:

    try:
        return int(
            str(value).strip()
        )
    except (TypeError, ValueError):
        return None


def _active_memory_jin_message_floor(
    runtime_memory: str,
) -> int:

    max_message_number = 0

    for line in parse_runtime_memory_lines(
        runtime_memory
    ):
        key = (
            line.get(
                "key",
                "",
            )
            or ""
        ).strip()

        if not is_active_memory_key(
            key
        ):
            continue

        suffix_values = {}

        for match in ACTIVE_MEMORY_JIN_MESSAGE_COUNTER_RE.finditer(
            str(
                line.get(
                    "value",
                    "",
                )
                or ""
            )
        ):
            parsed_value = _parse_runtime_int_value(
                match.group(
                    "value"
                )
            )

            if parsed_value is None:
                continue

            suffix_values[
                match.group(
                    "name"
                ).casefold()
            ] = max(
                0,
                parsed_value,
            )

        created_message_number = suffix_values.get(
            "created_jin_message_number"
        )
        elapsed_message_number = suffix_values.get(
            "elapsed_jin_message_number",
            0,
        )

        if created_message_number is None:
            continue

        max_message_number = max(
            max_message_number,
            created_message_number + elapsed_message_number,
        )

    return max_message_number


def _raise_runtime_counter_floor(
    context,
    field_name: str,
    floor: int,
):

    if floor <= 0:
        return

    current_value = _parse_runtime_int_value(
        getattr(
            context,
            field_name,
            0,
        )
    ) or 0

    if current_value >= floor:
        return

    setattr(
        context,
        field_name,
        floor,
    )


def hydrate_runtime_counters_from_bootstrap_metadata(
    context,
    message_data: dict,
):

    if not isinstance(
        message_data,
        dict,
    ):
        return

    runtime_snapshot = message_data.get(
        "runtime_snapshot",
        {},
    )

    snapshot_data = (
        runtime_snapshot
        if isinstance(
            runtime_snapshot,
            dict,
        )
        else {}
    )

    for field_name in (
        "turn_number",
        "runtime_turn_counter",
        "user_message_count",
        "assistant_message_count",
    ):
        floor = parse_bootstrap_counter(
            message_data.get(
                field_name,
                snapshot_data.get(
                    field_name,
                    0,
                ),
            )
        )

        _raise_runtime_counter_floor(
            context,
            field_name,
            floor,
        )


def hydrate_runtime_counters_from_active_memory(
    context,
    runtime_memory: str,
):

    message_floor = _active_memory_jin_message_floor(
        runtime_memory
    )

    if message_floor <= 0:
        return

    for field_name in (
        "turn_number",
        "assistant_message_count",
        "user_message_count",
    ):
        _raise_runtime_counter_floor(
            context,
            field_name,
            message_floor,
        )


def refresh_restored_active_memory_runtime_metadata(
    context,
    runtime_memory: str,
) -> str:

    runtime_memory = str(
        runtime_memory
        or ""
    ).strip()

    if not runtime_memory:
        return ""

    hydrate_runtime_counters_from_active_memory(
        context,
        runtime_memory,
    )

    return refresh_active_memory_runtime_metadata(
        runtime_memory,
        previous_memory=runtime_memory,
        context=context,
    )


def apply_runtime_resume(
    context,
    message_data: dict,
) -> bool:

    apply_active_memory_records(
        context,
        message_data,
    )
    apply_delayed_memory_reports(
        context,
        message_data,
    )
    apply_loaded_delayed_memory_ids(
        context,
        message_data,
    )

    session_memory = clean_bootstrap_memory(
        message_data.get(
            "session_memory",
            "",
        )
    )
    session_memory_updates = parse_bootstrap_counter(
        message_data.get(
            "session_memory_updates",
            0,
        )
    )
    current_session_memory_updates = parse_bootstrap_counter(
        getattr(
            context,
            "runtime_session_memory_updates",
            0,
        )
    )
    session_memory_restored = False

    if (
        session_memory
        and (
            not str(
                getattr(
                    context,
                    "session_memory",
                    "",
                )
                or ""
            ).strip()
            or session_memory_updates > current_session_memory_updates
        )
    ):
        context.session_memory = session_memory
        context.runtime_l3_session_memory = session_memory
        context.runtime_session_memory_updates = max(
            current_session_memory_updates,
            session_memory_updates,
        )
        context.runtime_l3_saved_runtime_snapshot_index = None
        context.session_memory_source = clean_bootstrap_memory(
            message_data.get(
                "session_memory_source",
                "browser_soft_reconnect",
            ),
            limit=80,
        ) or "browser_soft_reconnect"
        session_memory_restored = True

    runtime_memory = clean_bootstrap_runtime_memory(
        message_data.get(
            "runtime_memory",
            "",
        )
    )

    runtime_snapshot = message_data.get(
        "runtime_snapshot",
        {},
    )

    runtime_memory_is_snapshot_fallback = False

    if (
        not runtime_memory
        and isinstance(
            runtime_snapshot,
            dict,
        )
    ):
        runtime_memory = clean_bootstrap_runtime_memory(
            runtime_snapshot.get(
                "raw_memory",
                "",
            )
        )
        runtime_memory_is_snapshot_fallback = True

    if (
        not runtime_memory
        or is_default_runtime_memory_text(
            runtime_memory
        )
    ):
        return session_memory_restored

    hydrate_runtime_counters_from_bootstrap_metadata(
        context,
        message_data,
    )

    runtime_memory_updates = parse_bootstrap_counter(
        message_data.get(
            "runtime_memory_updates",
            0,
        )
    )

    if runtime_memory_is_snapshot_fallback:
        runtime_memory_updates = 0

    active_memory_text = active_memory_records_text(
        context
    )

    if active_memory_text:
        hydrate_runtime_counters_from_active_memory(
            context,
            active_memory_text,
        )

    runtime_memory = refresh_restored_active_memory_runtime_metadata(
        context,
        runtime_memory,
    )

    current_updates = parse_bootstrap_counter(
        getattr(
            context,
            "runtime_memory_updates",
            0,
        )
    )

    current_memory = clean_bootstrap_memory(
        getattr(
            context,
            "runtime_memory",
            "",
        )
    )

    if (
        current_memory
        and not is_default_runtime_memory_text(
            current_memory
        )
        and current_updates >= runtime_memory_updates
    ):
        return session_memory_restored

    restored_pheromone_snapshot = (
        build_restored_runtime_pheromone_snapshot(
            runtime_snapshot,
            runtime_memory,
        )
        if isinstance(
            runtime_snapshot,
            dict,
        )
        else None
    )

    context.runtime_memory = runtime_memory
    context.runtime_memory_stable = runtime_memory
    context.runtime_memory_updates = max(
        current_updates,
        runtime_memory_updates,
    )

    if restored_pheromone_snapshot:
        restored_snapshot = {
            **restored_pheromone_snapshot,
            "index": 0,
            "runtime_memory_updates": context.runtime_memory_updates,
        }
    else:
        restored_snapshot = build_runtime_memory_snapshot(
            context,
            runtime_memory,
        )

    context.runtime_memory_snapshots = [
        restored_snapshot
    ]
    context.runtime_memory_snapshot_index = 0

    return True


def apply_session_bootstrap(
    context,
    message_data: dict,
) -> bool:

    apply_active_memory_records(
        context,
        message_data,
    )
    apply_delayed_memory_reports(
        context,
        message_data,
    )
    apply_loaded_delayed_memory_ids(
        context,
        message_data,
    )

    session_memory = clean_bootstrap_memory(
        message_data.get(
            "session_memory",
            "",
        )
    )

    runtime_memory = clean_bootstrap_runtime_memory(
        message_data.get(
            "runtime_memory",
            "",
        )
    )

    runtime_snapshot = message_data.get(
        "runtime_snapshot",
        {},
    )
    # Track whether runtime_memory was inferred from runtime_snapshot.raw_memory
    # rather than being sent explicitly by the client.
    runtime_memory_is_snapshot_fallback = False

    if (
        not runtime_memory
        and isinstance(
            runtime_snapshot,
            dict,
        )
    ):
        runtime_memory = clean_bootstrap_runtime_memory(
            runtime_snapshot.get(
                "raw_memory",
                "",
            )
        )
        runtime_memory_is_snapshot_fallback = True

    has_bootstrap_content = bool(
        session_memory
        or runtime_memory
    )

    if has_bootstrap_content:
        hydrate_runtime_counters_from_bootstrap_metadata(
            context,
            message_data,
        )

    session_memory_updates = parse_bootstrap_counter(
        message_data.get(
            "session_memory_updates",
            message_data.get(
                "runtime_session_memory_updates",
                0,
            ),
        )
    )
    runtime_memory_updates = parse_bootstrap_counter(
        message_data.get(
            "runtime_memory_updates",
            0,
        )
    )

    # If runtime_memory arrived only through snapshot fallback and L3 exists,
    # force the L1 counter to 0 so stale bootstrap logic can reject it.
    if (
        runtime_memory_is_snapshot_fallback
        and session_memory
    ):
        runtime_memory_updates = 0

    # Preserve the original stale snapshot raw text for UI display before
    # replacing runtime_memory with the agent-facing status message.
    stale_runtime_memory_for_ui = None

    if should_ignore_bootstrap_runtime_memory(
        session_memory=session_memory,
        runtime_memory=runtime_memory,
        session_memory_updates=session_memory_updates,
        runtime_memory_updates=runtime_memory_updates,
        runtime_memory_is_snapshot_fallback=runtime_memory_is_snapshot_fallback,
    ):
        stale_runtime_memory_for_ui = runtime_memory
        runtime_memory = build_l3_bootstrap_runtime_memory(
            session_memory_updates=session_memory_updates,
        )
        runtime_memory_updates = 0

    active_memory_text = active_memory_records_text(
        context
    )

    if active_memory_text:
        hydrate_runtime_counters_from_active_memory(
            context,
            active_memory_text,
        )

    if runtime_memory and not stale_runtime_memory_for_ui:
        runtime_memory = refresh_restored_active_memory_runtime_metadata(
            context,
            runtime_memory,
        )

    if session_memory:
        session_metadata = parse_l3_session_snapshot_metadata(
            session_memory
        )

        context.session_memory = session_memory
        context.runtime_l3_session_memory = session_memory
        context.runtime_l3_session_first_turn = session_metadata.get(
            "session_snapshot_first_turn"
        )
        context.runtime_l3_session_last_turn = session_metadata.get(
            "session_snapshot_last_turn"
        )
        # Do not restore runtime_l3_saved_runtime_snapshot_index from browser L3.
        # Runtime snapshot indexes are window-local and may restart after reload;
        # only same-process saves use that marker to avoid re-feeding old UI pages.
        context.runtime_l3_saved_runtime_snapshot_index = None
        context.runtime_session_memory_updates = max(
            session_memory_updates,
            getattr(
                context,
                "runtime_session_memory_updates",
                0,
            ),
        )
        context.session_memory_source = clean_bootstrap_memory(
            message_data.get(
                "session_memory_source",
                "browser",
            ),
            limit=80,
        ) or "browser"

    if runtime_memory:
        restored_pheromone_snapshot = (
            build_restored_runtime_pheromone_snapshot(
                runtime_snapshot,
                runtime_memory,
            )
            if not stale_runtime_memory_for_ui
            else None
        )

        # Bootstrap should replace the initial/default runtime page, not append
        # extra pages. If L3 made the saved L1 runtime stale, the stale snapshot
        # must not stay visible as a separate page. If pheromone persistence is
        # enabled and the saved snapshot matches runtime_memory, keep that
        # snapshot as the single restored baseline so the next L1 update can
        # continue strength calculations from it.
        context.runtime_memory_snapshots = []
        context.runtime_memory_snapshot_index = 0

        context.runtime_memory = runtime_memory
        context.runtime_memory_stable = runtime_memory

        try:
            context.runtime_memory_updates = max(
                runtime_memory_updates,
                getattr(
                    context,
                    "runtime_memory_updates",
                    0,
                ),
            )
        except (
            TypeError,
            ValueError,
        ):
            pass

        if restored_pheromone_snapshot:
            restored_snapshot = {
                **restored_pheromone_snapshot,
                "index": 0,
                "runtime_memory_updates": getattr(
                    context,
                    "runtime_memory_updates",
                    runtime_memory_updates,
                ),
            }
        else:
            restored_snapshot = build_runtime_memory_snapshot(
                context,
                context.runtime_memory,
            )

        context.runtime_memory_snapshots.append(
            restored_snapshot
        )
        context.runtime_memory_snapshot_index = 0

    return bool(
        session_memory
        or runtime_memory
    )


# ---------------------------------------------------------
# CONNECTION SETUP
# ---------------------------------------------------------

async def emit_delayed_memory_store_snapshot(
    context,
) -> None:

    reports = clean_delayed_memory_reports(
        getattr(
            context,
            "delayed_memory_reports",
            {},
        )
    )

    await context.emitter.emit({
        "type": "delayed_memory_store_snapshot",
        "delayed_memory_reports": reports,
        "loaded_delayed_memory_ids": (
            get_context_loaded_delayed_memory_ids(
                context
            )
        ),
    })


async def initialize_connection(
    context,
    *,
    skip_initial_runtime_state: bool = False,
):

    await context.websocket.accept()

    await send_telemetry(
        context
    )

    file_warnings = list(
        getattr(
            context,
            "runtime_delayed_memory_file_warnings",
            [],
        )
        or []
    )
    context.runtime_delayed_memory_file_warnings = []

    for warning in file_warnings:
        await context.logger.log_system(
            "[DELAYED MEMORY] " + str(warning)
        )

    await emit_delayed_memory_store_snapshot(
        context
    )

    from runtime.L4_memory import (
        emit_l4_memory_update,
    )

    await emit_l4_memory_update(
        context,
        change={
            "source": "file_bootstrap",
        },
    )

    if skip_initial_runtime_state:
        await context.logger.log_system(
            "[WS] soft reconnect: initial runtime state skipped"
        )
        return

    await emit_current_runtime_memory(
        context
    )

    await emit_runtime_l1_diff_update(
        context
    )

    await emit_runtime_session_memory_update(
        context
    )


# ---------------------------------------------------------
# RECEIVE MESSAGE
# ---------------------------------------------------------
