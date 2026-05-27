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

from agents.agent_runtime import (
    AgentRuntime,
)

from agents.agent_state import (
    AgentState,
)

from utils.telemetry import (
    send_telemetry,
)

from utils.ws_errors import (
    handle_fatal_pipeline_error,
    handle_websocket_error,
)

from runtime.runtime_context import (
    RuntimeContext,
)

from emitter.runtime_emitter import (
    RuntimeEmitter,
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

        state = AgentState(
            user_input=user_text
        )

        runtime = AgentRuntime()

        await logger.log_system(
            "[WS] runtime=AgentRuntime"
        )

        await logger.log_system(
            "[WS] agent runtime start"
        )

        await runtime.run(
            state,
            context,
        )

        await logger.log_system(
            "[WS] agent runtime end"
        )

    except asyncio.CancelledError:

        await logger.log_runtime(
            "Pipeline task cancelled."
        )

        raise

    except Exception as error:

        await handle_fatal_pipeline_error(
            context,
            pipeline_name="agent_runtime",
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
                current_task
                and not current_task.done()
            ):

                await logger.log_runtime(
                    "Generation already running."
                )

                continue

            # -------------------------------------------------
            # START BACKGROUND TASK
            # -------------------------------------------------

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
