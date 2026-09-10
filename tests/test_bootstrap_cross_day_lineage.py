import json
import tempfile
import unittest
from pathlib import Path

from utils.session_restore import build_session_bootstrap_lineage_recent_turns


class CrossDayLineageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def session(self, sid, day, count=0, predecessor='', primary=False):
        directory = self.root / day / sid
        directory.mkdir(parents=True)
        if count:
            rows = []
            for i in range(count):
                for role in ('user', 'jin'):
                    rows.append(dict(turn=i + 1, turn_id=f'turn_{i+1:06}',
                                     role=role, text=f'{sid} {role} {i}',
                                     ts=f'{day}T10:{i:02}:00+03:00'))
            (directory / '100000.jsonl').write_text(
                '\n'.join(map(json.dumps, rows)), encoding='utf-8')
        link = f'<RESTORED_SESSION_DIALOG session_id="{predecessor}"></RESTORED_SESSION_DIALOG>' if predecessor else ''
        (directory / '100000.bootstrap.txt').write_text(
            '' if primary else link, encoding='utf-8')
        (directory / '100000.txt').write_text(
            link if primary else 'Later context without inherited dialogue',
            encoding='utf-8')

    def tail(self, sid):
        return build_session_bootstrap_lineage_recent_turns(sid, root=self.root)

    def test_primary_context_cannot_hide_previous_day(self):
        self.session('old', '2026-09-07', 6)
        self.session('new', '2026-09-08', 1, 'old')
        turns = self.tail('new')
        self.assertEqual([t['source_session_id'] for t in turns], ['old'] * 4 + ['new'])
        self.assertEqual(turns[0]['source_session_date'], '2026-09-07')
        self.assertEqual(turns[-1]['source_session_date'], '2026-09-08')
        self.assertTrue(all(t['jin_created_at'] > 0 for t in turns))

    def test_blank_tabs_do_not_spend_history_budget_or_stop_at_eight(self):
        self.session('old', '2026-09-06', 5)
        predecessor = 'old'
        for i in range(10):
            sid = f'blank-{i}'
            self.session(sid, '2026-09-07', predecessor=predecessor)
            predecessor = sid
        self.session('new', '2026-09-08', 1, predecessor)
        self.assertEqual(len(self.tail('new')), 5)

    def test_legacy_primary_context_fallback(self):
        self.session('old', '2026-09-07', 5)
        self.session('new', '2026-09-08', 1, 'old', primary=True)
        self.assertEqual(len(self.tail('new')), 5)

    def test_missing_lineage_metadata_falls_back_to_previous_real_session(self):
        self.session('old', '2026-09-07', 5)
        self.session('new', '2026-09-08', 1)

        turns = self.tail('new')

        self.assertEqual(len(turns), 5)
        self.assertEqual(
            [turn['source_session_id'] for turn in turns],
            ['old'] * 4 + ['new'],
        )

    def test_cycle_and_missing_predecessor_stop_without_duplicates(self):
        self.session('a', '2026-09-07', 1, 'b')
        self.session('b', '2026-09-08', 1, 'a')
        self.assertEqual(len(self.tail('b')), 2)
        self.session('missing-child', '2026-09-08', 1, 'deleted')
        self.assertEqual(len(self.tail('missing-child')), 1)

    def test_anonymous_predecessor_is_not_inherited(self):
        self.session('private-anon', '2026-09-07', 5)
        self.session('new', '2026-09-08', 1, 'private-anon')
        self.assertEqual(len(self.tail('new')), 1)
        self.assertEqual(self.tail('private-anon'), [])
