import unittest
from types import (
    SimpleNamespace,
)
from runtime.L1_memory import (
    schedule_interrupted_runtime_memory_update,
    schedule_runtime_memory_update,
    summarize_runtime_memory_pending_turns,
)
from config_loader import (
    config,
)
from tests.helpers.memory import (
    FakeLogger,
    FakeServiceClient,
)

class MemorySchedulerTests(
    unittest.IsolatedAsyncioTestCase
):

    async def test_pending_turns_do_not_inject_latest_turn_fields(self):

            service_client = FakeServiceClient(
                "active_topic: Batch update remains active."
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
                runtime_memory="active_topic: Initial topic.",
                runtime_memory_stable="active_topic: Initial topic.",
                runtime_memory_updates=1,
                runtime_memory_pending_turns=[
                    {
                        "user_message": "first message",
                        "assistant_message": "First answer.",
                    },
                    {
                        "user_message": '"hello" [ repeated: 3 ]',
                        "assistant_message": "Latest repeated answer.",
                    },
                ],
                runtime_memory_update_task=None,
                runtime_memory_snapshots=[],
                runtime_memory_snapshot_index=0,
                session_id="test-session",
            )

            async def emit(event):
                context.emitter.events.append(
                    event
                )

            context.emitter.emit = emit

            updated_memory = await summarize_runtime_memory_pending_turns(
                context=context,
            )

            self.assertIn(
                "active_topic: Batch update remains active.",
                updated_memory,
            )
            self.assertNotIn(
                "user_message:",
                updated_memory,
            )
            self.assertNotIn(
                "last_jin_response:",
                updated_memory,
            )

    async def test_scheduled_update_is_background_task(self):

            service_client = FakeServiceClient(
                "Updated background memory."
            )
            context = SimpleNamespace(
                clients={
                    "service": service_client,
                },
                logger=FakeLogger(),
                runtime_memory="Initial memory.",
                runtime_memory_stable="Initial memory.",
                runtime_memory_updates=0,
                runtime_memory_pending_turns=[],
                runtime_memory_update_task=None,
            )

            task = schedule_runtime_memory_update(
                context=context,
                user_message="First message",
                assistant_message="First answer",
            )

            self.assertIsNotNone(
                task
            )
            self.assertTrue(
                hasattr(
                    context,
                    "background_tasks",
                )
            )

            await task

            user_prompt = service_client.calls[0]["user_prompt"]

            self.assertNotIn(
                "<CURRENT_TRUSTED_RUNTIME_VARIABLES>",
                user_prompt,
            )
            self.assertNotIn(
                "New completed turns since that memory snapshot:",
                user_prompt,
            )

            self.assertIn(
                "Updated background memory.",
                context.runtime_memory,
            )
            self.assertNotIn(
                "user_message:",
                context.runtime_memory,
            )
            self.assertNotIn(
                "last_jin_response:",
                context.runtime_memory,
            )
            self.assertEqual(
                context.logger.summarizer_logs[0][0],
                "[MEMORY:L1] L1 summarizer request",
            )
            self.assertEqual(
                service_client.calls[0]["timeout"],
                config.SERVICE_REQUEST_TIMEOUT,
            )
            self.assertEqual(
                len(
                    context.background_tasks
                ),
                0,
            )

    async def test_pending_turns_log_batch_only_for_multiple_turns(self):

            service_client = FakeServiceClient(
                "Updated batch memory."
            )
            logger = FakeLogger()
            context = SimpleNamespace(
                clients={
                    "service": service_client,
                },
                logger=logger,
                runtime_memory="Initial memory.",
                runtime_memory_stable="Initial memory.",
                runtime_memory_updates=0,
                runtime_memory_pending_turns=[
                    {
                        "user_message": "First message",
                        "assistant_message": "First answer",
                    },
                    {
                        "user_message": "Second message",
                        "assistant_message": "Second answer",
                    },
                ],
                runtime_memory_update_task=None,
            )

            await summarize_runtime_memory_pending_turns(
                context=context,
            )

            self.assertEqual(
                logger.summarizer_logs[0][0],
                "[MEMORY:L1] L1 batch summarizer request",
            )
            self.assertEqual(
                service_client.calls[0]["timeout"],
                config.SERVICE_REQUEST_TIMEOUT,
            )

    async def test_interrupted_update_uses_partial_response(self):

            service_client = FakeServiceClient(
                "- Active topic: storytelling\n"
                "- Interrupted response: user stopped the answer before completion"
            )
            context = SimpleNamespace(
                clients={
                    "service": service_client,
                },
                logger=FakeLogger(),
                runtime_memory="Initial memory.",
                runtime_memory_stable="Initial memory.",
                runtime_memory_updates=0,
                runtime_memory_pending_turns=[],
                runtime_memory_update_task=None,
                runtime_turn_user_message="Tell me a story.",
                runtime_turn_assistant_response="Once upon a",
            )

            task = schedule_interrupted_runtime_memory_update(
                context=context,
            )

            self.assertIsNotNone(
                task
            )

            await task

            user_prompt = service_client.calls[0]["user_prompt"]

            self.assertIn(
                "interrupted by the user",
                user_prompt,
            )
            self.assertIn(
                "Tell me a story.",
                user_prompt,
            )
            self.assertIn(
                "Once upon a",
                user_prompt,
            )
            self.assertIn(
                "Interrupted response",
                context.runtime_memory,
            )

    async def test_guard_interrupted_update_uses_reason_and_quote(self):

            service_client = FakeServiceClient(
                "- Interrupted response: repeated sentence loop stopped"
            )
            context = SimpleNamespace(
                clients={
                    "service": service_client,
                },
                logger=FakeLogger(),
                runtime_memory="Initial memory.",
                runtime_memory_stable="Initial memory.",
                runtime_memory_updates=0,
                runtime_memory_pending_turns=[],
                runtime_memory_update_task=None,
                runtime_turn_user_message="Use load_skill if needed.",
                runtime_turn_assistant_response="Partial answer",
                runtime_turn_interruption_reason=(
                    "Repeated sentence loop detected."
                ),
                runtime_turn_interruption_quote=(
                    "Wait, I'll check if I should use load_skill first."
                ),
            )

            task = schedule_interrupted_runtime_memory_update(
                context=context,
            )

            self.assertIsNotNone(
                task
            )

            await task

            user_prompt = service_client.calls[0]["user_prompt"]

            self.assertIn(
                "Repeated sentence loop detected.",
                user_prompt,
            )
            self.assertIn(
                "Wait, I'll check if I should use load_skill first.",
                user_prompt,
            )
            self.assertNotIn(
                "interrupted by the user",
                user_prompt,
            )

