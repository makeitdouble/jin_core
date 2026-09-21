import unittest
from unittest.mock import patch
from types import SimpleNamespace

from utils.context.messages import (
    build_previous_chat_messages_context,
    build_previous_chat_messages_context_text,
)
from utils.context.session_actions import build_session_actions_history_context
from utils.session_actions_history import upsert_session_action_marker_history_since
from websocket.messages import (
    append_interrupted_runtime_recent_turn,
    append_runtime_recent_turn,
)


class PreviousChatMessagesContextTests(unittest.TestCase):

    def test_projects_executed_actions_as_timestamped_jin_messages(self):
        context = SimpleNamespace(
            session_id="session-1",
            runtime_restored_session_dialog="",
            runtime_current_sequence_jin_messages=[],
            runtime_recent_turns=[{
                "user": "помигай своим цветом",
                "jin": "",
                "runtime_turn_id": "turn-7",
                "user_created_at": 100.0,
            }],
            runtime_session_action_history=[],
            runtime_current_sequence_turn_id="turn-7",
            runtime_action_events=[],
        )

        colors = [
            "#00f2ff",
            "#ff00cc",
            "#00f2ff",
            "#ff00cc",
            "#00f2ff",
        ]
        with patch(
            "utils.session_actions_history.time.time",
            return_value=110.0,
        ):
            self.assertTrue(
                upsert_session_action_marker_history_since(
                    context,
                    0,
                    [{
                        "name": "JIN_COLOR",
                        "marker_count": 5,
                        "payloads": colors,
                        "raw_payloads": colors,
                        "colors": colors,
                    }],
                )
            )

        with patch(
            "utils.context.messages.time.time",
            return_value=170.0,
        ):
            context_text = build_previous_chat_messages_context(context)

        self.assertIn("<USER>помигай своим цветом", context_text)
        self.assertIn(
            (
                "<JIN>JIN_COLOR: #00f2ff, JIN_COLOR: #ff00cc, "
                "JIN_COLOR: #00f2ff, JIN_COLOR: #ff00cc, "
                "JIN_COLOR: #00f2ff ( 1m ago )"
            ),
            context_text,
        )

        with patch(
            "utils.context.session_actions.time.time",
            return_value=170.0,
        ):
            session_actions = build_session_actions_history_context(context)

        self.assertIn(
            (
                "1. JIN_COLOR: #00f2ff, JIN_COLOR: #ff00cc, "
                "JIN_COLOR: #00f2ff, JIN_COLOR: #ff00cc, "
                "JIN_COLOR: #00f2ff ( 1m ago )"
            ),
            session_actions,
        )
        self.assertNotIn("count: 5", session_actions)

    def test_does_not_project_actions_from_another_runtime_turn(self):
        context = SimpleNamespace(
            session_id="session-1",
            runtime_restored_session_dialog="",
            runtime_current_sequence_jin_messages=[],
            runtime_recent_turns=[{
                "user": "current request",
                "jin": "visible answer",
                "runtime_turn_id": "turn-2",
            }],
            runtime_session_action_history=[{
                "text": "SAVE_ACTIVE_MEMORY - stale",
                "created_at": 110.0,
                "runtime_turn_id": "turn-1",
                "session_id": "session-1",
            }],
        )

        context_text = build_previous_chat_messages_context(context)

        self.assertNotIn("SAVE_ACTIVE_MEMORY", context_text)
        self.assertIn("<JIN>visible answer", context_text)

    def test_recent_turn_keeps_runtime_turn_identity_for_action_projection(self):
        context = SimpleNamespace(
            runtime_recent_turns=[],
            runtime_restored_session_dialog="",
            runtime_current_sequence_turn_id="turn-9",
            runtime_turn_jin_reaction="",
        )

        append_runtime_recent_turn(
            context,
            user_message="save it",
            assistant_message="",
        )

        self.assertEqual(
            context.runtime_recent_turns[0]["runtime_turn_id"],
            "turn-9",
        )

    def test_preserves_complete_recent_messages_without_character_crop(self):

        user_text = "u" * 500
        jin_text = "j" * 700

        context_text = build_previous_chat_messages_context_text([
            {
                "user": user_text,
                "jin": jin_text,
            },
        ])

        self.assertIn(
            f"<USER>{user_text}",
            context_text,
        )
        self.assertIn(
            f"<JIN>{jin_text}",
            context_text,
        )

    def test_preserves_full_text_while_escaping_physical_newlines(self):

        user_text = "first line\n" + ("x" * 400) + "\nlast line"

        context_text = build_previous_chat_messages_context_text([
            {
                "user": user_text,
                "jin": "ok",
            },
        ])

        self.assertIn(
            "<USER>first line\\n" + ("x" * 400) + "\\nlast line",
            context_text,
        )

    def test_interrupted_user_turn_stays_in_previous_chat_history(self):

        context = SimpleNamespace(
            runtime_recent_turns=[
                {
                    "user": "older user",
                    "jin": "older jin",
                },
            ],
            runtime_turn_jin_reaction="",
            runtime_restored_session_dialog="",
            runtime_restored_session_source_id="",
        )

        append_interrupted_runtime_recent_turn(
            context,
            user_message="inspect agent/runtime.py",
            reasoning="action traversal in progress",
            user_created_at=123.0,
        )

        self.assertEqual(
            context.runtime_recent_turns[-1]["user"],
            "inspect agent/runtime.py",
        )
        self.assertEqual(
            context.runtime_recent_turns[-1]["jin"],
            "",
        )
        self.assertEqual(
            context.runtime_recent_turns[-1]["reasoning"],
            "action traversal in progress",
        )

        context_text = build_previous_chat_messages_context_text(
            context.runtime_recent_turns
        )
        self.assertIn("<USER>older user", context_text)
        self.assertIn("<JIN>older jin", context_text)
        self.assertIn("<USER>inspect agent/runtime.py", context_text)



if __name__ == "__main__":
    unittest.main()
