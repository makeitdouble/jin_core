import unittest
from types import SimpleNamespace
from unittest.mock import patch

from rules import brain_context_builder
from rules.brain_context_builder import build_brain_context


class CurrentRuntimeSettingsTests(unittest.TestCase):

    @staticmethod
    def _context(*, restore_priming=False):
        return SimpleNamespace(
            session_id="current-session-test",
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
            "<RUNTIME_SETTINGS>",
            prompt,
        )
        self.assertTrue(
            prompt.startswith("<TRUSTED_RUNTIME_VARIABLES>")
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
                "<RUNTIME_SETTINGS>\n"
                "mode: test\n"
                "feature: enabled\n"
                "</RUNTIME_SETTINGS>\n\n"
                "<TRUSTED_RUNTIME_VARIABLES>"
            )
        )

    def test_restore_priming_precedes_runtime_settings(self):
        context = self._context(
            restore_priming=True
        )
        context.runtime_restored_session_dialog = (
            "<OLD_SESSION_RESTORED_STATE>old</OLD_SESSION_RESTORED_STATE>"
        )
        with patch.object(
            brain_context_builder,
            "CURRENT_RUNTIME_SETTINGS_CONTENT",
            "restore_mode: enabled",
        ):
            prompt = build_brain_context(
                context=context,
                runtime_actions={},
                include_runtime_action_instructions=False,
            )

        settings_prefix = (
            "<RUNTIME_SETTINGS>\n"
            "restore_mode: enabled\n"
            "</RUNTIME_SETTINGS>\n\n"
        )
        self.assertIn("<MANDATORY_SYSTEM_NOTIFICATION>", prompt)
        mandatory_pos = prompt.index("<MANDATORY_SYSTEM_NOTIFICATION>")
        settings_pos = prompt.index(settings_prefix.strip())
        trusted_pos = prompt.index("<TRUSTED_RUNTIME_VARIABLES>")
        self.assertLess(mandatory_pos, settings_pos)
        self.assertLess(settings_pos, trusted_pos)

    def test_restore_priming_places_old_session_state_under_mandatory_notification(self):
        context = self._context(
            restore_priming=True
        )
        context.runtime_restored_session_dialog = (
            '<OLD_SESSION_RESTORED_STATE session_id="old">\n'
            '<USER ts="2026-08-26T00:31:00+03:00">first</USER>\n'
            '<JIN ts="2026-08-26T00:31:30+03:00">reply</JIN>\n'
            '<USER ts="2026-08-26T00:32:28+03:00">latest</USER>\n'
            '</OLD_SESSION_RESTORED_STATE>'
        )

        prompt = build_brain_context(
            context=context,
            runtime_actions={},
            include_runtime_action_instructions=False,
        )

        self.assertIn("<MANDATORY_SYSTEM_NOTIFICATION>", prompt)
        self.assertIn(
            "Current session id: current-session-test\nCurrent time: ",
            prompt,
        )
        session_pos = prompt.index("Current session id: current-session-test")
        time_pos = prompt.index("Current time: ")
        no_user_pos = prompt.index("!!! USER DIDN'T SEND NEW MESSAGE! !!!")
        self.assertLess(session_pos, time_pos)
        self.assertLess(time_pos, no_user_pos)
        mandatory_end = prompt.index("</MANDATORY_SYSTEM_NOTIFICATION>")
        trusted_pos = prompt.index("<TRUSTED_RUNTIME_VARIABLES>")
        self.assertLess(mandatory_end, trusted_pos)


if __name__ == "__main__":
    unittest.main()
