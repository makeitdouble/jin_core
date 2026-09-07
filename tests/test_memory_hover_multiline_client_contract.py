from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MEMORY_VIEW = ROOT / "ui/static/js/runtime/runtime-memory-view.js"
MEMORY_CSS = ROOT / "ui/static/css/runtime-memory.css"


class MemoryHoverMultilineClientContractTests(unittest.TestCase):

    def test_hover_decodes_runtime_single_line_newline_escapes(self):
        source = MEMORY_VIEW.read_text(encoding="utf-8")

        helper_start = source.index("function normalizeMemoryHoverText(")
        helper_end = source.index("function formatMemoryMetadataValue(", helper_start)
        helper = source[helper_start:helper_end]

        self.assertIn('.replace(/\\r\\n?/g, "\\n")', helper)
        self.assertIn('.replace(/\\\\r\\\\n|\\\\n|\\\\r/g, "\\n")', helper)
        self.assertIn("normalizeMemoryHoverText(value);", source)

        card_start = source.index("function buildMemoryDetailsHoverCard(")
        card_end = source.index("// Drafts are page-local", card_start)
        card_source = source[card_start:card_end]
        self.assertIn(
            "summary.textContent = normalizeMemoryHoverText(",
            card_source,
        )
        self.assertNotIn('.replace(/\\\\n/g, " ↵ ")', card_source)

    def test_hover_text_nodes_preserve_real_line_breaks(self):
        css = MEMORY_CSS.read_text(encoding="utf-8")

        summary_start = css.index(".runtime-memory-lt-hover-summary {")
        summary_end = css.index("}", summary_start)
        summary = css[summary_start:summary_end]
        self.assertIn("white-space: pre-wrap;", summary)

        metadata_start = css.index(".runtime-memory-lt-hover-metadata-value {")
        metadata_end = css.index("}", metadata_start)
        metadata = css[metadata_start:metadata_end]
        self.assertIn("white-space: pre-wrap;", metadata)


if __name__ == "__main__":
    unittest.main()
