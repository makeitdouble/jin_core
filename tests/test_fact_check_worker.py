import unittest
from types import SimpleNamespace

from runtime.fact_check import (
    CONFIRMABLE_MEMORY_KEYS,
    add_or_update_confirmation,
    apply_fact_check_result_to_memory,
    ensure_confirmable_memory_markers,
    extract_fact_check_candidates,
    run_fact_check_once,
)


class DummyEmitter:
    def __init__(self):
        self.events = []

    async def emit(self, payload):
        self.events.append(payload)


class FactCheckWorkerTests(unittest.IsolatedAsyncioTestCase):

    def test_confirmable_keys_constant_is_extendable(self):
        self.assertIn("user_fact", CONFIRMABLE_MEMORY_KEYS)
        self.assertIn("jin_recommendation", CONFIRMABLE_MEMORY_KEYS)

    def test_l1_confirmable_lines_get_default_none_marker(self):
        memory = "user_fact: User uses JIN locally.\ncurrent topic: Fact checking."

        updated = ensure_confirmable_memory_markers(memory)

        self.assertIn(
            "user_fact: User uses JIN locally. (confirmed: none)",
            updated,
        )
        self.assertIn("current topic: Fact checking.", updated)

    def test_explicit_user_confirmation_marks_user_fact_as_user(self):
        memory = "user_fact: User's project is called JIN."

        updated = ensure_confirmable_memory_markers(
            memory,
            user_message="Подтверждаю, это факт: проект называется JIN.",
        )

        self.assertIn("(confirmed: user)", updated)

    def test_fact_check_candidate_skips_web_confirmed_lines(self):
        memory = "pending_fact: Four Tet album R R R exists. (confirmed: web)"

        candidates = extract_fact_check_candidates(memory, layer="L1")

        self.assertEqual([], candidates)

    def test_add_web_failure_status_inside_confirmation_marker(self):
        line = "pending_fact: Four Tet album R R R exists. (confirmed: none)"

        updated = add_or_update_confirmation(line, web_status="fail")

        self.assertEqual(
            "pending_fact: Four Tet album R R R exists. (confirmed: none, web: fail (1))",
            updated,
        )

    def test_fact_check_updates_line_when_index_became_stale(self):
        memory_before = (
            "jin_fact: Recommended *Rathmore* as the ideal album. "
            "(confirmed: none) (trace: 0.50)"
        )
        candidate = extract_fact_check_candidates(
            memory_before,
            layer="L1",
        )[0]
        memory_after = (
            "session status: Session has just begun.\n"
            "jin_fact: Recommended *Rathmore* as the ideal album. "
            "(confirmed: none) (trace: 0.50)"
        )

        updated = apply_fact_check_result_to_memory(
            memory_after,
            candidate,
            "fail",
        )

        self.assertIn(
            "jin_fact: Recommended *Rathmore* as the ideal album. "
            "(confirmed: none, web: fail (1)) (trace: 0.50)",
            updated,
        )

    async def test_manual_fact_check_uses_injected_search_provider_and_marks_web(self):
        async def search_provider(query):
            return [
                {
                    "title": "Four Tet Rounds album",
                    "source": "example.test",
                    "url": "https://example.test/four-tet-rounds",
                    "quote": "Four Tet released the album Rounds.",
                    "excerpt": "Four Tet Rounds album",
                }
            ]

        context = SimpleNamespace(
            runtime_memory="pending_fact: Four Tet released the album Rounds. (confirmed: none)",
            runtime_l2_memory="",
            runtime_memory_stable="",
            runtime_memory_updates=1,
            runtime_memory_snapshots=[],
            runtime_memory_snapshot_index=0,
            runtime_memory_update_task=None,
            search_provider=search_provider,
            emitter=DummyEmitter(),
            logger=SimpleNamespace(log_service=None),
        )

        checks = await run_fact_check_once(context, reason="manual")

        self.assertEqual("web", checks[0]["status"])
        self.assertTrue(checks[0]["changed"])
        self.assertIn("(confirmed: web)", context.runtime_memory)
        self.assertTrue(
            any(event.get("type") == "fact_check_update" for event in context.emitter.events)
        )
        self.assertEqual(
            [
                {"type": "fact_check_state", "active": True, "reason": "manual"},
                {"type": "fact_check_state", "active": False, "reason": "manual"},
            ],
            [
                event
                for event in context.emitter.events
                if event.get("type") == "fact_check_state"
            ],
        )


if __name__ == "__main__":
    unittest.main()
