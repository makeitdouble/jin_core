import unittest
import asyncio
from types import SimpleNamespace

from runtime import (
    runtime_state,
)
from utils.brain import (
    get_brain_runtime_config,
)
from websocket import (
    apply_session_bootstrap,
    refresh_pending_brain_usage,
    wait_for_runtime_memory_update,
)


class FakeEmitter:

    def __init__(self):

        self.events = []

    async def emit(
        self,
        event,
    ):

        self.events.append(
            event
        )


class FakeLogger:

    def __init__(self):

        self.runtime_logs = []
        self.errors = []

    async def log_runtime(
        self,
        message: str,
    ):

        self.runtime_logs.append(
            message
        )

    async def log_error(
        self,
        message: str,
        details: str | None = None,
    ):

        self.errors.append(
            (
                message,
                details,
            )
        )


class WebSocketPendingUsageTests(unittest.IsolatedAsyncioTestCase):

    async def test_session_bootstrap_restores_browser_memory(self):

        context = SimpleNamespace(
            runtime_memory="session status: New session",
            runtime_memory_stable="session status: New session",
            runtime_memory_updates=0,
            runtime_memory_snapshots=[
                {
                    "index": 0,
                    "raw_memory": "session status: New session",
                },
            ],
            runtime_memory_snapshot_index=0,
            session_memory="",
            session_memory_source="",
            runtime_l3_session_memory="",
            runtime_session_memory_updates=0,
        )

        restored = apply_session_bootstrap(
            context,
            {
                "type": "session_bootstrap",
                "session_memory": "decision: Resume memory work",
                "session_memory_source": "browser_localStorage",
                "session_memory_updates": 2,
                "runtime_memory": "topic: restored runtime state",
                "runtime_memory_updates": 7,
            },
        )

        self.assertTrue(
            restored
        )
        self.assertEqual(
            context.session_memory,
            "decision: Resume memory work",
        )
        self.assertEqual(
            context.runtime_l3_session_memory,
            "decision: Resume memory work",
        )
        self.assertEqual(
            context.runtime_session_memory_updates,
            2,
        )
        self.assertEqual(
            context.session_memory_source,
            "browser_localStorage",
        )
        self.assertEqual(
            context.runtime_memory,
            "topic: restored runtime state",
        )
        self.assertEqual(
            context.runtime_memory_stable,
            "topic: restored runtime state",
        )
        self.assertEqual(
            context.runtime_memory_updates,
            7,
        )
        self.assertEqual(
            len(context.runtime_memory_snapshots),
            1,
        )
        self.assertEqual(
            context.runtime_memory_snapshots[0]["raw_memory"],
            "topic: restored runtime state",
        )

    async def test_pending_brain_usage_emits_before_stream_start(self):

        brain_runtime = get_brain_runtime_config()
        runtime_id = brain_runtime["runtime_id"]
        original_state = runtime_state.get_runtime_state(
            runtime_id
        )
        context = SimpleNamespace(
            emitter=FakeEmitter(),
            deep_thought_count=0,
            runtime_search_result="",
            runtime_search_result_id="",
        )

        try:
            await refresh_pending_brain_usage(
                context,
                "hi",
            )

            current_state = runtime_state.get_runtime_state(
                runtime_id
            )

            self.assertGreater(
                current_state["used_tokens"],
                0,
            )

            self.assertEqual(
                current_state["max_tokens"],
                brain_runtime["context_window"],
            )

            self.assertEqual(
                context.emitter.events[-1]["runtime"][runtime_id]["used_tokens"],
                current_state["used_tokens"],
            )

        finally:
            runtime_state.update_runtime_state(
                runtime_id=runtime_id,
                used_tokens=original_state["used_tokens"],
                max_tokens=original_state["max_tokens"],
                last_error=original_state["last_error"],
                status=original_state["status"],
            )

    async def test_pending_brain_usage_waits_for_translated_input(self):

        brain_runtime = get_brain_runtime_config()
        runtime_id = brain_runtime["runtime_id"]
        original_state = runtime_state.get_runtime_state(
            runtime_id
        )
        context = SimpleNamespace(
            emitter=FakeEmitter(),
            deep_thought_count=0,
            runtime_search_result="",
            runtime_search_result_id="",
        )

        try:
            await refresh_pending_brain_usage(
                context,
                "привет",
            )

            current_state = runtime_state.get_runtime_state(
                runtime_id
            )

            self.assertEqual(
                current_state["used_tokens"],
                original_state["used_tokens"],
            )

            self.assertEqual(
                context.emitter.events,
                [],
            )

        finally:
            runtime_state.update_runtime_state(
                runtime_id=runtime_id,
                used_tokens=original_state["used_tokens"],
                max_tokens=original_state["max_tokens"],
                last_error=original_state["last_error"],
                status=original_state["status"],
            )

    async def test_wait_for_runtime_memory_update_blocks_until_done(self):

        async def update_memory():
            await asyncio.sleep(0.01)
            context.memory_updated = True

        context = SimpleNamespace(
            logger=FakeLogger(),
            runtime_memory_update_task=None,
            memory_updated=False,
        )
        task = asyncio.create_task(
            update_memory()
        )
        context.runtime_memory_update_task = task

        await wait_for_runtime_memory_update(
            context
        )

        self.assertTrue(
            context.memory_updated
        )
        self.assertIsNone(
            context.runtime_memory_update_task
        )
        self.assertEqual(
            context.logger.runtime_logs,
            [
                "[WS] waiting pending memory update",
            ],
        )

    async def test_wait_for_runtime_memory_update_swallows_update_failure(self):

        async def fail_memory_update():
            raise RuntimeError(
                "context exceeded"
            )

        context = SimpleNamespace(
            logger=FakeLogger(),
            runtime_memory_update_task=None,
        )
        task = asyncio.create_task(
            fail_memory_update()
        )
        context.runtime_memory_update_task = task

        await wait_for_runtime_memory_update(
            context
        )

        self.assertIsNone(
            context.runtime_memory_update_task
        )
        self.assertEqual(
            context.logger.errors,
            [
                (
                    "[MEMORY] pending memory update failed",
                    "context exceeded",
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()
