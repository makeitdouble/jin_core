from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_JS = ROOT / "ui" / "static" / "js" / "chat-reference-ids.js"
CHAT_JS = ROOT / "ui" / "static" / "js" / "chat.js"
CHAT_CSS = ROOT / "ui" / "static" / "css" / "chat.css"
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"


class ChatReferenceIdsClientContractTests(unittest.TestCase):

    def test_answer_ids_resolve_only_against_live_file_and_delayed_stores(self):
        source = REFERENCE_JS.read_text(encoding="utf-8")

        self.assertIn("window.JinFiles.getFiles()", source)
        self.assertIn("window.JinRuntime.runtime", source)
        self.assertIn("runtime.getDelayedMemoryReports()", source)
        self.assertIn('kind: "file"', source)
        self.assertIn('kind: "delayed"', source)
        self.assertIn('references.has(id)', source)
        self.assertIn('new RegExp(`\\\\b(?:${ids.map(escapeRegex).join("|")})\\\\b`', source)

    def test_image_ids_use_existing_hover_preview_and_attachment_modal(self):
        source = REFERENCE_JS.read_text(encoding="utf-8")

        self.assertIn("window.bindJinAttachmentHoverPreview", source)
        self.assertIn("{ hoverPreviewMaxPx: 100 }", source)
        self.assertIn("window.openJinAttachmentModal(reference.record)", source)

    def test_text_ids_show_clean_filename_and_delayed_ids_open_report_modal(self):
        source = REFERENCE_JS.read_text(encoding="utf-8")

        self.assertIn("cleanPersistentFileName", source)
        self.assertIn('element.title = cleanPersistentFileName(reference.record) || reference.id;', source)
        self.assertIn("memoryView.openDelayedMemoryReportModal(reference.record)", source)
        self.assertIn("reference.record && reference.record.title", source)

    def test_stream_render_decorates_ids_without_replacing_chat_parser(self):
        source = CHAT_JS.read_text(encoding="utf-8")

        self.assertIn("window.JinChatReferenceIds.decorate", source)
        self.assertIn("renderChatTextHtml", source)

    def test_reference_ids_have_dark_and_light_theme_treatment(self):
        source = CHAT_CSS.read_text(encoding="utf-8")

        self.assertIn(".jin-chat-reference-id {", source)
        self.assertIn("font-weight: 700;", source)
        self.assertIn("body.theme-win95 .jin-chat-reference-id {", source)

    def test_reference_parser_is_loaded_before_chat_renderer(self):
        source = INDEX_HTML.read_text(encoding="utf-8")
        reference_script = '/static/js/chat-reference-ids.js?v=reference-ids-1'
        chat_script = '/static/js/chat.js?v='

        self.assertIn(reference_script, source)
        self.assertLess(source.index(reference_script), source.index(chat_script))


if __name__ == "__main__":
    unittest.main()
