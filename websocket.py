from fastapi import (
    APIRouter,
    WebSocket,
)

from starlette.websockets import (
    WebSocketDisconnect,
)

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

            await process_message(
                websocket,
                logger,
                message_data,
            )

    except WebSocketDisconnect:
        return

    except RuntimeError as error:

        if (
            "disconnect"
            in str(error).lower()
        ):

            return

        await handle_websocket_error(
            websocket,
            logger,
            exception=error,
        )

    except Exception as error:

        await handle_websocket_error(
            websocket,
            logger,
            exception=error,
        )
