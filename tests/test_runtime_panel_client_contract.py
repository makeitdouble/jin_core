from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PANEL_JS = ROOT / "ui" / "static" / "js" / "runtime" / "runtime-panel.js"
SOCKET_INPUT_JS = ROOT / "ui" / "static" / "js" / "socket" / "input.js"
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"


class RuntimePanelClientContractTests(unittest.TestCase):

    def test_service_tab_can_display_summarizer_usage_when_service_is_empty(self):
        source = RUNTIME_PANEL_JS.read_text(encoding="utf-8")

        self.assertIn(
            "function buildServiceRuntimeUsageFallback(",
            source,
        )
        self.assertIn(
            "runtimeHasUsage(serviceRuntime)",
            source,
        )
        self.assertIn(
            "runtimeHasUsage(summarizerRuntime)",
            source,
        )
        self.assertIn(
            "return getServiceRuntime();",
            source,
        )

    def test_submit_focuses_brain_context_tab(self):
        panel_source = RUNTIME_PANEL_JS.read_text(encoding="utf-8")
        input_source = SOCKET_INPUT_JS.read_text(encoding="utf-8")

        self.assertIn(
            "function focusBrainContextTab()",
            panel_source,
        )
        self.assertIn(
            "window.focusBrainContextTab = function ()",
            panel_source,
        )
        self.assertIn(
            "window.focusBrainContextTab();",
            input_source,
        )

    def test_cache_versions_are_bumped(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn(
            "/static/js/runtime/runtime-panel.js?v=runtime-panel-service-usage-1",
            source,
        )
        self.assertIn(
            "/static/js/socket/input.js?v=socket-input-memory-layer-toggle-brain-tab-1",
            source,
        )


if __name__ == "__main__":
    unittest.main()
