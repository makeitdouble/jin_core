import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from clients.brain_client import build_brain_context_snapshot
from contracts.rules_assembler import get_action_contracts, get_enabled_runtime_actions
from rules.brain_context_builder import BRAIN_RUNTIME_ACTIONS, build_brain_context
from tests.helpers.runtime_actions import FakeContext, FakeEmitter, patch_asset_roots
from utils.actions import RuntimeActionCall, RuntimeActionStreamFilter, extract_runtime_actions
from utils.actions.dispatcher import apply_runtime_action_calls


class RemovedTodoContractTests(unittest.TestCase):
    def test_obsolete_flag_cannot_enable_removed_actions(self):
        actions = get_enabled_runtime_actions({**BRAIN_RUNTIME_ACTIONS, "CAN_RUNTIME_TODO": True})
        removed = {"CREATE_TODO_LIST", "CHECK_TODO", "RESOLVE_TODO"}
        self.assertTrue(removed.isdisjoint(actions))
        self.assertTrue(
            removed.isdisjoint(
                contract["runtime_action"] for contract in get_action_contracts().values()
            )
        )
        self.assertTrue({"ASSET_ACTION", "LOAD_SKILL", "SAVE_ACTIVE_MEMORY"}.issubset(actions))

    def test_obsolete_markers_are_literal_and_do_not_break_adjacent_actions(self):
        markers = (
            "<TODO_LIST>1. Old task</TODO_LIST>",
            "<CREATE_TODO_LIST>1. Old task</CREATE_TODO_LIST>",
            "<INTERNAL_ACTION_TODO_LIST>1. Old task</INTERNAL_ACTION_TODO_LIST>",
            "<CHECK_TODO: 1>",
            "<RESOLVE_TODO: 1>",
            "<TODO_LIST",
        )
        enabled = (
            *get_enabled_runtime_actions(BRAIN_RUNTIME_ACTIONS),
            "CREATE_TODO_LIST",
            "CHECK_TODO",
            "RESOLVE_TODO",
        )

        for marker in markers:
            with self.subTest(marker=marker):
                text = f"before {marker} after <JIN_COLOR> #123456 </JIN_COLOR>"
                parsed = extract_runtime_actions(text, enabled_actions=enabled)
                self.assertEqual(
                    [(action.name, action.payload) for action in parsed.actions],
                    [("JIN_COLOR", "#123456")],
                )

        # Streaming fragmentation is parser infrastructure. Keep one representative
        # obsolete marker here to verify that it cannot swallow a following action.
        marker = markers[0]
        text = f"before {marker} after <JIN_COLOR> #123456 </JIN_COLOR>"
        for split in (1, len("before ") + len(marker) // 2, len(text) - 1):
            with self.subTest(split=split):
                stream = RuntimeActionStreamFilter(enabled_actions=enabled)
                chunks = [
                    stream.filter(text[:split]),
                    stream.filter(text[split:]),
                    stream.flush_result(),
                ]
                self.assertEqual(
                    [(action.name, action.payload) for chunk in chunks for action in chunk.actions],
                    [("JIN_COLOR", "#123456")],
                )

    def test_legacy_todo_state_is_ignored_by_brain_context(self):
        context = SimpleNamespace(
            runtime_memory="active_topic: Preserve FRAME.",
            runtime_todo=[{"id": 1, "text": "obsolete_task_sentinel", "status": "pending"}],
        )
        prompt = build_brain_context(context, user_input="Continue")
        self.assertIn("Preserve FRAME.", prompt)
        self.assertNotIn("obsolete_task_sentinel", prompt)
        self.assertNotIn("CURRENT_RUNTIME_TODO_LIST", prompt)
        self.assertEqual(
            build_brain_context_snapshot(system_prompt=prompt, user_prompt="Continue"),
            {"context_role": "brain", "system_prompt": prompt, "user_prompt": "Continue"},
        )


class RemovedTodoCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_obsolete_task_state_does_not_contaminate_asset_file_error(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            root = Path(directory)
            for patcher in patch_asset_roots(root):
                stack.enter_context(patcher)

            output = root / "assets/outputs/existing.txt"
            output.parent.mkdir(parents=True)
            output.write_text("original", encoding="utf-8")

            context = FakeContext()
            context.emitter = FakeEmitter()
            context.runtime_todo = [{"id": 1, "text": "Create file", "status": "pending"}]
            context.runtime_loaded_skills = [{"name": "file_manager"}]

            await apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="ASSET_ACTION",
                        payload=json.dumps(
                            {
                                "action": "create_asset_file",
                                "path": "assets/outputs/existing.txt",
                                "content": "replacement",
                            }
                        ),
                    ),
                ),
            )

            result = context.runtime_asset_results[0]
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], "file_exists")
            self.assertNotIn("runtime_todo_item", result)
            self.assertEqual(context.runtime_todo[0]["status"], "pending")
            self.assertEqual(output.read_text(encoding="utf-8"), "original")


if __name__ == "__main__":
    unittest.main()
