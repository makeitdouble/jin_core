from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
THINK_CITATIONS_JS = ROOT / "ui" / "static" / "js" / "think-citations.js"
THINK_WORKER_JS = ROOT / "ui" / "static" / "js" / "think-rule-worker.js"
CHAT_JS = ROOT / "ui" / "static" / "js" / "chat.js"
CHAT_CSS = ROOT / "ui" / "static" / "css" / "chat.css"
MEMORY_VIEW_JS = ROOT / "ui" / "static" / "js" / "runtime" / "runtime-memory-view.js"
MEMORY_CSS = ROOT / "ui" / "static" / "css" / "runtime-memory.css"
AVATAR_JS = ROOT / "ui" / "static" / "js" / "runtime" / "runtime-avatar.js"
WIN95_CSS = ROOT / "ui" / "static" / "css" / "theme-win95.css"
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"


class MemoryCitationLayersClientContractTests(unittest.TestCase):
    def test_reasoning_citations_cover_runtime_active_and_l4_layers(self):
        source = THINK_CITATIONS_JS.read_text(encoding="utf-8")
        worker = THINK_WORKER_JS.read_text(encoding="utf-8")

        self.assertIn("function buildActiveMemoryCitationFragments()", source)
        self.assertIn('sourceType: "active"', source)
        self.assertIn('citationType: "active_memory_citation"', source)
        self.assertIn("function buildL4CitationFragments()", source)
        self.assertIn('sourceType: "l4"', source)
        self.assertIn('citationType: "l4_citation"', source)
        self.assertIn("...buildActiveMemoryCitationFragments(),", source)
        self.assertIn("...buildL4CitationFragments(),", source)
        self.assertIn('match.sourceType === "active"', source)
        self.assertIn('match.sourceType === "l4"', source)
        self.assertIn('match.sourceType === "active"', worker)
        self.assertIn('match.sourceType === "l4"', worker)

    def test_active_and_l4_reasoning_citation_colors_are_layer_specific(self):
        css = CHAT_CSS.read_text(encoding="utf-8")

        self.assertIn(".think-citation-active.exact", css)
        self.assertIn("rgba(251, 191, 106, 0.96)", css)
        self.assertIn(".think-citation-l4.exact", css)
        self.assertIn("rgba(129, 230, 217, 0.98)", css)

    def test_reasoning_citation_reveal_is_not_hover_gated(self):
        source = THINK_CITATIONS_JS.read_text(encoding="utf-8")
        chat_source = CHAT_JS.read_text(encoding="utf-8")
        css = CHAT_CSS.read_text(encoding="utf-8")

        self.assertIn('"jin:think-runtime-citation-highlight"', source)
        self.assertNotIn('matches(":hover")', source)
        self.assertNotIn('is-rule-highlight-revealing', source)
        self.assertNotIn('has-rule-highlights:hover .think-citation-', css)
        self.assertIn('.jin-think-content.has-rule-highlights .think-citation-runtime.exact', css)
        self.assertNotIn('window.JinThinkCitations.syncThinkRuntimeCitationHighlight(', chat_source)
        self.assertIn("function resetThinkCitationHighlightTurn()", source)
        self.assertIn("resetThinkCitationHighlightTurn,", source)
        self.assertIn("window.JinThinkCitations.resetThinkCitationHighlightTurn();", chat_source)
    def test_latest_persistent_reference_text_combines_reasoning_and_answer(self):
        source = CHAT_JS.read_text(encoding="utf-8")
        start = source.index("const memoryReferenceText =")
        end = source.index("if (stream.answer.trim())", start)
        block = source[start:end]

        self.assertIn("stream.thinking,", block)
        self.assertIn("stream.answer,", block)
        self.assertIn("setLatestJinMemoryReferenceText(", block)

    def test_all_panel_rows_match_ids_titles_and_display_keys(self):
        source = MEMORY_VIEW_JS.read_text(encoding="utf-8")

        self.assertIn("record.title,", source)
        self.assertIn("record.name,", source)
        self.assertIn("record.id,", source)
        self.assertIn("record._storage_key,", source)
        self.assertIn("record.active_memory_id,", source)
        self.assertIn("memoryModel.runtimeMemoryDisplay.convertKeyToName(key)", source)
        self.assertIn("record.title,", source)

    def test_structured_reasoning_citation_sync_survives_runtime_page_rerender(self):
        source = MEMORY_VIEW_JS.read_text(encoding="utf-8")

        self.assertIn("const activeThinkMemoryCitationSources = new Map();", source)
        self.assertIn('"runtime-memory-citation-hit"', source)
        self.assertIn("handleThinkMemoryCitationHighlight", source)
        self.assertIn("applyThinkMemoryCitationHighlights();", source)
        self.assertIn("THINK_RUNTIME_CITATION_HIGHLIGHT_EVENT", source)

    def test_avatar_aliases_cover_titles_and_display_keys_across_layers(self):
        source = AVATAR_JS.read_text(encoding="utf-8")

        self.assertIn("function getAvatarMemoryReferenceDisplayKey(value)", source)
        self.assertIn("getAvatarMemoryReferenceDisplayKey(key)", source)
        self.assertIn("title,", source)
        self.assertIn('"is-memory-reference-hit"', source)

    def test_runtime_diff_colors_are_preserved_while_reference_glow_is_added(self):
        css = MEMORY_CSS.read_text(encoding="utf-8")

        self.assertIn(".runtime-memory-reference-hit .runtime-memory-key.flash-new", css)
        self.assertIn(".runtime-memory-citation-hit .runtime-memory-key.flash-new", css)
        self.assertIn(".runtime-memory-reference-hit .runtime-memory-key.flash-changed", css)
        self.assertIn(".runtime-memory-citation-hit .runtime-memory-value.flash-changed", css)
        self.assertIn("0 0 18px rgba(248,250,252,0.20)", css)

    def test_win95_keeps_reference_and_citation_hits_consistent(self):
        css = WIN95_CSS.read_text(encoding="utf-8")

        self.assertIn(".runtime-memory-reference-hit,", css)
        self.assertIn(".runtime-memory-citation-hit {", css)
        self.assertIn(".runtime-memory-citation-hit .runtime-memory-key", css)

    def test_cache_versions_are_bumped_for_citation_sync_assets(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn("/static/css/runtime-memory.css?v=memory-reference-sync-1", source)
        self.assertIn("/static/css/theme-win95.css?v=memory-citations-2", source)
        self.assertIn("/static/js/runtime/runtime-memory-view.js?v=runtime-memory-view-14", source)
        self.assertIn("/static/js/runtime/runtime-avatar.js?v=memory-rings-7", source)
        self.assertIn("/static/js/think-citations.js?v=think-citations-3", source)
        self.assertIn("/static/js/chat.js?v=memory-reference-sync-2", source)


if __name__ == "__main__":
    unittest.main()
