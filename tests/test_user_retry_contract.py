from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from rules.brain_context_builder import _append_user_retry_context
from runtime.L1_memory import discard_latest_runtime_memory_pending_turn
from websocket.messages import (
    build_user_retry_request,
    discard_latest_visible_turn_for_user_retry,
    format_runtime_memory_user_message,
)


ROOT = Path(__file__).resolve().parents[1]
ANSWER_RATING_JS = ROOT / "ui" / "static" / "js" / "answer-rating.js"
CHAT_RATING_CSS = ROOT / "ui" / "static" / "css" / "chat-rating.css"
CHAT_JS = ROOT / "ui" / "static" / "js" / "chat.js"
SOCKET_JS = ROOT / "ui" / "static" / "js" / "socket.js"
EVENT_HANDLERS_JS = ROOT / "ui" / "static" / "js" / "socket" / "event-handlers.js"
WEBSOCKET_INIT = ROOT / "websocket" / "__init__.py"


class UserRetryContractTests(unittest.TestCase):

    def test_release_disables_rating_without_deleting_old_rating_code(self):
        source = ANSWER_RATING_JS.read_text(encoding="utf-8")

        self.assertIn("const ANSWER_RATING_ENABLED = false;", source)
        self.assertIn("function addRatingHoverZones(root)", source)
        self.assertIn('"jin-rating-zone jin-rating-zone-minus"', source)
        self.assertIn('"jin-rating-zone jin-rating-zone-plus"', source)
        self.assertIn("recordJinAnswerRating", source)
        self.assertIn("addBubbleUtilityZones(root);", source)

    def test_padding_zones_own_copy_and_long_tap_only(self):
        source = ANSWER_RATING_JS.read_text(encoding="utf-8")
        css = CHAT_RATING_CSS.read_text(encoding="utf-8")

        self.assertIn('"Double-click: Copy all\\nLong-tap: Delete"', source)
        self.assertIn("const BUBBLE_RETRY_HOLD_MS = 1500;", source)
        self.assertIn('zone.addEventListener("dblclick"', source)
        self.assertIn('zone.addEventListener("pointerdown"', source)
        self.assertIn('bubble.style.opacity = "0";', source)
        self.assertIn(".jin-bubble-utility-zone-top", css)
        self.assertIn(".jin-bubble-utility-zone-left", css)
        self.assertIn("cursor: pointer;", css)
        self.assertIn("cursor: text;", css)
        self.assertIn("filter: brightness(1.03);", css)

    def test_only_explicitly_completed_live_answer_becomes_retryable(self):
        chat_source = CHAT_JS.read_text(encoding="utf-8")
        handlers_source = EVENT_HANDLERS_JS.read_text(encoding="utf-8")

        self.assertIn("options.retryable === true", chat_source)
        self.assertIn("window.markJinCompletedAnswerBubble", chat_source)
        self.assertIn("window.jinCurrentResponseRetryable", handlers_source)
        self.assertIn("data && data.retryable_response", handlers_source)
        self.assertGreaterEqual(handlers_source.count("{ retryable: false }"), 2)


    def test_retryability_commits_only_after_agent_runtime_end(self):
        handlers_source = EVENT_HANDLERS_JS.read_text(encoding="utf-8")

        message_end_start = handlers_source.index("function handleMessageEnd(")
        message_end_end = handlers_source.index("function handleMessageError(")
        message_end_source = handlers_source[message_end_start:message_end_end]
        self.assertIn("retryCandidate: Boolean(", message_end_source)
        self.assertNotIn("retryable: Boolean(", message_end_source)

        runtime_end_start = handlers_source.index("function handleAgentRuntimeEnd(data)")
        runtime_end_end = handlers_source.index("function handleMessageStart(")
        runtime_end_source = handlers_source[runtime_end_start:runtime_end_end]
        self.assertIn("data && data.retryable_response === true", runtime_end_source)
        self.assertIn("commitJinCompletedAnswerRetryCandidate", runtime_end_source)
        self.assertIn("clearJinCompletedAnswerRetryCandidate", runtime_end_source)

    def test_server_promotes_retry_source_only_after_completed_noninterrupted_response(self):
        source = (ROOT / "websocket" / "messages.py").read_text(encoding="utf-8")

        process_start = source.index("async def process_message(")
        process_source = source[process_start:]
        clear_index = process_source.index("context.runtime_last_retryable_request = {}")
        interrupted_index = process_source.index('"runtime_turn_interrupted"')
        promote_index = process_source.index(
            "context.runtime_last_retryable_request = deepcopy(\n                retry_source_candidate"
        )
        terminal_index = process_source.index('"type": "agent_runtime_end"')

        self.assertLess(clear_index, interrupted_index)
        self.assertLess(interrupted_index, promote_index)
        self.assertLess(promote_index, terminal_index)

    def test_retry_socket_request_has_no_new_visible_user_message(self):
        source = SOCKET_JS.read_text(encoding="utf-8")

        start = source.index("window.requestJinLastResponseRetry")
        retry_source = source[start:start + 2500]
        self.assertIn('type: "retry_last_response"', retry_source)
        self.assertIn("setGenerationState(", retry_source)
        self.assertNotIn("appendChatMessage(", retry_source)

    def test_server_rebuilds_same_request_and_refreshes_live_runtime_state(self):
        context = SimpleNamespace(
            runtime_last_retryable_request={
                "text": "same request",
                "attachments": [{"id": "A1"}],
            },
            runtime_recent_turns=[{
                "user": "same request",
                "jin": "discard me",
            }],
        )

        retry = build_user_retry_request(
            context,
            {
                "runtime_avatar": {"size": 44},
                "active_memory_records": [{"id": "M1"}],
                "user_idle": "must not replay",
            },
        )

        self.assertEqual(retry["type"], "retry_last_response")
        self.assertEqual(retry["text"], "same request")
        self.assertEqual(retry["attachments"], [{"id": "A1"}])
        self.assertEqual(retry["runtime_avatar"], {"size": 44})
        self.assertEqual(retry["active_memory_records"], [{"id": "M1"}])
        self.assertNotIn("user_idle", retry)

    def test_retry_discards_previous_prompt_turn_and_reasoning(self):
        context = SimpleNamespace(
            runtime_recent_turns=[{"user": "u", "jin": "old"}],
            runtime_metabolism_recent_turns=[{"user": "u", "jin": "old"}],
            runtime_previous_reasoning_content="old reasoning",
            runtime_previous_reasoning_loop_contents=["old loop"],
        )

        previous = discard_latest_visible_turn_for_user_retry(context)

        self.assertEqual(previous["jin"], "old")
        self.assertEqual(context.runtime_recent_turns, [])
        self.assertEqual(context.runtime_metabolism_recent_turns, [])
        self.assertEqual(context.runtime_previous_reasoning_content, "")
        self.assertEqual(context.runtime_previous_reasoning_loop_contents, [])

    def test_retry_is_explicit_in_brain_and_l1_context(self):
        context = SimpleNamespace(
            runtime_user_retry_active=True,
            runtime_user_retry_count=2,
            runtime_repeated_input_count=0,
        )
        parts = []

        _append_user_retry_context(parts, context)
        l1_message = format_runtime_memory_user_message(context, "same request")

        self.assertIn('<USER_RETRY attempt="2">', parts[0])
        self.assertIn("previous JIN answer has been discarded", parts[0])
        self.assertIn("user_retry: true", l1_message)
        self.assertIn("previous_jin_answer_discarded: true", l1_message)

    def test_websocket_has_retry_rejection_and_l1_discard_path(self):
        source = WEBSOCKET_INIT.read_text(encoding="utf-8")

        self.assertIn('if message_type == "retry_last_response":', source)
        self.assertIn("build_user_retry_request(", source)
        self.assertIn("discard_latest_runtime_memory_pending_turn(", source)
        self.assertIn('"retry_last_response_rejected"', source)


class UserRetryAsyncContractTests(unittest.IsolatedAsyncioTestCase):

    async def test_l1_retry_discards_latest_pending_turn_before_replacement(self):
        context = SimpleNamespace(
            runtime_memory_update_task=None,
            runtime_memory_pending_turns=[{
                "user_message": "same request",
                "assistant_message": "discarded answer",
            }],
            runtime_memory_pending_base_updates=4,
            runtime_memory_updates=4,
        )

        with (
            patch("runtime.L1_memory.clear_pending_l1_update") as clear_pending,
            patch("runtime.L1_memory.persist_pending_l1_update") as persist_pending,
            patch("runtime.L1_memory.resume_runtime_memory_pending_update") as resume_pending,
        ):
            discarded = await discard_latest_runtime_memory_pending_turn(context)

        self.assertTrue(discarded)
        self.assertEqual(context.runtime_memory_pending_turns, [])
        clear_pending.assert_called_once_with(context)
        persist_pending.assert_not_called()
        resume_pending.assert_not_called()



if __name__ == "__main__":
    unittest.main()
