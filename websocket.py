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

from pipelines.pipeline_factory import (
    get_pipeline,
)

from utils.telemetry import (
    send_telemetry,
)

from utils.ws_errors import (
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
):
    websocket = context.websocket
    logger = context.logger

    raw_data = (
        await websocket.receive_text()
    )

    try:

        return json.loads(
            raw_data
        )

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

        pipeline = get_pipeline(
            user_text
        )

        await logger.log_system(
            f"[WS] pipeline={pipeline.__class__.__name__}"
        )

        await logger.log_system(
            "[WS] pipeline start"
        )

        await pipeline.run(
            context=context,
            user_input=message_data["text"],
        )

        await logger.log_system(
            "[WS] pipeline end"
        )

    except asyncio.CancelledError:

        await logger.log_runtime(
            "Pipeline task cancelled."
        )

        raise


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

            if not message_data:
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
