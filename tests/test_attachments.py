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

    def test_attachment_context_includes_full_text_for_text_files(self):
        context = format_attachment_context({
            "attachments": [
                {
                    "name": "short.txt",
                    "kind": "text",
                    "type": "text/plain",
                    "size_label": "12 KB",
                    "text_preview": "preview must not replace full text",
                    "text_content": "full text body",
                },
                {
                    "name": "README.md",
                    "kind": "text",
                    "type": "text/markdown",
                    "size_label": "3 KB",
                    "text_preview": "# Preview heading",
                    "text_content": "# Real heading\n\nMarkdown body.",
                },
            ],
        })

        self.assertIn(
            "- short.txt: text, text/plain, 12 KB",
            context,
        )
        self.assertIn(
            "full text body",
            context,
        )
        self.assertIn(
            "<FILE_CONTENT: README.md >",
            context,
        )
        self.assertIn(
            "# Real heading\n\nMarkdown body.",
            context,
        )
        self.assertNotIn(
            "preview must not replace full text",
            context,
        )
        self.assertNotIn(
            "# Preview heading",
            context,
        )

    def test_attachment_context_falls_back_to_preview_for_older_text_payloads(self):
        context = format_attachment_context({
            "attachments": [
                {
                    "name": "legacy.md",
                    "kind": "text",
                    "type": "text/markdown",
                    "text_preview": "legacy markdown body",
                },
            ],
        })

        self.assertIn(
            "legacy markdown body",
            context,
        )

    def test_attachment_text_context_has_shared_message_budget(self):
        context = format_attachment_context(
            {
                "attachments": [
                    {
                        "name": "one.md",
                        "kind": "text",
                        "type": "text/markdown",
                        "text_content": "abcdefgh",
                    },
                    {
                        "name": "two.md",
                        "kind": "text",
                        "type": "text/markdown",
                        "text_content": "ijklmnop",
                    },
                ],
            },
            max_text_chars=10,
        )

        self.assertIn(
            "abcdefgh",
            context,
        )
        self.assertIn(
            "ij",
            context,
        )
        self.assertNotIn(
            "klmnop",
            context,
        )
        self.assertIn(
            "[attachment text truncated: 6 chars omitted]",
            context,
        )


if __name__ == "__main__":
    unittest.main()
