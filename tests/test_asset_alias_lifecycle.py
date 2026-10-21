import asyncio
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from runtime.stream import RuntimeStream
from tests.helpers.runtime_stream import FakeEmitter, FakeLogger, FakeWebSocket
from utils.actions import RuntimeActionStreamFilter

class AssetAliasLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def test_no_speculative_asset_at_every_boundary(self):
        for payload in ({'action':'create_jin_instances','id':1,'conditions':'task'}, {'action':'ATTACH_FILE_CONTENT','paths':['folder/1.png','folder/1.txt']}):
            text = '<ASSET_ACTION>' + json.dumps(payload) + '</ASSET_ACTION>'
            for cut in range(len(text)+1):
                parser = RuntimeActionStreamFilter(enabled_actions=['ASSET_ACTION'])
                results = [parser.filter(text[:cut]), parser.filter(text[cut:]), parser.flush_result()]
                self.assertFalse([a for r in results for a in r.started_actions if a.name == 'ASSET_ACTION'], (payload,cut))
                self.assertTrue([a for r in results for a in r.actions])

    async def test_stream_events_render_without_orphan_asset(self):
        scenarios = []
        for payload in ({'action':'create_jin_instances','id':1,'conditions':'task'}, {'action':'ATTACH_FILE_CONTENT','path':'missing.txt'}):
            context = SimpleNamespace(websocket=FakeWebSocket(), logger=FakeLogger(), emitter=FakeEmitter(),
                                      runtime_action_events=[], runtime_usage_events=[], runtime_asset_results=[],
                                      runtime_persistent_writes_restricted=True, active_memory_records=[], runtime_loaded_skills=[])
            async def chunks():
                for char in '<ASSET_ACTION>' + json.dumps(payload) + '</ASSET_ACTION>':
                    yield {'type':'content','content':char}
            stream = RuntimeStream(context=context, runtime_id='brain', role='brain', context_window=8192,
                                   log_method=context.logger.log_service, runtime_actions={'CAN_USE_ASSETS':True})
            with patch('utils.chat_log.append_chat_runtime_event'):
                await stream.run(chunks())
            events = [e for e in context.emitter.events if e.get('type') == 'runtime_action']
            self.assertFalse([e for e in events if e.get('action') == 'asset_action'])
            self.assertTrue([e for e in events if e.get('status') in ('completed','failed')])
            scenarios.append(events)
        Path('.tmp').mkdir(exist_ok=True)
        Path('.tmp/asset-alias-events.json').write_text(json.dumps(scenarios), encoding='utf-8')
