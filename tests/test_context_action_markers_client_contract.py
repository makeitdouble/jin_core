import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ContextActionMarkersClientContractTests(unittest.TestCase):

    def test_action_markers_are_direct_cards_in_the_actions_panel(self):
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
            "const actionBlocks = blocks.filter(",
            source,
        )
        self.assertIn(
            'const actionsStack = panelStack("actions");',
            source,
        )
        self.assertIn(
            "actionBlocks.forEach((block) => appendContextCard(",
            source,
        )
        self.assertNotIn(
            "function appendContextActionMarkersCard(",
            source,
        )

    def test_plain_runtime_action_titles_are_detected(self):
        source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "logger"
            / "trace-modal.js"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "const titleMatch =",
            source,
        )
        self.assertIn(
            "^([A-Z][A-Z0-9_]*)$",
            source,
        )
        self.assertIn(
            "return titleMatch",
            source,
        )

    def test_global_collapse_collects_direct_cards_from_all_snapshot_sections(self):
        source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "logger"
            / "trace-modal.js"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "const getAllCards = () => [",
            source,
        )
        self.assertIn(
            "...getCardsInStack(userStack)",
            source,
        )
        self.assertIn(
            'tabPanels.get(definition.key)\n          .querySelector(".jin-context-tab-stack")',
            source,
        )
        self.assertIn(
            "...getCardsInStack(commonStack)",
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
