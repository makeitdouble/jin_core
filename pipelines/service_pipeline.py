import asyncio
import config

from clients.service_client import (
    ask_service_model_stream,
)

from utils.runtime_state_sync import (
    refresh_runtime_state,
)

from utils.ws_errors import (
    handle_pipeline_error,
    handle_fatal_pipeline_error,
)

from utils.stream_handler import (
    StreamHandler,
)


class ServicePipeline:

    async def run(
        self,
        context,
        message_data,
    ):
        websocket = context.websocket
        logger = context.logger

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
                "SERVICE pipeline started."
            )

            service_client = (
                context.clients[
                    "service"
                ]
            )

            stream = StreamHandler(
                websocket,
                logger,
                role="service",
                enable_validator=True,
            )

            try:

                await stream.start()

                async for chunk in (
                    ask_service_model_stream(
                        client=service_client,
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
                ):

                    chunk_type = (
                        chunk.get("type")
                    )

                    chunk_content = (
                        chunk.get(
                            "content",
                            ""
                        )
                    )

                    # -----------------------------------------
                    # USAGE
                    # -----------------------------------------

                    if chunk_type == "usage":

                        stream.update_usage(
                            chunk
                        )

                        continue

                    # -----------------------------------------
                    # THINKING STREAM
                    # -----------------------------------------

                    if (
                        chunk_type
                        == "thinking"
                    ):

                        await stream.send_thinking(
                            chunk_content
                        )

                        continue

                    # -----------------------------------------
                    # CONTENT STREAM
                    # -----------------------------------------

                    if (
                        chunk_type
                        == "content"
                    ):

                        is_valid = (
                            await stream.send_content(
                                chunk_content
                            )
                        )

                        if not is_valid:

                            await stream.finish()

                            return

                await stream.finish()

                await refresh_runtime_state(
                    context,
                    runtime_id=(
                        config
                        .SERVICE_MODEL_UID
                    ),
                    used_tokens=(
                        stream.total_tokens
                    ),
                    max_tokens=(
                        config
                        .SERVICE_CONTEXT_WINDOW
                    ),
                    last_error=None,
                    status="online",
                )

                await logger.log_service(
                    stream.response
                )

            # ---------------------------------------------------------
            # TASK CANCELLED
            # ---------------------------------------------------------

            except asyncio.CancelledError:

                await logger.log_runtime(
                    "Service stream cancelled."
                )

                try:

                    await stream.finish()

                except Exception:
                    pass

                raise

            except Exception as error:

                await handle_pipeline_error(
                    context,
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

            await logger.log_runtime(
                "Service pipeline complete."
            )

        # ---------------------------------------------------------
        # TASK CANCELLED
        # ---------------------------------------------------------

        except asyncio.CancelledError:

            await logger.log_runtime(
                "Service pipeline cancelled."
            )

            raise

        except Exception as error:

            await handle_fatal_pipeline_error(
                context,
                pipeline_name=(
                    "service_pipeline"
                ),
                exception=error,
            )
