import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE_CSS = ROOT / "ui" / "static" / "css" / "base.css"
CHAT_CSS = ROOT / "ui" / "static" / "css" / "chat.css"
CHAT_JS = ROOT / "ui" / "static" / "js" / "chat.js"
PANEL_INACTIVITY_JS = ROOT / "ui" / "static" / "js" / "panel-inactivity.js"
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"


class ChatReasoningSpacingClientContractTests(unittest.TestCase):

    def test_reasoning_bubbles_use_compact_default_gap(self):
        css = BASE_CSS.read_text(encoding="utf-8")

        self.assertIn("--chat-reasoning-gap: 0.28rem;", css)
        self.assertIn("--chat-action-adjacent-gap: 0.82rem;", css)
        self.assertIn(
            "#chat-history > .jin-stream-wrapper:has(> .jin-think-wrapper:last-child)\n"
            "+ .jin-stream-wrapper:has(> .jin-think-wrapper:first-child)",
            css,
        )

    def test_action_bubble_expands_reasoning_stack_only_at_action_boundary(self):
        css = BASE_CSS.read_text(encoding="utf-8")

        self.assertIn(
            "#chat-history > .jin-stream-wrapper:has(> .jin-think-wrapper:last-child)\n"
            "+ .jin-runtime-action-row",
            css,
        )
        self.assertIn(
            "#chat-history > .jin-runtime-action-row\n"
            "+ .jin-stream-wrapper:has(> .jin-think-wrapper:first-child)",
            css,
        )

    def test_stream_wrapper_uses_explicit_inner_gap_instead_of_tailwind_space(self):
        css = CHAT_CSS.read_text(encoding="utf-8")
        source = CHAT_JS.read_text(encoding="utf-8")

        self.assertIn(
            ".jin-stream-wrapper > :not([hidden]) ~ :not([hidden])",
            css,
        )
        self.assertIn("margin-top: var(--chat-inner-gap) !important;", css)
        self.assertIn(
            '"jin-stream-wrapper mx-auto w-full max-w-4xl";',
            source,
        )
        self.assertNotIn(
            "jin-stream-wrapper mx-auto w-full max-w-4xl space-y-3",
            source,
        )

    def test_chat_input_overlays_history_without_cropping_messages(self):
        css = BASE_CSS.read_text(encoding="utf-8")
        source = CHAT_JS.read_text(encoding="utf-8")

        self.assertIn("--chat-input-overlay-space: 5.35rem;", css)
        self.assertIn("+ var(--chat-input-overlay-space)", css)
        self.assertIn("#chat-input-shell::before", css)
        self.assertIn("position: absolute;", css)
        self.assertIn("pointer-events: none;", css)
        self.assertIn("backdrop-filter: blur(1.5px);", css)
        self.assertIn("mask-image:", css)
        self.assertIn("rgba(0, 0, 0, 0.22) 18px", css)
        self.assertIn("rgba(0, 0, 0, 1) 52px", css)
        self.assertIn("const chatInputShell =", source)
        self.assertIn("function updateChatInputOverlaySpace()", source)
        self.assertIn("new ResizeObserver", source)
        self.assertIn("- getChatInputOverlaySpace()", source)

    def test_chat_scrollbar_only_appears_while_scrolling(self):
        css = BASE_CSS.read_text(encoding="utf-8")
        source = PANEL_INACTIVITY_JS.read_text(encoding="utf-8")

        self.assertIn("width: 1px;", css)
        self.assertIn("#chat-history::-webkit-scrollbar", css)
        self.assertIn("scrollbar-color: transparent transparent;", css)
        self.assertIn(
            "scrollbar-color: rgba(39, 39, 42, 0.90) transparent;",
            css,
        )
        self.assertIn("#chat-history.jin-scrollbar-active", css)
        self.assertIn(".jin-scrollbar-active::-webkit-scrollbar-thumb", css)
        self.assertIn(
            'const TRANSIENT_SCROLLBAR_CLASS = "jin-scrollbar-active";',
            source,
        )
        self.assertIn('"#chat-history"', source)
        self.assertIn("const SCROLL_KEYS = new Set(", source)
        self.assertIn("transientScrollbarElements.add(element);", source)
        self.assertIn("markKnownTransientScrollbarsActive", source)
        self.assertIn('"wheel"', source)
        self.assertIn('"touchmove"', source)
        self.assertIn('"keydown"', source)
        self.assertIn('"scroll"', source)
        self.assertIn("TRANSIENT_SCROLLBAR_HIDE_MS", source)

    def test_cache_versions_are_bumped_for_reasoning_spacing_assets(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn("/static/css/base.css?v=jin-size-4", source)
        self.assertIn("/static/css/chat.css?v=reasoning-gap-1", source)
        self.assertIn("/static/js/chat.js?v=jin-size-1", source)
        self.assertIn(
            "/static/js/panel-inactivity.js?v=jin-size-1",
            source,
        )


if __name__ == "__main__":
    unittest.main()
