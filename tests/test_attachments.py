import unittest

from websocket import (
    format_attachment_context,
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

    def test_attachment_context_omits_text_preview_for_text_files(self):
        context = format_attachment_context({
            "attachments": [
                {
                    "name": "short.txt",
                    "kind": "text",
                    "type": "text/plain",
                    "size_label": "12 KB",
                    "text_preview": "do not send this preview",
                    "text_content": "full content stays available to skills",
                },
                {
                    "name": "README.md",
                    "kind": "text",
                    "type": "text/markdown",
                    "size_label": "304.8 KB",
                    "text_preview": "# Dictionary body",
                    "preview_limit": 2000,
                    "truncated": True,
                    "text_content": "full markdown stays available to skills",
                },
            ],
        })

        self.assertIn(
            "- short.txt: text, text/plain, 12 KB",
            context,
        )
        self.assertIn(
            "- README.md: text, text/markdown, 304.8 KB",
            context,
        )
        self.assertNotIn(
            "runtime_attachment",
            context,
        )
        self.assertNotIn(
            "text_preview",
            context,
        )
        self.assertNotIn(
            "do not send this preview",
            context,
        )
        self.assertNotIn(
            "# Dictionary body",
            context,
        )


if __name__ == "__main__":
    unittest.main()
