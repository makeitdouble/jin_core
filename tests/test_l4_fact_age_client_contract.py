from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MEMORY_VIEW = (
    ROOT
    / "ui"
    / "static"
    / "js"
    / "runtime"
    / "runtime-memory-view.js"
)
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"


class L4FactAgeClientContractTests(unittest.TestCase):

    def test_l4_rows_show_live_context_age_after_display_value(self):
        source = MEMORY_VIEW.read_text(encoding="utf-8")

        self.assertIn(
            "function getLongTermFactContextTimestamp(fact)",
            source,
        )
        self.assertIn(
            "parseLongTermFactTimestamp(fact.updated_at)",
            source,
        )
        self.assertIn(
            "parseLongTermFactTimestamp(fact.created_at)",
            source,
        )
        self.assertIn(
            "context_age_timestamp:\n        getLongTermFactContextTimestamp(fact)",
            source,
        )
        self.assertIn(
            'ageSpan.className =\n            "runtime-memory-l4-age";',
            source,
        )
        self.assertIn(
            "valueSpan.appendChild(ageSpan);",
            source,
        )

    def test_l4_age_uses_same_bucket_format_as_brain_context(self):
        source = MEMORY_VIEW.read_text(encoding="utf-8")

        self.assertIn("Math.max(\n      1,", source)
        self.assertIn("` ( ${seconds}s ago )`", source)
        self.assertIn("` ( ${minutes}m ago )`", source)
        self.assertIn("` ( ${hours}h ago )`", source)
        self.assertIn("` ( ${days}d ago )`", source)
        self.assertIn(
            "window.setInterval(\n        refreshLongTermMemoryFactAges,\n        1000",
            source,
        )

    def test_runtime_memory_view_cache_version_is_bumped(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn(
            "/static/js/runtime/runtime-memory-view.js?"
            "v=context-card-chevronless-1&delayed-fact-paste=2&numeric-fact-order=1"
            "&l4-fact-age=1",
            source,
        )


if __name__ == "__main__":
    unittest.main()
