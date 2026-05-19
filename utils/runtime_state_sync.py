from memory.runtime_state import (
    runtime_state,
)

from utils.telemetry import (
    send_telemetry,
)


async def refresh_runtime_state(
    websocket,
    *,
    runtime_id: str,
    used_tokens: int | None = None,
    max_tokens: int | None = None,
    add_tokens: int | None = None,
    last_error: str | None = None,
    status: str | None = None,
):

    runtime_state.update_runtime_state(
        runtime_id=runtime_id,
        used_tokens=used_tokens,
        max_tokens=max_tokens,
        add_tokens=add_tokens,
        last_error=last_error,
        status=status,
    )

    await send_telemetry(
        websocket
    )


async def set_runtime_offline(
    websocket,
    *,
    runtime_id: str,
    error: str | None = None,
):

    runtime_state.update_runtime_state(
        runtime_id=runtime_id,
        last_error=error,
        status="offline",
    )

    await send_telemetry(
        websocket
    )
