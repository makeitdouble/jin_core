import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from utils.actions.jin_reaction_actions import emit_jin_reactions
from utils.chat_log import append_chat_log_entry, append_chat_runtime_event
from utils.session_restore import _build_recent_turns, build_archived_session_restore_payload
from websocket.bootstrap import apply_archived_session_continuation_state, build_session_bootstrap_chat_tail
from websocket.messages import append_runtime_recent_turn


class ReactionPersistenceTests(unittest.TestCase):
    def test_jsonl_reload_hydrate_including_interrupted_and_action_only(self):
        for anonymous in (False, True):
            for answer in (None, '', 'reply'):
                with self.subTest(anonymous=anonymous, answer=answer), tempfile.TemporaryDirectory() as tmp:
                    context = SimpleNamespace(
                        session_id='test-anon' if anonymous else 'test',
                        runtime_turn_counter=1, runtime_current_turn_id='turn_000001',
                        runtime_recent_turns=[], emitter=None,
                    )
                    with patch('utils.chat_log.chat_logging_enabled', return_value=True):
                        path = append_chat_log_entry(context, role='user', text='hello', root=tmp)
                        def persist(*args, **kwargs):
                            return append_chat_runtime_event(*args, **kwargs, root=tmp)
                        with patch('utils.chat_log.append_chat_runtime_event', side_effect=persist):
                            asyncio.run(emit_jin_reactions(
                                context, [SimpleNamespace(payload='🔥')],
                                action_display_ids={}, log_runtime=None,
                                with_action_context=lambda event: event,
                            ))
                        if answer is not None:
                            append_chat_log_entry(context, role='jin', text=answer, root=tmp)
                    entries = [json.loads(line) for line in Path(path).read_text().splitlines()]
                    if not anonymous:
                        payload = build_archived_session_restore_payload('test', root=tmp)
                        self.assertEqual(payload['messages'][0]['jin_reaction'], '🔥')
                    turns = _build_recent_turns(entries)
                    self.assertEqual(turns[0]['jin_reaction'], '🔥')
                    restored = SimpleNamespace()
                    apply_archived_session_continuation_state(restored, {'recent_turns': json.loads(json.dumps(turns))})
                    self.assertEqual(build_session_bootstrap_chat_tail(restored)[0]['jin_reaction'], '🔥')
                    append_runtime_recent_turn(context, user_message='hello', assistant_message=answer or '')
                    self.assertEqual(context.runtime_recent_turns[-1]['jin_reaction'], '🔥')

    def test_legacy_text_does_not_invent_reaction_and_empty_retry_clears(self):
        entries = [
            {'turn': 1, 'role': 'user', 'text': '<JIN_REACTION: 🔥 >'},
            {'turn': 1, 'role': 'jin', 'text': 'Лови 🔥'},
        ]
        self.assertNotIn('jin_reaction', _build_recent_turns(entries)[0])
        entries.insert(1, {'turn': 1, 'role': 'runtime', 'event': 'jin_reaction', 'payload': {'emoji': '🔥'}})
        entries[-1]['jin_reaction'] = ''
        self.assertNotIn('jin_reaction', _build_recent_turns(entries)[0])
        for value in ('', None, 'not emoji'):
            context = SimpleNamespace()
            apply_archived_session_continuation_state(context, {'recent_turns': [{'user': 'hello', 'jin_reaction': value}]})
            self.assertNotIn('jin_reaction', build_session_bootstrap_chat_tail(context)[0])
