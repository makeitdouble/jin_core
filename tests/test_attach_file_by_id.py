import asyncio
import base64
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tests import test_project_review as fixture
from clients.brain_client import build_brain_user_prompt_content
from contracts.rules_assembler import build_runtime_action_instructions, get_enabled_runtime_actions
from runtime.L1_memory_utils import build_runtime_session_checkpoint
from utils import attached_files_store as files
from utils.actions import RuntimeActionStreamFilter, extract_runtime_actions
from utils.actions.attachment_actions import apply_attachment_context_ids
from utils.actions.dispatcher import apply_runtime_action_calls
from utils.context.files import file_result_summary
from utils.context.session_actions import build_session_actions_history_context
from utils.context.tool_results import build_tool_results_context
from utils.session_actions_history import upsert_session_action_marker_history_since
from utils.tool_results import record_runtime_tool_result
from websocket.bootstrap import apply_bootstrap_tool_results
from agent.nodes.brain import consume_action_failure_followup_context


ACTION = 'ATTACH_FILE_BY_ID'


class AttachFileByIdTests(unittest.TestCase):
    setUp = fixture.ProjectReviewTests.setUp

    def attach(self, payload):
        actions = extract_runtime_actions(f'<{ACTION}: {payload} >', enabled_actions=[ACTION]).actions
        self.assertEqual(len(actions), 1)
        start = len(self.context.runtime_session_action_history)
        with patch('utils.actions.dispatcher.ensure_assets_tree'), patch('utils.chat_log.append_chat_runtime_event'):
            asyncio.run(apply_runtime_action_calls(self.context, actions))
        upsert_session_action_marker_history_since(self.context, start, [{'name': ACTION, 'payload': payload}])
        return self.context.runtime_tool_results[-1]['result']

    def test_full_text_image_history_and_checkpoint(self):
        body = '\n'.join(f'whole file line {n}' for n in range(400))
        text, _, _ = files.store_uploaded_file(name='полное_имя.txt', content=body.encode(), pin=False)
        image_bytes = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
        photo, _, _ = files.store_uploaded_file(name='полное_имя.png', content=image_bytes, mime_type='image/png', pin=False)
        for record in (text, photo):
            result = self.attach(record['id'])
            self.assertTrue(result['ok'])
            label = f'{ACTION}: {record["name"]}'
            self.assertEqual(file_result_summary(result), label)
            event = [e for e in self.context.emitter.events if e.get('attachment_result')][-1]
            self.assertEqual(event['text'], label)
            self.assertEqual(event['status'], 'completed')
            self.assertIn(label, build_session_actions_history_context(self.context))
        tools = build_tool_results_context(self.context)
        self.assertEqual(tools.count('whole file line 399'), 1)
        self.assertTrue(all(line in tools for line in body.splitlines()))
        with patch('clients.brain_client.config.BRAIN_IMAGE_INPUT_ENABLED', True):
            payload = build_brain_user_prompt_content('continue', self.context)
        self.assertEqual(base64.b64decode(payload[1]['image_url']['url'].split(',', 1)[1]), image_bytes)
        for i in range(65):
            record_runtime_tool_result(self.context, 'runtime_action', {'action': 'test', 'ok': True, 'value': i})
        snapshot = json.loads(json.dumps(build_runtime_session_checkpoint(self.context)))
        history = json.loads(json.dumps(self.context.runtime_session_action_history))
        self.context.runtime_tool_results = []
        apply_bootstrap_tool_results(self.context, snapshot)
        apply_attachment_context_ids(self.context, [text['id'], photo['id']])
        self.assertEqual(build_tool_results_context(self.context).count('whole file line 399'), 1)
        restored = SimpleNamespace(session_id=self.context.session_id, runtime_session_action_history=history)
        self.assertIn(f'{ACTION}: {photo["name"]}', build_session_actions_history_context(restored))
        apply_attachment_context_ids(self.context, [])
        self.assertNotIn('whole file line 399', build_tool_results_context(self.context))
        self.assertTrue(all(e['result'].get('loaded') is False for e in self.context.runtime_tool_results
                            if e['result'].get('action') == 'attach_file_by_id'))

    def test_missing_deleted_paths_and_filenames_fail_without_project_read(self):
        record, _, _ = files.store_uploaded_file(name='gone.jpg', content=b'image', pin=False)
        files.delete_file_record(record['id'])
        before = list(self.context.runtime_attached_file_ids)
        for value in (record['id'], 'zzzzzz', 'README.md', 'abcdef_image.png', 'src/main.py#L1-L20'):
            with patch('utils.actions.attachment_actions.parse_project_file_target', side_effect=AssertionError('must not read a path')):
                result = self.attach(value)
            self.assertFalse(result['ok'])
            label = f'{ACTION}: {value} : failed - file not exists'
            self.assertEqual(file_result_summary(result), label)
            self.assertIn(label, build_session_actions_history_context(self.context))
            self.assertEqual(self.context.runtime_attached_file_ids, before)
        tools = build_tool_results_context(self.context)
        self.assertIn('Correct action schema:', tools)
        self.assertIn(ACTION, consume_action_failure_followup_context(self.context))

    def test_anonymous_attach_does_not_pin_persistent_file(self):
        record, _, _ = files.store_uploaded_file(name='private.txt', content=b'local context', pin=False)
        with patch('utils.actions.attachment_actions.persistent_writes_restricted', return_value=True):
            self.assertTrue(self.attach(record['id'])['ok'])
        self.assertFalse(files.get_file_record(record['id'])['pinned'])
        self.assertIn(record['id'], self.context.runtime_attached_file_ids)

    def test_stream_boundaries_literals_false_prefix_repeat_and_flush(self):
        marker = f'<{ACTION}: abc123 >'
        for split in range(1, len(marker)):
            parser = RuntimeActionStreamFilter(enabled_actions=[ACTION])
            parts = [parser.filter(marker[:split]), parser.filter(marker[split:]), parser.flush_result()]
            self.assertEqual(sum(len(p.actions) for p in parts), 1, split)
            self.assertEqual(''.join(p.text for p in parts), '')
            for quote in ('"', "'", '`', '['):
                parser = RuntimeActionStreamFilter(enabled_actions=[ACTION])
                parts = [parser.filter(quote + marker[:split]), parser.filter(marker[split:]), parser.flush_result()]
                self.assertFalse(any(p.actions for p in parts))
                self.assertEqual(''.join(p.text for p in parts), quote + marker)
        self.assertEqual(len(extract_runtime_actions(marker * 2, enabled_actions=[ACTION]).actions), 1)
        self.assertFalse(extract_runtime_actions('<ATTACH_FILE_BY_IDISH: abc123>', enabled_actions=[ACTION]).actions)
        parser = RuntimeActionStreamFilter(enabled_actions=[ACTION])
        parser.filter(marker[:-2])
        self.assertFalse(parser.flush_result().actions)
        result = extract_runtime_actions('before ' + marker + ' after', enabled_actions=[ACTION])
        self.assertIn('before', result.text)
        self.assertIn('after', result.text)

    def test_contract_is_enabled_and_distinguishes_whole_files(self):
        enabled = get_enabled_runtime_actions({'CAN_USE_ASSETS': True})
        self.assertIn(ACTION, enabled)
        rules = build_runtime_action_instructions(enabled, self.context)
        self.assertIn(f'<{ACTION}: file_id >', rules)
        self.assertIn('whole file', rules)
        self.assertIn('photos/images', rules)


if __name__ == '__main__':
    unittest.main()
