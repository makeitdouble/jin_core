import json
import shutil
import subprocess
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from starlette.websockets import WebSocketDisconnect

import websocket as ws_runtime
from rules.brain_context_builder import build_loaded_delayed_memory_context
from runtime.anonymous_mode import (
    configure_runtime_anonymous_mode,
    runtime_action_write_is_restricted,
)
from runtime.runtime_context import RuntimeContext
from tests.test_anonymous_mode import FakeEmitter
from tests.helpers.memory import FakeLogger
from utils.actions import RuntimeActionCall, extract_runtime_actions
from utils.actions.dispatcher import apply_runtime_action_calls
from websocket.bootstrap import get_or_create_connection_context


class AnonymousDelayedMemoryTests(unittest.IsolatedAsyncioTestCase):
    def make_context(self, session_id="room-a-anon", *, anonymous=True):
        context = RuntimeContext(
            websocket=None, emitter=FakeEmitter(), logger=FakeLogger(),
            clients={}, session_id=session_id,
        )
        configure_runtime_anonymous_mode(context, anonymous)
        return context

    async def sync_reports(self, context, **fields):
        socket = SimpleNamespace(
            query_params={}, app=SimpleNamespace(state=SimpleNamespace()),
        )
        message = {"type": "delayed_memory_store_sync", **fields}
        with (
            patch.object(ws_runtime, "WebSocketLogger", return_value=SimpleNamespace(
                log_system=AsyncMock(), log_runtime=AsyncMock(),
            )),
            patch.object(ws_runtime, "get_or_create_connection_context", return_value=(context, False)),
            patch.object(ws_runtime, "initialize_connection", new_callable=AsyncMock),
            patch.object(ws_runtime, "register_lt_websocket_connection"),
            patch.object(ws_runtime, "unregister_lt_websocket_connection"),
            patch.object(ws_runtime, "receive_message", new_callable=AsyncMock) as receive,
            patch.object(ws_runtime, "cancel_current_task", new_callable=AsyncMock),
            patch.object(ws_runtime, "handle_websocket_error", new_callable=AsyncMock) as errors,
            patch.object(ws_runtime, "persist_delayed_memory_reports", return_value=[]) as save,
            patch.object(ws_runtime, "delete_delayed_memory_report_files", return_value=[]) as delete,
        ):
            receive.side_effect = [message, WebSocketDisconnect()]
            await ws_runtime.websocket_endpoint(socket)
            errors.assert_not_awaited()
            self.assertEqual(receive.await_count, 2)
        return save, delete

    async def save_report(self, context):
        parsed = extract_runtime_actions(
            "<SAVE_DELAYED_MEMORY>" + json.dumps({
                "title": "Room note", "summary": "Private summary",
                "tags": ["session"], "body": "Full anonymous report body.",
            }) + "</SAVE_DELAYED_MEMORY>",
            enabled_actions=["SAVE_DELAYED_MEMORY"],
        )
        self.assertEqual(len(parsed.actions), 1)
        applied = await apply_runtime_action_calls(
            context, parsed.actions, user_message="сохрани отчёт",
        )
        self.assertEqual(applied, 1)
        return next(iter(context.delayed_memory_reports))

    async def test_save_load_and_serialized_browser_sync_stay_in_one_room(self):
        room = self.make_context()
        other = self.make_context("room-b-anon")
        normal = self.make_context("normal-room", anonymous=False)
        with patch("utils.delayed_memory_file_store.persist_delayed_memory_reports") as disk:
            report_id = await self.save_report(room)
            event = next(e for e in room.emitter.events if e.get("action") == "save_delayed_memory")
            self.assertEqual(event["status"], "completed")
            self.assertEqual(event["delayed_memory_report"][report_id]["created_session_id"], room.session_id)
            self.assertIn("Delayed memory saved: Room note", str(room.runtime_session_action_history))
            self.assertNotIn("restricted write", str(room.runtime_session_action_history))
            self.assertIn("Full anonymous report body.", str(room.runtime_tool_results))

            snapshot = json.loads(json.dumps(event["delayed_memory_report"]))
            restored = self.make_context(room.session_id)
            save, delete = await self.sync_reports(restored, delayed_memory_reports=snapshot)
            save.assert_not_called()
            delete.assert_not_called()
            self.assertEqual(restored.delayed_memory_reports[report_id]["body"], snapshot[report_id]["body"])
            self.assertEqual(restored.delayed_memory_reports[report_id]["created_time"], snapshot[report_id]["created_time"])
            applied = await apply_runtime_action_calls(restored, (
                RuntimeActionCall(name="LOAD_DELAYED_MEMORY", payload=report_id),
            ))
            self.assertEqual(applied, 1)
            self.assertIn("Full anonymous report body.", build_loaded_delayed_memory_context(restored))
            disk.assert_not_called()
        self.assertEqual(other.delayed_memory_reports, {})
        self.assertEqual(normal.delayed_memory_reports, {})

    async def test_browser_pin_delete_and_restore_update_only_session_state(self):
        room = self.make_context()
        report_id = await self.save_report(room)
        snapshot = deepcopy(room.delayed_memory_reports)
        for pinned in (True, False):
            snapshot[report_id]["pinned"] = pinned
            save, delete = await self.sync_reports(
                room, delayed_memory_reports=snapshot,
                loaded_delayed_memory_ids=[report_id] if pinned else [],
            )
            self.assertEqual(room.delayed_memory_reports[report_id]["pinned"], pinned)
            save.assert_not_called()
            delete.assert_not_called()
        save, delete = await self.sync_reports(
            room, delayed_memory_reports={}, deleted_delayed_memory_report_ids=[report_id],
        )
        self.assertEqual(room.delayed_memory_reports, {})
        self.assertEqual(room.runtime_loaded_delayed_memory, {})
        self.assertEqual(room.runtime_loaded_delayed_memory_ids, [])
        save.assert_not_called()
        delete.assert_not_called()
        await self.sync_reports(room, delayed_memory_reports=snapshot)
        self.assertIn(report_id, room.delayed_memory_reports)

    async def test_soft_reconnect_preserves_reports_and_reload_starts_fresh(self):
        room = self.make_context()
        report_id = await self.save_report(room)
        await apply_runtime_action_calls(room, (
            RuntimeActionCall(name="LOAD_DELAYED_MEMORY", payload=report_id),
        ))
        room.runtime_memory = "Current frame"
        reports = deepcopy(room.delayed_memory_reports)
        loaded = deepcopy(room.runtime_loaded_delayed_memory)
        socket = SimpleNamespace(
            query_params={"anonymous_mode": "1", "client_id": room.session_id, "resume": "soft"},
            app=SimpleNamespace(state=SimpleNamespace(
                clients={}, websocket_runtime_contexts={room.session_id: room},
            )),
        )
        with (
            patch("websocket.bootstrap.hydrate_attached_files_from_store"),
            patch("websocket.bootstrap.resume_chat_log_session"),
            patch("websocket.bootstrap.restore_pending_l1_update"),
            patch("websocket.bootstrap.load_delayed_memory_reports_from_files") as disk,
        ):
            resumed, reused = get_or_create_connection_context(socket, FakeLogger())
            self.assertTrue(reused)
            self.assertIs(resumed, room)
            self.assertEqual(resumed.delayed_memory_reports, reports)
            self.assertEqual(resumed.runtime_loaded_delayed_memory, loaded)
            self.assertEqual(resumed.runtime_loaded_delayed_memory_ids, [report_id])
            socket.query_params.pop("resume")
            reloaded, reused = get_or_create_connection_context(socket, FakeLogger())
            self.assertFalse(reused)
            self.assertEqual(reloaded.delayed_memory_reports, {})
            self.assertEqual(reloaded.runtime_memory, self.make_context().runtime_memory)
            disk.assert_not_called()

    async def test_normal_persistence_and_non_anonymous_write_restriction_remain(self):
        normal = self.make_context("normal-room", anonymous=False)
        with patch("utils.delayed_memory_file_store.persist_delayed_memory_reports", return_value=[]) as disk:
            report_id = await self.save_report(normal)
            disk.assert_called_once()
        save, delete = await self.sync_reports(normal, deleted_delayed_memory_report_ids=[report_id])
        save.assert_called_once_with({})
        delete.assert_called_once_with(report_id)
        restricted = self.make_context("restricted-room", anonymous=False)
        restricted.runtime_persistent_writes_restricted = True
        self.assertTrue(runtime_action_write_is_restricted(restricted, "SAVE_DELAYED_MEMORY"))
        save, delete = await self.sync_reports(restricted, delayed_memory_reports={
            "abc123": {"title": "Blocked", "summary": "Blocked", "body": "Blocked"},
        })
        self.assertEqual(restricted.delayed_memory_reports, {})
        save.assert_not_called()
        delete.assert_not_called()

    @unittest.skipUnless(shutil.which("node"), "node is required")
    def test_browser_snapshot_survives_reload_and_isolates_new_room(self):
        script = r'''
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
function storage(seed = []) {
  const values = new Map(seed);
  return {values, getItem: k => values.get(k) ?? null,
    setItem: (k, v) => values.set(k, String(v)), removeItem: k => values.delete(k),
    key: i => [...values.keys()][i], get length() { return values.size; }};
}
const localStorage = new Proxy({}, {get() { throw Error('anonymous access to normal storage'); }});
function boot(id, sessionStorage) {
  const window = {sessionStorage, localStorage, location: {
    search: `?anonymous_mode=1&anonymous_session_id=${id}`,
  }, crypto: {randomUUID: () => 'fresh-id'}};
  const context = vm.createContext({window, URLSearchParams, URL, console,
    document: {documentElement: {classList: {add() {}}}}});
  for (const file of ['runtime-anonymous-mode.js', 'runtime-storage.js']) {
    vm.runInContext(fs.readFileSync('ui/static/js/runtime/' + file, 'utf8'), context);
  }
  return window.JinRuntime.storage;
}
const tab = storage();
const first = boot('room-a-anon', tab);
first.writeDelayedMemoryReports({abc123: {
  title: 'Saved report', summary: 'Summary', body: 'Full body', pinned: true,
  created_session_id: 'room-a-anon', created_time: '2026-09-02T12:00:00+03:00',
}});
const serialized = JSON.stringify(first.readDelayedMemoryReports());
const reloaded = boot('room-a-anon', storage([...tab.values]));
assert.strictEqual(JSON.stringify(reloaded.readDelayedMemoryReports()), serialized);
const other = boot('room-b-anon', storage([...tab.values]));
assert.strictEqual(JSON.stringify(other.readDelayedMemoryReports()), '{}');
other.writeDelayedMemoryReports({def456: {title: 'Other report', body: 'Other body'}});
assert.strictEqual(JSON.stringify(first.readDelayedMemoryReports()), serialized);
const closedAndReopened = boot('room-a-anon', storage());
assert.strictEqual(JSON.stringify(closedAndReopened.readDelayedMemoryReports()), '{}');
'''
        result = subprocess.run(
            ["node", "-e", script], cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
