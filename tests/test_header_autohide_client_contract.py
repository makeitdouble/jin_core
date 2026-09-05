from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"
BASE_CSS = ROOT / "ui" / "static" / "css" / "base.css"
HEADER_JS = ROOT / "ui" / "static" / "js" / "header-autohide.js"
LOGGER_JS = ROOT / "ui" / "static" / "js" / "logger" / "logger.js"


class HeaderAutoHideClientContractTests(unittest.TestCase):

    def test_header_is_hidden_by_default_and_revealed_with_a_body_class(self):
        css = BASE_CSS.read_text(encoding="utf-8")

        self.assertIn(
            "transform: translate3d(0, -100%, 0);",
            css,
        )
        self.assertIn(
            "body.app-header-visible #app-header",
            css,
        )
        self.assertIn(
            "transform: translate3d(0, var(--app-header-panel-shift), 0);",
            css,
        )

    def test_hover_zone_is_two_header_heights_and_only_colliding_panels_shift(self):
        source = HEADER_JS.read_text(encoding="utf-8")

        self.assertIn(
            "revealZoneHeight = headerHeight * 2;",
            source,
        )
        self.assertIn(
            "clearanceBottom - logicalTop",
            source,
        )
        self.assertIn(
            'const panels = [\n        consolePanel,\n        memoryPanel,',
            source,
        )

    def test_header_waits_one_second_before_hiding_after_hover_leaves(self):
        source = HEADER_JS.read_text(encoding="utf-8")

        self.assertIn(
            "const HIDE_DELAY_MS = 1000;",
            source,
        )
        self.assertIn(
            "window.setTimeout(() => {",
            source,
        )
        self.assertIn(
            "cancelPendingHide();",
            source,
        )

    def test_header_requires_333ms_hover_before_revealing(self):
        source = HEADER_JS.read_text(encoding="utf-8")

        self.assertIn(
            "const SHOW_DELAY_MS = 333;",
            source,
        )
        self.assertIn(
            "scheduleReveal();",
            source,
        )
        self.assertIn(
            "cancelPendingReveal();",
            source,
        )
        self.assertIn(
            "}, SHOW_DELAY_MS);",
            source,
        )

    def test_panels_occlude_the_hidden_header_hover_catch_zone(self):
        source = HEADER_JS.read_text(encoding="utf-8")

        self.assertIn(
            "let pointerOccludedByPanel = false;",
            source,
        )
        self.assertIn(
            "function pointerIsOnOccludingPanel(target)",
            source,
        )
        self.assertIn(
            "panels.some((panel) => panel.contains(target))",
            source,
        )
        self.assertIn(
            "!pointerOccludedByPanel",
            source,
        )
        self.assertIn(
            "pointerOccludedByPanel = pointerIsOnOccludingPanel(target);",
            source,
        )

    def test_chat_content_occludes_the_hidden_header_hover_catch_zone(self):
        source = HEADER_JS.read_text(encoding="utf-8")

        self.assertIn(
            'const chatHistory = document.getElementById("chat-history");',
            source,
        )
        self.assertIn(
            "let pointerOccludedByChatContent = false;",
            source,
        )
        self.assertIn(
            "function pointerIsOnChatContent(target)",
            source,
        )
        for selector in (
            ".jin-chat-avatar",
            ".jin-chat-bubble",
            ".jin-message-copy-control",
            ".jin-think-content",
            ".jin-runtime-action-row > *",
            ".jin-session-restore-divider",
        ):
            self.assertIn(selector, source)
        self.assertIn(
            "&& !pointerOccludedByChatContent",
            source,
        )
        self.assertIn(
            "pointerOccludedByChatContent = pointerIsOnChatContent(target);",
            source,
        )

    def test_temporary_header_shift_does_not_pollute_saved_room_geometry(self):
        source = LOGGER_JS.read_text(encoding="utf-8")

        self.assertIn(
            "function getHeaderAutoHidePanelShift(panel)",
            source,
        )
        self.assertIn(
            "- headerShift",
            source,
        )

    def test_header_controller_is_loaded_after_panel_controller(self):
        source = INDEX_HTML.read_text(encoding="utf-8")
        logger_index = source.index("/static/js/logger/logger.js")
        header_index = source.index("/static/js/header-autohide.js")

        self.assertLess(logger_index, header_index)


if __name__ == "__main__":
    unittest.main()
