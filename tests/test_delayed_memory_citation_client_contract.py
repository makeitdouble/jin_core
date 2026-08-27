from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
THINK = ROOT / "ui" / "static" / "js" / "think-citations.js"
VIEW = ROOT / "ui" / "static" / "js" / "runtime" / "runtime-memory-view.js"
CHAT_CSS = ROOT / "ui" / "static" / "css" / "chat.css"
INDEX = ROOT / "ui" / "templates" / "index.html"


class DelayedMemoryCitationClientContractTests(unittest.TestCase):
    def test_delayed_report_id_is_an_exact_reasoning_citation_candidate(self):
        source = THINK.read_text(encoding="utf-8")

        self.assertIn("function getDelayedMemoryCitationRecords()", source)
        self.assertIn('"delayed",\n        `delayedMemory[${record.id}]`', source)
        self.assertIn('citationType: "delayed_memory_citation"', source)
        self.assertIn('["runtime", "active", "delayed", "l4"]', source)
        self.assertIn('match.sourceType === "delayed"', source)
        self.assertIn('? "delayed"', source)

    def test_delayed_report_row_exposes_same_stable_citation_identity(self):
        source = VIEW.read_text(encoding="utf-8")

        self.assertIn('`delayed:${reportId}`', source)
        self.assertIn("runtimeMemoryLineIdentity:", source)
        self.assertIn("runtimeMemoryLineKey:", source)
        self.assertIn("normalizeRuntimeCitationIdentity(reportId)", source)

    def test_delayed_reasoning_citation_has_layer_specific_style(self):
        css = CHAT_CSS.read_text(encoding="utf-8")

        self.assertIn(".think-citation-delayed.exact", css)
        self.assertIn("rgba(103, 232, 249, 0.98)", css)

    def test_citation_assets_are_cache_bumped(self):
        source = INDEX.read_text(encoding="utf-8")

        self.assertIn("runtime-memory-view.js?v=", source)
        self.assertIn("think-citations.js?v=", source)
        self.assertGreaterEqual(source.count("delayed-id-citations=1"), 4)


if __name__ == "__main__":
    unittest.main()
