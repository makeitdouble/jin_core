"""Exercise project result semantics without the Brain/network stack."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from utils import project_reader as reader


class ProjectResultWordingTests(unittest.TestCase):
    def test_pages_limits_and_exclusions(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'src').mkdir()
            (root / 'src/a.py').write_text('needle\nNEEDLE again\nother\n')
            (root / 'node_modules').mkdir()
            (root / 'node_modules/hidden').write_text('absent')
            def search(**kwargs):
                return reader.run_project_action(None, dict(action='project_search', **{'query': 'needle', **kwargs}))
            with patch.object(reader, '_root_for', return_value=(root, {'id': 'abc123', 'name': 'demo.jin-folder'})):
                first = search(limit=1)
                self.assertEqual(first['content'], 'demo/src/a.py:1: needle')
                self.assertIn('1 matching lines', first['page'])
                self.assertIn('offset 1', first['notice'])
                last = search(limit=1, offset=1)
                self.assertEqual(last['content'], 'demo/src/a.py:2: NEEDLE again')
                self.assertIn('No more results', last['notice'])
                self.assertIn('No matching lines in the searched files', search(query='absent')['content'])
                self.assertIn('not a count of matches', search()['notice'])
                self.assertIn('does not prove', search(offset=99)['content'])
                self.assertTrue(search(path='src')['content'].startswith('demo/src/a.py:1:'))
                for name, value, reason in [('MAX_SCAN_SECONDS', -1, 'time limit'), ('MAX_SCAN_ENTRIES', 0, 'entry limit'), ('MAX_SCAN_BYTES', 0, 'file byte budget')]:
                    with self.subTest(name=name), patch.object(reader, name, value):
                        result = search()
                        self.assertTrue(result['ok'])
                        self.assertIn(reason, result['notice'])
                        self.assertIn('does not resume', result['notice'])
                        self.assertIn('does not prove', result['content'])
                tree = reader.run_project_action(None, {'action': 'project_tree', 'depth': 1})
                self.assertEqual(tree['content'], 'demo/src/')
                self.assertIn('file/folder paths', tree['page'])
