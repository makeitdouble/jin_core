import asyncio
from types import SimpleNamespace
import unittest

from contracts.rules_assembler import RUNTIME_ACTION_DEEP_WEB_SEARCH
from runtime.stream import RuntimeStream
from utils.actions import RuntimeActionCall


class FakeEmitter:
    def __init__(self):
        self.events = []

    async def emit(self, payload):
        self.events.append(dict(payload))


class DeepWebSearchMarkerLifecycleTests(unittest.TestCase):

    def build_runtime_stream(self):
        context = SimpleNamespace(
            emitter=FakeEmitter(),
            runtime_action_events=[],
            runtime_active_action_markers=[],
            runtime_current_turn_id="turn_000001",
            runtime_deep_web_search_action_sequence=0,
            delayed_memory_reports={},
        )
        runtime_stream = RuntimeStream.__new__(RuntimeStream)
        runtime_stream.context = context
        runtime_stream.context_snapshot = {}
        runtime_stream.stream = SimpleNamespace(message_id="message_000001")
        runtime_stream.deep_web_search_action_ids = {}
        runtime_stream.started_deep_web_search_action_ids = []
        runtime_stream.started_active_memory_action_ids = []
        runtime_stream.started_delayed_memory_action_ids = []
        runtime_stream.started_update_l4_facts_action_ids = []
        runtime_stream.jin_color_action_id = ""
        runtime_stream.jin_size_action_ids = {}
        runtime_stream.update_l4_facts_action_ids = {}
        runtime_stream.action_guard_confirmation_ids = {}
        return runtime_stream, context

    def test_opening_marker_emits_empty_parent_bubble_immediately(self):
        runtime_stream, context = self.build_runtime_stream()

        asyncio.run(runtime_stream.emit_started_runtime_actions((
            RuntimeActionCall(name=RUNTIME_ACTION_DEEP_WEB_SEARCH),
        )))

        self.assertEqual(len(context.emitter.events), 1)
        event = context.emitter.events[0]
        self.assertEqual(event["action"], "deep_web_search")
        self.assertEqual(event["status"], "started")
        self.assertEqual(event["text"], "DEEP_WEB_SEARCH")
        self.assertTrue(event["deep_search_parent"])
        self.assertFalse(event["deep_search_payload_ready"])
        self.assertTrue(event["id"])

    def test_closing_marker_reuses_opening_parent_bubble_id(self):
        runtime_stream, _context = self.build_runtime_stream()
        opening = RuntimeActionCall(name=RUNTIME_ACTION_DEEP_WEB_SEARCH)
        completed = RuntimeActionCall(
            name=RUNTIME_ACTION_DEEP_WEB_SEARCH,
            payload='{"query": "Noir jazz history and instrumentation"}',
        )

        opening_id = runtime_stream.get_runtime_action_display_id(opening)
        completed_id = runtime_stream.get_runtime_action_display_id(completed)

        self.assertEqual(completed_id, opening_id)
        self.assertEqual(runtime_stream.started_deep_web_search_action_ids, [])
        self.assertEqual(
            runtime_stream.deep_web_search_action_ids[completed.payload],
            opening_id,
        )


if __name__ == "__main__":
    unittest.main()
