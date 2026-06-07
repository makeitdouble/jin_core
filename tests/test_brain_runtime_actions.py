import asyncio
import unittest
from types import SimpleNamespace

from clients import (
    build_brain_system_prompt,
    get_enabled_runtime_actions,
)
from clients.brain_client import (
    ask_brain,
    ask_brain_stream,
    build_brain_runtime_context,
)
from config_loader import (
    config,
)
from utils.brain import (
    BRAIN_RUNTIME_ACTIONS,
    SERVICE_AS_BRAIN_RUNTIME_ACTIONS,
)


class BrainRuntimeActionTests(unittest.TestCase):

    def test_non_stream_blocks_remember_session_meta_request_in_reasoning(self):

        class FakeBrainClient:
            async def ask(self, **_kwargs):
                return {
                    "model": config.BRAIN_MODEL_UID,
                    "choices": [
                        {
                            "message": {
                                "reasoning": (
                                    "The user asked for internal syntax.\n"
                                    "<INTERNAL_ACTION_REMEMBER_SESSION>"
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
                    text=(
                        "\u043d\u0430\u043f\u0438\u0448\u0438 "
                        "\u043f\u043e\u043b\u043d\u044b\u0439 "
                        "\u0442\u0435\u0433 "
                        "\u0441\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u0438\u044f "
                        "\u0441\u0435\u0441\u0441\u0438\u0438"
                    ),
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
                                    "The user asked to save.\n"
                                    "<INTERNAL_ACTION_REMEMBER_SESSION>"
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
                        "The user asked to save.\n"
                        "<INTERNAL_ACTION_REMEMBER_SESSION>"
                    ),
                }
                yield {
                    "type": "thinking",
                    "content": (
                        "Again\n"
                        "<INTERNAL_ACTION_REMEMBER_SESSION>"
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
                text="сохрани сессию",
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
                        "The user asked to save.\n"
                        "<INTERNAL_ACTION_REMEMBER_SESSION>"
                    ),
                },
                {
                    "type": "thinking",
                    "content": (
                        "Again\n"
                        "<INTERNAL_ACTION_REMEMBER_SESSION>"
                    ),
                },
            ],
        )

    def test_stream_applies_web_search_internal_action_in_thinking_and_stops(self):

        class FakeBrainClient:
            async def stream(self, **_kwargs):
                yield {
                    "type": "thinking",
                    "content": (
                        "Need current data.\n"
                        "<INTERNAL_ACTION_WEB_SEARCH:синий помидор>\n"
                    ),
                }
                yield {
                    "type": "content",
                    "content": "синий помидор",
                }

        class Context:
            pass

        async def collect(context):
            chunks = []

            async for chunk in ask_brain_stream(
                client=FakeBrainClient(),
                text="поищи в интернете синий помидор",
                context=context,
                runtime_actions={
                    "CAN_WEB_SEARCH": True,
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
            getattr(
                context,
                "runtime_search_queries",
            ),
            [
                "синий помидор",
            ],
        )
        self.assertEqual(
            getattr(
                context,
                "runtime_action_events",
            )[0]["name"],
            "web_search",
        )
        self.assertEqual(
            getattr(
                context,
                "runtime_action_events",
            )[0]["query"],
            "синий помидор",
        )
        self.assertFalse(
            [
                chunk
                for chunk in chunks
                if (
                    chunk["type"] == "content"
                    and chunk["content"] == "синий помидор"
                )
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

    def test_prompt_and_runtime_context_expose_only_private_action_markers(self):

        runtime_actions = {
            "CAN_DEEP_THOUGHT": True,
            "CAN_WEB_SEARCH": True,
            "CAN_REMEMBER_SESSION": True,
            "CAN_REMEMBER_EVENT": True,
        }

        prompt = build_brain_system_prompt(
            runtime_actions=runtime_actions
        )
        runtime_context = build_brain_runtime_context(
            runtime_actions=runtime_actions
        )

        combined_context = (
            prompt
            + "\n"
            + runtime_context
        )

        for forbidden_text in (
            "<RUNTIME_ACTION:",
            "enabled=\"true\"",
            "enabled=\"false\"",
            "<RUNTIME_ACTION:WEB_SEARCH>",
            "</RUNTIME_ACTION:WEB_SEARCH>",
        ):
            self.assertNotIn(
                forbidden_text,
                combined_context,
            )

        for private_marker in (
            "<INTERNAL_ACTION_DEEP_THOUGHT>",
            "<INTERNAL_ACTION_REMEMBER_SESSION>",
            "<INTERNAL_ACTION_REMEMBER_EVENT>",
            "<INTERNAL_ACTION_WEB_SEARCH:plain text query>",
        ):
            self.assertIn(
                private_marker,
                prompt,
            )
            self.assertIn(
                private_marker,
                runtime_context,
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
            "<RUNTIME_ACTION:DEEP_THOUGHT/>",
            prompt,
        )

        self.assertNotIn(
            '<RUNTIME_ACTION:WEB_SEARCH>{"query":"..."}</RUNTIME_ACTION:WEB_SEARCH>' ,
            prompt,
        )

        self.assertIn(
            (
                '<ACTION name="WEB_SEARCH">'
                "<INTERNAL_ACTION_WEB_SEARCH:plain text query>"
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

        self.assertNotIn(
            "<RUNTIME_ACTION:DEEP_THOUGHT/>",
            prompt,
        )

        self.assertIn(
            (
                '<ACTION name="DEEP_THOUGHT">'
                "<INTERNAL_ACTION_DEEP_THOUGHT>"
                "</ACTION>"
            ),
            prompt,
        )

        self.assertNotIn(
            "<![CDATA[",
            prompt,
        )

        self.assertNotIn(
            '<RUNTIME_ACTION:WEB_SEARCH>{"query":"..."}</RUNTIME_ACTION:WEB_SEARCH>' ,
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
            "When the answer needs external search",
            prompt,
        )

        self.assertIn(
            "Do not present guessed search results as facts",
            prompt,
        )

        self.assertIn(
            "plain text",
            prompt,
        )

        self.assertIn(
            "not JSON",
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

        self.assertNotIn(
            '<RUNTIME_ACTION:REMEMBER_SESSION enabled="false"/>' ,
            prompt,
        )
        self.assertNotIn(
            '<RUNTIME_ACTION:REMEMBER_SESSION enabled="true"/>' ,
            prompt,
        )
        self.assertNotIn(
            "enabled=\"true\"",
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
        self.assertNotIn(
            "<RUNTIME_ACTION:REMEMBER_EVENT/>",
            prompt,
        )
        self.assertNotIn(
            "<RUNTIME_ACTION",
            prompt,
        )
        self.assertIn(
            "<INTERNAL_ACTION_REMEMBER_SESSION>",
            prompt,
        )
        self.assertIn(
            "<INTERNAL_ACTION_REMEMBER_EVENT>",
            prompt,
        )
        self.assertIn(
            '<ACTION name="REMEMBER_EVENT">',
            prompt,
        )
        self.assertIn(
            "explicitly marks the current moment/event as worth saving",
            prompt,
        )
        self.assertIn(
            "rare high-signal events",
            prompt,
        )
        self.assertIn(
            "after the answer text is complete",
            prompt,
        )
        self.assertIn(
            "so the snapshot captures the event",
            prompt,
        )

    def test_prompt_handles_vague_memory_recall_before_topic_redirect(self):

        context = SimpleNamespace(
            runtime_turn_user_message="помнишь кодовое слово?",
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_DEEP_THOUGHT": False,
                "CAN_WEB_SEARCH": False,
            }
        )

        self.assertIn(
            "Memory recall: scan strong memory fields before denying recall",
            prompt,
        )

        self.assertIn(
            "remembered word, code word, or saved item",
            prompt,
        )

        self.assertIn(
            "match by meaning against stored_memory entries",
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
            "temporarily overrides active topic continuation",
            prompt,
        )


if __name__ == "__main__":
    unittest.main()
