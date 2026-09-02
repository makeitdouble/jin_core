import json
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase

from contracts.rules_assembler import get_close_tag_runtime_actions, get_runtime_action_schema
from utils.actions import RuntimeActionStreamFilter


PAYLOADS = {
    'ASSET_ACTION': '{"action":"list_files"}',
    'DEEP_WEB_SEARCH': 'research this topic',
    'JIN_COLOR': '#112233',
    'JIN_POSITION': 'x:100px y:200px',
    'JIN_SIZE': 'w:120 h:120',
    'JIN_SPEED': '600px/s',
    'SAVE_ACTIVE_MEMORY': '{"conditions":"remember to test"}',
    'SAVE_DELAYED_MEMORY': '{"title":"test","summary":"summary","body":"body"}',
    'UPDATE_ACTIVE_MEMORY': '{"active_memory_id":"abc123","conditions":"test"}',
    'UPDATE_LT_FACTS': 'remember this fact',
}


def parse_chunks(chunks):
    parser = RuntimeActionStreamFilter()
    results = [parser.filter(chunk) for chunk in chunks]
    results.append(parser.flush_result())
    return parser, results


class UnclosedParserTests(TestCase):
    def test_covers_every_paired_contract(self):
        self.assertEqual(set(PAYLOADS), set(get_close_tag_runtime_actions()))

    def test_every_chunk_boundary_hides_and_fails_unclosed_blocks(self):
        for name, payload in PAYLOADS.items():
            for body in ('', payload, payload + f'</{name[:-2]}'):
                text = f'before\n<{name}>{body}'
                variants = [[text], list(text)] + [[text[:i], text[i:]] for i in range(1, len(text))]
                for chunks in variants:
                    with self.subTest(name=name, chunks=chunks):
                        parser, results = parse_chunks(chunks)
                        self.assertEqual(''.join(r.text for r in results).strip(), 'before')
                        self.assertFalse([a for r in results for a in r.actions])
                        failures = [a for r in results for a in r.failed_actions]
                        self.assertEqual([a.name for a in failures], [name])
                        self.assertEqual(failures[0].payload, body)
                        self.assertFalse(parser.flush_result().failed_actions)

    def test_repeated_opening_is_not_a_close_tag(self):
        for name, payload in PAYLOADS.items():
            for chunks in ([f'<{name}>{payload}<{name}>'], list(f'<{name}>{payload}<{name}>')):
                _, results = parse_chunks(chunks)
                self.assertFalse([a for r in results for a in r.actions], name)
                self.assertEqual([a.name for r in results for a in r.failed_actions], [name])
                self.assertEqual(''.join(r.text for r in results), '')

    def test_closed_blocks_and_literal_openings_keep_their_semantics(self):
        for name, payload in PAYLOADS.items():
            text = f'before <{name}>{payload}</{name}> after'
            _, results = parse_chunks(list(text))
            self.assertEqual([a.name for r in results for a in r.actions], [name])
            self.assertFalse([a for r in results for a in r.failed_actions])
            self.assertEqual(''.join(r.text for r in results), 'before  after')
            for opening in ('"', "'", '`', '(', '[', '{', '«'):
                text = f'{opening}<{name}>{payload}'
                _, results = parse_chunks(list(text))
                self.assertEqual(''.join(r.text for r in results), text)
                self.assertFalse([a for r in results for a in r.failed_actions])

    def test_private_tail_cannot_execute_nested_markers(self):
        for name in set(PAYLOADS) - {'ASSET_ACTION'}:
            text = f'before <{name}>private <CLEAN_TOOL_RESULTS><ASSET_ACTION>{{"action":"list_files"}}</ASSET_ACTION>'
            _, results = parse_chunks(list(text))
            self.assertEqual(''.join(r.text for r in results), 'before ')
            self.assertFalse([a for r in results for a in r.actions])
            self.assertEqual([a.name for r in results for a in r.failed_actions], [name])
            self.assertTrue(all(a.name == name for r in results for a in r.started_actions))

    def test_complete_then_incomplete_and_partial_false_prefix(self):
        _, results = parse_chunks(list('<UPDATE_LT_FACTS>first</UPDATE_LT_FACTS><UPDATE_LT_FACTS>second'))
        self.assertEqual(len([a for r in results for a in r.actions]), 1)
        self.assertEqual(len([a for r in results for a in r.failed_actions]), 1)
        for text in ('normal <ASSET_ACTOR> text', 'normal (<UPDATE_LT_', 'text < 5'):
            _, results = parse_chunks(list(text))
            self.assertEqual(''.join(r.text for r in results), text)
            self.assertFalse([a for r in results for a in r.failed_actions])
        _, results = parse_chunks(list('<CLEAN_TOOL_RESULTS>'))
        self.assertEqual(len([a for r in results for a in r.actions]), 1)
        self.assertFalse([a for r in results for a in r.failed_actions])


