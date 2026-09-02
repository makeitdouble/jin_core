import json
import shutil
import subprocess
import unittest
from pathlib import Path

from utils.actions import RuntimeActionStreamFilter, extract_runtime_actions


ROOT = Path(__file__).resolve().parents[1]
WRAPPERS = (
    ('"', '"'), ("'", "'"), ("`", "`"), ("«", "»"), ("‹", "›"),
    ("“", "”"), ("‘", "’"), ("„", "“"), ("‚", "‘"),
    ("(", ")"), ("[", "]"), ("{", "}"),
)
MARKERS = (
    "<UPDATE_LT_FACTS>",
    "<UPDATE_LT_FACTS>Remember this.</UPDATE_LT_FACTS>",
    "<WEB_SEARCH: test query>",
    "<DEEP_WEB_SEARCH>research this</DEEP_WEB_SEARCH>",
    "<CLEAN_TOOL_RESULTS>",
    "</CLEAN_TOOL_RESULTS>",
    "<JIN_COLOR> #00f2ff </JIN_COLOR>",
    "< JIN_COLOR : #00f2ff >",
    "<JIN_SIZE> w:120 h:120 </JIN_SIZE>",
    "<LOAD_SKILL: file_manager>",
    "<UNLOAD_SKILL: file_manager>",
    "<LOAD_SKILLS: file_manager, wildcards>",
    "<LOAD_DELAYED_MEMORY: abc123>",
    "<UNLOAD_DELAYED_MEMORY: abc123>",
    "<LIST_FILES>",
    "<ATTACH_FILE: abc123>",
    "<DETACH_FILE: abc123>",
    "<DELETE_ACTIVE_MEMORY: abc123>",
    '<SAVE_ACTIVE_MEMORY>{"conditions":"test"}</SAVE_ACTIVE_MEMORY>',
    '<UPDATE_ACTIVE_MEMORY>{"active_memory_id":"abc123","conditions":"test"}</UPDATE_ACTIVE_MEMORY>',
    "<JIN_POSITION> x:150px y:50px </JIN_POSITION>",
    "<JIN_SPEED> 600px/s </JIN_SPEED>",
    '<ASSET_ACTION>{"action":"list_files"}</ASSET_ACTION>',
    '<SAVE_DELAYED_MEMORY>{"title":"note","summary":"test","body":"text"}',
    '<UPDATE_ACTIVE_MEMORY active_memory_id="abc123" field="x" value="y" />',
)


def stream_results(text, cuts):
    stream = RuntimeActionStreamFilter()
    points = [0, *cuts, len(text)]
    results = [stream.filter(text[a:b]) for a, b in zip(points, points[1:])]
    results.append(stream.flush_result())
    return results


