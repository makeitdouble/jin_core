from agents.agent_runtime import (
    AgentRuntime,
)

from agents.agent_state import (
    AgentState,
)


class AgentPipeline:

    async def run(
            self,
            context,
            user_input,
    ):

        print("[AGENT PIPELINE RUN]")

        state = AgentState(
            user_input=user_input
        )

        runtime = AgentRuntime()

        result = await runtime.run(
            state,
            context,
        )

        await context.websocket.send_json({
            "type": "agent_final",
            "answer": result.final_answer,
        })

        return result.final_answer