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
        parsed = extract_runtime_actions(''.join(markers), enabled_actions=['ATTACH_FILE_CONTENT','ASSET_ACTION'])
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
                for marker in ('<ATTACH_FILE_CONTENT: src/main.py >', '<ATTACH_FILE_CONTENT: README.md >'):
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
        self.assertIn('<FILE_CONTENT: main.py#1-4 >', prompt)
        self.assertIn('Loaded: 3 files', prompt)
        tools = build_tool_results_context(self.context)
        for value in ('"content":', 'Notice:', 'Result (source data'):
            self.assertNotIn(value, tools)
        self.assertIn('1: first', tools)
        self.assertIn('1: Project overview', tools)
        main_tool = tools.index(f'File: {self.project.name}/src/main.py#1-4')
        main_source = tools.index('<FILE_CONTENT: main.py#1-4 >')
        main_close = tools.index('</TOOL_RESULT>', main_tool)
        self.assertLess(main_tool, main_source)
        self.assertLess(main_source, main_close)
        self.assertLess(tools.index('tool_id="T2"'), tools.index('tool_id="T1"'))
        self.assertIn('File lines: 1-4 of 4 lines', tools)
        events = [e for e in self.context.emitter.events if e.get('attachment_result')]
        self.assertEqual(len(events), 2)
        self.assertTrue(all(e['status'] == 'completed' for e in events))
        self.assertIn(self.ref(), events[0]['attachment_result']['file_ref'])
        self.assertIn('src/main.py', str(self.context.runtime_session_action_history))


    def test_relative_and_explicit_paths_share_identity_and_allow_reread(self):
        result = self.call('<ATTACH_FILE_CONTENT: src/main.py >')
        self.assertTrue(result['ok'])
        self.assertEqual(result['file_ref'], self.ref())
        for path in ('./src/main.py', f'{self.project.name}/src/main.py', self.ref()):
            result = self.call(f'<ATTACH_FILE_CONTENT: {path}#L1-L200 >')
            self.assertTrue(result['ok'])
            self.assertEqual(result['file_ref'], self.ref())
        ranged = self.call(r'<ATTACH_FILE_CONTENT: src\main.py#L2-L3 >')
        self.assertTrue(ranged['ok'])
        self.assertEqual((ranged['requested_start'], ranged['requested_end']), (2, 3))
        self.assertEqual(len(list(loaded_project_files(self.context))), 2)
        prompt = self.prompt()
        self.assertEqual(prompt.count('<FILE_CONTENT: main.py#1-4 >'), 1)
        self.assertEqual(prompt.count('<FILE_CONTENT: main.py#2-3 >'), 1)

    def test_relative_paths_preserve_nested_names_case_spaces_and_backslashes(self):
        (self.project / 'config').mkdir()
        (self.project / 'config' / 'My файл.txt').write_text('unique nested body', encoding='utf-8')
        result = self.call(r'<ATTACH_FILE_CONTENT: config\My файл.txt >')
        self.assertTrue(result['ok'])
        self.assertEqual(result['file_ref'], self.ref('config/My файл.txt'))
        self.assertIn('unique nested body', build_file_contents_context(self.context))
        # A six-character filename is a relative path unless it is a real persistent ID.
        (self.project / 'abcdef').write_text('six character file', encoding='utf-8')
        self.assertTrue(self.call('<ATTACH_FILE_CONTENT: abcdef >')['ok'])

    def test_multiple_folders_require_explicit_root_and_follow_current_attachments(self):
        from utils.project_reader import link_project_folder
        other = self.root / 'other'
        other.mkdir()
        (other / 'README.md').write_text('second project', encoding='utf-8')
        record, _, _ = link_project_folder(str(other))
        self.assertTrue(self.call('<ATTACH_FILE_CONTENT: README.md >')['ok'])
        apply_attachment_context_ids(self.context, [self.record['id'], record['id']])
        result = self.call('<ATTACH_FILE_CONTENT: src/main.py >')
        self.assertFalse(result['ok'])
        self.assertIn('Multiple folders', result['detail'])
        self.assertTrue(self.context.runtime_followup_action_failure_pending)
        self.assertIn('Project overview', build_file_contents_context(self.context))
        self.assertTrue(self.call(f'<ATTACH_FILE_CONTENT: {other.name}/README.md >')['ok'])
        # Old id-prefixed paths remain valid for compatibility.
        self.assertTrue(self.call(f'<ATTACH_FILE_CONTENT: {record["id"]}/README.md#L1-L200 >')['ok'])
        apply_attachment_context_ids(self.context, [record['id']])
        self.assertTrue(self.call('<ATTACH_FILE_CONTENT: README.md#L1-L200 >')['ok'])
        self.assertNotIn('Project overview', build_file_contents_context(self.context))
        self.assertIn('second project', build_file_contents_context(self.context))
        self.assertFalse(self.call(f'<ATTACH_FILE_CONTENT: {self.ref("README.md")} >')['ok'])

    def test_restore_priming_staged_folder_resolves_actions_without_becoming_live_prompt_context(self):
        apply_attachment_context_ids(self.context, [])
        self.context.runtime_session_restore_priming = True
        self.context.runtime_session_restore_pending_attached_file_ids = [self.record["id"]]

        self.assertFalse(fixture.project_review_active(self.context))
        tree = fixture.run_project_action(
            self.context,
            {"action": "project_tree", "attachment": self.record["id"], "path": "."},
        )
        self.assertTrue(tree["ok"])

        rooted = self.call(f'<ATTACH_FILE_CONTENT: {self.project.name}/src/main.py >')
        self.assertTrue(rooted["ok"])
        relative = self.call('<ATTACH_FILE_CONTENT: src/main.py#L1-L200 >')
        self.assertTrue(relative["ok"])
        self.assertEqual(relative["file_ref"], self.ref())
        self.assertEqual(self.context.runtime_attached_file_ids, [])

    def test_relative_paths_stay_inside_root_and_no_link_falls_back_to_jin_source(self):
        for path in ('../outside.txt', '/etc/passwd', r'C:\outside.txt', 'missing.txt'):
            result = self.call(f'<ATTACH_FILE_CONTENT: {path} >')
            self.assertFalse(result['ok'])
            self.assertNotIn('content', result)

        apply_attachment_context_ids(self.context, [])
        with patch('utils.project_reader.DEFAULT_PROJECT_ROOT', self.project):
            result = self.call('<ATTACH_FILE_CONTENT: README.md >')
            self.assertTrue(result['ok'])
            self.assertTrue(result['implicit_project'])
            self.assertEqual(result['project_name'], self.project.name)
            self.assertIn('1: Project overview', build_file_contents_context(self.context))
            self.assertFalse(fixture.project_review_active(self.context))

            rooted = self.call(f'<ATTACH_FILE_CONTENT: {self.project.name}/src/main.py#L1-L2 >')
            self.assertTrue(rooted['ok'])
            self.assertEqual(rooted['content'], '1: first\n2: needle = 42')

            search = fixture.run_project_action(self.context, {
                'action': 'project_search',
                'attachment': 'jin_core',
                'path': '.',
                'query': 'needle',
            })
            self.assertTrue(search['ok'])
            self.assertTrue(search['implicit_project'])
            self.assertIn(f'{self.project.name}/src/main.py:2: needle = 42', search['content'])

            tree = fixture.run_project_action(self.context, {
                'action': 'project_tree',
                'path': '.',
            })
            self.assertTrue(tree['ok'])
            self.assertTrue(tree['implicit_project'])

            # A real UI-linked folder still owns Project Mode and immediately
            # disables the implicit source root.
            apply_attachment_context_ids(self.context, [self.record['id']])
            self.assertTrue(fixture.project_review_active(self.context))
            self.assertFalse(any(r.get('implicit_project') for r in loaded_project_files(self.context)))

        self.assertIn('<ATTACH_FILE_CONTENT: relative/path >', get_runtime_action_schema('ATTACH_FILE_CONTENT'))

    def test_persistent_id_wins_over_same_relative_filename(self):
        record, _, _ = files.store_uploaded_file(name='upload.txt', content=b'persistent body', pin=False)
        (self.project / record['id']).write_text('project file body', encoding='utf-8')
        self.assertTrue(self.call(f'<ATTACH_FILE_CONTENT: {record["id"]} >')['ok'])
        self.assertIn('persistent body', build_file_contents_context(self.context))
        self.assertNotIn('project file body', build_file_contents_context(self.context))
        self.assertTrue(self.call(f'<ATTACH_FILE_CONTENT: ./{record["id"]} >')['ok'])
        self.assertIn('project file body', build_file_contents_context(self.context))
        # User attachment state, not a model action, controls persistent pinning.
        apply_attachment_context_ids(self.context, [self.record['id']])
        self.assertNotIn('persistent body', build_file_contents_context(self.context))
        self.assertIn('project file body', build_file_contents_context(self.context))

    def test_same_project_file_allows_distinct_ranges_and_exact_rereads(self):
        first = self.call(f'<ATTACH_FILE_CONTENT: {self.ref()} >')
        self.assertTrue(first['ok'])
        self.assertEqual((first['requested_start'], first['requested_end']), (1, 200))

        second = self.call(f'<ATTACH_FILE_CONTENT: {self.ref()}#L2-L3 >')
        self.assertTrue(second['ok'])
        self.assertEqual((second['requested_start'], second['requested_end']), (2, 3))

        for marker in (
            f'<ATTACH_FILE_CONTENT: {self.ref()}#L1-L200 >',
            f'<ATTACH_FILE_CONTENT: {self.ref()}#L2-L3 >',
            '<ASSET_ACTION>' + json.dumps({
                'action':'project_read',
                'attachment':self.record['id'],
                'path':'src/./main.py',
            }) + '</ASSET_ACTION>',
        ):
            result = self.call(marker)
            self.assertTrue(result['ok'])

        self.assertEqual(len(list(loaded_project_files(self.context))), 2)
        prompt = self.prompt()
        self.assertEqual(prompt.count('<FILE_CONTENT: main.py#1-4 >'), 1)
        self.assertEqual(prompt.count('<FILE_CONTENT: main.py#2-3 >'), 1)

    def test_sequential_project_windows_remain_loaded_as_separate_blocks(self):
        long_file = self.project / 'src' / 'long.py'
        long_file.write_text('\n'.join(f'line {number}' for number in range(1, 701)))

        results = [
            self.call(f'<ATTACH_FILE_CONTENT: {self.ref("src/long.py")} >')
            for _ in range(4)
        ]

        self.assertTrue(all(result['ok'] for result in results))
        self.assertEqual(
            [(result['requested_start'], result['requested_end']) for result in results],
            [(1, 200), (201, 400), (401, 600), (601, 800)],
        )
        self.assertEqual(results[-1]['loaded_end'], 700)
        prompt = self.prompt()
        for number in (1, 200, 201, 400, 401, 600, 601, 700):
            self.assertIn(f'{number}: line {number}', prompt)
        for label in ('long.py#1-200', 'long.py#201-400', 'long.py#401-600', 'long.py#601-700'):
            self.assertIn(f'<FILE_CONTENT: {label} >', prompt)

        exhausted = self.call(f'<ATTACH_FILE_CONTENT: {self.ref("src/long.py")} >')
        self.assertFalse(exhausted['ok'])
        self.assertEqual(exhausted['requested_start'], 701)
        self.assertIn('Start line exceeds file length: 700', exhausted['detail'])

        duplicate = self.call(f'<ATTACH_FILE_CONTENT: {self.ref("src/long.py")}#L201-L400 >')
        self.assertTrue(duplicate['ok'])
        self.assertEqual(self.prompt().count('<FILE_CONTENT: long.py#201-400 >'), 1)







    def test_legacy_read_and_attach_file_content_share_latest_projection(self):
        marker = '<ASSET_ACTION>' + json.dumps({'action':'project_read', 'attachment':self.record['id'], 'path':'src/main.py'}) + '</ASSET_ACTION>'
        self.call(marker)
        self.assertTrue(self.call(f'<ATTACH_FILE_CONTENT: {self.ref()}#L1-L200 >')['ok'])
        self.assertEqual(self.prompt().count('<FILE_CONTENT: main.py#1-4 >'), 1)

    def test_persistent_file_uses_same_body_projection_and_repeat_is_idempotent(self):
        record, _, _ = files.store_uploaded_file(name='upload.txt', content=b'UNIQUE UPLOAD BODY', pin=False)
        self.call(f'<ATTACH_FILE_CONTENT: {record["id"]} >')
        user = build_user_text_with_attachments({'text':'inspect', 'attachments':self.context.runtime_turn_attachments})
        self.assertNotIn('UNIQUE UPLOAD BODY', user)
        self.assertEqual((self.prompt() + user + build_followup_attachment_payload(self.context)).count('UNIQUE UPLOAD BODY'), 1)
        self.assertTrue(self.call(f'<ATTACH_FILE_CONTENT: {record["id"]} >')['ok'])
        self.assertEqual(build_tool_results_context(self.context).count('UNIQUE UPLOAD BODY'), 1)
        self.assertIsNotNone(files.get_file_record(record['id']))

    def test_upload_and_project_alias_of_same_bytes_can_both_load(self):
        record, _, _ = files.store_uploaded_file(name='copy.py', content=(self.project/'src/main.py').read_bytes(), pin=False)
        self.assertTrue(self.call(f'<ATTACH_FILE_CONTENT: {record["id"]} >')['ok'])
        self.assertTrue(self.call(f'<ATTACH_FILE_CONTENT: {self.ref()} >')['ok'])
        self.assertTrue(self.call(f'<ATTACH_FILE_CONTENT: {record["id"]} >')['ok'])

    def test_ui_unpin_drops_bodies_without_resurrection(self):
        apply_attachment_context_ids(self.context, [self.record['id']])
        self.call(f'<ATTACH_FILE_CONTENT: {self.ref()} >')
        apply_attachment_context_ids(self.context, [])
        self.assertNotIn('1: first', self.prompt())
        apply_attachment_context_ids(self.context, [self.record['id']])
        self.assertNotIn('1: first', self.prompt())
        self.assertTrue((self.project / 'src/main.py').is_file())

    def test_empty_binary_and_invalid_paths(self):
        (self.project/'empty.txt').write_text('')
        self.assertTrue(self.call(f'<ATTACH_FILE_CONTENT: {self.ref("empty.txt")} >')['ok'])
        self.assertTrue(self.call(f'<ATTACH_FILE_CONTENT: {self.ref("empty.txt")}#L1-L200 >')['ok'])
        (self.project/'binary.dat').write_bytes(b'hello\x00binary')
        for path in ('../outside', 'binary.dat', 'missing.txt'):
            self.assertFalse(self.call(f'<ATTACH_FILE_CONTENT: {self.ref(path)} >')['ok'])
        self.assertNotIn('project_read', '\n'.join(get_runtime_action_schema('ASSET_ACTION')))

    def test_snapshot_round_trip_keeps_live_body_beyond_history_tail_and_user_unpin(self):
        (self.project/'escapes.txt').write_text('\\' * 22000)
        self.call(f'<ATTACH_FILE_CONTENT: {self.ref("escapes.txt")} >')
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
        apply_attachment_context_ids(self.context, [])
        snapshot = json.loads(json.dumps(build_runtime_session_checkpoint(self.context)))
        self.context.runtime_tool_results = []
        apply_bootstrap_tool_results(self.context, snapshot)
        self.assertEqual(build_file_contents_context(self.context), '')
        apply_attachment_context_ids(self.context, [self.record['id']])
        self.assertTrue(self.call(f'<ATTACH_FILE_CONTENT: {self.ref("escapes.txt")}#L1-L200 >')['ok'])
        clear_runtime_tool_results(self.context)
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
        apply_attachment_context_ids(self.context, [])
        self.assertNotIn('old exact body', self.prompt())

    def test_explicit_empty_checkpoint_blocks_legacy_mirror_and_missing_keeps_state(self):
        self.call('<ASSET_ACTION>' + json.dumps({'action':'project_read', 'attachment':self.record['id'], 'path':'src/main.py'}) + '</ASSET_ACTION>')
        apply_bootstrap_tool_results(self.context, {})
        self.assertIn('1: first', build_file_contents_context(self.context))
        apply_bootstrap_tool_results(self.context, {'tool_results': []})
        self.assertEqual(build_file_contents_context(self.context), '')
        self.assertTrue(self.call(f'<ATTACH_FILE_CONTENT: {self.ref()} >')['ok'])

    def test_new_file_marker_chunk_boundaries_quotes_repetition_and_flush(self):
        for marker in (
            f'<ATTACH_FILE_CONTENT: {self.ref()}#L2-L3 >',
            '<ATTACH_FILE_CONTENT: src/main.py#L2-L3 >',
        ):
            for split in range(len(marker)+1):
                parser=RuntimeActionStreamFilter(enabled_actions=['ATTACH_FILE_CONTENT','ASSET_ACTION'])
                chunks=[parser.filter(marker[:split]),parser.filter(marker[split:]),parser.flush_result()]
                self.assertEqual(sum(len(c.actions) for c in chunks),1)
                self.assertEqual(''.join(c.text for c in chunks),'')
                parser=RuntimeActionStreamFilter(enabled_actions=['ATTACH_FILE_CONTENT','ASSET_ACTION'])
                chunks=[parser.filter('"'+marker[:split]),parser.filter(marker[split:]+'"'),parser.flush_result()]
                self.assertEqual(sum(len(c.actions) for c in chunks),0)
            self.assertEqual(len(extract_runtime_actions(marker+marker,enabled_actions=['ATTACH_FILE_CONTENT','ASSET_ACTION']).actions),1)
        parser=RuntimeActionStreamFilter(enabled_actions=['ATTACH_FILE_CONTENT','ASSET_ACTION'])
        parser.filter(f'<ATTACH_FILE_CONTENT: {self.ref()}')
        self.assertFalse(parser.flush_result().actions)
        self.assertFalse(extract_runtime_actions('<ATTACH_FILE_CONTENTISH: abc123>', enabled_actions=['ATTACH_FILE_CONTENT','ASSET_ACTION']).actions)

    def test_brain_batch_reread_followups_keep_reasoning_and_source_once(self):
        calls=[]
        async def stream(**kwargs):
            calls.append(kwargs)
            prompt=kwargs['system_prompt']
            index=len(calls)-1
            if index:
                self.assertIn('batch thought',prompt)
                self.assertNotIn('CURRENT_REQUEST_FLOW',prompt)
            if index==1:
                self.assertEqual(prompt.count('1: first'),1)
                markers=[f'<ATTACH_FILE_CONTENT: {self.ref()}#L1-L200 >']
            elif index==2:
                self.assertEqual(prompt.count('1: first'),1)
                return 'Done.','finished'
            else:
                markers=[f'<ATTACH_FILE_CONTENT: {self.ref()} >',f'<ATTACH_FILE_CONTENT: {self.ref("README.md")} >']
            actions=extract_runtime_actions(''.join(markers),enabled_actions=['ATTACH_FILE_CONTENT','ASSET_ACTION']).actions
            await apply_runtime_action_calls(self.context,actions,runtime_message_id=f'file-step-{index}')
            self.context.runtime_turn_reasoning_content += '\nbatch thought '+str(index)
            return '', 'batch thought '+str(index)
        state=AgentState(user_input='inspect project')
        runtime={'runtime_id':'brain-test','label':'brain','context_window':32768,'log_method':'log_brain','runtime_actions':BRAIN_RUNTIME_ACTIONS}
        self.context.clients={'brain':object()}
        with patch('agent.nodes.brain.get_brain_runtime_config',return_value=runtime),patch.object(BrainNode,'run_brain_stream',staticmethod(stream)):
            asyncio.run(BrainNode().run(state,self.context))
        self.assertEqual(len(calls),3)
        self.assertEqual(state.brain_response,'Done.')



def test_missing_project_file_reports_same_name_hint(tmp_path):
    from utils.project_reader import _inside

    (tmp_path / "agent" / "nodes").mkdir(parents=True)
    (tmp_path / "agent" / "nodes" / "brain.py").write_text("pass\n", encoding="utf-8")

    try:
        _inside(tmp_path, "agent/brain.py")
    except ValueError as error:
        message = str(error)
    else:
        raise AssertionError("missing path unexpectedly resolved")

    assert "Path not found inside linked folder: agent/brain.py" in message
    assert "Same-name file found at: agent/nodes/brain.py" in message
