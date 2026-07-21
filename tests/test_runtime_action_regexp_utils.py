import re
import unittest

from contracts.rules_assembler import get_action_contracts
from utils.actions.regexp_utils import (
    REGEXP_TEMPLATES,
    compile_runtime_action_regexp,
    find_runtime_action_matches,
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
            "before <INTERNAL_ACTION_WEB_SEARCH: blue tomato> after",
            regexp,
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].name, "WEB_SEARCH")
        self.assertEqual(matches[0].payload, "blue tomato")

    def test_shared_templates_extract_tool_call_payload(self):
        matches = match_regexp_templates(
            "<|tool_call>call:INTERNAL_ACTION_WEB_SEARCH: blue tomato >",
            "<WEB_SEARCH: plain text query >",
            "WEB_SEARCH",
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].name, "WEB_SEARCH")
        self.assertEqual(matches[0].payload, "blue tomato")
        self.assertEqual(matches[0].source, "regexp_template")

    def test_close_tag_regexp_extracts_block_payload(self):
        matches = find_runtime_action_matches(
            (
                "<INTERNAL_ACTION_ASSET_ACTION>\n"
                '{"action":"list_assets"}\n'
                "</INTERNAL_ACTION_ASSET_ACTION>"
            ),
            "<ASSET_ACTION>",
            "ASSET_ACTION",
            close_tag=True,
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].name, "ASSET_ACTION")
        self.assertEqual(matches[0].payload, '{"action":"list_assets"}')

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


if __name__ == "__main__":
    unittest.main()
