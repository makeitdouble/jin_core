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
import re
import sys
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent import AgentRuntime, AgentState  # noqa: E402
from clients import build_clients  # noqa: E402
from clients.brain_client_utils import create_active_memory_runtime_record  # noqa: E402
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
EXPECTED_RUNTIME_ACTION_1 = ["create_active_memory"]
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

PRINT_PRETTY_REPORT = sys.stdout.isatty()
PRINT_JSON_REPORT = False
PRINT_WEBSOCKET_MESSAGES = False
LIVE_STREAM_MODEL_OUTPUT = sys.stdout.isatty()
LIVE_PRINT_TURN_RESULTS = sys.stdout.isatty()
PRINT_ACTIVE_MEMORY_DEBUG = True

USE_ANSI_COLORS = True
MAX_ANSWER_PREVIEW_CHARS = 1400
MAX_MEMORY_PREVIEW_CHARS = 2200

# Which memory fields should be displayed and searched.
MEMORY_TEXT_FIELDS_TO_INSPECT = [
    "runtime_memory",
    "runtime_l2_memory",
    "active_memory_records",
]

# Extra RuntimeContext fields to scan for active memory contract entries right after
# refresh_pending_brain_usage() and before AgentRuntime.run(). This makes the
# probe show what memory was available to the next brain turn, not only what
# ended up in the post-turn snapshot. Unknown/missing fields are ignored.
CONTEXT_ACTIVE_MEMORY_DEBUG_FIELDS_TO_SCAN = [
    "runtime_memory",
    "runtime_l2_memory",
    "runtime_memory_snapshots",
    "runtime_memory_snapshot_index",
    "pending_brain_usage",
    "runtime_usage_events",
    "active_memory_records",
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
        self.live_message_ids = set()

    async def send_json(self, payload: dict):
        self.messages.append(payload)
        if not LIVE_STREAM_MODEL_OUTPUT:
            return

        payload_type = payload.get("type")

        if payload_type == "message_start":
            context = payload.get("context") or {}
            if context.get("context_role") != "brain":
                return

            message_id = payload.get("message_id")
            if not message_id:
                return

            self.live_message_ids.add(message_id)
            role = payload.get("role") or "model"
            print(paint(f"\nSTREAM {role}:", "green", bold=True), flush=True)
            return

        message_id = payload.get("message_id")
        if message_id not in self.live_message_ids:
            return

        if payload_type == "message_chunk":
            print(payload.get("chunk", ""), end="", flush=True)
        elif payload_type == "message_end":
            print("", flush=True)
            self.live_message_ids.discard(message_id)


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


def answer_has_recall_question(
        answer: str,
        recall_word: str = "",
) -> bool:
    """
    Detect whether JIN actually surfaced the recall contract.

    Accepted success shapes:
    - JIN asks a direct recall question: "Какое слово я загадал?"
    - JIN asks a softer direct recall question: "Помнишь то слово, которое ты хотел(а) вспомнить?"
    Rejected shapes:
    - "Ты хочешь, чтобы я ещё помнил слово?"
    - "Можем вернуться к игре, если ты помнишь слово?"
    """

    text = normalize_text(answer)
    if "?" not in text or "слово" not in text:
        return False

    # Some valid recall prompts are split across two short questions, e.g.:
    # "Помнишь, мы запоминали секретное слово? Какое оно было?"
    # A plain split("?") loses the connection between "слово" and the
    # anaphoric follow-up "какое оно". Detect that shape before checking
    # single-question fragments.
    anaphoric_recall_patterns = (
        r"\bслово\b[^?]{0,80}\?\s*(?:а\s+теперь[, ]*)?(?:како[ей]|как|что)\b[^?]{0,80}\b(?:оно|это|было|наш|секретн\w*)\b",
        r"\bсекретн\w+\s+слово\b[^?]{0,80}\?\s*(?:како[ей]|как|что)\b[^?]{0,80}\b(?:оно|это|было|наш|секретн\w*)\b",
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
        r"\bчто\s+(?:же\s+)?(?:это\s+)?(?:за\s+)?(?:то\s+)?(?:секретн\w+\s+)?слово\b",
        r"\bназови\s+(?:мне\s+)?(?:то\s+)?слово\b",
        r"\bвспомни\w*\s+(?:мне\s+)?(?:то\s+)?(?:секретн\w+\s+)?слово\b",
        r"\bугадай\s+(?:то\s+)?слово\b",
        r"\bнапомни\s+(?:мне\s*,?\s*)?(?:пожалуйста\s*,?\s*)?(?:то\s+)?слово\b",
        r"\bпомнишь\s*,?\s*како[ей]\s+.*?\bслово\b",
        r"(?:^|[.!?]\s*|\bкстати,\s*)\s*(?:а\s+)?(?:ты\s+)?помнишь\s+(?:то\s+)?слово\b",
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
    recall_word = WORD_TO_REMEMBER

    window_turns = [turn for turn in turns if 2 <= turn.index <= 4]
    fallback_turns = [turn for turn in turns if 2 <= turn.index <= 5]
    recall_turns_in_window = [turn.index for turn in window_turns if answer_has_recall_question(turn.answer, recall_word)]
    recall_turns_by_fallback = [turn.index for turn in fallback_turns if answer_has_recall_question(turn.answer, recall_word)]
    leaked_word_answer_turns = [
        turn.index
        for turn in turns[1:]
        if recall_word and fragment_found(turn.answer, recall_word)
    ]
    memory_turns_with_recall_word = [
        turn.index
        for turn in turns
        if recall_word and fragment_found(turn.memory_after_turn, recall_word)
    ]
    memory_has_recall_word_after_turn_1 = bool(
        turns
        and recall_word
        and fragment_found(turns[0].memory_after_turn, recall_word)
    )

    checks = [
        {
            "name": "turn_1.memory_contains_word_to_remember",
            "target": "memory",
            "turn": 1,
            "fragment": "WORD_TO_REMEMBER appears in memory after turn 1",
            "passed": memory_has_recall_word_after_turn_1,
        },
        {
            "name": "turn_any.memory_contains_word_to_remember",
            "target": "memory",
            "turn": "1-5",
            "fragment": "WORD_TO_REMEMBER appears in any memory snapshot",
            "passed": bool(memory_turns_with_recall_word),
        },
        {
            "name": "turn_2_4.recall_question_within_three_user_turns",
            "target": "answer",
            "turn": "2-4",
            "fragment": "answer contains direct recall wording without revealing WORD_TO_REMEMBER",
            "passed": bool(recall_turns_in_window),
        },
        {
            "name": "turn_2_5.recall_question_observed_by_fallback_turn",
            "target": "answer",
            "turn": "2-5",
            "fragment": "answer contains direct recall wording without revealing WORD_TO_REMEMBER",
            "passed": bool(recall_turns_by_fallback),
        },
        {
            "name": "turn_2_5.answer_does_not_reveal_word_to_remember",
            "target": "answer",
            "turn": "2-5",
            "fragment": "WORD_TO_REMEMBER must not appear in answers after turn 1",
            "passed": bool(recall_word) and not leaked_word_answer_turns,
        },
    ]

    passed = sum(1 for check in checks if check["passed"])
    total = len(checks)

    return {
        "passed": passed,
        "total": total,
        "ratio": passed / total if total else 1.0,
        "checks": checks,
        "word_to_remember": recall_word,
        "recall_turns_in_window": recall_turns_in_window,
        "recall_turns_by_fallback": recall_turns_by_fallback,
        "memory_turns_with_recall_word": memory_turns_with_recall_word,
        "leaked_word_answer_turns": leaked_word_answer_turns,
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


def find_trailing_balanced_suffix_start(value: str) -> int:
    """Return the start index of the last balanced trailing (...) or [...] suffix."""

    text = render_text(value).rstrip()
    if not text:
        return -1

    closing_to_opening = {
        ")": "(",
        "]": "[",
    }
    opening_to_closing = {
        "(": ")",
        "[": "]",
    }

    closing = text[-1]
    opening = closing_to_opening.get(closing)
    if not opening:
        return -1

    depth = 0

    for index in range(len(text) - 1, -1, -1):
        char = text[index]

        if char == closing:
            depth += 1
            continue

        if char == opening:
            depth -= 1
            if depth == 0:
                return index
            continue

        # Ignore the other suffix family while scanning the current one.
        if char in opening_to_closing or char in closing_to_opening:
            continue

    return -1


def find_trailing_balanced_parenthetical_start(value: str) -> int:
    """Backward-compatible helper used by older shape tests."""

    text = render_text(value).rstrip()
    if not text.endswith(")"):
        return -1
    return find_trailing_balanced_suffix_start(text)


def split_memory_contract_value_and_suffixes(raw_value: str) -> tuple[str, list[str]]:
    """
    Split a memory contract payload into the visible value and trailing suffixes.

    Supports both old parenthetical suffixes:
      active_memory: облако (purpose: recall challenge; status: pending)

    Parentheses are balanced, so nested diagnostic text like
    conditions: ... (reminded: 0) stays inside the same metadata suffix.
    """

    value = render_text(raw_value).strip().rstrip(",")
    suffixes: list[str] = []

    while value.endswith((")", "]")):
        start = find_trailing_balanced_suffix_start(value)
        if start < 0:
            break

        suffix = value[start:].strip()
        if not suffix:
            break

        suffixes.insert(0, suffix)
        value = value[:start].rstrip()

    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1].strip()

    return value, suffixes


def split_active_memory_value_and_suffixes(raw_value: str) -> tuple[str, list[str]]:
    """Backward-compatible name for existing active_memory shape tests."""

    return split_memory_contract_value_and_suffixes(raw_value)


def extract_suffix_field(suffix_text: str, field_name: str) -> str:
    pattern = re.compile(
        rf"\[\s*{re.escape(field_name)}\s*:\s*([^\]]+?)\s*\]",
        flags=re.IGNORECASE,
    )
    match = pattern.search(suffix_text)
    return match.group(1).strip() if match else ""


def summarize_contract_progress(key: str, suffix_text: str) -> str:
    """Produce a compact progress string for console diagnostics."""

    turn_match = re.search(
        r"\(\s*turn\s+(\d+)\s*/\s*(\d+)\s*\)",
        suffix_text,
        flags=re.IGNORECASE,
    )
    if turn_match:
        elapsed, total = turn_match.groups()
        return f"turn {elapsed}/{total}"

    reminded_match = re.search(r"\breminded\s*:\s*(\d+)\b", suffix_text, flags=re.IGNORECASE)
    if key.casefold().startswith("active_memory") and reminded_match:
        return f"reminded={reminded_match.group(1)}"

    return ""


def extract_active_memory_entries(text: Any, source: str = "") -> list[dict[str, str]]:
    """
    Return active_memory entries from a text-ish blob.

    The historical function name is kept because the probe already calls it.
    """

    entries: list[dict[str, str]] = []
    source_text = render_text(text)
    if "active_memory" not in source_text:
        return entries

    entry_pattern = re.compile(
        r"^\s*[\"']?"
        r"(?P<key>active_memory(?:_\d+)?)"
        r"[\"']?\s*[:=]\s*(?P<raw>.+?)\s*$",
        flags=re.IGNORECASE,
    )

    for line in source_text.splitlines():
        match = entry_pattern.match(line)
        if not match:
            continue

        key = match.group("key")
        raw_value = match.group("raw").strip().rstrip(",")
        value, suffixes = split_memory_contract_value_and_suffixes(raw_value)
        suffix_text = " ".join(suffixes)
        entries.append(
            {
                "source": source,
                "key": key,
                "value": value,
                "suffixes": suffix_text,
                "progress": summarize_contract_progress(key, suffix_text),
                "raw": f"{key}: {raw_value}",
            }
        )

    return entries


def render_active_memory_entries(entries: list[dict[str, str]]) -> str:
    if not entries:
        return paint("<no memory contract entries found>", "gray", dim=True)

    lines: list[str] = []
    last_source = None
    for entry in entries:
        source = entry.get("source") or "unknown"
        if source != last_source:
            lines.append(paint(f"[{source}]", "gray", bold=True))
            last_source = source

        suffixes = entry.get("suffixes") or paint("<none>", "gray", dim=True)
        progress = entry.get("progress") or paint("<none>", "gray", dim=True)
        lines.append(
            f"  {paint(entry.get('key', ''), 'cyan', bold=True)} "
            f"value={entry.get('value', '')} "
            f"progress={progress} "
            f"suffixes={suffixes}"
        )
        raw = entry.get("raw") or ""
        if raw:
            lines.append(paint(f"    raw: {raw}", "gray", dim=True))

    return "\n".join(lines)


def collect_active_memory_entries_from_context(
        context: RuntimeContext,
        *,
        source_prefix: str,
) -> list[dict[str, str]]:
    """
    Shallow-scan known RuntimeContext fields for active_memory lines.

    The goal is diagnostic output, not assertions: show what active recall
    state is present immediately before the next brain turn.
    """

    entries: list[dict[str, str]] = []
    seen_raw: set[tuple[str, str]] = set()

    for field_name in CONTEXT_ACTIVE_MEMORY_DEBUG_FIELDS_TO_SCAN:
        if not hasattr(context, field_name):
            continue

        try:
            value = getattr(context, field_name)
        except Exception as exc:  # pragma: no cover - diagnostic only
            entries.append(
                {
                    "source": f"{source_prefix}.{field_name}",
                    "key": "<read_error>",
                    "value": str(exc),
                    "suffixes": "",
                    "progress": "",
                    "raw": f"<read_error>: {exc}",
                }
            )
            continue

        # Avoid dumping full websocket/logger/client objects. For lists/dicts,
        # render_text(str(value)) is enough for the active_memory line probe.
        field_entries = extract_active_memory_entries(
            value,
            source=f"{source_prefix}.{field_name}",
        )
        for entry in field_entries:
            dedupe_key = (entry.get("source", ""), entry.get("raw", ""))
            if dedupe_key in seen_raw:
                continue
            seen_raw.add(dedupe_key)
            entries.append(entry)

    return entries


def collect_snapshot_active_memory_entries(memory_blob: str) -> list[dict[str, str]]:
    return extract_active_memory_entries(memory_blob, source="post_turn_snapshot")


def format_active_memory_debug(title: str, entries: list[dict[str, str]]) -> str:
    return paint(title, "yellow", bold=True) + "\n" + indent_block(render_active_memory_entries(entries))

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
        runtime_action_key = f"EXPECTED_RUNTIME_ACTION_{index}"

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
                    "expected_runtime_actions": expected_fragments(
                        globals().get(runtime_action_key, [])
                    ),
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
    expected_runtime_actions: list[str] = field(default_factory=list)
    context_active_memory_before_turn: str = ""
    snapshot_active_memory_after_turn: str = ""
    runtime_actions: list[dict[str, Any]] = field(default_factory=list)


def render_runtime_actions(actions: list[dict[str, Any]]) -> str:
    if not actions:
        return "<none>"

    lines = []
    for action in actions:
        parts = [str(action.get("name", "unknown"))]
        payload = action.get("payload")
        if payload:
            parts.append(f"payload={payload}")
        query = action.get("query")
        if query:
            parts.append(f"query={query}")
        lines.append(" | ".join(parts))

    return "\n".join(lines)


def print_live_turn_result(turn: TurnResult) -> None:
    if not LIVE_PRINT_TURN_RESULTS:
        return

    score = evaluate_expected_text([turn])
    print(paint(f"\nLIVE TURN {turn.index} RESULT", "blue", bold=True), flush=True)

    if not score["checks"]:
        print(paint("  No text checks for this turn.", "gray", dim=True), flush=True)
        return

    for check in score["checks"]:
        if check["name"].endswith("_not_contains"):
            description = f"{check['target']} does not contain: {check['fragment']}"
        else:
            description = f"{check['target']} contains: {check['fragment']}"
        print(f"  {status_label(check['passed'])} {description}", flush=True)

    print(
        paint("  RUNTIME ACTIONS EMITTED BY MODEL:", "yellow", bold=True),
        flush=True,
    )
    print(
        indent_block(render_runtime_actions(turn.runtime_actions), prefix="    "),
        flush=True,
    )

    if PRINT_ACTIVE_MEMORY_DEBUG:
        if turn.context_active_memory_before_turn:
            print(
                indent_block(turn.context_active_memory_before_turn, prefix="  "),
                flush=True,
            )
        if turn.snapshot_active_memory_after_turn:
            print(
                indent_block(turn.snapshot_active_memory_after_turn, prefix="  "),
                flush=True,
            )


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

    context.behavior_probe_context_active_memory_before_turn = format_active_memory_debug(
        "MEMORY CONTRACTS PASSED TO CONTEXT BEFORE TURN",
        collect_active_memory_entries_from_context(
            context,
            source_prefix="context_before_turn",
        ),
    )

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
        if isinstance(value, (list, tuple)):
            value = "\n".join(render_text(item) for item in value if render_text(item))
        if value:
            parts.append(f"[{field_name}]\n{value}")
    return "\n\n".join(parts)


def normalize_runtime_action_name(name: str) -> str:
    return normalize_text(name).replace("-", "_").replace(" ", "_")


def runtime_action_found(actions: list[dict[str, Any]], expected_name: str) -> bool:
    normalized_expected = normalize_runtime_action_name(expected_name)
    return any(
        normalize_runtime_action_name(str(action.get("name", ""))) == normalized_expected
        for action in actions
    )


def normalize_websocket_runtime_action(payload: dict[str, Any]) -> dict[str, Any] | None:
    if payload.get("type") != "runtime_action":
        return None

    action_name = render_text(payload.get("action", ""))
    if not action_name:
        return None

    action_event: dict[str, Any] = {"name": normalize_runtime_action_name(action_name)}

    for key in ("id", "query", "text", "active_memory"):
        value = render_text(payload.get(key, ""))
        if value:
            action_event[key] = value

    explicit_payload = render_text(payload.get("payload", ""))
    if explicit_payload:
        action_event["payload"] = explicit_payload
    elif action_event.get("text", "").startswith("Saving:"):
        action_event["payload"] = action_event["text"].split("Saving:", 1)[1].strip()

    return action_event


def collect_runtime_actions_after_offsets(
    context: RuntimeContext,
    *,
    context_event_offset: int,
    websocket_message_offset: int,
    websocket_messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Browser-visible runtime actions are emitted over websocket, while the
    backend also keeps context.runtime_action_events. The recall-word probe
    should track both channels instead of relying on old active_memory text
    generated by the memory updater.
    """

    actions: list[dict[str, Any]] = []

    for event in getattr(context, "runtime_action_events", [])[context_event_offset:]:
        if isinstance(event, dict):
            actions.append(dict(event))

    for message in websocket_messages[websocket_message_offset:]:
        if not isinstance(message, dict):
            continue

        action = normalize_websocket_runtime_action(message)
        if action is not None:
            actions.append(action)

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()

    for action in actions:
        key = (
            normalize_runtime_action_name(str(action.get("name", ""))),
            render_text(action.get("id", "")),
            render_text(action.get("query", "")),
            render_text(action.get("payload", "")),
            render_text(action.get("active_memory", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(action)

    return deduped


async def hydrate_active_memory_records_from_runtime_actions(
    context: RuntimeContext,
    actions: list[dict[str, Any]],
) -> None:
    """
    Browser runs persist accepted active-memory actions in frontend localStorage
    and send them back as active_memory_records on following turns. This probe
    has no browser, so mirror that handoff inside the test only.
    """

    for action in actions:
        if not runtime_action_found([action], "create_active_memory"):
            continue

        records = getattr(context, "active_memory_records", None)
        if records is None:
            records = []
            setattr(context, "active_memory_records", records)

        active_memory_line = render_text(action.get("active_memory", ""))
        if active_memory_line:
            if active_memory_line not in records:
                records.append(active_memory_line)
            continue

        payload = render_text(action.get("payload", ""))
        if not payload:
            continue

        if any(normalize_text(payload) in normalize_text(record) for record in records):
            continue

        before = list(records)
        await create_active_memory_runtime_record(context, payload)
        after = list(getattr(context, "active_memory_records", []) or [])

        if len(after) > len(before):
            print(
                paint("  HYDRATED ACTIVE MEMORY FROM ACTION:", "yellow", bold=True),
                flush=True,
            )
            print(
                indent_block(after[-1], prefix="    "),
                flush=True,
            )


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

        for action_name in turn.expected_runtime_actions:
            checks.append(
                {
                    "name": f"turn_{turn.index}.runtime_action_contains",
                    "target": "runtime_action",
                    "turn": turn.index,
                    "fragment": action_name,
                    "passed": runtime_action_found(turn.runtime_actions, action_name),
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
        "word_to_remember": recall_score["word_to_remember"],
        "recall_turns_in_window": recall_score["recall_turns_in_window"],
        "recall_turns_by_fallback": recall_score["recall_turns_by_fallback"],
        "memory_turns_with_recall_word": recall_score["memory_turns_with_recall_word"],
        "leaked_word_answer_turns": recall_score["leaked_word_answer_turns"],
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
    if score.get("word_to_remember"):
        print(paint(f"Word to remember: {score['word_to_remember']}", "gray"))
    if score.get("recall_turns_in_window"):
        print(paint(f"Recall question turns 2-4: {score['recall_turns_in_window']}", "gray"))
    if score.get("memory_turns_with_recall_word"):
        print(paint(f"Memory contains WORD_TO_REMEMBER after turns: {score['memory_turns_with_recall_word']}", "gray"))
    if score.get("leaked_word_answer_turns"):
        print(paint(f"Leaked WORD_TO_REMEMBER in answer turns: {score['leaked_word_answer_turns']}", "red", bold=True))

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

        if turn.get("expected_runtime_actions"):
            print(paint("EXPECTED RUNTIME ACTIONS:", "yellow", bold=True))
            for action_name in turn["expected_runtime_actions"]:
                print(
                    f"  {status_label(runtime_action_found(turn.get('runtime_actions', []), action_name))} "
                    f"{action_name}"
                )

        if turn.get("unexpected_answer"):
            print(paint("UNEXPECTED TEXT IN ANSWER:", "red", bold=True))
            for fragment in turn["unexpected_answer"]:
                print(f"  {status_label(not fragment_found(turn['answer'], fragment))} not: {fragment}")

        if turn.get("unexpected_memory"):
            print(paint("UNEXPECTED TEXT IN MEMORY:", "red", bold=True))
            for fragment in turn["unexpected_memory"]:
                print(f"  {status_label(not fragment_found(turn['memory_after_turn'], fragment))} not: {fragment}")

        print(paint("RUNTIME ACTIONS EMITTED BY MODEL:", "yellow", bold=True))
        print(indent_block(render_runtime_actions(turn.get("runtime_actions", []))))

        if PRINT_ACTIVE_MEMORY_DEBUG:
            if turn.get("context_active_memory_before_turn"):
                print(indent_block(turn["context_active_memory_before_turn"]))
            if turn.get("snapshot_active_memory_after_turn"):
                print(indent_block(turn["snapshot_active_memory_after_turn"]))

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
        self.assertIn("Сыграем в тест памяти", steps[0]["user_text"])
        self.assertIn(f"Запомни слово - {WORD_TO_REMEMBER}", steps[0]["user_text"])
        self.assertIn("напомни мне угадать это слово", steps[0]["user_text"])
        self.assertEqual(steps[0]["expected_memory"], [])
        self.assertEqual(steps[0]["expected_runtime_actions"], ["create_active_memory"])
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
                "action": "create_active_memory",
                "text": "Saving: запомнить слово Кофе для последующего теста памяти.",
            },
        ]

        actions = collect_runtime_actions_after_offsets(
            context,
            context_event_offset=0,
            websocket_message_offset=0,
            websocket_messages=websocket_messages,
        )

        self.assertTrue(runtime_action_found(actions, "create_active_memory"))
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
            action_event_offset = len(getattr(self.context, "runtime_action_events", []))
            websocket_message_offset = len(self.websocket.messages)
            state = await run_standard_turn(self.context, step["user_text"])
            answer = (
                state.final_answer
                or state.brain_response
                or self.context.runtime_turn_assistant_response
                or ""
            )
            runtime_actions = collect_runtime_actions_after_offsets(
                self.context,
                context_event_offset=action_event_offset,
                websocket_message_offset=websocket_message_offset,
                websocket_messages=self.websocket.messages,
            )
            await hydrate_active_memory_records_from_runtime_actions(
                self.context,
                runtime_actions,
            )
            memory_after_turn = build_memory_blob(self.context)
            context_active_memory_before_turn = getattr(
                self.context,
                "behavior_probe_context_active_memory_before_turn",
                "",
            )
            snapshot_active_memory_after_turn = format_active_memory_debug(
                "MEMORY CONTRACTS IN SNAPSHOT AFTER TURN",
                collect_snapshot_active_memory_entries(memory_after_turn),
            )

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
                    context_active_memory_before_turn=context_active_memory_before_turn,
                    snapshot_active_memory_after_turn=snapshot_active_memory_after_turn,
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
                    "unexpected_answer": turn.unexpected_answer,
                    "unexpected_memory": turn.unexpected_memory,
                    "expected_runtime_actions": turn.expected_runtime_actions,
                    "context_active_memory_before_turn": turn.context_active_memory_before_turn,
                    "snapshot_active_memory_after_turn": turn.snapshot_active_memory_after_turn,
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
