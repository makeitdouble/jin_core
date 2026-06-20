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
injects that word into dynamic forbidden-answer checks for later turns,
and then watches whether a recall question appears during the countdown window
without revealing the word again. The exact extracted word must also appear in
runtime memory after turn 1.
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
    "Сыграем в тест памяти.\n"
    "Сейчас выбери одно простое слово.\n"
    "В этом ответе назови выбранное слово ровно один раз в формате:\n"
    "Загаданное слово: <слово>\n"
    "После этого запомни задачу: в одном случайном из следующих 3 сообщений "
    "один раз напомни мне угадать это слово.\n"
    "Само слово больше не называй.\n"
    "Пиши только просьбу угадать загаданное слово.\n"
    "Не выбирай новое слово позже.\n"
    "Твоя задача не напоминать мне в каждом сообщении, а выбрать один случайный момент.\n"
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
LIVE_STREAM_MODEL_OUTPUT = True
LIVE_PRINT_TURN_RESULTS = True
PRINT_STORED_MEMORY_DEBUG = True

USE_ANSI_COLORS = True
MAX_ANSWER_PREVIEW_CHARS = 1400
MAX_MEMORY_PREVIEW_CHARS = 2200

# Which memory fields should be displayed and searched.
MEMORY_TEXT_FIELDS_TO_INSPECT = [
    "runtime_memory",
    "runtime_l2_memory",
]

