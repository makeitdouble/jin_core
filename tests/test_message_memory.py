import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from rules.assembler import (
    build_brain_system_prompt,
)
from clients.brain_context_builder import (
    build_session_actions_history_context,
)
from runtime import (
    DEFAULT_RUNTIME_MEMORY,
    L2_PATCH_WINDOW,
    RUNTIME_MEMORY_SUMMARIZER_RUNTIME_ID,
    RuntimeContext,
    build_interrupted_assistant_message,
    build_runtime_l2_memory_system_prompt,
    build_runtime_memory_system_prompt,
    build_runtime_memory_user_prompt,
    build_runtime_session_memory_system_prompt,
    build_runtime_session_memory_user_prompt,
    maybe_summarize_runtime_l2_memory,
    maybe_summarize_runtime_session_memory,
    record_runtime_l1_diff,
    schedule_interrupted_runtime_memory_update,
    schedule_runtime_memory_update,
    summarize_runtime_memory,
)
from runtime.L1_memory import (
    apply_runtime_response_feedback,
    build_runtime_response_feedback_value,
    normalize_runtime_response_feedback,
    ask_runtime_memory_model,
    summarize_runtime_memory_pending_turns,
)
from runtime.L1_memory_utils import (
    build_runtime_memory_context_text,
    build_runtime_memory_snapshot,
    enforce_runtime_turn_fields,
    get_strength_zones,
    normalize_compound_runtime_memory_lines,
    parse_runtime_memory_lines,
    quote_runtime_user_message_value,
)
from utils.runtime_actions import (
    refresh_active_memory_runtime_metadata,
    remove_active_memory_entries,
    strip_active_memory_runtime_metadata,
)
from runtime.L3_memory_utils import (
    build_l3_session_memory_max_tokens,
)
from runtime.L3_memory_rules import (
    L3_OUTPUT_MAX_TOKENS,
)
from runtime.L2_memory_rules import (
    BEHAVIOR_VS_INTENT,
    CONFIRMABLE_KEYS,
    EVIDENCE_LINE_LIFECYCLE,
    OCCURRENCE_COUNTING,
    OUTPUT_FORMAT,
    PATTERN_EVIDENCE_LINES,
    PATTERN_FAMILY_DEDUPLICATION,
    ROLE,
    RUNTIME_L2_MEMORY_SYSTEM_PROMPT,
    SELF_LEARNING_GUARD,
    SPAN_METADATA,
)
from runtime.L2_memory_utils import (
    extract_runtime_l2_pattern_evidence_lines,
    merge_runtime_l2_pattern_evidence_memory,
    normalize_l2_pattern_evidence_example,
    remove_runtime_l2_pattern_evidence_lines,
)
from runtime.registry import (
    runtime_state,
)
from config_loader import (
    config,
)


def assert_contains_text(test_case, text: str, needle: str) -> None:
    test_case.assertTrue(
        needle in text,
        f"expected text to contain: {needle!r}",
    )


def assert_not_contains_text(test_case, text: str, needle: str) -> None:
    test_case.assertFalse(
        needle in text,
        f"expected text to omit: {needle!r}",
    )


class RuntimeMemoryCompoundLineTests(unittest.TestCase):

    def test_normalize_compound_runtime_memory_lines_splits_sentence_glued_keys(self):
        memory = (
            "active_topic: Drawing a house using text format. "
            "user_intent: Initial request was for an image/drawing. "
            "jin_last_action: Provided ASCII art representation [trace: 0.50]"
        )

        self.assertEqual(
            normalize_compound_runtime_memory_lines(memory),
            "\n".join([
                "active_topic: Drawing a house using text format.",
                "user_intent: Initial request was for an image/drawing.",
                "jin_last_action: Provided ASCII art representation [trace: 0.50]",
            ]),
        )

    def test_normalize_compound_runtime_memory_lines_keeps_plain_sentence_colons(self):
        memory = (
            "last_jin_response: Пример: можно оставить внутри значения. "
            "user_message: \"ок\""
        )

        self.assertEqual(
            normalize_compound_runtime_memory_lines(memory),
            "\n".join([
                "last_jin_response: Пример: можно оставить внутри значения.",
                "user_message: \"ок\"",
            ]),
        )


    def test_normalize_compound_runtime_memory_lines_escapes_multiline_ascii_value(self):
        memory = "\n".join([
            "last_jin_response: Я нарисовал домик:",
            r" /\\",
            r"/  \\",
            "|---|",
            "session_status: Waiting for next request",
        ])

        self.assertEqual(
            normalize_compound_runtime_memory_lines(memory),
            "\n".join([
                r"last_jin_response: Я нарисовал домик:\n/\\\n/  \\\n|---|",
                "session_status: Waiting for next request",
            ]),
        )

    def test_parse_runtime_memory_lines_keeps_multiline_ascii_inside_value(self):
        memory = "\n".join([
            "last_jin_response: Я нарисовал домик:",
            r" /\\",
            r"/  \\",
            "|---|",
            "session_status: Waiting for next request",
        ])

        lines = parse_runtime_memory_lines(memory)

        self.assertEqual(
            [line["key"] for line in lines],
            ["last_jin_response", "session_status"],
        )
        self.assertEqual(
            lines[0]["value"],
            r"Я нарисовал домик:\n/\\\n/  \\\n|---|",
        )


class FakeServiceClient:

    def __init__(
        self,
        response_text,
        finish_reasons=None,
        usage=None,
        context_window=None,
    ):

        self.response_text = response_text
        self.finish_reasons = list(
            finish_reasons
            or []
        )
        self.usage = usage
        self.context_window = context_window
        self.calls = []

    async def resolve_request_context_window(self):

        return self.context_window

    async def ask(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
        timeout: float | None = None,
    ):

        self.calls.append({
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": timeout,
        })

        if isinstance(
            self.response_text,
            Exception,
        ):
            raise self.response_text

        if isinstance(
            self.response_text,
            list,
        ):
            content = self.response_text[
                len(
                    self.calls
                )
                - 1
            ]
        else:
            content = self.response_text

        choice = {
            "message": {
                "content": content,
            },
        }

        if self.finish_reasons:
            choice["finish_reason"] = (
                self.finish_reasons.pop(0)
            )

        response = {
            "choices": [
                choice,
            ],
        }

        if self.usage is not None:
            response["usage"] = self.usage

        return response


class FakeLogger:

    def __init__(self):
        self.service_logs = []
        self.summarizer_logs = []
        self.active_memory_logs = []
        self.runtime_logs = []
        self.errors = []

    async def log_runtime(
        self,
        message: str,
    ):

        self.runtime_logs.append(
            message
        )

    async def log_service(
        self,
        message: str,
    ):

        self.service_logs.append(
            message
        )

    async def log_summarizer(
            self,
            message: str,
            details: str | None = None,
    ):

        self.summarizer_logs.append(
            (
                message,
                details,
            )
        )

    async def log_active_memory(
            self,
            message: str,
            details: str | None = None,
            event: str | None = None,
    ):

        self.active_memory_logs.append(
            (
                message,
                details,
                event,
            )
        )

    async def log_error(
        self,
        message: str,
        details: str | None = None,
    ):

        self.errors.append(
            (
                message,
                details,
            )
        )


