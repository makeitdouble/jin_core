import asyncio
import unittest
from types import SimpleNamespace

from utils.delayed_memory_triggers import load_delayed_memory_by_tags
from websocket.bootstrap import (
    apply_suppressed_delayed_memory_auto_load_ids,
)



class FakeEmitter:
    def __init__(self):
        self.events = []

    async def emit(self, event):
        self.events.append(event)


class FakeLogger:
    async def log_runtime(self, _message):
        return None


class DelayedMemoryPinStateTests(unittest.TestCase):

    def test_tag_trigger_uses_normal_loaded_state(self):
        context = SimpleNamespace(
            delayed_memory_reports={
                "f7jf9a": {
                    "title": "Bigmac metaphor",
                    "summary": "Architecture memory analogy.",
                    "tags": ["bigmac"],
                    "body": "Report body",
                    "pinned": False,
                    "anchor_fact_ids": [],
                    "facts_ids": [],
                    "created_session_id": "session-old",
                    "created_time": "2026-08-12T21:24:12",
                },
            },
            runtime_loaded_delayed_memory={},
            runtime_loaded_delayed_memory_ids=[],
            delayed_memory_file_store_enabled=False,
            runtime_current_turn_id="turn_000001",
            session_id="session-now",
            timestamp="2026-08-14T12:46:00",
            emitter=FakeEmitter(),
            logger=FakeLogger(),
        )

        results = asyncio.run(
            load_delayed_memory_by_tags(
                context,
                "The bigmac analogy fits this case.",
            )
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["action"], "load_delayed_memory")
        self.assertIn(
            "f7jf9a",
            context.runtime_loaded_delayed_memory,
        )
        self.assertFalse(
            hasattr(context, "runtime_appended_delayed_memory_ids")
        )

    def test_manual_unload_suppresses_tag_auto_load_for_exactly_one_turn(self):
        context = SimpleNamespace(
            delayed_memory_reports={
                "f7jf9a": {
                    "title": "Bigmac metaphor",
                    "summary": "Architecture memory analogy.",
                    "tags": ["bigmac"],
                    "body": "Report body",
                    "pinned": False,
                    "anchor_fact_ids": [],
                    "facts_ids": [],
                    "created_session_id": "session-old",
                    "created_time": "2026-08-12T21:24:12",
                },
            },
            runtime_loaded_delayed_memory={},
            runtime_loaded_delayed_memory_ids=[],
            runtime_suppressed_delayed_memory_auto_load_ids=[],
            delayed_memory_file_store_enabled=False,
            runtime_current_turn_id="turn_000001",
            session_id="session-now",
            timestamp="2026-08-14T12:46:00",
            emitter=FakeEmitter(),
            logger=FakeLogger(),
        )

        suppressed = apply_suppressed_delayed_memory_auto_load_ids(
            context,
            {
                "suppressed_delayed_memory_auto_load_ids": ["f7jf9a"],
            },
        )
        self.assertEqual(suppressed, ["f7jf9a"])

        first_turn = asyncio.run(
            load_delayed_memory_by_tags(context, "bigmac")
        )
        self.assertEqual(first_turn, [])
        self.assertEqual(
            context.runtime_suppressed_delayed_memory_auto_load_ids,
            [],
        )

        second_turn = asyncio.run(
            load_delayed_memory_by_tags(context, "bigmac")
        )
        self.assertEqual(len(second_turn), 1)
        self.assertIn(
            "f7jf9a",
            context.runtime_loaded_delayed_memory,
        )


if __name__ == "__main__":
    unittest.main()
