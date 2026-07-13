from fastapi import (
    APIRouter,
    WebSocket,
)

from starlette.websockets import (
    WebSocketDisconnect,
)

import asyncio
import contextlib
import json
import re
import time
import httpx

from websocket_logger import (
    WebSocketLogger,
)

from agent import (
    AgentRuntime,
    AgentState,
)

from clients import (
    build_brain_payload,
)
from clients.brain_client import (
    should_execute_save_session,
)
from rules.assembler import (
    build_brain_system_prompt,
)

from clients.brain_client_utils import (
    get_brain_runtime_config,
)

from utils.language import (
    contains_cyrillic,
)

from utils.token_usage import (
    format_token_usage_summary,
)

from config_loader import (
    config,
)

from utils.urls import (
    join_url,
)

from utils.tokens import (
    estimate_runtime_tokens,
)

from utils.ws_errors import (
    handle_fatal_runtime_error,
    handle_websocket_error,
)

from runtime import (
    RuntimeContext,
    RuntimeEmitter,
    apply_runtime_response_feedback,
    build_runtime_memory_snapshot,
    emit_runtime_l1_diff_update,
    emit_runtime_session_memory_update,
    refresh_runtime_state,
    run_fact_check_once,
    schedule_interrupted_runtime_memory_update,
    schedule_runtime_memory_update,
    send_telemetry,
)
from runtime.L1_memory_utils import (
    emit_runtime_memory_snapshot_refresh,
    rebuild_latest_runtime_memory_snapshot,
    build_runtime_memory_context_text,
    canonicalize_runtime_memory_key,
    remove_runtime_user_idle_lines,
)
from utils.runtime_actions import (
    is_active_memory_key,
    is_delayed_memory_report_id,
    refresh_active_memory_runtime_metadata,
    remove_active_memory_entries,
)
from utils.session_actions_history import (
    emit_session_actions_update,
)
from runtime.L1_memory import (
    parse_runtime_memory_lines,
)
from runtime.L3_memory_utils import (
    parse_l3_session_snapshot_metadata,
)
from runtime.runtime_context import (
    RECENT_MESSAGES_MAX_PAIRS,
)


websocket_router = APIRouter()

MAX_BOOTSTRAP_MEMORY_CHARS = 12000
RUNTIME_STATUS_CHECK_TIMEOUT = getattr(
    config,
    "STATUS_CHECK_TIMEOUT",
    0.5,
)

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

    if not isinstance(
        value,
        dict,
    ):
        return {}

    reports = {}

    for key, report in value.items():
        report_id = str(
            key
            or ""
        ).strip().casefold()

        if not is_delayed_memory_report_id(
            report_id
        ):
            continue

        if not isinstance(
            report,
            dict,
        ):
            continue

        title = clean_bootstrap_memory(
            str(
                report.get(
                    "title",
                    "",
                )
                or ""
            ),
            limit=500,
        )

        if not title:
            continue

        tags = report.get(
            "tags",
            [],
        )

        if isinstance(
            tags,
            list,
        ):
            clean_tags = [
                clean_bootstrap_memory(
                    str(tag or ""),
                    limit=80,
                )
                for tag in tags
                if clean_bootstrap_memory(
                    str(tag or ""),
                    limit=80,
                )
            ][:30]
        else:
            clean_tags = [
                clean_bootstrap_memory(
                    tag,
                    limit=80,
                )
                for tag in str(
                    tags
                    or ""
                ).split(",")
                if clean_bootstrap_memory(
                    tag,
                    limit=80,
                )
            ][:30]

        reports[report_id] = {
            "title": title,
            "summary": clean_bootstrap_memory(
                str(
                    report.get(
                        "summary",
                        "",
                    )
                    or ""
                ),
                limit=2000,
            ),
            "tags": clean_tags,
            "body": clean_bootstrap_memory(
                str(
                    report.get(
                        "body",
                        "",
                    )
                    or ""
                ),
                limit=12000,
            ),
            "created_session_id": clean_bootstrap_memory(
                str(
                    report.get(
                        "created_session_id",
                        "",
                    )
                    or ""
                ),
                limit=200,
            ),
            "created_time": clean_bootstrap_memory(
                str(
                    report.get(
                        "created_time",
                        "",
                    )
                    or ""
                ),
                limit=100,
            ),
        }

    return reports


