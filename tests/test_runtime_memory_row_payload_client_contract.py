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


class RuntimeMemoryRowPayloadClientContractTests(unittest.TestCase):

    def test_rich_row_payload_is_kept_out_of_dom_datasets(self):
        source = MEMORY_VIEW_JS.read_text(encoding="utf-8")

        self.assertIn(
            "const runtimeMemoryRowState = new WeakMap();",
            source,
        )
        self.assertIn(
            "function setRuntimeMemoryRowState(row, values)",
            source,
        )
        self.assertNotIn(
            "row.dataset.runtimeMemoryLineIdentity =",
            source,
        )
        self.assertNotIn(
            "row.dataset.runtimeMemoryLineKey =",
            source,
        )
        self.assertNotIn(
            "row.dataset.runtimeMemoryLineText =",
            source,
        )
        self.assertNotIn(
            "row.dataset.runtimeMemoryValueDefaultText =",
            source,
        )
        self.assertNotIn(
            "row.dataset.runtimeMemoryValueFullText =",
            source,
        )
        self.assertNotIn(
            "[data-memory-reference-aliases]",
            source,
        )
        self.assertNotIn(
            "[data-runtime-memory-line-key]",
            source,
        )

    def test_hover_and_highlight_payload_still_uses_same_semantics(self):
        source = MEMORY_VIEW_JS.read_text(encoding="utf-8")

        self.assertIn(
            "runtimeMemoryLineIdentity: lineIdentity",
            source,
        )
        self.assertIn(
            "runtimeMemoryLineKey:",
            source,
        )
        self.assertIn(
            "runtimeMemoryLineText:",
            source,
        )
        self.assertIn(
            "runtimeMemoryValueDefaultText:",
            source,
        )
        self.assertIn(
            "runtimeMemoryValueFullText:",
            source,
        )
        self.assertIn(
            "getMemoryReferenceAliases(row).length",
            source,
        )
        self.assertIn(
            '!row.classList.contains("runtime-memory-lt-row")',
            source,
        )
        self.assertIn(
            "getRuntimeMemoryRowCitationState(row)",
            source,
        )
        self.assertIn(
            "let hoverTitle = null;",
            source,
        )
        self.assertIn(
            "formatRuntimeMemoryHoverTitle(",
            source,
        )

    def test_memory_view_cache_key_is_bumped_for_row_payload_cleanup(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn("row-payload=1", source)


if __name__ == "__main__":
    unittest.main()
