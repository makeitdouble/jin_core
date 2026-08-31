import unittest
from types import SimpleNamespace
from unittest.mock import patch

from rules.brain_context_builder import (
    build_delayed_memory_inventory_context,
)


class DelayedMemoryInventoryFactMetadataTests(unittest.TestCase):

    def test_inventory_lists_anchor_ids_and_total_fact_count(self):
        context = SimpleNamespace(
            delayed_memory_reports={
                "u5xx8l": {
                    "title": "Вкусы и предпочтения Сергея",
                    "created_time": "2026-08-28T12:00:00Z",
                    "anchor_fact_ids": ["F193"],
                    "facts_ids": ["F5", "F2", "F193", "F4", "F3"],
                },
            },
        )

        with patch(
            "utils.context.messages.time.time",
            return_value=1788177600.0,
        ):
            inventory = build_delayed_memory_inventory_context(
                context=context,
            )

        self.assertIn(
            "u5xx8l_Вкусы_и_предпочтения_Сергея ( 3d ago ) "
            "[ anchor_facts: F193 ] [ total_facts: 5 ]",
            inventory,
        )

    def test_inventory_omits_fact_metadata_when_report_has_no_facts(self):
        context = SimpleNamespace(
            delayed_memory_reports={
                "empty1": {
                    "title": "Report without facts",
                    "anchor_fact_ids": [],
                    "facts_ids": [],
                },
            },
        )

        inventory = build_delayed_memory_inventory_context(
            context=context,
        )

        self.assertEqual(
            inventory,
            "<DELAYED_MEMORY>\n"
            "empty1_Report_without_facts\n"
            "</DELAYED_MEMORY>",
        )


if __name__ == "__main__":
    unittest.main()
