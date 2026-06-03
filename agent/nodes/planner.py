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

        if not getattr(config, "TRANSLATION_ENABLED", False):
            state.current_plan = [
                "brain",
                "validator",
            ]

            state.translate_input = False
            state.translated_input = state.user_input


            return

        state.translate_input = contains_cyrillic(
            state.user_input
        )

        if state.translate_input:

            state.current_plan = [
                "translator",
                "brain",
                "validator",
            ]

            return

        state.translated_input = state.user_input

        state.current_plan = [
            "brain",
            "validator",
        ]
