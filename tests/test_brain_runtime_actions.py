import unittest

from clients import (
    build_brain_system_prompt,
    get_enabled_runtime_actions,
)
from runtime import (
    DEEP_THOUGHT_ACTION,
    WEB_SEARCH_ACTION_TEMPLATE,
)
from utils.brain import (
    BRAIN_RUNTIME_ACTIONS,
    SERVICE_AS_BRAIN_RUNTIME_ACTIONS,
)


class BrainRuntimeActionTests(unittest.TestCase):

    def test_agent_runtime_action_flags_enable_search_only(self):

        self.assertEqual(
            get_enabled_runtime_actions(
                SERVICE_AS_BRAIN_RUNTIME_ACTIONS
            ),
            (
                "WEB_SEARCH",
            ),
        )

        self.assertEqual(
            get_enabled_runtime_actions(
                BRAIN_RUNTIME_ACTIONS
            ),
            (
                "WEB_SEARCH",
            ),
        )

    def test_prompt_uses_passed_agent_runtime_actions(self):

        prompt = build_brain_system_prompt(
            runtime_actions={
                "CAN_DEEP_THOUGHT": False,
                "CAN_WEB_SEARCH": True,
            }
        )

        self.assertNotIn(
            "CAN_WEB_SEARCH",
            prompt,
        )

        self.assertNotIn(
            "CAN_DEEP_THOUGHT",
            prompt,
        )

        self.assertNotIn(
            "DEEP_THOUGHT_COUNTER",
            prompt,
        )

        self.assertNotIn(
            DEEP_THOUGHT_ACTION,
            prompt,
        )

        self.assertIn(
            WEB_SEARCH_ACTION_TEMPLATE,
            prompt,
        )

        self.assertIn(
            (
                '<ACTION name="WEB_SEARCH">'
                f"{WEB_SEARCH_ACTION_TEMPLATE}"
                "</ACTION>"
            ),
            prompt,
        )

        self.assertNotIn(
            "<![CDATA[",
            prompt,
        )

        self.assertNotIn(
            "&lt;RUNTIME_ACTION:WEB_SEARCH&gt;",
            prompt,
        )

        self.assertIn(
            "<TIMESTAMP>",
            prompt,
        )

        self.assertNotIn(
            "CURRENT_DATE",
            prompt,
        )

        self.assertNotIn(
            "CURRENT_TIME",
            prompt,
        )

        self.assertNotIn(
            "<YEAR>",
            prompt,
        )

        self.assertNotIn(
            "RUNTIME_STATE",
            prompt,
        )

        self.assertNotIn(
            "INITIAL_STATE",
            prompt,
        )

    def test_prompt_can_flip_agent_actions_dynamically(self):

        prompt = build_brain_system_prompt(
            runtime_actions={
                "CAN_DEEP_THOUGHT": True,
                "CAN_WEB_SEARCH": False,
            }
        )

        self.assertNotIn(
            "CAN_DEEP_THOUGHT",
            prompt,
        )

        self.assertNotIn(
            "CAN_WEB_SEARCH",
            prompt,
        )

        self.assertIn(
            DEEP_THOUGHT_ACTION,
            prompt,
        )

        self.assertIn(
            (
                '<ACTION name="DEEP_THOUGHT">'
                f"{DEEP_THOUGHT_ACTION}"
                "</ACTION>"
            ),
            prompt,
        )

        self.assertNotIn(
            "<![CDATA[",
            prompt,
        )

        self.assertNotIn(
            WEB_SEARCH_ACTION_TEMPLATE,
            prompt,
        )

    def test_search_prompt_requires_plain_query_and_exact_subject(self):

        prompt = build_brain_system_prompt(
            runtime_actions={
                "CAN_DEEP_THOUGHT": False,
                "CAN_WEB_SEARCH": True,
            }
        )

        self.assertIn(
            "preserve the exact subject",
            prompt,
        )

        self.assertIn(
            "only available source of fresh external data",
            prompt,
        )

        self.assertIn(
            "do not rely on memory or guesses",
            prompt,
        )

        self.assertIn(
            "plain text",
            prompt,
        )

        self.assertIn(
            "not another JSON object",
            prompt,
        )


if __name__ == "__main__":
    unittest.main()
