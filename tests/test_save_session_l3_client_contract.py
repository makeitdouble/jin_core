import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SaveSessionL3ClientContractTests(unittest.TestCase):

    def test_terminal_save_session_event_cannot_rearm_l3_bubble(self):

        source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "socket"
            / "runtime-actions.js"
        ).read_text(encoding="utf-8")

        force_start = source.index(
            "const forceCompletePendingL3 ="
        )
        force_end = source.index(
            "if (",
            force_start,
        )
        force_block = source[force_start:force_end]

        self.assertIn(
            'action === "save_session"',
            force_block,
        )
        self.assertIn(
            "&& terminalStatus",
            force_block,
        )
        self.assertNotIn(
            "!['",
            force_block,
        )

        completed_start = source.index(
            'if (\n    status === "completed"'
        )
        completed_end = source.index(
            "return;",
            completed_start,
        )
        completed_block = source[
            completed_start:completed_end
        ]

        self.assertIn(
            "forceCompletePendingL3,",
            completed_block,
        )


if __name__ == "__main__":
    unittest.main()
