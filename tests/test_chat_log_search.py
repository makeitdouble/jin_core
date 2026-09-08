import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from utils.actions import RuntimeActionCall, RuntimeActionStreamFilter, extract_runtime_actions
from utils.chat_log_search import normalize_chat_log_search, search_chat_logs, format_chat_log_search


class ChatLogSearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root_patch = patch('utils.chat_log.CHAT_LOG_ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.context = SimpleNamespace(session_id='current')

    def archive(self, rows, session='s', reasoning=None):
        folder = self.root / '2026-09-01' / session
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / 'chat.jsonl'
        path.write_text('\n'.join(json.dumps({'session_id': session, **row}, ensure_ascii=False) for row in rows), encoding='utf-8')
        for turn, text in (reasoning or {}).items():
            (folder / 'reasoning').mkdir(exist_ok=True)
            (folder / 'reasoning' / f'120000_{turn}.txt').write_text('session_id: header\n--- REASONING ---\n' + text, encoding='utf-8')
        return path

    def row(self, role, text, turn='t1', ts='2026-09-01T12:00:00+03:00', **extra):
        return {'role': role, 'text': text, 'turn_id': turn, 'ts': ts, **extra}

    def search(self, **request):
        return search_chat_logs(self.context, normalize_chat_log_search(json.dumps({'query': 'пицца', **request})))

    def test_defaults_validation_and_or(self):
        self.archive([self.row('user', 'ПИЦЦА'), self.row('user', 'доставка', 't2')])
        result = self.search(query=['пицца', 'доставка'])
        self.assertEqual(result['matched_turns'], 2)
        self.assertEqual(result['request']['max_limit'], 10)
        self.assertEqual(result['request']['source'], ['user', 'jin'])
        for value in ['', [], [''], [1], None]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_chat_log_search(json.dumps({'query': value}))
        for field, value in [('max_limit', 51), ('max_limit', True), ('max_limit', 0), ('max_limit', '10'), ('source', []), ('source', ['reasoning']), ('start_date', '2026-02-30'), ('start_time', '25:00'), ('typo', 1)]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                normalize_chat_log_search(json.dumps({'query': 'x', field: value}))
        with self.assertRaises(ValueError):
            normalize_chat_log_search('{query: pizza}')

    def test_attachment_filter_only_and_combined_with_query(self):
        self.archive([
            self.row('user', 'без текста про еду', 't1', attachments=[{'id': 'f1', 'name': 'photo.jpg'}]),
            self.row('user', 'пицца без файла', 't2'),
            self.row('user', 'пицца с файлом', 't3', attachments=[{'id': 'f2', 'name': 'pizza.jpg'}]),
            self.row('jin', 'пицца с jin-файлом', 't4', attachments=[{'id': 'f3', 'name': 'jin.txt'}]),
        ])
        filtered = search_chat_logs(self.context, normalize_chat_log_search(json.dumps({
            'has_attachments': True, 'source': 'user',
            'start_date': '2026-09-01', 'end_date': '2026-09-01',
        })))
        self.assertEqual(filtered['matched_turns'], 2)
        self.assertEqual({hit['turn_id'] for hit in filtered['results']}, {'t1', 't3'})
        self.assertTrue(all(hit['messages'][0]['attachments'] for hit in filtered['results']))

        combined = search_chat_logs(self.context, normalize_chat_log_search(json.dumps({
            'query': 'пицца', 'has_attachments': True, 'source': 'user',
        })))
        self.assertEqual(combined['matched_turns'], 1)
        self.assertEqual(combined['results'][0]['turn_id'], 't3')

    def test_attachment_filter_validation_and_does_not_read_reasoning(self):
        normalized = normalize_chat_log_search('{"has_attachments":true}')
        self.assertEqual(normalized['query'], [])
        self.assertTrue(normalized['has_attachments'])
        with self.assertRaisesRegex(ValueError, 'query or has_attachments=true'):
            normalize_chat_log_search('{}')
        with self.assertRaisesRegex(ValueError, 'has_attachments'):
            normalize_chat_log_search('{"has_attachments":"true"}')

        self.archive([
            self.row('user', 'обычное сообщение', attachments=[{'id': 'f1', 'name': 'photo.jpg'}]),
            self.row('jin', 'ответ'),
        ], reasoning={'t1': 'пицца в reasoning'})
        with patch('utils.chat_log_search._reasoning_excerpts', side_effect=AssertionError('filter-only search must not read reasoning')):
            result = search_chat_logs(self.context, normalized)
        self.assertEqual(result['matched_turns'], 1)

    def test_reasoning_needs_matching_user_same_turn_and_preserves_attachments(self):
        self.archive([
            self.row('user', 'пицца сегодня', attachments=[{'id': 'f1', 'name': 'menu.jpg'}]),
            self.row('jin', 'Хорошо'),
            self.row('user', 'другой вопрос', 't2'), self.row('jin', 'ок', 't2'),
        ], reasoning={'t1': 'a' * 500 + ' пицца с сыром ' + 'b' * 500, 't2': 'пицца'})
        result = self.search(source='jin')
        self.assertEqual(result['matched_turns'], 1)
        hit = result['results'][0]
        self.assertEqual(hit['messages'][0]['role'], 'user')
        self.assertEqual(hit['messages'][0]['attachments'][0]['id'], 'f1')
        self.assertLess(len(hit['reasoning'][0]['excerpts'][0]), 350)
        text = format_chat_log_search(result)
        self.assertIn('Attachments: menu.jpg [id: f1]', text)
        self.assertIn('Request:', text)
        self.assertNotIn('session_id: header', text)
        with patch('utils.chat_log_search._reasoning_excerpts', side_effect=AssertionError('must not read reasoning')):
            user = self.search(source='user')
        self.assertEqual(user['matched_turns'], 1)
        self.assertEqual(user['results'][0]['reasoning'], [])

    def test_jin_visible_matches_without_user_match_and_literal_only(self):
        self.archive([self.row('user', 'hello'), self.row('assistant', 'пицца'), self.row('user', 'a.b', 't2')])
        self.assertEqual(self.search(source='jin')['matched_turns'], 1)
        self.assertEqual(self.search(source='user')['matched_turns'], 0)
        self.assertEqual(self.search(query='a.b')['matched_turns'], 1)
        self.assertEqual(self.search(query='a.*b')['matched_turns'], 0)
        self.assertEqual(self.search(query='пиццу')['matched_turns'], 0)

    def test_date_time_inclusive_daily_filters_newest_and_cap(self):
        self.archive([self.row('user', 'пицца', f't{i}', f'2026-09-{i % 8 + 1:02d}T12:30:59+03:00') for i in range(60)])
        result = self.search(start_date='2026-09-03', end_date='2026-09-08', start_time='12:30', end_time='12:30', max_limit=10)
        self.assertEqual(len(result['results']), 10)
        self.assertTrue(result['has_more'])
        stamps = [r['messages'][0]['timestamp'] for r in result['results']]
        self.assertEqual(stamps, sorted(stamps, reverse=True))
        self.assertEqual(len(self.search(max_limit=50)['results']), 50)
        self.assertEqual(self.search(end_time='12:30:58')['results'], [])
        self.assertTrue(self.search(start_time='12:30:59', end_time='12:30')['results'])
        for bounds in [{'start_date':'2026-09-08','end_date':'2026-09-01'}, {'start_time':'13:00','end_time':'12:00'}]:
            with self.assertRaises(ValueError):
                self.search(**bounds)

    def test_missing_dates_malformed_and_anonymous_scope(self):
        path = self.archive([self.row('user', 'пицца'), self.row('user', 'пицца', 'missing', ts='')])
        with path.open('a', encoding='utf-8') as stream:
            stream.write('\n{broken\n')
        self.archive([self.row('user', 'пицца')], session='private-anon')
        result = self.search()
        self.assertEqual(result['matched_turns'], 1)
        self.assertEqual(result['skipped_records'], 2)
        self.context.session_id = 'private-anon'
        self.assertEqual(self.search()['matched_turns'], 2)

    def test_full_messages_survive_checkpoint_hydration_without_json_slicing(self):
        from websocket.bootstrap import clean_bootstrap_tool_results
        from utils.context.context_exports import build_tool_results_context
        text = 'пицца ' + 'длинное сообщение ' * 3000 + '<ASSET_ACTION>quoted</ASSET_ACTION>'
        self.archive([self.row('user', text, attachments=[{'id':'f1','name':'menu.jpg'}])])
        result = self.search(source='user')
        entries, _ = clean_bootstrap_tool_results(json.loads(json.dumps([
            {'kind':'runtime_action', 'tool_id':'T1', 'created_at':1234, 'result':result}
        ])))
        self.assertEqual(entries[0]['result'], result)
        self.assertEqual(entries[0]['created_at'], 1234)
        rendered = build_tool_results_context(SimpleNamespace(runtime_tool_results=entries))
        self.assertIn('&lt;ASSET_ACTION', rendered)
        self.assertIn('menu.jpg', rendered)

    def test_every_stream_boundary_repeated_literal_false_prefix_incomplete(self):
        marker = '<CHAT_LOG_SEARCH>{"query":"пицца"}</CHAT_LOG_SEARCH>'
        text = 'before ' + marker + marker + ' after'
        for split in range(len(text) + 1):
            stream = RuntimeActionStreamFilter(enabled_actions=['CHAT_LOG_SEARCH'])
            results = [stream.filter(text[:split]), stream.filter(text[split:]), stream.flush_result()]
            self.assertEqual(
                [a.payload for r in results for a in r.actions],
                ['{"query":"пицца"}', '{"query":"пицца"}'],
                split,
            )
            self.assertEqual(''.join(r.text for r in results).replace(' ', ''), 'beforeafter')
        for text in ['"' + marker, '`' + marker, '[' + marker, '<CHAT_LOG_SEARCHING>hello</CHAT_LOG_SEARCHING>']:
            stream = RuntimeActionStreamFilter(enabled_actions=['CHAT_LOG_SEARCH'])
            results = [stream.filter(c) for c in text] + [stream.flush_result()]
            self.assertFalse([a for r in results for a in r.actions])
            self.assertEqual(''.join(r.text for r in results), text)
        stream = RuntimeActionStreamFilter(enabled_actions=['CHAT_LOG_SEARCH'])
        results = [stream.filter('<CHAT_LOG_SEARCH>{"query":"x"}'), stream.flush_result()]
        self.assertFalse([a for r in results for a in r.actions])
        self.assertNotIn('CHAT_LOG_SEARCH', ''.join(r.text for r in results))
        self.assertEqual(extract_runtime_actions('<CHAT_LOG_SEARCH>{bad}</CHAT_LOG_SEARCH>').actions[0].payload, '{bad}')


class ChatLogSearchPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_visible_search_lifecycle_reuses_one_bubble_and_persists_full_summary(self):
        from runtime.runtime_context import RuntimeContext
        from utils.actions.dispatcher import apply_runtime_action_calls
        from utils.session_actions_history import replace_session_action_history_since

        events, logs = [], []

        async def emit(event):
            events.append(event)

        async def log_runtime(line):
            logs.append(line)

        c = RuntimeContext(
            websocket=None,
            emitter=SimpleNamespace(emit=emit),
            logger=SimpleNamespace(log_runtime=log_runtime),
            clients={},
        )
        c.session_id = 's'
        c.runtime_current_turn_id = 'turn1'
        request = normalize_chat_log_search('{"query":"пицца"}')
        hit = lambda index: {
            'session_id': 'old',
            'turn_id': f't{index}',
            'archive': '2026-09-01/old/chat.jsonl',
            'messages': [],
            'reasoning': [],
        }
        found = {
            'ok': True,
            'action': 'CHAT_LOG_SEARCH',
            'request': request,
            'results': [hit(1), hit(2)],
            'matched_turns': 2,
            'has_more': False,
            'skipped_records': 0,
        }
        raw_payload = '{"query":"пицца"}'
        action = RuntimeActionCall(
            name='CHAT_LOG_SEARCH',
            payload=raw_payload,
        )

        with patch(
            'utils.actions.chat_log_search_actions.search_chat_logs',
            return_value=found,
        ), patch(
            'utils.actions.chat_log_search_actions.append_chat_runtime_event',
        ):
            await apply_runtime_action_calls(
                c,
                [action],
                runtime_message_id='m1',
            )

        search_events = [
            event
            for event in events
            if event.get('action') == 'chat_log_search'
        ]
        self.assertEqual(
            [event['text'] for event in search_events],
            [
                'CHAT_LOG_SEARCH: пицца',
                'CHAT_LOG_SEARCH: пицца : 2 results',
            ],
        )
        self.assertEqual(
            search_events[0]['id'],
            search_events[1]['id'],
        )
        self.assertEqual(
            logs[-1],
            '[RUNTIME ACTION] CHAT_LOG_SEARCH: пицца : 2 results',
        )

        replace_session_action_history_since(
            c,
            0,
            [{
                'name': 'CHAT_LOG_SEARCH',
                'payload': raw_payload,
                'payloads': [raw_payload],
                'raw_payloads': [raw_payload],
            }],
        )
        self.assertTrue(
            c.runtime_session_action_history[-1]['text'].startswith(
                'CHAT_LOG_SEARCH: пицца : 2 results'
            )
        )

    async def test_identical_search_can_run_again_with_same_runtime_message_id(self):
        from runtime.runtime_context import RuntimeContext
        from utils.actions.dispatcher import apply_runtime_action_calls

        async def emit(_event):
            pass

        async def log_runtime(_line):
            pass

        c = RuntimeContext(
            websocket=None,
            emitter=SimpleNamespace(emit=emit),
            logger=SimpleNamespace(log_runtime=log_runtime),
            clients={},
        )
        c.runtime_current_turn_id = 'same-turn'
        request = normalize_chat_log_search('{"query":"пицца"}')
        found = {
            'ok': True,
            'action': 'CHAT_LOG_SEARCH',
            'request': request,
            'results': [],
            'matched_turns': 0,
            'has_more': False,
            'skipped_records': 0,
        }

        with patch(
            'utils.actions.chat_log_search_actions.search_chat_logs',
            return_value=found,
        ), patch(
            'utils.actions.chat_log_search_actions.append_chat_runtime_event',
        ):
            first = await apply_runtime_action_calls(
                c,
                [RuntimeActionCall(name='CHAT_LOG_SEARCH', payload='{"query":"пицца"}')],
                runtime_message_id='same-runtime-message',
            )
            second = await apply_runtime_action_calls(
                c,
                [RuntimeActionCall(name='CHAT_LOG_SEARCH', payload='{"query":"пицца"}')],
                runtime_message_id='same-runtime-message',
            )

        self.assertEqual(first, 1)
        self.assertEqual(second, 1)
        self.assertEqual(len(c.runtime_tool_results), 2)

    async def test_dispatch_error_followup_roundtrip_and_cleanup(self):
        from runtime.runtime_context import RuntimeContext
        from utils.actions.dispatcher import apply_runtime_action_calls
        from utils.context.context_exports import build_tool_results_context
        from utils.session_restore import _build_runtime_event_tool_results
        from utils.tool_results import clean_runtime_tool_result
        from agent.nodes.brain import action_event_requires_follow_up
        from rules.brain_context_builder import get_enabled_runtime_actions, BRAIN_RUNTIME_ACTIONS
        events, archives = [], []
        async def emit(event): events.append(event)
        async def log_runtime(line): pass
        c = RuntimeContext(websocket=None, emitter=SimpleNamespace(emit=emit), logger=SimpleNamespace(log_runtime=log_runtime), clients={})
        c.runtime_persistent_writes_restricted = True
        c.runtime_current_turn_id = 'live'
        request = normalize_chat_log_search('{"query":"пицца"}')
        found = {'ok': True, 'action': 'CHAT_LOG_SEARCH', 'request': request, 'results': [], 'matched_turns': 0, 'has_more': False, 'skipped_records': 0}
        def archive(context, *, event, payload):
            archives.append({'event': event, 'payload': json.loads(json.dumps(payload)), 'ts':'2026-09-08T12:00:00+03:00'})
        action = RuntimeActionCall(name='CHAT_LOG_SEARCH', payload='{"query":"пицца"}')
        with patch('utils.actions.chat_log_search_actions.search_chat_logs', return_value=found), patch('utils.actions.chat_log_search_actions.append_chat_runtime_event', side_effect=archive):
            count = await apply_runtime_action_calls(c, [action], runtime_message_id='m1', action_display_ids={id(action):'search1'})
        self.assertEqual(count, 1)
        self.assertEqual(len(c.runtime_tool_results), 1)
        self.assertTrue(action_event_requires_follow_up(c.runtime_action_events[-1]))
        self.assertIn('No matching messages', build_tool_results_context(c))
        restored = _build_runtime_event_tool_results(archives)
        self.assertEqual(restored[0]['result']['request'], request)
        self.assertEqual(restored[0]['tool_id'], c.runtime_tool_results[0]['tool_id'])
        c.runtime_tool_results = restored
        self.assertIn('CHAT_LOG_SEARCH', build_tool_results_context(c))
        with patch('utils.actions.chat_log_search_actions.append_chat_runtime_event', side_effect=archive):
            await apply_runtime_action_calls(c, [RuntimeActionCall(name='CHAT_LOG_SEARCH', payload='{"query":"x","max_limit":1000000}')], runtime_message_id='m2')
        self.assertTrue(c.runtime_followup_action_failure_pending)
        rendered = build_tool_results_context(c)
        self.assertIn('Correct action schema:', rendered)
        self.assertIn('1000000', rendered)
        failed = [e for e in events if e.get('action') == 'chat_log_search' and e.get('status') == 'failed'][-1]
        self.assertIn('1 to 50', failed['text'])
        self.assertIn('Correct action schema:', failed['detail'])
        self.assertTrue(clean_runtime_tool_result(c, c.runtime_tool_results[-1]['tool_id']))
        from websocket.bootstrap import apply_bootstrap_tool_results
        c.session_id = 'owner'
        apply_bootstrap_tool_results(c, {'tool_results': []})
        self.assertEqual(c.runtime_tool_results, [])
        self.assertEqual(c.session_id, 'owner')
        self.assertIn('CHAT_LOG_SEARCH', get_enabled_runtime_actions(BRAIN_RUNTIME_ACTIONS))

    async def test_archive_io_failure_is_not_empty_success(self):
        from utils.actions.chat_log_search_actions import apply_chat_log_search_actions
        c = SimpleNamespace(runtime_action_events=[])
        action = RuntimeActionCall(name='CHAT_LOG_SEARCH', payload='{"query":"x"}')
        with patch('utils.actions.chat_log_search_actions.search_chat_logs', side_effect=PermissionError('unreadable archive')), patch('utils.actions.chat_log_search_actions.append_chat_runtime_event'):
            results = await apply_chat_log_search_actions(c, [action], log_runtime=None, with_action_context=lambda x:x, action_display_ids={})
        self.assertEqual(results[0]['error'], 'archive_read_failed')
        self.assertTrue(c.runtime_followup_action_failure_pending)


if __name__ == '__main__':
    unittest.main()
