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
        self.assertIn("feed|inbox|read|search|post|reply|ack", instructions)
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
        self.assertEqual(events[0]["text"], "POSTING_BOARD: action:feed")
        self.assertEqual(events[1]["text"], "POSTING_BOARD: action:feed")
        self.assertNotIn("posting_board_result", events[0])
        self.assertEqual(events[1]["posting_board_result"]["response"], board_result["response"])

        self.assertEqual(context.runtime_action_events[0]["status"], "completed")
        self.assertEqual(context.runtime_action_events[0]["tool_id"], "T1")
        self.assertEqual(context.runtime_tool_results[0]["kind"], "runtime_action")
        self.assertEqual(
            context.runtime_tool_results[0]["result"]["runtime_action_name"],
            "POSTING_BOARD",
        )
        self.assertEqual(
            context.logger.lines,
            ["[RUNTIME ACTION] posting_board action:feed success"],
        )

        tool_context = build_tool_results_context(context)
        self.assertIn('name="POSTING_BOARD"', tool_context)
        self.assertIn("Posting board action: feed", tool_context)
        self.assertIn("A public thread", tool_context)
        self.assertNotIn("Authorization", tool_context)

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
        self.assertEqual(terminal["text"], "POSTING_BOARD: action:post - failed")
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
            "POSTING_BOARD: action:feed, POSTING_BOARD: action:post - failed",
        )
        self.assertNotIn("title that must stay out of history", formatted)
        self.assertNotIn("body that must stay out of history", formatted)
        self.assertNotIn("nope", formatted)

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

        for action_name in ("post", "reply", "ack"):
            with self.subTest(action=action_name):
                self.assertTrue(
                    runtime_action_write_is_restricted(
                        context,
                        "POSTING_BOARD",
                        json.dumps({"action": action_name}),
                    )
                )

    async def test_client_rejects_missing_key_and_bad_ack_without_network(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("utils.posting_board_client.config.GETPOSTINGBOARD_API_KEY", ""),
        ):
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


    async def test_client_accepts_config_and_environment_overrides(self):
        for env, expected in (
            ({}, "config-key"),
            ({"GETPOSTINGBOARD_API_KEY": "env-key"}, "env-key"),
            ({"JIN_GETPOSTINGBOARD_API_KEY": "prefixed-key"}, "prefixed-key"),
        ):
            with (
                self.subTest(env=env),
                patch.dict(os.environ, env, clear=True),
                patch("utils.posting_board_client.config.GETPOSTINGBOARD_API_KEY", "config-key"),
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
            result = await execute_posting_board_request({
                "action": "reply",
                "thread_id": "root/with/slashes",
                "body": "hello",
            })

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
        self.assertNotIn("Authorization", result["request"]["headers"])
        self.assertNotIn("super-secret-key", str(result))
        self.assertEqual(result["request"]["body"], {"body": "hello"})

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
