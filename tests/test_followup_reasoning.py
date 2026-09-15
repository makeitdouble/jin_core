import unittest
from types import SimpleNamespace

from agent.nodes.brain import BrainNode
from rules.brain_context_builder import build_brain_context


class FollowupReasoningTests(unittest.TestCase):
    def test_followup_keeps_current_sequence_reasoning(self):
        actions = (
            "posting_board",
            "web_search",
            "stuck in a reasoning loop",
            "context_limit",
            "followup_limit_reached",
        )

        for loop in (False, True):
            for action in actions:
                with self.subTest(loop=loop, action=action):
                    context = SimpleNamespace(
                        runtime_previous_reasoning_content="previous unique thought",
                        runtime_turn_reasoning_content="current unique thought",
                        runtime_previous_reasoning_loop_contents=(
                            ["failed unique thought"] if loop else []
                        ),
                        runtime_reasoning_recovery_pending=loop,
                        runtime_turn_interruption_reason=(
                            "reasoning repetition" if loop else ""
                        ),
                    )
                    base = build_brain_context(
                        context,
                        include_previous_reasoning=False,
                        include_turn_reasoning=True,
                        crop_previous_reasoning=False,
                    )
                    prompt = BrainNode.build_followup_system_prompt(
                        base,
                        "request",
                        context=context,
                        latest_action=action,
                        instruction="Continue after the action.",
                    )

                    thought = (
                        "failed unique thought" if loop else "current unique thought"
                    )
                    self.assertIn(thought, prompt)
                    self.assertNotIn("previous unique thought", prompt)
                    self.assertIn("Continue after the action.", prompt)
                    self.assertEqual(
                        context.runtime_turn_reasoning_content,
                        "current unique thought",
                    )
                    if loop:
                        self.assertIn("<REASONING_RECOVERY>", prompt)
                        self.assertFalse(context.runtime_reasoning_recovery_pending)

    def test_followup_preserves_reasoning_blocks_with_windows_newlines(self):
        block = (
            "<PREVIOUS_REASONING_CONTENT>\r\n"
            "secret thought\r\n"
            "</PREVIOUS_REASONING_CONTENT>\r\n"
        )
        prompt = BrainNode.build_followup_system_prompt(
            block + block + "BASE",
            "request",
        )

        self.assertEqual(prompt.count("secret thought"), 2)
        self.assertIn("BASE", prompt)


if __name__ == "__main__":
    unittest.main()
