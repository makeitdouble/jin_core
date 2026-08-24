from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CHAT_JS = ROOT / "ui" / "static" / "js" / "chat.js"
SOCKET_JS = ROOT / "ui" / "static" / "js" / "socket.js"
INPUT_JS = ROOT / "ui" / "static" / "js" / "socket" / "input.js"
ANSWER_RATING_JS = ROOT / "ui" / "static" / "js" / "answer-rating.js"
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"


class UiFixBundleContractTests(unittest.TestCase):

    def test_reasoning_uses_latest_manual_collapsed_state(self):
        source = CHAT_JS.read_text(encoding="utf-8")

        self.assertIn("let jinThinkCollapsedPreference = true;", source)
        self.assertIn("const initialThinkCollapsed =", source)
        self.assertIn("jinThinkCollapsedPreference =", source)
        self.assertIn("persist: true", source)

    def test_live_turn_releases_top_lock_and_autoscrolls_on_overflow(self):
        source = CHAT_JS.read_text(encoding="utf-8")

        self.assertIn("function liveUserTurnReachedViewportBottom()", source)
        self.assertIn("metrics.bottomSpace <= 1", source)
        self.assertIn("if (liveUserTurnReachedViewportBottom()) {", source)
        self.assertIn("releaseLiveUserTurnTopLock();", source)
        self.assertIn("liveTurnOverflowAutoscroll =", source)

    def test_reasoning_collapse_keeps_live_turn_viewport_stable(self):
        source = CHAT_JS.read_text(encoding="utf-8")

        self.assertIn(
            "function syncLiveUserTurnViewportForLayoutChange()",
            source,
        )
        self.assertIn(
            "syncLiveUserTurnViewportForLayoutChange();",
            source,
        )
        self.assertIn(
            "thinkContent.scrollTop =\n    thinkContent.scrollHeight;",
            source,
        )
        self.assertNotIn('behavior: "smooth"', source)

    def test_input_focus_and_form_padding_click(self):
        socket_source = SOCKET_JS.read_text(encoding="utf-8")
        input_source = INPUT_JS.read_text(encoding="utf-8")

        self.assertIn("function focusJinUserInput(", socket_source)
        self.assertIn("if (!active) {", socket_source)
        self.assertIn("focusJinUserInput({", socket_source)
        self.assertIn("function focusChatInputFromFormPointer(", input_source)
        self.assertIn('chatForm.addEventListener(\n  "mousedown",', input_source)

    def test_rating_hover_is_directional_and_bubble_has_no_count_title(self):
        source = ANSWER_RATING_JS.read_text(encoding="utf-8")

        self.assertIn('minus: "Dislike answer"', source)
        self.assertIn('plus: "Like answer"', source)
        self.assertIn("syncBubbleRatingZoneTitles(bubble);", source)
        click_alt_block = source[
            source.index("function setBubbleRatingClickAlt"):
            source.index("function clearBubbleRatingIntensity")
        ]
        self.assertIn('bubble.removeAttribute("title");', click_alt_block)
        self.assertNotIn('bubble.setAttribute("title", label);', click_alt_block)

    def test_cache_busters_cover_updated_ui_files(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn("&hover-labels=2", source)
        self.assertIn(
            "&reasoning-state=1&live-turn-overflow-scroll=2",
            source,
        )
        self.assertIn("&reasoning-collapse-stability=1", source)
        self.assertIn("&input-focus=2", source)
        self.assertIn("&input-focus=3", source)


if __name__ == "__main__":
    unittest.main()
