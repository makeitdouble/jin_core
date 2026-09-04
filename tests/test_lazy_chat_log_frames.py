import asyncio
import json
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from config_loader import config
from utils import chat_log


NOW = datetime(2026, 9, 3, 11, 16, 29, tzinfo=timezone.utc)


class LazyChatLogTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(config, "LOG_CHAT", True))
        self.stack.enter_context(patch.object(chat_log, "CHAT_LOG_ROOT", self.root))
        self.stack.enter_context(patch.object(chat_log, "_now", return_value=NOW))

    def context(self, anonymous=False):
        return SimpleNamespace(
            session_id="test-anon" if anonymous else "test",
            runtime_anonymous_mode=anonymous,
            runtime_turn_counter=1,
            runtime_current_turn_id="turn_000001",
            runtime_memory_display_index_offset=1,
        )

    def stage_bootstrap(self, context):
        self.assertIsNone(chat_log.save_chat_bootstrap_context_snapshot(
            context, system_prompt="inherited context",
        ))
        self.assertIsNone(chat_log.save_frame_snapshot(context, {
            "index": 0, "raw_memory": "topic: inherited", "created_at": "original time",
        }))
        return chat_log.get_chat_log_path(context)

    def test_blank_bootstrap_and_empty_reasoning_create_nothing_in_both_modes(self):
        for anonymous in (False, True):
            context = self.context(anonymous)
            path = self.stage_bootstrap(context)
            chat_log.save_chat_context_snapshot(context, system_prompt="prepared prompt")
            self.assertIsNone(chat_log.save_turn_reasoning(context, " \n "))
            self.assertFalse(path.parent.exists())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_first_real_record_flushes_bootstrap_in_both_modes(self):
        for anonymous in (False, True):
            for kind in ("user", "jin", "reasoning", "action"):
                with self.subTest(anonymous=anonymous, kind=kind):
                    context = self.context(anonymous)
                    context.session_id = f"{kind}-{context.session_id}"
                    path = self.stage_bootstrap(context)
                    if kind == "reasoning":
                        chat_log.save_turn_reasoning(context, "partial reasoning")
                        self.assertFalse(path.exists())  # No fabricated completed JIN row.
                    elif kind == "action":
                        chat_log.append_chat_runtime_event(context, event="runtime_action_request",
                                                          payload={"action": "JIN_COLOR", "color": "#123456"})
                    else:
                        chat_log.append_chat_log_entry(context, role=kind, text="real message")
                    self.assertTrue((path.parent / "reasoning").is_dir())
                    self.assertEqual(path.with_name("111629.bootstrap.txt").read_text().strip(),
                                     "inherited context")
                    self.assertIn("topic: inherited", (path.parent / "frames" / "111629_frame_1.txt").read_text())
                    self.assertEqual(context.runtime_chat_pending_snapshots, {})

    def test_all_frames_keep_history_refresh_in_place_and_resume_with_offset(self):
        context = self.context()
        path = self.stage_bootstrap(context)
        chat_log.append_chat_log_entry(context, role="user", text="hello")
        frames = path.parent / "frames"
        baseline = (frames / "111629_frame_1.txt").read_text()
        snapshot = {"index": 1, "raw_memory": "topic: second", "runtime_memory_id": "abc",
                    "created_at": "unchanged timestamp"}
        second = chat_log.save_frame_snapshot(context, snapshot)
        self.assertEqual(second.name, "111629_frame_2.txt")
        # A soft reconnect keeps visible FRAME numbering despite resetting the local index.
        resumed = self.context()
        resumed.runtime_memory_display_index_offset = 2
        chat_log.resume_chat_log_session(resumed)
        refreshed = chat_log.save_frame_snapshot(resumed, {**snapshot, "index": 0, "raw_memory": "topic: edited"})
        self.assertEqual(refreshed, second)
        self.assertIn("topic: edited", second.read_text())
        self.assertIn("unchanged timestamp", second.read_text())
        # Deleting the final row must not leave stale frame contents on disk.
        chat_log.save_frame_snapshot(resumed, {**snapshot, "index": 0, "raw_memory": ""})
        self.assertNotIn("topic:", second.read_text())
        self.assertEqual((frames / "111629_frame_1.txt").read_text(), baseline)
        self.assertEqual(len(list(frames.glob("*.txt"))), 2)

    def test_jsonl_has_no_dialog_path_for_messages_events_or_retry(self):
        context = self.context()
        path = self.stage_bootstrap(context)
        chat_log.save_chat_context_snapshot(context, system_prompt="current prompt")
        chat_log.append_chat_log_entry(context, role="user", text="question")
        chat_log.save_turn_reasoning(context, "reasoning")
        chat_log.append_chat_log_entry(context, role="jin", text="answer")
        # Legacy row compatibility: replacement removes the obsolete field too.
        entries = [json.loads(row) for row in path.read_text().splitlines()]
        entries[-1]["dialog_path"] = "legacy self-reference"
        path.write_text("\n".join(json.dumps(row) for row in entries) + "\n")
        chat_log.append_chat_runtime_event(context, event="runtime_action_request", payload={"action": "JIN_COLOR"})
        chat_log.replace_latest_chat_log_entry(context, role="jin", text="retried answer")
        entries = [json.loads(row) for row in path.read_text().splitlines()]
        self.assertEqual([e["role"] for e in entries], ["user", "jin", "runtime"])
        self.assertTrue(all("dialog_path" not in entry for entry in entries))
        self.assertIn("context_path", entries[1])
        self.assertIn("reasoning_path", entries[1])
        self.assertEqual(entries[1]["text"], "retried answer")
        from utils.session_restore import build_archived_session_restore_payload

        restored = build_archived_session_restore_payload(context.session_id, root=self.root)
        self.assertEqual(restored["recent_turns"][-1]["user"], "question")
        self.assertEqual(restored["recent_turns"][-1]["jin"], "retried answer")
        self.assertEqual(restored["recent_turns"][-1]["reasoning"], "reasoning")

    def test_pending_snapshot_survives_write_failure(self):
        context = self.context()
        path = self.stage_bootstrap(context)
        with patch.object(chat_log, "_write_context_snapshot", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                chat_log.append_chat_log_entry(context, role="user", text="keep user")
        self.assertEqual(json.loads(path.read_text())["text"], "keep user")
        self.assertTrue(context.runtime_chat_pending_snapshots)
        chat_log.save_turn_reasoning(context, "reasoning")
        self.assertEqual(context.runtime_chat_pending_snapshots, {})
        self.assertTrue(path.with_name("111629.bootstrap.txt").exists())

    def test_disabled_logging_does_not_stage_or_write(self):
        context = self.context()
        with patch.object(config, "LOG_CHAT", False):
            chat_log.save_chat_bootstrap_context_snapshot(context, system_prompt="bootstrap")
            chat_log.save_frame_snapshot(context, {"index": 0, "raw_memory": "frame"})
            chat_log.save_turn_reasoning(context, "reasoning")
            chat_log.append_chat_log_entry(context, role="user", text="hello")
        self.assertFalse(hasattr(context, "runtime_chat_pending_snapshots"))
        self.assertEqual(list(self.root.iterdir()), [])


class CancelledBootstrapLogTests(unittest.IsolatedAsyncioTestCase):
    async def test_frame_emission_and_refresh_write_archive_without_blocking_on_disk_error(self):
        from runtime.L1_memory_utils import emit_runtime_memory_update, emit_runtime_memory_snapshot_refresh
        from runtime.runtime_context import RuntimeContext

        with ExitStack() as stack:
            root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
            stack.enter_context(patch.object(config, "LOG_CHAT", True))
            stack.enter_context(patch.object(chat_log, "CHAT_LOG_ROOT", root))
            stack.enter_context(patch.object(chat_log, "_now", return_value=NOW))
            context = RuntimeContext(websocket=SimpleNamespace(send_json=AsyncMock()),
                                     emitter=SimpleNamespace(emit=AsyncMock()),
                                     logger=SimpleNamespace(log_error=AsyncMock()), clients={})
            context.session_id = "frames-session"
            context.runtime_memory_display_index_offset = 1
            context.runtime_memory = "topic: first"
            chat_log.append_chat_log_entry(context, role="user", text="hello")
            first = await emit_runtime_memory_update(context)
            context.runtime_memory = "topic: second"
            second = await emit_runtime_memory_update(context)
            second["raw_memory"] = "topic: edited"
            await emit_runtime_memory_snapshot_refresh(context, second)
            directory = Path(context.runtime_chat_log_path).parent / "frames"
            self.assertEqual(first["index"], 0)
            self.assertIn("topic: first", (directory / "111629_frame_1.txt").read_text())
            self.assertIn("topic: edited", (directory / "111629_frame_2.txt").read_text())
            context.emitter.emit.reset_mock()
            with patch.object(chat_log, "save_frame_snapshot", side_effect=OSError("disk full")):
                await emit_runtime_memory_snapshot_refresh(context, second)
            context.emitter.emit.assert_awaited_once()
            self.assertEqual(context.emitter.emit.call_args.args[0]["snapshot"], second)

    async def test_cancellation_preserves_real_stream_reasoning_without_fake_dialogue(self):
        from agent.nodes.brain import BrainNode
        from runtime.runtime_context import RuntimeContext
        from websocket.messages import process_message
        from websocket.bootstrap import emit_current_runtime_memory

        for anonymous in (False, True):
            for reasoning in ("", "already visible reasoning"):
                with self.subTest(anonymous=anonymous, reasoning=reasoning), ExitStack() as stack:
                    root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
                    stack.enter_context(patch.object(config, "LOG_CHAT", True))
                    stack.enter_context(patch.object(chat_log, "CHAT_LOG_ROOT", root))
                    stack.enter_context(patch.object(chat_log, "_now", return_value=NOW))
                    logger = SimpleNamespace(log_system=AsyncMock(), log_runtime=AsyncMock(), log_brain=AsyncMock())
                    context = RuntimeContext(websocket=SimpleNamespace(send_json=AsyncMock()),
                                             emitter=SimpleNamespace(emit=AsyncMock()), logger=logger, clients={})
                    context.session_id = "cancel-anon" if anonymous else "cancel"
                    context.runtime_anonymous_mode = anonymous
                    context.runtime_session_restore_priming = True
                    context.runtime_turn_reasoning_content = "stale previous turn"
                    context.runtime_memory = "topic: inherited"
                    context.runtime_memory_display_index_offset = 1
                    await emit_current_runtime_memory(context)
                    fake_stream = SimpleNamespace(stream=SimpleNamespace(reasoning=reasoning),
                                                  run=AsyncMock(side_effect=asyncio.CancelledError))
                    stack.enter_context(patch("agent.nodes.brain.RuntimeStream", return_value=fake_stream))
                    stack.enter_context(patch("agent.nodes.brain.ask_brain_stream", return_value=object()))
                    stack.enter_context(patch("agent.nodes.brain.prepare_current_context_window_prompt",
                                             new=AsyncMock(return_value=SimpleNamespace(system_prompt="bootstrap context", context_window=8192))))

                    async def run(state, context):
                        await BrainNode.run_brain_stream(
                            state=state, context=context, brain_runtime={"runtime_id": "brain", "label": "brain", "context_window": 8192,
                                                                        "log_method": "log_brain"},
                            brain_client=object(), system_prompt="bootstrap context", brain_payload="",
                            runtime_actions={},
                        )

                    stack.enter_context(patch("websocket.messages.AgentRuntime", return_value=SimpleNamespace(run=run)))
                    with self.assertRaises(asyncio.CancelledError):
                        await process_message(context, {"type": "archived_session_resume"})
                    self.assertEqual(context.runtime_turn_reasoning_content, reasoning)
                    self.assertEqual(list(root.rglob("*.jsonl")), [])
                    logs = list(root.rglob("*_turn_*.txt"))
                    if reasoning:
                        self.assertEqual(len(logs), 1)
                        self.assertIn(reasoning, logs[0].read_text())
                        self.assertEqual(len(list(root.rglob("*.bootstrap.txt"))), 1)
                        self.assertEqual(len(list(root.rglob("*_frame_1.txt"))), 1)
                    else:
                        self.assertEqual(list(root.iterdir()), [])
