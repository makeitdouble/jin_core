from unittest.mock import patch
import asyncio
from utils.tool_results import record_runtime_tool_result, clean_runtime_tool_result, clear_runtime_tool_results
from utils.actions import RuntimeActionStreamFilter, RuntimeActionCall
from utils.context import build_tool_results_context
from clients.brain_client import apply_runtime_action_calls
from runtime.runtime_context import RuntimeContext
from runtime.frame_memory_utils import build_runtime_session_checkpoint
from websocket.bootstrap import apply_bootstrap_tool_results, clean_bootstrap_tool_results
from utils.session_actions_history import upsert_session_action_marker_history_since


def test_every_stream_boundary():
    cases = [
        ('<CLEAN_TOOL_RESULTS>', ''),
        ('<CLEAN_TOOL_RESULTS: T1 >', 'T1'),
        ('<CLEAN_TOOL_RESULTS: wrong >', 'wrong'),
        ('<CLEAN_TOOL_RESULTS: >', ':'),
        ('<CLEAN_TOOL_RESULTS:>', ':'),
    ]
    for tag, payload in cases:
        for split in range(len(tag) + 1):
            parser = RuntimeActionStreamFilter()
            results = [parser.filter(tag[:split]), parser.filter(tag[split:]), parser.flush_result()]
            assert ''.join(r.text for r in results) == ''
            assert [(a.name, a.payload) for r in results for a in r.actions] == [('CLEAN_TOOL_RESULTS', payload)]
        parser = RuntimeActionStreamFilter()
        literal = '`' + tag + '`'
        results = [parser.filter(c) for c in literal] + [parser.flush_result()]
        assert ''.join(r.text for r in results) == literal
        assert not [a for r in results for a in r.actions]


def test_legacy_modern_clear_and_counter_roundtrip():
    ctx = RuntimeContext(websocket=None, emitter=None, logger=None, clients={})
    ctx.runtime_tool_results = [{'kind': 'search', 'result': 'legacy'}]
    record_runtime_tool_result(ctx, 'search', 'modern')
    record_runtime_tool_result(ctx, 'search', 'another')
    assert ctx.runtime_tool_results[1]['tool_id'] == 'T1'
    assert clean_runtime_tool_result(ctx, 'T1')
    assert [entry.get('tool_id') for entry in ctx.runtime_tool_results] == [None, 'T2']
    assert not clean_runtime_tool_result(ctx, 'T1')
    rendered = build_tool_results_context(ctx)
    assert '<TOOL_RESULT name="WEB_SEARCH"' in rendered
    assert '<TOOL_RESULT tool_id="T2" name="WEB_SEARCH"' in rendered
    clear_runtime_tool_results(ctx)
    snapshot = build_runtime_session_checkpoint(ctx)
    restored = RuntimeContext(websocket=None, emitter=None, logger=None, clients={})
    apply_bootstrap_tool_results(restored, snapshot)
    record_runtime_tool_result(restored, 'search', 'new')
    assert restored.runtime_tool_results[0]['tool_id'] == 'T3'


def test_invalid_clear_fails_everywhere():
    class Emitter:
        def __init__(self): self.events = []
        async def emit(self, data): self.events.append(data)

    for target in ['T999', 't1', 'T0', 'T01', 'T1 T2', ':']:
        ctx = RuntimeContext(websocket=None, emitter=None, logger=None, clients={})
        ctx.runtime_current_turn_id = 'turn_1'
        ctx.emitter = Emitter()
        record_runtime_tool_result(ctx, 'search', 'keep me')
        with patch('utils.actions.dispatcher.ensure_assets_tree'), patch('utils.chat_log.append_chat_runtime_event'):
            asyncio.run(apply_runtime_action_calls(ctx, (RuntimeActionCall(name='CLEAN_TOOL_RESULTS', payload=target),)))
        assert ctx.runtime_tool_results[0]['result'] == 'keep me'
        assert ctx.runtime_tool_results[-1]['result']['ok'] is False
        assert ctx.runtime_action_events[-1]['status'] == 'failed'
        assert any(e.get('status') == 'failed' and target in e.get('text', '') for e in ctx.emitter.events)
        upsert_session_action_marker_history_since(ctx, 0, [{'name': 'CLEAN_TOOL_RESULTS', 'payload': target}])
        assert 'failed' in ctx.runtime_session_action_history[-1]['text']
        assert target in ctx.runtime_session_action_history[-1]['text']
        assert 'Unknown or invalid tool_id' in build_tool_results_context(ctx)
        assert ctx.runtime_followup_action_failure_pending


