import unittest
import asyncio
import contextlib
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime import (
    RuntimeStream,
    runtime_state,
)
from app_settings import (
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

    async def log_validator(
        self,
        message,
        **kwargs,
    ):

        self.messages.append(
            (
                "validator",
                message,
                kwargs,
            )
        )

    async def log_error(
        self,
        message,
        **kwargs,
    ):

        self.messages.append(
            (
                "error",
                message,
                kwargs,
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


class FakeActiveStream:

    def __init__(self):

        self.closed = False

    async def aclose(self):

        self.closed = True


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


async def fake_sentence_loop_generator():

    repeated = (
        "* Wait, I'll check if I should use "
        "`append_skill` first. Yes.\n"
    )

    for _ in range(6):
        yield {
            "type": "content",
            "content": repeated,
        }


async def fake_thinking_sentence_loop_generator():

    repeated = (
        "*Wait*, I'll check if I can use "
        "`write_file` as a skill.\n"
    )

    for _ in range(6):
        yield {
            "type": "thinking",
            "content": repeated,
        }


async def fake_prompt_only_usage_generator():

    yield {
        "type": "usage",
        "prompt_tokens": 1,
        "completion_tokens": 0,
        "total_tokens": 0,
    }

    yield {
        "type": "content",
        "content": "final answer",
    }


async def fake_raw_asset_action_generator():

    yield {
        "type": "content",
        "content": (
            "<INTERNAL_ACTION_ASSET_ACTION>\n"
            '{"action":"create_wildcard_file","args":{"path":"clothing/test_tops","content":"silk camisole\\ncrochet halter top"}}\n'
            "</INTERNAL_ACTION_ASSET_ACTION>\n"
            "Создал wildcard файл."
        ),
    }


class RuntimeStreamTokenTests(unittest.IsolatedAsyncioTestCase):

    def patch_asset_roots(self, root: Path):
        assets_root = root / "assets"
        return (
            patch("utils.assets_service.PROJECT_ROOT", root),
            patch("utils.assets_service.ASSETS_ROOT", assets_root),
            patch("utils.assets_service.SKILLS_ROOT", assets_root / "skills"),
            patch("utils.assets_service.WILDCARDS_ROOT", assets_root / "wildcards"),
            patch("utils.assets_service.PROMPTS_ROOT", assets_root / "prompts"),
            patch("utils.assets_service.TEMPLATES_ROOT", assets_root / "templates"),
            patch("utils.assets_service.OUTPUTS_ROOT", assets_root / "outputs"),
        )

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
                context_tokens=original_state["context_tokens"],
                total_tokens=original_state["total_tokens"],
                max_tokens=original_state["max_tokens"],
                last_error=original_state["last_error"],
                status=original_state["status"],
            )

    async def test_runtime_counter_keeps_estimated_total_when_provider_usage_has_no_total(self):

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
                fake_prompt_only_usage_generator()
            )

            service_state = runtime_state.get_runtime_state(
                runtime_id
            )

            self.assertGreater(
                service_state["used_tokens"],
                service_state["context_tokens"],
            )
            self.assertEqual(
                service_state["total_tokens"],
                service_state["used_tokens"],
            )

        finally:
            runtime_state.update_runtime_state(
                runtime_id=runtime_id,
                used_tokens=original_state["used_tokens"],
                context_tokens=original_state["context_tokens"],
                total_tokens=original_state["total_tokens"],
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

    async def test_sentence_loop_content_is_preserved_without_interrupt(self):

        runtime_id = settings.SERVICE_MODEL_UID
        active_stream = FakeActiveStream()
        context = SimpleNamespace(
            websocket=FakeWebSocket(),
            logger=FakeLogger(),
            emitter=FakeEmitter(),
            active_streams={
                1: active_stream,
            },
            runtime_action_events=[],
            runtime_usage_events=[],
            runtime_turn_assistant_response="",
            runtime_turn_interrupted=False,
            runtime_turn_interruption_reason="",
            runtime_turn_interruption_quote="",
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
            fake_sentence_loop_generator()
        )

        self.assertIsNotNone(
            result
        )
        self.assertIn(
            "append_skill",
            result,
        )
        self.assertFalse(
            context.runtime_turn_interrupted
        )
        self.assertEqual(
            context.runtime_turn_interruption_reason,
            "",
        )
        self.assertEqual(
            context.active_streams,
            {
                1: active_stream,
            },
        )
        self.assertFalse(
            active_stream.closed
        )

        errors = [
            message
            for message in context.websocket.messages
            if message.get("type") == "message_error"
        ]

        self.assertEqual(
            len(errors),
            0,
        )

    async def test_thinking_sentence_loop_is_preserved_without_interrupt(self):

        runtime_id = settings.SERVICE_MODEL_UID
        active_stream = FakeActiveStream()
        context = SimpleNamespace(
            websocket=FakeWebSocket(),
            logger=FakeLogger(),
            emitter=FakeEmitter(),
            active_streams={
                1: active_stream,
            },
            runtime_action_events=[],
            runtime_usage_events=[],
            runtime_turn_assistant_response="",
            runtime_turn_interrupted=False,
            runtime_turn_interruption_reason="",
            runtime_turn_interruption_quote="",
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
            fake_thinking_sentence_loop_generator()
        )

        self.assertEqual(
            result,
            "",
        )
        self.assertFalse(
            context.runtime_turn_interrupted
        )
        self.assertEqual(
            context.runtime_turn_interruption_reason,
            "",
        )
        self.assertEqual(
            context.active_streams,
            {
                1: active_stream,
            },
        )
        self.assertFalse(
            active_stream.closed
        )

        thinking_chunks = [
            message
            for message in context.websocket.messages
            if message.get("type") == "thinking_chunk"
        ]
        self.assertGreaterEqual(
            len(thinking_chunks),
            1,
        )

        errors = [
            message
            for message in context.websocket.messages
            if message.get("type") == "message_error"
        ]

        self.assertEqual(
            len(errors),
            0,
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

    async def test_runtime_stream_filters_raw_asset_action_before_emit(self):

        runtime_id = settings.SERVICE_MODEL_UID

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                context = SimpleNamespace(
                    websocket=FakeWebSocket(),
                    logger=FakeLogger(),
                    emitter=FakeEmitter(),
                    runtime_action_events=[],
                    runtime_usage_events=[],
                    runtime_asset_results=[],
                    active_memory_records=[],
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
                    runtime_actions={
                        "CAN_USE_ASSETS": True,
                    },
                )

                await stream.run(
                    fake_raw_asset_action_generator()
                )

                emitted_text = "\n".join(
                    str(message.get("chunk", ""))
                    for message in context.websocket.messages
                    if message.get("type") == "message_chunk"
                )

                self.assertNotIn(
                    "INTERNAL_ACTION_ASSET_ACTION",
                    emitted_text,
                )
                self.assertIn(
                    "Создал wildcard файл.",
                    emitted_text,
                )
                self.assertEqual(
                    context.runtime_action_events[0]["name"],
                    "asset_action",
                )
                self.assertTrue(
                    (
                        root
                        / "assets"
                        / "wildcards"
                        / "clothing"
                        / "test_tops.txt"
                    ).exists()
                )

    async def test_asset_action_started_emits_when_opening_tag_is_stripped(self):

        runtime_id = settings.SERVICE_MODEL_UID

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_path = (
                root
                / "assets"
                / "outputs"
                / "rain_simulator.py"
            )

            class TrackingEmitter:

                def __init__(self):

                    self.events = []

                async def emit(
                    self,
                    event,
                ):

                    self.events.append({
                        **event,
                        "file_exists_at_emit": output_path.exists(),
                    })

            async def split_asset_action_generator():

                yield {
                    "type": "content",
                    "content": "<INTERNAL_ACTION_ASSET_ACTION>\n",
                }
                yield {
                    "type": "content",
                    "content": (
                        '{"action":"create_asset_file",'
                        '"path":"assets/outputs/rain_simulator.py",'
                        '"content":"print(\\\"rain\\\")"}\n'
                    ),
                }
                yield {
                    "type": "content",
                    "content": (
                        "</INTERNAL_ACTION_ASSET_ACTION>\n"
                        "Done."
                    ),
                }

            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                context = SimpleNamespace(
                    websocket=FakeWebSocket(),
                    logger=FakeLogger(),
                    emitter=TrackingEmitter(),
                    runtime_action_events=[],
                    runtime_usage_events=[],
                    runtime_asset_results=[],
                    active_memory_records=[],
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
                    runtime_actions={
                        "CAN_USE_ASSETS": True,
                    },
                )

                await stream.run(
                    split_asset_action_generator()
                )

                runtime_events = [
                    event
                    for event in context.emitter.events
                    if event.get("type") == "runtime_action"
                ]

                self.assertEqual(
                    [
                        event.get("status")
                        for event in runtime_events
                    ],
                    [
                        "started",
                        "started",
                        "completed",
                    ],
                )
                self.assertEqual(
                    len({
                        event.get("id")
                        for event in runtime_events
                    }),
                    1,
                )
                self.assertEqual(
                    runtime_events[0]["text"],
                    "Processed asset action",
                )
                self.assertFalse(
                    runtime_events[0]["file_exists_at_emit"],
                )
                self.assertEqual(
                    runtime_events[1]["text"],
                    "Created asset file - assets/outputs/rain_simulator.py",
                )
                self.assertTrue(
                    runtime_events[2]["file_exists_at_emit"],
                )
                self.assertTrue(
                    output_path.exists(),
                )


if __name__ == "__main__":
    unittest.main()
