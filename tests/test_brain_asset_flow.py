import contextlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent.nodes.brain import (
    BrainNode,
    FOLLOWUP_SYSTEM_MESSAGE,
    action_batch_requires_follow_up,
    action_event_requires_follow_up,
    build_idle_followup_system_prompt,
    build_context_limit_recovery_context,
    build_followup_system_message,
    build_reasoning_recovery_context,
    format_followup_action_from_event,
    format_followup_actions_from_events,
    prepare_asset_results_for_turn,
)
from rules.brain_context_builder import (
    build_appended_delayed_memory_context,
)
from utils.context.context_exports import (
    build_tool_results_context,
)
from agent.state import AgentState
from agent.runtime import (
    AgentRuntime,
)
from runtime.runtime_context import (
    RuntimeContext,
)
from utils.tool_results import (
    TOOL_RESULT_KIND_ASSET,
    record_runtime_tool_result,
)
from tests.helpers.runtime_actions import (
    patch_asset_roots,
)


def _brain_runtime():
    return {
        "runtime_id": "brain-model",
        "label": "brain",
        "context_window": 8192,
        "log_method": "log_brain",
        "runtime_actions": {
            "CAN_WEB_SEARCH": True,
            "CAN_USE_ASSETS": True,
            "CAN_SAVE_SESSION": True,
            "CAN_SAVE_DELAYED_MEMORY": True,
            "CAN_SAVE_ACTIVE_MEMORY": True,
        },
    }


def _context():
    return SimpleNamespace(
        logger=SimpleNamespace(),
        clients={"brain": object()},
        runtime_search_queries=[],
        runtime_search_calls=[],
        runtime_asset_results=[],
        runtime_delayed_memory_results=[],
        runtime_appended_skills=[],
        runtime_action_events=[],
    )


def _assert_latest_request_payload(
        test_case,
        call_kwargs,
        user_input,
        latest_action_fragment=None,
):
    payload = call_kwargs["brain_payload"]
    system_prompt = call_kwargs["system_prompt"]

    test_case.assertEqual(
        payload,
        "",
    )
    expected_followup_message = build_followup_system_message(
        latest_action_fragment or "",
    )
    test_case.assertTrue(
        system_prompt.startswith(
            expected_followup_message
        ),
        system_prompt,
    )
    test_case.assertIn(
        expected_followup_message,
        system_prompt,
    )
    test_case.assertLess(
        system_prompt.index(
            "</CURRENT_SEQUENCE>"
        ),
        system_prompt.index(
            "<TOOLS_RESULTS>"
        ),
    )
    test_case.assertLess(
        system_prompt.index(
            expected_followup_message
        ),
        system_prompt.index(
            "<CURRENT_SEQUENCE>"
        ),
    )
    test_case.assertIn(
        f"INITIAL_SEQUENCE_INSTRUCTION: {user_input}",
        system_prompt,
    )
    test_case.assertNotIn(
        "<SEQUENCE_ORIGIN_REQUEST>",
        system_prompt,
    )
    test_case.assertNotIn(
        "MANDATORY: THIS IS NOT CURRENT COMMAND",
        system_prompt,
    )
    test_case.assertNotIn(
        "<PREVIOUS_CHAT_MESSAGES>",
        system_prompt,
    )


