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


class BootstrapLatestSessionFixClientContractTests(unittest.TestCase):

    def test_bootstrap_selects_runtime_record_for_common_checkpoint_session(self):
        source = RUNTIME_SESSION_JS.read_text(encoding="utf-8")
        start = source.index("function getPersistedSessionBootstrap()")
        end = source.index("function clearPersistedSessionBootstrap()", start)
        block = source[start:end]

        self.assertIn("const checkpointSessionId =", block)
        self.assertIn("const runtimeCandidates = [", block)
        self.assertIn("browserLatestSavedRuntimeMemory", block)
        self.assertIn("latestCompletedConversationRuntime", block)
        self.assertIn("...(", block)
        self.assertIn("browserLatestRuntimeMemory", block)
        self.assertIn("runtimeCandidates.find(record => (", block)
        self.assertIn("=== checkpointSessionId", block)
        self.assertIn("if (!runtimeMemory && !conversationCheckpoint)", block)

    def test_stale_tab_cannot_rewind_global_bootstrap_pointer(self):
        source = RUNTIME_SESSION_JS.read_text(encoding="utf-8")
        persist_start = source.index("function persistLiveSessionCheckpoint(data)")
        persist_end = source.index(
            "function clearPersistedToolResultsCheckpoint()",
            persist_start,
        )
        persist = source[persist_start:persist_end]

        self.assertIn("const sessionMoved = Boolean(", persist)
        guard = "previousCheckpoint\n          && !sameSession\n          && !sessionMoved"
        self.assertIn(guard, persist)
        self.assertLess(
            persist.index(guard),
            persist.index("writeLatestSavedRuntimeMemory({"),
        )
        self.assertLess(
            persist.index(guard),
            persist.index("writeLatestSavedSessionSnapshot({"),
        )
        self.assertIn("hasUnsavedSessionActivity = false", persist)


if __name__ == "__main__":
    unittest.main()
