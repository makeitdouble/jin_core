import asyncio
import contextlib
import json
import gc
import weakref
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from starlette.websockets import WebSocketDisconnect
from starlette.datastructures import Headers
import websocket as ws
from runtime.runtime_context import RuntimeContext
from websocket.transport import PAGE_CLOSED_CODE, RECONNECT_GRACE_SECONDS, RuntimeTransport, stop_runtime_transports


class Socket:
    def __init__(self, app=None, soft=False):
        self.headers = Headers({"host": "localhost:8000", "origin": "http://localhost:8000"})
        self.scope = {"scheme": "ws"}
        self.app = app or SimpleNamespace(state=SimpleNamespace(clients={}))
        self.query_params = {"client_id": "transport-test", "resume": "soft" if soft else ""}
        self.incoming = asyncio.Queue()
        self.events = []
        self.accepted = 0

    async def accept(self):
        self.accepted += 1

    async def send_json(self, data):
        self.events.append(data)

    async def send_text(self, data):
        self.events.append(json.loads(data))

    async def receive_text(self):
        data = await self.incoming.get()
        if data is None:
            raise WebSocketDisconnect(1006)
        if isinstance(data, WebSocketDisconnect):
            raise data
        return json.dumps(data)

    async def close(self, code=1000):
        await self.incoming.put(WebSocketDisconnect(code))


