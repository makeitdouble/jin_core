from fastapi import (
    APIRouter,
    WebSocket,
    WebSocketDisconnect,
)

import json
import traceback

from logger import (
    WebSocketLogger,
)

from pipelines.pipeline_factory import (
    get_pipeline,
)

from utils.telemetry import (
    send_telemetry,
)


websocket_router = APIRouter()


# ---------------------------------------------------------
# WEBSOCKET HELPERS
# ---------------------------------------------------------

async def initialize_connection(
    websocket: WebSocket,
    logger: WebSocketLogger,
):

    await websocket.accept()

    await logger.log_system(
        "WebSocket connected."
    )

    await send_telemetry(
        websocket
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

            raw_data = await websocket.receive_text()

            try:

                message_data = json.loads(
                    raw_data
                )

            except json.JSONDecodeError as error:

                await logger.log_error(
                    f"Invalid JSON payload: {error}"
                )

                continue

            user_text = message_data.get(
                "text",
                "",
            )

            pipeline = get_pipeline(
                user_text
            )

            try:

                await pipeline.run(
                    websocket=websocket,
                    logger=logger,
                    message_data=message_data,
                )

            except Exception as error:

                traceback_text = (
                    traceback.format_exc()
                )

                await logger.log_error(
                    f"Pipeline error: {error}"
                )

                print(traceback_text)

    except WebSocketDisconnect:

        await logger.log_system(
            "Client disconnected."
        )

    except Exception as error:

        traceback_text = (
            traceback.format_exc()
        )

        await logger.log_error(
            f"WebSocket session error: {error}"
        )

        print(traceback_text)
