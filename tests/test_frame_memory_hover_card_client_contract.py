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


class FrameMemoryHoverCardClientContractTests(unittest.TestCase):

    def test_frame_rows_use_custom_hover_card(self):
        source = MEMORY_VIEW.read_text(encoding="utf-8")
        append_start = source.index("function appendRuntimeMemoryLineRows(")
        append_end = source.index(
            "function getRuntimeMemoryLineStatus",
            append_start,
        )
        append_source = source[append_start:append_end]

        self.assertIn(
            'row.classList.add(\n'
            '            "runtime-memory-frame-row"\n'
            '        );',
            append_source,
        )
        self.assertIn(
            "bindFrameMemoryHoverCard(\n"
            "            row,\n"
            "            line\n"
            "        );",
            append_source,
        )

    def test_frame_hover_card_orders_key_value_and_created_at(self):
        source = MEMORY_VIEW.read_text(encoding="utf-8")
        details_start = source.index("function buildMemoryDetailsHoverCard(")
        details_end = source.index(
            "function showLongTermMemoryHoverCard",
            details_start,
        )
        details_source = source[details_start:details_end]
        show_start = source.index("function showFrameMemoryHoverCard(anchor, line)")
        show_end = source.index(
            "function bindFrameMemoryHoverCard",
            show_start,
        )
        show_source = source[show_start:show_end]

        title_position = details_source.index("card.appendChild(header);")
        value_position = details_source.index("card.appendChild(summary);")
        metadata_position = details_source.index("card.appendChild(metadata);")

        self.assertLess(title_position, value_position)
        self.assertLess(value_position, metadata_position)
        self.assertIn("options.includeTags !== false", details_source)
        self.assertIn("options.metadataRows", details_source)
        self.assertIn('fallbackTitle: "Frame memory"', show_source)
        self.assertIn("includeTags: false", show_source)
        self.assertIn('["created_at", line.created_at]', show_source)

    def test_frame_hover_tracks_scroll_and_is_cleaned_up(self):
        source = MEMORY_VIEW.read_text(encoding="utf-8")

        self.assertIn(
            '".runtime-memory-frame-row:hover"',
            source,
        )
        self.assertIn(
            "scheduleFrameMemoryHoverCardScrollSync();",
            source,
        )
        self.assertIn(
            'if (displayMode !== "runtime") {\n'
            "      hideFrameMemoryHoverCard();\n"
            "    }",
            source,
        )
        self.assertIn(
            'row.addEventListener("pointerdown", () => {\n'
            "      hideFrameMemoryHoverCard(row);",
            source,
        )

    def test_hover_card_script_is_cache_busted(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertEqual(source.count("frame-hover-card=1"), 1)


if __name__ == "__main__":
    unittest.main()
