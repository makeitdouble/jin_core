import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agent import (
    AgentState,
    Router,
)

from agent.nodes import (
    PlannerNode,
)
from agent.nodes.brain import (
    complete_save_session_memory_before_follow_up,
)
from utils.context.brain_context_builder import (
    build_tool_results_context,
)
from utils.tool_results import (
    TOOL_RESULT_KIND_SESSION,
)


class AgentRoutingTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_save_session_follow_up_runs_l3_before_follow_up_without_l1(self):

        context = SimpleNamespace(
            runtime_save_session_requested=True,
            runtime_turn_memory_user_message="сохрани сессию",
            runtime_turn_user_message="",
            runtime_turn_assistant_response="",
        )
        state = SimpleNamespace(
            translated_input="save session",
        )

        saved_snapshot = (
            "session_saved_at: 2026-07-14 12:00, Tuesday\n"
            "decision: keep the full session snapshot"
        )

        async def save_existing_snapshots(*, context):
            context.runtime_save_session_result = {
                "action": "save_session",
                "ok": True,
                "status": "saved",
                "message": "Session snapshot saved successfully.",
                "destination": "L3 session memory",
                "session_snapshot": saved_snapshot,
            }
            context.runtime_save_session_requested = False

        with patch(
                "agent.nodes.brain.maybe_summarize_runtime_session_memory",
                side_effect=save_existing_snapshots,
        ) as save_l3:
            handled = await complete_save_session_memory_before_follow_up(
                context=context,
                state=state,
                response_text="Saving.",
            )

        self.assertTrue(handled)
        save_l3.assert_awaited_once_with(
            context=context,
        )
        self.assertFalse(
            hasattr(
                context,
                "runtime_save_session_memory_committed_this_turn",
            )
        )
        self.assertEqual(
            context.runtime_tool_results,
            [
                {
                    "kind": TOOL_RESULT_KIND_SESSION,
                    "result": context.runtime_save_session_result,
                },
            ],
        )
        tool_results_context = build_tool_results_context(
            context
        )
        self.assertNotIn(
            "<TOOL_RESULTS",
            tool_results_context,
        )
        self.assertIn(
            '<TOOL_RESULT name="SAVE_SESSION">',
            tool_results_context,
        )
        self.assertIn(
            "Session snapshot saved successfully.",
            tool_results_context,
        )
        self.assertIn(
            "decision: keep the full session snapshot",
            tool_results_context,
        )

    async def test_save_session_follow_up_records_missing_l3_result(self):

        context = SimpleNamespace(
            runtime_save_session_requested=True,
            runtime_turn_memory_user_message="сохрани сессию",
            runtime_turn_user_message="",
            runtime_turn_assistant_response="",
        )
        state = SimpleNamespace(
            translated_input="save session",
        )

        async def finish_without_result(*, context):
            context.runtime_save_session_requested = False

        with patch(
                "agent.nodes.brain.maybe_summarize_runtime_session_memory",
                side_effect=finish_without_result,
        ):
            handled = await complete_save_session_memory_before_follow_up(
                context=context,
                state=state,
                response_text="Saving.",
            )

        self.assertTrue(handled)
        result = context.runtime_tool_results[0]["result"]
        self.assertFalse(result["ok"])
        self.assertEqual(
            result["reason"],
            "l3_save_result_missing",
        )
        self.assertIn(
            "L3 save operation did not produce a result",
            build_tool_results_context(context),
        )

    async def test_cyrillic_input_routes_directly_to_brain(self):

        state = AgentState(
            user_input="привет"
        )

        with patch(
                "agent.nodes.planner.config.TRANSLATION_ENABLED",
                False,
        ), patch(
                "agent.nodes.planner.config.TRANSLATE_RESPONSE",
                False,
        ):
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

        with patch(
                "agent.nodes.planner.config.TRANSLATION_ENABLED",
                True,
        ), patch(
                "agent.nodes.planner.config.TRANSLATE_RESPONSE",
                True,
        ):
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
