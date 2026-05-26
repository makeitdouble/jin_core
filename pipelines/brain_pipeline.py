import asyncio

from settings.app_settings import settings

from clients.brain_client import (
    ask_brain_stream,
    build_brain_payload,
    build_brain_system_prompt,
    record_deep_thought_calls,
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
                context.clients[
                    brain_runtime["label"]
                ]
            )

            system_prompt = (
                build_brain_system_prompt(
                    context
                )
            )

            brain_payload = (
                build_brain_payload(
                    user_input,
                    context=context,
                )
            )

            stream_role = (
                "service"
                if settings.USE_SERVICE_AS_BRAIN
                else "brain"
            )

            runtime = RuntimeStream(
                context=context,
                runtime_id=(
                    brain_runtime[
                        "runtime_id"
                    ]
                ),
                role=stream_role,
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
                context_snapshot={
                    "context_role": "brain",
                    "system_prompt": system_prompt,
                    "user_prompt": brain_payload,
                },
            )

            generator = ask_brain_stream(
                client=brain_client,
                text=user_input,
                context=context,
                system_prompt=system_prompt,
                brain_payload=brain_payload,
            )

            await runtime.run(
                generator
            )

            record_deep_thought_calls(
                context,
                runtime.stream.reasoning,
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

            await handle_fatal_pipeline_error(
                context,
                pipeline_name=(
                    "brain_pipeline"
                ),
                exception=error,
            )
