import unittest
from pathlib import Path
from types import SimpleNamespace

from runtime.L1_memory_utils import build_runtime_session_checkpoint


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SESSION_JS = (
    ROOT
    / "ui"
    / "static"
    / "js"
    / "runtime"
    / "runtime-session.js"
)
RUNTIME_JS = (
    ROOT
    / "ui"
    / "static"
    / "js"
    / "runtime"
    / "runtime.js"
)


class LiveSessionCheckpointTests(unittest.TestCase):

    def test_runtime_checkpoint_contains_live_session_state_without_l3(self):
        context = SimpleNamespace(
            session_id="session-current",
            runtime_recent_turns=[
                {"user": "u1", "jin": "j1"},
                {"user": "u2", "jin": "j2"},
                {"user": "u3", "jin": "j3"},
                {"user": "u4", "jin": "j4"},
            ],
            runtime_turn_reasoning_content="latest reasoning",
            runtime_previous_reasoning_content="older reasoning",
            runtime_session_action_history=[
                {"text": "action"},
            ],
            runtime_tool_results=[
                {
                    "kind": "deep_search",
                    "result": "Deep web search report",
                    "id": "deep_web_search_001",
                },
            ],
            runtime_tool_result_created_ats=[42.0],
            runtime_turn_counter=17,
            turn_number=31,
            user_message_count=9,
            assistant_message_count=8,
            runtime_memory_updates=6,
            runtime_loaded_delayed_memory_ids=["dm-1", "dm-2"],
            runtime_attached_file_ids=["file-1"],
            active_memory_records=["active-memory-line"],
            jin_color="#123456",
            runtime_avatar_current_size={"width": 120, "height": 90},
            # This is intentionally present on the runtime context. The live
            # checkpoint must not copy the model-generated SAVE_SESSION L3.
            session_memory="generated L3 must stay out",
            runtime_l3_session_memory="generated L3 must stay out",
        )

        checkpoint = build_runtime_session_checkpoint(context)

        self.assertEqual(checkpoint["session_id"], "session-current")
        self.assertEqual(
            checkpoint["recent_turns"],
            context.runtime_recent_turns[-3:],
        )
        self.assertEqual(
            checkpoint["previous_reasoning"],
            "latest reasoning",
        )
        self.assertEqual(
            checkpoint["loaded_memory_ids"],
            ["dm-1", "dm-2"],
        )
        self.assertEqual(
            checkpoint["attached_file_ids"],
            ["file-1"],
        )
        self.assertEqual(
            checkpoint["current_jin_size"],
            {"width": 120, "height": 90},
        )
        self.assertEqual(
            checkpoint["tool_results"],
            [
                {
                    "kind": "deep_search",
                    "result": "Deep web search report",
                    "id": "deep_web_search_001",
                    "created_at": 42.0,
                },
            ],
        )
        self.assertNotIn("session_memory", checkpoint)
        self.assertNotIn("runtime_l3_session_memory", checkpoint)

    def test_every_runtime_l1_persists_the_live_session_checkpoint(self):
        source = RUNTIME_JS.read_text(encoding="utf-8")
        start = source.index("function persistRuntimeMemorySnapshot(")
        end = source.index("function runtimeMemoryTextIsDefaultNote", start)
        block = source[start:end]

        self.assertIn("writeLatestRuntimeMemory(", block)
        self.assertIn("session.persistLiveSessionCheckpoint(", block)
        self.assertIn("Number(data.updates || 0) <= 0", block)

    def test_explicit_save_merges_l3_into_existing_live_session_record(self):
        source = RUNTIME_SESSION_JS.read_text(encoding="utf-8")

        live_start = source.index("function persistLiveSessionCheckpoint(data)")
        live_end = source.index("function buildSessionSaveRuntimeSnapshot", live_start)
        live_block = source[live_start:live_end]

        self.assertIn("writeLatestSavedRuntimeMemory({", live_block)
        self.assertIn("writeLatestSavedSessionMemory({", live_block)
        self.assertIn("session_snapshot: sessionSnapshot", live_block)
        self.assertIn("archive: false", live_block)

        save_start = source.index("function persistSessionMemory(data)")
        save_end = source.index("function getRuntimeMemoryForSoftReconnect", save_start)
        save_block = source[save_start:save_end]

        self.assertIn("liveSessionCheckpoint", save_block)
        self.assertIn("? liveSessionCheckpoint", save_block)
        self.assertIn("session_memory_saved_at: savedAt", save_block)
        self.assertIn("session_memory: sessionMemory", save_block)
        self.assertNotIn(
            "latestSavedRuntimeMemoryStorageKey",
            save_block,
        )

    def test_bootstrap_prefers_continuous_last_saved_runtime(self):
        source = RUNTIME_SESSION_JS.read_text(encoding="utf-8")
        start = source.index("function getPersistedSessionBootstrap()")
        end = source.index("function clearPersistedSessionBootstrap", start)
        block = source[start:end]

        saved_runtime_read = block.index("readLatestSavedRuntimeMemory()")
        previous_runtime_read = block.index("readLatestPreviousRuntimeMemory")
        self.assertLess(saved_runtime_read, previous_runtime_read)
        self.assertIn(
            "lastSavedRuntime is now a continuously refreshed pointer",
            block,
        )

    def test_duplicate_l1_still_refreshes_live_session_checkpoint(self):
        source = RUNTIME_JS.read_text(encoding="utf-8")
        duplicate = '''if (session.isLatestRuntimeMemoryDuplicate(data)) {
    session.persistLiveSessionCheckpoint(
      data
    );
    return;
  }'''
        self.assertIn(duplicate, source)


if __name__ == "__main__":
    unittest.main()
