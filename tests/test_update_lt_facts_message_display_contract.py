from pathlib import Path
from types import SimpleNamespace
import unittest

from utils.context.session_actions import build_session_actions_history_context
from utils.session_actions_history import (
    build_session_actions_update_items,
    replace_session_action_history_since,
)


ROOT = Path(__file__).resolve().parents[1]
SESSION_ACTIONS_JS = ROOT / "ui" / "static" / "js" / "logger" / "session-actions.js"
SOCKET_RUNTIME_ACTIONS_JS = ROOT / "ui" / "static" / "js" / "socket" / "runtime-actions.js"
LOG_ENTRIES_JS = ROOT / "ui" / "static" / "js" / "logger" / "log-entries.js"
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"


class UpdateLTFactsMessageDisplayContractTests(unittest.TestCase):

    def test_session_actions_and_context_keep_full_update_message(self):
        message = (
            "Update F96: The system uses a dual-machine architecture where "
            "Gemma 26b a4b is the current active brain, and Qwen 3.8 27b is "
            "designated as the night brain model."
        )
        payload = (
            '{"fact_ids":["F96"],"message":"'
            + message
            + '"}'
        )
        context = SimpleNamespace(
            runtime_session_action_history=[],
            runtime_current_turn_id="turn-1",
        )

        replace_session_action_history_since(
            context,
            0,
            [{
                "name": "UPDATE_LT_FACTS",
                "payloads": [payload],
                "raw_payloads": [payload],
                "marker_count": 1,
            }],
        )

        item = build_session_actions_update_items(
            context,
            current_sequence=False,
        )[0]

        self.assertEqual(
            item["parts"],
            [{
                "text": "UPDATE_LT_FACTS",
                "message": message,
            }],
        )
        self.assertEqual(
            item["text"],
            f"UPDATE_LT_FACTS: {message}",
        )
        self.assertIn(
            f"UPDATE_LT_FACTS: {message}",
            build_session_actions_history_context(
                context,
                current_sequence=False,
            ),
        )

    def test_session_actions_ui_renders_message_and_uses_it_as_hover_text(self):
        source = SESSION_ACTIONS_JS.read_text(encoding="utf-8")

        self.assertIn('String(part.message || "").trim()', source)
        self.assertIn('`: ${part.message}`', source)
        self.assertIn('part.message\n      || part.detail', source)
        self.assertIn('message: part.message,', source)

    def test_chat_bubble_and_logger_tooltips_use_update_message(self):
        socket_source = SOCKET_RUNTIME_ACTIONS_JS.read_text(encoding="utf-8")
        logger_source = LOG_ENTRIES_JS.read_text(encoding="utf-8")

        self.assertIn('function getUpdateLTFactsMessage(data)', socket_source)
        self.assertIn('`${getRuntimeActionDisplayName(data, action)}: `', socket_source)
        self.assertIn('updateLTFactsMessage\n      || buildRuntimeActionDetail(', socket_source)
        self.assertIn('function getInternalActionUpdateLTMessage(data)', logger_source)
        self.assertIn('logDiv.title =\n      updateLTMessage || jinSizeHover;', logger_source)

    def test_cache_versions_are_bumped(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn('/static/js/logger/session-actions.js?v=logger-session-actions-13', source)
        self.assertIn('/static/js/logger/log-entries.js?v=update-lt-message-1', source)
        self.assertIn('/static/js/socket/runtime-actions.js?v=size-sequence-1', source)


if __name__ == "__main__":
    unittest.main()
