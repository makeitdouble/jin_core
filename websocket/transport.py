"""Page-session transport: model work never awaits a physical browser socket."""

import asyncio
import json
from collections import OrderedDict
from uuid import uuid4


class RuntimeTransport:
    def __init__(self, websocket):
        self.app = websocket.app
        self.query_params = websocket.query_params
        self.incoming = asyncio.Queue()
        self.pending = OrderedDict()
        self.changed = asyncio.Event()
        self.epoch = uuid4().hex
        self.sequence = 0
        self.acknowledged = 0
        self.socket = None
        self.task = None

    async def accept(self):
        # Physical connections are accepted by the endpoint, once each.
        pass

    async def receive_text(self):
        return await self.incoming.get()

    async def send_json(self, payload):
        self.sequence += 1
        # Serialize now: callers may mutate nested state after emitting it.
        self.pending[self.sequence] = json.dumps({
            **payload, "_jin_event_id": self.sequence,
        }, ensure_ascii=False)
        self.changed.set()

    def acknowledge(self, sequence):
        if type(sequence) is not int or not self.acknowledged < sequence <= self.sequence:
            return
        self.acknowledged = sequence
        while self.pending and next(iter(self.pending)) <= sequence:
            self.pending.popitem(last=False)

    async def deliver(self, websocket):
        sent = self.acknowledged
        while self.socket is websocket:
            self.changed.clear()
            while sent < self.sequence:
                if self.socket is not websocket:
                    return
                sent = max(sent, self.acknowledged)
                sequence = sent + 1
                payload = self.pending.get(sequence)
                if payload is not None:
                    await asyncio.wait_for(websocket.send_text(payload), timeout=10.0)
                sent = sequence
            await self.changed.wait()


async def stop_runtime_transports(app_state):
    tasks = []
    for context in getattr(app_state, "websocket_runtime_contexts", {}).values():
        transport = getattr(context, "runtime_transport", None)
        if transport is not None and transport.task is not None:
            transport.task.cancel()
            tasks.append(transport.task)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
