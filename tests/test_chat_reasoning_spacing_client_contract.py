import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE_CSS = ROOT / "ui" / "static" / "css" / "base.css"
CHAT_CSS = ROOT / "ui" / "static" / "css" / "chat.css"
CHAT_JS = ROOT / "ui" / "static" / "js" / "chat.js"
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

    def test_cache_versions_are_bumped_for_reasoning_spacing_assets(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn("/static/css/base.css?v=chat-input-overlay-2", source)
        self.assertIn("/static/css/chat.css?v=reasoning-gap-1", source)
        self.assertIn("/static/js/chat.js?v=chat-input-overlay-1", source)


if __name__ == "__main__":
    unittest.main()
