import asyncio
import json
import unittest

from contracts.rules_assembler import (
    RUNTIME_ACTION_UPDATE_L4_FACTS,
    build_runtime_action_contract_instructions,
    runtime_action_emits_followup,
)
from runtime.L4_memory_utils import normalize_l4_store
from runtime.runtime_context import RuntimeContext
from tests.helpers.memory import FakeLogger, FakeServiceClient
from utils.actions import RuntimeActionCall, extract_runtime_actions
from utils.actions.dispatcher import apply_runtime_action_calls


class FakeEmitter:

    def __init__(self):
        self.events = []

    async def emit(self, payload):
        self.events.append(payload)


class RuntimeUpdateL4FactsTests(unittest.IsolatedAsyncioTestCase):

    def test_marker_parses_focused_note_and_has_no_followup(self):
        result = extract_runtime_actions(
            (
                "Memory clarified.\n"
                "<UPDATE_L4_FACTS>\n"
                '{"fact_ids":["F1","F2"],'
                '"message":"Both facts describe the same residence."}\n'
                "</UPDATE_L4_FACTS>"
            ),
            enabled_actions=(RUNTIME_ACTION_UPDATE_L4_FACTS,),
        )

        self.assertEqual(result.text, "Memory clarified.")
        self.assertEqual(len(result.actions), 1)
        self.assertEqual(result.actions[0].name, RUNTIME_ACTION_UPDATE_L4_FACTS)
        self.assertEqual(
            json.loads(result.actions[0].payload),
            {
                "fact_ids": ["F1", "F2"],
                "message": "Both facts describe the same residence.",
            },
        )
        self.assertFalse(
            runtime_action_emits_followup(RUNTIME_ACTION_UPDATE_L4_FACTS)
        )

        instructions = build_runtime_action_contract_instructions(
            RUNTIME_ACTION_UPDATE_L4_FACTS
        )
        self.assertIn("ask one brief natural question", instructions)
        self.assertIn("harmless repetition", instructions)
        self.assertIn("L4 decides how to maintain its own facts", instructions)

    def test_invalid_note_marker_is_removed_without_action(self):
        result = extract_runtime_actions(
            (
                "before\n"
                "<UPDATE_L4_FACTS>\n"
                '{"fact_ids":[],"message":"missing scope"}\n'
                "</UPDATE_L4_FACTS>\n"
                "after"
            ),
            enabled_actions=(RUNTIME_ACTION_UPDATE_L4_FACTS,),
        )

        self.assertEqual(result.text, "before\nafter")
        self.assertEqual(result.actions, ())

    async def test_runtime_action_updates_l4_in_background(self):
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
        context.runtime_l4_file_store_enabled = False
        context.delayed_memory_file_store_enabled = False
        context.runtime_long_term_memory_store = normalize_l4_store({
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
            name=RUNTIME_ACTION_UPDATE_L4_FACTS,
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
            action_display_ids={id(action): "update_l4_facts_001"},
        )

        self.assertEqual(applied, 1)
        tasks = list(getattr(context, "background_tasks", set()))
        self.assertEqual(len(tasks), 1)
        await asyncio.gather(*tasks)

        facts = context.runtime_long_term_memory_store["facts"]
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["key"], "user.relationship.taras")
        self.assertIn("close friend", facts[0]["value"])
        self.assertNotIn("F1", [fact["id"] for fact in facts])
        self.assertNotIn("F2", [fact["id"] for fact in facts])

        replacement_id = facts[0]["id"]
        self.assertEqual(
            context.delayed_memory_reports["abc123"]["long_term_facts_ids"],
            [replacement_id],
        )

        lifecycle = [
            event
            for event in emitter.events
            if event.get("type") == "runtime_action"
            and event.get("action") == "update_l4_facts"
        ]
        self.assertTrue(any(event.get("status") == "completed" for event in lifecycle))
        self.assertFalse(
            any(event.get("status") == "failed" for event in lifecycle)
        )


if __name__ == "__main__":
    unittest.main()
