from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent import AgentRuntime, AgentState  # noqa: E402
from clients.registry import build_clients  # noqa: E402
from runtime.L1_memory import (  # noqa: E402
    build_runtime_memory_snapshot,
    schedule_runtime_memory_update,
)
from runtime.runtime_context import RuntimeContext, RuntimeEmitter  # noqa: E402
from utils.brain_client_utils import create_active_memory_runtime_record  # noqa: E402
from websocket import refresh_pending_brain_usage, wait_for_runtime_memory_update  # noqa: E402
from websocket.logger import WebSocketLogger  # noqa: E402


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
    expected_runtime_action_payload: list[str] = field(default_factory=list)
    context_active_memory_before_turn: str = ""
    snapshot_active_memory_after_turn: str = ""
    runtime_actions: list[dict[str, Any]] = field(default_factory=list)


class BehaviorProbeHelpers:
    def __init__(self, module_globals: dict[str, Any]):
        self.module_globals = module_globals

    def setting(self, name: str, default: Any = None) -> Any:
        return self.module_globals.get(name, default)

    def install(self) -> None:
        names = (
            "paint",
            "render_text",
            "normalize_text",
            "expected_fragments",
            "fragment_found",
            "memory_fragment_found",
            "clip_text",
            "indent_block",
            "status_label",
            "collect_dialogue_steps",
            "print_live_turn_result",
            "run_standard_turn",
            "build_memory_blob",
            "render_runtime_actions",
            "normalize_runtime_action_name",
            "runtime_action_found",
            "runtime_action_payload_contains_fragment",
            "normalize_websocket_runtime_action",
            "collect_runtime_actions_after_offsets",
            "hydrate_active_memory_records_from_runtime_actions",
            "active_memory_line_contains_fragment",
            "check_description",
            "evaluate_expected_text",
            "print_behavior_probe_report",
            "answer_has_recall_question",
            "evaluate_recall_word_behavior",
            "find_trailing_balanced_suffix_start",
            "find_trailing_balanced_parenthetical_start",
            "split_memory_contract_value_and_suffixes",
            "split_active_memory_value_and_suffixes",
            "extract_suffix_field",
            "summarize_contract_progress",
            "extract_active_memory_entries",
            "render_active_memory_entries",
            "collect_active_memory_entries_from_context",
            "collect_snapshot_active_memory_entries",
            "format_active_memory_debug",
        )
        for name in names:
            self.module_globals[name] = getattr(self, name)
        self.module_globals["CapturingWebSocket"] = self.capturing_websocket_class()
        self.module_globals["TurnResult"] = TurnResult

    def capturing_websocket_class(self):
        helpers = self

        class CapturingWebSocket:
            def __init__(self):
                self.messages = []
                self.live_message_ids = set()

            async def send_json(self, payload: dict):
                self.messages.append(payload)
                if not helpers.setting("LIVE_STREAM_MODEL_OUTPUT", False):
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
                    print(helpers.paint(f"\nSTREAM {role}:", "green", bold=True), flush=True)
                    return

                message_id = payload.get("message_id")
                if message_id not in self.live_message_ids:
                    return

                if payload_type == "message_chunk":
                    print(payload.get("chunk", ""), end="", flush=True)
                elif payload_type == "message_end":
                    print("", flush=True)
                    self.live_message_ids.discard(message_id)

        return CapturingWebSocket

    def paint(
        self,
        text: str,
        color: str | None = None,
        *,
        bold: bool = False,
        dim: bool = False,
    ) -> str:
        if not self.setting("USE_ANSI_COLORS", True):
            return text

        prefix = ""
        if bold:
            prefix += ANSI["bold"]
        if dim:
            prefix += ANSI["dim"]
        if color:
            prefix += ANSI.get(color, "")
        return f"{prefix}{text}{ANSI['reset']}"

    def render_text(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (list, tuple)):
            return "\n".join(self.render_text(item) for item in value).strip()
        return str(value).strip()

    def normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", self.render_text(text).casefold()).strip()

    def expected_fragments(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            value = value.strip()
            return [value] if value else []
        if isinstance(value, (list, tuple)):
            fragments: list[str] = []
            for item in value:
                fragments.extend(self.expected_fragments(item))
            return fragments
        value = str(value).strip()
        return [value] if value else []

    def fragment_found(self, text: str, fragment: str) -> bool:
        return self.normalize_text(fragment) in self.normalize_text(text)

    def memory_fragment_found(self, text: str, fragment: str) -> bool:
        raw_fragment = self.render_text(fragment).strip()
        field_match = re.fullmatch(r"([A-Za-z0-9_]+):", raw_fragment)

        if not field_match:
            return self.fragment_found(text, fragment)

        field_name = re.escape(field_match.group(1))
        if field_match.group(1) == "active_memory":
            field_pattern = r"active_memory(?:_\d+)?"
        else:
            field_pattern = field_name

        return re.search(rf"(?im)^\s*{field_pattern}\s*:", self.render_text(text)) is not None

    def clip_text(self, text: str, limit: int) -> str:
        text = self.render_text(text)
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + self.paint("\n... [clipped]", "gray", dim=True)

    def indent_block(self, text: str, prefix: str = "  ") -> str:
        text = self.render_text(text)
        if not text:
            return prefix + self.paint("<empty>", "gray", dim=True)
        return "\n".join(f"{prefix}{line}" for line in text.splitlines())

    def status_label(self, passed: bool) -> str:
        return self.paint("OK", "green", bold=True) if passed else self.paint("FAIL", "red", bold=True)

    def collect_dialogue_steps(self) -> list[dict[str, Any]]:
        steps: list[dict[str, Any]] = []
        index = 1

        while True:
            user_key = f"USER_TEXT_{index}"
            if user_key not in self.module_globals:
                break

            user_text = self.render_text(self.module_globals[user_key])
            if user_text:
                steps.append(
                    {
                        "index": index,
                        "user_text": user_text,
                        "expected_answer": self.expected_fragments(
                            self.module_globals.get(f"EXPECTED_TEXT_ANSWER_{index}", [])
                        ),
                        "expected_memory": self.expected_fragments(
                            self.module_globals.get(f"EXPECTED_TEXT_MEMORY_{index}", [])
                        ),
                        "expected_runtime_actions": self.expected_fragments(
                            self.module_globals.get(f"EXPECTED_RUNTIME_ACTION_{index}", [])
                        ),
                        "unexpected_runtime_actions": self.expected_fragments(
                            self.module_globals.get(f"UNEXPECTED_RUNTIME_ACTION_{index}", [])
                        ),
                        "expected_runtime_action_payload": self.expected_fragments(
                            self.module_globals.get(f"EXPECTED_RUNTIME_ACTION_PAYLOAD_{index}", [])
                        ),
                        "unexpected_answer": self.expected_fragments(
                            self.module_globals.get(f"UNEXPECTED_TEXT_ANSWER_{index}", [])
                        ),
                        "unexpected_memory": self.expected_fragments(
                            self.module_globals.get(f"UNEXPECTED_TEXT_MEMORY_{index}", [])
                        ),
                    }
                )

            index += 1

        return steps

    def create_test_context(self) -> tuple[httpx.AsyncClient, Any, RuntimeContext]:
        http_client = httpx.AsyncClient()
        websocket = self.module_globals["CapturingWebSocket"]()
        context = RuntimeContext(
            websocket=websocket,
            emitter=RuntimeEmitter(websocket),
            logger=WebSocketLogger(websocket),
            clients=build_clients(http_client),
        )

        initial_snapshot = build_runtime_memory_snapshot(
            context,
            context.runtime_memory,
        )
        context.runtime_memory_snapshots.append(initial_snapshot)
        context.runtime_memory_snapshot_index = 0

        return http_client, websocket, context

    async def async_set_up(self, test_case: Any) -> None:
        test_case.http_client, test_case.websocket, test_case.context = self.create_test_context()

    async def async_tear_down(self, test_case: Any) -> None:
        await wait_for_runtime_memory_update(test_case.context)
        await test_case.http_client.aclose()

    async def run_standard_turn(self, context: RuntimeContext, user_text: str) -> AgentState:
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

        if self.setting("PRINT_ACTIVE_MEMORY_DEBUG", False):
            context.behavior_probe_context_active_memory_before_turn = self.format_active_memory_debug(
                "MEMORY CONTRACTS PASSED TO CONTEXT BEFORE TURN",
                self.collect_active_memory_entries_from_context(
                    context,
                    source_prefix="context_before_turn",
                ),
            )

        state = AgentState(user_input=user_text)
        runtime = AgentRuntime()
        scenario_id = self.setting("SCENARIO_ID", "behavior_probe")

        await context.logger.log_system(
            f"[BEHAVIOR_PROBE] runtime=AgentRuntime scenario={scenario_id}"
        )
        await context.websocket.send_json({"type": "agent_runtime_start", "scenario": scenario_id})
        await runtime.run(state, context)
        await context.websocket.send_json({"type": "agent_runtime_end", "scenario": scenario_id})

        assistant_message = (
            state.final_answer
            or state.brain_response
            or context.runtime_turn_assistant_response
            or ""
        )

        if self.setting("RUN_MEMORY_UPDATE_AFTER_EACH_TURN", True):
            schedule_runtime_memory_update(
                context=context,
                user_message=user_text,
                assistant_message=assistant_message,
            )

            if self.setting("WAIT_FOR_MEMORY_UPDATE_AFTER_EACH_TURN", True):
                await wait_for_runtime_memory_update(context)

        context.assistant_message_count += 1
        context.turn_number += 1

        return state

    def build_memory_blob(self, context: RuntimeContext) -> str:
        parts = []
        for field_name in self.setting("MEMORY_TEXT_FIELDS_TO_INSPECT", []):
            value = getattr(context, field_name, "")
            if isinstance(value, (list, tuple)):
                value = "\n".join(self.render_text(item) for item in value if self.render_text(item))
            if value:
                parts.append(f"[{field_name}]\n{value}")
        return "\n\n".join(parts)

    def render_runtime_actions(self, actions: list[dict[str, Any]]) -> str:
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

    def print_live_turn_result(self, turn: TurnResult) -> None:
        if not self.setting("LIVE_PRINT_TURN_RESULTS", False):
            return

        score = self.evaluate_expected_text([turn])
        print(self.paint(f"\nLIVE TURN {turn.index} RESULT", "blue", bold=True), flush=True)

        if score["checks"]:
            for check in score["checks"]:
                print(
                    f"  {self.status_label(check['passed'])} {self.check_description(check)}",
                    flush=True,
                )
        else:
            print(self.paint("  No text checks for this turn.", "gray", dim=True), flush=True)

        if turn.runtime_actions:
            print(
                self.paint("  RUNTIME ACTIONS EMITTED BY MODEL:", "yellow", bold=True),
                flush=True,
            )
            print(
                self.indent_block(self.render_runtime_actions(turn.runtime_actions), prefix="    "),
                flush=True,
            )

        if self.setting("PRINT_ACTIVE_MEMORY_DEBUG", False):
            if turn.context_active_memory_before_turn:
                print(self.indent_block(turn.context_active_memory_before_turn, prefix="  "), flush=True)
            if turn.snapshot_active_memory_after_turn:
                print(self.indent_block(turn.snapshot_active_memory_after_turn, prefix="  "), flush=True)

    def normalize_runtime_action_name(self, name: str) -> str:
        return self.normalize_text(name).replace("-", "_").replace(" ", "_")

    def runtime_action_found(self, actions: list[dict[str, Any]], expected_name: str) -> bool:
        normalized_expected = self.normalize_runtime_action_name(expected_name)
        return any(
            self.normalize_runtime_action_name(str(action.get("name", ""))) == normalized_expected
            for action in actions
        )

    def runtime_action_payload_contains_fragment(
        self,
        actions: list[dict[str, Any]],
        fragment: str,
    ) -> bool:
        normalized_fragment = self.normalize_text(fragment)
        if not normalized_fragment:
            return False

        return any(
            normalized_fragment in self.normalize_text(action.get("payload", ""))
            for action in actions
        )

    def normalize_websocket_runtime_action(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        if payload.get("type") != "runtime_action":
            return None

        action_name = self.render_text(payload.get("action", ""))
        if not action_name:
            return None

        action_event: dict[str, Any] = {"name": self.normalize_runtime_action_name(action_name)}
        for key in ("id", "query", "text", "active_memory"):
            value = self.render_text(payload.get(key, ""))
            if value:
                action_event[key] = value

        delayed_memory_report = payload.get("delayed_memory_report")
        if delayed_memory_report:
            action_event["delayed_memory_report"] = delayed_memory_report

        explicit_payload = self.render_text(payload.get("payload", ""))
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
        elif action_event.get("text", "").startswith("CREATE_ACTIVE_MEMORY:"):
            action_event["payload"] = action_event["text"].split(
                "CREATE_ACTIVE_MEMORY:",
                1,
            )[1].strip()

        return action_event

    def collect_runtime_actions_after_offsets(
        self,
        context: RuntimeContext,
        *,
        context_event_offset: int,
        websocket_message_offset: int,
        websocket_messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []

        for event in getattr(context, "runtime_action_events", [])[context_event_offset:]:
            if isinstance(event, dict):
                actions.append(dict(event))

        for message in websocket_messages[websocket_message_offset:]:
            if not isinstance(message, dict):
                continue

            action = self.normalize_websocket_runtime_action(message)
            if action is not None:
                actions.append(action)

        deduped: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, str, str, str]] = set()

        for action in actions:
            base_key = (
                self.normalize_runtime_action_name(str(action.get("name", ""))),
                self.render_text(action.get("id", "")),
                self.render_text(action.get("query", "")),
                self.render_text(action.get("payload", "")),
            )
            active_memory = self.render_text(action.get("active_memory", ""))
            delayed_memory_report = self.render_text(action.get("delayed_memory_report", ""))
            key = (*base_key, active_memory, delayed_memory_report)
            if key in seen:
                continue

            duplicate_index = next(
                (
                    index
                    for index, existing_action in enumerate(deduped)
                    if (
                        (
                            self.normalize_runtime_action_name(str(existing_action.get("name", ""))),
                            self.render_text(existing_action.get("id", "")),
                            self.render_text(existing_action.get("query", "")),
                            self.render_text(existing_action.get("payload", "")),
                        )
                        == base_key
                        and (
                            not self.render_text(existing_action.get("active_memory", ""))
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
        self,
        context: RuntimeContext,
        actions: list[dict[str, Any]],
    ) -> None:
        for action in actions:
            if not self.runtime_action_found([action], "create_active_memory"):
                continue

            records = getattr(context, "active_memory_records", None)
            if records is None:
                records = []
                setattr(context, "active_memory_records", records)

            active_memory_line = self.render_text(action.get("active_memory", ""))
            if active_memory_line:
                if active_memory_line not in records:
                    records.append(active_memory_line)
                continue

            payload = self.render_text(action.get("payload", ""))
            if not payload:
                continue

            if any(self.normalize_text(payload) in self.normalize_text(record) for record in records):
                continue

            before = list(records)
            await create_active_memory_runtime_record(context, payload)
            after = list(getattr(context, "active_memory_records", []) or [])

            if len(after) > len(before):
                print(
                    self.paint("  HYDRATED ACTIVE MEMORY FROM ACTION:", "yellow", bold=True),
                    flush=True,
                )
                print(self.indent_block(after[-1], prefix="    "), flush=True)

    def active_memory_line_contains_fragment(self, memory: str, fragment: str) -> bool:
        normalized_fragment = self.normalize_text(fragment)
        if not normalized_fragment:
            return False

        for raw_line in self.render_text(memory).splitlines():
            line = raw_line.strip()
            if not line:
                continue

            normalized_line = self.normalize_text(line)
            if normalized_line.startswith("active_memory") and normalized_fragment in normalized_line:
                return True

        return False

    def check_description(self, check: dict[str, Any]) -> str:
        if check["name"].endswith("_not_contains"):
            return f"{check['target']} does not contain: {check['fragment']}"
        if check["name"].endswith("_contains"):
            return f"{check['target']} contains: {check['fragment']}"
        return f"{check['name']}: {check['fragment']}"

    def evaluate_expected_text(self, turns: list[TurnResult]) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []

        for turn in turns:
            for fragment in turn.expected_answer:
                checks.append(
                    {
                        "name": f"turn_{turn.index}.answer_contains",
                        "target": "answer",
                        "turn": turn.index,
                        "fragment": fragment,
                        "passed": self.fragment_found(turn.answer, fragment),
                    }
                )

            for fragment in turn.expected_memory:
                checks.append(
                    {
                        "name": f"turn_{turn.index}.memory_contains",
                        "target": "memory",
                        "turn": turn.index,
                        "fragment": fragment,
                        "passed": self.memory_fragment_found(turn.memory_after_turn, fragment),
                    }
                )

            for action_name in turn.expected_runtime_actions:
                checks.append(
                    {
                        "name": f"turn_{turn.index}.runtime_action_contains",
                        "target": "runtime_action",
                        "turn": turn.index,
                        "fragment": action_name,
                        "passed": self.runtime_action_found(turn.runtime_actions, action_name),
                    }
                )

            for action_name in turn.unexpected_runtime_actions:
                checks.append(
                    {
                        "name": f"turn_{turn.index}.runtime_action_not_contains",
                        "target": "runtime_action",
                        "turn": turn.index,
                        "fragment": action_name,
                        "passed": not self.runtime_action_found(turn.runtime_actions, action_name),
                    }
                )

            for fragment in turn.expected_runtime_action_payload:
                checks.append(
                    {
                        "name": f"turn_{turn.index}.runtime_action_payload_contains",
                        "target": "runtime_action_payload",
                        "turn": turn.index,
                        "fragment": fragment,
                        "passed": self.runtime_action_payload_contains_fragment(
                            turn.runtime_actions,
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
                        "passed": not self.fragment_found(turn.answer, fragment),
                    }
                )

            for fragment in turn.unexpected_memory:
                checks.append(
                    {
                        "name": f"turn_{turn.index}.memory_not_contains",
                        "target": "memory",
                        "turn": turn.index,
                        "fragment": fragment,
                        "passed": not self.memory_fragment_found(turn.memory_after_turn, fragment),
                    }
                )

        recall_score: dict[str, Any] = {}
        if self.setting("WORD_TO_REMEMBER", ""):
            recall_score = self.evaluate_recall_word_behavior(turns)
            checks.extend(recall_score["checks"])

        passed = sum(1 for check in checks if check["passed"])
        total = len(checks)
        score = {
            "passed": passed,
            "total": total,
            "ratio": passed / total if total else 1.0,
            "checks": checks,
        }
        score.update({key: value for key, value in recall_score.items() if key != "checks"})
        return score

    def print_behavior_probe_report(self, report: dict[str, Any]) -> None:
        score = report["score"]
        turns = report["turns"]

        header = f"BEHAVIOR PROBE :: {report['scenario_id']}"
        print("\n" + self.paint("=" * len(header), "cyan", bold=True))
        print(self.paint(header, "cyan", bold=True))
        print(self.paint("=" * len(header), "cyan", bold=True))

        score_color = "green" if score["ratio"] >= 0.85 else "yellow" if score["ratio"] >= 0.60 else "red"
        print(
            self.paint("Score: ", bold=True)
            + self.paint(f"{score['passed']}/{score['total']} ({score['ratio']:.0%})", score_color, bold=True)
        )
        print(self.paint(f"Title: {report['scenario_title']}", "gray"))
        if score.get("word_to_remember"):
            print(self.paint(f"Word to remember: {score['word_to_remember']}", "gray"))
        if score.get("recall_turns_in_window"):
            print(self.paint(f"Recall question turns 2-4: {score['recall_turns_in_window']}", "gray"))
        if score.get("memory_turns_with_recall_word"):
            print(
                self.paint(
                    f"Memory contains WORD_TO_REMEMBER after turns: {score['memory_turns_with_recall_word']}",
                    "gray",
                )
            )
        if score.get("leaked_word_answer_turns"):
            print(
                self.paint(
                    f"Leaked WORD_TO_REMEMBER in answer turns: {score['leaked_word_answer_turns']}",
                    "red",
                    bold=True,
                )
            )

        print("\n" + self.paint("DIALOGUE", "blue", bold=True))
        for turn in turns:
            print(self.paint(f"\n--- Turn {turn['index']} ---", "gray", bold=True))
            print(self.paint("USER:", "cyan", bold=True))
            print(self.indent_block(turn["user_text"]))

            print(self.paint("MODEL:", "green", bold=True))
            print(self.indent_block(self.clip_text(turn["answer"], self.setting("MAX_ANSWER_PREVIEW_CHARS", 1400))))

            if turn["expected_answer"]:
                print(self.paint("EXPECTED TEXT IN ANSWER:", "yellow", bold=True))
                for fragment in turn["expected_answer"]:
                    print(f"  {self.status_label(self.fragment_found(turn['answer'], fragment))} {fragment}")
            else:
                print(self.paint("EXPECTED TEXT IN ANSWER: <any answer accepted>", "gray", dim=True))

            if turn["expected_memory"]:
                print(self.paint("EXPECTED TEXT IN MEMORY:", "yellow", bold=True))
                for fragment in turn["expected_memory"]:
                    print(
                        f"  {self.status_label(self.memory_fragment_found(turn['memory_after_turn'], fragment))} "
                        f"{fragment}"
                    )
            else:
                print(self.paint("EXPECTED TEXT IN MEMORY: <any memory accepted>", "gray", dim=True))

            if turn.get("expected_runtime_actions"):
                print(self.paint("EXPECTED RUNTIME ACTIONS:", "yellow", bold=True))
                for action_name in turn["expected_runtime_actions"]:
                    print(
                        f"  {self.status_label(self.runtime_action_found(turn.get('runtime_actions', []), action_name))} "
                        f"{action_name}"
                    )

            if turn.get("unexpected_runtime_actions"):
                print(self.paint("UNEXPECTED RUNTIME ACTIONS:", "red", bold=True))
                for action_name in turn["unexpected_runtime_actions"]:
                    print(
                        f"  {self.status_label(not self.runtime_action_found(turn.get('runtime_actions', []), action_name))} "
                        f"not: {action_name}"
                    )

            if turn.get("expected_runtime_action_payload"):
                print(self.paint("EXPECTED RUNTIME ACTION PAYLOAD:", "yellow", bold=True))
                for fragment in turn["expected_runtime_action_payload"]:
                    print(
                        f"  {self.status_label(self.runtime_action_payload_contains_fragment(turn.get('runtime_actions', []), fragment))} "
                        f"{fragment}"
                    )

            if turn.get("unexpected_answer"):
                print(self.paint("UNEXPECTED TEXT IN ANSWER:", "red", bold=True))
                for fragment in turn["unexpected_answer"]:
                    print(f"  {self.status_label(not self.fragment_found(turn['answer'], fragment))} not: {fragment}")

            if turn.get("unexpected_memory"):
                print(self.paint("UNEXPECTED TEXT IN MEMORY:", "red", bold=True))
                for fragment in turn["unexpected_memory"]:
                    print(
                        f"  {self.status_label(not self.memory_fragment_found(turn['memory_after_turn'], fragment))} "
                        f"not: {fragment}"
                    )

            if turn.get("runtime_actions"):
                print(self.paint("RUNTIME ACTIONS EMITTED BY MODEL:", "yellow", bold=True))
                print(self.indent_block(self.render_runtime_actions(turn.get("runtime_actions", []))))

            if self.setting("PRINT_ACTIVE_MEMORY_DEBUG", False):
                if turn.get("context_active_memory_before_turn"):
                    print(self.indent_block(turn["context_active_memory_before_turn"]))
                if turn.get("snapshot_active_memory_after_turn"):
                    print(self.indent_block(turn["snapshot_active_memory_after_turn"]))

        print("\n" + self.paint("TEXT CHECKS", "blue", bold=True))
        if not score["checks"]:
            print(self.paint("  No expected fragments declared. This probe only prints dialogue.", "gray", dim=True))
        else:
            for check in score["checks"]:
                print(
                    f"  {self.status_label(check['passed'])} "
                    f"turn {check['turn']} {self.check_description(check)}"
                )

        final_memory = self.clip_text(report.get("final_memory", ""), self.setting("MAX_MEMORY_PREVIEW_CHARS", 2200))
        if final_memory:
            print("\n" + self.paint("FINAL MEMORY SNAPSHOT", "blue", bold=True))
            print(self.indent_block(final_memory))

        print("\n" + self.paint("COUNTERS", "blue", bold=True))
        print(f"  turns: {report['turn_number']}")
        print(f"  user messages: {report['user_message_count']}")
        print(f"  assistant messages: {report['assistant_message_count']}")
        print(f"  websocket messages: {report['websocket_message_count']}")
        print(self.paint("=" * len(header), "cyan", bold=True) + "\n")

    def answer_has_recall_question(self, answer: str, recall_word: str = "") -> bool:
        text = self.normalize_text(answer)
        if "?" not in text or "слово" not in text:
            return False

        anaphoric_recall_patterns = (
            r"\bслово\b[^?]{0,80}\?\s*(?:а\s+теперь[, ]*)?(?:како[ей]|как|что)\b[^?]{0,80}\b(?:оно|это|было|наш|секретн\w*)\b",
            r"\bсекретн\w+\s+слово\b[^?]{0,80}\?\s*(?:како[ей]|как|что)\b[^?]{0,80}\b(?:оно|это|было|наш|секретн\w*)\b",
        )
        if any(re.search(pattern, text) for pattern in anaphoric_recall_patterns):
            return True

        question_parts = [part.strip() for part in text.split("?") if "слово" in part]
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
            if "если ты помнишь" in part and not re.search(conditional_recall_trigger_pattern, part):
                continue
            if any(re.search(pattern, part) for pattern in direct_recall_patterns):
                return True

        return False

    def evaluate_recall_word_behavior(self, turns: list[TurnResult]) -> dict[str, Any]:
        recall_word = self.setting("WORD_TO_REMEMBER", "")

        window_turns = [turn for turn in turns if 2 <= turn.index <= 4]
        fallback_turns = [turn for turn in turns if 2 <= turn.index <= 5]
        recall_turns_in_window = [
            turn.index for turn in window_turns if self.answer_has_recall_question(turn.answer, recall_word)
        ]
        recall_turns_by_fallback = [
            turn.index for turn in fallback_turns if self.answer_has_recall_question(turn.answer, recall_word)
        ]
        leaked_word_answer_turns = [
            turn.index
            for turn in turns[1:]
            if recall_word and self.fragment_found(turn.answer, recall_word)
        ]
        memory_turns_with_recall_word = [
            turn.index
            for turn in turns
            if recall_word and self.fragment_found(turn.memory_after_turn, recall_word)
        ]
        memory_has_recall_word_after_turn_1 = bool(
            turns
            and recall_word
            and self.fragment_found(turns[0].memory_after_turn, recall_word)
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

    def find_trailing_balanced_suffix_start(self, value: str) -> int:
        text = self.render_text(value).rstrip()
        if not text:
            return -1

        closing_to_opening = {")": "(", "]": "["}
        opening_to_closing = {"(": ")", "[": "]"}
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
            if char in opening_to_closing or char in closing_to_opening:
                continue

        return -1

    def find_trailing_balanced_parenthetical_start(self, value: str) -> int:
        text = self.render_text(value).rstrip()
        if not text.endswith(")"):
            return -1
        return self.find_trailing_balanced_suffix_start(text)

    def split_memory_contract_value_and_suffixes(self, raw_value: str) -> tuple[str, list[str]]:
        value = self.render_text(raw_value).strip().rstrip(",")
        suffixes: list[str] = []

        while value.endswith((")", "]")):
            start = self.find_trailing_balanced_suffix_start(value)
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

    def split_active_memory_value_and_suffixes(self, raw_value: str) -> tuple[str, list[str]]:
        return self.split_memory_contract_value_and_suffixes(raw_value)

    def extract_suffix_field(self, suffix_text: str, field_name: str) -> str:
        pattern = re.compile(
            rf"\[\s*{re.escape(field_name)}\s*:\s*([^\]]+?)\s*\]",
            flags=re.IGNORECASE,
        )
        match = pattern.search(suffix_text)
        return match.group(1).strip() if match else ""

    def summarize_contract_progress(self, key: str, suffix_text: str) -> str:
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

    def extract_active_memory_entries(self, text: Any, source: str = "") -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []
        source_text = self.render_text(text)
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
            value, suffixes = self.split_memory_contract_value_and_suffixes(raw_value)
            suffix_text = " ".join(suffixes)
            entries.append(
                {
                    "source": source,
                    "key": key,
                    "value": value,
                    "suffixes": suffix_text,
                    "progress": self.summarize_contract_progress(key, suffix_text),
                    "raw": f"{key}: {raw_value}",
                }
            )

        return entries

    def render_active_memory_entries(self, entries: list[dict[str, str]]) -> str:
        if not entries:
            return self.paint("<no memory contract entries found>", "gray", dim=True)

        lines: list[str] = []
        last_source = None
        for entry in entries:
            source = entry.get("source") or "unknown"
            if source != last_source:
                lines.append(self.paint(f"[{source}]", "gray", bold=True))
                last_source = source

            suffixes = entry.get("suffixes") or self.paint("<none>", "gray", dim=True)
            progress = entry.get("progress") or self.paint("<none>", "gray", dim=True)
            lines.append(
                f"  {self.paint(entry.get('key', ''), 'cyan', bold=True)} "
                f"value={entry.get('value', '')} "
                f"progress={progress} "
                f"suffixes={suffixes}"
            )
            raw = entry.get("raw") or ""
            if raw:
                lines.append(self.paint(f"    raw: {raw}", "gray", dim=True))

        return "\n".join(lines)

    def collect_active_memory_entries_from_context(
        self,
        context: RuntimeContext,
        *,
        source_prefix: str,
    ) -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []
        seen_raw: set[tuple[str, str]] = set()

        for field_name in self.setting("CONTEXT_ACTIVE_MEMORY_DEBUG_FIELDS_TO_SCAN", []):
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

            field_entries = self.extract_active_memory_entries(
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

    def collect_snapshot_active_memory_entries(self, memory_blob: str) -> list[dict[str, str]]:
        return self.extract_active_memory_entries(memory_blob, source="post_turn_snapshot")

    def format_active_memory_debug(self, title: str, entries: list[dict[str, str]]) -> str:
        return self.paint(title, "yellow", bold=True) + "\n" + self.indent_block(
            self.render_active_memory_entries(entries)
        )
