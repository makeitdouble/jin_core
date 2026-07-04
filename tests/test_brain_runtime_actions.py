import asyncio
import unittest
from types import SimpleNamespace

from clients.brain_context_builder import (
    build_brain_runtime_context,
)
from clients.brain_client import (
    ask_brain,
    ask_brain_stream,
)
from rules.assembler import (
    build_brain_system_prompt,
    get_enabled_runtime_actions,
)
from config_loader import (
    config,
)
from app_settings import (
    settings,
)
from rules.assembler import (
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


def expected_enabled_runtime_actions(runtime_actions: dict) -> tuple[str, ...]:
    expected_actions = []

    if bool(runtime_actions.get("CAN_WEB_SEARCH", False)):
        expected_actions.append("WEB_SEARCH")

    if bool(runtime_actions.get("CAN_SAVE_SESSION", False)):
        expected_actions.append("SAVE_SESSION")

    if bool(runtime_actions.get("CAN_USE_ASSETS", False)):
        expected_actions.extend(
            (
                "LIST_SKILLS",
                "ASSET_ACTION",
            )
        )

    if bool(runtime_actions.get("CAN_SAVE_DELAYED_MEMORY", False)):
        expected_actions.append("SAVE_DELAYED_MEMORY_CONTENT")

    if bool(runtime_actions.get("CAN_SAVE_ACTIVE_MEMORY", False)):
        expected_actions.extend(
            (
                "CREATE_ACTIVE_MEMORY",
                "RESOLVE_ACTIVE_MEMORY",
            )
        )

    return tuple(expected_actions)


class BrainRuntimeActionTests(unittest.TestCase):

    def test_brain_system_prompt_keeps_runtime_rule_sentences_separated(self):

        context = SimpleNamespace(
            runtime_memory="",
            runtime_memory_stable="",
            active_memory_records=[
                "active_memory_1: Check whether this should resolve",
            ],
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_WEB_SEARCH": True,
                "CAN_SAVE_SESSION": True,
                "CAN_SAVE_DELAYED_MEMORY": True,
                "CAN_SAVE_ACTIVE_MEMORY": True,
            },
        )

        assert_not_contains_text(
            self,
            prompt,
            "final answer.Emit markers",
        )
        assert_not_contains_text(
            self,
            prompt,
            "specific cases.DO NOT invent",
        )
        assert_not_contains_text(
            self,
            prompt,
            "memory conditions.You need",
        )
        assert_contains_text(
            self,
            prompt,
            "final answer.\nEmit markers",
        )
        assert_contains_text(
            self,
            prompt,
            "specific cases.\nDO NOT invent",
        )
        assert_contains_text(
            self,
            prompt,
            "memory conditions.\nYou need",
        )

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

    def test_non_stream_preserves_save_session_marker_without_user_request(self):

        class FakeBrainClient:
            async def ask(self, **_kwargs):
                return {
                    "model": config.BRAIN_MODEL_UID,
                    "choices": [
                        {
                            "message": {
                                "reasoning": "",
                                "content": (
                                    "The literal marker is "
                                    "<INTERNAL_ACTION_SAVE_SESSION>."
                                ),
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
                    text="what marker saves the session?",
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
            "The literal marker is <INTERNAL_ACTION_SAVE_SESSION>.",
        )
        self.assertFalse(
            hasattr(
                context,
                "runtime_save_session_requested",
            )
        )

    def test_non_stream_preserves_delayed_memory_marker_without_user_request(self):

        marker_text = (
            "Example:\n"
            "<INTERNAL_ACTION_SAVE_DELAYED_MEMORY_CONTENT>\n"
            '{"demo": {"summary": "quoted marker"}}\n'
            "</INTERNAL_ACTION_SAVE_DELAYED_MEMORY_CONTENT>"
        )

        class FakeBrainClient:
            async def ask(self, **_kwargs):
                return {
                    "model": config.BRAIN_MODEL_UID,
                    "choices": [
                        {
                            "message": {
                                "reasoning": "",
                                "content": marker_text,
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
                    text="how does delayed memory marker look?",
                    context=context,
                    runtime_actions={
                        "CAN_SAVE_DELAYED_MEMORY": True,
                    },
                )
            )
        finally:
            config.USE_SERVICE_AS_BRAIN = original_use_service_as_brain

        self.assertEqual(
            answer,
            marker_text,
        )
        self.assertFalse(
            hasattr(
                context,
                "delayed_memory_reports",
            )
        )

    def test_non_stream_ignores_save_session_marker_in_reasoning(self):

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
                    text="save session",
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

    def test_stream_ignores_save_session_marker_in_thinking(self):

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
                text="save session",
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
        self.assertFalse(
            hasattr(
                context,
                "runtime_save_session_requested",
            )
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

    def test_stream_applies_save_session_marker_from_content_tail(self):

        class FakeBrainClient:
            async def stream(self, **_kwargs):
                yield {
                    "type": "content",
                    "content": "<INTERNAL_ACTION_SAVE_SESSION>",
                }

        class Context:
            pass

        async def collect(context):
            chunks = []

            async for chunk in ask_brain_stream(
                client=FakeBrainClient(),
                text="save session",
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
            chunks,
            [],
        )
        self.assertTrue(
            context.runtime_save_session_requested,
        )
        self.assertEqual(
            context.runtime_action_events,
            [
                {
                    "name": "save_session",
                },
            ],
        )

    def test_stream_ignores_web_search_internal_action_in_thinking(self):

        class FakeBrainClient:
            async def stream(self, **_kwargs):
                yield {
                    "type": "thinking",
                    "content": (
                        "Need current data.\n"
                        "<INTERNAL_ACTION_WEB_SEARCH:blue tomato>\n"
                    ),
                }
                yield {
                    "type": "content",
                    "content": "blue tomato",
                }

        class Context:
            pass

        async def collect(context):
            chunks = []

            async for chunk in ask_brain_stream(
                client=FakeBrainClient(),
                text="search blue tomato",
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

        self.assertFalse(
            hasattr(
                context,
                "runtime_search_queries",
            )
        )
        self.assertFalse(
            hasattr(
                context,
                "runtime_action_events",
            )
        )
        self.assertIn(
            {
                "type": "content",
                "content": "blue tomato",
            },
            chunks,
        )

    def test_agent_runtime_action_flags_follow_assembler_constants(self):

        self.assertEqual(
            get_enabled_runtime_actions(
                SERVICE_AS_BRAIN_RUNTIME_ACTIONS
            ),
            expected_enabled_runtime_actions(
                SERVICE_AS_BRAIN_RUNTIME_ACTIONS
            ),
        )

        self.assertEqual(
            get_enabled_runtime_actions(
                BRAIN_RUNTIME_ACTIONS
            ),
            expected_enabled_runtime_actions(
                BRAIN_RUNTIME_ACTIONS
            ),
        )

    def test_prompt_and_runtime_context_expose_only_private_action_markers(self):

        runtime_actions = {
            "CAN_WEB_SEARCH": True,
            "CAN_SAVE_SESSION": True,
            "CAN_SAVE_DELAYED_MEMORY": True,
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
            "<INTERNAL_ACTION_SAVE_DELAYED_MEMORY_CONTENT>",
            "<INTERNAL_ACTION_CREATE_ACTIVE_MEMORY: CONDITIONS >",
            "Use WEB_SEARCH when freshness",
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

    def test_prompt_routes_uncertain_operational_tasks_to_skills(self):

        prompt = build_brain_system_prompt(
            runtime_actions={
                "CAN_USE_ASSETS": True,
            }
        )

        assert_contains_text(
            self,
            prompt,
            "SKILL ROUTING:",
        )
        assert_contains_text(
            self,
            prompt,
            "At the first sign of uncertainty",
        )
        assert_contains_text(
            self,
            prompt,
            "<INTERNAL_ACTION_LIST_SKILLS>",
        )
        assert_not_contains_text(
            self,
            prompt,
            "list_wildcards",
        )
        assert_not_contains_text(
            self,
            prompt,
            "create_wildcard_file",
        )
        assert_not_contains_text(
            self,
            prompt,
            "assets/wildcards",
        )

    def test_prompt_places_tool_results_before_identity(self):

        context = SimpleNamespace(
            runtime_memory="session_status: active",
            runtime_memory_stable="session_status: active",
            runtime_l2_memory="",
            active_memory_records=[],
            runtime_asset_results=[
                {
                    "ok": True,
                    "action": "list_skills",
                    "skills": [
                        {
                            "name": "wildcards",
                            "content": "first line\nsecond line",
                        },
                    ],
                },
            ],
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_USE_ASSETS": True,
            },
        )
        runtime_context = build_brain_runtime_context(
            context=context,
            runtime_actions={
                "CAN_USE_ASSETS": True,
            },
        )

        self.assertLess(
            prompt.index("Choose at most ONE internal action"),
            prompt.index("<TOOL_RESULTS"),
        )
        self.assertLess(
            prompt.index("<TOOL_RESULTS"),
            prompt.index("<Identity>"),
        )
        self.assertNotIn(
            "first line\\nsecond line",
            prompt,
        )
        self.assertIn(
            "first line\n",
            prompt,
        )
        self.assertIn(
            "second line",
            prompt,
        )
        self.assertNotIn(
            "<TOOL_RESULTS",
            runtime_context,
        )

    def test_prompt_adds_resolve_active_memory_rules_from_active_records_only(self):

        context = SimpleNamespace(
            runtime_memory="session_status: active",
            runtime_memory_stable="session_status: active",
            runtime_l2_memory="",
            active_memory_records=[
                (
                    "active_memory_1: remember cuckoo "
                    "[ active_memory_id: 5fdg4g ] [ status: pending ]"
                ),
            ],
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_SAVE_ACTIVE_MEMORY": True,
            },
        )
        runtime_context = build_brain_runtime_context(
            context=context,
            runtime_actions={
                "CAN_SAVE_ACTIVE_MEMORY": True,
            },
        )

        assert_contains_text(
            self,
            prompt,
            "CREATE_ACTIVE_MEMORY:",
        )
        assert_contains_text(
            self,
            prompt,
            "RESOLVE_ACTIVE_MEMORY:",
        )
        assert_contains_text(
            self,
            runtime_context,
            "<ACTIVE_MEMORY priority=\"active_runtime_contracts\">",
        )
        assert_contains_text(
            self,
            runtime_context,
            "5fdg4g",
        )

        runtime_memory_block = runtime_context.split(
            "<ACTIVE_MEMORY",
            1,
        )[0]
        assert_not_contains_text(
            self,
            runtime_memory_block,
            "active_memory_1:",
        )
        assert_not_contains_text(
            self,
            context.runtime_memory,
            "active_memory",
        )

    def test_runtime_context_omits_paused_active_memory_records(self):

        context = SimpleNamespace(
            runtime_memory="session_status: active",
            runtime_memory_stable="session_status: active",
            runtime_l2_memory="",
            active_memory_records=[
                (
                    "active_memory_1: remember cuckoo "
                    "[ active_memory_id: 5fdg4g ] [ status: pending ]"
                ),
                (
                    "active_memory_2: paused reminder "
                    "[ active_memory_id: abc123 ] [ status: paused ]"
                ),
            ],
        )

        runtime_context = build_brain_runtime_context(
            context=context,
            runtime_actions={
                "CAN_SAVE_ACTIVE_MEMORY": True,
            },
            commit_active_memory_refresh=True,
        )

        assert_contains_text(
            self,
            runtime_context,
            "5fdg4g",
        )
        assert_not_contains_text(
            self,
            runtime_context,
            "abc123",
        )
        assert_not_contains_text(
            self,
            runtime_context,
            "paused reminder",
        )
        self.assertEqual(
            len(context.active_memory_records),
            2,
        )
        assert_contains_text(
            self,
            "\n".join(context.active_memory_records),
            "abc123",
        )
        assert_contains_text(
            self,
            "\n".join(context.active_memory_records),
            "[ status: paused ]",
        )

    def test_prompt_omits_resolve_active_memory_rules_without_active_records(self):

        context = SimpleNamespace(
            runtime_memory="session_status: active",
            runtime_memory_stable="session_status: active",
            runtime_l2_memory="",
            active_memory_records=[],
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_SAVE_ACTIVE_MEMORY": True,
            },
        )

        assert_contains_text(
            self,
            prompt,
            "CREATE_ACTIVE_MEMORY:",
        )
        assert_not_contains_text(
            self,
            prompt,
            "RESOLVE_ACTIVE_MEMORY:",
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
            "Use WEB_SEARCH when freshness",
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
            (
                "<MODE>SERVICE as BRAIN</MODE>"
                if settings.USE_SERVICE_AS_BRAIN
                else "<MODE>BRAIN</MODE>"
            ),
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
            "SAVE_SESSION: high priority action",
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
            "<INTERNAL_ACTION_CREATE_ACTIVE_MEMORY: CONDITIONS >",
            prompt,
        )
        assert_contains_text(
            self,
            prompt,
            "CREATE_ACTIVE_MEMORY:",
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
