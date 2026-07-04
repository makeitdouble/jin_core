import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agent.nodes.brain import BrainNode
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
        runtime_appended_skills=[],
        runtime_action_events=[],
    )


class BrainAssetFlowTests(unittest.IsolatedAsyncioTestCase):

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
                self.assertFalse(
                    kwargs["runtime_actions"].get("CAN_SAVE_ACTIVE_MEMORY"),
                )
                self.assertFalse(
                    kwargs["runtime_actions"].get("CAN_SAVE_DELAYED_MEMORY"),
                )
                self.assertFalse(
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
                self.assertIn(
                    "Latest tool result summary:",
                    kwargs["brain_payload"],
                )
                self.assertIn(
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
                self.assertIn(
                    "APPENDED_SKILLS",
                    kwargs["brain_payload"],
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

    async def test_append_skill_visible_answer_does_not_trigger_followup(self):

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

            self.fail("Brain model was called again after visible append answer")

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
            1,
        )
        self.assertEqual(
            state.brain_response,
            "I've loaded the wildcards skill. Ready to test.",
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
                self.assertIn(
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
                self.assertIn(
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
                self.assertFalse(
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
                self.assertIn(
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


async def _async_noop():
    return None


if __name__ == "__main__":
    unittest.main()
