import asyncio
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from runtime import heartbeat as hb
from tests.test_bootstrap_owner_lifecycle import context
from utils import chat_log, session_restore
from utils.actions import RuntimeActionCall, RuntimeActionStreamFilter
from utils.actions.dispatcher import apply_runtime_action_calls
from websocket.messages import process_message


class HeartbeatClockTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_deadline_activity_reset_and_repeat_interval(self):
        c = context()
        c.runtime_heartbeat_enqueue = lambda _: None
        with patch.object(hb.time, "monotonic", return_value=1000):
            hb.note_activity(c)
            first = c.runtime_heartbeat_handle
            self.assertAlmostEqual(first.when() - asyncio.get_running_loop().time(), 900, delta=.1)
            generation = c.runtime_heartbeat_generation
        with patch.object(hb.time, "monotonic", return_value=1200):
            self.assertFalse(hb.eligible(c, generation))
            hb.note_activity(c)
            self.assertTrue(first.cancelled())
        with patch.object(hb.time, "monotonic", return_value=2100):
            self.assertFalse(hb.eligible(c, generation))
            self.assertTrue(hb.eligible(c, c.runtime_heartbeat_generation))
            c.heartbeat_tick_speed = 3600
            hb.finish_activity(c)
            self.assertAlmostEqual(c.runtime_heartbeat_handle.when() - asyncio.get_running_loop().time(), 3600, delta=.1)
        hb.stop_heartbeat(c)
        self.assertIsNone(c.runtime_heartbeat_handle)

    async def test_room_independence_and_frame_completion(self):
        a, b = context(), context()
        a.runtime_heartbeat_enqueue = b.runtime_heartbeat_enqueue = lambda _: None
        hb.note_activity(a)
        hb.note_activity(b)
        b_handle = b.runtime_heartbeat_handle
        a.runtime_memory_update_task = asyncio.get_running_loop().create_future()
        hb.finish_activity(a)
        self.assertIsNone(a.runtime_heartbeat_handle)
        self.assertIs(b.runtime_heartbeat_handle, b_handle)
        a.runtime_memory_update_task.set_result(None)
        await asyncio.sleep(0)
        self.assertIsNotNone(a.runtime_heartbeat_handle)
        hb.stop_heartbeat(a)
        hb.stop_heartbeat(b)

    async def test_disconnected_and_retired_rooms_are_ineligible(self):
        c = context()
        c.runtime_transport = SimpleNamespace(socket=None, stopping=False)
        c.runtime_heartbeat_last_activity = 0
        with patch.object(hb.time, "monotonic", return_value=900):
            self.assertFalse(hb.eligible(c, 0))
            c.runtime_transport.socket = object()
            self.assertTrue(hb.eligible(c, 0))
            c.runtime_transport.stopping = True
            self.assertFalse(hb.eligible(c, 0))


