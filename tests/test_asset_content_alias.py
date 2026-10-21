import json
import unittest
from tests.test_unified_file_attachment import UnifiedFileAttachmentTests
from utils.actions import RuntimeActionCall, RuntimeActionStreamFilter
from utils import attached_files_store as files
from tests.test_attach_file_by_path import PNG
from clients.brain_client import build_brain_user_prompt_content
from utils.context.tool_results import build_tool_results_context


class AssetContentAliasTests(unittest.TestCase):
    setUp = UnifiedFileAttachmentTests.setUp
    execute = UnifiedFileAttachmentTests.execute
    asset = UnifiedFileAttachmentTests.asset

    def test_path_range_uses_native_loader_without_skill(self):
        self.context.runtime_loaded_skills = []
        self.context.runtime_persistent_writes_restricted = True
        entries = self.asset('ATTACH_FILE_CONTENT', attachment=self.project.name, path='src/main.py#L2-L2')
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0]['result']['ok'])
        self.assertEqual(entries[0]['action_name'], 'ATTACH_FILE_CONTENT')
        self.assertIn('needle = 42', build_tool_results_context(self.context))

    def test_id_and_image_reach_prompt(self):
        record, _, _ = files.store_uploaded_file(name='text.txt', content=b'ACTUAL_CONTENT', pin=False)
        entries = self.asset('attach_file_content', id=record['id'])
        self.assertTrue(entries[0]['result']['ok'])
        self.assertIn('ACTUAL_CONTENT', build_tool_results_context(self.context))
        (self.project / 'Photo.PNG').write_bytes(PNG)
        entries = self.asset('ATTACH_FILE_CONTENT', path=f'{self.project.name}/Photo.PNG')
        self.assertTrue(entries[0]['result']['ok'])
        self.assertEqual(len(build_brain_user_prompt_content('continue', self.context)), 2)

    def test_missing_file_fails_without_creating_it(self):
        entries = self.asset('ATTACH_FILE_CONTENT', path=f'{self.project.name}/missing.txt')
        self.assertFalse(entries[0]['result']['ok'])
        self.assertFalse((self.project / 'missing.txt').exists())

    def test_all_stream_boundaries(self):
        text = '<ASSET_ACTION>{"action":"ATTACH_FILE_CONTENT","path":"Folder/Photo.PNG"}</ASSET_ACTION>'
        for cut in range(len(text) + 1):
            parser = RuntimeActionStreamFilter(enabled_actions=['ASSET_ACTION'])
            results = [parser.filter('before ' + text[:cut]), parser.filter(text[cut:] + ' after'), parser.flush_result()]
            actions = [a for r in results for a in r.actions]
            self.assertEqual([(a.name, a.payload) for a in actions], [('ATTACH_FILE_CONTENT', 'Folder/Photo.PNG')])
            self.assertEqual(''.join(r.text for r in results).split(), ['before', 'after'])

    def test_quoted_incomplete_false_prefix(self):
        for text in ('`<ASSET_ACTION>{"action":"ATTACH_FILE_CONTENT","path":"x.txt"}</ASSET_ACTION>`', '<ASSET_ACTION>{"action":"ATTACH_FILE_CONTENT"', '<ASSET_ACTION_EXAMPLE>'):
            parser = RuntimeActionStreamFilter(enabled_actions=['ASSET_ACTION'])
            results = [parser.filter(c) for c in text] + [parser.flush_result()]
            self.assertFalse([a for r in results for a in r.actions])

    def test_ambiguous_or_invalid_payload_is_not_forwarded(self):
        for fields in ({}, {'path': []}, {'path': ''}, {'id': 'a', 'path': 'b'}, {'path': 'a,b'}):
            action = RuntimeActionCall('ASSET_ACTION', json.dumps(dict(action='ATTACH_FILE_CONTENT', **fields)))
            self.assertEqual(action.name, 'ASSET_ACTION')

    def test_exact_archived_paths_payloads(self):
        (self.project / '1.png').write_bytes(PNG)
        for paths in ([f'{self.project.name}/1.png', f'{self.project.name}/1.txt'], ['1.png', '1.txt']):
            entries = self.asset('ATTACH_FILE_CONTENT', attachment=self.project.name, paths=paths)
            self.assertEqual(len(entries), 2)
            self.assertTrue(entries[0]['result']['ok'])
            self.assertFalse(entries[1]['result']['ok'])
            self.assertTrue(all(e['action_name'] == 'ATTACH_FILE_CONTENT' for e in entries))
            self.assertEqual(len(build_brain_user_prompt_content('continue', self.context)), 2)
            self.assertFalse((self.project / '1.txt').exists())

    def test_plural_stream_all_boundaries(self):
        text = '<ASSET_ACTION>{"action":"ATTACH_FILE_CONTENT","attachment":"caption_test","paths":["caption_test/1.png","1.txt"]}</ASSET_ACTION>'
        for cut in range(len(text) + 1):
            parser = RuntimeActionStreamFilter(enabled_actions=['ASSET_ACTION'])
            results = [parser.filter(text[:cut]), parser.filter(text[cut:]), parser.flush_result()]
            actions = [a for r in results for a in r.actions]
            self.assertEqual([a.payload for a in actions], ['caption_test/1.png', 'caption_test/1.txt'])
            self.assertTrue(all(a.name == 'ATTACH_FILE_CONTENT' for a in actions))
            self.assertEqual(actions[0].marker_group, actions[1].marker_group)

    def test_asset_whole_files_emit_only_owner_bubble(self):
        from pathlib import Path
        (self.project / 'Photo.PNG').write_bytes(PNG)
        before = len(self.context.emitter.events)
        entries = self.asset('ATTACH_FILE_BY_PATH', attachment=self.project.name, paths=['Photo.PNG', 'missing.txt'])
        self.assertEqual(len(entries), 2)
        self.assertTrue(entries[0]['result']['ok'])
        self.assertFalse(entries[1]['result']['ok'])
        events = [e for e in self.context.emitter.events[before:] if e.get('type') == 'runtime_action']
        self.assertTrue(events)
        self.assertTrue(all(e['action'] == 'asset_action' for e in events), events)
        terminal = [e for e in events if e.get('status') in ('completed', 'failed')]
        self.assertEqual(len(terminal), 1)
        self.assertEqual(terminal[0]['status'], 'failed')
        self.assertIn('Photo.PNG', terminal[0]['detail'])
        self.assertIn('missing.txt', terminal[0]['detail'])
        Path('.tmp').mkdir(exist_ok=True)
        Path('.tmp/asset-owner-events.json').write_text(json.dumps(events), encoding='utf-8')
