import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SESSION_JS = (
    ROOT
    / "ui"
    / "static"
    / "js"
    / "runtime"
    / "runtime-session.js"
)
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"
WEBSOCKET_INIT = ROOT / "websocket" / "__init__.py"


class ReconnectPersistenceClientContractTests(unittest.TestCase):

    def test_soft_reconnect_carries_live_runtime_state_without_removed_l3_memory(self):

        source = RUNTIME_SESSION_JS.read_text(
            encoding="utf-8"
        )
        start = source.index(
            "function getSoftReconnectRuntimeResume()"
        )
        end = source.index(
            "function getInitialRuntimeMemoryBootstrap()",
            start,
        )
        block = source[start:end]

        self.assertIn(
            "runtime_memory: runtimeText,",
            block,
        )
        self.assertIn(
            "runtime_snapshot:",
            block,
        )
        self.assertIn(
            "loaded_memory_ids:",
            block,
        )
        self.assertNotIn(
            "session_memory:",
            block,
        )
        self.assertNotIn(
            "session_memory_updates:",
            block,
        )

    def test_backend_restart_is_not_treated_as_in_memory_soft_resume(self):

        source = WEBSOCKET_INIT.read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "soft_resume\n        and resumed_context",
            source.replace("\r\n", "\n"),
        )

    def test_runtime_session_cache_version_is_bumped(self):

        source = INDEX_HTML.read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "runtime-session.js?v=avatar-motion-1&delayed-load-contract-1-reconnect-persistence-1",
            source,
        )


if __name__ == "__main__":
    unittest.main()
