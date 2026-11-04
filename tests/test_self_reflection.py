import asyncio
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from runtime import self_reflection as reflection
from runtime.heartbeat import heartbeat_message
from rules.brain_context_builder import build_brain_context
from tests.test_bootstrap_owner_lifecycle import context
from utils import chat_log, self_reflection_store as store
from utils.self_reflection_history import normalize_session, serialize_history, compact
from utils.actions import RuntimeActionCall, RuntimeActionStreamFilter
from utils.actions.dispatcher import apply_runtime_action_calls
from utils.context.tool_results import build_tool_results_context


def reply(value):
    return {"choices": [{"message": {"content": json.dumps(value)}, "finish_reason": "stop"}]}


class ReflectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(store, "STORE_PATH", self.root / "memory" / "state.json"))
        self.stack.enter_context(patch.object(chat_log, "CHAT_LOG_ROOT", self.root / "logs"))
        self.stack.enter_context(patch.object(chat_log, "chat_logging_enabled", return_value=True))
        self.stack.enter_context(patch("utils.actions.dispatcher.ensure_assets_tree"))
        self.c = context()
        self.c.runtime_current_turn_id = "turn_000001"
        self.c.runtime_heartbeat_active = True
        self.c.runtime_self_reflection_allowed = True
        self.c.clients["service"] = SimpleNamespace(ask=AsyncMock())
        self.event = {"status": "event_found", "session_id": "old", "start_message_index": 1,
                      "end_message_index": 2, "operation": "CREATE",
                      "description": "Я проверил результат", "success": True}
        self.path = self.archive("old", [self.row("user", "Do it"), self.row("jin", "Done"),
                                         self.row("user", "Good", turn="turn_000002")])

    def row(self, role, text="", turn="turn_000001", **extra):
        return {"session_id": "old", "turn_id": turn, "ts": "2026-01-01T10:00:00Z", "role": role, "text": text, **extra}

    def archive(self, session_id, rows, day="2026-01-01"):
        path = self.root / "logs" / day / session_id / "100000.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps({**row, "session_id": session_id}) for row in rows), encoding="utf-8")
        return path

    async def dispatch(self, value=None, turn="turn_000001"):
        self.c.runtime_current_turn_id = turn
        if value is not None:
            self.c.clients["service"].ask.return_value = reply(value)
        return await apply_runtime_action_calls(self.c, [RuntimeActionCall(name="RUN_SELF_REFLECTION", payload="")],
                                              runtime_message_id="message_" + turn)

    def test_advertisement_and_live_anonymous_exclusion(self):
        self.assertTrue(reflection.available(self.c))
        ordinary = build_brain_context(self.c)
        initial = build_brain_context(self.c, initial_heartbeat=True)
        self.assertNotIn("<RUN_SELF_REFLECTION>", ordinary)
        self.assertIn("<RUN_SELF_REFLECTION>", initial)
        self.assertIn("optionally try RUN_SELF_REFLECTION", heartbeat_message(initial))
        self.assertNotIn("RUN_SELF_REFLECTION", heartbeat_message(ordinary))
        self.c.websocket.app = SimpleNamespace(state=SimpleNamespace(websocket_runtime_contexts={"old": SimpleNamespace(session_id="old")}))
        self.assertFalse(reflection.available(self.c))
        self.c.websocket.app.state.websocket_runtime_contexts.clear()
        self.c.runtime_anonymous_mode = True
        self.assertFalse(reflection.available(self.c))

    def test_history_fragments_snapshots_actions_cleaning(self):
        tool = self.row("runtime", event="runtime_tool_result", payload={"tool_id": "T1", "action_name": "ASSET_ACTION",
            "action_payload": '{"action":"create_file","content":"SECRET_FILE"}',
            "result": {"ok": False, "error": "denied", "content": "SECRET_TOOL"}})
        snapshot = self.row("runtime", event="session_actions_snapshot", payload={"items": [
            {"id": "item", "runtime_turn_id": "turn_000001", "parts": [{"text": "ASSET_ACTION", "tool_ids": ["T1"]}]}]})
        action = self.row("runtime", turn="turn_000003", event="runtime_tool_result", payload={
            "tool_id": "T2", "action_name": "WEB_SEARCH", "result": {"ok": True, "status": "completed"}})
        p = self.archive("old", [self.row("user", "<b>Do it</b>"), tool, snapshot, snapshot,
            self.row("jin", "Could not"), self.row("runtime", event="session_checkpoint", payload={"frame": "SECRET_FRAME"})])
        p2 = self.archive("old", [tool, snapshot, action], day="2026-01-02")
        history = normalize_session("old", [p, p2])
        self.assertEqual([r["role"] for r in history], ["USER", "JIN", "ACTION"])
        self.assertEqual([r["message_index"] for r in history], [1, 2, 3])
        self.assertEqual(len(history[0]["actions"]), 1)
        self.assertEqual(history[0]["actions"][0]["result"]["ok"], False)
        characteristic = {"characteristic_id": "IC-000001", "description": "I verify results",
                          "success_count": 2, "failure_count": 1}
        text = serialize_history("old", history, 0, [characteristic])
        self.assertNotIn("SECRET", text)
        self.assertNotIn("<b>", text)
        self.assertIn("denied", text)
        self.assertIn('"last_processed_index": 0', text)
        self.assertIn('"characteristic_id": "IC-000001"', text)
        remaining = json.loads(serialize_history("old", history, 2, [characteristic]))
        self.assertEqual([row["message_index"] for row in remaining["history"]], [3])
        self.assertNotIn("Do it", json.dumps(remaining))
        trimmed = compact({"data": {"ok": False, "error": "nested failure", "body": "SECRET"},
                           "results": [{"ok": True}] * 13 + [{"ok": False, "error": "late failure"}]})
        self.assertIn("nested failure", str(trimmed))
        self.assertIn("late failure", str(trimmed))
        self.assertNotIn("SECRET", str(trimmed))

    def test_snapshot_preserves_compact_action_details(self):
        items = [
            {"id": "skill", "parts": [{"text": "Load Skill", "detail": "research",
                "context_detail": "Loaded research instructions"}]},
            {"id": "legacy", "text": "Load Skill", "detail": "coding"},
            {"id": "large", "parts": [{"text": "Tool", "detail": json.dumps({
                "skill": "research", "file_content": "SECRET" * 1000}),
                "context_detail": {str(i): "long text " * 100 for i in range(20)}}]},
            {"id": "empty", "parts": [{"text": "No detail", "detail": "   ",
                "context_detail": {"body": "SECRET"}}]},
        ]
        p = self.archive("old", [self.row("runtime", event="session_actions_snapshot",
                                        payload={"items": items})])
        actions = normalize_session("old", [p])[0]["actions"]
        self.assertEqual(actions[0]["detail"], "research")
        self.assertEqual(actions[0]["context_detail"], "Loaded research instructions")
        self.assertEqual(actions[1]["detail"], "coding")
        self.assertEqual(actions[2]["detail"], {"skill": "research"})
        self.assertLessEqual(len(actions[2]["context_detail"]), 718)
        self.assertNotIn("SECRET", json.dumps(actions))
        self.assertNotIn("detail", actions[3])
        self.assertNotIn("context_detail", actions[3])

    def test_empty_dialogue_skipped_but_action_only_turn_preserved(self):
        p = self.archive("old", [self.row("jin"), self.row("user", "Question"),
            self.row("jin", " \n\t"), self.row("jin", "Answer"),
            self.row("jin", turn="action_turn"),
            self.row("runtime", turn="action_turn", event="session_actions_snapshot",
                payload={"items": [{"id": "skill", "text": "Load Skill", "detail": "research"}]}),
            self.row("jin", turn="empty_turn")])
        history = normalize_session("old", [p])
        self.assertEqual([r["role"] for r in history], ["USER", "JIN", "ACTION"])
        self.assertEqual([r["message_index"] for r in history], [1, 2, 3])
        self.assertEqual([r["text"] for r in history], ["Question", "Answer", ""])
        self.assertEqual(history[2]["actions"][0]["detail"], "research")
        empty = self.archive("blank", [self.row("jin"), self.row("jin", "   ")])
        self.assertEqual(normalize_session("blank", [empty]), [])

    async def test_event_restart_next_event_no_event_and_intuition(self):
        self.archive("old", [self.row("user", "Do it"), self.row("jin", "Done"),
                             self.row("user", "Good", turn="turn_000002"),
                             self.row("jin", "Thanks", turn="turn_000002")])
        await self.dispatch(self.event)
        saved = store.load_state()
        self.assertEqual(saved["sessions"]["old"]["cursor"], 2)
        self.assertEqual(saved["stats"]["events"], 1)
        characteristic_id = next(iter(saved["characteristics"]))
        self.assertEqual(characteristic_id, "IC-000001")
        self.assertIn("1.00 | 0.00", store.intuition_block())
        self.assertIn("IC-000001", store.intuition_block())
        # A fresh context reads the disk cursor, never a cached tool result.
        next_event = {"status": "event_found", "session_id": "old",
                      "start_message_index": 3, "end_message_index": 3,
                      "operation": "UPDATE", "characteristic_id": characteristic_id,
                      "success": True}
        await self.dispatch(next_event, turn="turn_000002")
        self.assertEqual(self.c.clients["service"].ask.await_count, 2)
        prompt = json.loads(self.c.clients["service"].ask.call_args.kwargs["user_prompt"])
        self.assertEqual(prompt["last_processed_index"], 2)
        self.assertNotIn("Do it", json.dumps(prompt))
        self.assertEqual(prompt["history"][0]["message_index"], 3)
        self.assertEqual(prompt["characteristics"][0]["characteristic_id"], characteristic_id)
        self.assertEqual(prompt["characteristics"][0]["success_count"], 1)
        await self.dispatch({"status": "no_event", "session_id": "old"}, turn="turn_000003")
        self.assertEqual(store.load_state()["stats"], {"processed_sessions": 1, "events": 2})
        self.assertEqual(store.load_state()["characteristics"][characteristic_id]["success_count"], 2)
        self.assertFalse(reflection.available(self.c))
        self.c.runtime_anonymous_mode = True
        self.assertIn("<JIN INTUITION BLOCK>", build_brain_context(self.c))
        self.assertNotIn("<RUN_SELF_REFLECTION>", build_brain_context(self.c, initial_heartbeat=True))
        self.assertFalse(self.c.runtime_failure_followup_entries)
        self.assertIn("no clear event", build_tool_results_context(self.c))

    async def test_create_update_failure_and_distinct_behavior(self):
        self.archive("old", [
            self.row("user", "Design protocol"), self.row("jin", "Protocol"),
            self.row("user", "Approved", turn="turn_000002"),
            self.row("jin", "Used it", turn="turn_000002"),
            self.row("user", "It failed", turn="turn_000003"),
            self.row("jin", "Acknowledged", turn="turn_000003"),
            self.row("user", "Different behavior", turn="turn_000004"),
            self.row("jin", "Different outcome", turn="turn_000004"),
        ])
        await self.dispatch(self.event)
        state = store.load_state()
        first_id = next(iter(state["characteristics"]))
        self.assertEqual(state["sessions"]["old"]["cursor"], 2)
        await self.dispatch({"status": "event_found", "session_id": "old",
            "start_message_index": 3, "end_message_index": 4, "operation": "UPDATE",
            "characteristic_id": first_id, "success": True}, turn="similar_success")
        self.assertEqual(store.load_state()["sessions"]["old"]["cursor"], 4)
        await self.dispatch({"status": "event_found", "session_id": "old",
            "start_message_index": 5, "end_message_index": 6, "operation": "UPDATE",
            "characteristic_id": first_id, "success": False}, turn="same_failure")
        state = store.load_state()
        self.assertEqual(state["characteristics"][first_id]["success_count"], 2)
        self.assertEqual(state["characteristics"][first_id]["failure_count"], 1)
        self.assertEqual(state["sessions"]["old"]["cursor"], 6)
        await self.dispatch({"status": "event_found", "session_id": "old",
            "start_message_index": 7, "end_message_index": 7, "operation": "CREATE",
            "description": "I distinguished behavior from topic overlap", "success": True},
            turn="different_behavior")
        state = store.load_state()
        self.assertEqual(list(state["characteristics"]), ["IC-000001", "IC-000002"])
        self.assertEqual(state["characteristics"][first_id]["success_count"], 2)
        self.assertEqual([event["operation"] for event in state["events"]],
                         ["CREATE", "UPDATE", "UPDATE", "CREATE"])

    async def test_no_event_and_empty_history_are_explicit_skips(self):
        await self.dispatch({"status": "no_event", "session_id": "old"})
        state = store.load_state()
        self.assertEqual(state["sessions"]["old"]["cursor"], 3)
        self.assertTrue(state["sessions"]["old"]["completed"])
        self.assertEqual(state["characteristics"], {})
        result = self.c.runtime_action_events[-1]["result"]
        self.assertEqual(result["operation"], "SKIP")
        self.assertIn("reviewed remainder", result["text"])

        store.STORE_PATH.unlink()
        self.path.unlink()
        self.archive("blank", [self.row("jin", "   ")])
        await self.dispatch({"status": "no_event", "session_id": "blank"}, turn="blank")
        state = store.load_state()
        self.assertEqual(state["sessions"]["blank"]["cursor"], 0)
        self.assertTrue(state["sessions"]["blank"]["completed"])
        prompt = json.loads(self.c.clients["service"].ask.call_args.kwargs["user_prompt"])
        self.assertEqual(prompt["history"], [])

    async def test_unknown_update_id_fails_without_mutation(self):
        await self.dispatch(self.event)
        before = store.load_state()
        await self.dispatch({"status": "event_found", "session_id": "old",
            "start_message_index": 3, "end_message_index": 3, "operation": "UPDATE",
            "characteristic_id": "IC-999999", "success": False}, turn="unknown")
        self.assertEqual(store.load_state(), before)
        self.assertEqual(self.c.runtime_action_events[-1]["status"], "failed")
        self.assertIn("unknown characteristic_id", self.c.runtime_action_events[-1]["result"]["error"])

    def test_legacy_state_migrates_stable_ids_and_preserves_history(self):
        legacy = {"version": 1,
            "sessions": {"old": {"cursor": 2, "completed": False,
                                     "history": [{"message_index": 1}, {"message_index": 2}]}},
            "events": [{"id": "old:1:2", "status": "event_found", "session_id": "old",
                        "start_message_index": 1, "end_message_index": 2,
                        "intuition_line": {"description": "I verify results", "success": True}}],
            "characteristics": {"i verify results": {
                "description": "I verify results", "success_count": 1, "failure_count": 0}},
            "stats": {"processed_sessions": 0, "events": 1}}
        store.STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        store.STORE_PATH.write_text(json.dumps(legacy), encoding="utf-8")
        state = store.load_state(persist_migration=True)
        repeated = store.load_state()
        self.assertEqual(state["version"], 2)
        self.assertEqual(list(state["characteristics"]), ["IC-000001"])
        self.assertEqual(list(repeated["characteristics"]), ["IC-000001"])
        self.assertEqual(state["events"][0]["characteristic_id"], "IC-000001")
        self.assertEqual(state["sessions"]["old"]["history"], legacy["sessions"]["old"]["history"])
        self.assertEqual(json.loads(store.STORE_PATH.read_text(encoding="utf-8"))["version"], 2)
        records = [{"message_index": 1}]
        update = {"status": "event_found", "session_id": "next",
                  "start_message_index": 1, "end_message_index": 1,
                  "operation": "UPDATE", "characteristic_id": "IC-000001",
                  "success": False}
        parsed = store.validate_result(json.dumps(update), "next", records, 0, state)
        store.commit_result(state, "next", records, parsed)
        persisted = json.loads(store.STORE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(persisted["version"], 2)
        self.assertEqual(persisted["characteristics"]["IC-000001"]["failure_count"], 1)

    def test_result_parser_accepts_model_wrappers_but_keeps_strict_schema(self):
        fenced = "```json\n" + json.dumps(self.event, ensure_ascii=False) + "\n```"
        self.assertEqual(
            store.validate_result(fenced, "old", normalize_session("old", [self.path]), 0, store._empty_state()),
            self.event,
        )
        wrapped = "Here is the result:\n" + json.dumps(self.event) + "\nDone."
        self.assertEqual(
            store.validate_result(wrapped, "old", normalize_session("old", [self.path]), 0, store._empty_state()),
            self.event,
        )
        with self.assertRaises(ValueError):
            store.validate_result("```json\n{\"status\":\"event_found\"}\n```", "old", [], 0, store._empty_state())

    async def test_failures_do_not_advance_or_follow_up(self):
        for index, bad in enumerate([{"status": "no_event", "session_id": "wrong"},
            {**self.event, "end_message_index": 50}, {**self.event, "start_message_index": True},
            {**self.event, "success": "false"}]):
            await self.dispatch(bad, turn=f"bad_{index}")
            self.assertFalse(store.STORE_PATH.exists())
            self.assertFalse(self.c.runtime_failure_followup_entries)
            self.assertEqual(self.c.runtime_action_events[-1]["status"], "failed")
        self.c.clients["service"].ask.side_effect = RuntimeError("offline")
        await self.dispatch(turn="offline")
        self.assertFalse(store.STORE_PATH.exists())
        self.assertIn("Correct action schema", build_tool_results_context(self.c))
        self.assertFalse(self.c.runtime_followup_action_failure_pending)

    async def test_cancelled_request_releases_claim_and_preserves_cursor(self):
        entered = asyncio.Event()
        async def wait(**_):
            entered.set()
            await asyncio.Future()
        self.c.clients["service"].ask.side_effect = wait
        task = asyncio.create_task(self.dispatch())
        await entered.wait()
        self.assertFalse(reflection.available(self.c))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(store.STORE_PATH.exists())
        self.assertFalse(store.ANALYSIS_LOCK.locked())
        self.assertEqual(self.c.runtime_action_events[-1]["result"]["error"], "cancelled")
        self.assertFalse(self.c.runtime_failure_followup_entries)

    async def test_handler_guards_and_atomic_write_failure(self):
        self.c.runtime_followup_tick_active = True
        await self.dispatch(self.event)
        self.c.clients["service"].ask.assert_not_awaited()
        self.c.runtime_followup_tick_active = False
        with patch.object(store, "atomic_write_json", side_effect=OSError("disk full")):
            await self.dispatch(self.event, turn="next")
        self.assertFalse(store.STORE_PATH.exists())
        self.assertFalse(self.c.runtime_failure_followup_entries)

    async def test_stop_flag_at_response_boundary_does_not_commit(self):
        async def stopped(**_):
            self.c.runtime_turn_abort_requested = True
            return reply(self.event)
        self.c.clients["service"].ask.side_effect = stopped
        with self.assertRaises(asyncio.CancelledError):
            await self.dispatch()
        self.assertFalse(store.STORE_PATH.exists())
        self.assertFalse(self.c.runtime_failure_followup_entries)

    async def test_restart_rejects_recount_and_keeps_frozen_indexes(self):
        await self.dispatch(self.event)
        first_id = next(iter(store.load_state()["characteristics"]))
        self.c = context()
        self.c.runtime_heartbeat_active = self.c.runtime_self_reflection_allowed = True
        self.c.clients["service"] = SimpleNamespace(ask=AsyncMock())
        self.path.write_text("changed archive", encoding="utf-8")
        await self.dispatch(self.event)
        self.assertEqual(store.load_state()["stats"]["events"], 1)
        self.assertEqual(store.load_state()["sessions"]["old"]["cursor"], 2)
        prompt = json.loads(self.c.clients["service"].ask.call_args.kwargs["user_prompt"])
        self.assertNotIn("Do it", json.dumps(prompt))
        self.assertEqual(prompt["last_processed_index"], 2)
        self.assertEqual(prompt["history"][0]["message_index"], 3)
        await self.dispatch({"status": "event_found", "session_id": "old",
            "start_message_index": 3, "end_message_index": 3, "operation": "UPDATE",
            "characteristic_id": first_id, "success": True}, turn="restart_continue")
        self.assertEqual(store.load_state()["sessions"]["old"]["cursor"], 3)
        self.assertEqual(store.load_state()["characteristics"][first_id]["success_count"], 2)

    async def test_anonymous_archives_never_become_candidates(self):
        self.path.unlink()
        self.archive("private_anon", [self.row("user", "private")])
        self.assertFalse(reflection.available(self.c))

    async def test_deleted_or_newly_live_source_during_service_is_not_committed(self):
        for mode in ("live", "deleted"):
            async def changed(**_):
                if mode == "live":
                    self.c.websocket.app = SimpleNamespace(state=SimpleNamespace(
                        websocket_runtime_contexts={"old": SimpleNamespace(session_id="old")}))
                else:
                    self.path.unlink()
                return reply(self.event)
            self.c.clients["service"].ask.side_effect = changed
            await self.dispatch(turn=mode)
            self.assertFalse(store.STORE_PATH.exists())
            if mode == "live":
                self.c.websocket.app.state.websocket_runtime_contexts.clear()

    async def test_completed_archive_changes_and_deletion_keep_experience(self):
        await self.dispatch({**self.event, "end_message_index": 3})
        self.assertFalse(reflection.available(self.c))
        self.path.write_text("corrupt", encoding="utf-8")
        self.assertFalse(reflection.available(self.c))
        self.path.unlink()
        self.assertIn("Я проверил результат", store.intuition_block())

    async def test_logs_and_terminal_ui_result(self):
        await self.dispatch(self.event)
        events = [call.args[0] for call in self.c.emitter.emit.call_args_list]
        lifecycle = [e for e in events if e.get("action") == "run_self_reflection"]
        self.assertEqual([e["status"] for e in lifecycle], ["running", "completed"])
        self.assertEqual(lifecycle[0]["id"], lifecycle[1]["id"])
        raw = [json.loads(line) for p in (self.root / "logs").glob("*/child/*.jsonl")
               for line in p.read_text(encoding="utf-8").splitlines()]
        self.assertIn("runtime_tool_result", [r.get("event") for r in raw])
        self.assertIn("runtime_action_request", [r.get("event") for r in raw])
        self.assertIn("runtime_action_result", [r.get("event") for r in raw])
        self.assertIn("Я проверил результат", build_tool_results_context(self.c))

        from utils.session_actions_history import upsert_session_action_marker_history_since, emit_session_actions_update
        from utils.session_restore import _build_runtime_event_session_actions
        upsert_session_action_marker_history_since(self.c, 0, [{"name": "RUN_SELF_REFLECTION", "count": 1}])
        await emit_session_actions_update(self.c, current_sequence=False)
        history = self.c.runtime_session_action_history
        self.assertIn("completed", history[-1]["text"])
        self.assertIn("Я проверил результат", history[-1]["parts"][0]["detail"])
        detail = history[-1]["parts"][0]["detail"]
        for expected in ("session=old", "sent=1–3", "event=1–2", "operation=CREATE",
                         "characteristic=IC-000001", "outcome=success", "cursor=0→2"):
            self.assertIn(expected, detail)
        raw = [json.loads(line) for p in (self.root / "logs").glob("*/child/*.jsonl")
               for line in p.read_text(encoding="utf-8").splitlines()]
        restored = _build_runtime_event_session_actions(raw)
        self.assertIn("Я проверил результат", restored[-1]["parts"][0]["detail"])
        self.assertEqual(restored[-1]["parts"][0]["tool_ids"], history[-1]["parts"][0]["tool_ids"])

    async def test_brain_sequence_success_and_failure_never_follow_up(self):
        from agent.nodes.brain import BrainNode
        from agent.state import AgentState
        from tests.helpers.brain import brain_runtime_config
        self.c.clients["brain"] = object()
        for index, response in enumerate([self.event, {"status": "invalid"}]):
            state = AgentState(user_input="")
            state.metadata["heartbeat_tick"] = True
            self.c.runtime_current_turn_id = f"brain_{index}"
            async def stream(**kwargs):
                self.assertFalse(kwargs.get("followup_tick"))
                self.assertIn("optionally try RUN_SELF_REFLECTION", kwargs["system_prompt"])
                await self.dispatch(response, turn=f"brain_{index}")
                return "", ""
            with patch("agent.nodes.brain.get_brain_runtime_config", return_value=brain_runtime_config()), patch(
                "agent.nodes.brain.emit_active_memory_records_update_if_dirty", new=AsyncMock()
            ), patch.object(BrainNode, "run_brain_stream", side_effect=stream) as run:
                await BrainNode().run(state, self.c)
            self.assertEqual(run.await_count, 1)

    async def test_other_action_followup_drops_contract_and_retains_intuition(self):
        from agent.nodes.brain import BrainNode
        await self.dispatch(self.event)
        initial = build_brain_context(self.c, initial_heartbeat=True)
        followup = BrainNode.build_followup_system_prompt(initial, "", context=self.c)
        self.assertIn("<RUN_SELF_REFLECTION>", initial)
        self.assertNotIn("Schema:\n<RUN_SELF_REFLECTION>", followup)
        self.assertEqual(followup.count("<JIN INTUITION BLOCK>"), 1)

    async def test_second_room_cannot_start_parallel_analysis(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def wait(**_):
            entered.set()
            await release.wait()
            return reply(self.event)
        self.c.clients["service"].ask.side_effect = wait
        task = asyncio.create_task(self.dispatch())
        await entered.wait()
        other = context()
        other.session_id = "other"
        other.runtime_heartbeat_active = other.runtime_self_reflection_allowed = True
        other.clients["service"] = SimpleNamespace(ask=AsyncMock())
        await apply_runtime_action_calls(other, [RuntimeActionCall(name="RUN_SELF_REFLECTION", payload="")], runtime_message_id="other")
        other.clients["service"].ask.assert_not_awaited()
        release.set()
        await task
        self.assertEqual(store.load_state()["stats"]["events"], 1)

    async def test_real_stream_dispatches_once_and_publishes_history(self):
        from runtime.stream import RuntimeStream
        from tests.helpers.runtime_stream import FakeWebSocket, FakeEmitter, FakeLogger
        self.c.websocket, self.c.emitter, self.c.logger = FakeWebSocket(), FakeEmitter(), FakeLogger()
        self.c.clients["service"].ask.return_value = reply(self.event)
        runtime = RuntimeStream(context=self.c, runtime_id="brain", role="brain", context_window=8192,
                                log_method=self.c.logger.log_service, runtime_actions=["RUN_SELF_REFLECTION"])
        async def chunks():
            for chunk in ["Before ", "<RUN_SELF_", "REFLECTION>", "<RUN_SELF_REFLECTION>", " after"]:
                yield {"type": "content", "content": chunk}
        text = await runtime.run(chunks())
        self.assertEqual(text.split(), ["Before", "after"])
        self.assertEqual(self.c.clients["service"].ask.await_count, 1)
        self.assertIn("completed", str(self.c.runtime_session_action_history))
        self.assertIn("Я проверил результат", str(self.c.runtime_session_action_history))
        self.assertFalse(self.c.runtime_failure_followup_entries)

    def test_stream_boundaries_and_literals(self):
        marker = "<RUN_SELF_REFLECTION>"
        for cut in range(len(marker) + 1):
            parser = RuntimeActionStreamFilter(enabled_actions=["RUN_SELF_REFLECTION"])
            results = [parser.filter("before " + marker[:cut]), parser.filter(marker[cut:] + " after"), parser.flush_result()]
            self.assertEqual([a.name for r in results for a in r.actions], ["RUN_SELF_REFLECTION"])
            self.assertEqual("".join(r.text for r in results).split(), ["before", "after"])
        for text in ["`" + marker + "`", "[" + marker + "]", "<RUN_SELF_REFLECTION_EXAMPLE>", "<RUN_SELF_REFLECT"]:
            parser = RuntimeActionStreamFilter(enabled_actions=["RUN_SELF_REFLECTION"])
            results = [parser.filter(c) for c in text] + [parser.flush_result()]
            self.assertFalse(any(a.name == "RUN_SELF_REFLECTION" for r in results for a in r.actions))


if __name__ == "__main__":
    unittest.main()
