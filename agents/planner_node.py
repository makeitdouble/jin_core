from agents.base_node import BaseNode

from utils.language import (
    contains_cyrillic,
)


class PlannerNode(BaseNode):

    async def run(
            self,
            state,
            context,
    ):

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
