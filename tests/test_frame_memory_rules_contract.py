import unittest

from runtime.L1_memory_rules import build_runtime_memory_system_prompt


class FrameMemoryRulesContractTests(unittest.TestCase):
    def test_frame_output_is_full_replacement_without_momentum_hint(self):
        prompt = build_runtime_memory_system_prompt(
            user_message="test",
        )

        self.assertIn(
            "Return the complete resulting compressed FRAME memory state as plain text.",
            prompt,
        )
        self.assertIn(
            "This response is a full replacement snapshot, not a patch or delta",
            prompt,
        )
        self.assertIn(
            "the previous FRAME state is replaced in full by exactly the state you return.",
            prompt,
        )
        self.assertNotIn(
            "- momentum:",
            prompt,
        )
        self.assertNotIn(
            "interaction_momentum",
            prompt,
        )


if __name__ == "__main__":
    unittest.main()
