import asyncio
import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from clients.brain_client import apply_runtime_action_calls
from clients.brain_client import should_execute_save_session
from contracts.rules_assembler import (
    RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
    RUNTIME_ACTION_IDLE,
    RUNTIME_ACTION_JIN_COLOR,
    get_runtime_action_private_marker,
)
from rules.brain_context_builder import build_appended_delayed_memory_context
from tests.helpers.runtime_actions import (
    FakeContext,
    FakeEmitter,
    RuntimeActionTestCase,
    legacy_internal_action_marker,
)
from utils.actions import (
    RuntimeActionCall,
    RuntimeActionRepetitionGuard,
    RuntimeActionStreamFilter,
    extract_active_memory_resolve_slot_id,
    extract_search_query,
    extract_runtime_actions,
    get_create_active_memory_marker_fields,
    get_create_active_memory_placeholder_payload,
    normalize_jin_color_payload,
    parse_delayed_memory_content_payload,
)
from utils.assets_utils import run_asset_action
from utils.brain_client_utils import (
    append_delayed_memory_runtime_result,
    flush_pending_active_memory_resolve_failure_history,
)
from utils.context.context_exports import build_tool_results_context
from utils.file_manager_asset_utils import read_asset_text_preview
from utils.runtime_todo import create_runtime_todo
from utils.skills_asset_utils import (
    list_skills,
    normalize_skill_name,
)
from utils.tool_results import (
    TOOL_RESULT_KIND_ACTIVE_MEMORY,
    TOOL_RESULT_KIND_ASSET,
    TOOL_RESULT_KIND_DELAYED_MEMORY,
    TOOL_RESULT_KIND_SEARCH,
    begin_runtime_tool_results_turn,
    record_runtime_tool_result,
)



