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

    def test_soft_reconnect_carries_saved_session_state(self):

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
            "getPersistedSessionBootstrap()",
            block,
        )
        self.assertIn(
            "session_memory:",
            block,
        )
        self.assertIn(
            "session_memory_updates:",
            block,
        )
        self.assertIn(
            "loaded_memory_ids:",
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
            "runtime-session.js?v=delayed-load-contract-1-reconnect-persistence-1",
            source,
        )


if __name__ == "__main__":
    unittest.main()
