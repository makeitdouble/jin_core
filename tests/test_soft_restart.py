"""Restart recovery: disk context survives without replaying the page or Brain."""
import asyncio
import contextlib
import shutil
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import websocket as ws
from runtime.runtime_context import RuntimeContext
from runtime import memory_profile
from utils import chat_log, session_restore
from rules.brain_context_builder import build_brain_context
from tests.test_runtime_transport import Socket, until
from websocket.bootstrap import get_or_create_connection_context, initialize_connection
from websocket.logger import WebSocketLogger
from websocket.transport import stop_runtime_transports


class SoftRestartTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.logs = self.root / "logs"
        self.stack.enter_context(patch.object(chat_log, "CHAT_LOG_ROOT", self.logs))
        self.stack.enter_context(patch.object(session_restore, "CHAT_LOG_ROOT", self.logs))
        self.stack.enter_context(patch.object(chat_log, "chat_logging_enabled", return_value=True))
        self.stack.enter_context(patch.object(memory_profile, "MEMORY_ROOT", self.root / "memory"))
        self.stack.enter_context(patch("runtime.frame_memory_pending.PENDING_FRAME_DIR", self.root / "pending"))
        self.stack.enter_context(patch("websocket.bootstrap.hydrate_attached_files_from_store"))
        self.stack.enter_context(patch("websocket.bootstrap.hydrate_attachment_ids", return_value=[]))

    def source(self, name, *, answer="saved answer", text="saved USER", frame="topic: saved FRAME"):
        context = RuntimeContext(None, None, None, {}, session_id=name)
        context.runtime_anonymous_mode = name.endswith("_anon")
        context.runtime_turn_counter = 1
        context.runtime_current_turn_id = "turn_000001"
        chat_log.append_chat_log_entry(context, role="user", text=text)
        if answer is not None:
            chat_log.save_turn_reasoning(context, "saved reasoning")
            chat_log.append_chat_log_entry(context, role="jin", text=answer)
        chat_log.save_frame_snapshot(context, {
            "index": 4, "runtime_memory_updates": 4, "raw_memory": frame,
            "created_at": "2026-09-20T01:00:00Z", "timestamp": "2026-09-20T01:00:00Z",
            "session_id": name,
            "lines": [{"key": "topic", "value": "saved FRAME", "created_at": "2026-09-20T01:00:00Z"}] if frame else [],
        })
        chat_log.append_chat_runtime_event(context, event="runtime_action_request", payload={
            "action": "JIN_COLOR", "color": "#123456", "event_id": "color-1",
            "session_action": {"id": "color-1", "session_id": name,
                               "text": "JIN_COLOR", "parts": [{"text": "JIN_COLOR", "colors": ["#123456"]}]},
        })
        chat_log.append_chat_runtime_event(context, event="session_checkpoint", payload={
            "tool_results": [{"kind": "search", "result": "saved tool", "tool_id": "T7"}],
            "tool_result_sequence": 7, "current_jin_color": "#123456",
        })
        return context

    def socket(self, name, *, soft=True, app=None):
        socket = Socket(app, soft=soft)
        socket.query_params["client_id"] = name
        if name.endswith("_anon"):
            socket.query_params["anonymous_mode"] = "1"
        socket.app.state.memory_profiles_initialized = True
        return socket

    def connect(self, name, *, soft=True):
        socket = self.socket(name, soft=soft)
        context, resumed = get_or_create_connection_context(socket, WebSocketLogger(socket))
        self.assertFalse(resumed)
        return context, socket

    def files(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    async def test_restart_recovers_each_room_and_next_brain_prompt_without_writes(self):
        for name in ("normal", "private_anon"):
            with self.subTest(name=name):
                self.source(name)
                self.source("unrelated-later-room", text="OTHER USER")
                memory_profile.read_profile(SimpleNamespace(
                    memory_profile_root=self.root / "memory",
                    runtime_anonymous_mode=name.endswith("_anon"),
                ))
                before = self.files()
                context, socket = self.connect(name)
                await initialize_connection(context, skip_initial_runtime_state=True)
                self.assertEqual(socket.events, [])
                self.assertEqual(self.files(), before)
                self.assertEqual(context.session_id, name)
                self.assertEqual(context.runtime_memory, "topic: saved FRAME")
                self.assertEqual(context.runtime_recent_turns[-1]["user"], "saved USER")
                self.assertEqual(context.runtime_recent_turns[-1]["jin"], "saved answer")
                self.assertEqual(context.runtime_memory_snapshots[0]["created_at"], "2026-09-20T01:00:00Z")
                self.assertEqual(context.runtime_memory_snapshots[0]["session_id"], name)
                self.assertEqual(context.runtime_memory_updates, 4)
                self.assertEqual(context.runtime_tool_result_sequence, 7)
                self.assertEqual(context.jin_color, "#123456")
                self.assertEqual(context.runtime_session_action_history[-1]["parts"][0]["colors"], ["#123456"])
                self.assertFalse(context.runtime_session_restore_priming)
                self.assertEqual(context.runtime_restored_session_dialog, "")
                prompt = build_brain_context(context, include_runtime_action_instructions=False)
                for expected in ("saved USER", "saved answer", "saved FRAME", "saved reasoning", "saved tool"):
                    self.assertIn(expected, prompt)
                self.assertNotIn("OTHER USER", prompt)
                self.assertNotIn("USER DIDN'T SEND NEW MESSAGE", prompt)
                if name.endswith("_anon"):
                    self.assertIsNone(session_restore.build_archived_session_restore_payload(name))

    async def test_empty_frame_and_tools_are_authoritative(self):
        for name in ("empty", "empty_anon"):
            source = self.source(name, frame="")
            chat_log.append_chat_runtime_event(source, event="session_checkpoint", payload={
                "tool_results": [], "tool_result_sequence": 12,
            })
            context, _ = self.connect(name)
            self.assertEqual(context.runtime_memory, "")
            self.assertEqual(context.runtime_memory_snapshots[0]["raw_memory"], "")
            self.assertEqual(context.runtime_memory_snapshots[0]["created_at"], "2026-09-20T01:00:00Z")
            self.assertEqual(context.runtime_tool_results, [])
            self.assertEqual(context.runtime_tool_result_sequence, 12)

    async def test_next_frame_and_second_restart_keep_the_latest_snapshot(self):
        self.source("frame-sequence")
        context, _ = self.connect("frame-sequence")
        next_snapshot = {**context.runtime_memory_snapshots[0], "index": 1,
                         "raw_memory": "topic: NEW FRAME", "runtime_memory_updates": 5}
        path = chat_log.save_frame_snapshot(context, next_snapshot)
        self.assertTrue(path.name.endswith("_frame_5.txt"))
        second, _ = self.connect("frame-sequence")
        self.assertEqual(second.runtime_memory, "topic: NEW FRAME")
        self.assertEqual(second.runtime_memory_updates, 5)
        self.assertEqual(second.runtime_memory_display_index_offset, 5)

    async def test_interrupted_and_action_only_turns_and_long_text(self):
        text = "BEGIN " + "x" * 14000 + "\nEND"
        for name, answer in (("interrupted", None), ("action_anon", "")):
            self.source(name, answer=answer, text=text)
            context, _ = self.connect(name)
            self.assertEqual(context.runtime_recent_turns[-1]["user"], text)
            self.assertEqual(context.runtime_recent_turns[-1]["jin"], "")
            prompt = build_brain_context(context, include_runtime_action_instructions=False)
            self.assertIn(text.replace("\n", "\\n"), prompt)

    async def test_blank_deleted_and_new_pages_never_select_another_room(self):
        self.source("other", text="OTHER USER")
        for name in ("deleted", "deleted_anon"):
            source = self.source(name)
            shutil.rmtree(Path(source.runtime_chat_log_path).parent)
            context, _ = self.connect(name)
            self.assertFalse(context.runtime_recent_turns)
        for name in ("blank", "blank_anon"):
            context, _ = self.connect(name)
            self.assertFalse(context.runtime_recent_turns)
        context, _ = self.connect("other", soft=False)
        self.assertFalse(context.runtime_recent_turns)
        self.assertFalse(getattr(context, "runtime_disk_bootstrap_applied", False))

    async def test_restore_error_does_not_register_an_empty_runtime(self):
        socket = self.socket("unreadable")
        with patch.object(session_restore, "build_runtime_reconnect_payload", side_effect=OSError("disk read failed")):
            with self.assertRaises(OSError):
                get_or_create_connection_context(socket, WebSocketLogger(socket))
        self.assertEqual(socket.app.state.websocket_runtime_contexts, {})
        self.assertEqual(socket.events, [])

    async def test_live_context_is_not_rehydrated(self):
        self.source("live")
        context, socket = self.connect("live")
        context.runtime_memory = "new live RAM"
        replacement = self.socket("live", app=socket.app)
        with patch.object(session_restore, "build_runtime_reconnect_payload", side_effect=AssertionError("disk reread")):
            resumed, was_resumed = get_or_create_connection_context(replacement, WebSocketLogger(replacement))
        self.assertTrue(was_resumed)
        self.assertIs(resumed, context)
        self.assertEqual(resumed.runtime_memory, "new live RAM")

    async def test_real_endpoint_is_quiet_until_user_and_prompt_has_disk_context(self):
        for name in ("endpoint", "endpoint_anon"):
            self.source(name)
            socket = self.socket(name)
            prompts = []
            async def process(context, message_data):
                prompts.append(build_brain_context(context, include_runtime_action_instructions=False))
            with ExitStack() as stack:
                for target in ("register_lt_websocket_connection", "unregister_lt_websocket_connection", "note_lt_user_activity", "note_lt_foreground_state"):
                    stack.enter_context(patch.object(ws, target))
                stack.enter_context(patch.object(ws, "process_message", side_effect=process))
                stack.enter_context(patch.object(ws, "reject_when_all_models_offline", new=AsyncMock(return_value=False)))
                endpoint = asyncio.create_task(ws.websocket_endpoint(socket))
                try:
                    await until(lambda: bool(socket.events))
                    context = socket.app.state.websocket_runtime_contexts[name]
                    await asyncio.sleep(0.03)
                    self.assertEqual([e["type"] for e in socket.events], ["runtime_transport_ready"])
                    self.assertEqual(prompts, [])
                    self.assertIn("saved USER", context.runtime_recent_turns[-1]["user"])
                    await socket.incoming.put({"text": "continue"})
                    await until(lambda: bool(prompts))
                    self.assertIn("saved FRAME", prompts[0])
                    self.assertIn("saved USER", prompts[0])
                finally:
                    endpoint.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await endpoint
                    await stop_runtime_transports(socket.app.state)

    async def test_surviving_page_receives_no_initial_projection(self):
        for anonymous in (False, True):
            context = SimpleNamespace(runtime_anonymous_mode=anonymous)
            with self.subTest(anonymous=anonymous), patch("runtime.memory_profile.publish_profile") as publish:
                await initialize_connection(context, skip_initial_runtime_state=True)
                publish.assert_not_called()
                self.assertEqual(vars(context), {"runtime_anonymous_mode": anonymous})
