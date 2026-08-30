from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MEMORY_VIEW_JS = (
    ROOT
    / "ui"
    / "static"
    / "js"
    / "runtime"
    / "runtime-memory-view.js"
)


def function_block(source, start_marker, end_marker):
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]


class RuntimeMemoryLTRenderPerfClientContractTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.source = MEMORY_VIEW_JS.read_text(encoding="utf-8")

    def test_lt_line_objects_are_built_only_when_lazy_batch_materializes(self):
        block = function_block(
            self.source,
            "function renderLongTermMemoryFacts()",
            "function renderActiveMemoryRecords()",
        )

        self.assertIn("appendRuntimeMemoryLineRows(", block)
        self.assertIn("records,", block)
        self.assertIn(
            "buildLine: fact => buildLongTermMemoryLine(",
            block,
        )
        self.assertNotIn("records.map(", block)

    def test_delayed_report_links_are_indexed_once_per_lt_render(self):
        block = function_block(
            self.source,
            "function renderLongTermMemoryFacts()",
            "function renderActiveMemoryRecords()",
        )

        self.assertIn(
            "buildDelayedMemoryFactReportIndex(",
            block,
        )
        self.assertIn("delayedReports", block)
        self.assertIn(
            "delayedReportByFactId instanceof Map",
            self.source,
        )
        self.assertIn(
            "delayedReportByFactId.get(normalizedFactId)",
            self.source,
        )

    def test_lt_metrics_are_lazy_and_do_not_build_a_giant_joined_string(self):
        block = function_block(
            self.source,
            "function renderLongTermMemoryFacts()",
            "function renderActiveMemoryRecords()",
        )
        metrics = function_block(
            self.source,
            "function updateRuntimeMemoryTitleMetricsFromItems(",
            "function clampRuntimeMemoryHistoryIndex()",
        )

        self.assertIn("updateRuntimeMemoryTitleMetricsFromItems(", block)
        self.assertNotIn('.join("\\n")', block)
        self.assertIn("let cachedTitle = null;", metrics)
        self.assertIn("bindRuntimeMemoryHoverTitle(", metrics)
        self.assertNotIn("Array.from(metricText)", self.source)

    def test_mode_availability_uses_cheap_presence_checks(self):
        block = function_block(
            self.source,
            "function getAvailableRuntimeMemoryDisplayModes()",
            "function ensureRuntimeMemoryDisplayModeAvailable(",
        )

        self.assertIn("hasLongTermMemoryFactRecords()", block)
        self.assertNotIn("getLongTermMemoryFactRecords().length", block)
        self.assertIn(
            "Array.isArray(options.availableModes)",
            self.source,
        )
        self.assertIn("availableModes: modes,", self.source)

    def test_highlight_pipeline_reuses_one_rendered_row_collection(self):
        reference_block = function_block(
            self.source,
            "function applyMemoryReferenceHighlights(options = {})",
            "function shouldReduceRuntimeMemoryMotion()",
        )
        citation_block = function_block(
            self.source,
            "function applyThinkMemoryCitationHighlights(options = {})",
            "function handleThinkMemoryCitationHighlight(event)",
        )
        sort_block = function_block(
            self.source,
            "function sortHighlightedMemoryRows(options = {})",
            "function getActiveThinkMemoryCitationIdentitySets()",
        )

        self.assertIn("Array.isArray(options.rows)", reference_block)
        self.assertIn("rows,", reference_block)
        self.assertIn("Array.isArray(options.rows)", citation_block)
        self.assertIn("rows,", citation_block)
        self.assertIn("Array.isArray(options.rows)", sort_block)
        self.assertNotIn(
            "rows.forEach(\n      syncLongTermMemoryRowValueDisplay",
            sort_block,
        )
        self.assertIn(
            "if (!options.interactiveLongTermMemory) {",
            self.source,
        )

    def test_lt_value_sync_skips_unchanged_dom_text(self):
        block = function_block(
            self.source,
            "function syncLongTermMemoryRowValueDisplay(row)",
            "function clearRuntimeMemoryHighlightClasses()",
        )

        self.assertIn("valueSpan.firstChild", block)
        self.assertIn(
            "if (valueTextNode.nodeValue !== nextValue)",
            block,
        )


if __name__ == "__main__":
    unittest.main()
