"""Folder links implicitly provide their skill, but not persistent LOAD_SKILL events."""

import asyncio
import contextlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.nodes.brain import BrainNode
from rules.brain_context_builder import BRAIN_RUNTIME_ACTIONS, build_brain_context
from runtime.runtime_context import RuntimeContext
from tests.helpers.runtime_actions import FakeEmitter
from utils import attached_files_store as files
from utils.context.skills import build_skills_inventory_context
from utils.context.tool_results import build_tool_results_context
from utils.project_reader import link_project_folder
from utils.python_skill_asset_utils import run_context_asset_action
from utils.skills_asset_utils import list_skills, load_skill
from utils.tool_results import begin_runtime_tool_results_turn


class DirectoryLinkSkillTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.folder = self.root / "My Folder"
        self.folder.mkdir()
        (self.folder / "photo.png").write_bytes(b"some data")
        for name, path in {
            "FILES_DIR": self.root / "files",
            "INDEX_FILE": self.root / "files/.index.json",
            "GITKEEP_FILE": self.root / "files/.gitkeep",
        }.items():
            self.stack.enter_context(patch.object(files, name, path))
        self.record, _, _ = link_project_folder(str(self.folder))
        self.context = RuntimeContext(websocket=object(), emitter=FakeEmitter(), logger=object(), clients={})
        self.context.runtime_attached_file_ids = []
        self.context.runtime_loaded_skills = []

    def link(self):
        self.context.runtime_attached_file_ids = [self.record["id"]]

    def test_renamed_skill_is_discoverable(self):
        names = {skill["name"] for skill in list_skills()["skills"]}
        self.assertIn("directory_link", names)
        self.assertNotIn("project", names)
        self.assertIn("project_tree", load_skill("directory_link")["skill"]["content"])

    def test_attaching_folder_projects_skill_without_loading_action(self):
        before = build_tool_results_context(self.context)
        self.assertNotIn('skill="directory_link"', before)
        self.assertIn('directory_link', build_skills_inventory_context(self.context))
        self.assertNotIn('directory_link (loaded)', build_skills_inventory_context(self.context))

        self.link()
        first = build_tool_results_context(self.context)
        second = build_tool_results_context(self.context)
        self.assertEqual(first, second)
        self.assertIn('<TOOL_RESULT name="LOAD_SKILL" skill="directory_link" source="linked_folder">', first)
        self.assertIn("Mandatory workflow:", first)
        self.assertIn('project_tree', first)
        self.assertEqual(first.count('skill="directory_link"'), 1)
        self.assertIn('directory_link (loaded)', build_skills_inventory_context(self.context))
        self.assertEqual(self.context.runtime_loaded_skills, [])
        self.assertFalse(getattr(self.context, 'runtime_tool_results', []))

        begin_runtime_tool_results_turn(self.context)
        self.assertIn('skill="directory_link"', build_tool_results_context(self.context))
        self.context.runtime_attached_file_ids = []
        self.assertNotIn('skill="directory_link"', build_tool_results_context(self.context))
        self.assertNotIn('directory_link (loaded)', build_skills_inventory_context(self.context))

    def test_brain_and_followup_prompts_both_include_linked_skill(self):
        self.link()
        prompt = build_brain_context(self.context, runtime_actions=BRAIN_RUNTIME_ACTIONS)
        self.assertIn('skill="directory_link" source="linked_folder"', prompt)
        self.assertIn('directory_link (loaded)', prompt)
        followup = BrainNode.build_followup_system_prompt(prompt, "inspect linked directory", context=self.context)
        self.assertIn('skill="directory_link" source="linked_folder"', followup)
        self.context.runtime_attached_file_ids = []
        detached_prompt = build_brain_context(self.context, runtime_actions=BRAIN_RUNTIME_ACTIONS)
        self.assertNotIn('skill="directory_link"', detached_prompt)

    def test_project_actions_work_without_manual_skill_after_link(self):
        self.link()
        payload = '{"action":"project_tree","attachment":"My Folder","path":"."}'
        result = asyncio.run(run_context_asset_action(payload, context=self.context))
        self.assertTrue(result['ok'], result)
        self.assertIn('My Folder/photo.png', result['content'])
        # Other skills must still be explicitly loaded.
        denied = asyncio.run(run_context_asset_action('{"action":"project_read","attachment":"My Folder","path":"photo.png"}', context=self.context))
        self.assertFalse(denied['ok'])
        self.assertIn('file_manager', str(denied))
        self.context.runtime_attached_file_ids = []
        denied = asyncio.run(run_context_asset_action(payload, context=self.context))
        self.assertFalse(denied['ok'])

    def test_explicit_loaded_skill_does_not_duplicate_automatic_copy(self):
        self.link()
        self.context.runtime_loaded_skills = [load_skill('directory_link')['skill']]
        tools = build_tool_results_context(self.context)
        self.assertEqual(tools.count('skill="directory_link"'), 1)

    def test_staged_restore_does_not_prematurely_project_skill(self):
        self.context.runtime_session_restore_priming = True
        self.context.runtime_session_restore_pending_attached_file_ids = [self.record['id']]
        self.assertNotIn('skill="directory_link"', build_tool_results_context(self.context))
        self.link()
        self.assertIn('skill="directory_link"', build_tool_results_context(self.context))


if __name__ == '__main__':
    unittest.main()
