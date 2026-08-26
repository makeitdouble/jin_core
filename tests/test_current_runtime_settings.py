import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from rules import brain_context_builder
from rules.brain_context_builder import build_brain_context


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

        settings_prefix = (
            "<CURRENT_RUNTIME_SETTINGS>\n"
            "restore_mode: enabled\n"
            "</CURRENT_RUNTIME_SETTINGS>\n\n"
        )
        self.assertTrue(
            prompt.startswith(
                settings_prefix
                + "<CONVERSATION_CONTINUE_RULES>\n"
            )
        )
        restore_lines = prompt[len(settings_prefix):].splitlines()[:3]
        self.assertIsNotNone(
            datetime.fromisoformat(restore_lines[1]).utcoffset()
        )
        self.assertEqual(
            restore_lines[2],
            "Current session was bootstrapped in a browser tab!",
        )

    def test_restore_priming_prefixes_current_bootstrap_timestamp(self):
        context = self._context(
            restore_priming=True
        )
        context.runtime_restored_session_dialog = (
            '<RESTORED_SESSION_DIALOG session_id="old">\n'
            '<USER ts="2026-08-26T00:31:00+03:00">first</USER>\n'
            '<JIN ts="2026-08-26T00:31:30+03:00">reply</JIN>\n'
            '<USER ts="2026-08-26T00:32:28+03:00">latest</USER>\n'
            '</RESTORED_SESSION_DIALOG>'
        )

        before = datetime.now().astimezone()
        prompt = build_brain_context(
            context=context,
            runtime_actions={},
            include_runtime_action_instructions=False,
        )
        after = datetime.now().astimezone()

        prefix_lines = prompt.splitlines()[:3]
        self.assertEqual(
            prefix_lines[0],
            "<CONVERSATION_CONTINUE_RULES>",
        )
        self.assertEqual(
            prefix_lines[2],
            "Current session was bootstrapped in a browser tab!",
        )
        bootstrap_time = datetime.fromisoformat(prefix_lines[1])
        self.assertIsNotNone(bootstrap_time.utcoffset())
        self.assertLessEqual(
            before.replace(microsecond=0),
            bootstrap_time,
        )
        self.assertLessEqual(
            bootstrap_time,
            after,
        )
        self.assertNotEqual(
            prefix_lines[1],
            "2026-08-26T00:32:28+03:00",
        )


if __name__ == "__main__":
    unittest.main()
