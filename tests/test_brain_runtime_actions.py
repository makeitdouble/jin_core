import asyncio
import contextlib
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from utils.context.context_exports import (
    build_runtime_xml,
    build_session_actions_history_context,
)
from clients.brain_client import (
    apply_runtime_action_calls,
    ask_brain_stream,
    build_brain_user_prompt_content,
)
from rules.brain_context_builder import (
    build_brain_context,
    get_enabled_runtime_actions,
)
from config_loader import (
    config,
)
from app_settings import (
    settings,
)
from rules.brain_context_builder import (
    BRAIN_RUNTIME_ACTIONS,
)
from rules import runtime as runtime_rules
from contracts.rules_assembler import (
    get_runtime_action_private_marker,
)
from utils.session_actions_history import (
    build_session_actions_update_items,
    format_session_action_marker_names,
    replace_session_action_history_since,
)
from utils.actions import (
    RuntimeActionCall,
)
from runtime.runtime_context import (
    DEFAULT_JIN_COLOR,
)
from utils.tool_results import (
    TOOL_RESULT_KIND_ASSET,
)
from tests.helpers.runtime_actions import patch_asset_roots



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


def expected_enabled_runtime_actions(runtime_actions: dict) -> tuple[str, ...]:
    expected_actions = []

    if bool(runtime_actions.get("CAN_DEEP_WEB_SEARCH", False)):
        expected_actions.append("DEEP_WEB_SEARCH")

    if bool(runtime_actions.get("CAN_WEB_SEARCH", False)):
        expected_actions.append("WEB_SEARCH")

    if bool(runtime_actions.get("CAN_CLEAN_TOOL_RESULTS", False)):
        expected_actions.append(
            "CLEAN_TOOL_RESULTS"
        )


    if bool(runtime_actions.get("CAN_JIN_COLOR", False)):
        expected_actions.append(
            "JIN_COLOR"
        )

    if bool(runtime_actions.get("CAN_JIN_REACTION", False)):
        expected_actions.append(
            "JIN_REACTION"
        )

    if bool(runtime_actions.get("CAN_JIN_SIZE", False)):
        expected_actions.append(
            "JIN_SIZE"
        )

    if bool(runtime_actions.get("CAN_JIN_POSITION", False)):
        expected_actions.append(
            "JIN_POSITION"
        )

    if bool(runtime_actions.get("CAN_JIN_SPEED", False)):
        expected_actions.append(
            "JIN_SPEED"
        )

    if bool(runtime_actions.get("CAN_UPDATE_LT_FACTS", False)):
        expected_actions.append(
            "UPDATE_LT_FACTS"
        )

    for flag, action in (("CAN_RECALL_FACT_CONTEXT", "RECALL_FACT_CONTEXT"),
                         ("CAN_CHAT_LOG_SEARCH", "CHAT_LOG_SEARCH")):
        if runtime_actions.get(flag, False):
            expected_actions.append(action)

    if bool(runtime_actions.get("CAN_USE_ASSETS", False)):
        expected_actions.extend(
            (
                "LOAD_SKILL",
                "UNLOAD_SKILL",
                "ASSET_ACTION",
            )
        )

    if bool(runtime_actions.get("CAN_POSTING_BOARD", False)):
        expected_actions.append(
            "POSTING_BOARD"
        )

    if bool(runtime_actions.get("CAN_CALL_MCP", False)):
        expected_actions.append(
            "CALL_MCP"
        )

    if bool(runtime_actions.get("CAN_USE_ASSETS", False)):
        expected_actions.extend(
            (
                "LIST_ALL_USER_SHARED_FILES",
                "ATTACH_FILE_CONTENT",
                "ATTACH_FILE_BY_ID",
            )
        )

    if bool(runtime_actions.get("CAN_SAVE_DELAYED_MEMORY", False)):
        expected_actions.extend(
            (
                "SAVE_DELAYED_MEMORY",
                "LOAD_DELAYED_MEMORY",
            )
        )

    if bool(runtime_actions.get("CAN_SAVE_ACTIVE_MEMORY", False)):
        expected_actions.extend(
            (
                "SAVE_ACTIVE_MEMORY",
                "DELETE_ACTIVE_MEMORY",
            )
        )

    return tuple(expected_actions)


