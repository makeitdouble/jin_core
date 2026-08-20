from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
FORMATTER_JS = ROOT / "ui" / "static" / "js" / "chat-response-formatter.js"
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"


class ChatResponseFormatterTests(unittest.TestCase):

    @unittest.skipUnless(
        shutil.which("node"),
        "node is required for the browser-side response formatter test",
    )
    def test_nested_italic_inside_bold_is_rendered_without_literal_markers(self):
        script = r'''
const fs = require("fs");
global.window = {};
eval(fs.readFileSync(process.argv[1], "utf8"));

const input = "**Outer text with *nested italic* inside.**";
const expected = "<p><strong>Outer text with <em>nested italic</em> inside.</strong></p>";
const actual = window.JinResponseFormatter.render(input);

if (actual !== expected) {
  throw new Error(`unexpected nested emphasis rendering: ${JSON.stringify(actual)}`);
}
'''
        completed = subprocess.run(
            [
                shutil.which("node"),
                "-e",
                script,
                str(FORMATTER_JS),
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

    @unittest.skipUnless(
        shutil.which("node"),
        "node is required for the browser-side response formatter test",
    )
    def test_combined_bold_italic_delimiters_keep_valid_nesting(self):
        script = r'''
const fs = require("fs");
global.window = {};
eval(fs.readFileSync(process.argv[1], "utf8"));

const cases = [
  ["***both***", "<p><strong><em>both</em></strong></p>"],
  ["___both___", "<p><strong><em>both</em></strong></p>"],
];

for (const [input, expected] of cases) {
  const actual = window.JinResponseFormatter.render(input);

  if (actual !== expected) {
    throw new Error(
      `unexpected combined emphasis rendering for ${JSON.stringify(input)}: ${JSON.stringify(actual)}`
    );
  }
}
'''
        completed = subprocess.run(
            [
                shutil.which("node"),
                "-e",
                script,
                str(FORMATTER_JS),
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

    @unittest.skipUnless(
        shutil.which("node"),
        "node is required for the browser-side response formatter test",
    )
    def test_underscores_inside_names_do_not_render_as_italic(self):
        script = r'''
const fs = require("fs");
global.window = {};
eval(fs.readFileSync(process.argv[1], "utf8"));

const cases = [
  [
    "1put0q_СинтезИнтеллектикакконтролируемыйхаос_Эволюциячерез_ошибку",
    "<p>1put0q_СинтезИнтеллектикакконтролируемыйхаос_Эволюциячерез_ошибку</p>",
  ],
  [
    "abc_Project_context",
    "<p>abc_Project_context</p>",
  ],
  [
    "before _italic_ after",
    "<p>before <em>italic</em> after</p>",
  ],
  [
    "before ___both___ after",
    "<p>before <strong><em>both</em></strong> after</p>",
  ],
];

for (const [input, expected] of cases) {
  const actual = window.JinResponseFormatter.render(input);

  if (actual !== expected) {
    throw new Error(
      `unexpected underscore emphasis rendering for ${JSON.stringify(input)}: ${JSON.stringify(actual)}`
    );
  }
}
'''
        completed = subprocess.run(
            [
                shutil.which("node"),
                "-e",
                script,
                str(FORMATTER_JS),
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

    @unittest.skipUnless(
        shutil.which("node"),
        "node is required for the browser-side response formatter test",
    )
    def test_jin_size_marker_is_rendered_as_runtime_marker(self):
        script = r'''
const fs = require("fs");
global.window = {};
eval(fs.readFileSync(process.argv[1], "utf8"));

const html = window.JinResponseFormatter.render("before <JIN_SIZE> w:220px h:440px </JIN_SIZE> after");

if (!html.includes("jin-chat-jin-size-marker")) {
  throw new Error(`size marker class missing: ${html}`);
}

if (!html.includes("w:220px h:440px")) {
  throw new Error(`normalized size missing: ${html}`);
}
'''
        completed = subprocess.run(
            [
                shutil.which("node"),
                "-e",
                script,
                str(FORMATTER_JS),
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

    def test_formatter_script_cache_version_is_bumped(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn(
            '/static/js/chat-response-formatter.js?v=jin-size-1',
            source,
        )


if __name__ == "__main__":
    unittest.main()
