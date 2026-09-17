import asyncio
import json
import unittest

from contracts.rules_assembler import RUNTIME_ACTION_UPDATE_LT_FACTS
from runtime.frame_memory import schedule_runtime_memory_update
from runtime.runtime_context import RuntimeContext
from tests.helpers.memory import FakeServiceClient
from utils.actions import RuntimeActionCall
from utils.actions.dispatcher import apply_runtime_action_calls
from utils.actions.update_lt_facts_actions import (
    preempt_update_lt_facts_actions,
    schedule_pending_update_lt_facts_actions,
)
from websocket.logger import WebSocketLogger
from websocket.messages import wait_for_runtime_memory_update


class EventSink:
    def __init__(self):
        self.events = []
        self.frame_published = asyncio.Event()
        self.release_publication = asyncio.Event()

    async def send_json(self, event):
        self.events.append(event)
        if event.get("type") == "runtime_memory_update":
            self.frame_published.set()
            await self.release_publication.wait()

    emit = send_json


class OrderedService(FakeServiceClient):
    def __init__(self):
        super().__init__([
            "discussion_focus: Finish FRAME before updating durable facts.",
            json.dumps({
                "action": "create", "replacement_facts": [],
                "new_facts": [{"key": "user.preference.language",
                               "value": "The user prefers Russian replies.",
                               "category": "user_preference"}],
            }),
        ])
        self.frame_started = asyncio.Event()
        self.release_frame = asyncio.Event()
        self.frame_error = None

    async def ask(self, **kwargs):
        response = await super().ask(**kwargs)
        if len(self.calls) == 1:
            self.frame_started.set()
            await self.release_frame.wait()
            if self.frame_error:
                raise self.frame_error
        return response


class FrameLTOrderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sink = EventSink()
        self.service = OrderedService()
        self.context = RuntimeContext(
            websocket=self.sink, emitter=self.sink,
            logger=WebSocketLogger(self.sink), clients={"service": self.service},
        )
        self.context.runtime_lt_file_store_enabled = False
        self.context.delayed_memory_file_store_enabled = False
        self.context.runtime_anonymous_mode = True
        self.context.runtime_persistent_writes_restricted = True
        self.context.runtime_foreground_turn_running = True
        self.context.runtime_current_turn_id = "turn_000001"
        action = RuntimeActionCall(
            name=RUNTIME_ACTION_UPDATE_LT_FACTS,
            payload=json.dumps({"fact_ids": [], "message":
                                "Create a new durable fact: the user prefers Russian replies."}),
        )
        await apply_runtime_action_calls(
            self.context, (action,), action_display_ids={id(action): "lt-1"},
        )
        self.frame = schedule_runtime_memory_update(
            context=self.context, user_message="Remember my language preference.",
            assistant_message="I will remember it.",
        )
        self.lt = schedule_pending_update_lt_facts_actions(self.context, frame_task=self.frame)
        await asyncio.wait_for(self.service.frame_started.wait(), 1)

    async def asyncTearDown(self):
        self.service.release_frame.set()
        self.sink.release_publication.set()
        for task in list(self.context.background_tasks):
            task.cancel()
        await asyncio.gather(*self.context.background_tasks, return_exceptions=True)

    async def assert_only_frame_running(self):
        # Give competing tasks enough runnable slots to expose the old race.
        for _ in range(10):
            await asyncio.sleep(0)
        self.assertEqual(len(self.service.calls), 1)
        requests = [(e.get("memory_level"), e.get("memory_event"))
                    for e in self.sink.events if e.get("memory_event") == "summarizer_request"]
        self.assertEqual(requests, [("FRAME", "summarizer_request")])

    async def test_lt_waits_for_frame_response_and_state_publication(self):
        await self.assert_only_frame_running()
        self.service.release_frame.set()
        await asyncio.wait_for(self.sink.frame_published.wait(), 1)
        await self.assert_only_frame_running()
        self.sink.release_publication.set()
        await asyncio.wait_for(asyncio.gather(self.frame, self.lt), 1)
        memory_events = [(e.get("memory_level"), e.get("memory_event")) for e in self.sink.events]
        self.assertLess(memory_events.index(("FRAME", "summarizer_response")),
                        memory_events.index(("L-T", "summarizer_request")))
        self.assertEqual(self.context.runtime_memory_updates, 1)
        self.assertEqual(len(self.context.runtime_long_term_memory_store["facts"]), 1)
        self.assertEqual(self.context.runtime_lt_explicit_note_queue, [])

    async def test_new_user_cancels_lt_waiter_but_frame_finishes_before_brain(self):
        self.assertTrue(await preempt_update_lt_facts_actions(self.context, reason="user_message"))
        await asyncio.gather(self.lt, return_exceptions=True)
        self.assertFalse(self.frame.done())
        self.assertIs(self.context.runtime_memory_update_task, self.frame)
        self.assertEqual(len(self.context.runtime_lt_explicit_note_queue), 1)
        foreground_wait = asyncio.create_task(wait_for_runtime_memory_update(self.context))
        await self.assert_only_frame_running()
        self.assertFalse(foreground_wait.done())
        self.service.release_frame.set()
        self.sink.release_publication.set()
        await asyncio.wait_for(foreground_wait, 1)
        self.assertEqual(self.context.runtime_memory_updates, 1)
        self.assertEqual(len(self.service.calls), 1)
        self.assertEqual(self.context.runtime_memory_pending_turns, [])
        retry = schedule_pending_update_lt_facts_actions(self.context, frame_task=self.frame)
        await asyncio.wait_for(retry, 1)
        self.assertEqual(len(self.service.calls), 2)
        self.assertEqual(self.context.runtime_lt_explicit_note_queue, [])

    async def test_cancelled_frame_preserves_note_for_next_boundary(self):
        self.frame.cancel()
        await asyncio.gather(self.frame, self.lt, return_exceptions=True)
        await self.assert_only_frame_running()
        entry, = self.context.runtime_lt_explicit_note_queue
        self.assertFalse(entry["_lt_frame_gate_bound"])
        self.assertIsNone(entry["_lt_frame_task"])
        self.assertEqual(len(self.context.runtime_memory_pending_turns), 1)
        self.assertIsNone(self.context.runtime_lt_active_attempt)

    async def test_frame_provider_failure_terminates_before_lt_and_retains_pending_turn(self):
        self.service.frame_error = RuntimeError("test provider failure")
        self.service.release_frame.set()
        await asyncio.wait_for(asyncio.gather(self.frame, self.lt), 1)
        memory_events = [(e.get("memory_level"), e.get("memory_event")) for e in self.sink.events]
        self.assertLess(memory_events.index(("FRAME", "summarizer_failed")),
                        memory_events.index(("L-T", "summarizer_request")))
        self.assertEqual(len(self.context.runtime_memory_pending_turns), 1)
        self.assertEqual(self.context.runtime_memory_updates, 0)


if __name__ == "__main__":
    import sys

    if sys.argv[1:] == ["--events"]:
        async def export_events():
            test = FrameLTOrderTests("test_lt_waits_for_frame_response_and_state_publication")
            await test.asyncSetUp()
            try:
                await test.test_lt_waits_for_frame_response_and_state_publication()
                print(json.dumps([e for e in test.sink.events if e.get("memory_level")]))
            finally:
                await test.asyncTearDown()

        asyncio.run(export_events())
    else:
        unittest.main()
