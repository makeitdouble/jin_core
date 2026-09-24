import asyncio
import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent.nodes.brain import action_event_requires_follow_up
from clients.brain_client import get_response_enabled_runtime_actions
from contracts.rules_assembler import (
    build_runtime_action_instructions,
    get_enabled_runtime_actions,
)
from runtime.anonymous_mode import runtime_action_write_is_restricted
from runtime.stream import RuntimeStream
from rules.brain_context_builder import BRAIN_RUNTIME_ACTIONS
from utils.actions import RuntimeActionCall, extract_runtime_actions
from utils.actions.dispatcher import apply_runtime_action_calls
from utils.context.tool_results import build_tool_results_context
from utils.posting_board_client import execute_posting_board_request
from utils.session_actions_history import format_session_action_marker_names


ROOT = Path(__file__).resolve().parents[1]
CHAT_RUNTIME_ACTIONS_JS = ROOT / "ui" / "static" / "js" / "chat-runtime-actions.js"
SOCKET_RUNTIME_ACTIONS_JS = ROOT / "ui" / "static" / "js" / "socket" / "runtime-actions.js"
LOGGER_JS = ROOT / "ui" / "static" / "js" / "logger" / "log-entries.js"
TRACE_MODAL_JS = ROOT / "ui" / "static" / "js" / "logger" / "trace-modal.js"


class FakeEmitter:
    def __init__(self):
        self.events = []

    async def emit(self, event):
        self.events.append(event)


class FakeLogger:
    def __init__(self):
        self.lines = []

    async def log_runtime(self, line):
        self.lines.append(line)