# Extra RuntimeContext fields to scan for active memory contract entries right after
# refresh_pending_brain_usage() and before AgentRuntime.run(). This makes the
# probe show what memory was available to the next brain turn, not only what
# ended up in the post-turn snapshot. Unknown/missing fields are ignored.
CONTEXT_STORED_MEMORY_DEBUG_FIELDS_TO_SCAN = [
    "runtime_memory",
    "runtime_l2_memory",
    "runtime_memory_snapshots",
    "runtime_memory_snapshot_index",
    "pending_brain_usage",
    "runtime_usage_events",
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
    first_answer = turns[0].answer if turns else ""
    extracted_word = extract_recall_word_from_first_answer(first_answer)

    window_turns = [turn for turn in turns if 2 <= turn.index <= 4]
    fallback_turns = [turn for turn in turns if 2 <= turn.index <= 5]
    recall_turns_in_window = [turn.index for turn in window_turns if answer_has_recall_question(turn.answer, extracted_word)]
    recall_turns_by_fallback = [turn.index for turn in fallback_turns if answer_has_recall_question(turn.answer, extracted_word)]
    leaked_word_answer_turns = [
        turn.index
        for turn in turns[1:]
        if extracted_word and fragment_found(turn.answer, extracted_word)
    ]
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
            "fragment": "answer contains direct recall wording without revealing the extracted word",
            "passed": bool(recall_turns_in_window),
        },
        {
            "name": "turn_2_5.recall_question_observed_by_fallback_turn",
            "target": "answer",
            "turn": "2-5",
            "fragment": "answer contains direct recall wording without revealing the extracted word",
            "passed": bool(recall_turns_by_fallback),
        },
        {
            "name": "turn_2_5.answer_does_not_reveal_extracted_recall_word",
            "target": "answer",
            "turn": "2-5",
            "fragment": "extracted recall word must not appear in answers after turn 1",
            "passed": bool(extracted_word) and not leaked_word_answer_turns,
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
      stored_memory: облако (purpose: recall challenge; status: pending)

    and countdown bracket suffixes:
      countdown_contract: remind user [current: 2] [remaining: 1]

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


def split_stored_memory_value_and_suffixes(raw_value: str) -> tuple[str, list[str]]:
    """Backward-compatible name for existing stored_memory shape tests."""

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

    current = extract_suffix_field(suffix_text, "current")
    remaining = extract_suffix_field(suffix_text, "remaining")
    count_to = extract_suffix_field(suffix_text, "count_to") or extract_suffix_field(
        suffix_text,
        "due_user_message_count",
    )

    if current or remaining or count_to:
        parts = []
        if current:
            parts.append(f"current={current}")
        if count_to:
            parts.append(f"due={count_to}")
        if remaining:
            parts.append(f"remaining={remaining}")
        return ", ".join(parts)

    current_time = extract_suffix_field(suffix_text, "current_time")
    due_at = extract_suffix_field(suffix_text, "due_at")
    if current_time or due_at:
        parts = []
        if current_time:
            parts.append(f"current_time={current_time}")
        if due_at:
            parts.append(f"due_at={due_at}")
        return ", ".join(parts)

    reminded_match = re.search(r"\breminded\s*:\s*(\d+)\b", suffix_text, flags=re.IGNORECASE)
    if key.casefold().startswith("stored_memory") and reminded_match:
        return f"reminded={reminded_match.group(1)}"

    return ""


def extract_stored_memory_entries(text: Any, source: str = "") -> list[dict[str, str]]:
    """
    Return active memory-contract entries from a text-ish blob.

    The historical function name is kept because the probe already calls it,
    but the console now shows stored_memory, open_contract and countdown_contract
    lines. This is what exposes turn/current/remaining suffixes when runtime
    actually has them.
    """

    entries: list[dict[str, str]] = []
    source_text = render_text(text)
    if not any(token in source_text for token in ("stored_memory", "open_contract", "countdown_contract")):
        return entries

    entry_pattern = re.compile(
        r"^\s*[\"']?"
        r"(?P<key>stored_memory(?:_\d+)?|open_contract(?:_\d+)?|countdown_contract(?:_\d+)?)"
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


def render_stored_memory_entries(entries: list[dict[str, str]]) -> str:
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


def collect_stored_memory_entries_from_context(
        context: RuntimeContext,
        *,
        source_prefix: str,
) -> list[dict[str, str]]:
    """
    Shallow-scan known RuntimeContext fields for memory contract lines.

    The goal is diagnostic output, not assertions: show what active recall /
    reminder contract state is present immediately before the next brain turn.
    """

    entries: list[dict[str, str]] = []
    seen_raw: set[tuple[str, str]] = set()

    for field_name in CONTEXT_STORED_MEMORY_DEBUG_FIELDS_TO_SCAN:
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
        # render_text(str(value)) is enough for the memory contract line probe.
        field_entries = extract_stored_memory_entries(
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


def collect_snapshot_stored_memory_entries(memory_blob: str) -> list[dict[str, str]]:
    return extract_stored_memory_entries(memory_blob, source="post_turn_snapshot")


def format_stored_memory_debug(title: str, entries: list[dict[str, str]]) -> str:
    return paint(title, "yellow", bold=True) + "\n" + indent_block(render_stored_memory_entries(entries))

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
    context_stored_memory_before_turn: str = ""
    snapshot_stored_memory_after_turn: str = ""


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

    if PRINT_STORED_MEMORY_DEBUG:
        if turn.context_stored_memory_before_turn:
            print(
                indent_block(turn.context_stored_memory_before_turn, prefix="  "),
                flush=True,
            )
        if turn.snapshot_stored_memory_after_turn:
            print(
                indent_block(turn.snapshot_stored_memory_after_turn, prefix="  "),
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

    context.behavior_probe_context_stored_memory_before_turn = format_stored_memory_debug(
        "MEMORY CONTRACTS PASSED TO CONTEXT BEFORE TURN",
        collect_stored_memory_entries_from_context(
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
    if score.get("extracted_recall_word"):
        print(paint(f"Extracted recall word: {score['extracted_recall_word']}", "gray"))
    if score.get("recall_turns_in_window"):
        print(paint(f"Recall question turns 2-4: {score['recall_turns_in_window']}", "gray"))
    if score.get("memory_turns_with_recall_word"):
        print(paint(f"Memory contains extracted word after turns: {score['memory_turns_with_recall_word']}", "gray"))
    if score.get("leaked_word_answer_turns"):
        print(paint(f"Leaked extracted word in answer turns: {score['leaked_word_answer_turns']}", "red", bold=True))

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

        if PRINT_STORED_MEMORY_DEBUG:
            if turn.get("context_stored_memory_before_turn"):
                print(indent_block(turn["context_stored_memory_before_turn"]))
            if turn.get("snapshot_stored_memory_after_turn"):
                print(indent_block(turn["snapshot_stored_memory_after_turn"]))

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
        self.assertIn("выбери одно простое слово", steps[0]["user_text"])
        self.assertIn("Загаданное слово: <слово>", steps[0]["user_text"])
        self.assertIn("нарисуй домик", steps[1]["user_text"])
        self.assertIn("хайку", steps[2]["user_text"])
        self.assertIn("спасибо", steps[3]["user_text"])
        self.assertIn("хорошо", steps[4]["user_text"])

    def test_extract_stored_memory_entries_splits_value_and_suffixes(self):
        blob = '[runtime_memory]\nstored_memory: облако (purpose: recall challenge; turns_left: 2; status: pending)'
        entries = extract_stored_memory_entries(blob, source="unit")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["key"], "stored_memory")
        self.assertEqual(entries[0]["value"], "облако")
        self.assertEqual(entries[0]["suffixes"], "(purpose: recall challenge; turns_left: 2; status: pending)")

    def test_extract_stored_memory_entries_keeps_nested_conditions_suffix(self):
        blob = (
            '[runtime_memory]\n'
            'stored_memory: облако '
            '(purpose: recall challenge; conditions: do not say secret word, '
            'remind one time (reminded: 0); status: pending)'
        )
        entries = extract_stored_memory_entries(blob, source="unit")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["key"], "stored_memory")
        self.assertEqual(entries[0]["value"], "облако")
        self.assertIn("conditions: do not say secret word", entries[0]["suffixes"])
        self.assertIn("reminded: 0", entries[0]["suffixes"])
        self.assertIn("status: pending", entries[0]["suffixes"])

    def test_extract_contract_entries_keeps_countdown_bracket_suffixes(self):
        blob = (
            '[runtime_memory]\n'
            'countdown_contract: ask user to recall the stored word '
            '[created_at: 2026-06-20T08:00:00] [count_from: 1] '
            '[count_to: 4] [current: 2] [remaining: 2] '
            '[trigger: ask recall question without revealing value]'
        )
        entries = extract_stored_memory_entries(blob, source="unit")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["key"], "countdown_contract")
        self.assertIn("[current: 2]", entries[0]["suffixes"])
        self.assertIn("[remaining: 2]", entries[0]["suffixes"])
        self.assertIn("current=2", entries[0]["progress"])
        self.assertIn("remaining=2", entries[0]["progress"])

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
                answer="Спасибо за слова. Кстати, продолжим игру памяти.",
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
            state = await run_standard_turn(self.context, step["user_text"])
            answer = (
                state.final_answer
                or state.brain_response
                or self.context.runtime_turn_assistant_response
                or ""
            )
            memory_after_turn = build_memory_blob(self.context)
            context_stored_memory_before_turn = getattr(
                self.context,
                "behavior_probe_context_stored_memory_before_turn",
                "",
            )
            snapshot_stored_memory_after_turn = format_stored_memory_debug(
                "MEMORY CONTRACTS IN SNAPSHOT AFTER TURN",
                collect_snapshot_stored_memory_entries(memory_after_turn),
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
                    context_stored_memory_before_turn=context_stored_memory_before_turn,
                    snapshot_stored_memory_after_turn=snapshot_stored_memory_after_turn,
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
                    "context_stored_memory_before_turn": turn.context_stored_memory_before_turn,
                    "snapshot_stored_memory_after_turn": turn.snapshot_stored_memory_after_turn,
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
