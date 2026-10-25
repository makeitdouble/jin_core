import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agent.nodes.brain import BrainNode
from agent.state import AgentState
from rules.brain_context_builder import build_brain_context
from runtime.runtime_context import RuntimeContext
from utils.actions.jin_instance_actions import INSTANCE_REASONING_DEFAULTS


class PreviousReasoningSingleSlotTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_replaces_last_reasoning_and_clears_it_when_empty(self):
        context = RuntimeContext(
            websocket=SimpleNamespace(send_json=AsyncMock()),
            emitter=SimpleNamespace(emit=AsyncMock()),
            logger=SimpleNamespace(log_system=AsyncMock(), log_brain=AsyncMock()),
            clients={},
        )
        context.runtime_previous_reasoning_content = "imported archived thought"
        context.runtime_previous_reasoning_from_session_restore = True
        reasoning_outputs = iter(("R1", "R2", ""))

        def make_runtime(**_kwargs):
            return SimpleNamespace(
                stream=SimpleNamespace(reasoning=next(reasoning_outputs)),
                run=AsyncMock(return_value=""),
            )

        brain_runtime = {
            "runtime_id": "brain", "label": "brain",
            "context_window": 8192, "log_method": "log_brain",
        }
        state = AgentState(user_input="start")
        with patch("agent.nodes.brain.RuntimeStream", side_effect=make_runtime), patch(
            "agent.nodes.brain.ask_brain_stream", return_value=object(),
        ), patch(
            "agent.nodes.brain.save_chat_context_snapshot",
        ), patch(
            "agent.nodes.brain.prepare_current_context_window_prompt",
            new=AsyncMock(return_value=SimpleNamespace(system_prompt="test", context_window=8192)),
        ):
            for prior, expected in (("imported archived thought", "R1"), ("R1", "R2"), ("R2", "")):
                if prior:
                    prompt = build_brain_context(
                        context, include_previous_reasoning=True,
                        crop_previous_reasoning=False,
                    )
                    self.assertIn(prior, prompt)
                await BrainNode.run_brain_stream(
                    state=state, context=context,
                    brain_runtime=brain_runtime, brain_client=object(),
                    system_prompt="test", brain_payload="",
                    runtime_actions={}, emit_content_to_chat=False,
                    followup_tick=True,
                )
                self.assertEqual(context.runtime_previous_reasoning_content, expected)
                self.assertFalse(context.runtime_previous_reasoning_from_session_restore)
                rendered = build_brain_context(context, crop_previous_reasoning=False)
                self.assertEqual(
                    rendered.count("<PREVIOUS_REASONING_EVIDENCE_TRAIL_AFTER_EXECUTED_ACTIONS>"),
                    int(bool(expected)),
                )
                self.assertNotIn("<PREVIOUS_REASONING_LOOP_CONTENT>", rendered)
                if expected:
                    self.assertIn(expected, rendered)
                    for stale in ("R1", "imported archived thought"):
                        if stale != expected:
                            self.assertNotIn(stale, rendered)

    def test_context_has_only_one_reasoning_text_slot(self):
        context = RuntimeContext(websocket=object(), emitter=object(), logger=object(), clients={})
        self.assertEqual(context.runtime_previous_reasoning_content, "")
        self.assertFalse(hasattr(context, "runtime_turn_reasoning_content"))
        self.assertFalse(hasattr(context, "runtime_previous_reasoning_loop_contents"))
        self.assertIn("runtime_previous_reasoning_content", INSTANCE_REASONING_DEFAULTS)
        self.assertNotIn("runtime_turn_reasoning_content", INSTANCE_REASONING_DEFAULTS)
        self.assertNotIn("runtime_previous_reasoning_loop_contents", INSTANCE_REASONING_DEFAULTS)


if __name__ == "__main__":
    unittest.main()
