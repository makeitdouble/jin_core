import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from utils.delayed_memory_file_store import (
    build_delayed_memory_file_payload,
    load_delayed_memory_reports_from_files,
    merge_delayed_memory_reports,
    persist_delayed_memory_report,
)
from websocket.bootstrap import apply_delayed_memory_reports


class DelayedMemoryFileStoreTests(unittest.TestCase):

    def build_report(
        self,
        *,
        title: str = "Внутреннее эхо JIN",
        body: str = "Body",
    ) -> dict:

        return {
            "title": title,
            "summary": "Summary",
            "tags": [
                "identity",
                "evolution",
            ],
            "body": body,
            "pinned": True,
            "anchor_fact_ids": [
                "F1",
            ],
            "absorbed_fact_ids": [
                "F2",
            ],
            "created_session_id": "session-a",
            "created_time": "2026-07-19T16:14:14.628194",
            "created_date": "2026-07-19T16:14:14.628194",
            "all_appended_session_ids": [
                "session-a",
            ],
        }

    def test_persist_and_load_direct_report_shape(self):

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            path = persist_delayed_memory_report(
                "48ggds",
                self.build_report(),
                root=root,
            )

            self.assertEqual(
                path.name,
                "48ggds_Внутреннее_эхо_JIN.json",
            )

            payload = json.loads(
                path.read_text(
                    encoding="utf-8",
                )
            )

            self.assertEqual(
                payload["id"],
                "48ggds",
            )
            self.assertEqual(
                payload["session"],
                "session-a",
            )
            self.assertEqual(
                payload["time"],
                "2026-07-19T16:14:14.628194",
            )
            self.assertEqual(
                payload["pinned"],
                True,
            )
            self.assertEqual(
                payload["anchor_fact_ids"],
                [
                    "F1",
                ],
            )
            self.assertEqual(
                payload["absorbed_fact_ids"],
                [
                    "F2",
                ],
            )

            reports, warnings = (
                load_delayed_memory_reports_from_files(
                    root=root,
                )
            )

            self.assertEqual(
                warnings,
                [],
            )
            self.assertEqual(
                reports["48ggds"]["title"],
                "Внутреннее эхо JIN",
            )
            self.assertEqual(
                reports["48ggds"]["created_session_id"],
                "session-a",
            )
            self.assertEqual(
                reports["48ggds"]["pinned"],
                True,
            )
            self.assertEqual(
                reports["48ggds"]["anchor_fact_ids"],
                [
                    "F1",
                ],
            )
            self.assertEqual(
                reports["48ggds"]["absorbed_fact_ids"],
                [
                    "F2",
                ],
            )

    def test_save_replaces_old_filename_for_same_id(self):

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)

            persist_delayed_memory_report(
                "48ggds",
                self.build_report(
                    title="Old title",
                ),
                root=root,
            )
            path = persist_delayed_memory_report(
                "48ggds",
                self.build_report(
                    title="New title",
                ),
                root=root,
            )

            self.assertEqual(
                path.name,
                "48ggds_New_title.json",
            )
            self.assertEqual(
                [
                    item.name
                    for item in root.glob("48ggds_*.json")
                ],
                [
                    "48ggds_New_title.json",
                ],
            )

    def test_invalid_files_are_skipped_without_crashing(self):

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            root.joinpath("broken.json").write_text(
                "{not json",
                encoding="utf-8",
            )
            root.joinpath("invalid_report.json").write_text(
                json.dumps({
                    "id": "invalid",
                    "title": "Bad report",
                }),
                encoding="utf-8",
            )
            persist_delayed_memory_report(
                "48ggds",
                self.build_report(),
                root=root,
            )

            reports, warnings = (
                load_delayed_memory_reports_from_files(
                    root=root,
                )
            )

            self.assertEqual(
                set(reports),
                {
                    "48ggds",
                },
            )
            self.assertEqual(
                len(warnings),
                2,
            )
            self.assertTrue(
                any(
                    "broken.json" in warning
                    for warning in warnings
                )
            )
            self.assertTrue(
                any(
                    "invalid_report.json" in warning
                    for warning in warnings
                )
            )

    def test_local_storage_reports_override_file_fallback_by_id(self):

        file_reports = {
            "48ggds": self.build_report(
                title="File title",
            ),
            "a1b2c3": self.build_report(
                title="File only",
            ),
        }
        browser_report = self.build_report(
            title="Browser title",
        )
        browser_report["absorbed_fact_ids"] = []
        browser_reports = {
            "48ggds": browser_report,
        }

        merged = merge_delayed_memory_reports(
            browser_reports,
            file_reports,
        )

        self.assertEqual(
            merged["48ggds"]["title"],
            "Browser title",
        )
        self.assertEqual(
            merged["a1b2c3"]["title"],
            "File only",
        )
        self.assertEqual(
            merged["48ggds"]["anchor_fact_ids"],
            [
                "F1",
            ],
        )
        self.assertEqual(
            merged["48ggds"]["absorbed_fact_ids"],
            [
                "F2",
            ],
        )

    def test_websocket_sync_merges_browser_primary_with_file_fallback(self):

        context = SimpleNamespace(
            delayed_memory_reports={
                "48ggds": self.build_report(
                    title="File title",
                ),
                "a1b2c3": self.build_report(
                    title="File only",
                ),
            },
        )

        apply_delayed_memory_reports(
            context,
            {
                "delayed_memory_reports": {
                    "48ggds": self.build_report(
                        title="Browser title",
                    ),
                },
            },
        )

        self.assertEqual(
            context.delayed_memory_reports["48ggds"]["title"],
            "Browser title",
        )
        self.assertEqual(
            context.delayed_memory_reports["a1b2c3"]["title"],
            "File only",
        )

    def test_file_payload_accepts_example_aliases(self):

        payload = build_delayed_memory_file_payload(
            "48ggds",
            {
                "title": "Внутреннее эхо JIN",
                "summary": "Summary",
                "time": "2026-07-19 16:14, Sunday",
                "tags": [
                    "identity",
                ],
                "id": "48ggds",
                "session": "session-a",
                "created_date": "2026-07-19T16:14:14.628194",
                "all_appended_session_ids": [],
                "body": "Body",
            },
        )

        self.assertEqual(
            payload["time"],
            "2026-07-19 16:14, Sunday",
        )
        self.assertEqual(
            payload["session"],
            "session-a",
        )


if __name__ == "__main__":
    unittest.main()
