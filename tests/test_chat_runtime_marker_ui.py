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
RUNTIME_STREAM_PY = ROOT / "runtime" / "stream.py"
COMMON_ACTION_UTILS_PY = (
    ROOT / "utils" / "actions" / "common_action_utils.py"
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
            '/static/js/chat.js?v=jin-size-1',
            source,
        )

        self.assertIn(
            '/static/js/chat-runtime-actions.js?v=active-hotpath-1',
            source,
        )

        self.assertIn(
            '/static/js/socket/runtime-actions.js?v=active-hotpath-1',
            source,
        )
        self.assertIn(
            '/static/css/chat-runtime-action.css?v=deep-search-stack-2',
            source,
        )

    def test_save_active_memory_does_not_add_second_token_hot_path_parser(self):
        runtime_stream_source = RUNTIME_STREAM_PY.read_text(
            encoding="utf-8"
        )
        common_action_source = COMMON_ACTION_UTILS_PY.read_text(
            encoding="utf-8"
        )
        chat_runtime_source = CHAT_RUNTIME_ACTIONS_JS.read_text(
            encoding="utf-8"
        )
        socket_runtime_source = SOCKET_RUNTIME_ACTIONS_JS.read_text(
            encoding="utf-8"
        )

        self.assertNotIn(
            "emit_live_active_memory_progress",
            runtime_stream_source,
        )
        self.assertNotIn(
            "get_pending_close_tag_payload",
            common_action_source,
        )
        self.assertNotIn(
            "liveActiveMemoryProgress",
            socket_runtime_source,
        )
        self.assertNotIn(
            "options.flushStreamFrame !== false",
            chat_runtime_source,
        )

    def test_runtime_action_icons_cover_core_actions(self):
        chat_runtime_source = CHAT_RUNTIME_ACTIONS_JS.read_text(
            encoding="utf-8"
        )

        for action in (
            "web_search",
            "deep_web_search",
            "save_delayed_memory_content",
            "append_delayed_memory",
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

    def test_deep_search_runtime_actions_use_stacked_child_bubbles(self):
        chat_runtime_source = CHAT_RUNTIME_ACTIONS_JS.read_text(
            encoding="utf-8"
        )
        socket_runtime_source = SOCKET_RUNTIME_ACTIONS_JS.read_text(
            encoding="utf-8"
        )
        runtime_action_css = (
            ROOT
            / "ui"
            / "static"
            / "css"
            / "chat-runtime-action.css"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "function syncRuntimeActionSearchState(",
            chat_runtime_source,
        )
        self.assertIn(
            "function isDeepSearchChildRuntimeAction(",
            chat_runtime_source,
        )
        self.assertIn(
            "jin-runtime-action-deep-search-parent",
            chat_runtime_source,
        )
        self.assertIn(
            "jin-runtime-action-deep-search-child",
            chat_runtime_source,
        )
        self.assertIn(
            "icon.remove();",
            chat_runtime_source,
        )
        self.assertNotIn(
            "jin-runtime-action-search-active",
            chat_runtime_source,
        )
        self.assertNotIn(
            "jin-runtime-action-search-active",
            runtime_action_css,
        )
        self.assertIn(
            "jin-runtime-action-deep-search-stack-expanded",
            runtime_action_css,
        )
        self.assertIn(
            "margin-top: -1.35rem",
            runtime_action_css,
        )
        self.assertIn(
            "function insertRuntimeActionRow(",
            chat_runtime_source,
        )
        self.assertIn(
            'parentRow.insertAdjacentElement(',
            chat_runtime_source,
        )
        self.assertIn(
            '"afterend",',
            chat_runtime_source,
        )
        self.assertIn(
            "margin-top 240ms cubic-bezier(0, 0, 0.2, 1)",
            runtime_action_css,
        )
        self.assertIn(
            "transition-timing-function: cubic-bezier(0.4, 0, 1, 1)",
            runtime_action_css,
        )
        self.assertIn(
            "const deepSearchChild =",
            socket_runtime_source,
        )
        self.assertIn(
            "const deepSearchParentId =",
            socket_runtime_source,
        )
        self.assertIn(
            "data.deep_search_child === true",
            socket_runtime_source,
        )
        self.assertIn(
            "data.deep_search_parent_id",
            socket_runtime_source,
        )
        self.assertIn(
            "deepSearchChild,",
            socket_runtime_source,
        )
        self.assertIn(
            "deepSearchParentId,",
            socket_runtime_source,
        )


if __name__ == "__main__":
    unittest.main()
