import asyncio
import unittest

from clients import (
    build_brain_system_prompt,
    get_enabled_runtime_actions,
)
from clients.brain_client import (
    ask_brain,
    ask_brain_stream,
)
from config_loader import (
    config,
)
from runtime import (
    DEEP_THOUGHT_ACTION,
    REMEMBER_EVENT_ACTION,
    REMEMBER_SESSION_ACTION,
    WEB_SEARCH_ACTION_TEMPLATE,
)
from utils.brain import (
    BRAIN_RUNTIME_ACTIONS,
    SERVICE_AS_BRAIN_RUNTIME_ACTIONS,
)


class BrainRuntimeActionTests(unittest.TestCase):

    def test_non_stream_ignores_remember_session_marker_in_reasoning(self):

        class FakeBrainClient:
            async def ask(self, **_kwargs):
                return {
                    "model": config.BRAIN_MODEL_UID,
                    "choices": [
                        {
                            "message": {
                                "reasoning": (
                                    "I should not emit "
                                    f"{REMEMBER_SESSION_ACTION} now."
                                ),
                                "content": "ok",
                            },
                        },
                    ],
                }

        class Context:
            pass

        context = Context()
        original_use_service_as_brain = config.USE_SERVICE_AS_BRAIN
        config.USE_SERVICE_AS_BRAIN = False

        try:
            answer = asyncio.run(
                ask_brain(
                    client=FakeBrainClient(),
                    text="save it later",
                    context=context,
                    runtime_actions={
                        "CAN_DEEP_THOUGHT": True,
                        "CAN_REMEMBER_SESSION": True,
                    },
                )
            )
        finally:
            config.USE_SERVICE_AS_BRAIN = original_use_service_as_brain

        self.assertEqual(
            answer,
            "ok",
        )
        self.assertFalse(
            hasattr(
                context,
                "runtime_remember_session_requested",
            )
        )

    def test_non_stream_applies_remember_session_marker_in_reasoning(self):

        class FakeBrainClient:
            async def ask(self, **_kwargs):
                return {
                    "model": config.BRAIN_MODEL_UID,
                    "choices": [
                        {
                            "message": {
                                "reasoning": (
                                    "The user asked to save. "
                                    f"{REMEMBER_SESSION_ACTION}"
                                ),
                                "content": "ok",
                            },
                        },
                    ],
                }

        class Context:
            pass

        context = Context()
        original_use_service_as_brain = config.USE_SERVICE_AS_BRAIN
        config.USE_SERVICE_AS_BRAIN = False

        try:
            answer = asyncio.run(
                ask_brain(
                    client=FakeBrainClient(),
                    text="сохрани сессию",
                    context=context,
                    runtime_actions={
                        "CAN_DEEP_THOUGHT": True,
                        "CAN_REMEMBER_SESSION": True,
                    },
                )
            )
        finally:
            config.USE_SERVICE_AS_BRAIN = original_use_service_as_brain

        self.assertEqual(
            answer,
            "ok",
        )
        self.assertTrue(
            context.runtime_remember_session_requested,
        )

    def test_stream_applies_remember_session_marker_in_thinking_once(self):

        class FakeBrainClient:
            async def stream(self, **_kwargs):
                yield {
                    "type": "thinking",
                    "content": (
                        "The user asked to save. "
                        f"{REMEMBER_SESSION_ACTION}"
                    ),
                }
                yield {
                    "type": "thinking",
                    "content": (
                        "Again "
                        f"{REMEMBER_SESSION_ACTION}"
                    ),
                }
                yield {
                    "type": "content",
                    "content": "ok",
                }

        class Context:
            pass

        async def collect(context):
            chunks = []

            async for chunk in ask_brain_stream(
                client=FakeBrainClient(),
                text="save it later",
                context=context,
                runtime_actions={
                    "CAN_DEEP_THOUGHT": True,
                    "CAN_REMEMBER_SESSION": True,
                },
            ):
                chunks.append(
                    chunk
                )

            return chunks

        context = Context()
        original_use_service_as_brain = config.USE_SERVICE_AS_BRAIN
        config.USE_SERVICE_AS_BRAIN = False

        try:
            chunks = asyncio.run(
                collect(
                    context
                )
            )
        finally:
            config.USE_SERVICE_AS_BRAIN = original_use_service_as_brain

        self.assertEqual(
            chunks[-1],
            {
                "type": "content",
                "content": "ok",
            },
        )
        self.assertTrue(
            context.runtime_remember_session_requested,
        )
        self.assertEqual(
            [
                chunk
                for chunk in chunks
                if chunk["type"] == "thinking"
            ],
            [
                {
                    "type": "thinking",
                    "content": (
                        "The user asked to save. "
                        f"{REMEMBER_SESSION_ACTION}"
                    ),
                },
                {
                    "type": "thinking",
                    "content": (
                        "Again "
                        f"{REMEMBER_SESSION_ACTION}"
                    ),
                },
            ],
        )

    def test_agent_runtime_action_flags_enable_search_and_remember_session(self):

        self.assertEqual(
            get_enabled_runtime_actions(
                SERVICE_AS_BRAIN_RUNTIME_ACTIONS
            ),
            (
                "WEB_SEARCH",
                "REMEMBER_SESSION",
                "REMEMBER_EVENT",
            ),
        )

        self.assertEqual(
            get_enabled_runtime_actions(
                BRAIN_RUNTIME_ACTIONS
            ),
            (
                "WEB_SEARCH",
                "REMEMBER_SESSION",
                "REMEMBER_EVENT",
            ),
        )

    def test_prompt_uses_passed_agent_runtime_actions(self):

        prompt = build_brain_system_prompt(
            runtime_actions={
                "CAN_DEEP_THOUGHT": False,
                "CAN_WEB_SEARCH": True,
            }
        )

        self.assertNotIn(
            "CAN_WEB_SEARCH",
            prompt,
        )

        self.assertNotIn(
            "CAN_DEEP_THOUGHT",
            prompt,
        )

        self.assertNotIn(
            "DEEP_THOUGHT_COUNTER",
            prompt,
        )

        self.assertNotIn(
            DEEP_THOUGHT_ACTION,
            prompt,
        )

        self.assertIn(
            WEB_SEARCH_ACTION_TEMPLATE,
            prompt,
        )

        self.assertIn(
            (
                '<ACTION name="WEB_SEARCH">'
                f"{WEB_SEARCH_ACTION_TEMPLATE}"
                "</ACTION>"
            ),
            prompt,
        )

        self.assertNotIn(
            "<![CDATA[",
            prompt,
        )

        self.assertNotIn(
            "&lt;RUNTIME_ACTION:WEB_SEARCH&gt;",
            prompt,
        )

        self.assertIn(
            "<TIMESTAMP>",
            prompt,
        )

        self.assertNotIn(
            "CURRENT_DATE",
            prompt,
        )

        self.assertNotIn(
            "CURRENT_TIME",
            prompt,
        )

        self.assertNotIn(
            "<YEAR>",
            prompt,
        )

        self.assertNotIn(
            "RUNTIME_STATE",
            prompt,
        )

        self.assertNotIn(
            "INITIAL_STATE",
            prompt,
        )

    def test_prompt_can_flip_agent_actions_dynamically(self):

        prompt = build_brain_system_prompt(
            runtime_actions={
                "CAN_DEEP_THOUGHT": True,
                "CAN_WEB_SEARCH": False,
            }
        )

        self.assertNotIn(
            "CAN_DEEP_THOUGHT",
            prompt,
        )

        self.assertNotIn(
            "CAN_WEB_SEARCH",
            prompt,
        )

        self.assertIn(
            DEEP_THOUGHT_ACTION,
            prompt,
        )

        self.assertIn(
            (
                '<ACTION name="DEEP_THOUGHT">'
                f"{DEEP_THOUGHT_ACTION}"
                "</ACTION>"
            ),
            prompt,
        )

        self.assertNotIn(
            "<![CDATA[",
            prompt,
        )

        self.assertNotIn(
            WEB_SEARCH_ACTION_TEMPLATE,
            prompt,
        )

    def test_search_prompt_requires_plain_query_and_exact_subject(self):

        prompt = build_brain_system_prompt(
            runtime_actions={
                "CAN_DEEP_THOUGHT": False,
                "CAN_WEB_SEARCH": True,
            }
        )

        self.assertIn(
            "preserve the exact subject",
            prompt,
        )

        self.assertIn(
            "only available source of fresh external data",
            prompt,
        )

        self.assertIn(
            "do not rely on memory or guesses",
            prompt,
        )

        self.assertIn(
            "plain text",
            prompt,
        )

        self.assertIn(
            "not another JSON object",
            prompt,
        )

    def test_prompt_includes_remember_session_only_when_enabled(self):

        prompt = build_brain_system_prompt(
            runtime_actions={
                "CAN_DEEP_THOUGHT": False,
                "CAN_WEB_SEARCH": False,
                "CAN_REMEMBER_SESSION": True,
                "CAN_REMEMBER_EVENT": True,
            }
        )

        self.assertIn(
            REMEMBER_SESSION_ACTION,
            prompt,
        )
        self.assertIn(
            "explicitly ends",
            prompt,
        )
        self.assertIn(
            '<ACTION name="REMEMBER_SESSION">',
            prompt,
        )
        self.assertIn(
            REMEMBER_EVENT_ACTION,
            prompt,
        )
        self.assertIn(
            '<ACTION name="REMEMBER_EVENT">',
            prompt,
        )
        self.assertIn(
            "хочу это запомнить",
            prompt,
        )
        self.assertIn(
            "rare high-signal events",
            prompt,
        )
        self.assertIn(
            "after the answer text for the event is complete",
            prompt,
        )
        self.assertIn(
            "do not ask the user to fill a form",
            prompt,
        )

    def test_prompt_handles_vague_memory_recall_before_topic_redirect(self):

        prompt = build_brain_system_prompt(
            runtime_actions={
                "CAN_DEEP_THOUGHT": False,
                "CAN_WEB_SEARCH": False,
            }
        )

        self.assertIn(
            "For memory recall questions, scan strong memory fields before denying recall",
            prompt,
        )

        self.assertIn(
            "remembered word, code word, important detail, or saved item",
            prompt,
        )

        self.assertIn(
            "match by meaning against stored_memory entries with explicit purpose",
            prompt,
        )

        self.assertIn(
            "purpose: future recall test",
            prompt,
        )

        self.assertIn(
            "strongest recall candidate",
            prompt,
        )

        self.assertIn(
            "temporarily overrides active topic/task continuation",
            prompt,
        )


if __name__ == "__main__":
    unittest.main()