def test_attach_history_id_and_restore():
    ctx = RuntimeContext(websocket=None, emitter=None, logger=None, clients={})
    ctx.runtime_current_turn_id = 'turn_1'
    ctx.runtime_action_events = [{'name': 'attach_file_content', 'payload': 'agent/nodes/base.py', 'runtime_turn_id': 'turn_1'}]
    record_runtime_tool_result(ctx, 'files', {'action': 'attach_file_content', 'ok': True, 'id': 'agent/nodes/base.py'})
    upsert_session_action_marker_history_since(ctx, 0, [{'name': 'ATTACH_FILE_CONTENT', 'payload': 'agent/nodes/base.py'}])
    assert '[ tool_id: T1 ]' in ctx.runtime_session_action_history[-1]['text']
    snapshot = build_runtime_session_checkpoint(ctx)
    entries, _ = clean_bootstrap_tool_results(snapshot['tool_results'])
    assert entries[0]['tool_id'] == 'T1'


def test_full_then_invalid_and_target_then_full():
    for targets in [('T1', ''), ('', 'T1')]:
        ctx = RuntimeContext(websocket=None, emitter=None, logger=None, clients={})
        record_runtime_tool_result(ctx, 'search', 'one')
        record_runtime_tool_result(ctx, 'search', 'two')
        with patch('utils.actions.dispatcher.ensure_assets_tree'), patch('utils.chat_log.append_chat_runtime_event'):
            asyncio.run(apply_runtime_action_calls(ctx, tuple(RuntimeActionCall(name='CLEAN_TOOL_RESULTS', payload=t) for t in targets)))
        assert all(e.get('result') not in ('one', 'two') for e in ctx.runtime_tool_results)
        if targets[0] == '':
            assert ctx.runtime_tool_results[-1]['result']['ok'] is False


def test_successful_targeted_cleanup_persists_only_survivors():
    class Emitter:
        def __init__(self): self.events = []
        async def emit(self, data): self.events.append(data)
    ctx = RuntimeContext(websocket=None, emitter=Emitter(), logger=None, clients={})
    ctx.runtime_tool_results = [{'kind': 'search', 'result': 'old'}]
    record_runtime_tool_result(ctx, 'asset', {'action': 'project_tree', 'ok': True, 'tree': 'a'})
    record_runtime_tool_result(ctx, 'search', 'keep')
    with patch('utils.actions.dispatcher.ensure_assets_tree'), patch('utils.chat_log.append_chat_runtime_event'):
        asyncio.run(apply_runtime_action_calls(ctx, (RuntimeActionCall(name='CLEAN_TOOL_RESULTS', payload='T1'),)))
    event = next(e for e in ctx.emitter.events if e.get('status') == 'completed')
    assert [e.get('tool_id') for e in event['tool_results']] == [None, 'T2']
    assert event['tool_result_sequence'] == 2
    restored = RuntimeContext(websocket=None, emitter=None, logger=None, clients={})
    apply_bootstrap_tool_results(restored, event)
    record_runtime_tool_result(restored, 'search', 'next')
    assert restored.runtime_tool_results[-1]['tool_id'] == 'T3'


def test_archive_reader_accepts_both_attribute_orders():
    from utils.session_restore import _parse_restore_tool_results
    text = '<TOOL_RESULT tool_id="T4" name="WEB_SEARCH">new</TOOL_RESULT><TOOL_RESULT name="WEB_SEARCH" tool_id="T5">next</TOOL_RESULT><TOOL_RESULT name="WEB_SEARCH">legacy</TOOL_RESULT>'
    assert [e.get('tool_id') for e in _parse_restore_tool_results(text, 123)] == ['T4', 'T5', None]


