import traceback

from utils.runtime_state_sync import (
    set_runtime_offline,
)


async def handle_pipeline_error(
    websocket,
    logger,
    *,
    runtime_id: str,
    public_message: str,
    exception: Exception,
):

    error_text = str(
        exception
    )

    await logger.log_error(
        f"[{runtime_id}] "
        f"{public_message}: "
        f"{error_text}"
    )

    await websocket.send_json({
        "type": "error",
        "runtime_id": runtime_id,
        "message": public_message,
        "details": error_text,
    })

    await set_runtime_offline(
        websocket,
        runtime_id=runtime_id,
        error=error_text,
    )


async def handle_fatal_pipeline_error(
    websocket,
    logger,
    *,
    pipeline_name: str,
    exception: Exception,
):

    error_text = str(
        exception
    )

    formatted_traceback = (
        traceback.format_exc()
    )

    await logger.log_error(
        f"[{pipeline_name}] "
        "Fatal pipeline error:\n"
        f"{formatted_traceback}"
    )

    await websocket.send_json({
        "type": "fatal_error",
        "pipeline": pipeline_name,
        "message": error_text,
        "traceback": formatted_traceback,
    })
