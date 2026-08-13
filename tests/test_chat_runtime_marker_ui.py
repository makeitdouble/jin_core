from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
CHAT_JS = ROOT / "ui" / "static" / "js" / "chat.js"
CHAT_RUNTIME_ACTIONS_JS = (
    ROOT / "ui" / "static" / "js" / "chat-runtime-actions.js"
)
SOCKET_RUNTIME_ACTIONS_JS = (
    ROOT / "ui" / "static" / "js" / "socket" / "runtime-actions.js"
)
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
  [
    "<DEEP_WEB_SEARCH>\nFind albums like Hitman.\n</DEEP_WEB_SEARCH>",
    "",
  ],
  [
    "<DEEP_WEB_SEARCH: research objective >\nFind albums like Hitman.\n</DEEP_WEB_SEARCH>",
    "",
  ],
  [
    "before\n<DEEP_WEB_SEARCH>\nFind albums.\n</DEEP_WEB_SEARCH>\nafter",
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
            '/static/js/chat.js?v=chat-input-overlay-1',
            source,
        )

        self.assertIn(
            '/static/js/chat-runtime-actions.js?v=runtime-action-icons-2',
            source,
        )

        self.assertIn(
            '/static/js/socket/runtime-actions.js?v=deep-search-bubbles-1',
            source,
        )
        self.assertIn(
            '/static/css/chat-runtime-action.css?v=runtime-action-icons-2',
            source,
        )

    def test_runtime_action_icons_cover_core_actions(self):
        chat_runtime_source = CHAT_RUNTIME_ACTIONS_JS.read_text(
            encoding="utf-8"
        )

        for action in (
            "web_search",
            "deep_web_search",
            "save_delayed_memory_content",
            "save_active_memory",
            "resolve_active_memory",
            "unload_delayed_memory",
            "clean_tool_results",
            "asset_action",
            "create_todo_list",
            "resolve_todo",
            "check_todo",
            "load_skill",
            "unload_skill",
            "idle",
            "jin_color",
            "update_l4_facts",
        ):
            self.assertIn(
                f"{action}: {{",
                chat_runtime_source,
            )

        self.assertIn(
            "appendRuntimeActionIconGlyph(",
            chat_runtime_source,
        )
        self.assertIn(
            "jin-runtime-action-icon-delete",
            (
                ROOT
                / "ui"
                / "static"
                / "css"
                / "chat-runtime-action.css"
            ).read_text(
                encoding="utf-8"
            ),
        )

    def test_deep_search_child_runtime_actions_stay_visible(self):
        chat_runtime_source = CHAT_RUNTIME_ACTIONS_JS.read_text(
            encoding="utf-8"
        )
        socket_runtime_source = SOCKET_RUNTIME_ACTIONS_JS.read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "function syncRuntimeActionSearchState(",
            chat_runtime_source,
        )
        self.assertIn(
            'row.dataset.runtimeActionDeepSearch =\n    "true";',
            chat_runtime_source,
        )
        self.assertIn(
            "row.dataset.runtimeActionDeepSearch === \"true\"",
            chat_runtime_source,
        )
        self.assertIn(
            '"jin-runtime-action-search-active"',
            chat_runtime_source,
        )
        self.assertIn(
            "const deepSearchChild =",
            socket_runtime_source,
        )
        self.assertIn(
            "data.deep_search_child === true",
            socket_runtime_source,
        )
        self.assertIn(
            "deepSearchChild,",
            socket_runtime_source,
        )


if __name__ == "__main__":
    unittest.main()
