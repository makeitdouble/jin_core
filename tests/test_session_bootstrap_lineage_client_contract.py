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
SESSION_RESTORE_JS = (
    ROOT
    / "ui"
    / "static"
    / "js"
    / "session-restore.js"
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

    def test_boot_color_prefers_common_checkpoint_then_action_fallback(self):
        source = RUNTIME_SESSION_JS.read_text(encoding="utf-8")
        resolver_start = source.index("function resolveBootstrapJinColor(")
        resolver_end = source.index(
            "function applyBootstrapSceneTintShift(",
            resolver_start,
        )
        resolver = source[resolver_start:resolver_end]

        self.assertLess(
            resolver.index("resolvePersistedJinColor()"),
            resolver.index("source.session_actions"),
        )
        self.assertLess(
            resolver.index("source.session_actions"),
            resolver.index("source.current_jin_color"),
        )
        self.assertIn("readLatestSavedSessionSnapshot()", source)
        self.assertIn('toUpperCase() !== "JIN_COLOR"', resolver)
        self.assertIn("part.colors", resolver)

        apply_start = source.index(
            "function applyPersistedSessionBootstrap(bootstrap)"
        )
        apply_end = source.index(
            "function getPersistedSessionBootstrap()",
            apply_start,
        )
        apply_block = source[apply_start:apply_end]
        self.assertIn("resolveBootstrapRoomState(bootstrap)", apply_block)
        self.assertIn("delete localRoomState.avatar.color;", apply_block)
        self.assertNotIn("applyBootstrapSceneTintShift(", apply_block)

    def test_early_room_restore_uses_common_checkpoint_color(self):
        runtime_source = RUNTIME_SESSION_JS.read_text(encoding="utf-8")
        helper_start = runtime_source.index(
            "function resolveBootstrapRoomState("
        )
        helper_end = runtime_source.index(
            "function applyBootstrapSceneTintShift(",
            helper_start,
        )
        helper = runtime_source[helper_start:helper_end]

        self.assertIn("resolveBootstrapJinColor(source)", helper)
        self.assertIn("color: restoredColor", helper)
        self.assertIn(
            "session.resolveBootstrapRoomState = resolveBootstrapRoomState",
            runtime_source,
        )

        logger_source = (
            ROOT / "ui" / "static" / "js" / "logger" / "logger.js"
        ).read_text(encoding="utf-8")
        stored_start = logger_source.index("function getStoredRoomState()")
        stored_end = logger_source.index(
            "function enableRoomStatePersistence(",
            stored_start,
        )
        stored_block = logger_source[stored_start:stored_end]

        self.assertNotIn("resolveBootstrapRoomState", stored_block)
        self.assertIn("snapshot.current_jin_color", stored_block)
        self.assertIn("roomState.avatar.color = color;", stored_block)
        self.assertNotIn("delete roomState.avatar.color;", stored_block)

    def test_live_bootstrap_preserves_tool_results(self):
        source = RUNTIME_SESSION_JS.read_text(encoding="utf-8")
        start = source.index("function normalizeLiveSessionSnapshot(")
        end = source.index("function persistLiveSessionCheckpoint", start)
        block = source[start:end]

        self.assertIn("tool_results:", block)
        self.assertIn("source.tool_results", block)
        self.assertIn("data.tool_results", block)

    def test_archived_bootstrap_passes_actions_and_tool_results(self):
        source = SESSION_RESTORE_JS.read_text(encoding="utf-8")
        start = source.index("function buildBootstrap(")
        end = source.index("async function restoreArchivedSession", start)
        block = source[start:end]

        self.assertIn("payload.session_actions", block)
        self.assertIn("payload.tool_results", block)
        self.assertNotIn("session_actions: []", block)

    def test_live_runtime_snapshot_keeps_direct_predecessor_link(self):
        source = RUNTIME_STORAGE_JS.read_text(encoding="utf-8")

        self.assertIn("booted_from_session_id", source)
        self.assertIn("setBootSourceRuntimeSessionId", source)
        self.assertIn("readLatestPreviousRuntimeMemory", source)
        self.assertIn("collectOtherLatestRuntimeMemorySnapshots", source)
        self.assertIn("saved_at:\n        new Date().toISOString()", source)

    def test_persisted_runtime_snapshot_keeps_its_origin_session_id(self):
        storage_source = RUNTIME_STORAGE_JS.read_text(encoding="utf-8")
        storage_start = storage_source.index(
            "function buildPersistedRuntimeSnapshot("
        )
        storage_end = storage_source.index(
            "function cloneRuntimeMemoryToCurrentSession(",
            storage_start,
        )
        storage_block = storage_source[storage_start:storage_end]

        self.assertIn(
            'String(snapshot.session_id || "").trim()',
            storage_block,
        )
        self.assertIn(
            "session_id: snapshotSessionId",
            storage_block,
        )
        self.assertNotIn(
            "session_id: runtimeSessionId",
            storage_block,
        )

        session_source = RUNTIME_SESSION_JS.read_text(encoding="utf-8")
        checkpoint_start = session_source.index(
            "function buildCheckpointRuntimeSnapshot("
        )
        checkpoint_end = session_source.index(
            "function runtimeMemoryObjectFromSnapshot(",
            checkpoint_start,
        )
        checkpoint_block = session_source[
            checkpoint_start:checkpoint_end
        ]

        self.assertIn(
            "persistedSnapshot.session_id",
            checkpoint_block,
        )
        self.assertIn(
            "|| getCurrentSavedSessionId()",
            checkpoint_block,
        )


if __name__ == "__main__":
    unittest.main()
