import unittest

from fastapi.testclient import TestClient

from app import app
from runtime.behavior_contract import (
    get_action_guard,
    get_action_guard_blockers,
    get_action_guard_name_for_runtime_action,
    get_action_guard_triggers,
    get_behavior_contract,
    should_pause_action_guard_for_confirmation,
    should_execute_action_guard,
)
from rules.runtime import (
    ACTION_ACCEPTED_MISSING_TRIGGER_WORDS_MESSAGE,
    ACTION_BLOCKED_TRIGGER_WORD_MESSAGE,
    ACTION_REJECTED_MISSING_TRIGGER_WORDS_MESSAGE,
    NO_ENTRIES_FOUND_MESSAGE,
)
from utils.context.runtime_state import (
    format_runtime_blocked_trigger_word_message,
    format_runtime_trigger_words_message,
)


class BehaviorContractTests(unittest.TestCase):

    def test_behavior_contract_loads_split_contracts(self):

        contract = get_behavior_contract()

        self.assertEqual(
            contract["version"],
            1,
        )
        self.assertIsInstance(
            contract["action_guards"],
            dict,
        )
        self.assertIn(
            "save_session",
            contract["action_guards"],
        )
        self.assertIn(
            "save_delayed_memory",
            contract["action_guards"],
        )

    def test_all_contracts_have_trigger_words_and_blockers_as_lists(self):

        for name, contract in get_behavior_contract()["action_guards"].items():
            self.assertIsInstance(
                contract.get("triggers", []),
                list,
                msg=f"{name}.triggers must be a list",
            )
            self.assertIsInstance(
                contract.get("blockers", []),
                list,
                msg=f"{name}.blockers must be a list",
            )

    def test_contract_text_fields_are_line_arrays_without_embedded_newlines(self):

        for name, contract in get_behavior_contract()["action_guards"].items():
            for field in (
                "rules",
            ):
                values = contract.get(
                    field,
                    [],
                )
                self.assertIsInstance(
                    values,
                    list,
                    msg=f"{name}.{field} must be a list",
                )

                for value in values:
                    self.assertIsInstance(
                        value,
                        str,
                    )
                    self.assertNotIn(
                        "\n",
                        value,
                        msg=f"{name}.{field} contains embedded newline",
                    )

    def test_contracts_do_not_define_failure_followup_message(self):

        for name, contract in get_behavior_contract()["action_guards"].items():
            self.assertNotIn(
                "failure_followup_message",
                contract,
                msg=(
                    f"{name}.failure_followup_message must come from "
                    "rules.runtime defaults"
                ),
            )

    def test_runtime_default_messages_are_formatted(self):

        self.assertEqual(
            NO_ENTRIES_FOUND_MESSAGE,
            "No entries found.",
        )
        self.assertEqual(
            format_runtime_trigger_words_message(
                ACTION_REJECTED_MISSING_TRIGGER_WORDS_MESSAGE,
                (
                    "save session",
                    "save summary",
                ),
            ),
            (
                "Action failed. User rejected an action and didn't provide "
                "any of trigger words: save session, save summary"
            ),
        )
        self.assertEqual(
            format_runtime_trigger_words_message(
                ACTION_ACCEPTED_MISSING_TRIGGER_WORDS_MESSAGE,
                (
                    "save session",
                    "save summary",
                ),
            ),
            (
                "User accepted an action and didn't provide any of action "
                "trigger words: save session, save summary"
            ),
        )
        self.assertEqual(
            ACTION_BLOCKED_TRIGGER_WORD_MESSAGE,
            "Action failed. Blocked trigger word: {blocked_trigger_word}",
        )
        self.assertEqual(
            format_runtime_blocked_trigger_word_message(
                "show tag"
            ),
            "Action failed. Blocked trigger word: show tag",
        )

    def test_save_session_guard_exists(self):

        guard = get_action_guard(
            "save_session"
        )

        self.assertEqual(
            guard["runtime_action"],
            "SAVE_SESSION",
        )
        self.assertEqual(
            guard["private_marker"],
            "<SAVE_SESSION>",
        )
        self.assertTrue(
            guard["effects"]["emit_followup"],
        )

    def test_save_delayed_memory_contract_has_close_tag(self):

        guard = get_action_guard(
            "save_delayed_memory"
        )

        self.assertEqual(
            guard["private_marker"],
            "<SAVE_DELAYED_MEMORY_CONTENT>",
        )
        self.assertTrue(
            guard["close_tag"],
        )

    def test_finds_guard_for_runtime_action(self):

        self.assertEqual(
            get_action_guard_name_for_runtime_action(
                "SAVE_DELAYED_MEMORY_CONTENT"
            ),
            "save_delayed_memory",
        )

    def test_empty_triggers_do_not_require_confirmation(self):

        self.assertFalse(
            should_pause_action_guard_for_confirmation(
                "clean_tool_results",
                "please keep going with the current work",
            )
        )

    def test_empty_triggers_allow_action_guard_execution(self):

        self.assertTrue(
            should_execute_action_guard(
                "clean_tool_results",
                "please keep going with the current work",
            )
        )

    def test_configured_triggers_require_confirmation_and_allow_matching_text(self):

        save_session_triggers = get_action_guard_triggers(
            "save_session"
        )
        if not save_session_triggers:
            self.skipTest(
                "save_session contract has no triggers configured"
            )

        self.assertTrue(
            should_pause_action_guard_for_confirmation(
                "save_session",
                "normal message",
            )
        )
        self.assertTrue(
            should_execute_action_guard(
                "save_session",
                save_session_triggers[0],
            )
        )

    def test_behavior_contract_api_returns_contract(self):

        client = TestClient(
            app
        )

        response = client.get(
            "/api/behavior-contract"
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            response.json(),
            get_behavior_contract(),
        )


if __name__ == "__main__":
    unittest.main()
