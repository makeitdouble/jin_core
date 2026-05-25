from agents.base_node import BaseNode

from runtime.runtime_stream import (
    RuntimeStream,
)

from settings.app_settings import (
    settings,
)

from clients.brain_client import (
    ask_brain_stream,
)

from utils.brain import (
    get_brain_runtime_config,
)


class BrainNode(BaseNode):

    async def run(
            self,
            state,
            context,
    ):

        logger = context.logger

        brain_runtime = (
            get_brain_runtime_config()
        )

        brain_client = (
            context.clients[
                brain_runtime["label"]
            ]
        )

        runtime = RuntimeStream(
            context=context,
            runtime_id=(
                brain_runtime[
                    "runtime_id"
                ]
            ),
            role="brain",
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
            text=state.translated_input,
            context=context
        )

        text = await runtime.run(
            generator
        )

        state.brain_response = text or ""