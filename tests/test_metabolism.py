import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from runtime.metabolism import (
    METABOLISM_DEFAULT_LEVELS,
    METABOLISM_MAX_OUTPUT_TOKENS,
    METABOLISM_MAX_STEP,
    METABOLISM_SYSTEM_PROMPT,
    append_metabolism_turn,
    apply_metabolism_target,
    build_metabolism_snapshot,
    compact_metabolism_snapshot_for_context,
    normalize_metabolism_levels,
    parse_metabolism_response,
    recover_metabolism_levels_locally,
    schedule_metabolism_update,
)


class MetabolismStateTests(unittest.TestCase):
    def test_normalizes_and_clamps_exact_five_channels(self):
        levels = normalize_metabolism_levels({
            "dopamine": 1.5,
            "serotonin": -1,
            "oxytocin": 0.3333,
            "norepinephrine": "0.7",
            "cortisol": None,
        })

        self.assertEqual(levels["dopamine"], 1.0)
        self.assertEqual(levels["serotonin"], 0.0)
        self.assertEqual(levels["oxytocin"], 0.333)
        self.assertEqual(levels["norepinephrine"], 0.7)
        self.assertEqual(
            levels["cortisol"],
            METABOLISM_DEFAULT_LEVELS["cortisol"],
        )
        self.assertEqual(set(levels), set(METABOLISM_DEFAULT_LEVELS))

    def test_runtime_owns_inertia_even_when_service_target_jumps(self):
        previous = dict(METABOLISM_DEFAULT_LEVELS)
        target = {
            "dopamine": 1.0,
            "serotonin": 0.0,
            "oxytocin": 1.0,
            "norepinephrine": 1.0,
            "cortisol": 1.0,
        }

        levels = apply_metabolism_target(previous, target)

        for channel, before in previous.items():
            self.assertLessEqual(
                abs(levels[channel] - before),
                METABOLISM_MAX_STEP[channel] + 1e-9,
            )

        self.assertEqual(levels["dopamine"], 0.50)
        self.assertEqual(levels["serotonin"], 0.54)
        self.assertEqual(levels["oxytocin"], 0.50)
        self.assertEqual(levels["norepinephrine"], 0.46)
        self.assertEqual(levels["cortisol"], 0.32)

    def test_snapshot_keeps_five_turns_actions_runtime_and_l4_index_only(self):
        context = SimpleNamespace(
            runtime_metabolism_levels=dict(METABOLISM_DEFAULT_LEVELS),
            runtime_metabolism_recent_turns=[],
            runtime_long_term_memory_store={
                "facts": [
                    {"id": "F1", "key": "one", "value": "alpha", "category": "other"},
                    {"id": "F2", "key": "two", "value": "beta", "category": "project_fact"},
                ]
            },
            runtime_session_action_history=[
                {
                    "text": "UPDATE_ACTIVE_MEMORY:failed",
                    "runtime_turn_id": "turn-12",
                    "parts": [
                        {
                            "text": "UPDATE_ACTIVE_MEMORY:failed",
                            "detail": "incorrect id",
                        }
                    ],
                }
            ],
            runtime_current_sequence_turn_id="turn-12",
            runtime_memory="state: current",
            turn_number=12,
            user_message_count=12,
            assistant_message_count=11,
            runtime_turn_interrupted=False,
            runtime_turn_interruption_reason="",
            runtime_last_response_feedback={"rating": "liked"},
        )

        for index in range(7):
            append_metabolism_turn(
                context,
                user_message=f"user-{index}",
                assistant_message=f"jin-{index}",
                reasoning=f"reason-{index}",
                feedback=(
                    {"rating": "liked", "clicks_count": 1}
                    if index == 6
                    else None
                ),
            )

        snapshot = build_metabolism_snapshot(context)

        self.assertEqual(len(snapshot["recent_interactions"]), 5)
        self.assertEqual(snapshot["recent_interactions"][0]["user"], "user-2")
        self.assertEqual(snapshot["recent_interactions"][-1]["reasoning"], "reason-6")
        self.assertEqual(
            snapshot["recent_interactions"][-1]["feedback"],
            {"rating": "liked", "clicks_count": 1},
        )
        self.assertEqual(len(snapshot["l4_index"]), 2)
        self.assertNotIn("value", snapshot["l4_index"][0])
        self.assertEqual(snapshot["runtime_state"]["runtime_memory"], "state: current")
        self.assertEqual(snapshot["runtime_state"]["latest_user_feedback"]["rating"], "liked")
        self.assertEqual(len(snapshot["recent_runtime_actions"]), 1)
        self.assertTrue(snapshot["recent_runtime_actions"][0]["current_turn"])
        self.assertEqual(
            snapshot["recent_runtime_actions"][0]["parts"][0]["detail"],
            "incorrect id",
        )

    def test_response_parser_accepts_fenced_json_and_requires_all_channels(self):
        response = {
            "choices": [{
                "message": {
                    "content": "```json\n{\"dopamine\":0.5,\"serotonin\":0.6,\"oxytocin\":0.4,\"norepinephrine\":0.3,\"cortisol\":0.2}\n```"
                }
            }]
        }
        levels, raw = parse_metabolism_response(response)
        self.assertIsNotNone(levels)
        self.assertEqual(levels["dopamine"], 0.5)
        self.assertIn("dopamine", raw)

        invalid, _ = parse_metabolism_response({
            "choices": [{"message": {"content": '{"dopamine":0.5}'}}]
        })
        self.assertIsNone(invalid)

        extra, _ = parse_metabolism_response({
            "choices": [{"message": {"content": json.dumps({
                "dopamine": 0.5,
                "serotonin": 0.6,
                "oxytocin": 0.4,
                "norepinephrine": 0.3,
                "cortisol": 0.2,
                "mood": "happy",
            })}}]
        })
        self.assertIsNone(extra)

        directed, _ = parse_metabolism_response({
            "choices": [{"message": {"content": json.dumps({
                "dopamine": 0.5,
                "serotonin": 0.6,
                "oxytocin": 0.4,
                "norepinephrine": 0.3,
                "cortisol": 0.2,
                "instruction": "Keep continuity and verify the relevant memory before committing.",
            })}}]
        })
        self.assertIsNotNone(directed)

    def test_context_budget_compacts_only_when_needed(self):
        snapshot = {
            "baseline": dict(METABOLISM_DEFAULT_LEVELS),
            "previous_levels": dict(METABOLISM_DEFAULT_LEVELS),
            "runtime_state": {
                "runtime_memory": "runtime " * 5000,
                "turn_number": 1,
                "user_messages": 1,
                "jin_messages": 1,
                "turn_interrupted": False,
                "interruption_reason": "",
                "latest_user_feedback": None,
            },
            "recent_runtime_actions": [
                {
                    "text": "UPDATE_ACTIVE_MEMORY:failed " * 100,
                    "current_turn": True,
                    "parts": [{"text": "failed", "detail": "incorrect id " * 100}],
                }
                for _ in range(10)
            ],
            "l4_index": [
                {
                    "id": f"F{index}",
                    "key": (f"key-{index} " * 100),
                    "category": "project_fact",
                }
                for index in range(30)
            ],
            "l4_facts_total": 30,
            "recent_interactions": [
                {
                    "user": "user " * 2000,
                    "jin": "jin " * 2000,
                    "reasoning": "reasoning " * 2000,
                }
                for _ in range(5)
            ],
        }

        unchanged = compact_metabolism_snapshot_for_context(
            snapshot,
            100000,
        )
        self.assertIs(unchanged, snapshot)

        compacted = compact_metabolism_snapshot_for_context(
            snapshot,
            4096,
        )
        self.assertTrue(compacted["snapshot_compaction"]["applied"])
        self.assertEqual(compacted["l4_facts_total"], 30)
        self.assertLessEqual(
            compacted["snapshot_compaction"]["estimated_input_tokens"],
            compacted["snapshot_compaction"]["input_budget_tokens"],
        )

    def test_instruction_prioritizes_runtime_evidence_and_runtime_owned_physics(self):
        self.assertIn("USER feedback/corrections", METABOLISM_SYSTEM_PROMPT)
        self.assertIn("concrete runtime action outcomes", METABOLISM_SYSTEM_PROMPT)
        self.assertIn("runtime applies inertia", METABOLISM_SYSTEM_PROMPT)
        self.assertIn("strict JSON only", METABOLISM_SYSTEM_PROMPT)
        self.assertIn("committed_l1.last_user_input", METABOLISM_SYSTEM_PROMPT)


