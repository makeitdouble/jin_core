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

    def test_memory_panels_materialize_rows_in_batches_of_forty(self):
        source = MEMORY_VIEW_JS.read_text(encoding="utf-8")

        self.assertIn(
            "const RUNTIME_MEMORY_LAZY_BATCH_SIZE = 40;",
            source,
        )
        self.assertIn(
            "function beginRuntimeMemoryLazyCollection(items, renderItem)",
            source,
        )
        self.assertIn(
            "for (let index = start; index < end; index += 1)",
            source,
        )
        self.assertGreaterEqual(
            source.count("beginRuntimeMemoryLazyCollection("),
            4,
        )

    def test_lazy_rows_are_not_precreated_and_hidden_in_dom(self):
        source = MEMORY_VIEW_JS.read_text(encoding="utf-8")

        self.assertNotIn(
            'row.style.display =\n          index < runtimeMemoryVisibleRowCount',
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

    def test_memory_view_cache_key_is_bumped_for_lazy_materialization(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn("lazy-rows=2", source)


if __name__ == "__main__":
    unittest.main()
