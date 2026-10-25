import asyncio
import base64
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests import test_project_review as fixture
from clients.brain_client import build_brain_user_prompt_content
from contracts.rules_assembler import build_runtime_action_instructions, get_enabled_runtime_actions
from runtime.frame_memory_utils import build_runtime_session_checkpoint
from utils import attached_files_store as files
from utils.actions import RuntimeActionStreamFilter, extract_runtime_actions
from utils.actions.attachment_actions import apply_attachment_context_ids, clear_path_attachments
from utils.actions.dispatcher import apply_runtime_action_calls
from utils.context.tool_results import build_tool_results_context
from utils.context.session_actions import build_session_actions_history_context
from utils.session_actions_history import upsert_session_action_marker_history_since
from utils.python_skill_asset_utils import run_context_asset_action
from websocket.bootstrap import apply_bootstrap_tool_results
from agent.nodes.brain import BrainNode, consume_action_failure_followup_context

ACTION = 'ATTACH_FILE_BY_PATH'
MARKER = 'ATTACH_FILE_BY_PATH'
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')

class AttachFileByPathTests(unittest.TestCase):
    setUp = fixture.ProjectReviewTests.setUp

    def attach(self, payload, message='m1'):
        actions = extract_runtime_actions('<ASSET_ACTION>' + json.dumps({'action': ACTION, 'paths': payload.split(', ')}) + '</ASSET_ACTION>', enabled_actions=['ASSET_ACTION']).actions
        self.assertTrue(actions)
        start = len(self.context.runtime_session_action_history)
        before = {e['tool_id'] for e in self.context.runtime_tool_results}
        with patch('utils.actions.dispatcher.ensure_assets_tree'), patch('utils.chat_log.append_chat_runtime_event'):
            asyncio.run(apply_runtime_action_calls(self.context, actions, runtime_message_id=message))
        upsert_session_action_marker_history_since(self.context, start, [{'name': a.name, 'payload': a.payload} for a in actions])
        return [e['result'] for e in self.context.runtime_tool_results if e['tool_id'] not in before]

    def pair(self, number):
        (self.project / f'Photo_{number}.PNG').write_bytes(PNG)
        (self.project / f'Caption_{number}.txt').write_text(f'CAPTION_{number}\nUnicode: Привет', encoding='utf-8')
        return f'{self.project.name}/Photo_{number}.PNG, {self.project.name}/Caption_{number}.txt'

    def test_image_text_followup_replacement_pinned_and_history(self):
        pinned, _, _ = files.store_uploaded_file(name='user.txt', content=b'USER_PINNED', pin=True)
        apply_attachment_context_ids(self.context, [self.record['id'], pinned['id']])
        first = self.attach(self.pair('035'))
        self.assertTrue(all(r['ok'] for r in first), first)
        prompt = BrainNode.build_followup_system_prompt(fixture.build_brain_context(self.context, runtime_actions=fixture.BRAIN_RUNTIME_ACTIONS), 'caption dataset', context=self.context)
        self.assertEqual(prompt.count('CAPTION_035'), 1)
        payload = build_brain_user_prompt_content('continue', self.context)
        self.assertEqual(base64.b64decode(payload[1]['image_url']['url'].split(',')[1]), PNG)
        self.assertEqual(len(payload), 2)
        second = self.attach(self.pair('036'), 'm2')
        self.assertTrue(all(r['ok'] for r in second), second)
        tools = build_tool_results_context(self.context)
        self.assertNotIn('CAPTION_035', tools)
        self.assertEqual(tools.count('CAPTION_036'), 1)
        self.assertIn('USER_PINNED', tools)
        self.assertTrue(all(r['loaded'] is False for r in first))
        self.assertEqual(len(build_brain_user_prompt_content('next', self.context)), 2)
        self.assertIn(self.record['id'], self.context.runtime_attached_file_ids)
        self.assertEqual(len(files.list_file_records()), 2)
        history = build_session_actions_history_context(self.context)
        self.assertIn('Photo_036.PNG', history)
        self.assertIn(ACTION, history)
        events = [e for e in self.context.emitter.events if e.get('attachment_results')]
        self.assertEqual(len(events), 2)
        self.assertTrue(all(len(e['attachment_results']) == 2 for e in events))
        self.assertFalse(any(e.get('attachment_result') for e in self.context.emitter.events))
        self.assertTrue(all(e['status'] == 'completed' for e in events))
        self.assertNotIn('base64', json.dumps(events))
        # Pinning another persistent file does not erase the current path set.
        apply_attachment_context_ids(self.context, self.context.runtime_attached_file_ids)
        self.assertEqual(len(build_brain_user_prompt_content('next', self.context)), 2)

    def test_clear_and_prune_keep_non_dict_tool_results(self):
        first = self.attach(self.pair('035'))
        other_results = [
            {'kind': 'search', 'result': 'old search text'},
            {'kind': 'search', 'result': None},
        ]
        self.context.runtime_tool_results[:0] = other_results
        from utils.actions.attachment_actions import prune_path_attachments
        prune_path_attachments(self.context)
        self.assertEqual(self.context.runtime_tool_results[:2], other_results)
        # Attaching a different group clears old path bytes and history without
        # crashing on results owned by another runtime action.
        self.assertTrue(all(r['ok'] for r in self.attach(self.pair('036'), 'm2')))
        self.assertEqual(self.context.runtime_tool_results[:2], other_results)
        self.assertFalse(first[0]['loaded'])
        self.assertEqual(len(build_brain_user_prompt_content('next', self.context)), 2)
        clear_path_attachments(self.context)
        self.assertEqual(self.context.runtime_tool_results[:2], other_results)
        self.assertEqual(build_brain_user_prompt_content('next', self.context), 'next')

    def test_missing_failure_followup_and_replacing_prior_set(self):
        self.attach(self.pair('035'))
        result = self.attach('missing.png', 'm2')[0]
        self.assertFalse(result['ok'])
        self.assertEqual(result['error'], 'file_not_found')
        self.assertIn('Correct action schema:', build_tool_results_context(self.context))
        self.assertIn(MARKER, build_tool_results_context(self.context))
        self.assertIn(ACTION, consume_action_failure_followup_context(self.context))
        self.assertEqual(build_brain_user_prompt_content('next', self.context), 'next')

    def test_invalid_paths_types_limits_and_no_implicit_root(self):
        (self.project / 'bad.exe').write_bytes(b'abc')
        (self.project / 'bad.png').write_bytes(b'not an image')
        (self.project / 'bad.txt').write_bytes(b'\xff\x00')
        (self.project / 'huge.txt').write_text('x' * 32001)
        for i, path in enumerate(['../secret.txt', '/Windows/win.ini', 'C:\\Windows\\win.ini', 'src/../../secret', 'bad.exe', 'bad.png', 'bad.txt', 'huge.txt', 'src', 'README.md#L1-L2', 'README.md:stream']):
            self.assertFalse(self.attach(path, f'bad{i}')[0]['ok'], path)
        self.context.runtime_attached_file_ids = []
        self.assertFalse(self.attach('README.md', 'no-folder')[0]['ok'])
        self.assertEqual(build_brain_user_prompt_content('next', self.context), 'next')

    def test_multiple_folders_and_unicode_backslashes(self):
        name = 'Фото с пробелом.TXT'
        (self.project / 'src' / name).write_text('полный текст', encoding='utf-8')
        self.assertTrue(self.attach(f'src\\{name}')[0]['ok'])
        other = self.root / 'other'; other.mkdir()
        record, _, _ = files.store_uploaded_file(name='other.jin-folder', content=json.dumps({'path': str(other)}).encode(), pin=True)
        self.context.runtime_attached_file_ids.append(record['id'])
        self.assertFalse(self.attach(f'src/{name}', 'm2')[0]['ok'])
        self.assertTrue(self.attach(f'{self.project.name}/src/{name}', 'm3')[0]['ok'])

    def test_symlink_escape_and_unreadable(self):
        outside = self.root / 'secret.txt'; outside.write_text('secret')
        try:
            (self.project / 'escape.txt').symlink_to(outside)
        except OSError:
            # Windows may require Developer Mode for symlinks; all other guards still run.
            pass
        else:
            self.assertFalse(self.attach('escape.txt')[0]['ok'])
        with patch('pathlib.Path.open', side_effect=PermissionError('denied')):
            # Descriptor/index reads also fail; no exception may escape loader.
            from utils.actions.attachment_actions import load_project_attachment
            with self.assertRaises((OSError, ValueError)):
                load_project_attachment(self.context, 'README.md')

    def test_checkpoint_bootstrap_detach_stop_and_deleted_source(self):
        self.attach(self.pair('035'))
        checkpoint = json.loads(json.dumps(build_runtime_session_checkpoint(self.context)))
        self.assertNotIn(base64.b64encode(PNG).decode(), json.dumps(checkpoint))
        apply_bootstrap_tool_results(self.context, checkpoint)
        self.assertEqual(build_brain_user_prompt_content('next', self.context), 'next')
        self.assertTrue(all(e['result'].get('loaded') is False for e in self.context.runtime_tool_results if e['result'].get('action') == 'attach_file_by_path'))
        self.attach(self.pair('036'), 'm2')
        (self.project / 'Photo_036.PNG').unlink()
        self.assertEqual(build_brain_user_prompt_content('next', self.context), 'next')
        self.attach(self.pair('037'), 'm3')
        apply_attachment_context_ids(self.context, [])
        self.assertEqual(build_brain_user_prompt_content('next', self.context), 'next')
        self.context.runtime_attached_file_ids = [self.record['id']]
        self.attach(self.pair('038'), 'm4')
        self.context.runtime_turn_abort_requested = True
        self.assertEqual(build_brain_user_prompt_content('next', self.context), 'next')
        self.assertNotIn('CAPTION_038', build_tool_results_context(self.context))

    def test_every_stream_split_literals_repeat_incomplete_and_case(self):
        marker = f'<ATTACH_FILE_CONTENT: {self.project.name}/Photo_036.PNG, src/Файл.TXT >'
        for split in range(1, len(marker)):
            parser = RuntimeActionStreamFilter(enabled_actions=['ATTACH_FILE_CONTENT'])
            parts = [parser.filter(marker[:split]), parser.filter(marker[split:]), parser.flush_result()]
            actions = [a for p in parts for a in p.actions]
            self.assertEqual([a.payload for a in actions], [f'{self.project.name}/Photo_036.PNG', 'src/Файл.TXT'], split)
            self.assertEqual(len({a.marker_group for a in actions}), 1)
            self.assertEqual(''.join(p.text for p in parts), '')
        for quote in ('"', "'", '`', '['):
            for split in (1, len(marker)//2, len(marker)-1):
                parser = RuntimeActionStreamFilter(enabled_actions=['ATTACH_FILE_CONTENT'])
                parts = [parser.filter(quote + marker[:split]), parser.filter(marker[split:]), parser.flush_result()]
                self.assertFalse(any(p.actions for p in parts))
                self.assertEqual(''.join(p.text for p in parts), quote + marker)
        self.assertEqual(len(extract_runtime_actions(marker * 2, enabled_actions=['ATTACH_FILE_CONTENT']).actions), 2)
        self.assertFalse(extract_runtime_actions('<ATTACH_FILES_BY_PATHISH> x </ATTACH_FILES_BY_PATHISH>', enabled_actions=['ATTACH_FILE_CONTENT']).actions)
        parser = RuntimeActionStreamFilter(enabled_actions=['ATTACH_FILE_CONTENT']); parser.filter(marker[:-2])
        self.assertFalse(parser.flush_result().actions)
        rules = build_runtime_action_instructions(get_enabled_runtime_actions({'CAN_USE_ASSETS': True}), self.context)
        self.assertIn('ATTACH_FILE_CONTENT', rules)

    def test_runtime_stream_to_provider_and_distinct_bubbles(self):
        from runtime.stream import RuntimeStream
        from tests.helpers.runtime_stream import FakeLogger, FakeWebSocket
        from clients.brain_client import ask_brain_stream
        self.context.logger = FakeLogger()
        self.context.websocket = FakeWebSocket()
        self.context.runtime_current_sequence_turn_id = self.context.runtime_current_turn_id
        pair = self.pair('036')
        async def run():
            stream = RuntimeStream(context=self.context, runtime_id='brain', role='brain', context_window=8192,
                                   log_method=self.context.logger.log_service, enable_validator=False,
                                   runtime_actions=['ASSET_ACTION'])
            async def chunks():
                marker = '<ASSET_ACTION>' + json.dumps({'action': ACTION, 'paths': pair.split(', ')}) + '</ASSET_ACTION>'
                for part in (marker[:9], marker[9:35], marker[35:]):
                    yield {'type':'content', 'content':part}
            with patch('utils.actions.dispatcher.ensure_assets_tree'), patch('utils.chat_log.append_chat_runtime_event'):
                await stream.run(chunks())
            captured = {}
            async def provider(**kwargs):
                captured.update(kwargs)
                yield {'type':'content', 'content':'seen'}
            base = fixture.build_brain_context(self.context, runtime_actions=fixture.BRAIN_RUNTIME_ACTIONS)
            followup = BrainNode.build_followup_system_prompt(base, 'caption dataset', context=self.context)
            async for _ in ask_brain_stream(client=SimpleNamespace(stream=provider), text='continue', context=self.context,
                                            system_prompt=followup, context_window_prepared=True):
                pass
            return captured
        captured = asyncio.run(run())
        self.assertEqual(captured['system_prompt'].count('CAPTION_036'), 1)
        self.assertEqual(base64.b64decode(captured['user_prompt'][1]['image_url']['url'].split(',')[1]), PNG)
        completed = [e for e in self.context.emitter.events if e.get('attachment_results')]
        self.assertEqual(len(completed), 1)
        self.assertEqual(len(completed[0]['attachment_results']), 2)
        self.assertFalse(any(e.get('attachment_result') for e in self.context.emitter.events))
        running = [e for e in self.context.emitter.events if e.get('action') == 'asset_action' and e.get('status') == 'started']
        self.assertEqual({e['id'] for e in running}, {e['id'] for e in completed})
        history = build_session_actions_history_context(self.context)
        self.assertIn('Photo_036.PNG', history)
        self.assertIn('Caption_036.txt', history)
        self.assertNotIn('CAPTION_036', history)

    def test_preview_endpoint_checks_live_folder_result_digest_and_bytes(self):
        import app as app_module
        from fastapi.testclient import TestClient
        self.context.session_id = 'test-path-preview'
        results = self.attach(self.pair('036'))
        with patch.object(app_module.app.state, 'websocket_runtime_contexts', {'test':self.context}, create=True):
            client = TestClient(app_module.app)
            image = client.get(results[0]['preview_url'] + '&raw=true')
            self.assertEqual(image.status_code, 200)
            self.assertEqual(image.content, PNG)
            self.assertEqual(image.headers['cache-control'], 'no-store')
            text = client.get(results[1]['preview_url'])
            self.assertIn('CAPTION_036', text.json()['text_content'])
            # A forged query cannot read arbitrary linked-folder files.
            forged = results[0]['preview_url'].replace('Photo_036.PNG', 'README.md')
            self.assertEqual(client.get(forged).status_code, 404)
            (self.project / 'Caption_036.txt').write_text('changed')
            self.assertEqual(client.get(results[1]['preview_url']).status_code, 404)
            self.context.runtime_attached_file_ids = []
            self.assertEqual(client.get(results[0]['preview_url']).status_code, 404)

    def write(self, action='create_asset_file', **kwargs):
        payload = {'action': action, 'attachment': self.project.name, 'path': 'captions/new.txt', 'content': 'first', **kwargs}
        return asyncio.run(run_context_asset_action(json.dumps(payload), context=self.context))

    def test_linked_file_manager_create_overwrite_append_preview_guards(self):
        self.assertTrue(self.write()['ok'])
        path = self.project / 'captions/new.txt'
        self.assertEqual(path.read_text(), 'first\n')
        self.assertEqual(self.write(content='replacement')['error'], 'file_exists')
        self.assertEqual(path.read_text(), 'first\n')
        self.assertTrue(self.write(content='replacement', overwrite=True)['ok'])
        self.assertTrue(self.write('append_asset_file', content='second')['ok'])
        self.assertEqual(path.read_text(), 'replacement\nsecond\n')
        preview = self.write('preview_file', count=1)
        self.assertEqual(preview['items'], ['replacement'])
        for bad in ('../outside.txt', '/outside.txt', 'C:\\outside.txt', 'new.txt:stream'):
            self.assertFalse(self.write(path=bad)['ok'], bad)
        self.context.runtime_persistent_writes_restricted = True
        self.assertFalse(self.write(overwrite=True)['ok'])
        self.context.runtime_persistent_writes_restricted = False
        self.context.runtime_attached_file_ids = []
        self.assertFalse(self.write()['ok'])
        self.assertEqual(path.read_text(), 'replacement\nsecond\n')

if __name__ == '__main__':
    unittest.main()
