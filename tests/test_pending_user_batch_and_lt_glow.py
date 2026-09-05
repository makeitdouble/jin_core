import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.LT_memory import schedule_lt_memory_idle_update
from websocket.messages import merge_pending_user_message_batch


ROOT = Path(__file__).resolve().parents[1]


class PendingUserBatchTests(unittest.TestCase):
    def test_transport_fragments_collapse_into_one_user_turn(self):
        root = {
            "type": "message",
            "text": "first",
            "attachments": [
                {"id": "A1", "name": "one.txt"},
            ],
            "runtime_avatar": {"x": 1},
            "active_memory_records": [{"id": "old"}],
            "pending_last_response_rating": "plus",
            "user_idle_seconds": 17,
            "runtime_pattern_counter": 3,
        }
        appended = [
            {
                "text": "second",
                "attachments": [
                    {"id": "a1", "name": "duplicate.txt"},
                    {"id": "B2", "name": "two.txt"},
                ],
                "runtime_avatar": {"x": 2},
                "append_to_pending_batch": True,
            },
            {
                "text": "third",
                "active_memory_records": [{"id": "new"}],
                "append_to_pending_batch": True,
            },
        ]

        merged = merge_pending_user_message_batch(root, appended)

        self.assertEqual(merged["text"], "first\nsecond\nthird")
        self.assertEqual(
            [attachment["id"] for attachment in merged["attachments"]],
            ["A1", "B2"],
        )
        self.assertEqual(merged["runtime_avatar"], {"x": 2})
        self.assertEqual(merged["active_memory_records"], [{"id": "new"}])
        self.assertEqual(merged["pending_last_response_rating"], "plus")
        self.assertEqual(merged["user_idle_seconds"], 17)
        self.assertEqual(merged["runtime_pattern_counter"], 3)
        self.assertNotIn("append_to_pending_batch", merged)

    def test_empty_attachment_only_fragments_remain_one_turn(self):
        merged = merge_pending_user_message_batch(
            {"text": "", "attachments": [{"id": "A"}]},
            [{"text": "next"}],
        )

        self.assertEqual(merged["text"], "next")
        self.assertEqual(merged["attachments"], [{"id": "A"}])

    def test_frame_wait_uses_open_commit_ack_handshake(self):
        server = (ROOT / "websocket" / "__init__.py").read_text(encoding="utf-8")
        handlers = (
            ROOT / "ui" / "static" / "js" / "socket" / "event-handlers.js"
        ).read_text(encoding="utf-8")
        input_source = (
            ROOT / "ui" / "static" / "js" / "socket" / "input.js"
        ).read_text(encoding="utf-8")
        chat_source = (
            ROOT / "ui" / "static" / "js" / "chat.js"
        ).read_text(encoding="utf-8")

        processor = server[server.index("async def process_pending_requests") :]
        self.assertLess(
            processor.index("await wait_for_runtime_memory_update("),
            processor.index('"type": "pending_user_batch_commit"'),
        )
        self.assertIn('"type": "pending_user_batch_open"', processor)
        self.assertIn('"type": "pending_user_batch_commit"', processor)
        self.assertIn('message_type == "pending_user_batch_commit_ack"', server)
        self.assertIn('message_data.get("append_to_pending_batch")', server)
        self.assertIn("merge_pending_user_message_batch(", server)

        self.assertIn("append_to_pending_batch: true,", input_source)
        self.assertIn("isPendingUserBatchOpen()", input_source)
        self.assertIn("window.appendToUserChatMessage(", input_source)
        self.assertIn('"pending_user_batch_open"', handlers)
        self.assertIn('"pending_user_batch_commit"', handlers)
        commit_block = handlers[
            handlers.index("function handlePendingUserBatchCommit") :
            handlers.index("function handleMessageStart")
        ]
        self.assertLess(
            commit_block.index("setGenerationState("),
            commit_block.index('type: "pending_user_batch_commit_ack"'),
        )
        self.assertIn("`${previousText}\\n${nextText}`", chat_source)

    def test_first_pending_candidate_does_not_flash_stop_before_server_routing(self):
        input_source = (
            ROOT / "ui" / "static" / "js" / "socket" / "input.js"
        ).read_text(encoding="utf-8")

        initial_send_block = input_source[
            input_source.index("const userMessageRow =") :
            input_source.index("const pendingLastResponseRating =")
        ]

        self.assertNotIn("setGenerationState(", initial_send_block)


class MemoryPriorityFlowTests(unittest.TestCase):
    def test_pending_request_holds_foreground_gate_across_frame_wait(self):
        server = (ROOT / "websocket" / "__init__.py").read_text(encoding="utf-8")
        processor = server[
            server.index("async def process_pending_requests") :
            server.index("pending_processor = asyncio.create_task")
        ]

        foreground_on = processor.index(
            "note_lt_foreground_state(\n                    context,\n                    running=True,"
        )
        frame_wait = processor.index("await wait_for_runtime_memory_update(")
        foreground_off = processor.rindex(
            "note_lt_foreground_state(\n                    context,\n                    running=False,"
        )

        self.assertLess(foreground_on, frame_wait)
        self.assertGreater(foreground_off, processor.index("await active_task"))

    def test_lt_idle_scheduler_refuses_foreground_frame_and_queued_work(self):
        class RunningTask:
            def done(self):
                return False

        class PendingQueue:
            def empty(self):
                return False

        cases = [
            SimpleNamespace(runtime_foreground_turn_running=True),
            SimpleNamespace(
                runtime_foreground_turn_running=False,
                runtime_memory_update_task=RunningTask(),
            ),
            SimpleNamespace(
                runtime_foreground_turn_running=False,
                runtime_memory_update_task=None,
                runtime_pending_requests_queue=PendingQueue(),
            ),
        ]

        with (
            patch("runtime.LT_memory.lt_memory_writes_restricted", return_value=False),
            patch("runtime.LT_memory.lt_memory_enabled", return_value=True),
        ):
            for context in cases:
                with self.subTest(context=context):
                    self.assertIsNone(
                        schedule_lt_memory_idle_update(context=context)
                    )


class LTPanelGlowContractTests(unittest.TestCase):
    def test_lt_glow_lifecycle_is_wired_to_extract_merge_apply(self):
        memory_source = (
            ROOT / "ui" / "static" / "js" / "socket" / "memory.js"
        ).read_text(encoding="utf-8")
        css_source = (
            ROOT / "ui" / "static" / "css" / "base.css"
        ).read_text(encoding="utf-8")
        lt_source = (
            ROOT / "runtime" / "LT_memory.py"
        ).read_text(encoding="utf-8")

        self.assertIn('active: "memory-lt-updating"', memory_source)
        self.assertIn('event === "summarizer_request"', memory_source)
        self.assertIn('event === "extract_applied"', memory_source)
        self.assertIn('event === "merge_applied"', memory_source)
        self.assertIn('data.facts_changed === true', memory_source)
        self.assertIn('finishLTMemoryGlow("failed")', memory_source)
        self.assertIn('event === "merge_paused"', memory_source)
        self.assertIn('event === "merge_deferred"', memory_source)

        self.assertIn("#memory-panel.memory-lt-updating", css_source)
        self.assertIn("@keyframes memoryLTSuccessFade", css_source)
        self.assertIn("@keyframes memoryLTFailureFade", css_source)
        self.assertIn("@keyframes memoryLTNeutralFade", css_source)

        self.assertIn("facts_changed=bool(", lt_source)
        self.assertIn('event="merge_deferred"', lt_source)


if __name__ == "__main__":
    unittest.main()
