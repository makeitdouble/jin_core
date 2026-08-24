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

    def test_bootstrap_prefers_newest_per_session_runtime_over_global_pointer(self):
        source = RUNTIME_SESSION_JS.read_text(encoding="utf-8")
        start = source.index("function getPersistedSessionBootstrap()")
        end = source.index("function clearPersistedSessionBootstrap()", start)
        block = source[start:end]

        selection_start = block.index("let runtimeMemory =")
        selection_end = block.index("if (!runtimeMemory)", selection_start)
        selection = block[selection_start:selection_end]

        self.assertLess(
            selection.index("browserLatestRuntimeMemory"),
            selection.index("browserLatestSavedRuntimeMemory"),
        )
        self.assertIn(
            "compatibility fallback when no per-session predecessor exists",
            block,
        )

    def test_stale_tab_cannot_rewind_global_bootstrap_pointer(self):
        source = RUNTIME_SESSION_JS.read_text(encoding="utf-8")
        helper_start = source.index(
            "function isCurrentRuntimeCheckpointFreshest("
        )
        helper_end = source.index(
            "function prefersReducedSceneTintMotion()",
            helper_start,
        )
        helper = source[helper_start:helper_end]

        self.assertIn("collectOtherLatestRuntimeMemorySnapshots()", helper)
        self.assertIn("return otherSavedAt > currentSavedAt", helper)

        persist_start = source.index("function persistLiveSessionCheckpoint(data)")
        persist_end = source.index(
            "function clearPersistedToolResultsCheckpoint()",
            persist_start,
        )
        persist = source[persist_start:persist_end]

        guard = "if (!isCurrentRuntimeCheckpointFreshest(currentRuntime))"
        self.assertIn(guard, persist)
        self.assertLess(
            persist.index(guard),
            persist.index("writeLatestSavedRuntimeMemory({"),
        )
        self.assertLess(
            persist.index(guard),
            persist.index("writeLatestSavedSessionSnapshot({"),
        )


if __name__ == "__main__":
    unittest.main()
