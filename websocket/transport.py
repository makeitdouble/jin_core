"""Page-session transport: model work never awaits a physical browser socket."""

import asyncio
import contextlib
import json
from collections import OrderedDict
from uuid import uuid4


RECONNECT_GRACE_SECONDS = 10 * 60
PAGE_CLOSED_CODE = 4001


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
        self.context = None
        self.client_id = ""
        self.stopping = False
        self.expiry = None
        self.stop_task = None
        self.stopping_tasks = set()

    def attach(self, socket):
        if self.expiry is not None:
            self.expiry.cancel()
            self.expiry = None
        self.socket = socket
        self.changed.set()

    def detach(self, socket):
        if self.socket is not socket or self.stopping:
            return
        self.socket = None
        self.context.runtime_lt_websocket_connected = False
        if self.expiry is not None:
            self.expiry.cancel()
        self.expiry = asyncio.get_running_loop().call_later(
            RECONNECT_GRACE_SECONDS, self.begin_stop,
        )

    def begin_stop(self):
        """Retire synchronously before awaiting cleanup, so reconnect cannot reuse us."""
        if self.stop_task is not None:
            return self.stop_task
        self.stopping = True
        if self.expiry is not None:
            self.expiry.cancel()
            self.expiry = None
        context = self.context
        store = getattr(self.app.state, "websocket_runtime_contexts", {})
        if store.get(self.client_id) is context:
            store.pop(self.client_id, None)
        if getattr(self.app.state, "lt_runtime_context", None) is context:
            self.app.state.lt_runtime_context = None
        if context is not None:
            context.runtime_lt_websocket_connected = False
            context.runtime_turn_abort_requested = True
            # Cancel guard waits; never resolve them as permission to execute.
            for future in list(context.runtime_action_guard_confirmations.values()):
                if not future.done():
                    future.cancel()
            context.runtime_action_guard_confirmations.clear()
            from runtime.LT_lane import get_active_lt_attempt, invalidate_lt_attempt
            attempt = get_active_lt_attempt(context)
            if attempt is not None:
                invalidate_lt_attempt(context, attempt)
            self.stopping_tasks.update(context.background_tasks)
            for name in ("runtime_memory_update_task", "runtime_lt_log_mention_backfill_task"):
                task = getattr(context, name, None)
                if task is not None:
                    self.stopping_tasks.add(task)
            for task in self.stopping_tasks:
                task.cancel()
        if self.task is not None:
            self.task.cancel()
        self.stop_task = asyncio.create_task(self._stop())
        return self.stop_task

    async def stop(self):
        await asyncio.shield(self.begin_stop())

    async def _stop(self):
        context = self.context
        try:
            if self.task is not None:
                await asyncio.gather(self.task, return_exceptions=True)
            if context is not None:
                tasks = self.stopping_tasks | set(context.background_tasks)
                for name in ("runtime_memory_update_task", "runtime_lt_log_mention_backfill_task"):
                    task = getattr(context, name, None)
                    if task is not None:
                        tasks.add(task)
                for task in tasks:
                    task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                context.background_tasks.clear()
                self.stopping_tasks.clear()
                for response in list(context.active_streams.values()):
                    with contextlib.suppress(Exception):
                        await response.aclose()
                context.active_streams.clear()
                from utils.mcp_client import close_context_mcp_manager
                with contextlib.suppress(Exception):
                    await close_context_mcp_manager(context)
        finally:
            from runtime.memory_profile import release_profile
            release_profile(context, self.app.state)
            self.pending.clear()
            while not self.incoming.empty():
                self.incoming.get_nowait()
            self.changed.set()
            wake = getattr(self.app.state, "lt_memory_scheduler_wake_event", None)
            if wake is not None:
                wake.set()

    async def accept(self):
        # Physical connections are accepted by the endpoint, once each.
        pass

    async def receive_text(self):
        return await self.incoming.get()

    async def send_json(self, payload):
        self.publish(payload)

    def publish(self, payload):
        if self.stopping:
            return
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
    for context in list(getattr(app_state, "websocket_runtime_contexts", {}).values()):
        transport = getattr(context, "runtime_transport", None)
        if transport is not None and transport.task is not None:
            tasks.append(transport.begin_stop())
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
