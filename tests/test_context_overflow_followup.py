import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agent.nodes.brain import BrainNode
from agent.state import AgentState
from rules.runtime import FOLLOW_UP_CONTEXT_OVERFLOW_MESSAGE, FOLLOW_UP_RESPONSE_MESSAGE
from runtime.client import LMStudioAPIError
from runtime.stream import RuntimeStream
from clients.response_extractor import ResponseExtractor
from utils.session_actions_history import (
    build_session_actions_update_items,
    compact_session_action_history_since,
    record_session_action_history,
)
from tests.test_brain_asset_flow import _brain_runtime, _context
from tests.test_runtime_stream_tokens import FakeEmitter, FakeLogger, FakeWebSocket


class ContextOverflowFollowupTests(unittest.IsolatedAsyncioTestCase):
    def test_overflow_prompt_is_separate_and_consumed_once(self):
        context = SimpleNamespace(
            runtime_context_limit_recovery_pending=True,
            runtime_context_limit_kind="context",
            runtime_context_limit_stage="reasoning",
            runtime_followup_response_action_lines=["POSTING_BOARD"],
            runtime_followup_response_tool_ids=["T19"],
        )
        base = "<TOOLS_RESULTS>\n<TOOL_RESULT id='T19'>useful evidence</TOOL_RESULT>\n</TOOLS_RESULTS>\nBASE"
        prompt = BrainNode.build_followup_system_prompt(base, "task", context=context)
        self.assertIn(FOLLOW_UP_CONTEXT_OVERFLOW_MESSAGE, prompt)
        self.assertNotIn(FOLLOW_UP_RESPONSE_MESSAGE, prompt)
        self.assertNotIn("Last executed actions:", prompt)
        self.assertNotIn("Tool results are available by id:", prompt)
        self.assertNotIn("<CONTEXT_LIMIT_RECOVERY>", prompt)
        self.assertIn("<TOOL_RESULT id='T19'>useful evidence</TOOL_RESULT>", prompt)
        self.assertFalse(context.runtime_context_limit_recovery_pending)
        self.assertEqual(context.runtime_context_limit_kind, "")
        next_prompt = BrainNode.build_followup_system_prompt(prompt, "task", context=context)
        self.assertNotIn(FOLLOW_UP_CONTEXT_OVERFLOW_MESSAGE, next_prompt)
        self.assertIn(FOLLOW_UP_RESPONSE_MESSAGE, next_prompt)

    async def test_finish_and_provider_errors_arm_recovery_before_stream_end(self):
        for kind in ("finish", "preflight", "provider", "full_length", "native_full", "output"):
            with self.subTest(kind=kind):
                context = SimpleNamespace(
                    websocket=FakeWebSocket(), logger=FakeLogger(), emitter=FakeEmitter(),
                    runtime_action_events=[], runtime_usage_events=[],
                    runtime_current_turn_id="overflow-test", runtime_session_action_history=[],
                )
                stream = RuntimeStream(
                    context=context, runtime_id="brain", role="brain",
                    context_window=8192, log_method=context.logger.log_service,
                    context_snapshot={"context_role": "brain"},
                )

                async def generate():
                    record_session_action_history(context, "POSTING_BOARD: action:feed")
                    yield {"type": "thinking", "content": "unfinished reasoning"}
                    if kind == "preflight":
                        raise LMStudioAPIError("too large", details=json.dumps({"error_kind": "context_overflow"}))
                    if kind == "provider":
                        raise LMStudioAPIError("HTTP 400: context length too small", details="{}")
                    if kind == "native_full":
                        native = {"type": "chat.end", "result": {"stats": {"input_tokens": 8000, "total_output_tokens": 192}}}
                        yield ResponseExtractor.extract_usage(native)
                        yield {"type": "finish", "finish_reason": ResponseExtractor.extract_finish_reason(native)}
                    else:
                        yield {"type": "usage", "prompt_tokens": 8000, "completion_tokens": 192 if kind == "full_length" else 10}
                        yield {"type": "finish", "finish_reason": "length" if kind == "output" or kind == "full_length" else "context_overflow"}
                    # The event must be visible before the generator ends.
                    self.assertTrue(any(e["type"] == "session_actions_update" for e in context.emitter.events))

                await stream.run(generate())
                self.assertTrue(context.runtime_context_limit_recovery_pending)
                self.assertEqual(context.runtime_context_limit_kind, "output" if kind == "output" else "context")
                self.assertEqual(len(context.runtime_session_action_history), 2)
                label = "output token limit" if kind == "output" else "context limit"
                expected = f"{label} reached during reasoning"
                self.assertEqual(context.runtime_session_action_history[-1]["text"], expected)
                record_session_action_history(context, "CLEAN_TOOL_RESULTS: T19")
                compact_session_action_history_since(context, 0)
                self.assertEqual(len(context.runtime_session_action_history), 3)
                restored = SimpleNamespace(**vars(context))
                restored.runtime_session_action_history = json.loads(json.dumps(context.runtime_session_action_history))
                items = build_session_actions_update_items(restored, current_sequence=False)
                self.assertEqual(items[1]["text"], expected)
                self.assertFalse(any(m["type"] == "message_error" for m in context.websocket.messages))
                self.assertTrue(any(m["type"] == "message_end" for m in context.websocket.messages))
                self.assertFalse(stream.mark_context_limit_recovery("context_overflow"))

    async def test_normal_stop_does_not_start_cleanup(self):
        context = SimpleNamespace(websocket=FakeWebSocket(), logger=FakeLogger(), emitter=FakeEmitter())
        stream = RuntimeStream(context=context, runtime_id="brain", role="brain", context_window=8192, log_method=context.logger.log_service)
        stream.stream.prompt_tokens = 8000
        stream.stream.completion_tokens = 10
        self.assertFalse(stream.mark_context_limit_recovery("stop"))

    async def test_brain_continues_same_turn_with_cleanup_actions_enabled(self):
        context = _context()
        state = AgentState(user_input="continue task")
        calls = []

        async def run_stream(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                context.runtime_turn_interrupted = True
                context.runtime_context_limit_recovery_pending = True
                context.runtime_context_limit_kind = "context"
                context.runtime_context_limit_stage = "reasoning"
                return "", "unfinished reasoning"
            self.assertEqual(len(calls), 2)
            self.assertIn(FOLLOW_UP_CONTEXT_OVERFLOW_MESSAGE, kwargs["system_prompt"])
            self.assertNotIn(FOLLOW_UP_RESPONSE_MESSAGE, kwargs["system_prompt"])
            self.assertTrue(kwargs["followup_tick"])
            self.assertEqual(kwargs["brain_payload"], "")
            self.assertTrue(kwargs["runtime_actions"]["CAN_CLEAN_TOOL_RESULTS"])
            return "Task completed after cleanup.", ""

        runtime = _brain_runtime()
        runtime["runtime_actions"]["CAN_CLEAN_TOOL_RESULTS"] = True
        with patch("agent.nodes.brain.get_brain_runtime_config", return_value=runtime), patch(
            "agent.nodes.brain.emit_active_memory_records_update_if_dirty", new=AsyncMock()
        ), patch.object(BrainNode, "run_brain_stream", side_effect=run_stream):
            await BrainNode().run(state, context)
        self.assertEqual(len(calls), 2)
        self.assertEqual(state.brain_response, "Task completed after cleanup.")
        self.assertFalse(context.runtime_turn_interrupted)


if __name__ == "__main__":
    unittest.main()
