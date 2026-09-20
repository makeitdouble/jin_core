import asyncio
import base64
import contextlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from clients.brain_client import get_response_enabled_runtime_actions
from contracts.rules_assembler import build_runtime_action_instructions, get_enabled_runtime_actions
from rules.brain_context_builder import BRAIN_RUNTIME_ACTIONS
from tests.helpers.runtime_actions import patch_asset_roots
from utils.actions import RuntimeActionCall, extract_runtime_actions
from utils.actions.mcp_actions import apply_mcp_actions, parse_call_mcp_payload
from utils.actions.result_reuse import find_reusable_result
from utils.actions.skill_actions import apply_skill_actions
from utils.mcp_client import MCPClientManager, _MCPConnection
from utils.mcp_skill_utils import parse_mcp_server_config


MCP_SKILL_TEXT = """# demo_mcp

<MCP_SERVER>
{"transport":"stdio","command":"python","args":["demo_server.py"],"env_from_host":["DEMO_TOKEN"]}
</MCP_SERVER>

Use the live MCP tool catalog appended by the runtime.
"""


class FakeEmitter:
    def __init__(self):
        self.events = []

    async def emit(self, event):
        self.events.append(event)


class MCPRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def test_contract_parser_and_skill_gating(self):
        parsed = extract_runtime_actions(
            '<CALL_MCP>{"skill":"demo_mcp","tool":"ping","arguments":{"value":1}}</CALL_MCP>',
            enabled_actions=("CALL_MCP",),
        )
        self.assertEqual(parsed.text, "")
        self.assertEqual(len(parsed.actions), 1)
        self.assertEqual(parsed.actions[0].name, "CALL_MCP")
        self.assertEqual(
            parse_call_mcp_payload(parsed.actions[0].payload),
            {"skill": "demo_mcp", "tool": "ping", "arguments": {"value": 1}},
        )

        enabled = get_enabled_runtime_actions(BRAIN_RUNTIME_ACTIONS)
        self.assertIn("CALL_MCP", enabled)

        without_skill = SimpleNamespace(runtime_loaded_skills=[])
        with_skill = SimpleNamespace(
            runtime_loaded_skills=[{"name": "demo_mcp", "content": MCP_SKILL_TEXT}],
        )
        self.assertNotIn(
            "CALL_MCP",
            get_response_enabled_runtime_actions(BRAIN_RUNTIME_ACTIONS, context=without_skill),
        )
        self.assertIn(
            "CALL_MCP",
            get_response_enabled_runtime_actions(BRAIN_RUNTIME_ACTIONS, context=with_skill),
        )
        self.assertNotIn(
            "<CALL_MCP>",
            build_runtime_action_instructions(("CALL_MCP",), context=without_skill),
        )
        self.assertIn(
            "<CALL_MCP>",
            build_runtime_action_instructions(("CALL_MCP",), context=with_skill),
        )

    def test_mcp_server_config_supports_stdio_http_sse_and_host_env(self):
        stdio = parse_mcp_server_config(MCP_SKILL_TEXT)
        self.assertEqual(stdio["transport"], "stdio")
        self.assertEqual(stdio["command"], "python")
        self.assertEqual(stdio["env_from_host"], {"DEMO_TOKEN": "DEMO_TOKEN"})

        http = parse_mcp_server_config(
            '<MCP_SERVER>{"transport":"streamable-http","url":"http://127.0.0.1:9000/mcp"}</MCP_SERVER>'
        )
        self.assertEqual(http["transport"], "streamable_http")
        self.assertEqual(http["url"], "http://127.0.0.1:9000/mcp")

        sse = parse_mcp_server_config(
            '<JIN_MCP>{"transport":"sse","url":"http://127.0.0.1:9000/sse"}</JIN_MCP>'
        )
        self.assertEqual(sse["transport"], "sse")

    async def test_loading_mcp_skill_discovers_live_tools_into_in_memory_skill(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            skill_dir = root / "assets" / "skills" / "demo_mcp"
            skill_dir.mkdir(parents=True)
            (skill_dir / "JIN_SKILL.md").write_text(MCP_SKILL_TEXT, encoding="utf-8")

            context = SimpleNamespace(runtime_loaded_skills=[])
            action = RuntimeActionCall(name="LOAD_SKILL", payload="demo_mcp")
            discovery = {
                "ok": True,
                "skill": "demo_mcp",
                "server": {
                    "protocol_version": "2026-07-28",
                    "server_name": "demo",
                    "server_version": "1.0",
                },
                "tools": [
                    {
                        "name": "create_cube",
                        "title": "Create cube",
                        "description": "Create one cube in the scene.",
                        "input_schema": {
                            "type": "object",
                            "properties": {"size": {"type": "number"}},
                        },
                    }
                ],
            }

            with contextlib.ExitStack() as stack:
                for patcher in patch_asset_roots(root):
                    stack.enter_context(patcher)
                stack.enter_context(
                    patch(
                        "utils.actions.skill_actions.discover_mcp_skill_tools",
                        new=AsyncMock(return_value=discovery),
                    )
                )
                result = await apply_skill_actions(
                    context,
                    load_skill_actions=[action],
                    unload_skill_actions=[],
                    log_runtime=None,
                )

        self.assertEqual(len(context.runtime_loaded_skills), 1)
        loaded = context.runtime_loaded_skills[0]
        self.assertIn("<MCP_RUNTIME>", loaded["content"])
        self.assertIn("create_cube", loaded["content"])
        self.assertEqual(loaded["mcp_runtime"]["server"]["server_name"], "demo")
        self.assertTrue(result["loaded_skill_results"][0]["ok"])

    async def test_call_mcp_records_result_and_turns_image_block_into_followup_attachment(self):
        png = base64.b64encode(
            b"\x89PNG\r\n\x1a\n" + b"test-image-payload"
        ).decode("ascii")
        context = SimpleNamespace(
            emitter=FakeEmitter(),
            runtime_loaded_skills=[{"name": "demo_mcp", "content": MCP_SKILL_TEXT}],
            runtime_action_events=[],
            runtime_turn_attachments=[],
            runtime_current_sequence_attachments=[],
            runtime_mcp_action_sequence=0,
        )
        action = RuntimeActionCall(
            name="CALL_MCP",
            payload='{"skill":"demo_mcp","tool":"render_scene","arguments":{"camera":"main"}}',
        )
        response = {
            "ok": True,
            "skill": "demo_mcp",
            "tool": "render_scene",
            "arguments": {"camera": "main"},
            "server": {"protocol_version": "2026-07-28"},
            "is_error": False,
            "content": [
                {"type": "text", "text": "rendered"},
                {"type": "image", "data": png, "mimeType": "image/png"},
            ],
            "structured_content": {"rendered": True},
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            files_dir = Path(temp_dir) / "files"
            with (
                patch("utils.actions.mcp_actions.call_mcp_tool", new=AsyncMock(return_value=response)),
                patch("utils.attached_files_store.FILES_DIR", files_dir),
                patch("utils.attached_files_store.INDEX_FILE", files_dir / ".index.json"),
                patch("utils.attached_files_store.GITKEEP_FILE", files_dir / ".gitkeep"),
            ):
                results = await apply_mcp_actions(
                    context,
                    [action],
                    action_display_ids={},
                    log_runtime=None,
                    with_action_context=lambda payload: payload,
                )

        self.assertTrue(results[0]["ok"])
        self.assertEqual(len(context.runtime_turn_attachments), 1)
        attachment = context.runtime_turn_attachments[0]
        self.assertEqual(attachment["kind"], "image")
        self.assertTrue(attachment["data_url"].startswith("data:image/png;base64,"))
        self.assertEqual(len(results[0]["attachments"]), 1)
        image_block = results[0]["content"][1]
        self.assertNotIn("data", image_block)
        self.assertEqual(image_block["file_id"], attachment["id"])
        statuses = [event.get("status") for event in context.emitter.events]
        self.assertEqual(statuses, ["running", "completed"])
        self.assertTrue(getattr(context, "runtime_tool_results", []))

    def test_call_mcp_is_never_satisfied_from_result_reuse_cache(self):
        context = SimpleNamespace(runtime_tool_results=[])
        action = RuntimeActionCall(
            name="CALL_MCP",
            payload='{"skill":"demo_mcp","tool":"create_cube","arguments":{}}',
        )
        self.assertIsNone(find_reusable_result(context, action))

    async def test_connection_worker_keeps_one_client_across_followups_and_closes_in_owner_task(self):
        class FakeBlock:
            def model_dump(self, **_kwargs):
                return {"type": "text", "text": "done"}

        class FakeClient:
            def __init__(self):
                self.enter_count = 0
                self.exit_count = 0
                self.protocol_version = "test"
                self.server_info = SimpleNamespace(name="fake", version="1")
                self.instructions = ""

            async def __aenter__(self):
                self.enter_count += 1
                return self

            async def __aexit__(self, *_args):
                self.exit_count += 1

            async def list_tools(self, **_kwargs):
                return SimpleNamespace(
                    tools=[SimpleNamespace(
                        name="ping",
                        title=None,
                        description="ping",
                        input_schema={"type": "object"},
                    )],
                    next_cursor=None,
                )

            async def call_tool(self, name, arguments):
                return SimpleNamespace(
                    is_error=False,
                    content=[FakeBlock()],
                    structured_content={"name": name, "arguments": arguments},
                )

        fake_client = FakeClient()
        connection = _MCPConnection(
            skill_name="demo_mcp",
            config={"transport": "stdio", "command": "fake"},
        )
        with patch.object(connection, "_build_client", return_value=fake_client):
            tools = await connection.list_tools()
            called = await connection.call_tool("ping", {"x": 1})
            self.assertEqual(fake_client.enter_count, 1)
            self.assertEqual(tools["tools"][0]["name"], "ping")
            self.assertEqual(called["structured_content"]["arguments"], {"x": 1})
            await connection.close()

        self.assertEqual(fake_client.exit_count, 1)


if __name__ == "__main__":
    unittest.main()