def apply_delayed_memory_reports(
    context,
    message_data: dict,
) -> None:

    reports = clean_delayed_memory_reports(
        message_data.get(
            "delayed_memory_reports",
            {},
        )
    )

    if "delayed_memory_reports" in message_data:
        context.delayed_memory_reports = reports


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


def get_status_http_client(
    context,
):

    clients = getattr(
        context,
        "clients",
        {},
    )

    for runtime_client in clients.values():
        http_client = getattr(
            runtime_client,
            "client",
            None,
        )

        if http_client is not None:
            return http_client

    return None


async def check_model_status(
    http_client,
    base_url: str,
) -> bool:

    try:
        response = await http_client.get(
            join_url(
                base_url,
                config.MODELS_ENDPOINT,
            ),
            timeout=RUNTIME_STATUS_CHECK_TIMEOUT,
        )

        return response.status_code == 200

    except (
        httpx.HTTPError,
        asyncio.TimeoutError,
    ):
        return False


async def has_available_model_runtime(
    context,
) -> bool:

    http_client = get_status_http_client(
        context
    )

    if http_client is None:
        return True

    brain_status, service_status = await asyncio.gather(
        check_model_status(
            http_client,
            config.BRAIN_API_BASE,
        ),
        check_model_status(
            http_client,
            config.SERVICE_API_BASE,
        ),
    )

    return (
        brain_status
        or service_status
    )


async def reject_when_all_models_offline(
    context,
) -> bool:

    if await has_available_model_runtime(
        context
    ):
        return False

    await context.logger.log_error(
        "[WS] all model runtimes are offline"
    )

    await context.websocket.send_json({
        "type": "error",
        "message": (
            "All model runtimes are offline."
        ),
        "details": (
            "Start BRAIN or SERVICE before sending a request."
        ),
        "component": "runtime_status",
    })

    return True


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
        return False

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
        return False

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

