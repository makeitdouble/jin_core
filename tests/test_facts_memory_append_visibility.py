import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FactsMemoryAppendVisibilityTests(unittest.TestCase):

    def test_append_visibility_uses_current_and_source_session_ids(self):
        source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "logger"
            / "log-entries.js"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "function setFactsMemoryAppendButtonVisible(",
            source,
        )
        self.assertIn(
            "storage.getCurrentFactsMemorySessionId()",
            source,
        )
        self.assertIn(
            "storage.getSessionIdFromFactsMemoryStorageKey(",
            source,
        )
        self.assertIn(
            "sourceSessionId !== currentSessionId",
            source,
        )
        self.assertIn(
            "!currentSessionHasFacts",
            source,
        )
        self.assertIn(
            "appendButton.style.display =\n      \"none\";",
            source,
        )
        self.assertIn(
            "appendButton.style.removeProperty(\n      \"display\"",
            source,
        )


if __name__ == "__main__":
    unittest.main()
