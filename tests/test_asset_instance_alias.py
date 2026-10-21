import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from utils.actions import RuntimeActionCall, RuntimeActionStreamFilter
from utils.actions.dispatcher import apply_runtime_action_calls


class AssetInstanceTests(unittest.IsolatedAsyncioTestCase):
    def call(self, **fields):
        return RuntimeActionCall('ASSET_ACTION', json.dumps(dict(action='create_jin_instances', id=1, conditions='Caption first image', **fields)))

    async def test_restricted_parent_creates_once_and_child_cannot_nest(self):
        context = SimpleNamespace(runtime_persistent_writes_restricted=True,
                                  runtime_tool_results=[], runtime_action_events=[],
                                  emitter=SimpleNamespace(emit=AsyncMock()))
        action = self.call()
        self.assertEqual(action.name, 'CREATE_JIN_INSTANCES')
        await apply_runtime_action_calls(context, (action,))
        group = context.runtime_jin_instance_group
        self.assertEqual(len(group['tasks']), 1)
        self.assertEqual(group['tasks'][0]['conditions'], 'Caption first image')
        self.assertTrue(context.runtime_tool_results[-1]['result']['ok'])
        await apply_runtime_action_calls(context, (self.call(),))
        self.assertIs(context.runtime_jin_instance_group, group)
        self.assertEqual(context.runtime_tool_results[-1]['result']['error'], 'nested_group')
        self.assertTrue(any(call.args[0].get('status') == 'completed' for call in context.emitter.emit.call_args_list))

    async def test_invalid_assignment_uses_native_validation(self):
        context = SimpleNamespace(runtime_persistent_writes_restricted=True, runtime_tool_results=[])
        action = RuntimeActionCall('ASSET_ACTION', '{"action":"create_jin_instances","id":true,"conditions":"task"}')
        await apply_runtime_action_calls(context, (action,))
        self.assertEqual(context.runtime_tool_results[-1]['result']['error'], 'invalid_payload')
        self.assertFalse(getattr(context, 'runtime_jin_instance_group', {}))

    def test_stream_all_boundaries(self):
        text = '<ASSET_ACTION>{"action":"create_jin_instances","id":1,"conditions":"task"}</ASSET_ACTION>'
        for cut in range(len(text) + 1):
            parser = RuntimeActionStreamFilter(enabled_actions=['ASSET_ACTION'])
            results = [parser.filter('before ' + text[:cut]), parser.filter(text[cut:] + ' after'), parser.flush_result()]
            actions = [a for r in results for a in r.actions]
            self.assertEqual([a.name for a in actions], ['CREATE_JIN_INSTANCES'], cut)
            self.assertEqual(''.join(r.text for r in results).split(), ['before', 'after'])

    def test_literal_incomplete_false_prefix(self):
        for text in ('`<ASSET_ACTION>{"action":"create_jin_instances","id":1,"conditions":"task"}</ASSET_ACTION>`', '<ASSET_ACTION>{"action":"create_jin_instances"', '<ASSET_ACTION_EXAMPLE>'):
            parser = RuntimeActionStreamFilter(enabled_actions=['ASSET_ACTION'])
            results = [parser.filter(c) for c in text] + [parser.flush_result()]
            self.assertFalse([a for r in results for a in r.actions])

    def test_real_asset_writes_stay_restricted(self):
        from runtime.anonymous_mode import runtime_action_write_is_restricted
        context = SimpleNamespace(runtime_persistent_writes_restricted=True)
        action = RuntimeActionCall('ASSET_ACTION', '{"action":"create_asset_file","path":"x.txt"}')
        self.assertEqual(action.name, 'ASSET_ACTION')
        self.assertTrue(runtime_action_write_is_restricted(context, action.name, action.payload))
