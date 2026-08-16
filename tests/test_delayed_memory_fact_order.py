import unittest
from pathlib import Path

from utils.actions.save_delayed_memory_utils import (
    normalize_delayed_memory_fact_ids,
)


ROOT = Path(__file__).resolve().parents[1]


class DelayedMemoryFactOrderTests(unittest.TestCase):

    def test_anchor_is_not_promoted_ahead_of_numeric_fact_order(self):
        anchor_ids, fact_ids = normalize_delayed_memory_fact_ids(
            anchor_fact_ids=["F190"],
            facts_ids=["F190", "F1", "F15", "F184"],
        )

        self.assertEqual(anchor_ids, ["F190"])
        self.assertEqual(
            fact_ids,
            ["F1", "F15", "F184", "F190"],
        )

    def test_modal_sorts_only_full_facts_field_by_number(self):
        source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "runtime"
            / "runtime-memory-view.js"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'fieldName === "facts_ids"\n'
            '          ? sortDelayedMemoryFactIdsByNumber(normalizedFactIds)',
            source,
        )


if __name__ == "__main__":
    unittest.main()
