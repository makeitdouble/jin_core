import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from runtime.metabolism import (
    METABOLISM_DEFAULT_LEVELS,
    METABOLISM_HALF_LIFE_SECONDS,
    advance_metabolism_clock,
    apply_metabolism_impulse,
    build_metabolism_brain_context,
    build_metabolism_reflex,
    learn_metabolism_associations,
    build_runtime_outcome_reflex,
    metabolic_memory_strength_boost,
    rank_active_memory_records,
    resolve_metabolism_temperature,
)


ROOT = Path(__file__).resolve().parents[1]


class MetabolismHomeostatTests(unittest.TestCase):
    def _context(self, **overrides):
        values = {
            "runtime_metabolism_levels": dict(METABOLISM_DEFAULT_LEVELS),
            "runtime_metabolism_last_tick_at": 0.0,
            "runtime_metabolism_last_delta": {},
            "runtime_metabolism_last_event": "",
            "runtime_metabolism_active_memory_salience": {},
            "runtime_metabolism_policy": {},
            "runtime_last_response_feedback": None,
            "runtime_metabolism_associations": [],
            "runtime_recent_turns": [],
            "runtime_metabolism_recent_turns": [],
            "runtime_restored_session_dialog": "",
            "runtime_memory": "",
            "delayed_memory_reports": {},
            "active_memory_records": [],
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_wall_clock_homeostasis_returns_each_channel_toward_baseline(self):
        start = 1_700_000_000.0
        levels = {
            "dopamine": 0.82,
            "serotonin": 0.82,
            "oxytocin": 0.76,
            "norepinephrine": 0.72,
            "cortisol": 0.64,
        }
        context = self._context(
            runtime_metabolism_levels=levels,
            runtime_metabolism_last_tick_at=start,
        )

        result = advance_metabolism_clock(
            context,
            now=start + METABOLISM_HALF_LIFE_SECONDS["dopamine"],
        )

        for channel, previous in levels.items():
            baseline = METABOLISM_DEFAULT_LEVELS[channel]
            self.assertLess(abs(result[channel] - baseline), abs(previous - baseline))
        self.assertEqual(context.runtime_metabolism_last_event, "homeostasis")

    def test_lexical_reflex_has_no_builtin_user_vocabulary_and_reuses_learned_runtime_cue(self):
        context = self._context(
            runtime_memory="avatar latency remains an unresolved runtime issue",
            runtime_metabolism_associations=[{
                "phrase": "avatar latency",
                "vector": {
                    "dopamine": -0.01,
                    "serotonin": -0.01,
                    "oxytocin": 0.0,
                    "norepinephrine": 0.03,
                    "cortisol": 0.04,
                },
                "weight": 0.9,
                "hits": 2,
                "updated_at": time.time(),
                "source": "session:4",
            }],
        )

        neutral, neutral_triggers = build_metabolism_reflex(
            "спасибо бро, кайф, давай разберись с кодом",
            context=context,
        )
        self.assertFalse(neutral_triggers)
        self.assertTrue(all(value == 0 for value in neutral.values()))

        impulse, triggers = build_metabolism_reflex(
            "avatar latency опять появилась",
            context=context,
        )
        self.assertTrue(any(item.startswith("learned:avatar latency") for item in triggers))
        self.assertGreater(impulse["norepinephrine"], 0)
        self.assertGreater(impulse["cortisol"], 0)

    def test_committed_l1_learns_last_input_cue_from_runtime_and_reuses_it(self):
        context = self._context(
            session_id="session-current",
            runtime_memory="ui_state: avatar latency is causing dissatisfaction",
            runtime_recent_turns=[
                {"user": "we saw avatar latency yesterday", "jin": "noted"},
            ],
            runtime_restored_session_dialog="previous session also mentioned avatar latency",
        )
        before = dict(METABOLISM_DEFAULT_LEVELS)
        after = {
            **before,
            "norepinephrine": 0.43,
            "cortisol": 0.29,
        }

        learned = learn_metabolism_associations(
            context,
            committed_snapshot={
                "index": 7,
                "total_diff": 30,
                "patch": {"changed": [{"current_key": "ui_state", "current_value": "avatar latency dissatisfaction"}]},
            },
            committed_turns=[{
                "user_message": "avatar latency опять мешает",
                "assistant_message": "исправлю",
            }],
            previous_levels=before,
            current_levels=after,
        )

        self.assertTrue(any("avatar latency" in item["phrase"] for item in learned))
        impulse, triggers = build_metabolism_reflex(
            "снова avatar latency",
            context=context,
        )
        self.assertTrue(any(item.startswith("learned:") for item in triggers))
        self.assertGreater(impulse["cortisol"], 0)
        self.assertGreater(impulse["norepinephrine"], 0)

    def test_runtime_action_failure_leaves_immediate_trace_before_background_estimator(self):
        context = self._context(
            runtime_current_sequence_turn_id="turn_000007",
            runtime_current_turn_id="turn_000007",
            runtime_turn_interrupted=False,
            runtime_turn_aborted_actions=[],
            runtime_pattern_counter=0,
            runtime_turn_reasoning_content="short reasoning",
            runtime_session_action_history=[
                {
                    "runtime_turn_id": "turn_000007",
                    "text": "UPDATE_ACTIVE_MEMORY: failed",
                    "parts": [{"detail": "incorrect id"}],
                }
            ],
        )

        impulse, triggers = build_runtime_outcome_reflex(context)

        self.assertIn("runtime_failure", triggers)
        self.assertGreater(impulse["cortisol"], 0)
        self.assertGreater(impulse["norepinephrine"], 0)
        self.assertLess(impulse["dopamine"], 0)

    def test_temperature_is_causal_but_oxytocin_does_not_make_agreement_more_likely(self):
        high_explore = self._context(runtime_metabolism_levels={
            **METABOLISM_DEFAULT_LEVELS,
            "dopamine": 0.78,
            "norepinephrine": 0.66,
        })
        high_pressure = self._context(runtime_metabolism_levels={
            **METABOLISM_DEFAULT_LEVELS,
            "serotonin": 0.80,
            "cortisol": 0.74,
        })
        high_oxy = self._context(runtime_metabolism_levels={
            **METABOLISM_DEFAULT_LEVELS,
            "oxytocin": 0.90,
        })

        base = 0.30
        self.assertGreater(resolve_metabolism_temperature(base, high_explore), base)
        self.assertLess(resolve_metabolism_temperature(base, high_pressure), base)
        self.assertEqual(resolve_metabolism_temperature(base, high_oxy), base)

    def test_oxytocin_changes_dialogue_policy_but_has_explicit_anti_sycophancy_guard(self):
        context = self._context(runtime_metabolism_levels={
            **METABOLISM_DEFAULT_LEVELS,
            "oxytocin": 0.72,
        })

        prompt = build_metabolism_brain_context(
            context,
            user_input="продолжим наш JIN",
        )

        self.assertIn("shared history naturally", prompt)
        self.assertIn("NEVER agreement, praise, deference", prompt)
        self.assertIn("Correct the user normally when needed", prompt)
        self.assertIn('role="silent_homeostat"', prompt)

    def test_active_memory_prompt_order_is_state_and_query_sensitive_without_mutating_storage(self):
        records = [
            "active_memory_1: keep project naming stable [ active_memory_id: aaa111 ] [ status: pending ]",
            "active_memory_2: proactively verify code errors [ active_memory_id: bbb222 ] [ status: pending ]",
            "active_memory_3: preserve social continuity with the user [ active_memory_id: ccc333 ] [ status: pending ]",
        ]
        context = self._context(
            runtime_metabolism_levels={
                **METABOLISM_DEFAULT_LEVELS,
                "norepinephrine": 0.78,
            },
            active_memory_records=list(records),
        )

        ranked = rank_active_memory_records(
            records,
            context=context,
            user_input="проверь code error и верифицируй фикс",
        )

        self.assertEqual(ranked[0], records[1])
        self.assertEqual(context.active_memory_records, records)
        self.assertGreater(
            context.runtime_metabolism_active_memory_salience["bbb222"],
            context.runtime_metabolism_active_memory_salience["aaa111"],
        )

    def test_state_shift_biases_existing_l1_strength_instead_of_creating_a_new_memory_type(self):
        context = self._context(
            runtime_metabolism_levels={
                **METABOLISM_DEFAULT_LEVELS,
                "norepinephrine": 0.72,
                "cortisol": 0.50,
            },
            runtime_metabolism_last_delta={
                "dopamine": 0.03,
                "serotonin": -0.02,
                "oxytocin": 0.01,
                "norepinephrine": 0.06,
                "cortisol": 0.05,
            },
            runtime_metabolism_associations=[{
                "phrase": "validator error",
                "vector": {
                    "dopamine": -0.01,
                    "serotonin": -0.01,
                    "oxytocin": 0.0,
                    "norepinephrine": 0.04,
                    "cortisol": 0.04,
                },
                "weight": 1.0,
                "hits": 2,
                "updated_at": time.time(),
                "source": "test",
            }],
        )

        boost, salience, channel = metabolic_memory_strength_boost(
            context,
            key="validator_error",
            value="verify failed action and prevent contradiction",
            status="changed",
        )

        self.assertGreater(boost, 0)
        self.assertGreater(salience, 0)
        self.assertIn(channel, {"norepinephrine", "cortisol"})


class MetabolismUiContractTests(unittest.TestCase):
    def test_avatar_uses_existing_tint_opacity_scale_language_with_long_transition(self):
        metabolism = (ROOT / "ui/static/js/runtime/runtime-metabolism.js").read_text(encoding="utf-8")
        avatar = (ROOT / "ui/static/js/runtime/runtime-avatar.js").read_text(encoding="utf-8")
        css = (ROOT / "ui/static/css/runtime-avatar.css").read_text(encoding="utf-8")
        events = (ROOT / "ui/static/js/socket/event-handlers.js").read_text(encoding="utf-8")

        self.assertIn("AMBIENT_BODY_MOTION_ENABLED", metabolism)
        self.assertIn("getBlendedChemistryColor", metabolism)
        self.assertIn("IDLE_HOMEOSTASIS_TICK_MS", metabolism)
        self.assertIn("--jin-avatar-metabolism-body-scale", metabolism)
        self.assertIn("--jin-avatar-metabolism-opacity", metabolism)
        self.assertIn("58s", css)
        self.assertIn("getActiveMemorySalience", avatar)
        self.assertIn("metabolism.applyServerUpdate(\n      data", events)
        self.assertNotIn("metabolism bubble", metabolism.lower())


if __name__ == "__main__":
    unittest.main()