class MessageMemoryTests(
    unittest.IsolatedAsyncioTestCase
):

    def test_runtime_memory_user_prompt_omits_empty_session_fallback(self):

        prompt = build_runtime_memory_user_prompt(
            current_memory="",
            user_message="hello",
            assistant_message="hi",
        )

        self.assertNotIn(
            DEFAULT_RUNTIME_MEMORY,
            prompt,
        )
        self.assertNotIn(
            "Current runtime memory:",
            prompt,
        )
        self.assertNotIn(
            "Current L2 pattern memory",
            prompt,
        )
        self.assertNotIn(
            "Occurrences: 2",
            prompt,
        )

    def test_runtime_memory_user_prompt_omits_default_note_line(self):

        prompt = build_runtime_memory_user_prompt(
            current_memory=(
                f"note: {DEFAULT_RUNTIME_MEMORY}"
            ),
            user_message="hello",
            assistant_message="hi",
        )

        self.assertNotIn(
            DEFAULT_RUNTIME_MEMORY,
            prompt,
        )
        self.assertNotIn(
            "Current runtime memory:",
            prompt,
        )

    def test_runtime_memory_user_prompt_keeps_real_memory(self):

        prompt = build_runtime_memory_user_prompt(
            current_memory="session_status: active",
            user_message="hello",
            assistant_message="hi",
        )

        self.assertIn(
            "Current runtime memory:\nsession_status: active",
            prompt,
        )

    def test_runtime_memory_user_prompt_omits_hot_traces(self):

        prompt = build_runtime_memory_user_prompt(
            current_memory="user_message: hello",
            user_message="hello",
            assistant_message="hi",
            strength_zones=get_strength_zones([
                {
                    "key": "user_message",
                    "strength": 0.9,
                },
                {
                    "key": "user_idle",
                    "strength": 0.9,
                },
            ]),
        )

        self.assertNotIn(
            "hot_traces:",
            prompt,
        )
        self.assertNotIn(
            "user_idle",
            prompt,
        )
        self.assertNotIn(
            "Memory traces (pheromone strength)",
            prompt,
        )
        self.assertNotIn(
            "Crystallized (stable facts)",
            prompt,
        )
        self.assertNotIn(
            "Fading (deprioritize)",
            prompt,
        )

    def test_first_brain_prompt_includes_default_runtime_memory(self):

        context = RuntimeContext(
            websocket=object(),
            emitter=object(),
            logger=object(),
            clients={},
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_WEB_SEARCH": False,
            },
        )

        self.assertIn(
            "<RUNTIME_MEMORY>",
            prompt,
        )
        self.assertIn(
            DEFAULT_RUNTIME_MEMORY,
            prompt,
        )

    def test_brain_prompt_places_user_idle_in_runtime_memory(self):

        context = RuntimeContext(
            websocket=object(),
            emitter=object(),
            logger=object(),
            clients={},
        )
        context.runtime_user_idle_seconds = 2

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_WEB_SEARCH": False,
            },
        )

        self.assertNotIn(
            "<USER_IDLE>",
            prompt,
        )
        self.assertIn(
            "<RUNTIME_MEMORY>",
            prompt,
        )
        self.assertIn(
            f"note: {DEFAULT_RUNTIME_MEMORY}",
            prompt,
        )
        self.assertIn(
            "user_idle: 2s",
            prompt,
        )

        snapshot = build_runtime_memory_snapshot(
            context,
            context.runtime_memory,
        )

        self.assertEqual(
            snapshot["turn_number"],
            0,
        )
        self.assertEqual(
            snapshot["user_message_count"],
            0,
        )
        self.assertEqual(
            snapshot["assistant_message_count"],
            0,
        )
        self.assertIn(
            f"note: {DEFAULT_RUNTIME_MEMORY}",
            snapshot["raw_memory"],
        )
        self.assertIn(
            "user_idle: 2s",
            snapshot["raw_memory"],
        )

    def test_runtime_memory_snapshot_persists_session_counters(self):

        context = RuntimeContext(
            websocket=object(),
            emitter=object(),
            logger=object(),
            clients={},
        )
        context.runtime_memory = "topic: reconnect counters"
        context.turn_number = 14
        context.user_message_count = 15
        context.assistant_message_count = 14

        snapshot = build_runtime_memory_snapshot(
            context,
            context.runtime_memory,
        )

        self.assertEqual(
            snapshot["turn_number"],
            14,
        )
        self.assertEqual(
            snapshot["user_message_count"],
            15,
        )
        self.assertEqual(
            snapshot["assistant_message_count"],
            14,
        )
        self.assertEqual(
            snapshot["raw_memory"],
            "topic: reconnect counters",
        )

    def test_runtime_memory_context_replaces_stale_user_idle(self):

        context = RuntimeContext(
            websocket=object(),
            emitter=object(),
            logger=object(),
            clients={},
        )
        context.runtime_memory = (
            "active topic: Metaphorical identity query\n"
            "user_idle: 3m 3s (trace: 0.50)"
        )
        context.runtime_user_idle_seconds = 9

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_WEB_SEARCH": False,
            },
        )

        self.assertEqual(
            prompt.count("user_idle:"),
            1,
        )
        self.assertIn(
            "user_idle: 9s",
            prompt,
        )
        self.assertNotIn(
            "user_idle: 3m 3s",
            prompt,
        )

        snapshot = build_runtime_memory_snapshot(
            context,
            context.runtime_memory,
        )

        self.assertEqual(
            snapshot["raw_memory"].count("user_idle:"),
            1,
        )
        self.assertIn(
            "user_idle: 9s",
            snapshot["raw_memory"],
        )
        self.assertNotIn(
            "user_idle: 3m 3s",
            snapshot["raw_memory"],
        )

    def test_runtime_memory_prompt_focuses_on_summary_depth(self):

        prompt = build_runtime_memory_system_prompt()

        # Keep this test focused on durable L1 prompt contracts, not exact wording.
        # Rules text is intentionally editable and should not break tests on every polish.
        for required_text in (
                "runtime L1 memory summarizer",
                "Return only the new compressed L1 memory state",
                "Every memory line must be a complete key:value entry",
                "user_fact",
                "jin_fact",
        ):
            assert_contains_text(
                self,
                prompt,
                required_text,
            )

        for conditional_text in (
                "L2_pattern_evidence_N",
                "active_memory and active_memory_N are high-priority active recall contracts",
                "The user asked JIN to remember a specific value",
                "identity_state: JIN identity remains unchanged",
        ):
            assert_not_contains_text(
                self,
                prompt,
                conditional_text,
            )

        for removed_text in (
                "space exploration costs",
                "assistant established",
                "after one completed user/JIN turn",
        ):
            assert_not_contains_text(
                self,
                prompt,
                removed_text,
            )

    def test_runtime_l2_memory_prompt_defines_pattern_layer(self):

        prompt = build_runtime_l2_memory_system_prompt()

        self.assertEqual(
            prompt,
            RUNTIME_L2_MEMORY_SYSTEM_PROMPT,
        )

        # Verify that the builder keeps every dedicated L2 rules section.
        for rules_section in (
                ROLE,
                OUTPUT_FORMAT,
                BEHAVIOR_VS_INTENT,
                SPAN_METADATA,
                OCCURRENCE_COUNTING,
                PATTERN_EVIDENCE_LINES,
                EVIDENCE_LINE_LIFECYCLE,
                PATTERN_FAMILY_DEDUPLICATION,
                SELF_LEARNING_GUARD,
                CONFIRMABLE_KEYS,
        ):
            self.assertIn(
                rules_section,
                prompt,
            )

    def test_l2_pattern_evidence_merge_preserves_first_seen_and_deduplicates(self):

        merged = merge_runtime_l2_pattern_evidence_memory(
            previous_memory=(
                "possible pattern: old line. Occurrences: 1; "
                "first_seen_snapshot: 5; last_seen_snapshot: 5; "
                "evidence summary: banana question; confidence: medium\n"
                'L2_pattern_evidence_1: user repeatedly sending message - "что такое бананы" '
                "[ first_seen_turn_snapshot: 5 ] [ last_seen_turn_snapshot: 5 ] [ occurrences: 1 ]"
            ),
            candidate_memory=(
                "possible pattern: updated line. Occurrences: 2; "
                "first_seen_snapshot: 5; last_seen_snapshot: 10; "
                "evidence summary: banana question; confidence: medium\n"
                'L2_pattern_evidence_2: user repeatedly sending message - "что такое бананы" '
                "[ last_seen_turn_snapshot: 10 ] [ occurrences: 2 ]"
            ),
        )

        self.assertIn(
            "possible pattern: updated line",
            merged,
        )
        self.assertEqual(
            1,
            merged.count(
                "L2_pattern_evidence_"
            ),
        )
        self.assertIn(
            "L2_pattern_evidence_1:",
            merged,
        )
        self.assertIn(
            "что такое бананы",
            merged,
        )
        self.assertIn(
            "[ first_seen_turn_snapshot: 5 ]",
            merged,
        )
        self.assertIn(
            "[ last_seen_turn_snapshot: 10 ]",
            merged,
        )

    def test_l2_candidate_evidence_lines_are_removed_before_deterministic_merge(self):

        cleaned = remove_runtime_l2_pattern_evidence_lines(
            "possible pattern: repeated message. Occurrences: 4\n"
            'L2_pattern_evidence_1: user repeatedly sending one message [ quote: "ping" ] '
            "[ first_seen_turn_snapshot: 9 ] [ last_seen_turn_snapshot: 10 ] [ occurrences: 4 ]\n"
            "scope: current session"
        )

        self.assertEqual(
            "possible pattern: repeated message. Occurrences: 4\n"
            "scope: current session",
            cleaned,
        )

    def test_embedded_l2_pattern_evidence_is_extracted_for_runtime_display(self):

        runtime_l2_memory = (
            "possible pattern: User initiates a request for abstract creative content. "
            'Occurrences: 1; evidence: [ user_message: "draw something unusual" ]; '
            "L2_pattern_evidence_3: User initiates a request for abstract creative content. "
            '[ quote: "draw something unusual" ] '
            "[ first_seen_turn_snapshot: 4 ] "
            "[ last_seen_turn_snapshot: 4 ]"
        )

        evidence_lines = extract_runtime_l2_pattern_evidence_lines(
            runtime_l2_memory
        )

        self.assertEqual(
            [
                "L2_pattern_evidence_3: User initiates a request for abstract creative content. "
                '[ quote: "draw something unusual" ] '
                "[ first_seen_turn_snapshot: 4 ] "
                "[ last_seen_turn_snapshot: 4 ]",
            ],
            evidence_lines,
        )

        rendered = build_runtime_memory_context_text(
            "current_request: waiting",
            SimpleNamespace(
                runtime_l2_memory=runtime_l2_memory,
            ),
        )

        self.assertIn(
            "L2_pattern_evidence_3:",
            rendered,
        )

    def test_l2_pattern_evidence_example_normalizer_strips_spaces_commas_and_dots(self):

        self.assertEqual(
            "чтотакоебананы",
            normalize_l2_pattern_evidence_example(
                " Что, такое. бананы "
            ),
        )

    def test_interrupted_assistant_message_marks_incomplete(self):

        message = build_interrupted_assistant_message(
            user_message="Tell me a story.",
            assistant_message="Once upon a",
        )

        self.assertIn(
            "interrupted by the user",
            message,
        )
        self.assertIn(
            "incomplete",
            message,
        )
        self.assertIn(
            "Do not treat this turn as resolved",
            message,
        )
        self.assertIn(
            "Tell me a story.",
            message,
        )
        self.assertIn(
            "Once upon a",
            message,
        )

    def test_guard_interrupted_assistant_message_includes_reason_quote(self):

        message = build_interrupted_assistant_message(
            user_message="Use a skill.",
            assistant_message="Partial answer",
            interruption_reason="Repeated sentence loop detected.",
            interruption_quote="Wait, I should use append_skill first.",
        )

        self.assertIn(
            "interrupted before completion",
            message,
        )
        self.assertIn(
            "Repeated sentence loop detected.",
            message,
        )
        self.assertIn(
            '"Wait, I should use append_skill first."',
            message,
        )
        self.assertNotIn(
            "interrupted by the user",
            message,
        )

    def test_brain_prompt_includes_runtime_memory(self):

        context = SimpleNamespace(
            runtime_memory=(
                "The user recently asked about Lamborghini pricing."
            ),
            deep_thought_count=0,
            runtime_search_result="",
            runtime_search_result_id="",
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_WEB_SEARCH": False,
            },
        )

        self.assertIn(
            "<RUNTIME_MEMORY>",
            prompt,
        )
        self.assertIn(
            "Lamborghini pricing",
            prompt,
        )

    def test_brain_prompt_places_runtime_state_before_session_actions_history(self):

        context = SimpleNamespace(
            runtime_memory="",
            deep_thought_count=0,
            runtime_search_result="",
            runtime_search_result_id="",
            turn_number=1,
            user_message_count=2,
            assistant_message_count=1,
            runtime_appended_skills=[
                {
                    "name": "wildcards",
                },
            ],
            runtime_session_action_history=[
                {
                    "text": "Listed skills",
                    "created_at": 40.0,
                },
                {
                    "text": "Appended skill: wildcards",
                    "created_at": 940.0,
                },
                {
                    "text": "Listed wildcards",
                    "created_at": 998.0,
                },
            ],
        )

        with patch(
            "clients.brain_context_builder.time.time",
            return_value=1000.0,
        ):
            prompt = build_brain_system_prompt(
                context=context,
                runtime_actions={
                    "CAN_WEB_SEARCH": False,
                    "CAN_USE_ASSETS": True,
                },
            )

        self.assertTrue(
            prompt.startswith(
                "<TOOLS_RESULTS>"
            ),
        )
        self.assertLess(
            prompt.index("</TOOLS_RESULTS>"),
            prompt.index("<RUNTIME_MEMORY>"),
        )
        self.assertLess(
            prompt.index("<RUNTIME_MEMORY>"),
            prompt.index("<CURRENT_TRUSTED_RUNTIME_VARIABLES>"),
        )
        self.assertLess(
            prompt.index("<CURRENT_TRUSTED_RUNTIME_VARIABLES>"),
            prompt.index("<CURRENT_SESSION_STATE>"),
        )
        self.assertLess(
            prompt.index("<CURRENT_SESSION_STATE>"),
            prompt.index("<CURRENT_APPENDED_SKILLS>"),
        )
        self.assertLess(
            prompt.index("<CURRENT_APPENDED_SKILLS>"),
            prompt.index("<SESSION_ACTIONS_HISTORY>"),
        )
        self.assertIn(
            "Total messages count:         4",
            prompt,
        )
        self.assertIn(
            "<CURRENT_APPENDED_SKILLS>\n    1. wildcards\n</CURRENT_APPENDED_SKILLS>",
            prompt,
        )
        self.assertIn(
            "1. Listed skills ( 16m ago )",
            prompt,
        )
        self.assertIn(
            "2. Appended skill: wildcards ( 1m ago )",
            prompt,
        )
        self.assertIn(
            "3. Listed wildcards ( 2s ago )",
            prompt,
        )
        self.assertLess(
            prompt.index("<SESSION_ACTIONS_HISTORY>"),
            prompt.index("I identify myself as JIN"),
        )

    def test_current_action_age_starts_at_one_second(self):

        context = SimpleNamespace(
            runtime_current_turn_id="turn_000002",
            runtime_turn_started_at=1000.0,
            runtime_action_sequence_turn_ids=[
                "turn_000002",
            ],
            runtime_session_action_history=[
                {
                    "text": "ASSET_ACTION",
                    "created_at": 1000.0,
                    "runtime_turn_id": "turn_000002",
                },
            ],
        )

        with patch(
            "clients.brain_context_builder.time.time",
            return_value=1000.0,
        ):
            history = build_session_actions_history_context(
                context,
                current_sequence=True,
            )

        self.assertIn(
            "Step 1 - ASSET_ACTION ( 1s ago )",
            history,
        )
        self.assertNotIn(
            "( 0s ago )",
            history,
        )

    def test_current_actions_history_filters_older_session_actions(self):

        context = SimpleNamespace(
            runtime_current_turn_id="turn_000002",
            runtime_turn_started_at=940.0,
            runtime_action_sequence_turn_ids=[
                "turn_000002",
            ],
            runtime_session_action_history=[
                {
                    "text": "SAVE_ACTIVE_MEMORY",
                    "created_at": 800.0,
                    "runtime_turn_id": "turn_000001",
                },
                {
                    "text": "STALE_SAME_TURN",
                    "created_at": 900.0,
                    "runtime_turn_id": "turn_000002",
                },
                {
                    "text": "LIST_SKILLS",
                    "created_at": 945.0,
                    "runtime_turn_id": "turn_000002",
                },
                {
                    "text": "APPEND_SKILL",
                    "created_at": 998.0,
                    "runtime_turn_id": "turn_000002",
                },
            ],
        )

        with patch(
            "clients.brain_context_builder.time.time",
            return_value=1000.0,
        ):
            history = build_session_actions_history_context(
                context,
                current_sequence=True,
            )

        self.assertEqual(
            history,
            (
                "<CURRENT_SEQUENCE>\n"
                "    --- Sequence started ---\n"
                "    Step 1 - LIST_SKILLS ( 55s ago )\n"
                "    Step 2 - APPEND_SKILL ( 2s ago )\n"
                "</CURRENT_SEQUENCE>"
            ),
        )
        self.assertNotIn(
            "SAVE_ACTIVE_MEMORY",
            history,
        )
        self.assertNotIn(
            "STALE_SAME_TURN",
            history,
        )
        self.assertNotIn(
            "Sequence ended",
            history,
        )

    def test_completed_sequence_is_wrapped_in_session_history(self):

        context = SimpleNamespace(
            runtime_action_sequence_turn_ids=[
                "turn_000002",
            ],
            runtime_session_action_history=[
                {
                    "text": "SAVE_ACTIVE_MEMORY",
                    "created_at": 800.0,
                    "runtime_turn_id": "turn_000001",
                },
                {
                    "text": "LIST_SKILLS",
                    "created_at": 945.0,
                    "runtime_turn_id": "turn_000002",
                },
                {
                    "text": "APPEND_SKILL",
                    "created_at": 998.0,
                    "runtime_turn_id": "turn_000002",
                },
            ],
        )

        with patch(
            "clients.brain_context_builder.time.time",
            return_value=1000.0,
        ):
            history = build_session_actions_history_context(
                context
            )

        self.assertEqual(
            history,
            (
                "<SESSION_ACTIONS_HISTORY>\n"
                "    1. SAVE_ACTIVE_MEMORY ( 3m ago )\n"
                "    --- Sequence started ---\n"
                "    2. LIST_SKILLS ( 55s ago )\n"
                "    3. APPEND_SKILL ( 2s ago )\n"
                "    --- Sequence ended ---\n"
                "</SESSION_ACTIONS_HISTORY>"
            ),
        )

    def test_brain_prompt_counts_current_turn_runtime_actions_and_pending_answer(self):

        context = SimpleNamespace(
            runtime_memory="",
            deep_thought_count=0,
            runtime_search_result="",
            runtime_search_result_id="",
            turn_number=0,
            user_message_count=1,
            assistant_message_count=0,
            runtime_action_events=[
                {
                    "name": "list_skills",
                },
                {
                    "name": "append_skill",
                },
            ],
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_WEB_SEARCH": False,
            },
        )

        session_state = prompt.split(
            "<CURRENT_SESSION_STATE>",
            1,
        )[1].split(
            "</CURRENT_SESSION_STATE>",
            1,
        )[0]

        self.assertIn(
            "JIN messages count:           3",
            session_state,
        )

    def test_brain_prompt_anchors_short_feedback_to_last_jin_response(self):

        context = SimpleNamespace(
            runtime_memory=(
                "last_jin_response: Offered a short poem about rain."
            ),
            deep_thought_count=0,
            runtime_search_result="",
            runtime_search_result_id="",
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_WEB_SEARCH": False,
            },
        )

        self.assertIn(
            "<RUNTIME_MEMORY>",
            prompt,
        )
        self.assertIn(
            "last_jin_response: Offered a short poem about rain.",
            prompt,
        )

    def test_brain_prompt_keeps_user_feedback_out_of_runtime_state(self):

        context = SimpleNamespace(
            runtime_memory=(
                "last_jin_response: Offered a short poem about rain."
            ),
            runtime_last_response_feedback={
                "rating": "disliked",
            },
            turn_number=57,
            user_message_count=58,
            assistant_message_count=57,
            deep_thought_count=0,
            runtime_search_result="",
            runtime_search_result_id="",
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_WEB_SEARCH": False,
            },
        )

        session_state = prompt.split(
            "<CURRENT_SESSION_STATE>",
            1,
        )[1].split(
            "</CURRENT_SESSION_STATE>",
            1,
        )[0]
        user_feedback = prompt.split(
            "<LATEST_USER_FEEDBACK priority=HIGH_PRIORITY>",
            1,
        )[1].split(
            "</LATEST_USER_FEEDBACK>",
            1,
        )[0]
        runtime_memory = prompt.split(
            "<RUNTIME_MEMORY>",
            1,
        )[1].split(
            "</RUNTIME_MEMORY>",
            1,
        )[0]

        self.assertIn(
            "Last response was disliked. First sentence of your reply must acknowledge the miss, "
            "then give corrected answer. Non-negotiable.",
            user_feedback,
        )
        self.assertTrue(
            prompt.startswith(
                "<TOOLS_RESULTS>"
            ),
        )
        self.assertLess(
            prompt.index("</TOOLS_RESULTS>"),
            prompt.index(
                "<LATEST_USER_FEEDBACK priority=HIGH_PRIORITY>"
            ),
        )
        self.assertLess(
            prompt.index("<LATEST_USER_FEEDBACK priority=HIGH_PRIORITY>"),
            prompt.index("<RUNTIME_MEMORY>"),
        )
        self.assertLess(
            prompt.index("<RUNTIME_MEMORY>"),
            prompt.index("<CURRENT_TRUSTED_RUNTIME_VARIABLES>"),
        )
        self.assertNotIn(
            "User feedback:",
            prompt,
        )
        self.assertNotIn(
            "Last response was disliked.",
            session_state,
        )
        self.assertNotIn(
            "<LATEST_USER_FEEDBACK",
            runtime_memory,
        )
        self.assertNotIn(
            "Last response was disliked.",
            runtime_memory,
        )

    async def test_runtime_response_feedback_does_not_write_runtime_memory(self):

        context = SimpleNamespace(
            runtime_memory=(
                "session_status: active\n"
                "JIN_LAST_RESPONSE_USER_FEEDBACK: stale"
            ),
            runtime_last_response_feedback=None,
        )

        result = await apply_runtime_response_feedback(
            context,
            {
                "rating": "disliked",
            },
        )

        self.assertEqual(
            "session_status: active",
            context.runtime_memory,
        )
        self.assertEqual(
            {
                "rating": "disliked",
            },
            context.runtime_last_response_feedback,
        )
        self.assertEqual(
            "session_status: active",
            result["runtime_memory"],
        )
        self.assertNotIn(
            "JIN_LAST_RESPONSE_USER_FEEDBACK",
            context.runtime_memory,
        )

    def test_runtime_response_feedback_uses_rating_clicks_count_suffix(self):

        feedback = normalize_runtime_response_feedback(
            {
                "rating": "liked",
                "clicks_count": "9",
            }
        )

        self.assertEqual(
            feedback,
            {
                "rating": "liked",
                "clicks_count": 9,
            },
        )

        value = build_runtime_response_feedback_value(
            feedback
        )

        self.assertIn(
            "liked",
            value,
        )
        self.assertTrue(
            value.endswith(
                "[ like_clicks_count: 9 ]"
            )
        )

        disliked_value = build_runtime_response_feedback_value(
            {
                "rating": "disliked",
                "clicks_count": 64,
            }
        )

        self.assertTrue(
            disliked_value.endswith(
                "[ dislike_clicks_count: 64 ]"
            )
        )

        neutral_value = build_runtime_response_feedback_value(
            {
                "rating": "neutral",
                "clicks_count": 3,
            }
        )

        self.assertTrue(
            neutral_value.endswith(
                "[ neutral_clicks_count: 3 ]"
            )
        )

    def test_brain_prompt_places_runtime_memory_above_session_memory(self):

        context = SimpleNamespace(
            session_memory=(
                "session_snapshot_first_turn: 0\n"
                "session_snapshot_last_turn: 6\n"
                "decision: Continue the memory architecture work."
            ),
            runtime_memory=(
                "topic: live runtime state"
            ),
            deep_thought_count=0,
            runtime_search_result="",
            runtime_search_result_id="",
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_WEB_SEARCH": False,
            },
        )

        self.assertIn(
            "<PREVIOUS_SESSION_STATE priority=\"higher_than_runtime_memory\">",
            prompt,
        )
        self.assertIn(
            "Continue the memory architecture work",
            prompt,
        )
        self.assertIn(
            "session_snapshot_first_turn",
            prompt,
        )
        self.assertIn(
            "session_snapshot_last_turn",
            prompt,
        )
        self.assertLess(
            prompt.index(
                "<RUNTIME_MEMORY>"
            ),
            prompt.index(
                "<PREVIOUS_SESSION_STATE"
            ),
        )

    def test_brain_prompt_includes_l2_memory_separately(self):

        context = SimpleNamespace(
            runtime_memory="topic: current factual work",
            runtime_l2_memory="possible pattern: user compares implementation paths before coding",
            deep_thought_count=0,
            runtime_search_result="",
            runtime_search_result_id="",
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_WEB_SEARCH": False,
            },
        )

        self.assertIn(
            "<RUNTIME_MEMORY>",
            prompt,
        )
        self.assertIn(
            "<RUNTIME_PATTERN_MEMORY>",
            prompt,
        )
        self.assertIn(
            "current factual work",
            prompt,
        )
        self.assertIn(
            "compares implementation paths",
            prompt,
        )
        self.assertNotIn(
            "image/action tool",
            prompt,
        )
        self.assertNotIn(
            "Choose the best available visual representation of the request instead of description",
            prompt,
        )

    def test_brain_prompt_includes_conditional_zero_diff_alert(self):

        context = SimpleNamespace(
            runtime_memory="topic: active loop diagnostics",
            runtime_l2_memory="",
            runtime_zero_diff_alert={
                "turn_number": 8,
                "user_message": "привет",
                "assistant_message": "Привет! Чем займемся?",
            },
            deep_thought_count=0,
            runtime_search_result="",
            runtime_search_result_id="",
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_WEB_SEARCH": False,
            },
        )

        self.assertIn(
            "<ZERO_DIFF_STALL_ALERT>",
            prompt,
        )
        self.assertIn(
            "Do not alarm from this fact alone",
            prompt,
        )
        self.assertNotIn(
            "soft success rules are intentionally not rendered",
            prompt,
        )
        self.assertIn(
            "bad rules for this turn",
            prompt,
        )
        self.assertIn(
            "stop continuing normally and refuse the repeated frame",
            prompt,
        )
        self.assertIn(
            "Do not try to break the loop by forcing the user",
            prompt,
        )
        self.assertIn(
            "purpose, task, topic, choice, or next step",
            prompt,
        )
        self.assertIn(
            "short, pointed, off-angle move",
            prompt,
        )
        self.assertIn(
            "changes the interaction shape",
            prompt,
        )
        self.assertIn(
            "same local interaction",
            prompt,
        )
        self.assertIn(
            "привет",
            prompt,
        )

    def test_brain_prompt_includes_conversation_activity(self):

        context = SimpleNamespace(
            runtime_memory="topic: active loop diagnostics",
            runtime_l2_memory=(
                "possible pattern: repeated greeting loop; Occurrences: 3"
            ),
            runtime_l2_pending_patches=[
                {
                    "total_diff": 29.85,
                },
            ],
            runtime_zero_diff_alert=None,
            deep_thought_count=0,
            runtime_search_result="",
            runtime_search_result_id="",
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_WEB_SEARCH": False,
            },
        )

        self.assertIn(
            "<CONVERSATION_ACTIVITY>",
            prompt,
        )
        self.assertLess(
            prompt.index(
                "<USER_DATETIME>"
            ),
            prompt.index(
                "<CONVERSATION_ACTIVITY>"
            ),
        )
        self.assertLess(
            prompt.index(
                "<CONVERSATION_ACTIVITY>"
            ),
            prompt.index(
                "</CURRENT_TRUSTED_RUNTIME_VARIABLES>"
            ),
        )
        self.assertNotIn(
            "<PERCENT>",
            prompt,
        )
        self.assertNotIn(
            "<INSTRUCTION>",
            prompt,
        )
        self.assertNotIn(
            "SOURCE_L1_DIFF",
            prompt,
        )
        self.assertIn(
            "LOW activity. The conversation is fading",
            prompt,
        )
        self.assertIn(
            "acting against the expected pattern",
            prompt,
        )

    def test_brain_prompt_marks_critical_conversation_activity(self):

        context = SimpleNamespace(
            runtime_memory="topic: active loop diagnostics",
            runtime_l2_memory=(
                "possible pattern: repeated greeting loop; Occurrences: 4"
            ),
            runtime_l2_pending_patches=[
                {
                    "total_diff": 9.85,
                },
            ],
            runtime_zero_diff_alert=None,
            deep_thought_count=0,
            runtime_search_result="",
            runtime_search_result_id="",
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_WEB_SEARCH": False,
            },
        )

        self.assertIn(
            "<CONVERSATION_ACTIVITY>",
            prompt,
        )
        self.assertNotIn(
            "<PERCENT>",
            prompt,
        )
        self.assertIn(
            "CRITICAL activity collapse",
            prompt,
        )
        self.assertIn(
            "current local response rules have failed",
            prompt,
        )
        self.assertIn(
            "Use a counter-reaction",
            prompt,
        )
        self.assertIn(
            "Do not force progress or extract a useful request",
            prompt,
        )

    def test_brain_prompt_marks_activity_below_twenty_as_critical(self):

        context = SimpleNamespace(
            runtime_memory="topic: active loop diagnostics",
            runtime_l2_memory="",
            runtime_l2_pending_patches=[
                {
                    "total_diff": 19,
                },
            ],
            runtime_zero_diff_alert=None,
            deep_thought_count=0,
            runtime_search_result="",
            runtime_search_result_id="",
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_WEB_SEARCH": False,
            },
        )

        self.assertIn(
            "<CONVERSATION_ACTIVITY>",
            prompt,
        )
        self.assertNotIn(
            "<PERCENT>",
            prompt,
        )
        self.assertIn(
            "CRITICAL activity collapse",
            prompt,
        )

    def test_brain_prompt_caps_conversation_activity_at_full(self):

        context = SimpleNamespace(
            runtime_memory="topic: active exchange",
            runtime_l2_memory="",
            runtime_l2_pending_patches=[
                {
                    "total_diff": 142,
                },
            ],
            runtime_zero_diff_alert=None,
            deep_thought_count=0,
            runtime_search_result="",
            runtime_search_result_id="",
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_WEB_SEARCH": False,
            },
        )

        self.assertNotIn(
            "<CONVERSATION_ACTIVITY>",
            prompt,
        )
        self.assertNotIn(
            "SOURCE_L1_DIFF",
            prompt,
        )

    def test_brain_prompt_uses_recorded_activity_after_l2_clears_pending(self):

        context = SimpleNamespace(
            runtime_memory="topic: active exchange",
            runtime_l2_memory=(
                "possible pattern: user revisits memory mechanics"
            ),
            runtime_l2_pending_patches=[],
            runtime_memory_snapshots=[
                {
                    "total_diff": 0,
                },
            ],
            runtime_conversation_activity_diff=150.55,
            runtime_zero_diff_alert=None,
            deep_thought_count=0,
            runtime_search_result="",
            runtime_search_result_id="",
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_WEB_SEARCH": False,
            },
        )

        self.assertNotIn(
            "<CONVERSATION_ACTIVITY>",
            prompt,
        )

    async def test_runtime_l1_diff_log_formats_float_noise(self):

        logger = FakeLogger()
        context = SimpleNamespace(
            logger=logger,
            runtime_l2_pending_patches=[
                {
                    "total_diff": 4.65,
                },
                {
                    "total_diff": 296.85,
                },
            ],
            runtime_l2_last_turn=2,
            user_message_count=5,
        )

        await record_runtime_l1_diff(
            context=context,
            snapshot={
                "index": 3,
                "total_diff": 167.29999999999998,
                "patch": {},
            },
            turns=[],
        )

        self.assertEqual(
            len(logger.service_logs),
            1,
        )
        self.assertIn(
            "[MEMORY:L1] L1 diff +167.3; "
            "recent diffs [4.65, 296.85, 167.3]; "
            "avg 156.27; range 292.2;",
            logger.service_logs[0],
        )
        self.assertNotIn(
            "167.29999999999998",
            logger.service_logs[0],
        )

    async def test_summarizer_updates_runtime_memory(self):

        service_client = FakeServiceClient(
            "The user is testing live runtime memory."
        )
        logger = FakeLogger()
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            emitter=SimpleNamespace(
                events=[],
                emit=None,
            ),
            logger=logger,
            runtime_memory="",
            runtime_memory_updates=0,
            runtime_memory_snapshots=[],
            runtime_memory_snapshot_index=0,
            session_id="test-session",
        )

        async def emit(event):
            context.emitter.events.append(
                event
            )

        context.emitter.emit = emit

        updated_memory = await summarize_runtime_memory(
            context=context,
            user_message="Do you remember this?",
            assistant_message="Yes, I can keep the live context updated.",
        )

        self.assertIn(
            "The user is testing live runtime memory.",
            updated_memory,
        )
        self.assertIn(
            'user_message: "Do you remember this?"',
            context.runtime_memory,
        )
        self.assertIn(
            "last_jin_response: Yes, I can keep the live context updated.",
            context.runtime_memory,
        )
        self.assertEqual(
            context.runtime_memory_updates,
            1,
        )
        self.assertIn(
            "Do you remember this?",
            service_client.calls[0]["user_prompt"],
        )
        self.assertNotIn(
            "atomic bullet lines",
            service_client.calls[0]["user_prompt"],
        )
        self.assertEqual(
            service_client.calls[0]["system_prompt"],
            build_runtime_memory_system_prompt(
                current_memory="",
                user_message="Do you remember this?",
            ),
        )
        self.assertEqual(
            logger.summarizer_logs[0][0],
            "[MEMORY:L1] L1 summarizer request",
        )
        self.assertIn(
            '"messages"',
            logger.summarizer_logs[0][1],
        )
        self.assertIn(
            "Do you remember this?",
            logger.summarizer_logs[0][1],
        )
        self.assertEqual(
            len(context.emitter.events),
            3,
        )

        telemetry_event = context.emitter.events[0]

        self.assertEqual(
            telemetry_event["type"],
            "telemetry",
        )
        self.assertGreater(
            telemetry_event["runtime"][
                RUNTIME_MEMORY_SUMMARIZER_RUNTIME_ID
            ]["used_tokens"],
            0,
        )

        event = context.emitter.events[1]

        self.assertEqual(
            event["type"],
            "runtime_memory_update",
        )

        diff_event = context.emitter.events[2]

        self.assertEqual(
            diff_event["type"],
            "runtime_l1_diff_update",
        )

        self.assertIn(
            "The user is testing live runtime memory.",
            event["memory"],
        )

        self.assertEqual(
            event["updates"],
            1,
        )

        self.assertIn(
            "snapshot",
            event,
        )

        self.assertEqual(
            event["snapshot"]["index"],
            0,
        )

        self.assertIn(
            'user_message: "Do you remember this?"',
            event["snapshot"]["raw_memory"],
        )

    def test_enforce_runtime_turn_fields_keeps_repetition_metadata_outside_quote(self):

        memory = enforce_runtime_turn_fields(
            "active_topic: loop check",
            user_message='"hello" [ repeated: 3 ]',
            assistant_message="I noticed the repeat.",
        )

        self.assertIn(
            'user_message: "hello" [ repeated: 3 ]',
            memory,
        )

    def test_quote_runtime_user_message_preserves_verbatim_quotes(self):

        self.assertEqual(
            quote_runtime_user_message_value(
                '"hello"'
            ),
            '"\\"hello\\""',
        )

    def test_parse_runtime_memory_keeps_multiline_user_message_together(self):

        lines = parse_runtime_memory_lines(
            'user_message: "first line\n'
            'second line\n'
            'third line"\n'
            "standalone continuation stays note\n"
            "last_jin_response: Answered."
        )

        self.assertEqual(
            lines[0]["key"],
            "user_message",
        )
        self.assertEqual(
            lines[0]["value"],
            (
                '"first line\\nsecond line\\nthird line"'
                "\\nstandalone continuation stays note"
            ),
        )
        self.assertEqual(
            lines[1]["key"],
            "last_jin_response",
        )
        self.assertEqual(
            len(lines),
            2,
        )

    def test_parse_runtime_memory_keeps_quoted_user_message_fragments_together(self):

        lines = parse_runtime_memory_lines(
            'user_message: "first line"\n'
            '"second line\\n"\n'
            '"third line\\n"\n'
            "active_memory: value"
        )

        self.assertEqual(
            [
                line["key"]
                for line in lines
            ],
            [
                "user_message",
                "active_memory",
            ],
        )
        self.assertIn(
            "second line",
            lines[0]["value"],
        )
        self.assertIn(
            "third line",
            lines[0]["value"],
        )

    def test_enforce_runtime_turn_fields_removes_broken_user_message_note_fragments(self):

        memory = enforce_runtime_turn_fields(
            (
                'user_message: "old"\n'
                'note: "\\"fragment one\\\\n\\""\n'
                'note: "fragment two\\\\n\\""\n'
                'active_memory: "Книга" (purpose: recall test; status: pending)'
            ),
            user_message="fresh message",
            assistant_message="Fresh answer.",
        )

        self.assertIn(
            'user_message: "fresh message"',
            memory,
        )
        self.assertIn(
            "active_memory:",
            memory,
        )
        self.assertNotIn(
            "fragment one",
            memory,
        )
        self.assertNotIn(
            "fragment two",
            memory,
        )

    def test_refresh_active_memory_runtime_metadata_attaches_suffixes_before_status(self):

        memory = refresh_active_memory_runtime_metadata(
            (
                "active_memory: Secret word: Sun "
                "[ purpose: Ask user to guess ] "
                "[ status: pending ]"
            ),
            context=SimpleNamespace(
                timestamp="2026-06-20T10:00:00",
                session_id="session-alpha",
                turn_number=3,
            ),
        )

        self.assertIn(
            "[ creation_time: 2026-06-20T10:00:00 ]",
            memory,
        )
        self.assertIn(
            "[ created_session_id: session-alpha ]",
            memory,
        )
        self.assertIn(
            "[ created_jin_message_number: 3 ]",
            memory,
        )
        self.assertIn(
            "[ elapsed_time: 00:00:00 ]",
            memory,
        )
        self.assertIn(
            "[ elapsed_jin_message_number: 0 ] [ status: pending ]",
            memory,
        )

    def test_refresh_active_memory_runtime_metadata_updates_elapsed_suffixes(self):

        previous_memory = (
            "active_memory: Secret word: Sun "
            "[ purpose: Ask user to guess ] "
            "[ creation_time: 2026-06-20T10:00:00 ] "
            "[ created_session_id: session-alpha ] "
            "[ created_jin_message_number: 3 ] "
            "[ elapsed_time: 00:00:00 ] "
            "[ elapsed_jin_message_number: 0 ] "
            "[ status: pending ]"
        )

        memory = refresh_active_memory_runtime_metadata(
            (
                "active_memory: Secret word: Sun "
                "[ purpose: Ask user to guess ] "
                "[ status: pending ]"
            ),
            previous_memory=previous_memory,
            context=SimpleNamespace(
                timestamp="2026-06-20T11:02:03",
                session_id="session-beta",
                turn_number=5,
            ),
        )

        self.assertIn(
            "[ creation_time: 2026-06-20T10:00:00 ]",
            memory,
        )
        self.assertIn(
            "[ created_session_id: session-alpha ]",
            memory,
        )
        self.assertIn(
            "[ created_jin_message_number: 3 ]",
            memory,
        )
        self.assertIn(
            "[ elapsed_time: 01:02:03 ]",
            memory,
        )
        self.assertIn(
            "[ elapsed_jin_message_number: 2 ]",
            memory,
        )

    def test_runtime_context_refresh_adds_user_idle_to_active_memory_elapsed(self):

        memory = (
            "active_memory: Reminder set for potatoes "
            "[ purpose: remind user ] "
            "[ creation_time: 2026-06-20T10:00:00 ] "
            "[ created_jin_message_number: 3 ] "
            "[ elapsed_time: 00:00:00 ] "
            "[ elapsed_jin_message_number: 0 ] "
            "[ status: pending ]"
        )

        context = SimpleNamespace(
            timestamp="2026-06-20T10:00:00",
            turn_number=4,
            runtime_user_idle_seconds=300,
            runtime_user_idle_text="5m 0s",
        )
        refreshed = refresh_active_memory_runtime_metadata(
            memory,
            previous_memory=memory,
            context=context,
            add_runtime_user_idle_to_elapsed=True,
        )
        refreshed = build_runtime_memory_context_text(
            refreshed,
            context,
        )

        self.assertIn(
            "[ elapsed_time: 00:05:00 ]",
            refreshed,
        )
        self.assertIn(
            "user_idle: 5m",
            refreshed,
        )

    def test_runtime_context_refresh_does_not_mutate_stored_elapsed_by_default(self):

        memory = (
            "active_memory: Reminder set for potatoes "
            "[ creation_time: 2026-06-20T10:00:00 ] "
            "[ created_jin_message_number: 3 ] "
            "[ elapsed_time: 00:00:00 ] "
            "[ elapsed_jin_message_number: 0 ] "
            "[ status: pending ]"
        )

        rendered = build_runtime_memory_context_text(
            memory,
            SimpleNamespace(
                timestamp="2026-06-20T10:00:00",
                turn_number=4,
                runtime_user_idle_seconds=300,
                runtime_user_idle_text="5m 0s",
            ),
        )

        self.assertIn(
            "[ elapsed_time: 00:00:00 ]",
            rendered,
        )


    def test_strip_active_memory_runtime_metadata_keeps_status_for_l1(self):

        memory = strip_active_memory_runtime_metadata(
            (
                "active_memory: Secret word: Sun "
                "[ purpose: Ask user to guess ] "
                "[ creation_time: 2026-06-20T10:00:00 ] "
                "[ created_session_id: session-alpha ] "
                "[ created_jin_message_number: 3 ] "
                "[ elapsed_time: 01:02:03 ] "
                "[ elapsed_jin_message_number: 2 ] "
                "[ status: pending ]\n"
                "primary_goal: Play a memory game."
            )
        )

        self.assertIn(
            (
                "active_memory: Secret word: Sun "
                "[ purpose: Ask user to guess ] "
                "[ status: pending ]"
            ),
            memory,
        )
        self.assertIn(
            "primary_goal: Play a memory game.",
            memory,
        )
        self.assertNotIn(
            "creation_time",
            memory,
        )
        self.assertNotIn(
            "created_session_id",
            memory,
        )
        self.assertNotIn(
            "elapsed_time",
            memory,
        )

    def test_strip_active_memory_runtime_metadata_keeps_value_suffix_for_l1(self):

        memory = strip_active_memory_runtime_metadata(
            (
                "active_memory: Secret recall request "
                "[ conditions: Ask when user returns ] "
                "[ value: Sun ] "
                "[ creation_time: 2026-06-20T10:00:00 ] "
                "[ created_session_id: session-alpha ] "
                "[ elapsed_time: 01:02:03 ] "
                "[ status: pending ]"
            )
        )

        self.assertIn(
            (
                "active_memory: Secret recall request "
                "[ conditions: Ask when user returns ] "
                "[ value: Sun ] "
                "[ status: pending ]"
            ),
            memory,
        )
        self.assertNotIn(
            "creation_time",
            memory,
        )
        self.assertNotIn(
            "created_session_id",
            memory,
        )
        self.assertNotIn(
            "elapsed_time",
            memory,
        )

    def test_remove_active_memory_entries_hides_runtime_owned_memory_from_l1(self):

        memory = remove_active_memory_entries(
            (
                "session_status: active\n"
                "active_memory: Drink coffee "
                "[ conditions: in 5 minutes ] "
                "[ status: pending ]\n"
                "user_message: hello"
            )
        )

        self.assertIn(
            "session_status: active",
            memory,
        )
        self.assertIn(
            "user_message: hello",
            memory,
        )
        self.assertNotIn(
            "active_memory",
            memory,
        )
        self.assertNotIn(
            "Drink coffee",
            memory,
        )

    async def test_summarizer_enforces_latest_user_message_when_model_is_stale(self):

        service_client = FakeServiceClient(
            (
                'user_message: "old message"\n'
                "last_jin_response: Fresh answer summary."
            )
        )
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            emitter=SimpleNamespace(
                events=[],
                emit=None,
            ),
            logger=FakeLogger(),
            runtime_memory=(
                'user_message: "old message"\n'
                "last_jin_response: Previous answer."
            ),
            runtime_memory_updates=1,
            runtime_memory_snapshots=[],
            runtime_memory_snapshot_index=0,
            session_id="test-session",
        )

        async def emit(event):
            context.emitter.events.append(
                event
            )

        context.emitter.emit = emit

        updated_memory = await summarize_runtime_memory(
            context=context,
            user_message="latest message",
            assistant_message="Fresh assistant answer.",
        )

        self.assertIn(
            'user_message: "latest message"',
            updated_memory,
        )
        self.assertNotIn(
            'user_message: "old message"',
            updated_memory,
        )

    async def test_summarizer_replaces_stale_last_jin_response(self):

        service_client = FakeServiceClient(
            (
                'user_message: "latest message"\n'
                "last_jin_response: Previous answer summary."
            )
        )
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            emitter=SimpleNamespace(
                events=[],
                emit=None,
            ),
            logger=FakeLogger(),
            runtime_memory=(
                'user_message: "old message"\n'
                "last_jin_response: Previous answer summary."
            ),
            runtime_memory_updates=1,
            runtime_memory_snapshots=[],
            runtime_memory_snapshot_index=0,
            session_id="test-session",
        )

        async def emit(event):
            context.emitter.events.append(
                event
            )

        context.emitter.emit = emit

        updated_memory = await summarize_runtime_memory(
            context=context,
            user_message="latest message",
            assistant_message="Latest assistant answer replaces the stale summary.",
        )

        self.assertIn(
            "last_jin_response: Latest assistant answer replaces the stale summary.",
            updated_memory,
        )
        self.assertNotIn(
            "last_jin_response: Previous answer summary.",
            updated_memory,
        )

    async def test_pending_turns_enforces_latest_turn_fields(self):

        service_client = FakeServiceClient(
            (
                'user_message: "first message"\n'
                "last_jin_response: Previous answer summary."
            )
        )
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            emitter=SimpleNamespace(
                events=[],
                emit=None,
            ),
            logger=FakeLogger(),
            runtime_memory=(
                'user_message: "first message"\n'
                "last_jin_response: Previous answer summary."
            ),
            runtime_memory_stable=(
                'user_message: "first message"\n'
                "last_jin_response: Previous answer summary."
            ),
            runtime_memory_updates=1,
            runtime_memory_pending_turns=[
                {
                    "user_message": "first message",
                    "assistant_message": "First answer.",
                },
                {
                    "user_message": '"hello" [ repeated: 3 ]',
                    "assistant_message": "Latest repeated answer.",
                },
            ],
            runtime_memory_update_task=None,
            runtime_memory_snapshots=[],
            runtime_memory_snapshot_index=0,
            session_id="test-session",
        )

        async def emit(event):
            context.emitter.events.append(
                event
            )

        context.emitter.emit = emit

        updated_memory = await summarize_runtime_memory_pending_turns(
            context=context,
        )

        self.assertIn(
            'user_message: "hello" [ repeated: 3 ]',
            updated_memory,
        )
        self.assertIn(
            "last_jin_response: Latest repeated answer.",
            updated_memory,
        )

    async def test_l1_summarizer_user_prompt_stays_turn_only(self):

        service_client = FakeServiceClient(
            (
                "temporary_preference: On 2026-06-05, user requested "
                "not to discuss past topics for the rest of that day.\n"
                "last_jin_response: Acknowledged the fresh-topic preference."
            )
        )
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            emitter=SimpleNamespace(
                events=[],
                emit=None,
            ),
            logger=FakeLogger(),
            runtime_memory="",
            runtime_memory_updates=0,
            runtime_memory_snapshots=[],
            runtime_memory_snapshot_index=0,
            runtime_l2_memory="",
            session_id="test-session",
            timestamp="2026-06-05T13:38:50",
            current_date="2026-06-05",
            current_time="13:38:50",
            weekday="Friday",
            year=2026,
            turn_number=12,
            user_message_count=7,
            assistant_message_count=6,
        )

        async def emit(event):
            context.emitter.events.append(
                event
            )

        context.emitter.emit = emit

        updated_memory = await summarize_runtime_memory(
            context=context,
            user_message="сегодня не хочу обсуждать прошлые темы",
            assistant_message="Хорошо, выберем свежую тему.",
        )

        user_prompt = service_client.calls[0]["user_prompt"]

        self.assertNotIn(
            "<CURRENT_TRUSTED_RUNTIME_VARIABLES>",
            user_prompt,
        )
        self.assertNotIn(
            "<CURRENT_SESSION_STATE>",
            user_prompt,
        )
        self.assertNotIn(
            "Total messages count:",
            user_prompt,
        )
        self.assertIn(
            "Latest user message:\nсегодня не хочу обсуждать прошлые темы",
            user_prompt,
        )
        self.assertIn(
            "Latest JIN answer:\nХорошо, выберем свежую тему.",
            user_prompt,
        )
        self.assertNotIn(
            "today",
            updated_memory.lower(),
        )
        self.assertIn(
            "On 2026-06-05, user requested not to discuss past topics for the rest of that day",
            updated_memory,
        )

    async def test_summarizer_preserves_durable_fact_keys(self):

        service_client = FakeServiceClient(
            (
                "session_status: Active, discussing a new topic\n"
                "last_jin_response: Asked a follow-up question."
            )
        )
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            emitter=SimpleNamespace(
                events=[],
                emit=None,
            ),
            logger=FakeLogger(),
            runtime_memory=(
                "user_fact: Name is Sergey; lives in Kyiv\n"
                "jin_facts: JIN can keep runtime memory\n"
                "active topic: Ukraine news"
            ),
            runtime_memory_updates=1,
            runtime_memory_snapshots=[],
            runtime_memory_snapshot_index=0,
            session_id="test-session",
        )

        async def emit(event):
            context.emitter.events.append(
                event
            )

        context.emitter.emit = emit

        updated_memory = await summarize_runtime_memory(
            context=context,
            user_message="Давай сменим тему.",
            assistant_message="Хорошо, о чем поговорим?",
        )

        self.assertIn(
            "session_status: Active, discussing a new topic",
            updated_memory,
        )
        self.assertIn(
            "user_fact: Name is Sergey; lives in Kyiv",
            updated_memory,
        )
        self.assertIn(
            "jin_facts: JIN can keep runtime memory",
            updated_memory,
        )

    async def test_summarizer_allows_explicit_fact_negation(self):

        service_client = FakeServiceClient(
            (
                "user_fact: not true; user corrected this fact\n"
                "session_status: Active, discussing a correction\n"
                "last_jin_response: Acknowledged the correction."
            )
        )
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            emitter=SimpleNamespace(
                events=[],
                emit=None,
            ),
            logger=FakeLogger(),
            runtime_memory=(
                "user_fact: Name is Sergey; lives in Kyiv\n"
                "active topic: personal context"
            ),
            runtime_memory_updates=1,
            runtime_memory_snapshots=[],
            runtime_memory_snapshot_index=0,
            session_id="test-session",
        )

        async def emit(event):
            context.emitter.events.append(
                event
            )

        context.emitter.emit = emit

        updated_memory = await summarize_runtime_memory(
            context=context,
            user_message="Это уже не факт.",
            assistant_message="Понял, убираю этот факт из памяти.",
        )

        self.assertIn(
            "user_fact: not true; user corrected this fact",
            updated_memory,
        )
        self.assertNotIn(
            "Name is Sergey; lives in Kyiv",
            updated_memory,
        )

    async def test_l2_memory_waits_for_repeated_patch_keys(self):

        service_client = FakeServiceClient(
            "possible pattern: should not run"
        )
        logger = FakeLogger()
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            logger=logger,
            runtime_l2_memory="",
            runtime_l2_pending_patches=[
                {
                    "turn_number": 1,
                    "snapshot_index": 1,
                    "total_diff": 110,
                    "changes": {
                        "added": [
                            {
                                "key": "topic",
                                "value": "one",
                            },
                        ],
                    },
                },
                {
                    "turn_number": 2,
                    "snapshot_index": 2,
                    "total_diff": 254,
                    "changes": {
                        "added": [
                            {
                                "key": "intent",
                                "value": "two",
                            },
                        ],
                    },
                },
                {
                    "turn_number": 3,
                    "snapshot_index": 3,
                    "total_diff": 80,
                    "changes": {
                        "added": [
                            {
                                "key": "choice",
                                "value": "three",
                            },
                        ],
                    },
                },
                {
                    "turn_number": 4,
                    "snapshot_index": 4,
                    "total_diff": 140,
                    "changes": {
                        "added": [
                            {
                                "key": "status",
                                "value": "four",
                            },
                        ],
                    },
                },
                {
                    "turn_number": 5,
                    "snapshot_index": 5,
                    "total_diff": 90,
                    "changes": {
                        "added": [
                            {
                                "key": "reference",
                                "value": "five",
                            },
                        ],
                    },
                },
            ],
            runtime_l2_last_turn=0,
            user_message_count=L2_PATCH_WINDOW,
        )

        updated_memory = await maybe_summarize_runtime_l2_memory(
            context=context,
        )

        self.assertEqual(
            updated_memory,
            "",
        )
        self.assertEqual(
            len(service_client.calls),
            0,
        )
        self.assertEqual(
            context.runtime_l2_memory,
            "",
        )

    async def test_l2_memory_keeps_evidence_but_drops_unconfirmed_pattern(self):

        service_client = FakeServiceClient(
            "possible pattern: user may be repeating one message. "
            "Occurrences: 4; first_seen_snapshot: 9; last_seen_snapshot: 10; "
            "evidence summary: duplicate rows for one snapshot; confidence: medium\n"
            'L2_pattern_evidence_1: user repeatedly sending one message [ quote: "ping" ] '
            "[ first_seen_turn_snapshot: 9 ] [ last_seen_turn_snapshot: 10 ] [ occurrences: 4 ]"
        )
        logger = FakeLogger()
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            logger=logger,
            runtime_memory="",
            runtime_memory_snapshots=[],
            runtime_memory_snapshot_index=0,
            runtime_l2_memory="",
            runtime_l2_pending_patches=[
                {
                    "turn_number": index + 1,
                    "snapshot_index": index + 1,
                    "total_diff": 120,
                    "changes": {
                        "added": [
                            {
                                "key": "topic",
                                "value": f"value {index}",
                            },
                        ],
                    },
                }
                for index in range(L2_PATCH_WINDOW - 1)
            ] + [
                {
                    "turn_number": 10,
                    "snapshot_index": 10,
                    "total_diff": 140,
                    "user_message": "ping",
                    "user_messages": [
                        "ping",
                    ],
                    "changes": {
                        "added": [
                            {
                                "key": "topic",
                                "value": "value final",
                            },
                            {
                                "key": "user_message",
                                "value": "ping",
                            },
                        ],
                    },
                },
            ],
            runtime_l1_diff_history=[],
            runtime_l2_last_turn=0,
            user_message_count=L2_PATCH_WINDOW,
        )

        updated_memory = await maybe_summarize_runtime_l2_memory(
            context=context,
        )

        self.assertNotIn(
            "possible pattern",
            updated_memory,
        )
        self.assertIn(
            "L2_pattern_evidence_1:",
            updated_memory,
        )
        self.assertIn(
            'quote: "ping"',
            updated_memory,
        )
        self.assertIn(
            "[ first_seen_turn_snapshot: 9 ]",
            updated_memory,
        )
        self.assertIn(
            "[ last_seen_turn_snapshot: 10 ]",
            updated_memory,
        )

    async def test_l2_memory_runs_after_repeated_patch_keys_even_with_noisy_diff(self):

        service_client = FakeServiceClient(
            "possible pattern: user revisits the same implementation tradeoff",
        )
        logger = FakeLogger()
        emitter = SimpleNamespace(
            events=[],
            emit=None,
        )
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            emitter=emitter,
            logger=logger,
            runtime_memory="",
            runtime_memory_snapshots=[],
            runtime_memory_snapshot_index=0,
            runtime_l2_memory="",
            runtime_l2_pending_patches=[
                {
                    "turn_number": 1,
                    "snapshot_index": 1,
                    "total_diff": 110,
                    "changes": {
                        "added": [
                            {
                                "key": "topic",
                                "value": "early broad update",
                            },
                        ],
                    },
                },
                {
                    "turn_number": 2,
                    "snapshot_index": 2,
                    "total_diff": 254,
                    "changes": {
                        "changed": [
                            {
                                "previous_key": "topic",
                                "previous_value": "early broad update",
                                "current_key": "topic",
                                "current_value": "large rewrite",
                            },
                        ],
                    },
                },
                {
                    "turn_number": 3,
                    "snapshot_index": 3,
                    "total_diff": 199.05,
                    "changes": {
                        "changed": [
                            {
                                "previous_key": "topic",
                                "previous_value": "large rewrite",
                                "current_key": "topic",
                                "current_value": "memory mechanics",
                            },
                        ],
                    },
                },
                {
                    "turn_number": 4,
                    "snapshot_index": 4,
                    "total_diff": 151,
                    "changes": {
                        "changed": [
                            {
                                "previous_key": "topic",
                                "previous_value": "memory mechanics",
                                "current_key": "topic",
                                "current_value": "pattern trigger",
                            },
                        ],
                    },
                },
                {
                    "turn_number": 5,
                    "snapshot_index": 5,
                    "total_diff": 144.9,
                    "changes": {
                        "changed": [
                            {
                                "previous_key": "topic",
                                "previous_value": "pattern trigger",
                                "current_key": "topic",
                                "current_value": "L2 window",
                            },
                        ],
                    },
                },
                {
                    "turn_number": 6,
                    "snapshot_index": 6,
                    "total_diff": 77.6,
                    "changes": {
                        "changed": [
                            {
                                "previous_key": "intent",
                                "previous_value": "inspect diff",
                                "current_key": "intent",
                                "current_value": "adjust trigger",
                            },
                        ],
                    },
                },
                {
                    "turn_number": 7,
                    "snapshot_index": 7,
                    "total_diff": 104.69,
                    "changes": {
                        "changed": [
                            {
                                "previous_key": "topic",
                                "previous_value": "L2 window",
                                "current_key": "topic",
                                "current_value": "repeated keys",
                            },
                        ],
                    },
                },
            ],
            runtime_l1_diff_history=[
                {
                    "snapshot_index": 1,
                    "total_diff": 110,
                },
                {
                    "snapshot_index": 7,
                    "total_diff": 104.69,
                },
            ],
            runtime_l2_last_turn=0,
            user_message_count=7,
            session_id="test-session",
        )

        async def emit(event):
            context.emitter.events.append(
                event
            )

        context.emitter.emit = emit

        updated_memory = await maybe_summarize_runtime_l2_memory(
            context=context,
        )

        self.assertEqual(
            updated_memory,
            "possible pattern: user revisits the same implementation tradeoff",
        )
        self.assertEqual(
            len(service_client.calls),
            1,
        )
        self.assertEqual(
            service_client.calls[0]["timeout"],
            config.SERVICE_REQUEST_TIMEOUT,
        )
        self.assertEqual(
            context.runtime_l2_memory,
            "possible pattern: user revisits the same implementation tradeoff",
        )
        self.assertEqual(
            context.runtime_l2_last_turn,
            7,
        )
        self.assertEqual(
            context.runtime_l2_pending_patches,
            [],
        )
        self.assertEqual(
            len(context.runtime_l1_diff_history),
            2,
        )
        self.assertIn(
            "Recent L1 patches",
            service_client.calls[0]["user_prompt"],
        )
        self.assertIn(
            "total_diff: 199.05",
            service_client.calls[0]["user_prompt"],
        )
        self.assertNotIn(
            "total_diff: 110",
            service_client.calls[0]["user_prompt"],
        )
        self.assertNotIn(
            "total_diff: 254",
            service_client.calls[0]["user_prompt"],
        )
        self.assertEqual(
            logger.summarizer_logs[0][0],
            "[MEMORY:L2] L2 summarizer request",
        )
        self.assertIn(
            '"messages"',
            logger.summarizer_logs[0][1],
        )
        self.assertIn(
            "total_diff: 199.05",
            logger.summarizer_logs[0][1],
        )
        self.assertEqual(
            logger.summarizer_logs[1][0],
            "[MEMORY:L2] L2 pattern memory summarizer result",
        )
        self.assertEqual(
            logger.summarizer_logs[1][1],
            "possible pattern: user revisits the same implementation tradeoff",
        )
        self.assertEqual(
            context.runtime_memory_snapshots,
            [],
        )
        memory_events = [
            event
            for event in context.emitter.events
            if event["type"] == "runtime_memory_update"
        ]

        self.assertEqual(
            len(memory_events),
            0,
        )

    def test_l3_session_memory_prompt_uses_all_runtime_snapshots(self):

        prompt = build_runtime_session_memory_user_prompt(
            current_session_memory="decision: old handoff",
            runtime_memory_snapshots=[
                {
                    "index": 0,
                    "raw_memory": "topic: first topic",
                    "total_diff": 30,
                },
                {
                    "index": 1,
                    "raw_memory": "decision: final direction",
                    "total_diff": 80,
                },
            ],
            diff_history=[
                {
                    "snapshot_index": 1,
                    "total_diff": 80,
                    "changes": {
                        "added": [
                            {
                                "key": "decision",
                            }
                        ],
                    },
                },
            ],
        )

        self.assertIn(
            "Selected L1 runtime memory snapshot history",
            prompt,
        )
        self.assertIn(
            "runtime_memory_id:",
            prompt,
        )
        self.assertIn(
            "topic: first topic",
            prompt,
        )
        self.assertIn(
            "decision: final direction",
            prompt,
        )
        self.assertIn(
            '"total_diff": 80',
            prompt,
        )
        self.assertIn(
            "omitted_middle_snapshots: 0",
            prompt,
        )
        self.assertIn(
            "Recent L1 diff history",
            prompt,
        )
        self.assertIn(
            "omitted_older_diffs: 0",
            prompt,
        )

    def test_l3_session_memory_prompt_bounds_long_snapshot_history(self):

        prompt = build_runtime_session_memory_user_prompt(
            current_session_memory="decision: old handoff",
            runtime_memory_snapshots=[
                {
                    "index": index,
                    "raw_memory": f"topic: snapshot {index}",
                    "total_diff": index,
                }
                for index in range(30)
            ],
            diff_history=[
                {
                    "snapshot_index": index,
                    "total_diff": index,
                    "changes": {
                        "changed": [
                            {
                                "current_key": f"decision_{index}",
                            }
                        ],
                    },
                }
                for index in range(40)
            ],
        )

        self.assertIn(
            "omitted_middle_snapshots: 0",
            prompt,
        )
        self.assertIn(
            "topic: snapshot 0",
            prompt,
        )
        self.assertIn(
            "topic: snapshot 29",
            prompt,
        )
        self.assertIn(
            "topic: snapshot 10",
            prompt,
        )
        self.assertIn(
            "omitted_older_diffs: 32",
            prompt,
        )

    def test_l3_session_memory_prompt_uses_compact_digest_not_raw_archive(self):

        prompt = build_runtime_session_memory_user_prompt(
            current_session_memory="\n".join(
                f"old narrative {index}: {'a' * 300}"
                for index in range(20)
            ),
            runtime_memory_snapshots=[
                {
                    "index": index,
                    "raw_memory": (
                        f"decision: keep snapshot {index}\n"
                        f"narrative: {'d' * 1200}"
                    ),
                    "total_diff": index,
                }
                for index in range(12)
            ],
            diff_history=[
                {
                    "snapshot_index": index,
                    "total_diff": index,
                    "changes": {
                        "changed": [
                            {
                                "previous_key": "narrative",
                                "previous_value": "e" * 1000,
                                "current_key": "decision",
                                "current_value": "f" * 1000,
                            }
                        ],
                    },
                }
                for index in range(20)
            ],
        )

        self.assertIn(
            "L3 compact digest minimal: False",
            prompt,
        )
        self.assertNotIn(
            "Compact L2 pattern context:",
            prompt,
        )
        self.assertNotIn(
            "Current L2 pattern memory for context only:",
            prompt,
        )
        self.assertEqual(
            prompt.count("snapshot:"),
            12,
        )
        self.assertNotIn(
            "c" * 500,
            prompt,
        )
        self.assertNotIn(
            "e" * 500,
            prompt,
        )
        self.assertIn(
            "omitted_older_diffs:",
            prompt,
        )

    def test_l3_session_memory_prompt_filters_noisy_l1_diff_keys(self):

        prompt = build_runtime_session_memory_user_prompt(
            current_session_memory="decision: old handoff",
            runtime_memory_snapshots=[
                {
                    "index": 1,
                    "raw_memory": "decision: keep useful snapshot",
                    "total_diff": 80,
                },
            ],
            diff_history=[
                {
                    "snapshot_index": 1,
                    "total_diff": 240.95,
                    "changes": {
                        "added": [
                            {
                                "key": "last_jin_response",
                            },
                            {
                                "key": "user_name",
                            },
                            {
                                "key": "active_memory_temporal_continuity",
                            },
                        ],
                        "changed": [
                            {
                                "current_key": "user_message",
                            },
                            {
                                "current_key": "user_idle",
                            },
                        ],
                        "removed": [
                            {
                                "key": "last_jin_response",
                            },
                        ],
                    },
                },
                {
                    "snapshot_index": 2,
                    "total_diff": 172.2,
                    "changes": {
                        "added": [
                            {
                                "key": "last_jin_response",
                            },
                        ],
                        "changed": [
                            {
                                "current_key": "active_memory_temporal_continuity",
                            },
                            {
                                "current_key": "user_idle",
                            },
                        ],
                        "removed": [
                            {
                                "key": "last_jin_response",
                            },
                        ],
                    },
                },
            ],
        )

        self.assertIn(
            '"user_name"',
            prompt,
        )
        self.assertNotIn(
            "last_jin_response",
            prompt,
        )
        self.assertNotIn(
            "active_memory_temporal_continuity",
            prompt,
        )
        self.assertNotIn(
            "user_message",
            prompt,
        )
        self.assertNotIn(
            "user_idle",
            prompt,
        )
        self.assertIn(
            '"snapshot_index": 1',
            prompt,
        )
        self.assertNotIn(
            '"snapshot_index": 2',
            prompt,
        )

    def test_l3_session_memory_budget_uses_detected_context_window(self):

        system_prompt = "system " * 2000
        user_prompt = "user " * 2000

        configured_budget = build_l3_session_memory_max_tokens(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        detected_budget = build_l3_session_memory_max_tokens(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            context_window=8192,
        )

        self.assertEqual(
            configured_budget,
            128,
        )
        self.assertGreater(
            detected_budget,
            configured_budget,
        )

    async def test_l3_session_memory_updates_from_snapshot_history(self):

        service_client = FakeServiceClient(
            "decision: Continue session memory implementation\n"
            "next step: Verify browser persistence"
        )
        logger = FakeLogger()
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            emitter=SimpleNamespace(
                events=[],
                emit=None,
            ),
            logger=logger,
            runtime_save_session_requested=True,
            runtime_l3_session_memory="",
            session_memory="",
            session_memory_source="",
            runtime_session_memory_updates=0,
            runtime_l2_memory="",
            timestamp="2026-06-05T13:38:50",
            current_date="2026-06-05",
            current_time="13:38:50",
            weekday="Friday",
            year=2026,
            runtime_l1_diff_history=[
                {
                    "snapshot_index": 1,
                    "total_diff": 80,
                },
            ],
            runtime_memory_snapshot_index=1,
            runtime_memory_snapshots=[
                {
                    "index": 0,
                    "raw_memory": "topic: first topic",
                    "total_diff": 30,
                },
                {
                    "index": 1,
                    "raw_memory": "decision: final direction",
                    "total_diff": 80,
                },
            ],
        )

        async def emit(event):
            context.emitter.events.append(
                event
            )

        context.emitter.emit = emit

        updated_memory = await maybe_summarize_runtime_session_memory(
            context=context,
        )

        self.assertIn(
            "Continue session memory implementation",
            updated_memory,
        )
        self.assertTrue(
            updated_memory.startswith(
                "session_saved_at: 2026-06-05 13:38, Friday\n"
                "session_snapshot_first_turn: 0\n"
            )
        )
        self.assertEqual(
            context.runtime_session_memory_updates,
            1,
        )
        self.assertFalse(
            context.runtime_save_session_requested,
        )
        self.assertEqual(
            context.runtime_memory_snapshots,
            [
                {
                    "index": 0,
                    "raw_memory": "topic: first topic",
                    "total_diff": 30,
                },
                {
                    "index": 1,
                    "raw_memory": "decision: final direction",
                    "total_diff": 80,
                },
            ],
        )
        self.assertEqual(
            context.runtime_memory_snapshot_index,
            1,
        )
        self.assertEqual(
            context.session_memory_source,
            "L3",
        )
        self.assertIn(
            "topic: first topic",
            service_client.calls[0]["user_prompt"],
        )
        self.assertIn(
            "decision: final direction",
            service_client.calls[0]["user_prompt"],
        )
        self.assertIn(
            "<USER_DATETIME>2026-06-05 13:38, Friday</USER_DATETIME>",
            service_client.calls[0]["user_prompt"],
        )
        self.assertLess(
            service_client.calls[0]["user_prompt"].index(
                "<CURRENT_TRUSTED_RUNTIME_VARIABLES>"
            ),
            service_client.calls[0]["user_prompt"].index(
                "Current L3 session memory:"
            ),
        )
        self.assertEqual(
            service_client.calls[0]["timeout"],
            config.SERVICE_REQUEST_TIMEOUT,
        )
        self.assertLess(
            service_client.calls[0]["max_tokens"],
            config.SERVICE_MAX_TOKENS,
        )
        self.assertGreaterEqual(
            service_client.calls[0]["max_tokens"],
            128,
        )
        self.assertEqual(
            service_client.calls[0]["max_tokens"],
            L3_OUTPUT_MAX_TOKENS,
        )
        self.assertIn(
            (
                "[MEMORY:L3] L3 session output token budget capped at "
                f"{L3_OUTPUT_MAX_TOKENS}"
            ),
            logger.runtime_logs,
        )
        self.assertEqual(
            context.emitter.events[-2]["type"],
            "runtime_session_memory_update",
        )
        self.assertTrue(
            context.emitter.events[-2]["persist"],
        )
        self.assertEqual(
            context.emitter.events[-1],
            {
                "type": "runtime_action",
                "action": "save_session",
                "status": "completed",
            },
        )

    async def test_l3_session_memory_uses_timestamp_when_date_fields_are_empty(self):

        service_client = FakeServiceClient(
            "decision: Continue restored session"
        )
        logger = FakeLogger()
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            emitter=SimpleNamespace(
                events=[],
                emit=None,
            ),
            logger=logger,
            runtime_save_session_requested=True,
            runtime_l3_session_memory="",
            session_memory="",
            session_memory_source="",
            runtime_session_memory_updates=0,
            runtime_l2_memory="",
            timestamp="2026-06-05T13:38:50",
            current_date="",
            current_time="",
            weekday="",
            year=2026,
            runtime_l1_diff_history=[],
            runtime_memory_snapshot_index=1,
            runtime_memory_snapshots=[
                {
                    "index": 1,
                    "raw_memory": "decision: restored tail",
                    "total_diff": 80,
                },
            ],
        )

        async def emit(event):
            context.emitter.events.append(
                event
            )

        context.emitter.emit = emit

        updated_memory = await maybe_summarize_runtime_session_memory(
            context=context,
        )

        self.assertTrue(
            updated_memory.startswith(
                "session_saved_at: 2026-06-05 13:38, Friday\n"
            )
        )
        self.assertNotIn(
            "session_saved_at: ,",
            updated_memory,
        )

    async def test_l3_session_memory_uses_current_runtime_update_steps_after_restore(self):

        service_client = FakeServiceClient(
            "decision: Continue restored current session"
        )
        logger = FakeLogger()
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            emitter=SimpleNamespace(
                events=[],
                emit=None,
            ),
            logger=logger,
            runtime_save_session_requested=True,
            runtime_l3_session_memory=(
                "session_saved_at: 2026-06-01 09:00, Monday\n"
                "session_snapshot_first_turn: 42\n"
                "session_snapshot_last_turn: 99\n"
                "decision: restored previous session handoff"
            ),
            session_memory_source="browser_localStorage",
            session_memory="",
            runtime_session_memory_updates=1,
            runtime_l3_saved_runtime_snapshot_index=None,
            runtime_l2_memory="",
            timestamp="2026-06-05T13:38:50",
            current_date="",
            current_time="",
            weekday="",
            year=2026,
            turn_number=97,
            user_message_count=97,
            assistant_message_count=108,
            runtime_memory_updates=13,
            runtime_l1_diff_history=[
                {
                    "snapshot_index": 1,
                    "total_diff": 80,
                },
            ],
            runtime_memory_snapshot_index=1,
            runtime_memory_snapshots=[
                {
                    "index": 1,
                    "raw_memory": "decision: current restored session tail",
                    "total_diff": 80,
                },
            ],
        )

        async def emit(event):
            context.emitter.events.append(
                event
            )

        context.emitter.emit = emit

        updated_memory = await maybe_summarize_runtime_session_memory(
            context=context,
        )

        self.assertIn(
            "session_saved_at: 2026-06-05 13:38, Friday",
            updated_memory,
        )
        self.assertIn(
            "session_snapshot_first_turn: 1",
            updated_memory,
        )
        self.assertIn(
            "session_snapshot_last_turn: 13",
            updated_memory,
        )
        self.assertEqual(
            context.runtime_l3_session_first_turn,
            1,
        )
        self.assertEqual(
            context.runtime_l3_session_last_turn,
            13,
        )

    async def test_l3_session_memory_merges_previous_snapshot_with_unsaved_tail_only(self):

        service_client = FakeServiceClient(
            "decision: merged handoff after new tail"
        )
        logger = FakeLogger()
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            emitter=SimpleNamespace(
                events=[],
                emit=None,
            ),
            logger=logger,
            runtime_save_session_requested=True,
            runtime_l3_session_memory=(
                "session_snapshot_first_turn: 0\n"
                "session_snapshot_last_turn: 15\n"
                "decision: old consolidated handoff"
            ),
            session_memory="",
            session_memory_source="",
            runtime_session_memory_updates=1,
            runtime_l3_saved_runtime_snapshot_index=15,
            runtime_l3_session_first_turn=0,
            runtime_l3_session_last_turn=15,
            runtime_l2_memory="",
            timestamp="2026-06-05T13:38:50",
            current_date="2026-06-05",
            current_time="13:38:50",
            weekday="Friday",
            year=2026,
            runtime_l1_diff_history=[
                {
                    "snapshot_index": 15,
                    "total_diff": 80,
                },
                {
                    "snapshot_index": 16,
                    "total_diff": 20,
                },
                {
                    "snapshot_index": 20,
                    "total_diff": 70,
                },
            ],
            runtime_memory_snapshot_index=20,
            runtime_memory_snapshots=[
                {
                    "index": 14,
                    "raw_memory": "topic: old stale page",
                    "total_diff": 30,
                },
                {
                    "index": 15,
                    "raw_memory": "decision: old saved boundary",
                    "total_diff": 80,
                },
                {
                    "index": 16,
                    "raw_memory": "topic: fresh tail starts",
                    "total_diff": 20,
                },
                {
                    "index": 20,
                    "raw_memory": "decision: fresh tail ends",
                    "total_diff": 70,
                },
            ],
        )

        async def emit(event):
            context.emitter.events.append(
                event
            )

        context.emitter.emit = emit

        updated_memory = await maybe_summarize_runtime_session_memory(
            context=context,
        )

        prompt = service_client.calls[0]["user_prompt"]

        self.assertIn(
            "decision: old consolidated handoff",
            prompt,
        )
        self.assertIn(
            "topic: fresh tail starts",
            prompt,
        )
        self.assertIn(
            "decision: fresh tail ends",
            prompt,
        )
        self.assertNotIn(
            "topic: old stale page",
            prompt,
        )
        self.assertNotIn(
            "decision: old saved boundary",
            prompt,
        )
        self.assertIn(
            "session_snapshot_first_turn: 0",
            updated_memory,
        )
        self.assertTrue(
            updated_memory.startswith(
                "session_saved_at: 2026-06-05 13:38, Friday\n"
                "session_snapshot_first_turn: 0\n"
            )
        )
        self.assertIn(
            "session_snapshot_last_turn: 20",
            updated_memory,
        )
        self.assertEqual(
            context.runtime_l3_saved_runtime_snapshot_index,
            20,
        )
        self.assertEqual(
            context.runtime_l3_session_last_turn,
            20,
        )

    async def test_l3_session_memory_logs_when_response_reaches_max_tokens(self):

        service_client = FakeServiceClient(
            "decision: incomplete",
            finish_reasons=[
                "length",
            ],
        )
        logger = FakeLogger()
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            emitter=SimpleNamespace(
                events=[],
                emit=None,
            ),
            logger=logger,
            runtime_save_session_requested=True,
            runtime_l3_session_memory="decision: keep current",
            session_memory="decision: keep current",
            session_memory_source="",
            runtime_session_memory_updates=0,
            runtime_l2_memory="",
            runtime_l1_diff_history=[],
            runtime_memory_snapshots=[
                {
                    "index": 0,
                    "raw_memory": "topic: first topic",
                    "total_diff": 30,
                },
            ],
        )

        async def emit(event):
            context.emitter.events.append(
                event
            )

        context.emitter.emit = emit

        updated_memory = await maybe_summarize_runtime_session_memory(
            context=context,
        )

        self.assertEqual(
            updated_memory,
            "decision: keep current",
        )
        self.assertFalse(
            context.runtime_save_session_requested,
        )
        self.assertFalse(
            context.runtime_save_session_action_emitted,
        )
        calls_after_skip = len(
            service_client.calls
        )
        repeated_memory = await maybe_summarize_runtime_session_memory(
            context=context,
        )
        self.assertEqual(
            repeated_memory,
            "decision: keep current",
        )
        self.assertEqual(
            len(service_client.calls),
            calls_after_skip,
        )
        self.assertEqual(
            context.runtime_memory_snapshots,
            [
                {
                    "index": 0,
                    "raw_memory": "topic: first topic",
                    "total_diff": 30,
                },
            ],
        )
        self.assertIn(
            "[MEMORY:L3] L3 session summarizer reached max_tokens",
            logger.runtime_logs,
        )
        self.assertEqual(
            logger.errors[-1][0],
            "[MEMORY:L3] L3 session memory update skipped",
        )
        self.assertIn(
            "truncated by max_tokens",
            logger.errors[-1][1],
        )

    async def test_l3_session_memory_skips_when_minimal_digest_exceeds_budget(self):

        class TinyContextServiceClient(FakeServiceClient):

            async def resolve_request_context_window(self):
                return 600

        service_client = TinyContextServiceClient(
            "should not be called"
        )
        logger = FakeLogger()
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            emitter=SimpleNamespace(
                events=[],
                emit=None,
            ),
            logger=logger,
            runtime_save_session_requested=True,
            runtime_l3_session_memory="decision: keep current",
            session_memory="decision: keep current",
            session_memory_source="",
            runtime_session_memory_updates=0,
            runtime_l2_memory="",
            runtime_l1_diff_history=[],
            runtime_memory_snapshots=[
                {
                    "index": 0,
                    "raw_memory": "decision: keep latest",
                    "total_diff": 1,
                }
            ],
        )

        async def emit(event):
            context.emitter.events.append(
                event
            )

        context.emitter.emit = emit

        updated_memory = await maybe_summarize_runtime_session_memory(
            context=context,
        )

        self.assertEqual(
            updated_memory,
            "decision: keep current",
        )
        self.assertEqual(
            service_client.calls,
            [],
        )
        self.assertFalse(
            context.runtime_save_session_requested,
        )
        self.assertEqual(
            context.emitter.events[-1],
            {
                "type": "runtime_action",
                "action": "save_session",
                "status": "completed",
            },
        )
        self.assertEqual(
            logger.errors[-1][0],
            "[MEMORY:L3] L3 session memory update skipped",
        )
        self.assertIn(
            "compact digest still exceeds safe input budget",
            logger.errors[-1][1],
        )
        self.assertEqual(
            context.runtime_memory_snapshots,
            [
                {
                    "index": 0,
                    "raw_memory": "decision: keep latest",
                    "total_diff": 1,
                }
            ],
        )

    async def test_l3_session_memory_preserves_snapshots_when_update_fails(self):

        service_client = FakeServiceClient(
            RuntimeError("service unavailable")
        )
        logger = FakeLogger()
        snapshots = [
            {
                "index": 0,
                "raw_memory": "topic: first topic",
                "total_diff": 30,
            },
            {
                "index": 1,
                "raw_memory": "decision: final direction",
                "total_diff": 80,
            },
        ]
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            emitter=SimpleNamespace(
                events=[],
                emit=None,
            ),
            logger=logger,
            runtime_save_session_requested=True,
            runtime_l3_session_memory="decision: keep current",
            session_memory="decision: keep current",
            session_memory_source="",
            runtime_l2_memory="",
            runtime_l1_diff_history=[],
            runtime_memory_snapshots=list(snapshots),
        )

        async def emit(event):
            context.emitter.events.append(
                event
            )

        context.emitter.emit = emit

        updated_memory = await maybe_summarize_runtime_session_memory(
            context=context,
        )

        self.assertEqual(
            updated_memory,
            "decision: keep current",
        )
        self.assertFalse(
            context.runtime_save_session_requested,
        )
        self.assertEqual(
            context.runtime_memory_snapshots,
            snapshots,
        )
        self.assertEqual(
            logger.errors[-1][0],
            "[MEMORY:L3] L3 session memory update failed",
        )

    async def test_l3_session_memory_no_snapshots_clears_save_request(self):

        service_client = FakeServiceClient(
            "should not be called"
        )
        logger = FakeLogger()
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            emitter=SimpleNamespace(
                events=[],
                emit=None,
            ),
            logger=logger,
            runtime_save_session_requested=True,
            runtime_l3_session_memory="decision: keep current",
            session_memory="decision: keep current",
            runtime_memory_snapshots=[],
        )

        async def emit(event):
            context.emitter.events.append(
                event
            )

        context.emitter.emit = emit

        updated_memory = await maybe_summarize_runtime_session_memory(
            context=context,
        )

        self.assertEqual(
            updated_memory,
            "decision: keep current",
        )
        self.assertEqual(
            service_client.calls,
            [],
        )
        self.assertEqual(
            context.runtime_memory_snapshots,
            [],
        )
        self.assertFalse(
            context.runtime_save_session_requested,
        )
        self.assertEqual(
            logger.runtime_logs,
            [
                "[MEMORY:L3] L3 session save skipped: no snapshots",
            ],
        )

    async def test_summarizer_usage_corrects_estimate_with_prompt_usage(self):

        service_client = FakeServiceClient(
            "Exact memory.",
            usage={
                "prompt_tokens": 90,
                "completion_tokens": 33,
                "total_tokens": 123,
            },
            context_window=8192,
        )
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            emitter=SimpleNamespace(
                events=[],
                emit=None,
            ),
            logger=FakeLogger(),
            runtime_memory="Initial memory.",
            runtime_memory_updates=0,
            runtime_memory_snapshots=[],
            runtime_memory_snapshot_index=0,
            session_id="test-session",
        )

        async def emit(event):
            context.emitter.events.append(
                event
            )

        context.emitter.emit = emit

        await summarize_runtime_memory(
            context=context,
            user_message="Remember this exactly.",
            assistant_message="I will update memory.",
        )

        telemetry_events = [
            event
            for event in context.emitter.events
            if event["type"] == "telemetry"
        ]

        self.assertEqual(
            len(telemetry_events),
            2,
        )
        self.assertEqual(
            telemetry_events[-1]["runtime"][
                RUNTIME_MEMORY_SUMMARIZER_RUNTIME_ID
            ]["used_tokens"],
            123,
        )
        self.assertEqual(
            telemetry_events[-1]["runtime"][
                RUNTIME_MEMORY_SUMMARIZER_RUNTIME_ID
            ]["context_tokens"],
            90,
        )
        self.assertEqual(
            telemetry_events[-1]["runtime"][
                RUNTIME_MEMORY_SUMMARIZER_RUNTIME_ID
            ]["total_tokens"],
            123,
        )
        self.assertEqual(
            telemetry_events[-1]["runtime"][
                RUNTIME_MEMORY_SUMMARIZER_RUNTIME_ID
            ]["max_tokens"],
            8192,
        )

    async def test_summarizer_uses_service_max_tokens(self):

        service_client = FakeServiceClient(
            "- Active topic: available functions\n"
            "- Capabilities listed: answering questions and writing text",
        )
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            emitter=SimpleNamespace(
                events=[],
                emit=None,
            ),
            logger=FakeLogger(),
            runtime_memory="",
            runtime_memory_updates=0,
            runtime_memory_snapshots=[],
            runtime_memory_snapshot_index=0,
            session_id="test-session",
        )

        updated_memory = await summarize_runtime_memory(
            context=context,
            user_message="What can you do?",
            assistant_message="I can answer questions and write text.",
        )

        # Keep this test focused on the L1 request budget contract.
        # The summarizer may normalize bullet prefixes, so exact formatting is not relevant here.
        self.assertIn(
            "Active topic: available functions",
            updated_memory,
        )
        self.assertIn(
            "Capabilities listed: answering questions and writing text",
            updated_memory,
        )
        self.assertEqual(
            len(
                service_client.calls
            ),
            1,
        )
        self.assertEqual(
            service_client.calls[0]["max_tokens"],
            config.SERVICE_MAX_TOKENS,
        )
        self.assertEqual(
            service_client.calls[0]["timeout"],
            config.SERVICE_REQUEST_TIMEOUT,
        )

    async def test_summarizer_skips_incomplete_memory(self):

        logger = FakeLogger()
        service_client = FakeServiceClient(
            "- Active topic: available functions\n"
            "- Capabilities listed: answering questions (emails",
        )
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            logger=logger,
            runtime_memory="Initial memory.",
            runtime_memory_updates=0,
        )

        updated_memory = await summarize_runtime_memory(
            context=context,
            user_message="What can you do?",
            assistant_message="I can answer questions.",
        )

        self.assertEqual(
            updated_memory,
            "note: Initial memory.",
        )
        self.assertEqual(
            context.runtime_memory,
            "note: Initial memory.",
        )
        self.assertEqual(
            context.runtime_memory_updates,
            0,
        )
        self.assertTrue(
            logger.errors
        )

    async def test_summarizer_failure_logs_traceback_details(self):

        class SilentError(Exception):
            def __str__(self):
                return ""

        logger = FakeLogger()
        service_client = FakeServiceClient(
            SilentError()
        )
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            logger=logger,
            runtime_memory="Initial memory.",
            runtime_memory_updates=0,
        )

        updated_memory = await summarize_runtime_memory(
            context=context,
            user_message="Remember this.",
            assistant_message="I will remember it.",
        )

        self.assertEqual(
            updated_memory,
            "note: Initial memory.",
        )
        self.assertEqual(
            len(logger.errors),
            1,
        )

        message, details = logger.errors[0]

        self.assertEqual(
            message,
            "[MEMORY:L1] L1 runtime memory update failed",
        )
        self.assertIn(
            "Traceback (most recent call last):",
            details,
        )
        self.assertIn(
            "SilentError",
            details,
        )

    async def test_summarizer_failure_logs_likely_token_reason(self):

        request = httpx.Request(
            "POST",
            "http://127.0.0.1:1234/v1/chat/completions",
        )
        response = httpx.Response(
            400,
            json={
                "error": {
                    "message": (
                        "This model's maximum context length is 8192 tokens, "
                        "but the request asked for 9000 tokens."
                    ),
                    "type": "invalid_request_error",
                    "code": "context_length_exceeded",
                }
            },
            request=request,
        )
        service_client = FakeServiceClient(
            httpx.HTTPStatusError(
                "Client error '400 Bad Request'",
                request=request,
                response=response,
            )
        )
        logger = FakeLogger()
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            logger=logger,
            runtime_memory="Initial memory.",
            runtime_memory_updates=0,
        )

        await summarize_runtime_memory(
            context=context,
            user_message="Remember this.",
            assistant_message="I will remember it.",
        )

        _message, details = logger.errors[0]

        self.assertIn(
            "Likely reason: Token/context limit exceeded",
            details,
        )
        self.assertIn(
            "context_length_exceeded",
            details,
        )
        self.assertIn(
            "Traceback:",
            details,
        )

    async def test_scheduled_update_is_background_task(self):

        service_client = FakeServiceClient(
            "Updated background memory."
        )
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            logger=FakeLogger(),
            runtime_memory="Initial memory.",
            runtime_memory_stable="Initial memory.",
            runtime_memory_updates=0,
            runtime_memory_pending_turns=[],
            runtime_memory_update_task=None,
        )

        task = schedule_runtime_memory_update(
            context=context,
            user_message="First message",
            assistant_message="First answer",
        )

        self.assertIsNotNone(
            task
        )
        self.assertTrue(
            hasattr(
                context,
                "background_tasks",
            )
        )

        await task

        user_prompt = service_client.calls[0]["user_prompt"]

        self.assertNotIn(
            "<CURRENT_TRUSTED_RUNTIME_VARIABLES>",
            user_prompt,
        )
        self.assertNotIn(
            "New completed turns since that memory snapshot:",
            user_prompt,
        )

        self.assertIn(
            "Updated background memory.",
            context.runtime_memory,
        )
        self.assertIn(
            'user_message: "First message"',
            context.runtime_memory,
        )
        self.assertIn(
            "last_jin_response: First answer",
            context.runtime_memory,
        )
        self.assertEqual(
            context.logger.summarizer_logs[0][0],
            "[MEMORY:L1] L1 summarizer request",
        )
        self.assertEqual(
            service_client.calls[0]["timeout"],
            config.SERVICE_REQUEST_TIMEOUT,
        )
        self.assertEqual(
            len(
                context.background_tasks
            ),
            0,
        )

    async def test_pending_turns_log_batch_only_for_multiple_turns(self):

        service_client = FakeServiceClient(
            "Updated batch memory."
        )
        logger = FakeLogger()
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            logger=logger,
            runtime_memory="Initial memory.",
            runtime_memory_stable="Initial memory.",
            runtime_memory_updates=0,
            runtime_memory_pending_turns=[
                {
                    "user_message": "First message",
                    "assistant_message": "First answer",
                },
                {
                    "user_message": "Second message",
                    "assistant_message": "Second answer",
                },
            ],
            runtime_memory_update_task=None,
        )

        await summarize_runtime_memory_pending_turns(
            context=context,
        )

        self.assertEqual(
            logger.summarizer_logs[0][0],
            "[MEMORY:L1] L1 batch summarizer request",
        )
        self.assertEqual(
            service_client.calls[0]["timeout"],
            config.SERVICE_REQUEST_TIMEOUT,
        )

    async def test_interrupted_update_uses_partial_response(self):

        service_client = FakeServiceClient(
            "- Active topic: storytelling\n"
            "- Interrupted response: user stopped the answer before completion"
        )
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            logger=FakeLogger(),
            runtime_memory="Initial memory.",
            runtime_memory_stable="Initial memory.",
            runtime_memory_updates=0,
            runtime_memory_pending_turns=[],
            runtime_memory_update_task=None,
            runtime_turn_user_message="Tell me a story.",
            runtime_turn_assistant_response="Once upon a",
        )

        task = schedule_interrupted_runtime_memory_update(
            context=context,
        )

        self.assertIsNotNone(
            task
        )

        await task

        user_prompt = service_client.calls[0]["user_prompt"]

        self.assertIn(
            "interrupted by the user",
            user_prompt,
        )
        self.assertIn(
            "Tell me a story.",
            user_prompt,
        )
        self.assertIn(
            "Once upon a",
            user_prompt,
        )
        self.assertIn(
            "Interrupted response",
            context.runtime_memory,
        )

    async def test_guard_interrupted_update_uses_reason_and_quote(self):

        service_client = FakeServiceClient(
            "- Interrupted response: repeated sentence loop stopped"
        )
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            logger=FakeLogger(),
            runtime_memory="Initial memory.",
            runtime_memory_stable="Initial memory.",
            runtime_memory_updates=0,
            runtime_memory_pending_turns=[],
            runtime_memory_update_task=None,
            runtime_turn_user_message="Use append_skill if needed.",
            runtime_turn_assistant_response="Partial answer",
            runtime_turn_interruption_reason=(
                "Repeated sentence loop detected."
            ),
            runtime_turn_interruption_quote=(
                "Wait, I'll check if I should use append_skill first."
            ),
        )

        task = schedule_interrupted_runtime_memory_update(
            context=context,
        )

        self.assertIsNotNone(
            task
        )

        await task

        user_prompt = service_client.calls[0]["user_prompt"]

        self.assertIn(
            "Repeated sentence loop detected.",
            user_prompt,
        )
        self.assertIn(
            "Wait, I'll check if I should use append_skill first.",
            user_prompt,
        )
        self.assertNotIn(
            "interrupted by the user",
            user_prompt,
        )


if __name__ == "__main__":
    unittest.main()
