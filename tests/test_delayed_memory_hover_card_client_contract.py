from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MEMORY_VIEW = (
    ROOT
    / "ui"
    / "static"
    / "js"
    / "runtime"
    / "runtime-memory-view.js"
)
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"


class DelayedMemoryHoverCardClientContractTests(unittest.TestCase):

    def test_delayed_rows_use_the_existing_custom_hover_card(self):
        source = MEMORY_VIEW.read_text(encoding="utf-8")
        render_start = source.index("function renderDelayedMemoryReports()")
        render_end = source.index(
            "function normalizeDelayedMemoryDisplayText",
            render_start,
        )
        render_source = source[render_start:render_end]

        self.assertIn(
            "bindDelayedMemoryHoverCard(\n"
            "          row,\n"
            "          report\n"
            "        );",
            render_source,
        )
        self.assertNotIn(
            "bindRuntimeMemoryHoverTitle(\n"
            "          row,\n"
            "          hoverTitle\n"
            "        );",
            render_source,
        )
        self.assertIn(
            'card.className =\n'
            '        "runtime-memory-lt-hover-card";',
            source,
        )
        self.assertIn("positionLongTermMemoryHoverCard(card, anchor);", source)

    def test_hover_card_contains_only_the_requested_report_preview(self):
        source = MEMORY_VIEW.read_text(encoding="utf-8")
        build_start = source.index("function buildDelayedMemoryHoverCard(report)")
        build_end = source.index(
            "function hideDelayedMemoryHoverCard",
            build_start,
        )
        build_source = source[build_start:build_end]

        for field in (
            '"created_at"',
            '"tags"',
            '"id"',
            '"anchor_fact_ids"',
            '"body"',
        ):
            self.assertIn(field, build_source)

        for excluded_field in (
            "facts_ids",
            "attachments_ids",
            "created_session_id",
            "loaded_times",
            "load_streak",
            "last_loaded_date",
            "all_loaded_session_ids",
        ):
            self.assertNotIn(excluded_field, build_source)

        self.assertIn("limit = 200", source)
        self.assertIn('characters.slice(0, limit).join("")', source)
        self.assertIn("report && report.summary", build_source)
        self.assertIn("report && report.title", build_source)

    def test_hover_card_tracks_scroll_and_is_removed_outside_delayed_view(self):
        source = MEMORY_VIEW.read_text(encoding="utf-8")

        self.assertIn(
            '".runtime-memory-delayed-row:hover"',
            source,
        )
        self.assertIn(
            "scheduleDelayedMemoryHoverCardScrollSync();",
            source,
        )
        self.assertIn(
            'if (displayMode !== "delayed") {\n'
            "      hideDelayedMemoryHoverCard();\n"
            "    }",
            source,
        )
        self.assertIn(
            'row.addEventListener("pointerdown", () => {\n'
            "      hideDelayedMemoryHoverCard(row);",
            source,
        )

    def test_hover_card_script_is_cache_busted(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertEqual(source.count("delayed-hover-card=1"), 1)


if __name__ == "__main__":
    unittest.main()
