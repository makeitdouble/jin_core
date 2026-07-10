import unittest

from fastapi.testclient import TestClient

from app import app
from clients.brain_client import (
    should_execute_save_session,
)
from runtime.behavior_contract import (
    get_action_guard,
    get_action_guard_blockers,
    get_action_guard_triggers,
    get_behavior_contract,
    should_execute_action_guard,
)


class BehaviorContractTests(unittest.TestCase):

    def test_behavior_contract_loads(self):

        contract = get_behavior_contract()

        self.assertEqual(
            contract["version"],
            1,
        )
        self.assertIsInstance(
            contract["action_guards"],
            dict,
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
            guard["effects"]["save_session"],
        )

    def test_save_session_triggers_include_known_phrases(self):

        triggers = get_action_guard_triggers(
            "save_session"
        )

        for phrase in (
            "закончим",
            "я спать",
            "сохрани сессию",
            "wrap up and save",
        ):
            self.assertIn(
                phrase,
                triggers,
            )

    def test_save_session_blockers_include_known_phrases(self):

        blockers = get_action_guard_blockers(
            "save_session"
        )

        for phrase in (
            "покажи тег",
            "напиши тег",
            "exact tag",
            "quote tag",
        ):
            self.assertIn(
                phrase,
                blockers,
            )

    def test_save_delayed_memory_guard_uses_clean_marker(self):

        guard = get_action_guard(
            "save_delayed_memory"
        )

        self.assertEqual(
            guard["private_marker"],
            "<SAVE_DELAYED_MEMORY_CONTENT>",
        )

    def test_save_delayed_memory_triggers_include_english_phrases(self):

        triggers = get_action_guard_triggers(
            "save_delayed_memory"
        )

        for phrase in (
            "save summary",
            "save delayed memory",
            "save dm",
            "summarize and save",
        ):
            self.assertIn(
                phrase,
                triggers,
            )

    def test_should_execute_save_delayed_memory_matches_english_request(self):

        self.assertTrue(
            should_execute_action_guard(
                "save_delayed_memory",
                "please summarize and save this as delayed memory",
            )
        )
        self.assertFalse(
            should_execute_action_guard(
                "save_delayed_memory",
                "show exact tag for saving delayed memory",
            )
        )

    def test_should_execute_save_delayed_memory_matches_create_report_request(self):

        self.assertTrue(
            should_execute_action_guard(
                "save_delayed_memory",
                "создай отчёт delayed memory",
            )
        )

    def test_should_execute_save_session_matches_bedtime(self):

        self.assertTrue(
            should_execute_save_session(
                "ладно, я спать, до завтра"
            )
        )

    def test_should_execute_save_session_matches_save_request(self):

        self.assertTrue(
            should_execute_save_session(
                "сохрани сессию"
            )
        )

    def test_should_execute_save_session_blocks_meta_tag_request(self):

        self.assertFalse(
            should_execute_save_session(
                "покажи тег save session"
            )
        )

    def test_should_execute_save_session_ignores_normal_message(self):

        self.assertFalse(
            should_execute_save_session(
                "обсудим статью дальше"
            )
        )

    def test_should_execute_save_session_ignores_event_save_request(self):

        self.assertFalse(
            should_execute_save_session(
                "хорошо, тогда сохрани это как нашу новую аксиому"
            )
        )

    def test_should_execute_save_session_ignores_generic_save_this(self):

        self.assertFalse(
            should_execute_save_session(
                "сохрани это"
            )
        )

    def test_should_execute_save_session_ignores_bare_save_command(self):

        self.assertFalse(
            should_execute_save_session(
                "сохрани"
            )
        )

    def test_should_execute_action_guard_normalizes_yo(self):

        self.assertTrue(
            should_execute_action_guard(
                "save_session",
                "давай на сегодня все",
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
