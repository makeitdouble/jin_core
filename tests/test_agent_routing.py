import unittest

from agent import (
    AgentState,
    Router,
)

from agent.nodes import (
    PlannerNode,
)


class AgentRoutingTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_cyrillic_input_routes_directly_to_brain(self):

        state = AgentState(
            user_input="привет"
        )

        await PlannerNode().run(
            state,
            context=None,
        )

        self.assertFalse(
            state.translate_input
        )

        self.assertEqual(
            state.translated_input,
            "привет",
        )

        self.assertEqual(
            state.current_plan,
            [
                "brain",
                "validator",
            ],
        )

    async def test_non_cyrillic_input_routes_directly_to_brain(self):

        state = AgentState(
            user_input="hello"
        )

        await PlannerNode().run(
            state,
            context=None,
        )

        self.assertFalse(
            state.translate_input
        )

        self.assertEqual(
            state.translated_input,
            "hello",
        )

        self.assertEqual(
            state.current_plan,
            [
                "brain",
                "validator",
            ],
        )

    def test_router_follows_planned_nodes(self):

        state = AgentState(
            user_input="hello",
            current_plan=[
                "brain",
                "validator",
            ],
        )

        router = Router()

        self.assertEqual(
            router.next(
                state,
                "planner",
            ),
            "brain",
        )

        self.assertEqual(
            router.next(
                state,
                "brain",
            ),
            "validator",
        )

        self.assertEqual(
            router.next(
                state,
                "validator",
            ),
            "END",
        )


if __name__ == "__main__":
    unittest.main()
