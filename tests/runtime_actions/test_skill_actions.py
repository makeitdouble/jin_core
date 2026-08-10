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
from rules.brain_context_builder import build_loaded_delayed_memory_context
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
    get_save_active_memory_marker_fields,
    get_save_active_memory_placeholder_payload,
    normalize_jin_color_payload,
    parse_delayed_memory_content_payload,
)
from utils.assets_utils import run_asset_action
from utils.brain_client_utils import (
    record_delayed_memory_runtime_result,
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



class RuntimeSkillActionTests(RuntimeActionTestCase):

    def test_extracts_list_skills_marker(self):

        result = extract_runtime_actions(
            "<LIST_SKILLS>",
            enabled_actions=[
                "CAN_USE_ASSETS",
            ],
        )

        self.assertEqual(
            result.text,
            "",
        )
        self.assertEqual(
            result.actions,
            (
                RuntimeActionCall(
                    name="LIST_SKILLS",
                    payload="",
                ),
            ),
        )

    def test_extracts_current_list_skills_marker(self):

        result = extract_runtime_actions(
            get_runtime_action_private_marker("LIST_SKILLS"),
            enabled_actions=[
                "CAN_USE_ASSETS",
            ],
        )

        self.assertEqual(
            result.text,
            "",
        )
        self.assertEqual(
            result.actions,
            (
                RuntimeActionCall(
                    name="LIST_SKILLS",
                    payload="",
                ),
            ),
        )


    def test_stream_filter_handles_split_self_closing_list_skills_marker(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_USE_ASSETS",
            ],
        )

        first = stream_filter.filter(
            "<LIST_SKILLS"
        )
        second = stream_filter.filter(
            "/>"
        )

        self.assertEqual(
            first.text,
            "",
        )
        self.assertEqual(
            first.actions,
            (),
        )
        self.assertEqual(
            second.text,
            "",
        )
        self.assertEqual(
            second.actions,
            (
                RuntimeActionCall(
                    name="LIST_SKILLS",
                    payload="",
                ),
            ),
        )
        self.assertEqual(
            stream_filter.flush(),
            "",
        )


    def test_extracts_append_and_remove_skill_markers(self):

        result = extract_runtime_actions(
            (
                "<APPEND_SKILL: image_prompt_generator>\n"
                "<REMOVE_SKILL: wildcards>"
            ),
            enabled_actions=[
                "CAN_USE_ASSETS",
            ],
        )

        self.assertEqual(
            result.text,
            "",
        )
        self.assertEqual(
            result.actions,
            (
                RuntimeActionCall(
                    name="APPEND_SKILL",
                    payload="image_prompt_generator",
                ),
                RuntimeActionCall(
                    name="REMOVE_SKILL",
                    payload="wildcards",
                ),
            ),
        )


    def test_extracts_plural_append_and_remove_skill_markers(self):

        result = extract_runtime_actions(
            (
                "<APPEND_SKILLS: "
                "file_manager, image_prompt_generator, porn, wildcards>\n"
                "<REMOVE_SKILLS: old_skill, unused_skill>"
            ),
            enabled_actions=[
                "CAN_USE_ASSETS",
            ],
        )

        self.assertEqual(
            result.text,
            "",
        )
        append_payload = (
            "file_manager, image_prompt_generator, porn, wildcards"
        )
        remove_payload = "old_skill, unused_skill"
        self.assertEqual(
            result.actions,
            (
                RuntimeActionCall(
                    name="APPEND_SKILL",
                    payload="file_manager",
                    marker_name="APPEND_SKILLS",
                    marker_payload=append_payload,
                    marker_group="append_skills_001",
                ),
                RuntimeActionCall(
                    name="APPEND_SKILL",
                    payload="image_prompt_generator",
                    marker_name="APPEND_SKILLS",
                    marker_payload=append_payload,
                    marker_group="append_skills_001",
                ),
                RuntimeActionCall(
                    name="APPEND_SKILL",
                    payload="porn",
                    marker_name="APPEND_SKILLS",
                    marker_payload=append_payload,
                    marker_group="append_skills_001",
                ),
                RuntimeActionCall(
                    name="APPEND_SKILL",
                    payload="wildcards",
                    marker_name="APPEND_SKILLS",
                    marker_payload=append_payload,
                    marker_group="append_skills_001",
                ),
                RuntimeActionCall(
                    name="REMOVE_SKILL",
                    payload="old_skill",
                    marker_name="REMOVE_SKILLS",
                    marker_payload=remove_payload,
                    marker_group="remove_skills_002",
                ),
                RuntimeActionCall(
                    name="REMOVE_SKILL",
                    payload="unused_skill",
                    marker_name="REMOVE_SKILLS",
                    marker_payload=remove_payload,
                    marker_group="remove_skills_002",
                ),
            ),
        )
        self.assertEqual(
            result.observed_actions,
            (
                RuntimeActionCall(
                    name="APPEND_SKILLS",
                    payload=append_payload,
                    marker_name="APPEND_SKILLS",
                    marker_payload=append_payload,
                    marker_group="append_skills_001",
                ),
                RuntimeActionCall(
                    name="REMOVE_SKILLS",
                    payload=remove_payload,
                    marker_name="REMOVE_SKILLS",
                    marker_payload=remove_payload,
                    marker_group="remove_skills_002",
                ),
            ),
        )
    def test_append_skill_name_attribute_stays_visible_text(self):

        result = extract_runtime_actions(
            '<APPEND_SKILL name="file_manager" />',
            enabled_actions=[
                "CAN_USE_ASSETS",
            ],
        )

        self.assertEqual(
            result.text,
            '<APPEND_SKILL name="file_manager" />',
        )
        self.assertEqual(
            result.actions,
            (),
        )


    def test_stream_filter_keeps_split_append_skill_name_attribute_as_text(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_USE_ASSETS",
            ],
        )

        first = stream_filter.filter(
            '<APPEND_SKILL name="file'
        )
        second = stream_filter.filter(
            '_manager" />'
        )

        self.assertEqual(
            first.text,
            '<APPEND_SKILL name="file',
        )
        self.assertEqual(
            first.actions,
            (),
        )
        self.assertEqual(
            second.text,
            '_manager" />',
        )
        self.assertEqual(
            second.actions,
            (),
        )
        self.assertEqual(
            stream_filter.flush(),
            "",
        )


    def test_stream_filter_handles_split_plural_append_skill_marker(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_USE_ASSETS",
            ],
        )

        first = stream_filter.filter(
            "<APPEND_SKILLS: file_manager,"
        )
        second = stream_filter.filter(
            " image_prompt_generator, porn, wildcards>"
        )

        self.assertEqual(
            first.text,
            "",
        )
        self.assertEqual(
            first.actions,
            (),
        )
        self.assertEqual(
            second.text,
            "",
        )
        marker_payload = (
            "file_manager, image_prompt_generator, porn, wildcards"
        )
        self.assertEqual(
            second.actions,
            (
                RuntimeActionCall(
                    name="APPEND_SKILL",
                    payload="file_manager",
                    marker_name="APPEND_SKILLS",
                    marker_payload=marker_payload,
                    marker_group="append_skills_001",
                ),
                RuntimeActionCall(
                    name="APPEND_SKILL",
                    payload="image_prompt_generator",
                    marker_name="APPEND_SKILLS",
                    marker_payload=marker_payload,
                    marker_group="append_skills_001",
                ),
                RuntimeActionCall(
                    name="APPEND_SKILL",
                    payload="porn",
                    marker_name="APPEND_SKILLS",
                    marker_payload=marker_payload,
                    marker_group="append_skills_001",
                ),
                RuntimeActionCall(
                    name="APPEND_SKILL",
                    payload="wildcards",
                    marker_name="APPEND_SKILLS",
                    marker_payload=marker_payload,
                    marker_group="append_skills_001",
                ),
            ),
        )
        self.assertEqual(
            second.observed_actions,
            (
                RuntimeActionCall(
                    name="APPEND_SKILLS",
                    payload=marker_payload,
                    marker_name="APPEND_SKILLS",
                    marker_payload=marker_payload,
                    marker_group="append_skills_001",
                ),
            ),
        )
        self.assertEqual(
            stream_filter.flush(),
            "",
        )
    def test_duplicate_append_skill_markers_are_preserved_as_text(self):

        appended_skill_names = set()

        def preserve_duplicate_append_skill(_raw_marker, action):
            if action.name != "APPEND_SKILL":
                return False

            requested_skill = normalize_skill_name(
                action.payload
            )

            if requested_skill in appended_skill_names:
                return True

            appended_skill_names.add(
                requested_skill
            )
            return False

        text = (
            "<SAVE_SESSION>\n"
            "<APPEND_SKILL: file_manager >\n"
            "<APPEND_SKILL: image_prompt_generator >\n"
            "<APPEND_SKILL: wildcards >\n"
            "<APPEND_SKILL: porn >\n"
            "<APPEND_SKILL: file_manager >\n"
            "<APPEND_SKILL: image_prompt_generator >"
        )

        result = extract_runtime_actions(
            text,
            enabled_actions=[
                "CAN_SAVE_SESSION",
                "CAN_USE_ASSETS",
            ],
            preserve_action_marker=preserve_duplicate_append_skill,
        )

        self.assertEqual(
            result.actions,
            (
                RuntimeActionCall(
                    name="SAVE_SESSION",
                ),
                RuntimeActionCall(
                    name="APPEND_SKILL",
                    payload="file_manager",
                ),
                RuntimeActionCall(
                    name="APPEND_SKILL",
                    payload="image_prompt_generator",
                ),
                RuntimeActionCall(
                    name="APPEND_SKILL",
                    payload="wildcards",
                ),
                RuntimeActionCall(
                    name="APPEND_SKILL",
                    payload="porn",
                ),
            ),
        )
        self.assertIn(
            "<APPEND_SKILL: file_manager >",
            result.text,
        )
        self.assertIn(
            "<APPEND_SKILL: image_prompt_generator >",
            result.text,
        )
        self.assertNotIn(
            "<APPEND_SKILL: wildcards >",
            result.text,
        )
        self.assertEqual(
            len(result.removed_markers),
            5,
        )


    def test_placeholder_append_skill_is_processed_once_and_duplicate_preserved(self):

        appended_skill_names = set()

        def preserve_duplicate_append_skill(_raw_marker, action):
            if action.name != "APPEND_SKILL":
                return False

            requested_skill = normalize_skill_name(
                action.payload
            )

            if requested_skill in appended_skill_names:
                return True

            appended_skill_names.add(
                requested_skill
            )
            return False

        result = extract_runtime_actions(
            (
                "<APPEND_SKILL: name of skill >\n"
                "<APPEND_SKILL: name of skill >"
            ),
            enabled_actions=[
                "CAN_USE_ASSETS",
            ],
            preserve_action_marker=preserve_duplicate_append_skill,
        )

        self.assertEqual(
            result.actions,
            (
                RuntimeActionCall(
                    name="APPEND_SKILL",
                    payload="name of skill",
                ),
            ),
        )
        self.assertIn(
            "<APPEND_SKILL: name of skill >",
            result.text,
        )
        self.assertEqual(
            len(result.removed_markers),
            1,
        )


    def test_apply_runtime_action_calls_lists_skills(self):

        Emitter = FakeEmitter

        Context = FakeContext

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                self.write_skill_fixture(
                    root,
                    "wildcards.txt",
                    "wildcards\nUse ASSET_ACTION for wildcard files.",
                )
                self.write_skill_fixture(
                    root,
                    "file_manager.txt",
                    "file_manager\nUse ASSET_ACTION for asset files.",
                )

                context = Context()
                context.emitter = Emitter()

                applied_count = asyncio.run(
                    apply_runtime_action_calls(
                        context,
                        (
                            RuntimeActionCall(
                                name="LIST_SKILLS",
                                payload="",
                            ),
                        ),
                    )
                )

                self.assertEqual(
                    applied_count,
                    1,
                )
                self.assertEqual(
                    context.runtime_asset_results[0]["action"],
                    "list_skills",
                )
                self.assertEqual(
                    context.runtime_asset_results[0]["requested"],
                    "",
                )
                skills_by_name = {
                    skill["name"]: skill
                    for skill in context.runtime_asset_results[0]["skills"]
                }
                self.assertIn(
                    "wildcards",
                    skills_by_name,
                )
                self.assertIn(
                    "file_manager",
                    skills_by_name,
                )
                self.assertNotIn(
                    "content",
                    skills_by_name["wildcards"],
                )
                self.assertTrue(
                    (root / "assets" / "skills" / "wildcards.txt").exists()
                )
                self.assertTrue(
                    (root / "assets" / "skills" / "file_manager.txt").exists()
                )
                self.assertEqual(
                    context.emitter.events[0]["action"],
                    "list_skills",
                )
                self.assertEqual(
                    context.emitter.events[0]["text"],
                    "Listed skills",
                )
                self.assertEqual(
                    context.runtime_session_action_history[0]["text"],
                    "Listed skills",
                )
                self.assertIsInstance(
                    context.runtime_session_action_history[0]["created_at"],
                    float,
                )

    def test_apply_runtime_action_calls_reads_list_skills_each_time(self):

        Emitter = FakeEmitter

        Context = FakeContext

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                self.write_skill_fixture(
                    root,
                    "file_manager.txt",
                    "file_manager\nUse ASSET_ACTION for asset files.",
                )

                context = Context()
                context.emitter = Emitter()
                context.runtime_current_turn_id = "turn_000001"

                asyncio.run(
                    apply_runtime_action_calls(
                        context,
                        (
                            RuntimeActionCall(
                                name="LIST_SKILLS",
                                payload="",
                            ),
                        ),
                    )
                )

                context.runtime_current_turn_id = "turn_000002"

                asyncio.run(
                    apply_runtime_action_calls(
                        context,
                        (
                            RuntimeActionCall(
                                name="LIST_SKILLS",
                                payload="",
                            ),
                        ),
                    )
                )

                self.assertEqual(
                    len(context.runtime_asset_results),
                    2,
                )
                self.assertNotIn(
                    "runtime_action_reused",
                    context.runtime_asset_results[0],
                )
                self.assertNotIn(
                    "runtime_action_reused",
                    context.runtime_asset_results[1],
                )
                self.assertEqual(
                    context.runtime_asset_results[1][
                        "runtime_turn_id"
                    ],
                    "turn_000002",
                )


    def test_empty_list_skills_returns_default_no_entries_tool_result(self):

        Emitter = FakeEmitter

        Context = FakeContext

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                context = Context()
                context.emitter = Emitter()

                applied_count = asyncio.run(
                    apply_runtime_action_calls(
                        context,
                        (
                            RuntimeActionCall(
                                name="LIST_SKILLS",
                                payload="",
                            ),
                        ),
                    )
                )

                self.assertEqual(
                    applied_count,
                    1,
                )
                self.assertEqual(
                    context.runtime_asset_results[0]["skills"],
                    [],
                )
                self.assertIn(
                    "No entries found.",
                    build_tool_results_context(
                        context
                    ),
                )


    def test_apply_runtime_action_calls_appends_and_removes_skill(self):

        Emitter = FakeEmitter

        Context = FakeContext

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                skill_path = (
                    root
                    / "assets"
                    / "skills"
                    / "Image Prompt Generator.txt"
                )
                skill_path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )
                skill_path.write_text(
                    "image_prompt_generator\nDescribe images.",
                    encoding="utf-8",
                )

                context = Context()
                context.emitter = Emitter()

                applied_count = asyncio.run(
                    apply_runtime_action_calls(
                        context,
                        (
                            RuntimeActionCall(
                                name="APPEND_SKILL",
                                payload="Image Prompt Generator.txt",
                            ),
                            RuntimeActionCall(
                                name="REMOVE_SKILL",
                                payload="wildcards",
                            ),
                        ),
                        runtime_message_id="skill-message-1",
                    )
                )

                self.assertEqual(
                    applied_count,
                    2,
                )
                self.assertEqual(
                    context.runtime_appended_skills[0]["name"],
                    "image_prompt_generator",
                )
                self.assertEqual(
                    context.runtime_appended_skills[0]["path"],
                    "assets/skills/Image Prompt Generator.txt",
                )
                self.assertIn(
                    "Describe images.",
                    context.runtime_appended_skills[0]["content"],
                )
                self.assertEqual(
                    context.emitter.events[0]["action"],
                    "append_skill",
                )
                self.assertEqual(
                    context.emitter.events[0]["text"],
                    "APPEND_SKILL: Image Prompt Generator.txt",
                )
                self.assertEqual(
                    context.emitter.events[2]["action"],
                    "remove_skill",
                )
                self.assertEqual(
                    context.emitter.events[2]["text"],
                    "REMOVE_SKILL: wildcards",
                )
                self.assertEqual(
                    {
                        event.get("runtime_message_id")
                        for event in context.emitter.events
                    },
                    {
                        "skill-message-1",
                    },
                )


    def test_append_missing_skill_records_error_for_model_and_history(self):

        Emitter = FakeEmitter

        Context = FakeContext

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                self.write_skill_fixture(
                    root,
                    "wildcards.txt",
                    "wildcards\nUse ASSET_ACTION for wildcard files.",
                )
                self.write_skill_fixture(
                    root,
                    "file_manager.txt",
                    "file_manager\nUse ASSET_ACTION for asset files.",
                )

                context = Context()
                context.emitter = Emitter()

                applied_count = asyncio.run(
                    apply_runtime_action_calls(
                        context,
                        (
                            RuntimeActionCall(
                                name="APPEND_SKILL",
                                payload="file_writer",
                            ),
                        ),
                    )
                )

                self.assertEqual(
                    applied_count,
                    1,
                )
                self.assertEqual(
                    context.runtime_appended_skills,
                    [],
                )
                self.assertEqual(
                    context.runtime_asset_results[0]["action"],
                    "append_skill",
                )
                self.assertEqual(
                    context.runtime_asset_results[0]["requested"],
                    "file_writer",
                )
                self.assertEqual(
                    context.runtime_asset_results[0]["error"],
                    "skill_not_found",
                )
                self.assertEqual(
                    context.runtime_session_action_history[0]["text"],
                    "APPEND_SKILL: file_writer ( does not exist )",
                )
                self.assertEqual(
                    len(context.emitter.events),
                    1,
                )
                self.assertEqual(
                    context.emitter.events[0]["text"],
                    "APPEND_SKILL: file_writer ( does not exist )",
                )
                self.assertEqual(
                    context.emitter.events[0]["status"],
                    "failed",
                )


    def test_append_skill_blocks_other_actions_in_same_stream(self):

        Emitter = FakeEmitter

        Context = FakeContext

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                skill_path = (
                    root
                    / "assets"
                    / "skills"
                    / "wildcards.txt"
                )
                skill_path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )
                skill_path.write_text(
                    "wildcards\nUse ASSET_ACTION for wildcard files.",
                    encoding="utf-8",
                )

                context = Context()
                context.emitter = Emitter()
                payload = json.dumps(
                    {
                        "action": "create_wildcard_file",
                        "path": "clothing/test_tops",
                        "lines": [
                            "linen shirt",
                        ],
                    }
                )

                applied_count = asyncio.run(
                    apply_runtime_action_calls(
                        context,
                        (
                            RuntimeActionCall(
                                name="APPEND_SKILL",
                                payload="wildcards",
                            ),
                            RuntimeActionCall(
                                name="ASSET_ACTION",
                                payload=payload,
                            ),
                        ),
                    )
                )

                self.assertEqual(
                    applied_count,
                    1,
                )
                self.assertEqual(
                    context.runtime_appended_skills[0]["name"],
                    "wildcards",
                )
                self.assertTrue(
                    context.runtime_skill_state_barrier_active,
                )
                self.assertEqual(
                    [
                        event["name"]
                        for event in context.runtime_action_events
                    ],
                    [
                        "append_skill",
                    ],
                )
                self.assertFalse(
                    hasattr(
                        context,
                        "runtime_asset_results",
                    )
                )
                self.assertFalse(
                    (
                        root
                        / "assets"
                        / "wildcards"
                        / "clothing"
                        / "test_tops.txt"
                    ).exists()
                )


    def test_list_skills_normalizes_name_from_filename(self):

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                skill_path = (
                    root
                    / "assets"
                    / "skills"
                    / "Image Prompt Generator.txt"
                )
                skill_path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )
                skill_path.write_text(
                    "ignored title\nSkill body.",
                    encoding="utf-8",
                )

                result = list_skills()

                names = [
                    skill["name"]
                    for skill in result["skills"]
                ]

                self.assertIn(
                    "image_prompt_generator",
                    names,
                )
                self.assertNotIn(
                    "ignored title",
                    names,
                )

