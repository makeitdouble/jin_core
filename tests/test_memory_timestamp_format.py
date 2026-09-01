from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import json
import re
import unittest

from runtime.L1_memory_utils import format_runtime_memory_lifecycle_timestamp
from utils.actions.active_memory_utils import refresh_active_memory_runtime_metadata
from utils.brain_client_utils import build_delayed_memory_report
from utils.time_utils import format_utc_iso, utc_now_iso


ROOT = Path(__file__).resolve().parents[1]
MEMORY_VIEW = ROOT / "ui" / "static" / "js" / "runtime" / "runtime-memory-view.js"


class MemoryTimestampFormatTests(unittest.TestCase):

    def test_shared_utc_storage_format_uses_z_and_seconds(self):
        value = datetime(
            2026,
            9,
            1,
            15,
            41,
            47,
            928341,
            tzinfo=timezone(timedelta(hours=3)),
        )

        self.assertEqual(
            format_utc_iso(value),
            "2026-09-01T12:41:47Z",
        )
        self.assertRegex(
            utc_now_iso(),
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
        )

    def test_frame_lifecycle_timestamp_uses_shared_utc_storage_format(self):
        self.assertEqual(
            format_runtime_memory_lifecycle_timestamp(
                "2026-09-01T15:41:47+03:00"
            ),
            "2026-09-01T12:41:47Z",
        )

    def test_active_and_delayed_fallback_writers_are_timezone_aware(self):
        active = refresh_active_memory_runtime_metadata(
            "active_memory: keep this [ status: pending ]",
            context=SimpleNamespace(
                session_id="session-1",
                turn_number=1,
            ),
        )
        creation_match = re.search(
            r"\[ creation_time: ([^\]]+) \]",
            active,
        )
        self.assertIsNotNone(creation_match)
        self.assertRegex(
            creation_match.group(1),
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
        )

        report = build_delayed_memory_report(
            SimpleNamespace(
                session_id="session-1",
                runtime_long_term_memory_store={"facts": []},
            ),
            json.dumps({
                "abc123": {
                    "title": "Timestamp test",
                    "summary": "Summary",
                    "tags": [],
                    "body": "Body",
                },
            }),
        )
        self.assertRegex(
            report["abc123"]["created_time"],
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
        )
        self.assertEqual(
            report["abc123"]["created_date"],
            report["abc123"]["created_time"],
        )

    def test_memory_ui_has_one_local_display_formatter_for_all_memory_dates(self):
        source = MEMORY_VIEW.read_text(encoding="utf-8")

        self.assertIn("function formatMemoryTimestamp(value)", source)
        self.assertIn(
            '`${date.getDate()} ${MEMORY_MONTH_NAMES[date.getMonth()]} `',
            source,
        )
        self.assertIn('"Wednesday"', source)
        for key in (
            "created_at",
            "updated_at",
            "creation_time",
            "created_time",
            "created_date",
            "last_loaded_date",
        ):
            self.assertIn(f'"{key}"', source)

        self.assertIn(
            "valueNode.textContent = formatMemoryMetadataValue(key, value);",
            source,
        )
        self.assertIn(
            "return formatMemoryTimestamp(\n"
            "        normalizeDelayedMemoryDisplayText(value)\n"
            "    );",
            source,
        )


if __name__ == "__main__":
    unittest.main()
