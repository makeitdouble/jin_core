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
from runtime.stream import RuntimeStream
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
    parse_delayed_memory_payload,
)
from utils.assets_utils import run_asset_action
from utils.brain_client_utils import (
    record_delayed_memory_runtime_result,
    build_delayed_memory_report,
    flush_pending_active_memory_resolve_failure_history,
    include_pinned_delayed_memory_reports,
    load_delayed_memory_report,
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
            "<SAVE_DELAYED_MEMORY>\n"
            '{"demo": {"summary": "quoted marker"}}\n'
            "</SAVE_DELAYED_MEMORY>\n"
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

        report = parse_delayed_memory_payload(
            (
                "title: Radius of Influence Specs\n"
                "summary: Three-zone data priority model for Kowloon Sandbox simulation.\n"
                "tags: kowloon_sandbox, simulation, world_state, radius_of_influence, Kowloon, radius of influence\n"
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
                    "Kowloon",
                    "radius of influence",
                ],
                "body": (
                    "### Radius of Influence Specs\n\n"
                    "A complete, self-sufficient summary..."
                ),
                "pinned": False,
                "anchor_fact_ids": [],
                "facts_ids": [],
                "attachments_ids": [],
                "created_session_id": "session-1",
                "created_time": "2026-06-29T12:00:00",
            },
        )


    def test_parses_long_term_fact_ids_for_delayed_memory_report(self):

        report = parse_delayed_memory_payload(
            (
                "title: Project context\n"
                "summary: Consolidated project details.\n"
                "tags: project, context\n"
                "body:\n"
                "Reusable project summary.\n"
                "long_term_facts_ids: "
                "F1, F2, invalid, F1"
            )
        )

        report_value = next(
            iter(report.values())
        )

        self.assertEqual(
            report_value["facts_ids"],
            [
                "F1",
                "F2",
            ],
        )
        self.assertNotIn("long_term_facts_ids", report_value)


    def test_parses_anchor_and_facts_ids_for_delayed_memory_report(self):

        report = parse_delayed_memory_payload(
            (
                "title: Social context\n"
                "summary: Consolidated social details.\n"
                "tags: social\n"
                "body: Reusable summary.\n"
                "anchor_fact_ids: F1, F1\n"
                "facts_ids: F1, F2, F3"
            )
        )
        report_value = next(iter(report.values()))

        self.assertEqual(report_value["anchor_fact_ids"], ["F1"])
        self.assertEqual(
            report_value["facts_ids"],
            ["F1", "F2", "F3"],
        )

    def test_parses_json_array_fact_ids_for_delayed_memory_report(self):

        report = parse_delayed_memory_payload(
            (
                "title: Architecture context\n"
                "summary: Consolidated architecture details.\n"
                "tags: architecture, protocol\n"
                "body: Reusable summary.\n"
                'anchor_fact_ids: ["F1", "F5", "F13"]\n'
                'facts_ids: ["F1", "F5", "F13", "F25", "F26"]'
            )
        )
        report_value = next(iter(report.values()))

        self.assertEqual(
            report_value["anchor_fact_ids"],
            ["F1", "F5", "F13"],
        )
        self.assertEqual(
            report_value["facts_ids"],
            ["F1", "F5", "F13", "F25", "F26"],
        )

    def test_parses_unbounded_attachment_ids_for_delayed_memory_report(self):

        report = parse_delayed_memory_payload(
            (
                "title: Files context\n"
                "summary: Linked files.\n"
                "tags: files\n"
                "body: Reusable summary.\n"
                "attachments_ids: abc123, def456, ghi789, jkl012, mno345, pqr678, abc123, bad"
            )
        )
        report_value = next(iter(report.values()))

        self.assertEqual(
            report_value["attachments_ids"],
            [
                "abc123",
                "def456",
                "ghi789",
                "jkl012",
                "mno345",
                "pqr678",
            ],
        )

    def test_build_report_keeps_only_existing_l4_fact_ids(self):

        context = SimpleNamespace(
            session_id="session-1",
            timestamp="2026-08-02T19:00:00",
            runtime_long_term_memory_store={
                "facts": [
                    {
                        "id": "F1",
                        "key": "project.fact",
                        "value": "Existing fact",
                    },
                ],
            },
        )
        report = build_delayed_memory_report(
            context,
            json.dumps({
                "abc123": {
                    "title": "Project context",
                    "summary": "Summary",
                    "tags": ["project"],
                    "body": "Body",
                    "long_term_facts_ids": [
                        "F1",
                        "F99",
                    ],
                },
            }),
        )

        report_value = report["abc123"]

        self.assertEqual(
            report_value["facts_ids"],
            [
                "F1",
            ],
        )
        self.assertNotIn("absorbed_fact_ids", report_value)
        self.assertNotIn("long_term_facts_ids", report_value)


    def test_extracts_delayed_memory_content_block(self):

        result = extract_runtime_actions(
            (
                "<SAVE_DELAYED_MEMORY>\n"
                "title: Radius of Influence Specs\n"
                "summary: Three-zone data priority model for Kowloon Sandbox simulation.\n"
                "tags: kowloon_sandbox, simulation, world_state, radius_of_influence\n"
                "body:\n"
                "### Radius of Influence Specs\n"
                "\n"
                "A complete, self-sufficient summary...\n"
                "</SAVE_DELAYED_MEMORY>\n"
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
            result.count("SAVE_DELAYED_MEMORY"),
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
                "<SAVE_DELAYED_MEMORY>\n"
                "title: Radius of Influence Specs\n"
                "summary: Three-zone data priority model.\n"
            )
        )
        second = stream_filter.filter(
            (
                "tags: simulation, world_state\n"
                "body: Complete report body.\n"
                "</SAVE_DELAYED_MEMORY>\n"
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
                    name="SAVE_DELAYED_MEMORY",
                    payload="",
                ),
            ),
        )
        self.assertEqual(
            second.count("SAVE_DELAYED_MEMORY"),
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
                "<SAVE_DELAYED_MEMORY>\n"
                "title: Radius of Influence Specs\n"
                "summary: Three-zone data priority model.\n"
                "tags: simulation, world_state\n"
                "body: Complete report body.\n"
            )
        )
        tail = stream_filter.flush_result()

        self.assertEqual(
            first.started_actions[0].name,
            "SAVE_DELAYED_MEMORY",
        )
        self.assertEqual(
            tail.count("SAVE_DELAYED_MEMORY"),
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
                "<LOAD_DELAYED_MEMORY: a1b2c3>\n"
                "<UNLOAD_DELAYED_MEMORY: d4e5f6>\n"
            ),
            enabled_actions=[
                "CAN_SAVE_DELAYED_MEMORY",
            ],
        )

        self.assertEqual(
            result.text,
            "<LIST_DELAYED_MEMORY>\n",
        )
        self.assertEqual(
            result.actions,
            (
                RuntimeActionCall(
                    name="LOAD_DELAYED_MEMORY",
                    payload="a1b2c3",
                ),
                RuntimeActionCall(
                    name="UNLOAD_DELAYED_MEMORY",
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
            "<LOAD_DELAYED_MEMORY: h"
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
                    name="LOAD_DELAYED_MEMORY",
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
            "<UNLOAD_DELAYED_MEMORY: k"
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
                    name="UNLOAD_DELAYED_MEMORY",
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
                "<SAVE_DELAYED_MEMORY>\n"
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
                "</SAVE_DELAYED_MEMORY>\n"
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
            second.count("SAVE_DELAYED_MEMORY"),
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
                        name="SAVE_DELAYED_MEMORY",
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
            report["loaded_times"],
            0,
        )
        self.assertEqual(
            report["load_streak"],
            0,
        )
        self.assertEqual(
            context.emitter.events,
            [
                {
                    "type": "runtime_action",
                    "action": "save_delayed_memory",
                    "id": "save_delayed_memory_001",
                    "status": "completed",
                    "display_name": "SAVE_DELAYED_MEMORY",
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
            '<TOOL_RESULT name="SAVE_DELAYED_MEMORY"',
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
            name="SAVE_DELAYED_MEMORY",
            payload=report_payload,
        )
        second_action = RuntimeActionCall(
            name="SAVE_DELAYED_MEMORY",
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
                if event.get("action") == "save_delayed_memory"
            ],
            [
                "save_delayed_memory_001",
                "save_delayed_memory_002",
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
                        name="SAVE_ACTIVE_MEMORY",
                        payload="current session state",
                    ),
                    RuntimeActionCall(
                        name="SAVE_DELAYED_MEMORY",
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
                "save_active_memory",
                "save_delayed_memory",
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
                "SAVE_ACTIVE_MEMORY, "
                "SAVE_DELAYED_MEMORY"
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
                        name="SAVE_DELAYED_MEMORY",
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


    def test_load_delayed_memory_prunes_missing_l4_fact_links(self):

        context = SimpleNamespace(
            delayed_memory_reports={
                "abc123": {
                    "title": "Architecture",
                    "anchor_fact_ids": ["F1", "F9"],
                    "facts_ids": ["F1", "F2", "F9"],
                    "long_term_facts_ids": ["F10"],
                },
            },
            runtime_long_term_memory_store={
                "facts": [
                    {"id": "F1"},
                    {"id": "F2"},
                ],
            },
            runtime_loaded_delayed_memory={
                "abc123": {
                    "id": "abc123",
                    "title": "Architecture",
                    "facts_ids": ["F1", "F2", "F9", "F10"],
                },
            },
            runtime_loaded_delayed_memory_ids=[],
            session_id="session-now",
            timestamp="2026-08-15T00:06:00",
            delayed_memory_file_store_enabled=False,
        )

        result = load_delayed_memory_report(
            context,
            "abc123",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(
            result["report"]["anchor_fact_ids"],
            ["F1"],
        )
        self.assertEqual(
            result["report"]["facts_ids"],
            ["F1", "F2"],
        )
        self.assertEqual(
            result["pruned_fact_ids"],
            ["F9", "F10"],
        )
        self.assertNotIn(
            "long_term_facts_ids",
            result["report"],
        )
        self.assertEqual(
            context.delayed_memory_reports["abc123"]["facts_ids"],
            ["F1", "F2"],
        )
        self.assertEqual(
            context.runtime_loaded_delayed_memory["abc123"]["facts_ids"],
            ["F1", "F2"],
        )


    def test_load_delayed_memory_uses_loaded_context_block(self):

        Emitter = FakeEmitter

        Context = FakeContext

        context = Context()
        context.emitter = Emitter()
        context.runtime_action_events = []
        context.runtime_search_calls = []
        context.runtime_loaded_skills = []
        context.runtime_asset_results = []
        context.delayed_memory_reports = {
            "a1b2c3": {
                "title": "Русский отчёт",
                "summary": "Summary",
                "tags": [
                    "tag",
                ],
                "body": "Body",
                "long_term_facts_ids": [
                    "14_1dbac3ba8724",
                ],
                "created_session_id": "session-a",
                "created_time": "2026-08-02T19:51:41.803270",
                "created_date": "2026-08-02T19:51:41.803270",
                "loaded_times": 1,
                "load_streak": 1,
                "last_loaded_date": "2026-08-02T19:57:42.787241",
                "last_loaded_session_id": "session-a",
                "all_loaded_session_ids": [
                    "session-a",
                ],
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
                        name="LOAD_DELAYED_MEMORY",
                        payload="a1b2c3",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            1,
        )
        tool_results = build_tool_results_context(
            context
        )
        self.assertEqual(
            tool_results,
            "<TOOLS_RESULTS>\n</TOOLS_RESULTS>",
        )
        loaded_context = build_loaded_delayed_memory_context(
            context
        )
        self.assertIn(
            "<LOADED_DELAYED_MEMORY>",
            loaded_context,
        )
        self.assertIn(
            '"id": "a1b2c3"',
            loaded_context,
        )
        self.assertLess(
            loaded_context.index(
                '"id": "a1b2c3"',
            ),
            loaded_context.index(
                '"title":',
            ),
        )
        for metadata_key in (
            "long_term_facts_ids",
            "created_session_id",
            "created_time",
            "created_date",
            "loaded_times",
            "load_streak",
            "last_loaded_date",
            "last_loaded_session_id",
            "all_loaded_session_ids",
        ):
            self.assertNotIn(
                metadata_key,
                loaded_context,
            )
        self.assertEqual(
            context.emitter.events[0]["text"],
            (
                "Loading: "
                + context.delayed_memory_reports[
                    "a1b2c3"
                ]["title"]
            ),
        )
        self.assertEqual(
            len(context.emitter.events),
            1,
        )
        self.assertEqual(
            context.runtime_session_action_history[0]["text"],
            (
                "Delayed memory loaded: "
                + context.delayed_memory_reports[
                    "a1b2c3"
                ]["title"]
            ),
        )


    def test_started_load_delayed_memory_events_are_report_scoped(self):

        context = SimpleNamespace(
            emitter=FakeEmitter(),
            delayed_memory_reports={
                "a1b2c3": {
                    "title": "First report",
                    "summary": "Summary",
                    "body": "Body",
                },
                "b2c3d4": {
                    "title": "Second report",
                    "summary": "Summary",
                    "body": "Body",
                },
            },
            runtime_active_action_markers=[],
            runtime_current_turn_id="turn_000001",
        )
        runtime_stream = RuntimeStream.__new__(
            RuntimeStream
        )
        runtime_stream.context = context
        runtime_stream.context_snapshot = {}
        runtime_stream.stream = SimpleNamespace(
            message_id="message_000001",
        )
        runtime_stream.started_delayed_memory_action_ids = []
        runtime_stream.jin_color_action_id = ""

        asyncio.run(
            runtime_stream.emit_started_runtime_actions((
                RuntimeActionCall(
                    name="LOAD_DELAYED_MEMORY",
                    payload="a1b2c3",
                ),
                RuntimeActionCall(
                    name="LOAD_DELAYED_MEMORY",
                    payload="b2c3d4",
                ),
            ))
        )

        self.assertEqual(
            [
                (
                    event["id"],
                    event["text"],
                    event["delayed_memory_report_id"],
                    event["delayed_memory_report"]["title"],
                )
                for event in context.emitter.events
            ],
            [
                (
                    "a1b2c3",
                    "LOAD_DELAYED_MEMORY: First report",
                    "a1b2c3",
                    "First report",
                ),
                (
                    "b2c3d4",
                    "LOAD_DELAYED_MEMORY: Second report",
                    "b2c3d4",
                    "Second report",
                ),
            ],
        )


    def test_load_delayed_memory_keeps_multiple_reports(self):

        Emitter = FakeEmitter

        Context = FakeContext

        context = Context()
        context.emitter = Emitter()
        context.runtime_action_events = []
        context.runtime_search_calls = []
        context.runtime_loaded_skills = []
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
                        name="LOAD_DELAYED_MEMORY",
                        payload="a1b2c3",
                    ),
                    RuntimeActionCall(
                        name="LOAD_DELAYED_MEMORY",
                        payload="a1b2c3",
                    ),
                    RuntimeActionCall(
                        name="LOAD_DELAYED_MEMORY",
                        payload="b2c3d4",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            2,
        )
        self.assertEqual(
            set(
                context.runtime_loaded_delayed_memory
            ),
            {
                "a1b2c3",
                "b2c3d4",
            },
        )

        loaded_context = build_loaded_delayed_memory_context(
            context
        )
        self.assertEqual(
            loaded_context.count(
                "<LOADED_DELAYED_MEMORY>"
            ),
            2,
        )
        self.assertRegex(
            loaded_context,
            r'"title": "First report \( \d+s ago \)"',
        )
        self.assertRegex(
            loaded_context,
            r'"title": "Second report \( \d+s ago \)"',
        )

        tool_results = build_tool_results_context(
            context
        )
        self.assertNotIn(
            "<TOOL_RESULTS type='delayed_memory'>",
            tool_results,
        )
        self.assertNotIn(
            "<LOADED_DELAYED_MEMORY>",
            tool_results,
        )
        self.assertEqual(
            [
                item["text"]
                for item in context.runtime_session_action_history
            ],
            [
                "Delayed memory loaded: First report",
                "Delayed memory loaded: Second report",
            ],
        )
        self.assertEqual(
            [
                (
                    event["id"],
                    event["text"],
                    event["delayed_memory_report_id"],
                    event["delayed_memory_report"]["title"],
                )
                for event in context.emitter.events
            ],
            [
                (
                    "a1b2c3",
                    "Loading: First report",
                    "a1b2c3",
                    "First report",
                ),
                (
                    "b2c3d4",
                    "Loading: Second report",
                    "b2c3d4",
                    "Second report",
                ),
            ],
        )


    def test_invalid_load_delayed_memory_id_returns_failure_tool_result(self):

        Emitter = FakeEmitter

        Context = FakeContext

        context = Context()
        context.emitter = Emitter()
        context.runtime_action_events = []
        context.runtime_search_calls = []
        context.runtime_loaded_skills = []
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
                        name="LOAD_DELAYED_MEMORY",
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
            '<TOOL_RESULT name="LOAD_DELAYED_MEMORY"',
            tool_results,
        )
        self.assertIn(
            "No entries found.",
            tool_results,
        )


    def test_load_delayed_memory_tracks_session_metadata(self):

        Emitter = FakeEmitter

        Context = FakeContext

        context = Context()
        context.emitter = Emitter()
        context.session_id = "session-a"
        context.timestamp = "2026-07-17T19:40:00+03:00"
        context.runtime_action_events = []
        context.runtime_search_calls = []
        context.runtime_loaded_skills = []
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
                        name="LOAD_DELAYED_MEMORY",
                        payload="a1b2c3",
                    ),
                    RuntimeActionCall(
                        name="LOAD_DELAYED_MEMORY",
                        payload="a1b2c3",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            1,
        )
        report = context.delayed_memory_reports["a1b2c3"]
        self.assertEqual(
            report["loaded_times"],
            1,
        )
        self.assertEqual(
            report["load_streak"],
            1,
        )
        self.assertEqual(
            report["created_date"],
            "2026-07-16T10:00:00+03:00",
        )
        self.assertEqual(
            report["last_loaded_date"],
            "2026-07-17T19:40:00+03:00",
        )
        self.assertEqual(
            report["last_loaded_session_id"],
            "session-a",
        )
        self.assertEqual(
            report["all_loaded_session_ids"],
            [
                "session-a",
            ],
        )
        self.assertEqual(
            context.runtime_loaded_delayed_memory_ids,
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
        next_context.runtime_loaded_skills = []
        next_context.runtime_asset_results = []
        next_context.delayed_memory_reports = (
            context.delayed_memory_reports
        )

        asyncio.run(
            apply_runtime_action_calls(
                next_context,
                (
                    RuntimeActionCall(
                        name="LOAD_DELAYED_MEMORY",
                        payload="a1b2c3",
                    ),
                ),
            )
        )

        report = next_context.delayed_memory_reports["a1b2c3"]
        self.assertEqual(
            report["loaded_times"],
            2,
        )
        self.assertEqual(
            report["load_streak"],
            2,
        )
        self.assertEqual(
            report["last_loaded_session_id"],
            "session-b",
        )
        self.assertEqual(
            report["all_loaded_session_ids"],
            [
                "session-a",
                "session-b",
            ],
        )


    def test_unload_delayed_memory_only_detaches_from_context(self):

        Emitter = FakeEmitter

        Context = FakeContext

        context = Context()
        context.emitter = Emitter()
        context.runtime_action_events = []
        context.runtime_search_calls = []
        context.runtime_loaded_skills = []
        context.runtime_asset_results = []
        context.runtime_loaded_delayed_memory = {
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
                        name="UNLOAD_DELAYED_MEMORY",
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
            context.runtime_loaded_delayed_memory,
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
            "Unloading: Pinned report",
        )
        self.assertEqual(
            context.runtime_session_action_history[0]["text"],
            "Delayed memory unloaded from context: Pinned report",
        )


    def test_unload_delayed_memory_detaches_multiple_reports(self):

        Emitter = FakeEmitter

        Context = FakeContext

        context = Context()
        context.emitter = Emitter()
        context.runtime_action_events = []
        context.runtime_search_calls = []
        context.runtime_loaded_skills = []
        context.runtime_asset_results = []
        context.runtime_loaded_delayed_memory = {
            "a1b2c3": {
                "id": "a1b2c3",
                "title": "First report",
            },
            "b2c3d4": {
                "id": "b2c3d4",
                "title": "Second report",
            },
            "c3d4e5": {
                "id": "c3d4e5",
                "title": "Third report",
            },
        }
        context.runtime_loaded_delayed_memory_ids = [
            "a1b2c3",
            "b2c3d4",
            "c3d4e5",
        ]
        context.delayed_memory_reports = {
            "a1b2c3": {
                "title": "First report",
            },
            "b2c3d4": {
                "title": "Second report",
            },
            "c3d4e5": {
                "title": "Third report",
            },
        }

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="UNLOAD_DELAYED_MEMORY",
                        payload="a1b2c3",
                    ),
                    RuntimeActionCall(
                        name="UNLOAD_DELAYED_MEMORY",
                        payload="b2c3d4",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            2,
        )
        self.assertEqual(
            set(
                context.runtime_loaded_delayed_memory
            ),
            {
                "c3d4e5",
            },
        )
        self.assertEqual(
            context.runtime_loaded_delayed_memory_ids,
            [
                "c3d4e5",
            ],
        )
        self.assertEqual(
            set(
                context.delayed_memory_reports
            ),
            {
                "a1b2c3",
                "b2c3d4",
                "c3d4e5",
            },
        )
        self.assertEqual(
            [
                event["text"]
                for event in context.emitter.events
            ],
            [
                "Unloading: First report",
                "Unloading: Second report",
            ],
        )



    def test_invalid_unload_delayed_memory_id_returns_failed_result(self):

        Emitter = FakeEmitter

        Context = FakeContext

        context = Context()
        context.emitter = Emitter()
        context.runtime_action_events = []
        context.runtime_search_calls = []
        context.runtime_loaded_skills = []
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
            "<UNLOAD_DELAYED_MEMORY: Test report (summary check)>",
            enabled_actions=(
                "UNLOAD_DELAYED_MEMORY",
            ),
        )

        self.assertEqual(
            extracted.actions,
            (
                RuntimeActionCall(
                    name="UNLOAD_DELAYED_MEMORY",
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
            '<TOOL_RESULT name="UNLOAD_DELAYED_MEMORY"',
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


    def test_missing_unload_delayed_memory_id_returns_failed_result(self):

        Emitter = FakeEmitter

        Context = FakeContext

        context = Context()
        context.emitter = Emitter()
        context.runtime_action_events = []
        context.runtime_search_calls = []
        context.runtime_loaded_skills = []
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
                        name="UNLOAD_DELAYED_MEMORY",
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
            '<TOOL_RESULT name="UNLOAD_DELAYED_MEMORY"',
            tool_results,
        )
        self.assertIn(
            "No entries found.",
            tool_results,
        )

    def test_pinned_delayed_memory_is_included_once_per_turn(self):

        context = SimpleNamespace(
            delayed_memory_reports={
                "a1b2c3": {
                    "title": "Pinned context",
                    "summary": "Summary",
                    "tags": [],
                    "body": "Pinned body",
                    "pinned": True,
                },
            },
            runtime_loaded_delayed_memory={},
            runtime_current_turn_id="turn-1",
            runtime_pinned_delayed_memory_turns={},
            session_id="session-1",
            timestamp="2026-08-02T20:00:00",
            delayed_memory_file_store_enabled=False,
        )

        first = include_pinned_delayed_memory_reports(context)
        second = include_pinned_delayed_memory_reports(context)

        self.assertIn("a1b2c3", first)
        self.assertIn("a1b2c3", second)
        self.assertEqual(
            context.delayed_memory_reports["a1b2c3"]["loaded_times"],
            1,
        )

        context.runtime_current_turn_id = "turn-2"
        context.timestamp = "2026-08-02T20:01:00"
        include_pinned_delayed_memory_reports(context)

        self.assertEqual(
            context.delayed_memory_reports["a1b2c3"]["loaded_times"],
            2,
        )
        self.assertEqual(
            context.delayed_memory_reports["a1b2c3"]["last_loaded_date"],
            "2026-08-02T20:01:00",
        )


    def test_remove_pinned_delayed_memory_returns_failed_result(self):

        context = FakeContext()
        context.emitter = FakeEmitter()
        context.runtime_action_events = []
        context.runtime_search_calls = []
        context.runtime_loaded_skills = []
        context.runtime_asset_results = []
        context.runtime_delayed_memory_results = []
        context.runtime_loaded_delayed_memory = {
            "a1b2c3": {
                "id": "a1b2c3",
                "title": "Pinned report",
                "pinned": True,
            },
        }
        context.delayed_memory_reports = {
            "a1b2c3": {
                "title": "Pinned report",
                "summary": "Summary",
                "tags": [],
                "body": "Body",
                "pinned": True,
            },
        }

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="UNLOAD_DELAYED_MEMORY",
                        payload="a1b2c3",
                    ),
                ),
            )
        )

        self.assertEqual(applied_count, 1)
        self.assertEqual(
            context.emitter.events[0]["status"],
            "failed",
        )
        self.assertEqual(
            context.runtime_delayed_memory_results[0]["error"],
            "delayed_memory_pinned",
        )
        self.assertIn(
            "a1b2c3",
            context.runtime_loaded_delayed_memory,
        )
