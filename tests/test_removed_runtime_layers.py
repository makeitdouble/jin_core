import contextlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from clients.brain_client import build_brain_context_snapshot
from contracts.rules_assembler import get_action_contracts, get_enabled_runtime_actions
from rules.brain_context_builder import BRAIN_RUNTIME_ACTIONS, build_brain_context
from runtime.L1_memory import (
    summarize_runtime_memory,
    summarize_runtime_memory_pending_turns,
)
from tests.helpers.runtime_actions import FakeContext, FakeEmitter, patch_asset_roots
from utils.actions import RuntimeActionCall, RuntimeActionStreamFilter, extract_runtime_actions
from utils.actions.dispatcher import apply_runtime_action_calls


class RemovedRuntimeLayerTests(unittest.TestCase):
    def test_obsolete_flag_cannot_enable_removed_actions(self):
        actions = get_enabled_runtime_actions({**BRAIN_RUNTIME_ACTIONS, "CAN_RUNTIME_TODO": True})
        removed = {"CREATE_TODO_LIST", "CHECK_TODO", "RESOLVE_TODO"}
        self.assertTrue(removed.isdisjoint(actions))
        self.assertTrue(removed.isdisjoint(
            contract["runtime_action"] for contract in get_action_contracts().values()
        ))
        self.assertTrue({"ASSET_ACTION", "LOAD_SKILL", "SAVE_ACTIVE_MEMORY"}.issubset(actions))

    def test_obsolete_markers_do_not_execute_or_break_adjacent_actions(self):
        markers = (
            "<TODO_LIST>1. Old task</TODO_LIST>",
            "<CREATE_TODO_LIST>1. Old task</CREATE_TODO_LIST>",
            "<INTERNAL_ACTION_TODO_LIST>1. Old task</INTERNAL_ACTION_TODO_LIST>",
            "<CHECK_TODO: 1>",
            "<RESOLVE_TODO: 1>",
            "<TODO_LIST",  # incomplete old marker must not buffer forever
        )
        enabled = (*get_enabled_runtime_actions(BRAIN_RUNTIME_ACTIONS),
                   "CREATE_TODO_LIST", "CHECK_TODO", "RESOLVE_TODO")
        for marker in markers:
            text = f"before {marker} after <JIN_COLOR> #123456 </JIN_COLOR>"
            with self.subTest(marker=marker):
                parsed = extract_runtime_actions(text, enabled_actions=enabled)
                self.assertEqual([(a.name, a.payload) for a in parsed.actions],
                                 [("JIN_COLOR", "#123456")])
                for split in range(len(text) + 1):
                    stream = RuntimeActionStreamFilter(enabled_actions=enabled)
                    chunks = [stream.filter(text[:split]), stream.filter(text[split:]),
                              stream.flush_result()]
                    self.assertEqual([(a.name, a.payload) for c in chunks for a in c.actions],
                                     [("JIN_COLOR", "#123456")], (marker, split))

    def test_legacy_state_is_ignored_and_context_snapshot_keeps_actual_prompt(self):
        context = SimpleNamespace(
            runtime_memory="active_topic: Preserve FRAME.",
            runtime_todo=[{"id": 1, "text": "obsolete_task_sentinel", "status": "pending"}],
        )
        prompt = build_brain_context(context, user_input="Continue")
        self.assertIn("Preserve FRAME.", prompt)
        self.assertNotIn("obsolete_task_sentinel", prompt)
        self.assertNotIn("CURRENT_RUNTIME_TODO_LIST", prompt)
        self.assertEqual(build_brain_context_snapshot(system_prompt=prompt, user_prompt="Continue"),
                         {"context_role": "brain", "system_prompt": prompt, "user_prompt": "Continue"})

    @unittest.skipUnless(shutil.which("node"), "node is required")
    def test_memory_socket_retains_frame_glow_and_active_updates(self):
        script = r'''
const fs = require("fs"), vm = require("vm"), assert = require("assert");
const handlers = {}, classes = new Set(), timers = new Map();
let nextTimer = 0, activeRecords;
const panel = {classList: {
  add: (...items) => items.forEach(item => classes.add(item)),
  remove: (...items) => items.forEach(item => classes.delete(item)),
  contains: item => classes.has(item),
}};
const window = {JinRuntime: {runtime: {
  replaceActiveMemoryRecords: records => { activeRecords = records; },
}}};
vm.runInNewContext(fs.readFileSync(process.argv[1], "utf8"), {
  window, document: {getElementById: () => panel},
  setTimeout: fn => { timers.set(++nextTimer, fn); return nextTimer; },
  clearTimeout: id => timers.delete(id), appendLog() {},
  registerSocketMessageHandler: (name, fn) => { handlers[name] = fn; },
});
assert.deepStrictEqual(Object.keys(handlers).sort(), ["active_memory_records_update", "log"]);
handlers.active_memory_records_update({active_memory_records: ["keep active"]});
assert.deepStrictEqual(activeRecords, ["keep active"]);
handlers.log({tag: "[MEMORY:L1]", memory_level: "L1", memory_event: "summarizer_request"});
assert(classes.has("memory-updating"));
handlers.log({tag: "[MEMORY:L1]", memory_level: "L1", memory_event: "summarizer_result"});
assert(classes.has("memory-fading"));
window.cancelPanelGlows();
assert.strictEqual(classes.size, 0);
assert.strictEqual(timers.size, 0);
'''
        source = Path(__file__).resolve().parents[1] / "ui/static/js/socket/memory.js"
        result = subprocess.run(["node", "-e", script, str(source)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class RemovedRuntimeLayerAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_and_batch_frame_updates_preserve_values_without_confirmation_injection(self):
        memory = "user_fact: Prefers quiet places.\nactive_topic: Current discussion."
        response = {"choices": [{"message": {"content": memory}, "finish_reason": "stop"}]}
        for batch in (False, True):
            with self.subTest(batch=batch):
                context = SimpleNamespace(
                    clients={"service": object()}, runtime_memory="", runtime_memory_stable="",
                    runtime_memory_updates=0,
                    runtime_memory_pending_turns=[{"user_message": "это факт", "assistant_message": "OK"}],
                )
                target = "ask_runtime_memory_batch_model" if batch else "ask_runtime_memory_model"
                with patch(f"runtime.L1_memory.{target}", new=AsyncMock(return_value=response)), \
                     patch("runtime.L1_memory.emit_runtime_memory_update", new=AsyncMock()) as emit, \
                     patch("runtime.L1_memory.record_runtime_l1_diff", new=AsyncMock()):
                    if batch:
                        result = await summarize_runtime_memory_pending_turns(context=context)
                        self.assertEqual(context.runtime_memory_pending_turns, [])
                    else:
                        result = await summarize_runtime_memory(
                            context=context, user_message="это факт", assistant_message="OK")
                self.assertEqual(result, memory)
                self.assertEqual(context.runtime_memory_stable, memory)
                self.assertEqual(context.runtime_memory_updates, 1)
                emit.assert_awaited_once_with(context)

    async def test_existing_file_error_is_preserved_even_with_obsolete_task_state(self):
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
            await apply_runtime_action_calls(context, (RuntimeActionCall(
                name="ASSET_ACTION", payload=json.dumps({"action": "create_asset_file",
                    "path": "assets/outputs/existing.txt", "content": "replacement"}),
            ),))
            result = context.runtime_asset_results[0]
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], "file_exists")
            self.assertNotIn("runtime_todo_item", result)
            self.assertEqual(context.runtime_todo[0]["status"], "pending")
            self.assertEqual(output.read_text(encoding="utf-8"), "original")


if __name__ == "__main__":
    unittest.main()
