import asyncio
import contextlib
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from utils.context.context_exports import (
    build_runtime_xml,
    build_session_actions_history_context,
)
from clients.brain_client import (
    apply_runtime_action_calls,
    ask_brain,
    ask_brain_stream,
    build_brain_user_prompt_content,
)
from rules.brain_context_builder import (
    build_brain_context,
    get_enabled_runtime_actions,
)
from config_loader import (
    config,
)
from app_settings import (
    settings,
)
from rules.brain_context_builder import (
    BRAIN_RUNTIME_ACTIONS,
    SERVICE_AS_BRAIN_RUNTIME_ACTIONS,
)
from rules import runtime as runtime_rules
from contracts.rules_assembler import (
    get_runtime_action_private_marker,
)
from utils.session_actions_history import (
    build_session_actions_update_items,
    format_session_action_marker_names,
    replace_session_action_history_since,
)
from utils.actions import (
    RuntimeActionCall,
)
from runtime.runtime_context import (
    DEFAULT_JIN_COLOR,
)
from utils.tool_results import (
    TOOL_RESULT_KIND_ASSET,
)
from tests.helpers.runtime_actions import patch_asset_roots



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

    if bool(runtime_actions.get("CAN_DEEP_WEB_SEARCH", False)):
        expected_actions.append("DEEP_WEB_SEARCH")

    if bool(runtime_actions.get("CAN_WEB_SEARCH", False)):
        expected_actions.append("WEB_SEARCH")

    if bool(runtime_actions.get("CAN_SAVE_SESSION", False)):
        expected_actions.append("SAVE_SESSION")

    if bool(runtime_actions.get("CAN_CLEAN_TOOL_RESULTS", False)):
        expected_actions.append(
            "CLEAN_TOOL_RESULTS"
        )

    if bool(runtime_actions.get("CAN_IDLE", False)):
        expected_actions.append(
            "IDLE"
        )

    if bool(runtime_actions.get("CAN_JIN_COLOR", False)):
        expected_actions.append(
            "JIN_COLOR"
        )

    if bool(runtime_actions.get("CAN_UPDATE_L4_FACTS", False)):
        expected_actions.append(
            "UPDATE_L4_FACTS"
        )

    if bool(runtime_actions.get("CAN_USE_ASSETS", False)):
        expected_actions.extend(
            (
                "LOAD_SKILL",
                "UNLOAD_SKILL",
                "ASSET_ACTION",
            )
        )

    if bool(runtime_actions.get("CAN_RUNTIME_TODO", False)):
        expected_actions.extend(
            (
                "CREATE_TODO_LIST",
                "RESOLVE_TODO",
                "CHECK_TODO",
            )
        )

    if bool(runtime_actions.get("CAN_SAVE_DELAYED_MEMORY", False)):
        expected_actions.extend(
            (
                "SAVE_DELAYED_MEMORY_CONTENT",
                "LOAD_DELAYED_MEMORY",
                "UNLOAD_DELAYED_MEMORY",
                "UPDATE_DELAYED_MEMORY",
            )
        )

    if bool(runtime_actions.get("CAN_SAVE_ACTIVE_MEMORY", False)):
        expected_actions.extend(
            (
                "SAVE_ACTIVE_MEMORY",
                "RESOLVE_ACTIVE_MEMORY",
            )
        )

    return tuple(expected_actions)


