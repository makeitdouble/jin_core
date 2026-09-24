import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.runtime_context import RuntimeContext
from runtime.memory_profile import (
    enable_profile, refresh_profile, read_profile, publish_profile, commit_active,
    persist_delayed, handle_store_sync, release_profile, collect_frame_candidates,
)
from runtime.LT_memory import ensure_runtime_lt_state, persist_runtime_lt_file_store
from utils.active_memory_file_store import load_active_records, persist_active_records
from utils.long_term_facts_file_store import (
    atomic_write_json, import_legacy_pending_records, load_long_term_facts_store,
    load_pending_facts, persist_long_term_facts_store,
)
from utils.brain_client_utils import save_active_memory_runtime_record, delete_active_memory_runtime_record
from runtime.memory_edit import apply_memory_value_edit


ROW = "active_memory_1: Example [ id: AM-abc123 ] [ status: paused ]"


class MemoryProfileTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = SimpleNamespace(websocket_runtime_contexts={})

    def context(self, name="normal", anonymous=False):
        context = RuntimeContext(None, None, None, {}, session_id=name)
        context.memory_profile_root = self.root
        context.runtime_anonymous_mode = anonymous
        context.runtime_persistent_writes_restricted = anonymous
        context.websocket = SimpleNamespace(app=SimpleNamespace(state=self.state))
        context.runtime_transport = SimpleNamespace(stopping=False, events=[])
        context.runtime_transport.publish = context.runtime_transport.events.append
        context.emitter = SimpleNamespace(emit=self.emit)
        enable_profile(context)
        self.state.websocket_runtime_contexts[name] = context
        refresh_profile(context)
        return context

    async def emit(self, payload):
        pass

    async def test_active_create_edit_pause_delete_reload_and_isolation(self):
        a = self.context()
        b = self.context("second")
        anon = self.context("a_anon", True)
        commit_active(a, [ROW])
        self.assertEqual(b.active_memory_records, [ROW])
        self.assertEqual(anon.active_memory_records, [])
        self.assertEqual(load_active_records(root=self.root / "active"), [ROW])
        result = await apply_memory_value_edit(a, {
            "kind": "active", "target": "AM-abc123", "request_id": "edit",
            "expected_value": "Example", "value": "Changed",
        })
        self.assertTrue(result["ok"])
        self.assertIn("Changed", load_active_records(root=self.root / "active")[0])
        self.assertIn("status: paused", b.active_memory_records[0])
        self.assertIn("updated_at:", b.active_memory_records[0])
        handle_store_sync(a, {"type": "active_memory_store_sync", "mutation": True,
            "memory_revision": a.memory_profile_revisions["active"],
            "active_memory_records": [a.active_memory_records[0].replace("status: paused", "status: pending")]})
        removed, _, _ = await delete_active_memory_runtime_record(a, "AM-abc123")
        self.assertTrue(removed)
        self.assertEqual(read_profile(b)["active"], [])
        self.assertEqual(b.active_memory_records, [])
        self.assertTrue(await save_active_memory_runtime_record(a, '{"conditions":"New"}'))
        self.assertEqual(len(list((self.root / "active").glob("*.json"))), 1)
        self.assertEqual(len(self.context("reload").active_memory_records), 1)

    async def test_stale_browser_and_physical_delete_cannot_resurrect(self):
        a = self.context()
        commit_active(a, [ROW])
        token = a.memory_profile_revisions["active"]
        (self.root / "active" / "AM-abc123.json").unlink()
        handled = handle_store_sync(a, {"type": "active_memory_store_sync", "mutation": True,
            "memory_revision": token, "active_memory_records": [ROW]})
        self.assertTrue(handled)
        self.assertEqual(a.active_memory_records, [])
        self.assertFalse((self.root / "active" / "AM-abc123.json").exists())
        handle_store_sync(a, {"type": "lt_memory_store_sync", "store": {"facts": [{"id":"F1", "key":"test.fact", "value":"stale"}]}})
        self.assertEqual(ensure_runtime_lt_state(a)["facts"], [])

    async def test_shared_anonymous_files_and_last_close(self):
        a = self.context("one_anon", True)
        b = self.context("two_anon", True)
        normal = self.context()
        commit_active(a, [ROW])
        persist_delayed(a, {"def456": {"title": "Report", "body": "Private"}})
        persist_runtime_lt_file_store(a, {"facts": [{"id":"F1", "key":"test.fact", "value":"Private"}]})
        self.assertEqual(b.active_memory_records, [ROW])
        self.assertIn("def456", b.delayed_memory_reports)
        self.assertEqual(normal.delayed_memory_reports, {})
        self.assertTrue((self.root / "facts/long_term_facts_anon.json").exists())
        self.assertFalse((self.root / "facts/long_term_facts.json").exists())
        self.state.websocket_runtime_contexts.pop("one_anon")
        release_profile(a, self.state)
        self.assertTrue((self.root / "active/AM-abc123_anon.json").exists())
        self.state.websocket_runtime_contexts.pop("two_anon")
        with patch("runtime.memory_profile.ANONYMOUS_CLOSE_GRACE_SECONDS", 0.01):
            release_profile(b, self.state)
            await asyncio.sleep(0.03)
        self.assertEqual(list(self.root.glob("**/*_anon.json")), [])

    async def test_backend_restart_anon_reconnect_keeps_shared_files(self):
        persist_active_records([ROW], root=self.root / "active", anonymous=True)
        with patch("runtime.memory_profile.ANONYMOUS_STARTUP_GRACE_SECONDS", 0.01):
            anon = self.context("reconnected_anon", True)
            await asyncio.sleep(0.03)
        self.assertEqual(anon.active_memory_records, [ROW])
        self.assertTrue((self.root / "active/AM-abc123_anon.json").exists())

    async def test_backend_restart_cleans_orphaned_anon_files_after_grace(self):
        persist_active_records([ROW], root=self.root / "active", anonymous=True)
        with patch("runtime.memory_profile.ANONYMOUS_STARTUP_GRACE_SECONDS", 0.01):
            self.context("normal_after_restart")
            await asyncio.sleep(0.03)
        self.assertFalse((self.root / "active/AM-abc123_anon.json").exists())

    async def test_reload_cancels_last_close_cleanup(self):
        a = self.context("one_anon", True)
        commit_active(a, [ROW])
        self.state.websocket_runtime_contexts.clear()
        with patch("runtime.memory_profile.ANONYMOUS_CLOSE_GRACE_SECONDS", 0.01):
            release_profile(a, self.state)
            b = self.context("new_anon", True)
            await asyncio.sleep(0.03)
        self.assertEqual(b.active_memory_records, [ROW])

    async def test_pending_server_frame_roundtrip(self):
        a = self.context()
        collect_frame_candidates(a, {"runtime_memory_id": "frame-1", "lines": [
            {"key":"user_message", "value":"not a fact"},
            {"key":"user_preference", "value":"Russian"},
        ]})
        file = self.root / "facts/pending_facts.json"
        data = json.loads(file.read_text())
        self.assertEqual(list(data["records"][0]["signals"]), ["user_preference"])
        self.assertEqual(self.context("reload").runtime_facts_memory_records, a.runtime_facts_memory_records)
        file.unlink()
        refresh_profile(a)
        self.assertEqual(a.runtime_facts_memory_records, [])
        self.assertTrue(file.exists())
        handle_store_sync(a, {"type":"facts_memory_store_sync", "records":data["records"]})
        self.assertEqual(load_pending_facts(root=self.root / "facts")["records"], [])

    async def test_separate_fact_files_preserve_each_other_and_migrate_queue(self):
        facts = self.root / "facts"
        atomic_write_json(facts / "long_term_facts.json", {
            "facts": [], "pending_facts": [{"id":"PF1", "key":"test.pending", "value":"Pending"}],
        })
        store, _ = load_long_term_facts_store(root=facts)
        self.assertEqual(len(store["pending_facts"]), 1)
        self.assertNotIn("pending_facts", json.loads((facts / "long_term_facts.json").read_text()))
        persist_long_term_facts_store({}, root=facts, anonymous=True)
        persist_long_term_facts_store(store, root=facts)
        self.assertTrue((facts / "long_term_facts_anon.json").exists())
        self.assertTrue((facts / "pending_facts_anon.json").exists())
        (facts / "pending_facts.json").unlink()
        self.assertEqual(load_long_term_facts_store(root=facts)[0]["pending_facts"], [])
        recreated = load_pending_facts(root=facts)
        self.assertEqual(recreated["records"], [])
        self.assertNotIn("legacy_browser_import_pending", recreated)

    async def test_legacy_browser_facts_are_imported_once_without_becoming_authoritative(self):
        facts = self.root / "facts"
        atomic_write_json(facts / "long_term_facts.json", {
            "facts": [], "pending_facts": [],
        })
        load_long_term_facts_store(root=facts)
        pending = load_pending_facts(root=facts)
        self.assertTrue(pending["legacy_browser_import_pending"])

        legacy = [{
            "storage_key": "jin.factsMemory.old-session.v2",
            "session_id": "old-session",
            "signals": {
                "user_preference": {
                    "content": "Russian",
                    "lt_status": "pending",
                },
            },
        }]
        self.assertTrue(import_legacy_pending_records(legacy, root=facts))
        imported = load_pending_facts(root=facts)
        self.assertEqual(imported["records"][0]["session_id"], "old-session")
        self.assertNotIn("legacy_browser_import_pending", imported)

        # Once the migration marker is consumed, later browser inventories are
        # ignored. Deleting disk state cannot resurrect the old browser copy.
        (facts / "pending_facts.json").unlink()
        load_long_term_facts_store(root=facts)
        self.assertFalse(import_legacy_pending_records(legacy, root=facts))
        self.assertEqual(load_pending_facts(root=facts)["records"], [])

    async def test_empty_delayed_folder_replaces_archive_and_browser(self):
        from websocket.bootstrap import apply_active_memory_records, apply_delayed_memory_reports
        a = self.context()
        apply_active_memory_records(a, {"active_memory_records":[ROW]})
        apply_delayed_memory_reports(a, {"delayed_memory_reports":{"def456":{"title":"stale"}}})
        self.assertEqual(a.active_memory_records, [])
        self.assertEqual(a.delayed_memory_reports, {})

    async def test_failed_active_write_does_not_publish_success(self):
        a = self.context()
        with patch("utils.active_memory_file_store.atomic_write_json", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                commit_active(a, [ROW])
        self.assertEqual(a.active_memory_records, [])
        self.assertEqual(a.runtime_transport.events, [])
