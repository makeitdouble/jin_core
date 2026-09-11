from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
MEMORY_VIEW = ROOT / "ui" / "static" / "js" / "runtime" / "runtime-memory-view.js"


@unittest.skipUnless(shutil.which("node"), "node is required")
class MemoryHoverTextClientBehaviorTests(unittest.TestCase):
    def test_multiline_text_normalization(self):
        script = r'''
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync(process.argv[1], "utf8");
const start = source.indexOf("  function normalizeMemoryHoverText(");
const end = source.indexOf("  function formatMemoryMetadataValue(", start);
if (start < 0 || end < 0) throw new Error("normalizeMemoryHoverText helper not found");
const context = vm.createContext({String});
vm.runInContext(source.slice(start, end), context);
const normalize = context.normalizeMemoryHoverText;
const cases = [
  ["first\\nsecond", "first\nsecond"],
  ["first\\r\\nsecond", "first\nsecond"],
  ["first\r\nsecond", "first\nsecond"],
  ["first\rsecond", "first\nsecond"],
  [null, ""],
];
for (const [input, expected] of cases) {
  const actual = normalize(input);
  if (actual !== expected) {
    throw new Error(`unexpected normalization: ${JSON.stringify(actual)}`);
  }
}
'''
        completed = subprocess.run(
            ["node", "-e", script, str(MEMORY_VIEW)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stderr or completed.stdout,
        )


if __name__ == "__main__":
    unittest.main()
