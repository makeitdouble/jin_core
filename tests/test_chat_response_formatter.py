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

    @unittest.skipUnless(
        shutil.which("node"),
        "node is required for the browser-side response formatter test",
    )
    def test_jin_size_marker_preserves_supported_relative_units(self):
        script = r'''
const fs = require("fs");
global.window = {};
eval(fs.readFileSync(process.argv[1], "utf8"));

const normalize = window.JinResponseFormatter.normalizeJinSizeMarker;
const cases = [
  ["120", "120px"],
  ["12.5vw", "12.5vw"],
  ["w:25vw h:40vh", "w:25vw h:40vh"],
  ["width:50% height:25%", "w:50% h:25%"],
  ["200px 30vh", "w:200px h:30vh"],
];

for (const [input, expected] of cases) {
  const actual = normalize(input);
  if (actual !== expected) {
    throw new Error(`unexpected normalized size for ${input}: ${actual}`);
  }
}

if (normalize("120em") !== "") {
  throw new Error("unsupported CSS unit must not be displayed as px");
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
    def test_inline_dollar_math_is_rendered_without_markdown_mangling(self):
        script = r'''
const fs = require("fs");
const calls = [];
global.window = {
  katex: {
    renderToString(source, options) {
      calls.push([source, options]);
      return `<span class="mock-katex">${source}</span>`;
    },
  },
};
eval(fs.readFileSync(process.argv[1], "utf8"));

const html = window.JinResponseFormatter.render(
  "**Energy: $E=mc^2$**, fraction: $\\frac{a_b}{c^2}$, backslash: \\(x_1+y_2\\)."
);

if (!html.includes('<strong>Energy: <span class="mock-katex">E=mc^2</span></strong>')) {
  throw new Error(`inline equation was not rendered: ${html}`);
}

if (!html.includes('<span class="mock-katex">\\frac{a_b}{c^2}</span>')) {
  throw new Error(`LaTeX source was changed by markdown parsing: ${html}`);
}

if (!html.includes('<span class="mock-katex">x_1+y_2</span>')) {
  throw new Error(`\\(...\\) equation was not rendered: ${html}`);
}

if (calls.length !== 3 || calls.some(([, options]) => options.displayMode !== false)) {
  throw new Error(`unexpected inline KaTeX calls: ${JSON.stringify(calls)}`);
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
    def test_display_math_and_code_boundaries_are_preserved(self):
        script = r'''
const fs = require("fs");
const calls = [];
global.window = {
  katex: {
    renderToString(source, options) {
      calls.push([source, options.displayMode]);
      return `<span class="mock-katex" data-display="${options.displayMode}">${source}</span>`;
    },
  },
};
eval(fs.readFileSync(process.argv[1], "utf8"));

const input = [
  "before `$raw_math$` after",
  "",
  "$$",
  "\\frac{x_1}{y^2}",
  "$$",
  "",
  "```txt",
  "$also_raw$",
  "```",
  "",
  "A = \\begin{bmatrix}",
  "1 & 0 \\\\",
  "0 & 1",
  "\\end{bmatrix}",
  "$$",
].join("\n");
const html = window.JinResponseFormatter.render(input);

if (!html.includes("<code>$raw_math$</code>")) {
  throw new Error(`inline code was interpreted as math: ${html}`);
}

if (!html.includes("$also_raw$")) {
  throw new Error(`fenced code was interpreted as math: ${html}`);
}

if (!html.includes('data-display="true">\\frac{x_1}{y^2}</span>')) {
  throw new Error(`display equation was not rendered: ${html}`);
}

if (!html.includes('class="jin-chat-matrix-block"')) {
  throw new Error(`bare matrix block was not rendered: ${html}`);
}

if (!html.includes('A = \\begin{bmatrix}')) {
  throw new Error(`matrix assignment was not preserved: ${html}`);
}

if (html.includes("<p>$$</p>")) {
  throw new Error(`orphan matrix delimiter leaked into output: ${html}`);
}

if (calls.length !== 2 || calls.some(([, display]) => display !== true)) {
  throw new Error(`unexpected display KaTeX calls: ${JSON.stringify(calls)}`);
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
    def test_math_falls_back_to_literal_delimiters_when_katex_is_unavailable(self):
        script = r'''
const fs = require("fs");
global.window = {};
eval(fs.readFileSync(process.argv[1], "utf8"));

const html = window.JinResponseFormatter.render(
  "formula $a_b^2$ and price $5 and $10"
);

if (html !== "<p>formula $a_b^2$ and price $5 and $10</p>") {
  throw new Error(`unexpected no-KaTeX fallback: ${JSON.stringify(html)}`);
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

    def test_katex_assets_are_loaded_before_response_formatter(self):
        source = INDEX_HTML.read_text(encoding="utf-8")
        katex_script = (
            'https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js'
        )
        formatter_script = (
            '/static/js/chat-response-formatter.js?v=jin-size-1&jin-reaction=1'
            '&marker-spacing=2&math=2'
        )

        self.assertIn(
            'https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css',
            source,
        )
        self.assertIn(katex_script, source)
        self.assertIn(formatter_script, source)
        self.assertLess(
            source.index(katex_script),
            source.index(formatter_script),
        )

    def test_formatter_script_cache_version_is_bumped(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn(
            '/static/js/chat-response-formatter.js?v=jin-size-1',
            source,
        )


if __name__ == "__main__":
    unittest.main()
