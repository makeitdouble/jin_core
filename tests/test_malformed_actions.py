import json
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase

from utils.actions import RuntimeActionStreamFilter, extract_runtime_actions


FORMS = (
    '<tool_call>call:ATTACH_FILE_BY_ID{id:"z4tsdy"}<tool_call|>',
    '<ATTACH_FILE_BY_ID id="z4tsdy"></ATTACH_FILE_BY_ID>',
    '<ATTACH_FILE_BY_ID>{ id="**z4tsdy**" }</ATTACH_FILE_BY_ID>',
)
PAYLOADS = ('{id:"z4tsdy"}', 'id="z4tsdy"', '{ id="**z4tsdy**" }')


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

    def test_all_boundaries_and_repeated_calls(self):
        for form, payload in zip(FORMS, PAYLOADS):
            text = 'before ' + form + ' after'
            variants = [[text], list(text)] + [[text[:i], text[i:]] for i in range(1, len(text))]
            for chunks in variants:
                with self.subTest(chunks=chunks):
                    visible, actions = parse(chunks)
                    self.assertEqual(visible.split(), ['before', 'after'])
                    self.assertEqual([(a.name, a.marker_name, a.payload) for a in actions],
                                     [('MALFORMED_ACTION', 'ATTACH_FILE_BY_ID', payload)])
            visible, actions = parse(list(form * 5))
            self.assertEqual(visible, '')
            self.assertEqual(len(actions), 5)
            self.assertTrue(all(a.name == 'MALFORMED_ACTION' for a in actions))

    def test_whole_text_and_mixed_source_order(self):
        source = FORMS[0] + '<LIST_FILES>' + FORMS[1] + '<ATTACH_FILE_BY_ID: abc123 >' + FORMS[2]
        for chunks in ([source], list(source)):
            visible, actions = parse(chunks)
            self.assertEqual(visible, '')
            self.assertEqual([a.name for a in actions], [
                'MALFORMED_ACTION', 'LIST_FILES', 'MALFORMED_ACTION',
                'ATTACH_FILE_BY_ID', 'MALFORMED_ACTION',
            ])
        self.assertEqual(len(extract_runtime_actions(source).actions), 5)

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
        for source in ('<ATTACH_FILE_BY_ID id="abc123">',
                       '<ATTACH_FILE_BY_ID>{ id="abc123" }',
                       '<tool_call>call:ATTACH_FILE_BY_ID{id:"abc123"}'):
            visible, actions = parse(list(source))
            self.assertEqual(visible, '')
            self.assertEqual([a.name for a in actions], ['MALFORMED_ACTION'])
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
            runtime_actions=['LIST_FILES', 'ATTACH_FILE_BY_ID'],
        )
        async def chunks():
            yield {'type': 'content', 'content': '<LIST_FILES>' + FORMS[0] + FORMS[1]}
        with patch('utils.actions.dispatcher.ensure_assets_tree'), patch('utils.actions.attachment_actions.list_file_records', return_value=[]):
            await stream.run(chunks())
        self.assertEqual([e['result']['action'] for e in context.runtime_tool_results],
                         ['list_files', 'malformed_action', 'malformed_action'])
        history = build_session_actions_history_context(context)
        self.assertIn('LIST_FILES: 0 files', history)
        self.assertEqual(history.count('MALFORMED_ACTION: ATTACH_FILE_BY_ID'), 2)
        self.assertLess(history.index('LIST_FILES'), history.index('MALFORMED_ACTION'))
        prompt = BrainNode.build_followup_system_prompt(build_tool_results_context(context), 'test', context=context)
        self.assertTrue(prompt.startswith('<MALFORMED_ACTION_NOTIFICATION>'))
        self.assertIn('name="LIST_FILES"', prompt)
        self.assertEqual(prompt.count('<MALFORMED_ACTION_NOTIFICATION>'), 2)

    async def test_repeated_malformed_followups_have_no_repair_limit(self):
        from unittest.mock import patch
        from agent.nodes.brain import BrainNode
        from agent.state import AgentState
        from tests.test_brain_asset_flow import _context, _brain_runtime, _async_noop
        from tests.test_runtime_stream_tokens import FakeLogger
        from utils.actions.malformed_action_utils import record_malformed_action
        context = _context()
        context.logger = FakeLogger()
        context.runtime_current_turn_id = 'turn-test'
        calls = []
        async def run(**kwargs):
            calls.append(kwargs)
            if len(calls) > 2:
                self.assertTrue(kwargs['system_prompt'].startswith('<MALFORMED_ACTION_NOTIFICATION>'))
                self.assertTrue(kwargs['filter_runtime_actions'])
                self.assertNotIn('<FOLLOWUP_LIMIT_REACHED>', kwargs['system_prompt'])
            if len(calls) == 1:
                context.runtime_action_events.append({'name':'list_files', 'status':'completed'})
                return '', 'first valid action'
            if len(calls) <= 5:
                action = extract_runtime_actions(FORMS[(len(calls)-1) % 3]).actions[0]
                await record_malformed_action(context, action)
                return '', 'attempt reasoning'
            return 'done', 'done reasoning'
        state = AgentState(user_input='attach file')
        with patch('agent.nodes.brain.get_brain_runtime_config', return_value=_brain_runtime()), \
             patch('agent.nodes.brain.build_brain_payload', return_value='payload'), \
             patch('agent.nodes.brain.emit_active_memory_records_update_if_dirty', new=lambda c: _async_noop()), \
             patch('agent.nodes.brain.config.BRAIN_MAX_FOLLOWUPS', 1), \
             patch.object(BrainNode, 'run_brain_stream', staticmethod(run)):
            await BrainNode().run(state, context)
        self.assertEqual(len(calls), 6)
        self.assertEqual(state.brain_response, 'done')

    async def test_stream_results_notifications_history_and_checkpoint(self):
        from runtime.stream import RuntimeStream
        from tests.test_runtime_stream_tokens import FakeEmitter, FakeLogger, FakeWebSocket
        from agent.nodes.brain import BrainNode, action_event_requires_follow_up
        from utils.context.tool_results import build_tool_results_context
        from contracts.rules_assembler import get_runtime_action_schema
        from runtime.L1_memory_utils import build_runtime_session_checkpoint
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
            for chunk in 'before ' + ''.join(FORMS) + ' after':
                yield {'type': 'content', 'content': chunk}
        response = await stream.run(chunks())
        self.assertEqual(response.split(), ['before', 'after'], context.logger.messages)
        events = [e for e in context.emitter.events if e.get('action') == 'malformed_action']
        self.assertEqual(len(events), 3)
        self.assertEqual(len({e['id'] for e in events}), 3)
        self.assertTrue(all(e['text'] == 'MALFORMED_ACTION: ATTACH_FILE_BY_ID' for e in events))
        self.assertEqual([e['payload'] for e in events], list(PAYLOADS))
        self.assertEqual(len(context.runtime_session_action_history), 3)
        self.assertTrue(all(action_event_requires_follow_up(e) for e in context.runtime_action_events))
        tool_context = build_tool_results_context(context)
        self.assertEqual(tool_context.count('name="MALFORMED_ACTION"'), 3)
        self.assertNotIn('Correct action schema', tool_context)
        prompt = BrainNode.build_followup_system_prompt(tool_context + '\nBASE', 'test', context=context)
        self.assertTrue(prompt.startswith('<MALFORMED_ACTION_NOTIFICATION>'))
        self.assertEqual(prompt.count('<MALFORMED_ACTION_NOTIFICATION>'), 3)
        self.assertLess(prompt.index('tool_id: T1'), prompt.index('tool_id: T2'))
        self.assertLess(prompt.index('tool_id: T2'), prompt.index('tool_id: T3'))
        self.assertEqual(prompt.count(get_runtime_action_schema('ATTACH_FILE_BY_ID')[0]), 3)
        self.assertNotIn('ACTION_FAILURE_FOLLOWUP', prompt)
        self.assertNotIn('<MALFORMED_ACTION_NOTIFICATION>', BrainNode.build_followup_system_prompt('BASE', 'test', context=context))
        checkpoint = build_runtime_session_checkpoint(context)
        restored, _ = clean_bootstrap_tool_results(json.loads(json.dumps(checkpoint['tool_results'])))
        self.assertEqual([e['result']['payload'] for e in restored], list(PAYLOADS))
        self.assertEqual([e['tool_id'] for e in restored], ['T1', 'T2', 'T3'])
        context.runtime_tool_results = restored
        self.assertEqual(build_tool_results_context(context).count('name="MALFORMED_ACTION"'), 3)
        from websocket.bootstrap import apply_archived_session_continuation_state
        restored_context = SimpleNamespace()
        saved_history = json.loads(json.dumps(context.runtime_session_action_history))
        apply_archived_session_continuation_state(restored_context, {'session_actions': saved_history})
        self.assertEqual(len(restored_context.runtime_session_action_history), 3)
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
