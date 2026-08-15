import asyncio
import unittest
from types import SimpleNamespace

from utils.delayed_memory_triggers import (
    RUNTIME_ACTION_LOAD_DELAYED_MEMORY,
    load_delayed_memory_by_tags,
    delayed_memory_trigger_matches,
)


class FakeEmitter:
    def __init__(self):
        self.events = []

    async def emit(self, event):
        self.events.append(event)


class FakeLogger:
    def __init__(self):
        self.lines = []

    async def log_runtime(self, message):
        self.lines.append(message)


class DelayedMemoryTriggerTests(unittest.TestCase):

    def test_trigger_match_is_case_insensitive_and_lexical(self):
        self.assertTrue(
            delayed_memory_trigger_matches(
                "This BIGMAC analogy is useful here.",
                "bigmac",
            )
        )
        self.assertFalse(
            delayed_memory_trigger_matches(
                "bigmac_analogy is only a longer token",
                "bigmac",
            )
        )

    def test_auto_load_uses_tags_and_emits_sequence_action(self):
        emitter = FakeEmitter()
        logger = FakeLogger()
        context = SimpleNamespace(
            delayed_memory_reports={
                "f7jf9a": {
                    "title": "Bigmac metaphor",
                    "summary": "Architecture memory analogy.",
                    "tags": [
                        "architecture",
                        "bigmac",
                    ],
                    "body": "Report body",
                    "pinned": False,
                    "anchor_fact_ids": [],
                    "facts_ids": [],
                    "created_session_id": "session-old",
                    "created_time": "2026-08-12T21:24:12",
                },
                "abc123": {
                    "title": "Generic memory",
                    "summary": "Should not be pulled without a tag match.",
                    "tags": [
                        "memory_model",
                    ],
                    "body": "Other body",
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
            timestamp="2026-08-13T16:39:00",
            emitter=emitter,
            logger=logger,
        )

        results = asyncio.run(
            load_delayed_memory_by_tags(
                context,
                "The bigmac analogy fits this case.",
            )
        )

        self.assertEqual(len(results), 1)
        self.assertIn("f7jf9a", context.runtime_loaded_delayed_memory)
        self.assertNotIn("abc123", context.runtime_loaded_delayed_memory)
        self.assertEqual(
            results[0]["action"],
            RUNTIME_ACTION_LOAD_DELAYED_MEMORY,
        )
        self.assertEqual(results[0]["triggered_by_tag"], "bigmac")
        self.assertEqual(len(emitter.events), 1)
        event = emitter.events[0]
        self.assertEqual(event["action"], RUNTIME_ACTION_LOAD_DELAYED_MEMORY)
        self.assertEqual(event["runtime_turn_id"], "turn_000001")
        self.assertIn('triggered_by_tag: "bigmac"', event["text"])
        self.assertEqual(
            context.delayed_memory_reports["f7jf9a"]["loaded_times"],
            1,
        )

    def test_index_tags_are_also_triggers(self):
        context = SimpleNamespace(
            delayed_memory_reports={
                "f7jf9a": {
                    "title": "Architecture note",
                    "summary": "Architecture memory.",
                    "tags": [
                        "architecture",
                    ],
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
            emitter=FakeEmitter(),
            logger=FakeLogger(),
        )

        results = asyncio.run(
            load_delayed_memory_by_tags(
                context,
                "Let's revisit the architecture here.",
            )
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["triggered_by_tag"], "architecture")

    def test_already_loaded_report_is_not_loaded_twice(self):
        report = {
            "title": "Already loaded",
            "tags": [
                "bigmac",
            ],
            "body": "Body",
            "pinned": False,
        }
        context = SimpleNamespace(
            delayed_memory_reports={"f7jf9a": report},
            runtime_loaded_delayed_memory={
                "f7jf9a": {
                    **report,
                    "id": "f7jf9a",
                },
            },
            runtime_loaded_delayed_memory_ids=["f7jf9a"],
            delayed_memory_file_store_enabled=False,
            emitter=FakeEmitter(),
            logger=FakeLogger(),
        )

        results = asyncio.run(
            load_delayed_memory_by_tags(
                context,
                "bigmac",
            )
        )

        self.assertEqual(results, [])
        self.assertEqual(context.emitter.events, [])


if __name__ == "__main__":
    unittest.main()
