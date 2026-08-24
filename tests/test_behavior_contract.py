import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import app
from contracts import rules_assembler
from contracts.rules_assembler import (
    build_runtime_action_contract_instructions,
    build_runtime_action_instructions,
)
from runtime.behavior_contract import (
    action_guard_has_exact_trigger_match,
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
from utils.actions.common_action_utils import (
    format_runtime_trigger_words_message,
)
from utils.context.runtime_state import (
    format_runtime_blocked_trigger_word_message,
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

    def test_contract_edits_are_loaded_without_runtime_restart(self):

        with tempfile.TemporaryDirectory() as directory:
            contracts_dir = Path(directory)
            contract_path = contracts_dir / "jin_color.json"

            def write_contract(trigger: str) -> None:
                contract_path.write_text(
                    json.dumps({
                        "jin_color": {
                            "runtime_action": "JIN_COLOR",
                            "triggers": [trigger],
                            "blockers": [],
                        },
                    }),
                    encoding="utf-8",
                )

            with patch.object(
                rules_assembler,
                "CONTRACTS_DIR",
                contracts_dir,
            ):
                write_contract("first trigger")
                self.assertEqual(
                    get_action_guard_triggers("jin_color"),
                    ("first trigger",),
                )

                write_contract("second trigger")
                self.assertEqual(
                    get_action_guard_triggers("jin_color"),
                    ("second trigger",),
                )

    def test_runtime_action_enablement_comes_from_contract_metadata(self):

        with tempfile.TemporaryDirectory() as directory:
            contracts_dir = Path(directory)
            (contracts_dir / "custom_action.json").write_text(
                json.dumps({
                    "custom_action": {
                        "runtime_action": "CUSTOM_ACTION",
                        "enable_flag": "CAN_CUSTOM_ACTION",
                        "runtime_order": 10,
                    },
                }),
                encoding="utf-8",
            )

            with patch.object(
                rules_assembler,
                "CONTRACTS_DIR",
                contracts_dir,
            ):
                self.assertEqual(
                    rules_assembler.get_enabled_runtime_actions({
                        "CAN_CUSTOM_ACTION": True,
                    }),
                    ("CUSTOM_ACTION",),
                )
                self.assertEqual(
                    rules_assembler.get_enabled_runtime_actions({
                        "CAN_CUSTOM_ACTION": False,
                    }),
                    (),
                )

    def test_all_contracts_define_runtime_enable_metadata(self):

        for name, contract in get_behavior_contract()["action_guards"].items():
            self.assertTrue(
                str(contract.get("enable_flag", "") or "").strip(),
                msg=f"{name}.enable_flag must be set",
            )
            self.assertIsInstance(
                contract.get("runtime_order"),
                int,
                msg=f"{name}.runtime_order must be an int",
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
            "No entries found. MANDATORY: DO NOT RETRY THIS ACTION AGAIN!",
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
                "User explicitly rejected requested action and you must skip it! "
                "Notify user didn't provide correct spelling in any of trigger "
                "words: save session, save summary"
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
            (
                "Action failed. DO NOT REPEAT THIS ACTION! "
                "Blocked trigger word: {blocked_trigger_word}"
            ),
        )
        self.assertEqual(
            format_runtime_blocked_trigger_word_message(
                "show tag"
            ),
            (
                "Action failed. DO NOT REPEAT THIS ACTION! "
                "Blocked trigger word: show tag"
            ),
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
            "<SAVE_DELAYED_MEMORY>",
        )
        self.assertTrue(
            guard["close_tag"],
        )

    def test_finds_guard_for_runtime_action(self):

        self.assertEqual(
            get_action_guard_name_for_runtime_action(
                "SAVE_DELAYED_MEMORY"
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

    def test_save_active_memory_contract_is_autonomous(self):

        instructions = build_runtime_action_contract_instructions(
            "SAVE_ACTIVE_MEMORY"
        )

        self.assertEqual(
            get_action_guard_triggers("save_active_memory"),
            (),
        )
        self.assertFalse(
            should_pause_action_guard_for_confirmation(
                "save_active_memory",
                "normal message",
            )
        )
        self.assertIn(
            "active memory is an autonomous runtime action",
            instructions,
        )
        self.assertIn(
            "briefly notify the user in natural text",
            instructions,
        )

    def test_runtime_action_instructions_include_marker_and_followup(self):

        instructions = build_runtime_action_contract_instructions(
            "CLEAN_TOOL_RESULTS"
        )

        self.assertTrue(
            instructions.startswith(
                "<CLEAN_TOOL_RESULTS>\n"
                "Follow-up: false\n"
                "Emit at any moment in you answer"
            )
        )

    def test_close_tag_runtime_action_instructions_include_both_markers(self):

        instructions = build_runtime_action_contract_instructions(
            "CREATE_TODO_LIST"
        )

        self.assertTrue(
            instructions.startswith(
                "<TODO_LIST></TODO_LIST>\n"
                "Follow-up: true\n"
                "RUNTIME TODO LEDGER:"
            )
        )

    def test_runtime_action_instruction_blocks_are_separated(self):

        instructions = build_runtime_action_instructions((
            "CLEAN_TOOL_RESULTS",
            "JIN_COLOR",
        ))

        self.assertIn(
            (
                "Emit at any moment in you answer to clean redundant "
                "tool results and only if they are present in the context "
                "inside <TOOLS_RESULTS> block.\n\n"
                "<JIN_COLOR>"
            ),
            instructions,
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

    def test_exact_trigger_match_requires_bare_contract_trigger(self):

        trigger = get_action_guard_triggers(
            "save_session"
        )[0]

        self.assertTrue(
            action_guard_has_exact_trigger_match(
                "save_session",
                f"  {trigger}  ",
            )
        )
        self.assertFalse(
            action_guard_has_exact_trigger_match(
                "save_session",
                f"{trigger}!",
            )
        )
        self.assertFalse(
            action_guard_has_exact_trigger_match(
                "save_session",
                f"пожалуйста, {trigger}",
            )
        )

    def test_matching_blocker_skips_without_confirmation(self):

        blockers = get_action_guard_blockers(
            "save_session"
        )
        if not blockers:
            self.skipTest(
                "save_session contract has no blockers configured"
            )

        self.assertFalse(
            should_pause_action_guard_for_confirmation(
                "save_session",
                blockers[0],
            )
        )
        self.assertFalse(
            should_execute_action_guard(
                "save_session",
                blockers[0],
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
