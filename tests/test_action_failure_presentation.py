import asyncio
import json
from unittest.mock import patch
from types import SimpleNamespace
from runtime.runtime_context import RuntimeContext
from utils.actions import RuntimeActionCall
from utils.actions.dispatcher import apply_runtime_action_calls
from utils.context import build_tool_results_context
from utils.context.files import file_result_summary
from utils.context.session_actions import build_session_actions_history_context
from utils.session_actions_history import upsert_session_action_marker_history_since
from utils.tool_results import (
    begin_runtime_tool_results_turn,
    clean_runtime_tool_result,
    record_runtime_tool_result,
)
from agent.nodes.brain import BrainNode, consume_action_failure_followup_context

PATH = '../outside.py'


def test_attachment_failure_bubble_history_context_and_followup():
    events = []
    class Emitter:
        async def emit(self, data):
            events.append(data)
    ctx = RuntimeContext(websocket=None, emitter=Emitter(), logger=None, clients={})
    ctx.runtime_current_turn_id = 'turn_1'
    with patch('utils.actions.dispatcher.ensure_assets_tree'), patch('utils.chat_log.append_chat_runtime_event'), patch('utils.project_reader.linked_projects', return_value=[]):
        asyncio.run(apply_runtime_action_calls(ctx, (RuntimeActionCall(name='ATTACH_FILE_CONTENT', payload=PATH),)))
    terminal = [e for e in events if e.get('action') == 'attach_file_content' and e.get('status') == 'failed'][-1]
    label = terminal['text']
    assert label.startswith('ATTACH_FILE_CONTENT: ')
    assert '../outside.py - failed: Use a relative path inside the linked folder' in label
    assert ctx.runtime_action_events[-1]['status'] == 'failed'
    upsert_session_action_marker_history_since(ctx, 0, [{'name': 'ATTACH_FILE_CONTENT', 'payload': PATH}])
    assert label in ctx.runtime_session_action_history[-1]['text']
    assert label in build_session_actions_history_context(ctx)
    # Serialized history must keep the same visible result after reload.
    restored = SimpleNamespace(session_id=ctx.session_id, runtime_session_action_history=json.loads(json.dumps(ctx.runtime_session_action_history)))
    assert label in build_session_actions_history_context(restored)
    tools = build_tool_results_context(ctx)
    prompt = BrainNode.build_followup_system_prompt(tools, 'read file', context=ctx)
    upper = prompt.split('<ACTION_FAILURE_FOLLOWUP>', 1)[1].split('</ACTION_FAILURE_FOLLOWUP>', 1)[0]
    assert label in upper
    assert 'File: ' in upper and '../outside.py' in upper
    assert 'Status: failed' in upper
    assert 'Correct action schema:' not in upper
    assert 'Correct action schema:' in prompt.split('<TOOLS_RESULTS>', 1)[1]
    assert '<CURRENT_REQUEST_FLOW>' not in prompt
    assert '<MANDATORY_ACTION_RULES>' not in prompt
    assert consume_action_failure_followup_context(ctx) == ''


def test_failure_summary_consumes_only_new_failures_and_preserves_structured_payload():
    ctx = SimpleNamespace()
    begin_runtime_tool_results_turn(ctx)
    first = {'action': 'update_active_memory', 'ok': False, 'detail': 'old failure', 'payload': '{"id":"first"}'}
    record_runtime_tool_result(ctx, 'runtime_action', first)
    assert 'old failure' in consume_action_failure_followup_context(ctx)
    record_runtime_tool_result(ctx, 'runtime_action', {'action': 'update_active_memory', 'ok': False, 'detail': 'new failure', 'payload': '{"id":"second","fields":{"value":"a\\nb"}}'})
    text = consume_action_failure_followup_context(ctx)
    assert 'old failure' not in text
    assert 'Id: second' in text and 'Fields:' in text and 'Value:' in text
    assert '{"id"' not in text
    begin_runtime_tool_results_turn(ctx)
    assert consume_action_failure_followup_context(ctx) == ''


def test_failure_followup_survives_targeted_tool_result_cleanup():
    ctx = SimpleNamespace()
    begin_runtime_tool_results_turn(ctx)
    record_runtime_tool_result(
        ctx,
        'runtime_action',
        {
            'action': 'attach_file_content',
            'ok': False,
            'detail': 'no project folder attached by user',
            'payload': PATH,
        },
    )
    tool_id = ctx.runtime_tool_results[-1]['tool_id']
    assert clean_runtime_tool_result(ctx, tool_id)
    assert ctx.runtime_tool_results == []

    text = consume_action_failure_followup_context(ctx)
    assert 'no project folder attached by user' in text
    assert PATH in text


def test_removed_request_flow_is_stripped_from_legacy_prompt():
    prompt = BrainNode.build_followup_system_prompt('<CURRENT_REQUEST_FLOW>stale</CURRENT_REQUEST_FLOW>\nother', 'read file', context=RuntimeContext(websocket=None, emitter=None, logger=None, clients={}))
    assert 'CURRENT_REQUEST_FLOW' not in prompt
    assert 'stale' not in prompt
