from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import unittest

from agent.nodes.brain import action_event_requires_follow_up
from utils.actions import RuntimeActionCall
from utils.actions.dispatcher import apply_runtime_action_calls
from utils.runtime_action_abort import mark_runtime_action_started, abort_active_runtime_actions


class Emitter:
    def __init__(self):
        self.events = []

    async def emit(self, event):
        self.events.append(deepcopy(event))


class ActionResultReuseTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_posting_board_read_executes_fresh_request_across_messages(self):
        ctx = SimpleNamespace(emitter=Emitter(), runtime_current_turn_id="turn-1",
                              runtime_loaded_skills=[{"name": "posting_board"}])

        async def fresh_result(_payload, **_kwargs):
            call_no = request.call_count
            return {
                "ok": True,
                "runtime_action_name": "POSTING_BOARD",
                "action": "read",
                "response": {"body": f"BOARD_BODY_{call_no}"},
            }

        with patch("utils.actions.posting_board_actions.execute_posting_board_request",
                   side_effect=fresh_result) as request, patch("utils.actions.dispatcher.ensure_assets_tree"):
            for i in range(1, 5):
                ctx.runtime_followup_tick_active = i > 1
                payload = '{"action":"read","root_id":"root"}' if i % 2 else '{ "root_id": "root", "action": "read" }'
                action = RuntimeActionCall(name="POSTING_BOARD", payload=payload)
                action_id = f"posting_board_{i:03}"
                mark_runtime_action_started(ctx, action="posting_board", action_id=action_id)
                assert await apply_runtime_action_calls(
                    ctx, [action], runtime_message_id=f"message-{i}",
                    action_display_ids={id(action): action_id},
                    context_snapshot={"system_prompt": f"PROMPT_{i}"},
                ) == 1
                assert ctx.runtime_active_action_markers == []

        assert request.call_count == 4
        assert [e["tool_id"] for e in ctx.runtime_tool_results] == ["T1", "T2", "T3", "T4"]
        assert all(not e.get("reused_from") for e in ctx.runtime_tool_results)
        assert [e["result"]["response"]["body"] for e in ctx.runtime_tool_results] == [
            "BOARD_BODY_1", "BOARD_BODY_2", "BOARD_BODY_3", "BOARD_BODY_4"
        ]
        terminal = [e for e in ctx.emitter.events if e.get("status") == "completed"]
        assert len(terminal) == 4
        assert len({e["id"] for e in terminal}) == 4
        assert [e["context"]["system_prompt"] for e in terminal] == [f"PROMPT_{i}" for i in range(1, 5)]
        assert all(action_event_requires_follow_up(e) for e in ctx.runtime_action_events)
        await abort_active_runtime_actions(ctx)
        assert not any(e.get("status") == "aborted" for e in ctx.emitter.events)

    async def test_same_message_parser_replay_does_not_allocate_another_result(self):
        ctx = SimpleNamespace(emitter=Emitter(), runtime_current_turn_id="turn-1")
        action = RuntimeActionCall(name="POSTING_BOARD", payload='{"action":"read","root_id":"a"}')
        with patch("utils.actions.posting_board_actions.execute_posting_board_request",
                   return_value={"ok": True, "runtime_action_name": "POSTING_BOARD", "action": "read", "response": "BODY"}) as request, patch("utils.actions.dispatcher.ensure_assets_tree"):
            await apply_runtime_action_calls(ctx, [action], runtime_message_id="m1")
            await apply_runtime_action_calls(ctx, [action], runtime_message_id="m1")
            assert request.call_count == 1
            assert len(ctx.runtime_tool_results) == 1
