from fastapi import (
    APIRouter,
    WebSocket,
)

from starlette.websockets import (
    WebSocketDisconnect,
)

import asyncio
import json

from logger import (
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


websocket_router = APIRouter()


# ---------------------------------------------------------
# CONNECTION SETUP
# ---------------------------------------------------------

async def initialize_connection(
    websocket: WebSocket,
    logger: WebSocketLogger,
):

    await websocket.accept()

    await send_telemetry(
        websocket
    )


# ---------------------------------------------------------
# RECEIVE MESSAGE
# ---------------------------------------------------------

async def receive_message(
    websocket: WebSocket,
    logger: WebSocketLogger,
):

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
    websocket: WebSocket,
    logger: WebSocketLogger,
    message_data: dict,
):

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

        await pipeline.run(
            websocket=websocket,
            logger=logger,
            message_data=message_data,
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
):

    if (
        not task
        or task.done()
    ):
        return

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

    current_task = None

    try:

        await initialize_connection(
            websocket,
            logger,
        )

        while True:

            message_data = (
                await receive_message(
                    websocket,
                    logger,
                )
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
                        websocket,
                        logger,
                        message_data,
                    )
                )
            )

    except WebSocketDisconnect:

        await cancel_current_task(
            current_task,
            logger,
        )

        return

    except Exception as error:

        await cancel_current_task(
            current_task,
            logger,
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
