from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
THEME_JS = ROOT / "ui" / "static" / "js" / "win95-theme.js"
TRACE_MODAL_JS = ROOT / "ui" / "static" / "js" / "logger" / "trace-modal.js"
SKIN_CSS = ROOT / "ui" / "static" / "css" / "chat-bamboo.css"
MEMORY_CSS = ROOT / "ui" / "static" / "css" / "runtime-memory.css"


class JinBubbleSkinClientContractTests(unittest.TestCase):

    def test_skin_is_persisted_and_theme_default_tracks_only_matching_skin(self):
        source = THEME_JS.read_text(encoding="utf-8")

        self.assertIn('const bubbleSkinKey = "jin_bubble_skin";', source)
        self.assertIn('const bubbleSkinPinnedKey = "jin_bubble_skin_pinned";', source)
        self.assertIn('dark: "jin-bubble-skin-dark"', source)
        self.assertIn('light: "jin-bubble-skin-light"', source)
        self.assertIn('bamboo: "jin-bubble-skin-bamboo"', source)
        self.assertIn('return win95Enabled ? "light" : "dark";', source)
        self.assertIn('pinned: normalized !== themeDefault', source)
        self.assertIn('if (!bubbleSkinPinned) {', source)
        self.assertIn('return bubbleSkinPinned;', source)
        self.assertIn('setBubbleSkin: setBubbleSkinFromUser', source)

    def test_all_three_skins_are_body_scoped_so_existing_bubbles_switch_live(self):
        css = SKIN_CSS.read_text(encoding="utf-8")

        for skin in ("dark", "light", "bamboo"):
            self.assertIn(f"body.jin-bubble-skin-{skin}", css)

        self.assertIn(
            "body.jin-bubble-skin-bamboo #chat-history .jin-chat-bubble-skin",
            css,
        )
        self.assertIn('border-image-source: url("/static/images/bamboo_bubble.png")', css)

    def test_context_modal_has_settings_card_and_tag_style_skin_picker(self):
        source = TRACE_MODAL_JS.read_text(encoding="utf-8")
        css = MEMORY_CSS.read_text(encoding="utf-8")

        self.assertIn('title: "SETTINGS"', source)
        self.assertIn('"jin_bubble_skin"', source)
        self.assertIn('"dark",\n  "light",\n  "bamboo"', source)
        self.assertIn('"delayed-memory-modal-tag jin-context-setting-tag"', source)
        self.assertIn('appearance.setBubbleSkin(normalized);', source)
        self.assertIn('.jin-context-setting-tag.is-active', css)
        self.assertIn('text-shadow:', css)


if __name__ == "__main__":
    unittest.main()
