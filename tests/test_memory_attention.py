from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from runtime.memory_attention import (
    delayed_memory_bubble_tier,
    rank_active_memory_records,
    rank_lt_facts_for_context,
    score_delayed_memory_report,
)


class MemoryAttentionTests(unittest.TestCase):
    def make_context(self, *, turns=None, facts=None):
        return SimpleNamespace(
            runtime_recent_turns=list(turns or []),
            runtime_long_term_memory_store={"facts": list(facts or [])},
            runtime_memory_attention_lt_focus_ids=[],
        )

    def test_active_uses_current_and_recent_context_without_mutating_records(self):
        records = [
            "active_memory_1: tune avatar colour [ active_memory_id: aaa111 ] [ status: pending ]",
            "active_memory_2: fix session bootstrap [ active_memory_id: bbb222 ] [ status: pending ]",
        ]
        before = list(records)
        context = self.make_context(
            turns=[{"user": "we were debugging session restore"}],
        )

        ranked = rank_active_memory_records(
            records,
            context=context,
            user_input="continue the bootstrap fix",
        )

        self.assertIn("bbb222", ranked[0])
        self.assertEqual(records, before)

    def test_active_explicit_id_wins(self):
        records = [
            "active_memory_1: bootstrap work [ active_memory_id: aaa111 ] [ status: pending ]",
            "active_memory_2: unrelated [ active_memory_id: bbb222 ] [ status: pending ]",
        ]

        ranked = rank_active_memory_records(
            records,
            context=self.make_context(),
            user_input="open bbb222",
        )

        self.assertIn("bbb222", ranked[0])

    def test_delayed_report_uses_bubble_tiers_and_explicit_id(self):
        context = self.make_context()
        report = {
            "id": "abc123",
            "title": "Kowloon architecture",
            "summary": "Device runtime decisions",
            "tags": ["hardware", "kowloon"],
        }

        lexical_score = score_delayed_memory_report(
            report,
            user_input="continue Kowloon",
            context=context,
        )
        id_score = score_delayed_memory_report(
            report,
            user_input="load abc123",
            context=context,
        )

        self.assertGreaterEqual(delayed_memory_bubble_tier(lexical_score), 1)
        self.assertEqual(id_score, 0.96)
        self.assertEqual(delayed_memory_bubble_tier(id_score), 2)

    def test_lt_focus_is_one_to_three_and_prompt_only(self):
        facts = [
            {"id": "F30", "key": "fresh", "value": "unrelated"},
            {"id": "F20", "key": "topic.primary", "value": "primary"},
            {"id": "F19", "key": "topic.secondary", "value": "secondary"},
            {"id": "F18", "key": "topic.tertiary", "value": "tertiary"},
        ]
        before = deepcopy(facts)
        context = self.make_context(facts=facts)
        scores = {"F30": 0.01, "F20": 0.70, "F19": 0.60, "F18": 0.50}

        with patch(
            "runtime.memory_attention.score_lt_fact_context_focus",
            side_effect=lambda fact, **_kwargs: scores[fact["id"]],
        ):
            ranked = rank_lt_facts_for_context(
                facts,
                context=context,
                user_input="topic",
            )

        self.assertEqual([fact["id"] for fact in ranked[:3]], ["F20", "F19", "F18"])
        self.assertEqual(
            context.runtime_memory_attention_lt_focus_ids,
            ["F20", "F19", "F18"],
        )
        self.assertEqual(facts, before)

    def test_lt_does_not_pad_focus_with_unrelated_facts(self):
        facts = [
            {"id": "F3", "key": "fresh", "value": "unrelated"},
            {"id": "F2", "key": "topic", "value": "match"},
            {"id": "F1", "key": "noise", "value": "weak"},
        ]
        context = self.make_context(facts=facts)
        scores = {"F3": 0.01, "F2": 0.65, "F1": 0.10}

        with patch(
            "runtime.memory_attention.score_lt_fact_context_focus",
            side_effect=lambda fact, **_kwargs: scores[fact["id"]],
        ):
            ranked = rank_lt_facts_for_context(
                facts,
                context=context,
                user_input="topic",
            )

        self.assertEqual(context.runtime_memory_attention_lt_focus_ids, ["F2"])
        self.assertEqual([fact["id"] for fact in ranked], ["F2", "F3", "F1"])

    def test_lt_recent_facts_do_not_focus_themselves(self):
        facts = [
            {"id": "F2", "key": "project.kowloon", "value": "device architecture"},
            {"id": "F1", "key": "user.camera", "value": "photography"},
        ]
        context = self.make_context(facts=facts)

        ranked = rank_lt_facts_for_context(
            facts,
            context=context,
            user_input="what should I cook for dinner",
        )

        self.assertEqual([fact["id"] for fact in ranked], ["F2", "F1"])
        self.assertEqual(context.runtime_memory_attention_lt_focus_ids, [])


if __name__ == "__main__":
    unittest.main()
