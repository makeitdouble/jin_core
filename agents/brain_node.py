from agents.base_node import BaseNode

from runtime.runtime_stream import (
    RuntimeStream,
)

from clients.brain_client import (
    ask_brain_stream,
    build_brain_payload,
    build_brain_system_prompt,
    record_deep_thought_calls,
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

        system_prompt = (
            build_brain_system_prompt(
                context
            )
        )

        brain_payload = (
            build_brain_payload(
                state.translated_input,
                context=context,
            )
        )

        stream_role = (
            brain_runtime["label"]
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
            text=state.translated_input,
            context=context,
            system_prompt=system_prompt,
            brain_payload=brain_payload,
        )

        text = await runtime.run(
            generator
        )

        record_deep_thought_calls(
            context,
            runtime.stream.reasoning,
        )

        state.brain_response = text or ""