async def until(predicate):
    async def poll():
        while not predicate():
            await asyncio.sleep(0.001)
    await asyncio.wait_for(poll(), 3)


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_ack_replay_and_payload_snapshot(self):
        socket = Socket()
        transport = RuntimeTransport(socket)
        payload = {"type": "chunk", "nested": [1]}
        await transport.send_json(payload)
        payload["nested"].append(2)
        await transport.send_json({"type": "agent_runtime_end"})
        transport.acknowledge(999)
        self.assertEqual(len(transport.pending), 2)
        transport.socket = socket
        sender = asyncio.create_task(transport.deliver(socket))
        await until(lambda: len(socket.events) == 2)
        self.assertEqual(socket.events[0]["nested"], [1])
        transport.acknowledge(1)
        sender.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sender
        replacement = Socket(socket.app, soft=True)
        transport.socket = replacement
        sender = asyncio.create_task(transport.deliver(replacement))
        await until(lambda: len(replacement.events) == 1)
        self.assertEqual(replacement.events[0]["type"], "agent_runtime_end")
        transport.acknowledge(2)
        self.assertFalse(transport.pending)
        sender.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sender

    async def test_slow_socket_does_not_block_model_emissions(self):
        socket = Socket()
        async def slow_send(_):
            await asyncio.sleep(100)
        socket.send_text = slow_send
        transport = RuntimeTransport(socket)
        transport.socket = socket
        sender = asyncio.create_task(transport.deliver(socket))
        for n in range(100):
            await asyncio.wait_for(transport.send_json({"chunk": str(n)}), .1)
        self.assertEqual(len(transport.pending), 100)
        sender.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sender

    async def test_real_queue_finishes_disconnected_and_reconnect_replays(self):
        await self.exercise_queue()

    async def test_frame_wait_and_appended_user_batch_survive_disconnect(self):
        await self.exercise_queue(frame_wait=True)

    async def test_page_close_cancels_generation_and_preserves_queued_user(self):
        await self.exercise_queue(page_close=True)

    async def test_page_close_cancels_guard_wait(self):
        await self.exercise_queue(page_close=True, guard_wait=True)

    async def test_page_close_preserves_user_batch_waiting_for_frame(self):
        await self.exercise_queue(page_close=True, frame_wait=True)

    async def test_grace_expiry_cancels_guard_and_removes_context(self):
        with patch("websocket.transport.RECONNECT_GRACE_SECONDS", .03):
            await self.exercise_queue(expire=True, guard_wait=True)

    async def test_grace_is_ten_minutes(self):
        self.assertEqual(RECONNECT_GRACE_SECONDS, 600)

    async def test_retirement_cancels_background_streams_and_lt_owner(self):
        socket = Socket()
        context = RuntimeContext(None, None, None, {})
        transport = RuntimeTransport(socket)
        transport.context = context
        transport.client_id = "transport-test"
        context.runtime_transport = transport
        socket.app.state.websocket_runtime_contexts = {"transport-test": context}
        socket.app.state.lt_runtime_context = context
        socket.app.state.lt_memory_scheduler_wake_event = asyncio.Event()
        tasks = [asyncio.create_task(asyncio.Event().wait()) for _ in range(4)]
        transport.task = tasks[0]
        context.background_tasks.add(tasks[1])
        context.runtime_memory_update_task = tasks[2]
        context.runtime_lt_log_mention_backfill_task = tasks[3]
        response = SimpleNamespace(aclose=AsyncMock())
        context.active_streams["brain"] = response
        await transport.send_json({"type": "private"})
        await asyncio.sleep(0)
        await transport.stop()
        await transport.stop()  # Idempotent and no second close/write.
        self.assertTrue(all(task.cancelled() for task in tasks))
        self.assertIsNone(socket.app.state.lt_runtime_context)
        self.assertTrue(socket.app.state.lt_memory_scheduler_wake_event.is_set())
        self.assertEqual(socket.app.state.websocket_runtime_contexts, {})
        self.assertFalse(transport.pending)
        response.aclose.assert_awaited_once()

    async def test_old_socket_and_old_cleanup_cannot_retire_replacement(self):
        socket = Socket()
        context = RuntimeContext(None, None, None, {})
        transport = RuntimeTransport(socket)
        transport.context = context
        transport.client_id = "transport-test"
        transport.attach(socket)
        replacement = Socket(socket.app, soft=True)
        transport.attach(replacement)
        transport.detach(socket)
        self.assertIs(transport.socket, replacement)
        self.assertIsNone(transport.expiry)
        new_context = RuntimeContext(None, None, None, {})
        socket.app.state.websocket_runtime_contexts = {"transport-test": new_context}
        socket.app.state.lt_runtime_context = new_context
        await transport.stop()
        self.assertIs(socket.app.state.websocket_runtime_contexts["transport-test"], new_context)
        self.assertIs(socket.app.state.lt_runtime_context, new_context)

    async def test_idle_lt_scheduler_releases_retired_context_from_ram(self):
        import runtime.LT_memory as lt
        socket = Socket()
        context = RuntimeContext(None, None, None, {})
        transport = RuntimeTransport(socket)
        transport.context = context
        transport.client_id = "transport-test"
        context.runtime_transport = transport
        socket.app.state.websocket_runtime_contexts = {"transport-test": context}
        ref = weakref.ref(context)
        with patch.object(lt, "lt_memory_has_pending_work", lambda _: True), \
                patch.object(lt, "get_lt_scheduler_interval_seconds", lambda **_: 0.01), \
                patch.object(lt, "schedule_lt_memory_idle_update", lambda **_: None):
            scheduler = asyncio.create_task(lt.run_lt_memory_server_scheduler(socket.app.state))
            try:
                await until(lambda: getattr(socket.app.state, "lt_runtime_context", None) is context)
                await transport.stop()
                del context, transport
                await asyncio.sleep(.03)
                gc.collect()
                self.assertIsNone(ref())
            finally:
                scheduler.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await scheduler

    async def exercise_queue(self, frame_wait=False, page_close=False, guard_wait=False, expire=False):
        socket = Socket()
        context = RuntimeContext(None, None, None, {})
        socket.app.state.websocket_runtime_contexts = {"transport-test": context}
        release = asyncio.Event()
        started = []
        completed = []
        interrupted = []
        frame_release = asyncio.Event()
        if frame_wait:
            context.runtime_memory_update_task = asyncio.create_task(frame_release.wait())

        async def wait_frame(_):
            if frame_wait:
                await asyncio.shield(context.runtime_memory_update_task)

        async def process(context, message):
            if message.get("_interrupt_before_brain"):
                interrupted.append(message["text"])
                raise asyncio.CancelledError()
            started.append(message["text"])
            await context.websocket.send_json({"type": "agent_runtime_start"})
            if guard_wait:
                future = asyncio.get_running_loop().create_future()
                context.runtime_action_guard_confirmations["test"] = future
                await future
            else:
                await release.wait()
            completed.append(message["text"])
            await context.websocket.send_json({"type": "chunk", "text": message["text"]})
            await context.websocket.send_json({"type": "agent_runtime_end"})

        async def initialize(context, **kwargs):
            await context.websocket.accept()

        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(ws, "get_or_create_connection_context", return_value=(context, False)))
            for name in ("ensure_initial_runtime_snapshot", "note_lt_foreground_state", "note_lt_user_activity",
                         "register_lt_websocket_connection", "unregister_lt_websocket_connection"):
                stack.enter_context(patch.object(ws, name))
            for name in ("cancel_lt_memory_idle_update", "preempt_update_lt_facts_actions",
                         "apply_runtime_response_feedback", "refresh_pending_brain_usage"):
                stack.enter_context(patch.object(ws, name, new=AsyncMock()))
            stack.enter_context(patch.object(ws, "wait_for_runtime_memory_update", side_effect=wait_frame))
            stack.enter_context(patch.object(ws, "reject_when_all_models_offline", new=AsyncMock(return_value=False)))
            stack.enter_context(patch.object(ws, "initialize_connection", side_effect=initialize))
            stack.enter_context(patch.object(ws, "process_message", side_effect=process))
            endpoint = asyncio.create_task(ws.websocket_endpoint(socket))
            try:
                await until(lambda: socket.accepted and context.runtime_transport.socket is socket)
                await socket.incoming.put({"text": "first"})
                if frame_wait:
                    await until(lambda: any(e.get("type") == "pending_user_batch_open" for e in socket.events))
                    await socket.incoming.put({"text": "second", "append_to_pending_batch": True})
                    await socket.incoming.put({"text": "third", "append_to_pending_batch": True})
                    await until(lambda: any("messages: 3" in e.get("message", "") for e in socket.events))
                else:
                    await until(lambda: started == ["first"])
                    await socket.incoming.put({"text": "second"})
                    await until(lambda: context.runtime_pending_requests_queue.qsize() == 1)
                worker = context.runtime_transport.task
                await socket.close(code=PAGE_CLOSED_CODE if page_close else 1006)
                await asyncio.wait_for(endpoint, 1)
                if page_close or expire:
                    await until(lambda: context.runtime_transport.stop_task is not None)
                    await asyncio.wait_for(context.runtime_transport.stop_task, 1)
                    self.assertTrue(worker.done())
                    self.assertFalse(socket.app.state.websocket_runtime_contexts)
                    self.assertFalse(context.runtime_action_guard_confirmations)
                    self.assertFalse(context.runtime_transport.pending)
                    self.assertEqual(completed, [])
                    if frame_wait:
                        self.assertTrue(all(text in interrupted[0] for text in ("first", "second", "third")))
                    else:
                        self.assertEqual(interrupted, ["second"])
                    return
                expiry = context.runtime_transport.expiry
                self.assertIsNotNone(expiry)
                release.set()
                frame_release.set()
                expected_count = 1 if frame_wait else 2
                await until(lambda: len(completed) == expected_count)
                if frame_wait:
                    self.assertTrue(all(text in completed[0] for text in ("first", "second", "third")))
                else:
                    self.assertEqual(completed, ["first", "second"])
                self.assertFalse(worker.done())
                replacement = Socket(socket.app, soft=True)
                endpoint = asyncio.create_task(ws.websocket_endpoint(replacement))
                await until(lambda: sum(e.get("type") == "agent_runtime_end" for e in replacement.events) == expected_count)
                self.assertTrue(replacement.events[0]["live_resume"])
                self.assertIs(context.runtime_transport.task, worker)
                self.assertTrue(expiry.cancelled())
                self.assertIsNone(context.runtime_transport.expiry)
                self.assertEqual(started, completed)
                await replacement.incoming.put({"type": "runtime_event_ack", "sequence": context.runtime_transport.sequence})
                await until(lambda: not context.runtime_transport.pending)
                await replacement.close()
                await asyncio.wait_for(endpoint, 1)
            finally:
                endpoint.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await endpoint
                await asyncio.wait_for(stop_runtime_transports(socket.app.state), 1)
