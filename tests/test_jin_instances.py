import time
import unittest
import json
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

from utils.actions import RuntimeActionCall
from utils.actions.dispatcher import apply_runtime_action_calls

from utils.actions.jin_instance_actions import (
    CHILD_TOOL_RESULTS_INSTRUCTION,
    active_child,
    build_child_instruction,
    build_parent_return_instruction,
    interrupt_instance_group,
    parse_instance_assignments,
    recent_lt_fact_ids,
    mark_child_started,
)


class JinInstanceParsingTests(unittest.TestCase):
    def test_instance_markers_at_every_chunk_boundary(self):
        from utils.actions import RuntimeActionStreamFilter
        for name, payload in (
            ("CREATE_JIN_INSTANCES", '{"id":1,"conditions":"task"}'),
            ("FINISH_SUBTASK", '{"subtask_agent_id":"a","session_id":"s","original_conditions":"task","finish_reason":"done"}'),
        ):
            marker = f"<{name}>{payload}</{name}>"
            for cut in range(len(marker) + 1):
                with self.subTest(name=name, cut=cut):
                    parser = RuntimeActionStreamFilter(enabled_actions=[name])
                    results = [parser.filter("before " + marker[:cut]), parser.filter(marker[cut:] + " after"), parser.flush_result()]
                    self.assertEqual("".join(result.text for result in results).split(), ["before", "after"])
                    self.assertEqual([action.name for result in results for action in result.actions], [name])
                    self.assertEqual([action.payload for result in results for action in result.actions], [payload])

    def test_incomplete_and_literal_instance_markers_do_not_execute(self):
        from utils.actions import RuntimeActionStreamFilter
        for name in ("CREATE_JIN_INSTANCES", "FINISH_SUBTASK"):
            for text in (f'<{name}>{{', f'`<{name}>{{}}</{name}>`', f'<{name}_EXAMPLE>'):
                parser = RuntimeActionStreamFilter(enabled_actions=[name])
                results = [parser.filter(character) for character in text] + [parser.flush_result()]
                self.assertFalse(any(action.name == name for result in results for action in result.actions))

    def test_rejects_wrong_json_types(self):
        for item in ({"id": 1.0, "conditions": "task"},
                     {"id": True, "conditions": "task"},
                     {"id": 1, "conditions": ["task"]},
                     {"id": 1, "conditions": {"task": "value"}}):
            with self.subTest(item=item), self.assertRaises(ValueError):
                parse_instance_assignments(json.dumps(item))

    def test_parses_newline_delimited_assignments(self):
        assignments = parse_instance_assignments(
            '{"id":1,"conditions":"first"}\n'
            '{"id":2,"conditions":"second"}'
        )
        self.assertEqual(
            assignments,
            [
                {"ordinal": 1, "conditions": "first"},
                {"ordinal": 2, "conditions": "second"},
            ],
        )

    def test_rejects_non_consecutive_ids(self):
        with self.assertRaisesRegex(ValueError, "consecutive"):
            parse_instance_assignments(
                '{"id":1,"conditions":"first"}\n'
                '{"id":3,"conditions":"third"}'
            )

    def test_rejects_empty_conditions(self):
        with self.assertRaisesRegex(ValueError, "non-empty"):
            parse_instance_assignments('{"id":1,"conditions":""}')

    def test_enforces_configured_default_limit(self):
        payload = "\n".join(
            '{"id":%d,"conditions":"task %d"}' % (index, index)
            for index in range(1, 34)
        )
        with self.assertRaisesRegex(ValueError, "at most 32"):
            parse_instance_assignments(payload)


