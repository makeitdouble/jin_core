from agent.nodes.brain import (
    BrainNode,
)


class AgentRuntime:

    def __init__(self):
        self.brain = BrainNode()

    async def run(
            self,
            state,
            context,
    ):

        await self.brain.run(
            state,
            context,
        )

        return state
