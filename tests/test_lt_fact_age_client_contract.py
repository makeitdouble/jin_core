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


class LTFactAgeClientContractTests(unittest.TestCase):

    def test_lt_rows_show_creation_age_in_header(self):
        source = MEMORY_VIEW.read_text(encoding="utf-8")

        self.assertIn(
            "function getLongTermFactCreatedTimestamp(fact)",
            source,
        )
        self.assertIn(
            "context_age_timestamp:\n        getLongTermFactCreatedTimestamp(fact)",
            source,
        )
        self.assertIn(
            'ageSpan.className =\n              "runtime-memory-lt-age";',
            source,
        )
        self.assertIn(
            'longTermHeader.className =\n            "runtime-memory-lt-header";',
            source,
        )
        self.assertIn(
            "longTermHeader.appendChild(ageSpan);",
            source,
        )
        self.assertNotIn(
            "valueSpan.appendChild(ageSpan);",
            source,
        )

    def test_lt_age_uses_same_bucket_format_as_brain_context(self):
        source = MEMORY_VIEW.read_text(encoding="utf-8")

        self.assertIn("Math.max(\n      1,", source)
        self.assertIn("`${seconds}s ago`", source)
        self.assertIn("`${minutes}m ago`", source)
        self.assertIn("`${hours}h ago`", source)
        self.assertIn("`${days}d ago`", source)
        self.assertIn(
            "window.setInterval(\n        refreshLongTermMemoryFactAges,\n        1000",
            source,
        )

    def test_lt_rows_use_fixed_header_and_separate_value_line(self):
        source = MEMORY_VIEW.read_text(encoding="utf-8")
        css = (
            ROOT
            / "ui"
            / "static"
            / "css"
            / "runtime-memory.css"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'longTermHeader.className =\n            "runtime-memory-lt-header";',
            source,
        )
        self.assertIn(
            "longTermHeader.appendChild(keySpan);",
            source,
        )
        self.assertIn(
            "row.appendChild(longTermHeader);",
            source,
        )
        self.assertIn(
            "? valuePresentation.text",
            source,
        )
        self.assertIn(
            ".runtime-memory-lt-row .runtime-memory-key {",
            css,
        )
        self.assertIn("text-overflow: ellipsis;", css)
        self.assertIn("white-space: nowrap;", css)
        self.assertIn(
            ".runtime-memory-lt-row .runtime-memory-value {",
            css,
        )
        self.assertIn("display: block;", css)



if __name__ == "__main__":
    unittest.main()