class BrainRuntimeActionTests(unittest.TestCase):

    def test_stream_update_l4_facts_bubble_tracks_marker_write_lifecycle(self):

        class FakeEmitter:

            def __init__(self):
                self.events = []

            async def emit(self, payload):
                self.events.append(dict(payload))

        class FakeBrainClient:

            async def stream(self, **_kwargs):
                yield {
                    "type": "content",
                    "content": "Reply.\n<UPDATE_L4_FACTS>",
                }
                yield {
                    "type": "content",
                    "content": (
                        '\n{"fact_ids":["F1"],'
                        '"message":"The relation is clarified."}\n'
                    ),
                }
                yield {
                    "type": "content",
                    "content": "</UPDATE_L4_FACTS>",
                }

        async def fake_apply_runtime_action_calls(
            _context,
            actions,
            **kwargs,
        ):
            applied.append((tuple(actions), dict(kwargs)))
            return len(tuple(actions))

        async def collect(context):
            return [
                chunk
                async for chunk in ask_brain_stream(
                    client=FakeBrainClient(),
                    text="clarify memory",
                    context=context,
                    runtime_actions={
                        "CAN_UPDATE_L4_FACTS": True,
                    },
                )
            ]

        emitter = FakeEmitter()
        context = SimpleNamespace(
            emitter=emitter,
        )
        applied = []
        original_use_service_as_brain = config.USE_SERVICE_AS_BRAIN
        config.USE_SERVICE_AS_BRAIN = False

        try:
            with patch(
                "clients.brain_client.apply_runtime_action_calls",
                new=fake_apply_runtime_action_calls,
            ):
                chunks = asyncio.run(
                    collect(context)
                )
        finally:
            config.USE_SERVICE_AS_BRAIN = original_use_service_as_brain

        lifecycle = [
            event
            for event in emitter.events
            if event.get("action") == "update_l4_facts"
            and event.get("id")
            and event.get("status") in {
                "started",
                "completed",
            }
        ]

        self.assertGreaterEqual(len(lifecycle), 2)
        self.assertEqual(lifecycle[0]["status"], "started")
        self.assertEqual(lifecycle[1]["status"], "completed")
        self.assertEqual(lifecycle[0]["id"], lifecycle[1]["id"])
        self.assertEqual(lifecycle[0]["text"], "UPDATE_L4_FACTS")
        self.assertEqual(lifecycle[1]["text"], "UPDATE_L4_FACTS")

        self.assertEqual(len(applied), 1)
        actions, kwargs = applied[0]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].name, "UPDATE_L4_FACTS")
        self.assertEqual(
            kwargs["action_display_ids"][id(actions[0])],
            lifecycle[0]["id"],
        )
        self.assertTrue(
            any(
                chunk.get("type") == "content"
                and chunk.get("content") == "Reply."
                for chunk in chunks
            )
        )

    def test_image_attachments_do_not_enter_model_payload_by_default(self):

        context = SimpleNamespace(
            runtime_turn_attachments=[
                {
                    "kind": "image",
                    "name": "screen.png",
                    "data_url": "data:image/png;base64,AAAA",
                },
            ],
        )

        original_use_service_as_brain = config.USE_SERVICE_AS_BRAIN
        original_service_image_input = getattr(
            config,
            "SERVICE_IMAGE_INPUT_ENABLED",
            None,
        )

        try:
            config.USE_SERVICE_AS_BRAIN = True
            if hasattr(
                config,
                "SERVICE_IMAGE_INPUT_ENABLED",
            ):
                delattr(
                    config,
                    "SERVICE_IMAGE_INPUT_ENABLED",
                )

            prompt = build_brain_user_prompt_content(
                "look",
                context=context,
            )
        finally:
            config.USE_SERVICE_AS_BRAIN = original_use_service_as_brain
            if original_service_image_input is not None:
                config.SERVICE_IMAGE_INPUT_ENABLED = original_service_image_input

        self.assertEqual(
            prompt,
            "look",
        )

    def test_image_attachments_enter_model_payload_when_enabled(self):

        context = SimpleNamespace(
            runtime_turn_attachments=[
                {
                    "kind": "image",
                    "name": "screen.png",
                    "data_url": "data:image/png;base64,AAAA",
                },
            ],
        )

        original_use_service_as_brain = config.USE_SERVICE_AS_BRAIN
        original_service_image_input = getattr(
            config,
            "SERVICE_IMAGE_INPUT_ENABLED",
            None,
        )

        try:
            config.USE_SERVICE_AS_BRAIN = True
            config.SERVICE_IMAGE_INPUT_ENABLED = True

            prompt = build_brain_user_prompt_content(
                "look",
                context=context,
            )
        finally:
            config.USE_SERVICE_AS_BRAIN = original_use_service_as_brain
            if original_service_image_input is None:
                delattr(
                    config,
                    "SERVICE_IMAGE_INPUT_ENABLED",
                )
            else:
                config.SERVICE_IMAGE_INPUT_ENABLED = original_service_image_input

        self.assertEqual(
            prompt,
            [
                {
                    "type": "text",
                    "text": "look",
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/png;base64,AAAA",
                    },
                },
            ],
        )

    def test_image_attachments_enter_empty_followup_payload_when_enabled(self):

        context = SimpleNamespace(
            runtime_turn_attachments=[
                {
                    "kind": "image",
                    "name": "screen.png",
                    "data_url": "data:image/png;base64,AAAA",
                },
            ],
        )

        original_use_service_as_brain = config.USE_SERVICE_AS_BRAIN
        original_service_image_input = getattr(
            config,
            "SERVICE_IMAGE_INPUT_ENABLED",
            None,
        )

        try:
            config.USE_SERVICE_AS_BRAIN = True
            config.SERVICE_IMAGE_INPUT_ENABLED = True

            prompt = build_brain_user_prompt_content(
                "",
                context=context,
            )
        finally:
            config.USE_SERVICE_AS_BRAIN = original_use_service_as_brain
            if original_service_image_input is None:
                delattr(
                    config,
                    "SERVICE_IMAGE_INPUT_ENABLED",
                )
            else:
                config.SERVICE_IMAGE_INPUT_ENABLED = original_service_image_input

        self.assertEqual(
            prompt,
            [
                {
                    "type": "text",
                    "text": "",
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/png;base64,AAAA",
                    },
                },
            ],
        )

    def test_brain_system_prompt_keeps_runtime_rule_sentences_separated(self):

        context = SimpleNamespace(
            runtime_memory="",
            runtime_memory_stable="",
            active_memory_records=[
                "active_memory_1: Check whether this should resolve",
            ],
        )

        prompt = build_brain_context(
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
            "RUNTIME ACTION EXECUTION RULES:",
        )
        assert_contains_text(
            self,
            prompt,
            "Use follow-up system ticks in sequence for multi-step tasks.\n"
            "In case of conflict",
        )
        assert_contains_text(
            self,
            prompt,
            "When no actions needed or sequence is done stop instantly and notify user naturally.\n\n"
            "MEMORY AND SESSION PROPOSALS:",
        )
        assert_contains_text(
            self,
            prompt,
            "Active memory does not require explicit confirmation.",
        )
        assert_contains_text(
            self,
            prompt,
            "Use proposals for save-session and delayed-memory decisions",
        )
        assert_not_contains_text(
            self,
            prompt,
            (
                "Never emit a save or memory marker during proposal until "
                "the user clearly accepts it."
            ),
        )
        assert_not_contains_text(
            self,
            prompt,
            "Propose active memory when",
        )
        assert_not_contains_text(
            self,
            prompt,
            (
                "Never emit a save or update marker until the user "
                "explicitly accepts the proposal."
            ),
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
                                    "<SAVE_SESSION>"
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

    def test_non_stream_preserves_save_session_marker_without_trigger(self):

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
                                    "<SAVE_SESSION>."
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
            "The literal marker is <SAVE_SESSION>.",
        )
        self.assertFalse(
            hasattr(
                context,
                "runtime_save_session_requested",
            )
        )

    def test_non_stream_preserves_delayed_memory_marker_without_trigger(self):

        marker_text = (
            "Example:\n"
            "<SAVE_DELAYED_MEMORY_CONTENT>\n"
            '{"demo": {"summary": "quoted marker"}}\n'
            "</SAVE_DELAYED_MEMORY_CONTENT>"
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
                                    "<SAVE_SESSION>"
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
                        "<SAVE_SESSION>"
                    ),
                }
                yield {
                    "type": "thinking",
                    "content": (
                        "Again\n"
                        "<SAVE_SESSION>"
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

        self.assertIn(
            {
                "type": "content",
                "content": "ok",
            },
            chunks,
        )
        self.assertEqual(
            chunks[-1],
            {
                "type": "raw_model_output",
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
                        "<SAVE_SESSION>"
                    ),
                },
                {
                    "type": "thinking",
                    "content": (
                        "Again\n"
                        "<SAVE_SESSION>"
                    ),
                },
            ],
        )

    def test_stream_preserves_explicit_empty_brain_payload(self):

        class FakeBrainClient:
            user_prompt = None

            async def stream(self, **kwargs):
                self.user_prompt = kwargs["user_prompt"]
                yield {
                    "type": "content",
                    "content": "ok",
                }

        class Context:
            pass

        async def collect(client, context):
            return [
                chunk
                async for chunk in ask_brain_stream(
                    client=client,
                    text="original user request",
                    context=context,
                    system_prompt="system prompt",
                    brain_payload="",
                    runtime_actions={},
                )
            ]

        client = FakeBrainClient()
        context = Context()
        original_use_service_as_brain = config.USE_SERVICE_AS_BRAIN
        config.USE_SERVICE_AS_BRAIN = False

        try:
            chunks = asyncio.run(
                collect(
                    client,
                    context,
                )
            )
        finally:
            config.USE_SERVICE_AS_BRAIN = original_use_service_as_brain

        self.assertEqual(
            client.user_prompt,
            "",
        )
        self.assertIn(
            {
                "type": "content",
                "content": "ok",
            },
            chunks,
        )
        self.assertEqual(
            chunks[-1],
            {
                "type": "raw_model_output",
                "content": "ok",
            },
        )

    def test_stream_applies_save_session_marker_from_content_tail(self):

        class FakeBrainClient:
            async def stream(self, **_kwargs):
                yield {
                    "type": "content",
                    "content": "<SAVE_SESSION>",
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
            [
                {
                    "type": "raw_model_output",
                    "content": "<SAVE_SESSION>",
                },
            ],
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

    def test_legacy_stream_runtime_actions_include_message_scope(self):

        class FakeEmitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class FakeBrainClient:
            async def stream(self, **_kwargs):
                yield {
                    "type": "content",
                    "content": "<JIN_COLOR: #00f2ff>",
                }

        async def collect(context):
            return [
                chunk
                async for chunk in ask_brain_stream(
                    client=FakeBrainClient(),
                    text="set color",
                    context=context,
                    system_prompt="system prompt",
                    brain_payload="brain payload",
                    runtime_actions={
                        "CAN_JIN_COLOR": True,
                    },
                )
            ]

        context = SimpleNamespace(
            emitter=FakeEmitter(),
            runtime_action_events=[],
            runtime_search_calls=[],
            runtime_loaded_skills=[],
            runtime_save_session_requested=False,
            runtime_save_session_action_emitted=False,
            runtime_skill_state_barrier_active=False,
            runtime_session_action_history=[],
            runtime_current_turn_id="turn-color-legacy-stream",
            logger=None,
        )
        original_use_service_as_brain = config.USE_SERVICE_AS_BRAIN
        config.USE_SERVICE_AS_BRAIN = False

        try:
            asyncio.run(
                collect(context)
            )
            asyncio.run(
                collect(context)
            )
        finally:
            config.USE_SERVICE_AS_BRAIN = original_use_service_as_brain

        color_events = [
            event
            for event in context.emitter.events
            if (
                event.get("type") == "runtime_action"
                and event.get("action") == "jin_color"
                and event.get("status") == "completed"
            )
        ]
        message_ids = [
            event.get("runtime_message_id")
            for event in color_events
        ]

        self.assertEqual(
            len(color_events),
            2,
        )
        self.assertEqual(
            len(set(message_ids)),
            2,
        )
        self.assertTrue(
            all(message_ids),
        )

    def test_stream_processes_adjacent_markers_after_web_search(self):

        class FakeBrainClient:
            async def stream(self, **_kwargs):
                for content in (
                    "<WEB_SEARCH: Latest astronomical news 2026>",
                    "\n",
                    (
                        "<SAVE_ACTIVE_MEMORY: "
                        "astronomical news tracker>"
                    ),
                    "\n",
                    "<LOAD_SKILL: wildcards>",
                ):
                    yield {
                        "type": "content",
                        "content": content,
                    }

        class Context:
            pass

        async def collect(context):
            return [
                chunk
                async for chunk in ask_brain_stream(
                    client=FakeBrainClient(),
                    text="perform three actions",
                    context=context,
                    system_prompt="system prompt",
                    brain_payload="brain payload",
                    runtime_actions={
                        "CAN_WEB_SEARCH": True,
                        "CAN_SAVE_ACTIVE_MEMORY": True,
                        "CAN_USE_ASSETS": True,
                    },
                )
            ]

        context = Context()
        original_use_service_as_brain = config.USE_SERVICE_AS_BRAIN
        config.USE_SERVICE_AS_BRAIN = False

        try:
            chunks = asyncio.run(
                collect(context)
            )
        finally:
            config.USE_SERVICE_AS_BRAIN = original_use_service_as_brain

        self.assertEqual(
            [
                chunk
                for chunk in chunks
                if chunk.get("type") == "content"
            ],
            [],
        )
        self.assertEqual(
            [
                event["name"]
                for event in context.runtime_action_events
            ],
            [
                "web_search",
                "save_active_memory",
                "load_skill",
            ],
        )
        self.assertEqual(
            context.runtime_search_queries,
            [
                "Latest astronomical news 2026",
            ],
        )
        self.assertEqual(
            len(context.active_memory_records),
            1,
        )
        self.assertIn(
            "astronomical news tracker",
            context.active_memory_records[0],
        )
        self.assertEqual(
            context.runtime_loaded_skills[-1]["name"],
            "wildcards",
        )
        self.assertEqual(
            [
                item["text"]
                for item in context.runtime_session_action_history
            ],
            [
                (
                    "WEB_SEARCH - Latest astronomical news 2026, "
                    "SAVE_ACTIVE_MEMORY - astronomical news tracker"
                ),
            ],
        )
        self.assertEqual(
            [
                item["parts"]
                for item in context.runtime_session_action_history
            ],
            [
                [
                    {
                        "text": "WEB_SEARCH",
                        "detail": "Latest astronomical news 2026",
                    },
                    {
                        "text": "SAVE_ACTIVE_MEMORY",
                        "detail": "astronomical news tracker",
                    },
                ],
            ],
        )

    def test_stream_preserves_text_after_runtime_actions(self):

        class FakeBrainClient:
            def __init__(self):
                self.completed = False

            async def stream(self, **_kwargs):
                for content in (
                    "<WEB_SEARCH: runtime action regression>",
                    "\n",
                    "Про",
                    "должаю видимый текст.\n",
                    "<JIN_COLOR: #ff00ff>",
                    "\nФинал генерации.",
                ):
                    yield {
                        "type": "content",
                        "content": content,
                    }

                self.completed = True

        class Context:
            pass

        async def collect(client, context):
            return [
                chunk
                async for chunk in ask_brain_stream(
                    client=client,
                    text="run runtime actions",
                    context=context,
                    system_prompt="system prompt",
                    brain_payload="brain payload",
                    runtime_actions={
                        "CAN_WEB_SEARCH": True,
                        "CAN_JIN_COLOR": True,
                    },
                )
            ]

        context = Context()
        client = FakeBrainClient()
        original_use_service_as_brain = config.USE_SERVICE_AS_BRAIN
        config.USE_SERVICE_AS_BRAIN = False

        try:
            chunks = asyncio.run(
                collect(client, context)
            )
        finally:
            config.USE_SERVICE_AS_BRAIN = original_use_service_as_brain

        visible_text = "".join(
            chunk.get("content", "")
            for chunk in chunks
            if chunk.get("type") == "content"
        )
        raw_model_output = next(
            chunk.get("content", "")
            for chunk in chunks
            if chunk.get("type") == "raw_model_output"
        )

        self.assertTrue(client.completed)
        self.assertEqual(
            visible_text,
            "\nПродолжаю видимый текст.\nФинал генерации.",
        )
        self.assertNotIn(
            "WEB_SEARCH",
            visible_text,
        )
        self.assertNotIn(
            "JIN_COLOR",
            visible_text,
        )
        self.assertIn(
            "Продолжаю видимый текст.",
            raw_model_output,
        )
        self.assertIn(
            "Финал генерации.",
            raw_model_output,
        )
        self.assertEqual(
            [
                event["name"]
                for event in context.runtime_action_events
            ],
            [
                "web_search",
                "jin_color",
            ],
        )

    def test_runtime_action_dedup_scopes_to_single_message(self):

        async def run_case():
            context = SimpleNamespace(
                runtime_action_events=[],
                runtime_search_calls=[],
                runtime_loaded_skills=[],
                runtime_save_session_requested=False,
                runtime_save_session_action_emitted=False,
                runtime_skill_state_barrier_active=False,
                runtime_current_turn_id="turn-action-dedup",
                logger=None,
            )
            duplicate_message_actions = (
                RuntimeActionCall(
                    name="WEB_SEARCH",
                    payload="blue tomato",
                ),
                RuntimeActionCall(
                    name="WEB_SEARCH",
                    payload="blue tomato",
                ),
                RuntimeActionCall(
                    name="CLEAN_TOOL_RESULTS",
                    payload="",
                ),
                RuntimeActionCall(
                    name="CLEAN_TOOL_RESULTS",
                    payload="",
                ),
            )

            first_count = await apply_runtime_action_calls(
                context,
                duplicate_message_actions,
                runtime_message_id="message-one",
            )

            context.runtime_search_queries = []
            context.runtime_search_calls = []

            second_count = await apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="WEB_SEARCH",
                        payload="blue tomato",
                    ),
                    RuntimeActionCall(
                        name="CLEAN_TOOL_RESULTS",
                        payload="",
                    ),
                ),
                runtime_message_id="message-two",
            )

            context.runtime_search_queries = []
            context.runtime_search_calls = []

            followup_count = await apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="WEB_SEARCH",
                        payload="blue tomato",
                    ),
                ),
                runtime_message_id="message-follow-up",
            )

            return (
                first_count,
                second_count,
                followup_count,
                [
                    event.get("name")
                    for event in context.runtime_action_events
                ],
            )

        (
            first_count,
            second_count,
            followup_count,
            action_names,
        ) = asyncio.run(
            run_case()
        )

        self.assertEqual(
            first_count,
            2,
        )
        self.assertEqual(
            second_count,
            2,
        )
        self.assertEqual(
            followup_count,
            1,
        )
        self.assertEqual(
            action_names,
            [
                "web_search",
                "clean_tool_results",
                "web_search",
                "clean_tool_results",
                "web_search",
            ],
        )

    def test_stream_groups_two_current_action_markers_into_one_history_item(self):

        class FakeBrainClient:
            async def stream(self, **_kwargs):
                yield {
                    "type": "content",
                    "content": (
                        "<SAVE_SESSION>\n"
                        "<JIN_COLOR: #112233>"
                    ),
                }

        class Context:
            pass

        async def collect(context):
            return [
                chunk
                async for chunk in ask_brain_stream(
                    client=FakeBrainClient(),
                    text="save session and set color",
                    context=context,
                    runtime_actions={
                        "CAN_SAVE_SESSION": True,
                        "CAN_JIN_COLOR": True,
                    },
                )
            ]

        context = Context()
        original_use_service_as_brain = config.USE_SERVICE_AS_BRAIN
        config.USE_SERVICE_AS_BRAIN = False

        try:
            asyncio.run(collect(context))
        finally:
            config.USE_SERVICE_AS_BRAIN = original_use_service_as_brain

        self.assertEqual(
            [item["text"] for item in context.runtime_session_action_history],
            ["SAVE_SESSION, JIN_COLOR"],
        )

        prompt = build_brain_context(
            context=context,
            runtime_actions={
                "CAN_SAVE_SESSION": True,
                "CAN_JIN_COLOR": True,
            },
        )
        self.assertIn("<SESSION_ACTIONS_HISTORY>", prompt)
        self.assertIn("1. SAVE_SESSION, JIN_COLOR", prompt)

    def test_stream_history_preserves_duplicate_markers_after_action_dedup(self):

        class FakeBrainClient:
            async def stream(self, **_kwargs):
                yield {
                    "type": "content",
                    "content": (
                        "<SAVE_SESSION>\n"
                        "<SAVE_SESSION>"
                    ),
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
            asyncio.run(
                collect(
                    context
                )
            )
        finally:
            config.USE_SERVICE_AS_BRAIN = original_use_service_as_brain

        self.assertEqual(
            context.runtime_action_events,
            [
                {
                    "name": "save_session",
                },
            ],
        )
        self.assertEqual(
            [
                item["text"]
                for item in context.runtime_session_action_history
            ],
            [
                "SAVE_SESSION (count: 2)",
            ],
        )

    def test_session_history_compacts_many_repeated_markers(self):

        context = SimpleNamespace(
            runtime_session_action_history=[],
        )

        replace_session_action_history_since(
            context,
            0,
            [
                "resolve_active_memory",
            ] * 24,
        )

        self.assertEqual(
            context.runtime_session_action_history[0]["text"],
            "RESOLVE_ACTIVE_MEMORY (count: 24)",
        )

        prompt = build_brain_context(
            context=context,
            runtime_actions={},
        )

        self.assertIn(
            "1. RESOLVE_ACTIVE_MEMORY (count: 24)",
            prompt,
        )

    def test_session_history_includes_loaded_and_unloaded_skill_names(self):

        formatted = format_session_action_marker_names([
            RuntimeActionCall(
                name="LIST_SKILLS",
            ),
            RuntimeActionCall(
                name="LOAD_SKILL",
                payload="wildcards",
            ),
            RuntimeActionCall(
                name="LOAD_SKILL",
                payload="file_manager",
            ),
            RuntimeActionCall(
                name="LOAD_SKILL",
                payload="wildcards",
            ),
            RuntimeActionCall(
                name="UNLOAD_SKILL",
                payload="image_prompt_generator",
            ),
            RuntimeActionCall(
                name="UNLOAD_SKILL",
                payload="image_prompt_generator",
            ),
            RuntimeActionCall(
                name="UNLOAD_SKILL",
                payload="file_manager",
            ),
        ])

        self.assertEqual(
            formatted,
            (
                "LIST_SKILLS, "
                "LOAD_SKILL: wildcards, "
                "LOAD_SKILL: file_manager, "
                "UNLOAD_SKILL: image_prompt_generator, "
                "UNLOAD_SKILL: file_manager"
            ),
        )

    def test_session_history_groups_current_marker_parts_for_turn(self):

        context = SimpleNamespace(
            runtime_session_action_history=[],
            runtime_current_turn_id="turn-1",
        )

        replace_session_action_history_since(
            context,
            0,
            [
                RuntimeActionCall(name="WEB_SEARCH", payload="latest news"),
                RuntimeActionCall(name="SAVE_ACTIVE_MEMORY", payload="remember coffee"),
                RuntimeActionCall(name="IDLE", payload="5s"),
                RuntimeActionCall(name="LOAD_SKILL", payload="wildcards"),
                RuntimeActionCall(name="LOAD_SKILL", payload="file_manager"),
            ],
        )

        self.assertEqual(
            [item["parts"] for item in context.runtime_session_action_history],
            [[
                {"text": "WEB_SEARCH", "detail": "latest news"},
                {"text": "SAVE_ACTIVE_MEMORY", "detail": "remember coffee"},
                {"text": "IDLE", "detail": "5s"},
                {"text": "LOAD_SKILL: wildcards"},
                {"text": "LOAD_SKILL: file_manager"},
            ]],
        )

    def test_jin_color_history_preserves_ordered_color_swatches(self):

        context = SimpleNamespace(
            runtime_session_action_history=[],
            runtime_current_turn_id="turn-1",
        )

        replace_session_action_history_since(
            context,
            0,
            [
                RuntimeActionCall(
                    name="JIN_COLOR",
                    payload="#ff0000",
                ),
                RuntimeActionCall(
                    name="JIN_COLOR",
                    payload="#00ff00",
                ),
                RuntimeActionCall(
                    name="JIN_COLOR",
                    payload="#ff0000",
                ),
            ],
        )

        self.assertEqual(
            context.runtime_session_action_history[0]["parts"],
            [
                {
                    "text": "JIN_COLOR",
                    "colors": [
                        "#ff0000",
                        "#00ff00",
                        "#ff0000",
                    ],
                    "count": 3,
                },
            ],
        )

        self.assertEqual(
            build_session_actions_update_items(
                context,
                current_sequence=False,
            )[0]["parts"],
            [
                {
                    "text": "JIN_COLOR",
                    "colors": [
                        "#ff0000",
                        "#00ff00",
                        "#ff0000",
                    ],
                    "count": 3,
                },
            ],
        )

    def test_jin_color_history_separates_marker_count_from_applied_colors(self):

        context = SimpleNamespace(
            runtime_session_action_history=[],
            runtime_current_turn_id="turn-1",
        )

        replace_session_action_history_since(
            context,
            0,
            [{
                "name": "JIN_COLOR",
                "colors": [
                    "#ff0000",
                ],
                "marker_count": 4,
            }],
        )

        self.assertEqual(
            context.runtime_session_action_history[0]["parts"],
            [{
                "text": "JIN_COLOR",
                "colors": [
                    "#ff0000",
                ],
                "count": 4,
            }],
        )

    def test_payload_distinct_active_memory_history_uses_separate_parts(self):

        context = SimpleNamespace(
            runtime_session_action_history=[],
            runtime_current_turn_id="turn-1",
        )

        replace_session_action_history_since(
            context,
            0,
            [{
                "name": "SAVE_ACTIVE_MEMORY",
                "marker_count": 2,
                "payloads": [
                    'CONDITIONS: слово "кулёк"',
                    'CONDITIONS: слово "кукушка"',
                ],
            }],
        )

        self.assertEqual(
            [
                item["parts"][0]
                for item in context.runtime_session_action_history
            ],
            [
                {
                    "text": "SAVE_ACTIVE_MEMORY",
                    "detail": 'CONDITIONS: слово "кулёк"',
                },
                {
                    "text": "SAVE_ACTIVE_MEMORY",
                    "detail": 'CONDITIONS: слово "кукушка"',
                },
            ],
        )

    def test_payload_distinct_resolve_active_memory_history_uses_separate_parts(self):

        context = SimpleNamespace(
            runtime_session_action_history=[],
            runtime_current_turn_id="turn-1",
        )

        replace_session_action_history_since(
            context,
            0,
            [{
                "name": "RESOLVE_ACTIVE_MEMORY",
                "marker_count": 2,
                "payloads": [
                    "enrrqo",
                    "yfpywn",
                ],
            }],
        )

        self.assertEqual(
            context.runtime_session_action_history[0]["parts"],
            [
                {
                    "text": "RESOLVE_ACTIVE_MEMORY",
                    "detail": "enrrqo",
                },
                {
                    "text": "RESOLVE_ACTIVE_MEMORY",
                    "detail": "yfpywn",
                },
            ],
        )

    def test_payload_distinct_save_delayed_history_uses_separate_parts(self):

        context = SimpleNamespace(
            runtime_session_action_history=[],
            runtime_current_turn_id="turn-1",
        )

        replace_session_action_history_since(
            context,
            0,
            [{
                "name": "SAVE_DELAYED_MEMORY_CONTENT",
                "marker_count": 2,
                "payloads": [
                    '{"report_1":{"title":"First report","body":"one"}}',
                    '{"report_2":{"title":"Second report","body":"two"}}',
                ],
            }],
        )

        self.assertEqual(
            context.runtime_session_action_history[0]["parts"],
            [
                {
                    "text": "SAVE_DELAYED_MEMORY_CONTENT",
                    "detail": "First report",
                },
                {
                    "text": "SAVE_DELAYED_MEMORY_CONTENT",
                    "detail": "Second report",
                },
            ],
        )

    def test_load_delayed_history_splits_by_raw_id(self):

        context = SimpleNamespace(
            runtime_session_action_history=[],
            runtime_current_turn_id="turn-1",
        )

        replace_session_action_history_since(
            context,
            0,
            [{
                "name": "LOAD_DELAYED_MEMORY",
                "marker_count": 2,
                "payloads": [
                    "Shared title",
                    "Shared title",
                ],
                "raw_payloads": [
                    "abc123",
                    "def456",
                ],
            }],
        )

        self.assertEqual(
            context.runtime_session_action_history[0]["parts"],
            [
                {
                    "text": "LOAD_DELAYED_MEMORY",
                    "detail": "Shared title",
                    "id": "abc123",
                },
                {
                    "text": "LOAD_DELAYED_MEMORY",
                    "detail": "Shared title",
                    "id": "def456",
                },
            ],
        )

    def test_unload_delayed_history_splits_by_raw_id(self):

        context = SimpleNamespace(
            runtime_session_action_history=[],
            runtime_current_turn_id="turn-1",
        )

        replace_session_action_history_since(
            context,
            0,
            [{
                "name": "UNLOAD_DELAYED_MEMORY",
                "marker_count": 2,
                "payloads": [
                    "First report",
                    "Second report",
                ],
                "raw_payloads": [
                    "abc123",
                    "def456",
                ],
            }],
        )

        self.assertEqual(
            context.runtime_session_action_history[0]["parts"],
            [
                {
                    "text": "UNLOAD_DELAYED_MEMORY",
                    "detail": "First report",
                    "id": "abc123",
                },
                {
                    "text": "UNLOAD_DELAYED_MEMORY",
                    "detail": "Second report",
                    "id": "def456",
                },
            ],
        )

    def test_session_history_includes_saved_content_title(self):

        title = (
            "Концептуальное позиционирование JIN Core: "
            "Среда мышления vs Интерфейс чата"
        )
        action = RuntimeActionCall(
            name="SAVE_DELAYED_MEMORY_CONTENT",
            payload=(
                '{"report_1":{"title":"'
                + title
                + '","body":"report"}}'
            ),
        )
        context = SimpleNamespace(
            runtime_session_action_history=[],
            runtime_current_turn_id="turn-1",
            runtime_turn_started_at=0,
            runtime_action_sequence_turn_ids=[],
        )

        replace_session_action_history_since(
            context,
            0,
            [action],
        )

        expected_text = (
            "SAVE_DELAYED_MEMORY_CONTENT - "
            + title
        )

        self.assertEqual(
            context.runtime_session_action_history[0]["text"],
            expected_text,
        )
        self.assertIn(
            (
                "JIN message 1 executed: "
                f"{expected_text.replace(' - ', ': ', 1)}"
            ),
            build_session_actions_history_context(
                context,
                current_sequence=True,
            ),
        )

    def test_replace_session_history_preserves_skill_marker_payloads(self):

        context = SimpleNamespace(
            runtime_session_action_history=[],
        )

        replace_session_action_history_since(
            context,
            0,
            [
                RuntimeActionCall(
                    name="LOAD_SKILL",
                    payload="wildcards",
                ),
                RuntimeActionCall(
                    name="LOAD_SKILL",
                    payload="wildcards",
                ),
                RuntimeActionCall(
                    name="LOAD_SKILL",
                    payload="file_manager",
                ),
                RuntimeActionCall(
                    name="UNLOAD_SKILL",
                    payload="image_prompt_generator",
                ),
            ],
        )

        self.assertEqual(
            context.runtime_session_action_history[0]["text"],
            (
                "LOAD_SKILL: wildcards, "
                "LOAD_SKILL: file_manager, "
                "UNLOAD_SKILL: image_prompt_generator"
            ),
        )

    def test_stream_preserves_duplicate_failed_load_skill_marker(self):

        class FakeBrainClient:
            async def stream(self, **_kwargs):
                yield {
                    "type": "content",
                    "content": (
                        "<LOAD_SKILL: name of skill >\n"
                        "<LOAD_SKILL: name of skill >"
                    ),
                }

        class Context:
            pass

        class TrackingEmitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(
                    event
                )

        async def collect(context):
            chunks = []

            async for chunk in ask_brain_stream(
                client=FakeBrainClient(),
                text="load a skill",
                context=context,
                runtime_actions={
                    "CAN_USE_ASSETS": True,
                },
            ):
                chunks.append(
                    chunk
                )

            return chunks

        context = Context()
        context.runtime_current_turn_id = "turn-1"
        context.emitter = TrackingEmitter()
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

        visible_text = "".join(
            chunk.get(
                "content",
                "",
            )
            for chunk in chunks
            if chunk.get("type") == "content"
        )

        self.assertIn(
            "<LOAD_SKILL: name of skill >",
            visible_text,
        )
        self.assertEqual(
            context.runtime_action_events,
            [
                {
                    "name": "load_skill",
                    "runtime_turn_id": "turn-1",
                    "payload": "name of skill",
                },
            ],
        )
        self.assertEqual(
            context.runtime_asset_results[-1]["action"],
            "load_skill",
        )
        self.assertEqual(
            context.runtime_asset_results[-1]["error"],
            "skill_not_found",
        )
        self.assertEqual(
            context.runtime_session_action_history[-1]["text"],
            (
                "LOAD_SKILL: name of skill "
                "( does not exist )"
            ),
        )
        self.assertIn(
            "LOAD_SKILL: name of skill ( does not exist )",
            build_session_actions_history_context(
                context,
                current_sequence=True,
            ),
        )

        counter_final_events = [
            event
            for event in context.emitter.events
            if event.get("type") == "runtime_action"
            and event.get("action") == "load_skill"
            and event.get("status") == "counter_final"
        ]

        self.assertEqual(
            counter_final_events,
            [],
        )

    def test_stream_allows_four_identical_jin_color_markers(self):

        state = {
            "emitted_markers": 0,
        }

        class FakeBrainClient:
            async def stream(self, **_kwargs):
                for index in range(4):
                    state["emitted_markers"] = index + 1
                    yield {
                        "type": "content",
                        "content": "<JIN_COLOR: #ff0000>",
                    }

        class TrackingEmitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(
                    event
                )

        class Context:
            pass

        async def collect(context):
            chunks = []

            async for chunk in ask_brain_stream(
                client=FakeBrainClient(),
                text="four red markers",
                context=context,
                runtime_actions={
                    "CAN_JIN_COLOR": True,
                },
            ):
                chunks.append(
                    chunk
                )

            return chunks

        context = Context()
        context.emitter = TrackingEmitter()
        context.runtime_current_turn_id = "turn-red-four"
        context.runtime_turn_started_at = 0
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

        counted_events = [
            event
            for event in context.emitter.events
            if (
                event.get("type") == "runtime_action"
                and event.get("action") == "jin_color"
                and event.get("status") == "counted"
            )
        ]

        self.assertEqual(
            chunks,
            [
                {
                    "type": "raw_model_output",
                    "content": (
                        "<JIN_COLOR: #ff0000>"
                        "<JIN_COLOR: #ff0000>"
                        "<JIN_COLOR: #ff0000>"
                        "<JIN_COLOR: #ff0000>"
                    ),
                },
            ],
        )
        self.assertEqual(
            state["emitted_markers"],
            4,
        )
        self.assertEqual(
            len(context.runtime_action_events),
            1,
        )
        self.assertEqual(
            [
                event["marker_count"]
                for event in counted_events
            ],
            [
                1,
                2,
                3,
                4,
            ],
        )
        self.assertEqual(
            counted_events[-1]["colors"],
            [
                "#ff0000",
            ],
        )
        self.assertEqual(
            counted_events[-1]["marker_count"],
            4,
        )
        self.assertEqual(
            context.runtime_session_action_history[-1]["parts"],
            [{
                "text": "JIN_COLOR",
                "colors": [
                    "#ff0000",
                ],
                "count": 4,
            }],
        )

    def test_stream_interrupts_on_fifth_identical_jin_color_marker(self):

        state = {
            "emitted_markers": 0,
        }

        class FakeBrainClient:
            async def stream(self, **_kwargs):
                for index in range(6):
                    state["emitted_markers"] = index + 1
                    yield {
                        "type": "content",
                        "content": "<JIN_COLOR: #ff0000>",
                    }

        class TrackingEmitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(
                    event
                )

        class Context:
            pass

        async def collect(context):
            chunks = []

            async for chunk in ask_brain_stream(
                client=FakeBrainClient(),
                text="five red markers",
                context=context,
                runtime_actions={
                    "CAN_JIN_COLOR": True,
                },
            ):
                chunks.append(
                    chunk
                )

            return chunks

        context = Context()
        context.emitter = TrackingEmitter()
        context.runtime_current_turn_id = "turn-red-five"
        context.runtime_turn_started_at = 0
        original_use_service_as_brain = config.USE_SERVICE_AS_BRAIN
        config.USE_SERVICE_AS_BRAIN = False

        try:
            asyncio.run(
                collect(
                    context
                )
            )
        finally:
            config.USE_SERVICE_AS_BRAIN = original_use_service_as_brain

        interruption_events = [
            event
            for event in context.emitter.events
            if (
                event.get("type") == "runtime_action"
                and event.get("action") == "jin_color"
                and event.get("status") == "interrupted"
            )
        ]

        self.assertEqual(
            state["emitted_markers"],
            5,
        )
        self.assertEqual(
            len(context.runtime_action_events),
            1,
        )
        self.assertEqual(
            len(interruption_events),
            1,
        )
        self.assertEqual(
            interruption_events[0]["colors"],
            [
                "#ff0000",
            ],
        )
        self.assertEqual(
            interruption_events[0]["marker_count"],
            5,
        )
        self.assertEqual(
            context.runtime_session_action_history[-1]["parts"],
            [{
                "text": "JIN_COLOR",
                "colors": [
                    "#ff0000",
                ],
                "count": 5,
            }],
        )

    def test_stream_stops_repeated_resolve_active_memory_markers(self):

        class FakeBrainClient:
            async def stream(self, **_kwargs):
                for _ in range(4):
                    yield {
                        "type": "content",
                        "content": (
                            "<RESOLVE_ACTIVE_MEMORY: "
                            "active_memory_id: 5fdg4g>"
                        ),
                    }

        class Context:
            pass

        async def collect(context):
            chunks = []

            async for chunk in ask_brain_stream(
                client=FakeBrainClient(),
                text="how are you",
                context=context,
                runtime_actions={
                    "CAN_SAVE_ACTIVE_MEMORY": True,
                },
            ):
                chunks.append(
                    chunk
                )

            return chunks

        context = Context()
        context.runtime_memory = (
            "active_memory_1: remember cuckoo "
            "[ active_memory_id: 5fdg4g ] [ status: pending ]"
        )
        context.runtime_memory_stable = context.runtime_memory
        context.active_memory_records = [
            context.runtime_memory,
        ]
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
            [
                {
                    "type": "raw_model_output",
                    "content": (
                        "<RESOLVE_ACTIVE_MEMORY: active_memory_id: 5fdg4g>"
                        "<RESOLVE_ACTIVE_MEMORY: active_memory_id: 5fdg4g>"
                        "<RESOLVE_ACTIVE_MEMORY: active_memory_id: 5fdg4g>"
                        "<RESOLVE_ACTIVE_MEMORY: active_memory_id: 5fdg4g>"
                    ),
                },
            ],
        )
        self.assertEqual(
            context.active_memory_records,
            [],
        )
        self.assertEqual(
            context.runtime_action_events,
            [
                {
                    "name": "resolve_active_memory",
                    "id": "5fdg4g",
                    "payload": "active_memory_id: 5fdg4g",
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
                        "<WEB_SEARCH:blue tomato>\n"
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

    def test_empty_asset_action_markers_stay_visible_without_runtime_bubble(self):

        class FakeBrainClient:

            def __init__(self, content):
                self.content = content

            async def stream(self, **_kwargs):
                yield {
                    "type": "content",
                    "content": self.content,
                }

        class TrackingEmitter:

            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        async def collect(marker, context):
            chunks = []

            async for chunk in ask_brain_stream(
                client=FakeBrainClient(marker),
                text="test empty asset marker",
                context=context,
                system_prompt="system prompt",
                brain_payload="brain payload",
                runtime_actions={
                    "CAN_USE_ASSETS": True,
                },
            ):
                chunks.append(chunk)

            return chunks

        variants = (
            "<ASSET_ACTION>",
            "<ASSET_ACTION/>",
            "<ASSET_ACTION></ASSET_ACTION>",
            "</ASSET_ACTION>",
        )
        original_use_service_as_brain = config.USE_SERVICE_AS_BRAIN
        config.USE_SERVICE_AS_BRAIN = False

        try:
            for marker in variants:
                with self.subTest(marker=marker):
                    context = Context()
                    context.emitter = TrackingEmitter()
                    chunks = asyncio.run(
                        collect(marker, context)
                    )
                    visible_text = "".join(
                        chunk.get("content", "")
                        for chunk in chunks
                        if chunk.get("type") == "content"
                    )
                    runtime_events = [
                        event
                        for event in context.emitter.events
                        if event.get("type") == "runtime_action"
                    ]

                    self.assertEqual(
                        visible_text,
                        marker,
                    )
                    self.assertEqual(
                        runtime_events,
                        [],
                    )
        finally:
            config.USE_SERVICE_AS_BRAIN = original_use_service_as_brain


    def test_unclosed_asset_action_after_other_marker_stays_text_without_bubble(self):

        class FakeBrainClient:

            async def stream(self, **_kwargs):
                yield {
                    "type": "content",
                    "content": "<CLEAN_TOOL_RESULTS>\n",
                }
                yield {
                    "type": "content",
                    "content": "<ASSET_ACTION>\n",
                }
                yield {
                    "type": "content",
                    "content": (
                        "Продолжаем тест. Следующий маркер – "
                        "ASSET_ACTION."
                    ),
                }

        class TrackingEmitter:

            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        async def collect(context):
            return [
                chunk
                async for chunk in ask_brain_stream(
                    client=FakeBrainClient(),
                    text="test marker sequence",
                    context=context,
                    system_prompt="system prompt",
                    brain_payload="brain payload",
                    runtime_actions={
                        "CAN_CLEAN_TOOL_RESULTS": True,
                        "CAN_USE_ASSETS": True,
                    },
                )
            ]

        context = Context()
        context.emitter = TrackingEmitter()
        original_use_service_as_brain = config.USE_SERVICE_AS_BRAIN
        config.USE_SERVICE_AS_BRAIN = False

        try:
            chunks = asyncio.run(
                collect(context)
            )
        finally:
            config.USE_SERVICE_AS_BRAIN = original_use_service_as_brain

        visible_text = "".join(
            chunk.get("content", "")
            for chunk in chunks
            if chunk.get("type") == "content"
        )
        asset_events = [
            event
            for event in context.emitter.events
            if event.get("action") == "asset_action"
        ]

        self.assertEqual(
            asset_events,
            [],
        )
        self.assertIn(
            "<ASSET_ACTION>",
            visible_text,
        )
        self.assertIn(
            "Продолжаем тест.",
            visible_text,
        )
        self.assertEqual(
            [
                event.get("name")
                for event in context.runtime_action_events
            ],
            [
                "clean_tool_results",
            ],
        )


    def test_non_followup_delayed_memory_action_keeps_visible_text(self):

        visible_answer = (
            "Я просмотрел доступные отчёты и выбрал отчёт. "
            "Добавляю его в контекст."
        )

        class FakeBrainClient:

            async def stream(self, **_kwargs):
                yield {
                    "type": "content",
                    "content": (
                        "<LOAD_DELAYED_MEMORY: pwajtw>\n\n"
                        f"{visible_answer}\n\n"
                        "<CLEAN_TOOL_RESULTS>"
                    ),
                }

        class TrackingEmitter:

            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        async def collect(context):
            return [
                chunk
                async for chunk in ask_brain_stream(
                    client=FakeBrainClient(),
                    text="append one delayed memory report",
                    context=context,
                    system_prompt="system prompt",
                    brain_payload="brain payload",
                    runtime_actions={
                        "CAN_SAVE_DELAYED_MEMORY": True,
                        "CAN_CLEAN_TOOL_RESULTS": True,
                    },
                )
            ]

        context = Context()
        context.emitter = TrackingEmitter()
        context.runtime_current_turn_id = "turn-delayed-append"
        context.session_id = "session-1"
        context.timestamp = "2026-08-01T16:20:00"
        context.delayed_memory_reports = {
            "pwajtw": {
                "title": "Архитектурный Срез",
                "summary": "Current JIN architecture.",
                "tags": ["architecture"],
                "body": "Complete report body.",
            },
        }
        context.runtime_tool_results = [
            {
                "kind": "asset",
                "result": {
                    "ok": True,
                },
            },
        ]
        context.runtime_tool_results_turn_count = 1
        context.runtime_tool_results_generation = 0

        original_use_service_as_brain = config.USE_SERVICE_AS_BRAIN
        config.USE_SERVICE_AS_BRAIN = False

        try:
            chunks = asyncio.run(
                collect(context)
            )
        finally:
            config.USE_SERVICE_AS_BRAIN = original_use_service_as_brain

        visible_text = "".join(
            chunk.get("content", "")
            for chunk in chunks
            if chunk.get("type") == "content"
        )

        self.assertEqual(
            visible_text,
            visible_answer,
        )
        self.assertEqual(
            [
                event.get("name")
                for event in context.runtime_action_events
            ],
            [
                "load_delayed_memory",
                "clean_tool_results",
            ],
        )


    def test_stream_asset_action_strips_marker_and_keeps_text(self):

        class FakeBrainClient:
            async def stream(self, **_kwargs):
                yield {
                    "type": "content",
                    "content": (
                        "\n<ASSET_ACTION>\n"
                        "{\n"
                        '  "action": "create_wildcard_file",\n'
                        '  "args": {\n'
                        '    "path": "clothing/shoes",\n'
                        '    "content": "sneakers\\nboots\\nheels"\n'
                        "  }\n"
                        "}\n"
                        "</ASSET_ACTION>\n"
                        "This should remain visible."
                    ),
                }

        class Context:
            pass

        async def collect(context):
            chunks = []

            async for chunk in ask_brain_stream(
                client=FakeBrainClient(),
                text="create shoes wildcard",
                context=context,
                system_prompt="system prompt",
                brain_payload="brain payload",
                runtime_actions={
                    "CAN_USE_ASSETS": True,
                },
            ):
                chunks.append(
                    chunk
                )

            return chunks

        original_use_service_as_brain = config.USE_SERVICE_AS_BRAIN
        config.USE_SERVICE_AS_BRAIN = False

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                with contextlib.ExitStack() as stack:
                    for patcher in patch_asset_roots(root):
                        stack.enter_context(patcher)

                    context = Context()

                    chunks = asyncio.run(
                        collect(
                            context
                        )
                    )

                    visible_text = "".join(
                        chunk.get(
                            "content",
                            "",
                        )
                        for chunk in chunks
                        if chunk.get("type") == "content"
                    )

                    self.assertEqual(
                        visible_text,
                        "This should remain visible.",
                    )
                    self.assertNotIn(
                        "ASSET_ACTION",
                        visible_text,
                    )
                    self.assertEqual(
                        context.runtime_action_events[0]["name"],
                        "asset_action",
                    )
                    self.assertEqual(
                        context.runtime_asset_results[0]["action"],
                        "create_wildcard_file",
                    )
                    self.assertTrue(
                        (
                            root
                            / "assets"
                            / "wildcards"
                            / "clothing"
                            / "shoes.txt"
                        ).exists()
                    )
        finally:
            config.USE_SERVICE_AS_BRAIN = original_use_service_as_brain

    def test_split_stream_asset_action_starts_chat_bubble_on_opening_tag(self):

        class FakeBrainClient:
            async def stream(self, **_kwargs):
                yield {
                    "type": "content",
                    "content": "<ASSET_ACTION>\n",
                }
                yield {
                    "type": "content",
                    "content": (
                        "{\n"
                        '  "action": "create_asset_file",\n'
                        '  "path": "assets/outputs/rain_simulator.py",\n'
                        '  "content": "print(\\"rain\\")"\n'
                        "}\n"
                    ),
                }
                yield {
                    "type": "content",
                    "content": (
                        "</ASSET_ACTION>\n"
                        "This should remain visible."
                    ),
                }

        class Context:
            pass

        async def collect(context):
            chunks = []

            async for chunk in ask_brain_stream(
                client=FakeBrainClient(),
                text="create rain simulator",
                context=context,
                system_prompt="system prompt",
                brain_payload="brain payload",
                runtime_actions={
                    "CAN_USE_ASSETS": True,
                },
            ):
                chunks.append(
                    chunk
                )

            return chunks

        original_use_service_as_brain = config.USE_SERVICE_AS_BRAIN
        config.USE_SERVICE_AS_BRAIN = False

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                output_path = (
                    root
                    / "assets"
                    / "outputs"
                    / "rain_simulator.py"
                )

                class TrackingEmitter:
                    def __init__(self):
                        self.events = []

                    async def emit(self, event):
                        self.events.append({
                            **event,
                            "file_exists_at_emit": output_path.exists(),
                        })

                with contextlib.ExitStack() as stack:
                    for patcher in patch_asset_roots(root):
                        stack.enter_context(patcher)

                    context = Context()
                    context.emitter = TrackingEmitter()

                    chunks = asyncio.run(
                        collect(
                            context
                        )
                    )

                    visible_text = "".join(
                        chunk.get(
                            "content",
                            "",
                        )
                        for chunk in chunks
                        if chunk.get("type") == "content"
                    )
                    runtime_events = [
                        event
                        for event in context.emitter.events
                        if event.get("type") == "runtime_action"
                    ]

                    self.assertEqual(
                        visible_text,
                        "This should remain visible.",
                    )
                    self.assertEqual(
                        [
                            event.get("status")
                            for event in runtime_events
                        ],
                        [
                            "started",
                            "counted",
                            "started",
                            "completed",
                            "counter_final",
                        ],
                    )
                    lifecycle_events = [
                        event
                        for event in runtime_events
                        if not event.get("counter_only")
                    ]
                    self.assertEqual(
                        len({
                            event.get("id")
                            for event in lifecycle_events
                        }),
                        1,
                    )
                    self.assertEqual(
                        runtime_events[0]["text"],
                        "ASSET_ACTION",
                    )
                    self.assertTrue(
                        runtime_events[0]["close_tag"],
                    )
                    self.assertFalse(
                        runtime_events[0]["file_exists_at_emit"],
                    )
                    self.assertEqual(
                        lifecycle_events[1]["text"],
                        (
                            "ASSET_ACTION: create_asset_file - "
                            "assets/outputs/rain_simulator.py"
                        ),
                    )
                    self.assertEqual(
                        lifecycle_events[2]["text"],
                        "Created asset file - assets/outputs/rain_simulator.py",
                    )
                    self.assertFalse(
                        lifecycle_events[1]["file_exists_at_emit"],
                    )
                    self.assertTrue(
                        lifecycle_events[2]["file_exists_at_emit"],
                    )
                    self.assertTrue(
                        output_path.exists(),
                    )
        finally:
            config.USE_SERVICE_AS_BRAIN = original_use_service_as_brain

    def test_split_stream_delayed_memory_reuses_started_bubble_id_on_completion(self):

        class FakeBrainClient:
            async def stream(self, **_kwargs):
                yield {
                    "type": "content",
                    "content": "<SAVE_DELAYED_MEMORY_CONTENT>\n",
                }
                yield {
                    "type": "content",
                    "content": (
                        "title: Test delayed memory report\n"
                        "summary: Current runtime state.\n"
                        "tags: runtime, test\n"
                        "body: Complete report body.\n"
                    ),
                }
                yield {
                    "type": "content",
                    "content": "</SAVE_DELAYED_MEMORY_CONTENT>\n",
                }

        class TrackingEmitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        async def collect(context):
            chunks = []

            async for chunk in ask_brain_stream(
                client=FakeBrainClient(),
                text="создай отчёт delayed memory",
                context=context,
                runtime_actions={
                    "CAN_SAVE_DELAYED_MEMORY": True,
                },
            ):
                chunks.append(chunk)

            return chunks

        context = Context()
        context.emitter = TrackingEmitter()
        context.session_id = "session-1"
        context.timestamp = "2026-07-10T14:00:00"

        original_use_service_as_brain = config.USE_SERVICE_AS_BRAIN
        config.USE_SERVICE_AS_BRAIN = False

        try:
            chunks = asyncio.run(
                collect(context)
            )
        finally:
            config.USE_SERVICE_AS_BRAIN = original_use_service_as_brain

        runtime_events = [
            event
            for event in context.emitter.events
            if event.get("type") == "runtime_action"
        ]

        self.assertEqual(
            chunks,
            [
                {
                    "type": "raw_model_output",
                    "content": (
                        "<SAVE_DELAYED_MEMORY_CONTENT>\n"
                        "title: Test delayed memory report\n"
                        "summary: Current runtime state.\n"
                        "tags: runtime, test\n"
                        "body: Complete report body.\n"
                        "</SAVE_DELAYED_MEMORY_CONTENT>\n"
                    ),
                },
            ],
        )
        self.assertEqual(
            [
                event.get("status")
                for event in runtime_events
            ],
            [
                "started",
                "counted",
                "completed",
                "counter_final",
            ],
        )
        lifecycle_events = [
            event
            for event in runtime_events
            if not event.get("counter_only")
        ]
        self.assertEqual(
            lifecycle_events[0]["id"],
            lifecycle_events[1]["id"],
        )
        self.assertEqual(
            lifecycle_events[0]["text"],
            "SAVE_DELAYED_MEMORY_CONTENT",
        )
        self.assertTrue(
            lifecycle_events[0]["close_tag"],
        )
        self.assertEqual(
            lifecycle_events[1]["text"],
            "Saved delayed memory: Test delayed memory report",
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

        prompt = build_brain_context(
            runtime_actions=runtime_actions
        )
        runtime_context = build_brain_context(
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
            get_runtime_action_private_marker("SAVE_SESSION"),
            get_runtime_action_private_marker("SAVE_DELAYED_MEMORY_CONTENT"),
            get_runtime_action_private_marker("SAVE_ACTIVE_MEMORY"),
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

    def test_runtime_xml_exposes_current_jin_color_default(self):

        runtime_xml = build_runtime_xml(
            context=SimpleNamespace(
                runtime_action_events=[],
            ),
        )

        self.assertIn(
            f"<JIN_COLOR>{DEFAULT_JIN_COLOR}</JIN_COLOR>",
            runtime_xml,
        )

    def test_runtime_xml_exposes_last_valid_jin_color(self):

        runtime_xml = build_runtime_xml(
            context=SimpleNamespace(
                runtime_action_events=[
                    {
                        "name": "jin_color",
                        "color": "#00f2ff",
                    },
                    {
                        "action": "jin_color",
                        "payload": "bad-color",
                    },
                    {
                        "action": "jin_color",
                        "payload": "f0a",
                    },
                ],
            ),
        )

        self.assertIn(
            "<JIN_COLOR>#ff00aa</JIN_COLOR>",
            runtime_xml,
        )

    def test_prompt_routes_uncertain_operational_tasks_to_skills(self):

        prompt = build_brain_context(
            runtime_actions={
                "CAN_USE_ASSETS": True,
            }
        )

        assert_contains_text(
            self,
            prompt,
            runtime_rules.SKILL_ROUTING_RULES,
        )
        assert_contains_text(
            self,
            prompt,
            "<SKILLS>",
        )
        assert_contains_text(
            self,
            prompt,
            get_runtime_action_private_marker("LOAD_SKILL"),
        )
        assert_contains_text(
            self,
            prompt,
            get_runtime_action_private_marker("UNLOAD_SKILL"),
        )
        assert_not_contains_text(
            self,
            prompt,
            "<LIST_SKILLS>",
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

    def test_prompt_always_shows_load_unload_rules_with_skill_inventory(self):

        context = SimpleNamespace(
            runtime_memory="session_status: active",
            runtime_memory_stable="session_status: active",
            runtime_l2_memory="",
            active_memory_records=[],
            runtime_loaded_skills=[],
        )

        prompt = build_brain_context(
            context=context,
            runtime_actions={
                "CAN_USE_ASSETS": True,
            },
        )

        assert_contains_text(
            self,
            prompt,
            "<SKILLS>",
        )
        assert_contains_text(
            self,
            prompt,
            "LOAD / UNLOAD SKILLS:",
        )
        assert_contains_text(
            self,
            prompt,
            get_runtime_action_private_marker("LOAD_SKILL"),
        )
        assert_contains_text(
            self,
            prompt,
            get_runtime_action_private_marker("UNLOAD_SKILL"),
        )
        assert_not_contains_text(
            self,
            prompt,
            "<LIST_SKILLS>",
        )

    def test_prompt_shows_always_visible_skill_inventory(self):

        context = SimpleNamespace(
            runtime_memory="session_status: active",
            runtime_memory_stable="session_status: active",
            runtime_l2_memory="",
            active_memory_records=[],
            runtime_loaded_skills=[
                {
                    "name": "wildcards",
                },
            ],
        )

        prompt = build_brain_context(
            context=context,
            runtime_actions={
                "CAN_USE_ASSETS": True,
            },
        )

        assert_contains_text(
            self,
            prompt,
            "<SKILLS>",
        )
        assert_contains_text(
            self,
            prompt,
            "wildcards (loaded)",
        )
        assert_contains_text(
            self,
            prompt,
            "<LOADED_SKILLS_CONTENT>",
        )
        assert_not_contains_text(
            self,
            prompt,
            '<TOOL_RESULT name="LIST_SKILLS">',
        )

    def test_prompt_places_tool_results_at_context_top(self):

        context = SimpleNamespace(
            runtime_memory="session_status: active",
            runtime_memory_stable="session_status: active",
            runtime_l2_memory="",
            active_memory_records=[],
            runtime_asset_results=[
                {
                    "ok": True,
                    "action": "read_asset",
                    "path": "assets/test.txt",
                    "content": "asset result",
                },
            ],
            runtime_session_action_history=[
                "Read asset",
            ],
            runtime_loaded_skills=[
                {
                    "name": "wildcards",
                    "path": "assets/skills/wildcards.txt",
                    "line_count": 2,
                    "content": "first line\nsecond line",
                },
            ],
        )

        prompt = build_brain_context(
            context=context,
            runtime_actions={
                "CAN_USE_ASSETS": True,
            },
        )

        self.assertTrue(prompt.startswith("<TOOLS_RESULTS>"))
        self.assertLess(
            prompt.index('<TOOL_RESULT name="ASSETS">'),
            prompt.index("<SKILLS>"),
        )
        self.assertLess(
            prompt.index("<SKILLS>"),
            prompt.index("<LOADED_SKILLS_CONTENT>"),
        )
        self.assertLess(
            prompt.index("<LOADED_SKILLS_CONTENT>"),
            prompt.index("<RUNTIME_MEMORY>"),
        )
        self.assertLess(
            prompt.index("<RUNTIME_MEMORY>"),
            prompt.index("<SESSION_ACTIONS_HISTORY>"),
        )
        self.assertIn("asset result", prompt)
        self.assertIn("first line\n", prompt)
        self.assertIn("second line", prompt)
        self.assertIn("wildcards (loaded)", prompt)
        self.assertNotIn('<TOOL_RESULT name="LIST_SKILLS">', prompt)

    def test_prompt_keeps_loaded_delayed_memory_in_normal_turns(self):

        context = SimpleNamespace(
            runtime_memory="session_status: active",
            runtime_memory_stable="session_status: active",
            runtime_l2_memory="",
            active_memory_records=[],
            runtime_loaded_delayed_memory={
                "id": "a1b2c3",
                "title": "Pinned task plan",
                "summary": "Use this plan for the next task.",
            },
        )

        prompt = build_brain_context(
            context=context,
            runtime_actions={
                "CAN_SAVE_DELAYED_MEMORY": True,
            },
            user_input="start the task",
        )

        self.assertIn(
            "<LOADED_DELAYED_MEMORY>",
            prompt,
        )
        self.assertIn(
            '"title": "Pinned task plan"',
            prompt,
        )
        self.assertEqual(
            prompt.count(
                "<LOADED_DELAYED_MEMORY>"
            ),
            1,
        )
        self.assertLess(
            prompt.index(
                "<LOADED_DELAYED_MEMORY>"
            ),
            prompt.index(
                "I identify myself as JIN"
            ),
        )

    def test_prompt_formats_loaded_delayed_memory_title_with_age_suffix(self):
        now = datetime(
            2026,
            8,
            2,
            12,
            0,
            tzinfo=timezone.utc,
        ).timestamp()
        context = SimpleNamespace(
            runtime_memory="session_status: active",
            runtime_memory_stable="session_status: active",
            runtime_l2_memory="",
            active_memory_records=[],
            runtime_loaded_delayed_memory={
                "id": "a1b2c3",
                "title": "Pinned task plan",
                "summary": "Use this plan for the next task.",
                "created_time": "2026-08-02T11:58:00Z",
            },
        )

        with patch(
            "utils.context.messages.time.time",
            return_value=now,
        ):
            prompt = build_brain_context(
                context=context,
                runtime_actions={
                    "CAN_SAVE_DELAYED_MEMORY": True,
                },
                user_input="start the task",
            )

        self.assertIn(
            '"title": "Pinned task plan ( 2m ago )"',
            prompt,
        )
        loaded_block = prompt[
            prompt.index("<LOADED_DELAYED_MEMORY>"):
            prompt.index("</LOADED_DELAYED_MEMORY>")
        ]
        self.assertNotIn(
            '"created_time"',
            loaded_block,
        )

    def test_prompt_lists_available_delayed_memory_below_session_state(self):

        empty_context = SimpleNamespace(
            runtime_memory="session_status: active",
            runtime_memory_stable="session_status: active",
            runtime_l2_memory="",
            active_memory_records=[],
            delayed_memory_reports={},
        )

        prompt_without_reports = build_brain_context(
            context=empty_context,
            runtime_actions={
                "CAN_SAVE_DELAYED_MEMORY": True,
            },
        )

        self.assertNotIn(
            "DELAYED MEMORY ACTIONS:",
            prompt_without_reports,
        )
        self.assertNotIn(
            "<DELAYED_MEMORY>",
            prompt_without_reports,
        )

        context = SimpleNamespace(
            runtime_memory="session_status: active",
            runtime_memory_stable="session_status: active",
            runtime_l2_memory="",
            active_memory_records=[],
            delayed_memory_reports={
                "3gs007": {
                    "title": "JIN Multi-Layered Memory Architecture",
                },
                "1put0q": {
                    "title": (
                        "Синтез: Интеллект как контролируемый хаос "
                        "(Эволюция через ошибку)"
                    ),
                },
                "bad": {
                    "title": "Invalid id",
                },
            },
        )

        prompt = build_brain_context(
            context=context,
            runtime_actions={
                "CAN_SAVE_DELAYED_MEMORY": True,
            },
        )

        expected_inventory = (
            "<DELAYED_MEMORY>\n"
            "1put0q_Синтез_Интеллект_как_контролируемый_хаос_"
            "Эволюция_через_ошибку\n"
            "3gs007_JIN_Multi_Layered_Memory_Architecture\n"
            "</DELAYED_MEMORY>"
        )

        self.assertNotIn(
            "DELAYED MEMORY ACTIONS:",
            prompt,
        )
        self.assertIn(
            "<LOAD_DELAYED_MEMORY: id >",
            prompt,
        )
        self.assertIn(
            "<UNLOAD_DELAYED_MEMORY: id >",
            prompt,
        )
        self.assertNotIn(
            "<LIST_DELAYED_MEMORY>",
            prompt,
        )
        self.assertEqual(
            prompt.count(
                "\n<DELAYED_MEMORY>\n"
            ),
            1,
        )
        self.assertIn(
            "</CURRENT_SESSION_STATE>\n"
            + expected_inventory,
            prompt,
        )
        self.assertLess(
            prompt.index(
                expected_inventory
            ),
            prompt.index(
                "RUNTIME ACTION EXECUTION RULES:"
            ),
        )
        self.assertFalse(
            prompt.rstrip().endswith(
                expected_inventory
            ),
        )
        self.assertNotIn(
            "bad_Invalid_id",
            prompt,
        )

    def test_prompt_lists_delayed_memory_inventory_with_age_suffix(self):
        now = datetime(
            2026,
            8,
            2,
            12,
            0,
            tzinfo=timezone.utc,
        ).timestamp()
        context = SimpleNamespace(
            runtime_memory="session_status: active",
            runtime_memory_stable="session_status: active",
            runtime_l2_memory="",
            active_memory_records=[],
            delayed_memory_reports={
                "a1b2c3": {
                    "title": "Fresh report",
                    "created_time": "2026-08-02T11:58:00Z",
                },
            },
        )

        with patch(
            "utils.context.messages.time.time",
            return_value=now,
        ):
            prompt = build_brain_context(
                context=context,
                runtime_actions={
                    "CAN_SAVE_DELAYED_MEMORY": True,
                },
            )

        self.assertIn(
            "a1b2c3_Fresh_report ( 2m ago )",
            prompt,
        )

    def test_prompt_formats_missing_skill_as_skill_error_tool_result(self):

        context = SimpleNamespace(
            runtime_memory="session_status: active",
            runtime_memory_stable="session_status: active",
            runtime_l2_memory="",
            active_memory_records=[],
            runtime_asset_results=[
                {
                    "ok": False,
                    "action": "load_skill",
                    "requested": "file_writer",
                    "error": "skill_not_found",
                },
            ],
            runtime_loaded_skills=[],
        )

        prompt = build_brain_context(
            context=context,
            runtime_actions={
                "CAN_USE_ASSETS": True,
            },
        )

        self.assertIn(
            '<TOOL_RESULT name="SKILL_ERROR">',
            prompt,
        )
        self.assertIn(
            "You attempted to load a skill that does not exist: file_writer",
            prompt,
        )
        self.assertNotIn(
            '"action": "load_skill"',
            prompt,
        )
        self.assertNotIn(
            "skill_not_found",
            prompt,
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

        prompt = build_brain_context(
            context=context,
            runtime_actions={
                "CAN_SAVE_ACTIVE_MEMORY": True,
            },
        )
        runtime_context = build_brain_context(
            context=context,
            runtime_actions={
                "CAN_SAVE_ACTIVE_MEMORY": True,
            },
        )

        assert_contains_text(
            self,
            prompt,
            "SAVE_ACTIVE_MEMORY:",
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
        self.assertTrue(
            prompt.startswith(
                "<TOOLS_RESULTS>"
            )
        )
        self.assertLess(
            prompt.index("</TOOLS_RESULTS>"),
            prompt.index(
                "<ACTIVE_MEMORY priority=\"active_runtime_contracts\">"
            ),
        )
        self.assertLess(
            prompt.index("<ACTIVE_MEMORY"),
            prompt.index("<RUNTIME_MEMORY>"),
        )
        self.assertLess(
            prompt.index("<RUNTIME_MEMORY>"),
            prompt.index("<CURRENT_TRUSTED_RUNTIME_VARIABLES>"),
        )
        self.assertLess(
            runtime_context.index("<ACTIVE_MEMORY"),
            runtime_context.index("<RUNTIME_MEMORY>"),
        )

        runtime_memory_block = runtime_context.split(
            "<RUNTIME_MEMORY>",
            1,
        )[1].split(
            "</RUNTIME_MEMORY>",
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

    def test_active_memory_recalculates_on_each_followup_tick(self):

        context = SimpleNamespace(
            runtime_memory="session_status: active",
            runtime_memory_stable="session_status: active",
            runtime_l2_memory="",
            active_memory_records=[
                (
                    "active_memory_1: Track experiment "
                    "[ creation_time: 2026-06-20T10:00:00 ] "
                    "[ created_jin_message_number: 3 ] "
                    "[ elapsed_time: 00:00:00 ] "
                    "[ elapsed_jin_message_number: 0 ] "
                    "[ status: pending ]"
                ),
            ],
            timestamp="2026-06-20T10:00:00",
            turn_number=4,
            user_message_count=2,
            runtime_user_idle_seconds=300,
            runtime_active_memory_refresh_tick=0,
        )

        build_brain_context(
            context=context,
            runtime_actions={},
            commit_active_memory_refresh=True,
        )

        self.assertIn(
            "[ elapsed_time: 00:05:00 ]",
            context.active_memory_records[0],
        )
        self.assertEqual(
            context.runtime_active_memory_records_refresh_turn,
            (4, 2, 0),
        )

        context.timestamp = "2026-06-20T10:01:00"
        context.runtime_active_memory_refresh_tick = 1

        build_brain_context(
            context=context,
            runtime_actions={},
            commit_active_memory_refresh=True,
        )

        self.assertIn(
            "[ elapsed_time: 00:05:00 ]",
            context.active_memory_records[0],
        )
        self.assertEqual(
            context.runtime_active_memory_records_refresh_turn,
            (4, 2, 1),
        )

        context.timestamp = "2026-06-20T10:06:00"
        context.runtime_active_memory_refresh_tick = 2

        build_brain_context(
            context=context,
            runtime_actions={},
            commit_active_memory_refresh=True,
        )

        self.assertIn(
            "[ elapsed_time: 00:06:00 ]",
            context.active_memory_records[0],
        )
        self.assertEqual(
            context.runtime_active_memory_records_refresh_turn,
            (4, 2, 2),
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

        runtime_context = build_brain_context(
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

        prompt = build_brain_context(
            context=context,
            runtime_actions={
                "CAN_SAVE_ACTIVE_MEMORY": True,
            },
        )

        assert_contains_text(
            self,
            prompt,
            "SAVE_ACTIVE_MEMORY:",
        )
        assert_not_contains_text(
            self,
            prompt,
            "RESOLVE_ACTIVE_MEMORY:",
        )

    def test_prompt_uses_passed_agent_runtime_actions(self):

        prompt = build_brain_context(
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
                "<RUNTIME_MODE>SERVICE as BRAIN</RUNTIME_MODE>"
                if settings.USE_SERVICE_AS_BRAIN
                else "<RUNTIME_MODE>BRAIN</RUNTIME_MODE>"
            ),
            prompt,
        )

        self.assertIn(
            f"<SERVICE_MODEL_UID>{config.SERVICE_MODEL_UID}</SERVICE_MODEL_UID>",
            prompt,
        )

        if settings.USE_SERVICE_AS_BRAIN:
            self.assertNotIn(
                "<BRAIN_MODEL_UID>",
                prompt,
            )
        else:
            self.assertIn(
                f"<BRAIN_MODEL_UID>{config.BRAIN_MODEL_UID}</BRAIN_MODEL_UID>",
                prompt,
            )

        self.assertNotIn(
            "<MODE>",
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

        prompt = build_brain_context(
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

        prompt = build_brain_context(
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

        prompt = build_brain_context(
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
            "SAVE_SESSION:",
        )
        self.assertNotIn(
            "<RUNTIME_ACTION",
            prompt,
        )
        self.assertIn(
            get_runtime_action_private_marker("SAVE_SESSION"),
            prompt,
        )
        self.assertIn(
            get_runtime_action_private_marker("SAVE_ACTIVE_MEMORY"),
            prompt,
        )
        assert_contains_text(
            self,
            prompt,
            "SAVE_ACTIVE_MEMORY:",
        )
        self.assertIn(
            "SAVE_ACTIVE_MEMORY",
            prompt,
        )

    def test_prompt_does_not_render_legacy_memory_recall_block(self):

        context = SimpleNamespace(
            runtime_turn_user_message="помнишь кодовое слово?",
        )

        prompt = build_brain_context(
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


    def test_idle_history_keeps_payloads_and_separate_turn_entries(self):

        context = SimpleNamespace(
            runtime_session_action_history=[],
            runtime_current_turn_id="turn-1",
        )

        replace_session_action_history_since(
            context,
            0,
            [
                RuntimeActionCall(
                    name="IDLE",
                    payload="5s",
                ),
                RuntimeActionCall(
                    name="IDLE",
                    payload="12s",
                ),
            ],
        )

        self.assertEqual(
            len(context.runtime_session_action_history),
            1,
        )
        self.assertEqual(
            context.runtime_session_action_history[0]["parts"],
            [
                {
                    "text": "IDLE",
                    "detail": "5s, 12s",
                    "count": 2,
                },
            ],
        )

        context.runtime_current_turn_id = "turn-2"
        replace_session_action_history_since(
            context,
            len(context.runtime_session_action_history),
            [
                RuntimeActionCall(
                    name="IDLE",
                    payload="7s",
                ),
            ],
        )

        self.assertEqual(
            len(context.runtime_session_action_history),
            2,
        )
        self.assertEqual(
            context.runtime_session_action_history[1]["parts"],
            [
                {
                    "text": "IDLE",
                    "detail": "7s",
                },
            ],
        )
        self.assertEqual(
            [
                item.get("runtime_turn_id")
                for item in context.runtime_session_action_history
            ],
            [
                "turn-1",
                "turn-2",
            ],
        )


if __name__ == "__main__":
    unittest.main()


