import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DelayedMemoryClientContractTests(unittest.TestCase):

    def test_remove_delayed_memory_does_not_rewrite_saved_reports(self):

        source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "socket.js"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            'action === "remove_delayed_memory"',
            source,
        )
        self.assertNotIn(
            "replaceDelayedMemoryReports",
            source,
        )
        self.assertNotRegex(
            source,
            r"delete\s+reports\s*\[",
        )


if __name__ == "__main__":
    unittest.main()
