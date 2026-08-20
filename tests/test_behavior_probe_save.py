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

from tests.prob_helpers import BehaviorProbeHelpers, TurnResult  # noqa: E402


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
   and emit resolve_active_memory to resolve it.
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
EXPECTED_RUNTIME_ACTION_4 = ["resolve_active_memory"]
UNEXPECTED_TEXT_ANSWER_4 = []
UNEXPECTED_TEXT_MEMORY_4 = []


# =============================================================================
# TEST / REPORT SETTINGS
# =============================================================================

RUN_MEMORY_UPDATE_AFTER_EACH_TURN = True
WAIT_FOR_MEMORY_UPDATE_AFTER_EACH_TURN = True

# If False, failed expected fragments are shown in red but do not fail the test.
# Keep False for heatmap/probe mode. Set True when this becomes a regression test.
STRICT_TEXT_ASSERTIONS = True

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
        self.assertEqual(steps[3]["expected_runtime_actions"], ["resolve_active_memory"])
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
                expected_runtime_actions=["resolve_active_memory"],
                runtime_actions=[
                    {"name": "resolve_active_memory", "payload": "abc123"}
                ],
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
            action_event_offset = len(getattr(self.context, "runtime_action_events", []))
            state = await run_standard_turn(self.context, step["user_text"])
            answer = (
                state.brain_response
                or state.brain_response
                or self.context.runtime_turn_assistant_response
                or ""
            )
            runtime_actions = list(
                getattr(self.context, "runtime_action_events", [])[action_event_offset:]
            )
            await hydrate_active_memory_records_from_runtime_actions(
                self.context,
                runtime_actions,
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
                    expected_runtime_actions=step["expected_runtime_actions"],
                    expected_runtime_action_payload=step["expected_runtime_action_payload"],
                    runtime_actions=runtime_actions,
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
                    "expected_runtime_actions": turn.expected_runtime_actions,
                    "expected_runtime_action_payload": turn.expected_runtime_action_payload,
                    "unexpected_answer": turn.unexpected_answer,
                    "unexpected_memory": turn.unexpected_memory,
                    "runtime_actions": turn.runtime_actions,
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

