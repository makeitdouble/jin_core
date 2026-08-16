import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from config_loader import config
from utils.chat_log import (
    append_chat_log_entry,
    build_chat_log_entry,
    extract_active_memory_ids,
    migrate_legacy_chat_logs,
    resume_chat_log_session,
    save_chat_context_snapshot,
    save_turn_reasoning,
    summarize_attachments,
)


class ChatLogTests(unittest.TestCase):

    def setUp(self):

        self.original_log_chat = getattr(
            config,
            "LOG_CHAT",
            None,
        )
        config.LOG_CHAT = True

    def tearDown(self):

        if self.original_log_chat is None:
            delattr(
                config,
                "LOG_CHAT",
            )
        else:
            config.LOG_CHAT = self.original_log_chat

    def test_extract_active_memory_ids_prefers_explicit_ids(self):

        self.assertEqual(
            extract_active_memory_ids([
                (
                    "active_memory_1: remember "
                    "[ active_memory_id: 5FDG4G ]"
                ),
                "active_memory_2: fallback id",
                "session_status: ignored",
            ]),
            [
                "5fdg4g",
                "active_memory_2",
            ],
        )

    def test_summarize_attachments_keeps_only_metadata(self):

        self.assertEqual(
            summarize_attachments([
                {
                    "id": "attachment-1",
                    "name": "screen.png",
                    "kind": "image",
                    "type": "image/png",
                    "size_bytes": 1234,
                    "size_label": "1.2 KB",
                    "width": 800,
                    "height": 600,
                    "data_url": "data:image/png;base64,AAAA",
                },
                {
                    "name": "notes.txt",
                    "kind": "text",
                    "type": "text/plain",
                    "size_bytes": 42,
                    "text_content": "secret text",
                },
            ]),
            [
                {
                    "name": "screen.png",
                    "id": "attachment-1",
                    "kind": "image",
                    "type": "image/png",
                    "size_bytes": 1234,
                    "size_label": "1.2 KB",
                    "width": 800,
                    "height": 600,
                    "resolution": "800x600",
                },
                {
                    "name": "notes.txt",
                    "kind": "text",
                    "type": "text/plain",
                    "size_bytes": 42,
                },
            ],
        )

    def test_append_chat_log_entry_uses_date_session_directory(self):

        context = SimpleNamespace(
            session_id="tab:one",
            runtime_turn_counter=1,
            runtime_current_turn_id="turn_000001",
            runtime_turn_attachments=[
                {
                    "name": "screen.png",
                    "kind": "image",
                    "type": "image/png",
                    "size_bytes": 1234,
                    "width": 800,
                    "height": 600,
                    "data_url": "data:image/png;base64,AAAA",
                },
            ],
            active_memory_records=[
                (
                    "active_memory_1: remember "
                    "[ active_memory_id: 5fdg4g ]"
                ),
            ],
            runtime_loaded_delayed_memory_ids=[
                "48ggds",
            ],
        )
        now = datetime(
            2026,
            8,
            12,
            16,
            59,
            49,
            tzinfo=timezone.utc,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            first_path = append_chat_log_entry(
                context,
                role="user",
                text="hello",
                now=now,
                root=Path(temp_dir),
            )
            second_path = append_chat_log_entry(
                context,
                role="jin",
                text="hi",
                now=now,
                root=Path(temp_dir),
            )

            self.assertEqual(
                first_path,
                second_path,
            )
            self.assertEqual(
                first_path.parent.name,
                "tab_one",
            )
            self.assertEqual(
                first_path.parent.parent.name,
                "2026-08-12",
            )
            self.assertEqual(
                first_path.name,
                "165949.jsonl",
            )
            self.assertTrue(
                (first_path.parent / "reasoning").is_dir()
            )
            self.assertFalse(
                (
                    first_path.parent
                    / "reasoning"
                    / ".gitkeep"
                ).exists()
            )
            entries = [
                json.loads(line)
                for line in first_path.read_text(
                    encoding="utf-8",
                ).splitlines()
            ]

        self.assertEqual(
            [entry["role"] for entry in entries],
            [
                "user",
                "jin",
            ],
        )
        self.assertEqual(
            entries[0]["attachments"][0]["resolution"],
            "800x600",
        )
        self.assertNotIn(
            "data_url",
            entries[0]["attachments"][0],
        )
        self.assertEqual(
            entries[0]["active_memory_ids"],
            [
                "5fdg4g",
            ],
        )
        self.assertEqual(
            entries[0]["delayed_memory_ids"],
            [
                "48ggds",
            ],
        )

    def test_resume_chat_log_session_reuses_existing_log_and_turn_counter(self):

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            session_id = "reconnect-session"
            session_directory = (
                root
                / "2026-08-15"
                / session_id
            )
            session_directory.mkdir(
                parents=True
            )
            log_path = (
                session_directory
                / "235959.jsonl"
            )
            log_path.write_text(
                "\n".join([
                    json.dumps({
                        "turn": 7,
                        "turn_id": "turn_000007",
                        "role": "user",
                    }),
                    json.dumps({
                        "turn": 7,
                        "turn_id": "turn_000007",
                        "role": "jin",
                    }),
                ]) + "\n",
                encoding="utf-8",
            )
            context_path = log_path.with_suffix(
                ".txt"
            )
            context_path.write_text(
                "saved context\n",
                encoding="utf-8",
            )
            context = SimpleNamespace(
                session_id=session_id,
                runtime_turn_counter=0,
            )

            resumed_path = resume_chat_log_session(
                context,
                root=root,
            )

            self.assertEqual(
                resumed_path,
                log_path,
            )
            self.assertEqual(
                Path(context.runtime_chat_log_path),
                log_path,
            )
            self.assertEqual(
                Path(context.runtime_chat_context_path),
                context_path,
            )
            self.assertEqual(
                context.runtime_turn_counter,
                7,
            )
            self.assertTrue(
                (session_directory / "reasoning").is_dir()
            )

    def test_resume_chat_log_session_keeps_pre_restart_log_across_midnight(self):

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            session_id = "overnight-session"
            old_directory = (
                root
                / "2026-08-15"
                / session_id
            )
            old_directory.mkdir(
                parents=True
            )
            old_log = old_directory / "235959.jsonl"
            old_log.write_text(
                json.dumps({
                    "turn": 12,
                    "turn_id": "turn_000012",
                    "role": "jin",
                }) + "\n",
                encoding="utf-8",
            )
            context = SimpleNamespace(
                session_id=session_id,
                runtime_turn_counter=0,
            )

            resume_chat_log_session(
                context,
                root=root,
            )
            context.runtime_turn_counter += 1
            context.runtime_current_turn_id = "turn_000013"
            appended_path = append_chat_log_entry(
                context,
                role="user",
                text="after restart",
                now=datetime(
                    2026,
                    8,
                    16,
                    0,
                    1,
                    tzinfo=timezone.utc,
                ),
                root=root,
            )

            self.assertEqual(
                appended_path,
                old_log,
            )
            entries = [
                json.loads(line)
                for line in old_log.read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            self.assertEqual(
                entries[-1]["turn"],
                13,
            )
            self.assertEqual(
                entries[-1]["turn_id"],
                "turn_000013",
            )

    def test_context_snapshot_is_saved_beside_dialog_and_overwritten(self):

        context = SimpleNamespace(
            session_id="session-a",
            runtime_turn_counter=1,
            runtime_current_turn_id="turn_000001",
        )
        now = datetime(
            2026,
            8,
            13,
            14,
            33,
            31,
            tzinfo=timezone.utc,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = save_chat_context_snapshot(
                context,
                context_snapshot={
                    "system_prompt": "PRIVATE RULES",
                    "visible_system_prompt": "VISIBLE CONTEXT",
                    "hide_internal_action_rules": True,
                    "user_prompt": "first user payload",
                },
                now=now,
                root=root,
            )
            second = save_chat_context_snapshot(
                context,
                context_snapshot={
                    "system_prompt": "PRIVATE RULES 2",
                    "visible_system_prompt": "VISIBLE CONTEXT 2",
                    "hide_internal_action_rules": True,
                    "user_prompt": "latest user payload",
                },
                now=now,
                root=root,
            )

            self.assertEqual(first, second)
            self.assertEqual(
                first,
                root / "2026-08-13" / "session-a" / "143331.txt",
            )
            saved = first.read_text(encoding="utf-8")

        self.assertIn("VISIBLE CONTEXT 2", saved)
        self.assertIn("latest user payload", saved)
        self.assertNotIn("PRIVATE RULES 2", saved)
        self.assertNotIn("first user payload", saved)

    def test_reasoning_trace_links_back_to_dialog_and_jin_log_entry(self):

        context = SimpleNamespace(
            session_id="5fa84aef-0537-4e56-9cb3-3d341bc7b93e",
            runtime_turn_counter=3,
            runtime_current_turn_id="turn_000003",
        )
        now = datetime(
            2026,
            8,
            13,
            14,
            33,
            31,
            tzinfo=timezone.utc,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            save_chat_context_snapshot(
                context,
                system_prompt="system context",
                user_prompt="user payload",
                now=now,
                root=root,
            )
            reasoning_path = save_turn_reasoning(
                context,
                "Tried again. Ugh, I keep miscounting. Switched strategy.",
                now=now,
                root=root,
            )
            dialog_path = append_chat_log_entry(
                context,
                role="jin",
                text="done",
                now=now,
                root=root,
            )
            reasoning_text = reasoning_path.read_text(encoding="utf-8")
            entry = json.loads(
                dialog_path.read_text(encoding="utf-8").splitlines()[-1]
            )

        self.assertEqual(
            reasoning_path.parent.name,
            "reasoning",
        )
        self.assertEqual(
            reasoning_path.parent.parent.name,
            "5fa84aef-0537-4e56-9cb3-3d341bc7b93e",
        )
        self.assertEqual(
            reasoning_path.parent.parent.parent.name,
            "2026-08-13",
        )
        self.assertIn("dialog_path:", reasoning_text)
        self.assertIn("143331.jsonl", reasoning_text)
        self.assertIn("Ugh, I keep miscounting", reasoning_text)
        self.assertIn("reasoning_path", entry)
        self.assertIn("context_path", entry)
        self.assertIn("dialog_path", entry)

    def test_legacy_log_directories_are_collapsed_under_date(self):

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first_legacy = (
                root
                / "2026-08-13-5fa84aef-0537-4e56-9cb3-3d341bc7b93e"
            )
            second_legacy = (
                root
                / "2026-08-13-session-two"
            )
            first_legacy.mkdir(parents=True)
            second_legacy.mkdir(parents=True)
            (first_legacy / "143331.jsonl").write_text(
                "first\n",
                encoding="utf-8",
            )
            (second_legacy / "170000.jsonl").write_text(
                "second\n",
                encoding="utf-8",
            )

            moved = migrate_legacy_chat_logs(
                root=root
            )

            self.assertEqual(len(moved), 2)
            self.assertFalse(first_legacy.exists())
            self.assertFalse(second_legacy.exists())
            self.assertEqual(
                (
                    root
                    / "2026-08-13"
                    / "5fa84aef-0537-4e56-9cb3-3d341bc7b93e"
                    / "143331.jsonl"
                ).read_text(encoding="utf-8"),
                "first\n",
            )
            self.assertEqual(
                (
                    root
                    / "2026-08-13"
                    / "session-two"
                    / "170000.jsonl"
                ).read_text(encoding="utf-8"),
                "second\n",
            )
            reasoning_directory = (
                root
                / "2026-08-13"
                / "5fa84aef-0537-4e56-9cb3-3d341bc7b93e"
                / "reasoning"
            )
            self.assertTrue(
                reasoning_directory.is_dir()
            )
            self.assertFalse(
                (reasoning_directory / ".gitkeep").exists()
            )
            resumed_context = SimpleNamespace(
                session_id="5fa84aef-0537-4e56-9cb3-3d341bc7b93e",
            )
            resumed_context_path = save_chat_context_snapshot(
                resumed_context,
                system_prompt="restored current JIN context",
                now=datetime(
                    2026,
                    8,
                    13,
                    18,
                    0,
                    0,
                    tzinfo=timezone.utc,
                ),
                root=root,
            )
            self.assertEqual(
                resumed_context_path.name,
                "143331.txt",
            )
            self.assertTrue(
                resumed_context_path.with_suffix(".jsonl").exists()
            )
            self.assertEqual(
                migrate_legacy_chat_logs(root=root),
                [],
            )

    def test_wrong_date_reasoning_directory_is_folded_into_sessions(self):

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            date_directory = root / "2026-08-15"
            session_id = "f78fce15-8933-495f-b304-8ac27d0f87cb"
            session_directory = date_directory / session_id
            wrong_reasoning = date_directory / "reasoning"
            session_directory.mkdir(parents=True)
            wrong_reasoning.mkdir(parents=True)
            (session_directory / "193900.jsonl").write_text(
                "dialog\n",
                encoding="utf-8",
            )
            source = (
                wrong_reasoning
                / f"{session_id}_193900_turn_000003.txt"
            )
            source.write_text(
                "\n".join([
                    "captured_at: 2026-08-15T19:39:00+03:00",
                    f"session_id: {session_id}",
                    "turn: 3",
                    "turn_id: turn_000003",
                    "",
                    "--- REASONING ---",
                    "Ugh, I keep miscounting.",
                ]),
                encoding="utf-8",
            )
            (wrong_reasoning / ".gitkeep").touch()

            moved = migrate_legacy_chat_logs(
                root=root
            )
            target = (
                session_directory
                / "reasoning"
                / "193900_turn_000003.txt"
            )

            self.assertEqual(
                moved,
                [(source, target)],
            )
            self.assertFalse(
                wrong_reasoning.exists()
            )
            self.assertTrue(
                target.exists()
            )
            self.assertIn(
                "Ugh, I keep miscounting.",
                target.read_text(encoding="utf-8"),
            )
            self.assertFalse(
                (
                    session_directory
                    / "reasoning"
                    / ".gitkeep"
                ).exists()
            )

    def test_build_chat_log_entry_includes_empty_arrays(self):

        entry = build_chat_log_entry(
            SimpleNamespace(
                session_id="session-a",
                runtime_turn_counter=2,
                runtime_current_turn_id="turn_000002",
            ),
            role="user",
            text="plain",
            now=datetime(
                2026,
                8,
                12,
                16,
                0,
                0,
                tzinfo=timezone.utc,
            ),
        )

        self.assertEqual(
            entry["attachments"],
            [],
        )
        self.assertEqual(
            entry["active_memory_ids"],
            [],
        )
        self.assertEqual(
            entry["delayed_memory_ids"],
            [],
        )


if __name__ == "__main__":
    unittest.main()
