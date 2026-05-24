from agents.planner_node import (
    PlannerNode,
)

from agents.translation_node import (
    TranslationNode,
)

from agents.validation_node import (
    ValidationNode,
)

from agents.router import (
    Router,
)

from agents.brain_node import (
    BrainNode,
)

class AgentRuntime:

    def __init__(self):

        self.nodes = {
            "planner": PlannerNode(),
            "translator": TranslationNode(),
            "brain": BrainNode(),
            "validator": ValidationNode(),
        }

        self.router = Router()

    async def run(
            self,
            state,
            context,
    ):

        current = "planner"

        while current != "END":

            await context.logger.log_runtime(
                f"[AGENT] {current}"
            )

            node = self.nodes[current]

            await node.run(
                state,
                context,
            )

            current = self.router.next(
                state,
                current,
            )

        return state