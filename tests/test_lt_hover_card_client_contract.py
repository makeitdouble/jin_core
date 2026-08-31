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


class LTHoverCardClientContractTests(unittest.TestCase):

    def test_lt_rows_use_custom_hover_card_instead_of_native_title(self):
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
        self.assertNotIn("runtime-memory-lt-hover-icon", source)

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

    def test_hover_card_opens_away_from_panel_and_does_not_capture_pointer(self):
        source = MEMORY_VIEW.read_text(encoding="utf-8")
        css = MEMORY_CSS.read_text(encoding="utf-8")

        self.assertIn(
            "panelCenterX <= (viewportWidth / 2)",
            source,
        )
        self.assertIn(
            "panelRect.left - cardRect.width - gap",
            source,
        )
        self.assertIn(
            "panelRect.right + gap",
            source,
        )
        self.assertIn(
            'let placement = panelIsOnLeft ? "right" : "left";',
            source,
        )
        self.assertIn(
            "card.dataset.placement = placement;",
            source,
        )
        self.assertIn(
            '"--runtime-memory-lt-hover-arrow-y"',
            source,
        )
        self.assertIn(".runtime-memory-lt-hover-card {", css)
        self.assertIn("position: fixed;", css)
        self.assertIn("pointer-events: none;", css)
        self.assertIn(".runtime-memory-lt-hover-card::before", css)
        self.assertIn(
            '.runtime-memory-lt-hover-card[data-placement="right"]::before',
            css,
        )
        self.assertIn(
            '.runtime-memory-lt-hover-card[data-placement="right"]::after',
            css,
        )
        self.assertNotIn(".runtime-memory-lt-hover-icon", css)

    def test_scroll_retargets_hover_card_under_stationary_pointer(self):
        source = MEMORY_VIEW.read_text(encoding="utf-8")

        self.assertIn(
            "const longTermMemoryHoverRows = new WeakMap();",
            source,
        )
        self.assertIn(
            '".runtime-memory-line:hover"',
            source,
        )
        self.assertIn(
            "scheduleLongTermMemoryHoverCardScrollSync();",
            source,
        )
        self.assertNotIn(
            'memoryScroll.addEventListener("scroll", () => {\n'
            '      hideLongTermMemoryHoverCard();',
            source,
        )

    def test_active_rows_reuse_the_same_detail_hover_card(self):
        source = MEMORY_VIEW.read_text(encoding="utf-8")

        self.assertIn(
            "function buildMemoryDetailsHoverCard(",
            source,
        )
        self.assertIn(
            "} else if (options.interactiveActiveMemory) {\n"
            "        bindActiveMemoryHoverCard(\n"
            "            row,\n"
            "            line\n"
            "        );",
            source,
        )
        self.assertIn(
            '".runtime-memory-active-row:hover"',
            source,
        )
        self.assertIn(
            'valuePresentation.tags.forEach((tag) => {',
            source,
        )
        self.assertIn(
            '{ fallbackTitle: "Active memory" }',
            source,
        )

    def test_hover_card_assets_are_cache_busted(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertEqual(source.count("lt-hover-card=3"), 1)
        self.assertEqual(source.count("lt-hover-card=4"), 1)
        self.assertEqual(source.count("active-hover-card=1"), 1)


if __name__ == "__main__":
    unittest.main()
