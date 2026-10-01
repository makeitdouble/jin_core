import json
import tempfile
import unittest
from pathlib import Path

from runtime.frame_memory_rules import (
    DEFAULT_SESSION_TITLE,
    INITIAL_RUNTIME_MEMORY,
    build_runtime_memory_system_prompt,
)
from runtime.frame_memory_utils import get_session_title, preserve_session_title
from utils.session_restore import (
    build_archived_session_preview,
    list_archived_sessions,
)
from websocket.bootstrap import remove_runtime_memory_slot_by_key


class SessionTitleFrameTests(unittest.TestCase):
    def test_new_frame_starts_with_reserved_placeholder(self):
        self.assertEqual(
            INITIAL_RUNTIME_MEMORY,
            f"session_title: {DEFAULT_SESSION_TITLE}",
        )

    def test_prompt_requires_title_and_topic_continuity(self):
        prompt = build_runtime_memory_system_prompt(
            current_memory="session_title: Sourdough storage",
            user_message="continue",
        )
        self.assertIn("session_title is a mandatory reserved key", prompt)
        self.assertIn("Preserve the current wording", prompt)
        self.assertIn("dominant subject changes substantially", prompt)

    def test_new_title_replaces_previous_and_duplicates_are_collapsed(self):
        result = preserve_session_title(
            "session_title: Old\ntopic: x\nsession_title: New subject",
            "session_title: Previous subject",
        )
        self.assertEqual(get_session_title(result), "New subject")
        self.assertEqual(result.count("session_title:"), 1)

    def test_missing_title_is_recovered_from_previous_frame(self):
        result = preserve_session_title(
            "topic: unchanged",
            "session_title: Existing title\ntopic: old",
        )
        self.assertTrue(result.startswith("session_title: Existing title\n"))

    def test_long_generated_title_is_preserved_as_one_reserved_line(self):
        long_title = "Обсуждение пигментации овощей и смены режима общения " * 4
        result = preserve_session_title(f"session_title: {long_title}\ntopic: x")
        title = get_session_title(result)
        self.assertEqual(title, long_title.strip())
        self.assertTrue(result.startswith(f"session_title: {title}\n"))
        self.assertEqual(result.count("session_title:"), 1)

    def test_reserved_title_cannot_be_deleted(self):
        memory = "session_title: Keep me\ntopic: x"
        self.assertEqual(
            remove_runtime_memory_slot_by_key(memory, "session_title"),
            (memory, False),
        )