class JinInstanceContextTests(unittest.TestCase):
    def test_children_isolate_reasoning_and_dialogue_but_keep_shared_results(self):
        context = self.make_context()
        context.runtime_previous_reasoning_content = "parent plan"
        context.runtime_current_sequence_jin_messages = [{"text": "parent message"}]
        context.runtime_tool_results = [{"result": "shared evidence"}]
        mark_child_started(context)
        self.assertEqual(context.runtime_previous_reasoning_content, "")
        context.runtime_previous_reasoning_content = "child private plan"
        context.runtime_current_sequence_jin_messages.append({"text": "child draft"})
        context.runtime_tool_results.append({"result": "new evidence"})
        mark_child_started(context)
        self.assertEqual(context.runtime_previous_reasoning_content, "")
        self.assertEqual(context.runtime_current_sequence_jin_messages, [{"text": "parent message"}])
        interrupt_instance_group(context)
        self.assertEqual(context.runtime_previous_reasoning_content, "parent plan")
        self.assertEqual(len(context.runtime_tool_results), 2)

    def make_context(self):
        return SimpleNamespace(
            runtime_jin_instance_group={
                "group_id": "g1",
                "phase": "child_pending",
                "active_index": 1,
                "parent_user_message": "create ten files",
                "tasks": [
                    {
                        "ordinal": 1,
                        "conditions": "create file one",
                        "subtask_agent_id": "sub_jin_1",
                        "session_id": "session_1",
                        "status": "completed",
                        "finish_reason": "created file one",
                    },
                    {
                        "ordinal": 2,
                        "conditions": "create file two",
                        "subtask_agent_id": "sub_jin_2",
                        "session_id": "session_2",
                        "status": "pending",
                        "finish_reason": "",
                    },
                ],
            },
        )

    def test_child_instruction_contains_parent_task_ids_and_cleanup_rule(self):
        context = self.make_context()
        instruction = build_child_instruction(context)
        self.assertIn("create ten files", instruction)
        self.assertIn("create file two", instruction)
        self.assertIn("sub_jin_2", instruction)
        self.assertIn("created file one", instruction)
        self.assertIn(CHILD_TOOL_RESULTS_INSTRUCTION, instruction)
        self.assertIn("You may create nested JIN instances", instruction)

    def test_parent_report_is_ordered(self):
        report = build_parent_return_instruction(self.make_context())
        self.assertLess(report.index("JIN #1"), report.index("JIN #2"))
        self.assertIn("status=completed", report)

    def test_stop_interrupts_active_and_cancels_pending(self):
        context = self.make_context()
        context.runtime_jin_instance_group["phase"] = "child_running"
        context.runtime_jin_instance_group["tasks"][1]["status"] = "running"
        interrupt_instance_group(context, "stopped_by_user")
        self.assertEqual(context.runtime_jin_instance_group["phase"], "interrupted")
        self.assertEqual(context.runtime_jin_instance_group["tasks"][1]["status"], "interrupted")
        self.assertIsNone(active_child(context))

    def test_child_lt_projection_keeps_only_created_or_updated_within_day(self):
        now = time.time()
        context = SimpleNamespace(runtime_long_term_memory_store={
            "version": 1,
            "revision": 3,
            "facts": [
                {"id": "F1", "created_at": now - 60, "updated_at": now - 60},
                {"id": "F2", "created_at": now - 100000, "updated_at": now - 60},
                {"id": "F3", "created_at": now - 100000, "updated_at": now - 90000},
                {"id": "F4", "created_at": now - 100000, "updated_at": now - 100000, "last_mentioned_at": now},
            ],
            "pending_facts": [{"id": "PF1"}],
        })
        original = context.runtime_long_term_memory_store
        self.assertEqual(recent_lt_fact_ids(context, now=now), ["F1", "F2"])
        self.assertIs(context.runtime_long_term_memory_store, original)


class JinInstanceActionFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_finish_sequence_uses_authoritative_conditions(self):
        emitted = []

        class Emitter:
            async def emit(self, payload):
                emitted.append(payload)

        context = SimpleNamespace(
            emitter=Emitter(),
            runtime_action_events=[],
            runtime_search_calls=[],
            runtime_deep_research_calls=[],
            runtime_loaded_skills=[],
            runtime_current_turn_id="turn_1",
            runtime_current_sequence_turn_id="turn_1",
            runtime_turn_user_message="make two files",
            runtime_active_action_markers=[],
            runtime_session_action_history=[],
            runtime_tool_results=[],
            runtime_tool_result_created_ats=[],
            runtime_tool_result_sequence=0,
            runtime_tool_results_turn_count=0,
            runtime_jin_instance_group={},
            runtime_persistent_writes_restricted=True,
        )
        await apply_runtime_action_calls(
            context,
            (RuntimeActionCall(
                name="CREATE_JIN_INSTANCES",
                payload=(
                    '{"id":1,"conditions":"make one"}\n'
                    '{"id":2,"conditions":"make two"}'
                ),
            ),),
        )
        group = context.runtime_jin_instance_group
        self.assertEqual(group["phase"], "child_pending")
        self.assertEqual(len(group["tasks"]), 2)

        from utils.actions.jin_instance_actions import mark_child_started

        mark_child_started(context)
        first = group["tasks"][0]
        await apply_runtime_action_calls(
            context,
            (RuntimeActionCall(
                name="FINISH_SUBTASK",
                payload=(
                    '{"subtask_agent_id":"%s","session_id":"%s",'
                    '"original_conditions":"wrong","finish_reason":"done"}'
                    % (first["subtask_agent_id"], first["session_id"])
                ),
            ),),
        )
        self.assertEqual(first["status"], "completed")
        self.assertEqual(group["phase"], "child_pending")
        finish_result = context.runtime_tool_results[-1]["result"]
        self.assertEqual(finish_result["original_conditions"], "make one")
        self.assertTrue(any(
            item.get("action") == "finish_subtask" and item.get("status") == "completed"
            for item in emitted
        ))
        # The same finish must validate the live owner, never reuse success.
        await apply_runtime_action_calls(context, (RuntimeActionCall(
            name="FINISH_SUBTASK",
            payload=json.dumps({
                "subtask_agent_id": first["subtask_agent_id"], "session_id": first["session_id"],
                "original_conditions": "wrong", "finish_reason": "done",
            }),
        ),))
        self.assertFalse(context.runtime_tool_results[-1]["result"]["ok"])
        self.assertEqual(group["tasks"][1]["status"], "pending")


