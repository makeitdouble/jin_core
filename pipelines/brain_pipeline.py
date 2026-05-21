import config

from clients.brain_client import (
    ask_brain_stream,
)

from runtime.runtime_stream import (
    RuntimeStream,
)

from utils.brain import (
    get_brain_runtime_config,
)

from utils.ws_errors import (
    handle_fatal_pipeline_error,
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

            runtime = RuntimeStream(
                websocket=websocket,
                logger=logger,
                runtime_id=(
                    brain_runtime[
                        "runtime_id"
                    ]
                ),
                role=(
                    "service"
                    if config.USE_SERVICE_AS_BRAIN
                    else "brain"
                ),
                context_window=(
                    brain_runtime[
                        "context_window"
                    ]
                ),
                log_method=getattr(
                    logger,
                    brain_runtime[
                        "log_method"
                    ],
                ),
                enable_validator=True,
            )

            await runtime.run(
                ask_brain_stream(
                    user_text
                )
            )

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
