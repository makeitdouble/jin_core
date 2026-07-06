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
  JIN_RUN_BEHAVIOR_PROBE=1 python -m unittest tests.test_behavior_probe_delayed -v
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

SCENARIO_ID = "delayed_memory_save_after_reminder"
SCENARIO_TITLE = "Save delayed memory content after reminder request"
SCENARIO_NOTES = """
Two-step probe:
1. The user asks JIN to remind them to drink coffee in 10 minutes.
   Any answer is accepted, but JIN must emit create_active_memory.
2. The user asks JIN to save the report.
   Any answer is accepted, but JIN must emit save_delayed_memory_content.
"""

# Add more turns by appending:
#   USER_TEXT_3 = "..."
#   EXPECTED_TEXT_ANSWER_3 = ["optional answer fragment"]
#   EXPECTED_TEXT_MEMORY_3 = ["optional memory fragment"]
#   EXPECTED_RUNTIME_ACTION_3 = ["optional expected runtime action"]
#   UNEXPECTED_TEXT_ANSWER_3 = ["optional forbidden answer fragment"]
#   UNEXPECTED_TEXT_MEMORY_3 = ["optional forbidden memory fragment"]
#   UNEXPECTED_RUNTIME_ACTION_3 = ["optional forbidden runtime action"]
#
# Empty lists mean: accept any text for this part.

USER_TEXT_1 = "напомни мне через 10 минут выпить кофе"
EXPECTED_TEXT_ANSWER_1 = []
EXPECTED_TEXT_MEMORY_1 = []
EXPECTED_RUNTIME_ACTION_1 = ["create_active_memory"]
UNEXPECTED_TEXT_ANSWER_1 = []
UNEXPECTED_TEXT_MEMORY_1 = []
UNEXPECTED_RUNTIME_ACTION_1 = []

USER_TEXT_2 = "сохрани отчёт"
EXPECTED_TEXT_ANSWER_2 = []
EXPECTED_TEXT_MEMORY_2 = []
EXPECTED_RUNTIME_ACTION_2 = ["save_delayed_memory_content"]
UNEXPECTED_TEXT_ANSWER_2 = []
UNEXPECTED_TEXT_MEMORY_2 = []
UNEXPECTED_RUNTIME_ACTION_2 = []


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
    "active_memory_records",
    "delayed_memory_reports",
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


