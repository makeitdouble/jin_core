import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace

from utils.delayed_memory_triggers import append_delayed_memory_by_tags
from websocket.bootstrap import (
    apply_appended_delayed_memory_ids,
    apply_suppressed_delayed_memory_append_ids,
    get_context_appended_delayed_memory_ids,
)


ROOT = Path(__file__).resolve().parents[1]


class FakeEmitter:
    def __init__(self):
        self.events = []

    async def emit(self, event):
        self.events.append(event)


class FakeLogger:
    async def log_runtime(self, _message):
        return None


class DelayedMemoryPinStateTests(unittest.TestCase):

    def test_tag_append_records_appended_source_state(self):
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
            runtime_appended_delayed_memory_ids=[],
            delayed_memory_file_store_enabled=False,
            runtime_current_turn_id="turn_000001",
            session_id="session-now",
            timestamp="2026-08-14T12:46:00",
            emitter=FakeEmitter(),
            logger=FakeLogger(),
        )

        results = asyncio.run(
            append_delayed_memory_by_tags(
                context,
                "The bigmac analogy fits this case.",
            )
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(
            context.runtime_appended_delayed_memory_ids,
            ["f7jf9a"],
        )
        self.assertIn(
            "f7jf9a",
            context.runtime_loaded_delayed_memory,
        )

    def test_manual_unappend_suppresses_tag_reappend_for_exactly_one_turn(self):
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
            runtime_appended_delayed_memory_ids=[],
            runtime_suppressed_delayed_memory_append_ids=[],
            delayed_memory_file_store_enabled=False,
            runtime_current_turn_id="turn_000001",
            session_id="session-now",
            timestamp="2026-08-14T12:46:00",
            emitter=FakeEmitter(),
            logger=FakeLogger(),
        )

        suppressed = apply_suppressed_delayed_memory_append_ids(
            context,
            {
                "suppressed_delayed_memory_append_ids": ["f7jf9a"],
            },
        )
        self.assertEqual(suppressed, ["f7jf9a"])

        first_turn = asyncio.run(
            append_delayed_memory_by_tags(
                context,
                "bigmac",
            )
        )
        self.assertEqual(first_turn, [])
        self.assertEqual(
            context.runtime_suppressed_delayed_memory_append_ids,
            [],
        )
        self.assertNotIn(
            "f7jf9a",
            context.runtime_loaded_delayed_memory,
        )

        second_turn = asyncio.run(
            append_delayed_memory_by_tags(
                context,
                "bigmac",
            )
        )
        self.assertEqual(len(second_turn), 1)
        self.assertIn(
            "f7jf9a",
            context.runtime_loaded_delayed_memory,
        )

    def test_appended_ids_are_limited_to_currently_loaded_reports(self):
        context = SimpleNamespace(
            runtime_loaded_delayed_memory={
                "f7jf9a": {"id": "f7jf9a"},
            },
            runtime_appended_delayed_memory_ids=["abc123"],
        )

        applied = apply_appended_delayed_memory_ids(
            context,
            {
                "appended_delayed_memory_ids": [
                    "f7jf9a",
                    "abc123",
                    "invalid-id",
                ],
            },
        )

        self.assertEqual(applied, ["f7jf9a"])
        self.assertEqual(
            get_context_appended_delayed_memory_ids(context),
            ["f7jf9a"],
        )

    def test_client_contract_has_separate_appended_and_pinned_states(self):
        runtime_source = (
            ROOT / "ui/static/js/runtime/runtime.js"
        ).read_text(encoding="utf-8")
        memory_view_source = (
            ROOT / "ui/static/js/runtime/runtime-memory-view.js"
        ).read_text(encoding="utf-8")
        trace_source = (
            ROOT / "ui/static/js/logger/trace-modal.js"
        ).read_text(encoding="utf-8")
        socket_source = (
            ROOT / "ui/static/js/socket/delayed-memory.js"
        ).read_text(encoding="utf-8")
        action_source = (
            ROOT / "ui/static/js/socket/runtime-actions.js"
        ).read_text(encoding="utf-8")
        session_source = (
            ROOT / "ui/static/js/runtime/runtime-session.js"
        ).read_text(encoding="utf-8")
        css_source = (
            ROOT / "ui/static/css/runtime-memory.css"
        ).read_text(encoding="utf-8")

        self.assertIn("appendedDelayedMemoryReportIds", runtime_source)
        self.assertIn("handleDelayedMemoryReportPinClick", runtime_source)
        self.assertIn('action: "unappend"', runtime_source)
        self.assertIn("sync: true", runtime_source)
        self.assertIn("suppressNextTurn: true", runtime_source)
        self.assertIn("markDelayedMemoryReportAppended", action_source)
        self.assertIn("appended_delayed_memory_ids", socket_source)
        self.assertIn("suppressed_delayed_memory_append_ids", socket_source)
        self.assertIn("appended_memory_ids", session_source)

        self.assertIn("runtime-memory-delayed-pin", memory_view_source)
        self.assertIn("runtime-memory-delayed-separator", memory_view_source)
        self.assertIn("delayed-memory-modal-pin-appended", memory_view_source)
        self.assertIn("delayed-memory-modal-pin-appended", trace_source)
        self.assertIn('row.classList.toggle(\n    "is-pinned"', trace_source)

        self.assertIn("rgba(196, 196, 198, 0.96)", css_source)
        self.assertIn(".delayed-memory-modal-pin:hover", css_source)
        self.assertIn(".jin-context-delayed-row.is-pinned", css_source)


if __name__ == "__main__":
    unittest.main()
