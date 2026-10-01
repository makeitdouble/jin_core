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
  JIN_RUN_BEHAVIOR_PROBE=1 python -m unittest tests.test_behavior_probe_movie_closure_simple -v
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

SCENARIO_ID = "ascii_house_swamp_continuation"
SCENARIO_TITLE = "ASCII house and swamp continuation"
SCENARIO_NOTES = """
Simple 4-step probe: greeting flow, then the user asks JIN to draw a house.
After JIN establishes ASCII/text-art as the available drawing form, the user asks
for a swamp. Both drawing answers should contain the core visual ASCII strokes: \\, |, /.
"""

# Add more turns by appending:
#   USER_TEXT_5 = "..."
#   EXPECTED_TEXT_ANSWER_5 = ["optional answer fragment"]
#   EXPECTED_TEXT_MEMORY_5 = ["optional memory fragment"]
#   UNEXPECTED_TEXT_ANSWER_5 = ["optional forbidden answer fragment"]
#   UNEXPECTED_TEXT_MEMORY_5 = ["optional forbidden memory fragment"]
#
# Empty lists mean: accept any text for this part.

USER_TEXT_1 = "привет"
EXPECTED_TEXT_ANSWER_1 = []
EXPECTED_TEXT_MEMORY_1 = []
UNEXPECTED_TEXT_ANSWER_1 = []
UNEXPECTED_TEXT_MEMORY_1 = []

USER_TEXT_2 = "нарисуй домик"
EXPECTED_TEXT_ANSWER_2 = [
    "\\",
    "|",
    "/",
]
EXPECTED_TEXT_MEMORY_2 = []
UNEXPECTED_TEXT_ANSWER_2 = []
UNEXPECTED_TEXT_MEMORY_2 = []

USER_TEXT_3 = "а теперь болото"
EXPECTED_TEXT_ANSWER_3 = [
    "\\",
    "|",
    "/",
]
EXPECTED_TEXT_MEMORY_3 = []
UNEXPECTED_TEXT_ANSWER_3 = []
UNEXPECTED_TEXT_MEMORY_3 = []


# =============================================================================
# PROBE SETTINGS / HELPERS
# =============================================================================

PROBE = install_behavior_probe(globals(), memory_fields=['runtime_memory', 'runtime_l2_memory'])


# =============================================================================
# LOCAL SHAPE TESTS. These always run and do not require the model.
# =============================================================================


class BehaviorProbeShapeTests(unittest.TestCase):
    def test_collect_dialogue_steps_finds_seed_steps(self):
        steps = collect_dialogue_steps()
        self.assertEqual(len(steps), 3)
        self.assertIn("привет", steps[0]["user_text"])
        self.assertIn("нарисуй домик", steps[1]["user_text"])
        self.assertIn("болото", steps[2]["user_text"])

        for step in steps[2:]:
            self.assertEqual(step["expected_answer"], ["\\", "|", "/"])

    def test_evaluator_uses_only_declared_expected_fragments(self):
        turns = [
            TurnResult(
                index=1,
                user_text="привет",
                answer="Привет.",
                memory_after_turn="greeting received",
                expected_answer=[],
                expected_memory=[],
                unexpected_answer=[],
                unexpected_memory=[],
            ),
            TurnResult(
                index=2,
                user_text="привет",
                answer="Привет ещё раз.",
                memory_after_turn="repeated greeting received",
                expected_answer=[],
                expected_memory=[],
                unexpected_answer=[],
                unexpected_memory=[],
            ),
            TurnResult(
                index=3,
                user_text="нарисуй домик",
                answer="Вот тебе домик:\n /\\\n/  \\\n| [] |",
                memory_after_turn="user asked for ASCII house drawing",
                expected_answer=["\\", "|", "/"],
                expected_memory=[],
                unexpected_answer=[],
                unexpected_memory=[],
            ),
            TurnResult(
                index=4,
                user_text="а теперь болото",
                answer="Вот болото:\n /\\\n~~~~ | ~~~~ /",
                memory_after_turn="user continued ASCII drawing scene with swamp",
                expected_answer=["\\", "|", "/"],
                expected_memory=[],
                unexpected_answer=[],
                unexpected_memory=[],
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

