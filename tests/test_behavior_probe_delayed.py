"""
Simple behavior probe for JIN multi-step dialogue tests.

Goal:
- Keep the test easy to copy/rename.
- Edit only constants near the top for most scenarios.
- No semantic marker heuristics.
- If EXPECTED_TEXT_ANSWER_N contains fragments, they are searched in model answer N.
- If EXPECTED_TEXT_MEMORY_N contains fragments, they are searched in memory after turn N.
- If UNEXPECTED_TEXT_ANSWER_N contains fragments, they must NOT appear in model answer N.
- If UNEXPECTED_TEXT_MEMORY_N contains fragments, they must NOT appear in memory after turn N.
- If a list is empty, that part accepts any output.

Run:
  npm run behavior_probe_tests
or:
  JIN_RUN_BEHAVIOR_PROBE=1 python -m unittest tests.test_behavior_probe_delayed -v
"""

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.prob_helpers import (  # noqa: E402
    install_behavior_probe,
    TurnResult,
    RuntimeContext,
    RuntimeEmitter,
    WebSocketLogger,
)


# =============================================================================
# EDIT THIS BLOCK FIRST
# =============================================================================

SCENARIO_ID = "delayed_memory_save_after_reminder"
SCENARIO_TITLE = "Save delayed memory content after reminder request"
SCENARIO_NOTES = """
Two-step probe:
1. The user asks JIN to remind them to drink coffee in 10 minutes.
   Any answer is accepted, but JIN must emit save_active_memory.
2. The user asks JIN to save the report.
   Any answer is accepted, but JIN must emit save_delayed_memory.
"""

# Add more turns by appending:
#   USER_TEXT_3 = "..."
#   EXPECTED_TEXT_ANSWER_3 = ["optional answer fragment"]
#   EXPECTED_TEXT_MEMORY_3 = ["optional memory fragment"]
#   EXPECTED_RUNTIME_ACTION_3 = ["optional expected runtime action"]
#   UNEXPECTED_TEXT_ANSWER_3 = ["optional forbidden answer fragment"]
#   UNEXPECTED_TEXT_MEMORY_3 = ["optional forbidden memory fragment"]
#   UNEXPECTED_RUNTIME_ACTION_3 = ["optional forbidden runtime action"]
#
# Empty lists mean: accept any text for this part.

USER_TEXT_1 = "напомни мне через 10 минут выпить кофе"
EXPECTED_TEXT_ANSWER_1 = []
EXPECTED_TEXT_MEMORY_1 = []
EXPECTED_RUNTIME_ACTION_1 = ["save_active_memory"]
UNEXPECTED_TEXT_ANSWER_1 = []
UNEXPECTED_TEXT_MEMORY_1 = []
UNEXPECTED_RUNTIME_ACTION_1 = []

USER_TEXT_2 = "сохрани отчёт о текущей беседе в delayed memory"
EXPECTED_TEXT_ANSWER_2 = []
EXPECTED_TEXT_MEMORY_2 = []
EXPECTED_RUNTIME_ACTION_2 = ["save_delayed_memory"]
UNEXPECTED_TEXT_ANSWER_2 = []
UNEXPECTED_TEXT_MEMORY_2 = []
UNEXPECTED_RUNTIME_ACTION_2 = []


# =============================================================================
# PROBE SETTINGS / HELPERS
# =============================================================================

PROBE = install_behavior_probe(globals(), memory_fields=['runtime_memory', 'runtime_l2_memory', 'active_memory_records', 'delayed_memory_reports'])


# =============================================================================
# LOCAL SHAPE TESTS. These always run and do not require the model.
# =============================================================================


