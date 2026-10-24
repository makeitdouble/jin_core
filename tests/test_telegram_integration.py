import asyncio
import contextlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import websocket as ws

from config_loader import config
from agent.nodes.brain import action_batch_requires_follow_up
from runtime.stream import project_telegram_asset_action_marker
from runtime.runtime_context import RuntimeContext
from utils import attached_files_store as files
from utils.actions import RuntimeActionCall, RuntimeActionStreamFilter
from utils.actions.asset_actions import apply_asset_actions, emit_saved_asset_results
from utils.python_skill_asset_utils import run_context_asset_action
from utils.skills_asset_utils import list_skills, load_skill
from utils.telegram_transport import (
    TELEGRAM_MAX_PHOTOS,
    TelegramPollingService,
    _telegram_api_call,
    start_telegram_polling,
    stop_telegram_polling,
    telegram_send,
)


class TelegramConfigMixin:
    def telegram_config(self, *, enabled=True, token="test-token", chat_id="269678016"):
        stack = contextlib.ExitStack()
        stack.enter_context(patch.object(config, "TELEGRAM_ENABLED", enabled, create=True))
        stack.enter_context(patch.object(config, "TELEGRAM_BOT_TOKEN", token, create=True))
        stack.enter_context(patch.object(config, "TELEGRAM_CHAT_ID", chat_id, create=True))
        return stack


class TelegramAssetActionTests(TelegramConfigMixin, unittest.IsolatedAsyncioTestCase):
    def context(self, loaded=True):
        return RuntimeContext(
            websocket=object(),
            emitter=object(),
            logger=object(),
            clients={},
            runtime_loaded_skills=(
                [load_skill("telegram")["skill"]]
                if loaded
                else []
            ),
        )

    async def test_telegram_skill_is_discoverable(self):
        self.assertIn("telegram", {item["name"] for item in list_skills()["skills"]})
        skill = load_skill("telegram")
        self.assertTrue(skill["ok"])
        self.assertIn('"action":"telegram_send"', skill["skill"]["content"])
        self.assertIn("Never claim", skill["skill"]["content"])
        self.assertIn("<TELEGRAM_MESSAGE_INPUT>", skill["skill"]["content"])

    async def test_telegram_dispatch_does_not_require_skill_loaded(self):
        success = {"ok": True, "action": "telegram_send", "chat_id": "269678016", "message_id": 42}
        with patch("utils.telegram_transport.telegram_send", new=AsyncMock(return_value=success)) as send:
            loaded_result = await run_context_asset_action(
                '{"action":"telegram_send","text":"hello"}',
                context=self.context(loaded=True),
            )
            unloaded_result = await run_context_asset_action(
                '{"action":"telegram_send","text":"hello"}',
                context=self.context(loaded=False),
            )
        self.assertEqual(loaded_result, success)
        self.assertEqual(unloaded_result, success)
        self.assertEqual(send.await_count, 2)

    async def test_send_validation_and_success(self):
        with self.telegram_config(enabled=False):
            self.assertEqual((await telegram_send({"text": "hello"}))["error"], "telegram_not_configured")
        with self.telegram_config(chat_id=""):
            self.assertEqual((await telegram_send({"text": "hello"}))["error"], "telegram_recipient_not_configured")
        with self.telegram_config():
            self.assertEqual((await telegram_send({"text": "  "}))["error"], "telegram_empty_text")
            self.assertEqual((await telegram_send({"text": "x" * 4097}))["error"], "telegram_text_too_long")
            self.assertEqual(
                (await telegram_send({"chat_id": "999", "text": "hello"}))["error"],
                "telegram_chat_not_allowed",
            )
            response = {"ok": True, "result": {"message_id": 42}}
            with patch("utils.telegram_transport._telegram_api_call", new=AsyncMock(return_value=response)) as call:
                result = await telegram_send({"text": "hello"})
            self.assertEqual(result, {
                "ok": True,
                "action": "telegram_send",
                "chat_id": "269678016",
                "message_id": 42,
            })
            call.assert_awaited_once_with(
                "sendMessage",
                {"chat_id": "269678016", "text": "hello"},
            )

    async def test_success_uses_existing_tool_result_event_without_followup(self):
        emitter = SimpleNamespace(events=[])

        async def emit(event):
            emitter.events.append(event)

        emitter.emit = emit
        context = self.context(loaded=True)
        context.emitter = emitter
        context.runtime_current_turn_id = "turn_telegram"
        success = {"ok": True, "action": "telegram_send", "chat_id": "269678016", "message_id": 42}
        action = RuntimeActionCall(
            name="ASSET_ACTION",
            payload='{"action":"telegram_send","text":"hello"}',
        )
        with patch("utils.telegram_transport.telegram_send", new=AsyncMock(return_value=success)):
            results = await apply_asset_actions(
                context,
                [action],
                log_runtime=None,
                with_action_context=lambda event: event,
            )
            await emit_saved_asset_results(
                context,
                results,
                with_action_context=lambda event: event,
            )

        self.assertEqual(results[0]["message_id"], 42)
        self.assertEqual(context.runtime_tool_results[-1]["result"], results[0])
        completed = [
            event for event in emitter.events
            if event.get("type") == "runtime_action" and event.get("status") == "completed"
        ]
        self.assertEqual(len(completed), 1)
        self.assertFalse(action_batch_requires_follow_up(completed, ""))
        self.assertTrue(action_batch_requires_follow_up([{
            "action": "asset_action",
            "status": "failed",
            "asset_result": {
                "ok": False,
                "action": "telegram_send",
                "error": "telegram_timeout",
            },
        }], ""))

    def test_telegram_send_marker_projects_output_in_source_order(self):
        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=("ASSET_ACTION",),
            project_action_marker=project_telegram_asset_action_marker,
        )
        chunks = (
            '<ASSET_ACTION> {"action":"telegram_',
            'send","text":"тест"} </ASSET_ACTION> ',
            'отправил',
        )
        visible = []
        actions = []
        for chunk in chunks:
            result = stream_filter.filter(chunk)
            visible.append(result.text)
            actions.extend(result.actions)
        tail = stream_filter.flush_result()
        visible.append(tail.text)
        actions.extend(tail.actions)

        self.assertEqual("".join(visible), (
            "\uE000<TELEGRAM_MESSAGE_OUTPUT>\n"
            "тест\n"
            "</TELEGRAM_MESSAGE_OUTPUT> отправил"
        ))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].name, "ASSET_ACTION")

    async def test_api_error_and_timeout_do_not_leak_token_or_retry(self):
        token = "secret:token-value"
        request = httpx.Request("POST", f"https://api.telegram.org/bot{token}/sendMessage")
        client = SimpleNamespace(
            post=AsyncMock(side_effect=httpx.ReadTimeout(f"timeout at {request.url}", request=request))
        )
        with self.telegram_config(token=token):
            result = await _telegram_api_call("sendMessage", {"text": "hello"}, client=client)
        self.assertEqual(result["error"], "telegram_timeout")
        self.assertNotIn(token, str(result))
        self.assertEqual(client.post.await_count, 1)

        response = SimpleNamespace(
            status_code=400,
            json=lambda: {"ok": False, "description": "Bad Request"},
        )
        client = SimpleNamespace(post=AsyncMock(return_value=response))
        with self.telegram_config(token=token):
            result = await _telegram_api_call("sendMessage", {}, client=client)
        self.assertEqual(result["error"], "telegram_api_error")
        self.assertEqual(result["detail"], "Bad Request")


