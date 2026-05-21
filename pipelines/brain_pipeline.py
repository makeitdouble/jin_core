import config

from clients.brain_client import (
    ask_brain_stream,
)

from utils.tokens import (
    estimate_tokens,
)

from utils.brain import (
    get_brain_runtime_config,
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


class BrainPipeline:

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
                "Brain pipeline started."
            )

            brain_runtime = (
                get_brain_runtime_config()
            )

            stream = StreamHandler(
                websocket,
                logger,
                role=(
                    "service"
                    if config.USE_SERVICE_AS_BRAIN
                    else "brain"
                ),
                enable_validator=True,
            )

            try:

                await stream.start()

                async for chunk in (
                    ask_brain_stream(
                        user_text
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
                    websocket,
                    runtime_id=(
                        brain_runtime[
                            "runtime_id"
                        ]
                    ),
                    used_tokens=(
                        estimate_tokens(
                            user_text
                            + stream.response
                        )
                    ),
                    max_tokens=(
                        brain_runtime[
                            "context_window"
                        ]
                    ),
                    last_error=None,
                    status="online",
                )

                await getattr(
                    logger,
                    brain_runtime[
                        "log_method"
                    ],
                )(
                    stream.response
                )

            except Exception as error:

                await handle_pipeline_error(
                    websocket,
                    logger,
                    runtime_id=(
                        brain_runtime[
                            "runtime_id"
                        ]
                    ),
                    public_message=(
                        "Brain request failed."
                    ),
                    exception=error,
                )

                return

            await logger.log_runtime(
                "Brain pipeline complete."
            )

        except Exception as error:

            await handle_fatal_pipeline_error(
                websocket,
                logger,
                pipeline_name=(
                    "brain_pipeline"
                ),
                exception=error,
            )
