import asyncio

from settings.app_settings import settings

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
            context,
            user_input: str,
    ):

        print("[BRAIN PIPELINE RUN]")
        print(user_input)

        logger = context.logger

        try:

            if not user_input:

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

            brain_client = (
                context.clients["brain"]
            )

            runtime = RuntimeStream(
                context=context,
                runtime_id=(
                    brain_runtime[
                        "runtime_id"
                    ]
                ),
                role=(
                    "service"
                    if settings.USE_SERVICE_AS_BRAIN
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

            generator = ask_brain_stream(
                client=brain_client,
                text=user_input,
            )

            await runtime.run(
                generator
            )

            await logger.log_runtime(
                "Brain pipeline complete."
            )

        # ---------------------------------------------------------
        # TASK CANCELLED
        # ---------------------------------------------------------

        except asyncio.CancelledError:

            await logger.log_runtime(
                "Brain pipeline cancelled."
            )

            raise

        # ---------------------------------------------------------
        # FATAL ERROR
        # ---------------------------------------------------------

        except Exception as error:

            import traceback

            tb = traceback.format_exc()

            print(tb)

            await logger.log_error(
                tb
            )

            await handle_fatal_pipeline_error(
                context,
                pipeline_name=(
                    "brain_pipeline"
                ),
                exception=error,
            )