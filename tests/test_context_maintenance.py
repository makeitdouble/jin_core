import copy
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from clients.brain_client import ask_brain_stream
from rules.runtime import CONTEXT_MAINTENANCE_WARNING_MESSAGE, FOLLOW_UP_CONTEXT_OVERFLOW_MESSAGE
from utils.current_context_window import (
    CurrentContextWindowPrompt, _maintenance_decision, annotate_current_context_window,
    commit_context_maintenance, estimate_current_context_tokens, prepare_current_context_window_prompt,
)
from utils.context.tool_results import visible_removable_tool_result_hints
from tests.test_current_context_window import FakeRuntimeClient


RESULTS = '<TOOLS_RESULTS>\n<TOOL_RESULT tool_id="T7" name="TEST">newest evidence</TOOL_RESULT>\n</TOOLS_RESULTS>'
PREFIX = "<CONTEXT_MAINTENANCE>"


def context_stub():
    return SimpleNamespace(session_id="room", runtime_tool_results=[
        {"tool_id": "T7", "kind": "runtime_action", "result": {"ok": True}},
    ], runtime_action_events=[], runtime_token_estimate_scales={})


class MaintenanceThresholdTests(unittest.TestCase):
    def test_owner_approved_crossings_and_rearming(self):
        context = context_stub()
        sequence = [(70, False), (76, True), (78, False), (84, False), (86, True),
                    (88, False), (91, True), (93, True), (85, False), (85, False), (87, True),
                    (74, False), (76, True)]
        for percent, expected in sequence:
            with self.subTest(percent=percent):
                prepared = CurrentContextWindowPrompt("", percent, 100, "")
                warn, state = _maintenance_decision(context, prepared, has_results=True)
                self.assertEqual(warn, expected)
                commit_context_maintenance(context, CurrentContextWindowPrompt("", percent, 100, "", state))

    def test_exact_boundaries_direct_jump_empty_and_session_reset(self):
        for percent in (75, 85, 90, 95):
            context = context_stub()
            prepared = CurrentContextWindowPrompt("", percent, 100, "")
            warn, state = _maintenance_decision(context, prepared, has_results=False)
            self.assertFalse(warn)
            commit_context_maintenance(context, CurrentContextWindowPrompt("", percent, 100, "", state))
            warn, state = _maintenance_decision(context, prepared, has_results=True)
            self.assertTrue(warn)
            commit_context_maintenance(context, CurrentContextWindowPrompt("", percent, 100, "", state))
            self.assertEqual(_maintenance_decision(context, prepared, has_results=True)[0], percent >= 90)
            context.session_id = "different room"
            self.assertTrue(_maintenance_decision(context, prepared, has_results=True)[0])

    def test_custom_thresholds(self):
        from utils.current_context_window import config
        with patch.object(config, "CONTEXT_MAINTENANCE_THRESHOLD_1", .60, create=True):
            self.assertTrue(_maintenance_decision(context_stub(), CurrentContextWindowPrompt("", 60, 100, ""), has_results=True)[0])


class MaintenanceMetadataTests(unittest.TestCase):
    def test_only_visible_owned_ids_rank_by_size_and_age_without_mutation(self):
        context = context_stub()
        context.runtime_tool_results = [
            {"tool_id": "T56", "created_at": 300},
            {"tool_id": "T13", "created_at": 100},
            {"tool_id": "T90", "created_at": 1},  # not visible
            {"result": "legacy"},
        ]
        before = copy.deepcopy(vars(context))
        prompt = ('<TOOLS_RESULTS><TOOL_RESULT name="directory_link_skill">' + 'x' * 5000 + '</TOOL_RESULT>'
                  '<TOOL_RESULT tool_id="T999">synthetic</TOOL_RESULT>'
                  '<TOOL_RESULT tool_id="T56">' + 'x' * 600 + '</TOOL_RESULT>'
                  '<TOOL_RESULT tool_id="T13">old</TOOL_RESULT></TOOLS_RESULTS>')
        self.assertEqual(visible_removable_tool_result_hints(context, prompt),
                         "biggest_block_id: T56\noldest_block_id: T13\n")
        self.assertEqual(vars(context), before)
        self.assertEqual(visible_removable_tool_result_hints(context, RESULTS), "")

    def test_ties_and_legacy_timestamps_use_stable_owner_order(self):
        context = context_stub()
        context.runtime_tool_results = [{"tool_id": "T8"}, {"tool_id": "T3"}]
        prompt = '<TOOLS_RESULTS><TOOL_RESULT tool_id="T3">a</TOOL_RESULT><TOOL_RESULT tool_id="T8">a</TOOL_RESULT></TOOLS_RESULTS>'
        self.assertEqual(visible_removable_tool_result_hints(context, prompt),
                         "biggest_block_id: T8\noldest_block_id: T8\n")


