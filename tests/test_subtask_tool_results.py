"""Tool-result ownership follows the same ephemeral subtask lifecycle as SUB-AM."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from utils.actions import RuntimeActionCall
from utils.actions.dispatcher import apply_runtime_action_calls
from utils.actions.jin_instance_actions import active_child, mark_child_started, interrupt_instance_group
from utils.subtask_memory import discard_orphan_tool_results
from utils.tool_results import (
    record_runtime_tool_result, clean_runtime_tool_results_by_ids,
    clean_runtime_tool_result,
)
from websocket.bootstrap import clean_bootstrap_tool_results
from runtime.frame_memory_utils import build_runtime_session_checkpoint


def instance_context():
    parent = SimpleNamespace(
        runtime_tool_results=[], runtime_tool_result_created_ats=[],
        runtime_tool_result_sequence=0, runtime_tool_results_turn_count=0,
        runtime_action_events=[], runtime_current_turn_id='turn',
        runtime_jin_instance_group={
            'phase': 'child_pending', 'active_index': 0,
            'tasks': [
                dict(subtask_agent_id='first', ordinal=1, session_id='c1', conditions='a', status='pending'),
                dict(subtask_agent_id='second', ordinal=2, session_id='c2', conditions='b', status='pending'),
            ],
        },
        active_memory_records=[], runtime_memory='', runtime_memory_stable='',
    )
    return parent


def test_parent_and_each_child_independent_numbering_and_cleanup():
    c = instance_context()
    with patch('utils.chat_log.append_chat_runtime_event'):
        record_runtime_tool_result(c, 'search', 'parent evidence')
        assert c.runtime_tool_results[-1]['tool_id'] == 'T1'
        mark_child_started(c)
        record_runtime_tool_result(c, 'search', 'first evidence')
        record_runtime_tool_result(c, 'asset', {'ok': False, 'detail': 'failed'})
        assert [e['tool_id'] for e in c.runtime_tool_results] == ['T1', 'SUB_T1', 'SUB_T2']
        assert [e.get('owner_subtask_agent_id') for e in c.runtime_tool_results] == [None, 'first', 'first']
        assert c.runtime_tool_result_sequence == 1
        assert c.runtime_tool_result_created_ats and len(c.runtime_tool_result_created_ats) == 3
        from utils.tool_results import remove_runtime_tool_results
        remove_runtime_tool_results(c, lambda e: e.get('owner_subtask_agent_id') == 'first')
        assert [e['tool_id'] for e in c.runtime_tool_results] == ['T1']
        assert len(c.runtime_tool_result_created_ats) == 1
        c.runtime_jin_instance_group['tasks'][0]['status'] = 'completed'
        c.runtime_jin_instance_group['phase'] = 'child_pending'
        c.runtime_jin_instance_group['active_index'] = 1
        mark_child_started(c)
        record_runtime_tool_result(c, 'files', {'ok': True})
        assert [e['tool_id'] for e in c.runtime_tool_results] == ['T1', 'SUB_T1']
        assert c.runtime_tool_results[-1]['owner_subtask_agent_id'] == 'second'


def test_child_cannot_clean_inherited_parent_results_and_empty_clear_is_local():
    c = instance_context()
    with patch('utils.chat_log.append_chat_runtime_event'):
        record_runtime_tool_result(c, 'search', 'parent evidence')
        mark_child_started(c)
        record_runtime_tool_result(c, 'search', 'child evidence')
        assert not clean_runtime_tool_result(c, 'T1')
        assert not clean_runtime_tool_results_by_ids(c, ['SUB_T1', 'T1'])
        assert [e['tool_id'] for e in c.runtime_tool_results] == ['T1', 'SUB_T1']
        assert clean_runtime_tool_results_by_ids(c, ['SUB_T1'])
        record_runtime_tool_result(c, 'files', {'ok': True})
    with patch('utils.actions.dispatcher.ensure_assets_tree'), patch('utils.chat_log.append_chat_runtime_event'):
        asyncio.run(apply_runtime_action_calls(c, (RuntimeActionCall(name='CLEAN_TOOL_RESULTS', payload=''),)))
    assert [e['tool_id'] for e in c.runtime_tool_results] == ['T1']


def test_interrupt_removes_all_child_results_including_failures():
    c = instance_context()
    with patch('utils.chat_log.append_chat_runtime_event'):
        record_runtime_tool_result(c, 'search', 'parent')
        mark_child_started(c)
        record_runtime_tool_result(c, 'files', {'ok': False, 'detail': 'bad'})
        record_runtime_tool_result(c, 'search', 'child')
    c.runtime_jin_instance_group['tasks'][0]['status'] = 'running'
    with patch('runtime.memory_profile.refresh_profile'), patch('runtime.memory_profile.commit_active'):
        interrupt_instance_group(c, 'cancel')
    assert [e['tool_id'] for e in c.runtime_tool_results] == ['T1']
    assert c.runtime_failure_followup_tool_ids == []
    assert c.runtime_failure_followup_entries == []


def test_orphan_cleanup_and_bootstrap_exclude_sub_t_even_without_owner():
    c = instance_context()
    with patch('utils.chat_log.append_chat_runtime_event'):
        record_runtime_tool_result(c, 'search', 'parent')
        mark_child_started(c)
        record_runtime_tool_result(c, 'search', 'child')
    child = c.runtime_tool_results[-1].copy()
    orphan = child.copy()
    orphan.pop('owner_subtask_agent_id')
    c.runtime_jin_instance_group['phase'] = 'interrupted'
    c.runtime_jin_instance_group['active_index'] = None
    c.runtime_tool_results.append(orphan)
    c.runtime_tool_result_created_ats.append(None)
    discard_orphan_tool_results(c)
    assert [e['tool_id'] for e in c.runtime_tool_results] == ['T1']
    results, _ = clean_bootstrap_tool_results([child, orphan, c.runtime_tool_results[0]])
    assert [e['tool_id'] for e in results] == ['T1']
