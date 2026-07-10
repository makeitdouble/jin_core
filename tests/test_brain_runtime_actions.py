import asyncio
import contextlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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
from rules import runtime as runtime_rules
from utils.session_actions_history import (
    replace_session_action_history_since,
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
                "APPEND_SKILL",
                "REMOVE_SKILL",
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
                "LIST_DELAYED_MEMORY",
                "APPEND_DELAYED_MEMORY",
                "REMOVE_DELAYED_MEMORY",
            )
        )

    if bool(runtime_actions.get("CAN_SAVE_ACTIVE_MEMORY", False)):
        expected_actions.extend(
            (
                "CREATE_ACTIVE_MEMORY",
                "RESOLVE_ACTIVE_MEMORY",
            )
        )

    return tuple(expected_actions)


class BrainRuntimeActionTests(unittest.TestCase):

    def patch_asset_roots(self, root: Path):
        assets_root = root / "assets"
        return (
            patch("utils.assets_service.PROJECT_ROOT", root),
            patch("utils.assets_service.ASSETS_ROOT", assets_root),
            patch("utils.assets_service.SKILLS_ROOT", assets_root / "skills"),
            patch("utils.assets_service.WILDCARDS_ROOT", assets_root / "wildcards"),
            patch("utils.assets_service.PROMPTS_ROOT", assets_root / "prompts"),
            patch("utils.assets_service.TEMPLATES_ROOT", assets_root / "templates"),
            patch("utils.assets_service.OUTPUTS_ROOT", assets_root / "outputs"),
        )

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
            "Runtime Action Markers are internal mechanics.\nEmit markers",
        )
        assert_contains_text(
            self,
            prompt,
            "short and brief.\nNEVER override",
        )
        assert_contains_text(
            self,
            prompt,
            "marker name!\nCheck all active_memory",
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

    def test_stream_groups_two_action_markers_into_one_history_item(self):

        class FakeBrainClient:
            async def stream(self, **_kwargs):
                yield {
                    "type": "content",
                    "content": (
                        "<SAVE_SESSION>\n"
                        "<LIST_SKILLS>"
                    ),
                }

        class Context:
            pass

        async def collect(context):
            chunks = []

            async for chunk in ask_brain_stream(
                client=FakeBrainClient(),
                text="save session and list skills",
                context=context,
                runtime_actions={
                    "CAN_SAVE_SESSION": True,
                    "CAN_USE_ASSETS": True,
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
            [
                item["text"]
                for item in context.runtime_session_action_history
            ],
            [
                "SAVE_SESSION, LIST_SKILLS",
            ],
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_SAVE_SESSION": True,
                "CAN_USE_ASSETS": True,
            },
        )

        self.assertIn(
            "<SESSION_ACTIONS_HISTORY>",
            prompt,
        )
        self.assertIn(
            "1. SAVE_SESSION, LIST_SKILLS",
            prompt,
        )

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
                "SAVE_SESSION ( repeated_times: 2 )",
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
            "RESOLVE_ACTIVE_MEMORY ( repeated_times: 24 )",
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={},
        )

        self.assertIn(
            "1. RESOLVE_ACTIVE_MEMORY ( repeated_times: 24 )",
            prompt,
        )

    def test_stream_preserves_duplicate_failed_append_skill_marker(self):

        class FakeBrainClient:
            async def stream(self, **_kwargs):
                yield {
                    "type": "content",
                    "content": (
                        "<INTERNAL_ACTION_APPEND_SKILL: name of skill >\n"
                        "<INTERNAL_ACTION_APPEND_SKILL: name of skill >"
                    ),
                }

        class Context:
            pass

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
            "<INTERNAL_ACTION_APPEND_SKILL: name of skill >",
            visible_text,
        )
        self.assertEqual(
            context.runtime_action_events,
            [
                {
                    "name": "append_skill",
                    "payload": "name of skill",
                },
            ],
        )
        self.assertEqual(
            context.runtime_asset_results[-1]["action"],
            "append_skill",
        )
        self.assertEqual(
            context.runtime_asset_results[-1]["error"],
            "skill_not_found",
        )

    def test_stream_stops_repeated_resolve_active_memory_markers(self):

        class FakeBrainClient:
            async def stream(self, **_kwargs):
                for _ in range(4):
                    yield {
                        "type": "content",
                        "content": (
                            "<INTERNAL_ACTION_RESOLVE_ACTIVE_MEMORY: "
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
            [],
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

    def test_stream_asset_action_is_runtime_boundary(self):

        class FakeBrainClient:
            async def stream(self, **_kwargs):
                yield {
                    "type": "content",
                    "content": (
                        "\n<INTERNAL_ACTION_ASSET_ACTION>\n"
                        "{\n"
                        '  "action": "create_wildcard_file",\n'
                        '  "args": {\n'
                        '    "path": "clothing/shoes",\n'
                        '    "content": "sneakers\\nboots\\nheels"\n'
                        "  }\n"
                        "}\n"
                        "</INTERNAL_ACTION_ASSET_ACTION>\n"
                        "This should not be visible."
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
                    for patcher in self.patch_asset_roots(root):
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
                        "",
                    )
                    self.assertNotIn(
                        "INTERNAL_ACTION_ASSET_ACTION",
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
                    "content": "<INTERNAL_ACTION_ASSET_ACTION>\n",
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
                        "</INTERNAL_ACTION_ASSET_ACTION>\n"
                        "This should not be visible."
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
                    for patcher in self.patch_asset_roots(root):
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
                        "",
                    )
                    self.assertEqual(
                        [
                            event.get("status")
                            for event in runtime_events
                        ],
                        [
                            "started",
                            "started",
                            "completed",
                        ],
                    )
                    self.assertEqual(
                        len({
                            event.get("id")
                            for event in runtime_events
                        }),
                        1,
                    )
                    self.assertEqual(
                        runtime_events[0]["text"],
                        "Processed asset action",
                    )
                    self.assertFalse(
                        runtime_events[0]["file_exists_at_emit"],
                    )
                    self.assertEqual(
                        runtime_events[1]["text"],
                        "Created asset file - assets/outputs/rain_simulator.py",
                    )
                    self.assertFalse(
                        runtime_events[1]["file_exists_at_emit"],
                    )
                    self.assertTrue(
                        runtime_events[2]["file_exists_at_emit"],
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

        self.assertEqual(chunks, [])
        self.assertEqual(
            [
                event.get("status")
                for event in runtime_events
            ],
            [
                "started",
                "completed",
            ],
        )
        self.assertEqual(
            runtime_events[0]["id"],
            runtime_events[1]["id"],
        )
        self.assertEqual(
            runtime_events[0]["text"],
            "Saving delayed memory report",
        )
        self.assertEqual(
            runtime_events[1]["text"],
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
            runtime_rules.INTERNAL_ACTION_SAVE_SESSION_MARKER,
            runtime_rules.INTERNAL_ACTION_SAVE_DELAYED_MEMORY_CONTENT_MARKER,
            runtime_rules.INTERNAL_ACTION_CREATE_ACTIVE_MEMORY_MARKER,
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
            "<MANDATORY SKILL ROUTING RULES>",
        )
        assert_contains_text(
            self,
            prompt,
            "If unsure about skill capabilities",
        )
        assert_contains_text(
            self,
            prompt,
            runtime_rules.INTERNAL_ACTION_LIST_SKILLS_MARKER,
        )
        assert_not_contains_text(
            self,
            prompt,
            runtime_rules.INTERNAL_ACTION_APPEND_SKILL_MARKER,
        )
        assert_not_contains_text(
            self,
            prompt,
            runtime_rules.INTERNAL_ACTION_REMOVE_SKILL_MARKER,
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

    def test_prompt_shows_append_remove_rules_only_after_list_skills_result(self):

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
                            "path": "assets/skills/wildcards.txt",
                        },
                    ],
                },
            ],
            runtime_appended_skills=[],
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_USE_ASSETS": True,
            },
        )

        assert_not_contains_text(
            self,
            prompt,
            "LIST SKILLS:",
        )
        assert_contains_text(
            self,
            prompt,
            "APPEND / REMOVE SKILLS:",
        )
        assert_contains_text(
            self,
            prompt,
            runtime_rules.INTERNAL_ACTION_APPEND_SKILL_MARKER,
        )
        assert_contains_text(
            self,
            prompt,
            runtime_rules.INTERNAL_ACTION_REMOVE_SKILL_MARKER,
        )

    def test_prompt_places_tool_results_after_session_history(self):

        context = SimpleNamespace(
            runtime_memory="session_status: active",
            runtime_memory_stable="session_status: active",
            runtime_l2_memory="",
            active_memory_records=[],
            runtime_session_action_history=[
                "Listed skills",
            ],
            runtime_asset_results=[
                {
                    "ok": True,
                    "action": "list_skills",
                    "skills": [
                        {
                            "name": "wildcards",
                            "path": "assets/skills/wildcards.txt",
                            "content": "first line\nsecond line",
                        },
                    ],
                },
                {
                    "ok": True,
                    "action": "list_skills",
                    "skills": [
                        {
                            "name": "wildcards",
                            "path": "assets/skills/wildcards.txt",
                            "content": "first line\nsecond line",
                        },
                    ],
                },
            ],
            runtime_appended_skills=[
                {
                    "name": "wildcards",
                    "path": "assets/skills/wildcards.txt",
                    "line_count": 2,
                    "content": "first line\nsecond line",
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
            prompt.index("<SESSION_ACTIONS_HISTORY>"),
            prompt.index("<TOOL_RESULTS"),
        )
        self.assertLess(
            prompt.index("<TOOL_RESULTS"),
            prompt.index("<APPENDED_SKILLS_CONTENT>"),
        )
        self.assertLess(
            prompt.index("<APPENDED_SKILLS_CONTENT>"),
            prompt.index("Runtime Action Markers are internal mechanics"),
        )
        self.assertLess(
            prompt.index("Runtime Action Markers are internal mechanics"),
            prompt.index("I identify as JIN"),
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
        self.assertIn(
            '<TOOL_RESULT name="SKILLS">',
            prompt,
        )
        self.assertEqual(
            prompt.count(
                '<TOOL_RESULT name="SKILLS">'
            ),
            1,
        )
        self.assertNotIn(
            '<TOOL_RESULT name="ASSETS">',
            prompt,
        )
        self.assertNotIn(
            "All available skills:",
            prompt,
        )
        self.assertIn(
            "1. wildcards (appended) - assets/skills/wildcards.txt",
            prompt,
        )
        self.assertNotIn(
            '"action": "list_skills"',
            prompt,
        )
        self.assertNotIn(
            '"skills":',
            prompt,
        )
        self.assertIn(
            "<APPENDED_SKILLS_CONTENT>",
            prompt,
        )
        self.assertNotIn(
            "<TOOL_RESULTS",
            runtime_context,
        )

    def test_prompt_keeps_appended_delayed_memory_in_normal_turns(self):

        context = SimpleNamespace(
            runtime_memory="session_status: active",
            runtime_memory_stable="session_status: active",
            runtime_l2_memory="",
            active_memory_records=[],
            runtime_appended_delayed_memory={
                "id": "a1b2c3",
                "title": "Pinned task plan",
                "summary": "Use this plan for the next task.",
            },
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_SAVE_DELAYED_MEMORY": True,
            },
            user_input="start the task",
        )

        self.assertIn(
            "<APPENDED_DELAYED_MEMORY>",
            prompt,
        )
        self.assertIn(
            '"title": "Pinned task plan"',
            prompt,
        )
        self.assertEqual(
            prompt.count(
                "<APPENDED_DELAYED_MEMORY>"
            ),
            1,
        )
        self.assertLess(
            prompt.index(
                "<APPENDED_DELAYED_MEMORY>"
            ),
            prompt.index(
                "I identify as JIN"
            ),
        )

    def test_prompt_adds_delayed_memory_rules_only_when_reports_exist(self):

        empty_context = SimpleNamespace(
            runtime_memory="session_status: active",
            runtime_memory_stable="session_status: active",
            runtime_l2_memory="",
            active_memory_records=[],
            delayed_memory_reports={},
        )

        prompt_without_reports = build_brain_system_prompt(
            context=empty_context,
            runtime_actions={
                "CAN_SAVE_DELAYED_MEMORY": True,
            },
        )

        self.assertNotIn(
            "DELAYED MEMORY ACTIONS:",
            prompt_without_reports,
        )

        context = SimpleNamespace(
            runtime_memory="session_status: active",
            runtime_memory_stable="session_status: active",
            runtime_l2_memory="",
            active_memory_records=[],
            delayed_memory_reports={
                "a1b2c3": {
                    "title": "Saved report",
                },
            },
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_SAVE_DELAYED_MEMORY": True,
            },
        )

        self.assertIn(
            "DELAYED MEMORY ACTIONS:",
            prompt,
        )
        self.assertIn(
            "<LIST_DELAYED_MEMORY>",
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
                    "action": "append_skill",
                    "requested": "file_writer",
                    "error": "skill_not_found",
                },
            ],
            runtime_appended_skills=[],
        )

        prompt = build_brain_system_prompt(
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
            "You attempted to append a skill that does not exist: file_writer",
            prompt,
        )
        self.assertNotIn(
            '"action": "append_skill"',
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
        self.assertTrue(
            prompt.startswith(
                "<ACTIVE_MEMORY priority=\"active_runtime_contracts\">"
            )
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
            runtime_rules.INTERNAL_ACTION_SAVE_SESSION_MARKER,
            prompt,
        )
        self.assertIn(
            runtime_rules.INTERNAL_ACTION_CREATE_ACTIVE_MEMORY_MARKER,
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
