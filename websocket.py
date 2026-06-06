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
    build_runtime_memory_snapshot,
    emit_runtime_l1_diff_update,
    emit_runtime_session_memory_update,
    refresh_runtime_state,
    schedule_interrupted_runtime_memory_update,
    schedule_runtime_memory_update,
    send_telemetry,
)


websocket_router = APIRouter()

MAX_BOOTSTRAP_MEMORY_CHARS = 12000
RUNTIME_STATUS_CHECK_TIMEOUT = getattr(
    config,
    "STATUS_CHECK_TIMEOUT",
    0.5,
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
        "memory": context.runtime_memory,
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

    runtime_memory = clean_bootstrap_memory(
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

    if (
        not runtime_memory
        and isinstance(
            runtime_snapshot,
            dict,
        )
    ):
        runtime_memory = clean_bootstrap_memory(
            runtime_snapshot.get(
                "raw_memory",
                "",
            )
        )

    if session_memory:
        context.session_memory = session_memory
        context.runtime_l3_session_memory = session_memory
        try:
            context.runtime_session_memory_updates = max(
                int(
                    message_data.get(
                        "session_memory_updates",
                        0,
                    ) or 0
                ),
                getattr(
                    context,
                    "runtime_session_memory_updates",
                    0,
                ),
            )
        except (
            TypeError,
            ValueError,
        ):
            pass
        context.session_memory_source = clean_bootstrap_memory(
            message_data.get(
                "session_memory_source",
                "browser",
            ),
            limit=80,
        ) or "browser"

    if runtime_memory:
        previous_runtime_memory = getattr(
            context,
            "runtime_memory",
            "",
        )

        if not getattr(
            context,
            "runtime_memory_snapshots",
            [],
        ):
            context.runtime_memory_snapshots = []
            initial_snapshot = build_runtime_memory_snapshot(
                context,
                previous_runtime_memory,
            )
            context.runtime_memory_snapshots.append(
                initial_snapshot
            )

        context.runtime_memory = runtime_memory
        context.runtime_memory_stable = runtime_memory

        try:
            context.runtime_memory_updates = max(
                int(
                    message_data.get(
                        "runtime_memory_updates",
                        0,
                    ) or 0
                ),
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

        restored_snapshot = build_runtime_memory_snapshot(
            context,
            context.runtime_memory,
        )

        context.runtime_memory_snapshots.append(
            restored_snapshot
        )
        context.runtime_memory_snapshot_index = restored_snapshot[
            "index"
        ]

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
    context
):

    await context.websocket.accept()

    await send_telemetry(
        context
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

        await logger.log_system(
            "[WS] runtime=AgentRuntime"
        )

        await logger.log_system(
            "[WS] agent runtime start"
        )

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

        schedule_runtime_memory_update(
            context=context,
            user_message=user_text,
            assistant_message=assistant_message,
        )

        context.assistant_message_count += 1
        context.turn_number += 1

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

    context = RuntimeContext(
        websocket=websocket,
        emitter=RuntimeEmitter(
            websocket
        ),
        logger=logger,
        clients=websocket.app.state.clients,
    )

    initial_snapshot = build_runtime_memory_snapshot(
        context,
        context.runtime_memory,
    )

    context.runtime_memory_snapshots.append(
        initial_snapshot
    )

    context.runtime_memory_snapshot_index = 0

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
            context
        )

        while True:

            await logger.log_system(
                "[WS] waiting message"
            )

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

            await logger.log_system(
                f"[WS] received: {message_data}"
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
