from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
FORMATTER_JS = ROOT / "ui" / "static" / "js" / "chat-response-formatter.js"
REACTIONS_JS = ROOT / "ui" / "static" / "js" / "chat-reactions.js"
CHAT_JS = ROOT / "ui" / "static" / "js" / "chat.js"
SOCKET_ACTIONS_JS = ROOT / "ui" / "static" / "js" / "socket" / "runtime-actions.js"
SOCKET_EVENT_HANDLERS_JS = ROOT / "ui" / "static" / "js" / "socket" / "event-handlers.js"
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"


class JinReactionUiTests(unittest.TestCase):

    @unittest.skipUnless(
        shutil.which("node"),
        "node is required for the browser-side response formatter test",
    )
    def test_formatter_turns_marker_into_invisible_source_anchor(self):
        script = r'''
const fs = require("fs");
global.window = {};
eval(fs.readFileSync(process.argv[1], "utf8"));

const actual = window.JinResponseFormatter.render(
  "before <JIN_REACTION: 😂 > after"
);

if (!actual.includes('class="jin-chat-jin-reaction-anchor"')) {
  throw new Error(`reaction source anchor missing: ${JSON.stringify(actual)}`);
}
if (!actual.includes('data-jin-reaction-emoji="😂"')) {
  throw new Error(`reaction emoji missing: ${JSON.stringify(actual)}`);
}
if (actual.includes("JIN_REACTION")) {
  throw new Error(`raw reaction marker leaked: ${JSON.stringify(actual)}`);
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
    def test_leading_reaction_markers_do_not_add_blank_answer_lines(self):
        script = r'''
const fs = require("fs");
global.window = {};
eval(fs.readFileSync(process.argv[1], "utf8"));

const leading = window.JinResponseFormatter.render(
  "\n<JIN_REACTION: 🤨 >\n<JIN_REACTION: 👋 >\nОтвет начинается сразу."
);
const middle = window.JinResponseFormatter.render(
  "До\n<JIN_REACTION: 🤨 >\nПосле"
);

if ((leading.match(/<br>/g) || []).length !== 0) {
  throw new Error(`leading reaction markers added blank lines: ${JSON.stringify(leading)}`);
}
if ((middle.match(/<br>/g) || []).length !== 2) {
  throw new Error(`non-leading reaction spacing changed: ${JSON.stringify(middle)}`);
}
if ((leading.match(/jin-chat-jin-reaction-anchor/g) || []).length !== 2) {
  throw new Error(`leading reaction anchors missing: ${JSON.stringify(leading)}`);
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
        "node is required for the browser-side chat renderer test",
    )
    def test_user_message_keeps_runtime_markers_literal(self):
        script = r'''
const fs = require("fs");
global.window = {};
eval(fs.readFileSync(process.argv[1], "utf8"));
const chatSource = fs.readFileSync(process.argv[2], "utf8");
eval(chatSource.slice(
  chatSource.indexOf("function escapeHtml("),
  chatSource.indexOf("function isStreamDebugEnabled(")
));

const makeElement = () => ({
  classList: { toggle() {} },
  dataset: {},
  innerHTML: "",
});
const userText = "before <JIN_REACTION: 😂 > <JIN_COLOR> #ff0000 </JIN_COLOR> after";
const userElement = makeElement();
renderChatTextElement(userElement, userText, {
  format: shouldFormatChatRole("user"),
  interpretRuntimeMarkers: shouldInterpretChatRuntimeMarkers("user"),
});

if (userElement.innerHTML.includes("jin-chat-jin-reaction-anchor")) {
  throw new Error(`USER reaction marker was interpreted: ${userElement.innerHTML}`);
}
if (userElement.innerHTML.includes("jin-chat-runtime-marker")) {
  throw new Error(`USER visual marker was interpreted: ${userElement.innerHTML}`);
}
if (!userElement.innerHTML.includes("&lt;JIN_REACTION: 😂 &gt;")) {
  throw new Error(`USER reaction marker was not kept literal: ${userElement.innerHTML}`);
}
if (!userElement.innerHTML.includes("&lt;JIN_COLOR&gt; #ff0000 &lt;/JIN_COLOR&gt;")) {
  throw new Error(`USER color marker was not kept literal: ${userElement.innerHTML}`);
}

const brainElement = makeElement();
renderChatTextElement(brainElement, "before <JIN_REACTION: 😂 > after", {
  format: false,
  interpretRuntimeMarkers: shouldInterpretChatRuntimeMarkers("brain"),
});
if (!brainElement.innerHTML.includes("jin-chat-jin-reaction-anchor")) {
  throw new Error(`BRAIN reaction marker stopped rendering: ${brainElement.innerHTML}`);
}
'''
        completed = subprocess.run(
            [
                shutil.which("node"),
                "-e",
                script,
                str(FORMATTER_JS),
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

    def test_socket_user_messages_bypass_assistant_marker_cleanup(self):
        source = SOCKET_EVENT_HANDLERS_JS.read_text(encoding="utf-8")
        function_start = source.index("function handleSocketChatMessage(")
        function_end = source.index("function handleThinkingChunk(", function_start)
        function_source = source[function_start:function_end]

        self.assertIn(
            'if (role !== "user")',
            function_source,
        )
        self.assertLess(
            function_source.index('if (role !== "user")'),
            function_source.index('filterDelayedMemoryContentFromChunk('),
        )
        self.assertLess(
            function_source.index('if (role !== "user")'),
            function_source.index('window.stripInternalActionMarkers('),
        )

    def test_reaction_flight_uses_exact_marker_anchor_and_current_user_bubble(self):
        source = REACTIONS_JS.read_text(encoding="utf-8")

        self.assertIn(
            '.jin-chat-jin-reaction-anchor',
            source,
        )
        self.assertIn(
            '.jin-stream-wrapper',
            source,
        )
        self.assertIn(
            '.jin-message-shell[data-role="user"]',
            source,
        )
        self.assertIn(
            'REACTION_FLIGHT_MS = 620',
            source,
        )
        self.assertIn(
            'cubic-bezier(0.22, 0.78, 0.2, 1)',
            source,
        )

        animate_index = source.index(
            'animateReaction(\n      anchor,\n      badge,\n      emoji\n    );'
        )
        hide_index = source.index(
            'hideReactionAnchors(\n      answerElement,\n      emoji\n    );',
            animate_index,
        )
        self.assertLess(
            animate_index,
            hide_index,
            'source anchor must stay laid out until its launch coordinates are read',
        )

    def test_socket_routes_reaction_away_from_generic_action_bubble(self):
        source = SOCKET_ACTIONS_JS.read_text(encoding="utf-8")

        self.assertIn(
            'action === "jin_reaction"',
            source,
        )
        self.assertIn(
            'window.JinChatReactions.handleRuntimeAction(data)',
            source,
        )

    def test_reaction_assets_are_loaded(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn(
            '/static/css/chat-reactions.css?v=jin-reaction-2',
            source,
        )
        self.assertIn(
            '/static/js/chat-reactions.js?v=jin-reaction-2',
            source,
        )
        self.assertIn(
            '/static/js/chat-response-formatter.js?v=jin-size-1&jin-reaction=1',
            source,
        )


if __name__ == "__main__":
    unittest.main()
