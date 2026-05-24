from agents.base_node import BaseNode


class PlannerNode(BaseNode):

    async def run(
            self,
            state,
            context,
    ):

        state.current_plan = [
            "translate"
        ]