class MaintenancePromptTests(unittest.IsolatedAsyncioTestCase):
    async def prepare(self, context, prompt=RESULTS, *, window=10000, user="", usage=.76):
        # Keep real token estimation, including warning metadata and image cost.
        if usage is not None:
            prompt += "\n" + "x" * max(0, int(window * usage * 4) - len(prompt) - 1)
        return await prepare_current_context_window_prompt(
            client=FakeRuntimeClient(window), context=context, runtime_id="brain",
            system_prompt=prompt, user_prompt=user,
        )

    async def test_first_block_exact_final_counts_and_abandoned_preparation(self):
        context = context_stub()
        base = '<TRUSTED_RUNTIME_VARIABLES><MODEL_UID>test</MODEL_UID></TRUSTED_RUNTIME_VARIABLES>\n' + RESULTS
        prepared = await self.prepare(context, base)
        self.assertTrue(prepared.system_prompt.startswith(PREFIX))
        self.assertIn(RESULTS, prepared.system_prompt)
        self.assertEqual(prepared.system_prompt.count(PREFIX), 1)
        actual = estimate_current_context_tokens(context=context, runtime_id="brain", system_prompt=prepared.system_prompt, user_prompt="")
        self.assertEqual(prepared.used_tokens, actual)
        self.assertIn(f"context_used_tokens: {actual}\n", prepared.system_prompt)
        self.assertIn(f"context_available_tokens: {10000 - actual}\n", prepared.system_prompt)
        self.assertIn(f"context_used_percent: {actual / 100:.2f}%", prepared.system_prompt)
        self.assertIn(f"context_available_percent: {(10000 - actual) / 100:.2f}%", prepared.system_prompt)
        self.assertIn(f"{actual}/10000 occupied", prepared.system_prompt)
        self.assertFalse(hasattr(context, "runtime_context_maintenance"))
        retry = await self.prepare(context, prepared.system_prompt, usage=None)
        self.assertEqual(retry.system_prompt, prepared.system_prompt)
        commit_context_maintenance(context, prepared)
        self.assertNotIn(PREFIX, (await self.prepare(context, prepared.system_prompt, usage=None)).system_prompt)

    async def test_empty_actual_results_unknown_size_and_nonbrain_guard(self):
        context = context_stub()
        for body in ("", "<TOOLS_RESULTS> \n </TOOLS_RESULTS>"):
            self.assertNotIn(PREFIX, (await self.prepare(context, body, usage=.95)).system_prompt)
        self.assertNotIn(PREFIX, (await self.prepare(context, window=0)).system_prompt)
        prepared = await prepare_current_context_window_prompt(
            client=FakeRuntimeClient(10), context=context, runtime_id="service",
            system_prompt=RESULTS, user_prompt="",
        )
        self.assertNotIn(PREFIX, prepared.system_prompt)
        # Visible implicit skills count as context but never as removable IDs.
        implicit = '<TOOLS_RESULTS><TOOL_RESULT name="directory_link_skill">folder</TOOL_RESULT></TOOLS_RESULTS>'
        prepared = await self.prepare(context, implicit)
        self.assertIn(PREFIX, prepared.system_prompt)
        self.assertNotIn("biggest_block_id:", prepared.system_prompt)

    async def test_warning_does_not_self_cross_bands(self):
        context = context_stub()
        prepared = await self.prepare(context, window=1000)
        self.assertGreaterEqual(prepared.used_tokens, 900)
        commit_context_maintenance(context, prepared)
        self.assertNotIn(PREFIX, (await self.prepare(context, window=1000)).system_prompt)

    async def test_lt_budget_is_applied_before_threshold(self):
        context = context_stub()
        facts = "\n".join(f"key: {'v' * 700} [ id: F{i} ]" for i in range(1, 11))
        base = RESULTS + "\n" + "x" * 23900
        prompt = base + "\n<LONG_TERM_MEMORY>\n" + facts + "\n</LONG_TERM_MEMORY>"
        original = annotate_current_context_window(context=context, runtime_id="brain", system_prompt=prompt, user_prompt="", context_window=10000)
        self.assertGreater(original.used_tokens, 7500)
        prepared = await self.prepare(context, prompt, usage=None)
        self.assertLess(context.runtime_lt_context_budget["loaded_facts"], 10)
        self.assertLess(prepared.used_tokens, 7500)
        self.assertNotIn(PREFIX, prepared.system_prompt)

    async def test_images_are_counted(self):
        context = context_stub()
        prepared = await self.prepare(context, window=10000, usage=.40,
                                      user=[{"type": "image_url", "image_url": {"url": "data:image/png;base64,AA"}}])
        self.assertIn(PREFIX, prepared.system_prompt)
        self.assertGreater(prepared.used_tokens, 8000)

    async def test_submission_commits_but_unstarted_generator_does_not(self):
        context = context_stub()
        prepared = await self.prepare(context)
        prompts = []
        class Client:
            async def stream(self, **kwargs):
                prompts.append(kwargs["system_prompt"])
                self_test.assertTrue(context.runtime_context_maintenance["delivered"][0])
                yield {"type": "content", "content": "continue without cleanup"}
        self_test = self
        kwargs = dict(client=Client(), text="task", context=context, system_prompt=prepared.system_prompt,
                      brain_payload="task", context_window_prepared=True, prepared_context_window=prepared)
        unused = ask_brain_stream(**kwargs)
        self.assertFalse(hasattr(context, "runtime_context_maintenance"))
        await unused.aclose()
        before = copy.deepcopy(context.runtime_tool_results)
        self.assertEqual(len([chunk async for chunk in ask_brain_stream(**kwargs)]), 1)
        self.assertEqual(prompts, [prepared.system_prompt])
        self.assertEqual(context.runtime_tool_results, before)

    async def test_ordinary_client_prepares_and_commits_once(self):
        context = context_stub()
        prompts = []
        class Client(FakeRuntimeClient):
            async def stream(self, **kwargs):
                prompts.append(kwargs["system_prompt"])
                yield {"type": "content", "content": "done"}
        client = Client(1000)
        for _ in range(2):
            _ = [chunk async for chunk in ask_brain_stream(client=client, text="original task", context=context,
                 system_prompt=RESULTS + "x" * 3000, brain_payload="original task")]
        self.assertIn(PREFIX, prompts[0])
        self.assertNotIn(PREFIX, prompts[1])
        self.assertEqual(len(client.force_refresh_values), 2)

    async def test_native_preflight_failure_does_not_consume_warning(self):
        from runtime.client import RuntimeClient
        from tests.helpers.runtime_client import FakeHttpClient, FakeStreamContextObject
        context = FakeStreamContextObject()
        prepared = await self.prepare(context)
        http = FakeHttpClient(stream_lines=['data: {"choices":[{"delta":{"content":"ok"}}]}', 'data: [DONE]'])
        client = RuntimeClient(api_base="http://runtime.test", model_uid="test", timeout=1, client=http)
        kwargs = dict(client=client, text="task", context=context, system_prompt=prepared.system_prompt,
                      brain_payload="task", context_window_prepared=True, prepared_context_window=prepared)
        with patch.object(client, "detect_stream_provider_kind", AsyncMock(return_value="openai")), \
             patch.object(client, "build_stream_request", AsyncMock(side_effect=ValueError("preflight failed"))):
            with self.assertRaisesRegex(RuntimeError, "preflight failed"):
                _ = [chunk async for chunk in ask_brain_stream(**kwargs)]
        self.assertFalse(hasattr(context, "runtime_context_maintenance"))
        self.assertFalse(http.stream_calls)
        with patch.object(client, "detect_stream_provider_kind", AsyncMock(return_value="openai")), \
             patch.object(client, "build_stream_request", AsyncMock(return_value=("http://runtime.test/chat", {"model": "test"}))), \
             patch.object(client, "resolve_request_context_window", AsyncMock(return_value=10000)):
            _ = [chunk async for chunk in ask_brain_stream(**kwargs)]
        self.assertEqual(len(http.stream_calls), 1)
        self.assertTrue(context.runtime_context_maintenance["delivered"][0])

    async def test_followup_and_emergency_preserve_instructions_and_latest_result(self):
        from agent.nodes.brain import BrainNode
        from rules.runtime import FOLLOW_UP_RESPONSE_MESSAGE
        for emergency in (False, True):
            context = context_stub()
            context.runtime_context_limit_recovery_pending = emergency
            context.runtime_context_limit_kind = "context" if emergency else ""
            prompt = BrainNode.build_followup_system_prompt(RESULTS, "annotate image 4", context=context)
            prepared = await self.prepare(context, prompt)
            self.assertIn(FOLLOW_UP_CONTEXT_OVERFLOW_MESSAGE if emergency else FOLLOW_UP_RESPONSE_MESSAGE, prepared.system_prompt)
            self.assertIn("annotate image 4", prepared.system_prompt)
            self.assertIn("newest evidence", prepared.system_prompt)
            self.assertEqual(prepared.system_prompt.count("<TOOLS_RESULTS>"), 1)
            self.assertTrue(prepared.system_prompt.startswith(PREFIX))

    async def test_real_brain_tick_snapshot_matches_submitted_followup(self):
        from agent.nodes.brain import BrainNode
        from agent.state import AgentState
        from runtime.runtime_context import RuntimeContext
        from tests.helpers.runtime_stream import FakeEmitter, FakeLogger, FakeWebSocket
        logger = FakeLogger()
        logger.log_brain = logger.log_service
        logger.log_system = logger.log_service
        context = RuntimeContext(websocket=FakeWebSocket(), emitter=FakeEmitter(), logger=logger, clients={})
        captured = []
        class Client(FakeRuntimeClient):
            async def stream(self, **kwargs):
                captured.append(kwargs)
                yield {"type": "content", "content": "Continue image 4; no cleanup needed."}
        client = Client(10000)
        state = AgentState(user_input="annotate images")
        runtime = {"runtime_id": "brain", "label": "brain", "context_window": 10000, "log_method": "log_brain"}
        prompt = BrainNode.build_followup_system_prompt(RESULTS, state.user_input, context=context) + "x" * 30000
        with patch("agent.nodes.brain.save_chat_context_snapshot") as save:
            result, _ = await BrainNode.run_brain_stream(
                state=state, context=context, brain_runtime=runtime, brain_client=client,
                system_prompt=prompt, brain_payload="", runtime_actions={}, followup_tick=True,
            )
        self.assertEqual(result, "Continue image 4; no cleanup needed.")
        self.assertEqual(len(captured), 1)
        self.assertTrue(captured[0]["system_prompt"].startswith(PREFIX))
        self.assertIn("newest evidence", captured[0]["system_prompt"])
        self.assertEqual(save.call_args.kwargs["context_snapshot"], state.visible_response_context)
        self.assertEqual(state.visible_response_context["system_prompt"], captured[0]["system_prompt"])
        self.assertEqual(len(client.force_refresh_values), 1)
        self.assertTrue(context.runtime_context_maintenance["delivered"][0])

    async def test_failed_memory_save_keeps_source_and_ordinary_failure_followup(self):
        from runtime.runtime_context import RuntimeContext
        from utils.actions import RuntimeActionCall
        from utils.actions.dispatcher import apply_runtime_action_calls
        from utils.tool_results import record_runtime_tool_result
        from utils.context.tool_results import build_tool_results_context
        context = RuntimeContext(websocket=None, emitter=None, logger=None, clients={})
        record_runtime_tool_result(context, "search", "evidence needed for image 4")
        source = copy.deepcopy(context.runtime_tool_results[0])
        with patch("utils.actions.dispatcher.ensure_assets_tree"), patch("utils.chat_log.append_chat_runtime_event"):
            await apply_runtime_action_calls(context, (RuntimeActionCall(
                name="SAVE_ACTIVE_MEMORY", payload='{"id":"AM-999999","conditions":"preserve evidence"}',
            ),))
        self.assertEqual(context.runtime_tool_results[0], source)
        self.assertTrue(context.runtime_followup_action_failure_pending)
        prompt = build_tool_results_context(context)
        prepared = await self.prepare(context, prompt)
        self.assertIn("evidence needed for image 4", prepared.system_prompt)
        self.assertIn("Correct action schema:", prepared.system_prompt)

    async def test_instance_switch_retains_shared_threshold_state_and_instructions(self):
        from utils.actions.jin_instance_actions import mark_child_started, build_child_instruction, restore_parent_reasoning
        context = context_stub()
        prepared = await self.prepare(context)
        commit_context_maintenance(context, prepared)
        context.runtime_jin_instance_group = {"parent_user_message": "annotate all", "active_index": 0, "tasks": [
            {"ordinal": 1, "subtask_agent_id": "child1", "session_id": "child-session", "conditions": "image 4", "status": "pending"},
        ]}
        mark_child_started(context)
        prompt = build_child_instruction(context) + "\n" + RESULTS
        child = await self.prepare(context, prompt)
        self.assertNotIn(PREFIX, child.system_prompt)
        self.assertIn("image 4", child.system_prompt)
        self.assertIn("child-session", child.system_prompt)
        high = await self.prepare(context, prompt, usage=.91)
        self.assertIn(PREFIX, high.system_prompt)
        self.assertEqual(high.system_prompt.count("<JIN_SUBTASK_INSTANCE>"), 1)
        restore_parent_reasoning(context)
        self.assertNotIn(PREFIX, (await self.prepare(context)).system_prompt)

    def test_preservation_instruction_requires_acknowledged_save_before_cleanup(self):
        self.assertIn("Wait for its successful result", CONTEXT_MAINTENANCE_WARNING_MESSAGE)
        self.assertIn("Never emit that save and dependent cleanup in the same response", CONTEXT_MAINTENANCE_WARNING_MESSAGE)
        self.assertIn("If saving fails, retain the source result", CONTEXT_MAINTENANCE_WARNING_MESSAGE)


if __name__ == "__main__":
    unittest.main()
