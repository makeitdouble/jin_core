import unittest
from pathlib import Path
from types import SimpleNamespace

from utils.session_restore import _build_recent_turns
from websocket.bootstrap import (
    apply_archived_session_continuation_state,
    build_session_bootstrap_chat_tail,
)
from websocket.messages import append_runtime_recent_turn


ROOT = Path(__file__).resolve().parents[1]
SOCKET_HANDLERS_JS = (
    ROOT / "ui" / "static" / "js" / "socket" / "event-handlers.js"
)


class SessionBootstrapChatTailTests(unittest.TestCase):

    def test_archive_tail_keeps_three_newest_user_moves_with_reasoning(self):
        entries = []
        reasoning = {}
        for turn in range(1, 5):
            turn_id = f"turn_{turn:06d}"
            entries.append({
                "turn": turn,
                "turn_id": turn_id,
                "role": "user",
                "text": f"user {turn}",
            })
            if turn != 3:
                entries.append({
                    "turn": turn,
                    "turn_id": turn_id,
                    "role": "jin",
                    "text": f"jin {turn}",
                })
                reasoning[turn_id] = (
                    "captured_at: now\n\n--- REASONING ---\n"
                    f"reasoning {turn}"
                )

        turns = _build_recent_turns(entries, reasoning)

        self.assertEqual(
            [(turn["user"], turn["jin"]) for turn in turns],
            [
                ("user 2", "jin 2"),
                ("user 3", ""),
                ("user 4", "jin 4"),
            ],
        )
        self.assertEqual(
            [turn.get("reasoning", "") for turn in turns],
            ["reasoning 2", "", "reasoning 4"],
        )

    def test_bootstrap_hydration_preserves_turn_reasoning_and_ui_tail(self):
        context = SimpleNamespace(
            runtime_recent_turns=[],
            runtime_previous_reasoning_content="",
            runtime_previous_reasoning_loop_contents=[],
            runtime_session_restore_delayed_memory_metadata=[],
            runtime_session_restore_attached_file_metadata=[],
            runtime_session_restore_reasoning_dump="",
            runtime_session_restore_lt_fact_ids=[],
            runtime_session_restore_pending_attached_file_ids=[],
            runtime_archived_session_id="",
            runtime_session_restore_priming=False,
        )

        apply_archived_session_continuation_state(
            context,
            {
                "recent_turns": [
                    {
                        "user": (
                            "hello\n\nAttached context:\n"
                            "- /assets/files/a.png: image [ id: a ]"
                        ),
                        "jin": "world",
                        "reasoning": "saved reasoning",
                    },
                ],
                "previous_reasoning": "latest reasoning",
            },
        )

        self.assertEqual(
            context.runtime_recent_turns[0]["reasoning"],
            "saved reasoning",
        )
        self.assertEqual(
            build_session_bootstrap_chat_tail(context),
            [
                {
                    "user": "hello",
                    "jin": "world",
                    "reasoning": "saved reasoning",
                }
            ],
        )

    def test_bootstrap_tail_keeps_interrupted_user_move_without_jin(self):
        context = SimpleNamespace(
            runtime_recent_turns=[{
                "user": "я отправил и сразу остановил",
                "jin": "",
                "user_created_at": 100.0,
            }],
        )

        self.assertEqual(
            build_session_bootstrap_chat_tail(context),
            [{
                "user": "я отправил и сразу остановил",
                "jin": "",
                "user_created_at": 100.0,
            }],
        )

    def test_bootstrap_tail_keeps_committed_user_only_action_turn(self):
        context = SimpleNamespace(
            runtime_recent_turns=[{
                "user": "поставь себе цвет ff0000",
                "jin": "",
                "user_created_at": 100.0,
                "jin_created_at": 101.0,
            }],
        )

        self.assertEqual(
            build_session_bootstrap_chat_tail(context),
            [{
                "user": "поставь себе цвет ff0000",
                "jin": "",
                "user_created_at": 100.0,
                "jin_created_at": 101.0,
            }],
        )

    def test_live_recent_turn_persists_reasoning(self):
        context = SimpleNamespace(
            runtime_recent_turns=[],
            runtime_restored_session_dialog="",
        )

        append_runtime_recent_turn(
            context,
            user_message="u",
            assistant_message="j",
            reasoning="r",
        )

        self.assertEqual(
            context.runtime_recent_turns,
            [{"user": "u", "jin": "j", "reasoning": "r"}],
        )

    def test_client_renders_bootstrap_tail_with_existing_chat_primitives(self):
        source = SOCKET_HANDLERS_JS.read_text(encoding="utf-8")

        self.assertIn('"session_bootstrap_chat_tail"', source)
        self.assertIn("handleSessionBootstrapChatTail", source)
        self.assertIn("appendChatMessage(", source)
        self.assertIn("appendThinkingChunk(", source)
        self.assertIn("appendStreamChunk(", source)
        self.assertIn("finishStreamMessage(", source)
        self.assertIn("window.jinArchivedSessionRestorePayload", source)
        self.assertIn(".slice(-3)", source)

    def test_client_keeps_user_only_turn_without_blank_br_bubble(self):
        source = SOCKET_HANDLERS_JS.read_text(encoding="utf-8")
        handler_start = source.index(
            "function handleSessionBootstrapChatTail"
        )
        handler_end = source.index(
            "function handleSessionActionsUpdate",
            handler_start,
        )
        handler_source = source[handler_start:handler_end]

        self.assertIn(
            '&& String(turn.user || "").trim()',
            handler_source,
        )
        self.assertNotIn(
            '&& String(turn.jin || "").trim()',
            handler_source,
        )
        self.assertIn("if (!jinText)", handler_source)
        self.assertIn("appendSessionBootstrapBoundary", handler_source)

    def test_client_places_current_session_boundary_above_new_response(self):
        source = SOCKET_HANDLERS_JS.read_text(encoding="utf-8")

        self.assertIn("appendSessionBootstrapBoundary", source)
        self.assertIn('"jin-session-restore-divider"', source)
        self.assertIn('"jin-session-restore-divider-label"', source)
        self.assertIn("window.activateLiveUserTurnViewport", source)
        self.assertIn("String(now.getHours()).padStart(2, \"0\")", source)
        self.assertIn("String(now.getMinutes()).padStart(2, \"0\")", source)
        self.assertIn("`${now.getDate()} `", source)
        self.assertIn("+ `${months[now.getMonth()]} `", source)
        self.assertIn("+ `${hours}:${minutes}, `", source)
        self.assertIn("+ weekdays[now.getDay()]", source)

        handler_start = source.index(
            "function handleSessionBootstrapChatTail"
        )
        handler_end = source.index(
            "function handleSessionActionsUpdate",
            handler_start,
        )
        handler_source = source[handler_start:handler_end]
        self.assertNotIn(
            "chatHistory.scrollTop =\n      chatHistory.scrollHeight",
            handler_source,
        )


if __name__ == "__main__":
    unittest.main()
