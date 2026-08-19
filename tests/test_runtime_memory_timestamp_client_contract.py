from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_MEMORY_VIEW_JS = (
    ROOT / "ui" / "static" / "js" / "runtime" / "runtime-memory-view.js"
)
RUNTIME_MEMORY_CSS = ROOT / "ui" / "static" / "css" / "runtime-memory.css"
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"


class RuntimeMemoryTitleClientContractTests(unittest.TestCase):

    def test_runtime_memory_header_stays_static(self):
        source = RUNTIME_MEMORY_VIEW_JS.read_text(encoding="utf-8")

        self.assertNotIn(
            "function formatRuntimeMemorySnapshotTitle(snapshot)",
            source,
        )
        self.assertNotIn(
            "runtime-memory-title-timestamp",
            source,
        )
        self.assertIn(
            ': "[ runtime memory ]";',
            source,
        )

    def test_runtime_memory_timestamp_title_style_removed(self):
        source = RUNTIME_MEMORY_CSS.read_text(encoding="utf-8")

        self.assertNotIn(
            "#runtime-memory-title.runtime-memory-title-timestamp",
            source,
        )

    def test_runtime_memory_assets_bump_cache_versions(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertGreaterEqual(
            source.count("runtime-memory-title=2"),
            2,
        )
        self.assertNotIn(
            "runtime-memory-ts=1",
            source,
        )


if __name__ == "__main__":
    unittest.main()
