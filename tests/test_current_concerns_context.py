import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agent.nodes.brain import BrainNode
from rules.brain_context_builder import build_brain_context
from utils.context.current_concerns import (
    build_current_concerns_context,
)


class CurrentConcernsContextTests(unittest.TestCase):

    def test_empty_current_concerns_block_is_followed_by_trusted_variables(self):
        context = SimpleNamespace(
            runtime_memory="",
            active_memory_records=[],
            runtime_attached_file_ids=[],
            delayed_memory_reports={},
            runtime_loaded_delayed_memory={},
        )

        prompt = build_brain_context(
            context=context,
            runtime_actions={
                "CAN_WEB_SEARCH": False,
            },
            include_runtime_action_instructions=False,
        )

        self.assertTrue(
            prompt.startswith(
                "<CURRENT_CONCERNS>\n</CURRENT_CONCERNS>\n\n"
                "<CURRENT_TRUSTED_RUNTIME_VARIABLES>"
            )
        )
        self.assertLess(
            prompt.index("</CURRENT_TRUSTED_RUNTIME_VARIABLES>"),
            prompt.index("<TOOLS_RESULTS>"),
        )

    def test_current_concerns_counts_pending_memory_and_loaded_resources(self):
        context = SimpleNamespace(
            active_memory_records=[
                "active_memory_1: first [ status: pending ]",
                "active_memory_2: paused [ status: paused ]",
                "active_memory_3: third",
            ],
            runtime_attached_file_ids=[
                "abc123",
                "def456",
                "missing",
            ],
        )

        def fake_get_file_record(file_id):
            if file_id in {"abc123", "def456"}:
                return {
                    "id": file_id,
                    "name": f"{file_id}.txt",
                }
            return None

        with patch(
            "utils.context.current_concerns.get_file_record",
            side_effect=fake_get_file_record,
        ), patch(
            "utils.context.current_concerns.include_pinned_delayed_memory_reports",
            return_value={
                "aaa111": {"id": "aaa111"},
                "bbb222": {"id": "bbb222"},
            },
        ):
            block = build_current_concerns_context(
                context
            )

        self.assertEqual(
            block,
            (
                "<CURRENT_CONCERNS>\n"
                "You have 2 pending active memories to resolve.\n"
                "Loaded: 2 files, 2 delayed memory\n"
                "</CURRENT_CONCERNS>"
            ),
        )

    def test_current_concerns_uses_singular_active_memory_and_file(self):
        context = SimpleNamespace(
            active_memory_records=[
                "active_memory_1: only concern",
            ],
            runtime_attached_file_ids=[
                "abc123",
            ],
        )

        with patch(
            "utils.context.current_concerns.get_file_record",
            return_value={
                "id": "abc123",
                "name": "one.txt",
            },
        ), patch(
            "utils.context.current_concerns.include_pinned_delayed_memory_reports",
            return_value={},
        ):
            block = build_current_concerns_context(
                context
            )

        self.assertIn(
            "You have 1 pending active memory to resolve.",
            block,
        )
        self.assertIn(
            "Loaded: 1 file",
            block,
        )

    def test_followup_rebuilds_current_concerns_from_live_context(self):
        context = SimpleNamespace(
            active_memory_records=[
                "active_memory_1: live concern",
            ],
            runtime_attached_file_ids=[],
            delayed_memory_reports={},
            runtime_loaded_delayed_memory={},
            runtime_session_action_history=[],
        )
        stale_prompt = (
            "<CURRENT_CONCERNS>\n"
            "You have 12 pending active memories to resolve.\n"
            "Loaded: 2 files, 2 delayed memory\n"
            "</CURRENT_CONCERNS>\n\n"
            "<TOOLS_RESULTS>\n</TOOLS_RESULTS>\n\n"
            "<RUNTIME_MEMORY>frozen</RUNTIME_MEMORY>"
        )

        prompt = BrainNode.build_followup_system_prompt(
            stale_prompt,
            "continue",
            context=context,
        )

        self.assertEqual(
            prompt.count("<CURRENT_CONCERNS>"),
            1,
        )
        self.assertIn(
            "You have 1 pending active memory to resolve.",
            prompt,
        )
        self.assertNotIn(
            "You have 12 pending active memories to resolve.",
            prompt,
        )
        self.assertNotIn(
            "Loaded: 2 files, 2 delayed memory",
            prompt,
        )
        self.assertLess(
            prompt.index("</CURRENT_CONCERNS>"),
            prompt.index("<TOOLS_RESULTS>"),
        )


if __name__ == "__main__":
    unittest.main()
