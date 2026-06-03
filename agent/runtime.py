from agent.nodes.planner import (
    PlannerNode,
)

from agent.nodes.translation import (
    TranslationNode,
)

from agent.nodes.validation import (
    ValidationNode,
)

from agent.router import (
    Router,
)

from agent.nodes.brain import (
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