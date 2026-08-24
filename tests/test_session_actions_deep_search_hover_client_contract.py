from pathlib import Path
from types import SimpleNamespace
import unittest

from runtime.deep_web_search import _record_sequence_line


ROOT = Path(__file__).resolve().parents[1]
SESSION_ACTIONS_JS = (
    ROOT / "ui" / "static" / "js" / "logger" / "session-actions.js"
)
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"


class DeepSearchSessionActionHoverTests(unittest.IsolatedAsyncioTestCase):

    async def test_completion_history_keeps_full_deep_search_text_for_hover(self):
        context = SimpleNamespace(
            runtime_session_action_history=[],
            emitter=None,
        )

        await _record_sequence_line(
            context,
            "DEEP_WEB_SEARCH complete: 8/10 searches",
            hover_text=(
                "DEEP_WEB_SEARCH: Deep dive into Noir Jazz genres and "
                "essential albums."
            ),
        )

        self.assertEqual(
            context.runtime_session_action_history[-1]["parts"][0][
                "context_detail"
            ],
            (
                "DEEP_WEB_SEARCH: Deep dive into Noir Jazz genres and "
                "essential albums."
            ),
        )

    def test_client_uses_deep_search_context_detail_for_hover_title(self):
        source = SESSION_ACTIONS_JS.read_text(encoding="utf-8")

        self.assertIn(
            'String(part.context_detail || "").trim()',
            source,
        )
        self.assertIn(
            'normalizedActionName === "DEEP_WEB_SEARCH"',
            source,
        )
        self.assertIn(
            '? part.contextDetail',
            source,
        )
        self.assertIn(
            'action.title =\n        hoverText;',
            source,
        )
        self.assertIn(
            'context_detail: part.contextDetail',
            source,
        )

    def test_session_actions_cache_version_is_bumped(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn(
            '/static/js/logger/session-actions.js?v=logger-session-actions-13',
            source,
        )


if __name__ == "__main__":
    unittest.main()
