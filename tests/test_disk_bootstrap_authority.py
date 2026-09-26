"""Disk-only continuation, including hostile/stale browser projections."""
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.runtime_context import RuntimeContext
from runtime.memory_profile import enable_profile, refresh_profile, handle_store_sync, read_profile
from utils import chat_log, session_restore
from utils.tool_results import record_runtime_tool_result
from websocket.bootstrap import apply_session_bootstrap, apply_runtime_resume, enrich_session_bootstrap_from_archive
from websocket.transport import RuntimeTransport


class DiskBootstrapAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.logs = self.root / 'logs'
        self.stack.enter_context(patch.object(chat_log, 'CHAT_LOG_ROOT', self.logs))
        self.stack.enter_context(patch.object(session_restore, 'CHAT_LOG_ROOT', self.logs))
        self.stack.enter_context(patch.object(chat_log, 'chat_logging_enabled', return_value=True))

    def context(self, name='source'):
        context = RuntimeContext(None, None, None, {}, session_id=name)
        context.runtime_turn_counter = 1
        context.runtime_current_turn_id = 'turn_000001'
        return context

    def user(self, context, text='disk USER'):
        chat_log.append_chat_log_entry(context, role='user', text=text)

    def resolve(self, **overrides):
        browser = dict(type='session_bootstrap', source_session_id='foreign',
                       runtime_memory='FOREIGN FRAME', saved_at='2099-01-01T00:00:00Z',
                       recent_turns=[{'user': 'FOREIGN USER'}],
                       runtime_snapshot={'raw_memory': 'FOREIGN FRAME'},
                       current_jin_color='#ffffff', tool_results=[{'result': 'FOREIGN TOOL'}])
        browser.update(overrides)
        return enrich_session_bootstrap_from_archive(json.loads(json.dumps(browser)))

    def test_clean_folder_ignores_every_browser_payload_variant(self):
        for extra in ({}, {'source_session_id': ''}, {'archived_session_restore': True}):
            with self.subTest(extra=extra):
                self.assertEqual(self.resolve(**extra), {'type': 'session_bootstrap'})
        self.assertFalse(self.logs.exists())

    def test_disk_selected_without_browser_owner_and_browser_cannot_replace_fields(self):
        context = self.context()
        self.user(context)
        chat_log.append_chat_log_entry(context, role='jin', text='disk JIN')
        chat_log.save_frame_snapshot(context, {'index': 2, 'raw_memory': 'topic: disk FRAME',
                                               'created_at': '2026-09-20T01:00:00Z',
                                               'timestamp': '2026-09-20T01:00:00Z',
                                               'lines': [{'key': 'topic', 'value': 'disk FRAME',
                                                          'created_at': '2026-09-20T01:00:00Z'}]})
        for _ in range(2):
            payload = self.resolve(source_session_id='')
            self.assertEqual(payload['source_session_id'], 'source')
            self.assertEqual(payload['runtime_memory'], 'topic: disk FRAME')
            self.assertEqual(payload['recent_turns'][-1]['user'], 'disk USER')
            self.assertNotIn('FOREIGN', json.dumps(payload))
            fresh = self.context('fresh')
            self.assertTrue(apply_session_bootstrap(fresh, payload, resolved_from_disk=True))
            self.assertEqual(fresh.runtime_memory_snapshots[-1]['created_at'], '2026-09-20T01:00:00Z')

    def test_latest_frame_beats_prompt_and_explicit_empty_stays_empty(self):
        context = self.context()
        self.user(context)
        chat_log.save_chat_context_snapshot(context, system_prompt='<PREVIOUS_RUNTIME_STATE>old</PREVIOUS_RUNTIME_STATE>')
        chat_log.save_frame_snapshot(context, {'index': 9, 'raw_memory': 'older frame'})
        chat_log.save_frame_snapshot(context, {'index': 10, 'raw_memory': ''})
        self.assertEqual(self.resolve()['runtime_memory'], '')
        self.assertEqual(self.resolve()['runtime_snapshot']['raw_memory'], '')

    def test_explicit_archive_selector_is_reloaded_from_disk(self):
        self.user(self.context())
        payload = self.resolve(source_session_id='source', archived_session_restore=True)
        self.assertEqual(payload['source_session_id'], 'source')
        self.assertNotIn('FOREIGN', json.dumps(payload))

    def test_reader_failure_never_falls_back_to_browser(self):
        with patch.object(session_restore, 'find_latest_completed_session_restore_payload', side_effect=OSError):
            with self.assertRaises(OSError):
                self.resolve()

    def test_soft_resume_cannot_mutate_live_context(self):
        context = self.context()
        context.runtime_memory = 'live FRAME'
        context.runtime_tool_results = [{'kind': 'search', 'result': 'live result'}]
        self.assertFalse(apply_runtime_resume(context, {'runtime_memory': 'FOREIGN', 'tool_results': []}))
        self.assertEqual(context.runtime_memory, 'live FRAME')
        self.assertEqual(context.runtime_tool_results[0]['result'], 'live result')

    def test_tools_checkpoint_cleanup_late_result_round_trip(self):
        context = self.context()
        self.user(context)
        record_runtime_tool_result(context, 'search', 'first result')
        chat_log.append_chat_runtime_event(context, event='session_checkpoint', payload={
            'tool_results': [], 'tool_result_sequence': 12})
        record_runtime_tool_result(context, 'search', 'later result')
        payload = self.resolve()
        self.assertEqual([item['result'] for item in payload['tool_results']], ['later result'])
        self.assertEqual(payload['tool_result_sequence'], 12)
        chat_log.append_chat_runtime_event(context, event='runtime_action', payload={
            'action': 'clean_tool_results', 'status': 'completed', 'tool_results': [],
            'tool_result_sequence': 12})
        self.assertEqual(self.resolve()['tool_results'], [])

    def test_clear_survives_passive_writes_until_another_user(self):
        context = self.context()
        self.user(context)
        session_restore.clear_normal_session_continuation(root=self.logs)
        chat_log.append_chat_runtime_event(context, event='session_checkpoint', payload={'tool_results': []})
        chat_log.append_chat_log_entry(context, role='jin', text='late completion')
        self.assertEqual(self.resolve(), {'type': 'session_bootstrap'})
        context.runtime_turn_counter = 2
        context.runtime_current_turn_id = 'turn_000002'
        self.user(context, 'new USER after CLEAR')
        self.assertEqual(self.resolve()['recent_turns'][-1]['user'], 'new USER after CLEAR')

    def test_transport_persists_projection_but_blank_page_creates_no_archive(self):
        socket = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()), query_params={})
        transport = RuntimeTransport(socket)
        context = self.context()
        transport.context = context
        chat_log.get_chat_log_path(context)
        transport.publish({'type': 'runtime_memory_update', 'session_snapshot': {'tool_results': []}})
        self.assertFalse(self.logs.exists())
        self.user(context)
        transport.publish({'type': 'agent_runtime_end', 'session_snapshot': {
            'tool_results': [], 'tool_result_sequence': 3, 'current_jin_color': '#123456'}})
        self.assertEqual(self.resolve()['current_jin_color'], '#123456')
        self.assertEqual(self.resolve()['tool_result_sequence'], 3)

    def test_legacy_browser_facts_never_import_into_empty_profile(self):
        context = self.context()
        context.memory_profile_root = self.root / 'memory'
        context.websocket = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
        enable_profile(context)
        refresh_profile(context)
        handle_store_sync(context, {'type': 'facts_memory_store_sync', 'legacy_records': [
            {'session_id': 'foreign', 'signals': {'topic': {'content': 'FOREIGN'}}}]})
        self.assertEqual(read_profile(context)['pending'], [])


if __name__ == '__main__':
    unittest.main()
