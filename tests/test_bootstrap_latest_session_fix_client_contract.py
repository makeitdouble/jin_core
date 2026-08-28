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

    def test_bootstrap_reads_one_atomic_checkpoint(self):
        source = RUNTIME_SESSION_JS.read_text(encoding="utf-8")
        start = source.index("function getPersistedSessionBootstrap()")
        end = source.index("function clearPersistedSessionBootstrap()", start)
        block = source[start:end]

        self.assertIn("const checkpoint =", block)
        self.assertIn("readSessionCheckpoint()", block)
        self.assertIn("checkpoint.session_id", block)
        self.assertIn("checkpoint.runtime_memory", block)
        self.assertNotIn("runtimeCandidates", block)
        self.assertNotIn("collectOtherLatestRuntimeMemorySnapshots", block)

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
            persist.index("writeSessionCheckpoint({"),
        )
        self.assertEqual(persist.count("writeSessionCheckpoint({"), 1)
        self.assertIn("hasUnsavedSessionActivity = false", persist)


if __name__ == "__main__":
    unittest.main()
