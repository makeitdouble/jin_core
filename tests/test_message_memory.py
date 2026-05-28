import unittest
from types import SimpleNamespace

from clients.brain_client import (
    build_brain_system_prompt,
)
from memory.message_memory import (
    build_runtime_memory_system_prompt,
    schedule_runtime_memory_update,
    summarize_runtime_memory,
)


class FakeServiceClient:

    def __init__(
        self,
        response_text: str,
    ):

        self.response_text = response_text
        self.calls = []

    async def ask(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ):

        self.calls.append({
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "temperature": temperature,
            "max_tokens": max_tokens,
        })

        return {
            "choices": [
                {
                    "message": {
                        "content": self.response_text,
                    },
                },
            ],
        }


class FakeLogger:

    def __init__(self):
        self.service_logs = []
        self.errors = []

    async def log_service(
        self,
        message: str,
    ):

        self.service_logs.append(
            message
        )

    async def log_error(
        self,
        message: str,
        details: str | None = None,
    ):

        self.errors.append(
            (
                message,
                details,
            )
        )


class MessageMemoryTests(
    unittest.IsolatedAsyncioTestCase
):

    def test_runtime_memory_prompt_focuses_on_summary_depth(self):

        prompt = build_runtime_memory_system_prompt()

        self.assertIn(
            "Decide the summary depth",
            prompt,
        )
        self.assertIn(
            "Use shallow summarization",
            prompt,
        )
        self.assertIn(
            "Use deep summarization",
            prompt,
        )
        self.assertNotIn(
            "after one completed user/JIN turn",
            prompt,
        )

    def test_brain_prompt_includes_runtime_memory(self):

        context = SimpleNamespace(
            runtime_memory=(
                "The user recently asked about Lamborghini pricing."
            ),
            deep_thought_count=0,
            runtime_search_result="",
            runtime_search_result_id="",
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_SEARCH": False,
                "CAN_DEEP_THOUGHT": False,
            },
        )

        self.assertIn(
            "<RUNTIME_MEMORY>",
            prompt,
        )
        self.assertIn(
            "Lamborghini pricing",
            prompt,
        )

    async def test_summarizer_updates_runtime_memory(self):

        service_client = FakeServiceClient(
            "The user is testing live runtime memory."
        )
        logger = FakeLogger()
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            logger=logger,
            runtime_memory="User and JIN just started interacting.",
            runtime_memory_updates=0,
        )

        updated_memory = await summarize_runtime_memory(
            context=context,
            user_message="Do you remember this?",
            assistant_message="Yes, I can keep the live context updated.",
        )

        self.assertEqual(
            updated_memory,
            "The user is testing live runtime memory.",
        )
        self.assertEqual(
            context.runtime_memory,
            "The user is testing live runtime memory.",
        )
        self.assertEqual(
            context.runtime_memory_updates,
            1,
        )
        self.assertIn(
            "Do you remember this?",
            service_client.calls[0]["user_prompt"],
        )
        self.assertEqual(
            service_client.calls[0]["system_prompt"],
            build_runtime_memory_system_prompt(),
        )
        self.assertIn(
            "[MEMORY] runtime memory updated",
            logger.service_logs,
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
            runtime_memory_updates=0,
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

        self.assertEqual(
            context.runtime_memory,
            "Updated background memory.",
        )
        self.assertEqual(
            len(
                context.background_tasks
            ),
            0,
        )


if __name__ == "__main__":
    unittest.main()
