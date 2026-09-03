import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tests import test_project_review as fixture
from agent.nodes.brain import BrainNode, build_followup_attachment_payload
from agent.state import AgentState
from clients.brain_client import apply_runtime_action_calls
from contracts.rules_assembler import get_runtime_action_schema
from rules.brain_context_builder import build_brain_context, BRAIN_RUNTIME_ACTIONS
from utils import attached_files_store as files
from utils.actions import RuntimeActionStreamFilter, extract_runtime_actions
from utils.actions.attachment_actions import apply_attachment_context_ids
from utils.context.files import build_file_contents_context, loaded_project_files
from utils.context.tool_results import build_tool_results_context
from utils.tool_results import record_runtime_tool_result, clear_runtime_tool_results
from websocket.attachments import build_user_text_with_attachments
from websocket.bootstrap import apply_bootstrap_tool_results
from runtime.L1_memory_utils import build_runtime_session_checkpoint


class ProjectFileLifecycleTests(unittest.TestCase):
    setUp = fixture.ProjectReviewTests.setUp
    prompt = fixture.ProjectReviewTests.prompt

    def call(self, *markers):
        parsed = extract_runtime_actions(''.join(markers), enabled_actions=['ATTACH_FILE','DETACH_FILE','ASSET_ACTION'])
        self.assertEqual(len(parsed.failed_actions), 0)
        self.assertTrue(parsed.actions)
        asyncio.run(apply_runtime_action_calls(self.context, parsed.actions))
        return self.context.runtime_tool_results[-1]['result']

    def ref(self, path='src/main.py'):
        return self.record['id'] + '/' + path

    def test_batch_loads_have_one_body_each_and_readable_results(self):
        from runtime.stream import RuntimeStream
        from tests import test_runtime_stream_tokens as stream_fixture
        self.context.logger = stream_fixture.FakeLogger()
        self.context.websocket = stream_fixture.FakeWebSocket()
        async def run():
            stream = RuntimeStream(context=self.context, runtime_id="file-lifecycle-test", role="brain",
                context_window=32768, log_method=self.context.logger.log_service,
                runtime_actions=BRAIN_RUNTIME_ACTIONS, enable_validator=False)
            async def chunks(**_kwargs):
                for marker in ('<ATTACH_FILE: src/main.py >', '<ATTACH_FILE: README.md >'):
                    for part in (marker[:13], marker[13:]):
                        yield {"type":"content", "content":part}
            from clients.brain_client import ask_brain_stream
            await stream.run(ask_brain_stream(client=SimpleNamespace(stream=chunks), text="inspect project",
                context=self.context, runtime_actions=BRAIN_RUNTIME_ACTIONS,
                system_prompt=self.prompt(), brain_payload="inspect project"))
        asyncio.run(run())
        prompt = self.prompt()
        self.assertEqual(prompt.count('1: first'), 1)
        self.assertEqual(prompt.count('1: Project overview'), 1)
        self.assertIn('<FILE_CONTENT: src/main.py >', prompt)
        self.assertIn('Loaded: 3 files', prompt)
        tools = build_tool_results_context(self.context)
        for value in ('1: first', '"content":', 'Notice:', 'Result (source data'):
            self.assertNotIn(value, tools)
        self.assertIn('Read: 1-4 of 4 lines', tools)
        events = [e for e in self.context.emitter.events if e.get('attachment_result')]
        self.assertEqual(len(events), 2)
        self.assertTrue(all(e['status'] == 'completed' for e in events))
        self.assertIn(self.ref(), events[0]['attachment_result']['file_ref'])
        self.assertIn('src/main.py', str(self.context.runtime_session_action_history))


    def test_relative_and_explicit_paths_share_identity_and_unload(self):
        result = self.call('<ATTACH_FILE: src/main.py >')
        self.assertTrue(result['ok'])
        self.assertEqual(result['file_ref'], self.ref())
        for path in ('./src/main.py', self.ref(), r'src\main.py#L2-L3'):
            result = self.call(f'<ATTACH_FILE: {path} >')
            self.assertFalse(result['ok'])
            self.assertIn('already loaded', result['detail'])
            self.assertTrue(self.context.runtime_followup_action_failure_pending)
            self.assertEqual(self.prompt().count('1: first'), 1)
        self.call('<DETACH_FILE: ./src/main.py >', '<ATTACH_FILE: src/main.py#L2-L3 >')
        self.assertNotIn('1: first', build_file_contents_context(self.context))
        self.assertEqual(self.prompt().count('2: needle = 42'), 1)
        self.assertTrue(self.call(f'<DETACH_FILE: {self.ref()} >')['ok'])
        self.assertEqual(build_file_contents_context(self.context), '')

    def test_relative_paths_preserve_nested_names_case_spaces_and_backslashes(self):
        (self.project / 'config').mkdir()
        (self.project / 'config' / 'My файл.txt').write_text('unique nested body', encoding='utf-8')
        result = self.call(r'<ATTACH_FILE: config\My файл.txt >')
        self.assertTrue(result['ok'])
        self.assertEqual(result['file_ref'], self.ref('config/My файл.txt'))
        self.assertTrue(self.call(r'<DETACH_FILE: config\My файл.txt >')['ok'])
        self.assertNotIn('unique nested body', build_file_contents_context(self.context))
        # A six-character filename is a relative path unless it is a real persistent ID.
        (self.project / 'abcdef').write_text('six character file', encoding='utf-8')
        self.assertTrue(self.call('<ATTACH_FILE: abcdef >')['ok'])
        self.assertTrue(self.call('<DETACH_FILE: abcdef >')['ok'])

    def test_multiple_folders_require_explicit_root_and_follow_current_attachments(self):
        from utils.project_reader import link_project_folder
        other = self.root / 'other'
        other.mkdir()
        (other / 'README.md').write_text('second project', encoding='utf-8')
        record, _, _ = link_project_folder(str(other))
        # Globally pinned files outside this runtime are not implicit roots.
        self.assertTrue(self.call('<ATTACH_FILE: README.md >')['ok'])
        apply_attachment_context_ids(self.context, [self.record['id'], record['id']])
        for marker in ('<ATTACH_FILE: src/main.py >', '<DETACH_FILE: README.md >'):
            result = self.call(marker)
            self.assertFalse(result['ok'])
            self.assertIn('Multiple folders', result['detail'])
            self.assertTrue(self.context.runtime_followup_action_failure_pending)
        self.assertIn('Project overview', build_file_contents_context(self.context))
        self.assertTrue(self.call(f'<ATTACH_FILE: {record["id"]}/README.md >')['ok'])
        self.assertTrue(self.call(f'<DETACH_FILE: {record["id"]}/README.md >')['ok'])
        apply_attachment_context_ids(self.context, [record['id']])
        self.assertTrue(self.call('<ATTACH_FILE: README.md >')['ok'])
        self.assertNotIn('Project overview', build_file_contents_context(self.context))
        self.assertIn('second project', build_file_contents_context(self.context))
        # An explicit detached folder must not fall back to the remaining root.
        self.assertFalse(self.call(f'<ATTACH_FILE: {self.ref("README.md")} >')['ok'])

    def test_relative_paths_need_attached_root_and_stay_inside_it(self):
        for path in ('../outside.txt', '/etc/passwd', r'C:\outside.txt', 'missing.txt'):
            result = self.call(f'<ATTACH_FILE: {path} >')
            self.assertFalse(result['ok'])
            self.assertNotIn('content', result)
        apply_attachment_context_ids(self.context, [])
        for name in ('ATTACH_FILE', 'DETACH_FILE'):
            result = self.call(f'<{name}: README.md >')
            self.assertFalse(result['ok'])
            self.assertIn('No folder attached', result['detail'])
        self.assertTrue(self.context.runtime_followup_action_failure_pending)
        self.assertIn('<ATTACH_FILE: relative/path >', get_runtime_action_schema('ATTACH_FILE'))
        self.assertIn('<DETACH_FILE: relative/path >', get_runtime_action_schema('DETACH_FILE'))

    def test_persistent_id_wins_over_same_relative_filename(self):
        record, _, _ = files.store_uploaded_file(name='upload.txt', content=b'persistent body', pin=False)
        (self.project / record['id']).write_text('project file body', encoding='utf-8')
        self.assertTrue(self.call(f'<ATTACH_FILE: {record["id"]} >')['ok'])
        self.assertIn('persistent body', build_file_contents_context(self.context))
        self.assertNotIn('project file body', build_file_contents_context(self.context))
        self.assertTrue(self.call(f'<ATTACH_FILE: ./{record["id"]} >')['ok'])
        self.assertTrue(self.call(f'<DETACH_FILE: {record["id"]} >')['ok'])
        self.assertNotIn('persistent body', build_file_contents_context(self.context))
        self.assertIn('project file body', build_file_contents_context(self.context))

    def test_duplicate_canonical_and_legacy_reads_fail_without_injecting_body(self):
        self.call(f'<ATTACH_FILE: {self.ref()} >')
        for marker in (f'<ATTACH_FILE: {self.ref()}#L2-L3 >',
                       '<ASSET_ACTION>' + json.dumps({'action':'project_read', 'attachment':self.record['id'], 'path':'src/./main.py'}) + '</ASSET_ACTION>'):
            result = self.call(marker)
            self.assertFalse(result['ok'])
            self.assertIn('already loaded', result['detail'])
            self.assertNotIn('content', result)
            self.assertTrue(self.context.runtime_followup_action_failure_pending)
            self.assertEqual(self.prompt().count('1: first'), 1)

    def test_detach_then_attach_range_in_same_message_and_attach_then_detach(self):
        self.call(f'<ATTACH_FILE: {self.ref()} >')
        self.call(f'<DETACH_FILE: {self.ref()} >', f'<ATTACH_FILE: {self.ref()}#L2-L3 >')
        self.assertNotIn('1: first', self.prompt())
        self.assertEqual(self.prompt().count('2: needle = 42'), 1)
        self.assertTrue(self.context.runtime_tool_results[-1]['result']['ok'])
        self.call(f'<ATTACH_FILE: {self.ref("README.md")} >', f'<DETACH_FILE: {self.ref("README.md")} >')
        self.assertNotIn('Project overview', build_file_contents_context(self.context))
        self.assertIn('3: third', build_file_contents_context(self.context))
        self.assertTrue((self.project / 'README.md').is_file())

    def test_legacy_read_uses_same_unload_and_dedupe_path(self):
        marker = '<ASSET_ACTION>' + json.dumps({'action':'project_read', 'attachment':self.record['id'], 'path':'src/main.py'}) + '</ASSET_ACTION>'
        self.call(marker)
        self.assertFalse(self.call(f'<ATTACH_FILE: {self.ref()} >')['ok'])
        self.call(f'<DETACH_FILE: {self.ref()} >')
        self.assertNotIn('content', self.context.runtime_asset_results[0])
        self.assertNotIn('1: first', self.prompt())
        self.assertTrue(self.call(f'<ATTACH_FILE: {self.ref()} >')['ok'])

    def test_persistent_file_uses_same_body_projection_and_duplicate_failure(self):
        record, _, _ = files.store_uploaded_file(name='upload.txt', content=b'UNIQUE UPLOAD BODY', pin=False)
        self.call(f'<ATTACH_FILE: {record["id"]} >')
        user = build_user_text_with_attachments({'text':'inspect', 'attachments':self.context.runtime_turn_attachments})
        self.assertNotIn('UNIQUE UPLOAD BODY', user)
        self.assertEqual((self.prompt() + user + build_followup_attachment_payload(self.context)).count('UNIQUE UPLOAD BODY'), 1)
        self.assertFalse(self.call(f'<ATTACH_FILE: {record["id"]} >')['ok'])
        self.assertTrue(self.context.runtime_followup_action_failure_pending)
        self.call(f'<DETACH_FILE: {record["id"]} >')
        self.assertNotIn('UNIQUE UPLOAD BODY', self.prompt())
        self.assertIsNotNone(files.get_file_record(record['id']))

    def test_upload_and_project_alias_of_same_bytes_do_not_duplicate(self):
        record, _, _ = files.store_uploaded_file(name='copy.py', content=(self.project/'src/main.py').read_bytes(), pin=False)
        self.call(f'<ATTACH_FILE: {record["id"]} >')
        self.assertFalse(self.call(f'<ATTACH_FILE: {self.ref()} >')['ok'])
        self.call(f'<DETACH_FILE: {record["id"]} >')
        self.assertTrue(self.call(f'<ATTACH_FILE: {self.ref()} >')['ok'])
        self.assertFalse(self.call(f'<ATTACH_FILE: {record["id"]} >')['ok'])

    def test_folder_detach_and_ui_unpin_drop_bodies_without_resurrection(self):
        for model_action in (True, False):
            apply_attachment_context_ids(self.context, [self.record['id']])
            self.call(f'<ATTACH_FILE: {self.ref()} >')
            if model_action:
                self.call(f'<DETACH_FILE: {self.record["id"]} >')
            else:
                apply_attachment_context_ids(self.context, [])
            self.assertNotIn('1: first', self.prompt())
            apply_attachment_context_ids(self.context, [self.record['id']])
            self.assertNotIn('1: first', self.prompt())
            self.assertTrue((self.project / 'src/main.py').is_file())

    def test_empty_binary_invalid_paths_and_detach_missing(self):
        (self.project/'empty.txt').write_text('')
        self.assertTrue(self.call(f'<ATTACH_FILE: {self.ref("empty.txt")} >')['ok'])
        self.assertFalse(self.call(f'<ATTACH_FILE: {self.ref("empty.txt")} >')['ok'])
        (self.project/'binary.dat').write_bytes(b'hello\x00binary')
        for path in ('../outside', 'binary.dat', 'missing.txt'):
            self.assertFalse(self.call(f'<ATTACH_FILE: {self.ref(path)} >')['ok'])
        self.assertFalse(self.call(f'<DETACH_FILE: {self.ref("missing.txt")} >')['ok'])
        self.assertNotIn('project_read', '\n'.join(get_runtime_action_schema('ASSET_ACTION')))
        self.assertIn('<DETACH_FILE: folder_id/relative/path >', get_runtime_action_schema('DETACH_FILE'))

    def test_snapshot_round_trip_keeps_live_body_beyond_history_tail_and_unload(self):
        # Escaped JSON is >32K although the exact read itself is <=24K.
        (self.project/'escapes.txt').write_text('\\' * 22000)
        self.call(f'<ATTACH_FILE: {self.ref("escapes.txt")} >')
        body = build_file_contents_context(self.context)
        for index in range(65):
            record_runtime_tool_result(self.context, 'runtime_action', {'action':'test', 'ok':True, 'value':index})
        snapshot = json.loads(json.dumps(build_runtime_session_checkpoint(self.context)))
        self.assertGreater(len(snapshot['tool_results']), 20)
        original_dates = [v.get('created_at') for v in snapshot['tool_results']]
        self.context.runtime_tool_results = []
        apply_bootstrap_tool_results(self.context, snapshot)
        self.assertEqual(build_file_contents_context(self.context), body)
        self.assertEqual(self.context.runtime_tool_result_created_ats, original_dates)
        self.call(f'<DETACH_FILE: {self.ref("escapes.txt")} >')
        snapshot = json.loads(json.dumps(build_runtime_session_checkpoint(self.context)))
        self.context.runtime_tool_results = []
        apply_bootstrap_tool_results(self.context, snapshot)
        self.assertEqual(build_file_contents_context(self.context), '')
        self.assertTrue(self.call(f'<ATTACH_FILE: {self.ref("escapes.txt")} >')['ok'])
        clear_runtime_tool_results(self.context)
        self.assertEqual(build_file_contents_context(self.context), '')
        apply_bootstrap_tool_results(self.context, {'tool_results': []})
        self.assertEqual(build_file_contents_context(self.context), '')

    def test_old_duplicate_records_and_user_attachment_bodies_are_not_reinjected(self):
        result = {'action':'project_read','attachment':self.record['id'],'path':'src/main.py','ok':True,'content':'old exact body'}
        for _ in range(2):
            record_runtime_tool_result(self.context,'asset',result)
        self.context.runtime_recent_turns = [{'user':'inspect\n--- BEGIN ATTACHMENT TEXT: old.txt ---\nOLD HIDDEN BODY\n--- END ATTACHMENT TEXT: old.txt ---','jin':'I read old.txt'}]
        prompt = self.prompt()
        self.assertEqual(prompt.count('old exact body'), 1)
        self.assertNotIn('OLD HIDDEN BODY', prompt)
        self.assertIn('I read old.txt', prompt)
        self.call(f'<DETACH_FILE: {self.ref()} >')
        self.assertNotIn('old exact body', self.prompt())

    def test_explicit_empty_checkpoint_blocks_legacy_mirror_and_missing_keeps_state(self):
        self.call('<ASSET_ACTION>' + json.dumps({'action':'project_read', 'attachment':self.record['id'], 'path':'src/main.py'}) + '</ASSET_ACTION>')
        apply_bootstrap_tool_results(self.context, {})
        self.assertIn('1: first', build_file_contents_context(self.context))
        apply_bootstrap_tool_results(self.context, {'tool_results': []})
        self.assertEqual(build_file_contents_context(self.context), '')
        self.assertTrue(self.call(f'<ATTACH_FILE: {self.ref()} >')['ok'])

    def test_new_file_marker_chunk_boundaries_quotes_repetition_and_flush(self):
        for marker in (f'<ATTACH_FILE: {self.ref()}#L2-L3 >', f'<DETACH_FILE: {self.ref()} >',
                       '<ATTACH_FILE: src/main.py#L2-L3 >', '<DETACH_FILE: README.md >'):
            for split in range(len(marker)+1):
                parser=RuntimeActionStreamFilter(enabled_actions=['ATTACH_FILE','DETACH_FILE','ASSET_ACTION'])
                chunks=[parser.filter(marker[:split]),parser.filter(marker[split:]),parser.flush_result()]
                self.assertEqual(sum(len(c.actions) for c in chunks),1)
                self.assertEqual(''.join(c.text for c in chunks),'')
                parser=RuntimeActionStreamFilter(enabled_actions=['ATTACH_FILE','DETACH_FILE','ASSET_ACTION'])
                chunks=[parser.filter('"'+marker[:split]),parser.filter(marker[split:]+'"'),parser.flush_result()]
                self.assertEqual(sum(len(c.actions) for c in chunks),0)
            self.assertEqual(len(extract_runtime_actions(marker+marker,enabled_actions=['ATTACH_FILE','DETACH_FILE','ASSET_ACTION']).actions),1)
        parser=RuntimeActionStreamFilter(enabled_actions=['ATTACH_FILE','DETACH_FILE','ASSET_ACTION'])
        parser.filter(f'<ATTACH_FILE: {self.ref()}')
        self.assertFalse(parser.flush_result().actions)
        self.assertFalse(extract_runtime_actions('<ATTACH_FILEISH: abc123>', enabled_actions=['ATTACH_FILE','DETACH_FILE','ASSET_ACTION']).actions)

    def test_brain_batch_duplicate_error_unload_followups_keep_reasoning_and_source_once(self):
        calls=[]
        async def stream(**kwargs):
            calls.append(kwargs)
            prompt=kwargs['system_prompt']
            index=len(calls)-1
            if index:
                self.assertIn('batch thought',prompt)
                self.assertIn('CURRENT_REQUEST_FLOW',prompt)
            if index==1:
                self.assertEqual(prompt.count('1: first'),1)
                markers=[f'<ATTACH_FILE: {self.ref()} >']
            elif index==2:
                self.assertIn('already loaded',prompt)
                self.assertEqual(prompt.count('1: first'),1)
                markers=[f'<DETACH_FILE: {self.ref()} >']
            elif index==3:
                self.assertNotIn('1: first',prompt)
                self.assertEqual(prompt.count('1: Project overview'),1)
                return 'Done.','finished'
            else:
                markers=[f'<ATTACH_FILE: {self.ref()} >',f'<ATTACH_FILE: {self.ref("README.md")} >']
            actions=extract_runtime_actions(''.join(markers),enabled_actions=['ATTACH_FILE','DETACH_FILE','ASSET_ACTION']).actions
            await apply_runtime_action_calls(self.context,actions,runtime_message_id=f'file-step-{index}')
            self.context.runtime_turn_reasoning_content += '\nbatch thought '+str(index)
            return '', 'batch thought '+str(index)
        state=AgentState(user_input='inspect project')
        runtime={'runtime_id':'brain-test','label':'brain','context_window':32768,'log_method':'log_brain','runtime_actions':BRAIN_RUNTIME_ACTIONS}
        self.context.clients={'brain':object()}
        with patch('agent.nodes.brain.get_brain_runtime_config',return_value=runtime),patch.object(BrainNode,'run_brain_stream',staticmethod(stream)):
            asyncio.run(BrainNode().run(state,self.context))
        self.assertEqual(len(calls),4)
        self.assertEqual(state.brain_response,'Done.')
