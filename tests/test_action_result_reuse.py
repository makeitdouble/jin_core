import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import unittest

from agent.nodes.brain import action_event_requires_follow_up
from utils.actions import RuntimeActionCall
from utils.actions.dispatcher import apply_runtime_action_calls
from utils.context.tool_results import build_tool_results_context
from utils.runtime_action_abort import mark_runtime_action_started, abort_active_runtime_actions
from utils.tool_results import clean_runtime_tool_result
from websocket.bootstrap import clean_bootstrap_tool_results


class Emitter:
    def __init__(self):
        self.events = []

    async def emit(self, event):
        self.events.append(deepcopy(event))


class ActionResultReuseTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_read_moves_body_and_preserves_each_attempt_and_stop(self):
        ctx = SimpleNamespace(emitter=Emitter(), runtime_current_turn_id="turn-1",
                              runtime_loaded_skills=[{"name": "posting_board"}])
        result = {"ok": True, "runtime_action_name": "POSTING_BOARD", "action": "read",
                  "response": {"body": "UNIQUE_BOARD_BODY"}}
        with patch("utils.actions.posting_board_actions.execute_posting_board_request",
                   return_value=result) as request, patch("utils.actions.dispatcher.ensure_assets_tree"):
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
            assert request.call_count == 1
            assert [e["tool_id"] for e in ctx.runtime_tool_results] == ["T1", "T2", "T3", "T4"]
            for i, entry in enumerate(ctx.runtime_tool_results[:-1], 2):
                assert entry["result"] == {}
                assert entry["absorbed_by"] == f"T{i}"
            prompt = build_tool_results_context(ctx)
            assert prompt.count("UNIQUE_BOARD_BODY") == 1
            assert "Result absorbed by duplicate action T4" in prompt
            assert "duplicate_action_execution" not in prompt
            terminal = [e for e in ctx.emitter.events if e.get("status") == "completed"]
            assert len(terminal) == 4
            assert len({e["id"] for e in terminal}) == 4
            assert [e["context"]["system_prompt"] for e in terminal] == [f"PROMPT_{i}" for i in range(1, 5)]
            assert all(action_event_requires_follow_up(e) for e in ctx.runtime_action_events)
            await abort_active_runtime_actions(ctx)
            assert not any(e.get("status") == "aborted" for e in ctx.emitter.events)
            # A genuinely started unfinished action must still be visible as ABORTED.
            mark_runtime_action_started(ctx, action="posting_board", action_id="unfinished")
            await abort_active_runtime_actions(ctx)
            assert ctx.emitter.events[-1]["status"] == "aborted"
            assert ctx.emitter.events[-1]["id"] == "unfinished"
            restored, _ = clean_bootstrap_tool_results(json.loads(json.dumps(ctx.runtime_tool_results)))
            assert restored[0]["absorbed_by"] == "T2"
            assert restored[-1]["action_payload"] == ctx.runtime_tool_results[-1]["action_payload"]
            ctx.runtime_tool_results = restored
            assert clean_runtime_tool_result(ctx, "T4")
            action = RuntimeActionCall(name="POSTING_BOARD", payload=payload)
            await apply_runtime_action_calls(ctx, [action], runtime_message_id="message-5")
            assert request.call_count == 2


    async def test_same_message_parser_replay_does_not_allocate_another_result(self):
        ctx = SimpleNamespace(emitter=Emitter(), runtime_current_turn_id="turn-1")
        action = RuntimeActionCall(name="POSTING_BOARD", payload='{"action":"read","root_id":"a"}')
        with patch("utils.actions.posting_board_actions.execute_posting_board_request",
                   return_value={"ok": True, "runtime_action_name": "POSTING_BOARD", "action": "read", "response": "BODY"}) as request, patch("utils.actions.dispatcher.ensure_assets_tree"):
            await apply_runtime_action_calls(ctx, [action], runtime_message_id="m1")
            await apply_runtime_action_calls(ctx, [action], runtime_message_id="m1")
            assert request.call_count == 1
            assert len(ctx.runtime_tool_results) == 1
