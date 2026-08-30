import asyncio
import json
import unittest

from contracts.rules_assembler import (
    RUNTIME_ACTION_UPDATE_LT_FACTS,
    build_runtime_action_contract_instructions,
    runtime_action_emits_followup,
)
from runtime.LT_memory_utils import normalize_lt_store
from runtime.runtime_context import RuntimeContext
from tests.helpers.memory import FakeLogger, FakeServiceClient
from utils.actions import RuntimeActionCall, extract_runtime_actions
from utils.actions.dispatcher import apply_runtime_action_calls


class FakeEmitter:

    def __init__(self):
        self.events = []

    async def emit(self, payload):
        self.events.append(payload)


class RuntimeUpdateLTFactsTests(unittest.IsolatedAsyncioTestCase):

    def test_marker_parses_focused_note_and_has_no_followup(self):
        result = extract_runtime_actions(
            (
                "Memory clarified.\n"
                "<UPDATE_LT_FACTS>\n"
                "Merge F1 and F2 into one durable fact: both describe the same residence.\n"
                "</UPDATE_LT_FACTS>"
            ),
            enabled_actions=(RUNTIME_ACTION_UPDATE_LT_FACTS,),
        )

        self.assertEqual(result.text, "Memory clarified.")
        self.assertEqual(len(result.actions), 1)
        self.assertEqual(result.actions[0].name, RUNTIME_ACTION_UPDATE_LT_FACTS)
        self.assertEqual(
            json.loads(result.actions[0].payload),
            {
                "fact_ids": ["F1", "F2"],
                "message": (
                    "Merge F1 and F2 into one durable fact: both describe "
                    "the same residence."
                ),
            },
        )
        self.assertFalse(
            runtime_action_emits_followup(RUNTIME_ACTION_UPDATE_LT_FACTS)
        )

        instructions = build_runtime_action_contract_instructions(
            RUNTIME_ACTION_UPDATE_LT_FACTS
        )
        self.assertIn("ask one brief natural question", instructions)
        self.assertIn("harmless repetition", instructions)
        self.assertIn("plain English text", instructions)
        self.assertIn("update, merge, or create", instructions)
        self.assertNotIn("delete", instructions.casefold())

    def test_marker_accepts_create_note_without_fact_ids(self):
        result = extract_runtime_actions(
            (
                "Memory clarified.\n"
                "<UPDATE_LT_FACTS>\n"
                "Create a new durable fact: the user prefers Russian replies.\n"
                "</UPDATE_LT_FACTS>"
            ),
            enabled_actions=(RUNTIME_ACTION_UPDATE_LT_FACTS,),
        )

        self.assertEqual(result.text, "Memory clarified.")
        self.assertEqual(len(result.actions), 1)
        self.assertEqual(
            json.loads(result.actions[0].payload),
            {
                "fact_ids": [],
                "message": (
                    "Create a new durable fact: the user prefers Russian "
                    "replies."
                ),
            },
        )

    def test_marker_rejects_destructive_plain_text_note(self):
        result = extract_runtime_actions(
            (
                "before\n"
                "<UPDATE_LT_FACTS>\n"
                "Delete F1 from long-term memory.\n"
                "</UPDATE_LT_FACTS>\n"
                "after"
            ),
            enabled_actions=(RUNTIME_ACTION_UPDATE_LT_FACTS,),
        )

        self.assertEqual(result.text, "before\nafter")
        self.assertEqual(result.actions, ())

    def test_marker_allows_removing_content_from_existing_fact(self):
        result = extract_runtime_actions(
            (
                "<UPDATE_LT_FACTS>\n"
                "Update F305: Remove white bonfire with cutout from the "
                "description. Keep coffee, bong, and bricks.\n"
                "</UPDATE_LT_FACTS>"
            ),
            enabled_actions=(RUNTIME_ACTION_UPDATE_LT_FACTS,),
        )

        self.assertEqual(len(result.actions), 1)
        payload = json.loads(result.actions[0].payload)
        self.assertEqual(payload["fact_ids"], ["F305"])
        self.assertIn("Remove white bonfire", payload["message"])

    def test_invalid_note_marker_is_removed_without_action(self):
        result = extract_runtime_actions(
            (
                "before\n"
                "<UPDATE_LT_FACTS>\n"
                '{"fact_ids":["F1"],"message":""}\n'
                "</UPDATE_LT_FACTS>\n"
                "after"
            ),
            enabled_actions=(RUNTIME_ACTION_UPDATE_LT_FACTS,),
        )

        self.assertEqual(result.text, "before\nafter")
        self.assertEqual(result.actions, ())

    async def test_runtime_action_updates_lt_in_background(self):
        emitter = FakeEmitter()
        logger = FakeLogger()
        service_client = FakeServiceClient(json.dumps({
            "action": "replace",
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
        }))
        context = RuntimeContext(
            websocket=None,
            emitter=emitter,
            logger=logger,
            clients={"service": service_client},
        )
        context.runtime_lt_file_store_enabled = False
        context.delayed_memory_file_store_enabled = False
        context.runtime_long_term_memory_store = normalize_lt_store({
            "facts": [
                {
                    "id": "F1",
                    "key": "user.social_connections",
                    "value": "Taras is a close friend.",
                    "category": "user_fact",
                },
                {
                    "id": "F2",
                    "key": "user.stakeholder_profile",
                    "value": "Taras is a key technical stakeholder.",
                    "category": "project_fact",
                },
            ],
        })
        context.delayed_memory_reports = {
            "abc123": {
                "title": "Social and project context",
                "long_term_facts_ids": [
                    "F1",
                    "F2",
                ],
            },
        }
        action = RuntimeActionCall(
            name=RUNTIME_ACTION_UPDATE_LT_FACTS,
            payload=json.dumps({
                "fact_ids": ["F1", "F2"],
                "message": (
                    "Taras is both a close friend and an active technical "
                    "stakeholder."
                ),
            }),
        )

        applied = await apply_runtime_action_calls(
            context,
            (action,),
            action_display_ids={id(action): "update_lt_facts_001"},
        )

        self.assertEqual(applied, 1)
        tasks = list(getattr(context, "background_tasks", set()))
        self.assertEqual(len(tasks), 1)
        await asyncio.gather(*tasks)

        facts = context.runtime_long_term_memory_store["facts"]
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["id"], "F3")
        self.assertEqual(facts[0]["key"], "user.relationship.taras")
        self.assertIn("close friend", facts[0]["value"])
        self.assertEqual(facts[0]["source_fact_ids"], ["F1", "F2"])
        self.assertEqual(
            context.runtime_long_term_memory_store["deleted_fact_ids"],
            ["F1", "F2"],
        )

        self.assertEqual(
            context.delayed_memory_reports["abc123"]["facts_ids"],
            ["F3"],
        )
        self.assertNotIn(
            "absorbed_fact_ids",
            context.delayed_memory_reports["abc123"],
        )
        self.assertNotIn(
            "long_term_facts_ids",
            context.delayed_memory_reports["abc123"],
        )

        lifecycle = [
            event
            for event in emitter.events
            if event.get("type") == "runtime_action"
            and event.get("action") == "update_lt_facts"
        ]
        self.assertTrue(any(event.get("status") == "completed" for event in lifecycle))
        completed_event = next(
            event
            for event in lifecycle
            if event.get("status") == "completed"
        )
        self.assertEqual(completed_event.get("text"), "UPDATE_LT_FACTS")
        self.assertTrue(any(
            event.get("lt_result", {}).get("change", {}).get("action") == "merge"
            for event in lifecycle
        ))
        self.assertFalse(
            any(event.get("status") == "failed" for event in lifecycle)
        )

    async def test_runtime_action_does_not_wait_for_cancelled_idle_lt_task(self):
        emitter = FakeEmitter()
        logger = FakeLogger()
        context = RuntimeContext(
            websocket=None,
            emitter=emitter,
            logger=logger,
            clients={},
        )
        release_idle = asyncio.Event()
        note_started = asyncio.Event()

        async def stubborn_idle_task():
            try:
                await release_idle.wait()
            except asyncio.CancelledError:
                # Simulate a provider request that takes time to unwind after
                # local cancellation. Foreground L-T must not wait for it.
                await release_idle.wait()

        async def fake_run_lt_jin_note(*, context, note):
            del context, note
            note_started.set()
            return {
                "phase": "jin_note",
                "status": "completed",
                "changed": False,
                "change": {},
            }

        idle_task = asyncio.create_task(stubborn_idle_task())
        context.runtime_lt_memory_update_task = idle_task
        context.runtime_lt_memory_update_kind = "idle"
        action = RuntimeActionCall(
            name=RUNTIME_ACTION_UPDATE_LT_FACTS,
            payload=json.dumps({
                "fact_ids": ["F1"],
                "message": "Update F1: keep the clarified wording.",
            }),
        )

        try:
            from unittest.mock import patch

            with patch(
                "utils.actions.update_lt_facts_actions.run_lt_jin_note",
                new=fake_run_lt_jin_note,
            ):
                applied = await apply_runtime_action_calls(
                    context,
                    (action,),
                    action_display_ids={id(action): "update_lt_facts_001"},
                )

                self.assertEqual(applied, 1)
                await asyncio.wait_for(note_started.wait(), timeout=0.2)
                tasks = list(getattr(context, "background_tasks", set()))
                await asyncio.wait_for(asyncio.gather(*tasks), timeout=0.2)
        finally:
            release_idle.set()
            await asyncio.gather(idle_task, return_exceptions=True)

    async def test_runtime_action_can_create_lt_without_selected_facts(self):
        emitter = FakeEmitter()
        logger = FakeLogger()
        service_client = FakeServiceClient(json.dumps({
            "action": "create",
            "replacement_facts": [],
            "new_facts": [
                {
                    "key": "user.preference.response_language",
                    "value": "The user prefers Russian replies.",
                    "category": "user_preference",
                },
            ],
        }))
        context = RuntimeContext(
            websocket=None,
            emitter=emitter,
            logger=logger,
            clients={"service": service_client},
        )
        context.runtime_lt_file_store_enabled = False
        context.delayed_memory_file_store_enabled = False
        context.runtime_long_term_memory_store = normalize_lt_store({"facts": []})
        action = RuntimeActionCall(
            name=RUNTIME_ACTION_UPDATE_LT_FACTS,
            payload=json.dumps({
                "fact_ids": [],
                "message": "Create a new durable fact: the user prefers Russian replies.",
            }),
        )

        applied = await apply_runtime_action_calls(
            context,
            (action,),
            action_display_ids={id(action): "update_lt_facts_001"},
        )

        self.assertEqual(applied, 1)
        tasks = list(getattr(context, "background_tasks", set()))
        self.assertEqual(len(tasks), 1)
        await asyncio.gather(*tasks)

        facts = context.runtime_long_term_memory_store["facts"]
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["key"], "user.preference.response_language")
        self.assertEqual(facts[0]["value"], "The user prefers Russian replies.")

        lifecycle = [
            event
            for event in emitter.events
            if event.get("type") == "runtime_action"
            and event.get("action") == "update_lt_facts"
        ]
        self.assertTrue(any(
            event.get("status") == "completed"
            and "1 new fact" in event.get("detail", "")
            for event in lifecycle
        ))

    async def test_runtime_action_can_update_and_create_in_one_explicit_note(self):
        emitter = FakeEmitter()
        logger = FakeLogger()
        service_client = FakeServiceClient(json.dumps({
            "action": "update",
            "replacement_facts": [
                {
                    "key": "project_fact.jin_architecture",
                    "value": (
                        "Gemma 26B A4B is the current active brain and "
                        "Qwen 3.8 27B is the night brain model."
                    ),
                    "category": "project_fact",
                },
            ],
            "new_facts": [
                {
                    "key": "project_fact.model_test_goal",
                    "value": "The current goal is to test Qwen 3.6 27B.",
                    "category": "project_fact",
                },
            ],
        }))
        context = RuntimeContext(
            websocket=None,
            emitter=emitter,
            logger=logger,
            clients={"service": service_client},
        )
        context.runtime_lt_file_store_enabled = False
        context.delayed_memory_file_store_enabled = False
        context.runtime_long_term_memory_store = normalize_lt_store({
            "facts": [
                {
                    "id": "F96",
                    "key": "project_fact.jin_architecture",
                    "value": "Qwen 3.8 27B is the current active brain.",
                    "category": "project_fact",
                },
            ],
        })
        action = RuntimeActionCall(
            name=RUNTIME_ACTION_UPDATE_LT_FACTS,
            payload=json.dumps({
                "fact_ids": ["F96"],
                "message": (
                    "Update F96: Gemma 26B A4B is the current active brain, "
                    "and Qwen 3.8 27B is the night brain model. Create a new "
                    "fact: the current developmental goal is to test Qwen "
                    "3.6 27B."
                ),
            }),
        )

        applied = await apply_runtime_action_calls(
            context,
            (action,),
            action_display_ids={id(action): "update_lt_facts_001"},
        )

        self.assertEqual(applied, 1)
        tasks = list(getattr(context, "background_tasks", set()))
        self.assertEqual(len(tasks), 1)
        await asyncio.gather(*tasks)

        facts = context.runtime_long_term_memory_store["facts"]
        self.assertEqual([fact["id"] for fact in facts], ["F96", "F97"])
        self.assertIn("current active brain", facts[0]["value"])
        self.assertEqual(facts[1]["key"], "project_fact.model_test_goal")

        lifecycle = [
            event
            for event in emitter.events
            if event.get("type") == "runtime_action"
            and event.get("action") == "update_lt_facts"
        ]
        self.assertTrue(any(event.get("status") == "completed" for event in lifecycle))
        self.assertFalse(any(event.get("status") == "failed" for event in lifecycle))


if __name__ == "__main__":
    unittest.main()
