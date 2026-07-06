import unittest

from websocket import (
    redacted_attachment_for_log,
)


class AttachmentLogRedactionTests(unittest.TestCase):

    def test_redacted_attachment_for_log_redacts_full_text_content(self):
        redacted = redacted_attachment_for_log({
            "name": "notes.txt",
            "kind": "text",
            "text_preview": "visible preview",
            "text_content": "secret full text",
        })

        self.assertEqual(
            redacted["text_preview"],
            "visible preview",
        )
        self.assertNotIn(
            "secret full text",
            redacted["text_content"],
        )
        self.assertIn(
            "redacted text attachment content",
            redacted["text_content"],
        )


if __name__ == "__main__":
    unittest.main()
