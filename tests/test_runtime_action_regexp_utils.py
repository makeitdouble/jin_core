import re
import unittest

from contracts.rules_assembler import get_action_contracts
from utils.actions.common_action_utils import extract_runtime_actions
from utils.actions.regexp_utils import (
    REGEXP_TEMPLATES,
    compile_runtime_action_regexp,
    find_runtime_action_matches,
    find_unclosed_runtime_action_start,
    match_regexp,
    match_regexp_templates,
)


class RuntimeActionRegexpUtilsTests(unittest.TestCase):

    def test_contracts_only_define_marker_shape(self):
        for name, contract in get_action_contracts().items():
            self.assertNotIn(
                "regexp",
                contract,
                msg=f"{name} must use shared regexp utilities",
            )
            self.assertNotIn(
                "regexp_templates",
                contract,
                msg=f"{name} must use shared regexp utilities",
            )

    def test_concrete_regexp_extracts_name_and_payload(self):
        regexp = compile_runtime_action_regexp(
            "<WEB_SEARCH: plain text query >",
            "WEB_SEARCH",
        )

        matches = match_regexp(
            "before <WEB_SEARCH: blue tomato> after",
            regexp,
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].name, "WEB_SEARCH")
        self.assertEqual(matches[0].payload, "blue tomato")

    def test_concrete_regexp_rejects_internal_action_prefix(self):
        regexp = compile_runtime_action_regexp(
            "<SAVE_ACTIVE_MEMORY>",
            "SAVE_ACTIVE_MEMORY",
            close_tag=True,
        )

        matches = match_regexp(
            "before <INTERNAL_ACTION_SAVE_ACTIVE_MEMORY: coffee> after",
            regexp,
        )

        self.assertEqual(matches, ())

    def test_shared_templates_extract_tool_call_payload(self):
        matches = match_regexp_templates(
            "<|tool_call>call:WEB_SEARCH: blue tomato >",
            "<WEB_SEARCH: plain text query >",
            "WEB_SEARCH",
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].name, "WEB_SEARCH")
        self.assertEqual(matches[0].payload, "blue tomato")
        self.assertEqual(matches[0].source, "regexp_template")

    def test_shared_templates_reject_internal_action_prefix(self):
        matches = match_regexp_templates(
            "<|tool_call>call:INTERNAL_ACTION_WEB_SEARCH: blue tomato >",
            "<WEB_SEARCH: plain text query >",
            "WEB_SEARCH",
        )

        self.assertEqual(matches, ())

    def test_close_tag_regexp_extracts_block_payload(self):
        matches = find_runtime_action_matches(
            (
                "<ASSET_ACTION>\n"
                '{"action":"list_assets"}\n'
                "</ASSET_ACTION>"
            ),
            "<ASSET_ACTION>",
            "ASSET_ACTION",
            close_tag=True,
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].name, "ASSET_ACTION")
        self.assertEqual(matches[0].payload, '{"action":"list_assets"}')


    def test_close_tag_action_rejects_bare_name_in_prose(self):
        matches = find_runtime_action_matches(
            "`ASSET_ACTION` relates to tool management.",
            "<ASSET_ACTION>",
            "ASSET_ACTION",
            close_tag=True,
        )

        self.assertEqual(matches, ())

    def test_close_tag_action_does_not_hold_bare_stream_token(self):
        marker_start = find_unclosed_runtime_action_start(
            "ASSET_ACTION` relates to tool management.",
            "<ASSET_ACTION>",
            "ASSET_ACTION",
            close_tag=True,
        )

        self.assertIsNone(marker_start)

    def test_close_tag_action_holds_opening_tag_with_header_payload(self):
        marker_start = find_unclosed_runtime_action_start(
            "<CUSTOM_ACTION: a1b2c3>\ntags: social",
            "<CUSTOM_ACTION: id >",
            "CUSTOM_ACTION",
            close_tag=True,
        )

        self.assertEqual(marker_start, 0)

    def test_explicit_regexp_can_be_used_without_templates(self):
        regexp = re.compile(
            r"ACTION\[(?P<name>[A-Z_]+)\]:(?P<payload>[^\n]+)"
        )

        matches = find_runtime_action_matches(
            "ACTION[WEB_SEARCH]:blue tomato",
            "<WEB_SEARCH: plain text query >",
            "WEB_SEARCH",
            regexp=regexp,
            regexp_templates=(),
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].payload, "blue tomato")

    def test_shared_template_collection_is_application_level(self):
        self.assertIsInstance(REGEXP_TEMPLATES, tuple)
        self.assertGreaterEqual(len(REGEXP_TEMPLATES), 4)

    def test_new_paired_action_contracts_expand_ordered_id_lists(self):
        cases = (
            (
                "<LOAD_DELAYED_MEMORY> a1b2c3, d4e5f6 </LOAD_DELAYED_MEMORY>",
                "LOAD_DELAYED_MEMORY",
                ("a1b2c3", "d4e5f6"),
            ),
            (
                "<DELETE_ACTIVE_MEMORY> a1b2c3, d4e5f6 </DELETE_ACTIVE_MEMORY>",
                "DELETE_ACTIVE_MEMORY",
                ("a1b2c3", "d4e5f6"),
            ),
            (
                "<ATTACH_FILES_BY_ID> a1b2c3, d4e5f6 </ATTACH_FILES_BY_ID>",
                "ATTACH_FILE_BY_ID",
                ("a1b2c3", "d4e5f6"),
            ),
        )

        for source, action_name, expected_ids in cases:
            with self.subTest(action=action_name):
                result = extract_runtime_actions(source, enabled_actions=[action_name])
                self.assertEqual(result.text, "")
                self.assertEqual(tuple(action.name for action in result.actions), (action_name,) * 2)
                self.assertEqual(tuple(action.payload for action in result.actions), expected_ids)

    def test_web_search_uses_paired_body_contract(self):
        result = extract_runtime_actions(
            "before <WEB_SEARCH> blue tomato </WEB_SEARCH> after",
            enabled_actions=["WEB_SEARCH"],
        )
        self.assertEqual(result.text, "before after")
        self.assertEqual(len(result.actions), 1)
        self.assertEqual(result.actions[0].name, "WEB_SEARCH")
        self.assertIn("blue tomato", result.actions[0].payload)

    def test_unload_delayed_memory_contract_is_absent(self):
        contracts = get_action_contracts()
        self.assertNotIn("unload_delayed_memory", contracts)


if __name__ == "__main__":
    unittest.main()
