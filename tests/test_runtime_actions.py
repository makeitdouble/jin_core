import asyncio
import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from clients import (
    apply_runtime_action_calls,
)
from clients.brain_client_utils import (
    flush_pending_active_memory_resolve_failure_history,
)
from utils.context.brain_context_builder import (
    build_appended_delayed_memory_context,
    build_tool_results_context,
)
from clients.brain_client import (
    should_execute_save_session,
)
from rules import runtime as runtime_rules
from utils.assets_service import (
    list_skills,
    normalize_skill_name,
    read_asset_text_preview,
    run_asset_action,
)
from utils.runtime_todo import (
    create_runtime_todo,
)
from utils.tool_results import (
    TOOL_RESULT_KIND_ACTIVE_MEMORY,
    TOOL_RESULT_KIND_ASSET,
    TOOL_RESULT_KIND_DELAYED_MEMORY,
    TOOL_RESULT_KIND_SEARCH,
    begin_runtime_tool_results_turn,
    record_runtime_tool_result,
)
from utils.runtime_actions import (
    RuntimeActionCall,
    RuntimeActionRepetitionGuard,
    RuntimeActionStreamFilter,
    extract_active_memory_resolve_slot_id,
    extract_search_query,
    extract_runtime_actions,
    get_create_active_memory_marker_fields,
    get_create_active_memory_placeholder_payload,
    parse_delayed_memory_content_payload,
)


def legacy_internal_action_marker(marker: str) -> str:
    if marker.startswith(
        "</"
    ):
        return marker.replace(
            "</",
            "</INTERNAL_ACTION_",
            1,
        )

    return marker.replace(
        "<",
        "<INTERNAL_ACTION_",
        1,
    )


