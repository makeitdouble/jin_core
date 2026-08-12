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
                "2026-08-12-tab_one",
            )
            self.assertEqual(
                first_path.name,
                "165949.jsonl",
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
