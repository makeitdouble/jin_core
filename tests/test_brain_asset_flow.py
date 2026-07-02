import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agent.nodes.brain import BrainNode
from agent.state import AgentState


class BrainAssetFlowTests(unittest.IsolatedAsyncioTestCase):

    async def test_asset_operation_result_is_reported_without_second_model_followup(self):

        calls = []
        emitted_reports = []

        async def fake_run_brain_stream(**kwargs):
            calls.append(kwargs)
            context = kwargs["context"]

            if len(calls) == 1:
                context.runtime_asset_results.append({
                    "ok": True,
                    "action": "list_skills",
                    "skills": [
                        {
                            "name": "wildcards",
                            "content": "Use ASSET_ACTION for wildcard files.",
                        },
                    ],
                })
                return "", ""

            if len(calls) == 2:
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
                self.assertFalse(
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
                return "premature model report", ""

            self.fail("Brain model was called again after asset operation result")

        async def fake_emit_brain_text(**kwargs):
            emitted_reports.append(kwargs["text"])
            return kwargs["text"], ""

        context = SimpleNamespace(
            logger=SimpleNamespace(),
            clients={"brain": object()},
            runtime_search_queries=[],
            runtime_search_calls=[],
            runtime_asset_results=[],
            runtime_action_events=[],
        )

        state = AgentState(
            user_input="создай wildcard файл clothing/test_bottoms на 2 строки",
        )
        state.translated_input = state.user_input

        brain_runtime = {
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
            len(emitted_reports),
            1,
        )
        self.assertIn(
            "Создал файл `assets/wildcards/clothing/test_bottoms.txt` на 2 строки.",
            emitted_reports[0],
        )
        self.assertIn(
            "- denim shorts",
            emitted_reports[0],
        )
        self.assertEqual(
            state.brain_response,
            emitted_reports[0],
        )


async def _async_noop():
    return None


if __name__ == "__main__":
    unittest.main()
