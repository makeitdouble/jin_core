from agent.nodes.base import BaseNode

from utils.language import (
    contains_cyrillic,
)
from config_loader import (
    config,
)


class PlannerNode(BaseNode):

    async def run(
            self,
            state,
            context,
    ):

        translation_enabled = getattr(
            config,
            "TRANSLATION_ENABLED",
            False,
        )
        translate_response_enabled = getattr(
            config,
            "TRANSLATE_RESPONSE",
            False,
        )

        state.translate_input = (
            translation_enabled
            and contains_cyrillic(
                state.user_input
            )
        )
        state.translate_response = (
            state.translate_input
            and translate_response_enabled
        )
        state.translated_input = state.user_input

        state.current_plan = []

        if state.translate_input:
            state.current_plan.append(
                "translator"
            )

        state.current_plan.extend([
            "brain",
            "validator",
        ])

        if state.translate_response:
            state.current_plan.append(
                "translator"
            )
