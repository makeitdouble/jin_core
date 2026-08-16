import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"
BASE_CSS = ROOT / "ui" / "static" / "css" / "base.css"
SCROLL_TOP_JS = ROOT / "ui" / "static" / "js" / "panel-scroll-top.js"


class PanelScrollTopClientContractTests(unittest.TestCase):

    def test_scroll_top_script_is_loaded_and_threshold_is_300px(self):
        index_source = INDEX_HTML.read_text(encoding="utf-8")
        js_source = SCROLL_TOP_JS.read_text(encoding="utf-8")

        self.assertIn(
            'panel-scroll-top.js?v=2',
            index_source,
        )
        self.assertIn(
            'const SCROLL_THRESHOLD_PX = 300;',
            js_source,
        )
        self.assertIn(
            'scroller.scrollTop > SCROLL_THRESHOLD_PX',
            js_source,
        )

    def test_console_affordance_tracks_scroll_viewport_above_plaques(self):
        js_source = SCROLL_TOP_JS.read_text(encoding="utf-8")

        self.assertIn(
            'panelRect.bottom - scrollerRect.bottom - seamOverlap',
            js_source,
        )
        self.assertIn(
            'document.getElementById("attached-delayed-memory")',
            js_source,
        )
        self.assertIn(
            'document.getElementById("attached-files")',
            js_source,
        )


    def test_affordance_is_localized_to_bottom_right_without_inner_edge_seam(self):
        css_source = BASE_CSS.read_text(encoding="utf-8")
        js_source = SCROLL_TOP_JS.read_text(encoding="utf-8")

        self.assertIn(
            'right: -1px;',
            css_source,
        )
        self.assertIn(
            'width: 154px;',
            css_source,
        )
        self.assertIn(
            'right: 10px;',
            css_source,
        )
        self.assertNotIn(
            '--panel-scroll-top-left-offset',
            css_source,
        )
        self.assertNotIn(
            '--panel-scroll-top-right-offset',
            css_source,
        )
        self.assertIn(
            'const CONSOLE_SEAM_OVERLAP_PX = 2;',
            js_source,
        )

    def test_click_hides_control_and_scrolls_to_absolute_top(self):
        js_source = SCROLL_TOP_JS.read_text(encoding="utf-8")

        self.assertIn(
            'suppressWhileReturning = true;',
            js_source,
        )
        self.assertIn(
            'affordance.classList.remove("is-visible", "is-hovered");',
            js_source,
        )
        self.assertIn(
            'top: 0,',
            js_source,
        )
        self.assertIn(
            'behavior: reducedMotion ? "auto" : "smooth"',
            js_source,
        )

    def test_affordance_uses_soft_radial_dim_and_masked_blur(self):
        css_source = BASE_CSS.read_text(encoding="utf-8")

        self.assertIn(
            '.panel-scroll-top-affordance::before',
            css_source,
        )
        self.assertIn(
            'backdrop-filter: blur(10px) saturate(0.92);',
            css_source,
        )
        self.assertIn(
            'mask-image: radial-gradient(',
            css_source,
        )
        self.assertIn(
            '.panel-scroll-top-affordance.is-hovered',
            css_source,
        )


if __name__ == "__main__":
    unittest.main()
