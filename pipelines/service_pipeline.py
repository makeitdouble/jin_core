import config

from clients.service_client import (
    ask_service_model,
)

from utils.tokens import (
    estimate_tokens,
)

from utils.runtime_state_sync import (
    refresh_runtime_state,
)

from utils.ws_errors import (
    handle_pipeline_error,
    handle_fatal_pipeline_error,
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
                message_data.get(
                    "text",
                    "",
                ).strip()
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

                await refresh_runtime_state(
                    websocket,
                    runtime_id=(
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
                    last_error=None,
                    status="online",
                )

                await logger.log_service(
                    response
                )

            except Exception as error:

                await handle_pipeline_error(
                    websocket,
                    logger,
                    runtime_id=(
                        config
                        .SERVICE_MODEL_UID
                    ),
                    public_message=(
                        "Service request failed."
                    ),
                    exception=error,
                )

                return

            await websocket.send_json({
                "type": "message",
                "role": "service",
                "text": response,
            })

            await logger.log_runtime(
                "Service pipeline complete."
            )

        except Exception as error:

            await handle_fatal_pipeline_error(
                websocket,
                logger,
                pipeline_name=(
                    "service_pipeline"
                ),
                exception=error,
            )
