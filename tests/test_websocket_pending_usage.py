import unittest
import asyncio
from types import SimpleNamespace

from runtime.action_guard import confirm_runtime_action_guards
from runtime.registry import runtime_state
from config_loader import (
    config,
)
from utils.brain_client_utils import (
    get_brain_runtime_config,
)
from utils.tool_results import (
    clear_runtime_tool_results,
)
from websocket import (
    apply_runtime_resume,
    build_runtime_action_guard_retry_request,
    apply_session_bootstrap,
    cancel_current_task,
    emit_runtime_action_guard_confirmation_failure,
    reject_when_all_models_offline,
    refresh_pending_brain_usage,
    wait_for_runtime_memory_update,
)
from utils.runtime_action_abort import (
    mark_runtime_action_started,
)
from utils.actions.common_action_utils import RuntimeActionCall


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

    def test_stale_guard_confirmation_builds_single_retry_with_original_context(self):

        message = {
            "decision": "continue",
            "action": "save_delayed_memory",
            "guard": "save_delayed_memory",
            "confirmation_id": "turn_7:save_delayed_memory:abc",
            "id": "save_delayed_memory_7",
            "retry_attempt": 1,
            "retry_user_message": "создай отчот",
            "retry_context_snapshot": {
                "system_prompt": "original system",
                "user_prompt": "original model payload",
            },
        }

        retry_request = build_runtime_action_guard_retry_request(
            message
        )

        self.assertEqual(
            retry_request["type"],
            "runtime_action_guard_retry",
        )
        self.assertEqual(
            retry_request["text"],
            "создай отчот",
        )
        self.assertEqual(
            retry_request["runtime_action_guard_retry"],
            {
                "action": "save_delayed_memory",
                "guard": "save_delayed_memory",
                "confirmation_id": "turn_7:save_delayed_memory:abc",
                "id": "save_delayed_memory_7",
                "attempt": 1,
                "context_snapshot": {
                    "system_prompt": "original system",
                    "user_prompt": "original model payload",
                },
            },
        )

        second_attempt = dict(
            message,
            retry_attempt=2,
        )
        self.assertIsNone(
            build_runtime_action_guard_retry_request(
                second_attempt
            )
        )
        self.assertIsNone(
            build_runtime_action_guard_retry_request({
                **message,
                "decision": "reject",
            })
        )
        self.assertIsNone(
            build_runtime_action_guard_retry_request({
                **message,
                "guard": "save_session",
            })
        )

    async def test_stale_guard_confirmation_failure_is_terminal_for_same_bubble(self):

        context = SimpleNamespace(
            emitter=FakeEmitter(),
        )

        await emit_runtime_action_guard_confirmation_failure(
            context,
            {
                "decision": "continue",
                "action": "save_delayed_memory",
                "confirmation_id": "stale-confirmation",
                "id": "save_delayed_memory_3",
            },
        )

        self.assertEqual(
            context.emitter.events,
            [{
                "type": "runtime_action",
                "action": "save_delayed_memory",
                "status": "failed",
                "display_name": "SAVE_DELAYED_MEMORY",
                "close_tag": True,
                "confirmation_id": "stale-confirmation",
                "error": "runtime_action_confirmation_expired",
                "text": "SAVE_DELAYED_MEMORY: FAILED",
                "detail": "The original confirmation no longer exists after reconnect.",
                "id": "save_delayed_memory_3",
            }],
        )

    async def test_action_guard_retry_bypasses_only_matching_guard_once(self):

        context = SimpleNamespace(
            emitter=FakeEmitter(),
            runtime_action_guard_confirmations={},
            runtime_action_guard_retry={
                "action": "save_delayed_memory",
                "guard": "save_delayed_memory",
                "confirmation_id": "stale-confirmation",
                "id": "save_delayed_memory_4",
                "attempt": 1,
            },
            runtime_action_guard_retry_consumed=False,
            runtime_action_failure_followup_messages=[],
        )
        action = RuntimeActionCall(
            name="SAVE_DELAYED_MEMORY",
            payload="title: Replay report",
        )

        (
            confirmed_action_ids,
            rejected_action_ids,
            confirmation_ids,
            action_display_ids,
        ) = await confirm_runtime_action_guards(
            context,
            (action,),
            user_message="создай отчот",
        )

        self.assertEqual(
            confirmed_action_ids,
            {id(action)},
        )
        self.assertEqual(
            rejected_action_ids,
            set(),
        )
        self.assertEqual(
            confirmation_ids[id(action)],
            "stale-confirmation",
        )
        self.assertEqual(
            action_display_ids[id(action)],
            "save_delayed_memory_4",
        )
        self.assertTrue(
            context.runtime_action_guard_retry_consumed
        )
        self.assertFalse(
            any(
                event.get("type") == "runtime_action_guard_confirmation"
                for event in context.emitter.events
            )
        )

        wrong_action = RuntimeActionCall(
            name="SAVE_DELAYED_MEMORY",
            payload="title: Second report",
        )
        context.runtime_action_guard_confirmations = {}

        async def reject_new_confirmation(event):
            await FakeEmitter.emit(
                context.emitter,
                event,
            )
            if event.get("type") == "runtime_action_guard_confirmation":
                future = context.runtime_action_guard_confirmations[
                    event["confirmation_id"]
                ]
                future.set_result("reject")

        context.emitter.emit = reject_new_confirmation

        confirmed, rejected, _, _ = await confirm_runtime_action_guards(
            context,
            (wrong_action,),
            user_message="сделай ещё один отчёт",
        )

        self.assertEqual(confirmed, set())
        self.assertEqual(rejected, {id(wrong_action)})

    async def test_cancel_current_task_aborts_active_action_when_task_already_done(self):

        context = SimpleNamespace(
            emitter=FakeEmitter(),
            runtime_action_events=[],
            runtime_active_action_markers=[],
            runtime_turn_aborted_actions=[],
            runtime_action_guard_confirmations={},
            runtime_current_turn_id="turn_done_abort",
            active_streams={},
        )
        logger = FakeLogger()

        async def finished():
            return None

        task = asyncio.create_task(
            finished()
        )
        await task

        mark_runtime_action_started(
            context,
            action="save_delayed_memory",
            action_id="save_delayed_memory_1",
            display_name="SAVE_DELAYED_MEMORY",
            text="SAVE_DELAYED_MEMORY",
            close_tag=True,
        )

        await cancel_current_task(
            task,
            logger,
            context,
            update_memory=False,
            emit_aborted_actions=True,
        )

        self.assertEqual(
            context.runtime_active_action_markers,
            [],
        )
        self.assertEqual(
            context.runtime_action_events[0]["status"],
            "aborted",
        )
        self.assertEqual(
            context.emitter.events[0]["text"],
            "SAVE_DELAYED_MEMORY: ABORTED",
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
            current_session_user_message_count=0,
            current_session_assistant_message_count=0,
        )

        restored = apply_session_bootstrap(
            context,
            {
                "type": "session_bootstrap",
                "runtime_memory": "topic: restored runtime state",
                "runtime_memory_updates": 7,
                "runtime_snapshot": {
                    "index": 4,
                    "turn_number": 14,
                    "user_message_count": 15,
                    "assistant_message_count": 14,
                    "current_session_user_message_count": 15,
                    "current_session_assistant_message_count": 14,
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
            context.turn_number,
            14,
        )
        self.assertEqual(
            context.user_message_count,
            15,
        )
        self.assertEqual(
            context.assistant_message_count,
            14,
        )
        self.assertEqual(
            context.current_session_user_message_count,
            0,
        )
        self.assertEqual(
            context.current_session_assistant_message_count,
            0,
        )
        self.assertEqual(
            context.runtime_memory_snapshots[0][
                "current_session_user_message_count"
            ],
            0,
        )
        self.assertEqual(
            context.runtime_memory_snapshots[0][
                "current_session_assistant_message_count"
            ],
            0,
        )
        self.assertEqual(
            context.runtime_memory_snapshots[0]["turn_number"],
            14,
        )
        self.assertEqual(
            len(context.runtime_memory_snapshots),
            1,
        )

    async def test_runtime_resume_restores_persisted_session_and_turn_counter(self):

        context = SimpleNamespace(
            runtime_memory="session status: New session",
            runtime_memory_stable="session status: New session",
            runtime_memory_updates=0,
            runtime_memory_snapshots=[],
            runtime_memory_snapshot_index=0,
            runtime_turn_counter=3,
            turn_number=3,
            user_message_count=3,
            assistant_message_count=3,
            current_session_user_message_count=2,
            current_session_assistant_message_count=2,
            session_memory="",
            runtime_l3_session_memory="",
            runtime_session_memory_updates=0,
            runtime_l3_saved_runtime_snapshot_index=4,
            session_memory_source="",
            delayed_memory_reports={
                "48ggds": {
                    "id": "48ggds",
                    "title": "Reconnect memory",
                },
            },
        )

        restored = apply_runtime_resume(
            context,
            {
                "type": "runtime_resume",
                "runtime_memory": "topic: live reconnect state",
                "runtime_memory_updates": 9,
                "runtime_snapshot": {
                    "raw_memory": "topic: live reconnect state",
                    "turn_number": 11,
                    "runtime_turn_counter": 17,
                    "user_message_count": 11,
                    "assistant_message_count": 10,
                    "current_session_user_message_count": 7,
                    "current_session_assistant_message_count": 6,
                },
                "session_memory": "decision: keep reconnect persistence",
                "session_memory_source": "browser_soft_reconnect",
                "session_memory_updates": 5,
                "loaded_memory_ids": [
                    "48ggds",
                ],
            },
        )

        self.assertTrue(
            restored
        )
        self.assertEqual(
            context.runtime_turn_counter,
            17,
        )
        self.assertEqual(
            context.turn_number,
            11,
        )
        self.assertEqual(
            context.current_session_user_message_count,
            7,
        )
        self.assertEqual(
            context.current_session_assistant_message_count,
            6,
        )
        self.assertEqual(
            context.runtime_memory_snapshots[0][
                "current_session_user_message_count"
            ],
            7,
        )
        self.assertEqual(
            context.runtime_memory_snapshots[0][
                "current_session_assistant_message_count"
            ],
            6,
        )
        self.assertEqual(
            context.runtime_loaded_delayed_memory_ids,
            [
                "48ggds",
            ],
        )

    async def test_runtime_resume_ignores_removed_l3_only_payload_without_live_l1(self):

        context = SimpleNamespace(
            runtime_memory="session status: New session",
            runtime_memory_stable="session status: New session",
            runtime_memory_updates=0,
            runtime_memory_snapshots=[],
            runtime_memory_snapshot_index=0,
            runtime_turn_counter=0,
            turn_number=0,
            user_message_count=0,
            assistant_message_count=0,
            delayed_memory_reports={},
        )

        restored = apply_runtime_resume(
            context,
            {
                "type": "runtime_resume",
                "runtime_memory": "",
                "session_memory": "decision: restore legacy L3 only",
                "session_memory_source": "browser_soft_reconnect",
                "session_memory_updates": 2,
            },
        )

        self.assertFalse(restored)
        self.assertEqual(
            context.runtime_memory,
            "session status: New session",
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
                "runtime_memory": "session status: restored",
                "active_memory_records": [
                    "active_memory: Remind the user about eating "
                    "[ purpose: Trigger notification to user about eating ] "
                    "[ creation_time: 2026-06-21T17:00:00 ] "
                    "[ created_jin_message_number: 2 ] "
                    "[ elapsed_time: 00:00:00 ] "
                    "[ elapsed_jin_message_number: 0 ] "
                    "[ status: pending ]"
                ],
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
            "[ elapsed_time: 00:00:00 ]",
            context.active_memory_records[0],
        )
        self.assertIn(
            "[ elapsed_jin_message_number: 0 ]",
            context.active_memory_records[0],
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
                "runtime_memory": "session status: restored",
                "active_memory_records": [
                    "active_memory: Remind the user about eating "
                    "[ purpose: Trigger notification to user about eating ] "
                    "[ creation_time: 2026-06-21T17:00:00 ] "
                    "[ created_jin_message_number: 2 ] "
                    "[ elapsed_time: 00:00:00 ] "
                    "[ elapsed_jin_message_number: 3 ] "
                    "[ status: pending ]"
                ],
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
            "[ elapsed_time: 00:00:00 ]",
            context.active_memory_records[0],
        )
        self.assertIn(
            "[ elapsed_jin_message_number: 3 ]",
            context.active_memory_records[0],
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

    async def test_pending_brain_usage_emits_provisional_cyrillic_input(self):

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

            self.assertGreater(
                current_state["used_tokens"],
                0,
            )

            self.assertEqual(
                context.emitter.events[-1]["runtime"][runtime_id]["used_tokens"],
                current_state["used_tokens"],
            )

        finally:
            runtime_state.update_runtime_state(
                runtime_id=runtime_id,
                used_tokens=original_state["used_tokens"],
                context_tokens=original_state["context_tokens"],
                total_tokens=original_state["total_tokens"],
                max_tokens=original_state["max_tokens"],
                last_error=original_state["last_error"],
                status=original_state["status"],
            )

    async def test_pending_brain_usage_applies_provider_calibration(self):

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
            runtime_token_estimate_scales={
                runtime_id: 2.0,
            },
        )

        try:
            await refresh_pending_brain_usage(
                context,
                "hi",
            )
            calibrated_tokens = runtime_state.get_runtime_state(
                runtime_id
            )["used_tokens"]

            context.runtime_token_estimate_scales = {}
            await refresh_pending_brain_usage(
                context,
                "hi",
            )
            baseline_tokens = runtime_state.get_runtime_state(
                runtime_id
            )["used_tokens"]

            self.assertEqual(
                calibrated_tokens,
                baseline_tokens * 2,
            )

        finally:
            runtime_state.update_runtime_state(
                runtime_id=runtime_id,
                used_tokens=original_state["used_tokens"],
                context_tokens=original_state["context_tokens"],
                total_tokens=original_state["total_tokens"],
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
