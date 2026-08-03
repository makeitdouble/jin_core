import json
import unittest

from runtime.L4_memory import (
    build_runtime_l4_memory_context,
    maybe_update_runtime_l4_memory,
)
from runtime.L4_memory_utils import (
    add_l4_pending_candidates,
    apply_l4_merge_operations,
    build_l4_fact_id,
    collect_pending_facts_memory_fields,
    extract_l4_json_payload,
    format_l4_fact_line,
    format_long_term_memory_context,
    mark_facts_memory_fields_analyzed,
    normalize_facts_memory_records,
    normalize_l4_candidates,
    normalize_l4_merge_operations,
    normalize_l4_store,
)
from runtime.runtime_context import RuntimeContext
from rules.brain_context_builder import build_brain_context
from tests.helpers.memory import FakeLogger, FakeServiceClient
from utils.actions import RuntimeActionCall
from utils.actions.delayed_memory_actions import (
    apply_save_delayed_memory_actions,
)


class FakeEmitter:

    def __init__(self):
        self.events = []

    async def emit(self, payload):
        self.events.append(payload)


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
                        "confidence": 0.9,
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
                    "confidence": 0.95,
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
        self.assertEqual(change["ignored_pending_ids"], [task_pending["id"]])

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
                "confidence": 0.95,
                "source_keys": ["gpu"]
              }}]
            }}''',
            f'''{{
              "facts": [{{
                "key": "user.preference.response_language",
                "value": "{language_value}",
                "category": "user_preference",
                "confidence": 0.9,
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
                  "category": "environment",
                  "confidence": 0.95
                }},
                {{
                  "action": "create",
                  "pending_id": "{language_pending_id}",
                  "key": "user.preference.response_language",
                  "value": "{language_value}",
                  "category": "user_preference",
                  "confidence": 0.9
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


if __name__ == "__main__":
    unittest.main()
