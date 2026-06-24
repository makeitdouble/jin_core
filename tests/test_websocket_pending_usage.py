import unittest
import asyncio
from types import SimpleNamespace

from runtime import (
    emit_runtime_session_memory_update,
    runtime_state,
)
from config_loader import (
    config,
)
from clients.brain_client_utils import (
    get_brain_runtime_config,
)
from websocket import (
    apply_runtime_resume,
    apply_session_bootstrap,
    arm_save_session_from_user_text,
    reject_when_all_models_offline,
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


class FakeStatusResponse:

    def __init__(
        self,
        status_code: int,
    ):

        self.status_code = status_code


class FakeStatusHttpClient:

    def __init__(
        self,
        *,
        brain_online: bool,
        service_online: bool,
    ):

        self.brain_online = brain_online
        self.service_online = service_online
        self.calls = []

    async def get(
        self,
        url: str,
        *,
        timeout,
    ):

        self.calls.append(
            (
                url,
                timeout,
            )
        )

        if url.startswith(
            config.BRAIN_API_BASE
        ):
            return FakeStatusResponse(
                200 if self.brain_online else 503
            )

        if url.startswith(
            config.SERVICE_API_BASE
        ):
            return FakeStatusResponse(
                200 if self.service_online else 503
            )

        return FakeStatusResponse(
            404
        )


class FakeWebSocket:

    def __init__(self):

        self.messages = []

    async def send_json(
        self,
        payload,
    ):

        self.messages.append(
            payload
        )


class WebSocketPendingUsageTests(unittest.IsolatedAsyncioTestCase):

    async def test_arm_save_session_prearms_without_banner(self):

        context = SimpleNamespace(
            emitter=FakeEmitter(),
            logger=FakeLogger(),
            runtime_save_session_armed=False,
            runtime_save_session_requested=False,
        )

        armed = await arm_save_session_from_user_text(
            context,
            "\u0441\u043e\u0445\u0440\u0430\u043d\u0438 \u0441\u0435\u0441\u0441\u0438\u044e",
        )

        self.assertTrue(
            armed,
        )
        self.assertTrue(
            context.runtime_save_session_armed,
        )
        self.assertFalse(
            context.runtime_save_session_requested,
        )
        self.assertFalse(
            context.runtime_save_session_action_emitted,
        )
        self.assertEqual(
            context.emitter.events,
            [],
        )

    async def test_rejects_user_request_when_all_models_are_offline(self):

        http_client = FakeStatusHttpClient(
            brain_online=False,
            service_online=False,
        )
        context = SimpleNamespace(
            clients={
                "service": SimpleNamespace(
                    client=http_client,
                ),
            },
            logger=FakeLogger(),
            websocket=FakeWebSocket(),
        )

        rejected = await reject_when_all_models_offline(
            context
        )

        self.assertTrue(
            rejected
        )
        self.assertEqual(
            context.logger.errors,
            [
                (
                    "[WS] all model runtimes are offline",
                    None,
                ),
            ],
        )
        self.assertEqual(
            context.websocket.messages[-1]["type"],
            "error",
        )
        self.assertEqual(
            context.websocket.messages[-1]["component"],
            "runtime_status",
        )

    async def test_all_models_guard_allows_request_when_any_model_is_online(self):

        http_client = FakeStatusHttpClient(
            brain_online=True,
            service_online=False,
        )
        context = SimpleNamespace(
            clients={
                "service": SimpleNamespace(
                    client=http_client,
                ),
            },
            logger=FakeLogger(),
            websocket=FakeWebSocket(),
        )

        rejected = await reject_when_all_models_offline(
            context
        )

        self.assertFalse(
            rejected
        )
        self.assertEqual(
            context.logger.errors,
            [],
        )
        self.assertEqual(
            context.websocket.messages,
            [],
        )

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
            runtime_session_event_snapshots=[],
        )

        restored = apply_session_bootstrap(
            context,
            {
                "type": "session_bootstrap",
                "session_memory": "decision: Resume memory work",
                "session_memory_source": "browser_localStorage",
                "session_memory_updates": 2,
                "session_event_snapshots": [
                    {
                        "memory_type": "session_event_snapshot",
                        "memory": "decision: Resume memory work",
                    }
                ],
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
            context.runtime_session_event_snapshots,
            [
                {
                    "memory_type": "session_event_snapshot",
                    "memory": "decision: Resume memory work",
                }
            ],
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
            context.runtime_memory_snapshots[0]["index"],
            0,
        )
        self.assertEqual(
            context.runtime_memory_snapshots[0]["raw_memory"],
            "topic: restored runtime state",
        )
        self.assertEqual(
            context.runtime_memory_snapshot_index,
            0,
        )

    async def test_session_bootstrap_normalizes_restored_snapshot_index(self):

        context = SimpleNamespace(
            runtime_memory="session status: New session",
            runtime_memory_stable="session status: New session",
            runtime_memory_updates=0,
            runtime_memory_snapshots=[],
            runtime_memory_snapshot_index=0,
            session_memory="",
            session_memory_source="",
            runtime_l3_session_memory="",
            runtime_session_memory_updates=0,
            runtime_session_event_snapshots=[],
        )

        restored = apply_session_bootstrap(
            context,
            {
                "type": "session_bootstrap",
                "runtime_memory": "topic: restored runtime state",
                "runtime_memory_updates": 7,
                "runtime_snapshot": {
                    "index": 4,
                    "raw_memory": "topic: restored runtime state",
                },
            },
        )

        self.assertTrue(
            restored
        )
        self.assertEqual(
            context.runtime_memory_snapshot_index,
            0,
        )
        self.assertEqual(
            context.runtime_memory_snapshots[0]["index"],
            0,
        )
        self.assertEqual(
            context.runtime_memory_snapshots[0]["raw_memory"],
            "topic: restored runtime state",
        )
        self.assertEqual(
            len(context.runtime_memory_snapshots),
            1,
        )

    async def test_runtime_resume_hydrates_active_memory_lifecycle_counters(self):

        context = SimpleNamespace(
            runtime_memory="session status: New session",
            runtime_memory_stable="session status: New session",
            runtime_memory_updates=0,
            runtime_memory_snapshots=[],
            runtime_memory_snapshot_index=0,
            turn_number=0,
            user_message_count=0,
            assistant_message_count=0,
            timestamp="2026-06-21T17:05:00",
            session_id="test-session",
        )

        restored = apply_runtime_resume(
            context,
            {
                "type": "runtime_resume",
                "runtime_memory": (
                    "active_memory: Remind the user about eating "
                    "[ purpose: Trigger notification to user about eating ] "
                    "[ creation_time: 2026-06-21T17:00:00 ] "
                    "[ created_jin_message_number: 2 ] "
                    "[ elapsed_time: 00:00:00 ] "
                    "[ elapsed_jin_message_number: 0 ] "
                    "[ status: pending ]"
                ),
                "runtime_memory_updates": 1,
            },
        )

        self.assertTrue(
            restored
        )
        self.assertEqual(
            context.turn_number,
            2,
        )
        self.assertEqual(
            context.assistant_message_count,
            2,
        )
        self.assertEqual(
            context.user_message_count,
            2,
        )
        self.assertIn(
            "[ elapsed_time: 00:05:00 ]",
            context.runtime_memory,
        )
        self.assertIn(
            "[ elapsed_jin_message_number: 0 ]",
            context.runtime_memory,
        )

    async def test_session_bootstrap_hydrates_active_memory_elapsed_counter_floor(self):

        context = SimpleNamespace(
            runtime_memory="session status: New session",
            runtime_memory_stable="session status: New session",
            runtime_memory_updates=0,
            runtime_memory_snapshots=[],
            runtime_memory_snapshot_index=0,
            session_memory="",
            session_memory_source="",
            runtime_l3_session_memory="",
            runtime_session_memory_updates=0,
            runtime_session_event_snapshots=[],
            turn_number=0,
            user_message_count=0,
            assistant_message_count=0,
            timestamp="2026-06-21T17:05:00",
            session_id="test-session",
        )

        restored = apply_session_bootstrap(
            context,
            {
                "type": "session_bootstrap",
                "runtime_memory": (
                    "active_memory: Remind the user about eating "
                    "[ purpose: Trigger notification to user about eating ] "
                    "[ creation_time: 2026-06-21T17:00:00 ] "
                    "[ created_jin_message_number: 2 ] "
                    "[ elapsed_time: 00:00:00 ] "
                    "[ elapsed_jin_message_number: 3 ] "
                    "[ status: pending ]"
                ),
                "runtime_memory_updates": 1,
            },
        )

        self.assertTrue(
            restored
        )
        self.assertEqual(
            context.turn_number,
            5,
        )
        self.assertEqual(
            context.assistant_message_count,
            5,
        )
        self.assertEqual(
            context.user_message_count,
            5,
        )
        self.assertIn(
            "[ elapsed_time: 00:05:00 ]",
            context.runtime_memory,
        )
        self.assertIn(
            "[ elapsed_jin_message_number: 3 ]",
            context.runtime_memory,
        )

    async def test_runtime_session_memory_update_is_not_browser_persisted_by_default(self):

        context = SimpleNamespace(
            emitter=FakeEmitter(),
            runtime_l3_session_memory="topic: restored but not saved",
            session_memory="",
            session_memory_source="browser_localStorage",
            runtime_session_memory_updates=1,
            runtime_session_event_snapshots=[
                {
                    "memory_type": "session_event_snapshot",
                    "memory": "topic: restored but not saved",
                }
            ],
        )

        await emit_runtime_session_memory_update(
            context
        )

        self.assertEqual(
            context.emitter.events[-1]["type"],
            "runtime_session_memory_update",
        )
        self.assertFalse(
            context.emitter.events[-1]["persist"],
        )
        self.assertEqual(
            context.emitter.events[-1]["event_snapshots"],
            context.runtime_session_event_snapshots,
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
