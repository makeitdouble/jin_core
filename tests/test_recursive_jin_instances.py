"""Part 1: real Brain loop and dispatcher, deterministic model replies, no provider."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from agent.nodes.brain import BrainNode
from agent.state import AgentState
from tests.helpers.brain import brain_context_stub, brain_runtime_config
from utils.actions import RuntimeActionCall
from utils.actions.dispatcher import apply_runtime_action_calls
from utils.actions.jin_instance_actions import (
    active_child, instance_groups, mark_child_started, mark_parent_returned,
    restore_parent_reasoning, interrupt_instance_group,
)
from utils.tool_results import record_runtime_tool_result


class RecursiveInstancesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.c = c = brain_context_stub()
        c.logger = SimpleNamespace(log_runtime=AsyncMock())
        c.websocket = SimpleNamespace(send_json=AsyncMock())
        c.emitter = SimpleNamespace(emit=AsyncMock())
        c.runtime_turn_user_message = 'ROOT_INTENTION'
        c.runtime_persistent_writes_restricted = True
        c.runtime_lt_file_store_enabled = False
        c.runtime_current_turn_id = c.runtime_current_sequence_turn_id = 'recursive-test'
        c.runtime_current_sequence_jin_messages = []
        c.runtime_tool_results = []
        c.runtime_memory = 'fixed FRAME'
        c.active_memory_records = []
        c.session_id = 'root-session'
        c.memory_profile_root = Path(self.temp.name)
        self.state = AgentState(user_input=c.runtime_turn_user_message)
        self.runtime = brain_runtime_config()
        self.runtime['runtime_actions'].update(CAN_CREATE_JIN_INSTANCES=True, CAN_FINISH_SUBTASK=True)
        self.groups = []
        self.trace = []
        self.log_patch = patch('utils.chat_log.append_chat_runtime_event')
        self.log_patch.start()
        self.addCleanup(self.log_patch.stop)
        self.event_patch = patch('utils.actions.jin_instance_actions.append_chat_runtime_event')
        self.event_patch.start()
        self.addCleanup(self.event_patch.stop)

    async def action(self, name, payload):
        await apply_runtime_action_calls(self.c, (RuntimeActionCall(name=name, payload=json.dumps(payload)),))

    async def create(self, *conditions):
        await self.action('CREATE_JIN_INSTANCES', [
            {'id': index, 'conditions': value} for index, value in enumerate(conditions, 1)
        ])
        self.groups.append(self.c.runtime_jin_instance_group)

    async def finish(self, reason=None):
        task = active_child(self.c)
        await self.action('FINISH_SUBTASK', {
            'subtask_agent_id': task['subtask_agent_id'], 'session_id': task['session_id'],
            'finish_reason': reason or 'done ' + task['conditions'],
        })

    async def run_model(self, stream, *, limit=16, tree_budget=256):
        with patch('agent.nodes.brain.get_brain_runtime_config', return_value=self.runtime), \
             patch('agent.nodes.brain.build_brain_payload', return_value='payload'), \
             patch('agent.nodes.brain.config.BRAIN_MAX_FOLLOWUPS', limit), \
             patch('agent.nodes.brain.config.JIN_MAX_INSTANCE_TICKS', tree_budget, create=True), \
             patch.object(BrainNode, 'run_brain_stream', side_effect=stream):
            await BrainNode().run(self.state, self.c)

    async def test_three_levels_return_to_immediate_parent_and_run_siblings(self):
        counts = {}
        ids = {}
        plans = {}

        async def stream(**kw):
            task = active_child(self.c)
            name = task['conditions'] if task else 'MAIN'
            counts[name] = counts.get(name, 0) + 1
            self.trace.append(name)
            self.assertLess(len(self.trace), 15)
            prompt = kw['system_prompt']
            if task:
                ids[name] = task['instance_id']
                self.assertEqual(prompt.count('<JIN_SUBTASK_INSTANCE>'), 1)
                self.assertIn(task['session_id'], prompt)
                self.assertTrue(kw['runtime_actions']['CAN_CREATE_JIN_INSTANCES'])
                self.assertTrue(kw['runtime_actions']['CAN_FINISH_SUBTASK'])
            if counts[name] == 1:
                plans[name] = 'PRIVATE_PLAN_' + name
                self.c.runtime_previous_reasoning_content = plans[name]
                self.c.runtime_current_sequence_jin_messages.append({'text': 'dialogue ' + name})
                if name == 'MAIN':
                    await self.create('A', 'D')
                elif name == 'A':
                    await self.create('B', 'B2')
                elif name == 'B':
                    await self.create('C')
                else:
                    await self.finish()
            else:
                self.assertEqual(self.c.runtime_previous_reasoning_content, plans[name])
                self.assertEqual(self.c.runtime_current_sequence_jin_messages[-1]['text'], 'dialogue ' + name)
                self.assertIn('<JIN_INSTANCES_RETURN_TO_PARENT>', prompt)
                if task:
                    self.assertEqual(task['status'], 'running')
                    child_name = 'C' if name == 'B' else 'B'
                    report = next(e for e in self.c.runtime_tool_results if e.get('id') == ids[child_name])
                    self.assertEqual(report['owner_subtask_agent_id'], task['instance_id'])
                    await self.finish()
                else:
                    self.assertFalse(kw['runtime_actions']['CAN_FINISH_SUBTASK'])
                    self.assertNotIn('<JIN_SUBTASK_INSTANCE>', prompt)
                    return 'final MAIN', 'root final'
            return '', ''

        await self.run_model(stream)
        self.assertEqual(self.trace, ['MAIN', 'A', 'B', 'C', 'B', 'B2', 'A', 'D', 'MAIN'])
        self.assertEqual(self.state.brain_response, 'final MAIN')
        self.assertEqual(self.c.runtime_jin_instance_stack, [])
        self.assertTrue(all(g['phase'] == 'completed' for g in self.groups))
        self.assertEqual(self.groups[1]['parent_instance_id'], ids['A'])
        self.assertEqual(self.groups[2]['parent_instance_id'], ids['B'])
        self.assertEqual(len(set(ids.values())), len(ids))
        self.assertFalse(any(e.get('owner_subtask_agent_id') for e in self.c.runtime_tool_results))

    async def test_create_barrier_prevents_overwrite_and_wrong_owner_actions(self):
        await self.create('A')
        mark_child_started(self.c)
        a = active_child(self.c)
        await self.create('B')
        b_group = self.c.runtime_jin_instance_group
        await self.action('CREATE_JIN_INSTANCES', {'id': 1, 'conditions': 'overwrite'})
        await self.action('FINISH_SUBTASK', {'subtask_agent_id': a['subtask_agent_id'],
                                           'session_id': a['session_id'], 'finish_reason': 'too early'})
        self.assertIs(self.c.runtime_jin_instance_group, b_group)
        self.assertEqual(a['status'], 'running')
        self.assertEqual(b_group['tasks'][0]['status'], 'pending')
        self.assertEqual(len(self.c.runtime_jin_instance_stack), 1)
        mark_child_started(self.c)
        await self.action('FINISH_SUBTASK', {'subtask_agent_id': a['subtask_agent_id'],
                                           'session_id': a['session_id'], 'finish_reason': 'wrong owner'})
        self.assertEqual(active_child(self.c)['status'], 'running')
        self.assertFalse(self.c.runtime_tool_results[-1]['result']['ok'])
        interrupt_instance_group(self.c)

    async def test_suspended_memory_is_not_reaped_and_cleanup_is_owner_scoped(self):
        from runtime.memory_profile import refresh_profile
        from utils.subtask_memory import owner
        self.c.memory_profile_enabled = True
        self.c.websocket.app = SimpleNamespace(state=SimpleNamespace(websocket_runtime_contexts={'root': self.c}))
        await self.action('SAVE_ACTIVE_MEMORY', {'conditions': 'MAIN memory'})
        original = self.c.active_memory_records[0]
        await self.create('A')
        mark_child_started(self.c)
        a = active_child(self.c)
        await self.action('SAVE_ACTIVE_MEMORY', {'conditions': 'A memory'})
        record_runtime_tool_result(self.c, 'search', 'A private evidence')
        parent_results = deepcopy(self.c.runtime_tool_results)
        await self.create('B')
        mark_child_started(self.c)
        b = active_child(self.c)
        await self.action('SAVE_ACTIVE_MEMORY', {'conditions': 'B memory'})
        record_runtime_tool_result(self.c, 'search', 'B private evidence')
        refresh_profile(self.c)
        self.assertEqual({owner(r) for r in self.c.active_memory_records}, {'', a['instance_id'], b['instance_id']})
        await self.finish()
        group = self.c.runtime_jin_instance_group
        restore_parent_reasoning(self.c)
        mark_parent_returned(self.c, group)
        self.assertIs(active_child(self.c), a)
        self.assertEqual({owner(r) for r in self.c.active_memory_records}, {'', a['instance_id']})
        self.assertEqual(self.c.runtime_tool_results[:len(parent_results)], parent_results)
        self.assertNotIn('B private evidence', str(self.c.runtime_tool_results))
        await self.finish()
        self.assertEqual(self.c.active_memory_records, [original])
        self.assertFalse(any(e.get('owner_subtask_agent_id') for e in self.c.runtime_tool_results))

    async def test_shared_budget_bounds_delegation_with_unlimited_followups(self):
        async def stream(**kw):
            self.trace.append(kw)
            if kw.get('preserve_runtime_action_markers'):
                self.assertIsNone(active_child(self.c))
                self.assertFalse(any(kw['runtime_actions'].values()))
                self.assertIn('Shared JIN instance execution budget exhausted (5 ticks)', kw['system_prompt'])
                return 'bounded', ''
            await self.create('recursive task')
            return '', ''
        await self.run_model(stream, limit=0, tree_budget=5)
        self.assertEqual(len(self.trace), 7)  # Initial call, 5 ticks, final summary.
        self.assertEqual(self.c.runtime_jin_instance_stack, [])
        self.assertTrue(all(g['phase'] == 'interrupted' for g in self.groups))
        self.assertEqual(self.state.brain_response, 'bounded')

    async def test_followup_budget_is_restored_not_reset_by_nested_return(self):
        counts = {}
        async def stream(**kw):
            task = active_child(self.c)
            name = task['conditions'] if task else 'MAIN'
            self.trace.append(name)
            counts[name] = counts.get(name, 0) + 1
            if kw.get('preserve_runtime_action_markers'):
                self.assertIsNone(task)
                return 'limit', ''
            if name == 'MAIN':
                await self.create('A')
            elif name == 'A' and counts[name] == 1:
                record_runtime_tool_result(self.c, 'asset', {'action': 'list_skills', 'ok': True})
            elif name == 'A' and counts[name] == 2:
                await self.create('B')
            elif name == 'B':
                await self.finish()
            else:
                self.fail('A exhausted its budget before launching B; must not get a fresh budget')
            return '', ''
        await self.run_model(stream, limit=2)
        self.assertEqual(self.trace, ['MAIN', 'A', 'A', 'B', 'MAIN'])
        self.assertEqual(self.groups[0]['tasks'][0]['status'], 'interrupted')

    async def test_provider_failure_unwinds_to_main_without_leaking_children(self):
        async def stream(**kw):
            depth = len(instance_groups(self.c)) if active_child(self.c) else 0
            if depth == 0:
                self.c.runtime_previous_reasoning_content = 'ROOT plan'
            if depth < 3:
                await self.create(str(depth))
                return '', ''
            record_runtime_tool_result(self.c, 'search', 'failed child scratch')
            raise RuntimeError('provider failed')
        with self.assertRaisesRegex(RuntimeError, 'provider failed'):
            await self.run_model(stream)
        self.assertEqual(self.c.runtime_jin_instance_stack, [])
        self.assertEqual(self.c.runtime_previous_reasoning_content, 'ROOT plan')
        self.assertFalse(any(e.get('owner_subtask_agent_id') for e in self.c.runtime_tool_results))
        self.assertTrue(all(g['phase'] == 'interrupted' for g in self.groups))

    async def test_resumed_child_can_create_another_group_and_recover(self):
        counts = {}
        async def stream(**kw):
            task = active_child(self.c)
            name = task['conditions'] if task else 'MAIN'
            self.trace.append(name)
            counts[name] = counts.get(name, 0) + 1
            if name == 'MAIN':
                if counts[name] == 1:
                    await self.create('A')
                else:
                    return 'done', ''
            elif name == 'A':
                if counts[name] == 1:
                    await self.create('B')
                elif counts[name] == 2:
                    await self.create('C')
                else:
                    await self.finish()
            elif name == 'C' and counts[name] == 1:
                self.c.runtime_context_limit_recovery_pending = True
                self.c.runtime_context_limit_kind = 'output'
                self.c.runtime_context_limit_stage = 'reasoning'
            else:
                self.assertEqual(kw['system_prompt'].count('<JIN_SUBTASK_INSTANCE>'), 1)
                self.assertIn(task['session_id'], kw['system_prompt'])
                self.assertTrue(kw['runtime_actions']['CAN_CREATE_JIN_INSTANCES'])
                await self.finish()
            return '', ''
        await self.run_model(stream)
        self.assertEqual(self.trace, ['MAIN', 'A', 'B', 'A', 'C', 'C', 'A', 'MAIN'])
        self.assertTrue(all(g['phase'] == 'completed' for g in self.groups))
        self.assertEqual(self.c.runtime_jin_instance_stack, [])

    async def test_pending_grandchild_cancellation_keeps_ancestors_live_until_cleanup(self):
        from utils.subtask_memory import live_owners
        await self.create('A', 'A2')
        mark_child_started(self.c)
        a = active_child(self.c)
        await self.create('B', 'B2')
        mark_child_started(self.c)
        b = active_child(self.c)
        await self.create('C')  # Stop between registration and the first C tick.
        self.assertEqual(live_owners(self.c), {a['instance_id'], b['instance_id']})
        interrupt_instance_group(self.c, 'stopped_by_user')
        self.assertEqual(live_owners(self.c), set())
        self.assertEqual([g['tasks'][0]['status'] for g in self.groups],
                         ['interrupted', 'interrupted', 'cancelled'])
        self.assertEqual(self.groups[0]['tasks'][1]['status'], 'cancelled')
        self.assertEqual(self.groups[1]['tasks'][1]['status'], 'cancelled')

    async def test_deep_stack_unwinds_without_python_recursion(self):
        # No model calls or heavyweight context snapshots; stress the execution
        # stack itself beyond Python's normal recursion limit.
        self.c.runtime_previous_reasoning_content = 'root'
        frames = []
        for index in range(1100):
            frames.append({'group_id': str(index), 'phase': 'child_running', 'active_index': 0,
                           'tasks': [{'ordinal': 1, 'subtask_agent_id': str(index), 'status': 'running'}],
                           'parent_reasoning_state': {'runtime_previous_reasoning_content': 'root' if index == 0 else str(index)}})
        self.c.runtime_jin_instance_stack = frames[:-1]
        self.c.runtime_jin_instance_group = frames[-1]
        with patch('utils.subtask_memory.cleanup_child_memory'):
            interrupt_instance_group(self.c)
        self.assertEqual(self.c.runtime_jin_instance_stack, [])
        self.assertEqual(self.c.runtime_previous_reasoning_content, 'root')
        self.assertTrue(all(g['phase'] == 'interrupted' for g in frames))

    async def test_stop_at_depth_three_cleans_tree_and_preserves_main(self):
        from websocket.tasks import cancel_current_task
        self.c.active_streams = {}
        entered = asyncio.Event()
        async def stream(**kw):
            if not active_child(self.c):
                self.c.runtime_previous_reasoning_content = 'ROOT plan'
            if len(self.groups) < 3:
                await self.create('level ' + str(len(self.groups)))
                return '', ''
            record_runtime_tool_result(self.c, 'search', 'C scratch')
            try:
                entered.set()
                await asyncio.Event().wait()
            finally:
                self.c.runtime_previous_reasoning_content += 'C tail'
        task = asyncio.create_task(self.run_model(stream))
        await asyncio.wait_for(entered.wait(), 10)
        await cancel_current_task(task, self.c.logger, self.c, update_memory=False, emit_aborted_actions=False)
        self.assertEqual(self.c.runtime_jin_instance_stack, [])
        self.assertEqual(self.c.runtime_previous_reasoning_content, 'ROOT plan')
        self.assertTrue(all(g['phase'] == 'interrupted' for g in self.groups))
        self.assertFalse(any(e.get('owner_subtask_agent_id') for e in self.c.runtime_tool_results))


if __name__ == '__main__':
    unittest.main()