class TelegramPollingTests(TelegramConfigMixin, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.stack = contextlib.ExitStack()
        self.addAsyncCleanup(self._cleanup)
        self.temp = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(self.telegram_config())
        for name, path in {
            "FILES_DIR": self.temp / "files",
            "INDEX_FILE": self.temp / "files/.index.json",
            "GITKEEP_FILE": self.temp / "files/.gitkeep",
        }.items():
            self.stack.enter_context(patch.object(files, name, path))
        self.stack.enter_context(patch("utils.telegram_transport.TELEGRAM_RUNTIME_DIR", self.temp / "runtime"))
        self.app_state = SimpleNamespace(websocket_runtime_contexts={})
        self.service = TelegramPollingService(self.app_state)

    async def _cleanup(self):
        await self.service.client.aclose()
        self.service.release_lock()
        self.stack.close()

    @staticmethod
    def context(opened_at, *, anonymous=False, active=True):
        enqueue = AsyncMock(return_value={"ok": True})
        transport = SimpleNamespace(
            stopping=not active,
            socket=object() if active else None,
        )
        return SimpleNamespace(
            runtime_anonymous_mode=anonymous,
            runtime_tab_opened_at=opened_at,
            runtime_transport=transport,
            runtime_external_user_enqueue=enqueue,
        )

    @staticmethod
    def text_message(text="hello", *, chat_id=269678016, sender_id=269678016):
        return {
            "message_id": 1,
            "from": {"id": sender_id},
            "chat": {"id": chat_id, "type": "private"},
            "text": text,
        }

    def test_newest_open_normal_active_tab_wins(self):
        old = self.context(10)
        newest = self.context(30)
        anonymous = self.context(40, anonymous=True)
        closed = self.context(50, active=False)
        self.app_state.websocket_runtime_contexts = {
            "old": old,
            "newest": newest,
            "anonymous": anonymous,
            "closed": closed,
        }
        self.assertIs(self.service._active_context(), newest)

    async def test_per_bot_process_lock_rejects_second_poller(self):
        second = TelegramPollingService(self.app_state)
        try:
            self.assertTrue(self.service.acquire_lock())
            self.assertFalse(second.acquire_lock())
        finally:
            await second.client.aclose()

    async def test_poller_starts_once_and_shutdown_cancels_long_poll(self):
        # This test owns a second app state because asyncSetUp's service has not
        # acquired the process lock.
        app_state = SimpleNamespace(websocket_runtime_contexts={})
        started = asyncio.Event()

        async def blocked_call(*_args, **_kwargs):
            started.set()
            await asyncio.Event().wait()

        with patch("utils.telegram_transport._telegram_api_call", new=blocked_call):
            task = start_telegram_polling(app_state)
            self.assertIsNotNone(task)
            await asyncio.wait_for(started.wait(), 1)
            await stop_telegram_polling(app_state)

        self.assertTrue(task.cancelled())
        self.assertIsNone(app_state.telegram_polling_task)
        self.assertIsNone(app_state.telegram_polling_service)

    async def test_no_active_tab_replies_with_error(self):
        self.app_state.websocket_runtime_contexts = {
            "anonymous": self.context(10, anonymous=True),
        }
        self.service._reply_error = AsyncMock()
        await self.service._handle_messages([self.text_message()])
        self.service._reply_error.assert_awaited_once()

    async def test_unauthorized_private_sender_and_group_are_ignored(self):
        context = self.context(10)
        self.app_state.websocket_runtime_contexts = {"target": context}
        self.service._reply_error = AsyncMock()
        await self.service._handle_messages([self.text_message(sender_id=5)])
        group = self.text_message()
        group["chat"]["type"] = "group"
        await self.service._handle_messages([group])
        context.runtime_external_user_enqueue.assert_not_awaited()
        self.service._reply_error.assert_not_awaited()

    async def test_text_is_one_user_turn(self):
        context = self.context(10)
        self.app_state.websocket_runtime_contexts = {"target": context}
        await self.service._handle_messages([self.text_message("telegram hello")])
        context.runtime_external_user_enqueue.assert_awaited_once_with({
            "type": "message",
            "text": "telegram hello",
            "attachments": [],
            "external_source": "telegram",
        })

    async def test_photo_caption_is_unpinned_single_turn_attachment(self):
        context = self.context(10)
        self.app_state.websocket_runtime_contexts = {"target": context}
        message = self.text_message("")
        message.pop("text")
        message["caption"] = "look"
        message["photo"] = [{"file_id": "f", "file_unique_id": "u"}]
        self.service._download_photo = AsyncMock(return_value=(
            {"name": "telegram_u_1.jpg", "mime_type": "image/jpeg", "width": 10, "height": 20},
            b"\xff\xd8\xffphoto",
        ))
        await self.service._handle_messages([message])
        packet = context.runtime_external_user_enqueue.await_args.args[0]
        self.assertEqual(packet["text"], "look")
        self.assertEqual(len(packet["attachments"]), 1)
        record = files.get_file_record(packet["attachments"][0]["id"])
        self.assertIsNotNone(record)
        self.assertFalse(record["pinned"])
        self.assertEqual(record["kind"], "image")

    async def test_album_over_five_is_rejected_atomically(self):
        context = self.context(10)
        self.app_state.websocket_runtime_contexts = {"target": context}
        self.service._reply_error = AsyncMock()
        album = []
        for index in range(TELEGRAM_MAX_PHOTOS + 1):
            message = self.text_message("")
            message.pop("text")
            message["message_id"] = index
            message["photo"] = [{"file_id": str(index)}]
            album.append(message)
        await self.service._handle_messages(album)
        context.runtime_external_user_enqueue.assert_not_awaited()
        self.service._reply_error.assert_awaited_once()
        self.assertEqual(files.list_file_records(), [])

    async def test_album_updates_buffer_into_one_ordered_turn_and_offset(self):
        handled = AsyncMock()
        self.service._handle_messages = handled
        first = self.text_message("")
        first["media_group_id"] = "album"
        first["photo"] = [{"file_id": "a"}]
        second = self.text_message("")
        second["media_group_id"] = "album"
        second["photo"] = [{"file_id": "b"}]
        self.service._ingest_update({"update_id": 100, "message": first}, 1.0)
        self.service._ingest_update({"update_id": 101, "message": second}, 1.1)
        self.service.pending[0]["deadline"] = 0.0
        await self.service._drain_ready()
        self.assertEqual(len(handled.await_args.args[0]), 2)
        self.assertEqual(self.service._load_offset(), 102)
        self.assertEqual(self.service.confirmed_offset, 102)
        self.assertEqual(self.service.pending, [])


class TelegramRoomAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_external_message_uses_live_fifo_and_emits_file_then_user_projection(self):
        received = asyncio.Queue()
        processed = asyncio.Event()
        process_calls = []
        socket = SimpleNamespace(send_json=AsyncMock(), query_params={})
        logger = SimpleNamespace(**{
            name: AsyncMock()
            for name in ("log", "log_system", "log_runtime", "log_user", "log_error")
        })
        context = RuntimeContext(
            websocket=socket,
            emitter=SimpleNamespace(emit=AsyncMock()),
            logger=logger,
            clients={},
            session_id="telegram-room",
        )
        context.runtime_transport = SimpleNamespace(stopping=False, socket=object())

        async def process(_context, packet):
            process_calls.append(packet)
            processed.set()

        with contextlib.ExitStack() as stack:
            for name in (
                "initialize_connection",
                "refresh_pending_brain_usage",
                "apply_runtime_response_feedback",
                "cancel_lt_memory_idle_update",
                "preempt_update_lt_facts_actions",
                "wait_for_runtime_memory_update",
            ):
                stack.enter_context(patch.object(ws, name, new=AsyncMock()))
            stack.enter_context(patch.object(ws, "receive_message", new=lambda _context: received.get()))
            stack.enter_context(patch.object(ws, "process_message", new=process))
            stack.enter_context(patch.object(ws, "reject_when_all_models_offline", new=AsyncMock(return_value=False)))
            stack.enter_context(patch.object(ws, "hydrate_attachment_ids", return_value=[{
                "id": "abc123", "name": "telegram.jpg", "kind": "image",
                "type": "image/jpeg", "data_url": "data:image/jpeg;base64,secret",
            }]))
            stack.enter_context(patch.object(ws, "public_file_snapshot", return_value={
                "files": [{"id": "abc123", "name": "telegram.jpg"}],
                "pinned_ids": [],
                "max_attached_files": 5,
            }))
            task = asyncio.create_task(ws.run_runtime_session(socket, context, False))
            try:
                for _ in range(100):
                    if callable(context.runtime_external_user_enqueue):
                        break
                    await asyncio.sleep(0)
                result = await context.runtime_external_user_enqueue({
                    "type": "message",
                    "text": "from telegram",
                    "attachments": [{"id": "abc123"}],
                    "external_source": "telegram",
                })
                self.assertTrue(result["ok"])
                await asyncio.wait_for(processed.wait(), 1)
                wrapped = (
                    "<TELEGRAM_MESSAGE_INPUT>\n"
                    "from telegram\n"
                    "</TELEGRAM_MESSAGE_INPUT>"
                )
                self.assertEqual(process_calls[0]["text"], wrapped)
                self.assertEqual(
                    [skill["name"] for skill in context.runtime_loaded_skills],
                    ["telegram"],
                )
                event_types = [call.args[0]["type"] for call in socket.send_json.await_args_list]
                self.assertLess(
                    event_types.index("attached_files_update"),
                    event_types.index("external_user_message"),
                )
                external = next(
                    call.args[0]
                    for call in socket.send_json.await_args_list
                    if call.args[0]["type"] == "external_user_message"
                )
                self.assertEqual(external["text"], wrapped)
                self.assertEqual(external["attachments"][0]["id"], "abc123")
                self.assertNotIn("data_url", external["attachments"][0])
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self.assertIsNone(context.runtime_external_user_enqueue)

    async def test_external_telegram_message_does_not_duplicate_loaded_skill(self):
        context = RuntimeContext(
            websocket=object(),
            emitter=object(),
            logger=object(),
            clients={},
            runtime_loaded_skills=[load_skill("telegram")["skill"]],
        )
        packet = ws.prepare_external_user_message(context, {
            "type": "message",
            "text": "проверка из телеги",
            "external_source": "telegram",
        })
        self.assertEqual(packet["text"], (
            "<TELEGRAM_MESSAGE_INPUT>\n"
            "проверка из телеги\n"
            "</TELEGRAM_MESSAGE_INPUT>"
        ))
        self.assertEqual(
            [skill["name"] for skill in context.runtime_loaded_skills],
            ["telegram"],
        )


class TelegramUIContractTests(unittest.TestCase):
    def test_external_user_event_reuses_normal_attachment_bubble(self):
        source = Path("ui/static/js/socket/event-handlers.js").read_text(encoding="utf-8")
        self.assertIn('"external_user_message"', source)
        self.assertIn('appendChatMessage(\n    "user",', source)
        self.assertIn("attachments", source)


if __name__ == "__main__":
    unittest.main()
