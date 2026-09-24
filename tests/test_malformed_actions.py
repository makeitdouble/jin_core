import json
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase

from utils.actions import RuntimeActionStreamFilter, extract_runtime_actions


FORMS = (
    '<tool_call>call:ATTACH_FILE_BY_ID{id:"z4tsdy"}<tool_call|>',
    '<ATTACH_FILE_BY_ID id="z4tsdy"></ATTACH_FILE_BY_ID>',
)
PAYLOADS = ('{id:"z4tsdy"}', 'id="z4tsdy"')


def parse(chunks):
    parser = RuntimeActionStreamFilter()
    results = [parser.filter(chunk) for chunk in chunks]
    results.append(parser.flush_result())
    return ''.join(r.text for r in results), [a for r in results for a in r.actions]


class MalformedParserTests(TestCase):
    def test_every_detectable_action_has_a_contract_schema(self):
        from contracts.rules_assembler import normalize_runtime_action_names, get_runtime_action_schema
        from utils.actions.malformed_action_utils import build_malformed_notification
        for name in normalize_runtime_action_names(None):
            actions = extract_runtime_actions(f'<tool_call>call:{name}{{id:"abc123"}}<tool_call|>').actions
            self.assertEqual(len(actions), 1, name)
            self.assertEqual(actions[0].name, 'MALFORMED_ACTION', name)
            schema = get_runtime_action_schema(name)
            self.assertTrue(schema, name)
            notification = build_malformed_notification({'tool_id':'T1', 'result':{
                'malformed_action': name, 'payload': actions[0].payload,
            }})
            self.assertIn('\n'.join(schema), notification)

    def test_malformed_syntax_boundary_matrix_and_repeated_calls(self):
        for form, payload in zip(FORMS, PAYLOADS):
            text = 'before ' + form + ' after'
            split_points = (
                1,
                text.index('ATTACH_FILE_BY_ID') + len('ATTACH_'),
                text.index('z4tsdy'),
                len(text) - len(' after'),
                len(text) - 1,
            )
            variants = [("whole", [text]), ("charwise", list(text))]
            variants.extend(
                (f"split:{split}", [text[:split], text[split:]])
                for split in split_points
            )
            for label, chunks in variants:
                with self.subTest(form=form, chunks=label):
                    visible, actions = parse(chunks)
                    self.assertEqual(visible.split(), ['before', 'after'])
                    self.assertEqual(
                        [(a.name, a.marker_name, a.payload) for a in actions],
                        [('MALFORMED_ACTION', 'ATTACH_FILE_BY_ID', payload)],
                    )

            visible, actions = parse(list(form * 5))
            self.assertEqual(visible, '')
            self.assertEqual(len(actions), 5)
            self.assertTrue(all(a.name == 'MALFORMED_ACTION' for a in actions))

    def test_whole_text_and_mixed_source_order(self):
        source = (
            FORMS[0]
            + '<LIST_ALL_USER_SHARED_FILES>'
            + FORMS[1]
            + '<ATTACH_FILES_BY_ID> abc123 </ATTACH_FILES_BY_ID>'
        )
        for chunks in ([source], list(source)):
            visible, actions = parse(chunks)
            self.assertEqual(visible, '')
            self.assertEqual([a.name for a in actions], [
                'MALFORMED_ACTION', 'LIST_ALL_USER_SHARED_FILES',
                'MALFORMED_ACTION', 'ATTACH_FILE_BY_ID',
            ])
        self.assertEqual(len(extract_runtime_actions(source).actions), 4)

    def test_quoted_unknown_and_false_prefix_are_plain_text(self):
        for form in FORMS:
            for opener in ('"', "'", '`', '(', '[', '{', '«'):
                for chunks in ([opener + form], list(opener + form)):
                    visible, actions = parse(chunks)
                    self.assertEqual(visible, opener + form)
                    self.assertEqual(actions, [])
            unknown = form.replace('ATTACH_FILE_BY_ID', 'UNKNOWN_ACTION')
            self.assertEqual(parse(list(unknown)), (unknown, []))
        for text in ('text <ATTACH_FILE_BY_', 'text <tool_cal', '<ATTACH_FILE_BY_IDEA>hi'):
            self.assertEqual(parse(list(text)), (text, []))

    def test_incomplete_known_envelopes_and_flush_once(self):
        cases = (
            ('<ATTACH_FILE_BY_ID id="abc123">', []),
            ('<tool_call>call:ATTACH_FILE_BY_ID{id:"abc123"}', ['MALFORMED_ACTION']),
        )
        for source, expected_actions in cases:
            visible, actions = parse(list(source))
            self.assertEqual(visible, '')
            self.assertEqual([a.name for a in actions], expected_actions)
        p = RuntimeActionStreamFilter()
        p.filter(FORMS[0])
        self.assertFalse(p.flush_result().actions)
        self.assertFalse(p.flush_result().actions)


