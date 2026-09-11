import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from utils.session_restore import (
    _build_recent_turns,
    build_archived_session_restore_payload,
    build_session_bootstrap_lineage_recent_turns,
)
from websocket.bootstrap import (
    apply_archived_session_continuation_state,
    build_session_bootstrap_chat_tail,
)
from websocket.messages import append_runtime_recent_turn



class SessionBootstrapChatTailTests(unittest.TestCase):

    def test_archive_tail_keeps_six_newest_user_moves_with_reasoning(self):
        entries = []
        reasoning = {}
        for turn in range(1, 8):
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
                ("user 5", "jin 5"),
                ("user 6", "jin 6"),
                ("user 7", "jin 7"),
            ],
        )
        self.assertEqual(
            [turn.get("reasoning", "") for turn in turns],
            [
                "reasoning 2",
                "",
                "reasoning 4",
                "reasoning 5",
                "reasoning 6",
                "reasoning 7",
            ],
        )


    def test_lineage_tail_backfills_five_completed_turns_before_stopped_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            date_dir = root / "2026-09-07"
            previous_id = "previous-session"
            child_id = "stopped-child"
            previous_dir = date_dir / previous_id
            child_dir = date_dir / child_id
            previous_dir.mkdir(parents=True)
            child_dir.mkdir(parents=True)

            previous_rows = []
            for turn in range(1, 7):
                previous_rows.extend([
                    {
                        "ts": f"2026-09-07T10:{turn:02d}:00+03:00",
                        "turn": turn,
                        "turn_id": f"turn_{turn:06d}",
                        "role": "user",
                        "text": f"old user {turn}",
                    },
                    {
                        "ts": f"2026-09-07T10:{turn:02d}:10+03:00",
                        "turn": turn,
                        "turn_id": f"turn_{turn:06d}",
                        "role": "jin",
                        "text": f"old jin {turn}",
                    },
                ])

            (previous_dir / "100000.jsonl").write_text(
                "\n".join(json.dumps(row) for row in previous_rows) + "\n",
                encoding="utf-8",
            )
            (previous_dir / "100000.txt").write_text("", encoding="utf-8")

            child_row = {
                "ts": "2026-09-07T11:16:06+03:00",
                "turn": 7,
                "turn_id": "turn_000007",
                "role": "user",
                "text": "new user then stop",
            }
            (child_dir / "111606.jsonl").write_text(
                json.dumps(child_row) + "\n",
                encoding="utf-8",
            )
            (child_dir / "111606.txt").write_text(
                (
                    f'<RESTORED_SESSION_DIALOG session_id="{previous_id}">\n'
                    "older context\n"
                    "</RESTORED_SESSION_DIALOG>\n"
                ),
                encoding="utf-8",
            )

            turns = build_session_bootstrap_lineage_recent_turns(
                child_id,
                root=root,
            )

            self.assertEqual(
                [turn["user"] for turn in turns],
                [
                    "old user 2",
                    "old user 3",
                    "old user 4",
                    "old user 5",
                    "old user 6",
                    "new user then stop",
                ],
            )
            self.assertEqual(
                [turn["source_session_id"] for turn in turns],
                [previous_id] * 5 + [child_id],
            )
            self.assertEqual(turns[-1]["jin"], "")

            payload = build_archived_session_restore_payload(
                child_id,
                root=root,
            )
            self.assertIsNotNone(payload)
            self.assertEqual(
                payload["bootstrap_lineage_turns"],
                turns,
            )
            self.assertIn(
                f'<RESTORED_SESSION_DIALOG session_id="{child_id}">',
                payload["bootstrap_lineage_dialog_context"],
            )
            self.assertIn(
                'source_session_id="previous-session"',
                payload["bootstrap_lineage_dialog_context"],
            )

    def test_bootstrap_ui_tail_prefers_lineage_projection_over_short_recent_tail(self):
        context = SimpleNamespace(
            runtime_recent_turns=[],
            runtime_bootstrap_chat_tail_turns=[],
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
        lineage_turns = [
            {
                "user": f"old {index}",
                "jin": f"answer {index}",
                "source_session_id": "old-session",
                "user_created_at": float(index),
                "jin_created_at": float(index) + 0.5,
            }
            for index in range(1, 6)
        ] + [{
            "user": "new stopped",
            "jin": "",
            "source_session_id": "new-session",
            "user_created_at": 10.0,
        }]

        apply_archived_session_continuation_state(
            context,
            {
                "recent_turns": [lineage_turns[-1]],
                "bootstrap_chat_tail_turns": lineage_turns,
            },
        )

        tail = build_session_bootstrap_chat_tail(context)
        self.assertEqual(len(tail), 6)
        self.assertEqual(tail[0]["user"], "old 1")
        self.assertEqual(tail[-1]["user"], "new stopped")
        self.assertEqual(
            [turn.get("source_session_id") for turn in tail],
            ["old-session"] * 5 + ["new-session"],
        )

    def test_archive_recent_turn_keeps_attachment_metadata(self):
        turns = _build_recent_turns([
            {
                "turn": 1,
                "turn_id": "turn_000001",
                "role": "user",
                "text": "photo",
                "attachments": [
                    {
                        "id": "abc123",
                        "name": "photo.png",
                        "kind": "image",
                        "type": "image/png",
                        "size_bytes": 123,
                        "data_url": "transient",
                    }
                ],
            },
            {
                "turn": 1,
                "turn_id": "turn_000001",
                "role": "jin",
                "text": "seen",
            },
        ])

        self.assertEqual(
            turns[0]["attachments"],
            [
                {
                    "name": "photo.png",
                    "id": "abc123",
                    "kind": "image",
                    "type": "image/png",
                    "size_bytes": 123,
                }
            ],
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
                        "attachments": [
                            {
                                "id": "abc123",
                                "name": "a.png",
                                "kind": "image",
                                "type": "image/png",
                                "size_bytes": 42,
                                "data_url": "must-not-survive-bootstrap",
                            }
                        ],
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
            context.runtime_recent_turns[0]["attachments"],
            [
                {
                    "name": "a.png",
                    "id": "abc123",
                    "kind": "image",
                    "type": "image/png",
                    "size_bytes": 42,
                }
            ],
        )
        self.assertEqual(
            build_session_bootstrap_chat_tail(context),
            [
                {
                    "user": "hello",
                    "jin": "world",
                    "attachments": [
                        {
                            "name": "a.png",
                            "id": "abc123",
                            "kind": "image",
                            "type": "image/png",
                            "size_bytes": 42,
                        }
                    ],
                    "reasoning": "saved reasoning",
                }
            ],
        )

    def test_bootstrap_tail_keeps_attachment_only_user_move(self):
        context = SimpleNamespace(
            runtime_recent_turns=[{
                "user": (
                    "Attached context:\n"
                    "- /assets/files/abc123_photo.png: image [ id: abc123 ]"
                ),
                "jin": "",
                "attachments": [{
                    "id": "abc123",
                    "name": "photo.png",
                    "kind": "image",
                }],
            }],
        )

        self.assertEqual(
            build_session_bootstrap_chat_tail(context),
            [{
                "user": "",
                "jin": "",
                "attachments": [{
                    "name": "photo.png",
                    "id": "abc123",
                    "kind": "image",
                }],
            }],
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
            attachments=[{
                "id": "abc123",
                "name": "photo.png",
                "kind": "image",
                "data_url": "large-transient-data",
            }],
        )

        self.assertEqual(
            context.runtime_recent_turns,
            [
                {
                    "user": "u",
                    "jin": "j",
                    "attachments": [
                        {
                            "name": "photo.png",
                            "id": "abc123",
                            "kind": "image",
                        }
                    ],
                    "reasoning": "r",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
