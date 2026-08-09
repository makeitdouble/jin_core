from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
MEMORY_VIEW_JS = (
    ROOT / "ui" / "static" / "js" / "runtime" / "runtime-memory-view.js"
)
RUNTIME_JS = ROOT / "ui" / "static" / "js" / "runtime" / "runtime.js"
CHAT_JS = ROOT / "ui" / "static" / "js" / "chat.js"
RUNTIME_MEMORY_CSS = ROOT / "ui" / "static" / "css" / "runtime-memory.css"
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"


class MemoryReferenceSyncClientContractTests(unittest.TestCase):

    def test_analyzed_facts_are_excluded_from_facts_memory_mode(self):
        source = MEMORY_VIEW_JS.read_text(encoding="utf-8")

        self.assertIn(
            'l4Status === "analyzed"',
            source,
        )
        self.assertIn(
            'if (getFactsMemoryFieldRecords().length > 0)',
            source,
        )

    def test_runtime_updates_do_not_force_the_runtime_tab(self):
        source = RUNTIME_JS.read_text(encoding="utf-8")
        start = source.index("function handleRuntimeMemoryMessage(data)")
        end = source.index("window.JinRuntime.runtime =", start)
        handler = source[start:end]

        self.assertNotIn(
            'runtimeMemoryDisplayMode = "runtime";',
            handler,
        )

    def test_chat_reference_highlight_is_persistent_per_jin_turn(self):
        source = CHAT_JS.read_text(encoding="utf-8")

        self.assertIn(
            '"jin:memory-reference-highlight"',
            source,
        )
        self.assertIn(
            'setLatestJinMemoryReferenceText(',
            source,
        )
        self.assertNotIn(
            'function bindJinMemoryReferenceBubble(',
            source,
        )
        self.assertNotIn(
            'clearJinMemoryReferenceHighlights();',
            source,
        )
        self.assertNotIn(
            'dispatchJinMemoryReferenceHighlight(\n      "hover"',
            source,
        )
    def test_memory_rows_expose_keys_and_ids_for_reference_matching(self):
        source = MEMORY_VIEW_JS.read_text(encoding="utf-8")

        self.assertIn(
            'collectMemoryRecordReferenceAliases(line)',
            source,
        )
        self.assertIn(
            'report._storage_key,',
            source,
        )
        self.assertIn(
            '"runtime-memory-reference-hit"',
            source,
        )
        css_source = RUNTIME_MEMORY_CSS.read_text(encoding="utf-8")
        self.assertIn(
            '.runtime-memory-reference-hit .runtime-memory-key',
            css_source,
        )
        self.assertNotIn(
            '.runtime-memory-reference-hit {',
            css_source,
        )

    def test_open_delayed_report_dispatches_avatar_active_state(self):
        source = MEMORY_VIEW_JS.read_text(encoding="utf-8")
        css_source = RUNTIME_MEMORY_CSS.read_text(encoding="utf-8")

        self.assertIn(
            '"jin:delayed-memory-report-active"',
            source,
        )
        self.assertIn(
            "function dispatchDelayedMemoryReportAvatarHighlight(",
            source,
        )
        self.assertIn(
            "dispatchDelayedMemoryReportAvatarHighlight(\n        delayedMemoryModalReport,\n        true",
            source,
        )
        self.assertIn(
            "dispatchDelayedMemoryReportAvatarHighlight(\n        delayedMemoryModalReport,\n        false",
            source,
        )
        self.assertIn(
            "let activeDelayedMemoryReportId = \"\";",
            source,
        )
        self.assertIn(
            "function setActiveDelayedMemoryReportRow(",
            source,
        )
        self.assertIn(
            '"runtime-memory-delayed-row-active"',
            source,
        )
        self.assertIn(
            ".runtime-memory-delayed-row-active",
            css_source,
        )
        self.assertIn(
            "pointer-events: none;",
            css_source,
        )
        active_rule_start = css_source.index(
            ".runtime-memory-delayed-row-active {"
        )
        active_rule_end = css_source.index(
            "}",
            active_rule_start,
        )
        active_rule = css_source[
            active_rule_start:active_rule_end
        ]
        self.assertNotIn(
            "background",
            active_rule,
        )
        self.assertNotIn(
            "box-shadow",
            active_rule,
        )

    def test_modal_l4_delete_cleans_local_report_refs_before_sync(self):
        source = RUNTIME_JS.read_text(encoding="utf-8")

        self.assertIn(
            "function removeLongTermFactIdFromDelayedMemoryReports(",
            source,
        )
        self.assertIn(
            "anchor_fact_ids: nextAnchorFactIds",
            source,
        )
        self.assertIn(
            "facts_ids: nextFactIds",
            source,
        )
        self.assertIn(
            "removeLongTermFactIdFromDelayedMemoryReports(\n      factId",
            source,
        )
        self.assertIn(
            "deleteLongTermMemoryFact: deleteLongTermMemoryFactAndRender",
            source,
        )

    def test_delayed_report_fact_chip_hover_targets_avatar_l4_dash(self):
        source = MEMORY_VIEW_JS.read_text(encoding="utf-8")

        self.assertIn(
            "function dispatchLongTermFactAvatarHover(",
            source,
        )
        self.assertIn(
            'buildAvatarMemoryHoverId(\n          "l4",',
            source,
        )
        self.assertIn(
            'item.addEventListener("mouseenter"',
            source,
        )
        self.assertIn(
            'item.addEventListener("mouseleave"',
            source,
        )
        self.assertIn(
            'item.addEventListener("focus"',
            source,
        )
        self.assertIn(
            'item.addEventListener("blur"',
            source,
        )

    def test_delayed_memory_fact_ids_render_inline_with_fact_titles(self):
        source = MEMORY_VIEW_JS.read_text(encoding="utf-8")
        runtime_source = RUNTIME_JS.read_text(encoding="utf-8")
        css_source = RUNTIME_MEMORY_CSS.read_text(encoding="utf-8")

        self.assertIn(
            'function appendDelayedMemoryFactIdField(',
            source,
        )
        self.assertIn(
            'function setDelayedMemoryModalAnchorFactId(',
            source,
        )
        self.assertIn(
            '"delayed-memory-modal-value delayed-memory-modal-fact-ids"',
            source,
        )
        self.assertIn(
            'item.title =',
            source,
        )
        self.assertIn(
            'function sortDelayedMemoryFactIdsByNumber(',
            source,
        )
        self.assertIn(
            'fieldName === "facts_ids"',
            source,
        )
        self.assertIn(
            '"delayed-memory-modal-fact-id-anchor"',
            source,
        )
        self.assertIn(
            'configureRuntimeMemoryDeleteHold(',
            source,
        )
        self.assertIn(
            'deleteLongTermMemoryFact(',
            source,
        )
        self.assertIn(
            'removeDelayedMemoryFactIdFromModal(',
            source,
        )
        self.assertIn(
            'item.addEventListener("dblclick"',
            source,
        )
        self.assertIn(
            ': !isAnchorFactId',
            source,
        )
        self.assertIn(
            'return `${key}: ${value}`;',
            source,
        )
        self.assertIn(
            'l4Memory.getFacts()',
            source,
        )
        self.assertIn(
            'function setDelayedMemoryReportAnchorFactIds(',
            runtime_source,
        )
        self.assertIn(
            'anchor_fact_ids:',
            runtime_source,
        )
        self.assertIn(
            'setDelayedMemoryReportAnchorFactIds,',
            runtime_source,
        )
        self.assertIn(
            '.delayed-memory-modal-fact-ids',
            css_source,
        )
        self.assertIn(
            'flex-wrap: wrap;',
            css_source,
        )
        self.assertIn(
            'cursor: pointer;',
            css_source,
        )
        self.assertIn(
            'color: rgba(244, 244, 245, 0.46);',
            css_source,
        )
        self.assertIn(
            'text-decoration: none;',
            css_source,
        )
        self.assertIn(
            '.delayed-memory-modal-fact-id-anchor',
            css_source,
        )
        self.assertIn(
            'color: rgba(255, 255, 255, 0.86);',
            css_source,
        )
        self.assertIn(
            '0 0 2px rgba(255, 255, 255, 0.64)',
            css_source,
        )
        self.assertNotIn(
            'text-decoration: underline',
            css_source,
        )
        self.assertNotIn(
            'inset 0 0 0 1px rgba(244, 244, 245',
            css_source,
        )

    def test_delayed_memory_modal_delete_uses_hold_and_runtime_restore_payload(self):
        source = MEMORY_VIEW_JS.read_text(encoding="utf-8")
        runtime_source = RUNTIME_JS.read_text(encoding="utf-8")
        css_source = RUNTIME_MEMORY_CSS.read_text(encoding="utf-8")

        self.assertIn(
            "delayedMemoryModalDeleteButton",
            source,
        )
        self.assertIn(
            '"delayed-memory-modal-icon-button delayed-memory-modal-delete"',
            source,
        )
        self.assertIn(
            "deleteDelayedMemoryModalReport",
            source,
        )
        self.assertIn(
            "configureRuntimeMemoryDeleteHold(\n        delayedMemoryModalDeleteButton",
            source,
        )
        self.assertIn(
            "deleteDelayedMemoryReport =\n        options.deleteDelayedMemoryReport",
            source,
        )
        self.assertIn(
            "function deleteDelayedMemoryReportAndRender(",
            runtime_source,
        )
        self.assertIn(
            "function restoreDelayedMemoryReportAndRender(",
            runtime_source,
        )
        self.assertIn(
            "deletedReportIds",
            runtime_source,
        )
        self.assertIn(
            ".delayed-memory-modal-delete svg",
            css_source,
        )

    @unittest.skipUnless(
        shutil.which("node"),
        "node is required for the browser-side reference matcher test",
    )
    def test_reference_matcher_requires_whole_ids_or_keys(self):
        script = r'''
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const start = source.indexOf("function normalizeMemoryReferenceSearchText(");
const end = source.indexOf("\n  function normalizeMemoryReferenceAliases(", start);

if (start < 0 || end < 0) {
  throw new Error("reference matcher functions were not found");
}

eval(source.slice(start, end));

const cases = [
  ["uses project.reasoning_injection_mechanism now", "project.reasoning_injection_mechanism", true],
  ["uses PROJECT.REASONING_INJECTION_MECHANISM now", "project.reasoning_injection_mechanism", true],
  ["record `5fdg4g` is active", "5fdg4g", true],
  ["record x5fdg4g is different", "5fdg4g", false],
  ["project.reasoning_injection_mechanism_extra", "project.reasoning_injection_mechanism", false],
  ["project.reasoning_injection_mechanism.child", "project.reasoning_injection_mechanism", false],
];

for (const [text, reference, expected] of cases) {
  const actual = containsMemoryReference(text, reference);

  if (actual !== expected) {
    throw new Error(`${JSON.stringify([text, reference])}: ${actual}`);
  }
}
'''
        completed = subprocess.run(
            [
                shutil.which("node"),
                "-e",
                script,
                str(MEMORY_VIEW_JS),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(
            completed.returncode,
            0,
            completed.stderr or completed.stdout,
        )

    def test_cache_versions_are_bumped(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn(
            '/static/css/runtime-memory.css?v=delayed-delete-1',
            source,
        )
        self.assertIn(
            '/static/js/runtime/runtime-memory-view.js?v=delayed-delete-1',
            source,
        )
        self.assertIn(
            '/static/js/runtime/runtime.js?v=delayed-delete-1',
            source,
        )
        self.assertIn(
            '/static/js/chat.js?v=reasoning-gap-1',
            source,
        )


if __name__ == "__main__":
    unittest.main()
