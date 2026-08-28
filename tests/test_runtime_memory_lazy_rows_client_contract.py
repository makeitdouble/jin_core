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
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"


class RuntimeMemoryLazyRowsClientContractTests(unittest.TestCase):

    def test_memory_panels_use_independent_lazy_batch_sizes(self):
        source = MEMORY_VIEW_JS.read_text(encoding="utf-8")

        expected_constants = (
            "const ACTIVE_MEMORY_LAZY_BATCH_SIZE = 50;",
            "const DELAYED_MEMORY_LAZY_BATCH_SIZE = 50;",
            "const FACTS_MEMORY_LAZY_BATCH_SIZE = 50;",
            "const LONG_TERM_MEMORY_LAZY_BATCH_SIZE = 20;",
            "const FILES_MEMORY_LAZY_BATCH_SIZE = 50;",
        )

        for declaration in expected_constants:
            self.assertIn(declaration, source)

        self.assertIn(
            "function getRuntimeMemoryLazyBatchSize(displayMode)",
            source,
        )
        self.assertIn(
            "getRuntimeMemoryLazyBatchSize(runtimeMemoryLazyMode)",
            source,
        )
        self.assertIn("start + nextBatchSize", source)
        self.assertIn("nextBatchSize = batchSize", source)
        self.assertIn("options.initialBatchSize", source)
        self.assertIn("const initialBatchSize =", source)
        self.assertNotIn(
            "const RUNTIME_MEMORY_LAZY_BATCH_SIZE =",
            source,
        )

    def test_lazy_rows_are_not_precreated_and_hidden_in_dom(self):
        source = MEMORY_VIEW_JS.read_text(encoding="utf-8")

        self.assertNotIn(
            "runtimeMemoryVisibleRowCount",
            source,
        )
        self.assertIn(
            "runtimeMemoryLazyAppendBatch = appendBatch;",
            source,
        )
        self.assertIn(
            "runtimeMemoryLazyAppendBatch();",
            source,
        )

    def test_next_batch_loads_only_near_panel_bottom(self):
        source = MEMORY_VIEW_JS.read_text(encoding="utf-8")

        self.assertIn(
            "remaining <= RUNTIME_MEMORY_LAZY_BOTTOM_THRESHOLD_PX",
            source,
        )
        self.assertNotIn(
            "runtimeMemoryFirstScrollBatchLoaded",
            source,
        )

    def test_native_scroll_path_is_not_debounced_after_downward_progress(self):
        source = MEMORY_VIEW_JS.read_text(encoding="utf-8")
        start = source.index("function handleRuntimeMemoryLazyScroll()")
        end = source.index("function handleRuntimeMemoryLazyWheel(event)", start)
        scroll_handler = source[start:end]

        self.assertIn("if (!scrollingDown)", scroll_handler)
        self.assertNotIn("runtimeMemoryLastBatchRevealAt", scroll_handler)
        self.assertIn(
            "remaining <= RUNTIME_MEMORY_LAZY_BOTTOM_THRESHOLD_PX",
            scroll_handler,
        )

    def test_l4_rerender_preserves_materialized_depth_and_scroll_position(self):
        source = MEMORY_VIEW_JS.read_text(encoding="utf-8")
        start = source.index("function renderLongTermMemoryFacts()")
        end = source.index("function renderActiveMemoryRecords()", start)
        block = source[start:end]

        self.assertIn("const preservedRenderedCount =", block)
        self.assertIn("runtimeMemoryLazyRenderedCount;", block)
        self.assertIn("const preservedScrollTop =", block)
        self.assertIn("initialBatchSize: renderBatchSize", block)
        self.assertIn("memoryScroll.scrollTop = Math.min(", block)
        self.assertIn("runtimeMemoryLastScrollTop =", block)


    def test_memory_view_cache_key_is_bumped_for_l4_lazy_optimization(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn("lazy-rows=6", source)
        self.assertIn("l4-priority-bubble=1", source)


if __name__ == "__main__":
    unittest.main()
