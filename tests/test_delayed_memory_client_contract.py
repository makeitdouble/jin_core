import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DelayedMemoryClientContractTests(unittest.TestCase):

    def test_remove_delayed_memory_does_not_rewrite_saved_reports(self):

        source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "socket"
            / "runtime-actions.js"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            'action === "remove_delayed_memory"',
            source,
        )
        self.assertNotIn(
            "replaceDelayedMemoryReports",
            source,
        )
        self.assertNotRegex(
            source,
            r"delete\s+reports\s*\[",
        )

    def test_delayed_memory_append_metadata_is_persisted_client_side(self):

        storage_source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "runtime"
            / "runtime-storage.js"
        ).read_text(
            encoding="utf-8"
        )
        runtime_actions_source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "socket"
            / "runtime-actions.js"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "appended_times",
            storage_source,
        )
        self.assertIn(
            "append_streak",
            storage_source,
        )
        self.assertIn(
            "last_appended_session_id",
            storage_source,
        )
        self.assertIn(
            "all_appended_session_ids",
            storage_source,
        )
        self.assertIn(
            "collectCurrentSessionAppendedMemoryIds",
            storage_source,
        )
        self.assertIn(
            'action === "append_delayed_memory"',
            runtime_actions_source,
        )
        self.assertIn(
            "data.delayed_memory_result.report",
            runtime_actions_source,
        )

    def test_session_snapshot_history_and_appended_ids_are_persisted(self):

        storage_source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "runtime"
            / "runtime-storage.js"
        ).read_text(
            encoding="utf-8"
        )
        session_source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "runtime"
            / "runtime-session.js"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "jin.savedSessionMemoryHistory.v1",
            storage_source,
        )
        self.assertIn(
            "archiveLatestSavedSessionMemory",
            storage_source,
        )
        self.assertIn(
            "readSavedSessionMemoryHistory",
            storage_source,
        )
        self.assertIn(
            "appended_memory_ids",
            session_source,
        )
        self.assertIn(
            "collectCurrentSessionAppendedMemoryIds()",
            session_source,
        )


if __name__ == "__main__":
    unittest.main()
