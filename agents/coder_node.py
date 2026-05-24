from agents.base_node import BaseNode

from utils.response_extractor import (
    ResponseExtractor,
)

from runtime.runtime_stream import (
    RuntimeStream,
)

from settings.app_settings import (
    settings,
)


class CoderNode(BaseNode):

    async def run(
            self,
            state,
            context,
    ):

        state.iteration += 1

        current_step = (
            state.current_plan[
                state.current_step_index
            ]
            if state.current_plan
            else state.user_input
        )

        prompt = f"""
Напиши Python код.

TASK:
{current_step}

PREVIOUS ERROR:
{state.execution_error}
"""

        generator = context.clients["service"].stream(
            system_prompt="Ты code generation agent.",
            user_prompt=prompt,
            temperature=0.3,
            max_tokens=1200,
        )

        stream = RuntimeStream(
            context=context,
            runtime_id=settings.BRAIN_MODEL_UID,
            role="brain",
            context_window=settings.BRAIN_CONTEXT_WINDOW,
            log_method=context.logger.log_brain,
        )

        text = await stream.run(generator)

        state.generated_code = text