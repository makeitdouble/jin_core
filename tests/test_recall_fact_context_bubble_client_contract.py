from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ACTIONS_JS = ROOT / "ui" / "static" / "js" / "socket" / "runtime-actions.js"


class RecallFactContextBubbleClientContractTests(unittest.TestCase):

    def test_counter_only_update_cannot_overwrite_terminal_failure_label(self):
        source = RUNTIME_ACTIONS_JS.read_text(encoding="utf-8")

        self.assertIn(
            "|| restrictedWriteFailure\n        || displayCounterOnly,",
            source,
        )
        self.assertNotIn(
            "displayCounterOnly\n          && closeTag",
            source,
        )


if __name__ == "__main__":
    unittest.main()
