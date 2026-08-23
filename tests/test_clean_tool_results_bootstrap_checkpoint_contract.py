import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SESSION_JS = (
    ROOT / "ui" / "static" / "js" / "runtime" / "runtime-session.js"
)
RUNTIME_ACTIONS_JS = (
    ROOT / "ui" / "static" / "js" / "socket" / "runtime-actions.js"
)
DISPATCHER_PY = ROOT / "utils" / "actions" / "dispatcher.py"


class CleanToolResultsBootstrapCheckpointContractTests(unittest.TestCase):

    def test_clean_only_mutates_tool_results_in_existing_browser_checkpoint(self):
        source = RUNTIME_SESSION_JS.read_text(encoding="utf-8")
        start = source.index("function clearPersistedToolResultsCheckpoint()")
        end = source.index("function buildCheckpointRuntimeSnapshot", start)
        block = source[start:end]

        self.assertIn("readLatestSavedSessionSnapshot()", block)
        self.assertIn("...previousCheckpoint", block)
        self.assertIn("...previousSessionSnapshot", block)
        self.assertIn("tool_results: []", block)
        self.assertNotIn("new Date().toISOString()", block)
        self.assertNotIn("saved_at:", block)
        self.assertNotIn("writeLatestSavedRuntimeMemory", block)

    def test_clean_runtime_action_does_not_rewrite_full_live_checkpoint(self):
        source = RUNTIME_ACTIONS_JS.read_text(encoding="utf-8")
        anchor = 'action === "clean_tool_results"'
        start = source.index(anchor)
        end = source.index("if (displayText.trim())", start)
        block = source[start:end]

        self.assertIn("clearPersistedToolResultsCheckpoint", block)
        self.assertNotIn("persistLiveSessionCheckpoint", block)
        self.assertNotIn("data.session_snapshot", block)

    def test_backend_clean_completion_no_longer_ships_full_session_snapshot(self):
        source = DISPATCHER_PY.read_text(encoding="utf-8")
        start = source.index('[RUNTIME ACTION] clean_tool_results requested')
        end = source.index("await emit_rejected_active_memory_results", start)
        block = source[start:end]

        self.assertNotIn("build_runtime_session_checkpoint", block)
        self.assertNotIn('"session_snapshot": session_snapshot', block)


if __name__ == "__main__":
    unittest.main()