class RuntimeJinColorActionTests(RuntimeActionTestCase):

    def test_jin_color_marker_validates_and_normalizes_hex(self):

        for marker, expected_color in (
            ("<JIN_COLOR: #00f2ff>", "#00f2ff"),
            ("<JIN_COLOR: 00F2FF>", "#00f2ff"),
            ("<JIN_COLOR: 0ff>", "#00ffff"),
            ("<INTERNAL_ACTION_JIN_COLOR: #f0A />", "#ff00aa"),
        ):
            with self.subTest(marker=marker):
                result = extract_runtime_actions(
                    f"before {marker} after",
                    enabled_actions=(
                        RUNTIME_ACTION_JIN_COLOR,
                    ),
                )

                self.assertEqual(
                    result.text,
                    "before after",
                )
                self.assertEqual(
                    len(result.actions),
                    1,
                )
                self.assertEqual(
                    result.actions[0].name,
                    RUNTIME_ACTION_JIN_COLOR,
                )
                self.assertEqual(
                    result.actions[0].payload,
                    expected_color,
                )


    def test_jin_color_invalid_payload_does_not_emit_action(self):

        for marker in (
            "<JIN_COLOR:>",
            "<JIN_COLOR: #>",
            "<JIN_COLOR: #00f2ff00>",
            "<JIN_COLOR: blue>",
            "<JIN_COLOR: #00f2fg>",
        ):
            with self.subTest(marker=marker):
                result = extract_runtime_actions(
                    marker,
                    enabled_actions=(
                        RUNTIME_ACTION_JIN_COLOR,
                    ),
                )

                self.assertEqual(
                    result.text,
                    "",
                )
                self.assertEqual(
                    result.actions,
                    (),
                )


    def test_jin_color_multiple_markers_keep_order(self):

        result = extract_runtime_actions(
            "<JIN_COLOR: #00f2ff><JIN_COLOR: f0a><JIN_COLOR: 101820><JIN_COLOR: #00f2ff>",
            enabled_actions=(
                RUNTIME_ACTION_JIN_COLOR,
            ),
            repetition_guard=RuntimeActionRepetitionGuard(),
        )

        self.assertEqual(
            result.text,
            "",
        )
        self.assertEqual(
            [
                action.payload
                for action in result.actions
            ],
            [
                "#00f2ff",
                "#ff00aa",
                "#101820",
                "#00f2ff",
            ],
        )
        self.assertFalse(
            result.marker_repetition_exceeded
        )


    def test_jin_color_alternating_markers_do_not_hit_identical_repeat_limit(self):

        result = extract_runtime_actions(
            (
                "<JIN_COLOR: #0000ff>"
                "<JIN_COLOR: #ffffff>"
                "<JIN_COLOR: #0000ff>"
                "<JIN_COLOR: #ffffff>"
                "<JIN_COLOR: #0000ff>"
            ),
            enabled_actions=(
                RUNTIME_ACTION_JIN_COLOR,
            ),
            repetition_guard=RuntimeActionRepetitionGuard(),
        )

        self.assertFalse(
            result.marker_repetition_exceeded
        )
        self.assertEqual(
            len(result.actions),
            5,
        )
        self.assertNotIn(
            "<JIN_COLOR",
            result.text,
        )


    def test_normalize_jin_color_payload_rejects_bad_colors(self):

        self.assertEqual(
            normalize_jin_color_payload("#abc"),
            "#aabbcc",
        )
        self.assertEqual(
            normalize_jin_color_payload("abcd"),
            "",
        )


    def test_apply_runtime_action_calls_emits_jin_color_in_order(self):

        Emitter = FakeEmitter

        async def run_case():
            emitter = Emitter()
            context = SimpleNamespace(
                runtime_action_events=[],
                runtime_search_calls=[],
                runtime_appended_skills=[],
                runtime_visible_skills_result={},
                runtime_save_session_requested=False,
                runtime_save_session_action_emitted=False,
                runtime_skill_state_barrier_active=False,
                logger=None,
                emitter=emitter,
            )
            actions = (
                RuntimeActionCall(
                    name=RUNTIME_ACTION_JIN_COLOR,
                    payload="#00f2ff",
                ),
                RuntimeActionCall(
                    name=RUNTIME_ACTION_JIN_COLOR,
                    payload="bad-color",
                ),
                RuntimeActionCall(
                    name=RUNTIME_ACTION_JIN_COLOR,
                    payload="f0a",
                ),
            )

            applied_count = await apply_runtime_action_calls(
                context,
                actions,
                user_message="поставь цвет бирюзовый, затем розовый",
            )

            self.assertEqual(
                applied_count,
                2,
            )
            self.assertEqual(
                [
                    event.get("payload")
                    for event in context.runtime_action_events
                ],
                [
                    "#00f2ff",
                    "#ff00aa",
                ],
            )
            self.assertEqual(
                [
                    event.get("color")
                    for event in emitter.events
                ],
                [
                    "#00f2ff",
                    "#ff00aa",
                ],
            )

        asyncio.run(run_case())


    def test_apply_runtime_action_calls_dedups_jin_colors_per_turn(self):

        Emitter = FakeEmitter

        async def run_case():
            emitter = Emitter()
            context = SimpleNamespace(
                runtime_action_events=[
                    {
                        "name": "jin_color",
                        "color": "#00f2ff",
                        "payload": "#00f2ff",
                    },
                ],
                runtime_search_calls=[],
                runtime_appended_skills=[],
                runtime_visible_skills_result={},
                runtime_save_session_requested=False,
                runtime_save_session_action_emitted=False,
                runtime_skill_state_barrier_active=False,
                runtime_current_turn_id="turn-color-reset",
                logger=None,
                emitter=emitter,
            )
            actions = (
                RuntimeActionCall(
                    name=RUNTIME_ACTION_JIN_COLOR,
                    payload="#00f2ff",
                ),
                RuntimeActionCall(
                    name=RUNTIME_ACTION_JIN_COLOR,
                    payload="#ff00aa",
                ),
                RuntimeActionCall(
                    name=RUNTIME_ACTION_JIN_COLOR,
                    payload="#ff00aa",
                ),
            )

            applied_count = await apply_runtime_action_calls(
                context,
                actions,
                user_message="поставь сначала бирюзовый, затем розовый",
            )

            self.assertEqual(
                applied_count,
                2,
            )
            self.assertEqual(
                [
                    event.get("payload")
                    for event in context.runtime_action_events
                ],
                [
                    "#00f2ff",
                    "#00f2ff",
                    "#ff00aa",
                ],
            )
            self.assertEqual(
                [
                    event.get("color")
                    for event in emitter.events
                ],
                [
                    "#00f2ff",
                    "#ff00aa",
                ],
            )

        asyncio.run(run_case())


    def test_apply_runtime_action_calls_executes_jin_color_without_trigger(self):

        Emitter = FakeEmitter

        async def run_case():
            emitter = Emitter()
            context = SimpleNamespace(
                runtime_action_events=[],
                runtime_search_calls=[],
                runtime_appended_skills=[],
                runtime_visible_skills_result={},
                runtime_save_session_requested=False,
                runtime_save_session_action_emitted=False,
                runtime_skill_state_barrier_active=False,
                runtime_action_failure_followup_messages=[],
                logger=None,
                emitter=emitter,
            )
            action = RuntimeActionCall(
                name=RUNTIME_ACTION_JIN_COLOR,
                payload="#ff0000",
            )

            applied_count = await apply_runtime_action_calls(
                context,
                (action,),
                user_message="поставь себе красный яркий",
            )

            self.assertEqual(
                applied_count,
                1,
            )
            self.assertEqual(
                context.runtime_action_events[-1]["color"],
                "#ff0000",
            )
            self.assertEqual(
                [event.get("status") for event in emitter.events],
                ["completed"],
            )

        asyncio.run(
            run_case()
        )

