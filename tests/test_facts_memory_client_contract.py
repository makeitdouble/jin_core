import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FactsMemoryClientContractTests(unittest.TestCase):

    def test_facts_memory_uses_new_storage_namespace_without_legacy_aliases(self):
        source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "runtime"
            / "runtime-storage.js"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'const factsMemoryStorageKeyPrefix =\n    "jin.factsMemory";',
            source,
        )
        self.assertIn(
            "function isFactsMemoryStorageKey(",
            source,
        )
        self.assertIn(
            "function getSessionIdFromFactsMemoryStorageKey(",
            source,
        )
        self.assertNotIn(
            "migrateSessionSignalsStorageKeysToFactsMemory",
            source,
        )
        self.assertNotIn(
            "jin.sessionSignals.",
            source,
        )
        self.assertNotIn(
            "sessionSignalsStorageKeyPrefix",
            source,
        )
        self.assertNotIn(
            "getSessionSignalsStorageKey",
            source,
        )

    def test_facts_memory_can_be_rekeyed_only_when_current_snapshot_is_empty(self):
        source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "runtime"
            / "runtime-storage.js"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "function canAppendFactsMemoryByStorageKey(",
            source,
        )
        self.assertIn(
            "sourceSessionId === currentSessionId",
            source,
        )
        self.assertIn(
            "hasFactsMemoryForSession(currentSessionId)",
            source,
        )
        self.assertIn(
            "function appendFactsMemoryByStorageKey(",
            source,
        )
        self.assertIn(
            "writeBrowserMemory(\n      targetStorageKey,\n      signals",
            source,
        )
        self.assertIn(
            "removeBrowserMemory(\n      storageKey",
            source,
        )

    def test_facts_memory_logger_exposes_dynamic_append_action(self):
        source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "logger"
            / "log-entries.js"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "function refreshFactsMemoryAppendButtons()",
            source,
        )
        self.assertIn(
            'appendButton.textContent =\n        "append";',
            source,
        )
        self.assertIn(
            "storage.appendFactsMemoryByStorageKey(",
            source,
        )
        self.assertIn(
            "window.JinRuntime.runtime.renderRuntimeMemorySnapshot();",
            source,
        )
        self.assertIn(
            "storage.clearFactsMemoryByStorageKey",
            source,
        )

    def test_explicit_session_save_uses_active_facts_memory_session_id(self):
        source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "runtime"
            / "runtime-session.js"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "getCurrentFactsMemorySessionId,",
            source,
        )
        self.assertIn(
            "function getCurrentSavedSessionId()",
            source,
        )
        self.assertIn(
            "getCurrentFactsMemorySessionId()",
            source,
        )
        self.assertGreaterEqual(
            source.count("getCurrentSavedSessionId(),"),
            3,
        )
        self.assertIn(
            "function buildSessionSaveRuntimeSnapshot(snapshot)",
            source,
        )
        self.assertIn(
            "window.refreshFactsMemoryAppendButtons();",
            source,
        )


if __name__ == "__main__":
    unittest.main()
