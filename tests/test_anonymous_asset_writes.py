import unittest
from tests.test_unified_file_attachment import UnifiedFileAttachmentTests
from tests.helpers.runtime_actions import patch_asset_roots
from runtime.anonymous_mode import configure_runtime_anonymous_mode, runtime_action_write_is_restricted


class AnonymousAssetWriteTests(unittest.TestCase):
    setUp = UnifiedFileAttachmentTests.setUp
    execute = UnifiedFileAttachmentTests.execute
    asset = UnifiedFileAttachmentTests.asset

    def enable_anonymous(self):
        configure_runtime_anonymous_mode(self.context, True)
        self.assertTrue(self.context.runtime_persistent_writes_restricted)
        self.assertTrue(self.context.runtime_anonymous_mode)

    def test_linked_create_append_overwrite_and_escape(self):
        self.enable_anonymous()
        fields = dict(attachment=self.project.name, path='captions/1.txt')
        result = self.asset('create_asset_file', content='first caption', **fields)[0]['result']
        self.assertTrue(result['ok'], result)
        target = self.project / 'captions/1.txt'
        self.assertEqual(target.read_text().strip(), 'first caption')
        result = self.asset('append_asset_file', content='second line', **fields)[0]['result']
        self.assertTrue(result['ok'], result)
        self.assertEqual(target.read_text().splitlines(), ['first caption', 'second line'])
        result = self.asset('create_asset_file', content='replacement', **fields)[0]['result']
        self.assertFalse(result['ok'])
        self.assertIn('first caption', target.read_text())
        result = self.asset('create_asset_file', content='replacement', overwrite=True, **fields)[0]['result']
        self.assertTrue(result['ok'], result)
        self.assertEqual(target.read_text().strip(), 'replacement')
        result = self.asset('create_asset_file', attachment=self.project.name, path='../escape.txt', content='escape')[0]['result']
        self.assertFalse(result['ok'])
        self.assertFalse((self.root / 'escape.txt').exists())
        self.assertTrue(runtime_action_write_is_restricted(self.context, 'POSTING_BOARD', {'action':'post'}))

    def test_assets_directory_creation_is_allowed(self):
        self.enable_anonymous()
        for patcher in patch_asset_roots(self.root):
            self.stack.enter_context(patcher)
        result = self.asset('create_asset_file', path='assets/outputs/caption.txt', content='caption')[0]['result']
        self.assertTrue(result['ok'], result)
        self.assertEqual((self.root/'assets/outputs/caption.txt').read_text().strip(), 'caption')

    def test_shadow_linked_writer_remains_restricted(self):
        from utils.file_manager_asset_utils import create_asset_file
        self.context.runtime_persistent_writes_restricted = True
        self.context.runtime_anonymous_mode = False
        payload = dict(action='create_asset_file', attachment=self.project.name, path='blocked.txt', content='blocked')
        with self.assertRaises(PermissionError):
            create_asset_file(payload, context=self.context)
        self.assertTrue(runtime_action_write_is_restricted(self.context,'ASSET_ACTION',payload))
        self.assertFalse((self.project/'blocked.txt').exists())
