import unittest
from types import SimpleNamespace

from clients.brain_client import (
    build_brain_system_prompt,
)
from memory.message_memory import (
    DEFAULT_RUNTIME_MEMORY,
    build_interrupted_assistant_message,
    build_runtime_memory_system_prompt,
    build_runtime_memory_user_prompt,
    schedule_interrupted_runtime_memory_update,
    schedule_runtime_memory_update,
    summarize_runtime_memory,
)
from runtime.runtime_context import (
    RuntimeContext,
)
from settings.config_loader import (
    config,
)


class FakeServiceClient:

    def __init__(
        self,
        response_text,
        finish_reasons=None,
    ):

        self.response_text = response_text
        self.finish_reasons = list(
            finish_reasons
            or []
        )
        self.calls = []

    async def ask(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
        timeout: float | None = None,
    ):

        self.calls.append({
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": timeout,
        })

        if isinstance(
            self.response_text,
            Exception,
        ):
            raise self.response_text

        if isinstance(
            self.response_text,
            list,
        ):
            content = self.response_text[
                len(
                    self.calls
                )
                - 1
            ]
        else:
            content = self.response_text

        choice = {
            "message": {
                "content": content,
            },
        }

        if self.finish_reasons:
            choice["finish_reason"] = (
                self.finish_reasons.pop(0)
            )

        return {
            "choices": [
                choice,
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

    def test_runtime_memory_user_prompt_uses_session_fallback(self):

        prompt = build_runtime_memory_user_prompt(
            current_memory="",
            user_message="hello",
            assistant_message="hi",
        )

        self.assertIn(
            DEFAULT_RUNTIME_MEMORY,
            prompt,
        )

    def test_first_brain_prompt_includes_default_runtime_memory(self):

        context = RuntimeContext(
            websocket=object(),
            emitter=object(),
            logger=object(),
            clients={},
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
            DEFAULT_RUNTIME_MEMORY,
            prompt,
        )

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
        self.assertIn(
            "atomic bullet lines",
            prompt,
        )
        self.assertIn(
            "one semantic entity per line",
            prompt,
        )
        self.assertIn(
            "compact semantic label",
            prompt,
        )
        self.assertIn(
            "Keep memory actionable",
            prompt,
        )
        self.assertIn(
            "failures or interruptions",
            prompt,
        )
        self.assertIn(
            "do not treat it as resolved",
            prompt,
        )
        self.assertNotIn(
            "space exploration costs",
            prompt,
        )
        self.assertNotIn(
            "assistant established",
            prompt,
        )
        self.assertNotIn(
            "after one completed user/JIN turn",
            prompt,
        )

    def test_interrupted_assistant_message_marks_incomplete(self):

        message = build_interrupted_assistant_message(
            user_message="Tell me a story.",
            assistant_message="Once upon a",
        )

        self.assertIn(
            "interrupted by the user",
            message,
        )
        self.assertIn(
            "incomplete",
            message,
        )
        self.assertIn(
            "Do not treat this turn as resolved",
            message,
        )
        self.assertIn(
            "Tell me a story.",
            message,
        )
        self.assertIn(
            "Once upon a",
            message,
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
            emitter=SimpleNamespace(
                events=[],
                emit=None,
            ),
            logger=logger,
            runtime_memory="",
            runtime_memory_updates=0,
        )

        async def emit(event):
            context.emitter.events.append(
                event
            )

        context.emitter.emit = emit

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
        self.assertIn(
            "atomic bullet lines",
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
        self.assertEqual(
            context.emitter.events,
            [
                {
                    "type": "runtime_memory_update",
                    "memory": "The user is testing live runtime memory.",
                    "updates": 1,
                },
            ],
        )

    async def test_summarizer_uses_service_max_tokens(self):

        service_client = FakeServiceClient(
            "- Active topic: available functions\n"
            "- Capabilities listed: answering questions and writing text",
        )
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            logger=FakeLogger(),
            runtime_memory="Initial memory.",
            runtime_memory_updates=0,
        )

        updated_memory = await summarize_runtime_memory(
            context=context,
            user_message="What can you do?",
            assistant_message="I can answer questions and write text.",
        )

        self.assertEqual(
            updated_memory,
            (
                "- Active topic: available functions\n"
                "- Capabilities listed: answering questions and writing text"
            ),
        )
        self.assertEqual(
            len(
                service_client.calls
            ),
            1,
        )
        self.assertEqual(
            service_client.calls[0]["max_tokens"],
            config.SERVICE_MAX_TOKENS,
        )

    async def test_summarizer_skips_incomplete_memory(self):

        logger = FakeLogger()
        service_client = FakeServiceClient(
            "- Active topic: available functions\n"
            "- Capabilities listed: answering questions (emails",
        )
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            logger=logger,
            runtime_memory="Initial memory.",
            runtime_memory_updates=0,
        )

        updated_memory = await summarize_runtime_memory(
            context=context,
            user_message="What can you do?",
            assistant_message="I can answer questions.",
        )

        self.assertEqual(
            updated_memory,
            "Initial memory.",
        )
        self.assertEqual(
            context.runtime_memory,
            "Initial memory.",
        )
        self.assertEqual(
            context.runtime_memory_updates,
            0,
        )
        self.assertTrue(
            logger.errors
        )

    async def test_summarizer_failure_logs_traceback_details(self):

        class SilentError(Exception):
            def __str__(self):
                return ""

        logger = FakeLogger()
        service_client = FakeServiceClient(
            SilentError()
        )
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            logger=logger,
            runtime_memory="Initial memory.",
            runtime_memory_updates=0,
        )

        updated_memory = await summarize_runtime_memory(
            context=context,
            user_message="Remember this.",
            assistant_message="I will remember it.",
        )

        self.assertEqual(
            updated_memory,
            "Initial memory.",
        )
        self.assertEqual(
            len(logger.errors),
            1,
        )

        message, details = logger.errors[0]

        self.assertEqual(
            message,
            "[MEMORY] runtime memory update failed",
        )
        self.assertIn(
            "Traceback (most recent call last):",
            details,
        )
        self.assertIn(
            "SilentError",
            details,
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


if __name__ == "__main__":
    unittest.main()
