from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MEMORY_VIEW_JS = ROOT / "ui" / "static" / "js" / "runtime" / "runtime-memory-view.js"
TRACE_MODAL_JS = ROOT / "ui" / "static" / "js" / "logger" / "trace-modal.js"


class DomLifecycleClientContractTests(unittest.TestCase):

    def test_memory_tab_switch_releases_previous_rows(self):
        source = MEMORY_VIEW_JS.read_text(encoding="utf-8")

        self.assertIn(
            "function releaseRuntimeMemoryDynamicDom(options = {})",
            source,
        )
        self.assertIn(
            "releaseRuntimeMemoryDynamicDom({\n          renderOnResume: false,",
            source,
        )
        self.assertIn(
            "runtimeMemoryText.replaceChildren();",
            source,
        )

    def test_avatar_mode_releases_dynamic_memory_dom_after_detach(self):
        source = MEMORY_VIEW_JS.read_text(encoding="utf-8")

        self.assertIn(
            "if (!isRuntimeMemoryViewDomConnected())",
            source,
        )
        self.assertIn(
            "releaseRuntimeMemoryDynamicDom({\n          renderOnResume: true,",
            source,
        )
        self.assertIn(
            "pendingRuntimeMemoryRender = true;",
            source,
        )

    def test_hidden_modals_release_heavy_payload_dom(self):
        memory_source = MEMORY_VIEW_JS.read_text(encoding="utf-8")
        trace_source = TRACE_MODAL_JS.read_text(encoding="utf-8")

        self.assertIn(
            "delayedMemoryModalContent.replaceChildren();",
            memory_source,
        )
        self.assertIn(
            "closeActiveDelayedMemoryAttachmentPicker();",
            memory_source,
        )
        self.assertIn(
            "traceModalContent.replaceChildren();",
            trace_source,
        )
        self.assertIn(
            'traceModalContextCopyText = "";',
            trace_source,
        )


if __name__ == "__main__":
    unittest.main()