class HeartbeatActionTests(unittest.IsolatedAsyncioTestCase):
    def test_heartbeat_does_not_reapply_last_user_idle_credit_to_active_memory(self):
        from rules.brain_context_builder import build_brain_context
        for autonomous in (False, True):
            c = context()
            c.runtime_heartbeat_active = autonomous
            c.runtime_user_idle_seconds = 900
            c.active_memory_records = ["active_memory_1: remember"]
            with patch("utils.actions.refresh_active_memory_runtime_metadata", return_value=c.active_memory_records[0]) as refresh:
                build_brain_context(c)
            self.assertEqual(refresh.call_args.kwargs["add_runtime_user_idle_to_elapsed"], not autonomous)

    async def test_guard_retry_drops_original_heartbeat_notification(self):
        from agent.nodes.brain import BrainNode
        from agent.state import AgentState
        from tests.helpers.brain import brain_context_stub, brain_runtime_config
        c = brain_context_stub()
        c.runtime_action_guard_retry = {
            "context_snapshot": {"system_prompt": hb.HEARTBEAT_TICK_MESSAGE + "\nbase", "user_prompt": ""}
        }
        c.runtime_persistent_writes_restricted = True
        c.logger = SimpleNamespace(log_runtime=AsyncMock())
        stream = AsyncMock(return_value=("", ""))
        with patch("agent.nodes.brain.get_brain_runtime_config", return_value=brain_runtime_config()), patch(
            "agent.nodes.brain.emit_active_memory_records_update_if_dirty", new=AsyncMock()
        ), patch.object(BrainNode, "run_brain_stream", stream):
            await BrainNode().run(AgentState(user_input=""), c)
        self.assertNotIn("<HEARTBEAT_TICK_MESSAGE>", stream.call_args.kwargs["system_prompt"])

    async def test_interval_changes_are_never_satisfied_by_cached_results(self):
        c = context()
        c.runtime_persistent_writes_restricted = True
        for index, seconds in enumerate((3600, 600, 3600)):
            with patch("utils.chat_log.append_chat_runtime_event"):
                await apply_runtime_action_calls(
                    c, (RuntimeActionCall(name="SET_HEARTBEAT_TICK_SPEED", payload=json.dumps({"seconds": seconds})),),
                    runtime_message_id=f"message_{index}",
                )
            self.assertEqual(c.heartbeat_tick_speed, seconds)

    async def test_brain_initial_notification_disappears_on_followup(self):
        from agent.nodes.brain import BrainNode
        from agent.state import AgentState
        from tests.helpers.brain import brain_context_stub, brain_runtime_config
        from utils.tool_results import record_runtime_tool_result, TOOL_RESULT_KIND_RUNTIME_ACTION
        for failure in (False, True):
            c = brain_context_stub()
            c.runtime_turn_user_message = ""
            c.runtime_persistent_writes_restricted = True
            c.runtime_heartbeat_active = True
            c.websocket = SimpleNamespace(send_json=AsyncMock())
            c.emitter = SimpleNamespace(emit=AsyncMock())
            c.logger = SimpleNamespace(log_runtime=AsyncMock())
            state = AgentState(user_input="")
            state.metadata["heartbeat_tick"] = True
            calls = []
            async def stream(**kwargs):
                calls.append(kwargs)
                if len(calls) == 1:
                    self.assertTrue(kwargs["system_prompt"].startswith("<HEARTBEAT_TICK_MESSAGE>"))
                    self.assertFalse(kwargs.get("followup_tick"))
                    self.assertEqual(kwargs["brain_payload"], "")
                    if failure:
                        record_runtime_tool_result(c, TOOL_RESULT_KIND_RUNTIME_ACTION,
                            {"action": "set_heartbeat_tick_speed", "ok": False, "error": "bad seconds"})
                        c.runtime_action_events.append({
                            "name": "set_heartbeat_tick_speed", "status": "failed",
                            "payload": '{"seconds":1}', "failure_reason": "bad seconds",
                        })
                else:
                    self.assertNotIn("<HEARTBEAT_TICK_MESSAGE>", kwargs["system_prompt"])
                    self.assertTrue(kwargs["followup_tick"])
                return "", ""
            runtime = brain_runtime_config()
            runtime["runtime_actions"]["CAN_SET_HEARTBEAT_TICK_SPEED"] = True
            with patch("agent.nodes.brain.get_brain_runtime_config", return_value=runtime), patch(
                "agent.nodes.brain.emit_active_memory_records_update_if_dirty", new=AsyncMock()
            ), patch("agent.nodes.brain.config.BRAIN_MAX_FOLLOWUPS", 3), patch.object(
                BrainNode, "run_brain_stream", side_effect=stream
            ):
                await BrainNode().run(state, c)
            self.assertEqual(len(calls), 2 if failure else 1)

    async def test_normal_dispatch_validation_and_failure_followup(self):
        for payload, valid in [
            ('{"seconds":3600}', True), ('{"seconds":60.5}', True),
            ('{"seconds":59}', False), ('{"seconds":true}', False),
            ('{"seconds":"600"}', False), ('{"seconds":NaN}', False),
            ('{"seconds":Infinity}', False), ('[]', False), ('{', False),
            ('{"seconds":600,"extra":1}', False),
        ]:
            with self.subTest(payload=payload):
                c = context()
                c.runtime_persistent_writes_restricted = True
                with patch("utils.chat_log.append_chat_runtime_event"):
                    await apply_runtime_action_calls(c, (RuntimeActionCall(name="SET_HEARTBEAT_TICK_SPEED", payload=payload),))
                self.assertEqual(c.runtime_action_events[-1]["status"], "completed" if valid else "failed")
                self.assertEqual(bool(getattr(c, "runtime_failure_followup_entries", [])), not valid)
                self.assertEqual(c.heartbeat_tick_speed, json.loads(payload)["seconds"] if valid else 600)

    def test_stream_splits_literals_repetition_and_flush(self):
        name = "SET_HEARTBEAT_TICK_SPEED"
        marker = f'<{name}>{{"seconds":3600}}</{name}>'
        for cut in range(len(marker) + 1):
            parser = RuntimeActionStreamFilter(enabled_actions=[name])
            results = [parser.filter("before " + marker[:cut]), parser.filter(marker[cut:] + " after"), parser.flush_result()]
            self.assertEqual("".join(r.text for r in results).split(), ["before", "after"])
            self.assertEqual([a.name for r in results for a in r.actions], [name])
        for literal in ("`" + marker + "`", "[" + marker + "]", f"<{name}>{{", f"<{name}_EXAMPLE>"):
            parser = RuntimeActionStreamFilter(enabled_actions=[name])
            results = [parser.filter(ch) for ch in literal] + [parser.flush_result()]
            self.assertFalse(any(a.name == name for r in results for a in r.actions))
        parser = RuntimeActionStreamFilter(enabled_actions=[name])
        results = [parser.filter(marker + marker), parser.flush_result()]
        self.assertEqual(len([a for r in results for a in r.actions]), 2)


