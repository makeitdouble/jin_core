import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agent.nodes.brain import (
    BrainNode,
    format_followup_action_from_event,
    format_followup_actions_from_events,
)
from agent.state import AgentState


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

    test_case.assertTrue(
        payload.startswith(
            "<runtime_system_message>\n"
            "This is not a start of a task sequence!\n"
            "This is not a new request!\n"
            "Multi-step task in progress!"
        ),
        payload,
    )
    test_case.assertIn(
        (
            "This is follow-up tick for JIN latest action: "
        ),
        payload,
    )
    if latest_action_fragment is not None:
        test_case.assertIn(
            latest_action_fragment,
            payload,
        )
    test_case.assertIn(
        (
            "Requested and available information provided in "
            "tool results section."
        ),
        payload,
    )
    test_case.assertNotEqual(
        payload,
        "No new messages, multi-task in progress",
    )
    test_case.assertNotIn(
        user_input,
        payload,
    )
    test_case.assertTrue(
        system_prompt.startswith(
            "<LATEST_USER_REQUEST>\n"
            "!!!this is not a current user prompt!!!"
            "!!!this is not a start message!!!"
            "!!!this is initial user request provided by follow up tick!!!"
            f"{user_input}\n"
            "</LATEST_USER_REQUEST>\n\n"
            "<PREVIOUS_CHAT_MESSAGES>\n"
            f"<USER>{user_input}\n"
            "</PREVIOUS_CHAT_MESSAGES>\n\n"
        ),
        system_prompt,
    )
    test_case.assertNotIn(
        "Continue using",
        payload,
    )
    test_case.assertNotIn(
        "Latest tool result summary:",
        payload,
    )
    test_case.assertNotIn(
        "APPENDED_SKILLS",
        payload,
    )


class BrainAssetFlowTests(unittest.IsolatedAsyncioTestCase):

    async def test_followup_event_formatter_keeps_only_action_name(self):

        self.assertEqual(
            format_followup_action_from_event({
                "name": "save_session",
                "payload": "session payload",
                "id": "save-123",
                "query": "ignored query",
            }),
            "save_session",
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
            "resolve_active_memory (repeated_times: 2 ), save_session",
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
            "<LATEST_RUNTIME_MEMORY>\nactive_topic: test\n"
            "</LATEST_RUNTIME_MEMORY>",
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

        self.assertTrue(
            prompt.startswith(
                "<LATEST_USER_REQUEST>\n"
                "!!!this is not a current user prompt!!!"
                "!!!this is not a start message!!!"
                "!!!this is initial user request provided by follow up tick!!!"
                "append the delayed memory\n"
                "</LATEST_USER_REQUEST>\n\n"
                "<APPENDED_DELAYED_MEMORY>\n"
            ),
            prompt,
        )
        self.assertLess(
            prompt.index(
                "<APPENDED_DELAYED_MEMORY>"
            ),
            prompt.index(
                "<PREVIOUS_CHAT_MESSAGES>"
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
            "clients.brain_context_builder.time.time",
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
            "<CURRENT_ACTIONS_HISTORY>\n"
            "    --- Sequence started ---\n"
            "    1. LIST_SKILLS ( 55s ago )\n"
            "    2. APPEND_SKILL ( 2s ago )\n"
            "</CURRENT_ACTIONS_HISTORY>",
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
            prompt.index("</LATEST_USER_REQUEST>"),
            prompt.index("<CURRENT_ACTIONS_HISTORY>"),
        )
        self.assertLess(
            prompt.index("<CURRENT_ACTIONS_HISTORY>"),
            prompt.index("<PREVIOUS_CHAT_MESSAGES>"),
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
            "agent.nodes.brain.build_brain_system_prompt",
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

    async def test_list_delayed_memory_result_triggers_followup(self):

        calls = []

        async def fake_run_brain_stream(**kwargs):
            calls.append(kwargs)
            context = kwargs["context"]

            if len(calls) == 1:
                context.runtime_delayed_memory_results.append({
                    "ok": True,
                    "action": "list_delayed_memory",
                    "reports": [
                        {
                            "id": "dm_note",
                            "title": "Solo note",
                        },
                    ],
                })
                return "", ""

            if len(calls) == 2:
                self.assertTrue(
                    kwargs["filter_runtime_actions"],
                )
                self.assertTrue(
                    kwargs["runtime_actions"].get(
                        "CAN_SAVE_DELAYED_MEMORY"
                    ),
                )
                _assert_latest_request_payload(
                    self,
                    kwargs,
                    state.translated_input,
                    "list_delayed_memory",
                )
                return (
                    "Found delayed memory `dm_note`: Solo note.",
                    "",
                )

            self.fail(
                "Brain model kept running after delayed-memory answer"
            )

        context = _context()
        state = AgentState(
            user_input=(
                "append delayed memory it is alone now"
            ),
        )
        state.translated_input = state.user_input
        brain_runtime = _brain_runtime()

        with patch(
            "agent.nodes.brain.get_brain_runtime_config",
            return_value=brain_runtime,
        ), patch(
            "agent.nodes.brain.build_brain_system_prompt",
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
            "Found delayed memory `dm_note`: Solo note.",
        )

    async def test_same_turn_list_skills_keeps_followup_payload(self):

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
                self.assertTrue(
                    kwargs["brain_payload"].startswith(
                        "<runtime_system_message>\n"
                        "This is not a start of a task sequence!"
                    ),
                    kwargs["brain_payload"],
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
            "agent.nodes.brain.build_brain_system_prompt",
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

    async def test_previous_turn_list_skills_uses_followup_payload(self):

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
                self.assertTrue(
                    kwargs["brain_payload"].startswith(
                        "<runtime_system_message>\n"
                        "This is not a start of a task sequence!"
                    ),
                    kwargs["brain_payload"],
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
            "agent.nodes.brain.build_brain_system_prompt",
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
            "agent.nodes.brain.build_brain_system_prompt",
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
                    'append_skill',
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
            "agent.nodes.brain.build_brain_system_prompt",
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
                    'append_skill',
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
            "agent.nodes.brain.build_brain_system_prompt",
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
            "agent.nodes.brain.build_brain_system_prompt",
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
            "agent.nodes.brain.build_brain_system_prompt",
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


    async def test_every_action_message_triggers_followup_and_keeps_actions_enabled(self):

        calls = []
        action_names = [
            "create_active_memory",
            "append_skill",
            "save_session",
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
            "agent.nodes.brain.build_brain_system_prompt",
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
            'create_active_memory',
            calls[1]["brain_payload"],
        )
        self.assertIn(
            'append_skill',
            calls[2]["brain_payload"],
        )
        self.assertIn(
            'save_session',
            calls[3]["brain_payload"],
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
                        "name": "create_active_memory",
                        "payload": "first",
                    },
                    {
                        "name": "resolve_active_memory",
                        "id": "active_memory_1",
                    },
                ])
                return "", ""

            self.assertIn(
                'create_active_memory',
                kwargs["brain_payload"],
            )
            self.assertIn(
                'resolve_active_memory',
                kwargs["brain_payload"],
            )
            self.assertNotIn(
                'payload=',
                kwargs["brain_payload"],
            )
            self.assertNotIn(
                'id=',
                kwargs["brain_payload"],
            )
            self.assertNotIn(
                'active_memory_1',
                kwargs["brain_payload"],
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
            "agent.nodes.brain.build_brain_system_prompt",
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
            "agent.nodes.brain.build_brain_system_prompt",
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
