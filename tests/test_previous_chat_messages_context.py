import unittest
from types import SimpleNamespace

from utils.context.messages import (
    build_previous_chat_messages_context_text,
)
from websocket.messages import append_interrupted_runtime_recent_turn


class PreviousChatMessagesContextTests(unittest.TestCase):

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
