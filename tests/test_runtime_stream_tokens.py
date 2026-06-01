import unittest
import asyncio
from types import SimpleNamespace

from runtime.runtime_registry import (
    runtime_state,
)
from runtime.runtime_stream import (
    RuntimeStream,
)
from settings.app_settings import (
    settings,
)


class FakeEmitter:

    def __init__(self):

        self.events = []

    async def emit(
        self,
        event,
    ):

        self.events.append(
            event
        )


class FakeLogger:

    def __init__(self):

        self.messages = []

    async def log_runtime(
        self,
        message,
    ):

        self.messages.append(
            (
                "runtime",
                message,
            )
        )

    async def log_service(
        self,
        message,
    ):

        self.messages.append(
            (
                "service",
                message,
            )
        )


class FakeWebSocket:

    def __init__(self):

        self.messages = []

    async def send_json(
        self,
        message,
    ):

        self.messages.append(
            message
        )


async def fake_generator():

    yield {
        "type": "usage",
        "prompt_tokens": 12,
        "completion_tokens": 30,
        "total_tokens": 42,
    }

    yield {
        "type": "thinking",
        "content": "think now",
    }

    yield {
        "type": "content",
        "content": "final answer",
    }

    yield {
        "type": "content",
        "content": " more words",
    }


async def fake_cancelled_generator():

    yield {
        "type": "content",
        "content": "partial answer",
    }

    raise asyncio.CancelledError()


class RuntimeStreamTokenTests(unittest.IsolatedAsyncioTestCase):

    async def test_runtime_context_counter_grows_during_stream(self):

        runtime_id = settings.SERVICE_MODEL_UID
        original_state = runtime_state.get_runtime_state(
            runtime_id
        )

        context = SimpleNamespace(
            websocket=FakeWebSocket(),
            logger=FakeLogger(),
            emitter=FakeEmitter(),
            runtime_action_events=[],
        )

        stream = RuntimeStream(
            context=context,
            runtime_id=runtime_id,
            role="service",
            context_window=(
                settings.SERVICE_CONTEXT_WINDOW
            ),
            log_method=(
                context.logger.log_service
            ),
            context_snapshot={
                "context_role": "brain",
                "system_prompt": "system prompt",
                "user_prompt": "user payload",
            },
        )

        try:
            await stream.run(
                fake_generator()
            )

            service_state = runtime_state.get_runtime_state(
                runtime_id
            )

            self.assertEqual(
                service_state["used_tokens"],
                42,
            )
            self.assertEqual(
                service_state["context_tokens"],
                12,
            )
            self.assertEqual(
                service_state["total_tokens"],
                42,
            )

            telemetry_counts = [
                event["runtime"][runtime_id]["used_tokens"]
                for event in context.emitter.events
                if event.get("type") == "telemetry"
            ]
            self.assertEqual(
                telemetry_counts[:4],
                [
                    4,
                    6,
                    8,
                    10,
                ],
            )

            self.assertEqual(
                telemetry_counts[-1],
                42,
            )

        finally:
            runtime_state.update_runtime_state(
                runtime_id=runtime_id,
                used_tokens=original_state["used_tokens"],
                max_tokens=original_state["max_tokens"],
                last_error=original_state["last_error"],
                status=original_state["status"],
            )

    async def test_cancelled_brain_stream_captures_partial_response(self):

        runtime_id = settings.SERVICE_MODEL_UID
        context = SimpleNamespace(
            websocket=FakeWebSocket(),
            logger=FakeLogger(),
            emitter=FakeEmitter(),
            runtime_action_events=[],
            runtime_usage_events=[],
            runtime_turn_assistant_response="",
            runtime_turn_interrupted=False,
        )

        stream = RuntimeStream(
            context=context,
            runtime_id=runtime_id,
            role="service",
            context_window=(
                settings.SERVICE_CONTEXT_WINDOW
            ),
            log_method=(
                context.logger.log_service
            ),
            context_snapshot={
                "context_role": "brain",
                "system_prompt": "system prompt",
                "user_prompt": "user payload",
            },
        )

        result = await stream.run(
            fake_cancelled_generator()
        )

        self.assertIsNone(
            result
        )
        self.assertTrue(
            context.runtime_turn_interrupted
        )
        self.assertEqual(
            context.runtime_turn_assistant_response,
            "partial answer",
        )

    async def test_non_brain_stream_does_not_update_context_counter(self):

        runtime_id = settings.SERVICE_MODEL_UID
        original_state = runtime_state.get_runtime_state(
            runtime_id
        )

        context = SimpleNamespace(
            websocket=FakeWebSocket(),
            logger=FakeLogger(),
            emitter=FakeEmitter(),
            runtime_action_events=[],
            runtime_usage_events=[],
        )

        stream = RuntimeStream(
            context=context,
            runtime_id=runtime_id,
            role="service",
            context_window=(
                settings.SERVICE_CONTEXT_WINDOW
            ),
            log_method=(
                context.logger.log_service
            ),
            context_snapshot=None,
        )

        try:
            await stream.run(
                fake_generator()
            )

            service_state = runtime_state.get_runtime_state(
                runtime_id
            )

            self.assertEqual(
                service_state["used_tokens"],
                original_state["used_tokens"],
            )

            self.assertEqual(
                context.emitter.events,
                [],
            )

            self.assertEqual(
                context.runtime_usage_events,
                [
                    {
                        "runtime_id": runtime_id,
                        "role": "service",
                        "kind": "service",
                        "prompt_tokens": 12,
                        "completion_tokens": 30,
                        "total_tokens": 42,
                        "context_tokens": 6,
                    },
                ],
            )

        finally:
            runtime_state.update_runtime_state(
                runtime_id=runtime_id,
                used_tokens=original_state["used_tokens"],
                max_tokens=original_state["max_tokens"],
                last_error=original_state["last_error"],
                status=original_state["status"],
            )


if __name__ == "__main__":
    unittest.main()
