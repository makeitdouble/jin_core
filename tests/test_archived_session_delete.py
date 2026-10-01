"""Disk-owned LOGS deletion and empty-day cleanup."""
import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from utils import chat_log, session_restore


class ArchivedSessionDeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "logs"
        self.root.mkdir()

    def make_session(self, day, session_id, *, user=True):
        folder = self.root / day / session_id
        (folder / "reasoning").mkdir(parents=True)
        (folder / "frames").mkdir()
        (folder / "reasoning" / "100000_turn.txt").write_text("reasoning", encoding="utf-8")
        (folder / "frames" / "100000_frame_1.txt").write_text("frame", encoding="utf-8")
        (folder / "100000.txt").write_text("context", encoding="utf-8")
        entries = ([{"ts": f"{day}T10:00:00Z", "turn": 1,
                    "role": "user", "text": "hello"}] if user else [])
        (folder / "100000.jsonl").write_text(
            "\n".join(json.dumps(row) for row in entries), encoding="utf-8"
        )
        return folder

    def test_only_target_session_removed_then_empty_date_removed(self):
        first = self.make_session("2026-09-29", "first")
        second = self.make_session("2026-09-29", "second")
        another_day = self.make_session("2026-09-28", "older")
        self.assertTrue(session_restore.delete_archived_session("first", root=self.root))
        self.assertFalse(first.exists())
        self.assertTrue(second.exists())
        self.assertTrue((self.root / "2026-09-29").exists())
        self.assertEqual([item["session_id"] for item in session_restore.list_archived_sessions(root=self.root)],
                         ["second", "older"])
        self.assertTrue(session_restore.delete_archived_session("second", root=self.root))
        self.assertFalse((self.root / "2026-09-29").exists())
        self.assertTrue(another_day.exists())
        self.assertTrue(self.root.exists())
        self.assertFalse(session_restore.delete_archived_session("second", root=self.root))

    def test_date_folder_with_other_contents_is_never_removed(self):
        self.make_session("2026-09-29", "first")
        marker = self.root / "2026-09-29" / "keep.txt"
        marker.write_text("preserve", encoding="utf-8")
        self.assertTrue(session_restore.delete_archived_session("first", root=self.root))
        self.assertTrue(marker.exists())

    def test_refuses_non_indexed_unsafe_and_anonymous_sessions(self):
        hidden = self.make_session("2026-09-29", "no-user", user=False)
        anonymous = self.make_session("2026-09-29", "private_anon")
        valid = self.make_session("2026-09-29", "valid")
        for session_id in ("no-user", "private_anon", "../valid", "valid?", "", "."):
            with self.subTest(session_id=session_id):
                self.assertFalse(session_restore.delete_archived_session(session_id, root=self.root))
        self.assertTrue(hidden.exists())
        self.assertTrue(anonymous.exists())
        self.assertTrue(valid.exists())

    def test_refuses_symlinked_session_and_date_directory(self):
        with tempfile.TemporaryDirectory() as other_temp:
            outside = Path(other_temp) / "external"
            outside.mkdir()
            (outside / "secret.txt").write_text("keep", encoding="utf-8")
            date = self.root / "2026-09-29"
            date.mkdir()
            try:
                (date / "external").symlink_to(outside, target_is_directory=True)
                (self.root / "2026-09-28").symlink_to(Path(other_temp), target_is_directory=True)
            except (NotImplementedError, OSError):
                self.skipTest("directory symlinks unavailable")
            self.assertFalse(session_restore.delete_archived_session("external", root=self.root))
            # A symlinked *date* must be rejected too, not just a linked session.
            (Path(other_temp) / "foreign").mkdir()
            (Path(other_temp) / "foreign" / "100000.jsonl").write_text(
                json.dumps({"ts": "2026-09-28T10:00:00Z", "role": "user", "text": "hello"}),
                encoding="utf-8",
            )
            self.assertFalse(session_restore.delete_archived_session("foreign", root=self.root))
            self.assertTrue((outside / "secret.txt").exists())
            self.assertTrue((Path(other_temp) / "foreign" / "100000.jsonl").exists())

    def test_live_writer_cannot_resurrect_deleted_session_or_date(self):
        moment = datetime(2026, 9, 29, 14, tzinfo=timezone.utc)
        context = SimpleNamespace(session_id="active", runtime_turn_counter=1,
                                  runtime_current_turn_id="turn_000001")
        with (patch.object(chat_log, "CHAT_LOG_ROOT", self.root),
              patch.object(chat_log, "chat_logging_enabled", return_value=True)):
            path = chat_log.append_chat_log_entry(context, role="user", text="hello", now=moment)
            self.assertTrue(path.exists())
            self.assertTrue(session_restore.delete_archived_session("active", root=self.root))
            self.assertIsNone(chat_log.append_chat_log_entry(context, role="jin", text="late", now=moment))
            self.assertIsNone(chat_log.save_frame_snapshot(context, {
                "index": 2, "raw_memory": "session_title: late"
            }, now=moment))
            self.assertFalse(path.parent.parent.exists())

    def test_http_delete_route(self):
        import httpx
        import app as jin_app
        self.make_session("2026-09-29", "api-session")

        async def check():
            transport = httpx.ASGITransport(app=jin_app.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                with patch.object(session_restore, "CHAT_LOG_ROOT", self.root):
                    result = await client.delete("/api/sessions/api-session")
                    self.assertEqual(result.status_code, 200)
                    self.assertEqual(result.json(), {"deleted": True, "session_id": "api-session"})
                    self.assertEqual((await client.get("/api/sessions")).json(), {"sessions": []})
                    self.assertEqual((await client.delete("/api/sessions/api-session")).status_code, 404)
        asyncio.run(check())