class MetabolismSchedulingTests(unittest.IsolatedAsyncioTestCase):
    def build_context(self):
        logger = SimpleNamespace(log_metabolism=AsyncMock())
        emitter = SimpleNamespace(emit=AsyncMock())
        service_client = SimpleNamespace(model_uid="service-test", configured_context_window=32768)
        context = SimpleNamespace(
            clients={"service": service_client},
            logger=logger,
            emitter=emitter,
            background_tasks=set(),
            runtime_memory_update_task=None,
            runtime_metabolism_task=None,
            runtime_metabolism_levels=dict(METABOLISM_DEFAULT_LEVELS),
            runtime_metabolism_associations=[],
            runtime_metabolism_last_committed_l1_id="",
            runtime_metabolism_last_tick_at=0.0,
            runtime_metabolism_recent_turns=[
                {"user": "u", "jin": "j", "reasoning": "r"}
            ],
            runtime_long_term_memory_store={"facts": []},
            runtime_session_action_history=[],
            runtime_current_sequence_turn_id="",
            runtime_current_turn_id="",
            runtime_memory="snapshot",
            runtime_recent_turns=[],
            runtime_restored_session_dialog="",
            active_memory_records=[],
            delayed_memory_reports={},
            turn_number=1,
            user_message_count=1,
            assistant_message_count=1,
            runtime_turn_interrupted=False,
            runtime_turn_interruption_reason="",
            runtime_last_response_feedback=None,
        )
        return context, logger, emitter

    async def test_background_update_logs_request_response_applies_inertia_and_emits(self):
        context, logger, emitter = self.build_context()
        response = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "dopamine": 0.90,
                        "serotonin": 0.20,
                        "oxytocin": 0.90,
                        "norepinephrine": 0.90,
                        "cortisol": 0.90,
                    })
                }
            }]
        }

        with patch(
            "runtime.metabolism.ask_service_model",
            new=AsyncMock(return_value=response),
        ):
            task = schedule_metabolism_update(context)
            self.assertIsNotNone(task)
            result = await task

        self.assertEqual(result["dopamine"], 0.50)
        self.assertEqual(result["serotonin"], 0.54)
        self.assertEqual(logger.log_metabolism.await_count, 2)
        request_call = logger.log_metabolism.await_args_list[0]
        response_call = logger.log_metabolism.await_args_list[1]
        self.assertEqual(
            request_call.kwargs["request_id"],
            response_call.kwargs["request_id"],
        )
        emitter.emit.assert_awaited_once()
        payload = emitter.emit.await_args.args[0]
        self.assertEqual(payload["type"], "metabolism_update")
        self.assertEqual(payload["levels"]["cortisol"], 0.32)

    async def test_invalid_primary_response_is_recovered_locally_without_second_inference(self):
        context, logger, emitter = self.build_context()
        loose_response = {
            "choices": [{
                "message": {
                    "content": (
                        "dopamine: 0.61, serotonin: 0.62, oxytocin: 0.49, "
                        "norepinephrine: 0.44, cortisol: 0.19"
                    )
                }
            }]
        }
        ask_mock = AsyncMock(return_value=loose_response)

        with patch(
            "runtime.metabolism.ask_service_model",
            new=ask_mock,
        ):
            task = schedule_metabolism_update(context, debounce_seconds=0)
            self.assertIsNotNone(task)
            result = await task

        self.assertEqual(ask_mock.await_count, 1)
        self.assertEqual(result["dopamine"], 0.50)
        self.assertEqual(result["serotonin"], 0.62)
        response_call = logger.log_metabolism.await_args_list[1]
        details = json.loads(response_call.kwargs["details"])
        self.assertEqual(details["status"], "local_recovered")
        emitter.emit.assert_awaited_once()

    async def test_unrecoverable_response_keeps_previous_state_without_second_inference(self):
        context, logger, _ = self.build_context()
        broken_response = {
            "choices": [{"message": {"content": "I cannot produce the requested state."}}]
        }
        ask_mock = AsyncMock(return_value=broken_response)

        with patch("runtime.metabolism.ask_service_model", new=ask_mock):
            task = schedule_metabolism_update(context, debounce_seconds=0)
            result = await task

        self.assertEqual(ask_mock.await_count, 1)
        self.assertEqual(result, METABOLISM_DEFAULT_LEVELS)
        details = json.loads(logger.log_metabolism.await_args_list[1].kwargs["details"])
        self.assertEqual(details["status"], "invalid")

    async def test_reasoning_model_has_room_and_reports_output_truncation_explicitly(self):
        context, logger, _ = self.build_context()
        truncated_response = {
            "choices": [{
                "finish_reason": "length",
                "message": {
                    "content": "",
                    "reasoning_content": "Analysis stopped before the final JSON.",
                },
            }],
            "usage": {
                "prompt_tokens": 400,
                "completion_tokens": METABOLISM_MAX_OUTPUT_TOKENS,
                "total_tokens": 400 + METABOLISM_MAX_OUTPUT_TOKENS,
            },
        }
        ask_mock = AsyncMock(return_value=truncated_response)

        with patch("runtime.metabolism.ask_service_model", new=ask_mock):
            task = schedule_metabolism_update(context, debounce_seconds=0)
            result = await task

        self.assertGreaterEqual(METABOLISM_MAX_OUTPUT_TOKENS, 1024)
        self.assertEqual(
            ask_mock.await_args.kwargs["max_tokens"],
            METABOLISM_MAX_OUTPUT_TOKENS,
        )
        self.assertEqual(result, METABOLISM_DEFAULT_LEVELS)
        details = json.loads(logger.log_metabolism.await_args_list[1].kwargs["details"])
        self.assertEqual(details["status"], "truncated")
        self.assertEqual(details["finish_reason"], "length")
        self.assertEqual(
            details["usage"]["completion_tokens"],
            METABOLISM_MAX_OUTPUT_TOKENS,
        )
        self.assertEqual(details["raw"], "")
        self.assertNotIn("Analysis stopped", details["raw"])
        self.assertIn("output token limit", details["error"])

    async def test_cancelled_request_logs_terminal_result_with_same_request_id(self):
        context, logger, _ = self.build_context()
        started = asyncio.Event()

        async def slow_service(**kwargs):
            started.set()
            await asyncio.sleep(30)

        with patch(
            "runtime.metabolism.ask_service_model",
            new=slow_service,
        ):
            task = schedule_metabolism_update(context)
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        self.assertEqual(logger.log_metabolism.await_count, 2)
        first = logger.log_metabolism.await_args_list[0]
        second = logger.log_metabolism.await_args_list[1]
        self.assertEqual(first.kwargs["request_id"], second.kwargs["request_id"])
        self.assertEqual(second.kwargs["event"], "result")
        self.assertIn("cancelled", second.args[0])


if __name__ == "__main__":
    unittest.main()
