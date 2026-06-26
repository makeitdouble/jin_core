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

SCENARIO_ID = "save_word_active_memory"
SCENARIO_TITLE = "Save word into active memory"
SCENARIO_NOTES = """
Two-step probe:
1. The user greets JIN. Any answer is accepted.
2. The user asks JIN to remember the word "кукушка". Any answer is accepted,
   but runtime memory must contain an active_memory line whose description
   includes that word.
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
EXPECTED_TEXT_MEMORY_2 = [
    "active_memory",
    WORD_TO_SAVE,
]
EXPECTED_ACTIVE_MEMORY_WORD_2 = WORD_TO_SAVE
UNEXPECTED_TEXT_ANSWER_2 = []
UNEXPECTED_TEXT_MEMORY_2 = []


# =============================================================================
# TEST / REPORT SETTINGS
# =============================================================================

RUN_MEMORY_UPDATE_AFTER_EACH_TURN = True
WAIT_FOR_MEMORY_UPDATE_AFTER_EACH_TURN = True

# If False, failed expected fragments are shown in red but do not fail the test.
# Keep False for heatmap/probe mode. Set True when this becomes a regression test.
STRICT_TEXT_ASSERTIONS = True

PRINT_PRETTY_REPORT = True
PRINT_JSON_REPORT = False
PRINT_WEBSOCKET_MESSAGES = False
LIVE_STREAM_MODEL_OUTPUT = True
LIVE_PRINT_TURN_RESULTS = True

USE_ANSI_COLORS = True
MAX_ANSWER_PREVIEW_CHARS = 1400
MAX_MEMORY_PREVIEW_CHARS = 2200

# Which memory fields should be displayed and searched.
MEMORY_TEXT_FIELDS_TO_INSPECT = [
    "runtime_memory",
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
        active_memory_word_key = f"EXPECTED_ACTIVE_MEMORY_WORD_{index}"
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
                    "expected_active_memory_words": expected_fragments(
                        globals().get(active_memory_word_key, [])
                    ),
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
    expected_active_memory_words: list[str] = field(default_factory=list)
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


def active_memory_line_contains_fragment(memory: str, fragment: str) -> bool:
    normalized_fragment = normalize_text(fragment)
    if not normalized_fragment:
        return False

    for raw_line in render_text(memory).splitlines():
        line = raw_line.strip()
        if not line:
            continue

        normalized_line = normalize_text(line)
        if (
                normalized_line.startswith("active_memory")
                and normalized_fragment in normalized_line
        ):
            return True

    return False


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

        for fragment in turn.expected_active_memory_words:
            checks.append(
                {
                    "name": f"turn_{turn.index}.active_memory_contains",
                    "target": "active_memory",
                    "turn": turn.index,
                    "fragment": fragment,
                    "passed": active_memory_line_contains_fragment(
                        turn.memory_after_turn,
                        fragment,
                    ),
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

    passed = sum(1 for check in checks if check["passed"])
    total = len(checks)

    return {
        "passed": passed,
        "total": total,
        "ratio": passed / total if total else 1.0,
        "checks": checks,
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

        print(paint("RUNTIME ACTIONS EMITTED BY MODEL:", "yellow", bold=True))
        print(indent_block(render_runtime_actions(turn.get("runtime_actions", []))))

    print("\n" + paint("TEXT CHECKS", "blue", bold=True))
    if not score["checks"]:
        print(paint("  No expected fragments declared. This probe only prints dialogue.", "gray", dim=True))
    else:
        for check in score["checks"]:
            print(
                f"  {status_label(check['passed'])} "
                + (
                    f"turn {check['turn']} {check['target']} contains: {check['fragment']}"
                    if check["name"].endswith("_contains")
                    else f"turn {check['turn']} {check['target']} does not contain: {check['fragment']}"
                )
            )

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
    def test_collect_dialogue_steps_finds_save_word_steps(self):
        steps = collect_dialogue_steps()
        self.assertEqual(len(steps), 2)

        self.assertEqual(steps[0]["user_text"], "привет")
        self.assertEqual(steps[0]["expected_answer"], [])
        self.assertEqual(steps[0]["expected_memory"], [])

        self.assertIn(WORD_TO_SAVE, steps[1]["user_text"])
        self.assertEqual(steps[1]["expected_answer"], [])
        self.assertEqual(steps[1]["expected_memory"], ["active_memory", WORD_TO_SAVE])
        self.assertEqual(steps[1]["expected_active_memory_words"], [WORD_TO_SAVE])

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
                expected_active_memory_words=[WORD_TO_SAVE],
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

    async def test_simple_behavior_probe(self):
        turns: list[TurnResult] = []

        for step in collect_dialogue_steps():
            action_event_offset = len(getattr(self.context, "runtime_action_events", []))
            state = await run_standard_turn(self.context, step["user_text"])
            answer = (
                state.final_answer
                or state.brain_response
                or self.context.runtime_turn_assistant_response
                or ""
            )
            memory_after_turn = build_memory_blob(self.context)
            runtime_actions = list(
                getattr(self.context, "runtime_action_events", [])[action_event_offset:]
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
                    expected_active_memory_words=step["expected_active_memory_words"],
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
                    "expected_active_memory_words": turn.expected_active_memory_words,
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
