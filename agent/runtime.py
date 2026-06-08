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

    @staticmethod
    async def _log_agent_flow(
            context,
            visited: list[str],
    ):

        if not visited:
            return

        message = " -> ".join(
            visited
        )

        log_flow = getattr(
            context.logger,
            "log_flow",
            None,
        )

        if log_flow:
            await log_flow(
                message
            )
            return

        await context.logger.log_runtime(
            f"[FLOW] {message}"
        )

    async def run(
            self,
            state,
            context,
    ):

        current = "planner"

        visited = []

        while current != "END":

            visited.append(
                current
            )

            await self._log_agent_flow(
                context,
                visited,
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
