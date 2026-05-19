from memory.runtime_state import (
    runtime_state,
)


async def send_telemetry(
    websocket,
):

    await websocket.send_json({
        "type": "telemetry",

        "runtime": (
            runtime_state
            .get_all_runtime_states()
        ),
    })
