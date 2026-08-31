import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from runtime.LT_memory_utils import normalize_lt_store
from runtime.LT_mention_backfill import (
    apply_lt_log_mention_backfill_to_store,
    load_or_create_lt_log_mention_backfill_state,
    scan_lt_log_fact_mentions,
)


class LTMentionBackfillTests(unittest.TestCase):
    def test_scanner_reads_only_jin_dialogue_and_reasoning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "logs"
            session = root / "2026-08-30" / "session-a"
            reasoning = session / "reasoning"
            reasoning.mkdir(parents=True)

            (session / "120000.jsonl").write_text(
                "\n".join([
                    json.dumps({
                        "ts": "2026-08-30T12:00:00+03:00",
                        "role": "user",
                        "text": "User says F1 but this must not count.",
                    }),
                    json.dumps({
                        "ts": "2026-08-30T12:01:00+03:00",
                        "role": "jin",
                        "text": "Visible answer cites F2 and F2 again.",
                    }),
                    json.dumps({
                        "ts": "2026-08-30T12:05:00+03:00",
                        "role": "jin",
                        "text": "Later answer cites F2 and F4.",
                    }),
                ]) + "\n",
                encoding="utf-8",
            )
            (reasoning / "120000_turn_000001.txt").write_text(
                "\n".join([
                    "captured_at: 2026-08-30T12:03:00+03:00",
                    "session_id: session-a",
                    "",
                    "--- REASONING ---",
                    "Thinking with F3 and F2.",
                ]),
                encoding="utf-8",
            )
            # Context dumps can contain the whole memory inventory; never scan it.
            (session / "120000.txt").write_text(
                "<LONG_TERM_MEMORY>F999 F998</LONG_TERM_MEMORY>",
                encoding="utf-8",
            )

            result = scan_lt_log_fact_mentions(
                log_root=root,
                fallback_at="2026-08-24T09:00:00Z",
                activated_at="2026-08-31T09:00:00Z",
            )

            self.assertNotIn("F1", result["latest_by_fact_id"])
            self.assertNotIn("F999", result["latest_by_fact_id"])
            self.assertEqual(
                result["latest_by_fact_id"]["F2"],
                "2026-08-30T09:05:00Z",
            )
            self.assertEqual(
                result["latest_by_fact_id"]["F3"],
                "2026-08-30T09:03:00Z",
            )
            self.assertEqual(
                result["latest_by_fact_id"]["F4"],
                "2026-08-30T09:05:00Z",
            )

    def test_backfill_maps_retired_source_ids_and_stales_unseen_facts(self):
        store = normalize_lt_store({
            "facts": [
                {
                    "id": "F20",
                    "key": "project.one",
                    "value": "One",
                    "mention_count": 7,
                    "last_mentioned_at": "2026-08-31T08:30:00Z",
                    "created_at": "2026-08-20T12:00:00Z",
                    "updated_at": "2026-08-31T08:30:00Z",
                    "source_fact_ids": ["F2"],
                },
                {
                    "id": "F21",
                    "key": "project.two",
                    "value": "Two",
                    "mention_count": 4,
                    "last_mentioned_at": "2026-08-31T08:00:00Z",
                    "created_at": "2026-08-20T12:00:00Z",
                    "updated_at": "2026-08-31T08:00:00Z",
                },
            ],
        }, now="2026-08-31T08:30:00Z")

        repaired, change = apply_lt_log_mention_backfill_to_store(
            store,
            latest_by_fact_id={
                "F2": "2026-08-30T18:15:00Z",
            },
            fallback_at="2026-08-24T09:00:00Z",
            activated_at="2026-08-31T09:00:00Z",
            now="2026-08-31T09:01:00Z",
        )

        facts = {fact["id"]: fact for fact in repaired["facts"]}
        self.assertEqual(facts["F20"]["last_mentioned_at"], "2026-08-30T18:15:00Z")
        self.assertEqual(facts["F21"]["last_mentioned_at"], "2026-08-24T09:00:00Z")
        self.assertEqual(facts["F20"]["mention_count"], 7)
        self.assertEqual(facts["F21"]["mention_count"], 4)
        self.assertEqual(change["mentioned_fact_ids"], ["F20"])
        self.assertEqual(change["fallback_fact_ids"], ["F21"])

    def test_backfill_never_rewinds_post_activation_live_mentions_or_new_facts(self):
        store = normalize_lt_store({
            "facts": [
                {
                    "id": "F9",
                    "key": "project.live",
                    "value": "Live",
                    "last_mentioned_at": "2026-08-31T09:02:00Z",
                    "created_at": "2026-08-20T12:00:00Z",
                    "updated_at": "2026-08-20T12:00:00Z",
                },
                {
                    "id": "F10",
                    "key": "project.new",
                    "value": "New",
                    "last_mentioned_at": "2026-08-31T09:03:00Z",
                    "created_at": "2026-08-31T09:03:00Z",
                    "updated_at": "2026-08-31T09:03:00Z",
                },
            ],
        }, now="2026-08-31T09:03:00Z")

        repaired, change = apply_lt_log_mention_backfill_to_store(
            store,
            latest_by_fact_id={
                "F9": "2026-08-28T10:00:00Z",
                "F10": "2026-08-28T11:00:00Z",
            },
            fallback_at="2026-08-24T09:00:00Z",
            activated_at="2026-08-31T09:00:00Z",
            now="2026-08-31T09:04:00Z",
        )

        facts = {fact["id"]: fact for fact in repaired["facts"]}
        self.assertFalse(change["changed"])
        self.assertEqual(facts["F9"]["last_mentioned_at"], "2026-08-31T09:02:00Z")
        self.assertEqual(facts["F10"]["last_mentioned_at"], "2026-08-31T09:03:00Z")

    def test_state_freezes_fallback_boundary_across_bootstraps(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first = load_or_create_lt_log_mention_backfill_state(
                facts_root=temp_dir,
                now=datetime(2026, 8, 31, 9, 0, tzinfo=timezone.utc),
            )
            second = load_or_create_lt_log_mention_backfill_state(
                facts_root=temp_dir,
                now=datetime(2026, 9, 5, 9, 0, tzinfo=timezone.utc),
            )

            self.assertEqual(first, second)
            self.assertEqual(first["activated_at"], "2026-08-31T09:00:00Z")
            self.assertEqual(first["fallback_at"], "2026-08-24T09:00:00Z")

    def test_websocket_sync_schedules_backfill_without_awaiting_it(self):
        source = (
            Path(__file__).resolve().parents[1] / "websocket" / "__init__.py"
        ).read_text(encoding="utf-8")
        sync_start = source.index('if message_type == "lt_memory_store_sync":')
        sync_end = source.index('if message_type == "lt_memory_idle_tick":', sync_start)
        block = source[sync_start:sync_end]

        self.assertIn("schedule_lt_log_mention_backfill(\n                    context\n                )", block)
        self.assertNotIn("await schedule_lt_log_mention_backfill", block)


if __name__ == "__main__":
    unittest.main()
