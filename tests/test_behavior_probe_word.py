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
- The dynamically extracted recall word from turn 1 must not be revealed again
  in later answers.
- If a list is empty, that part accepts any output.

Run:
  npm run behavior_probe_tests
or:
  JIN_RUN_BEHAVIOR_PROBE=1 python -m unittest tests.test_behavior_probe_recall_word -v
"""

from __future__ import annotations

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

SCENARIO_ID = "recall_word_surprise_window"
SCENARIO_TITLE = "Recall word surprise window"
SCENARIO_NOTES = """
Five-step probe for the recall-word contract.
Turn 1 gives JIN a fixed word from WORD_TO_REMEMBER, then asks JIN to ask for
it back at any self-selected moment within the next three user turns. The probe
checks that WORD_TO_REMEMBER appears in runtime memory after turn 1 and does not
appear in later answers, while a recall question appears during the recall
window.
"""

# Add more turns by appending:
#   USER_TEXT_5 = "..."
#   EXPECTED_TEXT_ANSWER_5 = ["optional answer fragment"]
#   EXPECTED_TEXT_MEMORY_5 = ["optional memory fragment"]
#   UNEXPECTED_TEXT_ANSWER_5 = ["optional forbidden answer fragment"]
#   UNEXPECTED_TEXT_MEMORY_5 = ["optional forbidden memory fragment"]
#
# Empty lists mean: accept any text for this part.

WORD_TO_REMEMBER = "Кофе"

USER_TEXT_1 = (
    "Сыграем в тест памяти.\n"
    f"Запомни слово - {WORD_TO_REMEMBER}\n"
    "После этого в одном случайном из следующих 3 своих сообщений "
    "один раз напомни мне угадать это слово.\n"
    "Само слово больше не называй.\n"
    "Пиши только просьбу угадать загаданное слово.\n"
    "Не выбирай новое слово позже.\n"
    "Твоя задача не напоминать мне в каждом сообщении, а выбрать один случайный момент.\n"
)
EXPECTED_TEXT_ANSWER_1 = []
EXPECTED_TEXT_MEMORY_1 = []
EXPECTED_RUNTIME_ACTION_1 = ["save_active_memory"]
UNEXPECTED_TEXT_ANSWER_1 = []
UNEXPECTED_TEXT_MEMORY_1 = []

USER_TEXT_2 = "теперь нарисуй домик"
EXPECTED_TEXT_ANSWER_2 = []
EXPECTED_TEXT_MEMORY_2 = []
UNEXPECTED_TEXT_ANSWER_2 = []
UNEXPECTED_TEXT_MEMORY_2 = []

USER_TEXT_3 = "расскажи хайку про лягушку"
EXPECTED_TEXT_ANSWER_3 = []
EXPECTED_TEXT_MEMORY_3 = []
UNEXPECTED_TEXT_ANSWER_3 = []
UNEXPECTED_TEXT_MEMORY_3 = []

USER_TEXT_4 = "спасибо"
EXPECTED_TEXT_ANSWER_4 = []
EXPECTED_TEXT_MEMORY_4 = []
UNEXPECTED_TEXT_ANSWER_4 = []
UNEXPECTED_TEXT_MEMORY_4 = []

USER_TEXT_5 = "у тебя хорошо получается"
EXPECTED_TEXT_ANSWER_5 = []
EXPECTED_TEXT_MEMORY_5 = []
UNEXPECTED_TEXT_ANSWER_5 = []
UNEXPECTED_TEXT_MEMORY_5 = []


# =============================================================================
# PROBE SETTINGS / HELPERS
# =============================================================================

PROBE = install_behavior_probe(
    globals(),
    memory_fields=["runtime_memory", "runtime_l2_memory", "active_memory_records"],
    print_active_memory_debug=True,
    context_active_memory_debug_fields=[
        "runtime_memory",
        "runtime_l2_memory",
        "runtime_memory_snapshots",
        "runtime_memory_snapshot_index",
        "pending_brain_usage",
        "runtime_usage_events",
        "active_memory_records",
    ],
)


# =============================================================================
# LOCAL SHAPE TESTS. These always run and do not require the model.
# =============================================================================


class BehaviorProbeShapeTests(unittest.TestCase):
    def test_collect_dialogue_steps_finds_seed_steps(self):
        steps = collect_dialogue_steps()
        self.assertEqual(len(steps), 5)
        self.assertIn("Сыграем в тест памяти", steps[0]["user_text"])
        self.assertIn(f"Запомни слово - {WORD_TO_REMEMBER}", steps[0]["user_text"])
        self.assertIn("напомни мне угадать это слово", steps[0]["user_text"])
        self.assertEqual(steps[0]["expected_memory"], [])
        self.assertEqual(steps[0]["expected_runtime_actions"], ["save_active_memory"])
        self.assertIn("нарисуй домик", steps[1]["user_text"])
        self.assertIn("хайку", steps[2]["user_text"])
        self.assertIn("спасибо", steps[3]["user_text"])
        self.assertIn("хорошо", steps[4]["user_text"])


    def test_collect_runtime_actions_reads_websocket_runtime_action(self):
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
                "text": "SAVE_ACTIVE_MEMORY: запомнить слово Кофе для последующего теста памяти.",
            },
        ]

        actions = collect_runtime_actions_after_offsets(
            context,
            context_event_offset=0,
            websocket_message_offset=0,
            websocket_messages=websocket_messages,
        )

        self.assertTrue(runtime_action_found(actions, "save_active_memory"))
        self.assertTrue(fragment_found(render_runtime_actions(actions), WORD_TO_REMEMBER))

    def test_extract_active_memory_entries_splits_value_and_suffixes(self):
        blob = '[runtime_memory]\nactive_memory: облако (purpose: recall challenge; turns_left: 2; status: pending)'
        entries = extract_active_memory_entries(blob, source="unit")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["key"], "active_memory")
        self.assertEqual(entries[0]["value"], "облако")
        self.assertEqual(entries[0]["suffixes"], "(purpose: recall challenge; turns_left: 2; status: pending)")

    def test_extract_active_memory_entries_keeps_nested_conditions_suffix(self):
        blob = (
            '[runtime_memory]\n'
            'active_memory: облако '
            '(purpose: recall challenge; conditions: do not say secret word, '
            'remind one time (reminded: 0); status: pending)'
        )
        entries = extract_active_memory_entries(blob, source="unit")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["key"], "active_memory")
        self.assertEqual(entries[0]["value"], "облако")
        self.assertIn("conditions: do not say secret word", entries[0]["suffixes"])
        self.assertIn("reminded: 0", entries[0]["suffixes"])
        self.assertIn("status: pending", entries[0]["suffixes"])

    def test_answer_has_recall_question_requires_direct_recall_trigger(self):
        self.assertTrue(
            answer_has_recall_question("А теперь вопрос: какое слово я загадал?")
        )
        self.assertTrue(
            answer_has_recall_question("Вспомни слово, которое я загадал?")
        )
        self.assertTrue(
            answer_has_recall_question("Назови слово из начала игры?")
        )
        self.assertTrue(
            answer_has_recall_question("Помнишь, какое было слово?")
        )
        self.assertTrue(
            answer_has_recall_question("Помнишь, мы запоминали секретное слово? Какое оно было?")
        )
        self.assertTrue(
            answer_has_recall_question("Помнишь слово, которое мы запомнили? Как оно?")
        )
        self.assertTrue(
            answer_has_recall_question("А теперь, если ты помнишь... какой же наш секретный слово?")
        )
        self.assertTrue(
            answer_has_recall_question("Помнишь то слово, которое ты хотел(а) вспомнить?")
        )
        self.assertTrue(
            answer_has_recall_question("Кстати, а ты помнишь слово, которое мы запоминали?")
        )
        self.assertTrue(
            answer_has_recall_question("Кстати, а что же слово, которое мы сегодня запоминали? Помнишь его?")
        )
        self.assertTrue(
            answer_has_recall_question("Кстати, напомни мне, пожалуйста, то слово, которое мы запоминали?")
        )
        self.assertTrue(
            answer_has_recall_question("Не мог бы ты вспомнить то секретное слово, которое мы запоминали?")
        )
        self.assertFalse(
            answer_has_recall_question(
                f"Кстати, наше слово было {WORD_TO_REMEMBER}.",
                WORD_TO_REMEMBER,
            )
        )
        self.assertFalse(
            answer_has_recall_question("Ты хочешь, чтобы я ещё помнил слово?")
        )
        self.assertFalse(
            answer_has_recall_question("Можем вернуться к нашей игре на память, если ты помнишь слово, которое мы загадали?")
        )
        self.assertFalse(
            answer_has_recall_question("Я всё ещё помню слово, продолжим.")
        )

    def test_evaluator_tracks_word_to_remember_recall_question(self):
        turns = [
            TurnResult(
                index=1,
                user_text=USER_TEXT_1,
                answer="Saved.",
                memory_after_turn=f'recall_word_fixture: "{WORD_TO_REMEMBER}" (purpose: recall evaluator fixture; status: pending)',
                expected_answer=[],
                expected_memory=[],
                unexpected_answer=[],
                unexpected_memory=[],
            ),
            TurnResult(
                index=2,
                user_text=USER_TEXT_2,
                answer="ASCII house",
                memory_after_turn=f'recall_word_fixture: "{WORD_TO_REMEMBER}" (purpose: recall evaluator fixture; status: pending)',
                expected_answer=[],
                expected_memory=[],
                unexpected_answer=[],
                unexpected_memory=[],
            ),
            TurnResult(
                index=3,
                user_text=USER_TEXT_3,
                answer="A small haiku.",
                memory_after_turn=f'recall_word_fixture: "{WORD_TO_REMEMBER}" (purpose: recall evaluator fixture; status: pending)',
                expected_answer=[],
                expected_memory=[],
                unexpected_answer=[],
                unexpected_memory=[],
            ),
            TurnResult(
                index=4,
                user_text=USER_TEXT_4,
                answer="Пожалуйста. Помнишь то слово, которое ты хотел(а) вспомнить?",
                memory_after_turn=f'recall_word_fixture: "{WORD_TO_REMEMBER}" (purpose: recall evaluator fixture; status: pending)',
                expected_answer=[],
                expected_memory=[],
                unexpected_answer=[],
                unexpected_memory=[],
            ),
            TurnResult(
                index=5,
                user_text=USER_TEXT_5,
                answer="Thanks.",
                memory_after_turn=f'recall_word_fixture: "{WORD_TO_REMEMBER}" (purpose: recall evaluator fixture; status: pending)',
                expected_answer=[],
                expected_memory=[],
                unexpected_answer=[],
                unexpected_memory=[],
            ),
        ]

        score = evaluate_expected_text(turns)
        self.assertEqual(score["word_to_remember"], WORD_TO_REMEMBER)
        self.assertEqual(score["memory_turns_with_recall_word"], [1, 2, 3, 4, 5])
        self.assertEqual(score["recall_turns_in_window"], [4])
        self.assertEqual(score["leaked_word_answer_turns"], [])
        self.assertEqual(score["passed"], score["total"])

# =============================================================================
# LIVE MODEL BEHAVIOR PROBE. Skipped unless explicitly enabled.
# =============================================================================


SimpleBehaviorProbe = PROBE.make_live_probe_test_case("test_recall_word_behavior_probe")

if __name__ == "__main__":
    unittest.main()

