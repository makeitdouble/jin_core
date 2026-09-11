import unittest
from types import SimpleNamespace

from runtime.L1_memory_utils import build_runtime_session_checkpoint



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
            current_session_user_message_count=2,
            current_session_assistant_message_count=1,
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
            checkpoint["current_session_user_message_count"],
            2,
        )
        self.assertEqual(
            checkpoint["current_session_assistant_message_count"],
            1,
        )
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





if __name__ == "__main__":
    unittest.main()
