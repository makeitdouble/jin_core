import unittest
from types import (
    SimpleNamespace,
)
import httpx
from runtime.L1_memory_rules import (
    DEFAULT_RUNTIME_MEMORY,
    build_runtime_memory_system_prompt,
)
from runtime.state import (
    RUNTIME_MEMORY_SUMMARIZER_RUNTIME_ID,
)
from runtime.runtime_context import (
    RuntimeContext,
)
from runtime.L1_memory_utils import (
    build_interrupted_assistant_message,
    build_runtime_memory_context_text,
    build_runtime_memory_snapshot,
    build_runtime_memory_user_prompt,
    enforce_runtime_turn_fields,
    get_strength_zones,
    normalize_compound_runtime_memory_lines,
    parse_runtime_memory_lines,
    quote_runtime_user_message_value,
    record_runtime_memory_reasoning_quotes,
)
from runtime.L1_memory import (
    apply_runtime_response_feedback,
    build_runtime_response_feedback_value,
    normalize_runtime_response_feedback,
    summarize_runtime_memory,
)
from utils.actions import (
    refresh_active_memory_runtime_metadata,
    remove_active_memory_entries,
    strip_active_memory_runtime_metadata,
)
from config_loader import (
    config,
)
from tests.helpers.memory import (
    FakeLogger,
    FakeServiceClient,
    assert_contains_text,
    assert_not_contains_text,
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

class L1MemoryTests(
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

    def test_runtime_memory_reasoning_quotes_boost_trace_once_per_response(self):

            context = RuntimeContext(
                websocket=object(),
                emitter=object(),
                logger=object(),
                clients={},
            )
            context.runtime_memory = (
                "topic: The user is tuning runtime memory trace "
                "through reasoning citations"
            )
            context.runtime_current_turn_id = "turn-1"

            reasoning = (
                "I should lean on this memory: The user is tuning runtime "
                "memory trace through reasoning citations. Repeating it: "
                "The user is tuning runtime memory trace through reasoning "
                "citations."
            )

            result = record_runtime_memory_reasoning_quotes(
                context,
                reasoning,
            )
            snapshot = build_runtime_memory_snapshot(
                context,
                context.runtime_memory,
            )
            line = snapshot["lines"][0]

            self.assertEqual(
                result["quoted_line_count"],
                1,
            )
            self.assertEqual(
                line["total_quotes_count"],
                1,
            )
            self.assertEqual(
                line["messages_quote_count"],
                1,
            )
            self.assertEqual(
                line["quote_boost"],
                0.06,
            )
            self.assertEqual(
                line["strength"],
                0.56,
            )
            self.assertIn(
                "[ total_quotes_count: 1 ]",
                snapshot["annotated_memory"],
            )
            self.assertIn(
                "[ messages_quote_count: 1 ]",
                snapshot["annotated_memory"],
            )

    def test_runtime_memory_reasoning_quotes_accumulate_across_responses(self):

            context = RuntimeContext(
                websocket=object(),
                emitter=object(),
                logger=object(),
                clients={},
            )
            context.runtime_memory = (
                "topic: The exact memory line keeps guiding later reasoning"
            )
            context.runtime_current_turn_id = "turn-1"

            record_runtime_memory_reasoning_quotes(
                context,
                "The exact memory line keeps guiding later reasoning.",
            )
            first_snapshot = build_runtime_memory_snapshot(
                context,
                context.runtime_memory,
            )
            context.runtime_memory_snapshots.append(
                first_snapshot
            )
            context.runtime_memory_pending_quote_identities = set()
            context.runtime_current_turn_id = "turn-2"

            record_runtime_memory_reasoning_quotes(
                context,
                "Again, the exact memory line keeps guiding later reasoning.",
            )
            second_snapshot = build_runtime_memory_snapshot(
                context,
                context.runtime_memory,
            )
            line = second_snapshot["lines"][0]

            self.assertEqual(
                line["total_quotes_count"],
                2,
            )
            self.assertEqual(
                line["messages_quote_count"],
                2,
            )
            self.assertGreater(
                line["strength"],
                first_snapshot["lines"][0]["strength"],
            )

    def test_runtime_memory_quote_history_uses_exact_key_value_identity(self):

            context = RuntimeContext(
                websocket=object(),
                emitter=object(),
                logger=object(),
                clients={},
            )
            original_memory = (
                "topic: The exact memory line keeps guiding later reasoning"
            )
            context.runtime_memory = original_memory
            context.runtime_current_turn_id = "turn-1"

            record_runtime_memory_reasoning_quotes(
                context,
                "The exact memory line keeps guiding later reasoning.",
            )
            first_snapshot = build_runtime_memory_snapshot(
                context,
                original_memory,
            )
            context.runtime_memory_snapshots.append(
                first_snapshot
            )
            context.runtime_memory_pending_quote_identities = set()

            context.runtime_memory = (
                "topic: The summarizer rewrote the thought into a new value"
            )
            second_snapshot = build_runtime_memory_snapshot(
                context,
                context.runtime_memory,
            )
            line = second_snapshot["lines"][0]

            self.assertEqual(
                line["total_quotes_count"],
                0,
            )
            self.assertEqual(
                line["messages_quote_count"],
                0,
            )
            self.assertEqual(
                line["strength"],
                0.5,
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

    def test_interrupted_assistant_message_includes_aborted_actions(self):

            message = build_interrupted_assistant_message(
                user_message="Save a delayed memory report.",
                assistant_message="Okay, saving.",
                aborted_actions=[
                    {
                        "name": "SAVE_DELAYED_MEMORY_CONTENT",
                        "status": "aborted",
                    },
                ],
            )

            self.assertIn(
                "Okay, saving.",
                message,
            )
            self.assertIn(
                "SAVE_DELAYED_MEMORY_CONTENT: ABORTED",
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

