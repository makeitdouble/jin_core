from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SESSION_ACTIONS_JS = ROOT / "ui" / "static" / "js" / "logger" / "session-actions.js"
CHAT_RUNTIME_ACTIONS_JS = ROOT / "ui" / "static" / "js" / "chat-runtime-actions.js"
SOCKET_RUNTIME_ACTIONS_JS = ROOT / "ui" / "static" / "js" / "socket" / "runtime-actions.js"


class MCPRuntimeUIContractTests(unittest.TestCase):
    def test_logger_renders_call_mcp_detail_inline_instead_of_title_hover(self):
        source = SESSION_ACTIONS_JS.read_text(encoding="utf-8")
        self.assertIn('normalizedActionName === "CALL_MCP"', source)
        self.assertIn('(isAttachmentAction || isCallMcpAction)', source)
        self.assertIn('isCallMcpAction\n        ? ""', source)

    def test_call_mcp_bubbles_receive_request_result_and_raw_payload(self):
        source = SOCKET_RUNTIME_ACTIONS_JS.read_text(encoding="utf-8")
        self.assertGreaterEqual(source.count("mcpRequest:"), 2)
        self.assertGreaterEqual(source.count("mcpResult:"), 2)
        self.assertGreaterEqual(source.count("mcpPayload:"), 2)

    def test_screenshot_reuses_attachment_preview_and_generic_mcp_uses_structured_modal(self):
        source = CHAT_RUNTIME_ACTIONS_JS.read_text(encoding="utf-8")
        self.assertIn('=== "get_viewport_screenshot"', source)
        self.assertIn("window.bindRuntimeActionAttachmentPreview(", source)
        self.assertIn("window.showMcpPayloadTrace(", source)
        self.assertIn('if (action === "call_mcp")', source)

        trace_source = (ROOT / "ui" / "static" / "js" / "logger" / "trace-modal.js").read_text(encoding="utf-8")
        self.assertIn("function renderMcpPayloadTrace(", trace_source)
        self.assertIn('title: "ARGUMENTS"', trace_source)
        self.assertIn("appendLTRequestFieldRows(", trace_source)


if __name__ == "__main__":
    unittest.main()
