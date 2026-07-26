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



class RuntimeDelayedMemoryTests(RuntimeActionTestCase):

    def test_preserves_delayed_memory_marker_when_action_disabled(self):

        text = (
            "before\n"
            "<INTERNAL_ACTION_SAVE_DELAYED_MEMORY_CONTENT>\n"
            '{"demo": {"summary": "quoted marker"}}\n'
            "</INTERNAL_ACTION_SAVE_DELAYED_MEMORY_CONTENT>\n"
            "after"
        )

        result = extract_runtime_actions(
            text,
            enabled_actions=[],
        )

        self.assertEqual(
            result.text,
            text,
        )
        self.assertEqual(
            result.actions,
            (),
        )
        self.assertEqual(
            result.removed_markers,
            (),
        )


    def test_parses_delayed_memory_content_payload(self):

        report = parse_delayed_memory_content_payload(
            (
                "title: Radius of Influence Specs\n"
                "summary: Three-zone data priority model for Kowloon Sandbox simulation.\n"
                "tags: kowloon_sandbox, simulation, world_state, radius_of_influence\n"
                "body:\n"
                "### Radius of Influence Specs\n"
                "\n"
                "A complete, self-sufficient summary..."
            ),
            created_session_id="session-1",
            created_time="2026-06-29T12:00:00",
        )

        self.assertEqual(
            len(report),
            1,
        )
        report_id, report_value = next(
            iter(report.items())
        )
        self.assertRegex(
            report_id,
            r"^[a-z0-9]{6}$",
        )
        self.assertEqual(
            report_value,
            {
                "title": "Radius of Influence Specs",
                "summary": (
                    "Three-zone data priority model for Kowloon Sandbox simulation."
                ),
                "tags": [
                    "kowloon_sandbox",
                    "simulation",
                    "world_state",
                    "radius_of_influence",
                ],
                "body": (
                    "### Radius of Influence Specs\n\n"
                    "A complete, self-sufficient summary..."
                ),
                "created_session_id": "session-1",
                "created_time": "2026-06-29T12:00:00",
            },
        )


    def test_extracts_delayed_memory_content_block(self):

        result = extract_runtime_actions(
            (
                "<INTERNAL_ACTION_SAVE_DELAYED_MEMORY_CONTENT>\n"
                "title: Radius of Influence Specs\n"
                "summary: Three-zone data priority model for Kowloon Sandbox simulation.\n"
                "tags: kowloon_sandbox, simulation, world_state, radius_of_influence\n"
                "body:\n"
                "### Radius of Influence Specs\n"
                "\n"
                "A complete, self-sufficient summary...\n"
                "</INTERNAL_ACTION_SAVE_DELAYED_MEMORY_CONTENT>\n"
                "\n"
                "Done."
            ),
            enabled_actions=[
                "CAN_SAVE_DELAYED_MEMORY",
            ],
        )

        self.assertEqual(
            result.text,
            "Done.",
        )
        self.assertEqual(
            result.count("SAVE_DELAYED_MEMORY_CONTENT"),
            1,
        )
        report = json.loads(
            result.actions[0].payload
        )
        self.assertEqual(
            len(report),
            1,
        )
        report_id, report_value = next(
            iter(report.items())
        )
        self.assertRegex(
            report_id,
            r"^[a-z0-9]{6}$",
        )
        self.assertEqual(
            report_value["title"],
            "Radius of Influence Specs",
        )


    def test_stream_filter_emits_delayed_memory_started_action(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_SAVE_DELAYED_MEMORY",
            ],
        )

        first = stream_filter.filter(
            (
                "<SAVE_DELAYED_MEMORY_CONTENT>\n"
                "title: Radius of Influence Specs\n"
                "summary: Three-zone data priority model.\n"
            )
        )
        second = stream_filter.filter(
            (
                "tags: simulation, world_state\n"
                "body: Complete report body.\n"
                "</SAVE_DELAYED_MEMORY_CONTENT>\n"
            )
        )

        self.assertEqual(
            first.text,
            "",
        )
        self.assertEqual(
            first.started_actions,
            (
                RuntimeActionCall(
                    name="SAVE_DELAYED_MEMORY_CONTENT",
                    payload="",
                ),
            ),
        )
        self.assertEqual(
            second.count("SAVE_DELAYED_MEMORY_CONTENT"),
            1,
        )


    def test_stream_filter_recovers_complete_delayed_memory_without_closing_tag(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_SAVE_DELAYED_MEMORY",
            ],
        )

        first = stream_filter.filter(
            (
                "<SAVE_DELAYED_MEMORY_CONTENT>\n"
                "title: Radius of Influence Specs\n"
                "summary: Three-zone data priority model.\n"
                "tags: simulation, world_state\n"
                "body: Complete report body.\n"
            )
        )
        tail = stream_filter.flush_result()

        self.assertEqual(
            first.started_actions[0].name,
            "SAVE_DELAYED_MEMORY_CONTENT",
        )
        self.assertEqual(
            tail.count("SAVE_DELAYED_MEMORY_CONTENT"),
            1,
        )
        report = json.loads(
            tail.actions[0].payload
        )
        self.assertEqual(
            next(iter(report.values()))["title"],
            "Radius of Influence Specs",
        )


    def test_extracts_delayed_memory_action_markers(self):

        result = extract_runtime_actions(
            (
                "<LIST_DELAYED_MEMORY>\n"
                "<APPEND_DELAYED_MEMORY: a1b2c3>\n"
                "<REMOVE_DELAYED_MEMORY: d4e5f6>\n"
            ),
            enabled_actions=[
                "CAN_SAVE_DELAYED_MEMORY",
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
                    name="LIST_DELAYED_MEMORY",
                    payload="",
                ),
                RuntimeActionCall(
                    name="APPEND_DELAYED_MEMORY",
                    payload="a1b2c3",
                ),
                RuntimeActionCall(
                    name="REMOVE_DELAYED_MEMORY",
                    payload="d4e5f6",
                ),
            ),
        )


    def test_stream_filter_holds_split_delayed_memory_action_marker(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_SAVE_DELAYED_MEMORY",
            ],
        )

        first = stream_filter.filter(
            "<APPEND_DELAYED_MEMORY: h"
        )
        second = stream_filter.filter(
            "0qa49>"
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
                    name="APPEND_DELAYED_MEMORY",
                    payload="h0qa49",
                ),
            ),
        )


    def test_stream_filter_holds_split_internal_delayed_memory_action_marker(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_SAVE_DELAYED_MEMORY",
            ],
        )

        first = stream_filter.filter(
            "<INTERNAL_ACTION_REMOVE_DELAYED_MEMORY: k"
        )
        second = stream_filter.filter(
            "dhpjo>\nRemoved it from the session."
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
            "Removed it from the session.",
        )
        self.assertEqual(
            second.actions,
            (
                RuntimeActionCall(
                    name="REMOVE_DELAYED_MEMORY",
                    payload="kdhpjo",
                ),
            ),
        )


    def test_stream_filter_holds_split_delayed_memory_block(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_SAVE_DELAYED_MEMORY",
            ],
        )

        first = stream_filter.filter(
            (
                "<INTERNAL_ACTION_SAVE_DELAYED_MEMORY_CONTENT>\n"
                "title: Radius"
            )
        )
        second = stream_filter.filter(
            (
                " of Influence Specs\n"
                "summary: Summary\n"
                "tags: a, b\n"
                "body:\n"
                "Body\n"
                "</INTERNAL_ACTION_SAVE_DELAYED_MEMORY_CONTENT>\n"
                "Saved."
            )
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
            "Saved.",
        )
        self.assertEqual(
            second.count("SAVE_DELAYED_MEMORY_CONTENT"),
            1,
        )


    def test_apply_runtime_action_calls_saves_delayed_memory_report(self):

        Emitter = FakeEmitter

        Context = FakeContext

        context = Context()
        context.emitter = Emitter()
        context.session_id = "session-1"
        context.timestamp = "2026-06-29T12:00:00"

        report_payload = json.dumps(
            {
                "radius_of_influence_specs": {
                    "title": "Radius of Influence Specs",
                    "summary": "Three-zone data priority model.",
                    "tags": [
                        "kowloon_sandbox",
                        "simulation",
                    ],
                    "body": "### Radius of Influence Specs\n\nBody",
                    "created_session_id": "",
                    "created_time": "",
                },
            },
            ensure_ascii=False,
        )

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="SAVE_DELAYED_MEMORY_CONTENT",
                        payload=report_payload,
                    ),
                ),
                user_message="save summary",
            )
        )

        self.assertEqual(
            applied_count,
            1,
        )
        self.assertEqual(
            len(context.delayed_memory_reports),
            1,
        )
        report_id, report = next(
            iter(context.delayed_memory_reports.items())
        )
        self.assertRegex(
            report_id,
            r"^[a-z0-9]{6}$",
        )
        self.assertEqual(
            report["created_session_id"],
            "session-1",
        )
        self.assertEqual(
            report["created_time"],
            "2026-06-29T12:00:00",
        )
        self.assertEqual(
            report["created_date"],
            "2026-06-29T12:00:00",
        )
        self.assertEqual(
            report["appended_times"],
            0,
        )
        self.assertEqual(
            report["append_streak"],
            0,
        )
        self.assertEqual(
            context.emitter.events,
            [
                {
                    "type": "runtime_action",
                    "action": "save_delayed_memory_content",
                    "id": "save_delayed_memory_content_001",
                    "status": "completed",
                    "display_name": "SAVE_DELAYED_MEMORY_CONTENT",
                    "close_tag": True,
                    "text": "Saved delayed memory: Radius of Influence Specs",
                    "delayed_memory_report_id": report_id,
                    "delayed_memory_report": context.delayed_memory_reports,
                },
            ],
        )

        self.assertEqual(
            context.runtime_session_action_history[0]["text"],
            "Delayed memory saved: Radius of Influence Specs",
        )
        self.assertIsInstance(
            context.runtime_session_action_history[0]["created_at"],
            float,
        )

        tool_results = build_tool_results_context(
            context
        )
        self.assertIn(
            '<TOOL_RESULT name="SAVE_DELAYED_MEMORY_CONTENT">',
            tool_results,
        )
        self.assertIn(
            "delayed_memory_reports (Delayed Memory storage)",
            tool_results,
        )
        self.assertIn(
            f'"id": "{report_id}"',
            tool_results,
        )
        self.assertIn(
            "Radius of Influence Specs",
            tool_results,
        )
        self.assertIn(
            "Three-zone data priority model.",
            tool_results,
        )


    def test_delayed_memory_save_events_use_monotonic_action_ids(self):

        Emitter = FakeEmitter

        Context = FakeContext

        context = Context()
        context.emitter = Emitter()
        context.session_id = "session-1"
        context.timestamp = "2026-06-29T12:00:00"

        report_payload = json.dumps(
            {
                "weather_report": {
                    "title": "Test Weather Report",
                    "summary": "Fake weather summary.",
                    "tags": [
                        "test",
                        "weather",
                    ],
                    "body": "Fake weather body.",
                },
            },
            ensure_ascii=False,
        )

        first_action = RuntimeActionCall(
            name="SAVE_DELAYED_MEMORY_CONTENT",
            payload=report_payload,
        )
        second_action = RuntimeActionCall(
            name="SAVE_DELAYED_MEMORY_CONTENT",
            payload=report_payload,
        )

        first_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    first_action,
                ),
                user_message="please save this report in delayed memory",
                confirmed_action_ids=[
                    id(first_action),
                ],
            )
        )
        second_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    second_action,
                ),
                user_message="please save this report in delayed memory",
                confirmed_action_ids=[
                    id(second_action),
                ],
            )
        )

        self.assertEqual(
            first_count,
            1,
        )
        self.assertEqual(
            second_count,
            1,
        )
        self.assertEqual(
            [
                event["id"]
                for event in context.emitter.events
                if event.get("action") == "save_delayed_memory_content"
            ],
            [
                "save_delayed_memory_content_001",
                "save_delayed_memory_content_002",
            ],
        )


    def test_rejected_delayed_memory_is_recorded_with_other_turn_actions(self):

        Emitter = FakeEmitter

        Context = FakeContext

        context = Context()
        context.emitter = Emitter()
        context.timestamp = "2026-07-13T18:00:00"
        context.session_id = "session-1"
        context.turn_number = 1
        context.runtime_current_turn_id = "turn-mixed-memory-save"

        delayed_memory_payload = json.dumps(
            {
                "session_state_snapshot": {
                    "title": "Session State Snapshot",
                    "summary": "Current session state.",
                    "tags": [
                        "session",
                    ],
                    "body": "Full report.",
                },
            },
            ensure_ascii=False,
        )

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="CREATE_ACTIVE_MEMORY",
                        payload="current session state",
                    ),
                    RuntimeActionCall(
                        name="SAVE_DELAYED_MEMORY_CONTENT",
                        payload=delayed_memory_payload,
                    ),
                ),
                user_message="save summary and save one state in active memory",
            )
        )

        self.assertEqual(
            applied_count,
            2,
        )
        self.assertEqual(
            [
                event["name"]
                for event in context.runtime_action_events
            ],
            [
                "create_active_memory",
                "save_delayed_memory_content",
            ],
        )
        from agent.nodes.brain import (
            format_followup_actions_from_events,
        )

        self.assertEqual(
            format_followup_actions_from_events(
                context.runtime_action_events
            ),
            (
                "create_active_memory, "
                "save_delayed_memory"
            ),
        )
        self.assertFalse(
            hasattr(
                context,
                "runtime_delayed_memory_save_rejected_pending",
            )
        )


    def test_apply_runtime_action_calls_suffixes_duplicate_delayed_memory_key(self):

        Emitter = FakeEmitter

        Context = FakeContext

        context = Context()
        context.emitter = Emitter()
        context.session_id = "session-1"
        context.timestamp = "2026-06-29T12:00:00"
        context.delayed_memory_reports = {
            "kowloon_sandbox_architecture_contextual_status": {
                "title": "Kowloon Sandbox Architecture & Contextual Status",
                "summary": "Existing report.",
            },
        }

        report_payload = json.dumps(
            {
                "kowloon_sandbox_architecture_contextual_status": {
                    "title": "Kowloon Sandbox Architecture & Contextual Status",
                    "summary": "New report.",
                    "tags": [],
                    "body": "Updated context.",
                    "created_session_id": "",
                    "created_time": "",
                },
            },
            ensure_ascii=False,
        )

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="SAVE_DELAYED_MEMORY_CONTENT",
                        payload=report_payload,
                    ),
                ),
                user_message="save summary",
            )
        )

        self.assertEqual(
            applied_count,
            1,
        )
        self.assertEqual(
            context.delayed_memory_reports[
                "kowloon_sandbox_architecture_contextual_status"
            ]["summary"],
            "Existing report.",
        )
        new_report_ids = [
            report_id
            for report_id in context.delayed_memory_reports
            if report_id != "kowloon_sandbox_architecture_contextual_status"
        ]
        self.assertEqual(
            len(new_report_ids),
            1,
        )
        self.assertRegex(
            new_report_ids[0],
            r"^[a-z0-9]{6}$",
        )
        self.assertEqual(
            context.delayed_memory_reports[
                new_report_ids[0]
            ]["summary"],
            "New report.",
        )
        self.assertEqual(
            context.emitter.events[0]["delayed_memory_report"],
            {
                new_report_ids[0]: (
                    context.delayed_memory_reports[
                        new_report_ids[0]
                    ]
                ),
            },
        )


    def test_append_delayed_memory_uses_appended_context_block(self):

        Emitter = FakeEmitter

        Context = FakeContext

        context = Context()
        context.emitter = Emitter()
        context.runtime_action_events = []
        context.runtime_search_calls = []
        context.runtime_appended_skills = []
        context.runtime_asset_results = []
        context.delayed_memory_reports = {
            "a1b2c3": {
                "title": "Русский отчёт",
                "summary": "Summary",
                "tags": [
                    "tag",
                ],
                "body": "Body",
            },
            "b2c3d4": {
                "title": "Second report",
                "summary": "Summary",
                "tags": [
                    "tag",
                ],
                "body": "Body",
            },
        }

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="LIST_DELAYED_MEMORY",
                    ),
                    RuntimeActionCall(
                        name="APPEND_DELAYED_MEMORY",
                        payload="a1b2c3",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            2,
        )
        tool_results = build_tool_results_context(
            context
        )
        self.assertIn(
            "<TOOLS_RESULTS>",
            tool_results,
        )
        self.assertNotIn(
            "<TOOL_RESULTS",
            tool_results,
        )
        self.assertIn(
            "1. Русский отчёт | id: a1b2c3",
            tool_results,
        )
        self.assertNotIn(
            '<TOOL_RESULT name="APPEND_DELAYED_MEMORY">',
            tool_results,
        )
        self.assertNotIn(
            "<APPENDED_DELAYED_MEMORY>",
            tool_results,
        )
        appended_context = build_appended_delayed_memory_context(
            context
        )
        self.assertIn(
            "<APPENDED_DELAYED_MEMORY>",
            appended_context,
        )
        self.assertIn(
            '"id": "a1b2c3"',
            appended_context,
        )
        self.assertEqual(
            context.emitter.events[0]["text"],
            "Listing delayed memory",
        )
        self.assertEqual(
            context.emitter.events[1]["text"],
            (
                "Appending: "
                + context.delayed_memory_reports[
                    "a1b2c3"
                ]["title"]
            ),
        )
        self.assertEqual(
            len(context.emitter.events),
            2,
        )
        self.assertEqual(
            context.runtime_session_action_history[0]["text"],
            (
                "Delayed memory appended: "
                + context.delayed_memory_reports[
                    "a1b2c3"
                ]["title"]
            ),
        )


    def test_append_delayed_memory_replaces_current_report(self):

        Emitter = FakeEmitter

        Context = FakeContext

        context = Context()
        context.emitter = Emitter()
        context.runtime_action_events = []
        context.runtime_search_calls = []
        context.runtime_appended_skills = []
        context.runtime_asset_results = []
        context.delayed_memory_reports = {
            "a1b2c3": {
                "title": "First report",
                "summary": "Summary",
                "tags": [
                    "tag",
                ],
                "body": "Body",
            },
            "b2c3d4": {
                "title": "Second report",
                "summary": "Summary",
                "tags": [
                    "tag",
                ],
                "body": "Body",
            },
        }

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="APPEND_DELAYED_MEMORY",
                        payload="a1b2c3",
                    ),
                    RuntimeActionCall(
                        name="APPEND_DELAYED_MEMORY",
                        payload="a1b2c3",
                    ),
                    RuntimeActionCall(
                        name="APPEND_DELAYED_MEMORY",
                        payload="b2c3d4",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            3,
        )
        self.assertEqual(
            context.runtime_appended_delayed_memory["id"],
            "b2c3d4",
        )

        appended_context = build_appended_delayed_memory_context(
            context
        )
        self.assertIn(
            "<APPENDED_DELAYED_MEMORY>",
            appended_context,
        )
        self.assertIn(
            '"title": "Second report"',
            appended_context,
        )
        self.assertNotIn(
            '"title": "First report"',
            appended_context,
        )

        tool_results = build_tool_results_context(
            context
        )
        self.assertNotIn(
            "<TOOL_RESULTS type='delayed_memory'>",
            tool_results,
        )
        self.assertNotIn(
            "<APPENDED_DELAYED_MEMORY>",
            tool_results,
        )
        self.assertEqual(
            [
                item["text"]
                for item in context.runtime_session_action_history
            ],
            [
                "Delayed memory appended: First report",
                "Delayed memory appended: Second report",
            ],
        )


    def test_invalid_append_delayed_memory_id_returns_failure_tool_result(self):

        Emitter = FakeEmitter

        Context = FakeContext

        context = Context()
        context.emitter = Emitter()
        context.runtime_action_events = []
        context.runtime_search_calls = []
        context.runtime_appended_skills = []
        context.runtime_asset_results = []
        context.runtime_delayed_memory_results = []
        context.delayed_memory_reports = {
            "a1b2c3": {
                "title": "Saved report",
                "summary": "Summary",
                "tags": [
                    "tag",
                ],
                "body": "Body",
            },
        }

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="APPEND_DELAYED_MEMORY",
                        payload="c7dtso",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            1,
        )
        self.assertEqual(
            context.emitter.events[0]["status"],
            "failed",
        )
        self.assertEqual(
            context.runtime_delayed_memory_results[0]["ok"],
            False,
        )
        self.assertEqual(
            context.runtime_delayed_memory_results[0]["error"],
            "delayed_memory_not_found",
        )
        tool_results = build_tool_results_context(
            context
        )
        self.assertEqual(
            tool_results.count("<TOOLS_RESULTS>"),
            1,
        )
        self.assertNotIn(
            "<TOOL_RESULTS",
            tool_results,
        )
        self.assertIn(
            '<TOOL_RESULT name="APPEND_DELAYED_MEMORY">',
            tool_results,
        )
        self.assertIn(
            "No entries found.",
            tool_results,
        )


    def test_append_delayed_memory_tracks_session_metadata(self):

        Emitter = FakeEmitter

        Context = FakeContext

        context = Context()
        context.emitter = Emitter()
        context.session_id = "session-a"
        context.timestamp = "2026-07-17T19:40:00+03:00"
        context.runtime_action_events = []
        context.runtime_search_calls = []
        context.runtime_appended_skills = []
        context.runtime_asset_results = []
        context.delayed_memory_reports = {
            "a1b2c3": {
                "title": "Pinned report",
                "summary": "Summary",
                "tags": [
                    "tag",
                ],
                "body": "Body",
                "created_time": "2026-07-16T10:00:00+03:00",
            },
        }

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="APPEND_DELAYED_MEMORY",
                        payload="a1b2c3",
                    ),
                    RuntimeActionCall(
                        name="APPEND_DELAYED_MEMORY",
                        payload="a1b2c3",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            2,
        )
        report = context.delayed_memory_reports["a1b2c3"]
        self.assertEqual(
            report["appended_times"],
            2,
        )
        self.assertEqual(
            report["append_streak"],
            1,
        )
        self.assertEqual(
            report["created_date"],
            "2026-07-16T10:00:00+03:00",
        )
        self.assertEqual(
            report["last_appended_date"],
            "2026-07-17T19:40:00+03:00",
        )
        self.assertEqual(
            report["last_appended_session_id"],
            "session-a",
        )
        self.assertEqual(
            report["all_appended_session_ids"],
            [
                "session-a",
            ],
        )
        self.assertEqual(
            context.runtime_appended_delayed_memory_ids,
            [
                "a1b2c3",
            ],
        )

        next_context = Context()
        next_context.emitter = Emitter()
        next_context.session_id = "session-b"
        next_context.timestamp = "2026-07-19T12:15:00+03:00"
        next_context.runtime_action_events = []
        next_context.runtime_search_calls = []
        next_context.runtime_appended_skills = []
        next_context.runtime_asset_results = []
        next_context.delayed_memory_reports = (
            context.delayed_memory_reports
        )

        asyncio.run(
            apply_runtime_action_calls(
                next_context,
                (
                    RuntimeActionCall(
                        name="APPEND_DELAYED_MEMORY",
                        payload="a1b2c3",
                    ),
                ),
            )
        )

        report = next_context.delayed_memory_reports["a1b2c3"]
        self.assertEqual(
            report["appended_times"],
            3,
        )
        self.assertEqual(
            report["append_streak"],
            2,
        )
        self.assertEqual(
            report["last_appended_session_id"],
            "session-b",
        )
        self.assertEqual(
            report["all_appended_session_ids"],
            [
                "session-a",
                "session-b",
            ],
        )


    def test_remove_delayed_memory_only_detaches_from_context(self):

        Emitter = FakeEmitter

        Context = FakeContext

        context = Context()
        context.emitter = Emitter()
        context.runtime_action_events = []
        context.runtime_search_calls = []
        context.runtime_appended_skills = []
        context.runtime_asset_results = []
        context.runtime_appended_delayed_memory = {
            "id": "a1b2c3",
            "title": "Pinned report",
            "summary": "Summary",
        }
        context.delayed_memory_reports = {
            "a1b2c3": {
                "title": "Pinned report",
                "summary": "Summary",
                "tags": [
                    "tag",
                ],
                "body": "Body",
            },
        }

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="REMOVE_DELAYED_MEMORY",
                        payload="a1b2c3",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            1,
        )
        self.assertEqual(
            context.runtime_appended_delayed_memory,
            {},
        )
        self.assertIn(
            "a1b2c3",
            context.delayed_memory_reports,
        )
        self.assertEqual(
            context.delayed_memory_reports,
            {
                "a1b2c3": {
                    "title": "Pinned report",
                    "summary": "Summary",
                    "tags": [
                        "tag",
                    ],
                    "body": "Body",
                },
            },
        )
        self.assertEqual(
            context.emitter.events[0]["text"],
            "Removing: Pinned report",
        )
        self.assertEqual(
            context.runtime_session_action_history[0]["text"],
            "Delayed memory removed from context: Pinned report",
        )


    def test_invalid_remove_delayed_memory_id_returns_failed_result(self):

        Emitter = FakeEmitter

        Context = FakeContext

        context = Context()
        context.emitter = Emitter()
        context.runtime_action_events = []
        context.runtime_search_calls = []
        context.runtime_appended_skills = []
        context.runtime_asset_results = []
        context.runtime_delayed_memory_results = []
        context.delayed_memory_reports = {
            "a1b2c3": {
                "title": "Saved report",
                "summary": "Summary",
                "tags": [
                    "tag",
                ],
                "body": "Body",
            },
        }

        extracted = extract_runtime_actions(
            "<INTERNAL_ACTION_REMOVE_DELAYED_MEMORY: Test report (summary check)>",
            enabled_actions=(
                "REMOVE_DELAYED_MEMORY",
            ),
        )

        self.assertEqual(
            extracted.actions,
            (
                RuntimeActionCall(
                    name="REMOVE_DELAYED_MEMORY",
                    payload="Test report (summary check)",
                ),
            ),
        )

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                extracted.actions,
            )
        )

        self.assertEqual(
            applied_count,
            1,
        )
        self.assertEqual(
            context.emitter.events[0]["status"],
            "failed",
        )
        self.assertEqual(
            context.runtime_delayed_memory_results[0]["ok"],
            False,
        )
        self.assertEqual(
            context.runtime_delayed_memory_results[0]["error"],
            "invalid_delayed_memory_id",
        )
        self.assertIn(
            '<TOOL_RESULT name="REMOVE_DELAYED_MEMORY">',
            build_tool_results_context(
                context
            ),
        )
        self.assertNotIn(
            "<TOOL_RESULTS",
            build_tool_results_context(
                context
            ),
        )
        self.assertIn(
            "No entries found.",
            build_tool_results_context(
                context
            ),
        )


    def test_missing_remove_delayed_memory_id_returns_failed_result(self):

        Emitter = FakeEmitter

        Context = FakeContext

        context = Context()
        context.emitter = Emitter()
        context.runtime_action_events = []
        context.runtime_search_calls = []
        context.runtime_appended_skills = []
        context.runtime_asset_results = []
        context.runtime_delayed_memory_results = []
        context.delayed_memory_reports = {
            "a1b2c3": {
                "title": "Saved report",
                "summary": "Summary",
                "tags": [
                    "tag",
                ],
                "body": "Body",
            },
        }

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="REMOVE_DELAYED_MEMORY",
                        payload="c7dtso",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            1,
        )
        self.assertEqual(
            context.emitter.events[0]["status"],
            "failed",
        )
        self.assertEqual(
            context.runtime_delayed_memory_results[0]["ok"],
            False,
        )
        self.assertEqual(
            context.runtime_delayed_memory_results[0]["error"],
            "delayed_memory_not_found",
        )
        tool_results = build_tool_results_context(
            context
        )
        self.assertEqual(
            tool_results.count("<TOOLS_RESULTS>"),
            1,
        )
        self.assertNotIn(
            "<TOOL_RESULTS",
            tool_results,
        )
        self.assertIn(
            '<TOOL_RESULT name="REMOVE_DELAYED_MEMORY">',
            tool_results,
        )
        self.assertIn(
            "No entries found.",
            tool_results,
        )

