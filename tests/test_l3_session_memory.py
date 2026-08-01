import unittest
from types import (
    SimpleNamespace,
)
from runtime.L3_memory_utils import (
    build_l3_session_memory_max_tokens,
    build_runtime_session_memory_user_prompt,
)
from runtime.L3_memory import (
    maybe_summarize_runtime_session_memory,
)
from runtime.L3_memory_rules import (
    L3_OUTPUT_MAX_TOKENS,
)
from config_loader import (
    config,
)
from tests.helpers.memory import (
    FakeLogger,
    FakeServiceClient,
)

class L3SessionMemoryTests(
    unittest.IsolatedAsyncioTestCase
):

    def test_l3_session_memory_prompt_uses_all_runtime_snapshots(self):

            prompt = build_runtime_session_memory_user_prompt(
                current_session_memory="decision: old handoff",
                runtime_memory_snapshots=[
                    {
                        "index": 0,
                        "raw_memory": "topic: first topic",
                        "total_diff": 30,
                    },
                    {
                        "index": 1,
                        "raw_memory": "decision: final direction",
                        "total_diff": 80,
                    },
                ],
                diff_history=[
                    {
                        "snapshot_index": 1,
                        "total_diff": 80,
                        "changes": {
                            "added": [
                                {
                                    "key": "decision",
                                }
                            ],
                        },
                    },
                ],
            )

            self.assertIn(
                "Selected L1 runtime memory snapshot history",
                prompt,
            )
            self.assertIn(
                "runtime_memory_id:",
                prompt,
            )
            self.assertIn(
                "topic: first topic",
                prompt,
            )
            self.assertIn(
                "decision: final direction",
                prompt,
            )
            self.assertIn(
                '"total_diff": 80',
                prompt,
            )
            self.assertIn(
                "omitted_middle_snapshots: 0",
                prompt,
            )
            self.assertIn(
                "Recent L1 diff history",
                prompt,
            )
            self.assertIn(
                "omitted_older_diffs: 0",
                prompt,
            )

    async def test_l3_session_memory_skips_service_when_turn_aborted(self):

            service_client = FakeServiceClient(
                "decision: should not be requested"
            )
            context = SimpleNamespace(
                clients={
                    "service": service_client,
                },
                emitter=SimpleNamespace(
                    events=[],
                    emit=None,
                ),
                logger=FakeLogger(),
                runtime_save_session_requested=True,
                runtime_turn_abort_requested=True,
                runtime_turn_discard_requested=False,
                runtime_l3_session_memory="decision: existing",
                session_memory="decision: existing",
                runtime_memory_snapshots=[
                    {
                        "index": 1,
                        "raw_memory": "decision: pending save",
                        "total_diff": 80,
                    },
                ],
            )

            async def emit(event):
                context.emitter.events.append(
                    event
                )

            context.emitter.emit = emit

            result = await maybe_summarize_runtime_session_memory(
                context=context,
            )

            self.assertEqual(
                result,
                "decision: existing",
            )
            self.assertEqual(
                service_client.calls,
                [],
            )
            self.assertFalse(
                context.runtime_save_session_requested,
            )
            self.assertEqual(
                context.runtime_save_session_result["status"],
                "aborted",
            )
            self.assertEqual(
                context.runtime_save_session_result["reason"],
                "turn_aborted",
            )
            self.assertEqual(
                context.emitter.events,
                [],
            )

    async def test_l3_session_memory_discards_service_response_when_turn_aborts(self):

            class AbortingServiceClient(
                FakeServiceClient
            ):

                async def ask(
                    self,
                    **kwargs,
                ):

                    response = await super().ask(
                        **kwargs
                    )
                    context.runtime_turn_abort_requested = True
                    return response

            service_client = AbortingServiceClient(
                "decision: should not be committed"
            )
            context = SimpleNamespace(
                clients={
                    "service": service_client,
                },
                emitter=SimpleNamespace(
                    events=[],
                    emit=None,
                ),
                logger=FakeLogger(),
                runtime_save_session_requested=True,
                runtime_turn_abort_requested=False,
                runtime_turn_discard_requested=False,
                runtime_l3_session_memory="decision: existing",
                session_memory="decision: existing",
                session_memory_source="",
                runtime_session_memory_updates=0,
                runtime_l1_diff_history=[],
                runtime_memory_snapshot_index=1,
                timestamp="2026-06-05T13:38:50",
                current_date="2026-06-05",
                current_time="13:38:50",
                weekday="Friday",
                year=2026,
                runtime_memory_snapshots=[
                    {
                        "index": 1,
                        "raw_memory": "decision: pending save",
                        "total_diff": 80,
                    },
                ],
            )

            async def emit(event):
                context.emitter.events.append(
                    event
                )

            context.emitter.emit = emit

            result = await maybe_summarize_runtime_session_memory(
                context=context,
            )

            self.assertEqual(
                result,
                "decision: existing",
            )
            self.assertEqual(
                len(service_client.calls),
                1,
            )
            self.assertEqual(
                context.session_memory,
                "decision: existing",
            )
            self.assertEqual(
                context.runtime_session_memory_updates,
                0,
            )
            self.assertEqual(
                context.runtime_save_session_result["status"],
                "aborted",
            )
            self.assertFalse(
                any(
                    event.get("type") == "runtime_session_memory_update"
                    for event in context.emitter.events
                )
            )
            self.assertFalse(
                any(
                    event.get("type") == "runtime_action"
                    and event.get("action") == "save_session"
                    and event.get("status") == "completed"
                    for event in context.emitter.events
                )
            )

    def test_l3_session_memory_prompt_bounds_long_snapshot_history(self):

            prompt = build_runtime_session_memory_user_prompt(
                current_session_memory="decision: old handoff",
                runtime_memory_snapshots=[
                    {
                        "index": index,
                        "raw_memory": f"topic: snapshot {index}",
                        "total_diff": index,
                    }
                    for index in range(30)
                ],
                diff_history=[
                    {
                        "snapshot_index": index,
                        "total_diff": index,
                        "changes": {
                            "changed": [
                                {
                                    "current_key": f"decision_{index}",
                                }
                            ],
                        },
                    }
                    for index in range(40)
                ],
            )

            self.assertIn(
                "omitted_middle_snapshots: 0",
                prompt,
            )
            self.assertIn(
                "topic: snapshot 0",
                prompt,
            )
            self.assertIn(
                "topic: snapshot 29",
                prompt,
            )
            self.assertIn(
                "topic: snapshot 10",
                prompt,
            )
            self.assertIn(
                "omitted_older_diffs: 32",
                prompt,
            )

    def test_l3_session_memory_prompt_uses_compact_digest_not_raw_archive(self):

            prompt = build_runtime_session_memory_user_prompt(
                current_session_memory="\n".join(
                    f"old narrative {index}: {'a' * 300}"
                    for index in range(20)
                ),
                runtime_memory_snapshots=[
                    {
                        "index": index,
                        "raw_memory": (
                            f"decision: keep snapshot {index}\n"
                            f"narrative: {'d' * 1200}"
                        ),
                        "total_diff": index,
                    }
                    for index in range(12)
                ],
                diff_history=[
                    {
                        "snapshot_index": index,
                        "total_diff": index,
                        "changes": {
                            "changed": [
                                {
                                    "previous_key": "narrative",
                                    "previous_value": "e" * 1000,
                                    "current_key": "decision",
                                    "current_value": "f" * 1000,
                                }
                            ],
                        },
                    }
                    for index in range(20)
                ],
            )

            self.assertIn(
                "L3 compact digest minimal: False",
                prompt,
            )
            self.assertNotIn(
                "Compact L2 pattern context:",
                prompt,
            )
            self.assertNotIn(
                "Current L2 pattern memory for context only:",
                prompt,
            )
            self.assertEqual(
                prompt.count("snapshot:"),
                12,
            )
            self.assertNotIn(
                "c" * 500,
                prompt,
            )
            self.assertNotIn(
                "e" * 500,
                prompt,
            )
            self.assertIn(
                "omitted_older_diffs:",
                prompt,
            )

    def test_l3_session_memory_prompt_filters_noisy_l1_diff_keys(self):

            prompt = build_runtime_session_memory_user_prompt(
                current_session_memory="decision: old handoff",
                runtime_memory_snapshots=[
                    {
                        "index": 1,
                        "raw_memory": "decision: keep useful snapshot",
                        "total_diff": 80,
                    },
                ],
                diff_history=[
                    {
                        "snapshot_index": 1,
                        "total_diff": 240.95,
                        "changes": {
                            "added": [
                                {
                                    "key": "last_jin_response",
                                },
                                {
                                    "key": "user_name",
                                },
                                {
                                    "key": "active_memory_temporal_continuity",
                                },
                            ],
                            "changed": [
                                {
                                    "current_key": "user_message",
                                },
                                {
                                    "current_key": "user_idle",
                                },
                            ],
                            "removed": [
                                {
                                    "key": "last_jin_response",
                                },
                            ],
                        },
                    },
                    {
                        "snapshot_index": 2,
                        "total_diff": 172.2,
                        "changes": {
                            "added": [
                                {
                                    "key": "last_jin_response",
                                },
                            ],
                            "changed": [
                                {
                                    "current_key": "active_memory_temporal_continuity",
                                },
                                {
                                    "current_key": "user_idle",
                                },
                            ],
                            "removed": [
                                {
                                    "key": "last_jin_response",
                                },
                            ],
                        },
                    },
                ],
            )

            self.assertIn(
                '"user_name"',
                prompt,
            )
            self.assertNotIn(
                "last_jin_response",
                prompt,
            )
            self.assertNotIn(
                "active_memory_temporal_continuity",
                prompt,
            )
            self.assertNotIn(
                "user_message",
                prompt,
            )
            self.assertNotIn(
                "user_idle",
                prompt,
            )
            self.assertIn(
                '"snapshot_index": 1',
                prompt,
            )
            self.assertNotIn(
                '"snapshot_index": 2',
                prompt,
            )

    def test_l3_session_memory_budget_uses_detected_context_window(self):

            system_prompt = "system " * 2000
            user_prompt = "user " * 2000

            configured_budget = build_l3_session_memory_max_tokens(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            detected_budget = build_l3_session_memory_max_tokens(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                context_window=8192,
            )

            self.assertEqual(
                configured_budget,
                128,
            )
            self.assertGreater(
                detected_budget,
                configured_budget,
            )

    async def test_l3_session_memory_updates_from_snapshot_history(self):

            service_client = FakeServiceClient(
                "decision: Continue session memory implementation\n"
                "next step: Verify browser persistence"
            )
            logger = FakeLogger()
            context = SimpleNamespace(
                clients={
                    "service": service_client,
                },
                emitter=SimpleNamespace(
                    events=[],
                    emit=None,
                ),
                logger=logger,
                runtime_save_session_requested=True,
                runtime_l3_session_memory="",
                session_memory="",
                session_memory_source="",
                runtime_session_memory_updates=0,
                runtime_l2_memory="",
                timestamp="2026-06-05T13:38:50",
                current_date="2026-06-05",
                current_time="13:38:50",
                weekday="Friday",
                year=2026,
                runtime_l1_diff_history=[
                    {
                        "snapshot_index": 1,
                        "total_diff": 80,
                    },
                ],
                runtime_memory_snapshot_index=1,
                runtime_memory_snapshots=[
                    {
                        "index": 0,
                        "raw_memory": "topic: first topic",
                        "total_diff": 30,
                    },
                    {
                        "index": 1,
                        "raw_memory": "decision: final direction",
                        "total_diff": 80,
                    },
                ],
            )

            async def emit(event):
                context.emitter.events.append(
                    event
                )

            context.emitter.emit = emit

            updated_memory = await maybe_summarize_runtime_session_memory(
                context=context,
            )

            self.assertIn(
                "Continue session memory implementation",
                updated_memory,
            )
            self.assertTrue(
                updated_memory.startswith(
                    "session_saved_at: 2026-06-05 13:38, Friday\n"
                    "session_snapshot_first_turn: 0\n"
                )
            )
            self.assertEqual(
                context.runtime_session_memory_updates,
                1,
            )
            self.assertFalse(
                context.runtime_save_session_requested,
            )
            self.assertEqual(
                context.runtime_memory_snapshots,
                [
                    {
                        "index": 0,
                        "raw_memory": "topic: first topic",
                        "total_diff": 30,
                    },
                    {
                        "index": 1,
                        "raw_memory": "decision: final direction",
                        "total_diff": 80,
                    },
                ],
            )
            self.assertEqual(
                context.runtime_memory_snapshot_index,
                1,
            )
            self.assertEqual(
                context.session_memory_source,
                "L3",
            )
            self.assertIn(
                "topic: first topic",
                service_client.calls[0]["user_prompt"],
            )
            self.assertIn(
                "decision: final direction",
                service_client.calls[0]["user_prompt"],
            )
            self.assertIn(
                "<USER_DATETIME>2026-06-05 13:38, Friday</USER_DATETIME>",
                service_client.calls[0]["user_prompt"],
            )
            self.assertLess(
                service_client.calls[0]["user_prompt"].index(
                    "<CURRENT_TRUSTED_RUNTIME_VARIABLES>"
                ),
                service_client.calls[0]["user_prompt"].index(
                    "Current L3 session memory:"
                ),
            )
            self.assertEqual(
                service_client.calls[0]["timeout"],
                config.SERVICE_REQUEST_TIMEOUT,
            )
            self.assertLess(
                service_client.calls[0]["max_tokens"],
                config.SERVICE_MAX_TOKENS,
            )
            self.assertGreaterEqual(
                service_client.calls[0]["max_tokens"],
                128,
            )
            self.assertEqual(
                service_client.calls[0]["max_tokens"],
                L3_OUTPUT_MAX_TOKENS,
            )
            self.assertIn(
                (
                    "[MEMORY:L3] L3 session output token budget capped at "
                    f"{L3_OUTPUT_MAX_TOKENS}"
                ),
                logger.runtime_logs,
            )
            self.assertEqual(
                context.emitter.events[-2]["type"],
                "runtime_session_memory_update",
            )
            self.assertTrue(
                context.emitter.events[-2]["persist"],
            )
            self.assertEqual(
                context.emitter.events[-1],
                {
                    "type": "runtime_action",
                    "action": "save_session",
                    "status": "completed",
                },
            )

    async def test_l3_session_memory_uses_timestamp_when_date_fields_are_empty(self):

            service_client = FakeServiceClient(
                "decision: Continue restored session"
            )
            logger = FakeLogger()
            context = SimpleNamespace(
                clients={
                    "service": service_client,
                },
                emitter=SimpleNamespace(
                    events=[],
                    emit=None,
                ),
                logger=logger,
                runtime_save_session_requested=True,
                runtime_l3_session_memory="",
                session_memory="",
                session_memory_source="",
                runtime_session_memory_updates=0,
                runtime_l2_memory="",
                timestamp="2026-06-05T13:38:50",
                current_date="",
                current_time="",
                weekday="",
                year=2026,
                runtime_l1_diff_history=[],
                runtime_memory_snapshot_index=1,
                runtime_memory_snapshots=[
                    {
                        "index": 1,
                        "raw_memory": "decision: restored tail",
                        "total_diff": 80,
                    },
                ],
            )

            async def emit(event):
                context.emitter.events.append(
                    event
                )

            context.emitter.emit = emit

            updated_memory = await maybe_summarize_runtime_session_memory(
                context=context,
            )

            self.assertTrue(
                updated_memory.startswith(
                    "session_saved_at: 2026-06-05 13:38, Friday\n"
                )
            )
            self.assertNotIn(
                "session_saved_at: ,",
                updated_memory,
            )

    async def test_l3_session_memory_uses_current_runtime_update_steps_after_restore(self):

            service_client = FakeServiceClient(
                "decision: Continue restored current session"
            )
            logger = FakeLogger()
            context = SimpleNamespace(
                clients={
                    "service": service_client,
                },
                emitter=SimpleNamespace(
                    events=[],
                    emit=None,
                ),
                logger=logger,
                runtime_save_session_requested=True,
                runtime_l3_session_memory=(
                    "session_saved_at: 2026-06-01 09:00, Monday\n"
                    "session_snapshot_first_turn: 42\n"
                    "session_snapshot_last_turn: 99\n"
                    "decision: restored previous session handoff"
                ),
                session_memory_source="browser_localStorage",
                session_memory="",
                runtime_session_memory_updates=1,
                runtime_l3_saved_runtime_snapshot_index=None,
                runtime_l2_memory="",
                timestamp="2026-06-05T13:38:50",
                current_date="",
                current_time="",
                weekday="",
                year=2026,
                turn_number=97,
                user_message_count=97,
                assistant_message_count=108,
                runtime_memory_updates=13,
                runtime_l1_diff_history=[
                    {
                        "snapshot_index": 1,
                        "total_diff": 80,
                    },
                ],
                runtime_memory_snapshot_index=1,
                runtime_memory_snapshots=[
                    {
                        "index": 1,
                        "raw_memory": "decision: current restored session tail",
                        "total_diff": 80,
                    },
                ],
            )

            async def emit(event):
                context.emitter.events.append(
                    event
                )

            context.emitter.emit = emit

            updated_memory = await maybe_summarize_runtime_session_memory(
                context=context,
            )

            self.assertIn(
                "session_saved_at: 2026-06-05 13:38, Friday",
                updated_memory,
            )
            self.assertIn(
                "session_snapshot_first_turn: 1",
                updated_memory,
            )
            self.assertIn(
                "session_snapshot_last_turn: 13",
                updated_memory,
            )
            self.assertEqual(
                context.runtime_l3_session_first_turn,
                1,
            )
            self.assertEqual(
                context.runtime_l3_session_last_turn,
                13,
            )

    async def test_l3_session_memory_merges_previous_snapshot_with_unsaved_tail_only(self):

            service_client = FakeServiceClient(
                "decision: merged handoff after new tail"
            )
            logger = FakeLogger()
            context = SimpleNamespace(
                clients={
                    "service": service_client,
                },
                emitter=SimpleNamespace(
                    events=[],
                    emit=None,
                ),
                logger=logger,
                runtime_save_session_requested=True,
                runtime_l3_session_memory=(
                    "session_snapshot_first_turn: 0\n"
                    "session_snapshot_last_turn: 15\n"
                    "decision: old consolidated handoff"
                ),
                session_memory="",
                session_memory_source="",
                runtime_session_memory_updates=1,
                runtime_l3_saved_runtime_snapshot_index=15,
                runtime_l3_session_first_turn=0,
                runtime_l3_session_last_turn=15,
                runtime_l2_memory="",
                timestamp="2026-06-05T13:38:50",
                current_date="2026-06-05",
                current_time="13:38:50",
                weekday="Friday",
                year=2026,
                runtime_l1_diff_history=[
                    {
                        "snapshot_index": 15,
                        "total_diff": 80,
                    },
                    {
                        "snapshot_index": 16,
                        "total_diff": 20,
                    },
                    {
                        "snapshot_index": 20,
                        "total_diff": 70,
                    },
                ],
                runtime_memory_snapshot_index=20,
                runtime_memory_snapshots=[
                    {
                        "index": 14,
                        "raw_memory": "topic: old stale page",
                        "total_diff": 30,
                    },
                    {
                        "index": 15,
                        "raw_memory": "decision: old saved boundary",
                        "total_diff": 80,
                    },
                    {
                        "index": 16,
                        "raw_memory": "topic: fresh tail starts",
                        "total_diff": 20,
                    },
                    {
                        "index": 20,
                        "raw_memory": "decision: fresh tail ends",
                        "total_diff": 70,
                    },
                ],
            )

            async def emit(event):
                context.emitter.events.append(
                    event
                )

            context.emitter.emit = emit

            updated_memory = await maybe_summarize_runtime_session_memory(
                context=context,
            )

            prompt = service_client.calls[0]["user_prompt"]

            self.assertIn(
                "decision: old consolidated handoff",
                prompt,
            )
            self.assertIn(
                "topic: fresh tail starts",
                prompt,
            )
            self.assertIn(
                "decision: fresh tail ends",
                prompt,
            )
            self.assertNotIn(
                "topic: old stale page",
                prompt,
            )
            self.assertNotIn(
                "decision: old saved boundary",
                prompt,
            )
            self.assertIn(
                "session_snapshot_first_turn: 0",
                updated_memory,
            )
            self.assertTrue(
                updated_memory.startswith(
                    "session_saved_at: 2026-06-05 13:38, Friday\n"
                    "session_snapshot_first_turn: 0\n"
                )
            )
            self.assertIn(
                "session_snapshot_last_turn: 20",
                updated_memory,
            )
            self.assertEqual(
                context.runtime_l3_saved_runtime_snapshot_index,
                20,
            )
            self.assertEqual(
                context.runtime_l3_session_last_turn,
                20,
            )

    async def test_l3_session_memory_logs_when_response_reaches_max_tokens(self):

            service_client = FakeServiceClient(
                "decision: incomplete",
                finish_reasons=[
                    "length",
                ],
            )
            logger = FakeLogger()
            context = SimpleNamespace(
                clients={
                    "service": service_client,
                },
                emitter=SimpleNamespace(
                    events=[],
                    emit=None,
                ),
                logger=logger,
                runtime_save_session_requested=True,
                runtime_l3_session_memory="decision: keep current",
                session_memory="decision: keep current",
                session_memory_source="",
                runtime_session_memory_updates=0,
                runtime_l2_memory="",
                runtime_l1_diff_history=[],
                runtime_memory_snapshots=[
                    {
                        "index": 0,
                        "raw_memory": "topic: first topic",
                        "total_diff": 30,
                    },
                ],
            )

            async def emit(event):
                context.emitter.events.append(
                    event
                )

            context.emitter.emit = emit

            updated_memory = await maybe_summarize_runtime_session_memory(
                context=context,
            )

            self.assertEqual(
                updated_memory,
                "decision: keep current",
            )
            self.assertFalse(
                context.runtime_save_session_requested,
            )
            self.assertFalse(
                context.runtime_save_session_action_emitted,
            )
            calls_after_skip = len(
                service_client.calls
            )
            repeated_memory = await maybe_summarize_runtime_session_memory(
                context=context,
            )
            self.assertEqual(
                repeated_memory,
                "decision: keep current",
            )
            self.assertEqual(
                len(service_client.calls),
                calls_after_skip,
            )
            self.assertEqual(
                context.runtime_memory_snapshots,
                [
                    {
                        "index": 0,
                        "raw_memory": "topic: first topic",
                        "total_diff": 30,
                    },
                ],
            )
            self.assertIn(
                "[MEMORY:L3] L3 session summarizer reached max_tokens",
                logger.runtime_logs,
            )
            self.assertEqual(
                logger.errors[-1][0],
                "[MEMORY:L3] L3 session memory update skipped",
            )
            self.assertIn(
                "truncated by max_tokens",
                logger.errors[-1][1],
            )

    async def test_l3_session_memory_skips_when_minimal_digest_exceeds_budget(self):

            class TinyContextServiceClient(FakeServiceClient):

                async def resolve_request_context_window(self):
                    return 600

            service_client = TinyContextServiceClient(
                "should not be called"
            )
            logger = FakeLogger()
            context = SimpleNamespace(
                clients={
                    "service": service_client,
                },
                emitter=SimpleNamespace(
                    events=[],
                    emit=None,
                ),
                logger=logger,
                runtime_save_session_requested=True,
                runtime_l3_session_memory="decision: keep current",
                session_memory="decision: keep current",
                session_memory_source="",
                runtime_session_memory_updates=0,
                runtime_l2_memory="",
                runtime_l1_diff_history=[],
                runtime_memory_snapshots=[
                    {
                        "index": 0,
                        "raw_memory": "decision: keep latest",
                        "total_diff": 1,
                    }
                ],
            )

            async def emit(event):
                context.emitter.events.append(
                    event
                )

            context.emitter.emit = emit

            updated_memory = await maybe_summarize_runtime_session_memory(
                context=context,
            )

            self.assertEqual(
                updated_memory,
                "decision: keep current",
            )
            self.assertEqual(
                service_client.calls,
                [],
            )
            self.assertFalse(
                context.runtime_save_session_requested,
            )
            self.assertEqual(
                context.emitter.events[-1],
                {
                    "type": "runtime_action",
                    "action": "save_session",
                    "status": "completed",
                },
            )
            self.assertEqual(
                logger.errors[-1][0],
                "[MEMORY:L3] L3 session memory update skipped",
            )
            self.assertIn(
                "compact digest still exceeds safe input budget",
                logger.errors[-1][1],
            )
            self.assertEqual(
                context.runtime_memory_snapshots,
                [
                    {
                        "index": 0,
                        "raw_memory": "decision: keep latest",
                        "total_diff": 1,
                    }
                ],
            )

    async def test_l3_session_memory_preserves_snapshots_when_update_fails(self):

            service_client = FakeServiceClient(
                RuntimeError("service unavailable")
            )
            logger = FakeLogger()
            snapshots = [
                {
                    "index": 0,
                    "raw_memory": "topic: first topic",
                    "total_diff": 30,
                },
                {
                    "index": 1,
                    "raw_memory": "decision: final direction",
                    "total_diff": 80,
                },
            ]
            context = SimpleNamespace(
                clients={
                    "service": service_client,
                },
                emitter=SimpleNamespace(
                    events=[],
                    emit=None,
                ),
                logger=logger,
                runtime_save_session_requested=True,
                runtime_l3_session_memory="decision: keep current",
                session_memory="decision: keep current",
                session_memory_source="",
                runtime_l2_memory="",
                runtime_l1_diff_history=[],
                runtime_memory_snapshots=list(snapshots),
            )

            async def emit(event):
                context.emitter.events.append(
                    event
                )

            context.emitter.emit = emit

            updated_memory = await maybe_summarize_runtime_session_memory(
                context=context,
            )

            self.assertEqual(
                updated_memory,
                "decision: keep current",
            )
            self.assertFalse(
                context.runtime_save_session_requested,
            )
            self.assertEqual(
                context.runtime_memory_snapshots,
                snapshots,
            )
            self.assertEqual(
                logger.errors[-1][0],
                "[MEMORY:L3] L3 session memory update failed",
            )

    async def test_l3_session_memory_no_snapshots_clears_save_request(self):

            service_client = FakeServiceClient(
                "should not be called"
            )
            logger = FakeLogger()
            context = SimpleNamespace(
                clients={
                    "service": service_client,
                },
                emitter=SimpleNamespace(
                    events=[],
                    emit=None,
                ),
                logger=logger,
                runtime_save_session_requested=True,
                runtime_l3_session_memory="decision: keep current",
                session_memory="decision: keep current",
                runtime_memory_snapshots=[],
            )

            async def emit(event):
                context.emitter.events.append(
                    event
                )

            context.emitter.emit = emit

            updated_memory = await maybe_summarize_runtime_session_memory(
                context=context,
            )

            self.assertEqual(
                updated_memory,
                "decision: keep current",
            )
            self.assertEqual(
                service_client.calls,
                [],
            )
            self.assertEqual(
                context.runtime_memory_snapshots,
                [],
            )
            self.assertFalse(
                context.runtime_save_session_requested,
            )
            self.assertEqual(
                logger.runtime_logs,
                [
                    "[MEMORY:L3] L3 session save skipped: no snapshots",
                ],
            )

