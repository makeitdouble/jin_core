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
            '/static/css/runtime-memory.css?v=memory-reference-sync-1',
            source,
        )
        self.assertIn(
            '/static/js/runtime/runtime-memory-view.js?v=runtime-memory-view-14',
            source,
        )
        self.assertIn(
            '/static/js/runtime/runtime.js?v=runtime-facade-17',
            source,
        )
        self.assertIn(
            '/static/js/chat.js?v=memory-reference-sync-2',
            source,
        )


if __name__ == "__main__":
    unittest.main()