def memory_fragment_found(text: str, fragment: str) -> bool:
    """
    Memory checks that look like field labels must match an actual memory field,
    not the same words inside another field value.

    Example:
      active_memory:      -> matches a line key "active_memory:" or "active_memory_1:"
      active_memory       -> regular substring check
    """

    raw_fragment = render_text(fragment).strip()
    field_match = re.fullmatch(r"([A-Za-z0-9_]+):", raw_fragment)

    if not field_match:
        return fragment_found(text, fragment)

    field_name = re.escape(field_match.group(1))

    if field_match.group(1) == "active_memory":
        field_pattern = r"active_memory(?:_\d+)?"
    else:
        field_pattern = field_name

    return re.search(rf"(?im)^\s*{field_pattern}\s*:", render_text(text)) is not None


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
        runtime_action_key = f"EXPECTED_RUNTIME_ACTION_{index}"
        unexpected_runtime_action_key = f"UNEXPECTED_RUNTIME_ACTION_{index}"

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
                    "unexpected_runtime_actions": expected_fragments(
                        globals().get(unexpected_runtime_action_key, [])
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
    unexpected_runtime_actions: list[str] = field(default_factory=list)
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
        delayed_memory_report = action.get("delayed_memory_report")
        if delayed_memory_report:
            parts.append(f"delayed_memory_report={delayed_memory_report}")
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
        print(f"  {status_label(check['passed'])} {check_description(check)}", flush=True)

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

    delayed_memory_report = payload.get("delayed_memory_report")
    if delayed_memory_report:
        action_event["delayed_memory_report"] = delayed_memory_report

    explicit_payload = render_text(payload.get("payload", ""))
    if explicit_payload:
        action_event["payload"] = explicit_payload
    elif delayed_memory_report:
        action_event["payload"] = json.dumps(
            delayed_memory_report,
            ensure_ascii=False,
            sort_keys=True,
        )
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
    backend also keeps context.runtime_action_events. The probe should accept
    both channels because direct AgentRuntime tests do not exercise the full
    browser/localStorage loop, and older paths may only expose one of them.
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
    seen: set[tuple[str, str, str, str, str, str]] = set()

    for action in actions:
        base_key = (
            normalize_runtime_action_name(str(action.get("name", ""))),
            render_text(action.get("id", "")),
            render_text(action.get("query", "")),
            render_text(action.get("payload", "")),
        )
        active_memory = render_text(action.get("active_memory", ""))
        delayed_memory_report = render_text(action.get("delayed_memory_report", ""))
        key = (
            *base_key,
            active_memory,
            delayed_memory_report,
        )
        if key in seen:
            continue

        duplicate_index = next(
            (
                index
                for index, existing_action in enumerate(deduped)
                if (
                    (
                        normalize_runtime_action_name(str(existing_action.get("name", ""))),
                        render_text(existing_action.get("id", "")),
                        render_text(existing_action.get("query", "")),
                        render_text(existing_action.get("payload", "")),
                    )
                    == base_key
                    and (
                        not render_text(existing_action.get("active_memory", ""))
                        or not active_memory
                    )
                )
            ),
            None,
        )
        if duplicate_index is not None:
            if active_memory:
                deduped[duplicate_index]["active_memory"] = active_memory
            seen.add(key)
            continue

        seen.add(key)
        deduped.append(action)

    return deduped


async def hydrate_active_memory_records_from_runtime_actions(
    context: RuntimeContext,
    actions: list[dict[str, Any]],
) -> None:
    """
    Browser stores accepted active-memory records in localStorage and sends them
    back on following turns. This probe has no browser, so mirror that tiny
    handoff from accepted create_active_memory actions inside the test only.
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


def check_description(check: dict[str, Any]) -> str:
    if check["name"].endswith("_not_contains"):
        return f"{check['target']} does not contain: {check['fragment']}"
    return f"{check['target']} contains: {check['fragment']}"


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
                    "passed": memory_fragment_found(turn.memory_after_turn, fragment),
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

        for action_name in turn.unexpected_runtime_actions:
            checks.append(
                {
                    "name": f"turn_{turn.index}.runtime_action_not_contains",
                    "target": "runtime_action",
                    "turn": turn.index,
                    "fragment": action_name,
                    "passed": not runtime_action_found(turn.runtime_actions, action_name),
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
                    "passed": not memory_fragment_found(turn.memory_after_turn, fragment),
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
                print(f"  {status_label(memory_fragment_found(turn['memory_after_turn'], fragment))} {fragment}")
        else:
            print(paint("EXPECTED TEXT IN MEMORY: <any memory accepted>", "gray", dim=True))

        if turn.get("expected_runtime_actions"):
            print(paint("EXPECTED RUNTIME ACTIONS:", "yellow", bold=True))
            for action_name in turn["expected_runtime_actions"]:
                print(
                    f"  {status_label(runtime_action_found(turn.get('runtime_actions', []), action_name))} "
                    f"{action_name}"
                )

        if turn.get("unexpected_runtime_actions"):
            print(paint("UNEXPECTED RUNTIME ACTIONS:", "red", bold=True))
            for action_name in turn["unexpected_runtime_actions"]:
                print(
                    f"  {status_label(not runtime_action_found(turn.get('runtime_actions', []), action_name))} "
                    f"not: {action_name}"
                )

        if turn.get("unexpected_answer"):
            print(paint("UNEXPECTED TEXT IN ANSWER:", "red", bold=True))
            for fragment in turn["unexpected_answer"]:
                print(f"  {status_label(not fragment_found(turn['answer'], fragment))} not: {fragment}")

        if turn.get("unexpected_memory"):
            print(paint("UNEXPECTED TEXT IN MEMORY:", "red", bold=True))
            for fragment in turn["unexpected_memory"]:
                print(f"  {status_label(not memory_fragment_found(turn['memory_after_turn'], fragment))} not: {fragment}")

        print(paint("RUNTIME ACTIONS EMITTED BY MODEL:", "yellow", bold=True))
        print(indent_block(render_runtime_actions(turn.get("runtime_actions", []))))

    print("\n" + paint("TEXT CHECKS", "blue", bold=True))
    if not score["checks"]:
        print(paint("  No expected fragments declared. This probe only prints dialogue.", "gray", dim=True))
    else:
        for check in score["checks"]:
            print(
                f"  {status_label(check['passed'])} "
                f"turn {check['turn']} {check_description(check)}"
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
    def test_collect_dialogue_steps_finds_delayed_memory_steps(self):
        steps = collect_dialogue_steps()
        self.assertEqual(len(steps), 2)

        self.assertEqual(steps[0]["user_text"], "напомни мне через 10 минут выпить кофе")
        self.assertEqual(steps[0]["expected_answer"], [])
        self.assertEqual(steps[0]["expected_memory"], [])
        self.assertEqual(steps[0]["expected_runtime_actions"], ["create_active_memory"])
        self.assertEqual(steps[0]["unexpected_runtime_actions"], [])

        self.assertEqual(steps[1]["user_text"], "сохрани отчёт")
        self.assertEqual(steps[1]["expected_answer"], [])
        self.assertEqual(steps[1]["expected_memory"], [])
        self.assertEqual(steps[1]["expected_runtime_actions"], ["save_delayed_memory_content"])
        self.assertEqual(steps[1]["unexpected_runtime_actions"], [])

    def test_evaluator_checks_declared_runtime_actions(self):
        turns = [
            TurnResult(
                index=1,
                user_text=USER_TEXT_1,
                answer="Поставлено напоминание. Через 10 минут я напомню выпить кофе.",
                memory_after_turn="active_memory_1: Reminder to drink coffee in 10 minutes",
                expected_answer=[],
                expected_memory=[],
                unexpected_answer=[],
                unexpected_memory=[],
                expected_runtime_actions=["create_active_memory"],
                unexpected_runtime_actions=[],
                runtime_actions=[
                    {
                        "name": "create_active_memory",
                        "payload": "Reminder to drink coffee in 10 minutes",
                    },
                ],
            ),
            TurnResult(
                index=2,
                user_text=USER_TEXT_2,
                answer="Сохранила отчёт.",
                memory_after_turn="delayed_memory_reports: coffee reminder report",
                expected_answer=[],
                expected_memory=[],
                unexpected_answer=[],
                unexpected_memory=[],
                expected_runtime_actions=["save_delayed_memory_content"],
                unexpected_runtime_actions=[],
                runtime_actions=[
                    {
                        "name": "save_delayed_memory_content",
                        "payload": "coffee reminder report",
                    },
                ],
            ),
        ]

        score = evaluate_expected_text(turns)
        self.assertEqual(score["passed"], score["total"])

    def test_evaluator_fails_when_second_turn_misses_delayed_save_action(self):
        turns = [
            TurnResult(
                index=2,
                user_text=USER_TEXT_2,
                answer="Сохранила.",
                memory_after_turn="",
                expected_answer=[],
                expected_memory=[],
                unexpected_answer=[],
                unexpected_memory=[],
                expected_runtime_actions=["save_delayed_memory_content"],
                unexpected_runtime_actions=[],
                runtime_actions=[],
            ),
        ]

        score = evaluate_expected_text(turns)

        self.assertEqual(score["passed"], 0)
        self.assertEqual(score["total"], 1)
        self.assertEqual(score["checks"][0]["name"], "turn_2.runtime_action_contains")

    def test_collect_runtime_actions_reads_websocket_create_active_memory_action(self):
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
                "text": "Saving: Reminder to drink coffee in 10 minutes",
                "active_memory": "active_memory_1: Reminder to drink coffee in 10 minutes",
            },
        ]

        actions = collect_runtime_actions_after_offsets(
            context,
            context_event_offset=0,
            websocket_message_offset=0,
            websocket_messages=websocket_messages,
        )

        self.assertTrue(runtime_action_found(actions, "create_active_memory"))

    def test_collect_runtime_actions_reads_websocket_delayed_memory_action(self):
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
                "action": "save_delayed_memory_content",
                "status": "completed",
                "text": "Saving delayed memory",
                "delayed_memory_report": {
                    "coffee_reminder_report": {
                        "title": "Coffee Reminder Report",
                        "summary": "Reminder to drink coffee in 10 minutes.",
                    },
                },
            },
        ]

        actions = collect_runtime_actions_after_offsets(
            context,
            context_event_offset=0,
            websocket_message_offset=0,
            websocket_messages=websocket_messages,
        )

        self.assertTrue(runtime_action_found(actions, "save_delayed_memory_content"))
        self.assertIn("delayed_memory_report", actions[0])
        self.assertIn("coffee_reminder_report", actions[0]["payload"])

    def test_collect_runtime_actions_dedupes_context_and_websocket_views(self):
        websocket = CapturingWebSocket()
        context = RuntimeContext(
            websocket=websocket,
            emitter=RuntimeEmitter(websocket),
            logger=WebSocketLogger(websocket),
            clients={},
        )
        context.runtime_action_events.append(
            {
                "name": "create_active_memory",
                "payload": "Reminder to drink coffee in 10 minutes",
            }
        )
        websocket_messages = [
            {
                "type": "runtime_action",
                "action": "create_active_memory",
                "text": "Saving: Reminder to drink coffee in 10 minutes",
                "active_memory": "active_memory_1: Reminder to drink coffee in 10 minutes",
            },
        ]

        actions = collect_runtime_actions_after_offsets(
            context,
            context_event_offset=0,
            websocket_message_offset=0,
            websocket_messages=websocket_messages,
        )

        self.assertEqual(len(actions), 1)
        self.assertTrue(runtime_action_found(actions, "create_active_memory"))
        self.assertIn(
            "active_memory",
            actions[0],
        )

    def test_check_description_handles_not_contains(self):
        self.assertEqual(
            check_description(
                {
                    "name": "turn_1.answer_not_contains",
                    "target": "answer",
                    "fragment": "<",
                }
            ),
            "answer does not contain: <",
        )

    def test_memory_field_check_does_not_match_field_name_inside_value(self):
        self.assertFalse(
            memory_fragment_found(
                "last_jin_response: save_delayed_memory_content was discussed as plain text.",
                "save_delayed_memory_content:",
            )
        )

    def test_memory_field_check_matches_delayed_memory_line_key(self):
        self.assertTrue(
            memory_fragment_found(
                "last_jin_response: ok\nsave_delayed_memory_content: Coffee reminder report saved.",
                "save_delayed_memory_content:",
            )
        )


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
                    unexpected_runtime_actions=step["unexpected_runtime_actions"],
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
                    "unexpected_runtime_actions": turn.unexpected_runtime_actions,
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
