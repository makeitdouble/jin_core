import unittest
from unittest.mock import patch

from runtime.LT_memory import build_runtime_lt_memory_context
from runtime.LT_memory_utils import normalize_lt_store
from runtime.runtime_context import RuntimeContext



class LTContextFocusContractTests(unittest.TestCase):
    def make_context(self, facts):
        context = RuntimeContext(
            websocket=None,
            emitter=None,
            logger=None,
            clients={},
        )
        context.runtime_long_term_memory_store = normalize_lt_store({
            "facts": facts,
        })
        context.delayed_memory_reports = {}
        return context

    def test_default_prompt_order_is_newest_fact_id_first(self):
        context = self.make_context([
            {"id": "F22", "key": "fact.twenty_two", "value": "Twenty two."},
            {"id": "F2", "key": "fact.two", "value": "Two."},
            {"id": "F10", "key": "fact.ten", "value": "Ten."},
        ])

        block = build_runtime_lt_memory_context(context=context)

        self.assertLess(block.index("[ id: F22 ]"), block.index("[ id: F10 ]"))
        self.assertLess(block.index("[ id: F10 ]"), block.index("[ id: F2 ]"))
        self.assertEqual(context.runtime_memory_attention_lt_focus_ids, [])

    def test_memory_attention_focus_promotes_only_prompt_view(self):
        context = self.make_context([
            {"id": "F1", "key": "project.unrelated", "value": "Unrelated durable fact."},
            {
                "id": "F22",
                "key": "identity_revision_protocol_established",
                "value": "JIN can propose structured identity revisions when contextual friction appears.",
            },
            {"id": "F30", "key": "project.other", "value": "Another unrelated fact."},
        ])
        stored_ids_before = [
            fact["id"]
            for fact in context.runtime_long_term_memory_store["facts"]
        ]

        block = build_runtime_lt_memory_context(
            context=context,
            user_input="show the identity revision protocol",
        )

        self.assertLess(block.index("[ id: F22 ]"), block.index("[ id: F1 ]"))
        self.assertEqual(context.runtime_memory_attention_lt_focus_ids, ["F22"])
        self.assertEqual(
            [fact["id"] for fact in context.runtime_long_term_memory_store["facts"]],
            stored_ids_before,
        )

    def test_memory_attention_focus_can_open_to_three_prompt_facts(self):
        context = self.make_context([
            {"id": "F227", "key": "fresh.latest", "value": "Fresh but unrelated."},
            {"id": "F226", "key": "fresh.previous", "value": "Also unrelated."},
            {"id": "F80", "key": "topic.primary", "value": "Primary resonant fact."},
            {"id": "F60", "key": "topic.secondary", "value": "Secondary resonant fact."},
            {"id": "F40", "key": "topic.tertiary", "value": "Tertiary resonant fact."},
        ])
        scores = {
            "F80": 0.62,
            "F60": 0.53,
            "F40": 0.44,
            "F227": 0.06,
            "F226": 0.05,
        }

        with patch(
            "runtime.memory_attention.score_lt_fact_context_focus",
            side_effect=lambda fact, **_kwargs: scores[fact["id"]],
        ):
            block = build_runtime_lt_memory_context(
                context=context,
                user_input="resonant topic",
            )

        self.assertLess(block.index("[ id: F80 ]"), block.index("[ id: F60 ]"))
        self.assertLess(block.index("[ id: F60 ]"), block.index("[ id: F40 ]"))
        self.assertLess(block.index("[ id: F40 ]"), block.index("[ id: F227 ]"))
        self.assertLess(block.index("[ id: F227 ]"), block.index("[ id: F226 ]"))
        self.assertEqual(
            context.runtime_memory_attention_lt_focus_ids,
            ["F80", "F60", "F40"],
        )

    def test_memory_attention_focus_does_not_pad_with_unrelated_facts(self):
        context = self.make_context([
            {"id": "F227", "key": "fresh.latest", "value": "Fresh unrelated."},
            {"id": "F22", "key": "topic.primary", "value": "Primary resonant fact."},
            {"id": "F21", "key": "topic.noise", "value": "Weak coincidence."},
        ])
        scores = {"F22": 0.58, "F21": 0.13, "F227": 0.04}

        with patch(
            "runtime.memory_attention.score_lt_fact_context_focus",
            side_effect=lambda fact, **_kwargs: scores[fact["id"]],
        ):
            block = build_runtime_lt_memory_context(
                context=context,
                user_input="resonant topic",
            )

        self.assertLess(block.index("[ id: F22 ]"), block.index("[ id: F227 ]"))
        self.assertLess(block.index("[ id: F227 ]"), block.index("[ id: F21 ]"))
        self.assertEqual(context.runtime_memory_attention_lt_focus_ids, ["F22"])


if __name__ == "__main__":
    unittest.main()