class BehaviorProbeShapeTests(unittest.TestCase):
    def test_collect_dialogue_steps_finds_delayed_memory_steps(self):
        steps = collect_dialogue_steps()
        self.assertEqual(len(steps), 2)

        self.assertEqual(steps[0]["user_text"], USER_TEXT_1)
        self.assertEqual(steps[0]["expected_answer"], [])
        self.assertEqual(steps[0]["expected_memory"], [])
        self.assertEqual(steps[0]["expected_runtime_actions"], ["save_active_memory"])
        self.assertEqual(steps[0]["unexpected_runtime_actions"], [])

        self.assertEqual(steps[1]["user_text"], USER_TEXT_2)
        self.assertEqual(steps[1]["expected_answer"], [])
        self.assertEqual(steps[1]["expected_memory"], [])
        self.assertEqual(steps[1]["expected_runtime_actions"], ["save_delayed_memory"])
        self.assertEqual(steps[1]["unexpected_runtime_actions"], [])

    def test_evaluator_checks_declared_runtime_actions(self):
        turns = [
            TurnResult(
                index=1,
                user_text=USER_TEXT_1,
                answer="Поставлено напоминание. Через 10 минут я напомню выпить кофе.",
                memory_after_turn="active_memory_1: Reminder to drink coffee in 10 minutes",
                expected_answer=[],
                expected_memory=[],
                unexpected_answer=[],
                unexpected_memory=[],
                expected_runtime_actions=["save_active_memory"],
                unexpected_runtime_actions=[],
                runtime_actions=[
                    {
                        "name": "save_active_memory",
                        "payload": "Reminder to drink coffee in 10 minutes",
                    },
                ],
            ),
            TurnResult(
                index=2,
                user_text=USER_TEXT_2,
                answer="Сохранила отчёт.",
                memory_after_turn="delayed_memory_reports: coffee reminder report",
                expected_answer=[],
                expected_memory=[],
                unexpected_answer=[],
                unexpected_memory=[],
                expected_runtime_actions=["save_delayed_memory"],
                unexpected_runtime_actions=[],
                runtime_actions=[
                    {
                        "name": "save_delayed_memory",
                        "payload": "coffee reminder report",
                    },
                ],
            ),
        ]

        score = evaluate_expected_text(turns)
        self.assertEqual(score["passed"], score["total"])

    def test_evaluator_fails_when_second_turn_misses_delayed_save_action(self):
        turns = [
            TurnResult(
                index=2,
                user_text=USER_TEXT_2,
                answer="Сохранила.",
                memory_after_turn="",
                expected_answer=[],
                expected_memory=[],
                unexpected_answer=[],
                unexpected_memory=[],
                expected_runtime_actions=["save_delayed_memory"],
                unexpected_runtime_actions=[],
                runtime_actions=[],
            ),
        ]

        score = evaluate_expected_text(turns)

        self.assertEqual(score["passed"], 0)
        self.assertEqual(score["total"], 1)
        self.assertEqual(score["checks"][0]["name"], "turn_2.runtime_action_contains")

    def test_collect_runtime_actions_reads_websocket_save_active_memory_action(self):
        websocket = CapturingWebSocket()
        context = RuntimeContext(
            websocket=websocket,
            emitter=RuntimeEmitter(websocket),
            logger=WebSocketLogger(websocket),
            clients={},
        )
        websocket_messages = [
            {"type": "message_chunk", "chunk": "ignored"},
            {
                "type": "runtime_action",
                "action": "save_active_memory",
                "text": "SAVE_ACTIVE_MEMORY: Reminder to drink coffee in 10 minutes",
                "active_memory": "active_memory_1: Reminder to drink coffee in 10 minutes",
            },
        ]

        actions = collect_runtime_actions_after_offsets(
            context,
            context_event_offset=0,
            websocket_message_offset=0,
            websocket_messages=websocket_messages,
        )

        self.assertTrue(runtime_action_found(actions, "save_active_memory"))

    def test_collect_runtime_actions_reads_websocket_delayed_memory_action(self):
        websocket = CapturingWebSocket()
        context = RuntimeContext(
            websocket=websocket,
            emitter=RuntimeEmitter(websocket),
            logger=WebSocketLogger(websocket),
            clients={},
        )
        websocket_messages = [
            {"type": "message_chunk", "chunk": "ignored"},
            {
                "type": "runtime_action",
                "action": "save_delayed_memory",
                "status": "completed",
                "text": "Saving delayed memory",
                "delayed_memory_report": {
                    "coffee_reminder_report": {
                        "title": "Coffee Reminder Report",
                        "summary": "Reminder to drink coffee in 10 minutes.",
                    },
                },
            },
        ]

        actions = collect_runtime_actions_after_offsets(
            context,
            context_event_offset=0,
            websocket_message_offset=0,
            websocket_messages=websocket_messages,
        )

        self.assertTrue(runtime_action_found(actions, "save_delayed_memory"))
        self.assertIn("delayed_memory_report", actions[0])
        self.assertIn("coffee_reminder_report", actions[0]["payload"])

    def test_collect_runtime_actions_dedupes_context_and_websocket_views(self):
        websocket = CapturingWebSocket()
        context = RuntimeContext(
            websocket=websocket,
            emitter=RuntimeEmitter(websocket),
            logger=WebSocketLogger(websocket),
            clients={},
        )
        context.runtime_action_events.append(
            {
                "name": "save_active_memory",
                "payload": "Reminder to drink coffee in 10 minutes",
            }
        )
        websocket_messages = [
            {
                "type": "runtime_action",
                "action": "save_active_memory",
                "text": "SAVE_ACTIVE_MEMORY: Reminder to drink coffee in 10 minutes",
                "active_memory": "active_memory_1: Reminder to drink coffee in 10 minutes",
            },
        ]

        actions = collect_runtime_actions_after_offsets(
            context,
            context_event_offset=0,
            websocket_message_offset=0,
            websocket_messages=websocket_messages,
        )

        self.assertEqual(len(actions), 1)
        self.assertTrue(runtime_action_found(actions, "save_active_memory"))
        self.assertIn(
            "active_memory",
            actions[0],
        )


    def test_memory_field_check_does_not_match_field_name_inside_value(self):
        self.assertFalse(
            memory_fragment_found(
                "last_jin_response: save_delayed_memory was discussed as plain text.",
                "save_delayed_memory:",
            )
        )

    def test_memory_field_check_matches_delayed_memory_line_key(self):
        self.assertTrue(
            memory_fragment_found(
                "last_jin_response: ok\nsave_delayed_memory: Coffee reminder report saved.",
                "save_delayed_memory:",
            )
        )


# =============================================================================
# LIVE MODEL BEHAVIOR PROBE. Skipped unless explicitly enabled.
# =============================================================================


SimpleBehaviorProbe = PROBE.make_live_probe_test_case("test_simple_behavior_probe")

if __name__ == "__main__":
    unittest.main()