class JinInstanceBrainFlowTests(unittest.IsolatedAsyncioTestCase):
    async def run_sequence(self, *, limit=8, stop=False, malformed=False, second_group=False, recovery=False, scratchpad=False):
        from agent.nodes.brain import BrainNode
        from agent.state import AgentState
        from tests.helpers.brain import brain_context_stub, brain_runtime_config
        from utils.tool_results import record_runtime_tool_result, TOOL_RESULT_KIND_ASSET

        context = brain_context_stub()
        context.logger = SimpleNamespace(log_runtime=AsyncMock())
        context.websocket = SimpleNamespace(send_json=AsyncMock())
        context.emitter = SimpleNamespace(emit=AsyncMock())
        context.runtime_turn_user_message = "original intention"
        context.runtime_persistent_writes_restricted = True
        context.runtime_lt_file_store_enabled = False
        context.runtime_current_turn_id = "instance-test"
        context.runtime_current_sequence_turn_id = "instance-test"
        context.runtime_memory = "fixed FRAME"
        context.runtime_tool_results = []
        context.runtime_current_sequence_jin_messages = []
        now = time.time()
        recent_time = datetime.fromtimestamp(now, timezone.utc).isoformat()
        old_time = datetime.fromtimestamp(now-200000, timezone.utc).isoformat()
        context.runtime_long_term_memory_store = {"facts": [
            {"id": "F1", "key": "recent", "value": "RECENT_FACT_SENTINEL", "created_at": recent_time, "updated_at": recent_time},
            {"id": "F2", "key": "old", "value": "OLD_FACT_SENTINEL", "created_at": old_time, "updated_at": old_time},
        ]}
        state = AgentState(user_input="original intention")
        calls = []
        child_calls = {}
        groups = []

        async def action(name, payload):
            await apply_runtime_action_calls(context, (RuntimeActionCall(name=name, payload=json.dumps(payload)),))

        async def create():
            await action("CREATE_JIN_INSTANCES", [{"id": 1, "conditions": "FIRST_ASSIGNMENT"}, {"id": 2, "conditions": "SECOND_ASSIGNMENT"}])
            groups.append(context.runtime_jin_instance_group)

        async def stream(**kwargs):
            calls.append(kwargs)
            self.assertLess(len(calls), 20)
            if len(calls) == 1:
                context.runtime_previous_reasoning_content = "PARENT_REASONING_SENTINEL"
                await create()
                return "", "parent"
            prompt = kwargs["system_prompt"]
            child = active_child(context)
            if child is not None:
                self.assertEqual(prompt.count("<JIN_SUBTASK_INSTANCE>"), 1)
                self.assertIn(child["conditions"], prompt)
                self.assertIn(child["session_id"], prompt)
                self.assertIn("RECENT_FACT_SENTINEL", prompt)
                self.assertNotIn("OLD_FACT_SENTINEL", prompt)
                self.assertNotIn("PARENT_REASONING_SENTINEL", prompt)
                self.assertTrue(kwargs["runtime_actions"]["CAN_CREATE_JIN_INSTANCES"])
                count = child_calls.get(child["subtask_agent_id"], 0) + 1
                child_calls[child["subtask_agent_id"]] = count
                if scratchpad:
                    scratch = "SCRATCH_" + child["subtask_agent_id"]
                    if count == 1:
                        self.assertNotIn("SCRATCH_", prompt)
                        await action("SAVE_ACTIVE_MEMORY", {"conditions": scratch})
                    else:
                        self.assertIn(scratch, prompt)
                if count == 1:
                    self.assertNotIn("CHILD_PRIVATE_SENTINEL", prompt)
                elif not malformed:
                    self.assertNotIn("<JIN_SUBTASK_NOT_FINISHED>", prompt)
                context.runtime_previous_reasoning_content = "CHILD_PRIVATE_SENTINEL"
                if stop:
                    context.runtime_turn_abort_requested = True
                    interrupt_instance_group(context, "stopped_by_user")
                    return "", "stopped"
                if malformed:
                    context.runtime_failure_followup_entries = [{"result": {"action": "malformed_action"}}]
                    return "", "bad syntax"
                if count == 1:
                    if recovery:
                        context.runtime_context_limit_recovery_pending = True
                        context.runtime_context_limit_kind = "output"
                        context.runtime_context_limit_stage = "reasoning"
                    else:
                        record_runtime_tool_result(context, TOOL_RESULT_KIND_ASSET, {"action": "list_skills", "ok": True})
                    return "", "child action"
                await action("FINISH_SUBTASK", {
                    "subtask_agent_id": child["subtask_agent_id"], "session_id": child["session_id"],
                    "original_conditions": "ignored", "finish_reason": "done " + child["conditions"],
                })
                return "", "child finish"
            self.assertIn("<JIN_INSTANCES_RETURN_TO_PARENT>", prompt)
            self.assertIn("OLD_FACT_SENTINEL", prompt)
            self.assertIn("PARENT_REASONING_SENTINEL", prompt)
            self.assertNotIn("CHILD_PRIVATE_SENTINEL", prompt)
            self.assertNotIn("<JIN_SUBTASK_INSTANCE>", prompt)
            if second_group and len(groups) == 1:
                await create()
                return "", "parent new group"
            return "parent final", "parent final reasoning"

        runtime = brain_runtime_config()
        runtime["runtime_actions"].update(CAN_CREATE_JIN_INSTANCES=True, CAN_FINISH_SUBTASK=True, CAN_CLEAN_TOOL_RESULTS=True)
        with patch("agent.nodes.brain.get_brain_runtime_config", return_value=runtime), patch(
            "agent.nodes.brain.build_brain_payload", return_value="payload"
        ), patch("agent.nodes.brain.emit_active_memory_records_update_if_dirty", new=AsyncMock()), patch(
            "agent.nodes.brain.config.BRAIN_MAX_FOLLOWUPS", limit
        ), patch.object(BrainNode, "run_brain_stream", side_effect=stream):
            await BrainNode().run(state, context)
        self.assertEqual(context.runtime_memory, "fixed FRAME")
        return context, state, calls, groups

    async def test_silent_child_stops_immediately_without_retry(self):
        """Parent -> silent child -> final parent; never retry the child."""
        from agent.nodes.brain import BrainNode
        from agent.state import AgentState
        from tests.helpers.brain import brain_context_stub, brain_runtime_config

        context = brain_context_stub()
        context.logger = SimpleNamespace(log_runtime=AsyncMock())
        context.websocket = SimpleNamespace(send_json=AsyncMock())
        context.emitter = SimpleNamespace(emit=AsyncMock())
        context.runtime_turn_user_message = "Caption the first picture via a subagent"
        context.runtime_persistent_writes_restricted = True
        context.runtime_lt_file_store_enabled = False
        context.runtime_current_turn_id = "child-idle-test"
        context.runtime_current_sequence_turn_id = "child-idle-test"
        context.runtime_tool_results = []
        context.runtime_current_sequence_jin_messages = []
        state = AgentState(user_input=context.runtime_turn_user_message)
        calls = []

        async def stream(**kwargs):
            calls.append(kwargs)
            self.assertLessEqual(len(calls), 3, "A silent child must never be re-prompted")
            if len(calls) == 1:
                await apply_runtime_action_calls(context, (
                    RuntimeActionCall(name="CREATE_JIN_INSTANCES", payload='{"id":1,"conditions":"caption first image"}'),
                ))
                return "", "parent reasoning"
            if len(calls) == 2:
                self.assertIsNotNone(active_child(context))
                self.assertIn("<JIN_SUBTASK_INSTANCE>", kwargs["system_prompt"])
                self.assertTrue(kwargs["runtime_actions"]["CAN_FINISH_SUBTASK"])
                return "I am scanning the folder, please wait.", "no actions"
            self.assertIsNone(active_child(context))
            self.assertIn("<JIN_INSTANCES_RETURN_TO_PARENT>", kwargs["system_prompt"])
            self.assertIn("<JIN_SUBTASK_STALLED>", kwargs["system_prompt"])
            self.assertNotIn("<JIN_SUBTASK_NOT_FINISHED>", kwargs["system_prompt"])
            self.assertFalse(any(kwargs["runtime_actions"].values()))
            return "Child did not do the work.", "parent conclusion"

        runtime = brain_runtime_config()
        runtime["runtime_actions"].update(CAN_CREATE_JIN_INSTANCES=True, CAN_FINISH_SUBTASK=True)
        with patch("agent.nodes.brain.get_brain_runtime_config", return_value=runtime), patch(
            "agent.nodes.brain.build_brain_payload", return_value="payload"
        ), patch("agent.nodes.brain.emit_active_memory_records_update_if_dirty", new=AsyncMock()), patch(
            "agent.nodes.brain.config.BRAIN_MAX_FOLLOWUPS", 0
        ), patch.object(BrainNode, "run_brain_stream", side_effect=stream):
            await BrainNode().run(state, context)

        self.assertEqual(len(calls), 3)
        self.assertEqual(context.runtime_jin_instance_group["phase"], "interrupted")
        self.assertEqual(context.runtime_jin_instance_group["tasks"][0]["finish_reason"], "no_progress")
        self.assertEqual(state.brain_response, "Child did not do the work.")
        context.websocket.send_json.assert_awaited_once()
        self.assertEqual(context.websocket.send_json.await_args.args[0]["action"], "subtask_stalled")

    async def test_children_keep_assignment_and_lt_on_action_followup_then_restore_parent(self):
        context, state, calls, groups = await self.run_sequence()
        self.assertEqual(state.brain_response, "parent final")
        self.assertEqual(groups[0]["phase"], "completed")
        self.assertEqual([task["status"] for task in groups[0]["tasks"]], ["completed", "completed"])
        self.assertEqual(len(calls), 6)

    async def test_scratchpad_survives_recovery_then_disappears_for_next_child_and_parent(self):
        context, state, calls, groups = await self.run_sequence(recovery=True, scratchpad=True)
        self.assertEqual(context.active_memory_records, [])
        self.assertNotIn("SCRATCH_", calls[-1]["system_prompt"])
        self.assertEqual(state.brain_response, "parent final")

    async def test_followup_cap_interrupts_group_and_final_tick_is_parent(self):
        context, state, calls, groups = await self.run_sequence(limit=1)
        self.assertEqual(groups[0]["phase"], "interrupted")
        self.assertEqual([task["status"] for task in groups[0]["tasks"]], ["interrupted", "cancelled"])
        self.assertFalse(any(calls[-1]["runtime_actions"].values()))
        self.assertEqual(state.brain_response, "parent final")

    async def test_stop_restores_parent_without_another_model_call(self):
        context, state, calls, groups = await self.run_sequence(limit=1, stop=True)
        self.assertEqual(len(calls), 2)
        self.assertEqual(groups[0]["phase"], "interrupted")
        self.assertEqual(context.runtime_previous_reasoning_content, "PARENT_REASONING_SENTINEL")

    async def test_repeated_malformed_child_returns_to_parent(self):
        context, state, calls, groups = await self.run_sequence(malformed=True)
        self.assertEqual(groups[0]["phase"], "interrupted")
        self.assertEqual(groups[0]["tasks"][0]["finish_reason"], "malformed_repair_limit")
        self.assertEqual(state.brain_response, "parent final")

    async def test_parent_can_start_a_second_group(self):
        context, state, calls, groups = await self.run_sequence(second_group=True)
        self.assertEqual(len(groups), 2)
        self.assertTrue(all(group["phase"] == "completed" for group in groups))

    async def test_recovery_ticks_keep_child_assignment_and_lt_filter(self):
        context, state, calls, groups = await self.run_sequence(recovery=True)
        self.assertEqual(state.brain_response, "parent final")
        self.assertEqual(groups[0]["phase"], "completed")

    async def test_stop_waits_for_stream_finally_before_restoring_parent(self):
        from websocket.tasks import cancel_current_task
        context = JinInstanceContextTests().make_context()
        context.runtime_previous_reasoning_content = "parent plan"
        context.active_streams = {}
        mark_child_started(context)
        entered = asyncio.Event()

        async def stream():
            try:
                entered.set()
                await asyncio.Event().wait()
            finally:
                context.runtime_previous_reasoning_content += "child tail"

        task = asyncio.create_task(stream())
        await entered.wait()
        with patch("websocket.tasks.abort_active_runtime_actions", new=AsyncMock()):
            await cancel_current_task(task, SimpleNamespace(log_runtime=AsyncMock()), context, update_memory=False)
        self.assertEqual(context.runtime_previous_reasoning_content, "parent plan")
        self.assertEqual(context.runtime_jin_instance_group["phase"], "interrupted")


