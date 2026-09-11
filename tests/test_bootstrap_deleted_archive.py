"""D049: disk deletion wins over browser replicas and unfinished workers."""
import json
import shutil
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from utils import chat_log, session_restore
from websocket.bootstrap import enrich_session_bootstrap_from_archive


class DeletedArchiveTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(chat_log, 'CHAT_LOG_ROOT', self.root))
        self.stack.enter_context(patch.object(session_restore, 'CHAT_LOG_ROOT', self.root))
        self.stack.enter_context(patch.object(chat_log, 'chat_logging_enabled', return_value=True))

    def context(self, session='survivor', day=10, anonymous=False):
        c = SimpleNamespace(session_id=session, runtime_turn_counter=1,
                            runtime_current_turn_id='turn_000001', runtime_anonymous_mode=anonymous)
        chat_log.get_chat_log_path(c, now=datetime(2026, 9, day, 19, tzinfo=timezone.utc))
        return c

    def remove_day(self, day):
        directory = self.root / f'2026-09-{day}'
        self.assertTrue(directory.resolve().is_relative_to(self.root.resolve()))
        shutil.rmtree(directory)

    def test_deleted_newer_browser_source_restores_surviving_pair_only(self):
        old = self.context()
        chat_log.append_chat_log_entry(old, role='user', text='old request')
        chat_log.append_chat_log_entry(old, role='jin', text='old answer')
        newer = self.context('deleted', 11)
        newer.runtime_turn_attachments = [{'id': 'photo', 'name': 'photo.png'}]
        chat_log.append_chat_log_entry(newer, role='user', text='photo request')
        newer.runtime_turn_counter = 2
        newer.runtime_current_turn_id = 'turn_000002'
        chat_log.append_chat_log_entry(newer, role='user', text='photo request')
        checkpoint = session_restore.build_archived_session_restore_payload('deleted')
        self.assertEqual(len(checkpoint['recent_turns']), 2)
        checkpoint.pop('archived_session_restore', None)
        checkpoint.update(type='session_bootstrap', saved_at='2099-09-11T19:00:00Z',
                          runtime_memory='deleted FRAME', runtime_snapshot={'session_id': 'deleted'},
                          attached_file_ids=['deleted-file'], tool_results=[{'text': 'deleted result'}])
        self.remove_day(11)
        del newer  # Restart: only the serialized browser checkpoint survives.
        for _ in range(2):
            restored = enrich_session_bootstrap_from_archive(json.loads(json.dumps(checkpoint)))
            self.assertEqual(restored['source_session_id'], 'survivor')
            self.assertEqual([(t['user'], t['jin']) for t in restored['recent_turns']],
                             [('old request', 'old answer')])
            self.assertNotIn('deleted FRAME', json.dumps(restored))
            self.assertNotIn('deleted-file', json.dumps(restored))
            self.assertNotIn('deleted result', json.dumps(restored))
            self.assertFalse((self.root / '2026-09-11').exists())

    def test_no_surviving_archive_drops_entire_browser_replica(self):
        restored = enrich_session_bootstrap_from_archive({
            'type': 'session_bootstrap', 'source_session_id': 'missing',
            'recent_turns': [{'user': 'trash'}], 'runtime_memory': 'trash'})
        self.assertEqual(restored, {'type': 'session_bootstrap'})

    def test_reader_error_is_not_mistaken_for_deletion(self):
        checkpoint = {'source_session_id': 'unreadable', 'runtime_memory': 'keep'}
        with patch.object(session_restore, 'build_archived_session_restore_payload', side_effect=OSError):
            self.assertEqual(enrich_session_bootstrap_from_archive(checkpoint), checkpoint)

    def test_deleted_live_archive_is_not_recreated_by_any_writer(self):
        for anonymous in (False, True):
            with self.subTest(anonymous=anonymous):
                c = self.context('worker', 11, anonymous)
                chat_log.append_chat_log_entry(c, role='user', text='before deletion')
                self.remove_day(11)
                chat_log.append_chat_runtime_event(c, event='session_actions_snapshot')
                chat_log.save_turn_reasoning(c, 'late reasoning')
                chat_log.save_chat_context_snapshot(c, system_prompt='late prompt')
                chat_log.save_frame_snapshot(c, {'index': 1, 'raw_memory': 'late frame'})
                chat_log.replace_latest_chat_log_entry(c, role='jin', text='late retry')
                chat_log.append_chat_log_entry(c, role='jin', text='late answer')
                self.assertFalse((self.root / '2026-09-11').exists())

    def test_startup_rows_reasoning_and_frames_wait_for_first_user(self):
        c = self.context('startup', 11)
        c.runtime_session_restore_priming = True
        chat_log.save_chat_bootstrap_context_snapshot(c, system_prompt='bootstrap')
        chat_log.save_frame_snapshot(c, {'index': 0, 'raw_memory': 'inherited'})
        chat_log.save_turn_reasoning(c, 'greeting reasoning')
        chat_log.append_chat_runtime_event(c, event='runtime_action_request')
        chat_log.append_chat_log_entry(c, role='jin', text='greeting')
        c.runtime_session_restore_priming = False
        chat_log.append_chat_runtime_event(c, event='session_actions_snapshot')
        self.assertFalse((self.root / '2026-09-11').exists())
        c.runtime_turn_counter = 2
        c.runtime_current_turn_id = 'turn_000002'
        path = chat_log.append_chat_log_entry(c, role='user', text='real input')
        rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
        self.assertEqual([r['text'] for r in rows if r['role'] != 'runtime'], ['greeting', 'real input'])
        self.assertIn('reasoning_path', rows[1])
        self.assertEqual(len(list(self.root.rglob('*_turn_000001.txt'))), 1)
        self.assertIsNotNone(session_restore.find_latest_completed_session_restore_payload())


if __name__ == '__main__':
    unittest.main()
