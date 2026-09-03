import asyncio
import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent.nodes.brain import BrainNode
from agent.state import AgentState
from clients.brain_client import apply_runtime_action_calls
from rules.brain_context_builder import BRAIN_RUNTIME_ACTIONS, build_brain_context
from runtime.runtime_context import RuntimeContext
from tests.helpers.runtime_actions import FakeEmitter
from utils import attached_files_store as files
from utils.actions import RuntimeActionCall, RuntimeActionStreamFilter, extract_runtime_actions
from utils.brain_client_utils import load_delayed_memory_report
from utils.context.tool_results import build_tool_results_context
from utils.project_reader import link_project_folder, project_review_active, run_project_action
from utils.session_actions_history import build_asset_action_context_detail
from utils.tool_results import begin_runtime_tool_results_turn, record_runtime_tool_result
from websocket.attachments import format_attachment_context


class ProjectReviewTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.project = self.root / "project with spaces"
        self.project.mkdir()
        (self.project / "src").mkdir()
        (self.project / "README.md").write_text("Project overview\n", encoding="utf-8")
        (self.project / "src" / "main.py").write_text("first\nneedle = 42\nthird\nfourth\n", encoding="utf-8")
        for key, value in {"FILES_DIR": self.root / "files", "INDEX_FILE": self.root / "files/.index.json", "GITKEEP_FILE": self.root / "files/.gitkeep"}.items():
            self.stack.enter_context(patch.object(files, key, value))
        self.record, _, _ = link_project_folder(str(self.project))
        self.context = RuntimeContext(websocket=object(), emitter=FakeEmitter(), logger=object(), clients={})
        self.context.runtime_attached_file_ids = [self.record["id"]]
        self.context.runtime_current_turn_id = "turn-project"
        self.context.runtime_memory = "task: inspect source"
        self.context.runtime_recent_turns = [{"user": "our prior question", "jin": "our prior answer"}]
        self.context.runtime_previous_reasoning_content = "previous thought"
        self.context.runtime_turn_reasoning_content = "first inspection thought"
        self.context.delayed_memory_file_store_enabled = False

    def action(self, action, **kwargs):
        return run_project_action(self.context, {"action": action, "attachment": self.record["id"], **kwargs})

    def prompt(self):
        return build_brain_context(self.context, runtime_actions=BRAIN_RUNTIME_ACTIONS)

    def memories(self, pinned=False):
        self.context.delayed_memory_reports = {
            "abc123": {"id": "abc123", "title": "selected report", "body": "SELECTED_REPORT_BODY", "summary": "selected summary", "pinned": pinned, "facts_ids": ["F1"], "anchor_fact_ids": []},
            "def456": {"id": "def456", "title": "UNRELATED_REPORT_TITLE", "body": "UNRELATED_REPORT_BODY", "summary": "unrelated summary", "facts_ids": ["F2"], "anchor_fact_ids": []},
        }
        self.context.runtime_loaded_delayed_memory = dict(self.context.delayed_memory_reports)
        self.context.runtime_loaded_delayed_memory_ids = ["abc123", "def456"]
        self.context.runtime_long_term_memory_store = {"facts": [
            {"id": "F1", "key": "selected", "value": "SELECTED_FACT_VALUE"},
            {"id": "F2", "key": "unrelated", "value": "UNRELATED_FACT_VALUE"},
            {"id": "F3", "key": "ordinary", "value": "ORDINARY_FACT_VALUE"},
        ]}

    def test_link_url_dedupe_restore_and_delete_only_descriptor(self):
        same, created, _ = link_project_folder(self.project.as_uri())
        self.assertFalse(created)
        self.assertEqual(same["id"], self.record["id"])
        record = files.get_file_record(same["id"])
        data = (files.FILES_DIR / record["stored_name"]).read_bytes()
        self.assertTrue(files.delete_file_record(record["id"]))
        self.assertTrue((self.project / "src/main.py").exists())
        restored, error = files.restore_file_record(record["id"], record=record, content=data)
        self.assertIsNone(error)
        self.assertEqual(restored["id"], record["id"])
        self.assertTrue(self.action("project_tree")["ok"])
        attachment_context = format_attachment_context({"attachments": files.hydrate_attachment_ids([record["id"]])})
        self.assertIn("Linked project", attachment_context)
        self.assertNotIn(str(self.project), attachment_context)

    def test_folder_names_survive_legacy_index_reload_without_descriptor_suffix(self):
        record = files.get_file_record(self.record["id"])
        self.assertEqual(record["display_name"], self.project.name)
        self.assertTrue(record["stored_name"].endswith(".jin-folder"))
        # Old indexes did not carry display_name; derive it from the stored name.
        index = json.loads(files.INDEX_FILE.read_text(encoding="utf-8"))
        for item in index:
            item.pop("display_name", None)
        files.INDEX_FILE.write_text(json.dumps(index), encoding="utf-8")
        restored = files.public_file_snapshot()["files"][0]
        self.assertEqual(restored["display_name"], self.project.name)
        for quote in ('"', "'"):
            same, created, _ = link_project_folder(quote + str(self.project) + quote)
            self.assertFalse(created)
            self.assertEqual(same["id"], record["id"])
        from utils.project_context import build_project_review_context
        from websocket.attachments import build_attached_files_inventory_context
        outputs = [build_project_review_context(self.context),
                   build_attached_files_inventory_context(self.context),
                   format_attachment_context({"attachments": files.hydrate_attachment_ids([record["id"]])}),
                   "\n".join(files.format_list_files_lines())]
        for output in outputs:
            self.assertIn(self.project.name, output)
            self.assertNotIn(".jin-folder", output)

    def test_success_results_are_compact_but_failure_and_unload_remain_explicit(self):
        from utils.context.files import format_file_result
        from utils.project_reader import format_project_result
        for action, kwargs in [("project_tree", {}), ("project_search", {"query": "needle"}),
                               ("project_read", {"path": "src/main.py"})]:
            result = self.action(action, **kwargs)
            self.assertTrue(result["ok"])
            self.assertEqual(result["project_name"], self.project.name)
            for legacy in (False, True):
                if legacy:
                    result.pop("project_name", None)
                output = format_project_result(result)
                self.assertNotIn("Status:", output)
                self.assertIn(self.project.name, output)
                self.assertNotIn(".jin-folder", output)
            self.assertNotIn("success", build_asset_action_context_detail(result))
        result = self.action("project_read", path="missing.txt")
        self.assertIn("Status: failed", format_project_result(result))
        self.assertIn("Correct action schema:", format_project_result(result))
        result = self.action("project_read", path="src/main.py")
        result["loaded"] = False
        self.assertIn("Status: unloaded", format_project_result(result))
        normal = {"action": "attach_file", "ok": True, "id": "abc123", "name": "notes.txt"}
        self.assertNotIn("Status:", format_file_result(normal))
        normal["action"] = "detach_file"
        self.assertIn("Status: unloaded", format_file_result(normal))
        record_runtime_tool_result(self.context, "files", {"ok": True, "action": "list_files",
                                                          "lines": files.format_list_files_lines()})
        output = build_tool_results_context(self.context)
        self.assertIn("Files:", output)
        self.assertNotIn("Status: success", output)

    def test_bad_links_and_unattached_targets_are_rejected(self):
        for target in ("", "https://example.com/repo", str(self.project / "README.md"), str(self.root / "missing")):
            with self.subTest(target=target), self.assertRaises((OSError, ValueError)):
                link_project_folder(target)
        self.context.runtime_attached_file_ids = []
        self.assertFalse(self.action("project_tree")["ok"])

    def test_tree_search_and_exact_line_ranges(self):
        tree = self.action("project_tree", limit=1)
        self.assertEqual(tree["content"], "README.md")
        self.assertIn("offset 1", tree["notice"])
        second = self.action("project_tree", offset=1, limit=2)
        self.assertEqual(second["content"], "src/\nsrc/main.py")
        search = self.action("project_search", query="NEEDLE")
        self.assertEqual(search["content"], "src/main.py:2: needle = 42")
        read = self.action("project_read", path="src\\main.py", start=2, end=3)
        self.assertEqual(read["content"], "2: needle = 42\n3: third")
        self.assertEqual(read["range"], "2-3 of 4 lines")
        self.assertIn("Next unread line: 4", read["notice"])
        self.assertIn("2-3 of 4 lines", build_asset_action_context_detail(read))

    def test_scope_escape_binary_large_and_invalid_ranges(self):
        (self.root / "outside.txt").write_text("outside secret")
        try:
            (self.project / "escape").symlink_to(self.root, target_is_directory=True)
        except OSError:
            pass
        for relative in ("../outside.txt", str(self.root / "outside.txt"), "C:\\secret.txt", "escape/outside.txt"):
            with self.subTest(path=relative):
                self.assertFalse(self.action("project_read", path=relative)["ok"])
        (self.project / "binary").write_bytes(b"a\x00b")
        (self.project / "large").write_bytes(b"x" * (1024 * 1024 + 1))
        for relative in ("binary", "large"):
            self.assertFalse(self.action("project_read", path=relative)["ok"])
        self.assertFalse(self.action("project_read", path="README.md", start=3, end=1)["ok"])
        self.assertFalse(self.action("project_tree", depth=0)["ok"])
        self.assertFalse(self.action("project_search", query="")["ok"])

    def test_scan_limits_and_generated_folders_are_explicit(self):
        (self.project / "node_modules").mkdir()
        (self.project / "node_modules/hidden.txt").write_text("needle hidden")
        result = self.action("project_search", query="needle")
        self.assertNotIn("needle hidden", result["content"])
        self.assertIn("Skipped", result["notice"])
        with patch("utils.project_reader.MAX_SCAN_ENTRIES", 1):
            self.assertIn("coverage is incomplete", self.action("project_tree")["notice"])
        (self.project / "long.txt").write_text("x" * 24001)
        result = self.action("project_read", path="long.txt")
        self.assertFalse(result["ok"])
        self.assertNotIn("content", result)
        self.assertIn("no content loaded", result["detail"])

    def test_clean_review_keeps_dialogue_frame_thought_and_no_memory(self):
        self.memories()
        prompt = self.prompt()
        for value in ("SELECTED_REPORT_BODY", "UNRELATED_REPORT_BODY", "UNRELATED_REPORT_TITLE", "SELECTED_FACT_VALUE", "UNRELATED_FACT_VALUE", "ORDINARY_FACT_VALUE"):
            self.assertNotIn(value, prompt)
        for value in ("our prior question", "our prior answer", "task: inspect source", "previous thought", "first inspection thought"):
            self.assertIn(value, prompt)
        self.assertIn("SAVE_DELAYED_MEMORY", prompt)
        self.assertIn("UPDATE_LT_FACTS", prompt)

    def test_pinned_report_and_only_its_facts_on_every_followup(self):
        self.memories(pinned=True)
        for step in range(3):
            self.context.runtime_turn_reasoning_content += f"\nthought {step} " + "x" * 2200
            base = build_brain_context(self.context, runtime_actions=BRAIN_RUNTIME_ACTIONS, include_previous_chat_messages=False, include_previous_reasoning=False, include_turn_reasoning=True)
            prompt = BrainNode.build_followup_system_prompt(base, "inspect project", context=self.context)
            self.assertIn("SELECTED_REPORT_BODY", prompt)
            self.assertIn("SELECTED_FACT_VALUE", prompt)
            self.assertNotIn("UNRELATED_REPORT_BODY", prompt)
            self.assertNotIn("UNRELATED_FACT_VALUE", prompt)
            self.assertNotIn("ORDINARY_FACT_VALUE", prompt)
            self.assertIn("our prior question", prompt)
            self.assertIn("first inspection thought", prompt)
            self.assertNotIn("CUTTED", prompt)
            self.assertEqual(prompt.count("SELECTED_REPORT_BODY"), 1)
        self.assertTrue(self.context.delayed_memory_reports["abc123"]["pinned"])
        self.assertEqual(len(self.context.runtime_long_term_memory_store["facts"]), 3)

    def test_unpin_and_detach_restore_normal_projection(self):
        self.memories(pinned=True)
        self.assertIn("SELECTED_REPORT_BODY", self.prompt())
        self.context.delayed_memory_reports["abc123"]["pinned"] = False
        self.assertNotIn("SELECTED_REPORT_BODY", self.prompt())
        self.context.runtime_attached_file_ids = []
        self.assertFalse(project_review_active(self.context))
        self.assertIn("ORDINARY_FACT_VALUE", self.prompt())
        self.assertIn("UNRELATED_REPORT_TITLE", self.prompt())

    def test_old_tool_memories_do_not_leak_and_write_acknowledgement_survives(self):
        self.memories()
        record_runtime_tool_result(self.context, "delayed_memory", {"ok": True, "action": "load_delayed_memory", "id": "def456", "body": "OLD_REPORT_TOOL_SECRET"})
        record_runtime_tool_result(self.context, "lt", {"ok": True, "value": "OLD_FACT_TOOL_SECRET"})
        begin_runtime_tool_results_turn(self.context)
        prompt = build_tool_results_context(self.context)
        self.assertNotIn("OLD_REPORT_TOOL_SECRET", prompt)
        self.assertNotIn("OLD_FACT_TOOL_SECRET", prompt)
        record_runtime_tool_result(self.context, "lt", {"ok": True, "value": "NEW_FACT_ACK"})
        record_runtime_tool_result(self.context, "delayed_memory", {"ok": True, "action": "save_delayed_memory", "id": "new123", "body": "NEW_REPORT_ACK"})
        prompt = build_tool_results_context(self.context)
        self.assertIn("NEW_FACT_ACK", prompt)
        self.assertIn("NEW_REPORT_ACK", prompt)
        denied = load_delayed_memory_report(self.context, "def456")
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["error"], "project_memory_not_pinned")

    def test_marker_splits_quotes_incomplete_and_repeated(self):
        marker = '<ASSET_ACTION>{"action":"project_tree"}</ASSET_ACTION>'
        for split in range(len(marker) + 1):
            parser = RuntimeActionStreamFilter(enabled_actions=["CAN_USE_ASSETS"])
            chunks = [parser.filter(marker[:split]), parser.filter(marker[split:]), parser.flush_result()]
            self.assertEqual(sum(len(chunk.actions) for chunk in chunks), 1)
            self.assertEqual("".join(chunk.text for chunk in chunks), "")
        for text, expected in [(marker + marker, 1), (marker + marker.replace("project_tree", "project_search"), 2), ('"' + marker + '"', 0), ("<ASSET_ACTIONISH>x", 0)]:
            self.assertEqual(len(extract_runtime_actions(text, enabled_actions=["CAN_USE_ASSETS"]).actions), expected)
        parser = RuntimeActionStreamFilter(enabled_actions=["CAN_USE_ASSETS"])
        parser.filter('<ASSET_ACTION>{"action":"project_tree"}')
        tail = parser.flush_result()
        self.assertEqual(len(tail.actions), 0)
        self.assertEqual(len(tail.failed_actions), 1)

    def test_dispatch_bubbles_results_failure_and_session_history(self):
        async def run():
            for action, args in [("project_tree", {}), ("project_search", {"query": "needle"}), ("project_read", {"path": "src/main.py", "start": 2, "end": 3}), ("project_read", {"path": "../outside"})]:
                payload = json.dumps({"action": action, "attachment": self.record["id"], **args})
                await apply_runtime_action_calls(self.context, (RuntimeActionCall(name="ASSET_ACTION", payload=payload),))
        asyncio.run(run())
        events = [event for event in self.context.emitter.events if event.get("action") == "asset_action"]
        completed = [event for event in events if event.get("status") in {"completed", "failed"}]
        self.assertEqual([event["status"] for event in completed], ["completed"] * 3 + ["failed"])
        self.assertIn("2: needle = 42", completed[2]["detail"])
        self.assertEqual(len(self.context.runtime_tool_results), 4)
        prompt = build_tool_results_context(self.context)
        self.assertIn("README.md", prompt)
        self.assertNotIn("<FILE_CONTENT:", prompt)
        self.assertIn("2: needle = 42", self.prompt())
        self.assertNotIn('"content":', prompt)
        self.assertTrue(self.context.runtime_session_action_history)

    def test_review_can_save_report_and_active_through_normal_actions(self):
        from clients.brain_client import get_response_enabled_runtime_actions
        from runtime.behavior_contract import should_pause_action_guard_for_confirmation

        self.context.runtime_turn_user_message = "inspect project"
        self.assertIn("SAVE_DELAYED_MEMORY", get_response_enabled_runtime_actions(
            BRAIN_RUNTIME_ACTIONS, "inspect project", context=self.context,
        ))
        self.assertFalse(should_pause_action_guard_for_confirmation(
            "save_delayed_memory", "inspect project", context=self.context,
        ))
        self.assertTrue(should_pause_action_guard_for_confirmation("save_delayed_memory", "inspect project"))
        payload = json.dumps({"title": "Project findings", "summary": "The requested source was inspected.",
            "body": "src/main.py lines 2-3: needle is assigned 42. The rest of the project remains unread.",
            "tags": ["project"], "facts_ids": [], "anchor_fact_ids": [], "attachments_ids": [self.record["id"]]})
        asyncio.run(apply_runtime_action_calls(self.context, (
            extract_runtime_actions("<SAVE_DELAYED_MEMORY>" + payload + "</SAVE_DELAYED_MEMORY>", enabled_actions=["CAN_SAVE_DELAYED_MEMORY"]).actions[0],
            RuntimeActionCall(name="SAVE_ACTIVE_MEMORY", payload='{"conditions":"Inspect the remaining project files when the user returns."}'),
        )))
        self.assertTrue(self.context.delayed_memory_reports)
        report = next(iter(self.context.delayed_memory_reports.values()))
        self.assertIn(self.record["id"], report["attachments_ids"])
        self.assertTrue(self.context.active_memory_records)
        events = self.context.emitter.events
        self.assertFalse(any(event.get("type") == "runtime_action_confirmation" for event in events))
        self.assertTrue(any(event.get("action") == "save_delayed_memory" and event.get("status") == "completed" for event in events))
        self.context.runtime_attached_file_ids = []
        self.assertNotIn("SAVE_DELAYED_MEMORY", get_response_enabled_runtime_actions(
            BRAIN_RUNTIME_ACTIONS, "inspect project", context=self.context,
        ))

    def test_brain_runs_tree_search_read_followups_with_continuity(self):
        self.memories(pinned=True)
        calls = []
        async def stream(**kwargs):
            calls.append(kwargs)
            index = len(calls) - 1
            prompt = kwargs["system_prompt"]
            self.assertIn("SELECTED_REPORT_BODY", prompt)
            self.assertIn("SELECTED_FACT_VALUE", prompt)
            self.assertNotIn("ORDINARY_FACT_VALUE", prompt)
            self.assertIn("our prior question", prompt)
            if index:
                self.assertIn("thought-step-0", prompt)
                self.assertIn("CURRENT_REQUEST_FLOW", prompt)
            if index == 3:
                self.assertIn("thought-step-2", prompt)
                self.assertIn("2: needle = 42", prompt)
                self.assertIn("README.md", prompt)
                return "Reviewed the requested lines.", "done"
            action, args = [("project_tree", {}), ("project_search", {"query": "needle"}), ("project_read", {"path": "src/main.py", "start": 2, "end": 3})][index]
            payload = json.dumps({"action": action, "attachment": self.record["id"], **args})
            await apply_runtime_action_calls(self.context, (RuntimeActionCall(name="ASSET_ACTION", payload=payload),))
            # The real stream appends each provider reasoning block to this slot.
            self.context.runtime_turn_reasoning_content += f"\nthought-step-{index}"
            return "", f"thought-step-{index}"
        state = AgentState(user_input="inspect project")
        runtime = {"runtime_id": "brain-test", "label": "brain", "context_window": 32768, "log_method": "log_brain", "runtime_actions": BRAIN_RUNTIME_ACTIONS}
        self.context.clients = {"brain": object()}
        with patch("agent.nodes.brain.get_brain_runtime_config", return_value=runtime), patch.object(BrainNode, "run_brain_stream", staticmethod(stream)):
            asyncio.run(BrainNode().run(state, self.context))
        self.assertEqual(len(calls), 4)
        self.assertEqual(state.brain_response, "Reviewed the requested lines.")


if __name__ == "__main__":
    unittest.main()
