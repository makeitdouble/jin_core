import asyncio
import importlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from utils.file_manager_asset_utils import read_project_asset_text_preview


class LinkedAssetTextPreviewTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / '44.txt').write_text('one\ntwo\n', encoding='utf-8')
        self.record = {'id': 'folder-123', 'name': 'caption_test.jin-folder'}
        self.context = SimpleNamespace(session_id='session-123')
        self.links = patch('utils.project_reader.linked_projects', return_value=[self.record])
        self.root_lookup = patch('utils.project_reader._root_for', return_value=(self.root, self.record))
        self.links.start()
        self.root_lookup.start()
        self.addCleanup(self.links.stop)
        self.addCleanup(self.root_lookup.stop)

    def test_reads_exact_txt_from_linked_folder(self):
        result = read_project_asset_text_preview(
            {'path': 'caption_test/44.txt', 'max_chars': 4}, context=self.context,
        )
        self.assertEqual(result['name'], 'caption_test/44.txt')
        self.assertEqual(result['text_content'], 'one\n')
        self.assertTrue(result['truncated'])
        self.assertEqual(result['line_count'], 2)

    def test_does_not_follow_parent_traversal_or_other_folder(self):
        with self.assertRaises(ValueError):
            read_project_asset_text_preview(
                {'path': 'caption_test/../outside.txt'}, context=self.context,
            )
        with self.assertRaises(FileNotFoundError):
            read_project_asset_text_preview(
                {'path': 'unknown/44.txt'}, context=self.context,
            )
        with self.assertRaises(FileNotFoundError):
            read_project_asset_text_preview(
                {'path': 'caption_test/44.png'}, context=self.context,
            )

    def test_http_preview_requires_live_matching_session(self):
        module = importlib.import_module('app')
        with patch.object(module.app.state, 'websocket_runtime_contexts', {'current': self.context}, create=True):
            result = asyncio.run(module.api_asset_text_preview(
                path='caption_test/44.txt', max_chars=60000, session_id='session-123',
            ))
            self.assertEqual(result['text_content'], 'one\ntwo\n')
            with self.assertRaises(HTTPException) as failure:
                asyncio.run(module.api_asset_text_preview(
                    path='caption_test/44.txt', max_chars=60000, session_id='wrong-session',
                ))
            self.assertEqual(failure.exception.status_code, 404)
