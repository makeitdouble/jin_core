import unittest
from types import SimpleNamespace

from agent import (
    AgentRuntime,
    AgentState,
)


class FakeLogger:

    def __init__(self):
        self.flows = []

    async def log_flow(self, message):
        self.flows.append(message)


class FakeBrain:

    def __init__(self):
        self.calls = []

    async def run(self, state, context):
        self.calls.append((state.user_input, context))
        state.brain_response = "direct brain response"


class AgentRuntimeTests(
    unittest.IsolatedAsyncioTestCase
):

    async def test_user_input_goes_directly_to_brain(self):

        state = AgentState(
            user_input="привет"
        )
        context = SimpleNamespace(
            logger=FakeLogger(),
        )
        runtime = AgentRuntime()
        brain = FakeBrain()
        runtime.brain = brain

        result = await runtime.run(
            state,
            context,
        )

        self.assertIs(
            result,
            state,
        )
        self.assertEqual(
            brain.calls,
            [
                (
                    "привет",
                    context,
                ),
            ],
        )
        self.assertEqual(
            state.brain_response,
            "direct brain response",
        )
        self.assertEqual(
            context.logger.flows,
            ["brain"],
        )

if __name__ == "__main__":
    unittest.main()
