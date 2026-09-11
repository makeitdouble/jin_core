from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
LOGGER_JS = ROOT / "ui" / "static" / "js" / "logger" / "logger.js"


class RuntimePanelClientContractTests(unittest.TestCase):


    @unittest.skipUnless(
        shutil.which("node"),
        "node is required for the browser-side JIN size test",
    )
    def test_jin_size_relative_units_resolve_against_live_viewport(self):
        script = r'''
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const start = source.indexOf("function normalizeJinSizeLength(");
const end = source.indexOf("function normalizeJinPositionPayload(", start);

if (start < 0 || end < 0) {
  throw new Error("JIN size normalization helpers not found");
}

global.window = { innerWidth: 2000, innerHeight: 1000 };
global.document = {
  documentElement: { clientWidth: 2000, clientHeight: 1000 },
};

const helpers = eval(
  `(() => { ${source.slice(start, end)}; return { normalizeJinSizePayload }; })()`
);
const cases = [
  ["120px", { width: 120, height: 120 }],
  ["w:25vw h:40vh", { width: 500, height: 400 }],
  ["w:50% h:25%", { width: 1000, height: 250 }],
  ["10%", { width: 200, height: 100 }],
  ["w:12.5vw h:20%", { width: 250, height: 200 }],
  [{ size: "w:25vw h:40%", width: 25, height: 40 }, { width: 500, height: 400 }],
];

for (const [input, expected] of cases) {
  const actual = helpers.normalizeJinSizePayload(input);
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`unexpected size for ${JSON.stringify(input)}: ${JSON.stringify(actual)}`);
  }
}

if (helpers.normalizeJinSizePayload("120em") !== null) {
  throw new Error("unsupported CSS unit must not be treated as px");
}
'''
        completed = subprocess.run(
            [
                shutil.which("node"),
                "-e",
                script,
                str(LOGGER_JS),
            ],
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
