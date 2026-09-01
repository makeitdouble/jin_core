import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.L1_memory_utils import build_runtime_memory_snapshot
from runtime.LT_memory import ensure_runtime_lt_state
from runtime.LT_memory_utils import normalize_lt_store
from runtime.memory_edit import apply_memory_value_edit, split_editable_memory_value
from runtime.runtime_context import RuntimeContext
from tests.helpers.memory import FakeLogger


class Emitter:
    def __init__(self):
        self.events = []

    async def emit(self, data):
        self.events.append(data)


class MemoryValueEditTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.context = RuntimeContext(None, Emitter(), FakeLogger(), {})
        self.context.runtime_lt_file_store_enabled = False
        self.context.runtime_memory = "discussion_focus: old value\nuser_state: unchanged"
        self.context.runtime_memory_stable = self.context.runtime_memory
        self.context.runtime_memory_snapshots = [build_runtime_memory_snapshot(
            self.context, self.context.runtime_memory,
        )]

    def payload(self, kind="frame", **fields):
        return {
            "kind": kind, "request_id": "edit-1", "target": "discussion_focus",
            "frame_id": self.context.runtime_memory_snapshots[-1]["runtime_memory_id"],
            "expected_value": "old value", "value": "new value", **fields,
        }

    async def test_current_frame_only_and_multiline_value_cannot_add_keys(self):
        old = copy.deepcopy(self.context.runtime_memory_snapshots[0])
        self.context.runtime_memory_snapshots.append(build_runtime_memory_snapshot(
            self.context, self.context.runtime_memory,
        ))
        result = await apply_memory_value_edit(self.context, self.payload(frame_id=old["runtime_memory_id"]))
        self.assertEqual(result["error"], "stale_frame")
        result = await apply_memory_value_edit(self.context, self.payload(value="edited\ninjected_key: text"))
        self.assertTrue(result["ok"])
        self.assertEqual(self.context.runtime_memory, "discussion_focus: edited\\ninjected_key: text\nuser_state: unchanged")
        self.assertEqual(self.context.runtime_memory_stable, self.context.runtime_memory)
        self.assertEqual(self.context.runtime_memory_snapshots[0], old)
        event = self.context.emitter.events[-1]
        self.assertTrue(event["replace_latest"])
        self.assertIn("session_snapshot", event)
        self.assertEqual(json.loads(json.dumps(event))["snapshot"]["raw_memory"], event["memory"])

    async def test_conflicts_busy_and_read_only_targets_do_not_write(self):
        before = copy.deepcopy(self.context.runtime_memory_snapshots)
        for change, error in [
            ({"expected_value": "stale"}, "value_changed"),
            ({"target": "user_idle"}, "invalid_target"),
            ({"target": "active_memory_1"}, "invalid_target"),
            ({"target": "missing"}, "not_found"),
            ({"value": "  "}, "invalid_value"),
        ]:
            result = await apply_memory_value_edit(self.context, self.payload(**change))
            self.assertEqual(result["error"], error)
        result = await apply_memory_value_edit(self.context, self.payload(), foreground_busy=True)
        self.assertEqual(result["error"], "memory_busy")
        self.context.runtime_memory_update_task = asyncio.get_running_loop().create_future()
        result = await apply_memory_value_edit(self.context, self.payload())
        self.assertEqual(result["error"], "memory_busy")
        self.context.runtime_memory_update_task.cancel()
        self.assertEqual(self.context.runtime_memory_snapshots, before)
        self.assertEqual(self.context.emitter.events, [])

    async def test_active_conditions_preserve_custom_fields_status_and_long_text(self):
        record = "active_memory_1: old value [ active_memory_id: abc123 ] [ conditions: old value ] [ photos: 5 ] [ creation_time: 2026-08-01 ] [ status: paused ]"
        self.context.active_memory_records = [record, "active_memory_2: untouched [ active_memory_id: def456 ]"]
        self.context.runtime_memory += "\n" + record
        value = "New conditions [with brackets]: " + "long text " * 60
        result = await apply_memory_value_edit(self.context, self.payload("active", target="abc123", value=value))
        self.assertTrue(result["ok"])
        updated = self.context.active_memory_records[0]
        body, tags = split_editable_memory_value(updated.split(":", 1)[1])
        self.assertEqual(body, value.strip())
        self.assertIn(f"[ conditions: {value.strip()} ]", updated)
        for suffix in ["[ photos: 5 ]", "[ creation_time: 2026-08-01 ]", "[ status: paused ]"]:
            self.assertIn(suffix, updated)
        self.assertEqual(self.context.active_memory_records[1], "active_memory_2: untouched [ active_memory_id: def456 ]")
        self.assertIn(updated, self.context.runtime_memory)
        self.assertTrue(any(e["type"] == "active_memory_records_update" for e in self.context.emitter.events))

    async def test_active_legacy_without_conditions_suffix_and_idempotent_retry(self):
        self.context.active_memory_records = ["active_memory_1: old value [ active_memory_id: abc123 ] [ status: pending ]"]
        payload = self.payload("active", target="abc123")
        first = await apply_memory_value_edit(self.context, payload)
        saved = self.context.active_memory_records[0]
        second = await apply_memory_value_edit(self.context, payload)
        self.assertTrue(first["ok"] and second["ok"])
        self.assertEqual(self.context.active_memory_records[0], saved)
        self.assertNotIn("[ conditions:", saved)

    def lt_store(self):
        return normalize_lt_store({"revision": 7, "facts": [{
            "id": "F376", "key": "hypothetical_modeling_mode", "value": "old value",
            "category": "persistent_constraint", "source_fact_ids": ["PF837"],
            "created_at": "2026-08-31T18:48:34Z", "last_mentioned": "2026-08-31T18:48:34Z",
            "mention_count": 3,
        }]})

    async def test_lt_edit_persists_and_preserves_identity_and_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            self.context.runtime_lt_file_store_enabled = True
            self.context.runtime_lt_file_store_root = Path(directory)
            self.context.runtime_long_term_memory_store = self.lt_store()
            original = copy.deepcopy(ensure_runtime_lt_state(self.context)["facts"][0])
            result = await apply_memory_value_edit(self.context, self.payload("lt", target="F376"))
            self.assertTrue(result["ok"])
            self.context.runtime_long_term_memory_store = None
            reloaded = ensure_runtime_lt_state(self.context)["facts"][0]
            self.assertEqual(reloaded["value"], "new value")
            for field in original:
                if field not in {"value", "updated_at"}:
                    self.assertEqual(reloaded[field], original[field], field)

    async def test_lt_restricted_conflict_and_failed_write_preserve_value(self):
        self.context.runtime_long_term_memory_store = self.lt_store()
        payload = self.payload("lt", target="F376")
        self.context.runtime_persistent_writes_restricted = True
        result = await apply_memory_value_edit(self.context, payload)
        self.assertEqual(result["error"], "restricted_write")
        self.context.runtime_persistent_writes_restricted = False
        result = await apply_memory_value_edit(self.context, {**payload, "expected_value": "stale"})
        self.assertEqual(result["error"], "value_changed")
        with patch("runtime.memory_edit.persist_runtime_lt_file_store", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                await apply_memory_value_edit(self.context, payload)
        self.assertEqual(self.context.runtime_long_term_memory_store["facts"][0]["value"], "old value")


if __name__ == "__main__":
    unittest.main()
