import unittest

from utils.context.messages import (
    build_previous_chat_messages_context_text,
)


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


if __name__ == "__main__":
    unittest.main()
