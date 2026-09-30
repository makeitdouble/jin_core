import shutil
import subprocess
import unittest
from pathlib import Path


class MemorySocketClientContractTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is required")
    def test_frame_glow_and_active_memory_updates_share_memory_socket(self):
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
assert.deepStrictEqual(Object.keys(handlers).sort(), ["active_memory_records_update", "log", "memory_profile_snapshot"]);
handlers.active_memory_records_update({active_memory_records: ["keep active"]});
assert.deepStrictEqual(activeRecords, ["keep active"]);
handlers.log({tag: "[MEMORY:FRAME]", memory_level: "FRAME", memory_event: "summarizer_request"});
assert(classes.has("memory-updating"));
handlers.log({tag: "[MEMORY:FRAME]", memory_level: "FRAME", memory_event: "summarizer_result"});
assert(classes.has("memory-fading"));
window.cancelPanelGlows();
assert.strictEqual(classes.size, 0);
assert.strictEqual(timers.size, 0);
'''
        source = Path(__file__).resolve().parents[1] / "ui/static/js/socket/memory.js"
        result = subprocess.run(
            ["node", "-e", script, str(source)],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
