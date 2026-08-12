import asyncio
import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from clients.brain_client import apply_runtime_action_calls
from clients.brain_client import should_execute_save_session
from contracts.rules_assembler import (
    RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
    RUNTIME_ACTION_IDLE,
    RUNTIME_ACTION_JIN_COLOR,
    get_runtime_action_private_marker,
    normalize_runtime_action_names,
)
from rules.brain_context_builder import build_loaded_delayed_memory_context
from tests.helpers.runtime_actions import (
    FakeContext,
    FakeEmitter,
    RuntimeActionTestCase,
    legacy_internal_action_marker,
)
from utils.actions import (
    RuntimeActionCall,
    RuntimeActionRepetitionGuard,
    RuntimeActionStreamFilter,
    extract_active_memory_resolve_slot_id,
    extract_search_query,
    extract_runtime_actions,
    get_save_active_memory_marker_fields,
    get_save_active_memory_placeholder_payload,
    normalize_jin_color_payload,
    parse_delayed_memory_content_payload,
)
from utils.assets_utils import run_asset_action
from utils.brain_client_utils import (
    record_delayed_memory_runtime_result,
    flush_pending_active_memory_resolve_failure_history,
)
from utils.context.context_exports import build_tool_results_context
from utils.file_manager_asset_utils import read_asset_text_preview
from utils.runtime_todo import create_runtime_todo
from utils.skills_asset_utils import (
    list_skills,
    normalize_skill_name,
)
from utils.tool_results import (
    TOOL_RESULT_KIND_ACTIVE_MEMORY,
    TOOL_RESULT_KIND_ASSET,
    TOOL_RESULT_KIND_DELAYED_MEMORY,
    TOOL_RESULT_KIND_SEARCH,
    begin_runtime_tool_results_turn,
    record_runtime_tool_result,
)



