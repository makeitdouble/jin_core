import traceback
import logging

from utils.runtime_state_sync import (
    set_runtime_offline,
)

module_logger = logging.getLogger(__name__)

async def send_ws_error(
    websocket,
    *,
    error_type: str,
    message: str,
    details: str | None = None,
    runtime_id: str | None = None,
    component: str | None = None,
):

    await websocket.send_json({
        "type": error_type,
        "message": message,
        "details": details,
        "runtime_id": runtime_id,
        "component": component,
    })


async def handle_runtime_error(
    context,
    *,
    runtime_id: str,
    public_message: str,
    exception: Exception,
):

    websocket = context.websocket
    logger = context.logger

    error_text = str(
        exception
    )

    await logger.log_error(
        f"[{runtime_id}] "
        f"{public_message}: "
        f"{error_text}"
    )

    await send_ws_error(
        websocket,
        error_type="error",
        runtime_id=runtime_id,
        message=public_message,
        details=error_text,
    )

    await set_runtime_offline(
        context,
        runtime_id=runtime_id,
        error=error_text,
    )


async def handle_fatal_runtime_error(
    context,
    *,
    component: str,
    exception: Exception,
):
    logger = context.logger
    websocket = context.websocket

    formatted_traceback = (
        traceback.format_exc()
    )

    await logger.log_error(
        f"[{component}] "
        f"Fatal runtime error: {exception}",
        details=formatted_traceback,
    )

    await send_ws_error(
        websocket,
        error_type="fatal_error",
        component=component,
        message=str(exception),
        details=formatted_traceback,
    )

    module_logger.error(
        "Fatal runtime error in %s",
        component,
        exc_info=True,
    )


async def handle_websocket_error(
    websocket,
    logger,
    *,
    exception: Exception,
):

    formatted_traceback = (
        traceback.format_exc()
    )

    await logger.log_error(
        "WebSocket session error.",
        details=formatted_traceback,
    )

    await send_ws_error(
        websocket,
        error_type="websocket_error",
        message="WebSocket session crashed.",
        details=formatted_traceback,
    )

    module_logger.error(
        "WebSocket session error",
        exc_info=True,
    )