class BrainAssetFlowTests(unittest.IsolatedAsyncioTestCase):

    async def test_retry_asset_payload_is_available_for_exactly_next_turn(self):

        failed_result = {
            "ok": False,
            "action": "create_asset_file",
            "error": "file_exists",
            "path": "assets/outputs/gemma.txt",
            "runtime_turn_id": "turn_000001",
            "payload": {
                "action": "create_asset_file",
                "path": "assets/outputs/gemma.txt",
                "content": "saved text",
            },
        }
        context = SimpleNamespace(
            runtime_asset_results=[
                {
                    "ok": True,
                    "action": "list_skills",
                },
            ],
            runtime_asset_retry_results=[
                failed_result,
            ],
        )

        prepare_asset_results_for_turn(
            context
        )

        self.assertEqual(
            context.runtime_asset_results,
            [],
        )
        self.assertEqual(
            context.runtime_asset_retry_results,
            [],
        )
        self.assertEqual(
            context.runtime_asset_retry_context,
            [failed_result],
        )
        self.assertIsNot(
            context.runtime_asset_retry_context[0],
            failed_result,
        )

        tool_results = build_tool_results_context(
            context
        )
        self.assertIn(
            "file_exists",
            tool_results,
        )
        self.assertIn(
            "saved text",
            tool_results,
        )
        self.assertIn(
            "assets/outputs/gemma.txt",
            tool_results,
        )

        prepare_asset_results_for_turn(
            context
        )

        self.assertEqual(
            context.runtime_asset_retry_context,
            [],
        )
        self.assertEqual(
            build_tool_results_context(
                context
            ),
            "<TOOLS_RESULTS>\n</TOOLS_RESULTS>",
        )

    async def test_followup_always_contains_tool_results_block(self):

        prompt = BrainNode.build_followup_system_prompt(
            "system prompt without results",
            "inspect available skills",
        )

        self.assertIn(
            "<TOOLS_RESULTS>\n</TOOLS_RESULTS>",
            prompt,
        )

    async def test_followup_places_runtime_instruction_under_header(self):

        instruction = (
            "Action-specific follow-up instruction."
        )
        prompt = BrainNode.build_followup_system_prompt(
            "system rules",
            "continue the task",
            instruction=instruction,
            latest_action="web_search",
        )

        self.assertLess(
            prompt.index(
                "This is follow-up tick for JIN latest action: web_search."
            ),
            prompt.index(instruction),
        )
        self.assertLess(
            prompt.index(instruction),
            prompt.index("<CURRENT_SEQUENCE>"),
        )
        self.assertLess(
            prompt.index("<CURRENT_SEQUENCE>"),
            prompt.index("<TOOLS_RESULTS>"),
        )

    async def test_followup_places_confirm_result_inside_tool_results(self):

        messages = (
            (
                "User accepted an action and didn't provide any of action "
                "trigger words: save session"
            ),
            (
                "Action failed. User rejected an action and didn't provide "
                "any of trigger words: save session"
            ),
        )

        followup_message = (
            "This is follow-up tick for JIN latest action: "
            "save_session.\n"
            "Requested and available information provided in tool "
            "results section."
        )

        for message in messages:
            with self.subTest(message=message):
                context = SimpleNamespace(
                    runtime_action_failure_followup_messages=[message],
                    runtime_recent_turns=[],
                    runtime_appended_delayed_memory={},
                )

                prompt = BrainNode.build_followup_system_prompt(
                    "<TOOL_RESULTS>\n</TOOL_RESULTS>",
                    "save the session",
                    context=context,
                    latest_action="save_session",
                )

                tools_start = prompt.index("<TOOLS_RESULTS>")
                confirm_start = prompt.index("<CONFIRM_RESULT>")
                confirm_end = prompt.index("</CONFIRM_RESULT>")
                tools_end = prompt.index("</TOOLS_RESULTS>")
                followup_start = prompt.index(followup_message)

                self.assertLess(
                    tools_start,
                    confirm_start,
                )
                self.assertLess(
                    confirm_start,
                    confirm_end,
                )
                self.assertLess(
                    confirm_end,
                    tools_end,
                )
                self.assertLess(
                    followup_start,
                    tools_start,
                )
                self.assertEqual(
                    prompt.count("<CONFIRM_RESULT>"),
                    1,
                )
                self.assertEqual(
                    context.runtime_action_failure_followup_messages,
                    [],
                )

    async def test_current_sequence_starts_with_original_user_message(self):

        context = SimpleNamespace(
            runtime_current_turn_id="turn_000001",
            runtime_turn_started_at=990.0,
            runtime_action_sequence_turn_ids=[],
            runtime_session_action_history=[
                {
                    "text": "LIST_SKILLS",
                    "created_at": 995.0,
                    "runtime_turn_id": "turn_000001",
                },
            ],
            runtime_recent_turns=[],
            runtime_appended_delayed_memory={},
        )

        with patch(
            "utils.context.context_exports.time.time",
            return_value=1000.0,
        ):
            prompt = BrainNode.build_followup_system_prompt(
                "rules",
                "keep <this> in delayed memory",
                context=context,
            )

        self.assertIn(
            "<CURRENT_SEQUENCE>\n"
            "INITIAL_SEQUENCE_INSTRUCTION: keep &lt;this&gt; in delayed memory ( 10s ago )\n"
            "DO NOT FOLLOW INITIAL_SEQUENCE_INSTRUCTION EXPLICITLY, CHECK CURRENT_SEQUENCE HISTORY BELOW!\n"
            "    --- Sequence started ---\n"
            "    JIN message 1 executed: LIST_SKILLS ( 5s ago )\n"
            "</CURRENT_SEQUENCE>",
            prompt,
        )
        self.assertNotIn(
            "SEQUENCE_ORIGIN_REQUEST",
            prompt,
        )
        self.assertNotIn(
            "MANDATORY: THIS IS NOT CURRENT COMMAND",
            prompt,
        )

    async def test_followup_collects_scattered_tool_results_below_current_sequence(self):

        prompt = BrainNode.build_followup_system_prompt(
            (
                "RULE A\n\n"
                "<TOOL_RESULTS type='external'>\n"
                "    <TOOL_RESULT name=\"SEARCH\">one</TOOL_RESULT>\n"
                "</TOOL_RESULTS>\n\n"
                "RULE B\n\n"
                "<TOOLS_RESULTS>\n"
                "<TOOL_RESULTS type='asset'>\n"
                "    <TOOL_RESULT name=\"FILE\">two</TOOL_RESULT>\n"
                "</TOOL_RESULTS>\n"
                "</TOOLS_RESULTS>\n\n"
                "RULE C"
            ),
            "continue",
        )

        self.assertTrue(
            prompt.startswith(
                build_followup_system_message()
            ),
            prompt,
        )
        self.assertLess(
            prompt.index("</CURRENT_SEQUENCE>"),
            prompt.index("<TOOLS_RESULTS>"),
        )
        self.assertEqual(
            prompt.count(
                "<TOOLS_RESULTS>"
            ),
            1,
        )
        self.assertEqual(
            prompt.count(
                "<TOOL_RESULTS type="
            ),
            2,
        )
        tools_end = prompt.index(
            "</TOOLS_RESULTS>"
        ) + len(
            "</TOOLS_RESULTS>"
        )
        self.assertNotIn(
            "<TOOL_RESULTS",
            prompt[tools_end:],
        )
        self.assertLess(
            prompt.index(
                "one"
            ),
            prompt.index(
                "two"
            ),
        )
        self.assertIn(
            "RULE A",
            prompt,
        )
        self.assertIn(
            "RULE B",
            prompt,
        )
        self.assertIn(
            "RULE C",
            prompt,
        )

    async def test_followup_consumes_reasoning_recovery_block(self):

        context = SimpleNamespace(
            runtime_reasoning_recovery_pending=True,
            runtime_turn_interrupted=True,
            runtime_turn_interruption_reason=(
                "Repeated thinking sentence loop detected."
            ),
            runtime_turn_interruption_quote="looped sentence",
            runtime_recent_turns=[],
            runtime_appended_delayed_memory={},
        )

        prompt = BrainNode.build_followup_system_prompt(
            "system prompt",
            "continue immediately",
            context=context,
        )

        self.assertIn(
            build_reasoning_recovery_context(),
            prompt,
        )
        self.assertFalse(
            context.runtime_reasoning_recovery_pending
        )
        self.assertFalse(
            context.runtime_turn_interrupted
        )
        self.assertEqual(
            context.runtime_turn_interruption_reason,
            "",
        )
        self.assertEqual(
            context.runtime_turn_interruption_quote,
            "",
        )

    async def test_followup_consumes_context_limit_recovery_block(self):

        context = SimpleNamespace(
            runtime_reasoning_recovery_pending=False,
            runtime_context_limit_recovery_pending=True,
            runtime_context_limit_stage="answer",
            runtime_context_limit_kind="output",
            runtime_context_limit_finish_reason="length",
            runtime_turn_interrupted=True,
            runtime_turn_interruption_reason=(
                "Context limit reached during answer."
            ),
            runtime_turn_interruption_quote="",
            runtime_recent_turns=[],
            runtime_appended_delayed_memory={},
        )

        prompt = BrainNode.build_followup_system_prompt(
            "system prompt",
            "continue immediately",
            context=context,
        )

        self.assertIn(
            build_context_limit_recovery_context(
                "answer",
                "output",
            ),
            prompt,
        )
        self.assertFalse(
            context.runtime_context_limit_recovery_pending
        )
        self.assertEqual(
            context.runtime_context_limit_stage,
            "",
        )
        self.assertEqual(
            context.runtime_context_limit_kind,
            "",
        )
        self.assertEqual(
            context.runtime_context_limit_finish_reason,
            "",
        )
        self.assertFalse(
            context.runtime_turn_interrupted
        )

    async def test_followup_event_formatter_keeps_only_action_name(self):

        self.assertEqual(
            format_followup_action_from_event({
                "name": "save_session",
                "payload": "session payload",
                "id": "save-123",
                "query": "ignored query",
            }),
            "SAVE_SESSION",
        )

    async def test_followup_event_formatter_groups_duplicate_action_names(self):

        self.assertEqual(
            format_followup_actions_from_events([
                {
                    "name": "resolve_active_memory",
                    "id": "active_memory_1",
                },
                {
                    "name": "resolve_active_memory",
                    "id": "active_memory_2",
                },
                {
                    "name": "save_session",
                    "id": "save-123",
                    "payload": "ignored",
                },
            ]),
            "RESOLVE_ACTIVE_MEMORY (count: 2), SAVE_SESSION",
        )

    async def test_followup_renames_runtime_memory_block(self):

        prompt = BrainNode.build_followup_system_prompt(
            (
                "<ACTIVE_MEMORY>\nactive memory\n</ACTIVE_MEMORY>\n\n"
                "<RUNTIME_MEMORY>\nactive_topic: test\n</RUNTIME_MEMORY>\n\n"
                "<RUNTIME_PATTERN_MEMORY>\npattern\n</RUNTIME_PATTERN_MEMORY>"
            ),
            "continue the task",
        )

        self.assertIn(
            "<PREVIOUS_RUNTIME_MEMORY>\nactive_topic: test\n"
            "</PREVIOUS_RUNTIME_MEMORY>",
            prompt,
        )
        self.assertNotIn(
            "<RUNTIME_MEMORY>",
            prompt,
        )
        self.assertNotIn(
            "</RUNTIME_MEMORY>",
            prompt,
        )
        self.assertIn(
            "<RUNTIME_PATTERN_MEMORY>\npattern\n"
            "</RUNTIME_PATTERN_MEMORY>",
            prompt,
        )

    async def test_appended_delayed_memory_is_under_latest_request(self):

        context = SimpleNamespace(
            runtime_recent_turns=[],
            runtime_appended_delayed_memory={
                "id": "a1b2c3",
                "title": "Pinned delayed report",
                "summary": "Summary",
            },
        )

        prompt = BrainNode.build_followup_system_prompt(
            "system prompt",
            "append the delayed memory",
            context=context,
        )

        appended_delayed_memory = (
            build_appended_delayed_memory_context(
                context
            )
        )
        self.assertTrue(
            prompt.startswith(
                build_followup_system_message()
            ),
            prompt,
        )
        self.assertLess(
            prompt.index("</CURRENT_SEQUENCE>"),
            prompt.index("<TOOLS_RESULTS>"),
        )
        self.assertIn(
            build_followup_system_message(),
            prompt,
        )
        self.assertIn(
            "INITIAL_SEQUENCE_INSTRUCTION: append the delayed memory",
            prompt,
        )
        self.assertIn(
            appended_delayed_memory,
            prompt,
        )
        self.assertNotIn(
            "<PREVIOUS_CHAT_MESSAGES>",
            prompt,
        )
        self.assertLess(
            prompt.index(
                "<CURRENT_SEQUENCE>"
            ),
            prompt.index(
                appended_delayed_memory
            ),
        )

    async def test_followup_places_current_sequence_under_latest_request(self):

        context = SimpleNamespace(
            runtime_current_turn_id="turn_000002",
            runtime_turn_started_at=940.0,
            runtime_action_sequence_turn_ids=[],
            runtime_session_action_history=[
                {
                    "text": "SAVE_ACTIVE_MEMORY",
                    "created_at": 800.0,
                    "runtime_turn_id": "turn_000001",
                },
                {
                    "text": "LIST_SKILLS",
                    "created_at": 945.0,
                    "runtime_turn_id": "turn_000002",
                },
                {
                    "text": "APPEND_SKILL",
                    "created_at": 998.0,
                    "runtime_turn_id": "turn_000002",
                },
            ],
            runtime_recent_turns=[],
            runtime_appended_delayed_memory={},
        )
        base_prompt = (
            "<RUNTIME_MEMORY>\nstate\n</RUNTIME_MEMORY>\n\n"
            "<SESSION_ACTIONS_HISTORY>\n"
            "    1. SAVE_ACTIVE_MEMORY\n"
            "    2. LIST_SKILLS\n"
            "    3. APPEND_SKILL\n"
            "</SESSION_ACTIONS_HISTORY>\n\n"
            "RULES"
        )

        with patch(
            "utils.context.context_exports.time.time",
            return_value=1000.0,
        ):
            prompt = BrainNode.build_followup_system_prompt(
                base_prompt,
                "first list skills, then append one",
                context=context,
            )

        self.assertIn(
            "turn_000002",
            context.runtime_action_sequence_turn_ids,
        )
        self.assertIn(
            "<CURRENT_SEQUENCE>\n"
            "INITIAL_SEQUENCE_INSTRUCTION: first list skills, then append one ( 1m ago )\n"
            "DO NOT FOLLOW INITIAL_SEQUENCE_INSTRUCTION EXPLICITLY, CHECK CURRENT_SEQUENCE HISTORY BELOW!\n"
            "    --- Sequence started ---\n"
            "    JIN message 1 executed: LIST_SKILLS ( 55s ago )\n"
            "    JIN message 2 executed: APPEND_SKILL ( 2s ago )\n"
            "</CURRENT_SEQUENCE>",
            prompt,
        )
        self.assertNotIn(
            "<SESSION_ACTIONS_HISTORY>",
            prompt,
        )
        self.assertNotIn(
            "Sequence ended",
            prompt,
        )
        self.assertLess(
            prompt.index("</CURRENT_SEQUENCE>"),
            prompt.index("<TOOLS_RESULTS>"),
        )
        self.assertNotIn(
            "<PREVIOUS_CHAT_MESSAGES>",
            prompt,
        )

    async def test_idle_followup_keeps_original_sequence_action_history(self):

        context = SimpleNamespace(
            runtime_current_turn_id="idle_000002",
            runtime_current_sequence_turn_id="turn_000001",
            runtime_turn_started_at=1031.0,
            runtime_current_sequence_started_at=1000.0,
            runtime_action_sequence_turn_ids=[],
            runtime_session_action_history=[
                {
                    "text": "IDLE - 30s",
                    "created_at": 1000.0,
                    "runtime_turn_id": "turn_000001",
                },
                {
                    "text": "IDLE - 20s, WEB_SEARCH",
                    "created_at": 1031.0,
                    "runtime_turn_id": "turn_000001",
                },
            ],
            runtime_recent_turns=[],
            runtime_appended_delayed_memory={},
        )

        with patch(
            "utils.context.context_exports.time.time",
            return_value=1032.0,
        ):
            prompt = BrainNode.build_followup_system_prompt(
                "<RUNTIME_MEMORY>state</RUNTIME_MEMORY>",
                "first idle 30s, then idle 20s and search",
                context=context,
                latest_action="web_search, idle",
            )

        self.assertIn(
            "turn_000001",
            context.runtime_action_sequence_turn_ids,
        )
        self.assertIn(
            "<CURRENT_SEQUENCE>\n"
            "INITIAL_SEQUENCE_INSTRUCTION: first idle 30s, then idle 20s and search ( 32s ago )\n"
            "DO NOT FOLLOW INITIAL_SEQUENCE_INSTRUCTION EXPLICITLY, CHECK CURRENT_SEQUENCE HISTORY BELOW!\n"
            "    --- Sequence started ---\n"
            "    JIN message 1 executed: IDLE: 30s ( 32s ago )\n"
            "    JIN message 2 executed: IDLE: 20s, WEB_SEARCH ( 1s ago )\n"
            "</CURRENT_SEQUENCE>",
            prompt,
        )
        self.assertIn(
            "first idle 30s, then idle 20s and search ( 32s ago )",
            prompt,
        )

    async def test_list_skills_followup_text_is_emitted_when_no_asset_action_follows(self):

        calls = []
        emitted_reports = []

        async def fake_run_brain_stream(**kwargs):
            calls.append(kwargs)
            context = kwargs["context"]

            if len(calls) == 1:
                context.runtime_asset_results.append({
                    "ok": True,
                    "action": "list_skills",
                    "requested": "",
                    "skills": [
                        {
                            "name": "image_prompt_generator",
                            "content": "I can build image prompts.",
                        },
                        {
                            "name": "wildcards",
                            "content": "I can manage wildcard files.",
                        },
                    ],
                })
                return "", ""

            if len(calls) == 2:
                self.assertTrue(
                    kwargs["emit_content_to_chat"],
                )
                self.assertTrue(
                    kwargs["filter_runtime_actions"],
                )
                self.assertTrue(
                    kwargs["runtime_actions"].get("CAN_USE_ASSETS"),
                )
                return (
                    "I have two skills: image_prompt_generator and wildcards.",
                    "",
                )

            self.fail("Brain model was called again after list_skills answer")

        async def fake_emit_brain_text(**kwargs):
            emitted_reports.append(kwargs["text"])
            return kwargs["text"], ""

        context = _context()
        state = AgentState(
            user_input="what skills do you have?",
        )
        state.translated_input = state.user_input
        brain_runtime = _brain_runtime()

        with patch(
            "agent.nodes.brain.get_brain_runtime_config",
            return_value=brain_runtime,
        ), patch(
            "agent.nodes.brain.build_brain_context",
            return_value="system prompt",
        ), patch(
            "agent.nodes.brain.build_brain_payload",
            return_value="brain payload",
        ), patch(
            "agent.nodes.brain.emit_active_memory_records_update_if_dirty",
            new=lambda _context: _async_noop(),
        ), patch.object(
            BrainNode,
            "run_brain_stream",
            staticmethod(fake_run_brain_stream),
        ), patch.object(
            BrainNode,
            "emit_brain_text",
            staticmethod(fake_emit_brain_text),
        ):
            await BrainNode().run(
                state,
                context,
            )

        self.assertEqual(
            len(calls),
            2,
        )
        self.assertEqual(
            emitted_reports,
            [],
        )
        self.assertEqual(
            state.brain_response,
            "I have two skills: image_prompt_generator and wildcards.",
        )

    async def test_list_skills_tool_result_alone_triggers_followup(self):

        calls = []

        async def fake_run_brain_stream(**kwargs):
            calls.append(kwargs)
            context = kwargs["context"]

            if len(calls) == 1:
                record_runtime_tool_result(
                    context,
                    TOOL_RESULT_KIND_ASSET,
                    {
                        "ok": True,
                        "action": "list_skills",
                        "runtime_turn_id": "turn_000001",
                        "skills": [
                            {
                                "name": "chunk_reader",
                            },
                        ],
                    },
                )
                return "", ""

            self.assertEqual(
                kwargs["brain_payload"],
                "",
            )
            self.assertIn(
                "list_skills",
                kwargs["system_prompt"],
            )
            return "Follow-up continued.", ""

        context = _context()
        context.runtime_current_turn_id = "turn_000001"
        state = AgentState(
            user_input="list skills, then append chunk_reader",
        )
        state.translated_input = state.user_input

        with patch(
            "agent.nodes.brain.get_brain_runtime_config",
            return_value=_brain_runtime(),
        ), patch(
            "agent.nodes.brain.build_brain_context",
            return_value="system prompt",
        ), patch(
            "agent.nodes.brain.build_brain_payload",
            return_value="brain payload",
        ), patch(
            "agent.nodes.brain.emit_active_memory_records_update_if_dirty",
            new=lambda _context: _async_noop(),
        ), patch.object(
            BrainNode,
            "run_brain_stream",
            staticmethod(fake_run_brain_stream),
        ):
            await BrainNode().run(
                state,
                context,
            )

        self.assertEqual(
            len(calls),
            2,
        )
        self.assertEqual(
            state.brain_response,
            "Follow-up continued.",
        )

    async def test_list_skills_followup_keeps_attachment_context_in_sequence(self):

        calls = []

        async def fake_run_brain_stream(**kwargs):
            calls.append(kwargs)
            context = kwargs["context"]

            if len(calls) == 1:
                context.runtime_action_events.append({
                    "name": "list_skills",
                })
                return "", ""

            self.assertEqual(
                kwargs["brain_payload"],
                "",
            )
            self.assertIn(
                "INITIAL_SEQUENCE_INSTRUCTION: что на скриншоте?\n\n"
                "Attached context:",
                kwargs["system_prompt"],
            )
            self.assertIn(
                "- screen.png: image, image/png, 462.8 KB",
                kwargs["system_prompt"],
            )
            self.assertNotIn(
                "runtime_attachment",
                kwargs["system_prompt"],
            )
            return "Follow-up saw attachment context.", ""

        context = _context()
        context.runtime_current_turn_id = "turn_000001"
        context.runtime_turn_started_at = 1000.0
        context.runtime_turn_user_message = (
            "что на скриншоте?\n\n"
            "Attached context:\n"
            "- screen.png: image, image/png, 462.8 KB\n"
            "  runtime_attachment: full content is available to appended skills"
        )
        state = AgentState(
            user_input="что на скриншоте?",
        )
        state.translated_input = state.user_input

        with patch(
            "agent.nodes.brain.get_brain_runtime_config",
            return_value=_brain_runtime(),
        ), patch(
            "agent.nodes.brain.build_brain_context",
            return_value="system prompt",
        ), patch(
            "agent.nodes.brain.build_brain_payload",
            return_value="brain payload",
        ), patch(
            "agent.nodes.brain.emit_active_memory_records_update_if_dirty",
            new=lambda _context: _async_noop(),
        ), patch.object(
            BrainNode,
            "run_brain_stream",
            staticmethod(fake_run_brain_stream),
        ):
            await BrainNode().run(
                state,
                context,
            )

        self.assertEqual(
            len(calls),
            2,
        )
        self.assertEqual(
            state.brain_response,
            "Follow-up saw attachment context.",
        )

    async def test_followup_stream_sends_attachment_payload_without_user_request(self):

        attachment = {
            "name": "screen.png",
            "kind": "image",
            "type": "image/png",
            "data_url": "data:image/png;base64,AAAA",
        }
        observed = {}

        async def fake_ask_brain_stream(**kwargs):
            observed["brain_payload"] = kwargs["brain_payload"]
            observed["attachments"] = list(
                getattr(
                    kwargs["context"],
                    "runtime_turn_attachments",
                    [],
                )
            )
            if False:
                yield {}

        class FakeRuntimeStream:

            def __init__(self, **_kwargs):
                self.stream = SimpleNamespace(
                    reasoning="",
                )

            async def run(self, generator):
                async for _event in generator:
                    pass
                return ""

        context = _context()
        context.runtime_turn_attachments = []
        context.runtime_current_sequence_turn_id = "turn_000001"
        context.runtime_current_sequence_attachments_turn_id = "turn_000001"
        context.runtime_current_sequence_attachments = [
            attachment,
        ]
        context.logger = SimpleNamespace(
            log_brain=lambda _message: _async_noop(),
        )
        state = AgentState(
            user_input="что на скриншоте?",
        )
        state.translated_input = state.user_input

        with patch(
            "agent.nodes.brain.ask_brain_stream",
            new=fake_ask_brain_stream,
        ), patch(
            "agent.nodes.brain.RuntimeStream",
            new=FakeRuntimeStream,
        ):
            await BrainNode.run_brain_stream(
                state=state,
                context=context,
                brain_runtime=_brain_runtime(),
                brain_client=object(),
                system_prompt=build_followup_system_message(
                    "list_skills"
                ),
                brain_payload="",
                runtime_actions={},
            )

        self.assertIn(
            "Attached context:",
            observed["brain_payload"],
        )
        self.assertIn(
            "- screen.png: image, image/png",
            observed["brain_payload"],
        )
        self.assertNotIn(
            "runtime_attachment",
            observed["brain_payload"],
        )
        self.assertNotIn(
            "что на скриншоте?",
            observed["brain_payload"],
        )
        self.assertEqual(
            observed["attachments"],
            [
                attachment,
            ],
        )
        self.assertEqual(
            context.runtime_followup_tick_active,
            False,
        )

    async def test_failed_delayed_memory_save_triggers_followup_with_payload(self):

        calls = []
        failed_payload = (
            "<SAVE_DELAYED_MEMORY_CONTENT>\n"
            "CONDITIONS: Simulation step 2/5\n"
            "</SAVE_ACTIVE_MEMORY>"
        )

        async def fake_run_brain_stream(**kwargs):
            calls.append(kwargs)
            context = kwargs["context"]

            if len(calls) == 1:
                context.runtime_delayed_memory_results.append({
                    "ok": False,
                    "action": "save_delayed_memory_content",
                    "error": "Delayed memory report was not saved",
                    "payload": failed_payload,
                })
                return "", ""

            if len(calls) == 2:
                self.assertTrue(
                    kwargs["filter_runtime_actions"],
                )
                _assert_latest_request_payload(
                    self,
                    kwargs,
                    state.translated_input,
                    "save_delayed_memory_content",
                )
                self.assertIn(
                    "Delayed memory report was not saved",
                    kwargs["system_prompt"],
                )
                self.assertIn(
                    "CONDITIONS: Simulation step 2/5",
                    kwargs["system_prompt"],
                )
                self.assertIn(
                    "&lt;SAVE_DELAYED_MEMORY_CONTENT&gt;",
                    kwargs["system_prompt"],
                )
                self.assertIn(
                    "&lt;/SAVE_ACTIVE_MEMORY&gt;",
                    kwargs["system_prompt"],
                )
                return "Retrying the failed save.", ""

            self.fail(
                "Brain model kept running after delayed-memory failure"
            )

        context = _context()
        state = AgentState(
            user_input="run five runtime steps",
        )
        state.translated_input = state.user_input
        brain_runtime = _brain_runtime()

        with patch(
            "agent.nodes.brain.get_brain_runtime_config",
            return_value=brain_runtime,
        ), patch(
            "agent.nodes.brain.build_brain_context",
            side_effect=lambda current_context, **_kwargs: (
                "system prompt\n"
                + build_tool_results_context(
                    current_context
                )
            ),
        ), patch(
            "agent.nodes.brain.build_brain_payload",
            return_value="brain payload",
        ), patch(
            "agent.nodes.brain.emit_active_memory_records_update_if_dirty",
            new=lambda _context: _async_noop(),
        ), patch.object(
            BrainNode,
            "run_brain_stream",
            staticmethod(fake_run_brain_stream),
        ):
            await BrainNode().run(
                state,
                context,
            )

        self.assertEqual(
            len(calls),
            2,
        )
        self.assertEqual(
            state.brain_response,
            "Retrying the failed save.",
        )

    async def test_validator_interruption_runs_recovery_followup_without_action(self):

        calls = []

        async def fake_run_brain_stream(**kwargs):
            calls.append(kwargs)
            context = kwargs["context"]

            if len(calls) == 1:
                context.runtime_turn_interrupted = True
                context.runtime_turn_interruption_reason = (
                    "Repeated thinking sentence loop detected."
                )
                context.runtime_turn_interruption_quote = (
                    "Wait, I'll use the search marker."
                )
                context.runtime_reasoning_recovery_pending = True
                return "", "looped reasoning"

            if len(calls) == 2:
                self.assertEqual(
                    kwargs["brain_payload"],
                    "",
                )
                self.assertIn(
                    build_reasoning_recovery_context(),
                    kwargs["system_prompt"],
                )
                return "Recovered answer.", ""

            self.fail(
                "Recovery follow-up kept running without a new trigger"
            )

        context = _context()
        context.runtime_current_turn_id = "turn_000002"
        context.runtime_reasoning_recovery_pending = False
        context.runtime_turn_interrupted = False
        context.runtime_turn_interruption_reason = ""
        context.runtime_turn_interruption_quote = ""
        state = AgentState(
            user_input="do the task",
        )
        state.translated_input = state.user_input
        brain_runtime = _brain_runtime()

        with patch(
            "agent.nodes.brain.get_brain_runtime_config",
            return_value=brain_runtime,
        ), patch(
            "agent.nodes.brain.build_brain_context",
            return_value="system prompt",
        ), patch(
            "agent.nodes.brain.emit_active_memory_records_update_if_dirty",
            new=lambda _context: _async_noop(),
        ), patch.object(
            BrainNode,
            "run_brain_stream",
            staticmethod(fake_run_brain_stream),
        ):
            await BrainNode().run(
                state,
                context,
            )

        self.assertEqual(
            len(calls),
            2,
        )
        self.assertEqual(
            state.brain_response,
            "Recovered answer.",
        )
        self.assertFalse(
            context.runtime_reasoning_recovery_pending
        )
        self.assertFalse(
            context.runtime_turn_interrupted
        )

    async def test_context_limit_runs_followup_without_l1_break(self):

        calls = []

        async def fake_run_brain_stream(**kwargs):
            calls.append(kwargs)
            context = kwargs["context"]

            if len(calls) == 1:
                context.runtime_turn_interrupted = True
                context.runtime_turn_interruption_reason = (
                    "Context limit reached during reasoning."
                )
                context.runtime_context_limit_recovery_pending = True
                context.runtime_context_limit_stage = "reasoning"
                context.runtime_context_limit_kind = "output"
                context.runtime_context_limit_finish_reason = "length"
                return "", "long reasoning"

            if len(calls) == 2:
                self.assertEqual(
                    kwargs["brain_payload"],
                    "",
                )
                self.assertIn(
                    build_context_limit_recovery_context(
                        "reasoning",
                        "output",
                    ),
                    kwargs["system_prompt"],
                )
                return "Recovered concise answer.", ""

            self.fail(
                "Context-limit recovery kept running without a new limit"
            )

        context = _context()
        context.runtime_current_turn_id = "turn_000003"
        context.runtime_reasoning_recovery_pending = False
        context.runtime_context_limit_recovery_pending = False
        context.runtime_context_limit_stage = ""
        context.runtime_context_limit_kind = ""
        context.runtime_context_limit_finish_reason = ""
        context.runtime_turn_interrupted = False
        context.runtime_turn_interruption_reason = ""
        context.runtime_turn_interruption_quote = ""
        state = AgentState(
            user_input="do the task",
        )
        state.translated_input = state.user_input
        brain_runtime = _brain_runtime()

        with patch(
            "agent.nodes.brain.get_brain_runtime_config",
            return_value=brain_runtime,
        ), patch(
            "agent.nodes.brain.build_brain_context",
            return_value="system prompt",
        ), patch(
            "agent.nodes.brain.emit_active_memory_records_update_if_dirty",
            new=lambda _context: _async_noop(),
        ), patch.object(
            BrainNode,
            "run_brain_stream",
            staticmethod(fake_run_brain_stream),
        ):
            await BrainNode().run(
                state,
                context,
            )

        self.assertEqual(
            len(calls),
            2,
        )
        self.assertEqual(
            state.brain_response,
            "Recovered concise answer.",
        )
        self.assertFalse(
            context.runtime_context_limit_recovery_pending
        )
        self.assertFalse(
            context.runtime_turn_interrupted
        )

    async def test_same_turn_list_skills_moves_followup_to_system_prompt(self):

        calls = []

        async def fake_run_brain_stream(**kwargs):
            calls.append(kwargs)
            context = kwargs["context"]

            if len(calls) == 1:
                context.runtime_asset_results.append({
                    "ok": True,
                    "action": "list_skills",
                    "runtime_turn_id": "turn_000002",
                    "skills": [
                        {
                            "name": "file_manager",
                            "content": "Manage files.",
                        },
                    ],
                })
                return "", ""

            if len(calls) == 2:
                self.assertEqual(
                    kwargs["brain_payload"],
                    "",
                )
                self.assertTrue(
                    kwargs["system_prompt"].startswith(
                        FOLLOWUP_SYSTEM_MESSAGE
                    ),
                    kwargs["system_prompt"],
                )
                self.assertIn(
                    FOLLOWUP_SYSTEM_MESSAGE,
                    kwargs["system_prompt"],
                )
                return (
                    "I am JIN.",
                    "",
                )

            self.fail(
                "Brain model kept running after list_skills answer"
            )

        context = _context()
        context.runtime_current_turn_id = "turn_000002"
        state = AgentState(
            user_input="tell me about yourself",
        )
        state.translated_input = state.user_input
        brain_runtime = _brain_runtime()

        with patch(
            "agent.nodes.brain.get_brain_runtime_config",
            return_value=brain_runtime,
        ), patch(
            "agent.nodes.brain.build_brain_context",
            return_value="system prompt",
        ), patch(
            "agent.nodes.brain.emit_active_memory_records_update_if_dirty",
            new=lambda _context: _async_noop(),
        ), patch.object(
            BrainNode,
            "run_brain_stream",
            staticmethod(fake_run_brain_stream),
        ):
            await BrainNode().run(
                state,
                context,
            )

        self.assertEqual(
            len(calls),
            2,
        )
        self.assertEqual(
            state.brain_response,
            "I am JIN.",
        )

    async def test_previous_turn_list_skills_uses_followup_system_prompt(self):

        calls = []

        async def fake_run_brain_stream(**kwargs):
            calls.append(kwargs)
            context = kwargs["context"]

            if len(calls) == 1:
                context.runtime_asset_results.append({
                    "ok": True,
                    "action": "list_skills",
                    "runtime_turn_id": "turn_000002",
                    "skills": [
                        {
                            "name": "file_manager",
                            "content": "Manage files.",
                        },
                    ],
                })
                return "", ""

            if len(calls) == 2:
                self.assertEqual(
                    kwargs["brain_payload"],
                    "",
                )
                self.assertTrue(
                    kwargs["system_prompt"].startswith(
                        FOLLOWUP_SYSTEM_MESSAGE
                    ),
                    kwargs["system_prompt"],
                )
                self.assertIn(
                    FOLLOWUP_SYSTEM_MESSAGE,
                    kwargs["system_prompt"],
                )
                return (
                    "I am JIN.",
                    "",
                )

            self.fail(
                "Brain model kept running after list_skills answer"
            )

        context = _context()
        context.runtime_current_turn_id = "turn_000002"
        state = AgentState(
            user_input="tell me about yourself",
        )
        state.translated_input = state.user_input
        brain_runtime = _brain_runtime()

        with patch(
            "agent.nodes.brain.get_brain_runtime_config",
            return_value=brain_runtime,
        ), patch(
            "agent.nodes.brain.build_brain_context",
            return_value="system prompt",
        ), patch(
            "agent.nodes.brain.emit_active_memory_records_update_if_dirty",
            new=lambda _context: _async_noop(),
        ), patch.object(
            BrainNode,
            "run_brain_stream",
            staticmethod(fake_run_brain_stream),
        ):
            await BrainNode().run(
                state,
                context,
            )

        self.assertEqual(
            len(calls),
            2,
        )
        self.assertEqual(
            state.brain_response,
            "I am JIN.",
        )

    async def test_asset_operation_result_is_returned_to_model_before_final_answer(self):

        calls = []
        emitted_reports = []

        async def fake_run_brain_stream(**kwargs):
            calls.append(kwargs)
            context = kwargs["context"]

            if len(calls) == 1:
                context.runtime_asset_results.append({
                    "ok": True,
                    "action": "list_skills",
                    "requested": "",
                    "skills": [
                        {
                            "name": "wildcards",
                            "content": "Use ASSET_ACTION for wildcard files.",
                        },
                    ],
                })
                return "", ""

            if len(calls) == 2:
                self.assertTrue(
                    kwargs["filter_runtime_actions"],
                )
                self.assertTrue(
                    kwargs["runtime_actions"].get("CAN_SAVE_ACTIVE_MEMORY"),
                )
                self.assertTrue(
                    kwargs["runtime_actions"].get("CAN_SAVE_DELAYED_MEMORY"),
                )
                self.assertTrue(
                    kwargs["runtime_actions"].get("CAN_SAVE_SESSION"),
                )
                self.assertTrue(
                    kwargs["runtime_actions"].get("CAN_USE_ASSETS"),
                )
                self.assertTrue(
                    kwargs["emit_content_to_chat"],
                )
                context.runtime_asset_results.append({
                    "ok": True,
                    "action": "create_wildcard_file",
                    "path": "assets/wildcards/clothing/test_bottoms.txt",
                    "line_count": 2,
                    "examples": [
                        "denim shorts",
                        "black skirt",
                    ],
                })
                return "", ""

            if len(calls) == 3:
                self.assertTrue(
                    kwargs["filter_runtime_actions"],
                )
                self.assertTrue(
                    kwargs["emit_content_to_chat"],
                )
                _assert_latest_request_payload(
                    self,
                    kwargs,
                    state.translated_input,
                    "create_wildcard_file",
                )
                self.assertNotIn(
                    "assets/wildcards/clothing/test_bottoms.txt",
                    kwargs["brain_payload"],
                )
                return (
                    "Created `assets/wildcards/clothing/test_bottoms.txt` with 2 lines.",
                    "",
                )

            self.fail("Brain model was called after final asset answer")

        async def fake_emit_brain_text(**kwargs):
            emitted_reports.append(kwargs["text"])
            return kwargs["text"], ""

        context = _context()
        state = AgentState(
            user_input="Create wildcard file clothing/test_bottoms with 2 lines",
        )
        state.translated_input = state.user_input
        brain_runtime = _brain_runtime()

        with patch(
            "agent.nodes.brain.get_brain_runtime_config",
            return_value=brain_runtime,
        ), patch(
            "agent.nodes.brain.build_brain_context",
            return_value="system prompt",
        ), patch(
            "agent.nodes.brain.build_brain_payload",
            return_value="brain payload",
        ), patch(
            "agent.nodes.brain.emit_active_memory_records_update_if_dirty",
            new=lambda _context: _async_noop(),
        ), patch.object(
            BrainNode,
            "run_brain_stream",
            staticmethod(fake_run_brain_stream),
        ), patch.object(
            BrainNode,
            "emit_brain_text",
            staticmethod(fake_emit_brain_text),
        ):
            await BrainNode().run(
                state,
                context,
            )

        self.assertEqual(
            len(calls),
            3,
        )
        self.assertEqual(
            emitted_reports,
            [],
        )
        self.assertEqual(
            state.brain_response,
            "Created `assets/wildcards/clothing/test_bottoms.txt` with 2 lines.",
        )

    async def test_append_skill_result_continues_with_appended_skill_context(self):

        calls = []

        async def fake_run_brain_stream(**kwargs):
            calls.append(kwargs)
            context = kwargs["context"]

            if len(calls) == 1:
                context.runtime_asset_results.append({
                    "ok": True,
                    "action": "list_skills",
                    "requested": "",
                    "skills": [
                        {
                            "name": "wildcards",
                            "path": "assets/skills/wildcards.txt",
                            "line_count": 39,
                        },
                    ],
                })
                return "", ""

            if len(calls) == 2:
                context.runtime_action_events.append({
                    "name": "append_skill",
                    "payload": "wildcards",
                })
                context.runtime_appended_skills.append({
                    "name": "wildcards",
                    "path": "assets/skills/wildcards.txt",
                    "line_count": 39,
                    "content": "Use ASSET_ACTION for wildcard files.",
                })
                return "", ""

            if len(calls) == 3:
                _assert_latest_request_payload(
                    self,
                    kwargs,
                    state.translated_input,
                    'APPEND_SKILL',
                )
                return (
                    "Ready to use the wildcard skill.",
                    "",
                )

            self.fail("Brain model kept running after appended skill answer")

        context = _context()
        state = AgentState(
            user_input="create a wildcard file",
        )
        state.translated_input = state.user_input
        brain_runtime = _brain_runtime()

        with patch(
            "agent.nodes.brain.get_brain_runtime_config",
            return_value=brain_runtime,
        ), patch(
            "agent.nodes.brain.build_brain_context",
            return_value="system prompt",
        ), patch(
            "agent.nodes.brain.build_brain_payload",
            return_value="brain payload",
        ), patch(
            "agent.nodes.brain.emit_active_memory_records_update_if_dirty",
            new=lambda _context: _async_noop(),
        ), patch.object(
            BrainNode,
            "run_brain_stream",
            staticmethod(fake_run_brain_stream),
        ):
            await BrainNode().run(
                state,
                context,
            )

        self.assertEqual(
            len(calls),
            3,
        )
        self.assertEqual(
            state.brain_response,
            "Ready to use the wildcard skill.",
        )

    async def test_append_skill_visible_answer_triggers_followup(self):

        calls = []

        async def fake_run_brain_stream(**kwargs):
            calls.append(kwargs)
            context = kwargs["context"]

            if len(calls) == 1:
                context.runtime_action_events.append({
                    "name": "append_skill",
                    "payload": "wildcards",
                })
                context.runtime_appended_skills.append({
                    "name": "wildcards",
                    "path": "assets/skills/wildcards.txt",
                    "line_count": 39,
                    "content": "Use ASSET_ACTION for wildcard files.",
                })
                return (
                    "I've loaded the wildcards skill. Ready to test.",
                    "",
                )

            if len(calls) == 2:
                _assert_latest_request_payload(
                    self,
                    kwargs,
                    state.translated_input,
                    'APPEND_SKILL',
                )
                return (
                    "Ready to test with the wildcards skill loaded.",
                    "",
                )

            self.fail("Brain model kept running after visible append answer")

        context = _context()
        state = AgentState(
            user_input="load the wildcards skill",
        )
        state.translated_input = state.user_input
        brain_runtime = _brain_runtime()

        with patch(
            "agent.nodes.brain.get_brain_runtime_config",
            return_value=brain_runtime,
        ), patch(
            "agent.nodes.brain.build_brain_context",
            return_value="system prompt",
        ), patch(
            "agent.nodes.brain.build_brain_payload",
            return_value="brain payload",
        ), patch(
            "agent.nodes.brain.emit_active_memory_records_update_if_dirty",
            new=lambda _context: _async_noop(),
        ), patch.object(
            BrainNode,
            "run_brain_stream",
            staticmethod(fake_run_brain_stream),
        ):
            await BrainNode().run(
                state,
                context,
            )

        self.assertEqual(
            len(calls),
            2,
        )
        self.assertEqual(
            state.brain_response,
            "Ready to test with the wildcards skill loaded.",
        )

    async def test_streamed_list_skills_append_skills_reaches_final_followup(self):

        class FakeBrainClient:

            def __init__(self):
                self.calls = 0
                self.system_prompts = []

            async def stream(self, **_kwargs):
                self.calls += 1
                self.system_prompts.append(
                    _kwargs.get(
                        "system_prompt",
                        "",
                    )
                )

                if self.calls == 1:
                    yield {
                        "type": "content",
                        "content": (
                            "Need the available skills first. "
                            "<LIST_SKILLS>"
                        ),
                    }
                    return

                if self.calls == 2:
                    yield {
                        "type": "content",
                        "content": (
                            "Append the requested skills. "
                            "<APPEND_SKILL: chunk_reader>\n"
                            "<APPEND_SKILL: image_prompt_generator>"
                        ),
                    }
                    return

                yield {
                    "type": "content",
                    "content": "Ready.",
                }

        class FakeWebSocket:

            def __init__(self):
                self.events = []

            async def send_json(self, payload):
                self.events.append(payload)

        class FakeEmitter:

            def __init__(self):
                self.events = []

            async def emit(self, payload):
                self.events.append(payload)

        class FakeLogger:

            async def log_runtime(self, *_args, **_kwargs):
                return None

            async def log_validator(self, *_args, **_kwargs):
                return None

            async def log_error(self, *_args, **_kwargs):
                return None

            async def log_brain(self, *_args, **_kwargs):
                return None

            async def log(self, *_args, **_kwargs):
                return None

            async def log_system(self, *_args, **_kwargs):
                return None

        def write_skill(root, name, content):
            path = (
                root
                / "assets"
                / "skills"
                / name
            )
            path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            path.write_text(
                content,
                encoding="utf-8",
            )

        fake_client = FakeBrainClient()
        websocket = FakeWebSocket()
        emitter = FakeEmitter()
        user_input = (
            "посмотри скилы, сделай апенд chunk_reader "
            "и image_prompt_generator"
        )
        context = SimpleNamespace(
            logger=FakeLogger(),
            websocket=websocket,
            emitter=emitter,
            clients={
                "brain": fake_client,
            },
            active_streams={},
            runtime_search_queries=[],
            runtime_search_calls=[],
            runtime_search_result="",
            runtime_search_result_id="",
            runtime_asset_results=[],
            runtime_asset_retry_results=[],
            runtime_asset_retry_context=[],
            runtime_delayed_memory_results=[],
            runtime_appended_skills=[],
            runtime_action_events=[],
            runtime_tool_results=[],
            runtime_tool_results_turn_count=0,
            runtime_tool_results_generation=0,
            runtime_current_turn_id="turn_000001",
            runtime_current_sequence_turn_id="turn_000001",
            runtime_turn_started_at=1,
            runtime_current_sequence_started_at=1,
            runtime_turn_user_message=user_input,
            runtime_turn_abort_requested=False,
            runtime_turn_interrupted=False,
            runtime_reasoning_recovery_pending=False,
            runtime_context_limit_recovery_pending=False,
            runtime_active_action_markers=[],
            runtime_session_action_history=[],
            runtime_turn_attachments=[],
            runtime_current_sequence_attachments=[],
            runtime_current_sequence_attachments_turn_id="turn_000001",
            runtime_save_session_requested=False,
            runtime_memory="",
            runtime_memory_stable="",
            runtime_token_usage={},
            runtime_provider_token_usage={},
            active_memory_records=[],
            background_tasks=set(),
        )
        state = AgentState(
            user_input=user_input,
        )
        state.translated_input = state.user_input

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in patch_asset_roots(root):
                    stack.enter_context(patcher)

                write_skill(
                    root,
                    "chunk_reader.txt",
                    "chunk_reader\nRead large files in chunks.",
                )
                write_skill(
                    root,
                    "image_prompt_generator.txt",
                    "image_prompt_generator\nGenerate image prompts.",
                )

                with patch(
                    "agent.nodes.brain.get_brain_runtime_config",
                    return_value=_brain_runtime(),
                ), patch(
                    "agent.nodes.brain.build_brain_context",
                    side_effect=lambda current_context, **_kwargs: (
                        "system prompt\n"
                        + build_tool_results_context(
                            current_context
                        )
                    ),
                ), patch(
                    "agent.nodes.brain.build_brain_payload",
                    return_value="brain payload",
                ), patch(
                    "agent.nodes.brain.emit_active_memory_records_update_if_dirty",
                    new=lambda _context: _async_noop(),
                ), patch(
                    "runtime.stream.refresh_runtime_state",
                    new=lambda *_args, **_kwargs: _async_noop(),
                ), patch(
                    "runtime.stream.record_stream_token_usage",
                    new=lambda *_args, **_kwargs: None,
                ):
                    await BrainNode().run(
                        state,
                        context,
                    )

        self.assertEqual(
            fake_client.calls,
            3,
        )
        self.assertIn(
            "LIST_SKILLS",
            fake_client.system_prompts[1],
        )
        self.assertIn(
            "chunk_reader",
            fake_client.system_prompts[1],
        )
        self.assertIn(
            "APPEND_SKILL",
            fake_client.system_prompts[2],
        )
        self.assertIn(
            "image_prompt_generator",
            fake_client.system_prompts[2],
        )
        self.assertEqual(
            state.brain_response,
            "Ready.",
        )
        self.assertEqual(
            [
                event["name"]
                for event in context.runtime_action_events
            ],
            [
                "list_skills",
                "append_skill",
                "append_skill",
            ],
        )
        self.assertEqual(
            [
                entry["result"]["action"]
                for entry in context.runtime_tool_results
                if entry.get("kind") == TOOL_RESULT_KIND_ASSET
            ],
            [
                "list_skills",
            ],
        )
        self.assertEqual(
            [
                skill["name"]
                for skill in context.runtime_appended_skills
            ],
            [
                "chunk_reader",
                "image_prompt_generator",
            ],
        )

    async def test_list_skills_followup_survives_current_turn_id_shift(self):

        class FakeBrainClient:

            def __init__(self):
                self.calls = 0

            async def stream(self, **kwargs):
                self.calls += 1

                if self.calls == 1:
                    yield {
                        "type": "content",
                        "content": (
                            "Need available skills. "
                            "<LIST_SKILLS> trailing text"
                        ),
                    }
                    kwargs["context"].runtime_current_turn_id = (
                        "turn_changed_after_list_skills"
                    )
                    return

                yield {
                    "type": "content",
                    "content": "Follow-up continued.",
                }

        class FakeWebSocket:

            async def send_json(self, _payload):
                return None

        class FakeEmitter:

            async def emit(self, _payload):
                return None

        class FakeLogger:

            async def log_runtime(self, *_args, **_kwargs):
                return None

            async def log_validator(self, *_args, **_kwargs):
                return None

            async def log_error(self, *_args, **_kwargs):
                return None

            async def log_brain(self, *_args, **_kwargs):
                return None

            async def log_service_as_brain(self, *_args, **_kwargs):
                return None

            async def log_service_as_brain_output(self, *_args, **_kwargs):
                return None

            async def log_flow(self, *_args, **_kwargs):
                return None

            async def log(self, *_args, **_kwargs):
                return None

            async def log_system(self, *_args, **_kwargs):
                return None

        fake_client = FakeBrainClient()
        context = RuntimeContext(
            websocket=FakeWebSocket(),
            emitter=FakeEmitter(),
            logger=FakeLogger(),
            clients={
                "brain": fake_client,
                "service": fake_client,
            },
        )
        context.runtime_current_turn_id = "turn_000001"
        context.runtime_current_sequence_turn_id = "turn_000001"
        context.runtime_turn_started_at = 1
        context.runtime_current_sequence_started_at = 1
        context.runtime_turn_user_message = (
            "посмотри скилы, потом продолжай"
        )

        state = AgentState(
            user_input=context.runtime_turn_user_message,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in patch_asset_roots(root):
                    stack.enter_context(patcher)

                skill_path = (
                    root
                    / "assets"
                    / "skills"
                    / "chunk_reader.txt"
                )
                skill_path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )
                skill_path.write_text(
                    "chunk_reader\nRead large files.",
                    encoding="utf-8",
                )

                await AgentRuntime().run(
                    state,
                    context,
                )

        self.assertEqual(
            fake_client.calls,
            2,
        )
        self.assertEqual(
            state.final_answer,
            "Follow-up continued.",
        )
        self.assertEqual(
            context.runtime_action_events[0]["name"],
            "list_skills",
        )
        self.assertEqual(
            context.runtime_action_events[0]["runtime_turn_id"],
            "turn_000001",
        )
        self.assertEqual(
            context.runtime_current_turn_id,
            "turn_changed_after_list_skills",
        )
        self.assertEqual(
            context.runtime_asset_results[0]["action"],
            "list_skills",
        )

    async def test_asset_workflow_can_continue_after_create_file_to_prompt_batch(self):

        calls = []
        emitted_reports = []

        async def fake_run_brain_stream(**kwargs):
            calls.append(kwargs)
            context = kwargs["context"]

            if len(calls) == 1:
                context.runtime_asset_results.append({
                    "ok": True,
                    "action": "list_skills",
                    "requested": "",
                    "skills": [
                        {
                            "name": "wildcards",
                            "content": "Use ASSET_ACTION for wildcard files.",
                        },
                    ],
                })
                return "", ""

            if len(calls) == 2:
                context.runtime_asset_results.append({
                    "ok": True,
                    "action": "create_wildcard_file",
                    "path": "assets/wildcards/clothing/shoes.txt",
                    "line_count": 10,
                    "examples": [
                        "sneakers",
                        "boots",
                        "heels",
                    ],
                })
                return "", ""

            if len(calls) == 3:
                _assert_latest_request_payload(
                    self,
                    kwargs,
                    state.translated_input,
                    "create_wildcard_file",
                )
                self.assertNotIn(
                    "assets/wildcards/clothing/shoes.txt",
                    kwargs["brain_payload"],
                )
                self.assertTrue(
                    kwargs["runtime_actions"].get("CAN_USE_ASSETS"),
                )
                self.assertTrue(
                    kwargs["emit_content_to_chat"],
                )
                context.runtime_asset_results.append({
                    "ok": True,
                    "action": "generate_prompt_batch",
                    "path": "assets/prompts/test_prompts.txt",
                    "line_count": 10,
                    "examples": [
                        "photo of a woman wearing linen shirt and black skirt and boots, studio lighting",
                    ],
                })
                return "", ""

            if len(calls) == 4:
                _assert_latest_request_payload(
                    self,
                    kwargs,
                    state.translated_input,
                    "generate_prompt_batch",
                )
                self.assertNotIn(
                    "assets/prompts/test_prompts.txt",
                    kwargs["brain_payload"],
                )
                return (
                    "Created shoes wildcard and generated `assets/prompts/test_prompts.txt` with 10 prompts.",
                    "",
                )

            self.fail("Brain model kept running after final multi-step answer")

        async def fake_emit_brain_text(**kwargs):
            emitted_reports.append(kwargs["text"])
            return kwargs["text"], ""

        context = _context()
        state = AgentState(
            user_input=(
                "Create a shoes wildcard file, then generate 10 prompts "
                "using tops, bottoms, and shoes."
            ),
        )
        state.translated_input = state.user_input
        brain_runtime = _brain_runtime()

        with patch(
            "agent.nodes.brain.get_brain_runtime_config",
            return_value=brain_runtime,
        ), patch(
            "agent.nodes.brain.build_brain_context",
            return_value="system prompt",
        ), patch(
            "agent.nodes.brain.build_brain_payload",
            return_value="brain payload",
        ), patch(
            "agent.nodes.brain.emit_active_memory_records_update_if_dirty",
            new=lambda _context: _async_noop(),
        ), patch.object(
            BrainNode,
            "run_brain_stream",
            staticmethod(fake_run_brain_stream),
        ), patch.object(
            BrainNode,
            "emit_brain_text",
            staticmethod(fake_emit_brain_text),
        ):
            await BrainNode().run(
                state,
                context,
            )

        self.assertEqual(
            len(calls),
            4,
        )
        self.assertEqual(
            emitted_reports,
            [],
        )
        self.assertEqual(
            state.brain_response,
            "Created shoes wildcard and generated `assets/prompts/test_prompts.txt` with 10 prompts.",
        )

    async def test_list_wildcards_result_can_continue_to_next_asset_action(self):

        calls = []
        emitted_reports = []

        async def fake_run_brain_stream(**kwargs):
            calls.append(kwargs)
            context = kwargs["context"]

            if len(calls) == 1:
                context.runtime_asset_results.append({
                    "ok": True,
                    "action": "list_skills",
                    "requested": "",
                    "skills": [
                        {
                            "name": "wildcards",
                            "content": "Use ASSET_ACTION for wildcard files.",
                        },
                    ],
                })
                return "", ""

            if len(calls) == 2:
                context.runtime_asset_results.append({
                    "ok": True,
                    "action": "list_wildcards",
                    "wildcards": [
                        {
                            "path": "assets/wildcards/clothing/test_tops.txt",
                            "wildcard": "clothing/test_tops",
                            "line_count": 10,
                        },
                        {
                            "path": "assets/wildcards/clothing/test_bottoms.txt",
                            "wildcard": "clothing/test_bottoms",
                            "line_count": 10,
                        },
                    ],
                })
                return "", ""

            if len(calls) == 3:
                self.assertTrue(
                    kwargs["runtime_actions"].get("CAN_USE_ASSETS"),
                )
                self.assertTrue(
                    kwargs["runtime_actions"].get("CAN_WEB_SEARCH"),
                )
                self.assertTrue(
                    kwargs["emit_content_to_chat"],
                )
                context.runtime_asset_results.append({
                    "ok": True,
                    "action": "generate_prompt_batch",
                    "path": "assets/prompts/test_prompts.txt",
                    "line_count": 20,
                    "examples": [
                        "photo of a woman wearing silk top and jeans, studio lighting",
                    ],
                })
                return "", ""

            if len(calls) == 4:
                _assert_latest_request_payload(
                    self,
                    kwargs,
                    state.translated_input,
                    "generate_prompt_batch",
                )
                self.assertNotIn(
                    "assets/prompts/test_prompts.txt",
                    kwargs["brain_payload"],
                )
                return (
                    "Created prompt batch `assets/prompts/test_prompts.txt` with 20 lines.",
                    "",
                )

            self.fail("Brain model was called after final prompt batch answer")

        async def fake_emit_brain_text(**kwargs):
            emitted_reports.append(kwargs["text"])
            return kwargs["text"], ""

        context = _context()
        state = AgentState(
            user_input=(
                "generate 20 prompts from clothing wildcards "
                "and save test_prompts.txt"
            ),
        )
        state.translated_input = state.user_input
        brain_runtime = _brain_runtime()

        with patch(
            "agent.nodes.brain.get_brain_runtime_config",
            return_value=brain_runtime,
        ), patch(
            "agent.nodes.brain.build_brain_context",
            return_value="system prompt",
        ), patch(
            "agent.nodes.brain.build_brain_payload",
            return_value="brain payload",
        ), patch(
            "agent.nodes.brain.emit_active_memory_records_update_if_dirty",
            new=lambda _context: _async_noop(),
        ), patch.object(
            BrainNode,
            "run_brain_stream",
            staticmethod(fake_run_brain_stream),
        ), patch.object(
            BrainNode,
            "emit_brain_text",
            staticmethod(fake_emit_brain_text),
        ):
            await BrainNode().run(
                state,
                context,
            )

        self.assertEqual(
            len(calls),
            4,
        )
        self.assertEqual(
            emitted_reports,
            [],
        )
        self.assertEqual(
            state.brain_response,
            "Created prompt batch `assets/prompts/test_prompts.txt` with 20 lines.",
        )


    async def test_idle_action_never_triggers_immediate_follow_up(self):

        self.assertFalse(
            action_batch_requires_follow_up(
                [
                    {
                        "name": "idle",
                        "seconds": 0,
                        "deferred_follow_up": True,
                    },
                ],
                "",
            )
        )

        self.assertFalse(
            action_batch_requires_follow_up(
                [
                    {
                        "name": "idle",
                        "seconds": 1,
                        "deferred_follow_up": True,
                    },
                    {
                        "name": "idle",
                        "seconds": 2,
                        "deferred_follow_up": True,
                    },
                ],
                "",
            )
        )

    async def test_idle_runtime_turn_restores_sequence_origin_and_history(self):

        calls = []

        async def fake_run_brain_stream(**kwargs):
            calls.append(kwargs)
            return "Sequence complete.", ""

        origin_request = (
            "first idle 30s, then idle 20s and search"
        )
        context = _context()
        context.runtime_current_turn_id = "idle_000002"
        context.runtime_current_sequence_turn_id = "turn_000001"
        context.runtime_turn_started_at = 1030.0
        context.runtime_current_sequence_started_at = 1000.0
        context.runtime_turn_user_message = origin_request
        context.runtime_action_sequence_turn_ids = []
        context.runtime_session_action_history = [
            {
                "text": "IDLE - 30s",
                "created_at": 1000.0,
                "runtime_turn_id": "turn_000001",
            },
        ]
        context.runtime_recent_turns = []
        context.runtime_appended_delayed_memory = {}

        state = AgentState(
            user_input=origin_request,
        )
        state.translated_input = origin_request
        state.metadata["idle_followup"] = {
            "id": "idle_001",
            "seconds": 30,
            "origin_user_request": origin_request,
            "context_snapshot": {
                "system_prompt": (
                    "<SEQUENCE_ORIGIN_REQUEST>stale</SEQUENCE_ORIGIN_REQUEST>\n"
                    "<CURRENT_SEQUENCE>stale</CURRENT_SEQUENCE>\n"
                    "<PREVIOUS_CHAT_MESSAGES>stale</PREVIOUS_CHAT_MESSAGES>\n"
                    "<RUNTIME_MEMORY>frozen state</RUNTIME_MEMORY>"
                ),
            },
        }

        with patch(
            "agent.nodes.brain.get_brain_runtime_config",
            return_value=_brain_runtime(),
        ), patch(
            "agent.nodes.brain.emit_active_memory_records_update_if_dirty",
            new=lambda _context: _async_noop(),
        ), patch.object(
            BrainNode,
            "run_brain_stream",
            staticmethod(fake_run_brain_stream),
        ), patch(
            "utils.context.context_exports.time.time",
            return_value=1030.0,
        ):
            await BrainNode().run(
                state,
                context,
            )

        self.assertEqual(
            len(calls),
            1,
        )
        prompt = calls[0]["system_prompt"]
        idle_instruction = (
            "This is a follow-up tick from an IDLE timer JIN chose to set."
        )
        self.assertEqual(
            prompt.count(idle_instruction),
            1,
            prompt,
        )
        self.assertLess(
            prompt.index(
                "This is follow-up tick for JIN latest action: idle."
            ),
            prompt.index(idle_instruction),
        )
        self.assertLess(
            prompt.index(idle_instruction),
            prompt.index("<CURRENT_SEQUENCE>"),
        )
        self.assertLess(
            prompt.index("<CURRENT_SEQUENCE>"),
            prompt.index("<TOOLS_RESULTS>"),
        )
        self.assertEqual(
            prompt.count("<SEQUENCE_ORIGIN_REQUEST>"),
            0,
            prompt,
        )
        self.assertEqual(
            prompt.count("<CURRENT_SEQUENCE>"),
            1,
            prompt,
        )
        self.assertEqual(
            prompt.count("<PREVIOUS_CHAT_MESSAGES>"),
            0,
            prompt,
        )
        self.assertIn(
            origin_request + " ( 30s ago )",
            prompt,
        )
        self.assertIn(
            "JIN message 1 executed: IDLE: 30s ( 30s ago )",
            prompt,
        )
        self.assertNotIn(
            ">stale<",
            prompt,
        )

    async def test_idle_followup_prompt_contains_tool_result_and_frozen_context(self):

        prompt = build_idle_followup_system_prompt({
            "id": "idle_1",
            "seconds": 5,
            "origin_user_request": "original request",
            "source_message": "reason <IDLE: 5s />",
            "context_snapshot": {
                "system_prompt": (
                    "<RUNTIME_MEMORY>frozen state</RUNTIME_MEMORY>"
                ),
            },
        })

        self.assertIn(
            '<TOOL_RESULTS type="idle">',
            prompt,
        )
        self.assertNotIn(
            "original request",
            prompt,
        )
        self.assertNotIn(
            "reason &lt;IDLE: 5s /&gt;",
            prompt,
        )
        self.assertTrue(
            prompt.startswith(
                "<TOOLS_RESULTS>"
            ),
            prompt,
        )
        self.assertEqual(
            prompt.count(
                "<TOOLS_RESULTS>"
            ),
            1,
        )
        self.assertIn(
            "<PREVIOUS_RUNTIME_MEMORY>frozen state</PREVIOUS_RUNTIME_MEMORY>",
            prompt,
        )

    async def test_no_follow_up_action_without_visible_answer_does_not_trigger_tick(self):

        calls = []

        async def fake_run_brain_stream(**kwargs):
            calls.append(kwargs)

            if len(calls) == 1:
                kwargs["context"].runtime_action_events.append({
                    "name": "clean_tool_results",
                })
                return "", ""

            return "Unexpected follow-up.", ""

        context = _context()
        state = AgentState(
            user_input="clear search results",
        )
        state.translated_input = state.user_input

        with patch(
            "agent.nodes.brain.get_brain_runtime_config",
            return_value=_brain_runtime(),
        ), patch(
            "agent.nodes.brain.build_brain_context",
            return_value="system prompt",
        ), patch(
            "agent.nodes.brain.build_brain_payload",
            return_value="brain payload",
        ), patch(
            "agent.nodes.brain.emit_active_memory_records_update_if_dirty",
            new=lambda _context: _async_noop(),
        ), patch.object(
            BrainNode,
            "run_brain_stream",
            staticmethod(fake_run_brain_stream),
        ):
            await BrainNode().run(
                state,
                context,
            )

        self.assertEqual(
            len(calls),
            1,
        )
        self.assertEqual(
            state.brain_response,
            "",
        )

    async def test_no_follow_up_action_keeps_visible_answer_without_tick(self):

        calls = []

        async def fake_run_brain_stream(**kwargs):
            calls.append(kwargs)
            kwargs["context"].runtime_action_events.append({
                "name": "clean_tool_results",
            })
            return "Done. Search results have been cleared.", ""

        context = _context()
        state = AgentState(
            user_input="clear search results",
        )
        state.translated_input = state.user_input

        with patch(
            "agent.nodes.brain.get_brain_runtime_config",
            return_value=_brain_runtime(),
        ), patch(
            "agent.nodes.brain.build_brain_context",
            return_value="system prompt",
        ), patch(
            "agent.nodes.brain.build_brain_payload",
            return_value="brain payload",
        ), patch(
            "agent.nodes.brain.emit_active_memory_records_update_if_dirty",
            new=lambda _context: _async_noop(),
        ), patch.object(
            BrainNode,
            "run_brain_stream",
            staticmethod(fake_run_brain_stream),
        ):
            await BrainNode().run(
                state,
                context,
            )

        self.assertEqual(
            len(calls),
            1,
        )
        self.assertEqual(
            state.brain_response,
            "Done. Search results have been cleared.",
        )
        self.assertFalse(
            action_event_requires_follow_up({
                "name": "clean_tool_results",
            })
        )
        self.assertFalse(
            action_event_requires_follow_up({
                "name": "jin_color",
            })
        )
        self.assertTrue(
            action_event_requires_follow_up({
                "name": "web_search",
            })
        )
        self.assertFalse(
            action_event_requires_follow_up({
                "name": "web_search",
                "status": "aborted",
            })
        )
        self.assertFalse(
            action_batch_requires_follow_up(
                [
                    {
                        "name": "clean_tool_results",
                    },
                    {
                        "name": "clean_tool_results",
                    },
                ],
                "",
            )
        )

    async def test_no_follow_up_action_batch_stops_without_tick(self):

        calls = []

        async def fake_run_brain_stream(**kwargs):
            calls.append(kwargs)

            if len(calls) == 1:
                kwargs["context"].runtime_action_events.extend([
                    {
                        "name": "clean_tool_results",
                    },
                    {
                        "name": "resolve_active_memory",
                        "id": "active_memory_1",
                    },
                ])
                return "First action batch processed.", ""

            return "Workflow complete.", ""

        context = _context()
        state = AgentState(
            user_input="clear results and create memory",
        )
        state.translated_input = state.user_input

        with patch(
            "agent.nodes.brain.get_brain_runtime_config",
            return_value=_brain_runtime(),
        ), patch(
            "agent.nodes.brain.build_brain_context",
            return_value="system prompt",
        ), patch(
            "agent.nodes.brain.build_brain_payload",
            return_value="brain payload",
        ), patch(
            "agent.nodes.brain.emit_active_memory_records_update_if_dirty",
            new=lambda _context: _async_noop(),
        ), patch.object(
            BrainNode,
            "run_brain_stream",
            staticmethod(fake_run_brain_stream),
        ):
            await BrainNode().run(
                state,
                context,
            )

        self.assertEqual(
            len(calls),
            1,
        )
        self.assertEqual(
            state.brain_response,
            "First action batch processed.",
        )


    async def test_follow_up_action_messages_keep_actions_enabled(self):

        calls = []
        action_names = [
            "append_skill",
            "list_skills",
            "check_todo",
        ]

        async def fake_run_brain_stream(**kwargs):
            calls.append(kwargs)
            context = kwargs["context"]
            call_index = len(calls)

            if call_index <= len(action_names):
                action_name = action_names[call_index - 1]
                context.runtime_action_events.append({
                    "name": action_name,
                    "payload": f"payload_{call_index}",
                })
                return "", ""

            self.assertEqual(
                kwargs["runtime_actions"],
                _brain_runtime()["runtime_actions"],
            )
            return "Finished all action steps.", ""

        context = _context()
        state = AgentState(
            user_input="emit several different runtime actions",
        )
        state.translated_input = state.user_input
        brain_runtime = _brain_runtime()

        with patch(
            "agent.nodes.brain.get_brain_runtime_config",
            return_value=brain_runtime,
        ), patch(
            "agent.nodes.brain.build_brain_context",
            return_value="system prompt",
        ), patch(
            "agent.nodes.brain.build_brain_payload",
            return_value="brain payload",
        ), patch(
            "agent.nodes.brain.emit_active_memory_records_update_if_dirty",
            new=lambda _context: _async_noop(),
        ), patch.object(
            BrainNode,
            "run_brain_stream",
            staticmethod(fake_run_brain_stream),
        ):
            await BrainNode().run(
                state,
                context,
            )

        self.assertEqual(
            len(calls),
            4,
        )
        self.assertIn(
            'APPEND_SKILL',
            calls[1]["system_prompt"],
        )
        self.assertIn(
            'LIST_SKILLS',
            calls[2]["system_prompt"],
        )
        self.assertIn(
            'CHECK_TODO',
            calls[3]["system_prompt"],
        )
        for call in calls[1:]:
            self.assertEqual(
                call["brain_payload"],
                "",
            )
        for call in calls[1:]:
            self.assertEqual(
                call["runtime_actions"],
                brain_runtime["runtime_actions"],
            )
        self.assertEqual(
            state.brain_response,
            "Finished all action steps.",
        )

    async def test_multiple_actions_in_one_message_use_one_followup_tick(self):

        calls = []

        async def fake_run_brain_stream(**kwargs):
            calls.append(kwargs)
            context = kwargs["context"]

            if len(calls) == 1:
                context.runtime_action_events.extend([
                    {
                        "name": "append_skill",
                        "payload": "first",
                    },
                    {
                        "name": "resolve_active_memory",
                        "id": "active_memory_1",
                    },
                ])
                return "", ""

            self.assertIn(
                'APPEND_SKILL',
                kwargs["system_prompt"],
            )
            self.assertIn(
                'RESOLVE_ACTIVE_MEMORY',
                kwargs["system_prompt"],
            )
            self.assertNotIn(
                'payload=',
                kwargs["system_prompt"],
            )
            self.assertNotIn(
                'id=',
                kwargs["system_prompt"],
            )
            self.assertNotIn(
                'active_memory_1',
                kwargs["system_prompt"],
            )
            self.assertEqual(
                kwargs["brain_payload"],
                "",
            )
            return "Finished.", ""

        context = _context()
        state = AgentState(
            user_input="run two actions in one message",
        )
        state.translated_input = state.user_input
        brain_runtime = _brain_runtime()

        with patch(
            "agent.nodes.brain.get_brain_runtime_config",
            return_value=brain_runtime,
        ), patch(
            "agent.nodes.brain.build_brain_context",
            return_value="system prompt",
        ), patch(
            "agent.nodes.brain.build_brain_payload",
            return_value="brain payload",
        ), patch(
            "agent.nodes.brain.emit_active_memory_records_update_if_dirty",
            new=lambda _context: _async_noop(),
        ), patch.object(
            BrainNode,
            "run_brain_stream",
            staticmethod(fake_run_brain_stream),
        ):
            await BrainNode().run(
                state,
                context,
            )

        self.assertEqual(
            len(calls),
            2,
        )
        self.assertEqual(
            state.brain_response,
            "Finished.",
        )

    async def test_one_step_tool_result_remains_after_sequence(self):

        calls = []

        async def fake_run_brain_stream(**kwargs):
            calls.append(kwargs)
            context = kwargs["context"]

            if len(calls) == 1:
                record_runtime_tool_result(
                    context,
                    TOOL_RESULT_KIND_ASSET,
                    {
                        "ok": True,
                        "action": "list_skills",
                        "skills": [],
                    },
                )
                context.runtime_action_events.append({
                    "name": "list_skills",
                })
                return "", ""

            return "Finished.", ""

        context = _context()
        state = AgentState(
            user_input="inspect available skills",
        )
        state.translated_input = state.user_input

        with patch(
            "agent.nodes.brain.get_brain_runtime_config",
            return_value=_brain_runtime(),
        ), patch(
            "agent.nodes.brain.build_brain_context",
            return_value="system prompt",
        ), patch(
            "agent.nodes.brain.build_brain_payload",
            return_value="brain payload",
        ), patch(
            "agent.nodes.brain.emit_active_memory_records_update_if_dirty",
            new=lambda _context: _async_noop(),
        ), patch.object(
            BrainNode,
            "run_brain_stream",
            staticmethod(fake_run_brain_stream),
        ):
            await BrainNode().run(
                state,
                context,
            )

        self.assertEqual(
            len(context.runtime_tool_results),
            1,
        )
        self.assertEqual(
            context.runtime_tool_results[0]["result"]["action"],
            "list_skills",
        )

    async def test_multi_step_tool_results_remain_after_sequence(self):

        calls = []

        async def fake_run_brain_stream(**kwargs):
            calls.append(kwargs)
            context = kwargs["context"]

            if len(calls) == 1:
                record_runtime_tool_result(
                    context,
                    TOOL_RESULT_KIND_ASSET,
                    {
                        "ok": True,
                        "action": "list_skills",
                        "skills": [],
                    },
                )
                context.runtime_action_events.append({
                    "name": "list_skills",
                })
                return "", ""

            if len(calls) == 2:
                record_runtime_tool_result(
                    context,
                    TOOL_RESULT_KIND_ASSET,
                    {
                        "ok": True,
                        "action": "read_asset_file",
                        "content": "skill content",
                    },
                )
                context.runtime_action_events.append({
                    "name": "asset_action",
                })
                return "", ""

            return "Finished.", ""

        context = _context()
        state = AgentState(
            user_input="inspect and read the skill",
        )
        state.translated_input = state.user_input

        with patch(
            "agent.nodes.brain.get_brain_runtime_config",
            return_value=_brain_runtime(),
        ), patch(
            "agent.nodes.brain.build_brain_context",
            return_value="system prompt",
        ), patch(
            "agent.nodes.brain.build_brain_payload",
            return_value="brain payload",
        ), patch(
            "agent.nodes.brain.emit_active_memory_records_update_if_dirty",
            new=lambda _context: _async_noop(),
        ), patch.object(
            BrainNode,
            "run_brain_stream",
            staticmethod(fake_run_brain_stream),
        ):
            await BrainNode().run(
                state,
                context,
            )

        self.assertEqual(
            len(calls),
            3,
        )
        self.assertEqual(
            len(context.runtime_tool_results),
            2,
        )
        self.assertEqual(
            [
                entry["result"]["action"]
                for entry in context.runtime_tool_results
            ],
            [
                "list_skills",
                "read_asset_file",
            ],
        )
        self.assertEqual(
            context.runtime_asset_results,
            [],
        )

    async def test_followup_limit_runs_final_non_executable_tick(self):

        calls = []
        runtime_logs = []
        websocket_events = []

        class Logger:

            async def log_runtime(self, message):
                runtime_logs.append(message)

        class Websocket:

            async def send_json(self, payload):
                websocket_events.append(payload)

        async def fake_run_brain_stream(**kwargs):
            calls.append(kwargs)
            context = kwargs["context"]

            if len(calls) <= 3:
                context.runtime_asset_results.append({
                    "ok": True,
                    "action": "append_wildcard_file",
                    "path": "assets/outputs/long_task.txt",
                })
                return "", ""

            self.assertFalse(
                kwargs["filter_runtime_actions"]
            )
            self.assertTrue(
                kwargs["preserve_runtime_action_markers"]
            )
            self.assertTrue(
                all(
                    value is False
                    for value in kwargs["runtime_actions"].values()
                )
            )
            self.assertIn(
                "<FOLLOWUP_LIMIT_REACHED>",
                kwargs["system_prompt"],
            )
            self.assertLess(
                kwargs["system_prompt"].index(
                    "<FOLLOWUP_LIMIT_REACHED>"
                ),
                kwargs["system_prompt"].index(
                    "<CURRENT_SEQUENCE>"
                ),
            )
            self.assertLess(
                kwargs["system_prompt"].index(
                    "<CURRENT_SEQUENCE>"
                ),
                kwargs["system_prompt"].index(
                    "<TOOLS_RESULTS>"
                ),
            )
            return "<ASSET_ACTION>still pending</ASSET_ACTION>", ""

        context = _context()
        context.logger = Logger()
        context.websocket = Websocket()
        context.runtime_current_turn_id = "turn_limit"

        state = AgentState(
            user_input="run a long task",
        )
        state.translated_input = state.user_input
        brain_runtime = _brain_runtime()

        with patch(
            "agent.nodes.brain.get_brain_runtime_config",
            return_value=brain_runtime,
        ), patch(
            "agent.nodes.brain.build_brain_context",
            return_value="system prompt",
        ), patch(
            "agent.nodes.brain.build_brain_payload",
            return_value="brain payload",
        ), patch(
            "agent.nodes.brain.emit_active_memory_records_update_if_dirty",
            new=lambda _context: _async_noop(),
        ), patch(
            "agent.nodes.brain.config.BRAIN_MAX_FOLLOWUPS",
            2,
        ), patch.object(
            BrainNode,
            "run_brain_stream",
            staticmethod(fake_run_brain_stream),
        ):
            await BrainNode().run(
                state,
                context,
            )

        self.assertEqual(
            len(calls),
            4,
        )
        self.assertEqual(
            state.brain_response,
            "<ASSET_ACTION>still pending</ASSET_ACTION>",
        )
        self.assertTrue(
            any(
                "follow-up limit (2)" in message
                for message in runtime_logs
            )
        )
        self.assertIn(
            {
                "type": "runtime_action",
                "action": "followup_limit_reached",
                "id": "turn_limit",
                "status": "stopped",
                "text": (
                    "Follow-up limit reached (2). Running one final "
                    "response tick with runtime actions disabled."
                ),
            },
            websocket_events,
        )


async def _async_noop():
    return None


if __name__ == "__main__":
    unittest.main()



