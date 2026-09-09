from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
FORMATTER_JS = ROOT / "ui" / "static" / "js" / "think-formatter.js"
THINK_CITATIONS_JS = ROOT / "ui" / "static" / "js" / "think-citations.js"
CHAT_JS = ROOT / "ui" / "static" / "js" / "chat.js"
CHAT_CSS = ROOT / "ui" / "static" / "css" / "chat.css"
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"


class ThinkFormatterClientContractTests(unittest.TestCase):

    @unittest.skipUnless(
        shutil.which("node"),
        "node is required for the browser-side reasoning formatter test",
    )
    def test_reasoning_markers_are_structured_without_losing_code_math_or_citations(self):
        script = r'''
const fs = require("fs");

class FakeNode {
  constructor(type, name = "") {
    this.type = type;
    this.name = name;
    this.children = [];
    this.className = "";
    this.dataset = {};
    this.attributes = {};
    this.style = { setProperty: (key, value) => { this.attributes[`style:${key}`] = value; } };
    this.classList = {
      add: (...names) => {
        const values = new Set(this.className.split(/\s+/).filter(Boolean));
        names.forEach(name => values.add(name));
        this.className = [...values].join(" ");
      },
      remove: (...names) => {
        const values = new Set(this.className.split(/\s+/).filter(Boolean));
        names.forEach(name => values.delete(name));
        this.className = [...values].join(" ");
      },
      contains: name => this.className.split(/\s+/).filter(Boolean).includes(name),
    };
  }

  appendChild(node) {
    if (node.type === "fragment") {
      [...node.children].forEach(child => this.appendChild(child));
      return node;
    }
    this.children.push(node);
    return node;
  }

  replaceChildren(...nodes) {
    this.children = [];
    nodes.forEach(node => this.appendChild(node));
  }

  setAttribute(key, value) {
    this.attributes[key] = String(value);
  }

  set textContent(value) {
    this.children = [new FakeText(String(value))];
  }

  get textContent() {
    return this.children.map(child => child.textContent).join("");
  }
}

class FakeText extends FakeNode {
  constructor(text) {
    super("text");
    this.text = text;
  }
  get textContent() { return this.text; }
  set textContent(value) { this.text = String(value); }
}

global.document = {
  createElement: name => new FakeNode("element", name),
  createTextNode: text => new FakeText(text),
  createDocumentFragment: () => new FakeNode("fragment"),
};
global.window = {};

eval(fs.readFileSync(process.argv[1], "utf8"));

const input = [
  "The user wants a direct answer.",
  "",
  "    *   *Technical Truth:* I am a Large Language Model and calculate $2+2$.",
  "    *   *Structure:*",
  "        1.  Acknowledge the request.",
  "        2.  Keep the *Hard Truth* direct.",
  "    *",
  "",
  "    *   *Drafting the response:*",
  "        \"Okay, no more metaphors.\"",
  "",
  "    ```",
  "      /\\_/\\",
  "     ( o.o )",
  "    ```",
].join("\n");

const citationText = "Large Language Model";
const citationStart = input.indexOf(citationText);
const root = new FakeNode("element", "div");

window.JinThinkFormatter.render(root, input, {
  decorations: [{
    start: citationStart,
    end: citationStart + citationText.length,
    className: "think-rule-hit think-citation-runtime exact",
    title: "citation",
    ariaLabel: "citation",
    score: 1,
  }],
});

function walk(node, out = []) {
  out.push(node);
  node.children.forEach(child => walk(child, out));
  return out;
}

const nodes = walk(root);
const classes = nodes.map(node => node.className || "");
const visible = root.textContent;

if (visible.includes("*Technical Truth:*") || visible.includes("*Structure:*")) {
  throw new Error(`literal reasoning markers leaked into visible text: ${visible}`);
}
if (!visible.includes("Technical Truth:") || !visible.includes("Structure:")) {
  throw new Error(`semantic labels were lost: ${visible}`);
}
if (!visible.includes("2+2") || visible.includes("$2+2$")) {
  throw new Error(`inline math was not normalized: ${visible}`);
}
if (!visible.includes("/\\_/\\\n     ( o.o )")) {
  throw new Error(`fenced ASCII was not preserved: ${visible}`);
}
if (!classes.some(value => value.includes("jin-think-list-item"))) {
  throw new Error("list structure missing");
}
if (!classes.some(value => value.includes("is-nested"))) {
  throw new Error("single nested reasoning level missing");
}
if (!classes.some(value => value.includes("is-section-child"))) {
  throw new Error("draft continuation grouping missing");
}
if (!classes.some(value => value.includes("think-citation-runtime exact"))) {
  throw new Error("citation decoration was lost during formatting");
}
if (root.__jinThinkRawText !== input) {
  throw new Error("raw reasoning text must remain available for citation offsets");
}

const streamingRoot = new FakeNode("element", "div");
const streamingPrefix = "    *   *Technical Truth:* first\n";
window.JinThinkFormatter.renderStreaming(
  streamingRoot,
  `${streamingPrefix}    *   *Struc`,
  { decorations: [] },
);
if (streamingRoot.textContent.includes("*Technical Truth:*")) {
  throw new Error("completed streaming lines must already be formatted");
}
const firstTail = streamingRoot.__jinThinkStreamingFormatState.tailElement;
window.JinThinkFormatter.renderStreaming(
  streamingRoot,
  `${streamingPrefix}    *   *Structure`,
  { decorations: [] },
);
if (streamingRoot.__jinThinkStreamingFormatState.tailElement !== firstTail) {
  throw new Error("unfinished streaming line should update without rebuilding stable lines");
}
window.JinThinkFormatter.renderStreaming(
  streamingRoot,
  `${streamingPrefix}    *   *Structure:*\n`,
  { decorations: [] },
);
if (streamingRoot.textContent.includes("*Structure:*")) {
  throw new Error("streaming tail must become structured after its newline");
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

    def test_reasoning_formatter_is_an_optional_citation_preserving_layer(self):
        citations = THINK_CITATIONS_JS.read_text(encoding="utf-8")
        chat = CHAT_JS.read_text(encoding="utf-8")
        css = CHAT_CSS.read_text(encoding="utf-8")
        index = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn("function renderStructuredThinkContent(", citations)
        self.assertIn("buildThinkFormatterDecorations(", citations)
        self.assertIn('element.classList.remove(\n          "is-structured"', citations)
        self.assertIn("const useStructuredFormatting =", citations)
        self.assertIn("Boolean(job.done || job.streaming)", citations)
        self.assertIn("structuredStreamingAvailable", citations)
        self.assertIn("const canRenderStructuredThinking = Boolean(", chat)
        self.assertIn("renderStreaming", chat)
        self.assertIn("done: true,", citations)
        self.assertIn(".jin-think-content.is-structured", css)
        self.assertIn("katex.renderToString", FORMATTER_JS.read_text(encoding="utf-8"))
        self.assertIn("MATRIX_START_PATTERN", FORMATTER_JS.read_text(encoding="utf-8"))
        self.assertIn("/static/js/think-formatter.js", index)
        self.assertLess(
            index.index("/static/js/think-formatter.js"),
            index.index("/static/js/think-citations.js"),
        )


if __name__ == "__main__":
    unittest.main()