class HeartbeatPersistenceTests(unittest.IsolatedAsyncioTestCase):
    def test_blank_tick_and_anonymous_stream_ownership(self):
        from runtime.stream import RuntimeStream
        with tempfile.TemporaryDirectory() as tmp, patch.object(chat_log, "CHAT_LOG_ROOT", Path(tmp)), patch.object(chat_log, "chat_logging_enabled", return_value=True):
            c = context()
            c.session_id = "heartbeat_anon"
            c.runtime_anonymous_mode = True
            c.runtime_heartbeat_active = True
            c.runtime_turn_counter = 1
            c.runtime_current_turn_id = "turn_000001"
            chat_log.save_turn_reasoning(c, "silent reasoning")
            self.assertEqual(list(Path(tmp).iterdir()), [], "blank room reasoning must stay deferred")
            stream = SimpleNamespace(
                context=c, stream=SimpleNamespace(response="🐈"),
                is_brain_context=lambda: True,
            )
            RuntimeStream.capture_runtime_turn_response(stream)
            self.assertTrue(c.runtime_heartbeat_meaningful)
            self.assertTrue(list(Path(tmp).glob("*/*/*.jsonl")))
            chat_log.append_chat_log_entry(c, role="jin", text="🐈")
            restored = session_restore.build_runtime_reconnect_payload(c.session_id, root=tmp)
            self.assertEqual(restored["recent_turns"][-1]["jin"], "🐈")
            self.assertEqual(len(restored["messages"]), 1, "ownership event must not duplicate assistant bubbles")
            self.assertIsNone(session_restore.find_latest_completed_session_restore_payload(root=tmp))

    async def test_greeting_then_empty_text_failed_action_and_stop(self):
        for mode in ("silent", "text", "failed_action", "stopped_action", "stopped_text"):
            with self.subTest(mode=mode), ExitStack() as stack:
                root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
                stack.enter_context(patch.object(chat_log, "CHAT_LOG_ROOT", root))
                stack.enter_context(patch.object(session_restore, "CHAT_LOG_ROOT", root))
                stack.enter_context(patch.object(chat_log, "chat_logging_enabled", return_value=True))
                c = context()
                c.runtime_session_restore_priming = True

                async def model(state, runtime):
                    runtime.runtime_turn_reasoning_content = "reasoning"
                    if state.metadata.get("session_restore_resume"):
                        state.brain_response = "greeting"
                        return
                    self.assertEqual(state.user_input, "")
                    self.assertTrue(state.metadata["heartbeat_tick"])
                    if "action" in mode:
                        hb.mark_heartbeat_activity(runtime)
                        runtime.heartbeat_tick_speed = 3600
                    if mode == "text":
                        state.brain_response = "🐈"
                    if mode == "stopped_text":
                        runtime.runtime_turn_assistant_response = "partial"
                    if mode.startswith("stopped"):
                        raise asyncio.CancelledError()

                stack.enter_context(patch("websocket.messages.AgentRuntime", return_value=SimpleNamespace(run=model)))
                for name in ("load_delayed_memory_by_tags", "emit_session_actions_update"):
                    stack.enter_context(patch("websocket.messages." + name, new=AsyncMock()))
                for name in ("schedule_runtime_memory_update", "schedule_pending_update_lt_facts_actions"):
                    stack.enter_context(patch("websocket.messages." + name))
                stack.enter_context(patch("websocket.messages.handle_fatal_runtime_error", new=AsyncMock(side_effect=AssertionError("unexpected runtime error"))))
                await process_message(c, {"type": "archived_session_resume"})
                self.assertEqual(list(root.iterdir()), [])
                if mode.startswith("stopped"):
                    with self.assertRaises(asyncio.CancelledError):
                        await process_message(c, {"type": "heartbeat_tick"})
                else:
                    await process_message(c, {"type": "heartbeat_tick"})
                restored = session_restore.find_latest_completed_session_restore_payload(root=root)
                if mode == "silent":
                    self.assertIsNone(restored)
                    self.assertEqual(list(root.iterdir()), [])
                    continue
                self.assertEqual(restored["source_session_id"], "child")
                self.assertTrue(restored["recent_turns"][-1]["heartbeat"])
                self.assertEqual(restored["recent_turns"][-1]["user"], "")
                self.assertEqual(restored["heartbeat_tick_speed"], 3600 if "action" in mode else 600)
                from websocket.bootstrap import apply_archived_session_continuation_state, build_session_bootstrap_chat_tail, apply_session_bootstrap
                fresh = context()
                payload = json.loads(json.dumps(restored))
                apply_session_bootstrap(fresh, payload, resolved_from_disk=True)
                apply_archived_session_continuation_state(fresh, payload)
                self.assertEqual(fresh.heartbeat_tick_speed, restored["heartbeat_tick_speed"])
                tail = build_session_bootstrap_chat_tail(fresh)
                self.assertTrue(tail[-1]["heartbeat"])
                self.assertEqual(tail[-1]["user"], "")
                rows = [json.loads(line) for path in root.glob("*/*/*.jsonl") for line in path.read_text(encoding="utf-8").splitlines()]
                self.assertFalse(any(row.get("role") == "user" for row in rows))
                self.assertIsNotNone(session_restore.read_archived_session_summary(next(root.glob("*/*/*.jsonl"))))

    def test_latest_cross_date_clear_barrier_and_deleted_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def write(date, session, rows):
                path = root / date / session / "120000.jsonl"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
                return path
            user = {"role": "user", "turn": 1, "text": "hi", "ts": "2026-10-20T12:00:00+00:00"}
            beat = {"role": "jin", "turn": 2, "text": "", "heartbeat": True, "heartbeat_tick_speed": 1800, "ts": "2026-10-20T13:00:00+00:00"}
            write("2026-10-20", "user", [user])
            p = write("2026-10-19", "beat", [beat])
            self.assertEqual(session_restore.find_latest_completed_session_restore_payload(root=root)["source_session_id"], "beat")
            session_restore.clear_normal_session_continuation(root=root)
            self.assertIsNone(session_restore.find_latest_completed_session_restore_payload(root=root))

            write("2026-10-19", "beat", [beat, {**beat, "text": "late completion"}])
            self.assertIsNone(session_restore.find_latest_completed_session_restore_payload(root=root))
            write("2026-10-19", "beat", [beat, {**beat, "turn": 3, "ts": "2026-10-20T14:00:00+00:00"}])
            self.assertEqual(session_restore.find_latest_completed_session_restore_payload(root=root)["source_session_id"], "beat")
            p.unlink()
            self.assertIsNone(session_restore.find_latest_completed_session_restore_payload(root=root))


class HeartbeatQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_serial_queue_activity_does_not_abort_and_no_accumulation(self):
        import websocket as ws
        c = context()
        received = asyncio.Queue()
        started, release = asyncio.Event(), asyncio.Event()
        calls = []
        active = 0
        async def process(_, data):
            nonlocal active
            active += 1
            self.assertEqual(active, 1)
            calls.append(data["type"])
            started.set()
            await release.wait()  # Covers the whole Brain/ACTION/child chain.
            active -= 1
        with ExitStack() as stack:
            for name in ("initialize_connection", "refresh_pending_brain_usage",
                         "apply_runtime_response_feedback", "cancel_lt_memory_idle_update",
                         "preempt_update_lt_facts_actions", "wait_for_runtime_memory_update"):
                stack.enter_context(patch.object(ws, name, new=AsyncMock()))
            stack.enter_context(patch.object(ws, "receive_message", new=lambda _: received.get()))
            stack.enter_context(patch.object(ws, "process_message", new=process))
            stack.enter_context(patch("websocket.tasks.schedule_interrupted_runtime_memory_update"))
            task = asyncio.create_task(ws.run_runtime_session(c.websocket, c, False))
            try:
                for _ in range(20):
                    if c.runtime_heartbeat_enqueue:
                        break
                    await asyncio.sleep(0)
                c.runtime_heartbeat_last_activity = hb.time.monotonic() - 900
                c.runtime_heartbeat_enqueue(c.runtime_heartbeat_generation)
                await asyncio.wait_for(started.wait(), 1)
                c.runtime_heartbeat_enqueue(c.runtime_heartbeat_generation)
                self.assertTrue(c.runtime_pending_requests_queue.empty())
                generation = c.runtime_heartbeat_generation
                await received.put({"type": "heartbeat_activity"})
                for _ in range(20):
                    if c.runtime_heartbeat_generation != generation:
                        break
                    await asyncio.sleep(0)
                self.assertEqual(active, 1, "page activity must not cancel an accepted chain")
                release.set()
                await asyncio.wait_for(c.runtime_pending_requests_queue.join(), 1)
                self.assertEqual(calls, ["heartbeat_tick"])
                self.assertIsNotNone(c.runtime_heartbeat_handle)
                self.assertAlmostEqual(c.runtime_heartbeat_handle.when() - asyncio.get_running_loop().time(), 900, delta=1)
                # An activity event invalidates a tick already in the queue.
                await c.runtime_pending_requests_queue.put({"type": "heartbeat_tick", "_heartbeat_generation": generation})
                await asyncio.wait_for(c.runtime_pending_requests_queue.join(), 1)
                self.assertEqual(calls, ["heartbeat_tick"])
            finally:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            self.assertIsNone(c.runtime_heartbeat_handle)
