import unittest
from types import SimpleNamespace

from runtime.LT_context_budget import (
    calculate_lt_context_fact_limit,
    limit_long_term_memory_context,
)


class LTContextBudgetTests(unittest.TestCase):
    def test_fact_limit_is_full_below_half_and_one_at_ninety_percent(self):
        self.assertEqual(
            calculate_lt_context_fact_limit(
                total_facts=10,
                used_tokens_without_lt=4999,
                context_window=10000,
            ),
            10,
        )
        self.assertEqual(
            calculate_lt_context_fact_limit(
                total_facts=10,
                used_tokens_without_lt=5000,
                context_window=10000,
            ),
            10,
        )
        self.assertEqual(
            calculate_lt_context_fact_limit(
                total_facts=10,
                used_tokens_without_lt=7000,
                context_window=10000,
            ),
            6,
        )
        self.assertEqual(
            calculate_lt_context_fact_limit(
                total_facts=10,
                used_tokens_without_lt=9000,
                context_window=10000,
            ),
            1,
        )

    def test_unknown_window_keeps_historical_all_facts_behavior(self):
        self.assertEqual(
            calculate_lt_context_fact_limit(
                total_facts=17,
                used_tokens_without_lt=999999,
                context_window=0,
            ),
            17,
        )

    def test_selection_uses_last_mention_but_preserves_existing_prompt_order(self):
        context = SimpleNamespace(
            runtime_long_term_memory_store={
                "facts": [
                    {
                        "id": "F1",
                        "last_mentioned_at": "2026-09-13T12:00:00Z",
                    },
                    {
                        "id": "F2",
                        "last_mentioned_at": "2026-09-11T12:00:00Z",
                    },
                    {
                        "id": "F3",
                        "last_mentioned_at": "2026-09-12T12:00:00Z",
                    },
                ],
            },
        )
        prompt = "\n".join([
            "before",
            "<LONG_TERM_MEMORY>",
            "three: value [ id: F3 ]",
            "two: value [ id: F2 ]",
            "one: value [ id: F1 ]",
            "</LONG_TERM_MEMORY>",
            "after",
        ])

        limited = limit_long_term_memory_context(
            context=context,
            system_prompt=prompt,
            fact_limit=2,
        )

        self.assertIn("[ id: F3 ]", limited)
        self.assertNotIn("[ id: F2 ]", limited)
        self.assertIn("[ id: F1 ]", limited)
        self.assertLess(
            limited.index("[ id: F3 ]"),
            limited.index("[ id: F1 ]"),
        )


if __name__ == "__main__":
    unittest.main()
