import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LTMemoryClientContractTests(unittest.TestCase):

    def test_long_term_memory_keeps_shared_local_storage_key(self):
        source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "runtime"
            / "runtime-lt-memory.js"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'const longTermFactsStorageKey = "jin.longTermFacts.v1";',
            source,
        )

    def test_idle_lt_scheduler_is_not_driven_by_browser_javascript(self):
        source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "runtime"
            / "runtime-lt-memory.js"
        ).read_text(encoding="utf-8")
        template = (
            ROOT
            / "ui"
            / "templates"
            / "index.html"
        ).read_text(encoding="utf-8")
        runtime_source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "runtime"
            / "runtime.js"
        ).read_text(encoding="utf-8")

        self.assertNotIn("lt_memory_idle_tick", source)
        self.assertNotIn("startIdleMonitor", source)
        self.assertNotIn("maybeSendIdleTick", source)
        self.assertNotIn('id="jin-lt-config"', template)
        self.assertIn(
            'typeof window.syncFactsMemoryToRuntime === "function"',
            runtime_source,
        )
        self.assertIn("window.syncFactsMemoryToRuntime();", runtime_source)


    def test_lt_fact_reference_runtime_keys_do_not_feed_facts_memory(self):
        source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "runtime"
            / "runtime.js"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "FACTS_MEMORY_EXCLUDED_KEY_PATTERNS",
            source,
        )
        self.assertIn(
            r"/^l-?t_fact_?#?f?[1-9]\d*$/i",
            source,
        )
        self.assertIn(
            "delete fields[key];",
            source,
        )

    def test_equal_revision_update_cannot_replace_larger_local_snapshot(self):
        source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "runtime"
            / "runtime-lt-memory.js"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "function countStoreItems(store)",
            source,
        )
        self.assertIn(
            "incoming.revision === local.revision",
            source,
        )
        self.assertIn(
            "countStoreItems(local) > countStoreItems(incoming)",
            source,
        )


if __name__ == "__main__":
    unittest.main()
