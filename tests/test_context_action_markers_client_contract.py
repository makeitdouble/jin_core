import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ContextActionMarkersClientContractTests(unittest.TestCase):

    def test_action_markers_are_grouped_and_collapsed_by_default(self):
        source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "logger"
            / "trace-modal.js"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "runtimeActionMarker,",
            source,
        )
        self.assertIn(
            'title: "ACTION MARKERS",',
            source,
        )
        self.assertIn(
            'metaLabel: `${markerBlocks.length} markers`,',
            source,
        )
        self.assertIn(
            '"jin-context-card-action-markers"',
            source,
        )
        self.assertIn(
            "setContextCardCollapsed(\n    groupCard,\n    true",
            source,
        )
        self.assertIn(
            "block.runtimeActionMarker === true",
            source,
        )

    def test_expanding_action_markers_expands_each_nested_marker(self):
        source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "logger"
            / "trace-modal.js"
        ).read_text(encoding="utf-8")

        self.assertIn(
            '".jin-context-action-markers-stack"',
            source,
        )
        self.assertIn(
            "setContextCardCollapsed(\n          markerCard,\n          false",
            source,
        )

    def test_context_and_delayed_cards_do_not_render_collapse_chevrons(self):
        trace_source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "logger"
            / "trace-modal.js"
        ).read_text(encoding="utf-8")
        memory_view_source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "runtime"
            / "runtime-memory-view.js"
        ).read_text(encoding="utf-8")

        self.assertNotIn(
            '"jin-context-card-chevron",\n      "▾"',
            trace_source,
        )
        self.assertNotIn(
            'chevron.className =\n        "jin-context-card-chevron"',
            memory_view_source,
        )


if __name__ == "__main__":
    unittest.main()
