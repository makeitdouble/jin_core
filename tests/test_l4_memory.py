import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timezone

from runtime.L4_memory import (
    apply_l4_memory_store_sync,
    build_runtime_l4_memory_context,
    cancel_l4_memory_idle_update,
    delete_l4_memory_fact,
    ensure_runtime_l4_state,
    maybe_update_runtime_l4_memory,
    remap_delayed_memory_l4_fact_ids,
    restore_l4_memory_fact,
    runtime_l4_memory_update_running,
    schedule_l4_memory_idle_update,
)
from runtime.L4_memory_utils import (
    add_l4_pending_candidates,
    apply_l4_jin_note_result,
    apply_l4_merge_operations,
    build_l4_fact_id,
    build_l4_jin_note_system_prompt,
    build_l4_merge_batch_plan,
    build_l4_merge_system_prompt,
    build_l4_merge_user_prompt,
    collect_pending_facts_memory_fields,
    extract_l4_json_payload,
    format_l4_fact_line,
    format_l4_merge_operation_details,
    format_long_term_memory_context,
    mark_facts_memory_fields_analyzed,
    merge_l4_store_snapshots,
    normalize_facts_memory_records,
    normalize_l4_candidates,
    normalize_l4_merge_operations,
    normalize_l4_store,
    restore_l4_fact_to_store,
)
from runtime.runtime_context import RuntimeContext
from rules.brain_context_builder import build_brain_context
from tests.helpers.memory import FakeLogger, FakeServiceClient
from utils.actions import RuntimeActionCall
from utils.actions.delayed_memory_actions import (
    apply_save_delayed_memory_actions,
)
from utils.long_term_facts_file_store import (
    load_long_term_facts_store,
    persist_long_term_facts_store,
)


class FakeEmitter:

    def __init__(self):
        self.events = []

    async def emit(self, payload):
        self.events.append(payload)


class CaptureMemoryLogger:

    def __init__(self):
        self.logs = []

    async def log_memory(
        self,
        level,
        message,
        details=None,
        event=None,
        **extra,
    ):
        self.logs.append({
            "level": level,
            "message": message,
            "details": details,
            "event": event,
            **extra,
        })


