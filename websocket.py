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
    cancel_runtime_memory_update,
    refresh_runtime_state,
    schedule_interrupted_runtime_memory_update,
    schedule_runtime_memory_update,
    send_telemetry,
)


websocket_router = APIRouter()


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

    await context.emitter.emit({
        "type": "runtime_memory_update",
        "memory": context.runtime_memory,
        "updates": getattr(
            context,
            "runtime_memory_updates",
            0,
        ),
        "snapshot": context.runtime_memory_snapshots[0],
        "snapshots_count": len(
            context.runtime_memory_snapshots
        ),
        "snapshot_index": 0,
    })


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

            await logger.log_system(
                f"[WS] received: {message_data}"
            )

            if message_data is None:
                continue

            message_type = (
                message_data.get(
                    "type",
                    "message",
                )
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

            # -------------------------------------------------
            # PREVENT PARALLEL GENERATION
            # -------------------------------------------------

            if (
                current_task is not None
                and not current_task.done()
            ):

                await logger.log_runtime(
                    "Generation already running."
                )

                continue

            # -------------------------------------------------
            # START BACKGROUND TASK
            # -------------------------------------------------

            await cancel_runtime_memory_update(
                context
            )

            await refresh_pending_brain_usage(
                context,
                user_text,
            )

            current_task = (
                asyncio.create_task(
                    process_message(
                        context,
                        message_data,
                    )
                )
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
