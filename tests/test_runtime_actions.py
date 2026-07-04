import asyncio
import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from clients import (
    apply_runtime_action_calls,
)
from clients.brain_client import (
    should_execute_save_session,
)
from rules import runtime as runtime_rules
from utils.assets_service import (
    list_skills,
    run_asset_action,
)
from utils.runtime_actions import (
    RuntimeActionCall,
    RuntimeActionStreamFilter,
    extract_active_memory_resolve_slot_id,
    extract_search_query,
    extract_runtime_actions,
    get_create_active_memory_marker_fields,
    get_create_active_memory_placeholder_payload,
    parse_delayed_memory_content_payload,
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

        for marker in (
            "<INTERNAL_ACTION_WEB_SEARCH:plain text query>",
            "<INTERNAL_ACTION_WEB_SEARCH:<plain text query>>",
            "<INTERNAL_ACTION_WEB_SEARCH:...>",
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
            report,
            {
                "radius_of_influence_specs": {
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
        self.assertEqual(
            json.loads(
                result.actions[0].payload
            )["radius_of_influence_specs"]["title"],
            "Radius of Influence Specs",
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
                self.assertEqual(
                    context.runtime_asset_results[0]["skills"][0]["name"],
                    "wildcards",
                )
                self.assertNotIn(
                    "content",
                    context.runtime_asset_results[0]["skills"][0],
                )
                self.assertTrue(
                    (root / "assets" / "skills" / "wildcards.txt").exists()
                )
                self.assertEqual(
                    context.emitter.events[0]["action"],
                    "list_skills",
                )
                self.assertEqual(
                    context.emitter.events[0]["text"],
                    "Reading skills",
                )
                self.assertEqual(
                    context.runtime_session_action_history,
                    [
                        "Reading skills",
                    ],
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
                    "Assets: create_wildcard_file - assets/wildcards/clothing/test_tops.txt",
                )
                self.assertEqual(
                    context.emitter.events[1]["status"],
                    "completed",
                )
                self.assertEqual(
                    context.emitter.events[1]["text"],
                    context.emitter.events[0]["text"],
                )
                self.assertEqual(
                    context.emitter.events[1]["id"],
                    context.emitter.events[0]["id"],
                )
                self.assertEqual(
                    context.runtime_session_action_history,
                    [
                        "Assets: create_wildcard_file - assets/wildcards/clothing/test_tops.txt",
                    ],
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
            context.delayed_memory_reports[
                "radius_of_influence_specs"
            ]["created_session_id"],
            "session-1",
        )
        self.assertEqual(
            context.delayed_memory_reports[
                "radius_of_influence_specs"
            ]["created_time"],
            "2026-06-29T12:00:00",
        )
        self.assertEqual(
            context.emitter.events,
            [
                {
                    "type": "runtime_action",
                    "action": "save_delayed_memory_content",
                    "status": "completed",
                    "text": "Saving delayed memory",
                    "delayed_memory_report": context.delayed_memory_reports,
                },
            ],
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
        self.assertEqual(
            context.delayed_memory_reports[
                "kowloon_sandbox_architecture_contextual_status_2"
            ]["summary"],
            "New report.",
        )
        self.assertEqual(
            context.emitter.events[0]["delayed_memory_report"],
            {
                "kowloon_sandbox_architecture_contextual_status_2": (
                    context.delayed_memory_reports[
                        "kowloon_sandbox_architecture_contextual_status_2"
                    ]
                ),
            },
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
            1,
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
            context.emitter.events,
            [
                {
                    "type": "runtime_action",
                    "action": "resolve_active_memory",
                    "id": "5fdg4g",
                    "text": "Active memory resolved",
                },
            ],
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
            context.emitter.events,
            [],
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

    def test_apply_runtime_action_calls_skips_unknown_active_memory_id(self):

        class Context:
            pass

        context = Context()
        context.runtime_memory = (
            "active_memory: remember cuckoo [ active_memory_id: 5fdg4g ] "
            "[ status: pending ]"
        )
        context.runtime_memory_stable = context.runtime_memory

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="RESOLVE_ACTIVE_MEMORY",
                        payload="active_memory_id: abc123",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            0,
        )
        self.assertIn(
            "5fdg4g",
            context.runtime_memory,
        )
        self.assertEqual(
            context.runtime_action_events,
            [],
        )


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
