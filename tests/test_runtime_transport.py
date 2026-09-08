import asyncio
import contextlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from starlette.websockets import WebSocketDisconnect
import websocket as ws
from runtime.runtime_context import RuntimeContext
from websocket.transport import RuntimeTransport, stop_runtime_transports


class Socket:
    def __init__(self, app=None, soft=False):
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
        return json.dumps(data)

    async def close(self, code=1000):
        await self.incoming.put(None)


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

    async def exercise_queue(self, frame_wait=False):
        socket = Socket()
        context = RuntimeContext(None, None, None, {})
        socket.app.state.websocket_runtime_contexts = {"transport-test": context}
        release = asyncio.Event()
        started = []
        completed = []
        frame_release = asyncio.Event()
        if frame_wait:
            context.runtime_memory_update_task = asyncio.create_task(frame_release.wait())

        async def wait_frame(_):
            if frame_wait:
                await asyncio.shield(context.runtime_memory_update_task)

        async def process(context, message):
            started.append(message["text"])
            await context.websocket.send_json({"type": "agent_runtime_start"})
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
                await socket.close()
                await asyncio.wait_for(endpoint, 1)
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
