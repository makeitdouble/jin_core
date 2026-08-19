import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class L4MemoryClientContractTests(unittest.TestCase):

    def test_long_term_memory_keeps_shared_local_storage_key(self):
        source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "runtime"
            / "runtime-l4-memory.js"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'const longTermFactsStorageKey = "jin.longTermFacts.v1";',
            source,
        )

    def test_idle_l4_waits_a_full_minute_and_resets_while_user_idle_is_paused(self):
        source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "runtime"
            / "runtime-l4-memory.js"
        ).read_text(encoding="utf-8")

        self.assertIn("const idleTickIntervalMs = 60000;", source)
        self.assertIn("const idleMinimumSeconds = 60;", source)
        self.assertIn("if (idleContext.user_idle_paused)", source)
        self.assertIn("lastIdleTickAt = now;", source)
        self.assertIn("if (userIdleSeconds < idleMinimumSeconds)", source)

    def test_equal_revision_update_cannot_replace_larger_local_snapshot(self):
        source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "runtime"
            / "runtime-l4-memory.js"
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