class ArchivedSessionIndexTests(unittest.TestCase):
    def _write_session(self, root, date, session_id, *, frame="", user=True):
        directory = root / date / session_id
        (directory / "frames").mkdir(parents=True)
        rows = []
        if user:
            rows.append({
                "ts": f"{date}T10:00:00+00:00",
                "turn": 1,
                "role": "user",
                "text": "hello",
            })
        (directory / "100000.jsonl").write_text(
            "\n".join(json.dumps(row) for row in rows),
            encoding="utf-8",
        )
        (directory / "100000.txt").write_text(
            "<FRAME_MEMORY_1>\nsession_title: Earlier title\n</FRAME_MEMORY_1>",
            encoding="utf-8",
        )
        if frame:
            snapshot = {"raw_memory": frame, "index": 2}
            (directory / "frames" / "100000_frame_2.txt").write_text(
                f"snapshot_json: {json.dumps(snapshot)}\n--- FRAME ---\n{frame}",
                encoding="utf-8",
            )

    def test_index_prefers_committed_frame_and_falls_back_to_session_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_session(
                root, "2026-09-28", "new-session",
                frame="session_title: Committed continuation\ntopic: x",
            )
            self._write_session(root, "2026-09-27", "legacy-session")
            (root / "2026-09-27" / "legacy-session" / "100000.txt").write_text(
                "<FRAME_MEMORY_1>\ntopic: legacy\n</FRAME_MEMORY_1>",
                encoding="utf-8",
            )
            self._write_session(root, "2026-09-29", "empty-session", user=False)
            self._write_session(root, "2026-09-29", "private_anon", user=True)

            sessions = list_archived_sessions(root=root)

        self.assertEqual(
            [(item["session_id"], item["title"]) for item in sessions],
            [
                ("new-session", "Committed continuation"),
                ("legacy-session", "legacy-session"),
            ],
        )

    def test_archived_session_summary_keeps_full_title(self):
        from utils.session_restore import get_archived_session_summary
        long_title = "Продолжение обсуждения пигментации овощей в режиме прямого диалога с выбором вектора анализа"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_session(
                root, "2026-09-29", "full-title-session",
                frame=f"session_title: {long_title}\ntopic: x",
            )
            self.assertEqual(
                get_archived_session_summary("full-title-session", root=root)["title"],
                long_title,
            )

    def test_summary_ignores_corrupted_latest_frame_and_uses_previous_commit(self):
        from utils.session_restore import get_archived_session_summary
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_session(root, "2026-09-29", "recover-session",
                                frame="session_title: Good saved title")
            frames = root / "2026-09-29" / "recover-session" / "frames"
            (frames / "100000_frame_3.txt").write_text(
                "snapshot_json: {bad json}\n--- FRAME ---\nsession_title: Invalid", encoding="utf-8"
            )
            summary = get_archived_session_summary("recover-session", root=root)
        self.assertEqual(summary["title"], "Good saved title")
        self.assertEqual(summary["date"], "2026-09-29")
        self.assertEqual(summary["created_at"], "2026-09-29T10:00:00+00:00")

    def test_preview_returns_only_five_newest_complete_pairs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "2026-09-28" / "preview-session"
            directory.mkdir(parents=True)
            rows = []
            for turn in range(1, 7):
                rows.extend([
                    {"turn": turn, "role": "user", "text": f"user {turn}"},
                    {"turn": turn, "role": "jin", "text": f"jin {turn}"},
                ])
            (directory / "100000.jsonl").write_text(
                "\n".join(json.dumps(row) for row in rows),
                encoding="utf-8",
            )
            preview = build_archived_session_preview(
                "preview-session",
                root=root,
            )

        self.assertEqual(len(preview["pairs"]), 5)
        self.assertEqual(preview["pairs"][0], {"user": "user 2", "jin": "jin 2"})
        self.assertEqual(preview["pairs"][-1], {"user": "user 6", "jin": "jin 6"})

    def test_preview_keeps_user_when_jin_is_empty_or_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "2026-09-13" / "action-only-session"
            directory.mkdir(parents=True)
            (directory / "100000.jsonl").write_text(
                "\n".join(json.dumps(row) for row in [
                    {"turn": 16, "role": "jin", "text": ""},
                    {"turn": 17, "role": "user", "text": "check the board"},
                    {"turn": 17, "role": "jin", "text": ""},
                    {"turn": 17, "role": "runtime", "event": "session_actions_snapshot"},
                    {"turn": 18, "role": "user", "text": "and another thing"},
                ]),
                encoding="utf-8",
            )
            preview = build_archived_session_preview("action-only-session", root=root)

        self.assertEqual(preview["pairs"], [
            {"user": "check the board", "jin": ""},
            {"user": "and another thing", "jin": ""},
        ])

    def test_preview_includes_latest_unanswered_turn_in_five_turn_limit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "2026-09-28" / "partial-session"
            directory.mkdir(parents=True)
            rows = []
            for turn in range(1, 7):
                rows.extend([
                    {"turn": turn, "role": "user", "text": f"user {turn}"},
                    {"turn": turn, "role": "jin", "text": f"jin {turn}"},
                ])
            rows.append({"turn": 7, "role": "user", "text": "unanswered"})
            (directory / "100000.jsonl").write_text(
                "\n".join(map(json.dumps, rows)), encoding="utf-8"
            )
            preview = build_archived_session_preview("partial-session", root=root)

        self.assertEqual([pair["user"] for pair in preview["pairs"]],
                         ["user 3", "user 4", "user 5", "user 6", "unanswered"])
        self.assertEqual(preview["pairs"][-1]["jin"], "")

    def test_preview_handles_attachment_only_and_unkeyed_legacy_turns(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "2026-09-28" / "legacy-session"
            directory.mkdir(parents=True)
            (directory / "100000.jsonl").write_text(
                "\n".join(map(json.dumps, [
                    {"role": "user", "text": "hello"},
                    {"role": "jin", "text": "hi"},
                    {"turn_id": "turn_2", "role": "user", "text": "",
                     "attachments": [{"name": "photo.png"}]},
                    {"turn_id": "turn_2", "role": "jin", "text": ""},
                ])), encoding="utf-8",
            )
            preview = build_archived_session_preview("legacy-session", root=root)

        self.assertEqual(preview["pairs"], [
            {"user": "hello", "jin": "hi"},
            {"user": "📎 photo.png", "jin": ""},
        ])

    def test_ui_lazily_loads_rows_and_hover_preview(self):
        source = Path("ui/static/js/runtime/runtime-memory-view.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("const LOGS_MEMORY_LAZY_BATCH_SIZE = 20", source)
        self.assertIn("archivedSessionCount = archivedSessions.length", source)
        self.assertNotIn('if (displayMode === "logs") archivedSessionsState = "idle"', source)
        self.assertIn("bindArchivedSessionHoverCard(row, session)", source)
        self.assertIn("new AbortController()", source)
        self.assertIn("payload.pairs.slice(-5)", source)
        self.assertIn("truncateArchivedSessionPreviewText(value, limit = 50)", source)
        self.assertIn("fallbackTitle: displayTitle", source)
        self.assertNotIn("metadataRows: displayTitle === sessionId", source)
        self.assertIn('label === "джин"', source)
        self.assertIn("restore_session=${encodeURIComponent(sessionId)}", source)
        css = Path("ui/static/css/runtime-memory.css").read_text(encoding="utf-8")
        hover_rule = css.split(
            ".runtime-memory-log-hover-card .runtime-memory-lt-hover-title {", 1
        )[1].split("}", 1)[0]
        self.assertIn("white-space: normal;", hover_rule)
        self.assertIn("overflow-wrap: anywhere;", hover_rule)
        self.assertIn("overflow: visible;", hover_rule)