class MalformedRuntimeTests(IsolatedAsyncioTestCase):
    async def test_mixed_valid_result_and_malformed_use_one_followup(self):
        from unittest.mock import patch
        from runtime.stream import RuntimeStream
        from tests.test_runtime_stream_tokens import FakeEmitter, FakeLogger, FakeWebSocket
        from agent.nodes.brain import BrainNode
        from utils.context.tool_results import build_tool_results_context
        from utils.context.session_actions import build_session_actions_history_context

        context = SimpleNamespace(
            websocket=FakeWebSocket(), emitter=FakeEmitter(), logger=FakeLogger(),
            runtime_current_turn_id='turn-test', runtime_current_sequence_turn_id='turn-test',
        )
        stream = RuntimeStream(
            context=context, runtime_id='brain', role='brain', context_window=8192,
            log_method=context.logger.log_service, enable_validator=False,
            runtime_actions=['LIST_ALL_USER_SHARED_FILES', 'ATTACH_FILE_BY_ID'],
        )
        async def chunks():
            yield {'type': 'content', 'content': '<LIST_ALL_USER_SHARED_FILES>' + FORMS[0] + FORMS[1]}
        with patch('utils.actions.dispatcher.ensure_assets_tree'), patch('utils.actions.attachment_actions.list_file_records', return_value=[]):
            await stream.run(chunks())
        self.assertEqual([e['result']['action'] for e in context.runtime_tool_results],
                         ['list_files', 'malformed_action', 'malformed_action'])
        history = build_session_actions_history_context(context)
        self.assertIn('LIST_ALL_USER_SHARED_FILES', history)
        self.assertEqual(history.count('MALFORMED_ACTION: ATTACH_FILE_BY_ID'), 2)
        self.assertLess(history.index('LIST_ALL_USER_SHARED_FILES'), history.index('MALFORMED_ACTION'))
        prompt = BrainNode.build_followup_system_prompt(build_tool_results_context(context), 'test', context=context)
        self.assertIn('<MALFORMED_ACTION_NOTIFICATION>', prompt)
        self.assertIn('name="LIST_ALL_USER_SHARED_FILES"', prompt)
        self.assertEqual(prompt.count('<MALFORMED_ACTION_NOTIFICATION>'), 2)

    async def test_repeated_malformed_followups_stop_after_one_repair(self):
        from unittest.mock import patch
        from agent.nodes.brain import BrainNode
        from agent.state import AgentState
        from tests.test_brain_asset_flow import _context, _brain_runtime, _async_noop
        from tests.test_runtime_stream_tokens import FakeLogger, FakeWebSocket
        from utils.actions.malformed_action_utils import record_malformed_action
        context = _context()
        context.logger = FakeLogger()
        context.websocket = FakeWebSocket()
        context.runtime_current_turn_id = 'turn-test'
        calls = []

        async def run(**kwargs):
            calls.append(kwargs)
            call_number = len(calls)
            if call_number == 1:
                context.runtime_action_events.append({'name':'list_files', 'status':'completed'})
                return '', 'first valid action'
            if call_number in (2, 3):
                if call_number == 3:
                    self.assertIn('<MALFORMED_ACTION_NOTIFICATION>', kwargs['system_prompt'])
                    self.assertTrue(kwargs['filter_runtime_actions'])
                action = extract_runtime_actions(FORMS[(call_number - 2) % 3]).actions[0]
                await record_malformed_action(context, action)
                return '', 'attempt reasoning'

            self.assertEqual(call_number, 4)
            self.assertIn('<FOLLOWUP_LIMIT_REACHED>', kwargs['system_prompt'])
            self.assertIn('malformed runtime-action syntax', kwargs['system_prompt'])
            self.assertFalse(kwargs['filter_runtime_actions'])
            self.assertTrue(all(value is False for value in kwargs['runtime_actions'].values()))
            return 'stopped cleanly', 'final reasoning'

        state = AgentState(user_input='attach file')
        with patch('agent.nodes.brain.get_brain_runtime_config', return_value=_brain_runtime()), \
             patch('agent.nodes.brain.build_brain_payload', return_value='payload'), \
             patch('agent.nodes.brain.emit_active_memory_records_update_if_dirty', new=lambda c: _async_noop()), \
             patch('agent.nodes.brain.config.BRAIN_MAX_FOLLOWUPS', 1), \
             patch.object(BrainNode, 'run_brain_stream', staticmethod(run)):
            await BrainNode().run(state, context)

        self.assertEqual(len(calls), 4)
        self.assertEqual(state.brain_response, 'stopped cleanly')
        stop_events = [
            event for event in context.websocket.messages
            if event.get('action') == 'followup_limit_reached'
        ]
        self.assertEqual(len(stop_events), 1)
        self.assertIn('Malformed action repair failed after 1 retry', stop_events[0]['text'])

    async def test_stream_results_notifications_history_and_checkpoint(self):
        from runtime.stream import RuntimeStream
        from tests.test_runtime_stream_tokens import FakeEmitter, FakeLogger, FakeWebSocket
        from agent.nodes.brain import BrainNode, action_event_requires_follow_up
        from utils.context.tool_results import build_tool_results_context
        from contracts.rules_assembler import get_runtime_action_schema
        from runtime.frame_memory_utils import build_runtime_session_checkpoint
        from websocket.bootstrap import clean_bootstrap_tool_results

        context = SimpleNamespace(
            websocket=FakeWebSocket(), emitter=FakeEmitter(), logger=FakeLogger(),
            runtime_action_events=[], runtime_session_action_history=[],
            runtime_current_turn_id='turn-test', runtime_current_sequence_turn_id='turn-test',
            runtime_session_id='session-test', runtime_turn_user_message='test',
        )
        stream = RuntimeStream(
            context=context, runtime_id='brain', role='brain', context_window=8192,
            log_method=context.logger.log_service, enable_validator=False,
            runtime_actions=['ATTACH_FILE_BY_ID'],
        )
        async def chunks():
            # Parser tests above own provider-boundary fragmentation. Runtime
            # coverage here is about result/event/history propagation.
            yield {'type': 'content', 'content': 'before ' + ''.join(FORMS) + ' after'}
        response = await stream.run(chunks())
        self.assertEqual(response.split(), ['before', 'after'], context.logger.messages)
        events = [e for e in context.emitter.events if e.get('action') == 'malformed_action']
        self.assertEqual(len(events), 2)
        self.assertEqual(len({e['id'] for e in events}), 2)
        self.assertTrue(all(e['text'] == 'MALFORMED_ACTION: ATTACH_FILE_BY_ID' for e in events))
        self.assertEqual([e['payload'] for e in events], list(PAYLOADS))
        self.assertEqual(len(context.runtime_session_action_history), 2)
        self.assertTrue(all(action_event_requires_follow_up(e) for e in context.runtime_action_events))
        tool_context = build_tool_results_context(context)
        self.assertEqual(tool_context.count('name="MALFORMED_ACTION"'), 2)
        self.assertNotIn('Correct action schema', tool_context)
        prompt = BrainNode.build_followup_system_prompt(tool_context + '\nBASE', 'test', context=context)
        self.assertIn('<MALFORMED_ACTION_NOTIFICATION>', prompt)
        self.assertEqual(prompt.count('<MALFORMED_ACTION_NOTIFICATION>'), 2)
        self.assertLess(prompt.index('tool_id: T2'), prompt.index('tool_id: T1'))
        self.assertEqual(prompt.count(get_runtime_action_schema('ATTACH_FILE_BY_ID')[0]), 2)
        self.assertNotIn('ACTION_FAILURE_FOLLOWUP', prompt)
        self.assertNotIn('<MALFORMED_ACTION_NOTIFICATION>', BrainNode.build_followup_system_prompt('BASE', 'test', context=context))
        checkpoint = build_runtime_session_checkpoint(context)
        restored, _ = clean_bootstrap_tool_results(json.loads(json.dumps(checkpoint['tool_results'])))
        self.assertEqual([e['result']['payload'] for e in restored], list(PAYLOADS))
        self.assertEqual([e['tool_id'] for e in restored], ['T1', 'T2'])
        context.runtime_tool_results = restored
        self.assertEqual(build_tool_results_context(context).count('name="MALFORMED_ACTION"'), 2)
        from websocket.bootstrap import apply_archived_session_continuation_state
        restored_context = SimpleNamespace()
        saved_history = json.loads(json.dumps(context.runtime_session_action_history))
        apply_archived_session_continuation_state(restored_context, {'session_actions': saved_history})
        self.assertEqual(len(restored_context.runtime_session_action_history), 2)
        for original, hydrated in zip(saved_history, restored_context.runtime_session_action_history):
            self.assertEqual(hydrated['created_at'], original['created_at'])
            self.assertEqual(hydrated['parts'], original['parts'])
            self.assertTrue(hydrated['runtime_session_action_preserve_separate'])

    async def test_cleanup_keeps_pending_notification_and_next_failure_has_new_id(self):
        from agent.nodes.brain import consume_action_failure_followup_context
        from utils.actions.malformed_action_utils import record_malformed_action
        from utils.tool_results import clean_runtime_tool_result, record_runtime_tool_result
        context = SimpleNamespace()
        action = extract_runtime_actions(FORMS[0]).actions[0]
        await record_malformed_action(context, action)
        self.assertTrue(clean_runtime_tool_result(context, 'T1'))
        record_runtime_tool_result(context, 'runtime_action', {
            'action': 'attach_file_by_id', 'ok': False, 'payload': 'missing-id', 'error': 'file_not_found',
        })
        text = consume_action_failure_followup_context(context)
        self.assertTrue(text.startswith('<MALFORMED_ACTION_NOTIFICATION>'))
        self.assertIn('tool_id: T1', text)
        self.assertIn('<ACTION_FAILURE_FOLLOWUP>', text)
        self.assertIn('missing-id', text)
        self.assertEqual(consume_action_failure_followup_context(context), '')
        await record_malformed_action(context, action)
        text = consume_action_failure_followup_context(context)
        self.assertIn('tool_id: T3', text)
        self.assertNotIn('tool_id: T1', text)
