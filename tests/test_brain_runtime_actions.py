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
from clients.brain_client_utils import (
    BRAIN_RUNTIME_ACTIONS,
    SERVICE_AS_BRAIN_RUNTIME_ACTIONS,
)



def assert_contains_text(test_case, text: str, needle: str) -> None:
    test_case.assertTrue(
        needle in text,
        f"expected text to contain: {needle!r}",
    )


def assert_not_contains_text(test_case, text: str, needle: str) -> None:
    test_case.assertFalse(
        needle in text,
        f"expected text to omit: {needle!r}",
    )


class BrainRuntimeActionTests(unittest.TestCase):

    def test_non_stream_blocks_save_session_meta_request_in_reasoning(self):

        class FakeBrainClient:
            async def ask(self, **_kwargs):
                return {
                    "model": config.BRAIN_MODEL_UID,
                    "choices": [
                        {
                            "message": {
                                "reasoning": (
                                    "The user asked for internal syntax.\n"
                                    "<INTERNAL_ACTION_SAVE_SESSION>"
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
                        "CAN_SAVE_SESSION": True,
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
                "runtime_save_session_requested",
            )
        )

    def test_non_stream_applies_save_session_marker_in_reasoning(self):

        class FakeBrainClient:
            async def ask(self, **_kwargs):
                return {
                    "model": config.BRAIN_MODEL_UID,
                    "choices": [
                        {
                            "message": {
                                "reasoning": (
                                    "The user asked to save.\n"
                                    "<INTERNAL_ACTION_SAVE_SESSION>"
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
                        "CAN_SAVE_SESSION": True,
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
            context.runtime_save_session_requested,
        )

    def test_stream_applies_save_session_marker_in_thinking_once(self):

        class FakeBrainClient:
            async def stream(self, **_kwargs):
                yield {
                    "type": "thinking",
                    "content": (
                        "The user asked to save.\n"
                        "<INTERNAL_ACTION_SAVE_SESSION>"
                    ),
                }
                yield {
                    "type": "thinking",
                    "content": (
                        "Again\n"
                        "<INTERNAL_ACTION_SAVE_SESSION>"
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
                    "CAN_SAVE_SESSION": True,
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
            context.runtime_save_session_requested,
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
                        "<INTERNAL_ACTION_SAVE_SESSION>"
                    ),
                },
                {
                    "type": "thinking",
                    "content": (
                        "Again\n"
                        "<INTERNAL_ACTION_SAVE_SESSION>"
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
                    "CAN_SAVE_SESSION": True,
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

    def test_agent_runtime_action_flags_enable_search_and_save_session(self):

        self.assertEqual(
            get_enabled_runtime_actions(
                SERVICE_AS_BRAIN_RUNTIME_ACTIONS
            ),
            (
                "SAVE_SESSION",
                "CREATE_ACTIVE_MEMORY",
                "UPDATE_ACTIVE_MEMORY",
            ),
        )

        self.assertEqual(
            get_enabled_runtime_actions(
                BRAIN_RUNTIME_ACTIONS
            ),
            (
                "WEB_SEARCH",
                "SAVE_SESSION",
                "CREATE_ACTIVE_MEMORY",
                "UPDATE_ACTIVE_MEMORY",
            ),
        )

    def test_prompt_and_runtime_context_expose_only_private_action_markers(self):

        runtime_actions = {
            "CAN_WEB_SEARCH": True,
            "CAN_SAVE_SESSION": True,
            "CAN_SAVE_ACTIVE_MEMORY": True,
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
            assert_not_contains_text(
                self,
                combined_context,
                forbidden_text,
            )

        for private_marker in (
            "<INTERNAL_ACTION_SAVE_SESSION>",
            "<INTERNAL_ACTION_CREATE_ACTIVE_MEMORY: PURPOSE | CONDITIONS | VALUE >",
            "<INTERNAL_ACTION_WEB_SEARCH:plain text query>",
        ):
            assert_contains_text(
                self,
                prompt,
                private_marker,
            )

        assert_contains_text(
            self,
            runtime_context,
            "<CURRENT_TRUSTED_RUNTIME_VARIABLES>",
        )

    def test_prompt_uses_passed_agent_runtime_actions(self):

        prompt = build_brain_system_prompt(
            runtime_actions={
                "CAN_WEB_SEARCH": True,
            }
        )

        self.assertNotIn(
            "CAN_WEB_SEARCH",
            prompt,
        )



        self.assertNotIn(
            '<RUNTIME_ACTION:WEB_SEARCH>{"query":"..."}</RUNTIME_ACTION:WEB_SEARCH>' ,
            prompt,
        )

        assert_contains_text(
            self,
            prompt,
            "<INTERNAL_ACTION_WEB_SEARCH:plain text query>",
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
            "<USER_DATETIME>",
            prompt,
        )

        self.assertNotIn(
            "<USER_WEEKDAY>",
            prompt,
        )

        self.assertIn(
            "<MODE>SERVICE as BRAIN</MODE>",
            prompt,
        )

        self.assertIn(
            f"<SERVICE_MODEL_UID>{config.SERVICE_MODEL_UID}</SERVICE_MODEL_UID>",
            prompt,
        )

        self.assertNotIn(
            "<CONTEXT>",
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
                "CAN_WEB_SEARCH": False,
            }
        )

        self.assertNotIn(
            "CAN_WEB_SEARCH",
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
                "CAN_WEB_SEARCH": True,
            }
        )

        self.assertIn(
            "preserve the exact subject",
            prompt,
        )

        self.assertIn(
            "Do not present guessed results as facts",
            prompt,
        )

        self.assertIn(
            "plain text",
            prompt,
        )


    def test_prompt_includes_save_session_only_when_enabled(self):

        prompt = build_brain_system_prompt(
            runtime_actions={
                "CAN_WEB_SEARCH": False,
                "CAN_SAVE_SESSION": True,
                "CAN_SAVE_ACTIVE_MEMORY": True,
            }
        )

        self.assertNotIn(
            '<RUNTIME_ACTION:SAVE_SESSION enabled="false"/>' ,
            prompt,
        )
        self.assertNotIn(
            '<RUNTIME_ACTION:SAVE_SESSION enabled="true"/>' ,
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
        assert_contains_text(
            self,
            prompt,
            "SAVE_SESSION: emit once",
        )
        self.assertNotIn(
            "<RUNTIME_ACTION",
            prompt,
        )
        self.assertIn(
            "<INTERNAL_ACTION_SAVE_SESSION>",
            prompt,
        )
        self.assertIn(
            "<INTERNAL_ACTION_CREATE_ACTIVE_MEMORY: PURPOSE | CONDITIONS | VALUE >",
            prompt,
        )
        assert_contains_text(
            self,
            prompt,
            "CREATE_ACTIVE_MEMORY: emit once",
        )
        self.assertIn(
            "CREATE_ACTIVE_MEMORY",
            prompt,
        )

    def test_prompt_does_not_render_legacy_memory_recall_block(self):

        context = SimpleNamespace(
            runtime_turn_user_message="помнишь кодовое слово?",
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_WEB_SEARCH": False,
            }
        )

        self.assertIn(
            "<CURRENT_TRUSTED_RUNTIME_VARIABLES>",
            prompt,
        )

        self.assertNotIn(
            "Memory recall: scan strong memory fields before denying recall",
            prompt,
        )

        self.assertNotIn(
            "temporarily overrides active topic continuation",
            prompt,
        )


if __name__ == "__main__":
    unittest.main()