class RuntimeActionTests(unittest.TestCase):

    def patch_asset_roots(self, root: Path):
        assets_root = root / "assets"
        return (
            patch("utils.assets_service.PROJECT_ROOT", root),
            patch("utils.assets_service.ASSETS_ROOT", assets_root),
            patch("utils.assets_service.SKILLS_ROOT", assets_root / "skills"),
            patch("utils.assets_service.WILDCARDS_ROOT", assets_root / "wildcards"),
            patch("utils.assets_service.PROMPTS_ROOT", assets_root / "prompts"),
            patch("utils.assets_service.TEMPLATES_ROOT", assets_root / "templates"),
            patch("utils.assets_service.OUTPUTS_ROOT", assets_root / "outputs"),
        )

    def write_skill_fixture(
        self,
        root: Path,
        filename: str,
        content: str,
    ):
        skill_path = (
            root
            / "assets"
            / "skills"
            / filename
        )
        skill_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        skill_path.write_text(
            content,
            encoding="utf-8",
        )
        return skill_path

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


    def test_extracts_bracketed_web_search_marker(self):

        result = extract_runtime_actions(
            "<INTERNAL_ACTION_WEB_SEARCH:\u0441\u0438\u043d\u0438\u0439 \u043f\u043e\u043c\u0438\u0434\u043e\u0440>",
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

    def test_extracts_bracketed_web_search_marker_inside_text(self):

        result = extract_runtime_actions(
            (
                "Before\n"
                "<INTERNAL_ACTION_WEB_SEARCH:\u0441\u0438\u043d\u0438\u0439 \u043f\u043e\u043c\u0438\u0434\u043e\u0440>\n"
                "After"
            ),
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
        )

        self.assertNotIn(
            "INTERNAL_ACTION_WEB_SEARCH",
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

    def test_extracts_bracketed_web_search_marker_terminated_by_newline(self):

        result = extract_runtime_actions(
            (
                "<INTERNAL_ACTION_WEB_SEARCH: house drawing ideas\n"
                "\n"
                "🏠\n"
                "\n"
                "Маленький уютный домик"
            ),
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
        )

        self.assertNotIn(
            "INTERNAL_ACTION_WEB_SEARCH",
            result.text,
        )
        self.assertEqual(
            result.text,
            "🏠\n\nМаленький уютный домик",
        )
        self.assertEqual(
            result.search_queries,
            (
                "house drawing ideas",
            ),
        )
        self.assertEqual(
            result.removed_markers,
            (
                "<INTERNAL_ACTION_WEB_SEARCH: house drawing ideas",
            ),
        )

    def test_extracts_tool_call_style_web_search_marker(self):

        result = extract_runtime_actions(
            "<|tool_call>call:INTERNAL_ACTION_WEB_SEARCH: \u0441\u0435\u0440\u0438\u0430\u043b\u044b, \u043f\u043e\u0445\u043e\u0436\u0438\u0435 \u043d\u0430 From (\u0441\u0435\u0440\u0438\u0430\u043b) >",
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
                "\u0441\u0435\u0440\u0438\u0430\u043b\u044b, \u043f\u043e\u0445\u043e\u0436\u0438\u0435 \u043d\u0430 From (\u0441\u0435\u0440\u0438\u0430\u043b)",
            ),
        )
        self.assertEqual(
            result.removed_markers,
            (
                "<|tool_call>call:INTERNAL_ACTION_WEB_SEARCH: \u0441\u0435\u0440\u0438\u0430\u043b\u044b, \u043f\u043e\u0445\u043e\u0436\u0438\u0435 \u043d\u0430 From (\u0441\u0435\u0440\u0438\u0430\u043b) >",
            ),
        )

    def test_extracts_tool_call_style_web_search_marker_without_internal_prefix(self):

        result = extract_runtime_actions(
            "<tool_call>call:WEB_SEARCH: Gemma 4 differences between e2b and e4b versions",
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
                "Gemma 4 differences between e2b and e4b versions",
            ),
        )
        self.assertEqual(
            result.removed_markers,
            (
                "<tool_call>call:WEB_SEARCH: Gemma 4 differences between e2b and e4b versions",
            ),
        )

    def test_extracts_bare_call_style_web_search_marker_line(self):

        result = extract_runtime_actions(
            "call:INTERNAL_ACTION_WEB_SEARCH: \u0441\u0435\u0440\u0438\u0430\u043b\u044b, \u043f\u043e\u0445\u043e\u0436\u0438\u0435 \u043d\u0430 From (\u0441\u0435\u0440\u0438\u0430\u043b)",
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
                "\u0441\u0435\u0440\u0438\u0430\u043b\u044b, \u043f\u043e\u0445\u043e\u0436\u0438\u0435 \u043d\u0430 From (\u0441\u0435\u0440\u0438\u0430\u043b)",
            ),
        )

    def test_extracts_bare_call_style_web_search_marker_without_internal_prefix(self):

        result = extract_runtime_actions(
            "call:WEB_SEARCH: blue tomato",
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

    def test_does_not_extract_inline_bare_call_style_marker(self):

        result = extract_runtime_actions(
            "before call:INTERNAL_ACTION_WEB_SEARCH: blue tomato after",
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
        )

        self.assertEqual(
            result.text,
            "before call:INTERNAL_ACTION_WEB_SEARCH: blue tomato after",
        )
        self.assertEqual(
            result.actions,
            (),
        )

    def test_ignores_placeholder_bracketed_web_search_marker(self):

        current_placeholder = runtime_rules.INTERNAL_ACTION_WEB_SEARCH_MARKER
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
                "",
            )
            self.assertEqual(
                result.count("WEB_SEARCH"),
                0,
            )

    def test_extracts_bracketed_save_session_marker(self):

        result = extract_runtime_actions(
            "<INTERNAL_ACTION_SAVE_SESSION>",
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
                "<INTERNAL_ACTION_SAVE_SESSION>",
            ),
        )

    def test_extracts_list_skills_marker(self):

        result = extract_runtime_actions(
            "<INTERNAL_ACTION_LIST_SKILLS>",
            enabled_actions=[
                "CAN_USE_ASSETS",
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
                    name="LIST_SKILLS",
                    payload="",
                ),
            ),
        )

    def test_extracts_hide_skills_marker(self):

        result = extract_runtime_actions(
            runtime_rules.INTERNAL_ACTION_HIDE_SKILLS_MARKER,
            enabled_actions=[
                "CAN_USE_ASSETS",
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
                    name="HIDE_SKILLS",
                    payload="",
                ),
            ),
        )

    def test_extracts_clean_tool_results_marker(self):

        result = extract_runtime_actions(
            runtime_rules.INTERNAL_ACTION_CLEAN_TOOL_RESULTS_MARKER,
            enabled_actions=[
                runtime_rules.RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
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
                    name=runtime_rules.RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
                    payload="",
                ),
            ),
        )

    def test_extracts_current_list_skills_marker(self):

        result = extract_runtime_actions(
            runtime_rules.INTERNAL_ACTION_LIST_SKILLS_MARKER,
            enabled_actions=[
                "CAN_USE_ASSETS",
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
                    name="LIST_SKILLS",
                    payload="",
                ),
            ),
        )

    def test_extracts_self_closing_runtime_markers_without_blocks(self):

        cases = (
            ("<SAVE_SESSION/>", "SAVE_SESSION", ""),
            ("<LIST_SKILLS/>", "LIST_SKILLS", ""),
            ("<INTERNAL_ACTION_LIST_SKILLS/>", "LIST_SKILLS", ""),
            (
                "<WEB_SEARCH: blue tomato/>",
                "WEB_SEARCH",
                json.dumps({
                    "query": "blue tomato",
                }),
            ),
            (
                "<CREATE_ACTIVE_MEMORY: remember tea/>",
                "CREATE_ACTIVE_MEMORY",
                "remember tea",
            ),
            (
                "<APPEND_SKILL: file_manager/>",
                "APPEND_SKILL",
                "file_manager",
            ),
            (
                "<RESOLVE_TODO: todo-1/>",
                "RESOLVE_TODO",
                "todo-1",
            ),
            (
                "<APPEND_DELAYED_MEMORY: a1b2c3/>",
                "APPEND_DELAYED_MEMORY",
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
            get_create_active_memory_marker_fields(
                "<CREATE_ACTIVE_MEMORY: one | two/>"
            ),
            (
                "one",
                "two",
            ),
        )

    def test_stream_filter_handles_split_self_closing_list_skills_marker(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_USE_ASSETS",
            ],
        )

        first = stream_filter.filter(
            "<LIST_SKILLS"
        )
        second = stream_filter.filter(
            "/>"
        )

        self.assertEqual(
            first.text,
            "",
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
            (
                RuntimeActionCall(
                    name="LIST_SKILLS",
                    payload="",
                ),
            ),
        )
        self.assertEqual(
            stream_filter.flush(),
            "",
        )

    def test_extracts_append_and_remove_skill_markers(self):

        result = extract_runtime_actions(
            (
                "<INTERNAL_ACTION_APPEND_SKILL: image_prompt_generator>\n"
                "<INTERNAL_ACTION_REMOVE_SKILL: wildcards>"
            ),
            enabled_actions=[
                "CAN_USE_ASSETS",
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
                    name="APPEND_SKILL",
                    payload="image_prompt_generator",
                ),
                RuntimeActionCall(
                    name="REMOVE_SKILL",
                    payload="wildcards",
                ),
            ),
        )

    def test_extracts_plural_append_and_remove_skill_markers(self):

        result = extract_runtime_actions(
            (
                "<INTERNAL_ACTION_APPEND_SKILLS: "
                "file_manager, image_prompt_generator, porn, wildcards>\n"
                "<INTERNAL_ACTION_REMOVE_SKILLS: old_skill, unused_skill>"
            ),
            enabled_actions=[
                "CAN_USE_ASSETS",
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
                    name="APPEND_SKILL",
                    payload="file_manager",
                ),
                RuntimeActionCall(
                    name="APPEND_SKILL",
                    payload="image_prompt_generator",
                ),
                RuntimeActionCall(
                    name="APPEND_SKILL",
                    payload="porn",
                ),
                RuntimeActionCall(
                    name="APPEND_SKILL",
                    payload="wildcards",
                ),
                RuntimeActionCall(
                    name="REMOVE_SKILL",
                    payload="old_skill",
                ),
                RuntimeActionCall(
                    name="REMOVE_SKILL",
                    payload="unused_skill",
                ),
            ),
        )

    def test_extracts_append_skill_marker_with_name_attribute(self):

        result = extract_runtime_actions(
            '<INTERNAL_ACTION_APPEND_SKILL name="file_manager" />',
            enabled_actions=[
                "CAN_USE_ASSETS",
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
                    name="APPEND_SKILL",
                    payload="file_manager",
                ),
            ),
        )

    def test_extracts_asset_action_block(self):

        result = extract_runtime_actions(
            (
                "<INTERNAL_ACTION_ASSET_ACTION>\n"
                '{"action":"list_wildcards"}\n'
                "</INTERNAL_ACTION_ASSET_ACTION>\n"
                "Done."
            ),
            enabled_actions=[
                "CAN_USE_ASSETS",
            ],
        )

        self.assertEqual(
            result.text,
            "Done.",
        )
        self.assertEqual(
            result.actions,
            (
                RuntimeActionCall(
                    name="ASSET_ACTION",
                    payload='{"action":"list_wildcards"}',
                ),
            ),
        )

    def test_extracts_asset_action_block_with_args_payload(self):

        result = extract_runtime_actions(
            (
                "<INTERNAL_ACTION_ASSET_ACTION>\n"
                '{"action":"create_wildcard_file","args":{"path":"clothing/test_tops","content":"cropped tank top\\nlace camisole"}}\n'
                "</INTERNAL_ACTION_ASSET_ACTION>\n"
                "Создал файл."
            ),
            enabled_actions=[
                "CAN_USE_ASSETS",
            ],
        )

        self.assertEqual(
            result.text,
            "Создал файл.",
        )
        self.assertEqual(
            result.count("ASSET_ACTION"),
            1,
        )
        self.assertNotIn(
            "INTERNAL_ACTION_ASSET_ACTION",
            result.text,
        )

    def test_extracts_asset_action_block_closed_by_repeated_open_tag(self):

        result = extract_runtime_actions(
            (
                "<INTERNAL_ACTION_ASSET_ACTION>\n"
                '{"action":"append_asset_file","path":"assets/outputs/posing_woman_prompts.txt","content":"\\nBatch 1 complete."}\n'
                "<INTERNAL_ACTION_ASSET_ACTION>\n"
                "Done."
            ),
            enabled_actions=[
                "CAN_USE_ASSETS",
            ],
        )

        self.assertEqual(
            result.text,
            "Done.",
        )
        self.assertEqual(
            result.actions,
            (
                RuntimeActionCall(
                    name="ASSET_ACTION",
                    payload='{"action":"append_asset_file","path":"assets/outputs/posing_woman_prompts.txt","content":"\\nBatch 1 complete."}',
                ),
            ),
        )

    def test_extracts_asset_action_block_with_spaced_closing_tag(self):

        result = extract_runtime_actions(
            (
                "< INTERNAL_ACTION_ASSET_ACTION >\n"
                '{"action":"append_asset_file","path":"assets/outputs/woman_prompts.txt","content":"Batch 1"}\n'
                "< /INTERNAL_ACTION_ASSET_ACTION >\n"
                "Done."
            ),
            enabled_actions=[
                "CAN_USE_ASSETS",
            ],
        )

        self.assertEqual(
            result.text,
            "Done.",
        )
        self.assertEqual(
            result.actions,
            (
                RuntimeActionCall(
                    name="ASSET_ACTION",
                    payload='{"action":"append_asset_file","path":"assets/outputs/woman_prompts.txt","content":"Batch 1"}',
                ),
            ),
        )

    def test_stream_filter_strips_asset_action_block(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_USE_ASSETS",
            ],
        )

        first = stream_filter.filter(
            (
                "<INTERNAL_ACTION_ASSET_ACTION>\n"
                '{"action":"create_wildcard_file","args":{"path":"clothing/test_tops",'
            )
        )
        second = stream_filter.filter(
            (
                '"content":"cropped tank top\\nlace camisole"}}\n'
                "</INTERNAL_ACTION_ASSET_ACTION>\n"
                "Создал файл."
            )
        )

        self.assertEqual(
            first.text,
            "",
        )
        self.assertEqual(
            first.actions,
            (),
        )
        self.assertEqual(
            second.text,
            "Создал файл.",
        )
        self.assertEqual(
            second.count("ASSET_ACTION"),
            1,
        )
        self.assertEqual(
            first.started_actions,
            (
                RuntimeActionCall(
                    name="ASSET_ACTION",
                    payload="",
                ),
            ),
        )

    def test_stream_filter_strips_asset_action_block_boundary_variants(self):

        variants = [
            [
                (
                    "<INTERNAL_ACTION_ASSET_ACTION>\n"
                    '{"action":"create_wildcard_file","args":{"path":"clothing/shoes","content":"sneakers\\nboots"}}\n'
                    "</INTERNAL_ACTION_ASSET_ACTION>"
                ),
            ],
            [
                "<INTERNAL_ACTION_AS",
                "SET_ACTION>\n",
                '{"action":"create_wildcard_file","args":{"path":"clothing/shoes","content":"sneakers\\nboots"}}\n',
                "</INTERNAL_ACTION_ASSET_ACTION>",
            ],
            [
                "\n\n  <INTERNAL_ACTION_ASSET_ACTION>\n",
                '{\n  "action": "create_wildcard_file",\n  "args": {\n    "path": "clothing/shoes",\n    "content": "sneakers\\nboots"\n  }\n}\n',
                "</INTERNAL_ACTION_ASSET_ACTION>\n",
            ],
            [
                "<INTERNAL_ACTION_ASSET_ACTION>\n",
                '{"action":"create_wildcard_file","args":{"path":"clothing/shoes","content":"sneakers\\nboots"}}\n',
                "<INTERNAL_ACTION_ASSET_ACTION>\n",
            ],
            [
                "< INTERNAL_ACTION_ASSET_ACTION >\n",
                '{"action":"create_wildcard_file","args":{"path":"clothing/shoes","content":"sneakers\\nboots"}}\n',
                "< / INTERNAL_ACTION_ASSET_ACTION >\n",
            ],
            [
                "<INTERNAL_ACTION_ASSET_ACTION>\n",
                '{"action":"create_wildcard_file","args":{"path":"clothing/shoes","content":"sneakers\\nboots"}}\n',
                "< /INTERNAL_ACTION_ASSET_ACTION>\n",
            ],
        ]

        for chunks in variants:
            with self.subTest(chunks=chunks):
                stream_filter = RuntimeActionStreamFilter(
                    enabled_actions=[
                        "CAN_USE_ASSETS",
                    ],
                )
                visible_text = []
                actions = []

                for chunk in chunks:
                    result = stream_filter.filter(
                        chunk
                    )
                    visible_text.append(
                        result.text
                    )
                    actions.extend(
                        result.actions
                    )

                tail = stream_filter.flush_result()
                visible_text.append(
                    tail.text
                )
                actions.extend(
                    tail.actions
                )

                joined_visible_text = "".join(
                    visible_text
                )

                self.assertNotIn(
                    "INTERNAL_ACTION_ASSET_ACTION",
                    joined_visible_text,
                )
                self.assertEqual(
                    joined_visible_text.strip(),
                    "",
                )
                self.assertEqual(
                    len(actions),
                    1,
                )
                self.assertEqual(
                    actions[0].name,
                    "ASSET_ACTION",
                )

    def test_preserves_marker_when_action_disabled(self):

        result = extract_runtime_actions(
            "before <INTERNAL_ACTION_SAVE_SESSION> after",
            enabled_actions=[],
        )

        self.assertEqual(
            result.text,
            "before <INTERNAL_ACTION_SAVE_SESSION> after",
        )
        self.assertEqual(
            result.actions,
            (),
        )
        self.assertEqual(
            result.removed_markers,
            (),
        )

    def test_preserves_delayed_memory_marker_when_action_disabled(self):

        text = (
            "before\n"
            "<INTERNAL_ACTION_SAVE_DELAYED_MEMORY_CONTENT>\n"
            '{"demo": {"summary": "quoted marker"}}\n'
            "</INTERNAL_ACTION_SAVE_DELAYED_MEMORY_CONTENT>\n"
            "after"
        )

        result = extract_runtime_actions(
            text,
            enabled_actions=[],
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

    def test_extracts_bracketed_create_active_memory_marker(self):

        result = extract_runtime_actions(
            (
                "before "
                "<INTERNAL_ACTION_CREATE_ACTIVE_MEMORY:remind later | tomorrow | coffee>"
                " after"
            ),
            enabled_actions=[
                "CAN_SAVE_ACTIVE_MEMORY",
            ],
        )

        self.assertEqual(
            result.text,
            "before  after",
        )
        self.assertEqual(
            result.count("CREATE_ACTIVE_MEMORY"),
            1,
        )
        self.assertEqual(
            result.actions[0].payload,
            "remind later | tomorrow | coffee",
        )

    def test_extracts_create_active_memory_marker_closed_with_short_end_tag(self):

        result = extract_runtime_actions(
            (
                "before "
                "<INTERNAL_ACTION_CREATE_ACTIVE_MEMORY: remember the word coffee "
                "and ask for a guess later.</>"
                " after"
            ),
            enabled_actions=[
                "CAN_SAVE_ACTIVE_MEMORY",
            ],
        )

        self.assertEqual(
            result.text,
            "before  after",
        )
        self.assertEqual(
            result.actions,
            (
                RuntimeActionCall(
                    name="CREATE_ACTIVE_MEMORY",
                    payload=(
                        "remember the word coffee "
                        "and ask for a guess later."
                    ),
                ),
            ),
        )

    def test_parses_delayed_memory_content_payload(self):

        report = parse_delayed_memory_content_payload(
            (
                "title: Radius of Influence Specs\n"
                "summary: Three-zone data priority model for Kowloon Sandbox simulation.\n"
                "tags: kowloon_sandbox, simulation, world_state, radius_of_influence\n"
                "body:\n"
                "### Radius of Influence Specs\n"
                "\n"
                "A complete, self-sufficient summary..."
            ),
            created_session_id="session-1",
            created_time="2026-06-29T12:00:00",
        )

        self.assertEqual(
            len(report),
            1,
        )
        report_id, report_value = next(
            iter(report.items())
        )
        self.assertRegex(
            report_id,
            r"^[a-z0-9]{6}$",
        )
        self.assertEqual(
            report_value,
            {
                "title": "Radius of Influence Specs",
                "summary": (
                    "Three-zone data priority model for Kowloon Sandbox simulation."
                ),
                "tags": [
                    "kowloon_sandbox",
                    "simulation",
                    "world_state",
                    "radius_of_influence",
                ],
                "body": (
                    "### Radius of Influence Specs\n\n"
                    "A complete, self-sufficient summary..."
                ),
                "created_session_id": "session-1",
                "created_time": "2026-06-29T12:00:00",
            },
        )

    def test_extracts_delayed_memory_content_block(self):

        result = extract_runtime_actions(
            (
                "<INTERNAL_ACTION_SAVE_DELAYED_MEMORY_CONTENT>\n"
                "title: Radius of Influence Specs\n"
                "summary: Three-zone data priority model for Kowloon Sandbox simulation.\n"
                "tags: kowloon_sandbox, simulation, world_state, radius_of_influence\n"
                "body:\n"
                "### Radius of Influence Specs\n"
                "\n"
                "A complete, self-sufficient summary...\n"
                "</INTERNAL_ACTION_SAVE_DELAYED_MEMORY_CONTENT>\n"
                "\n"
                "Done."
            ),
            enabled_actions=[
                "CAN_SAVE_DELAYED_MEMORY",
            ],
        )

        self.assertEqual(
            result.text,
            "Done.",
        )
        self.assertEqual(
            result.count("SAVE_DELAYED_MEMORY_CONTENT"),
            1,
        )
        report = json.loads(
            result.actions[0].payload
        )
        self.assertEqual(
            len(report),
            1,
        )
        report_id, report_value = next(
            iter(report.items())
        )
        self.assertRegex(
            report_id,
            r"^[a-z0-9]{6}$",
        )
        self.assertEqual(
            report_value["title"],
            "Radius of Influence Specs",
        )

    def test_stream_filter_emits_delayed_memory_started_action(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_SAVE_DELAYED_MEMORY",
            ],
        )

        first = stream_filter.filter(
            (
                "<SAVE_DELAYED_MEMORY_CONTENT>\n"
                "title: Radius of Influence Specs\n"
                "summary: Three-zone data priority model.\n"
            )
        )
        second = stream_filter.filter(
            (
                "tags: simulation, world_state\n"
                "body: Complete report body.\n"
                "</SAVE_DELAYED_MEMORY_CONTENT>\n"
            )
        )

        self.assertEqual(
            first.text,
            "",
        )
        self.assertEqual(
            first.started_actions,
            (
                RuntimeActionCall(
                    name="SAVE_DELAYED_MEMORY_CONTENT",
                    payload="",
                ),
            ),
        )
        self.assertEqual(
            second.count("SAVE_DELAYED_MEMORY_CONTENT"),
            1,
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

    def test_stream_filter_recovers_complete_delayed_memory_without_closing_tag(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_SAVE_DELAYED_MEMORY",
            ],
        )

        first = stream_filter.filter(
            (
                "<SAVE_DELAYED_MEMORY_CONTENT>\n"
                "title: Radius of Influence Specs\n"
                "summary: Three-zone data priority model.\n"
                "tags: simulation, world_state\n"
                "body: Complete report body.\n"
            )
        )
        tail = stream_filter.flush_result()

        self.assertEqual(
            first.started_actions[0].name,
            "SAVE_DELAYED_MEMORY_CONTENT",
        )
        self.assertEqual(
            tail.count("SAVE_DELAYED_MEMORY_CONTENT"),
            1,
        )
        report = json.loads(
            tail.actions[0].payload
        )
        self.assertEqual(
            next(iter(report.values()))["title"],
            "Radius of Influence Specs",
        )

    def test_extracts_delayed_memory_action_markers(self):

        result = extract_runtime_actions(
            (
                "<LIST_DELAYED_MEMORY>\n"
                "<APPEND_DELAYED_MEMORY: a1b2c3>\n"
                "<REMOVE_DELAYED_MEMORY: d4e5f6>\n"
            ),
            enabled_actions=[
                "CAN_SAVE_DELAYED_MEMORY",
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
                    name="LIST_DELAYED_MEMORY",
                    payload="",
                ),
                RuntimeActionCall(
                    name="APPEND_DELAYED_MEMORY",
                    payload="a1b2c3",
                ),
                RuntimeActionCall(
                    name="REMOVE_DELAYED_MEMORY",
                    payload="d4e5f6",
                ),
            ),
        )

    def test_stream_filter_holds_split_delayed_memory_action_marker(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_SAVE_DELAYED_MEMORY",
            ],
        )

        first = stream_filter.filter(
            "<APPEND_DELAYED_MEMORY: h"
        )
        second = stream_filter.filter(
            "0qa49>"
        )

        self.assertEqual(
            first.text,
            "",
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
            (
                RuntimeActionCall(
                    name="APPEND_DELAYED_MEMORY",
                    payload="h0qa49",
                ),
            ),
        )

    def test_stream_filter_holds_split_internal_delayed_memory_action_marker(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_SAVE_DELAYED_MEMORY",
            ],
        )

        first = stream_filter.filter(
            "<INTERNAL_ACTION_REMOVE_DELAYED_MEMORY: k"
        )
        second = stream_filter.filter(
            "dhpjo>\nRemoved it from the session."
        )

        self.assertEqual(
            first.text,
            "",
        )
        self.assertEqual(
            first.actions,
            (),
        )
        self.assertEqual(
            second.text,
            "Removed it from the session.",
        )
        self.assertEqual(
            second.actions,
            (
                RuntimeActionCall(
                    name="REMOVE_DELAYED_MEMORY",
                    payload="kdhpjo",
                ),
            ),
        )

    def test_stream_filter_holds_split_delayed_memory_block(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_SAVE_DELAYED_MEMORY",
            ],
        )

        first = stream_filter.filter(
            (
                "<INTERNAL_ACTION_SAVE_DELAYED_MEMORY_CONTENT>\n"
                "title: Radius"
            )
        )
        second = stream_filter.filter(
            (
                " of Influence Specs\n"
                "summary: Summary\n"
                "tags: a, b\n"
                "body:\n"
                "Body\n"
                "</INTERNAL_ACTION_SAVE_DELAYED_MEMORY_CONTENT>\n"
                "Saved."
            )
        )

        self.assertEqual(
            first.text,
            "",
        )
        self.assertEqual(
            first.actions,
            (),
        )
        self.assertEqual(
            second.text,
            "Saved.",
        )
        self.assertEqual(
            second.count("SAVE_DELAYED_MEMORY_CONTENT"),
            1,
        )

    def test_dedupes_duplicate_runtime_action_markers_by_payload(self):

        cases = (
            (
                (
                    "Before "
                    "<INTERNAL_ACTION_CREATE_ACTIVE_MEMORY: Remind to drink coffee>"
                    " middle "
                    "<INTERNAL_ACTION_CREATE_ACTIVE_MEMORY: Remind to drink coffee>"
                    " after"
                ),
                [
                    "CAN_SAVE_ACTIVE_MEMORY",
                ],
                (
                    RuntimeActionCall(
                        name="CREATE_ACTIVE_MEMORY",
                        payload="Remind to drink coffee",
                    ),
                ),
                "Before  middle  after",
            ),
            (
                (
                    "Before "
                    "<INTERNAL_ACTION_SAVE_SESSION>"
                    " middle "
                    "<INTERNAL_ACTION_SAVE_SESSION>"
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
                "Before  middle  after",
            ),
            (
                (
                    "Before\n"
                    "INTERNAL_ACTION_CREATE_ACTIVE_MEMORY: Remind to drink coffee\n"
                    "INTERNAL_ACTION_CREATE_ACTIVE_MEMORY: Remind to drink coffee\n"
                    "After"
                ),
                [
                    "CAN_SAVE_ACTIVE_MEMORY",
                ],
                (
                    RuntimeActionCall(
                        name="CREATE_ACTIVE_MEMORY",
                        payload="Remind to drink coffee",
                    ),
                ),
                "Before\nAfter",
            ),
            (
                (
                    "Before\n"
                    "INTERNAL_ACTION_SAVE_SESSION\n"
                    "INTERNAL_ACTION_SAVE_SESSION\n"
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

    def test_extracts_bare_create_active_memory_marker_line(self):

        result = extract_runtime_actions(
            (
                "Я напомню.\n\n"
                "INTERNAL_ACTION_CREATE_ACTIVE_MEMORY: "
                "REMINDER: Drink coffee in 5 minutes\n"
            ),
            enabled_actions=[
                "CAN_SAVE_ACTIVE_MEMORY",
            ],
        )

        self.assertEqual(
            result.text,
            "Я напомню.\n",
        )
        self.assertEqual(
            result.count("CREATE_ACTIVE_MEMORY"),
            1,
        )
        self.assertEqual(
            result.actions[0].payload,
            "REMINDER: Drink coffee in 5 minutes",
        )

    def test_create_active_memory_marker_helpers_accept_bare_marker(self):

        marker = "INTERNAL_ACTION_CREATE_ACTIVE_MEMORY: PURPOSE | CONDITIONS"

        self.assertEqual(
            get_create_active_memory_marker_fields(
                marker
            ),
            (
                "purpose",
                "conditions",
            ),
        )
        self.assertEqual(
            get_create_active_memory_placeholder_payload(
                marker
            ),
            "PURPOSE | CONDITIONS",
        )

    def test_extracts_bare_resolve_active_memory_marker(self):

        result = extract_runtime_actions(
            (
                "INTERNAL_ACTION_RESOLVE_ACTIVE_MEMORY: "
                "active_memory_id=e2qxe7 STATUS=resolved\n"
                "\n"
                "Память очищена."
            ),
            enabled_actions=[
                "CAN_SAVE_ACTIVE_MEMORY",
            ],
        )

        self.assertEqual(
            result.text,
            "Память очищена.",
        )
        self.assertEqual(
            result.count("RESOLVE_ACTIVE_MEMORY"),
            1,
        )
        self.assertEqual(
            result.actions[0].payload,
            "active_memory_id=e2qxe7 STATUS=resolved",
        )

    def test_extracts_bracketed_resolve_active_memory_marker(self):

        result = extract_runtime_actions(
            (
                "before "
                "<INTERNAL_ACTION_RESOLVE_ACTIVE_MEMORY:e2qxe7 | resolved>"
                " after"
            ),
            enabled_actions=[
                "CAN_SAVE_ACTIVE_MEMORY",
            ],
        )

        self.assertEqual(
            result.text,
            "before  after",
        )
        self.assertEqual(
            result.count("RESOLVE_ACTIVE_MEMORY"),
            1,
        )
        self.assertEqual(
            result.actions[0].payload,
            "e2qxe7 | resolved",
        )

    def test_extract_active_memory_resolve_slot_id_accepts_loose_payload_shape(self):

        self.assertEqual(
            extract_active_memory_resolve_slot_id(
                "active_memory_id: 5fdg4g",
            ),
            "5fdg4g",
        )
        self.assertEqual(
            extract_active_memory_resolve_slot_id(
                "resolve slot 5fdg4g please",
                existing_ids={
                    "5fdg4g",
                },
            ),
            "5fdg4g",
        )

    def test_extract_active_memory_resolve_slot_id_skips_non_existing_tokens(self):

        self.assertEqual(
            extract_active_memory_resolve_slot_id(
                "active_memory_id | STATUS",
                existing_ids={
                    "5fdg4g",
                },
            ),
            "",
        )
        self.assertEqual(
            extract_active_memory_resolve_slot_id(
                "resolve status abc123",
                existing_ids={
                    "5fdg4g",
                },
            ),
            "",
        )

    def test_ignores_placeholder_create_active_memory_marker(self):

        with patch.object(
            runtime_rules,
            "INTERNAL_ACTIONS_WITH_PAYLOAD",
            [
                "<INTERNAL_ACTION_CREATE_ACTIVE_MEMORY: DETAILS | PURPOSE | VALUE >",
            ],
        ):
            result = extract_runtime_actions(
                "<INTERNAL_ACTION_CREATE_ACTIVE_MEMORY: details|purpose|value >",
                enabled_actions=[
                    "CAN_SAVE_ACTIVE_MEMORY",
                ],
            )

        self.assertEqual(
            result.text,
            "",
        )
        self.assertEqual(
            result.count("CREATE_ACTIVE_MEMORY"),
            0,
        )

    def test_ignores_placeholder_from_all_payload_marker_bodies(self):

        with patch.object(
            runtime_rules,
            "INTERNAL_ACTIONS_WITH_PAYLOAD",
            [
                "<INTERNAL_ACTION_WEB_SEARCH: plain text query >",
                "<INTERNAL_ACTION_RESOLVE_ACTIVE_MEMORY: active_memory_id | STATUS >",
            ],
        ):
            search_result = extract_runtime_actions(
                "<INTERNAL_ACTION_WEB_SEARCH:<plain text query>>",
                enabled_actions=[
                    "CAN_WEB_SEARCH",
                ],
            )
            memory_result = extract_runtime_actions(
                "<INTERNAL_ACTION_CREATE_ACTIVE_MEMORY: active_memory_id|status>",
                enabled_actions=[
                    "CAN_SAVE_ACTIVE_MEMORY",
                ],
            )

        self.assertEqual(
            search_result.count("WEB_SEARCH"),
            0,
        )
        self.assertEqual(
            memory_result.count("CREATE_ACTIVE_MEMORY"),
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
                runtime_rules.RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
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
            "visible answer\n\n",
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
                    name=runtime_rules.RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
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
            "<INTERNAL_ACTION_WEB_SEARCH:\u0441\u0438"
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

    def test_stream_filter_handles_split_append_skill_marker_with_name_attribute(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_USE_ASSETS",
            ],
        )

        first = stream_filter.filter(
            '<INTERNAL_ACTION_APPEND_SKILL name="file'
        )
        second = stream_filter.filter(
            '_manager" />'
        )

        self.assertEqual(
            first.text,
            "",
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
            (
                RuntimeActionCall(
                    name="APPEND_SKILL",
                    payload="file_manager",
                ),
            ),
        )
        self.assertEqual(
            stream_filter.flush(),
            "",
        )

    def test_stream_filter_handles_split_plural_append_skill_marker(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_USE_ASSETS",
            ],
        )

        first = stream_filter.filter(
            "<INTERNAL_ACTION_APPEND_SKILLS: file_manager,"
        )
        second = stream_filter.filter(
            " image_prompt_generator, porn, wildcards>"
        )

        self.assertEqual(
            first.text,
            "",
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
            (
                RuntimeActionCall(
                    name="APPEND_SKILL",
                    payload="file_manager",
                ),
                RuntimeActionCall(
                    name="APPEND_SKILL",
                    payload="image_prompt_generator",
                ),
                RuntimeActionCall(
                    name="APPEND_SKILL",
                    payload="porn",
                ),
                RuntimeActionCall(
                    name="APPEND_SKILL",
                    payload="wildcards",
                ),
            ),
        )
        self.assertEqual(
            stream_filter.flush(),
            "",
        )

    def test_stream_filter_handles_split_bracketed_web_search_marker_terminated_by_newline(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
        )

        first = stream_filter.filter(
            "<INTERNAL_ACTION_WEB_SEARCH: house"
        )
        second = stream_filter.filter(
            " drawing ideas\n\n🏠\n\nМаленький уютный домик"
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
            "🏠\n\nМаленький уютный домик",
        )
        self.assertEqual(
            second.search_queries,
            (
                "house drawing ideas",
            ),
        )
        self.assertEqual(
            stream_filter.flush(),
            "",
        )

    def test_stream_filter_handles_split_tool_call_style_web_search_marker(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
        )

        first = stream_filter.filter(
            "<|tool"
        )
        second = stream_filter.filter(
            "_call>call:INTERNAL_ACTION_WEB_SEARCH: blue"
        )
        final = stream_filter.filter(
            " tomato>"
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
            second.count("WEB_SEARCH"),
            0,
        )
        self.assertEqual(
            final.text,
            "",
        )
        self.assertEqual(
            final.search_queries,
            (
                "blue tomato",
            ),
        )
        self.assertEqual(
            stream_filter.flush(),
            "",
        )

    def test_stream_filter_handles_split_tool_call_style_web_search_without_internal_prefix(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
        )

        first = stream_filter.filter(
            "<tool"
        )
        second = stream_filter.filter(
            "_call>call:WEB_SEARCH: blue"
        )
        final = stream_filter.filter(
            " tomato>"
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
            second.count("WEB_SEARCH"),
            0,
        )
        self.assertEqual(
            final.text,
            "",
        )
        self.assertEqual(
            final.search_queries,
            (
                "blue tomato",
            ),
        )
        self.assertEqual(
            stream_filter.flush(),
            "",
        )

    def test_stream_filter_flush_extracts_unclosed_tool_call_style_web_search_without_internal_prefix(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
        )

        result = stream_filter.filter(
            "<tool_call>call:WEB_SEARCH: blue tomato"
        )
        flushed = stream_filter.flush_result()

        self.assertEqual(
            result.text,
            "",
        )
        self.assertEqual(
            result.count("WEB_SEARCH"),
            0,
        )
        self.assertEqual(
            flushed.text,
            "",
        )
        self.assertEqual(
            flushed.search_queries,
            (
                "blue tomato",
            ),
        )

    def test_stream_filter_handles_split_bare_call_style_web_search_marker(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
        )

        first = stream_filter.filter(
            "call:"
        )
        second = stream_filter.filter(
            "INTERNAL_ACTION_WEB_SEARCH: blue tomato\n"
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
                "blue tomato",
            ),
        )
        self.assertEqual(
            stream_filter.flush(),
            "",
        )

    def test_stream_filter_preserves_thinking_marker_text_when_requested(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
            preserve_action_text=True,
        )

        result = stream_filter.filter(
            "Need search. <INTERNAL_ACTION_WEB_SEARCH:\u0441\u0438\u043d\u0438\u0439 \u043f\u043e\u043c\u0438\u0434\u043e\u0440>"
        )

        self.assertEqual(
            result.text,
            "Need search. <INTERNAL_ACTION_WEB_SEARCH:\u0441\u0438\u043d\u0438\u0439 \u043f\u043e\u043c\u0438\u0434\u043e\u0440>",
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
            "hello <INTERNAL_ACTION_WEB_SEARCH:??"
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
            "<INTERNAL_ACTION_WEB_SEARCH:"
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
            "quoted <INTERNAL_ACTION_SAVE_SESSION"
        )
        second = stream_filter.filter(
            "> marker"
        )

        self.assertEqual(
            first.text,
            "quoted <INTERNAL_ACTION_SAVE_SESSION",
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

    def test_stream_filter_handles_short_end_tag_closed_active_memory_marker(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_SAVE_ACTIVE_MEMORY",
            ],
        )

        first = stream_filter.filter(
            "<INTERNAL_ACTION_CREATE_ACTIVE_MEMORY: remember"
        )
        middle = stream_filter.filter(
            " the word coffee and ask for a guess later.</"
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
            final.actions,
            (
                RuntimeActionCall(
                    name="CREATE_ACTIVE_MEMORY",
                    payload=(
                        "remember the word coffee "
                        "and ask for a guess later."
                    ),
                ),
            ),
        )
        self.assertEqual(
            stream_filter.flush(),
            "",
        )

    def test_stream_filter_executes_consecutive_markers_across_all_chunk_boundaries(self):

        marker_text = (
            "<WEB_SEARCH: latest breakthroughs in fusion energy 2026>\n"
            "<CREATE_ACTIVE_MEMORY: experiment_start_time: "
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
                name="CREATE_ACTIVE_MEMORY",
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

    def test_stream_filter_handles_split_bare_create_active_memory_marker(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_SAVE_ACTIVE_MEMORY",
            ],
        )

        first = stream_filter.filter(
            "INTERNAL_ACTION_CREATE_ACTIVE_MEMORY:"
        )
        second = stream_filter.filter(
            " REMINDER: Drink coffee in 5 minutes\n"
        )

        self.assertEqual(
            first.text,
            "",
        )
        self.assertEqual(
            first.count("CREATE_ACTIVE_MEMORY"),
            0,
        )
        self.assertEqual(
            second.text,
            "",
        )
        self.assertEqual(
            second.count("CREATE_ACTIVE_MEMORY"),
            1,
        )
        self.assertEqual(
            second.actions[0].payload,
            "REMINDER: Drink coffee in 5 minutes",
        )

    def test_stream_filter_dedupes_duplicate_markers_across_chunks(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_SAVE_ACTIVE_MEMORY",
            ],
        )

        first = stream_filter.filter(
            "<INTERNAL_ACTION_CREATE_ACTIVE_MEMORY: Remind to drink coffee>"
        )
        second = stream_filter.filter(
            "<INTERNAL_ACTION_CREATE_ACTIVE_MEMORY: Remind to drink coffee>"
        )

        self.assertEqual(
            first.text,
            "",
        )
        self.assertEqual(
            first.actions,
            (
                RuntimeActionCall(
                    name="CREATE_ACTIVE_MEMORY",
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

    def test_duplicate_append_skill_markers_are_preserved_as_text(self):

        appended_skill_names = set()

        def preserve_duplicate_append_skill(_raw_marker, action):
            if action.name != "APPEND_SKILL":
                return False

            requested_skill = normalize_skill_name(
                action.payload
            )

            if requested_skill in appended_skill_names:
                return True

            appended_skill_names.add(
                requested_skill
            )
            return False

        text = (
            "<INTERNAL_ACTION_SAVE_SESSION>\n"
            "<INTERNAL_ACTION_APPEND_SKILL: file_manager >\n"
            "<INTERNAL_ACTION_APPEND_SKILL: image_prompt_generator >\n"
            "<INTERNAL_ACTION_APPEND_SKILL: wildcards >\n"
            "<INTERNAL_ACTION_APPEND_SKILL: porn >\n"
            "<INTERNAL_ACTION_APPEND_SKILL: file_manager >\n"
            "<INTERNAL_ACTION_APPEND_SKILL: image_prompt_generator >"
        )

        result = extract_runtime_actions(
            text,
            enabled_actions=[
                "CAN_SAVE_SESSION",
                "CAN_USE_ASSETS",
            ],
            preserve_action_marker=preserve_duplicate_append_skill,
        )

        self.assertEqual(
            result.actions,
            (
                RuntimeActionCall(
                    name="SAVE_SESSION",
                ),
                RuntimeActionCall(
                    name="APPEND_SKILL",
                    payload="file_manager",
                ),
                RuntimeActionCall(
                    name="APPEND_SKILL",
                    payload="image_prompt_generator",
                ),
                RuntimeActionCall(
                    name="APPEND_SKILL",
                    payload="wildcards",
                ),
                RuntimeActionCall(
                    name="APPEND_SKILL",
                    payload="porn",
                ),
            ),
        )
        self.assertIn(
            "<INTERNAL_ACTION_APPEND_SKILL: file_manager >",
            result.text,
        )
        self.assertIn(
            "<INTERNAL_ACTION_APPEND_SKILL: image_prompt_generator >",
            result.text,
        )
        self.assertNotIn(
            "<INTERNAL_ACTION_APPEND_SKILL: wildcards >",
            result.text,
        )
        self.assertEqual(
            len(result.removed_markers),
            5,
        )

    def test_placeholder_append_skill_is_processed_once_and_duplicate_preserved(self):

        appended_skill_names = set()

        def preserve_duplicate_append_skill(_raw_marker, action):
            if action.name != "APPEND_SKILL":
                return False

            requested_skill = normalize_skill_name(
                action.payload
            )

            if requested_skill in appended_skill_names:
                return True

            appended_skill_names.add(
                requested_skill
            )
            return False

        result = extract_runtime_actions(
            (
                "<INTERNAL_ACTION_APPEND_SKILL: name of skill >\n"
                "<INTERNAL_ACTION_APPEND_SKILL: name of skill >"
            ),
            enabled_actions=[
                "CAN_USE_ASSETS",
            ],
            preserve_action_marker=preserve_duplicate_append_skill,
        )

        self.assertEqual(
            result.actions,
            (
                RuntimeActionCall(
                    name="APPEND_SKILL",
                    payload="name of skill",
                ),
            ),
        )
        self.assertIn(
            "<INTERNAL_ACTION_APPEND_SKILL: name of skill >",
            result.text,
        )
        self.assertEqual(
            len(result.removed_markers),
            1,
        )

    def test_marker_repetition_guard_flags_consecutive_repeats(self):

        repetition_guard = RuntimeActionRepetitionGuard(
            max_consecutive=3,
            max_per_message=5,
        )
        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_USE_ASSETS",
            ],
            repetition_guard=repetition_guard,
        )

        result = stream_filter.filter(
            "<INTERNAL_ACTION_APPEND_SKILL: wildcards>\n"
            "<INTERNAL_ACTION_APPEND_SKILL: wildcards>\n"
            "<INTERNAL_ACTION_APPEND_SKILL: wildcards>\n"
            "<INTERNAL_ACTION_APPEND_SKILL: wildcards>"
        )

        self.assertTrue(
            result.marker_repetition_exceeded,
        )
        self.assertIn(
            "in a row",
            result.marker_repetition_reason,
        )

    def test_marker_repetition_guard_flags_message_repeats(self):

        repetition_guard = RuntimeActionRepetitionGuard(
            max_consecutive=3,
            max_per_message=5,
        )
        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_USE_ASSETS",
            ],
            repetition_guard=repetition_guard,
        )

        result = stream_filter.filter(
            "<INTERNAL_ACTION_APPEND_SKILL: file_manager>\n"
            "<INTERNAL_ACTION_APPEND_SKILL: wildcards>\n"
            "<INTERNAL_ACTION_APPEND_SKILL: file_manager>\n"
            "<INTERNAL_ACTION_APPEND_SKILL: wildcards>\n"
            "<INTERNAL_ACTION_APPEND_SKILL: file_manager>\n"
            "<INTERNAL_ACTION_APPEND_SKILL: wildcards>\n"
            "<INTERNAL_ACTION_APPEND_SKILL: file_manager>\n"
            "<INTERNAL_ACTION_APPEND_SKILL: wildcards>\n"
            "<INTERNAL_ACTION_APPEND_SKILL: file_manager>\n"
            "<INTERNAL_ACTION_APPEND_SKILL: wildcards>\n"
            "<INTERNAL_ACTION_APPEND_SKILL: file_manager>"
        )

        self.assertTrue(
            result.marker_repetition_exceeded,
        )
        self.assertIn(
            "one message",
            result.marker_repetition_reason,
        )

    def test_apply_runtime_action_calls_stores_search_queries(self):

        class Context:
            pass

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

        class Context:
            pass

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

    def test_apply_runtime_action_calls_uses_one_search_query(self):

        class Context:
            pass

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
            1,
        )
        self.assertEqual(
            getattr(
                context,
                "runtime_search_queries",
            ),
            [
                "first",
            ],
        )

    def test_bracketed_save_session_marker_allowed_by_save_request(self):

        class Context:
            pass

        context = Context()
        result = extract_runtime_actions(
            "<INTERNAL_ACTION_SAVE_SESSION>",
            enabled_actions=[
                "CAN_SAVE_SESSION",
            ],
        )

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                result.actions,
                user_message="\u0441\u043e\u0445\u0440\u0430\u043d\u0438 \u0441\u0435\u0441\u0441\u0438\u044e",
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

        class Context:
            pass

        context = Context()
        context.runtime_save_session_memory_committed_this_turn = True
        result = extract_runtime_actions(
            "<INTERNAL_ACTION_SAVE_SESSION>",
            enabled_actions=[
                "CAN_SAVE_SESSION",
            ],
        )

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                result.actions,
                user_message="сохрани сессию",
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

    def test_bracketed_save_session_marker_allowed_by_bedtime_pause(self):

        class Context:
            pass

        context = Context()
        result = extract_runtime_actions(
            "<INTERNAL_ACTION_SAVE_SESSION>",
            enabled_actions=[
                "CAN_SAVE_SESSION",
            ],
        )

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                result.actions,
                user_message="ладно, я спать, до завтра!",
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

        class Context:
            pass

        context = Context()
        result = extract_runtime_actions(
            "<INTERNAL_ACTION_SAVE_SESSION>",
            enabled_actions=[
                "CAN_SAVE_SESSION",
            ],
        )

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                result.actions,
                user_message="\u043d\u0430\u043f\u0438\u0448\u0438 \u043f\u043e\u043b\u043d\u044b\u0439 \u0442\u0435\u0433 \u0441\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u0438\u044f \u0441\u0435\u0441\u0441\u0438\u0438",
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
            getattr(
                context,
                "runtime_save_session_requested",
                False,
            )
        )

    def test_save_session_guard_intents(self):

        self.assertTrue(
            should_execute_save_session(
                "\u0441\u043e\u0445\u0440\u0430\u043d\u0438 \u0441\u0435\u0441\u0441\u0438\u044e"
            )
        )
        self.assertTrue(
            should_execute_save_session(
                "\u0437\u0430\u043a\u043e\u043d\u0447\u0438\u043c"
            )
        )
        self.assertTrue(
            should_execute_save_session(
                "\u043b\u0430\u0434\u043d\u043e, \u044f \u0441\u043f\u0430\u0442\u044c, \u0434\u043e \u0437\u0430\u0432\u0442\u0440\u0430!"
            )
        )
        self.assertFalse(
            should_execute_save_session(
                "\u043d\u0430\u043f\u0438\u0448\u0438 \u043f\u043e\u043b\u043d\u044b\u0439 \u0442\u0435\u0433 \u0441\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u0438\u044f \u0441\u0435\u0441\u0441\u0438\u0438"
            )
        )
        self.assertFalse(
            should_execute_save_session(
                "\u043f\u043e\u043a\u0430\u0436\u0438 \u0442\u043e\u0447\u043d\u044b\u0439 \u0442\u0435\u0433 \u0434\u043b\u044f \u0441\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u0438\u044f \u0441\u0435\u0441\u0441\u0438\u0438"
            )
        )
        self.assertFalse(
            should_execute_save_session(
                "\u043f\u0440\u0438\u043c\u0435\u0440 \u0442\u0435\u0433\u0430"
            )
        )
        self.assertFalse(
            should_execute_save_session(
                "\u0437\u0430\u0431\u0443\u0434\u044c \u043f\u0440\u043e\u0448\u043b\u043e\u0435, \u0441\u043c\u0435\u043d\u0438\u043c \u0442\u0435\u043c\u0443"
            )
        )
        self.assertFalse(
            should_execute_save_session(
                "\u0445\u043e\u0440\u043e\u0448\u043e, \u044f \u0441\u043e\u0445\u0440\u0430\u043d\u0438\u043b, \u0441\u043f\u0430\u0441\u0438\u0431\u043e"
            )
        )

    def test_apply_runtime_action_calls_records_create_active_memory(self):

        class Context:
            pass

        context = Context()

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="CREATE_ACTIVE_MEMORY",
                        payload="remind later",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            1,
        )
        self.assertEqual(
            context.runtime_action_events,
            [
                {
                    "name": "create_active_memory",
                    "payload": "remind later",
                }
            ],
        )

    def test_apply_runtime_action_calls_lists_skills(self):

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                self.write_skill_fixture(
                    root,
                    "wildcards.txt",
                    "wildcards\nUse ASSET_ACTION for wildcard files.",
                )
                self.write_skill_fixture(
                    root,
                    "file_manager.txt",
                    "file_manager\nUse ASSET_ACTION for asset files.",
                )

                context = Context()
                context.emitter = Emitter()

                applied_count = asyncio.run(
                    apply_runtime_action_calls(
                        context,
                        (
                            RuntimeActionCall(
                                name="LIST_SKILLS",
                                payload="",
                            ),
                        ),
                    )
                )

                self.assertEqual(
                    applied_count,
                    1,
                )
                self.assertEqual(
                    context.runtime_asset_results[0]["action"],
                    "list_skills",
                )
                self.assertEqual(
                    context.runtime_asset_results[0]["requested"],
                    "",
                )
                self.assertIs(
                    context.runtime_visible_skills_result,
                    context.runtime_asset_results[0],
                )
                skills_by_name = {
                    skill["name"]: skill
                    for skill in context.runtime_asset_results[0]["skills"]
                }
                self.assertIn(
                    "wildcards",
                    skills_by_name,
                )
                self.assertIn(
                    "file_manager",
                    skills_by_name,
                )
                self.assertNotIn(
                    "content",
                    skills_by_name["wildcards"],
                )
                self.assertTrue(
                    (root / "assets" / "skills" / "wildcards.txt").exists()
                )
                self.assertTrue(
                    (root / "assets" / "skills" / "file_manager.txt").exists()
                )
                self.assertEqual(
                    context.emitter.events[0]["action"],
                    "list_skills",
                )
                self.assertEqual(
                    context.emitter.events[0]["text"],
                    "Listed skills",
                )
                self.assertEqual(
                    context.runtime_session_action_history[0]["text"],
                    "Listed skills",
                )
                self.assertIsInstance(
                    context.runtime_session_action_history[0]["created_at"],
                    float,
                )

    def test_apply_runtime_action_calls_hides_only_listed_skills(self):

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        listed_skills = {
            "ok": True,
            "action": "list_skills",
            "skills": [
                {
                    "name": "file_manager",
                    "path": "assets/skills/file_manager.txt",
                },
            ],
        }
        appended_skill = {
            "name": "file_manager",
            "path": "assets/skills/file_manager.txt",
            "content": "Use ASSET_ACTION for files.",
        }
        context = Context()
        context.emitter = Emitter()
        context.runtime_visible_skills_result = listed_skills
        context.runtime_asset_results = [
            listed_skills,
            {
                "ok": True,
                "action": "read_asset_text",
            },
        ]
        context.runtime_appended_skills = [
            appended_skill,
        ]

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="HIDE_SKILLS",
                        payload="",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            1,
        )
        self.assertEqual(
            context.runtime_visible_skills_result,
            {},
        )
        self.assertEqual(
            context.runtime_asset_results,
            [
                {
                    "ok": True,
                    "action": "read_asset_text",
                },
            ],
        )
        self.assertEqual(
            context.runtime_appended_skills,
            [
                appended_skill,
            ],
        )
        self.assertEqual(
            context.runtime_action_events[-1]["name"],
            "hide_skills",
        )
        self.assertEqual(
            context.runtime_session_action_history[-1]["text"],
            "Hidden skills list",
        )

    def test_apply_runtime_action_calls_reads_list_skills_each_time(self):

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                self.write_skill_fixture(
                    root,
                    "file_manager.txt",
                    "file_manager\nUse ASSET_ACTION for asset files.",
                )

                context = Context()
                context.emitter = Emitter()
                context.runtime_current_turn_id = "turn_000001"

                asyncio.run(
                    apply_runtime_action_calls(
                        context,
                        (
                            RuntimeActionCall(
                                name="LIST_SKILLS",
                                payload="",
                            ),
                        ),
                    )
                )

                context.runtime_current_turn_id = "turn_000002"

                asyncio.run(
                    apply_runtime_action_calls(
                        context,
                        (
                            RuntimeActionCall(
                                name="LIST_SKILLS",
                                payload="",
                            ),
                        ),
                    )
                )

                self.assertEqual(
                    len(context.runtime_asset_results),
                    2,
                )
                self.assertNotIn(
                    "runtime_action_reused",
                    context.runtime_asset_results[0],
                )
                self.assertNotIn(
                    "runtime_action_reused",
                    context.runtime_asset_results[1],
                )
                self.assertEqual(
                    context.runtime_asset_results[1][
                        "runtime_turn_id"
                    ],
                    "turn_000002",
                )

    def test_apply_runtime_action_calls_appends_and_removes_skill(self):

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                skill_path = (
                    root
                    / "assets"
                    / "skills"
                    / "Image Prompt Generator.txt"
                )
                skill_path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )
                skill_path.write_text(
                    "image_prompt_generator\nDescribe images.",
                    encoding="utf-8",
                )

                context = Context()
                context.emitter = Emitter()

                applied_count = asyncio.run(
                    apply_runtime_action_calls(
                        context,
                        (
                            RuntimeActionCall(
                                name="APPEND_SKILL",
                                payload="Image Prompt Generator.txt",
                            ),
                            RuntimeActionCall(
                                name="REMOVE_SKILL",
                                payload="wildcards",
                            ),
                        ),
                    )
                )

                self.assertEqual(
                    applied_count,
                    2,
                )
                self.assertEqual(
                    context.runtime_appended_skills[0]["name"],
                    "image_prompt_generator",
                )
                self.assertEqual(
                    context.runtime_appended_skills[0]["path"],
                    "assets/skills/Image Prompt Generator.txt",
                )
                self.assertIn(
                    "Describe images.",
                    context.runtime_appended_skills[0]["content"],
                )
                self.assertEqual(
                    context.emitter.events[0]["action"],
                    "append_skill",
                )
                self.assertEqual(
                    context.emitter.events[0]["text"],
                    "Appended skill: image_prompt_generator",
                )
                self.assertEqual(
                    context.emitter.events[2]["action"],
                    "remove_skill",
                )
                self.assertEqual(
                    context.emitter.events[2]["text"],
                    "Removed skill: wildcards",
                )

    def test_append_missing_skill_records_error_for_model_and_history(self):

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                self.write_skill_fixture(
                    root,
                    "wildcards.txt",
                    "wildcards\nUse ASSET_ACTION for wildcard files.",
                )
                self.write_skill_fixture(
                    root,
                    "file_manager.txt",
                    "file_manager\nUse ASSET_ACTION for asset files.",
                )

                context = Context()
                context.emitter = Emitter()

                applied_count = asyncio.run(
                    apply_runtime_action_calls(
                        context,
                        (
                            RuntimeActionCall(
                                name="APPEND_SKILL",
                                payload="file_writer",
                            ),
                        ),
                    )
                )

                self.assertEqual(
                    applied_count,
                    1,
                )
                self.assertEqual(
                    context.runtime_appended_skills,
                    [],
                )
                self.assertEqual(
                    context.runtime_asset_results[0]["action"],
                    "append_skill",
                )
                self.assertEqual(
                    context.runtime_asset_results[0]["requested"],
                    "file_writer",
                )
                self.assertEqual(
                    context.runtime_asset_results[0]["error"],
                    "skill_not_found",
                )
                self.assertEqual(
                    context.runtime_session_action_history[0]["text"],
                    "Appended skill: file_writer ( does not exist )",
                )
                self.assertEqual(
                    len(context.emitter.events),
                    1,
                )
                self.assertEqual(
                    context.emitter.events[0]["text"],
                    "Appended skill: file_writer ( does not exist )",
                )
                self.assertEqual(
                    context.emitter.events[0]["status"],
                    "failed",
                )

    def test_append_skill_blocks_other_actions_in_same_stream(self):

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                skill_path = (
                    root
                    / "assets"
                    / "skills"
                    / "wildcards.txt"
                )
                skill_path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )
                skill_path.write_text(
                    "wildcards\nUse ASSET_ACTION for wildcard files.",
                    encoding="utf-8",
                )

                context = Context()
                context.emitter = Emitter()
                payload = json.dumps(
                    {
                        "action": "create_wildcard_file",
                        "path": "clothing/test_tops",
                        "lines": [
                            "linen shirt",
                        ],
                    }
                )

                applied_count = asyncio.run(
                    apply_runtime_action_calls(
                        context,
                        (
                            RuntimeActionCall(
                                name="APPEND_SKILL",
                                payload="wildcards",
                            ),
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
                self.assertEqual(
                    context.runtime_appended_skills[0]["name"],
                    "wildcards",
                )
                self.assertTrue(
                    context.runtime_skill_state_barrier_active,
                )
                self.assertEqual(
                    [
                        event["name"]
                        for event in context.runtime_action_events
                    ],
                    [
                        "append_skill",
                    ],
                )
                self.assertFalse(
                    hasattr(
                        context,
                        "runtime_asset_results",
                    )
                )
                self.assertFalse(
                    (
                        root
                        / "assets"
                        / "wildcards"
                        / "clothing"
                        / "test_tops.txt"
                    ).exists()
                )

    def test_list_skills_normalizes_name_from_filename(self):

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                skill_path = (
                    root
                    / "assets"
                    / "skills"
                    / "Image Prompt Generator.txt"
                )
                skill_path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )
                skill_path.write_text(
                    "ignored title\nSkill body.",
                    encoding="utf-8",
                )

                result = list_skills()

                names = [
                    skill["name"]
                    for skill in result["skills"]
                ]

                self.assertIn(
                    "image_prompt_generator",
                    names,
                )
                self.assertNotIn(
                    "ignored title",
                    names,
                )

    def test_apply_runtime_action_calls_runs_asset_action(self):

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                context = Context()
                context.emitter = Emitter()
                payload = json.dumps(
                    {
                        "action": "create_wildcard_file",
                        "path": "clothing/test_tops",
                        "lines": [
                            "linen shirt",
                            "wool sweater",
                        ],
                    }
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
                    "linen shirt\nwool sweater\n",
                )
                self.assertEqual(
                    context.runtime_asset_results[0]["line_count"],
                    2,
                )
                self.assertEqual(
                    context.emitter.events[0]["action"],
                    "asset_action",
                )
                self.assertEqual(
                    context.emitter.events[0]["id"],
                    "create_wildcard_file_001",
                )
                self.assertEqual(
                    context.emitter.events[0]["text"],
                    "Created wildcard file",
                )
                self.assertEqual(
                    context.emitter.events[0]["status"],
                    "started",
                )
                self.assertEqual(
                    context.emitter.events[1]["action"],
                    "asset_action",
                )
                self.assertEqual(
                    context.emitter.events[1]["id"],
                    "create_wildcard_file_001",
                )
                self.assertEqual(
                    context.emitter.events[1]["text"],
                    "Created wildcard file - assets/wildcards/clothing/test_tops.txt",
                )
                self.assertEqual(
                    context.emitter.events[1]["status"],
                    "completed",
                )
                self.assertEqual(
                    len(context.emitter.events),
                    2,
                )
                self.assertEqual(
                    context.runtime_session_action_history[0]["text"],
                    "Created wildcard file - assets/wildcards/clothing/test_tops.txt",
                )
                self.assertIsInstance(
                    context.runtime_session_action_history[0]["created_at"],
                    float,
                )


    def test_failed_create_asset_file_preserves_payload_for_retry(self):

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                output_path = (
                    root
                    / "assets"
                    / "outputs"
                    / "gemma.txt"
                )
                output_path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )
                output_path.write_text(
                    "old text\n",
                    encoding="utf-8",
                )

                context = Context()
                context.emitter = Emitter()
                context.runtime_current_turn_id = "turn_000001"
                payload_data = {
                    "action": "create_asset_file",
                    "path": "assets/outputs/gemma.txt",
                    "content": "new text",
                }
                payload = json.dumps(
                    payload_data
                )

                asyncio.run(
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

                result = context.runtime_asset_results[0]
                self.assertFalse(
                    result["ok"],
                )
                self.assertEqual(
                    result["error"],
                    "file_exists",
                )
                self.assertEqual(
                    result["payload"],
                    payload_data,
                )
                self.assertEqual(
                    result["runtime_turn_id"],
                    "turn_000001",
                )
                self.assertEqual(
                    context.runtime_asset_retry_results,
                    [result],
                )
                self.assertIsNot(
                    context.runtime_asset_retry_results[0],
                    result,
                )
                self.assertEqual(
                    output_path.read_text(encoding="utf-8"),
                    "old text\n",
                )

    def test_create_asset_file_emits_started_with_path_before_completed(self):

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                context = Context()
                context.emitter = Emitter()
                payload = json.dumps(
                    {
                        "action": "create_asset_file",
                        "path": "assets/outputs/rain_script.py",
                        "content": "print('rain')",
                    }
                )

                asyncio.run(
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
                    len(context.emitter.events),
                    2,
                )
                self.assertEqual(
                    context.emitter.events[0]["status"],
                    "started",
                )
                self.assertEqual(
                    context.emitter.events[0]["text"],
                    "Created asset file - assets/outputs/rain_script.py",
                )
                self.assertEqual(
                    context.emitter.events[0]["id"],
                    "create_asset_file_001",
                )
                self.assertEqual(
                    context.emitter.events[1]["status"],
                    "completed",
                )
                self.assertEqual(
                    context.emitter.events[1]["id"],
                    "create_asset_file_001",
                )


    def test_asset_action_writes_actual_path_back_to_runtime_todo(self):

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                context = Context()
                context.emitter = Emitter()
                create_runtime_todo(
                    context,
                    "1. Создать новый файл-вайлдкард `assets/wildcards/shoes/` с 10 видами обуви.",
                )

                payload = json.dumps(
                    {
                        "action": "create_wildcard_file",
                        "path": "assets/wildcards/shoes/",
                        "lines": [
                            "sneakers",
                            "boots",
                        ],
                    }
                )

                asyncio.run(
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
                    context.runtime_todo[0]["status"],
                    "resolved",
                )
                self.assertEqual(
                    context.runtime_todo[0]["result_path"],
                    "assets/wildcards/shoes.txt",
                )
                self.assertEqual(
                    context.runtime_asset_results[0]["runtime_todo_item"]["result_path"],
                    "assets/wildcards/shoes.txt",
                )

    def test_apply_runtime_action_calls_runs_asset_action_args_payload(self):

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                context = Context()
                context.emitter = Emitter()
                payload = json.dumps(
                    {
                        "action": "create_wildcard_file",
                        "args": {
                            "path": "clothing/test_tops",
                            "content": "cropped tank top\nlace camisole",
                        },
                    }
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
                    "cropped tank top\nlace camisole\n",
                )

    def test_apply_runtime_action_calls_repairs_backslash_separated_content(self):

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

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

    def test_create_and_append_asset_file_actions_stay_inside_assets(self):

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                create_result = run_asset_action(json.dumps({
                    "action": "create_asset_file",
                    "path": "assets/outputs/test_notes",
                    "content": "first line\nsecond line",
                }))
                append_result = run_asset_action(json.dumps({
                    "action": "append_asset_file",
                    "path": "assets/outputs/test_notes",
                    "content": "third line",
                }))

                output_path = (
                    root
                    / "assets"
                    / "outputs"
                    / "test_notes.txt"
                )

                self.assertTrue(
                    create_result["ok"],
                )
                self.assertEqual(
                    create_result["path"],
                    "assets/outputs/test_notes.txt",
                )
                self.assertTrue(
                    append_result["ok"],
                )
                self.assertEqual(
                    append_result["line_count"],
                    3,
                )
                self.assertEqual(
                    output_path.read_text(encoding="utf-8"),
                    "first line\nsecond line\nthird line\n",
                )

    def test_read_asset_text_preview_returns_attachment_modal_payload(self):

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                run_asset_action(json.dumps({
                    "action": "create_asset_file",
                    "path": "assets/outputs/test_notes",
                    "content": "first line\nsecond line",
                }))

                result = read_asset_text_preview({
                    "path": "assets/outputs/test_notes.txt",
                    "max_chars": 8,
                })

                self.assertTrue(
                    result["ok"],
                )
                self.assertEqual(
                    result["kind"],
                    "text",
                )
                self.assertEqual(
                    result["path"],
                    "assets/outputs/test_notes.txt",
                )
                self.assertEqual(
                    result["text_content"],
                    "first li",
                )
                self.assertTrue(
                    result["truncated"],
                )

    def test_create_asset_file_content_preserves_indentation(self):

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                content = (
                    "def generate_rain_sound():\n"
                    "    print(\"start\")\n"
                    "    if True:\n"
                    "        print(\"nested\")\n"
                    "\n"
                    "if __name__ == \"__main__\":\n"
                    "    generate_rain_sound()\n"
                )
                result = run_asset_action(json.dumps({
                    "action": "create_asset_file",
                    "path": "assets/outputs/rain_script.py",
                    "content": content,
                }))
                output_path = (
                    root
                    / "assets"
                    / "outputs"
                    / "rain_script.py"
                )

                self.assertTrue(
                    result["ok"],
                )
                self.assertEqual(
                    output_path.read_text(encoding="utf-8"),
                    content,
                )
                self.assertEqual(
                    result["examples"][1],
                    "    print(\"start\")",
                )

    def test_append_asset_file_content_preserves_existing_formatting(self):

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                output_path = (
                    root
                    / "assets"
                    / "outputs"
                    / "script.py"
                )
                output_path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )
                output_path.write_text(
                    "def main():\n"
                    "    print(\"before\")",
                    encoding="utf-8",
                )

                result = run_asset_action(json.dumps({
                    "action": "append_asset_file",
                    "path": "assets/outputs/script.py",
                    "content": (
                        "    print(\"after\")\n"
                        "    return True\n"
                    ),
                }))

                self.assertTrue(
                    result["ok"],
                )
                self.assertEqual(
                    output_path.read_text(encoding="utf-8"),
                    (
                        "def main():\n"
                        "    print(\"before\")\n"
                        "    print(\"after\")\n"
                        "    return True\n"
                    ),
                )

    def test_generate_prompt_batch_expands_wildcards_and_accepts_assets_prompts_path(self):

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                run_asset_action(json.dumps({
                    "action": "create_wildcard_file",
                    "path": "clothing/test_tops",
                    "lines": [
                        "linen shirt",
                    ],
                }))
                run_asset_action(json.dumps({
                    "action": "create_wildcard_file",
                    "path": "clothing/test_bottoms",
                    "lines": [
                        "black skirt",
                    ],
                }))

                result = run_asset_action(json.dumps({
                    "action": "generate_prompt_batch",
                    "count": 2,
                    "template": "woman wearing __clothing/test_tops__ and __clothing/test_bottoms__, studio lighting.",
                    "path": "assets/prompts/test_prompts.txt",
                }))

                self.assertTrue(
                    result.get("ok"),
                    result,
                )
                output_path = (
                    root
                    / "assets"
                    / "prompts"
                    / "test_prompts.txt"
                )
                self.assertTrue(
                    output_path.exists(),
                )
                self.assertFalse(
                    (root / "assets" / "prompts" / "assets").exists(),
                )
                self.assertFalse(
                    (root / "assets" / "wildcards" / "assets").exists(),
                )
                content = output_path.read_text(encoding="utf-8")
                self.assertEqual(
                    content,
                    (
                        "woman wearing linen shirt and black skirt, studio lighting.\n"
                        "woman wearing linen shirt and black skirt, studio lighting.\n"
                    ),
                )
                self.assertNotIn(
                    "__clothing/",
                    content,
                )

    def test_generate_prompt_batch_overwrites_existing_prompt_file_by_default(self):

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                run_asset_action(json.dumps({
                    "action": "create_wildcard_file",
                    "path": "clothing/test_tops",
                    "lines": [
                        "linen shirt",
                    ],
                }))

                output_path = (
                    root
                    / "assets"
                    / "prompts"
                    / "test_prompts.txt"
                )
                output_path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )
                output_path.write_text(
                    "old prompt\n",
                    encoding="utf-8",
                )

                result = run_asset_action(json.dumps({
                    "action": "generate_prompt_batch",
                    "count": 1,
                    "template": "woman wearing __clothing/test_tops__",
                    "path": "assets/prompts/test_prompts.txt",
                }))

                self.assertTrue(
                    result.get("ok"),
                    result,
                )
                self.assertEqual(
                    result.get("path"),
                    "assets/prompts/test_prompts.txt",
                )
                self.assertEqual(
                    output_path.read_text(encoding="utf-8"),
                    "woman wearing linen shirt\n",
                )
                self.assertFalse(
                    (
                        root
                        / "assets"
                        / "prompts"
                        / "test_prompts_002.txt"
                    ).exists(),
                )

    def test_generate_prompt_batch_still_accepts_output_file_alias(self):

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                run_asset_action(json.dumps({
                    "action": "create_wildcard_file",
                    "path": "clothing/test_tops",
                    "lines": [
                        "linen shirt",
                    ],
                }))

                result = run_asset_action(json.dumps({
                    "action": "generate_prompt_batch",
                    "count": 1,
                    "template": "woman wearing __clothing/test_tops__",
                    "output_file": "assets/prompts/legacy_prompts.txt",
                }))

                self.assertTrue(
                    result.get("ok"),
                    result,
                )
                self.assertEqual(
                    result.get("path"),
                    "assets/prompts/legacy_prompts.txt",
                )

    def test_generate_prompt_batch_reports_missing_wildcards(self):

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                result = run_asset_action(json.dumps({
                    "action": "generate_prompt_batch",
                    "count": 2,
                    "template": "woman wearing __clothing/missing_tops__",
                    "path": "assets/prompts/test_prompts.txt",
                }))

                self.assertFalse(
                    result.get("ok"),
                )
                self.assertEqual(
                    result.get("error"),
                    "missing_wildcards",
                )
                self.assertEqual(
                    result.get("missing", [])[0].get("wildcard"),
                    "clothing/missing_tops",
                )

    def test_failed_generate_prompt_batch_runtime_bubble_shows_failed(self):

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                context = Context()
                context.emitter = Emitter()
                payload = json.dumps({
                    "action": "generate_prompt_batch",
                    "count": 2,
                    "template": "woman wearing __clothing/missing_tops__",
                    "path": "assets/prompts/test_prompts.txt",
                })

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
                self.assertEqual(
                    context.emitter.events[0]["text"],
                    "Generated prompt batch",
                )
                self.assertEqual(
                    context.emitter.events[0]["status"],
                    "started",
                )
                self.assertEqual(
                    context.emitter.events[1]["text"],
                    "Generated prompt batch - failed",
                )
                self.assertEqual(
                    context.emitter.events[1]["status"],
                    "failed",
                )
                self.assertEqual(
                    len(context.emitter.events),
                    2,
                )
                self.assertEqual(
                    context.runtime_session_action_history[0]["text"],
                    "Generated prompt batch - failed",
                )
                self.assertIsInstance(
                    context.runtime_session_action_history[0]["created_at"],
                    float,
                )

    def test_create_wildcard_file_rejects_assets_prompts_path(self):

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                result = run_asset_action(json.dumps({
                    "action": "create_wildcard_file",
                    "path": "assets/prompts/test_prompts.txt",
                    "lines": [
                        "bad prompt",
                    ],
                }))

                self.assertFalse(
                    result.get("ok"),
                )
                self.assertEqual(
                    result.get("error"),
                    "ValueError",
                )
                self.assertFalse(
                    (root / "assets" / "wildcards" / "assets").exists(),
                )

    def test_apply_runtime_action_calls_saves_delayed_memory_report(self):

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        context = Context()
        context.emitter = Emitter()
        context.session_id = "session-1"
        context.timestamp = "2026-06-29T12:00:00"

        report_payload = json.dumps(
            {
                "radius_of_influence_specs": {
                    "title": "Radius of Influence Specs",
                    "summary": "Three-zone data priority model.",
                    "tags": [
                        "kowloon_sandbox",
                        "simulation",
                    ],
                    "body": "### Radius of Influence Specs\n\nBody",
                    "created_session_id": "",
                    "created_time": "",
                },
            },
            ensure_ascii=False,
        )

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="SAVE_DELAYED_MEMORY_CONTENT",
                        payload=report_payload,
                    ),
                ),
                user_message="please summarize and save this as delayed memory",
            )
        )

        self.assertEqual(
            applied_count,
            1,
        )
        self.assertEqual(
            len(context.delayed_memory_reports),
            1,
        )
        report_id, report = next(
            iter(context.delayed_memory_reports.items())
        )
        self.assertRegex(
            report_id,
            r"^[a-z0-9]{6}$",
        )
        self.assertEqual(
            report["created_session_id"],
            "session-1",
        )
        self.assertEqual(
            report["created_time"],
            "2026-06-29T12:00:00",
        )
        self.assertEqual(
            context.emitter.events,
            [
                {
                    "type": "runtime_action",
                    "action": "save_delayed_memory_content",
                    "id": "save_delayed_memory_content_001",
                    "status": "completed",
                    "text": "Saved delayed memory: Radius of Influence Specs",
                    "delayed_memory_report_id": report_id,
                    "delayed_memory_report": context.delayed_memory_reports,
                },
            ],
        )

        self.assertEqual(
            context.runtime_session_action_history[0]["text"],
            "Delayed memory saved: Radius of Influence Specs",
        )
        self.assertIsInstance(
            context.runtime_session_action_history[0]["created_at"],
            float,
        )

        tool_results = build_tool_results_context(
            context
        )
        self.assertIn(
            '<TOOL_RESULT name="SAVE_DELAYED_MEMORY_CONTENT">',
            tool_results,
        )
        self.assertIn(
            "delayed_memory_reports (Delayed Memory storage)",
            tool_results,
        )
        self.assertIn(
            f'"id": "{report_id}"',
            tool_results,
        )
        self.assertIn(
            "Radius of Influence Specs",
            tool_results,
        )
        self.assertIn(
            "Three-zone data priority model.",
            tool_results,
        )

    def test_rejected_delayed_memory_is_recorded_with_other_turn_actions(self):

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        context = Context()
        context.emitter = Emitter()
        context.timestamp = "2026-07-13T18:00:00"
        context.session_id = "session-1"
        context.turn_number = 1
        context.runtime_current_turn_id = "turn-mixed-memory-save"

        delayed_memory_payload = json.dumps(
            {
                "session_state_snapshot": {
                    "title": "Session State Snapshot",
                    "summary": "Current session state.",
                    "tags": [
                        "session",
                    ],
                    "body": "Full report.",
                },
            },
            ensure_ascii=False,
        )

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="CREATE_ACTIVE_MEMORY",
                        payload="current session state",
                    ),
                    RuntimeActionCall(
                        name="SAVE_DELAYED_MEMORY_CONTENT",
                        payload=delayed_memory_payload,
                    ),
                ),
                user_message="save one state in active memory",
            )
        )

        self.assertEqual(
            applied_count,
            1,
        )
        self.assertEqual(
            [
                event["name"]
                for event in context.runtime_action_events
            ],
            [
                "create_active_memory",
                "save_delayed_memory_content",
            ],
        )
        self.assertEqual(
            context.runtime_action_events[1]["status"],
            "failed",
        )
        self.assertEqual(
            context.runtime_action_events[1]["error"],
            "user_did_not_explicitly_request_report_save",
        )
        self.assertEqual(
            context.runtime_action_events[1]["title"],
            "Session State Snapshot",
        )

        from agent.nodes.brain import (
            format_followup_actions_from_events,
        )

        self.assertEqual(
            format_followup_actions_from_events(
                context.runtime_action_events
            ),
            (
                "create_active_memory, "
                "save_delayed_memory_content"
            ),
        )
        self.assertTrue(
            context.runtime_delayed_memory_save_rejected_pending
        )

    def test_apply_runtime_action_calls_suffixes_duplicate_delayed_memory_key(self):

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        context = Context()
        context.emitter = Emitter()
        context.session_id = "session-1"
        context.timestamp = "2026-06-29T12:00:00"
        context.delayed_memory_reports = {
            "kowloon_sandbox_architecture_contextual_status": {
                "title": "Kowloon Sandbox Architecture & Contextual Status",
                "summary": "Existing report.",
            },
        }

        report_payload = json.dumps(
            {
                "kowloon_sandbox_architecture_contextual_status": {
                    "title": "Kowloon Sandbox Architecture & Contextual Status",
                    "summary": "New report.",
                    "tags": [],
                    "body": "Updated context.",
                    "created_session_id": "",
                    "created_time": "",
                },
            },
            ensure_ascii=False,
        )

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="SAVE_DELAYED_MEMORY_CONTENT",
                        payload=report_payload,
                    ),
                ),
                user_message="please summarize and save this as delayed memory",
            )
        )

        self.assertEqual(
            applied_count,
            1,
        )
        self.assertEqual(
            context.delayed_memory_reports[
                "kowloon_sandbox_architecture_contextual_status"
            ]["summary"],
            "Existing report.",
        )
        new_report_ids = [
            report_id
            for report_id in context.delayed_memory_reports
            if report_id != "kowloon_sandbox_architecture_contextual_status"
        ]
        self.assertEqual(
            len(new_report_ids),
            1,
        )
        self.assertRegex(
            new_report_ids[0],
            r"^[a-z0-9]{6}$",
        )
        self.assertEqual(
            context.delayed_memory_reports[
                new_report_ids[0]
            ]["summary"],
            "New report.",
        )
        self.assertEqual(
            context.emitter.events[0]["delayed_memory_report"],
            {
                new_report_ids[0]: (
                    context.delayed_memory_reports[
                        new_report_ids[0]
                    ]
                ),
            },
        )

    def test_recorded_tool_results_replace_then_append_in_order(self):

        class Context:
            pass

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
                "ok": True,
                "action": "list_delayed_memory",
                "reports": [],
            },
        )

        tool_results = build_tool_results_context(
            context
        )

        self.assertNotIn(
            "old result",
            tool_results,
        )
        self.assertLess(
            tool_results.index("file_manager"),
            tool_results.index("No delayed memory reports saved."),
        )
        self.assertEqual(
            len(context.runtime_tool_results),
            2,
        )

    def test_clean_tool_results_action_clears_all_result_state(self):

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        context = Context()
        context.emitter = Emitter()
        context.runtime_action_events = []
        context.runtime_search_calls = []
        context.runtime_appended_skills = []
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
                "action": "list_delayed_memory",
            },
        ]
        context.runtime_visible_skills_result = {
            "action": "list_skills",
        }

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name=runtime_rules.RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
                    ),
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
            context.runtime_visible_skills_result,
            {},
        )
        self.assertEqual(
            context.runtime_action_events[-1]["name"],
            "clean_tool_results",
        )
        self.assertEqual(
            context.emitter.events[-1]["action"],
            "clean_tool_results",
        )

    def test_append_delayed_memory_uses_appended_context_block(self):

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        context = Context()
        context.emitter = Emitter()
        context.runtime_action_events = []
        context.runtime_search_calls = []
        context.runtime_appended_skills = []
        context.runtime_asset_results = []
        context.delayed_memory_reports = {
            "a1b2c3": {
                "title": "Русский отчёт",
                "summary": "Summary",
                "tags": [
                    "tag",
                ],
                "body": "Body",
            },
            "b2c3d4": {
                "title": "Second report",
                "summary": "Summary",
                "tags": [
                    "tag",
                ],
                "body": "Body",
            },
        }

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="LIST_DELAYED_MEMORY",
                    ),
                    RuntimeActionCall(
                        name="APPEND_DELAYED_MEMORY",
                        payload="a1b2c3",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            2,
        )
        tool_results = build_tool_results_context(
            context
        )
        self.assertIn(
            "<TOOL_RESULTS type='delayed_memory'>",
            tool_results,
        )
        self.assertIn(
            "1. Русский отчёт | id: a1b2c3",
            tool_results,
        )
        self.assertNotIn(
            '<TOOL_RESULT name="APPEND_DELAYED_MEMORY">',
            tool_results,
        )
        self.assertNotIn(
            "<APPENDED_DELAYED_MEMORY>",
            tool_results,
        )
        appended_context = build_appended_delayed_memory_context(
            context
        )
        self.assertIn(
            "<APPENDED_DELAYED_MEMORY>",
            appended_context,
        )
        self.assertIn(
            '"id": "a1b2c3"',
            appended_context,
        )
        self.assertEqual(
            context.emitter.events[0]["text"],
            "Listing delayed memory",
        )
        self.assertEqual(
            context.emitter.events[1]["text"],
            (
                "Appending: "
                + context.delayed_memory_reports[
                    "a1b2c3"
                ]["title"]
            ),
        )
        self.assertEqual(
            len(context.emitter.events),
            2,
        )
        self.assertEqual(
            context.runtime_session_action_history[0]["text"],
            (
                "Delayed memory appended: "
                + context.delayed_memory_reports[
                    "a1b2c3"
                ]["title"]
            ),
        )

    def test_append_delayed_memory_replaces_current_report(self):

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        context = Context()
        context.emitter = Emitter()
        context.runtime_action_events = []
        context.runtime_search_calls = []
        context.runtime_appended_skills = []
        context.runtime_asset_results = []
        context.delayed_memory_reports = {
            "a1b2c3": {
                "title": "First report",
                "summary": "Summary",
                "tags": [
                    "tag",
                ],
                "body": "Body",
            },
            "b2c3d4": {
                "title": "Second report",
                "summary": "Summary",
                "tags": [
                    "tag",
                ],
                "body": "Body",
            },
        }

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="APPEND_DELAYED_MEMORY",
                        payload="a1b2c3",
                    ),
                    RuntimeActionCall(
                        name="APPEND_DELAYED_MEMORY",
                        payload="a1b2c3",
                    ),
                    RuntimeActionCall(
                        name="APPEND_DELAYED_MEMORY",
                        payload="b2c3d4",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            3,
        )
        self.assertEqual(
            context.runtime_appended_delayed_memory["id"],
            "b2c3d4",
        )

        appended_context = build_appended_delayed_memory_context(
            context
        )
        self.assertIn(
            "<APPENDED_DELAYED_MEMORY>",
            appended_context,
        )
        self.assertIn(
            '"title": "Second report"',
            appended_context,
        )
        self.assertNotIn(
            '"title": "First report"',
            appended_context,
        )

        tool_results = build_tool_results_context(
            context
        )
        self.assertNotIn(
            "<TOOL_RESULTS type='delayed_memory'>",
            tool_results,
        )
        self.assertNotIn(
            "<APPENDED_DELAYED_MEMORY>",
            tool_results,
        )
        self.assertEqual(
            [
                item["text"]
                for item in context.runtime_session_action_history
            ],
            [
                "Delayed memory appended: First report",
                "Delayed memory appended: Second report",
            ],
        )

    def test_remove_delayed_memory_only_detaches_from_context(self):

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        context = Context()
        context.emitter = Emitter()
        context.runtime_action_events = []
        context.runtime_search_calls = []
        context.runtime_appended_skills = []
        context.runtime_asset_results = []
        context.runtime_appended_delayed_memory = {
            "id": "a1b2c3",
            "title": "Pinned report",
            "summary": "Summary",
        }
        context.delayed_memory_reports = {
            "a1b2c3": {
                "title": "Pinned report",
                "summary": "Summary",
                "tags": [
                    "tag",
                ],
                "body": "Body",
            },
        }

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="REMOVE_DELAYED_MEMORY",
                        payload="a1b2c3",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            1,
        )
        self.assertEqual(
            context.runtime_appended_delayed_memory,
            {},
        )
        self.assertIn(
            "a1b2c3",
            context.delayed_memory_reports,
        )
        self.assertEqual(
            context.delayed_memory_reports,
            {
                "a1b2c3": {
                    "title": "Pinned report",
                    "summary": "Summary",
                    "tags": [
                        "tag",
                    ],
                    "body": "Body",
                },
            },
        )
        self.assertEqual(
            context.emitter.events[0]["text"],
            "Removing: Pinned report",
        )
        self.assertEqual(
            context.runtime_session_action_history[0]["text"],
            "Delayed memory removed from context: Pinned report",
        )

    def test_invalid_remove_delayed_memory_id_returns_failed_result(self):

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        context = Context()
        context.emitter = Emitter()
        context.runtime_action_events = []
        context.runtime_search_calls = []
        context.runtime_appended_skills = []
        context.runtime_asset_results = []
        context.runtime_delayed_memory_results = []
        context.delayed_memory_reports = {
            "a1b2c3": {
                "title": "Saved report",
                "summary": "Summary",
                "tags": [
                    "tag",
                ],
                "body": "Body",
            },
        }

        extracted = extract_runtime_actions(
            "<INTERNAL_ACTION_REMOVE_DELAYED_MEMORY: Test report (summary check)>",
            enabled_actions=(
                "REMOVE_DELAYED_MEMORY",
            ),
        )

        self.assertEqual(
            extracted.actions,
            (
                RuntimeActionCall(
                    name="REMOVE_DELAYED_MEMORY",
                    payload="Test report (summary check)",
                ),
            ),
        )

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                extracted.actions,
            )
        )

        self.assertEqual(
            applied_count,
            1,
        )
        self.assertEqual(
            context.emitter.events[0]["status"],
            "failed",
        )
        self.assertEqual(
            context.runtime_delayed_memory_results[0]["ok"],
            False,
        )
        self.assertEqual(
            context.runtime_delayed_memory_results[0]["error"],
            "invalid_delayed_memory_id",
        )
        self.assertIn(
            '<TOOL_RESULT name="REMOVE_DELAYED_MEMORY">',
            build_tool_results_context(
                context
            ),
        )

    def test_apply_runtime_action_calls_emits_create_active_memory_bubble(self):

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        context = Context()
        context.emitter = Emitter()
        context.timestamp = "2026-06-20T10:00:00"
        context.session_id = "test-session"
        context.turn_number = 3

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="CREATE_ACTIVE_MEMORY",
                        payload="remind later",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            1,
        )
        self.assertEqual(
            len(context.emitter.events),
            2,
        )
        self.assertEqual(
            context.emitter.events[0]["type"],
            "runtime_action",
        )
        self.assertEqual(
            context.emitter.events[0]["action"],
            "create_active_memory",
        )
        self.assertEqual(
            context.emitter.events[0]["text"],
            "Saving: remind later",
        )
        self.assertEqual(
            len(context.active_memory_records),
            1,
        )
        self.assertRegex(
            context.active_memory_records[0],
            (
                r"^active_memory_1: remind later "
                r"\[ active_memory_id: [a-z0-9]{6} \] "
                r"\[ conditions: remind later \] "
                r"\[ creation_time: 2026-06-20T10:00:00 \] "
                r"\[ created_session_id: test-session \] "
                r"\[ created_jin_message_number: 3 \] "
                r"\[ elapsed_time: 00:00:00 \] "
                r"\[ elapsed_jin_message_number: 0 \] "
                r"\[ status: pending \]$"
            ),
        )
        self.assertEqual(
            context.emitter.events[0]["active_memory"],
            context.active_memory_records[0],
        )
        self.assertEqual(
            context.emitter.events[1],
            {
                "type": "runtime_action",
                "action": "create_active_memory",
                "status": "completed",
            },
        )

        tool_results = build_tool_results_context(
            context
        )
        self.assertIn(
            '<TOOL_RESULT name="CREATE_ACTIVE_MEMORY">',
            tool_results,
        )
        self.assertIn(
            "active_memory_records -&gt; &lt;ACTIVE_MEMORY&gt;",
            tool_results,
        )
        self.assertIn(
            "remind later",
            tool_results,
        )
        self.assertIn(
            "active_memory_1:",
            tool_results,
        )

    def test_create_active_memory_replaces_model_runtime_suffixes(self):

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        context = Context()
        context.emitter = Emitter()
        context.timestamp = "2026-07-13T00:12:00"
        context.session_id = "runtime-session"
        context.turn_number = 8

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="CREATE_ACTIVE_MEMORY",
                        payload=(
                            "Experiment Progress: 2m elapsed "
                            "[ active_memory_id: progress_marker_1 ] "
                            "[ conditions: stale condition ] "
                            "[ creation_time: 1999-01-01T00:00:00 ] "
                            "[ created_session_id: model-session ] "
                            "[ created_jin_message_number: 999 ] "
                            "[ elapsed_time: 99:99:99 ] "
                            "[ elapsed_jin_message_number: 999 ] "
                            "[ status: resolved ]"
                        ),
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            1,
        )
        self.assertEqual(
            context.emitter.events[0]["text"],
            "Saving: Experiment Progress: 2m elapsed",
        )
        self.assertEqual(
            context.runtime_action_events[0]["payload"],
            "Experiment Progress: 2m elapsed",
        )

        active_memory = context.active_memory_records[0]

        self.assertRegex(
            active_memory,
            (
                r"^active_memory_1: Experiment Progress: 2m elapsed "
                r"\[ active_memory_id: [a-z0-9]{6} \] "
                r"\[ conditions: Experiment Progress: 2m elapsed \] "
                r"\[ creation_time: 2026-07-13T00:12:00 \] "
                r"\[ created_session_id: runtime-session \] "
                r"\[ created_jin_message_number: 8 \] "
                r"\[ elapsed_time: 00:00:00 \] "
                r"\[ elapsed_jin_message_number: 0 \] "
                r"\[ status: pending \]$"
            ),
        )
        self.assertNotIn(
            "progress_marker_1",
            active_memory,
        )
        self.assertNotIn(
            "stale condition",
            active_memory,
        )
        self.assertNotIn(
            "model-session",
            active_memory,
        )
        self.assertNotIn(
            "99:99:99",
            active_memory,
        )

    def test_apply_runtime_action_calls_queues_active_memory_record(self):

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        context = Context()
        context.emitter = Emitter()
        context.timestamp = "2026-06-24T15:00:00"
        context.session_id = "tab-session"
        context.turn_number = 7
        context.runtime_memory = "session_status: active"
        context.runtime_memory_updates = 0

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="CREATE_ACTIVE_MEMORY",
                        payload="Drink coffee | Trigger in 5 minutes | coffee",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            1,
        )
        self.assertEqual(
            context.runtime_memory_updates,
            0,
        )
        self.assertEqual(
            context.runtime_memory,
            "session_status: active",
        )
        self.assertEqual(
            len(context.active_memory_records),
            1,
        )
        self.assertRegex(
            context.active_memory_records[0],
            (
                r"^active_memory_1: Drink coffee \| Trigger in 5 minutes \| coffee "
                r"\[ active_memory_id: [a-z0-9]{6} \] "
                r"\[ conditions: Drink coffee \| Trigger in 5 minutes \| coffee \] "
                r"\[ creation_time: 2026-06-24T15:00:00 \] "
                r"\[ created_session_id: tab-session \] "
                r"\[ created_jin_message_number: 7 \] "
                r"\[ elapsed_time: 00:00:00 \] "
                r"\[ elapsed_jin_message_number: 0 \] "
                r"\[ status: pending \]$"
            ),
        )
        self.assertEqual(
            context.emitter.events[0]["type"],
            "runtime_action",
        )
        self.assertEqual(
            context.emitter.events[0]["action"],
            "create_active_memory",
        )
        self.assertEqual(
            context.emitter.events[0]["text"],
            "Saving: Drink coffee | Trigger in 5 minutes | coffee",
        )
        self.assertEqual(
            context.emitter.events[0]["active_memory"],
            context.active_memory_records[0],
        )

    def test_apply_runtime_action_calls_skips_exact_active_memory_copy(self):

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        context = Context()
        context.emitter = Emitter()
        context.runtime_action_events = []
        context.runtime_search_calls = []
        context.runtime_memory = ""
        context.runtime_memory_stable = ""
        context.active_memory_records = [
            (
                "active_memory_1: remember cuckoo "
                "[ active_memory_id: 5fdg4g ] "
                "[ conditions: remember cuckoo ] "
                "[ creation_time: 2026-06-24T15:00:00 ] "
                "[ elapsed_time: 00:00:00 ] "
                "[ status: pending ]"
            ),
        ]

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="CREATE_ACTIVE_MEMORY",
                        payload="remember cuckoo",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            0,
        )
        self.assertEqual(
            len(context.active_memory_records),
            1,
        )
        self.assertEqual(
            context.runtime_action_events,
            [
                {
                    "name": "create_active_memory",
                    "payload": "remember cuckoo",
                },
            ],
        )
        self.assertEqual(
            context.emitter.events,
            [
                {
                    "type": "runtime_action",
                    "action": "create_active_memory",
                    "text": "Saving: remember cuckoo",
                },
                {
                    "type": "runtime_action",
                    "action": "create_active_memory",
                    "status": "completed",
                },
            ],
        )

    def test_apply_runtime_action_calls_skips_active_memory_copy_from_runtime_memory(self):

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        context = Context()
        context.emitter = Emitter()
        context.runtime_action_events = []
        context.runtime_search_calls = []
        context.runtime_memory = (
            "session_status: active\n"
            "active_memory_1: remember cuckoo "
            "[ active_memory_id: 5fdg4g ] "
            "[ conditions: remember cuckoo ] "
            "[ status: pending ]"
        )
        context.runtime_memory_stable = ""
        context.active_memory_records = []

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="CREATE_ACTIVE_MEMORY",
                        payload="remember cuckoo",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            0,
        )
        self.assertEqual(
            context.active_memory_records,
            [],
        )
        self.assertEqual(
            context.runtime_action_events,
            [
                {
                    "name": "create_active_memory",
                    "payload": "remember cuckoo",
                },
            ],
        )
        self.assertEqual(
            context.emitter.events,
            [
                {
                    "type": "runtime_action",
                    "action": "create_active_memory",
                    "text": "Saving: remember cuckoo",
                },
                {
                    "type": "runtime_action",
                    "action": "create_active_memory",
                    "status": "completed",
                },
            ],
        )

    def test_apply_runtime_action_calls_resolves_active_memory_by_id(self):

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        context = Context()
        context.emitter = Emitter()
        context.runtime_memory = (
            "session_status: active\n"
            "active_memory: remember cuckoo [ active_memory_id: 5fdg4g ] "
            "[ status: pending ]\n"
            "user_message: hello"
        )
        context.runtime_memory_stable = context.runtime_memory
        context.active_memory_records = [
            (
                "active_memory_1: remember cuckoo [ active_memory_id: 5fdg4g ] "
                "[ status: pending ]"
            ),
        ]

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="RESOLVE_ACTIVE_MEMORY",
                        payload="active_memory_id: 5fdg4g",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            1,
        )
        self.assertNotIn(
            "active_memory: remember cuckoo",
            context.runtime_memory,
        )
        self.assertNotIn(
            "5fdg4g",
            context.runtime_memory_stable,
        )
        self.assertIn(
            "session_status: active",
            context.runtime_memory,
        )
        self.assertEqual(
            context.active_memory_records,
            [],
        )
        self.assertEqual(
            context.runtime_action_events[0]["id"],
            "5fdg4g",
        )
        self.assertEqual(
            context.runtime_tool_results,
            [
                {
                    "kind": TOOL_RESULT_KIND_ACTIVE_MEMORY,
                    "result": {
                        "ok": True,
                        "action": "resolve_active_memory",
                        "destination": (
                            "active_memory_records -> <ACTIVE_MEMORY> "
                            "(resolved and removed)"
                        ),
                        "id": "5fdg4g",
                        "content": "remember cuckoo",
                        "record": (
                            "active_memory_1: remember cuckoo "
                            "[ active_memory_id: 5fdg4g ] "
                            "[ status: pending ]"
                        ),
                    },
                },
            ],
        )
        tool_results = build_tool_results_context(
            context
        )
        self.assertIn(
            '<TOOL_RESULT name="RESOLVE_ACTIVE_MEMORY">',
            tool_results,
        )
        self.assertIn(
            "remember cuckoo",
            tool_results,
        )
        self.assertIn(
            "active_memory_1:",
            tool_results,
        )
        self.assertIn(
            "5fdg4g",
            tool_results,
        )
        self.assertEqual(
            context.emitter.events,
            [
                {
                    "type": "runtime_action",
                    "action": "resolve_active_memory",
                    "id": "5fdg4g",
                    "text": "Active memory resolved",
                },
                {
                    "type": "runtime_action",
                    "action": "resolve_active_memory",
                    "id": "5fdg4g",
                    "status": "completed",
                },
            ],
        )

    def test_apply_runtime_action_calls_resolves_multiple_active_memories(self):

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        context = Context()
        context.emitter = Emitter()
        context.runtime_memory = (
            "active_memory_1: first [ active_memory_id: one111 ] "
            "[ status: pending ]\n"
            "active_memory_2: second [ active_memory_id: two222 ] "
            "[ status: pending ]\n"
            "active_memory_3: third [ active_memory_id: tri333 ] "
            "[ status: pending ]"
        )
        context.runtime_memory_stable = context.runtime_memory
        context.active_memory_records = context.runtime_memory.splitlines()

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
                        payload="two222",
                    ),
                    RuntimeActionCall(
                        name="RESOLVE_ACTIVE_MEMORY",
                        payload="tri333",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            3,
        )
        self.assertEqual(
            context.active_memory_records,
            [],
        )
        self.assertNotIn(
            "active_memory_",
            context.runtime_memory,
        )
        self.assertNotIn(
            "active_memory_",
            context.runtime_memory_stable,
        )
        self.assertTrue(
            context.runtime_active_memory_records_dirty,
        )
        self.assertEqual(
            [
                event.get("id")
                for event in context.emitter.events
                if event.get("status") == "completed"
            ],
            [
                "one111",
                "two222",
                "tri333",
            ],
        )
        self.assertEqual(
            [
                event.get("id")
                for event in context.runtime_action_events
            ],
            [
                "one111",
                "two222",
                "tri333",
            ],
        )

    def test_apply_runtime_action_calls_deduplicates_same_resolve_id(self):

        class Context:
            pass

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

    def test_apply_runtime_action_calls_does_not_resolve_paused_active_memory(self):

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        context = Context()
        context.emitter = Emitter()
        context.runtime_memory = (
            "session_status: active\n"
            "active_memory_1: respond only in Russian "
            "[ active_memory_id: one111 ] [ status: pending ]\n"
            "active_memory_2: remember cuckoo "
            "[ active_memory_id: two222 ] [ status: paused ]"
        )
        context.runtime_memory_stable = context.runtime_memory
        context.active_memory_records = [
            (
                "active_memory_1: respond only in Russian "
                "[ active_memory_id: one111 ] [ status: pending ]"
            ),
            (
                "active_memory_2: remember cuckoo "
                "[ active_memory_id: two222 ] [ status: paused ]"
            ),
        ]

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="RESOLVE_ACTIVE_MEMORY",
                        payload="active_memory_id: two222",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            0,
        )
        self.assertEqual(
            len(context.active_memory_records),
            2,
        )
        self.assertIn(
            "two222",
            "\n".join(context.active_memory_records),
        )
        self.assertIn(
            "two222",
            context.runtime_memory,
        )
        self.assertEqual(
            len(context.emitter.events),
            1,
        )
        self.assertEqual(
            context.emitter.events[0]["status"],
            "failed",
        )
        self.assertEqual(
            context.runtime_tool_results[0]["result"]["error"],
            "active_memory_not_resolved",
        )

    def test_apply_runtime_action_calls_allows_multiple_create_active_memory_turns(self):

        class Context:
            pass

        context = Context()
        context.runtime_action_events = []
        context.runtime_search_calls = []
        context.active_memory_records = []
        context.runtime_memory = ""
        context.runtime_memory_stable = ""

        first_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="CREATE_ACTIVE_MEMORY",
                        payload="First reminder",
                    ),
                ),
            )
        )
        second_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="CREATE_ACTIVE_MEMORY",
                        payload="Second reminder",
                    ),
                ),
            )
        )

        self.assertEqual(
            first_count,
            1,
        )
        self.assertEqual(
            second_count,
            1,
        )
        self.assertEqual(
            len(context.active_memory_records),
            2,
        )
        self.assertRegex(
            context.active_memory_records[0],
            r"^active_memory_1: First reminder ",
        )
        self.assertRegex(
            context.active_memory_records[1],
            r"^active_memory_2: Second reminder ",
        )

    def test_apply_runtime_action_calls_reports_invalid_active_memory_reference(self):

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        context = Context()
        context.emitter = Emitter()
        context.runtime_memory = (
            "active_memory: remember cuckoo [ active_memory_id: 5fdg4g ] "
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
                        payload="active_memory_10",
                    ),
                    RuntimeActionCall(
                        name="RESOLVE_ACTIVE_MEMORY",
                        payload="active_memory_10",
                    ),
                    RuntimeActionCall(
                        name="CLEAN_TOOL_RESULTS",
                        payload="",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            1,
        )
        self.assertIn(
            "5fdg4g",
            context.runtime_memory,
        )
        self.assertEqual(
            len(context.runtime_action_events),
            2,
        )
        self.assertEqual(
            context.runtime_action_events[0]["status"],
            "failed",
        )
        self.assertEqual(
            context.runtime_action_events[0]["requested"],
            "active_memory_10",
        )
        self.assertEqual(
            context.runtime_tool_results,
            [
                {
                    "kind": TOOL_RESULT_KIND_ACTIVE_MEMORY,
                    "result": {
                        "ok": False,
                        "action": "resolve_active_memory",
                        "error": "invalid_active_memory_id",
                        "requested": "active_memory_10",
                        "detail": (
                            "Active memory was not resolved. Use an exact "
                            "6-character active_memory_id from <ACTIVE_MEMORY> "
                            "and retry only for a record that is still pending."
                        ),
                        "available_ids": [
                            "5fdg4g",
                        ],
                    },
                },
            ],
        )
        self.assertEqual(
            [
                event.get("status")
                for event in context.emitter.events
            ],
            [
                "completed",
                "failed",
            ],
        )

        tool_results = build_tool_results_context(
            context
        )
        self.assertIn(
            '<TOOL_RESULT name="RESOLVE_ACTIVE_MEMORY">',
            tool_results,
        )
        self.assertIn(
            '"ok": false',
            tool_results,
        )
        self.assertIn(
            '"requested": "active_memory_10"',
            tool_results,
        )
        self.assertIn(
            '"available_ids": [',
            tool_results,
        )

        flush_pending_active_memory_resolve_failure_history(
            context
        )
        self.assertIn(
            "RESOLVE_ACTIVE_MEMORY - failed: active_memory_10",
            context.runtime_session_action_history[-1]["text"],
        )


    def test_idle_marker_variants_are_removed_and_normalized(self):

        for marker in (
            "<IDLE: 10>",
            "<IDLE: 10s >",
            "<IDLE: 10 s>",
            "<IDLE: 10ms>",
            "<IDLE: 10 ms />",
            "<IDLE:10s>",
            "<INTERNAL_ACTION_IDLE: 10 />",
            "<INTERNAL_ACTION_IDLE: 10ms />",
        ):
            with self.subTest(marker=marker):
                result = extract_runtime_actions(
                    f"before {marker} after",
                    enabled_actions=(
                        runtime_rules.RUNTIME_ACTION_IDLE,
                    ),
                )

                self.assertEqual(
                    result.text,
                    "before  after",
                )
                self.assertEqual(
                    len(result.actions),
                    1,
                )
                self.assertEqual(
                    result.actions[0].name,
                    runtime_rules.RUNTIME_ACTION_IDLE,
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
                        runtime_rules.RUNTIME_ACTION_IDLE,
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
                        runtime_rules.RUNTIME_ACTION_IDLE,
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

    def test_stream_filter_preserves_idle_word_emitted_as_own_chunk(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=(
                runtime_rules.RUNTIME_ACTION_IDLE,
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
                runtime_rules.RUNTIME_ACTION_IDLE,
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
                runtime_rules.RUNTIME_ACTION_IDLE,
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

    def test_multiple_idle_actions_queue_requests_and_flash_bubbles(self):

        class Emitter:

            def __init__(self):
                self.events = []

            async def emit(self, payload):
                self.events.append(payload)

        async def run_case():
            queue = asyncio.Queue()
            emitter = Emitter()
            context = SimpleNamespace(
                background_tasks=set(),
                runtime_action_events=[],
                runtime_search_calls=[],
                runtime_appended_skills=[],
                runtime_visible_skills_result={},
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
                    name=runtime_rules.RUNTIME_ACTION_IDLE,
                    payload="0s",
                ),
                RuntimeActionCall(
                    name=runtime_rules.RUNTIME_ACTION_IDLE,
                    payload="0s",
                ),
                RuntimeActionCall(
                    name=runtime_rules.RUNTIME_ACTION_IDLE,
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
                for _ in actions
            ]

            self.assertEqual(
                applied_count,
                3,
            )
            self.assertEqual(
                [
                    item["idle_followup"]["id"]
                    for item in queued
                ],
                [
                    "idle_001",
                    "idle_002",
                    "idle_003",
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
                    ("idle_001", "started", "IDLE", "0s"),
                    ("idle_001", "completed", "", "0s"),
                    ("idle_002", "started", "IDLE", "0s"),
                    ("idle_002", "completed", "", "0s"),
                    ("idle_003", "started", "IDLE", "0s"),
                    ("idle_003", "completed", "", "0s"),
                ],
            )

        asyncio.run(run_case())


    def test_zero_second_idle_queues_followup_with_full_source_message(self):

        async def run_case():
            queue = asyncio.Queue()
            context = SimpleNamespace(
                background_tasks=set(),
                runtime_action_events=[],
                runtime_search_calls=[],
                runtime_appended_skills=[],
                runtime_visible_skills_result={},
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
                    runtime_rules.RUNTIME_ACTION_IDLE,
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


if __name__ == "__main__":
    unittest.main()