async def initialize_connection(
    context,
    *,
    skip_initial_runtime_state: bool = False,
):

    await context.websocket.accept()

    await send_telemetry(
        context
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

async def receive_message(
    context,
) -> dict | None:
    websocket = context.websocket
    logger = context.logger

    raw_data = (
        await websocket.receive_text()
    )

    try:

        message_data = json.loads(
            raw_data
        )

        if isinstance(
            message_data,
            dict,
        ):
            return message_data

        await logger.log_error(
            "Invalid JSON payload: expected object."
        )

        return None

    except json.JSONDecodeError as error:

        await logger.log_error(
            f"Invalid JSON payload: {error}"
        )

        return None


# ---------------------------------------------------------
# PROCESS MESSAGE
# ---------------------------------------------------------

async def arm_save_session_from_user_text(
    context,
    user_text: str,
) -> bool:

    if (
        getattr(
            context,
            "runtime_save_session_armed",
            False,
        )
        or getattr(
            context,
            "runtime_save_session_requested",
            False,
        )
    ):
        return False

    if not should_execute_save_session(
        user_text,
    ):
        return False

    context.runtime_save_session_armed = True
    context.runtime_save_session_requested = False
    # This path is only a deterministic early trigger. It lets the brain see
    # the user's explicit save intent, but it does not confirm the save and
    # must not show the UI banner. The save becomes real only when JIN emits
    # the private SAVE_SESSION marker handled by apply_runtime_action_calls().
    context.runtime_save_session_action_emitted = False

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

    if log_runtime is not None:
        await log_runtime(
            "[RUNTIME ACTION] save_session armed"
        )

    return True


async def refresh_pending_brain_usage(
    context,
    user_text: str,
):

    if contains_cyrillic(
        user_text
    ):
        return

    brain_runtime = (
        get_brain_runtime_config()
    )

    runtime_actions = (
        brain_runtime.get(
            "runtime_actions",
            {},
        )
    )

    system_prompt = (
        build_brain_system_prompt(
            context,
            runtime_actions=runtime_actions,
        )
    )

    brain_payload = (
        build_brain_payload(
            user_text,
            context=context,
        )
    )

    used_tokens = (
        estimate_runtime_tokens(
            system_prompt=system_prompt,
            user_input=brain_payload,
        )
    )

    await refresh_runtime_state(
        context,
        runtime_id=(
            brain_runtime["runtime_id"]
        ),
        used_tokens=used_tokens,
        context_tokens=used_tokens,
        total_tokens=used_tokens,
        max_tokens=(
            brain_runtime["context_window"]
        ),
        last_error=None,
        status="online",
    )


async def wait_for_runtime_memory_update(
    context,
):

    while True:

        task = getattr(
            context,
            "runtime_memory_update_task",
            None,
        )

        if task is None:
            return

        if task.done():
            try:
                await task

            except asyncio.CancelledError:
                if task.cancelled():
                    await context.logger.log_runtime(
                        "[MEMORY] pending memory update cancelled"
                    )
                else:
                    raise

            except Exception as error:
                await context.logger.log_error(
                    "[MEMORY] pending memory update failed",
                    details=str(error),
                )

            finally:
                if (
                    getattr(
                        context,
                        "runtime_memory_update_task",
                        None,
                    )
                    is task
                ):
                    context.runtime_memory_update_task = None

            continue

        await context.logger.log_runtime(
            "[WS] waiting pending memory update"
        )

        try:
            await asyncio.shield(
                task
            )

        except asyncio.CancelledError:
            if task.cancelled():
                await context.logger.log_runtime(
                    "[MEMORY] pending memory update cancelled"
                )
            else:
                raise

        except Exception as error:
            await context.logger.log_error(
                "[MEMORY] pending memory update failed",
                details=str(error),
            )

        finally:
            if (
                getattr(
                    context,
                    "runtime_memory_update_task",
                    None,
                )
                is task
            ):
                context.runtime_memory_update_task = None


def parse_user_idle_seconds(
    value,
) -> int | None:

    try:
        seconds = int(
            float(
                value
            )
        )
    except (
        TypeError,
        ValueError,
    ):
        return None

    if seconds < 0:
        return None

    # Keep the value useful for conversational context, not as an
    # unbounded client-controlled payload. One year is more than enough
    # for a human re-entry signal.
    return min(
        seconds,
        365 * 24 * 60 * 60,
    )


def apply_user_idle_context(
    context,
    message_data: dict,
):

    seconds = parse_user_idle_seconds(
        message_data.get(
            "user_idle_seconds",
        )
    )

    if seconds is None:
        context.runtime_user_idle_seconds = None
        context.runtime_user_idle_text = ""
        context.runtime_user_idle_paused = False
        return

    context.runtime_user_idle_seconds = seconds
    context.runtime_user_idle_text = str(
        message_data.get(
            "user_idle",
            "",
        )
        or ""
    ).strip()[:32]
    context.runtime_user_idle_paused = bool(
        message_data.get(
            "user_idle_paused",
            False,
        )
    )
    attach_user_idle_to_initial_runtime_snapshot(
        context
    )


def parse_runtime_pattern_counter(
    value,
) -> int:

    try:
        counter = int(
            value
            or 0
        )
    except (
        TypeError,
        ValueError,
    ):
        return 0

    return max(
        0,
        min(
            counter,
            100,
        ),
    )


def apply_runtime_pattern_context(
    context,
    message_data: dict,
):

    context.runtime_pattern_counter = parse_runtime_pattern_counter(
        message_data.get(
            "runtime_pattern_counter",
            0,
        )
    )
    context.runtime_repeated_input_count = parse_runtime_pattern_counter(
        message_data.get(
            "runtime_repeated_input_count",
            0,
        )
    )


def append_runtime_recent_turn(
    context,
    *,
    user_message: str,
    assistant_message: str,
    user_created_at: float | None = None,
    assistant_created_at: float | None = None,
) -> None:

    if context is None:
        return

    if not hasattr(
        context,
        "runtime_recent_turns",
    ):
        context.runtime_recent_turns = []

    user_message = str(
        user_message
        or ""
    ).strip()
    assistant_message = str(
        assistant_message
        or ""
    ).strip()

    if not user_message and not assistant_message:
        return

    turn = {
        "user": user_message,
        "jin": assistant_message,
    }

    if isinstance(
        user_created_at,
        (int, float),
    ):
        turn["user_created_at"] = float(
            user_created_at
        )

    if isinstance(
        assistant_created_at,
        (int, float),
    ):
        turn["jin_created_at"] = float(
            assistant_created_at
        )

    context.runtime_recent_turns.append(
        turn
    )

    context.runtime_recent_turns = context.runtime_recent_turns[
        -RECENT_MESSAGES_MAX_PAIRS:
    ]


def format_runtime_memory_user_message(
    context,
    user_text: str,
) -> str:

    repeated = parse_runtime_pattern_counter(
        getattr(
            context,
            "runtime_repeated_input_count",
            0,
        )
    )

    if repeated < 2:
        return user_text

    return f"{json.dumps(user_text, ensure_ascii=False)} [ repeated: {repeated} ]"


def has_message_attachments(
    message_data: dict,
) -> bool:

    attachments = message_data.get(
        "attachments",
    )

    return isinstance(
        attachments,
        list,
    ) and bool(
        attachments,
    )


def format_attachment_context(
    message_data: dict,
) -> str:

    attachments = message_data.get(
        "attachments",
    )

    if not isinstance(
        attachments,
        list,
    ):
        return ""

    lines = [
        "Attached context:",
    ]

    included = 0

    for index, attachment in enumerate(
        attachments,
        start=1,
    ):

        if not isinstance(
            attachment,
            dict,
        ):
            continue

        included += 1

        name = str(
            attachment.get(
                "name",
                f"attachment-{index}",
            )
        )
        kind = str(
            attachment.get(
                "kind",
                "file",
            )
        )
        mime_type = str(
            attachment.get(
                "type",
                "application/octet-stream",
            )
        )
        size_label = str(
            attachment.get(
                "size_label",
                "",
            )
        )

        detail_parts = [
            kind,
            mime_type,
        ]

        if size_label:
            detail_parts.append(
                size_label
            )

        width = attachment.get(
            "width",
        )
        height = attachment.get(
            "height",
        )

        if width and height:
            detail_parts.append(
                f"{width}x{height}"
            )

        lines.append(
            f"- {name}: {', '.join(detail_parts)}"
        )

        text_preview = attachment.get(
            "text_preview",
        )

        if text_preview is not None:
            preview = str(
                text_preview
            )
            preview_limit = int(
                attachment.get(
                    "preview_limit",
                    len(
                        preview
                    ),
                )
                or 0
            )
            truncated = bool(
                attachment.get(
                    "truncated",
                    False,
                )
            )
            status = (
                f"first {preview_limit} chars sent"
                if truncated
                else f"{len(preview)} chars sent"
            )

            lines.append(
                f"  text_preview ({status}):"
            )
            lines.append(
                preview
            )

    if not included:
        return ""

    return "\n".join(
        lines,
    ).strip()


def redacted_attachment_for_log(
    attachment: dict,
) -> dict:

    redacted = dict(
        attachment
    )

    if redacted.get(
        "data_url",
    ):
        redacted["data_url"] = (
            f"<redacted image data url; "
            f"{len(str(redacted.get('data_url') or ''))} chars>"
        )

    if redacted.get(
        "text_content",
    ):
        redacted["text_content"] = (
            f"<redacted text attachment content; "
            f"{len(str(redacted.get('text_content') or ''))} chars>"
        )

    return redacted


def redacted_message_data_for_log(
    message_data: dict,
) -> dict:

    redacted = dict(
        message_data
    )

    attachments = redacted.get(
        "attachments",
    )

    if isinstance(
        attachments,
        list,
    ):
        redacted["attachments"] = [
            redacted_attachment_for_log(
                attachment
            )
            if isinstance(
                attachment,
                dict,
            )
            else attachment
            for attachment in attachments
        ]

    return redacted


def build_user_text_with_attachments(
    message_data: dict,
) -> str:

    user_text = str(
        message_data.get(
            "text",
            "",
        )
    ).strip()

    attachment_context = format_attachment_context(
        message_data,
    )

    if not attachment_context:
        return user_text

    if not user_text:
        return attachment_context

    return "\n\n".join([
        user_text,
        attachment_context,
    ])


async def process_message(
    context,
    message_data: dict,
):
    websocket = context.websocket
    logger = context.logger

    try:

        user_text = (
            build_user_text_with_attachments(
                message_data,
            )
        )

        context.runtime_turn_user_message = user_text
        context.runtime_turn_started_at = time.time()
        context.runtime_turn_counter = (
            getattr(
                context,
                "runtime_turn_counter",
                0,
            )
            + 1
        )
        context.runtime_current_turn_id = (
            f"turn_{context.runtime_turn_counter:06d}"
        )
        context.runtime_turn_attachments = (
            message_data.get(
                "attachments",
                [],
            )
            if isinstance(
                message_data.get(
                    "attachments",
                ),
                list,
            )
            else []
        )
        context.runtime_turn_assistant_response = ""
        context.runtime_turn_interrupted = False
        context.runtime_turn_interruption_reason = ""
        context.runtime_turn_interruption_quote = ""
        context.runtime_reasoning_recovery_pending = False
        context.runtime_context_limit_recovery_pending = False
        context.runtime_context_limit_stage = ""
        context.runtime_context_limit_kind = ""
        context.runtime_context_limit_finish_reason = ""
        await arm_save_session_from_user_text(
            context,
            user_text,
        )
        apply_user_idle_context(
            context,
            message_data,
        )
        apply_active_memory_records(
            context,
            message_data,
        )
        apply_runtime_pattern_context(
            context,
            message_data,
        )
        context.user_message_count += 1

        state = AgentState(
            user_input=user_text
        )

        if hasattr(
            context,
            "runtime_usage_events",
        ):
            context.runtime_usage_events.clear()

        else:
            context.runtime_usage_events = []

        runtime = AgentRuntime()

        await websocket.send_json({
            "type": "agent_runtime_start",
        })

        await runtime.run(
            state,
            context,
        )

        await emit_session_actions_update(
            context,
            current_sequence=False,
        )

        await logger.log(
            "[FLOW TELEMETRY]",
            format_token_usage_summary(
                context
            ),
        )

        await logger.log_system(
            "[WS] agent runtime end"
        )

        await websocket.send_json({
            "type": "agent_runtime_end",
        })

        assistant_message = (
                state.final_answer
                or state.brain_response
                or context.runtime_turn_assistant_response
        )

        append_runtime_recent_turn(
            context,
            user_message=user_text,
            assistant_message=assistant_message,
            user_created_at=getattr(
                context,
                "runtime_turn_started_at",
                None,
            ),
            assistant_created_at=time.time(),
        )

        if getattr(
            context,
            "runtime_turn_interrupted",
            False,
        ):
            memory_update_task = schedule_interrupted_runtime_memory_update(
                context=context,
            )
        else:
            memory_update_task = schedule_runtime_memory_update(
                context=context,
                user_message=format_runtime_memory_user_message(
                    context,
                    user_text,
                ),
                assistant_message=assistant_message,
            )

        if getattr(
            context,
            "runtime_save_session_requested",
            False,
        ):
            await wait_for_runtime_memory_update(
                context
            )

        context.assistant_message_count += 1
        context.turn_number += 1

        # Background fact-checking is intentionally not armed here.
        # Fact-checking runs only from the explicit UI request path.

    except asyncio.CancelledError:

        await logger.log_runtime(
            "Agent runtime task cancelled."
        )

        raise

    except Exception as error:

        await handle_fatal_runtime_error(
            context,
            component="agent_runtime",
            exception=error,
        )


# ---------------------------------------------------------
# CANCEL CURRENT TASK
# ---------------------------------------------------------

async def cancel_current_task(
    task: asyncio.Task | None,
    logger: WebSocketLogger,
    context: RuntimeContext | None = None,
):

    if (
        not task
        or task.done()
    ):
        return

    # -----------------------------------
    # FORCE CLOSE ACTIVE STREAMS
    # -----------------------------------

    if context:

        context.runtime_turn_interrupted = True

        active_streams = (
            getattr(
                context,
                "active_streams",
                {},
            )
        )

        for stream_id, response in list(
                active_streams.items()
        ):

            with contextlib.suppress(Exception):

                await response.aclose()

        active_streams.clear()

    # -----------------------------------
    # CANCEL TASK
    # -----------------------------------

    task.cancel()

    try:

        await task

    except asyncio.CancelledError:

        await logger.log_runtime(
            "Generation cancelled."
        )

    if context:
        schedule_interrupted_runtime_memory_update(
            context=context,
        )


# ---------------------------------------------------------
# WEBSOCKET CHAT
# ---------------------------------------------------------

@websocket_router.websocket(
    "/ws/chat"
)
async def websocket_endpoint(
    websocket: WebSocket,
):

    logger = WebSocketLogger(
        websocket
    )

    soft_resume = is_soft_resume_request(
        websocket
    )

    context, resumed_context = get_or_create_connection_context(
        websocket,
        logger,
    )

    skip_initial_runtime_state = soft_resume

    ensure_initial_runtime_snapshot(
        context
    )

    current_task = None
    pending_requests = asyncio.Queue()

    async def process_pending_requests():
        nonlocal current_task

        while True:

            message_data = await pending_requests.get()

            try:

                user_text = (
                    str(
                        message_data.get(
                            "text",
                            "",
                        )
                    ).strip()
                )

                await wait_for_runtime_memory_update(
                    context
                )

                await apply_runtime_response_feedback(
                    context,
                    (
                        message_data.get(
                            "pending_last_response_rating",
                        )
                        or message_data.get(
                            "runtime_response_feedback",
                        )
                    ),
                )

                await refresh_pending_brain_usage(
                    context,
                    user_text,
                )

                active_task = asyncio.create_task(
                    process_message(
                        context,
                        message_data,
                    )
                )
                current_task = active_task

                try:
                    await active_task

                except asyncio.CancelledError:
                    if active_task.cancelled():
                        await logger.log_runtime(
                            "[WS] queued request interrupted"
                        )
                    else:
                        raise

                finally:
                    if current_task is active_task:
                        current_task = None

            finally:
                pending_requests.task_done()

    pending_processor = asyncio.create_task(
        process_pending_requests()
    )

    try:

        await initialize_connection(
            context,
            skip_initial_runtime_state=skip_initial_runtime_state,
        )

        while True:

            message_data = (
                await receive_message(
                    context,
                )
            )

            if message_data is None:
                await logger.log_system(
                    "[WS] received: None"
                )
                continue

            message_type = (
                message_data.get(
                    "type",
                    "message",
                )
            )

            # -------------------------------------------------
            # SOFT RECONNECT RUNTIME RESUME
            # -------------------------------------------------

            if message_type == "runtime_resume":

                restored = apply_runtime_resume(
                    context,
                    message_data,
                )

                if restored:
                    await logger.log_system(
                        "[WS] runtime resumed from browser memory"
                    )

                    if message_data.get(
                        "emit_after_restore"
                    ):
                        await emit_current_runtime_memory(
                            context
                        )

                        await emit_runtime_l1_diff_update(
                            context
                        )

                continue

            # -------------------------------------------------
            # RESTORE BROWSER SESSION MEMORY
            # -------------------------------------------------

            if message_type == "runtime_memory_delete_slot":
                await apply_runtime_memory_slot_delete(
                    context,
                    message_data,
                )
                continue

            if message_type == "delayed_memory_store_sync":
                apply_delayed_memory_reports(
                    context,
                    message_data,
                )
                report_count = len(
                    getattr(
                        context,
                        "delayed_memory_reports",
                        {},
                    )
                    or {}
                )
                await logger.log_system(
                    (
                        "[WS] delayed memory store synced "
                        f"({report_count} reports)"
                    )
                )
                continue

            if message_type == "session_bootstrap":

                await logger.log(
                    "[SESSION]",
                    "[BOOTSTRAP] browser session restore request",
                    details=json.dumps(
                        message_data,
                        ensure_ascii=False,
                        indent=2,
                    ),
                )

                restored = apply_session_bootstrap(
                    context,
                    message_data,
                )

                if restored:
                    await logger.log_system(
                        "[WS] browser session memory restored"
                    )

                    await emit_current_runtime_memory(
                        context
                    )

                    await emit_runtime_l1_diff_update(
                        context
                    )

                    await emit_runtime_session_memory_update(
                        context
                    )

                continue

            await logger.log_user(
                str(
                    message_data.get(
                        "text",
                        "",
                    )
                ),
                details=json.dumps(
                    redacted_message_data_for_log(
                        message_data
                    ),
                    ensure_ascii=False,
                    indent=2,
                ),
            )

            # -------------------------------------------------
            # ABORT GENERATION
            # -------------------------------------------------

            if message_type == "abort":

                await cancel_current_task(
                    current_task,
                    logger,
                    context,
                )

                current_task = None

                continue

            # -------------------------------------------------
            # MANUAL FACT CHECK
            # -------------------------------------------------

            if message_type == "fact_check":

                if (
                    current_task is not None
                    and not current_task.done()
                ):
                    await logger.log_runtime(
                        "[FACT_CHECK] skipped: generation is running"
                    )
                    continue

                await logger.log(
                    "[MEMORY:FACT_CHECK]",
                    "[FACT_CHECK] manual web check requested",
                    channel="memory",
                    memory_level="FACT_CHECK",
                    memory_event="fact_check_manual",
                )

                runtime_memory_task = getattr(
                    context,
                    "runtime_memory_update_task",
                    None,
                )

                if runtime_memory_task is not None:
                    await logger.log_runtime(
                        "[FACT_CHECK] waiting for runtime memory update"
                    )
                    await runtime_memory_task

                await run_fact_check_once(
                    context
                )

                continue

            # -------------------------------------------------
            # IGNORE EMPTY MESSAGE
            # -------------------------------------------------

            user_text = (
                str(
                    message_data.get(
                        "text",
                        "",
                    )
                ).strip()
            )

            if (
                not user_text
                and not has_message_attachments(
                    message_data
                )
            ):

                await logger.log_error(
                    "Received empty message."
                )

                continue

            if await reject_when_all_models_offline(
                context
            ):
                continue

            # -------------------------------------------------
            # QUEUE MESSAGE
            # -------------------------------------------------

            if (
                current_task is not None
                and not current_task.done()
            ):

                await logger.log_runtime(
                    "[WS] queued message while generation is running"
                )

            elif (
                getattr(
                    context,
                    "runtime_memory_update_task",
                    None,
                )
                is not None
            ):

                await logger.log_runtime(
                    "[WS] queued message while memory update is running"
                )

            await pending_requests.put(
                message_data
            )

            await logger.log_runtime(
                f"[WS] pending requests: {pending_requests.qsize()}"
            )

    except WebSocketDisconnect:

        await cancel_current_task(
            current_task,
            logger,
            context,
        )

        return

    except Exception as error:

        await cancel_current_task(
            current_task,
            logger,
            context,
        )

        if (
            isinstance(error, RuntimeError)
            and "disconnect" in str(error).lower()
        ):
            return

        await handle_websocket_error(
            websocket,
            logger,
            exception=error,
        )

    finally:
        pending_processor.cancel()

        with contextlib.suppress(
            asyncio.CancelledError,
            Exception,
        ):
            await pending_processor
