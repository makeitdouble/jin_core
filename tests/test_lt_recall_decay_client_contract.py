from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
LT_MEMORY_JS = ROOT / "ui" / "static" / "js" / "runtime" / "runtime-lt-memory.js"
MEMORY_VIEW_JS = ROOT / "ui" / "static" / "js" / "runtime" / "runtime-memory-view.js"
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"


class LTRecallDecayClientContractTests(unittest.TestCase):

    def test_browser_store_preserves_last_mentioned_at(self):
        source = LT_MEMORY_JS.read_text(encoding="utf-8")

        self.assertIn("last_mentioned_at: normalizeText(", source)
        self.assertIn(
            "value.last_mentioned_at || value.updated_at || value.created_at",
            source,
        )

    def test_lt_hover_metadata_exposes_last_mentioned_at(self):
        source = MEMORY_VIEW_JS.read_text(encoding="utf-8")

        self.assertIn('"mention_count",\n      "last_mentioned_at",', source)
        self.assertIn('`last_mentioned: ${ageLabel}`', source)

    def test_recall_decay_assets_are_cache_bumped(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertGreaterEqual(source.count("lt-recall-decay=1"), 2)


if __name__ == "__main__":
    unittest.main()
