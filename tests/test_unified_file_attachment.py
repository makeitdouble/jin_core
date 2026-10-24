import asyncio
import json
import unittest
from unittest.mock import patch

from tests import test_project_review as fixture
from tests.test_attach_file_by_path import PNG
from clients.brain_client import build_brain_user_prompt_content
from contracts.rules_assembler import get_enabled_runtime_actions
from utils import attached_files_store as files
from utils.actions import extract_runtime_actions
from utils.actions.dispatcher import apply_runtime_action_calls
from utils.context.tool_results import build_tool_results_context
from agent.nodes.brain import consume_action_failure_followup_context


class UnifiedFileAttachmentTests(unittest.TestCase):
    setUp = fixture.ProjectReviewTests.setUp

    def execute(self, source, message='unified'):
        actions = extract_runtime_actions(source).actions
        self.assertTrue(actions)
        before = len(self.context.runtime_tool_results)
        with patch('utils.actions.dispatcher.ensure_assets_tree'), patch('utils.chat_log.append_chat_runtime_event'):
            asyncio.run(apply_runtime_action_calls(self.context, actions, runtime_message_id=f'{message}-{before}'))
        return self.context.runtime_tool_results[before:]

    def asset(self, operation, **fields):
        return self.execute('<ASSET_ACTION>' + json.dumps({'action': operation, **fields}) + '</ASSET_ACTION>')

    def test_only_one_attachment_marker_and_retired_markers_are_inert(self):
        enabled = get_enabled_runtime_actions({'CAN_USE_ASSETS': True})
        self.assertEqual([name for name in enabled if name.startswith('ATTACH_')], ['ATTACH_FILE_CONTENT'])
        for name in ('ATTACH_FILES_BY_ID', 'ATTACH_FILES_BY_PATH', 'ATTACH_FILE_BY_ID', 'ATTACH_FILE_BY_PATH'):
            for source in (f'<{name}> abc123 </{name}>', f'<{name}: abc123 >'):
                self.assertFalse(extract_runtime_actions(source).actions, source)

    def test_marker_id_image_and_source_range_deliver_actual_content_once(self):
        record, _, _ = files.store_uploaded_file(name='pinned.txt', content=b'WHOLE_PERSISTENT', pin=False)
        (self.project / 'Photo.PNG').write_bytes(PNG)
        entries = self.execute(
            f'<ATTACH_FILE_CONTENT: {record["id"]}, {self.project.name}/Photo.PNG, '
            f'{self.project.name}/src/main.py#L2-L2 >')
        self.assertEqual(len(entries), 3)
        self.assertTrue(all(entry['result']['ok'] for entry in entries))
        self.assertTrue(all(entry.get('action_name') == 'ATTACH_FILE_CONTENT' for entry in entries))
        prompt = build_brain_user_prompt_content('continue', self.context)
        self.assertEqual(len(prompt), 2)
        tools = build_tool_results_context(self.context)
        self.assertEqual(tools.count('WHOLE_PERSISTENT'), 1)
        self.assertIn('needle = 42', tools)

    def test_asset_pair_has_single_results_bound_to_owner_and_rechecks_files(self):
        (self.project / 'Photo.PNG').write_bytes(PNG)
        (self.project / 'Caption.TXT').write_text('ORIGINAL', encoding='utf-8')
        entries = self.asset('attach_file_by_path', attachment=self.project.name,
                             paths=['Photo.PNG', 'Caption.TXT'])
        self.assertEqual(len(entries), 2)
        self.assertTrue(all(entry['result']['ok'] for entry in entries))
        self.assertTrue(all(entry['action_name'] == 'ASSET_ACTION' for entry in entries))
        self.assertEqual(len(set(entry['tool_id'] for entry in entries)), 2)
        (self.project / 'Caption.TXT').write_text('UPDATED', encoding='utf-8')
        self.asset('ATTACH_FILE_BY_PATH', path=f'{self.project.name}/Caption.TXT')
        tools = build_tool_results_context(self.context)
        self.assertIn('UPDATED', tools)
        self.assertNotIn('ORIGINAL', tools)

    def test_asset_bad_payloads_fail_with_schema_and_no_attachment(self):
        for fields in ({}, {'ids': []}, {'ids': 'abc123'}, {'id': 12}, {'ids': [None]}):
            result = self.asset('ATTACH_FILE_BY_ID', **fields)[0]['result']
            self.assertFalse(result['ok'], fields)
            self.assertEqual(result['error'], 'invalid_attachment_action')
        tools = build_tool_results_context(self.context)
        self.assertIn('Correct action schema:', tools)
        self.assertIn('ATTACH_FILE_BY_ID', tools)
        self.assertTrue(consume_action_failure_followup_context(self.context))

    def test_asset_requires_linked_folder_and_never_falls_back_from_id(self):
        self.context.runtime_loaded_skills = []
        result = self.asset('ATTACH_FILE_BY_PATH', path='README.md')[0]['result']
        self.assertTrue(result['ok'])
        self.context.runtime_loaded_skills = [{'name': 'file_manager'}]
        result = self.asset('ATTACH_FILE_BY_ID', id='README.md')[0]['result']
        self.assertEqual(result['error'], 'file_not_found')
        self.context.runtime_attached_file_ids = []
        result = self.asset('ATTACH_FILE_BY_PATH', path='README.md')[0]['result']
        self.assertFalse(result['ok'])

    def test_failed_asset_payload_is_preserved_in_tool_snapshot(self):
        payload = {'action': 'nonexistent_operation', 'paths': ['Photo.PNG']}
        result = self.execute('<ASSET_ACTION>' + json.dumps(payload) + '</ASSET_ACTION>')[0]['result']
        self.assertEqual(result['payload'], payload)


if __name__ == '__main__':
    unittest.main()
