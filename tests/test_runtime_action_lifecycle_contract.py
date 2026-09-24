from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAT_RUNTIME_ACTIONS_JS = ROOT / "ui" / "static" / "js" / "chat-runtime-actions.js"
SOCKET_RUNTIME_ACTIONS_JS = ROOT / "ui" / "static" / "js" / "socket" / "runtime-actions.js"


class RuntimeActionLifecycleContractTests(unittest.TestCase):
    def test_append_reconciles_started_row_before_creating_duplicate(self):
        source = CHAT_RUNTIME_ACTIONS_JS.read_text(encoding="utf-8")
        append_start = source.index("function appendRuntimeAction(")
        append_end = source.index("function queueRuntimeActionAfterNextResponse(")
        append_source = source[append_start:append_end]

        reconcile_at = append_source.index("findRuntimeActionLifecycleRow(")
        create_at = append_source.index('document.createElement("div")')
        self.assertLess(reconcile_at, create_at)
        self.assertIn("markRuntimeActionLifecyclePhase(", append_source)
        self.assertIn("isRuntimeActionLifecycleTerminalStatus(", append_source)

    def test_terminal_without_label_still_retires_started_row(self):
        source = SOCKET_RUNTIME_ACTIONS_JS.read_text(encoding="utf-8")
        blank_branch = source.index("if (!displayText.trim()) {")
        appended = source.index("const appended = appendRuntimeAction(", blank_branch)
        branch_source = source[blank_branch:appended]
        self.assertIn("window.fadeRuntimeAction(", branch_source)
        self.assertIn("terminalFailure", branch_source)
        self.assertIn("status,", branch_source)

    @unittest.skipUnless(shutil.which("node"), "node is required")
    def test_lifecycle_pairing_is_fifo_and_terminal_can_recover_bound_row(self):
        source = CHAT_RUNTIME_ACTIONS_JS.read_text(encoding="utf-8")
        names = [
            "normalizeRuntimeActionKeyPart",
            "normalizeRuntimeActionLifecycleStatus",
            "isRuntimeActionLifecycleStartStatus",
            "isRuntimeActionLifecycleProgressStatus",
            "isRuntimeActionLifecycleTerminalStatus",
            "runtimeActionRowMatchesLifecycleScope",
            "findRuntimeActionLifecycleRow",
        ]

        chunks = []
        for index, name in enumerate(names):
            start = source.index(f"function {name}(")
            if index + 1 < len(names):
                end = source.index(f"function {names[index + 1]}(", start)
            else:
                end = source.index("const normalizeRuntimeActionColor =", start)
            chunks.append(source[start:end])

        script = "\n".join(chunks) + r'''
const rows = [
  {
    dataset: {
      runtimeAction: "posting_board",
      runtimeActionTurn: "1",
      runtimeActionRuntimeMessage: "message-1",
      runtimeActionLifecycleStarted: "true",
      runtimeActionLifecycleBound: "false",
    },
  },
  {
    dataset: {
      runtimeAction: "posting_board",
      runtimeActionTurn: "1",
      runtimeActionRuntimeMessage: "message-1",
      runtimeActionLifecycleStarted: "true",
      runtimeActionLifecycleBound: "false",
    },
  },
];
global.jinConversationTurnCounter = 1;
global.chatHistory = {querySelectorAll: () => rows};
const first = findRuntimeActionLifecycleRow(
  "posting_board",
  {runtimeMessageId: "message-1", status: "running"}
);
if (first !== rows[0]) throw new Error("running event did not bind FIFO started row");
rows[0].dataset.runtimeActionLifecycleBound = "true";
const second = findRuntimeActionLifecycleRow(
  "posting_board",
  {runtimeMessageId: "message-1", status: "running"}
);
if (second !== rows[1]) throw new Error("second running event reused an already bound row");
rows[1].dataset.runtimeActionLifecycleBound = "true";
const terminal = findRuntimeActionLifecycleRow(
  "posting_board",
  {runtimeMessageId: "message-1", status: "failed"},
  {allowBound: true}
);
if (terminal !== rows[0]) throw new Error("terminal recovery could not retire a bound started row");
'''
        completed = subprocess.run(
            [shutil.which("node"), "-e", script],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)


if __name__ == "__main__":
    unittest.main()
