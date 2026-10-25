import unittest
from types import SimpleNamespace

from agent.nodes.brain import BrainNode
from rules.brain_context_builder import build_brain_context
from rules.identity import IDENTITY


class PromptTailTests(unittest.TestCase):
    def assert_tail(self, prompt):
        tags = [IDENTITY.strip(), "<PREVIOUS_CHAT_MESSAGES>",
                "<PREVIOUS_REASONING_EVIDENCE_TRAIL_AFTER_EXECUTED_ACTIONS>",
                "<TOOLS_RESULTS>"]
        positions = [prompt.index(tag) for tag in tags]
        self.assertEqual(positions, sorted(positions))
        for tag in tags:
            self.assertEqual(prompt.count(tag), 1)
        self.assertTrue(prompt.rstrip().endswith("</TOOLS_RESULTS>"))
        self.assertNotIn("<CONCERNS>", prompt)
        self.assertNotIn("<CURRENT_CONCERNS>", prompt)

    def test_ordinary_restore_and_repeated_followup_tail(self):
        for restore in (False, True):
            with self.subTest(restore=restore):
                context = SimpleNamespace(
                    runtime_memory="session_title: test",
                    active_memory_records=["active_memory_1: pending"],
                    runtime_previous_answer_context_window={"used_tokens": 90, "context_window": 100},
                    runtime_recent_turns=[{"user": "prior user", "jin": "prior answer"}],
                    runtime_previous_reasoning_content="previous thought",
                    runtime_asset_results=[{
                        "ok": True, "action": "read_asset", "content": "tool evidence",
                    }],
                    runtime_session_restore_priming=restore,
                    runtime_restored_session_dialog=(
                        "<PREVIOUS_CHAT_MESSAGES><USER>restored user</PREVIOUS_CHAT_MESSAGES>"
                        if restore else ""
                    ),
                )
                prompt = build_brain_context(context, include_runtime_action_instructions=False)
                self.assert_tail(prompt)
                self.assertIn("tool evidence", prompt)
                if restore:
                    self.assertTrue(prompt.startswith("<MANDATORY_SYSTEM_NOTIFICATION>"))
                for _ in range(2):
                    prompt = BrainNode.build_followup_system_prompt(
                        prompt, "current request", context=context,
                    )
                    self.assert_tail(prompt)
                    self.assertTrue(prompt.startswith("<FOLLOW_UP_RESPONSE_MESSAGE>"))

    def test_stale_concerns_are_discarded(self):
        prompt = BrainNode.build_followup_system_prompt(
            "<CONCERNS>old warning</CONCERNS>\n"
            "<CURRENT_CONCERNS>older warning</CURRENT_CONCERNS>\n" + IDENTITY,
            "continue", context=SimpleNamespace(),
        )
        self.assertNotIn("warning", prompt)
        self.assertNotIn("CONCERNS", prompt)
