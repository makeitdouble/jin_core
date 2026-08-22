import unittest
from types import SimpleNamespace
from unittest.mock import patch

from rules import brain_context_builder
from rules.brain_context_builder import build_brain_context
from rules.runtime import SESSION_RESTORE_MESSAGE


class CurrentRuntimeSettingsTests(unittest.TestCase):

    @staticmethod
    def _context(*, restore_priming=False):
        return SimpleNamespace(
            runtime_memory="",
            active_memory_records=[],
            runtime_attached_file_ids=[],
            delayed_memory_reports={},
            runtime_loaded_delayed_memory={},
            runtime_session_restore_priming=restore_priming,
        )

    def test_empty_runtime_settings_are_omitted(self):
        with patch.object(
            brain_context_builder,
            "CURRENT_RUNTIME_SETTINGS_CONTENT",
            "   \n\t",
        ):
            prompt = build_brain_context(
                context=self._context(),
                runtime_actions={},
                include_runtime_action_instructions=False,
            )

        self.assertNotIn(
            "<CURRENT_RUNTIME_SETTINGS>",
            prompt,
        )
        self.assertTrue(
            prompt.startswith("<CURRENT_CONCERNS>")
        )

    def test_runtime_settings_are_absolute_first_prompt_block(self):
        with patch.object(
            brain_context_builder,
            "CURRENT_RUNTIME_SETTINGS_CONTENT",
            "mode: test\nfeature: enabled",
        ):
            prompt = build_brain_context(
                context=self._context(),
                runtime_actions={},
                include_runtime_action_instructions=False,
            )

        self.assertTrue(
            prompt.startswith(
                "<CURRENT_RUNTIME_SETTINGS>\n"
                "mode: test\n"
                "feature: enabled\n"
                "</CURRENT_RUNTIME_SETTINGS>\n\n"
                "<CURRENT_CONCERNS>"
            )
        )

    def test_runtime_settings_stay_before_restore_priming(self):
        with patch.object(
            brain_context_builder,
            "CURRENT_RUNTIME_SETTINGS_CONTENT",
            "restore_mode: enabled",
        ):
            prompt = build_brain_context(
                context=self._context(
                    restore_priming=True
                ),
                runtime_actions={},
                include_runtime_action_instructions=False,
            )

        expected_prefix = (
            "<CURRENT_RUNTIME_SETTINGS>\n"
            "restore_mode: enabled\n"
            "</CURRENT_RUNTIME_SETTINGS>\n\n"
            f"{SESSION_RESTORE_MESSAGE}"
        )
        self.assertTrue(
            prompt.startswith(expected_prefix)
        )


if __name__ == "__main__":
    unittest.main()
