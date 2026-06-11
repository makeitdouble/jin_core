import unittest

from fastapi.testclient import TestClient

from app import app
from clients.brain_client import (
    should_execute_remember_session,
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

    def test_remember_session_guard_exists(self):

        guard = get_action_guard(
            "remember_session"
        )

        self.assertEqual(
            guard["runtime_action"],
            "REMEMBER_SESSION",
        )
        self.assertEqual(
            guard["private_marker"],
            "<INTERNAL_ACTION_REMEMBER_SESSION>",
        )
        self.assertTrue(
            guard["effects"]["save_session"],
        )

    def test_remember_session_triggers_include_known_phrases(self):

        triggers = get_action_guard_triggers(
            "remember_session"
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

    def test_remember_session_blockers_include_known_phrases(self):

        blockers = get_action_guard_blockers(
            "remember_session"
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

    def test_should_execute_remember_session_matches_bedtime(self):

        self.assertTrue(
            should_execute_remember_session(
                "ладно, я спать, до завтра"
            )
        )

    def test_should_execute_remember_session_matches_save_request(self):

        self.assertTrue(
            should_execute_remember_session(
                "сохрани сессию"
            )
        )

    def test_should_execute_remember_session_blocks_meta_tag_request(self):

        self.assertFalse(
            should_execute_remember_session(
                "покажи тег remember session"
            )
        )

    def test_should_execute_remember_session_ignores_normal_message(self):

        self.assertFalse(
            should_execute_remember_session(
                "обсудим статью дальше"
            )
        )

    def test_should_execute_action_guard_normalizes_yo(self):

        self.assertTrue(
            should_execute_action_guard(
                "remember_session",
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
