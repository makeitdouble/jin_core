from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_JS = ROOT / "ui" / "static" / "js" / "runtime" / "runtime.js"
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"


class ActiveMemoryPauseSyncClientContractTests(unittest.TestCase):

    def test_memory_panel_writes_sync_active_store_before_later_edits(self):
        source = RUNTIME_JS.read_text(encoding="utf-8")
        start = source.index("function writeActiveMemoryRecordsAndRefresh(")
        end = source.index("\nfunction showLatestRuntimeMemorySnapshot()", start)
        block = source[start:end]

        self.assertIn("const activeMemoryRecords =", block)
        self.assertIn("readActiveMemoryRecords();", block)
        self.assertIn('type: "active_memory_store_sync"', block)
        self.assertIn("active_memory_records: activeMemoryRecords", block)
        self.assertLess(
            block.index('type: "active_memory_store_sync"'),
            block.index("dispatchActiveMemoryRecordsChanged("),
        )



if __name__ == "__main__":
    unittest.main()
