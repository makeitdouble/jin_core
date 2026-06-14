from agent.nodes.base import BaseNode


class ValidationNode(BaseNode):

    async def run(
            self,
            state,
            context,
    ):

        state.validation_error = ""

        response = (
                state.brain_response
                or ""
        ).strip()

        # ---------------------------------------------------------
        # EMPTY RESPONSE
        # ---------------------------------------------------------

        if not response:

            state.validation_error = (
                "Empty brain response."
            )

            return

        state.final_answer = response
