from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MEMORY_VIEW_JS = (
    ROOT
    / "ui"
    / "static"
    / "js"
    / "runtime"
    / "runtime-memory-view.js"
)
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"


class RuntimeMemoryHoverTitleClientContractTests(unittest.TestCase):

    def test_hover_titles_live_outside_dom_until_mouseenter(self):
        source = MEMORY_VIEW_JS.read_text(encoding="utf-8")

        self.assertIn(
            "const runtimeMemoryHoverTitleSources = new WeakMap();",
            source,
        )
        self.assertIn(
            'node.addEventListener("mouseenter", () => {',
            source,
        )
        self.assertIn(
            'node.setAttribute("title", title);',
            source,
        )
        self.assertIn(
            'node.addEventListener("mouseleave", () => {',
            source,
        )
        self.assertIn(
            'node.removeAttribute("title");',
            source,
        )

    def test_runtime_memory_view_does_not_prepopulate_native_titles(self):
        source = MEMORY_VIEW_JS.read_text(encoding="utf-8")

        self.assertNotIn(".title =", source)
        self.assertEqual(
            source.count('setAttribute("title", title)'),
            1,
        )

    def test_row_hover_title_is_formatted_only_on_first_hover(self):
        source = MEMORY_VIEW_JS.read_text(encoding="utf-8")

        self.assertIn("let hoverTitle = null;", source)
        self.assertIn("if (hoverTitle === null) {", source)
        self.assertIn(
            "formatRuntimeMemoryHoverTitle(",
            source,
        )
        self.assertIn("row,", source)
        self.assertIn("() => {", source)
        self.assertNotIn(
            "bindRuntimeMemoryHoverTitle(\n        valueSpan,",
            source,
        )

    def test_memory_view_cache_key_is_bumped_for_hover_titles(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn("hover-title=1", source)


if __name__ == "__main__":
    unittest.main()
