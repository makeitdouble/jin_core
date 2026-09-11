"""Owner-locked D049 scenarios, using actual logging/restore/queue paths."""
import asyncio
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import websocket as ws
from runtime.runtime_context import RuntimeContext
from utils import chat_log, session_restore
from websocket.bootstrap import (
    apply_archived_session_continuation_state,
    build_session_bootstrap_chat_tail,
)
from websocket.messages import process_message


def context():
    logger = SimpleNamespace(**{name: AsyncMock() for name in (
        'log', 'log_system', 'log_runtime', 'log_user', 'log_error',
    )})
    socket = SimpleNamespace(send_json=AsyncMock(), query_params={})
    return RuntimeContext(websocket=socket, emitter=SimpleNamespace(emit=AsyncMock()),
                          logger=logger, clients={}, session_id='child')


class BootstrapOwnerLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_four_owner_scenarios_round_trip(self):
        for scenario in (1, 2, 3, 4):
            with self.subTest(scenario=scenario), ExitStack() as stack:
                root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
                stack.enter_context(patch.object(chat_log, 'chat_logging_enabled', return_value=True))
                stack.enter_context(patch.object(chat_log, 'CHAT_LOG_ROOT', root))
                stack.enter_context(patch.object(session_restore, 'CHAT_LOG_ROOT', root))
                c = context()
                c.runtime_session_restore_priming = scenario in (1, 2)

                async def model(state, runtime):
                    if scenario == 3:
                        raise asyncio.CancelledError()
                    state.brain_response = 'greeting' if runtime.runtime_session_restore_priming else 'reply'
                    runtime.runtime_turn_reasoning_content = 'saved reasoning'

                stack.enter_context(patch('websocket.messages.AgentRuntime', return_value=SimpleNamespace(run=model)))
                stack.enter_context(patch('websocket.messages.load_delayed_memory_by_tags', new=AsyncMock()))
                stack.enter_context(patch('websocket.messages.schedule_runtime_memory_update'))
                stack.enter_context(patch('websocket.messages.schedule_pending_update_lt_facts_actions'))
                stack.enter_context(patch('websocket.messages.emit_session_actions_update', new=AsyncMock()))
                stack.enter_context(patch('websocket.messages.handle_fatal_runtime_error', new=AsyncMock(side_effect=AssertionError('unexpected runtime error'))))
                if scenario in (1, 2):
                    await process_message(c, {'type': 'archived_session_resume'})
                if scenario != 1:
                    if scenario == 3:
                        with self.assertRaises(asyncio.CancelledError):
                            await process_message(c, {'text': 'real request'})
                    elif scenario == 2:
                        # The user closed/stopped before an answer: retain the input.
                        with patch('websocket.messages.AgentRuntime', return_value=SimpleNamespace(run=AsyncMock(side_effect=asyncio.CancelledError))):
                            with self.assertRaises(asyncio.CancelledError):
                                await process_message(c, {'text': 'real request'})
                    else:
                        await process_message(c, {'text': 'real request'})
                selected = session_restore.find_latest_completed_session_restore_payload(root=root)
                if scenario == 1:
                    self.assertIsNone(selected, 'greeting-only must not own continuation')
                    self.assertEqual(list(root.iterdir()), [], 'greeting must not create an archive')
                    continue
                self.assertEqual(selected['source_session_id'], 'child')
                restored = SimpleNamespace()
                payload = json.loads(json.dumps(selected))
                apply_archived_session_continuation_state(restored, payload)
                tail = build_session_bootstrap_chat_tail(restored)
                self.assertEqual(len(tail), 1)
                self.assertEqual(tail[0]['user'], 'real request')
                self.assertEqual(tail[0]['jin'], 'reply' if scenario == 4 else '')
                if scenario == 4:
                    self.assertEqual(tail[0]['reasoning'], 'saved reasoning')
                else:
                    self.assertNotIn('jin_created_at', tail[0])

    async def test_cancelled_startup_packet_never_becomes_real_user(self):
        c = context()
        c.runtime_session_restore_priming = False
        with patch('websocket.messages.AgentRuntime') as model, patch('websocket.messages.append_chat_log_entry') as log:
            await process_message(c, {'type': 'archived_session_resume'})
        model.assert_not_called()
        log.assert_not_called()
        self.assertEqual(c.current_session_user_message_count, 0)

    async def test_stopped_pending_user_commits_without_model(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(chat_log, 'CHAT_LOG_ROOT', Path(tmp)), patch.object(chat_log, 'chat_logging_enabled', return_value=True):
            c = context()
            with patch('websocket.messages.AgentRuntime') as model, patch('websocket.messages.load_delayed_memory_by_tags', new=AsyncMock()):
                with self.assertRaises(asyncio.CancelledError):
                    await process_message(c, {'text': 'stopped while waiting', '_interrupt_before_brain': True})
            model.assert_not_called()
            end = c.websocket.send_json.call_args.args[0]
            self.assertEqual(end['type'], 'agent_runtime_end')
            self.assertFalse(end['completed_turn_commit'])
            self.assertEqual(end['session_snapshot']['recent_turns'][-1]['user'], 'stopped while waiting')
            archive = session_restore.find_latest_completed_session_restore_payload(root=tmp)
            self.assertEqual(archive['recent_turns'], [{'user': 'stopped while waiting', 'jin': '',
                'user_created_at': archive['recent_turns'][0]['user_created_at']}])

    async def test_stop_or_user_during_startup_frame_wait_drops_tick(self):
        for command, phase in (('abort', 'waiting'), ('message', 'waiting'), ('abort', 'running'), ('message', 'running')):
            with self.subTest(command=command, phase=phase), ExitStack() as stack:
                c = context()
                c.runtime_session_restore_priming = True
                received = asyncio.Queue()
                waiting = asyncio.Event()
                release = asyncio.Event()
                ran_user = asyncio.Event()
                calls = []

                async def wait_frame(_):
                    if phase == 'waiting':
                        waiting.set()
                        await release.wait()

                async def process(_, data):
                    if data.get('type') == 'archived_session_resume' and phase == 'running':
                        waiting.set()
                        await release.wait()
                    calls.append(data.get('type', 'message'))
                    ran_user.set()

                for name in ('initialize_connection', 'refresh_pending_brain_usage',
                             'apply_runtime_response_feedback', 'cancel_lt_memory_idle_update',
                             'preempt_update_lt_facts_actions'):
                    stack.enter_context(patch.object(ws, name, new=AsyncMock()))
                stack.enter_context(patch('websocket.tasks.schedule_interrupted_runtime_memory_update'))
                stack.enter_context(patch.object(ws, 'ensure_initial_runtime_snapshot'))
                stack.enter_context(patch.object(ws, 'note_lt_foreground_state'))
                stack.enter_context(patch.object(ws, 'note_lt_user_activity'))
                stack.enter_context(patch.object(ws, 'reject_when_all_models_offline', new=AsyncMock(return_value=False)))
                stack.enter_context(patch.object(ws, 'receive_message', new=lambda _: received.get()))
                stack.enter_context(patch.object(ws, 'wait_for_runtime_memory_update', new=wait_frame))
                stack.enter_context(patch.object(ws, 'process_message', new=process))
                task = asyncio.create_task(ws.run_runtime_session(c.websocket, c, False))
                try:
                    await received.put({'type': 'archived_session_resume'})
                    await asyncio.wait_for(waiting.wait(), 1)
                    await received.put({'type': command, 'text': 'real request'} if command == 'message' else {'type': 'abort'})
                    # Wait for the actual receive handler to invalidate priming.
                    for _ in range(100):
                        if not c.runtime_session_restore_priming:
                            break
                        await asyncio.sleep(0)
                    self.assertFalse(c.runtime_session_restore_priming)
                    release.set()
                    if command == 'message':
                        await asyncio.wait_for(ran_user.wait(), 1)
                    await asyncio.wait_for(c.runtime_pending_requests_queue.join(), 1)
                    self.assertEqual(calls, ['message'] if command == 'message' else [])
                finally:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
