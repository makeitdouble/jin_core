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
MEMORY_CSS = ROOT / "ui" / "static" / "css" / "runtime-memory.css"
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"


class L4HoverCardClientContractTests(unittest.TestCase):

    def test_l4_rows_use_custom_hover_card_instead_of_native_title(self):
        source = MEMORY_VIEW.read_text(encoding="utf-8")

        self.assertIn(
            "if (options.interactiveLongTermMemory) {\n"
            "        bindLongTermMemoryHoverCard(\n"
            "            row,\n"
            "            line\n"
            "        );",
            source,
        )
        self.assertIn('row.removeAttribute("title");', source)
        self.assertIn('card.setAttribute("role", "tooltip");', source)
        self.assertNotIn("runtime-memory-l4-hover-icon", source)

    def test_hover_card_reads_the_same_value_and_metadata_used_by_old_title(self):
        source = MEMORY_VIEW.read_text(encoding="utf-8")

        self.assertIn(
            "memoryModel.splitMemoryMeta(line.value || \"\")",
            source,
        )
        self.assertIn("valuePresentation.text", source)
        self.assertIn("valuePresentation.tags.forEach((tag) => {", source)
        self.assertIn("String(tag && tag.key || \"\")", source)
        self.assertIn("String(tag && tag.value || \"\")", source)

    def test_hover_card_sits_left_of_panel_and_does_not_capture_pointer(self):
        source = MEMORY_VIEW.read_text(encoding="utf-8")
        css = MEMORY_CSS.read_text(encoding="utf-8")

        self.assertIn(
            "panelRect.left - cardRect.width - gap",
            source,
        )
        self.assertIn(
            '"--runtime-memory-l4-hover-arrow-y"',
            source,
        )
        self.assertIn(".runtime-memory-l4-hover-card {", css)
        self.assertIn("position: fixed;", css)
        self.assertIn("pointer-events: none;", css)
        self.assertIn(".runtime-memory-l4-hover-card::before", css)
        self.assertNotIn(".runtime-memory-l4-hover-icon", css)

    def test_hover_card_assets_are_cache_busted(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertEqual(source.count("l4-hover-card=2"), 2)


if __name__ == "__main__":
    unittest.main()