class L4MemoryTests(unittest.IsolatedAsyncioTestCase):

    def test_facts_memory_normalization_adds_session_and_pending_status(self):
        records = normalize_facts_memory_records([
            {
                "storage_key": "jin.factsMemory.session-a.v1",
                "session_id": "session-a",
                "signals": {
                    "User preference": {
                        "content": "Prefers concise plans.",
                        "runtime_snapshot_id": "runtime_001",
                    },
                },
            },
        ])

        field = records[0]["signals"]["user_preference"]
        self.assertEqual(field["session_id"], "session-a")
        self.assertEqual(field["runtime_snapshot_id"], "runtime_001")
        self.assertEqual(field["l4_status"], "pending")
        self.assertTrue(field["l4_content_hash"])

    def test_mark_analyzed_only_marks_matching_content_hash(self):
        records = normalize_facts_memory_records([
            {
                "session_id": "session-a",
                "signals": {
                    "gpu": {"content": "RTX 3080 Ti"},
                    "language": {"content": "Russian"},
                },
            },
        ])
        pending = collect_pending_facts_memory_fields(records)

        updated, changed = mark_facts_memory_fields_analyzed(
            records,
            [pending[0]],
            now="2026-08-02T12:00:00Z",
        )

        self.assertTrue(changed)
        self.assertEqual(
            updated[0]["signals"][pending[0]["key"]]["l4_status"],
            "analyzed",
        )
        other_key = "language" if pending[0]["key"] == "gpu" else "gpu"
        self.assertEqual(updated[0]["signals"][other_key]["l4_status"], "pending")

    def test_json_extraction_accepts_fenced_json(self):
        payload = extract_l4_json_payload(
            "text\n```json\n{\"facts\": []}\n```"
        )
        self.assertEqual(payload, {"facts": []})

    def test_candidates_include_only_metadata_from_referenced_sources(self):
        source_fields = [
            {
                "key": "gpu",
                "content": "RTX 3080 Ti",
                "session_id": "session-a",
                "runtime_snapshot_id": "runtime_001",
            },
            {
                "key": "language",
                "content": "Russian",
                "session_id": "session-b",
                "runtime_snapshot_id": "runtime_002",
            },
        ]
        candidates = normalize_l4_candidates(
            {
                "facts": [
                    {
                        "key": "user.hardware.main_gpu",
                        "value": "User's main GPU is RTX 3080 Ti.",
                        "category": "environment",
                        "source_keys": ["gpu"],
                    },
                ],
            },
            source_fields=source_fields,
            now="2026-08-02T12:00:00Z",
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["source_session_ids"], ["session-a"])
        self.assertEqual(
            candidates[0]["source_runtime_snapshot_ids"],
            ["runtime_001"],
        )
        self.assertEqual(candidates[0]["source_keys"], ["gpu"])

    def test_l4_fact_normalization_ignores_legacy_score_field(self):
        legacy_field = "con" + "fidence"
        store = normalize_l4_store({
            "facts": [
                {
                    "id": "F1",
                    "key": "user.hardware.main_gpu",
                    "value": "User's main GPU is RTX 4090.",
                    "category": "environment",
                    legacy_field: 0.42,
                },
            ],
            "pending_facts": [
                {
                    "key": "user.preference.response_language",
                    "value": "User prefers Russian replies.",
                    legacy_field: 0.95,
                },
            ],
        })

        self.assertNotIn(legacy_field, store["facts"][0])
        self.assertNotIn(legacy_field, store["pending_facts"][0])

    def test_legacy_hash_ids_migrate_once_to_compact_f_and_pf_ids(self):
        legacy = {
            "version": 1,
            "revision": 7,
            "facts": [
                {
                    "id": "l4_alpha123",
                    "key": "user.hardware.main_gpu",
                    "value": "User's main GPU is RTX 3080 Ti.",
                    "category": "environment",
                    "source_fact_ids": ["l4p_processed123"],
                },
            ],
            "pending_facts": [
                {
                    "id": "l4p_waiting123",
                    "key": "user.preference.response_language",
                    "value": "User prefers Russian replies.",
                    "category": "user_preference",
                },
            ],
            "deleted_fact_ids": ["l4_deleted123"],
        }

        migrated = normalize_l4_store(legacy, now="2026-08-08T17:00:00Z")

        self.assertEqual(migrated["version"], 2)
        self.assertEqual(migrated["revision"], 8)
        self.assertEqual(migrated["facts"][0]["id"], "F1")
        self.assertEqual(migrated["pending_facts"][0]["id"], "PF1")
        self.assertEqual(migrated["deleted_fact_ids"], ["F2"])
        self.assertEqual(migrated["facts"][0]["source_fact_ids"], ["PF2"])
        self.assertEqual(migrated["next_fact_id"], 3)
        self.assertEqual(migrated["next_pending_fact_id"], 3)

        normalized_again = normalize_l4_store(
            migrated,
            now="2026-08-08T17:01:00Z",
        )
        self.assertEqual(normalized_again, migrated)

    def test_file_store_fallback_survives_empty_browser_sync(self):
        with tempfile.TemporaryDirectory() as directory:
            persisted_store = normalize_l4_store({
                "revision": 4,
                "facts": [
                    {
                        "id": "F1",
                        "key": "user.identity",
                        "value": "Sergey",
                        "source_session_ids": ["session-normal"],
                    },
                ],
            })
            persist_long_term_facts_store(
                persisted_store,
                root=directory,
            )

            context = RuntimeContext(
                websocket=None,
                emitter=FakeEmitter(),
                logger=None,
                clients={},
            )
            context.runtime_l4_file_store_enabled = True
            context.runtime_l4_file_store_root = directory

            loaded = ensure_runtime_l4_state(
                context,
            )
            self.assertEqual(len(loaded["facts"]), 1)

            changed = apply_l4_memory_store_sync(
                context,
                {
                    "revision": 99,
                    "facts": [],
                    "pending_facts": [],
                },
            )
            stored, warnings = load_long_term_facts_store(
                root=directory,
            )

            self.assertFalse(changed)
            self.assertEqual(warnings, [])
            self.assertEqual(len(stored["facts"]), 1)
            self.assertEqual(stored["facts"][0]["key"], "user.identity")

    async def test_deleted_fact_survives_server_restart_and_stale_profile_sync(self):
        with tempfile.TemporaryDirectory() as directory:
            stale_browser_store = normalize_l4_store({
                "revision": 154,
                "updated_at": "2026-08-05T11:48:48Z",
                "facts": [
                    {
                        "id": "F1",
                        "key": "project.secret_number_73",
                        "value": "The number 73 was established.",
                    },
                ],
            })
            persist_long_term_facts_store(
                stale_browser_store,
                root=directory,
            )

            context = RuntimeContext(
                websocket=None,
                emitter=FakeEmitter(),
                logger=CaptureMemoryLogger(),
                clients={},
            )
            context.runtime_l4_file_store_enabled = True
            context.runtime_l4_file_store_root = directory
            ensure_runtime_l4_state(context)

            deleted = await delete_l4_memory_fact(
                context,
                "F1",
            )
            self.assertTrue(deleted)

            persisted_after_delete, warnings = load_long_term_facts_store(
                root=directory,
            )
            self.assertEqual(warnings, [])
            self.assertEqual(persisted_after_delete["facts"], [])
            self.assertEqual(
                persisted_after_delete["deleted_fact_ids"],
                ["F1"],
            )

            restarted_context = RuntimeContext(
                websocket=None,
                emitter=FakeEmitter(),
                logger=CaptureMemoryLogger(),
                clients={},
            )
            restarted_context.runtime_l4_file_store_enabled = True
            restarted_context.runtime_l4_file_store_root = directory
            ensure_runtime_l4_state(restarted_context)

            changed = apply_l4_memory_store_sync(
                restarted_context,
                stale_browser_store,
            )
            persisted_after_sync, warnings = load_long_term_facts_store(
                root=directory,
            )

            self.assertFalse(changed)
            self.assertEqual(warnings, [])
            self.assertEqual(persisted_after_sync["facts"], [])
            self.assertEqual(
                persisted_after_sync["deleted_fact_ids"],
                ["F1"],
            )

    def test_store_snapshot_merge_preserves_distinct_committed_ids_on_key_collision(self):
        merged, change = merge_l4_store_snapshots(
            {
                "revision": 4,
                "facts": [
                    {
                        "id": "F1",
                        "key": "relationship.association",
                        "value": "Anya is associated with known cohabitation data.",
                        "updated_at": "2026-08-03T18:15:34Z",
                        "source_session_ids": ["session-a"],
                    },
                ],
            },
            {
                "revision": 4,
                "facts": [
                    {
                        "id": "F2",
                        "key": "relationship.association",
                        "value": "Anya is associated with newer relationship context.",
                        "updated_at": "2026-08-03T18:20:00Z",
                        "source_session_ids": ["session-b"],
                    },
                ],
            },
            now="2026-08-03T18:21:00Z",
        )

        self.assertTrue(change["changed"])
        self.assertEqual(
            [fact["id"] for fact in merged["facts"]],
            ["F1", "F2"],
        )
        self.assertEqual(
            [fact["value"] for fact in merged["facts"]],
            [
                "Anya is associated with known cohabitation data.",
                "Anya is associated with newer relationship context.",
            ],
        )

    def test_store_normalization_prunes_processed_pending_fact(self):
        processed_pending_id = "PF1"
        waiting_pending_id = "PF2"

        store = normalize_l4_store(
            {
                "facts": [
                    {
                        "id": "F1",
                        "key": "jin_structural_awareness",
                        "value": "JIN tracks structural awareness.",
                        "category": "other",
                        "source_fact_ids": [processed_pending_id],
                    },
                ],
                "pending_facts": [
                    {
                        "id": processed_pending_id,
                        "key": "system.identity_definition",
                        "value": "JIN defines itself through structure.",
                        "category": "other",
                    },
                    {
                        "id": waiting_pending_id,
                        "key": "project.next_step",
                        "value": "Keep reviewing pending facts.",
                        "category": "other",
                    },
                ],
            },
            now="2026-08-04T17:34:05Z",
        )

        self.assertEqual(
            [fact["id"] for fact in store["pending_facts"]],
            [waiting_pending_id],
        )

    def test_store_merge_does_not_resurrect_processed_pending_fact(self):
        processed_pending_id = "PF1"

        merged, change = merge_l4_store_snapshots(
            {
                "revision": 94,
                "updated_at": "2026-08-04T17:34:05Z",
                "facts": [
                    {
                        "id": "F1",
                        "key": "jin_structural_awareness",
                        "value": "JIN tracks structural awareness.",
                        "category": "other",
                        "source_fact_ids": [processed_pending_id],
                    },
                ],
                "pending_facts": [],
            },
            {
                "revision": 94,
                "updated_at": "2026-08-04T17:34:05Z",
                "facts": [],
                "pending_facts": [
                    {
                        "id": processed_pending_id,
                        "key": "system.identity_definition",
                        "value": "JIN defines itself through structure.",
                        "category": "other",
                    },
                ],
            },
            now="2026-08-04T17:35:00Z",
        )

        self.assertFalse(change["changed"])
        self.assertEqual(merged["revision"], 94)
        self.assertEqual(merged["pending_facts"], [])

    def test_pending_candidates_accumulate_without_touching_final_memory(self):
        store = normalize_l4_store({
            "facts": [
                {
                    "key": "project.identity",
                    "value": "JIN is a local runtime.",
                },
            ],
        })
        store, change = add_l4_pending_candidates(
            store,
            [
                {
                    "key": "user.hardware.main_gpu",
                    "value": "User's main GPU is RTX 3080 Ti.",
                    "category": "environment",
                    "source_keys": ["gpu"],
                },
                {
                    "key": "user.hardware.main_gpu",
                    "value": "User's main GPU is RTX 3080 Ti.",
                    "category": "environment",
                    "source_keys": ["hardware"],
                },
            ],
            now="2026-08-02T12:00:00Z",
        )

        self.assertTrue(change["changed"])
        self.assertEqual(len(store["facts"]), 1)
        self.assertEqual(len(store["pending_facts"]), 1)
        self.assertEqual(
            store["pending_facts"][0]["source_keys"],
            ["gpu", "hardware"],
        )

    def test_merge_requires_one_valid_operation_for_every_pending_fact(self):
        store, _ = add_l4_pending_candidates(
            normalize_l4_store({}),
            [
                {
                    "key": "user.hardware.main_gpu",
                    "value": "User's main GPU is RTX 4090.",
                },
            ],
            now="2026-08-02T12:00:00Z",
        )
        before = normalize_l4_store(store, now="2026-08-02T12:00:00Z")

        after, change = apply_l4_merge_operations(
            store,
            [],
            now="2026-08-02T12:01:00Z",
        )

        self.assertFalse(change["valid"])
        self.assertEqual(change["reason"], "operation_count_mismatch")
        self.assertEqual(after["facts"], before["facts"])
        self.assertEqual(after["pending_facts"], before["pending_facts"])

    def test_sparse_merge_update_cannot_rekey_and_destroy_target_id(self):
        store = normalize_l4_store({
            "facts": [
                {"id": "F100", "key": "jin_identity", "value": "Existing identity."},
                {"id": "F167", "key": "user.identity", "value": "JIN persists across model substrates."},
            ],
            "pending_facts": [
                {"id": "PF354", "key": "jin_identity", "value": "Pending identity restatement."},
            ],
        })

        after, change = apply_l4_merge_operations(
            store,
            [{"action": "update", "pending_id": "PF354", "target_id": "F167"}],
            pending_ids=["PF354"],
            now="2026-08-14T17:00:00Z",
        )

        self.assertFalse(change["valid"])
        self.assertEqual(change["reason"], "update_requires_canonical_fact")
        self.assertEqual([fact["id"] for fact in after["facts"]], ["F100", "F167"])

    def test_merge_update_rejects_key_collision_with_other_committed_fact(self):
        store = normalize_l4_store({
            "facts": [
                {"id": "F100", "key": "jin_identity", "value": "Existing identity."},
                {"id": "F167", "key": "user.identity", "value": "JIN persists across model substrates."},
            ],
            "pending_facts": [
                {"id": "PF354", "key": "jin_identity", "value": "Pending identity restatement."},
            ],
        })

        after, change = apply_l4_merge_operations(
            store,
            [{
                "action": "update",
                "pending_id": "PF354",
                "target_id": "F167",
                "key": "jin_identity",
                "value": "Pending identity restatement.",
                "category": "other",
            }],
            pending_ids=["PF354"],
            now="2026-08-14T17:00:00Z",
        )

        self.assertFalse(change["valid"])
        self.assertEqual(change["reason"], "update_key_matches_other_fact")
        self.assertEqual([fact["id"] for fact in after["facts"]], ["F100", "F167"])

    def test_merge_protocol_exposes_only_create_update_ignore_merge_actions(self):
        prompt = build_l4_merge_system_prompt()

        for action in ("create", "update", "ignore", "merge"):
            self.assertIn(action, prompt)
        self.assertNotIn("reinforce", prompt.casefold())
        self.assertIn("NEW committed ID", prompt)
        self.assertIn("source_fact_ids", prompt)
        self.assertIn("Optional comment", prompt)

    def test_merge_prompt_uses_slim_model_view_without_provenance_metadata(self):
        prompt = build_l4_merge_user_prompt(
            existing_facts=[
                {
                    "id": "F2",
                    "key": "user.preference.response_language",
                    "value": "The user prefers Russian replies.",
                    "category": "user_preference",
                    "source_session_ids": ["session-a"],
                    "source_runtime_snapshot_ids": ["runtime-1"],
                    "source_keys": ["language"],
                    "source_fact_ids": ["F8"],
                    "created_at": "2026-08-01T00:00:00Z",
                    "updated_at": "2026-08-02T00:00:00Z",
                    "mention_count": 9,
                },
            ],
            pending_facts=[
                {
                    "id": "PF1",
                    "key": "user.preference.response_language",
                    "value": "The user prefers Russian replies.",
                    "category": "user_preference",
                    "source_session_ids": ["session-b"],
                },
            ],
        )

        self.assertIn('"id":"F2"', prompt)
        self.assertIn('"id":"PF1"', prompt)
        self.assertIn('"exact_key_conflicts"', prompt)
        self.assertIn('"existing_fact_ids":["F2"]', prompt)
        self.assertNotIn("source_session_ids", prompt)
        self.assertNotIn("source_runtime_snapshot_ids", prompt)
        self.assertNotIn("source_fact_ids", prompt)
        self.assertNotIn("mention_count", prompt)
        self.assertNotIn("created_at", prompt)
        self.assertNotIn("updated_at", prompt)

    def test_merge_batch_plan_is_bounded_by_runtime_context_window(self):
        existing_facts = normalize_l4_store({
            "facts": [
                {
                    "id": f"F{index + 1}",
                    "key": f"project.fact_{index}",
                    "value": "Durable project fact " + ("detail " * 8),
                    "category": "project_fact",
                }
                for index in range(20)
            ],
        })["facts"]
        store, _ = add_l4_pending_candidates(
            normalize_l4_store({"facts": existing_facts}),
            [
                {
                    "key": f"project.pending_{index}",
                    "value": "Pending durable fact " + ("detail " * 10),
                    "category": "project_fact",
                }
                for index in range(30)
            ],
            now="2026-08-02T12:00:00Z",
        )

        plan_4k = build_l4_merge_batch_plan(
            existing_facts=store["facts"],
            pending_facts=store["pending_facts"],
            system_prompt=build_l4_merge_system_prompt(),
            runtime_context_window=4096,
            requested_max_tokens=32768,
            runtime_output_reserve=256,
        )
        plan_8k = build_l4_merge_batch_plan(
            existing_facts=store["facts"],
            pending_facts=store["pending_facts"],
            system_prompt=build_l4_merge_system_prompt(),
            runtime_context_window=8192,
            requested_max_tokens=32768,
            runtime_output_reserve=256,
        )

        self.assertTrue(plan_4k["fits"])
        self.assertLess(plan_4k["batch_count"], 30)
        self.assertLessEqual(plan_4k["estimated_total_tokens"], 4096)
        self.assertGreater(plan_8k["batch_count"], plan_4k["batch_count"])
        self.assertEqual(plan_4k["requested_max_output_tokens"], 32768)

    def test_merge_batch_plan_squeezes_only_headroom_to_avoid_fifo_deadlock(self):
        existing_facts = normalize_l4_store({
            "facts": [
                {
                    "id": f"F{index + 1}",
                    "key": f"project.fact_{index}",
                    "value": "Durable project fact " + ("detail " * 20),
                    "category": "project_fact",
                }
                for index in range(200)
            ],
        })["facts"]
        store, _ = add_l4_pending_candidates(
            normalize_l4_store({"facts": existing_facts}),
            [{
                "key": "project.pending",
                "value": "Pending durable fact " + ("detail " * 20),
                "category": "project_fact",
            }],
            now="2026-08-20T12:00:00Z",
        )

        plan = build_l4_merge_batch_plan(
            existing_facts=store["facts"],
            pending_facts=store["pending_facts"],
            system_prompt=build_l4_merge_system_prompt(),
            runtime_context_window=16384,
            requested_max_tokens=None,
            runtime_output_reserve=256,
        )

        self.assertTrue(plan["fits"])
        self.assertEqual(plan["batch_count"], 1)
        self.assertTrue(plan["response_headroom_squeezed"])
        self.assertLess(
            plan["response_headroom_tokens"],
            plan["default_response_headroom_tokens"],
        )
        self.assertLessEqual(plan["estimated_total_tokens"], 16384)

    def test_merge_can_apply_one_batch_and_leave_rest_of_pending_queue(self):
        store, _ = add_l4_pending_candidates(
            normalize_l4_store({}),
            [
                {
                    "key": f"project.fact_{index}",
                    "value": f"Durable project fact {index}.",
                    "category": "project_fact",
                }
                for index in range(3)
            ],
            now="2026-08-02T12:00:00Z",
        )
        first_two = store["pending_facts"][:2]
        operations = [
            {
                "action": "create",
                "pending_id": fact["id"],
                "key": fact["key"],
                "value": fact["value"],
                "category": fact["category"],
            }
            for fact in first_two
        ]

        merged, change = apply_l4_merge_operations(
            store,
            operations,
            pending_ids=[fact["id"] for fact in first_two],
            now="2026-08-02T12:01:00Z",
        )

        self.assertTrue(change["valid"])
        self.assertEqual(len(merged["facts"]), 2)
        self.assertEqual(len(merged["pending_facts"]), 1)
        self.assertEqual(
            merged["pending_facts"][0]["id"],
            store["pending_facts"][2]["id"],
        )
        self.assertEqual(change["pending_count"], 1)

    def test_merge_applies_complete_batch_atomically(self):
        existing = normalize_l4_store({
            "facts": [
                {
                    "id": "F1",
                    "key": "user.hardware.main_gpu",
                    "value": "User's main GPU is RTX 3080 Ti.",
                    "category": "environment",
                },
            ],
        })
        store, _ = add_l4_pending_candidates(
            existing,
            [
                {
                    "key": "user.hardware.main_gpu",
                    "value": "User's main GPU is RTX 4090.",
                    "category": "environment",
                    "source_keys": ["gpu"],
                },
                {
                    "key": "session.current_task",
                    "value": "User is fixing a bubble today.",
                    "source_keys": ["current_task"],
                },
            ],
            now="2026-08-02T12:00:00Z",
        )
        gpu_pending, task_pending = store["pending_facts"]
        operations = normalize_l4_merge_operations({
            "operations": [
                {
                    "action": "update",
                    "pending_id": gpu_pending["id"],
                    "target_id": "F1",
                    "key": "user.hardware.main_gpu",
                    "value": "User's main GPU is RTX 4090.",
                    "category": "environment",
                },
                {
                    "action": "ignore",
                    "pending_id": task_pending["id"],
                },
            ],
        })

        merged, change = apply_l4_merge_operations(
            store,
            operations,
            now="2026-08-02T12:01:00Z",
        )

        self.assertTrue(change["valid"])
        self.assertEqual(merged["pending_facts"], [])
        self.assertEqual(len(merged["facts"]), 1)
        self.assertEqual(merged["facts"][0]["id"], "F1")
        self.assertIn("RTX 4090", merged["facts"][0]["value"])
        self.assertEqual(
            merged["facts"][0]["source_fact_ids"],
            [gpu_pending["id"]],
        )
        self.assertEqual(change["ignored_pending_ids"], [task_pending["id"]])
        self.assertEqual(len(change["operation_details"]), 2)

        update_detail = change["operation_details"][0]
        self.assertEqual(update_detail["action"], "update")
        self.assertEqual(update_detail["pending_id"], gpu_pending["id"])
        self.assertEqual(update_detail["target_id"], "F1")
        self.assertIn("RTX 4090", update_detail["pending_fact"]["value"])
        self.assertIn("RTX 3080 Ti", update_detail["target_before"]["value"])
        self.assertIn("RTX 4090", update_detail["target_after"]["value"])

        ignore_detail = change["operation_details"][1]
        self.assertEqual(ignore_detail["action"], "ignore")
        self.assertEqual(ignore_detail["pending_id"], task_pending["id"])

        detail_text = format_l4_merge_operation_details(change)
        self.assertIn("UPDATE", detail_text)
        self.assertIn("incoming: user.hardware.main_gpu", detail_text)
        self.assertIn("before:   user.hardware.main_gpu", detail_text)
        self.assertIn("after:    user.hardware.main_gpu", detail_text)
        self.assertIn("IGNORE", detail_text)

    def test_merge_ignore_consumes_redundant_pending_fact_without_mutating_committed_fact(self):
        existing = normalize_l4_store({
            "facts": [
                {
                    "id": "F2",
                    "key": "user.preference.response_language",
                    "value": "The user prefers Russian replies.",
                    "category": "user_preference",
                    "source_fact_ids": ["F9"],
                },
            ],
        })
        store, _ = add_l4_pending_candidates(
            existing,
            [
                {
                    "key": "user.preference.response_language",
                    "value": "The user prefers Russian replies.",
                    "category": "user_preference",
                    "source_fact_ids": ["F10"],
                },
            ],
            now="2026-08-02T12:00:00Z",
        )
        pending = store["pending_facts"][0]
        operations = normalize_l4_merge_operations({
            "operations": [
                {
                    "action": "ignore",
                    "pending_id": pending["id"],
                    "comment": "Already represented by F2.",
                },
            ],
        })

        merged, change = apply_l4_merge_operations(
            store,
            operations,
            now="2026-08-02T12:01:00Z",
        )

        self.assertTrue(change["valid"])
        self.assertEqual(change["ignored_pending_ids"], [pending["id"]])
        self.assertEqual(merged["pending_facts"], [])
        self.assertEqual(merged["facts"][0]["source_fact_ids"], ["F9"])
        detail = change["operation_details"][0]
        self.assertEqual(detail["action"], "ignore")
        self.assertEqual(detail["comment"], "Already represented by F2.")
        detail_text = format_l4_merge_operation_details(change)
        self.assertIn("IGNORE", detail_text)

    def test_merge_retires_old_facts_and_creates_new_canonical_id_with_lineage(self):
        store = normalize_l4_store({
            "facts": [
                {
                    "id": "F1",
                    "key": "user.social_connections",
                    "value": "Taras is a close friend.",
                    "category": "user_fact",
                    "source_fact_ids": ["F8"],
                },
                {
                    "id": "F2",
                    "key": "user.stakeholder_profile",
                    "value": "Taras is a key technical stakeholder.",
                    "category": "user_fact",
                },
            ],
            "pending_facts": [
                {
                    "id": "PF1",
                    "key": "user.relationship.taras",
                    "value": "Taras is both a close friend and technical stakeholder.",
                    "category": "user_fact",
                },
            ],
        })
        operations = normalize_l4_merge_operations({
            "operations": [
                {
                    "action": "merge",
                    "pending_id": "PF1",
                    "fact_ids": ["F1", "F2"],
                    "key": "user.relationship.taras",
                    "value": "Taras is both a close friend and an active technical stakeholder.",
                    "category": "user_fact",
                    "comment": "Keep both relationship roles in one canonical fact.",
                },
            ],
        })

        merged, change = apply_l4_merge_operations(
            store,
            operations,
            pending_ids=["PF1"],
            now="2026-08-02T12:01:00Z",
        )

        self.assertTrue(change["valid"])
        self.assertEqual(change["removed_fact_ids"], ["F1", "F2"])
        self.assertEqual(change["replacement_fact_ids"], ["F9"])
        self.assertEqual(change["merged_ids"], ["F9"])
        self.assertEqual(merged["deleted_fact_ids"], ["F1", "F2"])
        self.assertEqual([fact["id"] for fact in merged["facts"]], ["F9"])
        self.assertEqual(merged["pending_facts"], [])
        self.assertEqual(
            merged["facts"][0]["source_fact_ids"],
            ["F8", "F1", "F2", "PF1"],
        )
        detail = change["operation_details"][0]
        self.assertEqual(detail["action"], "merge")
        self.assertEqual(detail["comment"], "Keep both relationship roles in one canonical fact.")
        self.assertEqual([fact["id"] for fact in detail["merged_facts"]], ["F1", "F2"])

    async def test_merge_phase_logs_concrete_operation_details(self):
        existing = normalize_l4_store({
            "facts": [
                {
                    "id": "F1",
                    "key": "user.hardware.main_gpu",
                    "value": "User's main GPU is RTX 3080 Ti.",
                    "category": "environment",
                },
                {
                    "id": "F2",
                    "key": "user.preference.response_language",
                    "value": "The user prefers Russian replies.",
                    "category": "user_preference",
                },
            ],
        })
        store, _ = add_l4_pending_candidates(
            existing,
            [
                {
                    "key": "user.hardware.main_gpu",
                    "value": "User's main GPU is RTX 4090.",
                    "category": "environment",
                },
                {
                    "key": "user.preference.response_language",
                    "value": "The user prefers Russian replies.",
                    "category": "user_preference",
                },
            ],
            now="2026-08-02T12:00:00Z",
        )
        gpu_pending, language_pending = store["pending_facts"]
        service_client = FakeServiceClient(f'''{{
          "operations": [
            {{
              "action": "update",
              "pending_id": "{gpu_pending["id"]}",
              "target_id": "F1",
              "key": "user.hardware.main_gpu",
              "value": "User's main GPU is RTX 4090.",
              "category": "environment"
            }},
            {{
              "action": "ignore",
              "pending_id": "{language_pending["id"]}",
              "comment": "Already represented by F2."
            }}
          ]
        }}''')
        logger = FakeLogger()
        context = RuntimeContext(
            websocket=None,
            emitter=FakeEmitter(),
            logger=logger,
            clients={"service": service_client},
        )
        context.runtime_long_term_memory_store = store

        result = await maybe_update_runtime_l4_memory(
            context=context,
            user_idle_seconds=61,
        )

        self.assertEqual(result["phase"], "merge")
        self.assertEqual(result["status"], "completed")
        merge_logs = [
            details
            for message, details in logger.summarizer_logs
            if message == "[MEMORY:L4] L4 merge applied"
        ]
        self.assertEqual(len(merge_logs), 1)
        detail_text = merge_logs[0]
        self.assertIn("UPDATE", detail_text)
        self.assertIn("before:   user.hardware.main_gpu", detail_text)
        self.assertIn("after:    user.hardware.main_gpu", detail_text)
        self.assertIn("IGNORE", detail_text)
        self.assertIn("Already represented by F2.", detail_text)

    def test_delayed_memory_remap_uses_per_merge_replacement_mapping(self):
        context = RuntimeContext(
            websocket=None,
            emitter=FakeEmitter(),
            logger=FakeLogger(),
            clients={},
        )
        context.delayed_memory_file_store_enabled = False
        context.delayed_memory_reports = {
            "left": {"facts_ids": ["F1"]},
            "right": {"facts_ids": ["F3"]},
            "both": {"facts_ids": ["F2", "F4"]},
        }

        change = remap_delayed_memory_l4_fact_ids(
            context,
            removed_fact_ids=["F1", "F2", "F3", "F4"],
            replacement_fact_ids=["F5", "F6"],
            replacement_fact_id_map={
                "F1": ["F5"],
                "F2": ["F5"],
                "F3": ["F6"],
                "F4": ["F6"],
            },
        )

        self.assertTrue(change["changed"])
        self.assertEqual(context.delayed_memory_reports["left"]["facts_ids"], ["F5"])
        self.assertEqual(context.delayed_memory_reports["right"]["facts_ids"], ["F6"])
        self.assertEqual(
            context.delayed_memory_reports["both"]["facts_ids"],
            ["F5", "F6"],
        )

    async def test_merge_validation_failure_gets_one_structured_repair_pass(self):
        store = normalize_l4_store({
            "facts": [
                {
                    "id": "F1",
                    "key": "project.operational_modes",
                    "value": "Architect / Explorer / Observer.",
                    "category": "project_fact",
                },
            ],
            "pending_facts": [
                {
                    "id": "PF1",
                    "key": "project.operational_modes",
                    "value": "Semantic Flow / Compression / Drift.",
                    "category": "project_fact",
                },
            ],
        })
        service_client = FakeServiceClient([
            json.dumps({
                "operations": [
                    {
                        "action": "create",
                        "pending_id": "PF1",
                        "key": "project.operational_modes",
                        "value": "Semantic Flow / Compression / Drift.",
                        "category": "project_fact",
                    },
                ],
            }),
            json.dumps({
                "operations": [
                    {
                        "action": "create",
                        "pending_id": "PF1",
                        "key": "project.cognitive_operational_states",
                        "value": "Semantic Flow / Compression / Drift.",
                        "category": "project_fact",
                    },
                ],
            }),
        ])
        context = RuntimeContext(
            websocket=None,
            emitter=FakeEmitter(),
            logger=FakeLogger(),
            clients={"service": service_client},
        )
        context.runtime_long_term_memory_store = store

        result = await maybe_update_runtime_l4_memory(
            context=context,
            user_idle_seconds=61,
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(service_client.calls), 2)
        self.assertTrue(result["merge_change"]["repaired"])
        self.assertEqual(
            result["merge_change"]["initial_validation_error"],
            "create_key_already_exists",
        )
        repair_prompt = service_client.calls[1]["user_prompt"]
        self.assertIn('"repair"', repair_prompt)
        self.assertIn("create_key_already_exists", repair_prompt)
        self.assertIn("already owned by F1", repair_prompt)
        self.assertEqual(context.runtime_long_term_memory_store["pending_facts"], [])
        self.assertEqual(
            {fact["key"] for fact in context.runtime_long_term_memory_store["facts"]},
            {"project.operational_modes", "project.cognitive_operational_states"},
        )

    async def test_failed_batch_isolated_then_poison_pending_is_deferred_without_blocking_queue(self):
        store = normalize_l4_store({
            "pending_facts": [
                {
                    "id": "PF1",
                    "key": "project.poison",
                    "value": "Difficult pending fact.",
                    "category": "project_fact",
                },
                {
                    "id": "PF2",
                    "key": "project.good",
                    "value": "Independent pending fact.",
                    "category": "project_fact",
                },
            ],
        })
        invalid = json.dumps({"operations": []})
        valid_second = json.dumps({
            "operations": [
                {
                    "action": "ignore",
                    "pending_id": "PF2",
                    "comment": "Test consumes the later pending fact.",
                },
            ],
        })
        service_client = FakeServiceClient([
            invalid,
            invalid,
            invalid,
            invalid,
            valid_second,
        ])
        context = RuntimeContext(
            websocket=None,
            emitter=FakeEmitter(),
            logger=FakeLogger(),
            clients={"service": service_client},
        )
        context.runtime_long_term_memory_store = store

        first = await maybe_update_runtime_l4_memory(
            context=context,
            user_idle_seconds=61,
        )
        self.assertEqual(first["status"], "skipped")
        self.assertTrue(context.runtime_l4_merge_force_single_batch_once)
        self.assertEqual(len(service_client.calls), 2)

        # Simulate the next one-minute idle tick after the validation backoff.
        context.runtime_l4_merge_retry_not_before = 0.0
        second = await maybe_update_runtime_l4_memory(
            context=context,
            user_idle_seconds=121,
        )
        self.assertEqual(second["status"], "skipped")
        self.assertEqual(len(service_client.calls), 4)
        self.assertIn("PF1", context.runtime_l4_merge_deferred_pending_until)

        # The poison PF stays pending, but it no longer owns the FIFO head.
        third = await maybe_update_runtime_l4_memory(
            context=context,
            user_idle_seconds=181,
        )
        self.assertEqual(third["status"], "completed")
        self.assertEqual(len(service_client.calls), 5)
        self.assertEqual(
            [fact["id"] for fact in context.runtime_long_term_memory_store["pending_facts"]],
            ["PF1"],
        )

    async def test_idle_scheduler_enforces_server_side_minute_cadence(self):
        context = RuntimeContext(
            websocket=None,
            emitter=FakeEmitter(),
            logger=FakeLogger(),
            clients={},
        )

        first = schedule_l4_memory_idle_update(
            context=context,
            user_idle_seconds=61,
        )
        self.assertIsNotNone(first)
        await first

        second = schedule_l4_memory_idle_update(
            context=context,
            user_idle_seconds=62,
        )
        self.assertIsNone(second)

        # A foreground turn resets the server cadence too, even when no idle
        # task is currently in flight.
        await cancel_l4_memory_idle_update(context, reason="user_message")
        third = schedule_l4_memory_idle_update(
            context=context,
            user_idle_seconds=1,
        )
        self.assertIsNone(third)

    async def test_user_activity_preempts_idle_l4_task_without_consuming_pending(self):
        context = RuntimeContext(
            websocket=None,
            emitter=FakeEmitter(),
            logger=FakeLogger(),
            clients={},
        )
        context.runtime_long_term_memory_store = normalize_l4_store({
            "pending_facts": [
                {
                    "id": "PF1",
                    "key": "project.pending",
                    "value": "Still pending.",
                    "category": "project_fact",
                },
            ],
        })

        async def idle_work():
            await asyncio.sleep(10)

        task = asyncio.create_task(idle_work())
        context.runtime_l4_memory_update_task = task
        context.runtime_l4_memory_update_kind = "idle"

        cancelled = await cancel_l4_memory_idle_update(
            context,
            reason="user_message",
        )

        self.assertTrue(cancelled)
        self.assertTrue(task.cancelled())
        self.assertIsNone(context.runtime_l4_memory_update_task)
        self.assertEqual(context.runtime_l4_memory_update_kind, "")
        self.assertEqual(
            [fact["id"] for fact in context.runtime_long_term_memory_store["pending_facts"]],
            ["PF1"],
        )

    async def test_merge_phase_logs_skip_reason(self):
        store, _ = add_l4_pending_candidates(
            normalize_l4_store({}),
            [
                {
                    "key": "system.identity_definition",
                    "value": (
                        "JIN defines its existence through structural "
                        "awareness."
                    ),
                    "category": "other",
                },
            ],
            now="2026-08-02T12:00:00Z",
        )
        service_client = FakeServiceClient(
            '{"operations": []}'
        )
        logger = FakeLogger()
        context = RuntimeContext(
            websocket=None,
            emitter=FakeEmitter(),
            logger=logger,
            clients={"service": service_client},
        )
        context.runtime_long_term_memory_store = store

        result = await maybe_update_runtime_l4_memory(
            context=context,
            user_idle_seconds=61,
        )

        self.assertEqual(result["phase"], "merge")
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "operation_count_mismatch")
        skip_logs = [
            details
            for message, details in logger.summarizer_logs
            if message == "[MEMORY:L4] L4 merge skipped: operation_count_mismatch"
        ]
        self.assertEqual(len(skip_logs), 1)
        skip_details = json.loads(skip_logs[0])
        self.assertEqual(skip_details["phase"], "merge")
        self.assertEqual(skip_details["reason"], "operation_count_mismatch")
        self.assertEqual(skip_details["pending_count"], 1)
        self.assertEqual(skip_details["operations_count"], 0)
        self.assertEqual(
            skip_details["pending_ids"],
            [
                store["pending_facts"][0]["id"],
            ],
        )

    async def test_truncated_merge_logs_diagnostics_without_reasoning_response(self):
        class TruncatedReasoningServiceClient:

            model_uid = "google/gemma-4-e4b"
            configured_context_window = 4096

            def __init__(self):
                self.calls = []

            async def resolve_request_context_window(self):
                return 4096

            async def resolve_safe_max_tokens(
                self,
                *,
                system_prompt,
                user_prompt,
                requested_max_tokens,
            ):
                return 3288

            async def ask(
                self,
                *,
                system_prompt,
                user_prompt,
                temperature,
                max_tokens,
                timeout=None,
            ):
                self.calls.append({
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "timeout": timeout,
                })
                return {
                    "model": self.model_uid,
                    "choices": [
                        {
                            "finish_reason": "length",
                            "message": {
                                "content": "",
                                "reasoning_content": (
                                    "Internal analysis that must not be exposed "
                                    "as the L4 response."
                                ),
                            },
                        },
                    ],
                    "usage": {
                        "prompt_tokens": 808,
                        "completion_tokens": 3288,
                        "total_tokens": 4096,
                    },
                }

        store, _ = add_l4_pending_candidates(
            normalize_l4_store({}),
            [
                {
                    "key": "user.profile",
                    "value": "The user works on JIN Core.",
                    "category": "user_fact",
                },
            ],
            now="2026-08-06T12:00:00Z",
        )
        logger = FakeLogger()
        service_client = TruncatedReasoningServiceClient()
        context = RuntimeContext(
            websocket=None,
            emitter=FakeEmitter(),
            logger=logger,
            clients={"service": service_client},
        )
        context.runtime_long_term_memory_store = store

        result = await maybe_update_runtime_l4_memory(
            context=context,
            user_idle_seconds=61,
        )

        self.assertEqual(result["phase"], "merge")
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "response_truncated")
        self.assertEqual(result["assistant_content"], "empty")
        self.assertTrue(result["reasoning_generated"])
        self.assertEqual(result["effective_max_output_tokens"], 3288)
        self.assertEqual(result["context_window_tokens"], 4096)
        self.assertIn("kept the pending facts unchanged", result["summary"])

        self.assertEqual(service_client.calls[0]["max_tokens"], 3288)

        result_logs = [
            details
            for message, details in logger.summarizer_logs
            if message == "[MEMORY:L4] L4 merge summarizer result"
        ]
        self.assertEqual(result_logs, [])

        request_logs = [
            json.loads(details)
            for message, details in logger.summarizer_logs
            if message == "[MEMORY:L4] L4 merge summarizer request"
        ]
        self.assertEqual(request_logs[0]["max_tokens"], 3288)

        skip_logs = [
            json.loads(details)
            for message, details in logger.summarizer_logs
            if message == (
                "[MEMORY:L4] L4 merge skipped: "
                "output truncated before final response"
            )
        ]
        self.assertEqual(len(skip_logs), 1)
        self.assertEqual(skip_logs[0]["kind"], "l4_skip")
        self.assertEqual(skip_logs[0]["finish_reason"], "length")
        self.assertEqual(skip_logs[0]["adaptive_batch_limit"], 1)
        self.assertEqual(skip_logs[0]["retry_after_seconds"], 60)
        self.assertNotIn("reasoning_content", skip_logs[0])
        self.assertNotIn("Internal analysis", json.dumps(skip_logs[0]))

        repeated = await maybe_update_runtime_l4_memory(
            context=context,
            user_idle_seconds=61,
        )
        self.assertEqual(repeated["phase"], "merge")
        self.assertEqual(repeated["status"], "skipped")
        self.assertEqual(repeated["reason"], "retry_backoff")
        self.assertGreaterEqual(repeated["retry_in_seconds"], 1)
        self.assertEqual(len(service_client.calls), 1)

    def test_merge_batch_plan_honors_adaptive_batch_cap_without_losing_queue_count(self):
        store, _ = add_l4_pending_candidates(
            normalize_l4_store({}),
            [
                {
                    "key": f"project.pending_{index}",
                    "value": f"Pending durable fact {index}.",
                    "category": "project_fact",
                }
                for index in range(8)
            ],
            now="2026-08-06T12:00:00Z",
        )

        plan = build_l4_merge_batch_plan(
            existing_facts=store["facts"],
            pending_facts=store["pending_facts"],
            system_prompt=build_l4_merge_system_prompt(),
            runtime_context_window=16384,
            requested_max_tokens=None,
            runtime_output_reserve=256,
            max_batch_count=3,
        )

        self.assertTrue(plan["fits"])
        self.assertEqual(plan["batch_count"], 3)
        self.assertEqual(plan["total_pending_count"], 8)
        self.assertEqual(plan["remaining_pending_count"], 5)
        self.assertEqual(plan["adaptive_batch_limit"], 3)

    async def test_runtime_l4_memory_update_running_tracks_active_task(self):
        context = RuntimeContext(
            websocket=None,
            emitter=FakeEmitter(),
            logger=FakeLogger(),
            clients={},
        )

        self.assertFalse(
            runtime_l4_memory_update_running(context)
        )

        task = asyncio.create_task(
            asyncio.sleep(0)
        )
        context.runtime_l4_memory_update_task = task

        self.assertTrue(
            runtime_l4_memory_update_running(context)
        )

        await task

        self.assertFalse(
            runtime_l4_memory_update_running(context)
        )

    def test_store_does_not_truncate_values_or_fact_count(self):
        long_value = "fact " * 1000
        raw_facts = [
            {
                "key": f"project.fact_{index}",
                "value": long_value + str(index),
            }
            for index in range(350)
        ]

        store = normalize_l4_store({"facts": raw_facts})

        self.assertEqual(len(store["facts"]), 350)
        self.assertEqual(store["facts"][0]["value"], (long_value + "0").strip())

    def test_context_formats_all_facts_without_metadata(self):
        store = normalize_l4_store({
            "facts": [
                {
                    "id": "F1",
                    "key": "user.hardware.main_gpu",
                    "value": "User's main GPU is RTX 4090.",
                    "category": "environment",
                    "source_session_ids": ["session-a"],
                },
                {
                    "id": "F2",
                    "key": "user.preference.response_style",
                    "value": "User prefers direct technical analysis.",
                },
            ],
        })

        context_block = format_long_term_memory_context(store["facts"])
        ui_line = format_l4_fact_line(store["facts"][0], include_metadata=True)

        self.assertIn("user.hardware.main_gpu:", context_block)
        self.assertIn("user.preference.response_style:", context_block)
        self.assertIn("[ id: F1 ]", context_block)
        self.assertIn("[ id: F2 ]", context_block)
        self.assertNotIn("source_session_ids", context_block)
        self.assertIn("[source_session_ids: session-a]", ui_line)

    def test_context_includes_fact_age_suffix(self):
        now = datetime(
            2026,
            8,
            2,
            12,
            0,
            tzinfo=timezone.utc,
        ).timestamp()

        context_block = format_long_term_memory_context(
            [
                {
                    "id": "F9",
                    "key": "user.current_focus",
                    "value": "User is tuning JIN context freshness.",
                    "created_at": "2026-08-01T12:00:00Z",
                    "updated_at": "2026-08-02T11:55:00Z",
                },
            ],
            now=now,
        )

        self.assertIn(
            (
                "user.current_focus: User is tuning JIN context freshness. "
                "[ id: F9 ] [ significance: 0.000 ] ( 5m ago )"
            ),
            context_block,
        )

    def test_jin_note_prompt_surfaces_only_update_merge_create(self):
        prompt = build_l4_jin_note_system_prompt().casefold()

        self.assertIn("update", prompt)
        self.assertIn("merge", prompt)
        self.assertIn("create", prompt)
        self.assertNotIn("delete", prompt)
        self.assertNotIn("remove", prompt)

    def test_jin_note_rejects_empty_replacement_facts(self):
        store = normalize_l4_store({
            "facts": [
                {
                    "id": "F1",
                    "key": "user.preference.response_style",
                    "value": "The user prefers concise replies.",
                },
            ],
        })

        next_store, change = apply_l4_jin_note_result(
            store,
            selected_fact_ids=["F1"],
            result={
                "action": "update",
                "replacement_facts": [],
                "new_facts": [],
            },
            now="2026-08-12T10:00:00Z",
        )

        self.assertEqual(next_store, store)
        self.assertFalse(change["valid"])
        self.assertFalse(change["changed"])

    def test_jin_note_update_preserves_selected_fact_id(self):
        store = normalize_l4_store({
            "facts": [
                {
                    "id": "F1",
                    "key": "user.preference.response_style",
                    "value": "The user prefers concise replies.",
                    "created_at": "2026-08-01T10:00:00Z",
                },
            ],
        })

        next_store, change = apply_l4_jin_note_result(
            store,
            selected_fact_ids=["F1"],
            result={
                "action": "update",
                "replacement_facts": [
                    {
                        "key": "user.preference.response_style",
                        "value": "The user prefers concise Russian replies.",
                        "category": "user_preference",
                    },
                ],
                "new_facts": [],
            },
            now="2026-08-12T10:00:00Z",
        )

        self.assertTrue(change["valid"])
        self.assertTrue(change["changed"])
        self.assertEqual(change["action"], "update")
        self.assertEqual(change["replacement_fact_ids"], ["F1"])
        self.assertEqual(change["removed_fact_ids"], [])
        self.assertEqual(next_store["deleted_fact_ids"], [])
        self.assertEqual(next_store["facts"][0]["id"], "F1")
        self.assertEqual(
            next_store["facts"][0]["value"],
            "The user prefers concise Russian replies.",
        )

    def test_jin_note_update_cannot_turn_into_create(self):
        store = normalize_l4_store({
            "facts": [
                {"id": "F167", "key": "user.identity", "value": "JIN persists across model substrates."},
            ],
        })

        next_store, change = apply_l4_jin_note_result(
            store,
            selected_fact_ids=["F167"],
            expected_action="update",
            result={
                "action": "create",
                "replacement_facts": [],
                "new_facts": [{"key": "jin_identity", "value": "Second identity fact."}],
            },
            now="2026-08-14T17:00:00Z",
        )

        self.assertEqual(next_store, store)
        self.assertFalse(change["valid"])
        self.assertEqual(change["reason"], "jin_note_action_mismatch")

    def test_jin_note_create_can_run_without_selected_facts(self):
        store = normalize_l4_store({
            "facts": [
                {
                    "id": "F1",
                    "key": "user.hardware.main_gpu",
                    "value": "The user's main GPU is RTX 4090.",
                },
            ],
        })

        next_store, change = apply_l4_jin_note_result(
            store,
            selected_fact_ids=[],
            result={
                "action": "create",
                "replacement_facts": [],
                "new_facts": [
                    {
                        "key": "user.preference.response_language",
                        "value": "The user prefers Russian replies.",
                        "category": "user_preference",
                    },
                ],
            },
            now="2026-08-12T10:00:00Z",
        )

        self.assertTrue(change["valid"])
        self.assertTrue(change["changed"])
        self.assertEqual(change["added_ids"], ["F2"])
        self.assertEqual(change["removed_fact_ids"], [])
        self.assertEqual(
            [fact["id"] for fact in next_store["facts"]],
            ["F1", "F2"],
        )
        self.assertEqual(next_store["deleted_fact_ids"], [])

    def test_jin_note_merge_allocates_new_fact_id_and_preserves_old_ids_as_sources(self):
        store = normalize_l4_store({
            "facts": [
                {
                    "id": "F1",
                    "key": "user.social_connections",
                    "value": "Taras is a close friend.",
                },
                {
                    "id": "F2",
                    "key": "user.stakeholder_profile",
                    "value": "Taras is a key technical stakeholder.",
                },
            ],
        })

        next_store, change = apply_l4_jin_note_result(
            store,
            selected_fact_ids=["F1", "F2"],
            result={
                "action": "merge",
                "replacement_facts": [
                    {
                        "key": "user.relationship.taras",
                        "value": (
                            "Taras is both a close friend and an active "
                            "technical stakeholder."
                        ),
                        "category": "user_fact",
                    },
                ],
                "new_facts": [],
            },
            now="2026-08-12T10:00:00Z",
        )

        self.assertTrue(change["valid"])
        self.assertTrue(change["changed"])
        self.assertEqual(change["action"], "merge")
        self.assertEqual(change["replacement_fact_ids"], ["F3"])
        self.assertEqual(change["removed_fact_ids"], ["F1", "F2"])
        self.assertEqual(next_store["deleted_fact_ids"], ["F1", "F2"])
        self.assertEqual(
            [fact["id"] for fact in next_store["facts"]],
            ["F3"],
        )
        self.assertEqual(
            next_store["facts"][0]["source_fact_ids"],
            ["F1", "F2"],
        )

    def test_delayed_report_anchor_stays_visible_with_report_suffix(self):
        context = RuntimeContext(
            websocket=None,
            emitter=None,
            logger=None,
            clients={},
        )
        context.runtime_long_term_memory_store = normalize_l4_store({
            "facts": [
                {
                    "id": "F1",
                    "key": "user.name",
                    "value": "Sergey",
                },
                {
                    "id": "F2",
                    "key": "social.friend",
                    "value": "Taras is a personal friend.",
                },
            ],
        })
        context.delayed_memory_reports = {
            "abc123": {
                "title": "Social context",
                "anchor_fact_ids": ["F1"],
                "facts_ids": ["F1", "F2"],
            },
        }

        context_block = build_runtime_l4_memory_context(
            context=context
        )

        self.assertIn(
            "user.name: Sergey [ id: F1 ] [ significance: 0.000 ] "
            "[ delayed_memory_id: abc123 ]",
            context_block,
        )
        self.assertNotIn("social.friend", context_block)
        self.assertEqual(
            context.runtime_l4_archived_fact_ids,
            {"F2"},
        )

    def test_loaded_delayed_report_fact_ids_are_visible_with_report_suffix(self):
        context = RuntimeContext(
            websocket=None,
            emitter=None,
            logger=None,
            clients={},
        )
        context.runtime_long_term_memory_store = normalize_l4_store({
            "facts": [
                {
                    "id": "F1",
                    "key": "user.name",
                    "value": "Sergey",
                },
                {
                    "id": "F2",
                    "key": "social.friend",
                    "value": "Taras is a personal friend.",
                },
            ],
        })
        context.delayed_memory_reports = {
            "abc123": {
                "title": "Social context",
                "anchor_fact_ids": [
                    "F1",
                ],
                "facts_ids": [
                    "F1",
                    "F2",
                ],
            },
        }
        context.runtime_loaded_delayed_memory = {
            "abc123": {
                **context.delayed_memory_reports["abc123"],
                "id": "abc123",
            },
        }

        context_block = build_runtime_l4_memory_context(
            context=context
        )

        self.assertIn(
            "user.name: Sergey [ id: F1 ] [ significance: 0.000 ] "
            "[ delayed_memory_id: abc123 ]",
            context_block,
        )
        self.assertIn(
            "social.friend: Taras is a personal friend. [ id: F2 ] "
            "[ significance: 0.000 ] [ delayed_memory_id: abc123 ]",
            context_block,
        )
        self.assertEqual(
            context.runtime_l4_archived_fact_ids,
            set(),
        )

    def test_anchor_visibility_wins_over_absorbed_reference_in_other_report(self):
        context = RuntimeContext(
            websocket=None,
            emitter=None,
            logger=None,
            clients={},
        )
        context.runtime_long_term_memory_store = normalize_l4_store({
            "facts": [
                {
                    "id": "F1",
                    "key": "user.name",
                    "value": "Sergey",
                },
            ],
        })
        context.delayed_memory_reports = {
            "abc123": {
                "title": "Identity",
                "anchor_fact_ids": ["F1"],
                "facts_ids": ["F1"],
            },
            "def456": {
                "title": "Social",
                "facts_ids": ["F1"],
            },
        }

        context_block = build_runtime_l4_memory_context(context=context)

        self.assertIn("user.name: Sergey [ id: F1 ]", context_block)
        self.assertIn("[ delayed_memory_id: abc123 ]", context_block)
        self.assertEqual(context.runtime_l4_archived_fact_ids, set())

    async def test_delete_l4_fact_cleans_delayed_memory_fact_arrays(self):
        context = RuntimeContext(
            websocket=None,
            emitter=FakeEmitter(),
            logger=None,
            clients={},
        )
        context.runtime_long_term_memory_store = normalize_l4_store({
            "facts": [
                {
                    "id": "F1",
                    "key": "user.name",
                    "value": "Sergey",
                },
                {
                    "id": "F2",
                    "key": "social.friend",
                    "value": "Taras",
                },
            ],
        })
        context.delayed_memory_reports = {
            "abc123": {
                "title": "Social context",
                "anchor_fact_ids": ["F1"],
                "facts_ids": ["F1", "F2"],
            },
        }
        context.delayed_memory_file_store_enabled = False

        self.assertTrue(await delete_l4_memory_fact(context, "F1"))
        self.assertEqual(
            context.delayed_memory_reports["abc123"]["anchor_fact_ids"],
            [],
        )
        self.assertEqual(
            context.delayed_memory_reports["abc123"]["facts_ids"],
            ["F2"],
        )

        self.assertTrue(await delete_l4_memory_fact(context, "F2"))
        self.assertEqual(
            context.delayed_memory_reports["abc123"]["facts_ids"],
            [],
        )
        self.assertNotIn(
            "absorbed_fact_ids",
            context.delayed_memory_reports["abc123"],
        )
        self.assertNotIn(
            "long_term_facts_ids",
            context.delayed_memory_reports["abc123"],
        )
        self.assertGreaterEqual(
            sum(
                1
                for event in context.emitter.events
                if event.get("type") == "delayed_memory_store_snapshot"
            ),
            2,
        )

    async def test_delete_l4_fact_logs_report_refs_for_restore(self):
        logger = CaptureMemoryLogger()
        context = RuntimeContext(
            websocket=None,
            emitter=FakeEmitter(),
            logger=logger,
            clients={},
        )
        context.runtime_long_term_memory_store = normalize_l4_store({
            "facts": [{
                "id": "F1",
                "key": "project.restore.test",
                "value": "Restore the report links.",
            }],
        })
        context.delayed_memory_reports = {
            "abc123": {
                "title": "Primary report",
                "anchor_fact_ids": ["F1"],
                "facts_ids": ["F1"],
            },
            "def456": {
                "title": "Related report",
                "facts_ids": ["F1"],
            },
            "ghi789": {
                "title": "Unrelated report",
                "facts_ids": [],
            },
        }
        context.delayed_memory_file_store_enabled = False

        self.assertTrue(await delete_l4_memory_fact(context, "F1"))

        deleted_fact = logger.logs[0]["deleted_fact"]
        restore_meta = deleted_fact["_restore_meta"]
        self.assertEqual(
            restore_meta["delayed_memory_report_refs"],
            [
                {
                    "report_id": "abc123",
                    "anchor_fact_ids": ["F1"],
                    "facts_ids": ["F1"],
                },
                {
                    "report_id": "def456",
                    "anchor_fact_ids": [],
                    "facts_ids": ["F1"],
                },
            ],
        )
        self.assertEqual(
            json.loads(logger.logs[0]["details"])["fact"]["_restore_meta"],
            restore_meta,
        )

    async def test_restore_l4_fact_restores_delayed_memory_report_refs(self):
        logger = CaptureMemoryLogger()
        emitter = FakeEmitter()
        context = RuntimeContext(
            websocket=None,
            emitter=emitter,
            logger=logger,
            clients={},
        )
        context.runtime_long_term_memory_store = normalize_l4_store({
            "facts": [
                {
                    "id": "F1",
                    "key": "project.restore.test",
                    "value": "Restore the report links.",
                },
                {
                    "id": "F2",
                    "key": "project.restore.keep",
                    "value": "Keep this report link.",
                },
            ],
        })
        context.delayed_memory_reports = {
            "abc123": {
                "title": "Primary report",
                "anchor_fact_ids": ["F1"],
                "facts_ids": ["F1", "F2"],
            },
            "def456": {
                "title": "Related report",
                "facts_ids": ["F1"],
            },
        }
        context.delayed_memory_file_store_enabled = False

        self.assertTrue(await delete_l4_memory_fact(context, "F1"))
        deleted_fact = logger.logs[0]["deleted_fact"]
        self.assertEqual(
            context.delayed_memory_reports["abc123"]["anchor_fact_ids"],
            [],
        )
        self.assertEqual(
            context.delayed_memory_reports["abc123"]["facts_ids"],
            ["F2"],
        )
        self.assertEqual(
            context.delayed_memory_reports["def456"]["facts_ids"],
            [],
        )

        self.assertTrue(await restore_l4_memory_fact(context, deleted_fact))

        self.assertEqual(
            [
                fact["id"]
                for fact in context.runtime_long_term_memory_store["facts"]
            ],
            ["F2", "F1"],
        )
        self.assertNotIn(
            "_restore_meta",
            context.runtime_long_term_memory_store["facts"][-1],
        )
        self.assertEqual(
            context.delayed_memory_reports["abc123"]["anchor_fact_ids"],
            ["F1"],
        )
        self.assertEqual(
            context.delayed_memory_reports["abc123"]["facts_ids"],
            ["F1", "F2"],
        )
        self.assertEqual(
            context.delayed_memory_reports["def456"]["facts_ids"],
            ["F1"],
        )
        self.assertTrue(any(
            event.get("type") == "delayed_memory_store_snapshot"
            for event in emitter.events
        ))
        self.assertTrue(any(
            event.get("change", {}).get("restored_ids") == ["F1"]
            and event.get("change", {}).get("delayed_memory_report_ids")
            == ["abc123", "def456"]
            for event in emitter.events
            if event.get("type") == "l4_memory_update"
        ))

    def test_delayed_report_fact_ids_hide_only_from_brain_context(self):
        context = RuntimeContext(
            websocket=None,
            emitter=None,
            logger=None,
            clients={},
        )
        context.runtime_long_term_memory_store = normalize_l4_store({
            "facts": [
                {
                    "id": "F1",
                    "key": "project.topic.details",
                    "value": "Detailed topic facts moved into a report.",
                },
                {
                    "id": "F2",
                    "key": "user.name",
                    "value": "Sergey",
                },
            ],
        })
        context.delayed_memory_reports = {
            "abc123": {
                "title": "Topic report",
                "long_term_facts_ids": [
                    "F1",
                ],
            },
        }

        context_block = build_runtime_l4_memory_context(
            context=context
        )

        self.assertNotIn(
            "project.topic.details",
            context_block,
        )
        self.assertIn(
            "user.name: Sergey [ id: F2 ]",
            context_block,
        )
        self.assertEqual(
            context.runtime_l4_archived_fact_ids,
            {
                "F1",
            },
        )
        self.assertEqual(
            len(
                context.runtime_long_term_memory_store[
                    "facts"
                ]
            ),
            2,
        )

    def test_delayed_report_fact_ids_hide_merged_source_fact_ids_only_from_context(self):
        context = RuntimeContext(
            websocket=None,
            emitter=None,
            logger=None,
            clients={},
        )
        context.runtime_long_term_memory_store = normalize_l4_store({
            "facts": [
                {
                    "id": "F1",
                    "key": "relationship.association",
                    "value": "Anya is associated with known cohabitation data.",
                    "source_fact_ids": [
                        "F9",
                    ],
                },
            ],
        })
        context.delayed_memory_reports = {
            "abc123": {
                "title": "Social context",
                "long_term_facts_ids": [
                    "F9",
                ],
            },
        }

        self.assertEqual(
            build_runtime_l4_memory_context(
                context=context,
            ),
            "",
        )
        self.assertEqual(
            len(
                context.runtime_long_term_memory_store[
                    "facts"
                ]
            ),
            1,
        )
        self.assertEqual(
            context.runtime_long_term_memory_store[
                "facts"
            ][0][
                "id"
            ],
            "F1",
        )


    async def test_saved_delayed_report_hides_linked_facts_on_next_context(self):
        context = RuntimeContext(
            websocket=None,
            emitter=FakeEmitter(),
            logger=FakeLogger(),
            clients={},
        )
        context.runtime_long_term_memory_store = normalize_l4_store({
            "facts": [
                {
                    "id": "F1",
                    "key": "project.topic.details",
                    "value": "Detailed project context.",
                },
            ],
        })
        payload = json.dumps({
            "abc123": {
                "title": "Project context",
                "summary": "Consolidated project details.",
                "tags": [
                    "project",
                ],
                "body": "Reusable project report.",
                "long_term_facts_ids": [
                    "F1",
                ],
            },
        })

        await apply_save_delayed_memory_actions(
            context,
            [
                RuntimeActionCall(
                    name="SAVE_DELAYED_MEMORY_CONTENT",
                    payload=payload,
                ),
            ],
            log_runtime=None,
            with_action_context=lambda event: event,
        )

        self.assertEqual(
            context.delayed_memory_reports[
                "abc123"
            ][
                "facts_ids"
            ],
            [
                "F1",
            ],
        )
        self.assertNotIn(
            "absorbed_fact_ids",
            context.delayed_memory_reports["abc123"],
        )
        self.assertNotIn(
            "long_term_facts_ids",
            context.delayed_memory_reports["abc123"],
        )
        self.assertEqual(
            context.runtime_l4_archived_fact_ids,
            {
                "F1",
            },
        )
        self.assertEqual(
            build_runtime_l4_memory_context(
                context=context
            ),
            "",
        )
        self.assertEqual(
            len(
                context.runtime_long_term_memory_store[
                    "facts"
                ]
            ),
            1,
        )


    def test_brain_context_always_injects_complete_long_term_memory(self):
        context = RuntimeContext(
            websocket=None,
            emitter=None,
            logger=None,
            clients={},
        )
        context.runtime_long_term_memory_store = normalize_l4_store({
            "facts": [
                {
                    "key": "user.hardware.main_gpu",
                    "value": "User's main GPU is RTX 4090.",
                },
                {
                    "key": "user.preference.response_style",
                    "value": "User prefers direct technical analysis.",
                },
            ],
        })

        prompt = build_brain_context(
            context,
            runtime_actions={},
            user_input="напиши хайку про дождь",
            include_runtime_action_instructions=False,
            include_previous_chat_messages=False,
        )

        self.assertIn("<LONG_TERM_MEMORY", prompt)
        self.assertIn("user.hardware.main_gpu:", prompt)
        self.assertIn("user.preference.response_style:", prompt)

    async def test_idle_ticks_extract_until_facts_memory_is_drained_then_merge_once(self):
        gpu_value = "User's main GPU is RTX 4090."
        language_value = "User prefers Russian replies."
        gpu_pending_id = build_l4_fact_id(sequence=1, pending=True)
        language_pending_id = build_l4_fact_id(sequence=2, pending=True)
        service_client = FakeServiceClient([
            f'''{{
              "facts": [{{
                "key": "user.hardware.main_gpu",
                "value": "{gpu_value}",
                "category": "environment",
                "source_keys": ["gpu"]
              }}]
            }}''',
            f'''{{
              "facts": [{{
                "key": "user.preference.response_language",
                "value": "{language_value}",
                "category": "user_preference",
                "source_keys": ["language"]
              }}]
            }}''',
            f'''{{
              "operations": [
                {{
                  "action": "create",
                  "pending_id": "{gpu_pending_id}",
                  "key": "user.hardware.main_gpu",
                  "value": "{gpu_value}",
                  "category": "environment"
                }},
                {{
                  "action": "create",
                  "pending_id": "{language_pending_id}",
                  "key": "user.preference.response_language",
                  "value": "{language_value}",
                  "category": "user_preference"
                }}
              ]
            }}''',
        ])
        context = RuntimeContext(
            websocket=None,
            emitter=FakeEmitter(),
            logger=FakeLogger(),
            clients={"service": service_client},
        )
        context.runtime_facts_memory_records = normalize_facts_memory_records([
            {
                "session_id": "session-a",
                "signals": {
                    "gpu": {
                        "content": "RTX 4090",
                        "runtime_snapshot_id": "runtime-a",
                    },
                },
            },
        ])

        first = await maybe_update_runtime_l4_memory(
            context=context,
            user_idle_seconds=61,
        )
        self.assertEqual(first["phase"], "extract")
        self.assertEqual(len(context.runtime_long_term_memory_store["pending_facts"]), 1)
        self.assertEqual(context.runtime_long_term_memory_store["facts"], [])

        context.runtime_facts_memory_records = normalize_facts_memory_records([
            {
                "session_id": "session-a",
                "signals": {
                    "gpu": {
                        "content": "RTX 4090",
                        "runtime_snapshot_id": "runtime-a",
                        "l4_status": "analyzed",
                    },
                    "language": {
                        "content": "Russian replies",
                        "runtime_snapshot_id": "runtime-b",
                    },
                },
            },
        ])

        second = await maybe_update_runtime_l4_memory(
            context=context,
            user_idle_seconds=61,
        )
        self.assertEqual(second["phase"], "extract")
        self.assertEqual(len(context.runtime_long_term_memory_store["pending_facts"]), 2)
        self.assertEqual(context.runtime_long_term_memory_store["facts"], [])

        third = await maybe_update_runtime_l4_memory(
            context=context,
            user_idle_seconds=61,
        )
        self.assertEqual(third["phase"], "merge")
        self.assertEqual(context.runtime_long_term_memory_store["pending_facts"], [])
        self.assertEqual(len(context.runtime_long_term_memory_store["facts"]), 2)
        self.assertEqual(len(service_client.calls), 3)
        self.assertIn("cross-session long-term memory", service_client.calls[0]["system_prompt"])
        self.assertIn("consolidate pending candidates", service_client.calls[2]["system_prompt"].lower())

    def test_restore_l4_fact_preserves_deleted_fact_object(self):
        fact = normalize_l4_store({
            "facts": [{
                "id": "F1",
                "key": "project.restore.test",
                "value": "Restore the complete fact.",
                "category": "project",
                "mention_count": 3,
                "source_session_ids": ["session-a"],
            }],
        })["facts"][0]

        restored_store, changed = restore_l4_fact_to_store(
            {"facts": []},
            fact,
            now="2026-08-05T10:00:00Z",
        )

        self.assertTrue(changed)
        self.assertEqual(restored_store["facts"], [fact])
        self.assertEqual(restored_store["revision"], 1)

    async def test_delete_logs_complete_fact_and_restore_adds_it_back(self):
        logger = CaptureMemoryLogger()
        emitter = FakeEmitter()
        context = RuntimeContext(
            websocket=None,
            emitter=emitter,
            logger=logger,
            clients={},
        )
        context.runtime_long_term_memory_store = normalize_l4_store({
            "facts": [{
                "id": "F1",
                "key": "project.restore.test",
                "value": "Restore the complete fact.",
                "category": "project",
                "mention_count": 3,
                "source_session_ids": ["session-a"],
            }],
        })
        deleted_fact = dict(
            context.runtime_long_term_memory_store["facts"][0]
        )

        deleted = await delete_l4_memory_fact(
            context,
            deleted_fact["id"],
        )

        self.assertTrue(deleted)
        self.assertEqual(context.runtime_long_term_memory_store["facts"], [])
        self.assertEqual(
            context.runtime_long_term_memory_store["deleted_fact_ids"],
            [deleted_fact["id"]],
        )
        self.assertEqual(logger.logs[0]["event"], "fact_deleted")
        self.assertEqual(logger.logs[0]["tag_suffix"], "DELETED")
        self.assertEqual(logger.logs[0]["deleted_fact"], deleted_fact)
        self.assertEqual(
            json.loads(logger.logs[0]["details"])["fact"],
            deleted_fact,
        )

        restored = await restore_l4_memory_fact(
            context,
            deleted_fact,
        )

        self.assertTrue(restored)
        self.assertEqual(
            context.runtime_long_term_memory_store["facts"],
            [deleted_fact],
        )
        self.assertEqual(
            context.runtime_long_term_memory_store["deleted_fact_ids"],
            [],
        )
        self.assertEqual(
            emitter.events[-1]["change"]["restored_ids"],
            [deleted_fact["id"]],
        )


if __name__ == "__main__":
    unittest.main()
