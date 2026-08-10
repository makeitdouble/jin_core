from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
ANSWER_RATING_JS = ROOT / "ui" / "static" / "js" / "answer-rating.js"
RUNTIME_FEEDBACK_JS = ROOT / "ui" / "static" / "js" / "runtime" / "runtime-feedback.js"
CHAT_RATING_CSS = ROOT / "ui" / "static" / "css" / "chat-rating.css"
THEME_WIN95_CSS = ROOT / "ui" / "static" / "css" / "theme-win95.css"
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"


class AnswerRatingClientContractTests(unittest.TestCase):

    def test_submit_commit_preserves_selected_rating_visual_state(self):
        source = ANSWER_RATING_JS.read_text(encoding="utf-8")

        self.assertIn("const ratingPressClasses = [", source)
        self.assertIn(
            "const waitingForL1 = !blocked && !pastTurn && !l1Ready;",
            source,
        )
        self.assertIn(
            'bubble.classList.toggle("jin-rating-l1-waiting", waitingForL1);',
            source,
        )
        self.assertIn("bubble.classList.remove(...ratingPressClasses);", source)
        self.assertIn('bubble.dataset.ratingCommitted = "true";', source)
        self.assertIn('bubble.dataset.ratingPastTurn = "true";', source)
        self.assertNotIn(
            "delete bubble.dataset.ratingSelected;\n                    clearBubbleRatingIntensity",
            source,
        )

    def test_runtime_gate_lock_does_not_clear_committed_rating_visuals(self):
        source = RUNTIME_FEEDBACK_JS.read_text(encoding="utf-8")

        self.assertIn("const ratingLockedTransientClasses = [", source)
        self.assertNotIn("const ratingLockedVisualClasses = [", source)
        self.assertNotIn("delete bubble.dataset.ratingSelected;", source)
        self.assertNotIn("delete bubble.dataset.ratingClickAlt;", source)
        self.assertNotIn("bubble.removeAttribute(\"aria-label\");", source)

    def test_committed_selected_rating_still_uses_selected_css(self):
        source = CHAT_RATING_CSS.read_text(encoding="utf-8")

        self.assertIn(".jin-chat-bubble-rateable.jin-rating-selected-minus {", source)
        self.assertIn(".jin-chat-bubble-rateable.jin-rating-selected-plus {", source)
        self.assertIn(
            ".jin-chat-bubble-rateable.jin-rating-committed .jin-rating-zone",
            source,
        )
        self.assertNotIn(
            ".jin-chat-bubble-rateable.jin-rating-selected-minus:not(.jin-rating-committed)",
            source,
        )
        self.assertNotIn(
            ".jin-chat-bubble-rateable.jin-rating-selected-plus:not(.jin-rating-committed)",
            source,
        )

    def test_win95_theme_keeps_selected_rules_for_committed_bubbles(self):
        source = THEME_WIN95_CSS.read_text(encoding="utf-8")

        self.assertIn(
            "body.theme-win95 .jin-chat-bubble-rateable.jin-rating-selected-minus,",
            source,
        )
        self.assertIn(
            "body.theme-win95 .jin-chat-bubble-rateable.jin-rating-selected-plus {",
            source,
        )

    def test_cache_versions_are_bumped_for_rating_assets(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn("/static/css/chat-rating.css?v=rating-persist-1", source)
        self.assertIn("/static/css/theme-win95.css?v=delayed-context-loaded-1", source)
        self.assertIn("/static/js/answer-rating.js?v=answer-rating-persist-1", source)
        self.assertIn(
            "/static/js/runtime/runtime-feedback.js?v=runtime-feedback-persist-1",
            source,
        )


if __name__ == "__main__":
    unittest.main()
