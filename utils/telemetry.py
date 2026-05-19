from memory.runtime_state import (
    runtime_state,
)


async def send_telemetry(websocket):

    await websocket.send_json({
        "type": "telemetry",
        "brain": runtime_state.brain,
        "service": runtime_state.service,
        "translator": runtime_state.translator,
    })
