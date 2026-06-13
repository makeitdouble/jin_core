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
    build_brain_system_prompt,
)
from clients.brain_client import (
    should_execute_remember_session,
)

from utils.brain import (
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
from runtime.memory_utils import (
    build_runtime_memory_context_text,
    remove_runtime_user_idle_lines,
)
from runtime.memory import (
    parse_runtime_memory_lines,
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

    return remove_runtime_user_idle_lines(
        clean_bootstrap_memory(
            value,
            limit=limit,
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


def apply_runtime_resume(
    context,
    message_data: dict,
) -> bool:

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

    runtime_memory_updates = parse_bootstrap_counter(
        message_data.get(
            "runtime_memory_updates",
            0,
        )
    )

    if runtime_memory_is_snapshot_fallback:
        runtime_memory_updates = 0

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
    session_event_snapshots = message_data.get(
        "session_event_snapshots",
        message_data.get(
            "runtime_session_event_snapshots",
            [],
        ),
    )

    if isinstance(
        session_event_snapshots,
        list,
    ):
        context.runtime_session_event_snapshots = [
            snapshot
            for snapshot in session_event_snapshots
            if isinstance(
                snapshot,
                dict,
            )
        ]

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

    if session_memory:
        context.session_memory = session_memory
        context.runtime_l3_session_memory = session_memory
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
        or getattr(
            context,
            "runtime_session_event_snapshots",
            [],
        )
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

async def arm_remember_session_from_user_text(
    context,
    user_text: str,
) -> bool:

    if getattr(
        context,
        "runtime_remember_session_requested",
        False,
    ):
        return False

    if not should_execute_remember_session(
        user_text,
    ):
        return False

    context.runtime_remember_session_requested = True
    context.runtime_remember_session_action_emitted = True

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
            "[RUNTIME ACTION] remember_session requested"
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
            "action": "remember_session",
            "text": "Remembering this session",
        })

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


async def process_message(
    context,
    message_data: dict,
):
    websocket = context.websocket
    logger = context.logger

    try:

        user_text = (
            message_data.get(
                "text",
                "",
            )
        )

        context.runtime_turn_user_message = user_text
        context.runtime_turn_assistant_response = ""
        context.runtime_turn_interrupted = False
        await arm_remember_session_from_user_text(
            context,
            user_text,
        )
        apply_user_idle_context(
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

        memory_update_task = schedule_runtime_memory_update(
            context=context,
            user_message=user_text,
            assistant_message=assistant_message,
        )

        if (
            memory_update_task is not None
            and getattr(
                context,
                "runtime_remember_session_requested",
                False,
            )
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
                    message_data.get(
                        "text",
                        "",
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
                        "[WS] soft reconnect runtime resumed"
                    )

                continue

            # -------------------------------------------------
            # RESTORE BROWSER SESSION MEMORY
            # -------------------------------------------------

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
                f'{message_data}'
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
                message_data.get(
                    "text",
                    "",
                ).strip()
            )

            if not user_text:

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