class QuotedRuntimeMarkerTests(unittest.TestCase):
    def assert_literal(self, text, results):
        self.assertEqual("".join(result.text for result in results), text)
        for result in results:
            self.assertFalse(result.actions)
            self.assertFalse(result.observed_actions)
            self.assertFalse(result.started_actions)
            self.assertFalse(result.removed_markers)
            self.assertFalse(result.marker_repetition_exceeded)

    def test_quotes_and_brackets_preserve_markers_in_batch_and_stream(self):
        for opening, closing in WRAPPERS:
            for marker in MARKERS:
                text = f"before {opening}{marker}{closing} after"
                with self.subTest(text=text):
                    self.assert_literal(text, [extract_runtime_actions(text)])
                    self.assert_literal(text, stream_results(text, range(1, len(text))))
                    for split in range(1, len(text)):
                        self.assert_literal(text, stream_results(text, [split]))

    def test_screenshot_and_incomplete_literals_survive_stop(self):
        for text in (
            "Долгосрочные факты: создавать и обновлять (`<UPDATE_LT_FACTS>`). После.",
            '"<UPDATE_LT_',
            '(<UPDATE_ACTIVE_MEMORY field="conditions"',
            '`<JIN_COLOR',
            '«<NOT_A_RUNTIME_ACTION>»',
            "text (", "text `", "text [",
        ):
            with self.subTest(text=text):
                self.assert_literal(text, stream_results(text, range(1, len(text))))

    def test_real_action_after_quoted_opening_still_runs_once(self):
        text = '"<UPDATE_LT_FACTS>" then <UPDATE_LT_FACTS>real fact</UPDATE_LT_FACTS>'
        for cuts in ([], list(range(1, len(text))), [2, 18, 27, 30]):
            results = stream_results(text, cuts)
            self.assertEqual([a.name for r in results for a in r.actions], ["UPDATE_LT_FACTS"])
            self.assertEqual([a.name for r in results for a in r.started_actions], ["UPDATE_LT_FACTS"])
            visible = "".join(r.text for r in results)
            self.assertEqual(visible.rstrip(), '\"<UPDATE_LT_FACTS>\" then')
        result = extract_runtime_actions(text)
        self.assertEqual(len(result.actions), 1)
        self.assertIn("real fact", result.actions[0].payload)

    def test_quote_rule_is_immediate_and_does_not_disable_real_markers(self):
        for text in (
            '<CLEAN_TOOL_RESULTS>',
            '(<CLEAN_TOOL_RESULTS>) <CLEAN_TOOL_RESULTS>',
            '" <CLEAN_TOOL_RESULTS>',
            ')<CLEAN_TOOL_RESULTS>',
            '<CLEAN_TOOL_RESULTS>' * 3,
        ):
            expected = 3 if text.endswith('<CLEAN_TOOL_RESULTS>' * 3) else 1
            for cuts in ([], list(range(1, len(text)))):
                results = stream_results(text, cuts)
                self.assertEqual(len([a for r in results for a in r.actions]), expected)

    def test_quoted_delimiter_inside_real_payload_does_not_close_action(self):
        text = '<UPDATE_LT_FACTS>Use "<UPDATE_LT_FACTS>" in docs.</UPDATE_LT_FACTS>'
        for cuts in ([], list(range(1, len(text)))):
            results = stream_results(text, cuts)
            actions = [a for r in results for a in r.actions]
            self.assertEqual(len(actions), 1)
            self.assertEqual(json.loads(actions[0].payload)["message"], 'Use "<UPDATE_LT_FACTS>" in docs.')
            self.assertEqual("".join(r.text for r in results), "")

    def test_two_stream_filters_do_not_reinterpret_literal_text(self):
        text = 'Example (`<UPDATE_LT_FACTS>`). "<CLEAN_TOOL_RESULTS>" End.'
        outer = RuntimeActionStreamFilter()
        results = [outer.filter(r.text) for r in stream_results(text, range(1, len(text)))]
        results.append(outer.flush_result())
        self.assert_literal(text, results)

    @unittest.skipUnless(shutil.which("node"), "node is required")
    def test_markdown_plain_rendering_and_client_cleanup_keep_literals(self):
        script = r"""
const fs = require("fs");
global.window = {};
eval(fs.readFileSync(process.argv[1], "utf8"));
const source = fs.readFileSync(process.argv[2], "utf8");
eval(source.slice(source.indexOf("function escapeHtml("), source.indexOf("function isJinMemoryReferenceRole(")));
eval(source.slice(source.indexOf("function stripInternalActionMarkers("), source.indexOf("function collapseAnswerMarkerGap(")));
const wrappers = JSON.parse(process.argv[3]);
for (const [open, close] of wrappers) {
  for (const tag of ["<UPDATE_LT_FACTS>", "<JIN_COLOR>#00f2ff</JIN_COLOR>", "<JIN_SIZE>120px</JIN_SIZE>"]) {
    const text = `before ${open}${tag}${close} after`;
    for (const html of [window.JinResponseFormatter.render(text), renderChatTextHtml(text)]) {
      if (!html.includes("&lt;" + tag.slice(1).split(">")[0] + "&gt;") || html.includes("jin-chat-runtime-marker")) {
        throw new Error(`literal marker was transformed: ${text}: ${html}`);
      }
    }
    if (stripInternalActionMarkers(text) !== text) throw new Error("literal stripped");
  }
}
if (!window.JinResponseFormatter.render("<JIN_COLOR>#00f2ff</JIN_COLOR>").includes("jin-chat-runtime-marker")) {
  throw new Error("real visual marker no longer renders");
}
"""
        completed = subprocess.run([
            shutil.which("node"), "-e", script,
            str(ROOT / "ui/static/js/chat-response-formatter.js"),
            str(ROOT / "ui/static/js/chat.js"), json.dumps(WRAPPERS),
        ], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
