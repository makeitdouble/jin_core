from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AttachmentUiContractTests(unittest.TestCase):

    def test_attachment_hover_title_uses_name_middle_dot_size(self):
        source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "chat-attachments.js"
        ).read_text(
            encoding="utf-8",
        )

        self.assertIn(
            "function formatAttachmentHoverTitle",
            source,
        )
        self.assertIn(
            '.filter(Boolean).join(" · ")',
            source,
        )
        self.assertIn(
            "element.title =\n    formatAttachmentHoverTitle(",
            source,
        )
        self.assertNotIn(
            "`Preview ${attachment.name}`",
            source,
        )

    def test_attachment_modal_info_starts_with_system_id(self):
        source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "chat-attachments.js"
        ).read_text(encoding="utf-8")

        self.assertIn("const systemId =", source)
        self.assertIn("attachment && attachment.id", source)
        self.assertIn("detailParts[0] = systemId;", source)


if __name__ == "__main__":
    unittest.main()
