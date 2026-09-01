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


class MemoryValueEditClientContractTests(unittest.TestCase):

    def test_active_and_lt_edit_ack_upserts_updated_at_in_open_editor(self):
        source = MEMORY_VIEW.read_text(encoding="utf-8")
        helper_start = source.index("function updateMemoryValueEditorMetadataRow(")
        handler_start = source.index("function handleMemoryValueEditResult(", helper_start)
        helper_source = source[helper_start:handler_start]
        handler_end = source.index("function openMemoryValueEditor(", handler_start)
        handler_source = source[handler_start:handler_end]

        self.assertIn("createIfMissing = false", helper_source)
        self.assertIn("if (!createIfMissing) return;", helper_source)
        self.assertIn("appendLongTermMemoryHoverMetadataRow(", helper_source)
        self.assertIn(
            '(memoryValueEditor.kind === "active" || memoryValueEditor.kind === "lt")',
            handler_source,
        )
        self.assertIn('"updated_at",', handler_source)
        self.assertIn("{ createIfMissing: true }", handler_source)

    def test_active_conditions_metadata_is_not_created_for_legacy_records(self):
        source = MEMORY_VIEW.read_text(encoding="utf-8")
        handler_start = source.index("function handleMemoryValueEditResult(")
        handler_end = source.index("function openMemoryValueEditor(", handler_start)
        handler_source = source[handler_start:handler_end]

        conditions_start = handler_source.index('"conditions",')
        updated_start = handler_source.index('"updated_at",')
        conditions_source = handler_source[conditions_start:updated_start]

        self.assertNotIn("createIfMissing", conditions_source)

    def test_runtime_memory_view_cache_buster_is_updated(self):
        source = INDEX_HTML.read_text(encoding="utf-8")
        self.assertEqual(source.count("memory-value-edit=2"), 1)


if __name__ == "__main__":
    unittest.main()
