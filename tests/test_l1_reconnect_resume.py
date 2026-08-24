import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import runtime.L1_memory as l1_memory
import runtime.L1_memory_pending as l1_pending
from tests.helpers.memory import (
    FakeLogger,
    FakeServiceClient,
)


class L1ReconnectResumeTests(
    unittest.IsolatedAsyncioTestCase
):

    @staticmethod
    def build_context(
        *,
        service_client,
        session_id="reconnect-session",
        runtime_memory_updates=0,
        runtime_persistent_writes_restricted=False,
    ):
        emitter = SimpleNamespace(
            events=[],
            emit=None,
        )

        async def emit(event):
            emitter.events.append(
                event
            )

        emitter.emit = emit

        return SimpleNamespace(
            session_id=session_id,
            runtime_persistent_writes_restricted=(
                runtime_persistent_writes_restricted
            ),
            clients={
                "service": service_client,
            },
            logger=FakeLogger(),
            emitter=emitter,
            runtime_memory="Initial memory.",
            runtime_memory_stable="Initial memory.",
            runtime_memory_updates=runtime_memory_updates,
            runtime_memory_pending_turns=[],
            runtime_memory_pending_base_updates=0,
            runtime_memory_update_task=None,
            background_tasks=set(),
            runtime_memory_snapshots=[],
            runtime_memory_snapshot_index=0,
        )

    async def test_interrupted_l1_request_replays_after_backend_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            pending_dir = Path(directory)

            with patch.object(
                l1_pending,
                "PENDING_L1_DIR",
                pending_dir,
            ):
                first_context = self.build_context(
                    service_client=FakeServiceClient(
                        "First attempt should not matter."
                    )
                )

                first_task = l1_memory.schedule_runtime_memory_update(
                    context=first_context,
                    user_message="Remember the interrupted turn.",
                    assistant_message="I will keep it in L1.",
                )

                self.assertIsNotNone(
                    first_task
                )
                self.assertEqual(
                    len(list(pending_dir.glob("*.l1_pending.json"))),
                    1,
                )

                # Simulate the backend process disappearing while the L1 job is
                # still owned by that process. The durable checkpoint must stay.
                first_task.cancel()
                with self.assertRaises(
                    asyncio.CancelledError
                ):
                    await first_task

                restarted_service = FakeServiceClient(
                    "Recovered runtime memory."
                )
                restarted_context = self.build_context(
                    service_client=restarted_service,
                )

                restored = l1_pending.restore_pending_l1_update(
                    restarted_context
                )

                self.assertTrue(
                    restored
                )
                self.assertEqual(
                    restarted_context.runtime_memory_pending_turns,
                    [
                        {
                            "user_message": "Remember the interrupted turn.",
                            "assistant_message": "I will keep it in L1.",
                        },
                    ],
                )

                resumed_task = l1_memory.resume_runtime_memory_pending_update(
                    restarted_context
                )

                self.assertIsNotNone(
                    resumed_task
                )

                await resumed_task

                self.assertEqual(
                    len(restarted_service.calls),
                    1,
                )
                self.assertIn(
                    "Remember the interrupted turn.",
                    restarted_service.calls[0]["user_prompt"],
                )
                self.assertEqual(
                    restarted_context.runtime_memory_updates,
                    1,
                )
                self.assertTrue(
                    any(
                        event.get("type") == "runtime_memory_update"
                        for event in restarted_context.emitter.events
                    )
                )

    async def test_restricted_mode_replays_pending_l1_after_backend_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            pending_dir = Path(directory)

            with patch.object(
                l1_pending,
                "PENDING_L1_DIR",
                pending_dir,
            ):
                first_context = self.build_context(
                    service_client=FakeServiceClient(
                        "First attempt should not matter."
                    ),
                    runtime_persistent_writes_restricted=True,
                )

                first_task = l1_memory.schedule_runtime_memory_update(
                    context=first_context,
                    user_message="Keep this L1 turn across reconnect.",
                    assistant_message="This request must be replayed.",
                )

                self.assertIsNotNone(
                    first_task
                )
                self.assertEqual(
                    len(list(pending_dir.glob("*.l1_pending.json"))),
                    1,
                )

                first_task.cancel()
                with self.assertRaises(
                    asyncio.CancelledError
                ):
                    await first_task

                restarted_service = FakeServiceClient(
                    "Recovered restricted-mode runtime memory."
                )
                restarted_context = self.build_context(
                    service_client=restarted_service,
                    runtime_persistent_writes_restricted=True,
                )

                self.assertTrue(
                    l1_pending.restore_pending_l1_update(
                        restarted_context
                    )
                )

                resumed_task = l1_memory.resume_runtime_memory_pending_update(
                    restarted_context
                )

                self.assertIsNotNone(
                    resumed_task
                )

                await resumed_task

                self.assertEqual(
                    len(restarted_service.calls),
                    1,
                )
                self.assertTrue(
                    any(
                        message == "[MEMORY:L1] L1 summarizer request"
                        for message, _details
                        in restarted_context.logger.summarizer_logs
                    )
                )
                self.assertIn(
                    "Keep this L1 turn across reconnect.",
                    restarted_service.calls[0]["user_prompt"],
                )
                self.assertEqual(
                    restarted_context.runtime_memory_updates,
                    1,
                )
                self.assertTrue(
                    any(
                        event.get("type") == "runtime_memory_update"
                        for event in restarted_context.emitter.events
                    )
                )

    async def test_newer_browser_snapshot_discards_stale_pending_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            pending_dir = Path(directory)

            with patch.object(
                l1_pending,
                "PENDING_L1_DIR",
                pending_dir,
            ):
                source_context = self.build_context(
                    service_client=FakeServiceClient(
                        "Unused."
                    ),
                    runtime_memory_updates=4,
                )
                source_context.runtime_memory_pending_turns = [
                    {
                        "user_message": "Already committed.",
                        "assistant_message": "Already visible in browser L1.",
                    },
                ]
                source_context.runtime_memory_pending_base_updates = 4

                self.assertTrue(
                    l1_pending.persist_pending_l1_update(
                        source_context
                    )
                )

                resumed_context = self.build_context(
                    service_client=FakeServiceClient(
                        "Must not run."
                    ),
                    runtime_memory_updates=5,
                )

                self.assertTrue(
                    l1_pending.restore_pending_l1_update(
                        resumed_context
                    )
                )

                resumed_task = l1_memory.resume_runtime_memory_pending_update(
                    resumed_context
                )

                self.assertIsNone(
                    resumed_task
                )
                self.assertEqual(
                    resumed_context.runtime_memory_pending_turns,
                    [],
                )
                self.assertEqual(
                    list(pending_dir.glob("*.l1_pending.json")),
                    [],
                )


if __name__ == "__main__":
    unittest.main()
