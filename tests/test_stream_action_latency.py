import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from clients.brain_client import ask_brain_stream
from utils.stream_action_queue import StreamActionQueue
from utils.stream_handler import StreamHandler
from utils.actions import RuntimeActionStreamFilter


class StreamActionLatencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_outer_runtime_emits_before_action_completion(self):
        from runtime.stream import RuntimeStream
        from tests.test_runtime_stream_tokens import FakeEmitter, FakeLogger, FakeWebSocket

        started, release, visible = asyncio.Event(), asyncio.Event(), asyncio.Event()
        context = SimpleNamespace(
            websocket=FakeWebSocket(), emitter=FakeEmitter(), logger=FakeLogger(),
            runtime_action_events=[], runtime_session_action_history=[],
            runtime_current_turn_id="latency", runtime_current_sequence_turn_id="latency",
            runtime_session_id="latency", runtime_turn_user_message="test",
        )
        original_send = context.websocket.send_json

        async def send(event):
            await original_send(event)
            if event.get("type") == "message_chunk":
                visible.set()

        context.websocket.send_json = send
        runtime = RuntimeStream(
            context=context, runtime_id="brain", role="brain", context_window=8192,
            log_method=context.logger.log_service, runtime_actions=["LOAD_SKILL"],
        )

        async def apply(*args, **kwargs):
            started.set()
            await release.wait()

        async def chunks():
            yield {"type": "content", "content": "<LOAD_SKILLS_CONTEXT> blender_mcp </LOAD_SKILLS_CONTEXT>"}
            await started.wait()
            yield {"type": "content", "content": "Hello"}
            yield {"type": "content", "content": " world!"}

        with patch("utils.brain_client_utils.apply_runtime_action_calls", apply):
            task = asyncio.create_task(runtime.run(chunks()))
            try:
                await asyncio.wait_for(visible.wait(), 2)
                self.assertFalse(any(e["type"] == "message_end" for e in context.websocket.messages))
                release.set()
                self.assertEqual(await asyncio.wait_for(task, 2), "Hello world!")
                self.assertTrue(any(e["type"] == "message_end" for e in context.websocket.messages))
            finally:
                release.set()
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_every_paired_action_releases_text_without_flush(self):
        from tests.test_unclosed_runtime_actions import PAYLOADS
        from contracts.rules_assembler import get_close_tag_runtime_actions, get_runtime_action_private_marker

        payloads = dict(PAYLOADS, WEB_SEARCH="test query", LOAD_SKILL="blender_mcp",
                        UNLOAD_SKILL="blender_mcp", RECALL_FACT_CONTEXT="F1",
                        ATTACH_FILE_BY_ID="file1", LOAD_DELAYED_MEMORY="D1",
                        DELETE_ACTIVE_MEMORY="abc123")
        for name in get_close_tag_runtime_actions():
            marker_name = get_runtime_action_private_marker(name).strip("<> ")
            marker = f"<{marker_name}>{payloads[name]}</{marker_name}>"
            for split in range(len(marker) + 1):
                with self.subTest(name=name, split=split):
                    parser = RuntimeActionStreamFilter(enabled_actions=[name])
                    parser.filter(marker[:split])
                    parser.filter(marker[split:])
                    self.assertIn("Hello", parser.filter("Hello").text)
                    self.assertEqual(parser.filter(" world!").text, " world!")

    async def test_text_reaches_websocket_while_action_is_waiting(self):
        for marker, flags in (
            ("<LOAD_SKILLS_CONTEXT> blender_mcp </LOAD_SKILLS_CONTEXT>",
             {"CAN_USE_ASSETS": True}),
            ('<SAVE_ACTIVE_MEMORY>{"conditions":"test"}</SAVE_ACTIVE_MEMORY>',
             {"CAN_SAVE_ACTIVE_MEMORY": True}),
            ("<JIN_COLOR> #ff00ff </JIN_COLOR>", {"CAN_JIN_COLOR": True}),
        ):
            with self.subTest(marker=marker):
                started = asyncio.Event()
                release = asyncio.Event()
                visible = asyncio.Event()
                events = []

                async def apply(*args, **kwargs):
                    started.set()
                    await release.wait()

                async def send(event):
                    events.append(event)
                    if event.get("type") == "message_chunk":
                        visible.set()

                class Client:
                    async def stream(self, **kwargs):
                        for char in marker:
                            yield {"type": "content", "content": char}
                        await started.wait()
                        for text in ("\n\n", "Hello", " world", "!"):
                            yield {"type": "content", "content": text}

                handler = StreamHandler(
                    SimpleNamespace(send_json=send), SimpleNamespace(),
                    role="brain", enable_validator=True,
                )

                async def consume():
                    async for chunk in ask_brain_stream(
                        client=Client(), text="test", context=SimpleNamespace(),
                        system_prompt="test", brain_payload="test",
                        context_window_prepared=True, runtime_actions=flags,
                    ):
                        if chunk["type"] == "content":
                            await handler.send_content(chunk["content"])

                with patch("clients.brain_client.apply_runtime_action_calls", apply):
                    task = asyncio.create_task(consume())
                    try:
                        await asyncio.wait_for(visible.wait(), 2)
                        self.assertFalse(task.done(), "completion must wait for actions")
                        self.assertIn("Hello", handler.response)
                        self.assertNotIn("<", handler.response)
                        release.set()
                        await asyncio.wait_for(task, 2)
                        self.assertEqual(handler.response.strip(), "Hello world!")
                    finally:
                        release.set()
                        if not task.done():
                            task.cancel()
                        await asyncio.gather(task, return_exceptions=True)

    async def test_queue_preserves_order_and_drains(self):
        queue = StreamActionQueue()
        release = asyncio.Event()
        order = []

        async def first():
            order.append("first start")
            await release.wait()
            order.append("first end")

        async def second():
            order.append("second")

        queue.submit(first)
        queue.submit(second)
        await asyncio.sleep(0)
        self.assertEqual(order, ["first start"])
        release.set()
        await queue.drain()
        self.assertEqual(order, ["first start", "first end", "second"])
        await queue.close()

    async def test_closing_brain_generator_cancels_its_pending_action(self):
        cancelled = asyncio.Event()

        async def apply(*args, **kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        class Client:
            async def stream(self, **kwargs):
                yield {"type": "content", "content": "<LOAD_SKILLS_CONTEXT> blender_mcp </LOAD_SKILLS_CONTEXT>"}
                yield {"type": "content", "content": "Hello"}

        with patch("clients.brain_client.apply_runtime_action_calls", apply):
            generator = ask_brain_stream(
                client=Client(), text="test", context=SimpleNamespace(),
                system_prompt="test", brain_payload="test", context_window_prepared=True,
                runtime_actions={"CAN_USE_ASSETS": True},
            )
            try:
                chunk = await asyncio.wait_for(anext(generator), 2)
                self.assertEqual(chunk["content"], "Hello")
            finally:
                await generator.aclose()
            self.assertTrue(cancelled.is_set())

    async def test_close_cancels_running_and_queued_actions(self):
        queue = StreamActionQueue()
        cancelled = asyncio.Event()

        async def first():
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        second = AsyncMock()
        queue.submit(first)
        queue.submit(second)
        await asyncio.sleep(0)
        await queue.close()
        self.assertTrue(cancelled.is_set())
        second.assert_not_called()

    async def test_failure_prevents_later_actions_and_is_propagated(self):
        queue = StreamActionQueue()

        async def fail():
            raise ValueError("failed action")

        second = AsyncMock()
        queue.submit(fail)
        queue.submit(second)
        with self.assertRaisesRegex(ValueError, "failed action"):
            await queue.drain()
        second.assert_not_called()
        await queue.close()
