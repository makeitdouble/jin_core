"""Backfill must not commit an old snapshot over a concurrent live L-T write."""
import asyncio
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import runtime.LT_memory as lt
import runtime.LT_mention_backfill as backfill
from runtime.memory_edit import apply_memory_value_edit
from runtime.runtime_context import RuntimeContext
from runtime.LT_memory_utils import normalize_lt_store
from utils.long_term_facts_file_store import (
    load_long_term_facts_store,
    persist_long_term_facts_store,
)


class Emitter:
    async def emit(self, payload):
        await asyncio.sleep(0)


class LTStoreConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def exercise_interleaving(self, operation, *, during_scan=False):
        with tempfile.TemporaryDirectory() as root:
            seed = normalize_lt_store({"facts": [
                {
                    "id": f"F{index}", "key": f"test.fact{index}",
                    "value": f"value {index}",
                    "created_at": "2025-01-01T00:00:00Z",
                    "updated_at": "2025-01-01T00:00:00Z",
                    "last_mentioned_at": "2025-01-01T00:00:00Z",
                }
                for index in (1, 2)
            ]}, now="2025-01-01T00:00:00Z")
            persist_long_term_facts_store(seed, root=root)

            def context():
                ctx = RuntimeContext(None, Emitter(), None, {})
                ctx.runtime_lt_file_store_enabled = True
                ctx.runtime_lt_file_store_root = root
                lt.ensure_runtime_lt_state(ctx)
                return ctx

            a, b = context(), context()
            competitor = None
            original_apply = backfill.apply_lt_log_mention_backfill_to_store
            original_to_thread = asyncio.to_thread
            state = {"fallback_at": "2025-02-01T00:00:00Z", "activated_at": "2026-01-01T00:00:00Z"}
            scan = {"latest_by_fact_id": {}, "jsonl_files_scanned": 0,
                    "reasoning_files_scanned": 0, "jin_entries_scanned": 0}

            async def mutate():
                if operation == "delete":
                    self.assertTrue(await lt.delete_lt_memory_fact(b, "F1"))
                elif operation == "edit":
                    result = await apply_memory_value_edit(b, {
                        "kind": "lt", "target": "F1", "expected_value": "value 1",
                        "value": "edited value",
                    })
                    self.assertTrue(result["ok"])
                else:
                    result = await lt.record_lt_reasoning_fact_mentions(
                        b, "F1", now="2026-06-01T00:00:00Z",
                    )
                    self.assertTrue(result["changed"])

            def apply(*args, **kwargs):
                nonlocal competitor
                result = original_apply(*args, **kwargs)
                if not during_scan:
                    # Another page becomes runnable just after snapshot preparation.
                    competitor = asyncio.create_task(mutate())
                return result

            async def to_thread(function, *args, **kwargs):
                nonlocal competitor
                if function is backfill.load_or_create_lt_log_mention_backfill_state:
                    return state
                if function is backfill.scan_lt_log_fact_mentions:
                    if during_scan:
                        competitor = asyncio.create_task(mutate())
                        await competitor
                    return scan
                # Reproduce the old ordering deterministically: an offloaded
                # snapshot write lands after the live operation. On the fixed
                # path, commit has no suspension point and this branch is unused.
                if function is lt.persist_runtime_lt_file_store and competitor:
                    await competitor
                return await original_to_thread(function, *args, **kwargs)

            with patch.object(backfill, "apply_lt_log_mention_backfill_to_store", apply), \
                    patch.object(backfill.asyncio, "to_thread", to_thread), \
                    patch.object(lt, "log_memory_event", AsyncMock()), \
                    patch.object(lt, "remap_delayed_memory_lt_fact_ids", return_value={}):
                try:
                    await backfill.run_lt_log_mention_backfill(a)
                finally:
                    if competitor:
                        await competitor

            stored, warnings = load_long_term_facts_store(root=root)
            self.assertFalse(warnings)
            facts = {fact["id"]: fact for fact in stored["facts"]}
            if operation == "delete":
                self.assertNotIn("F1", facts)
            elif operation == "edit":
                self.assertEqual(facts["F1"]["value"], "edited value")
            else:
                self.assertEqual(facts["F1"]["last_mentioned_at"], "2026-06-01T00:00:00Z")
                self.assertEqual(facts["F1"]["mention_count"], 2)
            self.assertEqual(facts["F2"]["last_mentioned_at"], state["fallback_at"])
            # Reopen through a fresh runtime, including tombstone reconciliation.
            self.assertEqual(lt.ensure_runtime_lt_state(context()), stored)

    async def test_delete_after_snapshot_preparation_survives(self):
        await self.exercise_interleaving("delete")

    async def test_edit_after_snapshot_preparation_survives(self):
        await self.exercise_interleaving("edit")

    async def test_live_mention_after_snapshot_preparation_survives(self):
        await self.exercise_interleaving("mention")

    async def test_delete_during_archive_scan_survives(self):
        await self.exercise_interleaving("delete", during_scan=True)

    async def test_edit_during_archive_scan_survives(self):
        await self.exercise_interleaving("edit", during_scan=True)

    async def test_live_mention_during_archive_scan_survives(self):
        await self.exercise_interleaving("mention", during_scan=True)
