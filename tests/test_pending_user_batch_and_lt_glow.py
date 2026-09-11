import unittest
from types import SimpleNamespace
from unittest.mock import patch

from runtime.LT_memory import schedule_lt_memory_idle_update
from websocket.messages import merge_pending_user_message_batch



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


class MemoryPriorityFlowTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