class RuntimeStreamFilterTests(RuntimeActionTestCase):

    def test_extract_runtime_actions_handles_none_text(self):

        result = extract_runtime_actions(
            None
        )

        self.assertEqual(
            result.text,
            "",
        )
        self.assertEqual(
            result.actions,
            (),
        )


    def test_all_bare_runtime_action_names_stay_ordinary_text(self):

        action_names = normalize_runtime_action_names(None)
        text = "\n".join(
            (
                "Runtime actions mentioned as text:",
                *(f"`{name}`" for name in action_names),
                *action_names,
            )
        )

        result = extract_runtime_actions(
            text,
            enabled_actions=action_names,
        )

        self.assertEqual(result.text, text)
        self.assertEqual(result.actions, ())
        self.assertEqual(result.observed_actions, ())
        self.assertEqual(result.removed_markers, ())


    def test_extracts_bracketed_web_search_marker(self):

        result = extract_runtime_actions(
            "<WEB_SEARCH:\u0441\u0438\u043d\u0438\u0439 \u043f\u043e\u043c\u0438\u0434\u043e\u0440>",
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
        )

        self.assertEqual(
            result.text,
            "",
        )
        self.assertEqual(
            result.search_queries,
            (
                "\u0441\u0438\u043d\u0438\u0439 \u043f\u043e\u043c\u0438\u0434\u043e\u0440",
            ),
        )


    def test_extracts_current_bracketed_web_search_marker(self):

        result = extract_runtime_actions(
            "<WEB_SEARCH:blue tomato>",
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
        )

        self.assertEqual(
            result.text,
            "",
        )
        self.assertEqual(
            result.search_queries,
            (
                "blue tomato",
            ),
        )


    def test_extracts_deep_web_search_marker_payload(self):

        result = extract_runtime_actions(
            (
                "<DEEP_WEB_SEARCH>\n"
                "blue tomato varieties\n"
                "</DEEP_WEB_SEARCH>"
            ),
            enabled_actions=[
                "CAN_DEEP_WEB_SEARCH",
            ],
        )

        self.assertEqual(
            result.text,
            "",
        )
        self.assertEqual(
            len(result.actions),
            1,
        )
        self.assertEqual(
            result.actions[0].name,
            "DEEP_WEB_SEARCH",
        )
        self.assertIn(
            "blue tomato varieties",
            result.actions[0].payload,
        )


    def test_extracts_legacy_inline_deep_web_search_marker_payload(self):

        result = extract_runtime_actions(
            "<DEEP_WEB_SEARCH: blue tomato varieties>",
            enabled_actions=[
                "CAN_DEEP_WEB_SEARCH",
            ],
        )

        self.assertEqual(
            result.text,
            "",
        )
        self.assertEqual(
            len(result.actions),
            1,
        )
        self.assertIn(
            "blue tomato varieties",
            result.actions[0].payload,
        )


    def test_legacy_inline_deep_web_search_placeholder_is_ignored(self):

        result = extract_runtime_actions(
            "<DEEP_WEB_SEARCH: research objective >",
            enabled_actions=[
                "CAN_DEEP_WEB_SEARCH",
            ],
        )

        self.assertEqual(
            result.text,
            "",
        )
        self.assertEqual(
            result.actions,
            (),
        )


    def test_deep_web_search_block_uses_body_when_attribute_is_placeholder(self):

        result = extract_runtime_actions(
            (
                "<DEEP_WEB_SEARCH: research objective >\n"
                "Identify the movie with the talking head robot.\n"
                "</DEEP_WEB_SEARCH>"
            ),
            enabled_actions=[
                "CAN_DEEP_WEB_SEARCH",
            ],
        )

        self.assertEqual(
            result.text,
            "",
        )
        self.assertEqual(
            len(result.actions),
            1,
        )
        self.assertIn(
            "talking head robot",
            result.actions[0].payload,
        )
        self.assertNotIn(
            "research objective",
            result.actions[0].payload,
        )


    def test_extracts_bracketed_web_search_marker_inside_text(self):

        result = extract_runtime_actions(
            (
                "Before\n"
                "<WEB_SEARCH:\u0441\u0438\u043d\u0438\u0439 \u043f\u043e\u043c\u0438\u0434\u043e\u0440>\n"
                "After"
            ),
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
        )

        self.assertNotIn(
            "WEB_SEARCH",
            result.text,
        )
        self.assertIn(
            "Before",
            result.text,
        )
        self.assertIn(
            "After",
            result.text,
        )
        self.assertEqual(
            result.search_queries,
            (
                "\u0441\u0438\u043d\u0438\u0439 \u043f\u043e\u043c\u0438\u0434\u043e\u0440",
            ),
        )


    def test_rejects_web_search_marker_without_closing_angle_bracket(self):

        text = (
            "<WEB_SEARCH: house drawing ideas\n"
            "\n"
            "🏠\n"
            "\n"
            "Маленький уютный домик"
        )
        result = extract_runtime_actions(
            text,
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
        )

        self.assertEqual(
            result.text,
            text,
        )
        self.assertEqual(
            result.actions,
            (),
        )
        self.assertEqual(
            result.removed_markers,
            (),
        )

    def test_tool_call_wrapper_stays_text_without_canonical_action_tag(self):

        text = (
            "<|tool_call>call:WEB_SEARCH: сериалы, "
            "похожие на From (сериал) >"
        )
        result = extract_runtime_actions(
            text,
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
        )

        self.assertEqual(result.text, text)
        self.assertEqual(result.actions, ())
        self.assertEqual(result.removed_markers, ())

    def test_tool_call_prefix_stays_text_without_canonical_action_tag(self):

        text = (
            "<tool_call>call:WEB_SEARCH: Gemma 4 differences "
            "between e2b and e4b versions"
        )
        result = extract_runtime_actions(
            text,
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
        )

        self.assertEqual(result.text, text)
        self.assertEqual(result.actions, ())
        self.assertEqual(result.removed_markers, ())

    def test_bare_call_style_web_search_line_stays_text(self):

        text = (
            "call:WEB_SEARCH: сериалы, похожие на From (сериал)"
        )
        result = extract_runtime_actions(
            text,
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
        )

        self.assertEqual(result.text, text)
        self.assertEqual(result.actions, ())
        self.assertEqual(result.removed_markers, ())

    def test_bare_web_search_name_and_payload_stay_text(self):

        text = "call:WEB_SEARCH: blue tomato"
        result = extract_runtime_actions(
            text,
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
        )

        self.assertEqual(result.text, text)
        self.assertEqual(result.actions, ())
        self.assertEqual(result.removed_markers, ())

    def test_does_not_extract_inline_bare_call_style_marker(self):

        result = extract_runtime_actions(
            "before call:WEB_SEARCH: blue tomato after",
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
        )

        self.assertEqual(
            result.text,
            "before call:WEB_SEARCH: blue tomato after",
        )
        self.assertEqual(
            result.actions,
            (),
        )


    def test_ignores_placeholder_bracketed_web_search_marker(self):

        current_placeholder = get_runtime_action_private_marker("WEB_SEARCH")
        legacy_placeholder = legacy_internal_action_marker(
            current_placeholder
        )
        current_angle_placeholder = current_placeholder.replace(
            ": ",
            ":",
        ).replace(
            "plain text query",
            "<plain text query>",
        ).replace(
            " >",
            ">",
        )
        legacy_angle_placeholder = legacy_placeholder.replace(
            ": ",
            ":",
        ).replace(
            "plain text query",
            "<plain text query>",
        ).replace(
            " >",
            ">",
        )

        for marker in (
            current_placeholder,
            current_placeholder.replace(
                ": ",
                ":",
            ),
            current_angle_placeholder,
            current_placeholder.replace(
                "plain text query",
                "...",
            ),
        ):

            result = extract_runtime_actions(
                marker,
                enabled_actions=[
                    "CAN_WEB_SEARCH",
                ],
            )

            self.assertEqual(
                result.text,
                "",
            )
            self.assertEqual(
                result.count("WEB_SEARCH"),
                0,
            )

        for marker in (
            legacy_placeholder,
            legacy_placeholder.replace(
                ": ",
                ":",
            ),
            legacy_angle_placeholder,
            legacy_placeholder.replace(
                "plain text query",
                "...",
            ),
        ):

            result = extract_runtime_actions(
                marker,
                enabled_actions=[
                    "CAN_WEB_SEARCH",
                ],
            )

            self.assertEqual(
                result.text,
                marker,
            )
            self.assertEqual(
                result.count("WEB_SEARCH"),
                0,
            )


    def test_extracts_bracketed_save_session_marker(self):

        result = extract_runtime_actions(
            "<SAVE_SESSION>",
            enabled_actions=[
                "CAN_SAVE_SESSION",
            ],
        )

        self.assertEqual(
            result.text,
            "",
        )
        self.assertEqual(
            result.count("SAVE_SESSION"),
            1,
        )
        self.assertEqual(
            result.removed_markers,
            (
                "<SAVE_SESSION>",
            ),
        )


    def test_extracts_clean_tool_results_marker(self):

        result = extract_runtime_actions(
            get_runtime_action_private_marker("CLEAN_TOOL_RESULTS"),
            enabled_actions=[
                RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
            ],
        )

        self.assertEqual(
            result.text,
            "",
        )
        self.assertEqual(
            result.actions,
            (
                RuntimeActionCall(
                    name=RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
                    payload="",
                ),
            ),
        )


    def test_repeated_clean_tool_results_markers_remain_countable(self):

        result = extract_runtime_actions(
            "<CLEAN_TOOL_RESULTS>" * 3,
            enabled_actions=[
                RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
            ],
            repetition_guard=RuntimeActionRepetitionGuard(),
        )

        self.assertEqual(
            len(result.actions),
            3,
        )
        self.assertFalse(
            result.marker_repetition_exceeded,
        )


    def test_extracts_self_closing_runtime_markers_without_blocks(self):

        cases = (
            ("<SAVE_SESSION/>", "SAVE_SESSION", ""),
            (
                "<WEB_SEARCH: blue tomato/>",
                "WEB_SEARCH",
                json.dumps({
                    "query": "blue tomato",
                }),
            ),
            (
                "<SAVE_ACTIVE_MEMORY: remember tea/>",
                "SAVE_ACTIVE_MEMORY",
                "remember tea",
            ),
            (
                "<LOAD_SKILL: file_manager/>",
                "LOAD_SKILL",
                "file_manager",
            ),
            (
                "<RESOLVE_TODO: todo-1/>",
                "RESOLVE_TODO",
                "todo-1",
            ),
            (
                "<LOAD_DELAYED_MEMORY: a1b2c3/>",
                "LOAD_DELAYED_MEMORY",
                "a1b2c3",
            ),
        )

        for marker, action_name, payload in cases:
            with self.subTest(marker=marker):
                result = extract_runtime_actions(
                    marker
                )

                self.assertEqual(
                    result.text,
                    "",
                )
                self.assertEqual(
                    result.actions,
                    (
                        RuntimeActionCall(
                            name=action_name,
                            payload=payload,
                        ),
                    ),
                )
                self.assertEqual(
                    result.removed_markers,
                    (
                        marker,
                    ),
                )

        self.assertEqual(
            get_save_active_memory_marker_fields(
                "<SAVE_ACTIVE_MEMORY: one | two/>"
            ),
            (
                "one",
                "two",
            ),
        )


    def test_preserves_marker_when_action_disabled(self):

        result = extract_runtime_actions(
            "before <SAVE_SESSION> after",
            enabled_actions=[],
        )

        self.assertEqual(
            result.text,
            "before <SAVE_SESSION> after",
        )
        self.assertEqual(
            result.actions,
            (),
        )
        self.assertEqual(
            result.removed_markers,
            (),
        )


    def test_stream_filter_emits_started_action_for_complete_delayed_block_chunk(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_SAVE_DELAYED_MEMORY",
            ],
        )

        result = stream_filter.filter(
            (
                "<SAVE_DELAYED_MEMORY_CONTENT>\n"
                "title: Runtime state report\n"
                "summary: Current runtime state.\n"
                "tags: runtime\n"
                "body: Full report.\n"
                "</SAVE_DELAYED_MEMORY_CONTENT>\n"
            )
        )

        self.assertEqual(
            result.started_actions,
            (
                RuntimeActionCall(
                    name="SAVE_DELAYED_MEMORY_CONTENT",
                    payload="",
                ),
            ),
        )
        self.assertEqual(
            result.count("SAVE_DELAYED_MEMORY_CONTENT"),
            1,
        )


    def test_dedupes_duplicate_runtime_action_markers_by_payload(self):

        cases = (
            (
                (
                    "Before "
                    "<SAVE_ACTIVE_MEMORY: Remind to drink coffee>"
                    " middle "
                    "<SAVE_ACTIVE_MEMORY: Remind to drink coffee>"
                    " after"
                ),
                [
                    "CAN_SAVE_ACTIVE_MEMORY",
                ],
                (
                    RuntimeActionCall(
                        name="SAVE_ACTIVE_MEMORY",
                        payload="Remind to drink coffee",
                    ),
                ),
                "Before middle after",
            ),
            (
                (
                    "Before "
                    "<SAVE_SESSION>"
                    " middle "
                    "<SAVE_SESSION>"
                    " after"
                ),
                [
                    "CAN_SAVE_SESSION",
                ],
                (
                    RuntimeActionCall(
                        name="SAVE_SESSION",
                    ),
                ),
                "Before middle after",
            ),
            (
                (
                    "Before\n"
                    "<SAVE_ACTIVE_MEMORY: Remind to drink coffee>\n"
                    "<SAVE_ACTIVE_MEMORY: Remind to drink coffee>\n"
                    "After"
                ),
                [
                    "CAN_SAVE_ACTIVE_MEMORY",
                ],
                (
                    RuntimeActionCall(
                        name="SAVE_ACTIVE_MEMORY",
                        payload="Remind to drink coffee",
                    ),
                ),
                "Before\nAfter",
            ),
            (
                (
                    "Before\n"
                    "<SAVE_SESSION>\n"
                    "<SAVE_SESSION>\n"
                    "After"
                ),
                [
                    "CAN_SAVE_SESSION",
                ],
                (
                    RuntimeActionCall(
                        name="SAVE_SESSION",
                    ),
                ),
                "Before\nAfter",
            ),
        )

        for text, enabled_actions, expected_actions, expected_text in cases:
            with self.subTest(
                text=text,
            ):
                result = extract_runtime_actions(
                    text,
                    enabled_actions=enabled_actions,
                )

                self.assertEqual(
                    result.text,
                    expected_text,
                )
                self.assertEqual(
                    result.actions,
                    expected_actions,
                )
                self.assertNotIn(
                    "INTERNAL_ACTION_",
                    result.text,
                )


    def test_resolve_and_remove_actions_share_payload_normalization(self):

        cases = (
            (
                "<RESOLVE_ACTIVE_MEMORY: **abc123**>",
                "RESOLVE_ACTIVE_MEMORY",
                "abc123",
            ),
            (
                "<RESOLVE_TODO: **todo-1**>",
                "RESOLVE_TODO",
                "todo-1",
            ),
            (
                "<UNLOAD_DELAYED_MEMORY: **d4e5f6**>",
                "UNLOAD_DELAYED_MEMORY",
                "d4e5f6",
            ),
            (
                "<UNLOAD_SKILL: **wildcards**>",
                "UNLOAD_SKILL",
                "wildcards",
            ),
        )

        for marker, action_name, expected_payload in cases:
            with self.subTest(action_name=action_name):
                result = extract_runtime_actions(
                    marker
                )

                self.assertEqual(
                    result.actions,
                    (
                        RuntimeActionCall(
                            name=action_name,
                            payload=expected_payload,
                        ),
                    ),
                )


    def test_ignores_placeholder_from_all_payload_marker_bodies(self):

        with patch(
            "utils.actions.action_payload_utils.get_internal_actions_with_payload",
            return_value=(
                "<WEB_SEARCH: plain text query >",
                "<RESOLVE_ACTIVE_MEMORY: active_memory_id | STATUS >",
            ),
        ):
            search_result = extract_runtime_actions(
                "<WEB_SEARCH:<plain text query>>",
                enabled_actions=[
                    "CAN_WEB_SEARCH",
                ],
            )
            memory_result = extract_runtime_actions(
                "<SAVE_ACTIVE_MEMORY: active_memory_id|status>",
                enabled_actions=[
                    "CAN_SAVE_ACTIVE_MEMORY",
                ],
            )

        self.assertEqual(
            search_result.count("WEB_SEARCH"),
            0,
        )
        self.assertEqual(
            memory_result.count("SAVE_ACTIVE_MEMORY"),
            0,
        )


    def test_old_xml_runtime_action_protocol_is_not_parsed(self):

        result = extract_runtime_actions(
            '<RUNTIME_ACTION:SAVE_SESSION enabled="true"/>',
            enabled_actions=[
                "CAN_SAVE_SESSION",
            ],
        )

        self.assertEqual(
            result.text,
            '<RUNTIME_ACTION:SAVE_SESSION enabled="true"/>',
        )
        self.assertEqual(
            result.actions,
            (),
        )


    def test_old_internal_action_line_protocol_is_not_parsed(self):

        result = extract_runtime_actions(
            "INTERNAL_ACTION: WEB_SEARCH query: blue tomato",
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
        )

        self.assertEqual(
            result.text,
            "INTERNAL_ACTION: WEB_SEARCH query: blue tomato",
        )
        self.assertEqual(
            result.actions,
            (),
        )


    def test_stream_filter_keeps_deep_thought_marker_as_text(self):

        stream_filter = RuntimeActionStreamFilter()

        first = stream_filter.filter(
            "before <INTERNAL_ACTION_DEEP"
        )
        second = stream_filter.filter(
            "_THOUGHT> after"
        )

        self.assertEqual(
            first.text,
            "before <INTERNAL_ACTION_DEEP",
        )
        self.assertEqual(
            second.text,
            "_THOUGHT> after",
        )
        self.assertEqual(
            stream_filter.flush(),
            "",
        )


    def test_stream_filter_handles_split_clean_tool_results_marker(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
            ],
        )

        first = stream_filter.filter(
            "visible answer\n\n<CLEAN_"
        )
        second = stream_filter.filter(
            "TOOL_RESULTS>"
        )

        self.assertEqual(
            first.text,
            "visible answer",
        )
        self.assertEqual(
            first.actions,
            (),
        )
        self.assertEqual(
            second.text,
            "",
        )
        self.assertEqual(
            second.actions,
            (),
        )

        flushed = stream_filter.flush_result()

        self.assertEqual(
            flushed.text,
            "",
        )
        self.assertEqual(
            flushed.actions,
            (
                RuntimeActionCall(
                    name=RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
                ),
            ),
        )


    def test_stream_filter_handles_split_bracketed_web_search_marker(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
        )

        first = stream_filter.filter(
            "<WEB_SEARCH:\u0441\u0438"
        )
        second = stream_filter.filter(
            "\u043d\u0438\u0439 \u043f\u043e\u043c\u0438\u0434\u043e\u0440>"
        )

        self.assertEqual(
            first.text,
            "",
        )
        self.assertEqual(
            first.count("WEB_SEARCH"),
            0,
        )
        self.assertEqual(
            second.text,
            "",
        )
        self.assertEqual(
            second.search_queries,
            (
                "\u0441\u0438\u043d\u0438\u0439 \u043f\u043e\u043c\u0438\u0434\u043e\u0440",
            ),
        )
        self.assertEqual(
            stream_filter.flush(),
            "",
        )


    def test_stream_filter_keeps_unclosed_angle_marker_as_text(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
        )

        first = stream_filter.filter(
            "<WEB_SEARCH: house"
        )
        second = stream_filter.filter(
            " drawing ideas\n\n🏠\n\nМаленький уютный домик"
        )

        self.assertEqual(first.text, "")
        self.assertEqual(first.actions, ())
        self.assertEqual(
            second.text,
            (
                "<WEB_SEARCH: house drawing ideas\n\n"
                "🏠\n\nМаленький уютный домик"
            ),
        )
        self.assertEqual(second.actions, ())
        self.assertEqual(stream_filter.flush(), "")

    def test_stream_filter_keeps_split_tool_call_wrapper_as_text(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
        )

        results = (
            stream_filter.filter("<|tool"),
            stream_filter.filter("_call>call:WEB_SEARCH: blue"),
            stream_filter.filter(" tomato>"),
        )

        self.assertEqual(
            "".join(result.text for result in results),
            "<|tool_call>call:WEB_SEARCH: blue tomato>",
        )
        self.assertTrue(all(not result.actions for result in results))
        self.assertEqual(stream_filter.flush(), "")

    def test_stream_filter_keeps_split_tool_call_prefix_as_text(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
        )

        results = (
            stream_filter.filter("<tool"),
            stream_filter.filter("_call>call:WEB_SEARCH: blue"),
            stream_filter.filter(" tomato>"),
        )

        self.assertEqual(
            "".join(result.text for result in results),
            "<tool_call>call:WEB_SEARCH: blue tomato>",
        )
        self.assertTrue(all(not result.actions for result in results))
        self.assertEqual(stream_filter.flush(), "")

    def test_stream_filter_flush_keeps_unclosed_tool_call_prefix_as_text(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
        )
        text = "<tool_call>call:WEB_SEARCH: blue tomato"

        result = stream_filter.filter(text)
        flushed = stream_filter.flush_result()

        self.assertEqual(result.text, text)
        self.assertEqual(result.actions, ())
        self.assertEqual(flushed.text, "")
        self.assertEqual(flushed.actions, ())

    def test_stream_filter_keeps_bare_block_action_name_as_text(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "ASSET_ACTION",
            ],
        )

        chunks = (
            "`",
            "ASSET_ACTION",
            "` relates to tool management.",
        )
        results = tuple(
            stream_filter.filter(chunk)
            for chunk in chunks
        )

        self.assertEqual(
            "".join(result.text for result in results),
            "`ASSET_ACTION` relates to tool management.",
        )
        self.assertTrue(
            all(not result.actions for result in results)
        )
        self.assertTrue(
            all(not result.started_actions for result in results)
        )


    def test_stream_filter_keeps_split_bare_call_style_as_text(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
        )

        first = stream_filter.filter("call:")
        second = stream_filter.filter("WEB_SEARCH: blue tomato\n")

        flushed = stream_filter.flush()

        self.assertEqual(
            first.text + second.text + flushed,
            "call:WEB_SEARCH: blue tomato\n",
        )
        self.assertEqual(first.actions, ())
        self.assertEqual(second.actions, ())

    def test_stream_filter_preserves_thinking_marker_text_when_requested(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
            preserve_action_text=True,
        )

        result = stream_filter.filter(
            "Need search. <WEB_SEARCH:\u0441\u0438\u043d\u0438\u0439 \u043f\u043e\u043c\u0438\u0434\u043e\u0440>"
        )

        self.assertEqual(
            result.text,
            "Need search. <WEB_SEARCH:\u0441\u0438\u043d\u0438\u0439 \u043f\u043e\u043c\u0438\u0434\u043e\u0440>",
        )
        self.assertEqual(
            result.search_queries,
            (
                "\u0441\u0438\u043d\u0438\u0439 \u043f\u043e\u043c\u0438\u0434\u043e\u0440",
            ),
        )


    def test_stream_filter_flush_drops_incomplete_private_marker(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
        )

        result = stream_filter.filter(
            "hello <WEB_SEARCH:??"
        )

        self.assertEqual(
            result.text,
            "hello ",
        )
        self.assertEqual(
            stream_filter.flush(),
            "",
        )


    def test_stream_filter_does_not_hold_plain_angle_text(self):

        stream_filter = RuntimeActionStreamFilter()

        first = stream_filter.filter(
            "hello <"
        )
        second = stream_filter.filter(
            "not action"
        )

        self.assertEqual(
            first.text,
            "hello ",
        )
        self.assertEqual(
            second.text,
            "<not action",
        )


    def test_stream_filter_holds_confirmed_action_until_close(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
        )

        first = stream_filter.filter(
            "<WEB_SEARCH:"
        )
        middle = stream_filter.filter(
            "blue tomato"
        )
        final = stream_filter.filter(
            ">"
        )

        self.assertEqual(
            first.text,
            "",
        )
        self.assertEqual(
            middle.text,
            "",
        )
        self.assertEqual(
            final.search_queries,
            (
                "blue tomato",
            ),
        )


    def test_stream_filter_preserves_disabled_action_marker(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[],
        )

        first = stream_filter.filter(
            "quoted <SAVE_SESSION"
        )
        second = stream_filter.filter(
            "> marker"
        )

        self.assertEqual(
            first.text,
            "quoted <SAVE_SESSION",
        )
        self.assertEqual(
            second.text,
            "> marker",
        )
        self.assertEqual(
            first.actions,
            (),
        )
        self.assertEqual(
            second.actions,
            (),
        )


    def test_stream_filter_executes_consecutive_markers_across_all_chunk_boundaries(self):

        marker_text = (
            "<WEB_SEARCH: latest breakthroughs in fusion energy 2026>\n"
            "<SAVE_ACTIVE_MEMORY: experiment_start_time: "
            "2026-07-12 23:55>"
        )
        expected_actions = (
            RuntimeActionCall(
                name="WEB_SEARCH",
                payload=(
                    '{"query": "latest breakthroughs in fusion energy 2026"}'
                ),
            ),
            RuntimeActionCall(
                name="SAVE_ACTIVE_MEMORY",
                payload="experiment_start_time: 2026-07-12 23:55",
            ),
        )

        for split_at in range(1, len(marker_text)):
            with self.subTest(split_at=split_at):
                stream_filter = RuntimeActionStreamFilter(
                    enabled_actions=[
                        "CAN_WEB_SEARCH",
                        "CAN_SAVE_ACTIVE_MEMORY",
                    ],
                )

                first = stream_filter.filter(
                    marker_text[:split_at]
                )
                second = stream_filter.filter(
                    marker_text[split_at:]
                )
                final = stream_filter.flush_result()

                self.assertEqual(
                    (
                        first.text
                        + second.text
                        + final.text
                    ).strip(),
                    "",
                )
                self.assertEqual(
                    (
                        *first.actions,
                        *second.actions,
                        *final.actions,
                    ),
                    expected_actions,
                )


    def test_stream_filter_dedupes_duplicate_markers_across_chunks(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_SAVE_ACTIVE_MEMORY",
            ],
        )

        first = stream_filter.filter(
            "<SAVE_ACTIVE_MEMORY: Remind to drink coffee>"
        )
        second = stream_filter.filter(
            "<SAVE_ACTIVE_MEMORY: Remind to drink coffee>"
        )

        self.assertEqual(
            first.text,
            "",
        )
        self.assertEqual(
            first.actions,
            (
                RuntimeActionCall(
                    name="SAVE_ACTIVE_MEMORY",
                    payload="Remind to drink coffee",
                ),
            ),
        )
        self.assertEqual(
            second.text,
            "",
        )
        self.assertEqual(
            second.actions,
            (),
        )


    def test_marker_repetition_guard_flags_fifth_marker(self):

        repetition_guard = RuntimeActionRepetitionGuard(
            max_per_message=5,
        )
        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_USE_ASSETS",
            ],
            repetition_guard=repetition_guard,
        )

        result = stream_filter.filter(
            "<LOAD_SKILL: wildcards>\n"
            "<LOAD_SKILL: wildcards>\n"
            "<LOAD_SKILL: wildcards>\n"
            "<LOAD_SKILL: wildcards>\n"
            "<LOAD_SKILL: wildcards>"
        )

        self.assertTrue(
            result.marker_repetition_exceeded,
        )
        self.assertIn(
            "5 identical occurrences in one message",
            result.marker_repetition_reason,
        )


    def test_marker_repetition_guard_flags_message_repeats(self):

        repetition_guard = RuntimeActionRepetitionGuard(
            max_per_message=5,
        )
        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_USE_ASSETS",
            ],
            repetition_guard=repetition_guard,
        )

        result = stream_filter.filter(
            "<LOAD_SKILL: file_manager>\n"
            "<LOAD_SKILL: wildcards>\n"
            "<LOAD_SKILL: file_manager>\n"
            "<LOAD_SKILL: wildcards>\n"
            "<LOAD_SKILL: file_manager>\n"
            "<LOAD_SKILL: wildcards>\n"
            "<LOAD_SKILL: file_manager>\n"
            "<LOAD_SKILL: wildcards>\n"
            "<LOAD_SKILL: file_manager>\n"
            "<LOAD_SKILL: wildcards>\n"
            "<LOAD_SKILL: file_manager>"
        )

        self.assertTrue(
            result.marker_repetition_exceeded,
        )
        self.assertIn(
            "one message",
            result.marker_repetition_reason,
        )


    def test_marker_repetition_guard_stops_observing_after_trigger(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_JIN_COLOR",
            ],
            repetition_guard=RuntimeActionRepetitionGuard(
                max_per_message=5,
            ),
        )

        result = stream_filter.filter(
            "".join(
                f"<JIN_COLOR: {color}>"
                for _ in range(5)
                for color in (
                    "#0000ff",
                    "#ff0000",
                )
            )
        )

        self.assertTrue(
            result.marker_repetition_exceeded,
        )
        self.assertEqual(
            len(result.observed_actions),
            9,
        )


    def test_apply_runtime_action_calls_stores_search_queries(self):

        Context = FakeContext

        context = Context()

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="WEB_SEARCH",
                        payload='{"query":"test"}',
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            1,
        )
        self.assertEqual(
            getattr(
                context,
                "runtime_search_queries",
            ),
            [
                "test",
            ],
        )
        self.assertEqual(
            getattr(
                context,
                "runtime_action_events",
            )[0]["id"],
            "web_search_001",
        )


    def test_apply_runtime_action_calls_ignores_empty_search_payload(self):

        Context = FakeContext

        context = Context()

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="WEB_SEARCH",
                        payload='{"query":"..."}',
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            0,
        )
        self.assertFalse(
            getattr(
                context,
                "runtime_search_calls",
            ),
        )
        self.assertFalse(
            getattr(
                context,
                "runtime_action_events",
            ),
        )


    def test_apply_runtime_action_calls_keeps_distinct_search_queries(self):

        Context = FakeContext

        context = Context()

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="WEB_SEARCH",
                        payload='{"query":"first"}',
                    ),
                    RuntimeActionCall(
                        name="WEB_SEARCH",
                        payload='{"query":"second"}',
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            2,
        )
        self.assertEqual(
            getattr(
                context,
                "runtime_search_queries",
            ),
            [
                "first",
                "second",
            ],
        )


    def test_bracketed_save_session_marker_allowed_by_save_request(self):

        Context = FakeContext

        context = Context()
        result = extract_runtime_actions(
            "<SAVE_SESSION>",
            enabled_actions=[
                "CAN_SAVE_SESSION",
            ],
        )

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                result.actions,
                user_message="save session",
            )
        )

        self.assertEqual(
            result.text,
            "",
        )
        self.assertEqual(
            applied_count,
            1,
        )
        self.assertTrue(
            context.runtime_save_session_requested,
        )


    def test_save_session_marker_is_ignored_after_same_turn_l3_commit(self):

        Context = FakeContext

        context = Context()
        context.runtime_save_session_memory_committed_this_turn = True
        result = extract_runtime_actions(
            "<SAVE_SESSION>",
            enabled_actions=[
                "CAN_SAVE_SESSION",
            ],
        )

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                result.actions,
                user_message="save session",
            )
        )

        self.assertEqual(
            applied_count,
            0,
        )
        self.assertFalse(
            getattr(
                context,
                "runtime_save_session_requested",
                False,
            ),
        )


    def test_bracketed_save_session_marker_allowed_by_trigger(self):

        Context = FakeContext

        context = Context()
        result = extract_runtime_actions(
            "<SAVE_SESSION>",
            enabled_actions=[
                "CAN_SAVE_SESSION",
            ],
        )

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                result.actions,
                user_message="save session",
            )
        )

        self.assertEqual(
            applied_count,
            1,
        )
        self.assertTrue(
            context.runtime_save_session_requested,
        )


    def test_bracketed_save_session_marker_blocked_by_meta_request(self):

        Context = FakeContext

        context = Context()
        result = extract_runtime_actions(
            "<SAVE_SESSION>",
            enabled_actions=[
                "CAN_SAVE_SESSION",
            ],
        )

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                result.actions,
                user_message="show tag",
            )
        )

        self.assertEqual(
            result.text,
            "",
        )
        self.assertEqual(
            applied_count,
            0,
        )
        self.assertFalse(
            hasattr(
                context,
                "runtime_save_session_requested",
            )
        )
        self.assertEqual(
            context.runtime_action_events[-1]["status"],
            "failed",
        )


    def test_save_session_guard_intents(self):

        self.assertTrue(
            should_execute_save_session(
                "save session"
            )
        )
        self.assertFalse(
            should_execute_save_session(
                "show tag"
            )
        )
        self.assertFalse(
            should_execute_save_session(
                "normal message"
            )
        )


    def test_apply_runtime_action_calls_repairs_backslash_separated_content(self):

        Emitter = FakeEmitter

        Context = FakeContext

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                context = Context()
                context.emitter = Emitter()
                payload = (
                    r'{"action":"create_wildcard_file","args":{"path":"clothing/test_tops",'
                    r'"content":"crop top\tank top\bsleeveless blouse\mesh bodysuit\nstrappy camisole"}}'
                )

                applied_count = asyncio.run(
                    apply_runtime_action_calls(
                        context,
                        (
                            RuntimeActionCall(
                                name="ASSET_ACTION",
                                payload=payload,
                            ),
                        ),
                    )
                )

                self.assertEqual(
                    applied_count,
                    1,
                )
                output_path = (
                    root
                    / "assets"
                    / "wildcards"
                    / "clothing"
                    / "test_tops.txt"
                )
                self.assertEqual(
                    output_path.read_text(encoding="utf-8"),
                    (
                        "crop top\n"
                        "tank top\n"
                        "sleeveless blouse\n"
                        "mesh bodysuit\n"
                        "strappy camisole\n"
                    ),
                )


    def test_begin_tool_results_turn_keeps_previous_results(self):

        Context = FakeContext

        context = Context()
        context.runtime_tool_results = [
            {
                "kind": TOOL_RESULT_KIND_SEARCH,
                "result": "<RESULTS>persisted result</RESULTS>",
            },
        ]
        context.runtime_tool_results_turn_count = 1

        begin_runtime_tool_results_turn(
            context
        )

        self.assertEqual(
            context.runtime_tool_results_turn_count,
            0,
        )
        self.assertEqual(
            len(context.runtime_tool_results),
            1,
        )
        self.assertIn(
            "persisted result",
            build_tool_results_context(
                context
            ),
        )


    def test_recorded_tool_results_persist_then_append_in_order(self):

        Context = FakeContext

        context = Context()
        context.runtime_tool_results = [
            {
                "kind": TOOL_RESULT_KIND_SEARCH,
                "result": "<RESULTS>old result</RESULTS>",
            },
        ]

        begin_runtime_tool_results_turn(
            context
        )
        record_runtime_tool_result(
            context,
            TOOL_RESULT_KIND_ASSET,
            {
                "ok": True,
                "action": "list_skills",
                "skills": [
                    {
                        "name": "file_manager",
                        "path": "assets/skills/file_manager.txt",
                    },
                ],
            },
        )
        record_runtime_tool_result(
            context,
            TOOL_RESULT_KIND_DELAYED_MEMORY,
            {
                "ok": False,
                "action": "unload_delayed_memory",
                "failure": "No entries found.",
            },
        )

        tool_results = build_tool_results_context(
            context
        )

        self.assertIn(
            "old result",
            tool_results,
        )
        self.assertLess(
            tool_results.index("old result"),
            tool_results.index("file_manager"),
        )
        self.assertLess(
            tool_results.index("file_manager"),
            tool_results.index("No entries found."),
        )
        self.assertEqual(
            len(context.runtime_tool_results),
            3,
        )


    def test_failed_tool_results_dedupe_ignores_volatile_result_id(self):

        Context = FakeContext

        context = Context()
        context.runtime_delayed_memory_results = []

        begin_runtime_tool_results_turn(
            context
        )
        record_delayed_memory_runtime_result(
            context,
            {
                "ok": False,
                "action": "save_delayed_memory_content",
                "id": "save_delayed_memory_content_012",
                "error": "user_did_not_explicitly_request_report_save",
                "payload": "<SAVE_DELAYED_MEMORY_CONTENT>",
                "detail": (
                    "JIN attempted to save a delayed memory report when "
                    "the user did not explicitly request it."
                ),
                "runtime_turn_id": "turn_000001",
            },
        )
        record_delayed_memory_runtime_result(
            context,
            {
                "runtime_turn_id": "turn_000001",
                "detail": (
                    "JIN attempted to save a delayed memory report when "
                    "the user did not explicitly request it."
                ),
                "payload": "<SAVE_DELAYED_MEMORY_CONTENT>",
                "error": "user_did_not_explicitly_request_report_save",
                "id": "save_delayed_memory_content_013",
                "action": "save_delayed_memory_content",
                "ok": False,
            },
        )

        tool_results = build_tool_results_context(
            context
        )

        self.assertEqual(
            len(context.runtime_tool_results),
            1,
        )
        self.assertEqual(
            len(context.runtime_delayed_memory_results),
            1,
        )
        self.assertEqual(
            context.runtime_tool_results_turn_count,
            1,
        )
        self.assertEqual(
            tool_results.count(
                '<TOOL_RESULT name="SAVE_DELAYED_MEMORY_CONTENT">'
            ),
            1,
        )
        self.assertEqual(
            tool_results.count(
                "user_did_not_explicitly_request_report_save"
            ),
            1,
        )


    def test_clean_tool_results_action_clears_all_result_state(self):

        Emitter = FakeEmitter

        Context = FakeContext

        context = Context()
        context.emitter = Emitter()
        context.runtime_action_events = []
        context.runtime_search_calls = []
        context.runtime_loaded_skills = []
        context.runtime_tool_results = [
            {
                "kind": TOOL_RESULT_KIND_SEARCH,
                "result": "search result",
            },
        ]
        context.runtime_tool_results_turn_count = 1
        context.runtime_search_result = "search result"
        context.runtime_search_result_id = "web_search_001"
        context.runtime_asset_results = [
            {
                "action": "list_skills",
            },
        ]
        context.runtime_asset_retry_results = [
            {
                "action": "create_asset_file",
            },
        ]
        context.runtime_asset_retry_context = [
            {
                "action": "create_asset_file",
            },
        ]
        context.runtime_delayed_memory_results = [
            {
                "action": "load_delayed_memory",
            },
        ]
        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                tuple(
                    RuntimeActionCall(
                        name=RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
                    )
                    for _ in range(3)
                ),
            )
        )

        self.assertEqual(
            applied_count,
            1,
        )
        self.assertEqual(
            context.runtime_tool_results,
            [],
        )
        self.assertEqual(
            context.runtime_search_result,
            "",
        )
        self.assertEqual(
            context.runtime_search_result_id,
            "",
        )
        self.assertEqual(
            context.runtime_asset_results,
            [],
        )
        self.assertEqual(
            context.runtime_asset_retry_results,
            [],
        )
        self.assertEqual(
            context.runtime_asset_retry_context,
            [],
        )
        self.assertEqual(
            context.runtime_delayed_memory_results,
            [],
        )
        self.assertEqual(
            [
                event["name"]
                for event in context.runtime_action_events
            ],
            [
                "clean_tool_results",
            ],
        )
        self.assertEqual(
            [
                event["action"]
                for event in context.emitter.events
            ],
            [
                "clean_tool_results",
            ],
        )


    def test_apply_runtime_action_calls_deduplicates_same_resolve_id(self):

        Context = FakeContext

        context = Context()
        context.runtime_memory = (
            "active_memory_1: first [ active_memory_id: one111 ] "
            "[ status: pending ]"
        )
        context.runtime_memory_stable = context.runtime_memory
        context.active_memory_records = [
            context.runtime_memory,
        ]

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="RESOLVE_ACTIVE_MEMORY",
                        payload="one111",
                    ),
                    RuntimeActionCall(
                        name="RESOLVE_ACTIVE_MEMORY",
                        payload="one111",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            1,
        )
        self.assertEqual(
            context.active_memory_records,
            [],
        )
        self.assertEqual(
            len(context.runtime_action_events),
            1,
        )


    def test_idle_marker_variants_are_removed_and_normalized(self):

        for marker in (
            "<IDLE: 10>",
            "<IDLE: 10s >",
            "<IDLE: 10 s>",
            "<IDLE: 10ms>",
            "<IDLE: 10 ms />",
            "<IDLE:10s>",
            "<IDLE: 10 />",
            "<IDLE: 10ms />",
        ):
            with self.subTest(marker=marker):
                result = extract_runtime_actions(
                    f"before {marker} after",
                    enabled_actions=(
                        RUNTIME_ACTION_IDLE,
                    ),
                )

                self.assertEqual(
                    result.text,
                    "before after",
                )
                self.assertEqual(
                    len(result.actions),
                    1,
                )
                self.assertEqual(
                    result.actions[0].name,
                    RUNTIME_ACTION_IDLE,
                )
                self.assertEqual(
                    result.actions[0].payload,
                    "10s",
                )


    def test_idle_marker_unit_suffix_is_ignored_and_value_means_seconds(self):

        for marker in (
            "<IDLE: 20>",
            "<IDLE: 20 s>",
            "<IDLE: 20ms>",
        ):
            with self.subTest(marker=marker):
                result = extract_runtime_actions(
                    marker,
                    enabled_actions=(
                        RUNTIME_ACTION_IDLE,
                    ),
                )

                self.assertEqual(
                    result.text,
                    "",
                )
                self.assertEqual(
                    len(result.actions),
                    1,
                )
                self.assertEqual(
                    result.actions[0].payload,
                    "20s",
                )


    def test_non_marker_idle_text_is_preserved(self):

        for text in (
            "idle",
            "before idle after",
            "<IDLE>",
            "<IDLE: test >",
            "<IDLE: 20seconds>",
            "<IDLE: 20.5s>",
            "<IDLE: -20s>",
            "IDLE: test",
        ):
            with self.subTest(text=text):
                result = extract_runtime_actions(
                    text,
                    enabled_actions=(
                        RUNTIME_ACTION_IDLE,
                    ),
                )

                self.assertEqual(
                    result.text,
                    text,
                )
                self.assertEqual(
                    result.actions,
                    (),
                )
                self.assertEqual(
                    result.removed_markers,
                    (),
                )


    def test_runtime_action_marker_removal_compacts_inline_whitespace(self):

        cases = (
            (
                "before <JIN_COLOR: #00f2ff> after",
                "before after",
            ),
            (
                "<JIN_COLOR: #00f2ff> after",
                "after",
            ),
            (
                "before <JIN_COLOR: #00f2ff>",
                "before",
            ),
            (
                "before\n<JIN_COLOR: #00f2ff>\n\nafter",
                "before\nafter",
            ),
            (
                "before\n\n<JIN_COLOR: #00f2ff>",
                "before",
            ),
        )

        for source, expected_text in cases:
            with self.subTest(source=source):
                result = extract_runtime_actions(
                    source,
                    enabled_actions=(
                        RUNTIME_ACTION_JIN_COLOR,
                    ),
                )

                self.assertEqual(
                    result.text,
                    expected_text,
                )
                self.assertEqual(
                    len(result.actions),
                    1,
                )


    def test_stream_filter_holds_trailing_blank_space_before_marker(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=(
                RUNTIME_ACTION_JIN_COLOR,
            ),
        )

        first = stream_filter.filter(
            "before\n\n"
        )
        second = stream_filter.filter(
            "<JIN_COLOR: #00f2ff>"
        )
        final = stream_filter.flush_result()

        self.assertEqual(
            first.text,
            "before",
        )
        self.assertEqual(
            second.text,
            "",
        )
        self.assertEqual(
            final.text,
            "",
        )
        self.assertEqual(
            [
                action.payload
                for action in second.actions
            ],
            [
                "#00f2ff",
            ],
        )


    def test_stream_filter_holds_trailing_blank_space_before_partial_marker(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=(
                RUNTIME_ACTION_JIN_COLOR,
            ),
        )

        first = stream_filter.filter(
            "before\n\n"
        )
        second = stream_filter.filter(
            "<JIN"
        )
        third = stream_filter.filter(
            "_COLOR: #00f2ff>"
        )

        self.assertEqual(
            first.text,
            "before",
        )
        self.assertEqual(
            second.text,
            "",
        )
        self.assertEqual(
            third.text,
            "",
        )
        self.assertEqual(
            [
                action.payload
                for action in third.actions
            ],
            [
                "#00f2ff",
            ],
        )


    def test_stream_filter_holds_inline_trailing_blank_space_before_partial_marker(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=(
                RUNTIME_ACTION_JIN_COLOR,
            ),
        )

        first = stream_filter.filter(
            "before\n\n<JIN"
        )
        second = stream_filter.filter(
            "_COLOR: #00f2ff>"
        )

        self.assertEqual(
            first.text,
            "before",
        )
        self.assertEqual(
            second.text,
            "",
        )
        self.assertEqual(
            [
                action.payload
                for action in second.actions
            ],
            [
                "#00f2ff",
            ],
        )


    def test_stream_filter_releases_held_blank_space_before_plain_text(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=(
                RUNTIME_ACTION_JIN_COLOR,
            ),
        )

        first = stream_filter.filter(
            "before\n\n"
        )
        second = stream_filter.filter(
            "after"
        )

        self.assertEqual(
            first.text,
            "before",
        )
        self.assertEqual(
            second.text,
            "\n\nafter",
        )
        self.assertEqual(
            second.actions,
            (),
        )


    def test_stream_filter_preserves_idle_word_emitted_as_own_chunk(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=(
                RUNTIME_ACTION_IDLE,
            ),
        )

        results = [
            stream_filter.filter(
                "Привет, вставляю слово "
            ),
            stream_filter.filter(
                "idle"
            ),
            stream_filter.filter(
                " в середине сообщения."
            ),
            stream_filter.flush_result(),
        ]

        self.assertEqual(
            "".join(
                result.text
                for result in results
            ),
            "Привет, вставляю слово idle в середине сообщения.",
        )
        self.assertEqual(
            tuple(
                action
                for result in results
                for action in result.actions
            ),
            (),
        )
        self.assertEqual(
            tuple(
                marker
                for result in results
                for marker in result.removed_markers
            ),
            (),
        )


    def test_repeated_idle_markers_remain_independent_actions(self):

        result = extract_runtime_actions(
            "<IDLE: 0s /><IDLE: 0s /><IDLE: 0s /><IDLE: 0s />",
            enabled_actions=(
                RUNTIME_ACTION_IDLE,
            ),
            repetition_guard=RuntimeActionRepetitionGuard(),
        )

        self.assertEqual(
            result.text,
            "",
        )
        self.assertFalse(
            result.marker_repetition_exceeded
        )
        self.assertEqual(
            [
                action.payload
                for action in result.actions
            ],
            [
                "0s",
                "0s",
                "0s",
                "0s",
            ],
        )


    def test_stream_filter_keeps_repeated_idle_markers_across_chunks(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=(
                RUNTIME_ACTION_IDLE,
            ),
            repetition_guard=RuntimeActionRepetitionGuard(),
        )

        first = stream_filter.filter(
            "<IDLE: 3s />"
        )
        second = stream_filter.filter(
            "<IDLE: 3s />"
        )

        self.assertEqual(
            [
                action.payload
                for action in (
                    *first.actions,
                    *second.actions,
                )
            ],
            [
                "3s",
                "3s",
            ],
        )
        self.assertFalse(
            first.marker_repetition_exceeded
        )
        self.assertFalse(
            second.marker_repetition_exceeded
        )


    def test_duplicate_idle_actions_queue_one_request_and_flash_bubble(self):

        Emitter = FakeEmitter

        async def run_case():
            queue = asyncio.Queue()
            emitter = Emitter()
            context = SimpleNamespace(
                background_tasks=set(),
                runtime_action_events=[],
                runtime_search_calls=[],
                runtime_loaded_skills=[],
                runtime_pending_requests_queue=queue,
                runtime_pending_idle_followups=[],
                runtime_idle_action_sequence=0,
                runtime_save_session_requested=False,
                runtime_save_session_action_emitted=False,
                runtime_skill_state_barrier_active=False,
                runtime_current_turn_id="turn_000001",
                logger=None,
                emitter=emitter,
            )
            actions = (
                RuntimeActionCall(
                    name=RUNTIME_ACTION_IDLE,
                    payload="0s",
                ),
                RuntimeActionCall(
                    name=RUNTIME_ACTION_IDLE,
                    payload="0s",
                ),
                RuntimeActionCall(
                    name=RUNTIME_ACTION_IDLE,
                    payload="0s",
                ),
            )

            applied_count = await apply_runtime_action_calls(
                context,
                actions,
                user_message="schedule three ticks",
                context_snapshot={
                    "system_prompt": "frozen prompt",
                    "user_prompt": "schedule three ticks",
                },
                assistant_message=(
                    "<IDLE: 0s /><IDLE: 0s /><IDLE: 0s />"
                ),
            )
            queued = [
                await asyncio.wait_for(
                    queue.get(),
                    timeout=1,
                )
                for _ in range(1)
            ]

            self.assertEqual(
                applied_count,
                1,
            )
            self.assertEqual(
                [
                    item["idle_followup"]["id"]
                    for item in queued
                ],
                [
                    "idle_001",
                ],
            )
            self.assertEqual(
                [
                    (
                        event.get("id"),
                        event.get("status"),
                        event.get("text", ""),
                        event.get("detail", ""),
                    )
                    for event in emitter.events
                ],
                [
                    ("idle_001", "started", "IDLE: 0s", "0s"),
                    ("idle_001", "completed", "", "0s"),
                ],
            )
            self.assertEqual(
                {
                    event.get("runtime_turn_id")
                    for event in emitter.events
                },
                {"turn_000001"},
            )

        asyncio.run(run_case())


    def test_zero_second_idle_queues_followup_with_full_source_message(self):

        async def run_case():
            queue = asyncio.Queue()
            context = SimpleNamespace(
                background_tasks=set(),
                runtime_action_events=[],
                runtime_search_calls=[],
                runtime_loaded_skills=[],
                runtime_pending_requests_queue=queue,
                runtime_pending_idle_followups=[],
                runtime_idle_action_sequence=0,
                runtime_save_session_requested=False,
                runtime_save_session_action_emitted=False,
                runtime_skill_state_barrier_active=False,
                runtime_current_turn_id="turn_000001",
                logger=None,
            )
            source_message = (
                "I will check this again. "
                "<IDLE: 0s /> "
                "The rest of the same message."
            )
            result = extract_runtime_actions(
                source_message,
                enabled_actions=(
                    RUNTIME_ACTION_IDLE,
                ),
            )

            applied_count = await apply_runtime_action_calls(
                context,
                result.actions,
                user_message="original request",
                context_snapshot={
                    "system_prompt": "frozen prompt",
                    "user_prompt": "original request",
                },
                assistant_message=source_message,
            )
            queued = await asyncio.wait_for(
                queue.get(),
                timeout=1,
            )

            self.assertEqual(applied_count, 1)
            self.assertEqual(queued["type"], "idle_followup")
            self.assertEqual(
                queued["idle_followup"]["source_message"],
                source_message,
            )
            self.assertEqual(
                queued["idle_followup"]["seconds"],
                0,
            )

        asyncio.run(run_case())


    def test_extract_search_query_unnests_json_string(self):

        self.assertEqual(
            extract_search_query(
                '"{\\"query\\":\\"apples price 2026\\"}"'
            ),
            "apples price 2026",
        )


    def test_extract_search_query_unnests_query_json_string(self):

        self.assertEqual(
            extract_search_query(
                '{"query":"{\\"query\\":\\"apples price 2026\\"}"}'
            ),
            "apples price 2026",
        )

