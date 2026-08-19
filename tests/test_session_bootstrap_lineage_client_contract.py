import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_STORAGE_JS = (
    ROOT
    / "ui"
    / "static"
    / "js"
    / "runtime"
    / "runtime-storage.js"
)
RUNTIME_SESSION_JS = (
    ROOT
    / "ui"
    / "static"
    / "js"
    / "runtime"
    / "runtime-session.js"
)


class SessionBootstrapLineageClientContractTests(unittest.TestCase):

    def test_session_save_uses_current_runtime_id_not_restored_facts_id(self):
        source = RUNTIME_SESSION_JS.read_text(encoding="utf-8")
        start = source.index("function getCurrentSavedSessionId()")
        end = source.index("function buildSessionSaveRuntimeSnapshot", start)
        block = source[start:end]

        self.assertIn("getCurrentRuntimeSessionId()", block)
        self.assertNotIn("getCurrentFactsMemorySessionId()", block)

    def test_normal_boot_prefers_latest_live_runtime_snapshot(self):
        source = RUNTIME_SESSION_JS.read_text(encoding="utf-8")
        start = source.index("function getPersistedSessionBootstrap()")
        end = source.index("function clearPersistedSessionBootstrap()", start)
        block = source[start:end]

        self.assertIn("readLatestPreviousRuntimeMemory()", block)
        self.assertIn("browserLatestRuntimeMemory", block)
        self.assertIn("saved_runtime.txt is a last-resort compatibility fallback", block)
        self.assertIn("if (!sessionText && !runtimeText)", block)

    def test_boot_materializes_current_session_as_next_direct_predecessor(self):
        source = RUNTIME_SESSION_JS.read_text(encoding="utf-8")
        start = source.index("function applyPersistedSessionBootstrap(bootstrap)")
        end = source.index("function getPersistedSessionBootstrap()", start)
        block = source[start:end]

        self.assertIn("cloneRuntimeMemoryToCurrentSession", block)
        self.assertIn("bootstrap.source_session_id", block)
        self.assertIn("bootstrap.runtime_memory", block)

    def test_live_runtime_snapshot_keeps_direct_predecessor_link(self):
        source = RUNTIME_STORAGE_JS.read_text(encoding="utf-8")

        self.assertIn("booted_from_session_id", source)
        self.assertIn("setBootSourceRuntimeSessionId", source)
        self.assertIn("readLatestPreviousRuntimeMemory", source)
        self.assertIn("collectOtherLatestRuntimeMemorySnapshots", source)
        self.assertIn("saved_at:\n        new Date().toISOString()", source)


if __name__ == "__main__":
    unittest.main()
