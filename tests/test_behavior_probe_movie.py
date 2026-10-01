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

SCENARIO_ID = "movie_recommendation_closure"
SCENARIO_TITLE = "Niche movie recommendation graceful closure"
SCENARIO_NOTES = """
Simple 3-step probe: the user asks for an unusual movie, gives a taste marker,
then closes the topic and says High Life is the active viewing target.
"""

# Add more turns by appending:
#   USER_TEXT_4 = "..."
#   EXPECTED_TEXT_ANSWER_4 = ["optional answer fragment"]
#   EXPECTED_TEXT_MEMORY_4 = ["optional memory fragment"]
#   UNEXPECTED_TEXT_ANSWER_4 = ["optional forbidden answer fragment"]
#   UNEXPECTED_TEXT_MEMORY_4 = ["optional forbidden memory fragment"]
#
# Empty lists mean: accept any text for this part.

USER_TEXT_1 = "посоветуй необычный фильм, но не то что у всех на слуху, удиви меня"
EXPECTED_TEXT_ANSWER_1 = []
EXPECTED_TEXT_MEMORY_1 = []
UNEXPECTED_TEXT_ANSWER_1 = [
    "?",
]
UNEXPECTED_TEXT_MEMORY_1 = []

USER_TEXT_2 = "шикарная рекомендация, спасибо. мне ещё понравился с Паттинсоном фильм The Rover"
EXPECTED_TEXT_ANSWER_2 = []
EXPECTED_TEXT_MEMORY_2 = [
    "The Rover",
]
UNEXPECTED_TEXT_ANSWER_2 = []
UNEXPECTED_TEXT_MEMORY_2 = []

USER_TEXT_3 = "The Lighthouse я уже смотрел. я думаю можно дропнуть этот топик, я уже скачиваю High Life для просмотра."
EXPECTED_TEXT_ANSWER_3 = [
]
EXPECTED_TEXT_MEMORY_3 = [
    "High Life",
    "The Rover",
]
UNEXPECTED_TEXT_ANSWER_3 = [
    # Topic is explicitly closed here, so the final answer should not pull user back.
    "?",
    # These titles should stay in memory, but the final closing answer should not reopen them.
    "The Lighthouse",
    "The Rover",
]
UNEXPECTED_TEXT_MEMORY_3 = [

]


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
        self.assertGreaterEqual(len(steps), 3)
        self.assertIn("необычный фильм", steps[0]["user_text"])
        self.assertIn("High Life", steps[-1]["user_text"])

    def test_evaluator_uses_only_declared_expected_fragments(self):
        turns = [
            TurnResult(
                index=1,
                user_text="u1",
                answer="any answer",
                memory_after_turn="any memory",
                expected_answer=[],
                expected_memory=[],
                unexpected_answer=[],
                unexpected_memory=[],
            ),
            TurnResult(
                index=2,
                user_text="u2",
                answer="model mentioned The Rover",
                memory_after_turn="memory preserved The Rover",
                expected_answer=[],
                expected_memory=["The Rover"],
                unexpected_answer=[],
                unexpected_memory=[],
            ),
            TurnResult(
                index=3,
                user_text="u3",
                answer="Enjoy High Life.",
                memory_after_turn="High Life and The Lighthouse are present.",
                expected_answer=["High Life"],
                expected_memory=["High Life", "The Lighthouse"],
                unexpected_answer=["wrong title"],
                unexpected_memory=["user loves arthouse"],
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

