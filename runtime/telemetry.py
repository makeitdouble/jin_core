from runtime.registry import (
    runtime_state,
)


async def send_telemetry(
        context,
):

    await context.emitter.emit({
        "type": "telemetry",

        "runtime": (
            runtime_state
            .get_all_runtime_states()
        ),
    })
