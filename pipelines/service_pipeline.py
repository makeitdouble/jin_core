import traceback

import config

from clients.service_client import (
    ask_service_model,
)

from memory.runtime_state import (
    runtime_state,
)

from utils.telemetry import (
    send_telemetry,
)

from utils.tokens import (
    estimate_tokens,
)


class ServicePipeline:

    async def run(
        self,
        websocket,
        logger,
        message_data,
    ):

        try:

            user_text = (
                message_data.get("text", "")
                .strip()
            )

            if not user_text:

                await logger.log_error(
                    "Received empty message."
                )

                return

            await logger.log_runtime(
                "SERVICE pipeline enabled."
            )

            try:

                response = (
                    await ask_service_model(
                        user_prompt=user_text,
                        system_prompt="",
                        temperature=(
                            config
                            .SERVICE_TEMPERATURE
                        ),
                        max_tokens=(
                            config
                            .SERVICE_MAX_TOKENS
                        ),
                    )
                )

                runtime_state.update_node_state(
                    "service",
                    model=(
                        config
                        .SERVICE_MODEL_UID
                    ),
                    used_tokens=(
                        estimate_tokens(
                            user_text
                            + response
                        )
                    ),
                    max_tokens=(
                        config
                        .SERVICE_CONTEXT_WINDOW
                    ),
                )

                await send_telemetry(
                    websocket
                )

                await logger.log_service(
                    response
                )

            except Exception as e:

                runtime_state.update_node_state(
                    "service",
                    model="OFFLINE",
                )

                await send_telemetry(
                    websocket
                )

                await logger.log_error(
                    f"Service error: {e}"
                )

                await websocket.send_json({
                    "type": "error",
                    "source": "service",
                    "text": str(e),
                })

                return

            await websocket.send_json({
                "type": "message",
                "role": "service",
                "text": response,
            })

            await logger.log_runtime(
                "Service pipeline complete."
            )

        except Exception as e:

            await logger.log_error(
                traceback.format_exc()
            )

            await logger.log_error(
                f"Service pipeline error: {e}"
            )

            await websocket.send_json({
                "type": "error",
                "source": "service_pipeline",
                "text": str(e),
            })