def test_background_result_updates_existing_history():
    from utils.actions.update_lt_facts_actions import _record_update_lt_tool_result
    ctx = RuntimeContext(websocket=None, emitter=None, logger=None, clients={})
    ctx.runtime_session_action_history = [{'text': 'UPDATE_LT_FACTS: remember', 'parts': [{'text': 'UPDATE_LT_FACTS', 'message': 'remember'}]}]
    with patch('utils.actions.update_lt_facts_actions.append_chat_runtime_event'):
        _record_update_lt_tool_result(ctx, action_id='lt_1', note={'message': 'remember'}, result={'status': 'completed'})
    assert '[ tool_id: T1 ]' in ctx.runtime_session_action_history[0]['text']


def test_mixed_cleanup_history_keeps_failure_on_its_own_action():
    ctx = RuntimeContext(websocket=None, emitter=None, logger=None, clients={})
    ctx.runtime_current_turn_id = 'turn_1'
    record_runtime_tool_result(ctx, 'search', 'one')
    actions = [RuntimeActionCall(name='CLEAN_TOOL_RESULTS'), RuntimeActionCall(name='CLEAN_TOOL_RESULTS', payload='T1')]
    with patch('utils.actions.dispatcher.ensure_assets_tree'), patch('utils.chat_log.append_chat_runtime_event'):
        asyncio.run(apply_runtime_action_calls(ctx, actions))
    assert not ctx.runtime_action_events[0].get('tool_id')
    assert ctx.runtime_action_events[1]['tool_id'] == 'T2'
    upsert_session_action_marker_history_since(ctx, 0, [{'name': a.name, 'payload': a.payload} for a in actions])
    parts = [p for item in ctx.runtime_session_action_history for p in item['parts']]
    assert [p['text'] for p in parts] == ['CLEAN_TOOL_RESULTS', 'CLEAN_TOOL_RESULTS:failed']
    assert parts[1]['tool_ids'] == ['T2']


def test_duplicate_failed_actions_get_fresh_tool_ids_every_time():
    ctx = RuntimeContext(websocket=None, emitter=None, logger=None, clients={})
    ctx.runtime_current_turn_id = 'turn_1'
    failure = {
        'action': 'attach_file_content',
        'ok': False,
        'id': 'plnsaf/agent/nodes/brain.py',
        'error': 'project_read_failed',
        'detail': 'File range already loaded',
    }

    for _ in range(3):
        ctx.runtime_action_events.append({
            'name': 'attach_file_content',
            'payload': 'jin_core/agent/nodes/brain.py#L1-L200',
            'runtime_turn_id': 'turn_1',
        })
        assert record_runtime_tool_result(ctx, 'files', failure) is True

    assert [entry['tool_id'] for entry in ctx.runtime_tool_results] == ['T1', 'T2', 'T3']
    assert [event['tool_id'] for event in ctx.runtime_action_events] == ['T1', 'T2', 'T3']
    assert ctx.runtime_tool_results_turn_count == 3


def test_repeated_same_payload_history_uses_latest_action_occurrence_id_only():
    ctx = RuntimeContext(websocket=None, emitter=None, logger=None, clients={})
    ctx.runtime_current_turn_id = 'turn_1'
    payload = 'jin_core/agent/nodes/brain.py'
    ctx.runtime_action_events = [
        {'name': 'attach_file_content', 'payload': payload, 'runtime_turn_id': 'turn_1', 'tool_id': tool_id}
        for tool_id in ('T9', 'T10', 'T11')
    ]

    upsert_session_action_marker_history_since(
        ctx,
        0,
        [{'name': 'ATTACH_FILE_CONTENT', 'payload': payload}],
    )

    assert ctx.runtime_session_action_history[-1]['parts'][0]['tool_ids'] == ['T11']
    assert '[ tool_id: T11 ]' in ctx.runtime_session_action_history[-1]['text']
    assert 'T9' not in ctx.runtime_session_action_history[-1]['text']
    assert 'T10' not in ctx.runtime_session_action_history[-1]['text']
