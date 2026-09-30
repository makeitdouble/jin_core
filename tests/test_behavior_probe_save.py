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
  JIN_RUN_BEHAVIOR_PROBE=1 python tests/test_behavior_probe_save.py -v
"""

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.prob_helpers import install_behavior_probe, TurnResult  # noqa: E402


# =============================================================================
# EDIT THIS BLOCK FIRST
# =============================================================================

SCENARIO_ID = "save_word_active_memory"
SCENARIO_TITLE = "Save word into active memory"
SCENARIO_NOTES = """
Four-step probe:
1. The user greets JIN. Any answer is accepted.
2. The user asks JIN to remember the word "кукушка". Any answer is accepted,
   but JIN must emit save_active_memory runtime action whose payload
   includes that word.
3. The user says thanks. Any answer is accepted.
4. The user asks JIN to forget the word and resolve the task. Any answer is
   accepted, but JIN must see the active-memory record created from turn 2
   and emit delete_active_memory to delete it.
"""

# Add more turns by appending:
#   USER_TEXT_3 = "..."
#   EXPECTED_TEXT_ANSWER_3 = ["optional answer fragment"]
#   EXPECTED_TEXT_MEMORY_3 = ["optional memory fragment"]
#   UNEXPECTED_TEXT_ANSWER_3 = ["optional forbidden answer fragment"]
#   UNEXPECTED_TEXT_MEMORY_3 = ["optional forbidden memory fragment"]
#
# Empty lists mean: accept any text for this part.

WORD_TO_SAVE = "кукушка"

USER_TEXT_1 = "привет"
EXPECTED_TEXT_ANSWER_1 = []
EXPECTED_TEXT_MEMORY_1 = []
UNEXPECTED_TEXT_ANSWER_1 = []
UNEXPECTED_TEXT_MEMORY_1 = []

USER_TEXT_2 = f'запомни слово "{WORD_TO_SAVE}"'
EXPECTED_TEXT_ANSWER_2 = []
EXPECTED_TEXT_MEMORY_2 = []
EXPECTED_RUNTIME_ACTION_2 = ["save_active_memory"]
EXPECTED_RUNTIME_ACTION_PAYLOAD_2 = [WORD_TO_SAVE]
UNEXPECTED_TEXT_ANSWER_2 = []
UNEXPECTED_TEXT_MEMORY_2 = []

USER_TEXT_3 = "спасибо"
EXPECTED_TEXT_ANSWER_3 = []
EXPECTED_TEXT_MEMORY_3 = []
UNEXPECTED_TEXT_ANSWER_3 = []
UNEXPECTED_TEXT_MEMORY_3 = []

USER_TEXT_4 = f'теперь забудь слово "{WORD_TO_SAVE}" и зарезолви active memory'
EXPECTED_TEXT_ANSWER_4 = []
EXPECTED_TEXT_MEMORY_4 = []
EXPECTED_RUNTIME_ACTION_4 = ["delete_active_memory"]
UNEXPECTED_TEXT_ANSWER_4 = []
UNEXPECTED_TEXT_MEMORY_4 = []


# =============================================================================
# PROBE SETTINGS / HELPERS
# =============================================================================

PROBE = install_behavior_probe(globals(), memory_fields=['runtime_memory'])


# =============================================================================
# LOCAL SHAPE TESTS. These always run and do not require the model.
# =============================================================================


class BehaviorProbeShapeTests(unittest.TestCase):
    def test_collect_dialogue_steps_finds_save_word_steps(self):
        steps = collect_dialogue_steps()
        self.assertEqual(len(steps), 4)

        self.assertEqual(steps[0]["user_text"], "привет")
        self.assertEqual(steps[0]["expected_answer"], [])
        self.assertEqual(steps[0]["expected_memory"], [])

        self.assertIn(WORD_TO_SAVE, steps[1]["user_text"])
        self.assertEqual(steps[1]["expected_answer"], [])
        self.assertEqual(steps[1]["expected_memory"], [])
        self.assertEqual(steps[1]["expected_runtime_actions"], ["save_active_memory"])
        self.assertEqual(steps[1]["expected_runtime_action_payload"], [WORD_TO_SAVE])

        self.assertEqual(steps[2]["user_text"], "спасибо")
        self.assertEqual(steps[2]["expected_answer"], [])
        self.assertEqual(steps[2]["expected_memory"], [])
        self.assertEqual(steps[2]["unexpected_memory"], [])

        self.assertIn(WORD_TO_SAVE, steps[3]["user_text"])
        self.assertEqual(steps[3]["expected_answer"], [])
        self.assertEqual(steps[3]["expected_memory"], [])
        self.assertEqual(steps[3]["expected_runtime_actions"], ["delete_active_memory"])
        self.assertEqual(steps[3]["unexpected_memory"], [])

    def test_evaluator_checks_word_inside_active_memory_line(self):
        turns = [
            TurnResult(
                index=1,
                user_text=USER_TEXT_1,
                answer="Привет!",
                memory_after_turn="",
                expected_answer=[],
                expected_memory=[],
                unexpected_answer=[],
                unexpected_memory=[],
            ),
            TurnResult(
                index=2,
                user_text=USER_TEXT_2,
                answer="Запомнил.",
                memory_after_turn=(
                    f"active_memory: запомнить слово {WORD_TO_SAVE} "
                    "[ id: abc123 ] [ status: pending ]"
                ),
                expected_answer=[],
                expected_memory=["active_memory", WORD_TO_SAVE],
                unexpected_answer=[],
                unexpected_memory=[],
                expected_runtime_actions=["save_active_memory"],
                expected_runtime_action_payload=[WORD_TO_SAVE],
                runtime_actions=[
                    {"name": "save_active_memory", "payload": f"remember {WORD_TO_SAVE}"}
                ],
            ),
            TurnResult(
                index=4,
                user_text=USER_TEXT_4,
                answer="Память очищена.",
                memory_after_turn="session_status: active",
                expected_answer=[],
                expected_memory=[],
                unexpected_answer=[],
                unexpected_memory=["active_memory"],
                expected_runtime_actions=["delete_active_memory"],
                runtime_actions=[
                    {"name": "delete_active_memory", "payload": "abc123"}
                ],
            ),
        ]

        score = evaluate_expected_text(turns)
        self.assertEqual(score["passed"], score["total"])


# =============================================================================
# LIVE MODEL BEHAVIOR PROBE. Skipped unless explicitly enabled.
# =============================================================================


SimpleBehaviorProbe = PROBE.make_live_probe_test_case("test_simple_behavior_probe")

if __name__ == "__main__":
    unittest.main()

