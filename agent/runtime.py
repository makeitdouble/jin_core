from agent.nodes.brain import (
    BrainNode,
)


class AgentRuntime:

    def __init__(self):
        self.brain = BrainNode()

    @staticmethod
    async def _log_agent_flow(
            context,
    ):

        log_flow = getattr(
            context.logger,
            "log_flow",
            None,
        )

        if log_flow:
            await log_flow(
                "brain"
            )
            return

        await context.logger.log_runtime(
            "[FLOW] brain"
        )

    async def run(
            self,
            state,
            context,
    ):

        await self._log_agent_flow(
            context,
        )

        await self.brain.run(
            state,
            context,
        )

        return state