class UnclosedRuntimeTests(IsolatedAsyncioTestCase):
    async def test_eof_fails_every_contract_before_message_end_and_survives_bootstrap(self):
        from agent.nodes.brain import (
            action_event_requires_follow_up, consume_action_failure_followup_context,
            _build_failed_runtime_action_marker,
        )
        from runtime.stream import RuntimeStream
        from runtime.L1_memory_utils import build_runtime_session_checkpoint
        from websocket.bootstrap import clean_bootstrap_tool_results
        from utils.context.tool_results import build_tool_results_context
        from tests.test_runtime_stream_tokens import FakeEmitter, FakeLogger, FakeWebSocket

        for name, payload in PAYLOADS.items():
            with self.subTest(name=name):
                context = SimpleNamespace(
                    websocket=FakeWebSocket(), emitter=FakeEmitter(), logger=FakeLogger(),
                    runtime_action_events=[], runtime_session_action_history=[],
                    runtime_current_turn_id='turn-test', runtime_current_sequence_turn_id='turn-test',
                    runtime_session_id='session-test', runtime_turn_user_message='test',
                )
                stream = RuntimeStream(
                    context=context, runtime_id='brain', role='brain', context_window=8192,
                    log_method=context.logger.log_service, enable_validator=False,
                    runtime_actions=list(PAYLOADS),
                )
                # Guards are a separate completed-action policy; don't open a real
                # confirmation timer in this protocol-lifecycle test.
                async def no_guard(actions):
                    return None
                stream.confirm_started_runtime_action_guards = no_guard
                async def chunks():
                    for chunk in f'before\n<{name}>{payload}':
                        yield {'type': 'content', 'content': chunk}
                response = await stream.run(chunks())
                self.assertIsNotNone(response, context.logger.messages)
                self.assertEqual(response.strip(), 'before')
                failures = [e for e in context.emitter.events if e.get('status') == 'failed']
                self.assertEqual(len(failures), 1)
                failure = failures[0]
                self.assertEqual(failure['action'], name.lower())
                self.assertEqual(failure['text'], f'{name}: failed: no close tag provided in output')
                starts = [e for e in context.emitter.events if e.get('status') == 'started']
                if starts and starts[-1].get('id'):
                    self.assertEqual(failure['id'], starts[-1]['id'])
                self.assertFalse(context.runtime_active_action_markers)
                self.assertTrue(action_event_requires_follow_up(context.runtime_action_events[-1]))
                self.assertNotIn(f'</{name}>', _build_failed_runtime_action_marker(context.runtime_action_events[-1]))
                self.assertTrue(consume_action_failure_followup_context(context))
                self.assertIn('failed: no close tag', stream.build_action_log(0))
                self.assertIn('failed: no close tag', str(context.logger.messages))
                self.assertIn('failed: no close tag', str(context.runtime_session_action_history))
                prompt = build_tool_results_context(context)
                self.assertIn(f'name="{name}"', prompt)
                self.assertIn('Status: failed', prompt)
                self.assertIn('Reason: no close tag provided in output', prompt)
                if get_runtime_action_schema(name):
                    self.assertIn('Correct action schema:', prompt)
                checkpoint = build_runtime_session_checkpoint(context)
                restored, _ = clean_bootstrap_tool_results(json.loads(json.dumps(checkpoint['tool_results'])))
                self.assertEqual(restored[0]['result'], context.runtime_tool_results[0]['result'])
                context.runtime_tool_results = restored
                self.assertIn('no close tag provided in output', build_tool_results_context(context))
                self.assertFalse(getattr(context, 'runtime_pending_delayed_memory_action_ids', []))
                self.assertFalse(getattr(context, 'runtime_pending_asset_action_ids', []))
