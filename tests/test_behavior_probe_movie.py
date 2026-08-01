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

from tests.prob_helpers import BehaviorProbeHelpers, TurnResult  # noqa: E402


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
# TEST / REPORT SETTINGS
# =============================================================================

RUN_MEMORY_UPDATE_AFTER_EACH_TURN = True
WAIT_FOR_MEMORY_UPDATE_AFTER_EACH_TURN = True

# If False, failed expected fragments are shown in red but do not fail the test.
# Keep False for heatmap/probe mode. Set True when this becomes a regression test.
STRICT_TEXT_ASSERTIONS = False

PRINT_PRETTY_REPORT = sys.stdout.isatty()
PRINT_JSON_REPORT = False
PRINT_WEBSOCKET_MESSAGES = False
LIVE_STREAM_MODEL_OUTPUT = sys.stdout.isatty()
LIVE_PRINT_TURN_RESULTS = sys.stdout.isatty()

USE_ANSI_COLORS = True
MAX_ANSWER_PREVIEW_CHARS = 1400
MAX_MEMORY_PREVIEW_CHARS = 2200

# Which memory fields should be displayed and searched.
MEMORY_TEXT_FIELDS_TO_INSPECT = [
    "runtime_memory",
    "runtime_l2_memory",
]


# =============================================================================
# PROBE HELPERS
# =============================================================================

PROBE = BehaviorProbeHelpers(globals())
CapturingWebSocket = PROBE.capturing_websocket_class()
paint = PROBE.paint
render_text = PROBE.render_text
normalize_text = PROBE.normalize_text
expected_fragments = PROBE.expected_fragments
fragment_found = PROBE.fragment_found
memory_fragment_found = PROBE.memory_fragment_found
clip_text = PROBE.clip_text
indent_block = PROBE.indent_block
status_label = PROBE.status_label
collect_dialogue_steps = PROBE.collect_dialogue_steps
print_live_turn_result = PROBE.print_live_turn_result
run_standard_turn = PROBE.run_standard_turn
build_memory_blob = PROBE.build_memory_blob
render_runtime_actions = PROBE.render_runtime_actions
normalize_runtime_action_name = PROBE.normalize_runtime_action_name
runtime_action_found = PROBE.runtime_action_found
runtime_action_payload_contains_fragment = PROBE.runtime_action_payload_contains_fragment
normalize_websocket_runtime_action = PROBE.normalize_websocket_runtime_action
collect_runtime_actions_after_offsets = PROBE.collect_runtime_actions_after_offsets
hydrate_active_memory_records_from_runtime_actions = PROBE.hydrate_active_memory_records_from_runtime_actions
active_memory_line_contains_fragment = PROBE.active_memory_line_contains_fragment
check_description = PROBE.check_description
evaluate_expected_text = PROBE.evaluate_expected_text
print_behavior_probe_report = PROBE.print_behavior_probe_report
answer_has_recall_question = PROBE.answer_has_recall_question
evaluate_recall_word_behavior = PROBE.evaluate_recall_word_behavior
find_trailing_balanced_suffix_start = PROBE.find_trailing_balanced_suffix_start
find_trailing_balanced_parenthetical_start = PROBE.find_trailing_balanced_parenthetical_start
split_memory_contract_value_and_suffixes = PROBE.split_memory_contract_value_and_suffixes
split_active_memory_value_and_suffixes = PROBE.split_active_memory_value_and_suffixes
extract_suffix_field = PROBE.extract_suffix_field
summarize_contract_progress = PROBE.summarize_contract_progress
extract_active_memory_entries = PROBE.extract_active_memory_entries
render_active_memory_entries = PROBE.render_active_memory_entries
collect_active_memory_entries_from_context = PROBE.collect_active_memory_entries_from_context
collect_snapshot_active_memory_entries = PROBE.collect_snapshot_active_memory_entries
format_active_memory_debug = PROBE.format_active_memory_debug


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


@unittest.skipUnless(
    os.getenv("JIN_RUN_BEHAVIOR_PROBE", "") == "1",
    "Set JIN_RUN_BEHAVIOR_PROBE=1 to run the live behavior probe.",
)
class SimpleBehaviorProbe(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.http_client, self.websocket, self.context = PROBE.create_test_context()

    async def asyncTearDown(self):
        await PROBE.async_tear_down(self)

    async def test_simple_behavior_probe(self):
        turns: list[TurnResult] = []

        for step in collect_dialogue_steps():
            state = await run_standard_turn(self.context, step["user_text"])
            answer = (
                state.final_answer
                or state.brain_response
                or self.context.runtime_turn_assistant_response
                or ""
            )
            memory_after_turn = build_memory_blob(self.context)

            turns.append(
                TurnResult(
                    index=step["index"],
                    user_text=step["user_text"],
                    answer=answer,
                    memory_after_turn=memory_after_turn,
                    expected_answer=step["expected_answer"],
                    expected_memory=step["expected_memory"],
                    unexpected_answer=step["unexpected_answer"],
                    unexpected_memory=step["unexpected_memory"],
                )
            )
            print_live_turn_result(turns[-1])

        score = evaluate_expected_text(turns)

        report = {
            "scenario_id": SCENARIO_ID,
            "scenario_title": SCENARIO_TITLE,
            "scenario_notes": SCENARIO_NOTES,
            "score": score,
            "turns": [
                {
                    "index": turn.index,
                    "user_text": turn.user_text,
                    "answer": turn.answer,
                    "memory_after_turn": turn.memory_after_turn,
                    "expected_answer": turn.expected_answer,
                    "expected_memory": turn.expected_memory,
                    "unexpected_answer": turn.unexpected_answer,
                    "unexpected_memory": turn.unexpected_memory,
                }
                for turn in turns
            ],
            "final_memory": build_memory_blob(self.context),
            "turn_number": self.context.turn_number,
            "user_message_count": self.context.user_message_count,
            "assistant_message_count": self.context.assistant_message_count,
            "websocket_message_count": len(self.websocket.messages),
        }

        if PRINT_WEBSOCKET_MESSAGES:
            report["websocket_messages"] = self.websocket.messages

        if PRINT_PRETTY_REPORT:
            print_behavior_probe_report(report)

        if PRINT_JSON_REPORT:
            print(json.dumps(report, ensure_ascii=False, indent=2))

        if STRICT_TEXT_ASSERTIONS:
            failed = [check for check in score["checks"] if not check["passed"]]
            self.assertEqual(failed, [], f"Expected text checks failed: {failed}")


if __name__ == "__main__":
    unittest.main()

