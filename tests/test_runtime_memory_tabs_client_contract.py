from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"
MEMORY_VIEW_JS = (
    ROOT / "ui" / "static" / "js" / "runtime" / "runtime-memory-view.js"
)
RUNTIME_JS = ROOT / "ui" / "static" / "js" / "runtime" / "runtime.js"
MEMORY_CSS = ROOT / "ui" / "static" / "css" / "runtime-memory.css"


class RuntimeMemoryTabsClientContractTests(unittest.TestCase):

    def test_all_five_memory_tabs_are_always_present(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        expected_tabs = (
            ('data-runtime-memory-mode="runtime"', "FRAME"),
            ('data-runtime-memory-mode="active"', "ACTIVE"),
            ('data-runtime-memory-mode="delayed"', "DELAYED"),
            ('data-runtime-memory-mode="long_term"', "L-T"),
            ('data-runtime-memory-mode="files"', "FILES"),
        )

        for mode, label in expected_tabs:
            self.assertIn(mode, source)
            self.assertIn(f">{label}</button>", source)

        self.assertNotIn('data-runtime-memory-mode="facts"', source)

    def test_tabs_replace_title_cycling_and_skip_unprocessed_facts(self):
        source = MEMORY_VIEW_JS.read_text(encoding="utf-8")

        modes_start = source.index("const RUNTIME_MEMORY_DISPLAY_MODES = [")
        modes_end = source.index("];", modes_start)
        modes = source[modes_start:modes_end]

        self.assertNotIn('"facts"', modes)
        self.assertNotIn("toggleRuntimeMemoryDisplayMode", source)
        self.assertNotIn("isRuntimeMemoryTitleBackZone", source)
        self.assertIn('tab.addEventListener("click"', source)
        self.assertIn("updateRuntimeMemoryTabsState(availableModes);", source)

    def test_shared_counter_tracks_active_tab_and_frame_owns_arrows(self):
        source = MEMORY_VIEW_JS.read_text(encoding="utf-8")
        css = MEMORY_CSS.read_text(encoding="utf-8")

        self.assertIn("runtimeMemoryNavigation.dataset.activeIndex", source)
        self.assertIn("runtimeMemoryNavigation.dataset.activeMode", source)
        self.assertIn("syncRuntimeMemoryNavigationGeometry(displayMode);", source)
        self.assertIn("new ResizeObserver", source)
        self.assertIn(
            '.runtime-memory-navigation:not([data-active-mode="runtime"]) '
            "#runtime-memory-prev",
            css,
        )
        self.assertIn("display: flex;", css)
        self.assertIn("flex: 0 0 auto;", css)
        self.assertIn("min-width: max-content;", css)
        self.assertIn("--runtime-memory-active-tab-left", css)
        self.assertIn("--runtime-memory-active-tab-width", css)
        self.assertIn(
            '.runtime-memory-navigation[data-active-mode="runtime"] '
            ".runtime-memory-navigation-slot",
            css,
        )
        self.assertIn("justify-content: flex-start;", css)
        self.assertIn(
            "transform 0.18s cubic-bezier(0.22, 0.61, 0.36, 1)",
            css,
        )
        self.assertNotIn("grid-template-columns: repeat(5", css)
        self.assertNotIn('width: 20%;', css)

    def test_lt_counter_toggles_active_and_all_report_backed_facts(self):
        source = MEMORY_VIEW_JS.read_text(encoding="utf-8")
        runtime_source = RUNTIME_JS.read_text(encoding="utf-8")
        css = MEMORY_CSS.read_text(encoding="utf-8")

        self.assertIn("let longTermMemoryShowsAll = false;", source)
        self.assertIn('? "show active"\n              : "show all"', source)
        self.assertIn(
            'if (displayMode === "long_term") {\n'
            "        longTermMemoryShowsAll = !longTermMemoryShowsAll;",
            source,
        )
        self.assertIn("getAllLongTermMemoryFacts", source)
        self.assertNotIn("const archivedRecords = [];", source)
        self.assertNotIn("!activeFactIds.has(factId)", source)
        self.assertNotIn("...archivedRecords,", source)
        self.assertIn("...priorityRecords,\n      ...overflowRecords,", source)
        self.assertIn(
            "getAllLongTermMemoryFacts,\n"
            "  deleteLongTermMemoryFact: deleteLongTermMemoryFactAndRender",
            runtime_source,
        )
        self.assertIn("fact.source_fact_ids", source)
        self.assertIn(
            '.runtime-memory-navigation[data-active-mode="long_term"] '
            "#runtime-memory-position.runtime-memory-position-pinned",
            css,
        )


if __name__ == "__main__":
    unittest.main()
