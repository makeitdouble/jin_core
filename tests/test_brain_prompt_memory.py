import unittest
from types import (
    SimpleNamespace,
)
from unittest.mock import (
    patch,
)
from rules.brain_context_builder import (
    PREVIOUS_REASONING_EDGE_PERCENT,
    PREVIOUS_REASONING_MIN_CROP_CHARS,
    build_brain_context,
    crop_previous_reasoning_text,
)
from utils.context.context_exports import (
    build_session_actions_history_context,
)
from runtime.L1_memory_rules import (
    DEFAULT_RUNTIME_MEMORY,
)
from runtime.runtime_context import (
    RuntimeContext,
)
from runtime.L1_memory_utils import (
    build_runtime_memory_snapshot,
)

class BrainPromptMemoryTests(
    unittest.IsolatedAsyncioTestCase
):

    def test_first_brain_prompt_includes_default_runtime_memory(self):

            context = RuntimeContext(
                websocket=object(),
                emitter=object(),
                logger=object(),
                clients={},
            )

            prompt = build_brain_context(
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

            prompt = build_brain_context(
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

            prompt = build_brain_context(
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

    def test_brain_prompt_includes_runtime_memory(self):

            context = SimpleNamespace(
                runtime_memory=(
                    "The user recently asked about Lamborghini pricing."
                ),
                deep_thought_count=0,
                runtime_search_result="",
                runtime_search_result_id="",
            )

            prompt = build_brain_context(
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
                "utils.context.context_exports.time.time",
                return_value=1000.0,
            ):
                prompt = build_brain_context(
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

    def test_previous_reasoning_is_inserted_after_session_actions_history(self):

            context = SimpleNamespace(
                runtime_memory="",
                deep_thought_count=0,
                runtime_search_result="",
                runtime_search_result_id="",
                runtime_session_action_history=[
                    {
                        "text": "CLEAN_TOOL_RESULTS",
                    },
                ],
                runtime_previous_reasoning_content=(
                    "first internal note <private>\n"
                    "short conclusion"
                ),
            )

            prompt = build_brain_context(
                context=context,
                runtime_actions={
                    "CAN_WEB_SEARCH": False,
                },
                include_runtime_action_instructions=False,
            )

            self.assertIn(
                "<PREVIOUS_JIN_RESPONSE_REASONING>",
                prompt,
            )
            self.assertIn(
                "first internal note &lt;private&gt;",
                prompt,
            )
            self.assertLess(
                prompt.index("</SESSION_ACTIONS_HISTORY>"),
                prompt.index("<PREVIOUS_JIN_RESPONSE_REASONING>"),
            )
            self.assertLess(
                prompt.index("</PREVIOUS_JIN_RESPONSE_REASONING>"),
                prompt.index("I identify myself as JIN"),
            )

    def test_previous_reasoning_block_is_inserted_even_when_empty(self):

            context = SimpleNamespace(
                runtime_memory="",
                deep_thought_count=0,
                runtime_search_result="",
                runtime_search_result_id="",
                runtime_session_action_history=[],
                runtime_previous_reasoning_content="",
            )

            prompt = build_brain_context(
                context=context,
                runtime_actions={
                    "CAN_WEB_SEARCH": False,
                },
                include_runtime_action_instructions=False,
            )

            self.assertIn(
                (
                    "<PREVIOUS_JIN_RESPONSE_REASONING>\n"
                    "\n"
                    "</PREVIOUS_JIN_RESPONSE_REASONING>"
                ),
                prompt,
            )
            self.assertLess(
                prompt.index("<PREVIOUS_JIN_RESPONSE_REASONING>"),
                prompt.index("I identify myself as JIN"),
            )

    def test_previous_reasoning_crop_keeps_short_text_whole_and_percent_edges(self):

            short_reasoning = (
                "brief opening\n"
                "brief conclusion"
            )
            self.assertEqual(
                crop_previous_reasoning_text(
                    short_reasoning
                ),
                short_reasoning,
            )

            threshold_reasoning = (
                "x"
                * PREVIOUS_REASONING_MIN_CROP_CHARS
            )
            self.assertEqual(
                crop_previous_reasoning_text(
                    threshold_reasoning
                ),
                threshold_reasoning,
            )

            prefix = "a" * 300
            middle = "m" * 600
            suffix = "z" * 300
            long_reasoning = (
                prefix
                + middle
                + suffix
            )
            edge_chars = int(
                len(long_reasoning)
                * PREVIOUS_REASONING_EDGE_PERCENT
                / 100
            )

            self.assertEqual(
                crop_previous_reasoning_text(
                    long_reasoning
                ),
                prefix[:edge_chars]
                + "\n,,,\n"
                + suffix[-edge_chars:],
            )

    def test_previous_reasoning_can_be_excluded_for_followup_ticks(self):

            context = SimpleNamespace(
                runtime_memory="",
                deep_thought_count=0,
                runtime_search_result="",
                runtime_search_result_id="",
                runtime_session_action_history=[
                    {
                        "text": "CLEAN_TOOL_RESULTS",
                    },
                ],
                runtime_previous_reasoning_content="previous reasoning",
            )

            prompt = build_brain_context(
                context=context,
                runtime_actions={
                    "CAN_WEB_SEARCH": False,
                },
                include_previous_reasoning=False,
            )

            self.assertNotIn(
                "<PREVIOUS_JIN_RESPONSE_REASONING>",
                prompt,
            )

            context.runtime_followup_tick_active = True
            guarded_prompt = build_brain_context(
                context=context,
                runtime_actions={
                    "CAN_WEB_SEARCH": False,
                },
            )

            self.assertNotIn(
                "<PREVIOUS_JIN_RESPONSE_REASONING>",
                guarded_prompt,
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
                "utils.context.context_exports.time.time",
                return_value=1000.0,
            ):
                history = build_session_actions_history_context(
                    context,
                    current_sequence=True,
                )

            self.assertIn(
                "JIN message 1 executed: ASSET_ACTION ( 1s ago )",
                history,
            )
            self.assertNotIn(
                "( 0s ago )",
                history,
            )

    def test_action_context_hides_single_emission_counts(self):

            context = SimpleNamespace(
                runtime_current_turn_id="turn_000002",
                runtime_turn_started_at=900.0,
                runtime_action_sequence_turn_ids=[
                    "turn_000002",
                ],
                runtime_session_action_history=[
                    {
                        "text": "LIST_SKILLS",
                        "parts": [
                            {
                                "text": "LIST_SKILLS",
                                "count": 1,
                            },
                        ],
                        "created_at": 995.0,
                        "runtime_turn_id": "turn_000002",
                    },
                    {
                        "text": (
                            "APPEND_SKILL: file_manager (count: 3), "
                            "CLEAN_TOOL_RESULTS"
                        ),
                        "parts": [
                            {
                                "text": "APPEND_SKILL: file_manager",
                                "count": 3,
                            },
                            {
                                "text": "CLEAN_TOOL_RESULTS",
                                "count": 1,
                            },
                        ],
                        "created_at": 998.0,
                        "runtime_turn_id": "turn_000002",
                    },
                    {
                        "text": "SAVE_SESSION",
                        "parts": [
                            {
                                "text": "SAVE_SESSION",
                                "count": 1,
                            },
                        ],
                        "created_at": 999.0,
                        "runtime_turn_id": "turn_000002",
                    },
                ],
            )

            with patch(
                "utils.context.context_exports.time.time",
                return_value=1000.0,
            ):
                history = build_session_actions_history_context(
                    context,
                    current_sequence=True,
                )

            self.assertNotIn(
                "(count: 1)",
                history,
            )
            self.assertIn(
                "JIN message 1 executed: LIST_SKILLS ( 5s ago )",
                history,
            )
            self.assertIn(
                (
                    "JIN message 2 executed: APPEND_SKILL: file_manager (count: 3), "
                    "CLEAN_TOOL_RESULTS ( 2s ago )"
                ),
                history,
            )
            self.assertIn(
                "JIN message 3 executed: SAVE_SESSION ( 1s ago )",
                history,
            )

    def test_current_sequence_includes_jin_content_for_marker_message_only(self):

            jin_content = (
                "Приятно познакомиться, Сергей. "
                "Сейчас посмотрю, что это за проект Ouroboros."
            )
            context = SimpleNamespace(
                runtime_current_turn_id="turn_000002",
                runtime_turn_started_at=900.0,
                runtime_action_sequence_turn_ids=[
                    "turn_000002",
                ],
                runtime_session_action_history=[
                    {
                        "text": (
                            "WEB_SEARCH - Ouroboros AI project framework "
                            "competitor LLM agents"
                        ),
                        "parts": [
                            {
                                "text": "WEB_SEARCH",
                                "detail": (
                                    "Ouroboros AI project framework "
                                    "competitor LLM agents"
                                ),
                            },
                        ],
                        "created_at": 999.0,
                        "runtime_turn_id": "turn_000002",
                        "jin_message_content": jin_content,
                    },
                ],
            )

            with patch(
                "utils.context.context_exports.time.time",
                return_value=1000.0,
            ):
                current_sequence = build_session_actions_history_context(
                    context,
                    current_sequence=True,
                )
                session_history = build_session_actions_history_context(
                    context,
                )

            self.assertIn(
                (
                    "JIN message 1 content: "
                    f"{jin_content} ( 1s ago )"
                ),
                current_sequence,
            )
            self.assertIn(
                (
                    "JIN message 1 executed: WEB_SEARCH: "
                    "Ouroboros AI project framework competitor LLM agents "
                    "( 1s ago )"
                ),
                current_sequence,
            )
            self.assertIn(
                (
                    "1. WEB_SEARCH: Ouroboros AI project framework "
                    "competitor LLM agents ( 1s ago )"
                ),
                session_history,
            )
            self.assertNotIn(
                "JIN message 1 content",
                session_history,
            )
            self.assertNotIn(
                jin_content,
                session_history,
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
                "utils.context.context_exports.time.time",
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
                    "    JIN message 1 executed: LIST_SKILLS ( 55s ago )\n"
                    "    JIN message 2 executed: APPEND_SKILL ( 2s ago )\n"
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

    def test_current_sequence_expands_memory_action_payloads_without_counts(self):

            context = SimpleNamespace(
                runtime_current_turn_id="turn_000002",
                runtime_turn_started_at=940.0,
                runtime_action_sequence_turn_ids=[
                    "turn_000002",
                ],
                runtime_session_action_history=[
                    {
                        "text": "RESOLVE_ACTIVE_MEMORY, RESOLVE_ACTIVE_MEMORY",
                        "parts": [
                            {
                                "text": "RESOLVE_ACTIVE_MEMORY",
                                "detail": "word: кукушка",
                                "id": "enrrqo",
                            },
                            {
                                "text": "RESOLVE_ACTIVE_MEMORY",
                                "detail": "word: кулёк",
                                "id": "yfpywn",
                            },
                        ],
                        "created_at": 998.0,
                        "runtime_turn_id": "turn_000002",
                    },
                ],
            )

            with patch(
                "utils.context.context_exports.time.time",
                return_value=1000.0,
            ):
                history = build_session_actions_history_context(
                    context,
                    current_sequence=True,
                )

            self.assertIn(
                (
                    "JIN message 1 executed: RESOLVE_ACTIVE_MEMORY: "
                    "id: enrrqo; content: word: кукушка, "
                    "RESOLVE_ACTIVE_MEMORY: id: yfpywn; "
                    "content: word: кулёк ( 2s ago )"
                ),
                history,
            )
            self.assertNotIn(
                "count:",
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
                "utils.context.context_exports.time.time",
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

    def test_brain_prompt_does_not_count_runtime_actions_as_messages(self):

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

            prompt = build_brain_context(
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
                "JIN messages count:           1",
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

            prompt = build_brain_context(
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

            prompt = build_brain_context(
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

            prompt = build_brain_context(
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

            prompt = build_brain_context(
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

            prompt = build_brain_context(
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

            prompt = build_brain_context(
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

            prompt = build_brain_context(
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

            prompt = build_brain_context(
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

            prompt = build_brain_context(
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

            prompt = build_brain_context(
                context=context,
                runtime_actions={
                    "CAN_WEB_SEARCH": False,
                },
            )

            self.assertNotIn(
                "<CONVERSATION_ACTIVITY>",
                prompt,
            )

