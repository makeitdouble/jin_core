from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_MEMORY_CSS = ROOT / "ui" / "static" / "css" / "runtime-memory.css"
CHAT_ATTACHMENTS_JS = ROOT / "ui" / "static" / "js" / "chat-attachments.js"
RUNTIME_JS = ROOT / "ui" / "static" / "js" / "runtime" / "runtime.js"
TRACE_MODAL_JS = ROOT / "ui" / "static" / "js" / "logger" / "trace-modal.js"
SESSION_ACTIONS_JS = ROOT / "ui" / "static" / "js" / "logger" / "session-actions.js"
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"


class DelayedMemoryPinnedGlowClientContractTests(unittest.TestCase):
    def test_pinned_delayed_memory_text_glow_is_stronger_in_panel_and_bubble(self):
        css_source = RUNTIME_MEMORY_CSS.read_text(encoding="utf-8")

        self.assertIn(".runtime-memory-delayed-row-pinned .runtime-memory-key", css_source)
        self.assertIn("0 0 24px rgba(16, 185, 129, 0.12)", css_source)
        self.assertIn(".jin-runtime-action-delayed-memory-pinned", css_source)

    def test_pinned_delayed_memory_bubbles_can_sync_after_modal_pin_toggle(self):
        attachments_source = CHAT_ATTACHMENTS_JS.read_text(encoding="utf-8")
        runtime_source = RUNTIME_JS.read_text(encoding="utf-8")

        self.assertIn("function applyDelayedMemoryReportPreviewState(", attachments_source)
        self.assertIn("function syncDelayedMemoryReportPreviewState(", attachments_source)
        self.assertIn('"jin-runtime-action-delayed-memory-pinned"', attachments_source)
        self.assertIn("window.syncDelayedMemoryReportPreviewState =", attachments_source)
        self.assertIn("window.syncDelayedMemoryReportPreviewState(", runtime_source)

    def test_modal_icon_sizes_are_bumped_for_close_and_pin_controls(self):
        css_source = RUNTIME_MEMORY_CSS.read_text(encoding="utf-8")
        trace_source = TRACE_MODAL_JS.read_text(encoding="utf-8")
        session_source = SESSION_ACTIONS_JS.read_text(encoding="utf-8")
        attachments_source = CHAT_ATTACHMENTS_JS.read_text(encoding="utf-8")

        self.assertIn("width: 31px;", css_source)
        self.assertIn("height: 31px;", css_source)
        self.assertIn("width: 18px;", css_source)
        self.assertIn("font-size: 23px;", css_source)
        self.assertIn("drop-shadow(0 0 16px rgba(153, 246, 228, 0.34))", css_source)
        self.assertIn('"delayed-memory-modal-icon-button delayed-memory-modal-close"', trace_source)
        self.assertIn('"delayed-memory-modal-icon-button delayed-memory-modal-close"', session_source)
        self.assertIn('"delayed-memory-modal-icon-button delayed-memory-modal-close shrink-0"', attachments_source)

    def test_cache_versions_are_bumped(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn("/static/css/runtime-memory.css?v=memory-reference-sync-1", source)
        self.assertIn("/static/js/runtime/runtime.js?v=runtime-facade-17", source)
        self.assertIn("/static/js/chat-attachments.js?v=chat-attachments-4", source)
        self.assertIn("/static/js/logger/trace-modal.js?v=l4-truncate-diagnostics-1", source)
        self.assertIn("/static/js/logger/session-actions.js?v=logger-session-actions-6", source)


if __name__ == "__main__":
    unittest.main()
