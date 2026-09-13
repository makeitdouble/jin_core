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



    @unittest.skipUnless(
        shutil.which("node"),
        "node is required for the deep-search click interaction test",
    )
    def test_deep_search_stack_click_interaction_routes_only_expected_clicks(self):
        script = r'''
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const start = source.indexOf("function deepSearchStackHasSelectedText()");
const end = source.indexOf("function scheduleDeepSearchStackGeometrySync(", start);

if (start < 0 || end < 0) {
  throw new Error("deep-search click helpers were not found");
}

let selectedText = "";
const deepSearchStackExpandedGroups = new Set();
const rowsByGroup = new Map();
const stateChanges = [];

global.window = {
  getSelection() {
    return {
      isCollapsed: !selectedText,
      toString() {
        return selectedText;
      },
    };
  },
};

function makeRow(kind, name) {
  const listeners = {};
  const label = {
    name: `${name}-label`,
    addEventListener(type, callback) {
      listeners[type] = callback;
    },
  };

  const row = {
    name,
    dataset: {},
    classList: {
      contains(value) {
        return value === `jin-runtime-action-deep-search-${kind}`;
      },
    },
    querySelector() {
      return label;
    },
    contains(target) {
      return target === row || target === label;
    },
    listeners,
    label,
  };

  return row;
}

const parent = makeRow("parent", "parent");
const first = makeRow("child", "first");
const second = makeRow("child", "second");
[parent, first, second].forEach((row) => {
  row.dataset.runtimeActionDeepSearchGroup = "group-1";
});
rowsByGroup.set("group-1", [parent, first, second]);

function readDeepSearchGroupId(row) {
  return row.dataset.runtimeActionDeepSearchGroup || "";
}

function findDeepSearchGroupRows(groupId) {
  return rowsByGroup.get(groupId) || [];
}

function setDeepSearchStackExpanded(row, expanded) {
  const groupId = readDeepSearchGroupId(row);
  stateChanges.push([row.name, expanded]);
  if (expanded) {
    deepSearchStackExpandedGroups.add(groupId);
  } else {
    deepSearchStackExpandedGroups.delete(groupId);
  }
}

eval(source.slice(start, end));

bindDeepSearchStackClick(first);
bindDeepSearchStackClick(second);

second.listeners.click();
if (stateChanges.length !== 0) {
  throw new Error("non-first child opened the stack");
}

selectedText = "copy me";
first.listeners.click();
if (stateChanges.length !== 0) {
  throw new Error("text selection triggered stack opening");
}

selectedText = "";
first.listeners.click();
if (stateChanges.length !== 1 || stateChanges[0][1] !== true) {
  throw new Error("first child click did not open the stack");
}

first.listeners.click();
if (stateChanges.length !== 1) {
  throw new Error("clicking a bubble while expanded changed stack state");
}

handleDeepSearchStackDocumentClick({ target: second.label });
if (stateChanges.length !== 1) {
  throw new Error("clicking inside a child bubble collapsed the stack");
}

handleDeepSearchStackDocumentClick({ target: { name: "outside" } });
if (stateChanges.length !== 2 || stateChanges[1][1] !== false) {
  throw new Error("outside click did not collapse the stack");
}
'''
        completed = subprocess.run(
            [
                shutil.which("node"),
                "-e",
                script,
                str(CHAT_RUNTIME_ACTIONS_JS),
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
        "node is required for the browser-side search scene test",
    )
    def test_deep_search_scene_overlay_stays_until_parent_completes(self):
        script = r'''
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const end = source.indexOf("\nfunction formatRuntimeActionContextTitle(");

if (end < 0) {
  throw new Error("search scene helpers were not found");
}

eval(source.slice(0, end));

const classes = new Set();
global.document = {
  querySelector(selector) {
    if (selector !== "main") {
      return null;
    }

    return {
      classList: {
        add(value) {
          classes.add(value);
        },
        remove(value) {
          classes.delete(value);
        },
      },
    };
  },
};

syncSceneSearchScreenForRuntimeAction(
  "deep_web_search",
  true,
  {
    id: "deep_web_search_001",
    runtimeMessageId: "message_1",
    sceneEffect: "search",
  }
);

if (!classes.has("scene-searching")) {
  throw new Error("deep search parent did not activate the search scene");
}

syncSceneSearchScreenForRuntimeAction(
  "web_search",
  true,
  {
    id: "web_search_001",
    deepSearchParentId: "deep_web_search_001",
    sceneEffect: "search",
  }
);
syncSceneSearchScreenForRuntimeAction(
  "web_search",
  false,
  {
    id: "web_search_001",
    deepSearchParentId: "deep_web_search_001",
    sceneEffect: "search",
  }
);

if (!classes.has("scene-searching")) {
  throw new Error("child web search completion hid the deep search scene");
}

syncSceneSearchScreenForRuntimeAction(
  "deep_web_search",
  false,
  {
    id: "deep_web_search_001",
    sceneEffect: "search",
  }
);

if (classes.has("scene-searching")) {
  throw new Error("deep search parent completion did not hide the search scene");
}
'''
        completed = subprocess.run(
            [
                shutil.which("node"),
                "-e",
                script,
                str(CHAT_RUNTIME_ACTIONS_JS),
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
        "node is required for the update-active-memory UI test",
    )
    def test_update_active_memory_success_bubble_and_payload_hover(self):
        script = r'''
const fs = require("fs");
global.window = {};
global.registerSocketMessageHandler = () => {};
global.getRuntimeActionMessageId = () => "";
global.appendRuntimeAction = (action, text, options) => {
  global.captured = {action, text, options};
  return true;
};

const source = fs.readFileSync(process.argv[1], "utf8");
eval(source);

handleRuntimeAction({
  action: "update_active_memory",
  status: "completed",
  text: "UPDATE_ACTIVE_MEMORY: old conditions",
  display_name: "UPDATE_ACTIVE_MEMORY",
  id: "su5vfx",
  active_memory_id: "su5vfx",
  active_memory_key: "active_memory_1",
  active_memory_title: "old conditions",
  active_memory_result: {
    ok: true,
    id: "su5vfx",
    key: "active_memory_1",
    title: "new conditions",
    payload: JSON.stringify({
      active_memory_id: "su5vfx",
      fields_to_update: {
        type: "updated_test",
        conditions: "new conditions",
      },
    }),
  },
  active_memory_requested_changes: [
    {field: "type", after: "updated_test"},
    {field: "conditions", after: "new conditions"},
  ],
  close_tag: true,
});

if (!global.captured) {
  throw new Error("UPDATE_ACTIVE_MEMORY was not rendered");
}
if (global.captured.text !== "UPDATE_ACTIVE_MEMORY: active_memory_1") {
  throw new Error(`unexpected text: ${global.captured.text}`);
}
const expectedDetail = [
  "active_memory_id: su5vfx",
  "fields_to_update:",
  "\ttype: updated_test",
  "\tconditions: new conditions",
].join("\n");
if (global.captured.options.detail !== expectedDetail) {
  throw new Error(
    `unexpected detail: ${JSON.stringify(global.captured.options.detail)}`
  );
}
'''
        completed = subprocess.run(
            [
                shutil.which("node"),
                "-e",
                script,
                str(SOCKET_RUNTIME_ACTIONS_JS),
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