class PostingBoardTests(unittest.IsolatedAsyncioTestCase):
    def test_block_parser_preserves_posting_board_json_payload(self):
        source = (
            '<POSTING_BOARD>\n'
            '{"action":"feed","limit":30}\n'
            '</POSTING_BOARD>'
        )

        parsed = extract_runtime_actions(
            source,
            enabled_actions=("POSTING_BOARD",),
        )

        self.assertEqual(parsed.text, "")
        self.assertEqual(len(parsed.actions), 1)
        self.assertEqual(parsed.actions[0].name, "POSTING_BOARD")
        self.assertEqual(
            parsed.actions[0].payload,
            '{"action":"feed","limit":30}',
        )

    def test_inline_posting_board_payload_is_accepted_as_compatibility_fallback(self):
        source = (
            '<POSTING_BOARD: {"action":"read","source":"named",'
            '"root_id":"74184b96-95ca-4ba0-ba14-6db104400132"} >'
        )

        parsed = extract_runtime_actions(
            source,
            enabled_actions=("POSTING_BOARD",),
        )

        self.assertEqual(parsed.text, "")
        self.assertEqual(len(parsed.actions), 1)
        self.assertEqual(parsed.actions[0].name, "POSTING_BOARD")
        self.assertEqual(
            parsed.actions[0].payload,
            '{"action":"read","source":"named",'
            '"root_id":"74184b96-95ca-4ba0-ba14-6db104400132"}',
        )

    def test_stream_reuses_posting_board_display_id_until_terminal_event(self):
        context = SimpleNamespace(
            websocket=SimpleNamespace(),
            logger=SimpleNamespace(),
            runtime_loaded_skills=[],
            runtime_posting_board_action_sequence=0,
        )
        stream = RuntimeStream(
            context=context,
            runtime_id="posting-board-id-test",
            role="brain",
            context_window=4096,
            log_method=lambda *_args, **_kwargs: None,
            runtime_actions={},
            filter_runtime_actions=False,
        )
        action = RuntimeActionCall(
            name="POSTING_BOARD",
            payload='{"action":"feed","limit":5}',
        )

        opening_id = stream.get_runtime_action_display_id(action)
        execution_id = stream.get_runtime_action_display_id(action)

        self.assertTrue(opening_id)
        self.assertEqual(opening_id, execution_id)
        self.assertEqual(context.runtime_posting_board_action_sequence, 1)

        second_action = RuntimeActionCall(
            name="POSTING_BOARD",
            payload='{"action":"inbox"}',
        )
        second_id = stream.get_runtime_action_display_id(second_action)
        self.assertNotEqual(opening_id, second_id)
        self.assertEqual(context.runtime_posting_board_action_sequence, 2)

    def test_action_is_skill_gated_for_prompt_and_parser(self):
        enabled = get_enabled_runtime_actions(BRAIN_RUNTIME_ACTIONS)
        self.assertIn("POSTING_BOARD", enabled)

        without_skill = SimpleNamespace(runtime_loaded_skills=[])
        with_skill = SimpleNamespace(
            runtime_loaded_skills=[{"name": "posting_board"}],
        )

        self.assertNotIn(
            "POSTING_BOARD",
            get_response_enabled_runtime_actions(
                BRAIN_RUNTIME_ACTIONS,
                context=without_skill,
            ),
        )
        self.assertIn(
            "POSTING_BOARD",
            get_response_enabled_runtime_actions(
                BRAIN_RUNTIME_ACTIONS,
                context=with_skill,
            ),
        )

        self.assertNotIn(
            "<POSTING_BOARD>",
            build_runtime_action_instructions(
                ("POSTING_BOARD",),
                context=without_skill,
            ),
        )
        instructions = build_runtime_action_instructions(
            ("POSTING_BOARD",),
            context=with_skill,
        )
        self.assertIn("<POSTING_BOARD>", instructions)
        self.assertIn("feed|inbox|read|search|post|reply|ack|delete", instructions)
        self.assertTrue(
            action_event_requires_follow_up({
                "name": "posting_board",
                "status": "completed",
            })
        )
        self.assertTrue(
            action_event_requires_follow_up({
                "name": "posting_board",
                "status": "failed",
            })
        )

    def test_search_action_uses_one_canonical_display_form(self):
        payload = '{"action":"search","query":"Meatproxy"}'

        from utils.actions.posting_board_actions import (
            build_posting_board_display_text,
        )

        self.assertEqual(
            build_posting_board_display_text(payload),
            "POSTING_BOARD: action:search | query: Meatproxy",
        )
        self.assertEqual(
            format_session_action_marker_names([{
                "name": "POSTING_BOARD",
                "payload": payload,
                "payloads": [payload],
                "raw_payloads": [payload],
                "status": "completed",
            }]),
            "POSTING_BOARD: action:search | query: Meatproxy",
        )

    async def test_dispatcher_emits_running_then_terminal_and_records_tool_result(self):
        context = SimpleNamespace(
            emitter=FakeEmitter(),
            logger=FakeLogger(),
            runtime_current_turn_id="turn-1",
            runtime_loaded_skills=[{"name": "posting_board"}],
        )
        action = RuntimeActionCall(
            name="POSTING_BOARD",
            payload='{"action":"feed","limit":5}',
        )
        board_result = {
            "ok": True,
            "runtime_action_name": "POSTING_BOARD",
            "action": "feed",
            "status_code": 200,
            "request": {
                "method": "GET",
                "path": "/v1/feed",
                "headers": {
                    "Accept": "application/json",
                    "X-Agent-Protocol": "getpostingboard/1",
                },
                "query": {"limit": 5},
            },
            "response": {
                "items": [{"title": "A public thread"}],
                "action_templates": {
                    "reply": {
                        "method": "POST",
                        "url": "/v1/posts/{thread_id}/replies",
                        "mcp": "reply_to_thread",
                        "required_fields": ["body", "request_id"],
                    },
                },
            },
        }

        with (
            patch(
                "utils.actions.posting_board_actions.execute_posting_board_request",
                return_value=board_result,
            ),
            patch("utils.actions.dispatcher.ensure_assets_tree"),
        ):
            applied = await apply_runtime_action_calls(
                context,
                [action],
                runtime_message_id="message-1",
            )

        self.assertEqual(applied, 1)
        events = [
            event
            for event in context.emitter.events
            if event.get("action") == "posting_board"
        ]
        self.assertEqual([event["status"] for event in events], ["running", "completed"])
        self.assertEqual(events[0]["id"], events[1]["id"])
        self.assertEqual(events[0]["text"], "POSTING_BOARD")
        self.assertEqual(events[1]["text"], "POSTING_BOARD: action:feed | limit: 5")
        self.assertNotIn("posting_board_result", events[0])
        self.assertEqual(events[1]["posting_board_result"]["response"], board_result["response"])
        self.assertIn(
            "action_templates",
            events[1]["posting_board_result"]["response"],
        )

        self.assertEqual(context.runtime_action_events[0]["status"], "completed")
        self.assertEqual(context.runtime_action_events[0]["tool_id"], "T1")
        self.assertEqual(context.runtime_tool_results[0]["kind"], "runtime_action")
        self.assertEqual(
            context.runtime_tool_results[0]["result"]["runtime_action_name"],
            "POSTING_BOARD",
        )
        self.assertIn(
            "action_templates",
            context.runtime_tool_results[0]["result"]["response"],
        )
        self.assertEqual(
            context.logger.lines,
            ["[RUNTIME ACTION] POSTING_BOARD: action:feed | limit: 5 success"],
        )

        tool_context = build_tool_results_context(context)
        self.assertIn('name="POSTING_BOARD"', tool_context)
        self.assertIn("POSTING_BOARD: action:feed | limit: 5", tool_context)
        self.assertIn("A public thread", tool_context)
        self.assertNotIn("Authorization", tool_context)
        self.assertNotIn("action_templates", tool_context)
        self.assertNotIn("request_id", tool_context)
        self.assertNotIn("reply_to_thread", tool_context)

    async def test_failed_action_is_terminal_and_followup_readable(self):
        context = SimpleNamespace(
            emitter=FakeEmitter(),
            logger=FakeLogger(),
            runtime_current_turn_id="turn-1",
            runtime_loaded_skills=[{"name": "posting_board"}],
        )
        action = RuntimeActionCall(
            name="POSTING_BOARD",
            payload='{"action":"post","title":"x","body":"y"}',
        )
        board_result = {
            "ok": False,
            "runtime_action_name": "POSTING_BOARD",
            "action": "post",
            "status_code": 429,
            "error": "posting_board_http_error",
            "detail": "rate limited",
            "retry_after": "30",
            "request": {
                "method": "POST",
                "path": "/v1/posts",
                "body": {"topic": "general", "title": "x", "body": "y"},
            },
            "response": {"error": {"message": "rate limited"}},
        }

        with (
            patch(
                "utils.actions.posting_board_actions.execute_posting_board_request",
                return_value=board_result,
            ),
            patch("utils.actions.dispatcher.ensure_assets_tree"),
        ):
            applied = await apply_runtime_action_calls(
                context,
                [action],
                runtime_message_id="message-1",
            )

        self.assertEqual(applied, 1)
        terminal = [
            event
            for event in context.emitter.events
            if event.get("action") == "posting_board"
        ][-1]
        self.assertEqual(terminal["status"], "failed")
        self.assertEqual(terminal["text"], "POSTING_BOARD: action:post | topic: general - failed")
        self.assertEqual(context.runtime_action_events[0]["status"], "failed")
        self.assertEqual(context.runtime_action_events[0]["failure_reason"], "rate limited")
        self.assertTrue(context.runtime_followup_action_failure_pending)

        tool_context = build_tool_results_context(context)
        self.assertIn("Status: failed", tool_context)
        self.assertIn("Reason: rate limited", tool_context)
        self.assertIn("Correct action schema:", tool_context)
        self.assertIn("Retry after: 30", tool_context)

    def test_session_history_is_compact_and_never_includes_board_payload(self):
        feed_payload = '{"action":"feed","limit":30}'
        post_payload = json.dumps(
            {
                "action": "post",
                "topic": "general",
                "title": "title that must stay out of history",
                "body": "body that must stay out of history",
            },
            ensure_ascii=False,
        )
        formatted = format_session_action_marker_names([
            {
                "name": "POSTING_BOARD",
                "payload": feed_payload,
                "payloads": [feed_payload],
                "raw_payloads": [feed_payload],
                "status": "completed",
            },
            {
                "name": "POSTING_BOARD",
                "payload": post_payload,
                "payloads": [post_payload],
                "raw_payloads": [post_payload],
                "status": "failed",
                "failure_reason": "nope",
            },
        ])

        self.assertEqual(
            formatted,
            "POSTING_BOARD: action:feed | limit: 30, "
            "POSTING_BOARD: action:post | topic: general - failed",
        )
        self.assertNotIn("title that must stay out of history", formatted)
        self.assertNotIn("body that must stay out of history", formatted)
        self.assertNotIn("nope", formatted)

    async def test_semantic_duplicate_payload_in_one_message_executes_board_once(self):
        context = SimpleNamespace(
            emitter=FakeEmitter(),
            logger=FakeLogger(),
            runtime_current_turn_id="turn-dedup",
            runtime_loaded_skills=[{"name": "posting_board"}],
        )
        first = RuntimeActionCall(
            name="POSTING_BOARD",
            payload='{"action":"reply","thread_id":"root","body":"same"}',
        )
        second = RuntimeActionCall(
            name="POSTING_BOARD",
            payload='{ "body": "same", "thread_id": "root", "action": "reply" }',
        )
        board_result = {
            "ok": True,
            "runtime_action_name": "POSTING_BOARD",
            "action": "reply",
            "status_code": 201,
            "response": {"id": "reply-1"},
        }

        with (
            patch(
                "utils.actions.posting_board_actions.execute_posting_board_request",
                return_value=board_result,
            ) as request,
            patch("utils.actions.dispatcher.ensure_assets_tree"),
        ):
            applied = await apply_runtime_action_calls(
                context,
                [first, second],
                runtime_message_id="message-dedup",
            )

        self.assertEqual(applied, 1)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(len(context.runtime_tool_results), 1)

    async def test_equivalent_write_payloads_share_one_effective_request(self):
        context = SimpleNamespace(
            emitter=FakeEmitter(),
            logger=FakeLogger(),
            runtime_current_turn_id="turn-write-normalize",
            runtime_loaded_skills=[{"name": "posting_board"}],
        )
        first = RuntimeActionCall(
            name="POSTING_BOARD",
            payload='{"action":"post","title":"hello","body":"world"}',
        )
        second = RuntimeActionCall(
            name="POSTING_BOARD",
            payload=(
                '{"ignored":"x","body":" world ","topic":"general",'
                '"title":" hello ","action":"POST"}'
            ),
        )
        board_result = {
            "ok": True,
            "runtime_action_name": "POSTING_BOARD",
            "action": "post",
            "status_code": 201,
            "response": {"id": "post-1"},
        }

        with (
            patch(
                "utils.actions.posting_board_actions.execute_posting_board_request",
                return_value=board_result,
            ) as request,
            patch("utils.actions.dispatcher.ensure_assets_tree"),
        ):
            applied = await apply_runtime_action_calls(
                context,
                [first, second],
                runtime_message_id="message-write-normalize",
            )

        self.assertEqual(applied, 1)
        self.assertEqual(request.call_count, 1)

    async def test_concurrent_semantic_duplicate_never_starts_second_board_request(self):
        context = SimpleNamespace(
            emitter=FakeEmitter(),
            logger=FakeLogger(),
            runtime_current_turn_id="turn-concurrent",
            runtime_loaded_skills=[{"name": "posting_board"}],
        )
        first_started = asyncio.Event()
        release_first = asyncio.Event()

        async def delayed_result(*_args, **_kwargs):
            first_started.set()
            await release_first.wait()
            return {
                "ok": True,
                "runtime_action_name": "POSTING_BOARD",
                "action": "reply",
                "status_code": 201,
                "response": {"id": "reply-1"},
            }

        first = RuntimeActionCall(
            name="POSTING_BOARD",
            payload='{"action":"reply","thread_id":"root","body":"same"}',
        )
        second = RuntimeActionCall(
            name="POSTING_BOARD",
            payload='{ "body": "same", "thread_id": "root", "action": "reply" }',
        )

        with (
            patch(
                "utils.actions.posting_board_actions.execute_posting_board_request",
                side_effect=delayed_result,
            ) as request,
            patch("utils.actions.dispatcher.ensure_assets_tree"),
        ):
            first_task = asyncio.create_task(
                apply_runtime_action_calls(
                    context,
                    [first],
                    runtime_message_id="message-one",
                )
            )
            await first_started.wait()
            second_result = await asyncio.wait_for(
                apply_runtime_action_calls(
                    context,
                    [second],
                    runtime_message_id="message-two",
                ),
                timeout=1.0,
            )
            self.assertEqual(second_result, 1)
            self.assertEqual(request.call_count, 1)
            self.assertEqual(
                context.runtime_tool_results[-1]["result"]["error"],
                "duplicate_action_execution",
            )
            release_first.set()
            await first_task

        self.assertEqual(request.call_count, 1)

    async def test_inbox_is_refetched_after_ack_instead_of_reusing_stale_result(self):
        context = SimpleNamespace(
            emitter=FakeEmitter(),
            logger=FakeLogger(),
            runtime_current_turn_id="turn-inbox-ack",
            runtime_loaded_skills=[{"name": "posting_board"}],
        )
        responses = [
            {
                "ok": True,
                "runtime_action_name": "POSTING_BOARD",
                "action": "inbox",
                "status_code": 200,
                "response": {
                    "items": [{"seq": 36563, "inbox_seq": 59767}],
                    "read_through": 0,
                    "latest_cursor": 59767,
                    "resume_after": 59767,
                    "unread_count": 1,
                },
            },
            {
                "ok": True,
                "runtime_action_name": "POSTING_BOARD",
                "action": "ack",
                "status_code": 200,
                "response": {"acknowledged_through": 59767},
            },
            {
                "ok": True,
                "runtime_action_name": "POSTING_BOARD",
                "action": "inbox",
                "status_code": 200,
                "response": {
                    "items": [],
                    "read_through": 59767,
                    "latest_cursor": 59767,
                    "resume_after": 59767,
                    "unread_count": 0,
                },
            },
        ]

        with (
            patch(
                "utils.actions.posting_board_actions.execute_posting_board_request",
                side_effect=responses,
            ) as request,
            patch("utils.actions.dispatcher.ensure_assets_tree"),
        ):
            for message_id, payload in (
                ("message-inbox-before", '{"action":"inbox","limit":10}'),
                ("message-ack", '{"action":"ack","through":59767}'),
                ("message-inbox-after", '{"action":"inbox","limit":10}'),
            ):
                action = RuntimeActionCall(name="POSTING_BOARD", payload=payload)
                applied = await apply_runtime_action_calls(
                    context,
                    [action],
                    runtime_message_id=message_id,
                )
                self.assertEqual(applied, 1)

        self.assertEqual(request.call_count, 3)
        self.assertEqual(len(context.runtime_tool_results), 3)
        self.assertFalse(any(
            result.get("reused_from")
            for result in context.runtime_tool_results
        ))
        self.assertEqual(
            context.runtime_tool_results[-1]["result"]["response"]["unread_count"],
            0,
        )
        self.assertEqual(
            context.runtime_tool_results[-1]["result"]["response"]["read_through"],
            59767,
        )

    async def test_successful_equivalent_write_is_reused_across_runtime_messages(self):
        context = SimpleNamespace(
            emitter=FakeEmitter(),
            logger=FakeLogger(),
            runtime_current_turn_id="turn-cross-message",
            runtime_loaded_skills=[{"name": "posting_board"}],
        )
        board_result = {
            "ok": True,
            "runtime_action_name": "POSTING_BOARD",
            "action": "post",
            "status_code": 201,
            "response": {"id": "post-1"},
        }
        payloads = (
            '{"action":"post","title":"hello","body":"world"}',
            (
                '{"ignored":"x","body":" world ","topic":"general",'
                '"title":" hello ","action":"POST"}'
            ),
        )

        with (
            patch(
                "utils.actions.posting_board_actions.execute_posting_board_request",
                return_value=board_result,
            ) as request,
            patch("utils.actions.dispatcher.ensure_assets_tree"),
        ):
            for index, payload in enumerate(payloads, 1):
                action = RuntimeActionCall(name="POSTING_BOARD", payload=payload)
                applied = await apply_runtime_action_calls(
                    context,
                    [action],
                    runtime_message_id=f"message-{index}",
                )
                self.assertEqual(applied, 1)

        self.assertEqual(request.call_count, 1)
        self.assertEqual(len(context.runtime_tool_results), 2)
        self.assertEqual(context.runtime_tool_results[-1]["reused_from"], "T1")

    async def test_write_retry_reuses_same_idempotency_key_within_turn(self):
        context = SimpleNamespace(
            emitter=FakeEmitter(),
            logger=FakeLogger(),
            runtime_current_turn_id="turn-retry",
            runtime_loaded_skills=[{"name": "posting_board"}],
        )
        seen_keys = []

        async def retryable_result(_payload, *, idempotency_key=""):
            seen_keys.append(idempotency_key)
            if len(seen_keys) == 1:
                return {
                    "ok": False,
                    "runtime_action_name": "POSTING_BOARD",
                    "action": "reply",
                    "error": "network_error",
                    "detail": "lost response",
                    "request": {},
                    "response": None,
                }
            return {
                "ok": True,
                "runtime_action_name": "POSTING_BOARD",
                "action": "reply",
                "status_code": 201,
                "response": {"id": "reply-1", "replayed": True},
            }

        with (
            patch(
                "utils.actions.posting_board_actions.execute_posting_board_request",
                side_effect=retryable_result,
            ),
            patch("utils.actions.dispatcher.ensure_assets_tree"),
        ):
            for message_id in ("retry-one", "retry-two"):
                action = RuntimeActionCall(
                    name="POSTING_BOARD",
                    payload='{"action":"reply","thread_id":"root","body":"same"}',
                )
                await apply_runtime_action_calls(
                    context,
                    [action],
                    runtime_message_id=message_id,
                )

        self.assertEqual(len(seen_keys), 2)
        self.assertTrue(seen_keys[0])
        self.assertEqual(seen_keys[0], seen_keys[1])

    def test_anonymous_mode_allows_reads_but_blocks_public_writes(self):
        context = SimpleNamespace(runtime_persistent_writes_restricted=True)

        for action_name in ("feed", "inbox", "read", "search"):
            with self.subTest(action=action_name):
                self.assertFalse(
                    runtime_action_write_is_restricted(
                        context,
                        "POSTING_BOARD",
                        json.dumps({"action": action_name}),
                    )
                )

        for action_name in ("post", "reply", "ack", "delete"):
            with self.subTest(action=action_name):
                self.assertTrue(
                    runtime_action_write_is_restricted(
                        context,
                        "POSTING_BOARD",
                        json.dumps({"action": action_name}),
                    )
                )

    async def test_client_rejects_missing_key_and_bad_ack_without_network(self):
        with patch.dict(os.environ, {}, clear=True):
            missing_key = await execute_posting_board_request({"action": "feed"})
        self.assertFalse(missing_key["ok"])
        self.assertEqual(missing_key["error"], "missing_api_key")
        self.assertNotIn("Authorization", str(missing_key))

        with patch.dict(os.environ, {"GETPOSTINGBOARD_API_KEY": "secret"}, clear=True):
            bad_ack = await execute_posting_board_request(
                {"action": "ack", "through": "not-a-number"}
            )
        self.assertFalse(bad_ack["ok"])
        self.assertEqual(bad_ack["error"], "invalid_payload")
        self.assertEqual(bad_ack["request"], {})
        self.assertNotIn("secret", str(bad_ack))


    async def test_client_rejects_delete_without_post_id_without_network(self):
        with patch.dict(os.environ, {"GETPOSTINGBOARD_API_KEY": "secret"}, clear=True):
            result = await execute_posting_board_request({"action": "delete"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "invalid_payload")
        self.assertEqual(result["detail"], "delete requires post_id")
        self.assertEqual(result["request"], {})
        self.assertNotIn("secret", str(result))

    async def test_client_accepts_environment_overrides(self):
        for env, expected in (
            ({"GETPOSTINGBOARD_API_KEY": "env-key"}, "env-key"),
            ({"JIN_GETPOSTINGBOARD_API_KEY": "prefixed-key"}, "prefixed-key"),
        ):
            with (
                self.subTest(env=env),
                patch.dict(os.environ, env, clear=True),
                patch("utils.posting_board_client._base_headers", return_value={}) as headers,
            ):
                result = await execute_posting_board_request({"action": "ack", "through": "invalid"})
                headers.assert_called_once_with(expected)
                self.assertEqual(result["error"], "invalid_payload")
                self.assertNotIn(expected, str(result))

    async def test_client_encodes_ids_and_redacts_bearer_from_public_result(self):
        calls = []

        class FakeResponse:
            status_code = 201
            headers = {}
            text = ""

            @staticmethod
            def json():
                return {"ok": True, "post_id": "reply-1"}

        class FakeClient:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def request(self, method, path, **kwargs):
                calls.append((method, path, kwargs))
                return FakeResponse()

        with (
            patch.dict(
                os.environ,
                {"GETPOSTINGBOARD_API_KEY": "super-secret-key"},
                clear=True,
            ),
            patch(
                "utils.posting_board_client.httpx.AsyncClient",
                FakeClient,
            ),
        ):
            result = await execute_posting_board_request(
                {
                    "action": "reply",
                    "thread_id": "root/with/slashes",
                    "body": "hello",
                },
                idempotency_key="fixed-retry-key-1234",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(calls[0][0], "POST")
        self.assertEqual(
            calls[0][1],
            "/v1/posts/root%2Fwith%2Fslashes/replies",
        )
        self.assertEqual(
            calls[0][2]["headers"]["Authorization"],
            "Bearer super-secret-key",
        )
        self.assertEqual(
            calls[0][2]["headers"]["Idempotency-Key"],
            "fixed-retry-key-1234",
        )
        self.assertNotIn("Authorization", result["request"]["headers"])
        self.assertNotIn("super-secret-key", str(result))
        self.assertEqual(result["request"]["body"], {"body": "hello"})

    async def test_client_deletes_owned_post_by_exact_id(self):
        calls = []

        class FakeResponse:
            status_code = 200
            headers = {}
            text = ""

            @staticmethod
            def json():
                return {"deleted": True}

        class FakeClient:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def request(self, method, path, **kwargs):
                calls.append((method, path, kwargs))
                return FakeResponse()

        with (
            patch.dict(
                os.environ,
                {"GETPOSTINGBOARD_API_KEY": "super-secret-key"},
                clear=True,
            ),
            patch(
                "utils.posting_board_client.httpx.AsyncClient",
                FakeClient,
            ),
        ):
            result = await execute_posting_board_request({
                "action": "delete",
                "post_id": "reply/with/slashes",
            })

        self.assertTrue(result["ok"])
        self.assertEqual(calls[0][0], "DELETE")
        self.assertEqual(calls[0][1], "/v1/posts/reply%2Fwith%2Fslashes")
        self.assertIsNone(calls[0][2]["json"])
        self.assertEqual(
            calls[0][2]["headers"]["Authorization"],
            "Bearer super-secret-key",
        )
        self.assertNotIn("Idempotency-Key", calls[0][2]["headers"])
        self.assertNotIn("Authorization", result["request"]["headers"])
        self.assertNotIn("super-secret-key", str(result))
        self.assertEqual(result["request"]["method"], "DELETE")
        self.assertEqual(result["request"]["path"], "/v1/posts/reply%2Fwith%2Fslashes")
        self.assertNotIn("body", result["request"])

    def test_ui_contract_keeps_live_bubble_logger_and_request_response_modal(self):
        chat_js = CHAT_RUNTIME_ACTIONS_JS.read_text(encoding="utf-8")
        socket_js = SOCKET_RUNTIME_ACTIONS_JS.read_text(encoding="utf-8")
        logger_js = LOGGER_JS.read_text(encoding="utf-8")
        trace_js = TRACE_MODAL_JS.read_text(encoding="utf-8")

        self.assertIn("posting_board:", chat_js)
        self.assertIn("bindPostingBoardResultPreview", chat_js)
        self.assertIn("options.postingBoardResult", chat_js)
        self.assertIn('"posting_board"', socket_js)
        self.assertIn("data.posting_board_result", socket_js)
        self.assertIn("fadeRuntimeAction", socket_js)
        self.assertIn("data.posting_board_result", logger_js)
        self.assertIn("renderPostingBoardTrace", trace_js)
        self.assertIn('title: "REQUEST"', trace_js)
        self.assertIn('title: "RESPONSE"', trace_js)
        self.assertIn("window.showPostingBoardTrace", trace_js)


if __name__ == "__main__":
    unittest.main()
