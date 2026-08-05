import asyncio
import json
import tempfile
import unittest

from runtime.L4_memory import (
    apply_l4_memory_store_sync,
    build_runtime_l4_memory_context,
    delete_l4_memory_fact,
    ensure_runtime_l4_state,
    maybe_update_runtime_l4_memory,
    restore_l4_memory_fact,
    runtime_l4_memory_update_running,
)
from runtime.L4_memory_utils import (
    add_l4_pending_candidates,
    apply_l4_merge_operations,
    build_l4_fact_id,
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
                    "id": "l4_gpu",
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

    def test_file_store_fallback_survives_empty_browser_sync(self):
        with tempfile.TemporaryDirectory() as directory:
            persisted_store = normalize_l4_store({
                "revision": 4,
                "facts": [
                    {
                        "id": "l4_saved",
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
                        "id": "l4_secret",
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
                "l4_secret",
            )
            self.assertTrue(deleted)

            persisted_after_delete, warnings = load_long_term_facts_store(
                root=directory,
            )
            self.assertEqual(warnings, [])
            self.assertEqual(persisted_after_delete["facts"], [])
            self.assertEqual(
                persisted_after_delete["deleted_fact_ids"],
                ["l4_secret"],
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
                ["l4_secret"],
            )

    def test_store_snapshot_merge_keeps_one_fact_per_key_with_sources(self):
        merged, change = merge_l4_store_snapshots(
            {
                "revision": 4,
                "facts": [
                    {
                        "id": "l4_existing",
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
                        "id": "l4_incoming",
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
        self.assertEqual(len(merged["facts"]), 1)
        self.assertEqual(
            merged["facts"][0]["value"],
            "Anya is associated with newer relationship context.",
        )
        self.assertEqual(
            merged["facts"][0]["source_session_ids"],
            ["session-a", "session-b"],
        )
        self.assertEqual(
            merged["facts"][0]["source_fact_ids"],
            ["l4_incoming"],
        )

    def test_store_normalization_prunes_processed_pending_fact(self):
        processed_pending_id = "l4p_fd9b07b15788"
        waiting_pending_id = "l4p_waiting"

        store = normalize_l4_store(
            {
                "facts": [
                    {
                        "id": "l4_32df84cf695d",
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
        processed_pending_id = "l4p_fd9b07b15788"

        merged, change = merge_l4_store_snapshots(
            {
                "revision": 94,
                "updated_at": "2026-08-04T17:34:05Z",
                "facts": [
                    {
                        "id": "l4_32df84cf695d",
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

    def test_merge_applies_complete_batch_atomically(self):
        existing = normalize_l4_store({
            "facts": [
                {
                    "id": "l4_gpu",
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
                    "target_id": "l4_gpu",
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
        self.assertEqual(merged["facts"][0]["id"], "l4_gpu")
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
        self.assertEqual(update_detail["target_id"], "l4_gpu")
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

    def test_merge_reinforce_tracks_pending_fact_source_id(self):
        existing = normalize_l4_store({
            "facts": [
                {
                    "id": "l4_language",
                    "key": "user.preference.response_language",
                    "value": "The user prefers Russian replies.",
                    "category": "user_preference",
                    "source_fact_ids": ["l4_legacy_source"],
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
                    "source_fact_ids": ["l4_imported_source"],
                },
            ],
            now="2026-08-02T12:00:00Z",
        )
        pending = store["pending_facts"][0]
        operations = normalize_l4_merge_operations({
            "operations": [
                {
                    "action": "reinforce",
                    "pending_id": pending["id"],
                    "target_id": "l4_language",
                },
            ],
        })

        merged, change = apply_l4_merge_operations(
            store,
            operations,
            now="2026-08-02T12:01:00Z",
        )

        self.assertTrue(change["valid"])
        self.assertEqual(change["reinforced_ids"], ["l4_language"])
        self.assertEqual(len(change["operation_details"]), 1)
        reinforce_detail = change["operation_details"][0]
        self.assertEqual(reinforce_detail["action"], "reinforce")
        self.assertEqual(reinforce_detail["pending_id"], pending["id"])
        self.assertEqual(reinforce_detail["target_id"], "l4_language")
        self.assertEqual(
            reinforce_detail["pending_fact"]["value"],
            "The user prefers Russian replies.",
        )
        self.assertEqual(
            reinforce_detail["target_before"]["value"],
            "The user prefers Russian replies.",
        )
        self.assertEqual(
            reinforce_detail["target_after"]["mention_count"],
            2,
        )
        detail_text = format_l4_merge_operation_details(change)
        self.assertIn("REINFORCE", detail_text)
        self.assertIn("confirmation: user.preference.response_language", detail_text)
        self.assertIn("existing:     user.preference.response_language", detail_text)
        self.assertEqual(
            merged["facts"][0]["source_fact_ids"],
            [
                "l4_legacy_source",
                "l4_imported_source",
                pending["id"],
            ],
        )

    async def test_merge_phase_logs_concrete_operation_details(self):
        existing = normalize_l4_store({
            "facts": [
                {
                    "id": "l4_gpu",
                    "key": "user.hardware.main_gpu",
                    "value": "User's main GPU is RTX 3080 Ti.",
                    "category": "environment",
                },
                {
                    "id": "l4_language",
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
              "target_id": "l4_gpu",
              "key": "user.hardware.main_gpu",
              "value": "User's main GPU is RTX 4090.",
              "category": "environment"
            }},
            {{
              "action": "reinforce",
              "pending_id": "{language_pending["id"]}",
              "target_id": "l4_language"
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
        self.assertIn("REINFORCE", detail_text)
        self.assertIn("confirmation: user.preference.response_language", detail_text)
        self.assertIn("existing:     user.preference.response_language", detail_text)

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
                    "id": "l4_gpu",
                    "key": "user.hardware.main_gpu",
                    "value": "User's main GPU is RTX 4090.",
                    "category": "environment",
                    "source_session_ids": ["session-a"],
                },
                {
                    "id": "l4_style",
                    "key": "user.preference.response_style",
                    "value": "User prefers direct technical analysis.",
                },
            ],
        })

        context_block = format_long_term_memory_context(store["facts"])
        ui_line = format_l4_fact_line(store["facts"][0], include_metadata=True)

        self.assertIn("user.hardware.main_gpu:", context_block)
        self.assertIn("user.preference.response_style:", context_block)
        self.assertIn("[ id: l4_gpu ]", context_block)
        self.assertIn("[ id: l4_style ]", context_block)
        self.assertNotIn("source_session_ids", context_block)
        self.assertIn("[source_session_ids: session-a]", ui_line)

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
                    "id": "l4_archived",
                    "key": "project.topic.details",
                    "value": "Detailed topic facts moved into a report.",
                },
                {
                    "id": "l4_active",
                    "key": "user.name",
                    "value": "Sergey",
                },
            ],
        })
        context.delayed_memory_reports = {
            "abc123": {
                "title": "Topic report",
                "long_term_facts_ids": [
                    "l4_archived",
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
            "user.name: Sergey [ id: l4_active ]",
            context_block,
        )
        self.assertEqual(
            context.runtime_l4_archived_fact_ids,
            {
                "l4_archived",
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
                    "id": "l4_current",
                    "key": "relationship.association",
                    "value": "Anya is associated with known cohabitation data.",
                    "source_fact_ids": [
                        "l4_archived_source",
                    ],
                },
            ],
        })
        context.delayed_memory_reports = {
            "abc123": {
                "title": "Social context",
                "long_term_facts_ids": [
                    "l4_archived_source",
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
            "l4_current",
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
                    "id": "l4_project_details",
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
                    "l4_project_details",
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
                "long_term_facts_ids"
            ],
            [
                "l4_project_details",
            ],
        )
        self.assertEqual(
            context.runtime_l4_archived_fact_ids,
            {
                "l4_project_details",
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
        gpu_pending_id = build_l4_fact_id(
            key="user.hardware.main_gpu",
            value=gpu_value,
            pending=True,
        )
        language_pending_id = build_l4_fact_id(
            key="user.preference.response_language",
            value=language_value,
            pending=True,
        )
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
                "id": "l4_restore_me",
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
                "id": "l4_restore_me",
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
