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
  JIN_RUN_BEHAVIOR_PROBE=1 python -m unittest tests.test_behavior_probe_recall_word -v
"""

from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent import AgentRuntime, AgentState  # noqa: E402
from clients import build_clients  # noqa: E402
from runtime import (  # noqa: E402
    RuntimeContext,
    RuntimeEmitter,
    build_runtime_memory_snapshot,
    schedule_runtime_memory_update,
)
from websocket import (  # noqa: E402
    refresh_pending_brain_usage,
    wait_for_runtime_memory_update,
)
from websocket_logger import WebSocketLogger  # noqa: E402


# =============================================================================
# EDIT THIS BLOCK FIRST
# =============================================================================

SCENARIO_ID = "recall_word_surprise_countdown"
SCENARIO_TITLE = "Recall word surprise countdown"
SCENARIO_NOTES = """
Five-step probe for the recall-word contract.
Turn 1 asks JIN to choose and reveal a word immediately, then ask for it back
at any self-selected moment within the next three user turns. The probe extracts
the proposed word from the first answer after a colon or dash-like separator,
and then watches whether a recall question appears during the countdown window.
The exact extracted word must also appear in runtime memory after turn 1.
"""

# Add more turns by appending:
#   USER_TEXT_5 = "..."
#   EXPECTED_TEXT_ANSWER_5 = ["optional answer fragment"]
#   EXPECTED_TEXT_MEMORY_5 = ["optional memory fragment"]
#   UNEXPECTED_TEXT_ANSWER_5 = ["optional forbidden answer fragment"]
#   UNEXPECTED_TEXT_MEMORY_5 = ["optional forbidden memory fragment"]
#
# Empty lists mean: accept any text for this part.

USER_TEXT_1 = (
    "привет, загадай мне слово, а через время спроси какое слово ты загадал "
    "и я должен буду назвать его. пришли сразу слово. не надо происить меня "
    "напомнить тебе, сам выбери любой момент в течение ближайших 3 ходов начиная от текущего."
)
EXPECTED_TEXT_ANSWER_1 = []
EXPECTED_TEXT_MEMORY_1 = [
    "stored_memory",
]
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
# TEST / REPORT SETTINGS
# =============================================================================

RUN_MEMORY_UPDATE_AFTER_EACH_TURN = True
WAIT_FOR_MEMORY_UPDATE_AFTER_EACH_TURN = True

# If False, failed expected fragments are shown in red but do not fail the test.
# Keep False for heatmap/probe mode. Set True when this becomes a regression test.
STRICT_TEXT_ASSERTIONS = False

PRINT_PRETTY_REPORT = True
PRINT_JSON_REPORT = False
PRINT_WEBSOCKET_MESSAGES = False

USE_ANSI_COLORS = True
MAX_ANSWER_PREVIEW_CHARS = 1400
MAX_MEMORY_PREVIEW_CHARS = 2200

# Which memory fields should be displayed and searched.
MEMORY_TEXT_FIELDS_TO_INSPECT = [
    "runtime_memory",
    "runtime_l2_memory",
]


# =============================================================================
# SMALL HELPERS
# =============================================================================

ANSI = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "green": "\033[32m",
    "red": "\033[31m",
    "yellow": "\033[33m",
    "cyan": "\033[36m",
    "blue": "\033[34m",
    "gray": "\033[90m",
}


class CapturingWebSocket:
    def __init__(self):
        self.messages = []

    async def send_json(self, payload: dict):
        self.messages.append(payload)


def paint(text: str, color: str | None = None, *, bold: bool = False, dim: bool = False) -> str:
    if not USE_ANSI_COLORS:
        return text

    prefix = ""
    if bold:
        prefix += ANSI["bold"]
    if dim:
        prefix += ANSI["dim"]
    if color:
        prefix += ANSI.get(color, "")
    return f"{prefix}{text}{ANSI['reset']}"


def render_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        return "\n".join(render_text(item) for item in value).strip()
    return str(value).strip()


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", render_text(text).casefold()).strip()


def expected_fragments(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = value.strip()
        return [value] if value else []
    if isinstance(value, (list, tuple)):
        fragments: list[str] = []
        for item in value:
            fragments.extend(expected_fragments(item))
        return fragments
    value = str(value).strip()
    return [value] if value else []


def fragment_found(text: str, fragment: str) -> bool:
    return normalize_text(fragment) in normalize_text(text)


def strip_markdown_and_emoji(text: str) -> str:
    text = render_text(text)
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_~>#]+", " ", text)

    cleaned_chars = []
    for char in text:
        category = unicodedata.category(char)
        if category.startswith("S"):
            continue
        if char in {"\ufe0f", "\u200d"}:
            continue
        cleaned_chars.append(char)

    text = "".join(cleaned_chars)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" \t\r\n:—–-.,;!?«»\"'()[]{}")


def extract_recall_word_from_first_answer(answer: str) -> str:
    """
    Extract the model-proposed word from the first answer.
    Expected shapes:
    - "Первое слово: **Книга** 📖📚"
    - "Первое слово — **Книга** 📖📚"
    - "Моё слово - **Книга** 📖📚"

    Prefer a separator that follows the word marker itself. This avoids false
    extraction from a decorative dash earlier in the same sentence, for example:
    "Интересная игра — первое слово — **Солнце**".
    """

    word_marker_pattern = re.compile(
        r"\b(?:первое\s+)?слово\b\s*[:：\-—–]\s*(.+)",
        flags=re.IGNORECASE,
    )
    fallback_separator_pattern = re.compile(r"[:：\-—–]")

    # Prefer explicit word markers anywhere in the answer. Do not let an
    # earlier decorative dash, for example "... слова — это ...", win over
    # a later direct marker like "я загадал слово: **Облако**".
    lines = render_text(answer).splitlines()

    for raw_line in lines:
        marker_match = word_marker_pattern.search(raw_line)
        if not marker_match:
            continue

        cleaned = strip_markdown_and_emoji(marker_match.group(1))
        tokens = re.findall(r"[0-9A-Za-zА-Яа-яЁё-]+", cleaned)
        if tokens:
            return tokens[0].strip("-")

    for raw_line in lines:
        fallback_match = fallback_separator_pattern.search(raw_line)
        if not fallback_match:
            continue

        cleaned = strip_markdown_and_emoji(raw_line[fallback_match.end():])
        tokens = re.findall(r"[0-9A-Za-zА-Яа-яЁё-]+", cleaned)
        if tokens:
            return tokens[0].strip("-")

    return ""


def answer_has_recall_question(
        answer: str,
        recall_word: str = "",
) -> bool:
    """
    Detect whether JIN actually surfaced the recall contract.

    Accepted success shapes:
    - JIN asks a direct recall question: "Какое слово я загадал?"
    - JIN asks a softer direct recall question: "Помнишь то слово, которое ты хотел(а) вспомнить?"
    - JIN mentions the extracted secret word in a later answer, which means the
      contract surfaced even if the wording was not a clean question.

    Rejected shapes:
    - "Ты хочешь, чтобы я ещё помнил слово?"
    - "Можем вернуться к игре, если ты помнишь слово?"
    """

    text = normalize_text(answer)
    normalized_recall_word = normalize_text(recall_word)

    if normalized_recall_word and fragment_found(text, normalized_recall_word):
        return True

    if "?" not in text or "слово" not in text:
        return False

    # Some valid recall prompts are split across two short questions, e.g.:
    # "Помнишь, мы запоминали секретное слово? Какое оно было?"
    # A plain split("?") loses the connection between "слово" and the
    # anaphoric follow-up "какое оно". Detect that shape before checking
    # single-question fragments.
    anaphoric_recall_patterns = (
        r"\bслово\b[^?]{0,80}\?\s*(?:а\s+теперь[, ]*)?(?:како[ей]|что)\b[^?]{0,80}\b(?:оно|это|было|наш|секретн\w*)\b",
        r"\bсекретн\w+\s+слово\b[^?]{0,80}\?\s*(?:како[ей]|что)\b[^?]{0,80}\b(?:оно|это|было|наш|секретн\w*)\b",
    )

    if any(re.search(pattern, text) for pattern in anaphoric_recall_patterns):
        return True

    question_parts = [
        part.strip()
        for part in text.split("?")
        if "слово" in part
    ]

    direct_recall_patterns = (
        r"\bкако[ей]\s+(?:же\s+)?слово\b",
        r"\bкако[ей]\s+.*?\bслово\b",
        r"\bчто\s+за\s+слово\b",
        r"\bназови\s+(?:мне\s+)?(?:то\s+)?слово\b",
        r"\bвспомни\w*\s+(?:мне\s+)?(?:то\s+)?(?:секретн\w+\s+)?слово\b",
        r"\bугадай\s+(?:то\s+)?слово\b",
        r"\bнапомни\s+(?:мне\s*,?\s*)?(?:пожалуйста\s*,?\s*)?(?:то\s+)?слово\b",
        r"\bпомнишь\s*,?\s*како[ей]\s+.*?\bслово\b",
        r"(?:^|[.!?]\s*|\bкстати,\s*)помнишь\s+(?:то\s+)?слово\b",
        r"\bпришло\s*,?\s*время\s+.*?\bслово\b",
        r"\bпора\s*,?\s*назвать\s+.*?\bслово\b",
        r"\bкако[ей]\s*,?\s*было\s+.*?\bслово\b",
    )

    conditional_recall_trigger_pattern = (
        r"\b(?:како[ей]|что\s+за|назови|вспомни|угадай|напомни|пришло|пора)\b"
    )

    for part in question_parts:
        # Reject passive conditional mentions like
        # "... если ты помнишь слово ...", but allow the common shape
        # "если ты помнишь... какой же ... слово?" where the condition is
        # only a lead-in to a direct recall question.
        if "если ты помнишь" in part and not re.search(conditional_recall_trigger_pattern, part):
            continue

        if any(re.search(pattern, part) for pattern in direct_recall_patterns):
            return True

    return False


def evaluate_recall_word_behavior(turns: list[TurnResult]) -> dict[str, Any]:
    first_answer = turns[0].answer if turns else ""
    extracted_word = extract_recall_word_from_first_answer(first_answer)

    window_turns = [turn for turn in turns if 2 <= turn.index <= 4]
    fallback_turns = [turn for turn in turns if 2 <= turn.index <= 5]
    recall_turns_in_window = [turn.index for turn in window_turns if answer_has_recall_question(turn.answer, extracted_word)]
    recall_turns_by_fallback = [turn.index for turn in fallback_turns if answer_has_recall_question(turn.answer, extracted_word)]
    memory_turns_with_recall_word = [
        turn.index
        for turn in turns
        if extracted_word and fragment_found(turn.memory_after_turn, extracted_word)
    ]
    memory_has_recall_word_after_turn_1 = bool(
        turns
        and extracted_word
        and fragment_found(turns[0].memory_after_turn, extracted_word)
    )

    checks = [
        {
            "name": "turn_1.extract_recall_word_after_separator",
            "target": "answer",
            "turn": 1,
            "fragment": "non-empty cleaned word after colon or dash separator",
            "passed": bool(extracted_word),
        },
        {
            "name": "turn_1.memory_contains_extracted_recall_word",
            "target": "memory",
            "turn": 1,
            "fragment": "extracted recall word appears in memory after turn 1",
            "passed": memory_has_recall_word_after_turn_1,
        },
        {
            "name": "turn_any.memory_contains_extracted_recall_word",
            "target": "memory",
            "turn": "1-5",
            "fragment": "extracted recall word appears in any memory snapshot",
            "passed": bool(memory_turns_with_recall_word),
        },
        {
            "name": "turn_2_4.recall_question_within_three_user_turns",
            "target": "answer",
            "turn": "2-4",
            "fragment": 'answer contains direct recall wording or extracted word mention',
            "passed": bool(recall_turns_in_window),
        },
        {
            "name": "turn_2_5.recall_question_observed_by_fallback_turn",
            "target": "answer",
            "turn": "2-5",
            "fragment": 'answer contains direct recall wording or extracted word mention',
            "passed": bool(recall_turns_by_fallback),
        },
    ]

    passed = sum(1 for check in checks if check["passed"])
    total = len(checks)

    return {
        "passed": passed,
        "total": total,
        "ratio": passed / total if total else 1.0,
        "checks": checks,
        "extracted_recall_word": extracted_word,
        "recall_turns_in_window": recall_turns_in_window,
        "recall_turns_by_fallback": recall_turns_by_fallback,
        "memory_turns_with_recall_word": memory_turns_with_recall_word,
    }


def clip_text(text: str, limit: int) -> str:
    text = render_text(text)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + paint("\n... [clipped]", "gray", dim=True)


def indent_block(text: str, prefix: str = "  ") -> str:
    text = render_text(text)
    if not text:
        return prefix + paint("<empty>", "gray", dim=True)
    return "\n".join(f"{prefix}{line}" for line in text.splitlines())


def status_label(passed: bool) -> str:
    return paint("OK", "green", bold=True) if passed else paint("FAIL", "red", bold=True)


def collect_dialogue_steps() -> list[dict[str, Any]]:
    """
    Auto-collect USER_TEXT_N plus expected/unexpected answer and memory markers.
    To extend the scenario, add the next numeric constants at the top.
    """

    steps: list[dict[str, Any]] = []
    index = 1

    while True:
        user_key = f"USER_TEXT_{index}"
        answer_key = f"EXPECTED_TEXT_ANSWER_{index}"
        memory_key = f"EXPECTED_TEXT_MEMORY_{index}"
        unexpected_answer_key = f"UNEXPECTED_TEXT_ANSWER_{index}"
        unexpected_memory_key = f"UNEXPECTED_TEXT_MEMORY_{index}"

        if user_key not in globals():
            break

        user_text = render_text(globals()[user_key])
        if user_text:
            steps.append(
                {
                    "index": index,
                    "user_text": user_text,
                    "expected_answer": expected_fragments(globals().get(answer_key, [])),
                    "expected_memory": expected_fragments(globals().get(memory_key, [])),
                    "unexpected_answer": expected_fragments(globals().get(unexpected_answer_key, [])),
                    "unexpected_memory": expected_fragments(globals().get(unexpected_memory_key, [])),
                }
            )

        index += 1

    return steps


@dataclass
class TurnResult:
    index: int
    user_text: str
    answer: str
    memory_after_turn: str
    expected_answer: list[str]
    expected_memory: list[str]
    unexpected_answer: list[str]
    unexpected_memory: list[str]


async def run_standard_turn(context: RuntimeContext, user_text: str) -> AgentState:
    await wait_for_runtime_memory_update(context)
    await refresh_pending_brain_usage(context, user_text)

    context.runtime_turn_user_message = user_text
    context.runtime_turn_assistant_response = ""
    context.runtime_turn_interrupted = False
    context.user_message_count += 1

    if hasattr(context, "runtime_usage_events"):
        context.runtime_usage_events.clear()
    else:
        context.runtime_usage_events = []

    state = AgentState(user_input=user_text)
    runtime = AgentRuntime()

    await context.logger.log_system(
        f"[BEHAVIOR_PROBE] runtime=AgentRuntime scenario={SCENARIO_ID}"
    )
    await context.websocket.send_json({"type": "agent_runtime_start", "scenario": SCENARIO_ID})

    await runtime.run(state, context)

    await context.websocket.send_json({"type": "agent_runtime_end", "scenario": SCENARIO_ID})

    assistant_message = (
        state.final_answer
        or state.brain_response
        or context.runtime_turn_assistant_response
        or ""
    )

    if RUN_MEMORY_UPDATE_AFTER_EACH_TURN:
        schedule_runtime_memory_update(
            context=context,
            user_message=user_text,
            assistant_message=assistant_message,
        )

        if WAIT_FOR_MEMORY_UPDATE_AFTER_EACH_TURN:
            await wait_for_runtime_memory_update(context)

    context.assistant_message_count += 1
    context.turn_number += 1

    return state


def build_memory_blob(context: RuntimeContext) -> str:
    parts = []
    for field_name in MEMORY_TEXT_FIELDS_TO_INSPECT:
        value = getattr(context, field_name, "")
        if value:
            parts.append(f"[{field_name}]\n{value}")
    return "\n\n".join(parts)


def evaluate_expected_text(turns: list[TurnResult]) -> dict[str, Any]:
    """
    Only checks expected fragments declared in constants.
    Empty expected lists produce no checks.
    """

    checks: list[dict[str, Any]] = []

    for turn in turns:
        for fragment in turn.expected_answer:
            checks.append(
                {
                    "name": f"turn_{turn.index}.answer_contains",
                    "target": "answer",
                    "turn": turn.index,
                    "fragment": fragment,
                    "passed": fragment_found(turn.answer, fragment),
                }
            )

        for fragment in turn.expected_memory:
            checks.append(
                {
                    "name": f"turn_{turn.index}.memory_contains",
                    "target": "memory",
                    "turn": turn.index,
                    "fragment": fragment,
                    "passed": fragment_found(turn.memory_after_turn, fragment),
                }
            )

        for fragment in turn.unexpected_answer:
            checks.append(
                {
                    "name": f"turn_{turn.index}.answer_not_contains",
                    "target": "answer",
                    "turn": turn.index,
                    "fragment": fragment,
                    "passed": not fragment_found(turn.answer, fragment),
                }
            )

        for fragment in turn.unexpected_memory:
            checks.append(
                {
                    "name": f"turn_{turn.index}.memory_not_contains",
                    "target": "memory",
                    "turn": turn.index,
                    "fragment": fragment,
                    "passed": not fragment_found(turn.memory_after_turn, fragment),
                }
            )

    recall_score = evaluate_recall_word_behavior(turns)
    checks.extend(recall_score["checks"])

    passed = sum(1 for check in checks if check["passed"])
    total = len(checks)

    return {
        "passed": passed,
        "total": total,
        "ratio": passed / total if total else 1.0,
        "checks": checks,
        "extracted_recall_word": recall_score["extracted_recall_word"],
        "recall_turns_in_window": recall_score["recall_turns_in_window"],
        "recall_turns_by_fallback": recall_score["recall_turns_by_fallback"],
        "memory_turns_with_recall_word": recall_score["memory_turns_with_recall_word"],
    }


def print_behavior_probe_report(report: dict[str, Any]) -> None:
    score = report["score"]
    turns = report["turns"]

    header = f"BEHAVIOR PROBE :: {report['scenario_id']}"
    print("\n" + paint("=" * len(header), "cyan", bold=True))
    print(paint(header, "cyan", bold=True))
    print(paint("=" * len(header), "cyan", bold=True))

    score_color = "green" if score["ratio"] >= 0.85 else "yellow" if score["ratio"] >= 0.60 else "red"
    print(
        paint("Score: ", bold=True)
        + paint(f"{score['passed']}/{score['total']} ({score['ratio']:.0%})", score_color, bold=True)
    )
    print(paint(f"Title: {report['scenario_title']}", "gray"))
    if score.get("extracted_recall_word"):
        print(paint(f"Extracted recall word: {score['extracted_recall_word']}", "gray"))
    if score.get("recall_turns_in_window"):
        print(paint(f"Recall question turns 2-4: {score['recall_turns_in_window']}", "gray"))
    if score.get("memory_turns_with_recall_word"):
        print(paint(f"Memory contains extracted word after turns: {score['memory_turns_with_recall_word']}", "gray"))

    print("\n" + paint("DIALOGUE", "blue", bold=True))
    for turn in turns:
        print(paint(f"\n--- Turn {turn['index']} ---", "gray", bold=True))
        print(paint("USER:", "cyan", bold=True))
        print(indent_block(turn["user_text"]))

        print(paint("MODEL:", "green", bold=True))
        print(indent_block(clip_text(turn["answer"], MAX_ANSWER_PREVIEW_CHARS)))

        if turn["expected_answer"]:
            print(paint("EXPECTED TEXT IN ANSWER:", "yellow", bold=True))
            for fragment in turn["expected_answer"]:
                print(f"  {status_label(fragment_found(turn['answer'], fragment))} {fragment}")
        else:
            print(paint("EXPECTED TEXT IN ANSWER: <any answer accepted>", "gray", dim=True))

        if turn["expected_memory"]:
            print(paint("EXPECTED TEXT IN MEMORY:", "yellow", bold=True))
            for fragment in turn["expected_memory"]:
                print(f"  {status_label(fragment_found(turn['memory_after_turn'], fragment))} {fragment}")
        else:
            print(paint("EXPECTED TEXT IN MEMORY: <any memory accepted>", "gray", dim=True))

        if turn.get("unexpected_answer"):
            print(paint("UNEXPECTED TEXT IN ANSWER:", "red", bold=True))
            for fragment in turn["unexpected_answer"]:
                print(f"  {status_label(not fragment_found(turn['answer'], fragment))} not: {fragment}")

        if turn.get("unexpected_memory"):
            print(paint("UNEXPECTED TEXT IN MEMORY:", "red", bold=True))
            for fragment in turn["unexpected_memory"]:
                print(f"  {status_label(not fragment_found(turn['memory_after_turn'], fragment))} not: {fragment}")

    print("\n" + paint("TEXT CHECKS", "blue", bold=True))
    if not score["checks"]:
        print(paint("  No expected fragments declared. This probe only prints dialogue.", "gray", dim=True))
    else:
        for check in score["checks"]:
            if check["name"].endswith("_not_contains"):
                description = f"turn {check['turn']} {check['target']} does not contain: {check['fragment']}"
            elif check["name"].endswith("_contains"):
                description = f"turn {check['turn']} {check['target']} contains: {check['fragment']}"
            else:
                description = f"{check['name']}: {check['fragment']}"
            print(f"  {status_label(check['passed'])} {description}")

    final_memory = clip_text(report.get("final_memory", ""), MAX_MEMORY_PREVIEW_CHARS)
    if final_memory:
        print("\n" + paint("FINAL MEMORY SNAPSHOT", "blue", bold=True))
        print(indent_block(final_memory))

    print("\n" + paint("COUNTERS", "blue", bold=True))
    print(f"  turns: {report['turn_number']}")
    print(f"  user messages: {report['user_message_count']}")
    print(f"  assistant messages: {report['assistant_message_count']}")
    print(f"  websocket messages: {report['websocket_message_count']}")
    print(paint("=" * len(header), "cyan", bold=True) + "\n")


# =============================================================================
# LOCAL SHAPE TESTS. These always run and do not require the model.
# =============================================================================


class BehaviorProbeShapeTests(unittest.TestCase):
    def test_collect_dialogue_steps_finds_seed_steps(self):
        steps = collect_dialogue_steps()
        self.assertEqual(len(steps), 5)
        self.assertIn("загадай мне слово", steps[0]["user_text"])
        self.assertIn("нарисуй домик", steps[1]["user_text"])
        self.assertIn("хайку", steps[2]["user_text"])
        self.assertIn("спасибо", steps[3]["user_text"])
        self.assertIn("хорошо", steps[4]["user_text"])

    def test_extract_recall_word_strips_markdown_and_emoji(self):
        answer = "Интересная игра на внимание. Первое слово: **Книга** 📖📚"
        self.assertEqual(extract_recall_word_from_first_answer(answer), "Книга")

    def test_extract_recall_word_accepts_dash_separator(self):
        examples = (
            "Первое слово — **Солнце**. ☀️",
            "Первое слово - **Солнце**. ☀️",
            "Первое слово – **Солнце**. ☀️",
            "Интересная игра — первое слово — **Солнце**. ☀️",
        )

        for answer in examples:
            with self.subTest(answer=answer):
                self.assertEqual(
                    extract_recall_word_from_first_answer(answer),
                    "Солнце",
                )

    def test_extract_recall_word_prefers_explicit_marker_over_earlier_dash(self):
        answer = (
            "Привет! Отличная идея для игры. Загадывать слова — это всегда интересно.\n\n"
            "Итак, я загадал слово: **Облако**. ☁️"
        )
        self.assertEqual(extract_recall_word_from_first_answer(answer), "Облако")

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
            answer_has_recall_question("А теперь, если ты помнишь... какой же наш секретный слово?")
        )
        self.assertTrue(
            answer_has_recall_question("Помнишь то слово, которое ты хотел(а) вспомнить?")
        )
        self.assertTrue(
            answer_has_recall_question("Кстати, напомни мне, пожалуйста, то слово, которое мы запоминали?")
        )
        self.assertTrue(
            answer_has_recall_question("Не мог бы ты вспомнить то секретное слово, которое мы запоминали?")
        )
        self.assertTrue(
            answer_has_recall_question("Кстати, наше слово было Книга.", "Книга")
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

    def test_evaluator_tracks_dynamic_recall_question(self):
        turns = [
            TurnResult(
                index=1,
                user_text=USER_TEXT_1,
                answer="Интересная игра. Первое слово: **Книга** 📖📚",
                memory_after_turn='stored_memory: "Книга" (purpose: recall test; status: pending)',
                expected_answer=[],
                expected_memory=["stored_memory"],
                unexpected_answer=[],
                unexpected_memory=[],
            ),
            TurnResult(
                index=2,
                user_text=USER_TEXT_2,
                answer="Вот домик:\n /\\\n/  \\\n| [] |",
                memory_after_turn='stored_memory: "Книга" (purpose: recall test; status: pending)',
                expected_answer=[],
                expected_memory=[],
                unexpected_answer=[],
                unexpected_memory=[],
            ),
            TurnResult(
                index=3,
                user_text=USER_TEXT_3,
                answer="Лягушка в пруду...",
                memory_after_turn='stored_memory: "Книга" (purpose: recall test; status: pending)',
                expected_answer=[],
                expected_memory=[],
                unexpected_answer=[],
                unexpected_memory=[],
            ),
            TurnResult(
                index=4,
                user_text=USER_TEXT_4,
                answer="Пожалуйста. Помнишь то слово, которое ты хотел(а) вспомнить?",
                memory_after_turn='stored_memory: "Книга" (purpose: recall test; status: pending)',
                expected_answer=[],
                expected_memory=[],
                unexpected_answer=[],
                unexpected_memory=[],
            ),
            TurnResult(
                index=5,
                user_text=USER_TEXT_5,
                answer="Спасибо за слова. Кстати, наше слово было Книга.",
                memory_after_turn='stored_memory: "Книга" (purpose: recall test; status: pending)',
                expected_answer=[],
                expected_memory=[],
                unexpected_answer=[],
                unexpected_memory=[],
            ),
        ]

        score = evaluate_expected_text(turns)
        self.assertEqual(score["extracted_recall_word"], "Книга")
        self.assertEqual(score["memory_turns_with_recall_word"], [1, 2, 3, 4, 5])
        self.assertEqual(score["recall_turns_in_window"], [4])
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
        self.http_client = httpx.AsyncClient()
        self.websocket = CapturingWebSocket()

        self.context = RuntimeContext(
            websocket=self.websocket,
            emitter=RuntimeEmitter(self.websocket),
            logger=WebSocketLogger(self.websocket),
            clients=build_clients(self.http_client),
        )

        initial_snapshot = build_runtime_memory_snapshot(
            self.context,
            self.context.runtime_memory,
        )
        self.context.runtime_memory_snapshots.append(initial_snapshot)
        self.context.runtime_memory_snapshot_index = 0

    async def asyncTearDown(self):
        await wait_for_runtime_memory_update(self.context)
        await self.http_client.aclose()

    async def test_recall_word_behavior_probe(self):
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
