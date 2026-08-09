from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
CHAT_JS = ROOT / "ui" / "static" / "js" / "chat.js"
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"


class ChatRuntimeMarkerUiTests(unittest.TestCase):

    @unittest.skipUnless(
        shutil.which("node"),
        "node is required for the browser-side marker filter test",
    )
    def test_empty_asset_action_blocks_stay_visible_in_chat(self):
        script = r'''
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const start = source.indexOf("function stripInternalActionMarkers(");
const end = source.indexOf("\nfunction collapseAnswerMarkerGap(", start);

if (start < 0 || end < 0) {
  throw new Error("stripInternalActionMarkers was not found");
}

eval(source.slice(start, end));

const cases = [
  ["<ASSET_ACTION>", "<ASSET_ACTION>"],
  ["<ASSET_ACTION/>", "<ASSET_ACTION/>"],
  ["<ASSET_ACTION></ASSET_ACTION>", "<ASSET_ACTION></ASSET_ACTION>"],
  ["</ASSET_ACTION>", "</ASSET_ACTION>"],
  [
    "<ASSET_ACTION>\n   \n</ASSET_ACTION>",
    "<ASSET_ACTION>\n   \n</ASSET_ACTION>",
  ],
  [
    "before\n<ASSET_ACTION></ASSET_ACTION>\nafter",
    "before\n<ASSET_ACTION></ASSET_ACTION>\nafter",
  ],
  [
    "before\n<ASSET_ACTION>{\"action\":\"test\"}</ASSET_ACTION>\nafter",
    "before\n\nafter",
  ],
];

for (const [input, expected] of cases) {
  const actual = stripInternalActionMarkers(input);

  if (actual !== expected) {
    throw new Error(
      `unexpected marker filtering for ${JSON.stringify(input)}: ${JSON.stringify(actual)}`
    );
  }
}
'''
        completed = subprocess.run(
            [
                shutil.which("node"),
                "-e",
                script,
                str(CHAT_JS),
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

    def test_chat_script_cache_version_is_bumped(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn(
            '/static/js/chat.js?v=reasoning-gap-1',
            source,
        )


if __name__ == "__main__":
    unittest.main()