if __name__ == "__main__":
    unittest.main()

class EphemeralSubtaskMemoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.app_state = SimpleNamespace(websocket_runtime_contexts={})
        self.context = self.make_context('parent')

    def make_context(self, name, anonymous=False):
        context = SimpleNamespace(
            memory_profile_enabled=True, memory_profile_root=self.root,
            runtime_anonymous_mode=anonymous, session_id=name,
            websocket=SimpleNamespace(app=SimpleNamespace(state=self.app_state), send_json=AsyncMock()),
            emitter=SimpleNamespace(emit=AsyncMock()), logger=SimpleNamespace(log_runtime=AsyncMock()),
            runtime_transport=SimpleNamespace(stopping=False, publish=lambda event: None),
            active_memory_records=[], runtime_memory='', runtime_memory_stable='',
            runtime_jin_instance_group={}, runtime_tool_results=[], runtime_action_events=[],
            runtime_persistent_writes_restricted=True, runtime_current_turn_id=name,
            runtime_turn_user_message='test',
        )
        self.app_state.websocket_runtime_contexts[name] = context
        return context

    async def action(self, name, payload, context=None):
        await apply_runtime_action_calls(context or self.context, (
            RuntimeActionCall(name=name, payload=payload if isinstance(payload, str) else json.dumps(payload)),
        ))

    async def start(self, context=None):
        context = context or self.context
        await self.action('CREATE_JIN_INSTANCES', [
            {'id': 1, 'conditions': 'first'}, {'id': 2, 'conditions': 'second'},
        ], context)
        mark_child_started(context)
        return active_child(context)

    async def finish(self, context=None):
        context = context or self.context
        child = active_child(context)
        await self.action('FINISH_SUBTASK', {
            'subtask_agent_id': child['subtask_agent_id'], 'session_id': child['session_id'],
            'finish_reason': 'useful final signal',
        }, context)

    async def test_lifecycle_disk_followups_and_parent_return(self):
        from runtime.memory_profile import refresh_profile
        from utils.active_memory_file_store import record_payload
        from utils.tool_results import record_runtime_tool_result
        from utils.actions.jin_instance_actions import restore_parent_reasoning
        c = self.context
        await self.action('SAVE_ACTIVE_MEMORY', {'conditions': 'same text'})
        parent = c.active_memory_records[0]
        child = await self.start()
        await self.action('SAVE_ACTIVE_MEMORY', {'conditions': 'same text', 'a': '1', 'b': '2', 'c': '3',
                                                'owner_subtask_agent_id': 'spoof'})
        await self.action('SAVE_ACTIVE_MEMORY', {'conditions': 'second note'})
        self.assertEqual(len(c.active_memory_records), 3)
        own = record_payload(c.active_memory_records[1])
        self.assertTrue(own['id'].startswith('SUB-AM-'))
        self.assertEqual(own['owner_subtask_agent_id'], child['subtask_agent_id'])
        self.assertEqual(own['subtask_memory_label'], 'sub1_active_memory_1')
        self.assertEqual([own[key] for key in ['a', 'b', 'c']], ['1', '2', '3'])
        await self.action('SAVE_ACTIVE_MEMORY', {'id': own['id'], 'conditions': 'updated note'})
        refresh_profile(c)
        self.assertEqual(record_payload(c.active_memory_records[1])['owner_subtask_agent_id'], child['subtask_agent_id'])
        self.assertIn('updated note', c.active_memory_records[1])
        c.runtime_memory = c.runtime_memory_stable = '\n'.join(c.active_memory_records)
        record_runtime_tool_result(c, 'asset', {'ok': True, 'content': 'keep evidence'})
        await self.finish()
        self.assertEqual(c.active_memory_records, [parent])
        self.assertNotIn('SUB-AM-', c.runtime_memory)
        self.assertNotIn('SUB-AM-', c.runtime_memory_stable)
        self.assertEqual(len(list((self.root / 'active').glob('*.json'))), 1)
        self.assertFalse(any(entry.get('owner_subtask_agent_id') for entry in c.runtime_tool_results))
        self.assertFalse(any(entry['kind'] == 'asset' for entry in c.runtime_tool_results))
        self.assertTrue(any(call.args[0].get('type') == 'active_memory_records_update'
                            for call in c.emitter.emit.call_args_list))
        mark_child_started(c)
        self.assertEqual(c.active_memory_records, [parent])
        await self.action('SAVE_ACTIVE_MEMORY', {'conditions': 'child two'})
        self.assertEqual(record_payload(c.active_memory_records[-1])['subtask_memory_label'], 'sub2_active_memory_1')
        await self.finish()
        restore_parent_reasoning(c)
        await self.action('SAVE_ACTIVE_MEMORY', {'conditions': 'parent again'})
        self.assertTrue(record_payload(c.active_memory_records[-1])['id'].startswith('AM-'))
        refresh_profile(c)
        self.assertEqual(len(c.active_memory_records), 2)

    async def test_finish_cleans_sub_tool_results_and_resets_next_child_ids(self):
        from utils.tool_results import record_runtime_tool_result
        c = self.context
        await self.start()
        first = active_child(c)["subtask_agent_id"]
        record_runtime_tool_result(c, 'files', {'ok': True, 'source': 'child_one'})
        record_runtime_tool_result(c, 'search', 'private result')
        self.assertEqual([e['tool_id'] for e in c.runtime_tool_results[-2:]], ['SUB_T1', 'SUB_T2'])
        self.assertTrue(all(e['owner_subtask_agent_id'] == first for e in c.runtime_tool_results[-2:]))
        parent_sequence = c.runtime_tool_result_sequence
        await self.finish()
        self.assertFalse(any(e.get('owner_subtask_agent_id') for e in c.runtime_tool_results))
        self.assertFalse(any(e['tool_id'].startswith('SUB_') for e in c.runtime_tool_results))
        self.assertEqual(c.runtime_tool_result_sequence, parent_sequence + 1)
        self.assertEqual(c.runtime_tool_results[-1]['result']['action'], 'finish_subtask')
        mark_child_started(c)
        record_runtime_tool_result(c, 'asset', {'ok': True, 'source': 'child_two'})
        self.assertEqual(c.runtime_tool_results[-1]['tool_id'], 'SUB_T1')
        await self.finish()
        self.assertFalse(any(e['tool_id'].startswith('SUB_') for e in c.runtime_tool_results))

    async def test_shared_writes_denied_and_own_delete_allowed(self):
        from utils.active_memory_file_store import record_payload
        c = self.context
        await self.action('SAVE_ACTIVE_MEMORY', {'conditions': 'protected'})
        parent = c.active_memory_records[0]
        parent_id = record_payload(parent)['id']
        await self.start()
        for name, payload in [
            ('SAVE_ACTIVE_MEMORY', {'id': parent_id, 'conditions': 'wrong'}),
            ('DELETE_ACTIVE_MEMORY', parent_id),
            ('UPDATE_LT_FACTS', 'change main facts'),
            ('SAVE_DELAYED_MEMORY', {'title': 'wrong', 'body': 'wrong'}),
        ]:
            await self.action(name, payload)
            self.assertFalse(c.runtime_tool_results[-1]['result']['ok'])
            self.assertEqual(c.active_memory_records, [parent])
        await self.action('SAVE_ACTIVE_MEMORY', {'conditions': 'own'})
        identity = record_payload(c.active_memory_records[-1])['id']
        await self.action('SAVE_ACTIVE_MEMORY', {'id': identity, 'owner_subtask_agent_id': 'spoof'})
        self.assertFalse(c.runtime_tool_results[-1]['result']['ok'])
        await self.action('DELETE_ACTIVE_MEMORY', identity)
        self.assertEqual(c.active_memory_records, [parent])
        await self.finish()
        self.assertFalse(any(e.get('owner_subtask_agent_id') for e in c.runtime_tool_results))

    async def test_invalid_finish_and_failed_cleanup_keep_child_running(self):
        c = self.context
        child = await self.start()
        await self.action('SAVE_ACTIVE_MEMORY', {'conditions': 'must survive failure'})
        before = c.active_memory_records[:]
        await self.action('FINISH_SUBTASK', {'subtask_agent_id': 'wrong', 'finish_reason': 'done'})
        self.assertEqual(c.active_memory_records, before)
        with patch('utils.active_memory_file_store.persist_active_records', side_effect=OSError('disk denied')):
            await self.finish()
        self.assertEqual(c.active_memory_records, before)
        self.assertEqual(child['status'], 'running')
        self.assertEqual(c.runtime_tool_results[-1]['result']['error'], 'subtask_memory_cleanup_failed')
        await self.finish()
        self.assertEqual(c.active_memory_records, [])

    async def test_source_order_finish_blocks_late_actions_across_batches(self):
        c = self.context
        child = await self.start()
        await apply_runtime_action_calls(c, (
            RuntimeActionCall(name='SAVE_ACTIVE_MEMORY', payload='{"conditions":"temporary"}'),
            RuntimeActionCall(name='FINISH_SUBTASK', payload=json.dumps({
                'subtask_agent_id': child['subtask_agent_id'], 'session_id': child['session_id'], 'finish_reason': 'done'})),
            RuntimeActionCall(name='SAVE_ACTIVE_MEMORY', payload='{"conditions":"orphan"}'),
        ))
        await self.action('SAVE_ACTIVE_MEMORY', {'conditions': 'another late chunk'})
        self.assertEqual(c.active_memory_records, [])
        self.assertFalse(list((self.root / 'active').glob('*.json')))

    async def test_post_finish_rejections_redact_payload_without_losing_followup(self):
        from runtime.frame_memory_utils import build_runtime_session_checkpoint
        from utils.context.tool_results import build_tool_results_context
        c = self.context
        child = await self.start()
        secret = 'REJECTED_CHILD_PRIVATE_SENTINEL'
        await apply_runtime_action_calls(c, (
            RuntimeActionCall(name='SAVE_ACTIVE_MEMORY', payload='{"conditions":"early scratchpad"}'),
            RuntimeActionCall(name='FINISH_SUBTASK', payload=json.dumps({
                'subtask_agent_id': child['subtask_agent_id'],
                'session_id': child['session_id'], 'finish_reason': 'done',
            })),
            RuntimeActionCall(name='SAVE_ACTIVE_MEMORY', payload=json.dumps({'conditions': secret})),
        ))
        self.assertEqual(c.active_memory_records, [])
        denied = [entry for entry in c.runtime_tool_results if
                  entry['kind'] == 'runtime_action' and
                  entry['result'].get('error') == 'subtask_memory_read_only']
        self.assertEqual(len(denied), 1)
        self.assertNotIn('payload', denied[0]['result'])
        self.assertIn('transitioned', denied[0]['result']['detail'])
        self.assertTrue(c.runtime_followup_action_failure_pending)
        self.assertTrue(c.runtime_action_failure_followup_messages)
        for stored in (c.runtime_tool_results, c.runtime_failure_followup_entries,
                       c.runtime_action_events, build_runtime_session_checkpoint(c),
                       build_tool_results_context(c)):
            self.assertNotIn(secret, json.dumps(stored))
        # A late action arriving in a different dispatch batch is equally isolated.
        await self.action('SAVE_ACTIVE_MEMORY', {'conditions': 'ANOTHER_LATE_CHILD_SENTINEL'})
        self.assertNotIn('ANOTHER_LATE_CHILD_SENTINEL', json.dumps(c.runtime_tool_results))
        self.assertNotIn('ANOTHER_LATE_CHILD_SENTINEL', json.dumps(c.runtime_action_events))

    async def test_stop_and_restart_preserve_other_live_owner(self):
        from runtime.memory_profile import refresh_profile
        from utils.subtask_memory import owner
        c = self.context
        other = self.make_context('other')
        first = await self.start(c)
        await self.action('SAVE_ACTIVE_MEMORY', {'conditions': 'first'}, c)
        second = await self.start(other)
        await self.action('SAVE_ACTIVE_MEMORY', {'conditions': 'other live'}, other)
        interrupt_instance_group(c)
        refresh_profile(c)
        self.assertEqual({owner(row) for row in c.active_memory_records}, {second['subtask_agent_id']})
        # Reconnecting context must not reap another live context's memory.
        replacement = self.make_context('replacement')
        refresh_profile(replacement)
        self.assertEqual(len(replacement.active_memory_records), 1)
        # A server restart has no live in-process group to reclaim it.
        self.app_state.websocket_runtime_contexts = {'replacement': replacement}
        refresh_profile(replacement)
        self.assertEqual(replacement.active_memory_records, [])
        self.assertFalse(list((self.root / 'active').glob('*.json')))

    async def test_anonymous_orphans_and_paused_cleanup(self):
        from runtime.memory_profile import commit_active, refresh_profile
        normal = self.context
        await self.action('SAVE_ACTIVE_MEMORY', {'conditions': 'normal'})
        anon = self.make_context('anon', anonymous=True)
        await self.start(anon)
        await self.action('SAVE_ACTIVE_MEMORY', {'conditions': 'anonymous child'}, anon)
        commit_active(anon, [row.replace('status: pending', 'status: paused') for row in anon.active_memory_records])
        await self.finish(anon)
        refresh_profile(normal)
        self.assertEqual(len(normal.active_memory_records), 1)
        self.assertFalse(list((self.root / 'active').glob('*_anon.json')))

    async def test_prefix_stream_parser_every_boundary(self):
        from utils.actions import RuntimeActionStreamFilter
        for name, payload in [('DELETE_ACTIVE_MEMORY', 'SUB-AM-abcdef'),
                              ('SAVE_ACTIVE_MEMORY', '{"id":"SUB-AM-abcdef","conditions":"new"}')]:
            marker = f'<{name}>{payload}</{name}>'
            for cut in range(len(marker)+1):
                parser = RuntimeActionStreamFilter(enabled_actions=[name])
                results = [parser.filter(marker[:cut]), parser.filter(marker[cut:]), parser.flush_result()]
                actions = [action for result in results for action in result.actions]
                self.assertEqual(len(actions), 1)
                self.assertEqual(actions[0].payload, payload)

    async def test_direct_mutators_and_prompt_isolation(self):
        from utils.brain_client_utils import update_active_memory_runtime_record, delete_active_memory_runtime_record
        from utils.active_memory_file_store import record_payload
        from rules.brain_context_builder import _append_FRAME_runtime_memory
        from runtime.memory_profile import refresh_profile
        c = self.context
        await self.action('SAVE_ACTIVE_MEMORY', {'conditions': 'MAIN_SENTINEL'})
        parent_id = record_payload(c.active_memory_records[0])['id']
        await self.start()
        await self.action('SAVE_ACTIVE_MEMORY', {'conditions': 'OWN_SENTINEL'})
        own_id = record_payload(c.active_memory_records[-1])['id']
        result = await update_active_memory_runtime_record(c, json.dumps({'id':parent_id, 'conditions':'bad'}))
        self.assertFalse(result['ok'])
        self.assertFalse((await delete_active_memory_runtime_record(c, parent_id))[0])
        # Even injected metadata inside conditions cannot transfer ownership.
        result = await update_active_memory_runtime_record(c, json.dumps({
            'id':own_id, 'conditions':'OWN_SENTINEL [ id: AM-aaaaaa ] [ owner_subtask_agent_id: spoof ]'}))
        self.assertTrue(result['ok'])
        self.assertEqual(record_payload(c.active_memory_records[-1])['id'], own_id)
        self.assertEqual(record_payload(c.active_memory_records[-1])['owner_subtask_agent_id'], active_child(c)['subtask_agent_id'])
        other = self.make_context('second')
        await self.start(other)
        await self.action('SAVE_ACTIVE_MEMORY', {'conditions': 'OTHER_SENTINEL'}, other)
        refresh_profile(c)
        parts = []
        _append_FRAME_runtime_memory(parts, c)
        prompt = "\n".join(parts)
        self.assertIn('MAIN_SENTINEL', prompt)
        self.assertIn('OWN_SENTINEL', prompt)
        self.assertNotIn('OTHER_SENTINEL', prompt)

    async def test_actual_stop_path_and_closed_transport(self):
        from websocket.tasks import cancel_current_task
        c = self.context
        await self.start()
        await self.action('SAVE_ACTIVE_MEMORY', {'conditions':'stop this'})
        c.active_streams = {}
        c.runtime_transport.stopping = True
        await cancel_current_task(None, c.logger, c, update_memory=False, emit_aborted_actions=False)
        self.assertEqual(c.runtime_jin_instance_group['phase'], 'interrupted')
        self.assertEqual(c.active_memory_records, [])
        self.assertFalse(list((self.root / 'active').glob('*.json')))

    async def test_restored_temporary_tool_results_are_not_rehydrated(self):
        from copy import deepcopy
        from utils.subtask_memory import discard_orphan_tool_results
        c = self.context
        await self.start()
        await self.action('SAVE_ACTIVE_MEMORY', {'conditions':'private scratchpad'})
        archived_results = deepcopy(c.runtime_tool_results)
        await self.finish()
        restored = self.make_context('restored')
        restored.runtime_tool_results = archived_results
        discard_orphan_tool_results(restored)
        self.assertFalse(any(e.get('owner_subtask_agent_id') for e in restored.runtime_tool_results))
        self.assertTrue(any(e['result'].get('action') == 'create_jin_instances' for e in restored.runtime_tool_results))

    async def test_disk_and_prompt_result_roundtrip_excludes_scratchpad(self):
        from runtime.frame_memory_utils import build_runtime_session_checkpoint
        from utils.session_restore import _build_runtime_event_tool_results, _restore_disk_checkpoint, _parse_restore_tool_results
        from websocket.bootstrap import apply_bootstrap_tool_results
        from utils.context.tool_results import build_tool_results_context
        from utils.tool_results import record_runtime_tool_result
        c = self.context
        await self.action('SAVE_ACTIVE_MEMORY', {'conditions':'KEEP_SENTINEL'})
        await self.start()
        await self.action('SAVE_ACTIVE_MEMORY', {'conditions':'SCRATCHPAD_SENTINEL'})
        prompt = build_tool_results_context(c)
        self.assertIn('SCRATCHPAD_SENTINEL', prompt)
        self.assertIn('owner_subtask_agent_id=', prompt)
        restored_prompt = _parse_restore_tool_results(prompt, time.time())
        self.assertNotIn('SCRATCHPAD_SENTINEL', json.dumps(restored_prompt))
        self.assertIn('KEEP_SENTINEL', json.dumps(restored_prompt))
        events = json.loads(json.dumps([{'event':'runtime_tool_result','payload':entry} for entry in c.runtime_tool_results]))
        restored_events = _build_runtime_event_tool_results(events)
        self.assertNotIn('SCRATCHPAD_SENTINEL', json.dumps(restored_events))
        checkpoint = json.loads(json.dumps(build_runtime_session_checkpoint(c)))
        self.assertNotIn('SCRATCHPAD_SENTINEL', json.dumps(checkpoint['tool_results']))
        replay = _restore_disk_checkpoint([{'event':'session_checkpoint','payload':checkpoint}, *events])
        restored = self.make_context('disk-restored')
        apply_bootstrap_tool_results(restored, replay)
        self.assertNotIn('SCRATCHPAD_SENTINEL', json.dumps(restored.runtime_tool_results))
        self.assertIn('KEEP_SENTINEL', json.dumps(restored.runtime_tool_results))