class BrainRuntimeActionTests(unittest.TestCase):

    def setUp(self):
        self._search_actions_patcher = patch(
            "rules.brain_context_builder.search_actions_available",
            return_value=True,
        )
        self._search_actions_patcher.start()
        self.addCleanup(
            self._search_actions_patcher.stop
        )

    def test_provider_transport_passes_runtime_marker_chunks_through_unchanged(self):

        expected_chunks = [
            {"type": "content", "content": "Reply. <JIN_COLOR> #ff0000 </JIN_COLOR>"},
            {"type": "content", "content": "<SAVE_ACTIVE_MEMORY>remember this</SAVE_ACTIVE_MEMORY>"},
        ]

        class FakeBrainClient:
            def __init__(self):
                self.kwargs = None

            async def stream(self, **kwargs):
                self.kwargs = kwargs
                for chunk in expected_chunks:
                    yield dict(chunk)

        async def collect(client):
            return [
                chunk
                async for chunk in ask_brain_stream(
                    client=client,
                    text="user text",
                    context=SimpleNamespace(runtime_turn_attachments=[]),
                    system_prompt="system prompt",
                    brain_payload="brain payload",
                    runtime_actions={"CAN_JIN_COLOR": True, "CAN_SAVE_ACTIVE_MEMORY": True},
                    context_window_prepared=True,
                )
            ]

        client = FakeBrainClient()
        with patch(
            "clients.brain_client.apply_runtime_action_calls",
            side_effect=AssertionError("provider transport must not execute runtime actions"),
        ):
            chunks = asyncio.run(collect(client))

        self.assertEqual(chunks, expected_chunks)
        self.assertEqual(client.kwargs["user_prompt"], "brain payload")
        self.assertEqual(client.kwargs["system_prompt"], "system prompt")

    def test_provider_transport_preserves_explicit_empty_brain_payload(self):

        class FakeBrainClient:
            def __init__(self):
                self.user_prompt = None

            async def stream(self, **kwargs):
                self.user_prompt = kwargs["user_prompt"]
                yield {"type": "content", "content": "ok"}

        async def collect(client):
            return [
                chunk
                async for chunk in ask_brain_stream(
                    client=client,
                    text="fallback text",
                    context=SimpleNamespace(runtime_turn_attachments=[]),
                    system_prompt="system prompt",
                    brain_payload="",
                    context_window_prepared=True,
                )
            ]

        client = FakeBrainClient()
        chunks = asyncio.run(collect(client))

        self.assertEqual(chunks, [{"type": "content", "content": "ok"}])
        self.assertEqual(client.user_prompt, "")




    def test_image_attachments_enter_model_payload(self):

        context = SimpleNamespace(
            runtime_turn_attachments=[{
                "kind": "image",
                "name": "screen.png",
                "data_url": "data:image/png;base64,AAAA",
            }],
        )
        prompt = build_brain_user_prompt_content("look", context=context)
        self.assertEqual(prompt, [
            {"type": "text", "text": "look"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ])

    def test_image_attachments_enter_empty_followup_payload(self):

        context = SimpleNamespace(
            runtime_turn_attachments=[{
                "kind": "image",
                "name": "screen.png",
                "data_url": "data:image/png;base64,AAAA",
            }],
        )
        prompt = build_brain_user_prompt_content("", context=context)
        self.assertEqual(prompt, [
            {"type": "text", "text": ""},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ])

    def test_brain_system_prompt_keeps_runtime_rule_sentences_separated(self):

        context = SimpleNamespace(
            runtime_memory="",
            runtime_memory_stable="",
            active_memory_records=[
                "active_memory_1: Check whether this should resolve",
            ],
        )

        prompt = build_brain_context(
            context=context,
            runtime_actions={
                "CAN_WEB_SEARCH": True,
                "CAN_SAVE_DELAYED_MEMORY": True,
                "CAN_SAVE_ACTIVE_MEMORY": True,
            },
        )

        for broken_join in (
            "final answer.Emit markers",
            "specific cases.DO NOT invent",
            "memory conditions.You need",
        ):
            assert_not_contains_text(self, prompt, broken_join)

        assert_contains_text(self, prompt, "<WEB_SEARCH> query </WEB_SEARCH>")
        assert_contains_text(self, prompt, "<SAVE_DELAYED_MEMORY>")
        assert_contains_text(self, prompt, "<SAVE_ACTIVE_MEMORY>")
        assert_contains_text(self, prompt, "<DELETE_ACTIVE_MEMORY> AM-abcdef, AM-ghijkl </DELETE_ACTIVE_MEMORY>")
        assert_contains_text(self, prompt, "Follow-up: false")





    def test_runtime_action_dedup_scopes_to_single_message(self):

        async def run_case():
            context = SimpleNamespace(
                runtime_action_events=[],
                runtime_search_calls=[],
                runtime_loaded_skills=[],
                runtime_save_session_requested=False,
                runtime_save_session_action_emitted=False,
                runtime_skill_state_barrier_active=False,
                runtime_current_turn_id="turn-action-dedup",
                logger=None,
            )
            duplicate_message_actions = (
                RuntimeActionCall(
                    name="WEB_SEARCH",
                    payload="blue tomato",
                ),
                RuntimeActionCall(
                    name="WEB_SEARCH",
                    payload="blue tomato",
                ),
                RuntimeActionCall(
                    name="CLEAN_TOOL_RESULTS",
                    payload="",
                ),
                RuntimeActionCall(
                    name="CLEAN_TOOL_RESULTS",
                    payload="",
                ),
            )

            first_count = await apply_runtime_action_calls(
                context,
                duplicate_message_actions,
                runtime_message_id="message-one",
            )

            context.runtime_search_queries = []
            context.runtime_search_calls = []

            second_count = await apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="WEB_SEARCH",
                        payload="blue tomato",
                    ),
                    RuntimeActionCall(
                        name="CLEAN_TOOL_RESULTS",
                        payload="",
                    ),
                ),
                runtime_message_id="message-two",
            )

            context.runtime_search_queries = []
            context.runtime_search_calls = []

            followup_count = await apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="WEB_SEARCH",
                        payload="blue tomato",
                    ),
                ),
                runtime_message_id="message-follow-up",
            )

            return (
                first_count,
                second_count,
                followup_count,
                [
                    event.get("name")
                    for event in context.runtime_action_events
                ],
            )

        (
            first_count,
            second_count,
            followup_count,
            action_names,
        ) = asyncio.run(
            run_case()
        )

        self.assertEqual(
            first_count,
            2,
        )
        self.assertEqual(
            second_count,
            2,
        )
        self.assertEqual(
            followup_count,
            1,
        )
        self.assertEqual(
            action_names,
            [
                "web_search",
                "clean_tool_results",
                "web_search",
                "clean_tool_results",
                "web_search",
            ],
        )

    def test_followup_without_stored_result_executes_without_duplicate_failure(self):

        async def run_case():
            context = SimpleNamespace(
                runtime_action_events=[],
                runtime_search_calls=[],
                runtime_loaded_skills=[],
                runtime_save_session_requested=False,
                runtime_save_session_action_emitted=False,
                runtime_skill_state_barrier_active=False,
                runtime_current_turn_id="turn-interleaved-dedup",
                runtime_followup_tick_active=True,
                logger=None,
            )

            first_count = await apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="CLEAN_TOOL_RESULTS",
                        payload="",
                    ),
                    RuntimeActionCall(
                        name="JIN_COLOR",
                        payload="#112233",
                    ),
                ),
                runtime_message_id="message-one",
            )

            second_count = await apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="CLEAN_TOOL_RESULTS",
                        payload="",
                    ),
                    RuntimeActionCall(
                        name="JIN_COLOR",
                        payload="#112233",
                    ),
                ),
                runtime_message_id="message-two",
            )

            return first_count, second_count, context

        first_count, second_count, context = asyncio.run(run_case())

        self.assertEqual(first_count, 1)
        self.assertEqual(second_count, 1)
        self.assertEqual(
            [event.get("name") for event in context.runtime_action_events],
            [
                "clean_tool_results",
                "jin_color",
                "clean_tool_results",
                "jin_color",
            ],
        )
        self.assertFalse(any(event.get("status") == "failed"
                             for event in context.runtime_action_events[-2:]))



    def test_session_history_compacts_many_repeated_markers(self):

        context = SimpleNamespace(
            runtime_session_action_history=[],
        )

        replace_session_action_history_since(
            context,
            0,
            [
                "delete_active_memory",
            ] * 24,
        )

        repeated_actions = ", ".join(
            ["DELETE_ACTIVE_MEMORY"] * 24
        )
        self.assertEqual(
            context.runtime_session_action_history[0]["text"],
            repeated_actions,
        )

        prompt = build_brain_context(
            context=context,
            runtime_actions={},
        )

        self.assertIn(
            f"1. {repeated_actions}",
            prompt,
        )
        self.assertNotIn("(count:", prompt)

    def test_session_history_includes_loaded_and_unloaded_skill_names(self):

        formatted = format_session_action_marker_names([
            RuntimeActionCall(
                name="LIST_SKILLS",
            ),
            RuntimeActionCall(
                name="LOAD_SKILL",
                payload="wildcards",
            ),
            RuntimeActionCall(
                name="LOAD_SKILL",
                payload="file_manager",
            ),
            RuntimeActionCall(
                name="LOAD_SKILL",
                payload="wildcards",
            ),
            RuntimeActionCall(
                name="UNLOAD_SKILL",
                payload="image_prompt_generator",
            ),
            RuntimeActionCall(
                name="UNLOAD_SKILL",
                payload="image_prompt_generator",
            ),
            RuntimeActionCall(
                name="UNLOAD_SKILL",
                payload="file_manager",
            ),
        ])

        self.assertEqual(
            formatted,
            (
                "LIST_SKILLS, "
                "LOAD_SKILL: wildcards, "
                "LOAD_SKILL: file_manager, "
                "UNLOAD_SKILL: image_prompt_generator, "
                "UNLOAD_SKILL: file_manager"
            ),
        )

    def test_session_history_groups_current_marker_parts_for_turn(self):

        context = SimpleNamespace(
            runtime_session_action_history=[],
            runtime_current_turn_id="turn-1",
        )

        replace_session_action_history_since(
            context,
            0,
            [
                RuntimeActionCall(name="WEB_SEARCH", payload="latest news"),
                RuntimeActionCall(name="SAVE_ACTIVE_MEMORY", payload="remember coffee"),
                RuntimeActionCall(name="LOAD_SKILL", payload="wildcards"),
                RuntimeActionCall(name="LOAD_SKILL", payload="file_manager"),
            ],
        )

        self.assertEqual(
            [item["parts"] for item in context.runtime_session_action_history],
            [[
                {"text": "WEB_SEARCH", "detail": "latest news"},
                {"text": "SAVE_ACTIVE_MEMORY", "detail": "remember coffee"},
                {"text": "LOAD_SKILL: wildcards"},
                {"text": "LOAD_SKILL: file_manager"},
            ]],
        )

    def test_jin_color_history_preserves_ordered_color_swatches(self):

        context = SimpleNamespace(
            runtime_session_action_history=[],
            runtime_current_turn_id="turn-1",
        )

        replace_session_action_history_since(
            context,
            0,
            [
                RuntimeActionCall(
                    name="JIN_COLOR",
                    payload="#ff0000",
                ),
                RuntimeActionCall(
                    name="JIN_COLOR",
                    payload="#00ff00",
                ),
                RuntimeActionCall(
                    name="JIN_COLOR",
                    payload="#ff0000",
                ),
            ],
        )

        self.assertEqual(
            context.runtime_session_action_history[0]["parts"],
            [
                {
                    "text": "JIN_COLOR",
                    "colors": [
                        "#ff0000",
                        "#00ff00",
                        "#ff0000",
                    ],
                    "context_detail": "#ff0000, #00ff00",
                    "count": 3,
                },
            ],
        )

        self.assertEqual(
            build_session_actions_update_items(
                context,
                current_sequence=False,
            )[0]["parts"],
            [
                {
                    "text": "JIN_COLOR",
                    "colors": [
                        "#ff0000",
                        "#00ff00",
                        "#ff0000",
                    ],
                    "context_detail": "#ff0000, #00ff00",
                    "count": 3,
                },
            ],
        )

    def test_jin_color_history_separates_marker_count_from_applied_colors(self):

        context = SimpleNamespace(
            runtime_session_action_history=[],
            runtime_current_turn_id="turn-1",
        )

        replace_session_action_history_since(
            context,
            0,
            [{
                "name": "JIN_COLOR",
                "colors": [
                    "#ff0000",
                ],
                "marker_count": 4,
            }],
        )

        self.assertEqual(
            context.runtime_session_action_history[0]["parts"],
            [{
                "text": "JIN_COLOR",
                "colors": [
                    "#ff0000",
                ],
                "context_detail": "#ff0000",
                "count": 4,
            }],
        )

    def test_payload_distinct_active_memory_history_uses_separate_parts(self):

        context = SimpleNamespace(
            runtime_session_action_history=[],
            runtime_current_turn_id="turn-1",
        )

        replace_session_action_history_since(
            context,
            0,
            [{
                "name": "SAVE_ACTIVE_MEMORY",
                "marker_count": 2,
                "payloads": [
                    'CONDITIONS: слово "кулёк"',
                    'CONDITIONS: слово "кукушка"',
                ],
            }],
        )

        self.assertEqual(
            [
                item["parts"][0]
                for item in context.runtime_session_action_history
            ],
            [
                {
                    "text": "SAVE_ACTIVE_MEMORY",
                    "detail": 'CONDITIONS: слово "кулёк"',
                },
                {
                    "text": "SAVE_ACTIVE_MEMORY",
                    "detail": 'CONDITIONS: слово "кукушка"',
                },
            ],
        )

    def test_payload_distinct_delete_active_memory_history_uses_separate_parts(self):

        context = SimpleNamespace(
            runtime_session_action_history=[],
            runtime_current_turn_id="turn-1",
        )

        replace_session_action_history_since(
            context,
            0,
            [{
                "name": "DELETE_ACTIVE_MEMORY",
                "marker_count": 2,
                "payloads": [
                    "enrrqo",
                    "yfpywn",
                ],
            }],
        )

        self.assertEqual(
            context.runtime_session_action_history[0]["parts"],
            [
                {
                    "text": "DELETE_ACTIVE_MEMORY",
                    "detail": "enrrqo",
                },
                {
                    "text": "DELETE_ACTIVE_MEMORY",
                    "detail": "yfpywn",
                },
            ],
        )

    def test_payload_distinct_save_delayed_history_uses_separate_parts(self):

        context = SimpleNamespace(
            runtime_session_action_history=[],
            runtime_current_turn_id="turn-1",
        )

        replace_session_action_history_since(
            context,
            0,
            [{
                "name": "SAVE_DELAYED_MEMORY",
                "marker_count": 2,
                "payloads": [
                    '{"report_1":{"title":"First report","body":"one"}}',
                    '{"report_2":{"title":"Second report","body":"two"}}',
                ],
            }],
        )

        self.assertEqual(
            context.runtime_session_action_history[0]["parts"],
            [
                {
                    "text": "SAVE_DELAYED_MEMORY",
                    "detail": "First report",
                },
                {
                    "text": "SAVE_DELAYED_MEMORY",
                    "detail": "Second report",
                },
            ],
        )

    def test_load_delayed_history_splits_by_raw_id(self):

        context = SimpleNamespace(
            runtime_session_action_history=[],
            runtime_current_turn_id="turn-1",
        )

        replace_session_action_history_since(
            context,
            0,
            [{
                "name": "LOAD_DELAYED_MEMORY",
                "marker_count": 2,
                "payloads": [
                    "Shared title",
                    "Shared title",
                ],
                "raw_payloads": [
                    "abc123",
                    "def456",
                ],
            }],
        )

        self.assertEqual(
            context.runtime_session_action_history[0]["parts"],
            [
                {
                    "text": "LOAD_DELAYED_MEMORY",
                    "detail": "Shared title",
                    "id": "abc123",
                },
                {
                    "text": "LOAD_DELAYED_MEMORY",
                    "detail": "Shared title",
                    "id": "def456",
                },
            ],
        )

    def test_unload_delayed_history_splits_by_raw_id(self):

        context = SimpleNamespace(
            runtime_session_action_history=[],
            runtime_current_turn_id="turn-1",
        )

        replace_session_action_history_since(
            context,
            0,
            [{
                "name": "UNLOAD_DELAYED_MEMORY",
                "marker_count": 2,
                "payloads": [
                    "First report",
                    "Second report",
                ],
                "raw_payloads": [
                    "abc123",
                    "def456",
                ],
            }],
        )

        self.assertEqual(
            context.runtime_session_action_history[0]["parts"],
            [
                {
                    "text": "UNLOAD_DELAYED_MEMORY",
                    "detail": "First report",
                    "id": "abc123",
                },
                {
                    "text": "UNLOAD_DELAYED_MEMORY",
                    "detail": "Second report",
                    "id": "def456",
                },
            ],
        )

    def test_session_history_includes_saved_content_title(self):

        title = (
            "Концептуальное позиционирование JIN Core: "
            "Среда мышления vs Интерфейс чата"
        )
        action = RuntimeActionCall(
            name="SAVE_DELAYED_MEMORY",
            payload=(
                '{"report_1":{"title":"'
                + title
                + '","body":"report"}}'
            ),
        )
        context = SimpleNamespace(
            runtime_session_action_history=[],
            runtime_current_turn_id="turn-1",
            runtime_turn_started_at=0,
            runtime_action_sequence_turn_ids=[],
        )

        replace_session_action_history_since(
            context,
            0,
            [action],
        )

        expected_text = (
            "SAVE_DELAYED_MEMORY - "
            + title
        )

        self.assertEqual(
            context.runtime_session_action_history[0]["text"],
            expected_text,
        )
        self.assertIn(
            (
                "1. "
                f"{expected_text.replace(' - ', ': ', 1)}"
            ),
            build_session_actions_history_context(
                context,
                current_sequence=True,
            ),
        )

    def test_replace_session_history_preserves_skill_marker_payloads(self):

        context = SimpleNamespace(
            runtime_session_action_history=[],
        )

        replace_session_action_history_since(
            context,
            0,
            [
                RuntimeActionCall(
                    name="LOAD_SKILL",
                    payload="wildcards",
                ),
                RuntimeActionCall(
                    name="LOAD_SKILL",
                    payload="wildcards",
                ),
                RuntimeActionCall(
                    name="LOAD_SKILL",
                    payload="file_manager",
                ),
                RuntimeActionCall(
                    name="UNLOAD_SKILL",
                    payload="image_prompt_generator",
                ),
            ],
        )

        self.assertEqual(
            context.runtime_session_action_history[0]["text"],
            (
                "LOAD_SKILL: wildcards, "
                "LOAD_SKILL: file_manager, "
                "UNLOAD_SKILL: image_prompt_generator"
            ),
        )





    def test_stream_ignores_web_search_internal_action_in_thinking(self):

        class FakeBrainClient:
            async def stream(self, **_kwargs):
                yield {
                    "type": "thinking",
                    "content": (
                        "Need current data.\n"
                        "<WEB_SEARCH:blue tomato>\n"
                    ),
                }
                yield {
                    "type": "content",
                    "content": "blue tomato",
                }

        class Context:
            pass

        async def collect(context):
            chunks = []

            async for chunk in ask_brain_stream(
                client=FakeBrainClient(),
                text="search blue tomato",
                context=context,
                runtime_actions={
                    "CAN_WEB_SEARCH": True,
                    "CAN_SAVE_SESSION": True,
                },
            ):
                chunks.append(
                    chunk
                )

            return chunks

        context = Context()

        chunks = asyncio.run(
            collect(
                context
            )
        )

        self.assertFalse(
            hasattr(
                context,
                "runtime_search_queries",
            )
        )
        self.assertFalse(
            hasattr(
                context,
                "runtime_action_events",
            )
        )
        self.assertIn(
            {
                "type": "content",
                "content": "blue tomato",
            },
            chunks,
        )









    def test_agent_runtime_action_flags_follow_assembler_constants(self):

        self.assertEqual(
            get_enabled_runtime_actions(
                BRAIN_RUNTIME_ACTIONS
            ),
            expected_enabled_runtime_actions(
                BRAIN_RUNTIME_ACTIONS
            ),
        )

        self.assertEqual(
            get_enabled_runtime_actions(
                BRAIN_RUNTIME_ACTIONS
            ),
            expected_enabled_runtime_actions(
                BRAIN_RUNTIME_ACTIONS
            ),
        )

    def test_prompt_and_runtime_context_expose_only_private_action_markers(self):

        runtime_actions = {
            "CAN_WEB_SEARCH": True,
            "CAN_SAVE_SESSION": True,
            "CAN_SAVE_DELAYED_MEMORY": True,
            "CAN_SAVE_ACTIVE_MEMORY": True,
        }

        prompt = build_brain_context(
            runtime_actions=runtime_actions
        )
        runtime_context = build_brain_context(
            runtime_actions=runtime_actions
        )

        combined_context = (
            prompt
            + "\n"
            + runtime_context
        )

        for forbidden_text in (
            "<RUNTIME_ACTION:",
            "enabled=\"true\"",
            "enabled=\"false\"",
            "<RUNTIME_ACTION:WEB_SEARCH>",
            "</RUNTIME_ACTION:WEB_SEARCH>",
        ):
            assert_not_contains_text(
                self,
                combined_context,
                forbidden_text,
            )

        for private_marker in (
            get_runtime_action_private_marker("SAVE_DELAYED_MEMORY"),
            get_runtime_action_private_marker("SAVE_ACTIVE_MEMORY"),
            "Use this marker for web search by google!",
        ):
            assert_contains_text(
                self,
                prompt,
                private_marker,
            )

        assert_contains_text(
            self,
            runtime_context,
            "<TRUSTED_RUNTIME_VARIABLES>",
        )
        assert_not_contains_text(self, prompt, "<SAVE_SESSION>")

    def test_runtime_xml_exposes_current_jin_color_default(self):

        runtime_xml = build_runtime_xml(
            context=SimpleNamespace(
                runtime_action_events=[],
            ),
        )

        self.assertIn(
            f"<JIN_COLOR>{DEFAULT_JIN_COLOR}</JIN_COLOR>",
            runtime_xml,
        )

    def test_runtime_xml_exposes_last_valid_jin_color(self):

        runtime_xml = build_runtime_xml(
            context=SimpleNamespace(
                runtime_action_events=[
                    {
                        "name": "jin_color",
                        "color": "#00f2ff",
                    },
                    {
                        "action": "jin_color",
                        "payload": "bad-color",
                    },
                    {
                        "action": "jin_color",
                        "payload": "f0a",
                    },
                ],
            ),
        )

        self.assertIn(
            "<JIN_COLOR>#ff00aa</JIN_COLOR>",
            runtime_xml,
        )

    def test_prompt_routes_uncertain_operational_tasks_to_skills(self):

        prompt = build_brain_context(
            runtime_actions={
                "CAN_USE_ASSETS": True,
            }
        )

        assert_contains_text(
            self,
            prompt,
            runtime_rules.SKILL_ROUTING_RULES,
        )
        assert_contains_text(
            self,
            prompt,
            "<SKILLS_LIST>",
        )
        assert_contains_text(
            self,
            prompt,
            get_runtime_action_private_marker("LOAD_SKILL"),
        )
        assert_contains_text(
            self,
            prompt,
            get_runtime_action_private_marker("UNLOAD_SKILL"),
        )
        assert_not_contains_text(
            self,
            prompt,
            "<LIST_SKILLS>",
        )
        assert_not_contains_text(
            self,
            prompt,
            "list_wildcards",
        )
        assert_not_contains_text(
            self,
            prompt,
            "create_wildcard_file",
        )

    def test_prompt_always_shows_load_unload_rules_with_skill_inventory(self):

        context = SimpleNamespace(
            runtime_memory="session_status: active",
            runtime_memory_stable="session_status: active",
            runtime_l2_memory="",
            active_memory_records=[],
            runtime_loaded_skills=[],
        )

        prompt = build_brain_context(
            context=context,
            runtime_actions={
                "CAN_USE_ASSETS": True,
            },
        )

        assert_contains_text(
            self,
            prompt,
            "<SKILLS_LIST>",
        )
        assert_contains_text(
            self,
            prompt,
            "<LOAD_SKILL",
        )
        assert_contains_text(
            self,
            prompt,
            get_runtime_action_private_marker("LOAD_SKILL"),
        )
        assert_contains_text(
            self,
            prompt,
            get_runtime_action_private_marker("UNLOAD_SKILL"),
        )
        assert_not_contains_text(
            self,
            prompt,
            "<LIST_SKILLS>",
        )

    def test_prompt_shows_always_visible_skill_inventory(self):

        context = SimpleNamespace(
            runtime_memory="session_status: active",
            runtime_memory_stable="session_status: active",
            runtime_l2_memory="",
            active_memory_records=[],
            runtime_loaded_skills=[
                {
                    "name": "wildcards",
                },
            ],
        )

        prompt = build_brain_context(
            context=context,
            runtime_actions={
                "CAN_USE_ASSETS": True,
            },
        )

        assert_contains_text(
            self,
            prompt,
            "<SKILLS_LIST>",
        )
        assert_contains_text(
            self,
            prompt,
            "wildcards (loaded)",
        )
        assert_contains_text(
            self,
            prompt,
            '<TOOL_RESULT name="LOAD_SKILL" skill="wildcards">',
        )
        assert_not_contains_text(
            self,
            prompt,
            '<TOOL_RESULT name="LIST_SKILLS"',
        )

    def test_prompt_places_tool_results_at_context_top(self):

        context = SimpleNamespace(
            runtime_memory="session_status: active",
            runtime_memory_stable="session_status: active",
            runtime_l2_memory="",
            active_memory_records=[],
            runtime_asset_results=[
                {
                    "ok": True,
                    "action": "read_asset",
                    "path": "assets/test.txt",
                    "content": "asset result",
                },
            ],
            runtime_session_action_history=[
                "Read asset",
            ],
            runtime_loaded_skills=[
                {
                    "name": "wildcards",
                    "path": "assets/skills/wildcards.txt",
                    "line_count": 2,
                    "content": "first line\nsecond line",
                },
            ],
        )

        prompt = build_brain_context(
            context=context,
            runtime_actions={
                "CAN_USE_ASSETS": True,
            },
        )

        self.assertTrue(prompt.startswith("<TRUSTED_RUNTIME_VARIABLES>"))
        self.assertLess(
            prompt.index('<TOOL_RESULT name="ASSETS"'),
            prompt.index("<SESSION_ACTIONS_HISTORY>"),
        )
        self.assertLess(
            prompt.index("</SESSION_ACTIONS_HISTORY>"),
            prompt.index("<SKILLS_LIST>"),
        )
        self.assertLess(
            prompt.index("<SKILLS_LIST>"),
            prompt.index("<FRAME_MEMORY_"),
        )
        self.assertIn("asset result", prompt)
        self.assertIn("first line\n", prompt)
        self.assertIn("second line", prompt)
        self.assertIn("wildcards (loaded)", prompt)
        self.assertNotIn('<TOOL_RESULT name="LIST_SKILLS"', prompt)

    def test_prompt_keeps_loaded_delayed_memory_in_normal_turns(self):

        context = SimpleNamespace(
            runtime_memory="session_status: active",
            runtime_memory_stable="session_status: active",
            runtime_l2_memory="",
            active_memory_records=[],
            runtime_loaded_delayed_memory={
                "id": "a1b2c3",
                "title": "Pinned task plan",
                "summary": "Use this plan for the next task.",
            },
        )

        prompt = build_brain_context(
            context=context,
            runtime_actions={
                "CAN_SAVE_DELAYED_MEMORY": True,
            },
            user_input="start the task",
        )

        self.assertIn(
            "<LOADED_DELAYED_MEMORY>",
            prompt,
        )
        self.assertIn(
            '"title": "Pinned task plan"',
            prompt,
        )
        self.assertEqual(
            prompt.count(
                "<LOADED_DELAYED_MEMORY>"
            ),
            1,
        )
        self.assertLess(
            prompt.index(
                "<LOADED_DELAYED_MEMORY>"
            ),
            prompt.index(
                "I identify as JIN"
            ),
        )

    def test_prompt_formats_loaded_delayed_memory_title_with_age_suffix(self):
        now = datetime(
            2026,
            8,
            2,
            12,
            0,
            tzinfo=timezone.utc,
        ).timestamp()
        context = SimpleNamespace(
            runtime_memory="session_status: active",
            runtime_memory_stable="session_status: active",
            runtime_l2_memory="",
            active_memory_records=[],
            runtime_loaded_delayed_memory={
                "id": "a1b2c3",
                "title": "Pinned task plan",
                "summary": "Use this plan for the next task.",
                "created_time": "2026-08-02T11:58:00Z",
            },
        )

        with patch(
            "utils.context.messages.time.time",
            return_value=now,
        ):
            prompt = build_brain_context(
                context=context,
                runtime_actions={
                    "CAN_SAVE_DELAYED_MEMORY": True,
                },
                user_input="start the task",
            )

        self.assertIn(
            '"title": "Pinned task plan ( 2m ago )"',
            prompt,
        )
        loaded_block = prompt[
            prompt.index("<LOADED_DELAYED_MEMORY>"):
            prompt.index("</LOADED_DELAYED_MEMORY>")
        ]
        self.assertNotIn(
            '"created_time"',
            loaded_block,
        )

    def test_prompt_lists_available_delayed_memory_below_tool_results(self):

        empty_context = SimpleNamespace(
            runtime_memory="session_status: active",
            runtime_memory_stable="session_status: active",
            runtime_l2_memory="",
            active_memory_records=[],
            delayed_memory_reports={},
        )

        prompt_without_reports = build_brain_context(
            context=empty_context,
            runtime_actions={
                "CAN_SAVE_DELAYED_MEMORY": True,
            },
        )

        self.assertNotIn(
            "DELAYED MEMORY ACTIONS:",
            prompt_without_reports,
        )
        self.assertNotIn(
            "<DELAYED_MEMORY>",
            prompt_without_reports,
        )

        context = SimpleNamespace(
            runtime_memory="session_status: active",
            runtime_memory_stable="session_status: active",
            runtime_l2_memory="",
            active_memory_records=[],
            delayed_memory_reports={
                "3gs007": {
                    "title": "JIN Multi-Layered Memory Architecture",
                },
                "1put0q": {
                    "title": (
                        "Синтез: Интеллект как контролируемый хаос "
                        "(Эволюция через ошибку)"
                    ),
                },
                "bad": {
                    "title": "Invalid id",
                },
            },
        )

        prompt = build_brain_context(
            context=context,
            runtime_actions={
                "CAN_SAVE_DELAYED_MEMORY": True,
            },
        )

        expected_inventory = (
            "<DELAYED_MEMORY>\n"
            "1put0q_Синтез_Интеллект_как_контролируемый_хаос_"
            "Эволюция_через_ошибку\n"
            "3gs007_JIN_Multi_Layered_Memory_Architecture\n"
            "</DELAYED_MEMORY>"
        )

        self.assertNotIn(
            "DELAYED MEMORY ACTIONS:",
            prompt,
        )
        self.assertIn(
            "<LOAD_DELAYED_MEMORY> id1, id2 </LOAD_DELAYED_MEMORY>",
            prompt,
        )
        self.assertNotIn(
            "UNLOAD_DELAYED_MEMORY",
            prompt,
        )
        self.assertNotIn(
            "<LIST_DELAYED_MEMORY>",
            prompt,
        )
        self.assertEqual(
            prompt.count(
                "\n<DELAYED_MEMORY>\n"
            ),
            1,
        )
        self.assertIn(
            "</TOOLS_RESULTS>\n\n"
            + expected_inventory,
            prompt,
        )
        self.assertLess(
            prompt.index(
                expected_inventory
            ),
            prompt.index(
                "<SKILLS_LIST>"
            ),
        )
        self.assertFalse(
            prompt.rstrip().endswith(
                expected_inventory
            ),
        )
        self.assertNotIn(
            "bad_Invalid_id",
            prompt,
        )

    def test_delayed_memory_inventory_is_sorted_by_last_loaded_date_newest_first(self):

        context = SimpleNamespace(
            delayed_memory_reports={
                "aaa111": {
                    "title": "Alphabetically first but old",
                    "last_loaded_date": "2026-08-10T10:00:00",
                },
                "zzz999": {
                    "title": "Alphabetically last but newest",
                    "last_loaded_date": "2026-08-20T14:00:00+03:00",
                },
                "mmm555": {
                    "title": "Never loaded",
                    "last_loaded_date": "",
                },
            },
        )

        prompt = build_brain_context(
            context=context,
            runtime_actions={
                "CAN_SAVE_DELAYED_MEMORY": True,
            },
        )

        newest = "zzz999_Alphabetically_last_but_newest"
        old = "aaa111_Alphabetically_first_but_old"
        never_loaded = "mmm555_Never_loaded"

        self.assertLess(
            prompt.index(newest),
            prompt.index(old),
        )
        self.assertLess(
            prompt.index(old),
            prompt.index(never_loaded),
        )

    def test_prompt_lists_delayed_memory_inventory_with_age_suffix(self):
        now = datetime(
            2026,
            8,
            2,
            12,
            0,
            tzinfo=timezone.utc,
        ).timestamp()
        context = SimpleNamespace(
            runtime_memory="session_status: active",
            runtime_memory_stable="session_status: active",
            runtime_l2_memory="",
            active_memory_records=[],
            delayed_memory_reports={
                "a1b2c3": {
                    "title": "Fresh report",
                    "created_time": "2026-08-02T11:58:00Z",
                },
            },
        )

        with patch(
            "utils.context.messages.time.time",
            return_value=now,
        ):
            prompt = build_brain_context(
                context=context,
                runtime_actions={
                    "CAN_SAVE_DELAYED_MEMORY": True,
                },
            )

        self.assertIn(
            "a1b2c3_Fresh_report ( 2m ago )",
            prompt,
        )

    def test_prompt_formats_missing_skill_as_skill_error_tool_result(self):

        context = SimpleNamespace(
            runtime_memory="session_status: active",
            runtime_memory_stable="session_status: active",
            runtime_l2_memory="",
            active_memory_records=[],
            runtime_asset_results=[
                {
                    "ok": False,
                    "action": "load_skill",
                    "requested": "file_writer",
                    "error": "skill_not_found",
                },
            ],
            runtime_loaded_skills=[],
        )

        prompt = build_brain_context(
            context=context,
            runtime_actions={
                "CAN_USE_ASSETS": True,
            },
        )

        self.assertIn(
            '<TOOL_RESULT name="LOAD_SKILL"',
            prompt,
        )
        self.assertIn(
            "You attempted to load a skill that does not exist: file_writer",
            prompt,
        )
        self.assertNotIn(
            '"action": "load_skill"',
            prompt,
        )
        self.assertIn(
            "Error code: skill_not_found",
            prompt,
        )

    def test_prompt_adds_delete_active_memory_rules_from_active_records_only(self):

        context = SimpleNamespace(
            runtime_memory="session_status: active",
            runtime_memory_stable="session_status: active",
            runtime_l2_memory="",
            active_memory_records=[
                (
                    "active_memory_1: remember cuckoo "
                    "[ id: AM-5fdg4g ] [ status: pending ]"
                ),
            ],
        )

        prompt = build_brain_context(
            context=context,
            runtime_actions={
                "CAN_SAVE_ACTIVE_MEMORY": True,
            },
        )
        runtime_context = build_brain_context(
            context=context,
            runtime_actions={
                "CAN_SAVE_ACTIVE_MEMORY": True,
            },
        )

        assert_contains_text(
            self,
            prompt,
            '{"conditions":"Descriptive conditions text", "additional_conditions":"additional value",}',
        )
        assert_contains_text(
            self,
            prompt,
            "<DELETE_ACTIVE_MEMORY> AM-abcdef, AM-ghijkl </DELETE_ACTIVE_MEMORY>",
        )
        assert_contains_text(
            self,
            runtime_context,
            "<ACTIVE_MEMORY priority=\"active_runtime_contracts\">",
        )
        assert_contains_text(
            self,
            runtime_context,
            "AM-5fdg4g",
        )
        self.assertTrue(
            prompt.startswith(
                "<CONCERNS>"
            )
        )
        self.assertLess(
            prompt.index("</CONCERNS>"),
            prompt.index("<TRUSTED_RUNTIME_VARIABLES>"),
        )
        self.assertLess(
            prompt.index("</TRUSTED_RUNTIME_VARIABLES>"),
            prompt.index("</TOOLS_RESULTS>"),
        )
        self.assertLess(
            prompt.index("</TOOLS_RESULTS>"),
            prompt.index(
                "<ACTIVE_MEMORY priority=\"active_runtime_contracts\">"
            ),
        )
        self.assertLess(
            prompt.index("<ACTIVE_MEMORY"),
            prompt.index("<FRAME_MEMORY_"),
        )
        self.assertLess(
            runtime_context.index("<ACTIVE_MEMORY"),
            runtime_context.index("<FRAME_MEMORY_"),
        )

        frame_memory_suffix = runtime_context.split(
            "<FRAME_MEMORY_",
            1,
        )[1]
        frame_memory_tag = (
            "FRAME_MEMORY_"
            + frame_memory_suffix.split(
                None,
                1,
            )[0].split(
                ">",
                1,
            )[0]
        )
        runtime_memory_block = frame_memory_suffix.split(
            ">",
            1,
        )[1].split(
            f"</{frame_memory_tag}>",
            1,
        )[0]
        assert_not_contains_text(
            self,
            runtime_memory_block,
            "active_memory_1:",
        )
        assert_not_contains_text(
            self,
            context.runtime_memory,
            "active_memory",
        )

    def test_active_memory_recalculates_on_each_followup_tick(self):

        context = SimpleNamespace(
            runtime_memory="session_status: active",
            runtime_memory_stable="session_status: active",
            runtime_l2_memory="",
            active_memory_records=[
                (
                    "active_memory_1: Track experiment "
                    "[ creation_time: 2026-06-20T10:00:00 ] "
                    "[ created_jin_message_number: 3 ] "
                    "[ elapsed_time: 00:00:00 ] "
                    "[ elapsed_jin_message_number: 0 ] "
                    "[ status: pending ]"
                ),
            ],
            timestamp="2026-06-20T10:00:00",
            turn_number=4,
            runtime_turn_counter=4,
            runtime_user_idle_seconds=300,
            runtime_active_memory_refresh_tick=0,
        )

        build_brain_context(
            context=context,
            runtime_actions={},
            commit_active_memory_refresh=True,
        )

        self.assertIn(
            "[ elapsed_time: 00:05:00 ]",
            context.active_memory_records[0],
        )
        self.assertEqual(
            context.runtime_active_memory_records_refresh_turn,
            (4, 0),
        )

        context.timestamp = "2026-06-20T10:01:00"
        context.runtime_active_memory_refresh_tick = 1

        build_brain_context(
            context=context,
            runtime_actions={},
            commit_active_memory_refresh=True,
        )

        self.assertIn(
            "[ elapsed_time: 00:05:00 ]",
            context.active_memory_records[0],
        )
        self.assertEqual(
            context.runtime_active_memory_records_refresh_turn,
            (4, 1),
        )

        context.timestamp = "2026-06-20T10:06:00"
        context.runtime_active_memory_refresh_tick = 2

        build_brain_context(
            context=context,
            runtime_actions={},
            commit_active_memory_refresh=True,
        )

        self.assertIn(
            "[ elapsed_time: 00:06:00 ]",
            context.active_memory_records[0],
        )
        self.assertEqual(
            context.runtime_active_memory_records_refresh_turn,
            (4, 2),
        )


    def test_runtime_context_omits_paused_active_memory_records(self):

        context = SimpleNamespace(
            runtime_memory="session_status: active",
            runtime_memory_stable="session_status: active",
            runtime_l2_memory="",
            active_memory_records=[
                (
                    "active_memory_1: remember cuckoo "
                    "[ id: AM-5fdg4g ] [ status: pending ]"
                ),
                (
                    "active_memory_2: paused reminder "
                    "[ active_memory_id: abc123 ] [ status: paused ]"
                ),
            ],
        )

        runtime_context = build_brain_context(
            context=context,
            runtime_actions={
                "CAN_SAVE_ACTIVE_MEMORY": True,
            },
            commit_active_memory_refresh=True,
        )

        assert_contains_text(
            self,
            runtime_context,
            "5fdg4g",
        )
        assert_not_contains_text(
            self,
            runtime_context,
            "abc123",
        )
        assert_not_contains_text(
            self,
            runtime_context,
            "paused reminder",
        )
        self.assertEqual(
            len(context.active_memory_records),
            2,
        )
        assert_contains_text(
            self,
            "\n".join(context.active_memory_records),
            "abc123",
        )
        assert_contains_text(
            self,
            "\n".join(context.active_memory_records),
            "[ status: paused ]",
        )

    def test_prompt_omits_delete_active_memory_rules_without_active_records(self):

        context = SimpleNamespace(
            runtime_memory="session_status: active",
            runtime_memory_stable="session_status: active",
            runtime_l2_memory="",
            active_memory_records=[],
        )

        prompt = build_brain_context(
            context=context,
            runtime_actions={
                "CAN_SAVE_ACTIVE_MEMORY": True,
            },
        )

        assert_contains_text(
            self,
            prompt,
            '{"conditions":"Descriptive conditions text", "additional_conditions":"additional value",}',
        )
        assert_not_contains_text(
            self,
            prompt,
            "<DELETE_ACTIVE_MEMORY> AM-abcdef, AM-ghijkl </DELETE_ACTIVE_MEMORY>",
        )

    def test_prompt_uses_passed_agent_runtime_actions(self):

        prompt = build_brain_context(
            runtime_actions={
                "CAN_WEB_SEARCH": True,
            }
        )

        self.assertNotIn("CAN_WEB_SEARCH", prompt)
        assert_contains_text(self, prompt, "<WEB_SEARCH> query </WEB_SEARCH>")
        assert_contains_text(self, prompt, "Use this marker for web search by google!")
        self.assertNotIn("<![CDATA[", prompt)
        self.assertNotIn("&lt;RUNTIME_ACTION:WEB_SEARCH&gt;", prompt)
        self.assertIn("<USER_DATETIME>", prompt)
        current_model_uid = (
            config.BRAIN_MODEL_UID
        )
        self.assertIn(
            f"<MODEL_UID>{current_model_uid}</MODEL_UID>",
            prompt,
        )
        self.assertNotIn("<SERVICE_MODEL_UID>", prompt)
        self.assertNotIn("<BRAIN_MODEL_UID>", prompt)
        self.assertNotIn("<RUNTIME_MODE>", prompt)
        self.assertNotIn("<MODE>", prompt)
        self.assertNotIn("<CONTEXT>", prompt)

    def test_prompt_can_flip_agent_actions_dynamically(self):

        prompt = build_brain_context(
            runtime_actions={
                "CAN_WEB_SEARCH": False,
            }
        )

        self.assertNotIn(
            "CAN_WEB_SEARCH",
            prompt,
        )




        self.assertNotIn(
            "<![CDATA[",
            prompt,
        )

        self.assertNotIn(
            '<RUNTIME_ACTION:WEB_SEARCH>{"query":"..."}</RUNTIME_ACTION:WEB_SEARCH>' ,
            prompt,
        )

    def test_search_prompt_requires_plain_query_and_exact_subject(self):

        prompt = build_brain_context(
            runtime_actions={
                "CAN_WEB_SEARCH": True,
            }
        )



        self.assertIn(
            "<WEB_SEARCH> query </WEB_SEARCH>",
            prompt,
        )
        self.assertIn("Use this marker for web search by google!", prompt)


    def test_prompt_does_not_render_legacy_memory_recall_block(self):

        context = SimpleNamespace(
            runtime_turn_user_message="помнишь кодовое слово?",
        )

        prompt = build_brain_context(
            context=context,
            runtime_actions={
                "CAN_WEB_SEARCH": False,
            }
        )

        self.assertIn(
            "<TRUSTED_RUNTIME_VARIABLES>",
            prompt,
        )

        self.assertNotIn(
            "Memory recall: scan strong memory fields before denying recall",
            prompt,
        )

        self.assertNotIn(
            "temporarily overrides active topic continuation",
            prompt,
        )




if __name__ == "__main__":
    unittest.main()


