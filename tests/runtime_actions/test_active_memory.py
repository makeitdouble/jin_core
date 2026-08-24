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
    parse_delayed_memory_payload,
)
from utils.assets_utils import run_asset_action
from utils.brain_client_utils import (
    record_delayed_memory_runtime_result,
    flush_pending_active_memory_resolve_failure_history,
    update_active_memory_runtime_record,
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



class RuntimeActiveMemoryTests(RuntimeActionTestCase):

    def test_extracts_bracketed_save_active_memory_marker(self):

        result = extract_runtime_actions(
            (
                "before "
                "<SAVE_ACTIVE_MEMORY>remind later | tomorrow | coffee</SAVE_ACTIVE_MEMORY>"
                " after"
            ),
            enabled_actions=[
                "CAN_SAVE_ACTIVE_MEMORY",
            ],
        )

        self.assertEqual(
            result.text,
            "before after",
        )
        self.assertEqual(
            result.count("SAVE_ACTIVE_MEMORY"),
            1,
        )
        self.assertEqual(
            result.actions[0].payload,
            "remind later | tomorrow | coffee",
        )


    def test_rejects_internal_action_save_active_memory_marker(self):

        text = (
            "before "
            "<INTERNAL_ACTION_SAVE_ACTIVE_MEMORY:remind later>"
            " after"
        )

        result = extract_runtime_actions(
            text,
            enabled_actions=[
                "CAN_SAVE_ACTIVE_MEMORY",
            ],
        )

        self.assertEqual(
            result.text,
            text,
        )
        self.assertEqual(
            result.actions,
            (),
        )


    def test_extracts_save_active_memory_marker_body(self):

        result = extract_runtime_actions(
            (
                "before "
                "<SAVE_ACTIVE_MEMORY>remember the word coffee "
                "and ask for a guess later.</SAVE_ACTIVE_MEMORY>"
                " after"
            ),
            enabled_actions=[
                "CAN_SAVE_ACTIVE_MEMORY",
            ],
        )

        self.assertEqual(
            result.text,
            "before after",
        )
        self.assertEqual(
            result.actions,
            (
                RuntimeActionCall(
                    name="SAVE_ACTIVE_MEMORY",
                    payload=(
                        "remember the word coffee "
                        "and ask for a guess later."
                    ),
                ),
            ),
        )


    def test_bare_save_active_memory_marker_line_stays_text(self):

        text = (
            "Я напомню.\n\n"
            "SAVE_ACTIVE_MEMORY: "
            "REMINDER: Drink coffee in 5 minutes\n"
        )
        result = extract_runtime_actions(
            text,
            enabled_actions=[
                "CAN_SAVE_ACTIVE_MEMORY",
            ],
        )

        self.assertEqual(result.text, text)
        self.assertEqual(result.actions, ())
        self.assertEqual(result.removed_markers, ())

    def test_save_active_memory_marker_helpers_use_conditions_placeholder(self):

        self.assertEqual(
            get_save_active_memory_marker_fields(),
            (
                "conditions",
            ),
        )
        self.assertEqual(
            get_save_active_memory_placeholder_payload(),
            "CONDITIONS",
        )


    def test_bare_resolve_active_memory_marker_stays_text(self):

        text = (
            "RESOLVE_ACTIVE_MEMORY: "
            "active_memory_id=e2qxe7 STATUS=resolved\n"
            "\n"
            "Память очищена."
        )
        result = extract_runtime_actions(
            text,
            enabled_actions=[
                "CAN_SAVE_ACTIVE_MEMORY",
            ],
        )

        self.assertEqual(result.text, text)
        self.assertEqual(result.actions, ())
        self.assertEqual(result.removed_markers, ())

    def test_extracts_bracketed_resolve_active_memory_marker(self):

        result = extract_runtime_actions(
            (
                "before "
                "<RESOLVE_ACTIVE_MEMORY:e2qxe7 | resolved>"
                " after"
            ),
            enabled_actions=[
                "CAN_SAVE_ACTIVE_MEMORY",
            ],
        )

        self.assertEqual(
            result.text,
            "before after",
        )
        self.assertEqual(
            result.count("RESOLVE_ACTIVE_MEMORY"),
            1,
        )
        self.assertEqual(
            result.actions[0].payload,
            "e2qxe7 | resolved",
        )


    def test_extract_active_memory_resolve_slot_id_accepts_loose_payload_shape(self):

        self.assertEqual(
            extract_active_memory_resolve_slot_id(
                "active_memory_id: 5fdg4g",
            ),
            "5fdg4g",
        )
        self.assertEqual(
            extract_active_memory_resolve_slot_id(
                "resolve slot 5fdg4g please",
                existing_ids={
                    "5fdg4g",
                },
            ),
            "5fdg4g",
        )


    def test_extract_active_memory_resolve_slot_id_skips_non_existing_tokens(self):

        self.assertEqual(
            extract_active_memory_resolve_slot_id(
                "active_memory_id | STATUS",
                existing_ids={
                    "5fdg4g",
                },
            ),
            "",
        )
        self.assertEqual(
            extract_active_memory_resolve_slot_id(
                "resolve status abc123",
                existing_ids={
                    "5fdg4g",
                },
            ),
            "",
        )


    def test_ignores_placeholder_save_active_memory_marker(self):

        result = extract_runtime_actions(
            "<SAVE_ACTIVE_MEMORY> CONDITIONS </SAVE_ACTIVE_MEMORY>",
            enabled_actions=[
                "CAN_SAVE_ACTIVE_MEMORY",
            ],
        )

        self.assertEqual(
            result.text,
            "",
        )
        self.assertEqual(
            result.count("SAVE_ACTIVE_MEMORY"),
            0,
        )


    def test_stream_filter_handles_split_active_memory_block(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_SAVE_ACTIVE_MEMORY",
            ],
        )

        first = stream_filter.filter(
            "<SAVE_ACTIVE_MEMORY>"
        )
        middle = stream_filter.filter(
            "remember the word coffee and ask for a guess later."
        )
        final = stream_filter.filter(
            "</SAVE_ACTIVE_MEMORY>"
        )

        self.assertEqual(
            first.text,
            "",
        )
        self.assertEqual(
            middle.text,
            "",
        )
        self.assertEqual(
            final.actions,
            (
                RuntimeActionCall(
                    name="SAVE_ACTIVE_MEMORY",
                    payload=(
                        "remember the word coffee "
                        "and ask for a guess later."
                    ),
                ),
            ),
        )
        self.assertEqual(
            stream_filter.flush(),
            "",
        )


    def test_stream_filter_keeps_split_bare_save_active_memory_as_text(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_SAVE_ACTIVE_MEMORY",
            ],
        )

        first = stream_filter.filter("SAVE_ACTIVE_MEMORY:")
        second = stream_filter.filter(
            " REMINDER: Drink coffee in 5 minutes\n"
        )
        flushed = stream_filter.flush()

        self.assertEqual(
            first.text + second.text + flushed,
            (
                "SAVE_ACTIVE_MEMORY: "
                "REMINDER: Drink coffee in 5 minutes\n"
            ),
        )
        self.assertEqual(first.actions, ())
        self.assertEqual(second.actions, ())

    def test_apply_runtime_action_calls_records_save_active_memory(self):

        Context = FakeContext

        context = Context()

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="SAVE_ACTIVE_MEMORY",
                        payload="remind later",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            1,
        )
        self.assertEqual(
            context.runtime_action_events,
            [
                {
                    "id": "save_active_memory_001",
                    "name": "save_active_memory",
                    "payload": "remind later",
                }
            ],
        )


    def test_apply_runtime_action_calls_emits_save_active_memory_bubble(self):

        Emitter = FakeEmitter

        Context = FakeContext

        context = Context()
        context.emitter = Emitter()
        context.timestamp = "2026-06-20T10:00:00"
        context.session_id = "test-session"
        context.turn_number = 3

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="SAVE_ACTIVE_MEMORY",
                        payload="remind later",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            1,
        )
        self.assertEqual(
            len(context.emitter.events),
            2,
        )
        self.assertEqual(
            context.emitter.events[0]["type"],
            "runtime_action",
        )
        self.assertEqual(
            context.emitter.events[0]["action"],
            "save_active_memory",
        )
        self.assertEqual(
            context.emitter.events[0]["text"],
            "SAVE_ACTIVE_MEMORY: remind later",
        )
        self.assertEqual(
            context.emitter.events[0]["display_name"],
            "SAVE_ACTIVE_MEMORY",
        )
        self.assertTrue(
            context.emitter.events[0]["close_tag"],
        )
        self.assertEqual(
            len(context.active_memory_records),
            1,
        )
        self.assertRegex(
            context.active_memory_records[0],
            (
                r"^active_memory_1: remind later "
                r"\[ active_memory_id: [a-z0-9]{6} \] "
                r"\[ conditions: remind later \] "
                r"\[ creation_time: 2026-06-20T10:00:00 \] "
                r"\[ created_session_id: test-session \] "
                r"\[ created_jin_message_number: 3 \] "
                r"\[ elapsed_time: 00:00:00 \] "
                r"\[ elapsed_jin_message_number: 0 \] "
                r"\[ status: pending \]$"
            ),
        )
        self.assertEqual(
            context.emitter.events[0]["active_memory"],
            context.active_memory_records[0],
        )
        self.assertEqual(
            context.emitter.events[0]["id"],
            "save_active_memory_001",
        )
        self.assertRegex(
            context.emitter.events[0]["active_memory_id"],
            r"^[a-z0-9]{6}$",
        )
        self.assertEqual(
            context.emitter.events[1],
            {
                "type": "runtime_action",
                "action": "save_active_memory",
                "id": "save_active_memory_001",
                "status": "completed",
                "display_name": "SAVE_ACTIVE_MEMORY",
                "close_tag": True,
                "active_memory_id": (
                    context.emitter.events[0]["active_memory_id"]
                ),
                "active_memory": context.active_memory_records[0],
            },
        )

        tool_results = build_tool_results_context(
            context
        )
        self.assertIn(
            '<TOOL_RESULT name="SAVE_ACTIVE_MEMORY"',
            tool_results,
        )
        self.assertIn(
            "active_memory_records -&gt; &lt;ACTIVE_MEMORY&gt;",
            tool_results,
        )
        self.assertIn(
            "remind later",
            tool_results,
        )
        self.assertIn(
            "active_memory_1:",
            tool_results,
        )

    def test_apply_runtime_action_calls_emits_one_bubble_per_saved_active_memory(self):

        Emitter = FakeEmitter

        Context = FakeContext

        context = Context()
        context.emitter = Emitter()
        context.timestamp = "2026-06-20T10:00:00"
        context.session_id = "test-session"
        context.turn_number = 3

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="SAVE_ACTIVE_MEMORY",
                        payload="first reminder",
                    ),
                    RuntimeActionCall(
                        name="SAVE_ACTIVE_MEMORY",
                        payload="second reminder",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            2,
        )
        self.assertEqual(
            len(context.active_memory_records),
            2,
        )
        self.assertEqual(
            [
                event.get("id")
                for event in context.emitter.events
            ],
            [
                "save_active_memory_001",
                "save_active_memory_001",
                "save_active_memory_002",
                "save_active_memory_002",
            ],
        )
        self.assertEqual(
            [
                event.get("text")
                for event in context.emitter.events
                if not event.get("status")
            ],
            [
                "SAVE_ACTIVE_MEMORY: first reminder",
                "SAVE_ACTIVE_MEMORY: second reminder",
            ],
        )
        self.assertEqual(
            len({
                event["active_memory_id"]
                for event in context.emitter.events
                if event.get("active_memory_id")
            }),
            2,
        )
        self.assertEqual(
            [
                event.get("id")
                for event in context.runtime_action_events
            ],
            [
                "save_active_memory_001",
                "save_active_memory_002",
            ],
        )


    def test_save_active_memory_replaces_model_runtime_suffixes(self):

        Emitter = FakeEmitter

        Context = FakeContext

        context = Context()
        context.emitter = Emitter()
        context.timestamp = "2026-07-13T00:12:00"
        context.session_id = "runtime-session"
        context.turn_number = 8

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="SAVE_ACTIVE_MEMORY",
                        payload=(
                            "Experiment Progress: 2m elapsed "
                            "[ active_memory_id: progress_marker_1 ] "
                            "[ conditions: stale condition ] "
                            "[ creation_time: 1999-01-01T00:00:00 ] "
                            "[ created_session_id: model-session ] "
                            "[ created_jin_message_number: 999 ] "
                            "[ elapsed_time: 99:99:99 ] "
                            "[ elapsed_jin_message_number: 999 ] "
                            "[ status: resolved ]"
                        ),
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            1,
        )
        self.assertEqual(
            context.emitter.events[0]["text"],
            "SAVE_ACTIVE_MEMORY: Experiment Progress: 2m elapsed",
        )
        self.assertEqual(
            context.runtime_action_events[0]["payload"],
            "Experiment Progress: 2m elapsed",
        )

        active_memory = context.active_memory_records[0]

        self.assertRegex(
            active_memory,
            (
                r"^active_memory_1: Experiment Progress: 2m elapsed "
                r"\[ active_memory_id: [a-z0-9]{6} \] "
                r"\[ conditions: Experiment Progress: 2m elapsed \] "
                r"\[ creation_time: 2026-07-13T00:12:00 \] "
                r"\[ created_session_id: runtime-session \] "
                r"\[ created_jin_message_number: 8 \] "
                r"\[ elapsed_time: 00:00:00 \] "
                r"\[ elapsed_jin_message_number: 0 \] "
                r"\[ status: pending \]$"
            ),
        )
        self.assertNotIn(
            "progress_marker_1",
            active_memory,
        )
        self.assertNotIn(
            "stale condition",
            active_memory,
        )
        self.assertNotIn(
            "model-session",
            active_memory,
        )
        self.assertNotIn(
            "99:99:99",
            active_memory,
        )


    def test_extracts_update_active_memory_block_from_active_memory_capability(self):

        result = extract_runtime_actions(
            (
                "before "
                "<UPDATE_ACTIVE_MEMORY: abc123>\n"
                "last_photo_id: def456\n"
                "current_photo_count: 2\n"
                "</UPDATE_ACTIVE_MEMORY>"
                " after"
            ),
            enabled_actions=[
                "CAN_SAVE_ACTIVE_MEMORY",
            ],
        )

        self.assertEqual(result.text, "before after")
        self.assertEqual(
            result.actions,
            (
                RuntimeActionCall(
                    name="UPDATE_ACTIVE_MEMORY",
                    payload=(
                        "abc123\n"
                        "last_photo_id: def456\n"
                        "current_photo_count: 2"
                    ),
                ),
            ),
        )


    def test_extracts_update_active_memory_json_block_from_active_memory_capability(self):

        result = extract_runtime_actions(
            (
                "before "
                "<UPDATE_ACTIVE_MEMORY>\n"
                "{\"active_memory_id\":\"abc123\",\"fields\":{"
                "\"last_photo_id\":\"def456\","
                "\"current_photo_count\":\"2\""
                "}}\n"
                "</UPDATE_ACTIVE_MEMORY>"
                " after"
            ),
            enabled_actions=[
                "CAN_SAVE_ACTIVE_MEMORY",
            ],
        )

        self.assertEqual(result.text, "before after")
        self.assertEqual(
            result.actions,
            (
                RuntimeActionCall(
                    name="UPDATE_ACTIVE_MEMORY",
                    payload=(
                        "{\"active_memory_id\":\"abc123\",\"fields\":{"
                        "\"last_photo_id\":\"def456\","
                        "\"current_photo_count\":\"2\""
                        "}}"
                    ),
                ),
            ),
        )


    def test_extracts_update_active_memory_self_closing_attribute_marker(self):

        marker = (
            '<UPDATE_ACTIVE_MEMORY active_memory_id="abc123" '
            'last_update="23 august" current_photos=2 '
            'last_photo_id="def456" />'
        )

        result = extract_runtime_actions(
            (
                "before "
                + marker
                + " after"
            ),
            enabled_actions=[
                "CAN_SAVE_ACTIVE_MEMORY",
            ],
        )

        self.assertEqual(result.text, "before after")
        self.assertEqual(
            result.actions,
            (
                RuntimeActionCall(
                    name="UPDATE_ACTIVE_MEMORY",
                    payload=(
                        'active_memory_id="abc123" '
                        'last_update="23 august" current_photos=2 '
                        'last_photo_id="def456"'
                    ),
                ),
            ),
        )
        self.assertEqual(
            result.removed_markers,
            (
                marker,
            ),
        )


    def test_save_active_memory_materializes_hidden_custom_state_fields(self):

        context = FakeContext()
        context.emitter = FakeEmitter()
        context.timestamp = "2026-08-18T23:25:00"
        context.session_id = "state-session"
        context.turn_number = 11

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="SAVE_ACTIVE_MEMORY",
                        payload=(
                            "Once a day ask for a photo. "
                            "(last_photo_id: qamzck) "
                            "(current_photo_count: 1)"
                        ),
                    ),
                ),
            )
        )

        self.assertEqual(applied_count, 1)
        self.assertEqual(len(context.active_memory_records), 1)
        record = context.active_memory_records[0]
        self.assertIn(
            "active_memory_1: Once a day ask for a photo.",
            record,
        )
        self.assertIn("[ last_photo_id: qamzck ]", record)
        self.assertIn("[ current_photo_count: 1 ]", record)
        self.assertNotIn("(last_photo_id:", record)
        self.assertNotIn("(current_photo_count:", record)
        self.assertEqual(
            context.emitter.events[0]["text"],
            "SAVE_ACTIVE_MEMORY: Once a day ask for a photo.",
        )
        self.assertEqual(
            context.emitter.events[0]["payload"],
            "Once a day ask for a photo.",
        )


    def test_update_active_memory_changes_only_fixed_fields_and_adds_updated_at(self):

        context = FakeContext()
        context.emitter = FakeEmitter()
        context.timestamp = "2026-08-18T23:25:00"
        context.session_id = "state-session"
        context.turn_number = 11

        asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="SAVE_ACTIVE_MEMORY",
                        payload=(
                            "Once a day ask for a photo. "
                            "(last_photo_id: qamzck) "
                            "(current_photo_count: 1)"
                        ),
                    ),
                ),
            )
        )
        active_memory_id = context.emitter.events[0]["active_memory_id"]
        context.emitter.events.clear()
        context.timestamp = "2026-08-18T23:26:00"

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="UPDATE_ACTIVE_MEMORY",
                        payload=(
                            f"{active_memory_id}\n"
                            "last_photo_id: def456\n"
                            "current_photo_count: 2"
                        ),
                    ),
                ),
            )
        )

        self.assertEqual(applied_count, 1)
        record = context.active_memory_records[0]
        self.assertIn("[ last_photo_id: def456 ]", record)
        self.assertIn("[ current_photo_count: 2 ]", record)
        self.assertIn(
            "[ updated_at: 2026-08-18T23:26:00 ]",
            record,
        )
        event = context.emitter.events[0]
        self.assertEqual(event["action"], "update_active_memory")
        self.assertEqual(event["status"], "completed")
        self.assertEqual(
            event["text"],
            "UPDATE_ACTIVE_MEMORY: Once a day ask for a photo.",
        )
        self.assertEqual(
            event["active_memory_changes"],
            [
                {
                    "field": "last_photo_id",
                    "before": "qamzck",
                    "after": "def456",
                },
                {
                    "field": "current_photo_count",
                    "before": "1",
                    "after": "2",
                },
            ],
        )


    def test_update_active_memory_accepts_numbered_slot_key_reference(self):

        context = FakeContext()
        context.emitter = FakeEmitter()
        context.timestamp = "2026-08-18T23:25:00"
        context.session_id = "state-session"
        context.turn_number = 11

        asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="SAVE_ACTIVE_MEMORY",
                        payload=(
                            "Once a day ask for a photo. "
                            "(last_photo_id: qamzck) "
                            "(current_photo_count: 1)"
                        ),
                    ),
                ),
            )
        )
        active_memory_id = context.emitter.events[0]["active_memory_id"]
        context.emitter.events.clear()
        context.timestamp = "2026-08-18T23:26:00"

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="UPDATE_ACTIVE_MEMORY",
                        payload=(
                            "active_memory_1\n"
                            "last_photo_id: def456\n"
                            "current_photo_count: 2"
                        ),
                    ),
                ),
            )
        )

        self.assertEqual(applied_count, 1)
        record = context.active_memory_records[0]
        self.assertIn("[ last_photo_id: def456 ]", record)
        self.assertIn("[ current_photo_count: 2 ]", record)
        event = context.emitter.events[0]
        self.assertEqual(event["status"], "completed")
        self.assertEqual(event["active_memory_id"], active_memory_id)
        self.assertEqual(
            event["active_memory_result"]["requested_id"],
            "active_memory_1",
        )
        self.assertEqual(
            event["active_memory_result"]["id"],
            active_memory_id,
        )


    def test_update_active_memory_accepts_numbered_slot_key_inside_raw_marker(self):

        context = FakeContext()
        context.emitter = FakeEmitter()
        context.timestamp = "2026-08-18T23:25:00"
        context.session_id = "state-session"
        context.turn_number = 11

        asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="SAVE_ACTIVE_MEMORY",
                        payload=(
                            "Once a day ask for a photo. "
                            "(last_photo_id: qamzck) "
                            "(current_date: 2026-08-21)"
                        ),
                    ),
                ),
            )
        )
        active_memory_id = context.emitter.events[0]["active_memory_id"]
        context.emitter.events.clear()
        context.timestamp = "2026-08-22T00:00:00"

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="UPDATE_ACTIVE_MEMORY",
                        payload=(
                            "<UPDATE_ACTIVE_MEMORY: active_memory_1>\n"
                            "last_photo_id: 1sot0h\n"
                            "current_date: 2026-08-22\n"
                            "</UPDATE_ACTIVE_MEMORY>"
                        ),
                    ),
                ),
            )
        )

        self.assertEqual(applied_count, 1)
        record = context.active_memory_records[0]
        self.assertIn("[ last_photo_id: 1sot0h ]", record)
        self.assertIn("[ current_date: 2026-08-22 ]", record)
        event = context.emitter.events[0]
        self.assertEqual(event["status"], "completed")
        self.assertEqual(event["active_memory_id"], active_memory_id)
        self.assertEqual(
            event["active_memory_result"]["requested_id"],
            "active_memory_1",
        )
        self.assertEqual(
            event["active_memory_result"]["id"],
            active_memory_id,
        )


    def test_update_active_memory_accepts_json_numbered_slot_key(self):

        context = FakeContext()
        context.emitter = FakeEmitter()
        context.timestamp = "2026-08-18T23:25:00"
        context.session_id = "state-session"
        context.turn_number = 11

        asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="SAVE_ACTIVE_MEMORY",
                        payload=(
                            "Once a day ask for a photo. "
                            "(last_photo_id: qamzck) "
                            "(current_date: 2026-08-21)"
                        ),
                    ),
                ),
            )
        )
        active_memory_id = context.emitter.events[0]["active_memory_id"]
        context.emitter.events.clear()
        context.timestamp = "2026-08-22T00:00:00"

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="UPDATE_ACTIVE_MEMORY",
                        payload=(
                            "{\"active_memory_id\":\"active_memory_1\","
                            "\"fields\":{"
                            "\"last_photo_id\":\"1sot0h\","
                            "\"current_date\":\"2026-08-22\""
                            "}}"
                        ),
                    ),
                ),
            )
        )

        self.assertEqual(applied_count, 1)
        record = context.active_memory_records[0]
        self.assertIn("[ last_photo_id: 1sot0h ]", record)
        self.assertIn("[ current_date: 2026-08-22 ]", record)
        event = context.emitter.events[0]
        self.assertEqual(event["status"], "completed")
        self.assertEqual(event["active_memory_id"], active_memory_id)
        self.assertEqual(
            event["active_memory_result"]["requested_id"],
            "active_memory_1",
        )
        self.assertEqual(
            event["active_memory_result"]["id"],
            active_memory_id,
        )


    def test_update_active_memory_json_fields_ignores_creation_time(self):

        context = FakeContext()
        context.emitter = FakeEmitter()
        context.timestamp = "2026-08-18T23:25:00"
        context.session_id = "state-session"
        context.turn_number = 11

        asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="SAVE_ACTIVE_MEMORY",
                        payload=(
                            "Once a day ask for a photo. "
                            "(current_photo_id: qamzck) "
                            "(current_photo_count: 1)"
                        ),
                    ),
                ),
            )
        )
        context.emitter.events.clear()
        context.timestamp = "2026-08-22T14:55:00"

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="UPDATE_ACTIVE_MEMORY",
                        payload=(
                            "{\"active_memory_id\":\"active_memory_1\","
                            "\"fields\":{"
                            "\"current_photo_id\":\"1sot0h\","
                            "\"current_photo_count\":2,"
                            "\"creation_time\":\"2026-08-22T14:54:17Z\""
                            "}}"
                        ),
                    ),
                ),
            )
        )

        self.assertEqual(applied_count, 1)
        record = context.active_memory_records[0]
        self.assertIn("[ current_photo_id: 1sot0h ]", record)
        self.assertIn("[ current_photo_count: 2 ]", record)
        self.assertNotIn(
            "2026-08-22T14:54:17Z",
            record,
        )
        event = context.emitter.events[0]
        self.assertEqual(event["status"], "completed")
        self.assertEqual(
            event["active_memory_changes"],
            [
                {
                    "field": "current_photo_id",
                    "before": "qamzck",
                    "after": "1sot0h",
                },
                {
                    "field": "current_photo_count",
                    "before": "1",
                    "after": "2",
                },
            ],
        )


    def test_update_active_memory_accepts_json_inside_raw_marker(self):

        context = FakeContext()
        context.emitter = FakeEmitter()
        context.timestamp = "2026-08-18T23:25:00"
        context.session_id = "state-session"
        context.turn_number = 11

        asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="SAVE_ACTIVE_MEMORY",
                        payload=(
                            "Once a day ask for a photo. "
                            "(last_photo_id: qamzck) "
                            "(current_date: 2026-08-21)"
                        ),
                    ),
                ),
            )
        )
        active_memory_id = context.emitter.events[0]["active_memory_id"]
        context.emitter.events.clear()
        context.timestamp = "2026-08-22T00:00:00"

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="UPDATE_ACTIVE_MEMORY",
                        payload=(
                            "<UPDATE_ACTIVE_MEMORY>\n"
                            "{\"active_memory_id\":\"active_memory_1\","
                            "\"fields\":{"
                            "\"last_photo_id\":\"1sot0h\","
                            "\"current_date\":\"2026-08-22\""
                            "}}\n"
                            "</UPDATE_ACTIVE_MEMORY>"
                        ),
                    ),
                ),
            )
        )

        self.assertEqual(applied_count, 1)
        record = context.active_memory_records[0]
        self.assertIn("[ last_photo_id: 1sot0h ]", record)
        self.assertIn("[ current_date: 2026-08-22 ]", record)
        event = context.emitter.events[0]
        self.assertEqual(event["status"], "completed")
        self.assertEqual(event["active_memory_id"], active_memory_id)
        self.assertEqual(
            event["active_memory_result"]["requested_id"],
            "active_memory_1",
        )
        self.assertEqual(
            event["active_memory_result"]["id"],
            active_memory_id,
        )


    def test_update_active_memory_accepts_self_closing_attribute_marker(self):

        context = FakeContext()
        context.emitter = FakeEmitter()
        context.timestamp = "2026-08-23T10:00:00"
        context.session_id = "state-session"
        context.turn_number = 11

        asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="SAVE_ACTIVE_MEMORY",
                        payload=(
                            '{"conditions":"Track workspace photo state.",'
                            '"last_update":"22 august",'
                            '"current_photos":"1",'
                            '"last_photo_id":"qamzck"}'
                        ),
                    ),
                ),
            )
        )
        active_memory_id = context.emitter.events[0]["active_memory_id"]
        context.emitter.events.clear()
        context.timestamp = "2026-08-23T10:01:00"

        result = extract_runtime_actions(
            (
                f'<UPDATE_ACTIVE_MEMORY active_memory_id="{active_memory_id}" '
                'last_update="23 august" current_photos=2 '
                'last_photo_id="8vyf97" />'
            ),
            enabled_actions=[
                "CAN_SAVE_ACTIVE_MEMORY",
            ],
        )
        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                result.actions,
            )
        )

        self.assertEqual(result.text, "")
        self.assertEqual(applied_count, 1)
        record = context.active_memory_records[0]
        self.assertIn("[ last_update: 23 august ]", record)
        self.assertIn("[ current_photos: 2 ]", record)
        self.assertIn("[ last_photo_id: 8vyf97 ]", record)
        self.assertIn(
            "[ updated_at: 2026-08-23T10:01:00 ]",
            record,
        )
        event = context.emitter.events[0]
        self.assertEqual(event["status"], "completed")
        self.assertEqual(event["active_memory_id"], active_memory_id)
        self.assertEqual(
            event["active_memory_changes"],
            [
                {
                    "field": "last_update",
                    "before": "22 august",
                    "after": "23 august",
                },
                {
                    "field": "current_photos",
                    "before": "1",
                    "after": "2",
                },
                {
                    "field": "last_photo_id",
                    "before": "qamzck",
                    "after": "8vyf97",
                },
            ],
        )


    def test_update_active_memory_rejects_new_field_atomically(self):

        context = FakeContext()
        context.emitter = FakeEmitter()
        context.timestamp = "2026-08-18T23:25:00"
        context.session_id = "state-session"
        context.turn_number = 11

        asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="SAVE_ACTIVE_MEMORY",
                        payload=(
                            "Once a day ask for a photo. "
                            "(last_photo_id: qamzck)"
                        ),
                    ),
                ),
            )
        )
        active_memory_id = context.emitter.events[0]["active_memory_id"]
        original_record = context.active_memory_records[0]
        context.emitter.events.clear()
        context.timestamp = "2026-08-18T23:26:00"

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="UPDATE_ACTIVE_MEMORY",
                        payload=(
                            f"{active_memory_id}\n"
                            "last_photo_id: def456\n"
                            "new_field: nope"
                        ),
                    ),
                ),
            )
        )

        self.assertEqual(applied_count, 0)
        self.assertEqual(context.active_memory_records[0], original_record)
        self.assertNotIn("updated_at", context.active_memory_records[0])
        event = context.emitter.events[0]
        self.assertEqual(event["status"], "failed")
        self.assertEqual(
            event["active_memory_result"]["error"],
            "active_memory_field_not_declared",
        )
        self.assertEqual(
            event["active_memory_result"]["unknown_fields"],
            ["new_field"],
        )


    def test_update_active_memory_slot_key_rejects_new_field_atomically(self):

        context = FakeContext()
        context.emitter = FakeEmitter()
        context.timestamp = "2026-08-18T23:25:00"
        context.session_id = "state-session"
        context.turn_number = 11

        asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="SAVE_ACTIVE_MEMORY",
                        payload=(
                            "Once a day ask for a photo. "
                            "(last_photo_id: qamzck)"
                        ),
                    ),
                ),
            )
        )
        original_record = context.active_memory_records[0]
        context.emitter.events.clear()
        context.timestamp = "2026-08-18T23:26:00"

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="UPDATE_ACTIVE_MEMORY",
                        payload=(
                            "active_memory_1\n"
                            "last_photo_id: def456\n"
                            "new_field: nope"
                        ),
                    ),
                ),
            )
        )

        self.assertEqual(applied_count, 0)
        self.assertEqual(context.active_memory_records[0], original_record)
        self.assertNotIn("updated_at", context.active_memory_records[0])
        event = context.emitter.events[0]
        self.assertEqual(event["status"], "failed")
        self.assertEqual(
            event["active_memory_result"]["error"],
            "active_memory_field_not_declared",
        )
        self.assertEqual(
            event["active_memory_result"]["requested_id"],
            "active_memory_1",
        )
        self.assertEqual(
            event["active_memory_result"]["unknown_fields"],
            ["new_field"],
        )


    def test_update_active_memory_slot_key_rejects_runtime_managed_field(self):

        context = FakeContext()
        context.emitter = FakeEmitter()
        context.timestamp = "2026-08-18T23:25:00"
        context.session_id = "state-session"
        context.turn_number = 11

        asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="SAVE_ACTIVE_MEMORY",
                        payload=(
                            "Once a day ask for a photo. "
                            "(last_photo_id: qamzck)"
                        ),
                    ),
                ),
            )
        )
        original_record = context.active_memory_records[0]

        result = asyncio.run(
            update_active_memory_runtime_record(
                context,
                (
                    "active_memory_1\n"
                    "updated_at: 1999-01-01T00:00:00"
                ),
            )
        )

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["error"],
            "invalid_update_active_memory_payload",
        )
        self.assertEqual(
            result["requested_id"],
            "active_memory_1",
        )
        self.assertEqual(context.active_memory_records[0], original_record)
        self.assertNotIn(
            "1999-01-01T00:00:00",
            context.active_memory_records[0],
        )


    def test_update_active_memory_json_rejects_runtime_managed_field(self):

        context = FakeContext()
        context.emitter = FakeEmitter()
        context.timestamp = "2026-08-18T23:25:00"
        context.session_id = "state-session"
        context.turn_number = 11

        asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="SAVE_ACTIVE_MEMORY",
                        payload=(
                            "Once a day ask for a photo. "
                            "(last_photo_id: qamzck)"
                        ),
                    ),
                ),
            )
        )
        original_record = context.active_memory_records[0]

        result = asyncio.run(
            update_active_memory_runtime_record(
                context,
                (
                    "{\"active_memory_id\":\"active_memory_1\","
                    "\"fields\":{"
                    "\"updated_at\":\"1999-01-01T00:00:00\""
                    "}}"
                ),
            )
        )

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["error"],
            "invalid_update_active_memory_payload",
        )
        self.assertEqual(
            result["requested_id"],
            "active_memory_1",
        )
        self.assertEqual(context.active_memory_records[0], original_record)
        self.assertNotIn(
            "1999-01-01T00:00:00",
            context.active_memory_records[0],
        )


    def test_save_active_memory_rejects_more_than_three_custom_fields(self):

        context = FakeContext()
        context.emitter = FakeEmitter()
        context.timestamp = "2026-08-18T23:25:00"
        context.session_id = "state-session"
        context.turn_number = 11

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="SAVE_ACTIVE_MEMORY",
                        payload=(
                            "Track a small state. "
                            "(field_one: 1) "
                            "(field_two: 2) "
                            "(field_three: 3) "
                            "(field_four: 4)"
                        ),
                    ),
                ),
            )
        )

        self.assertEqual(applied_count, 0)
        self.assertEqual(
            getattr(context, "active_memory_records", []),
            [],
        )


    def test_save_active_memory_accepts_flat_json_and_keeps_last_duplicate(self):

        context = FakeContext()
        context.emitter = FakeEmitter()
        context.timestamp = "2026-08-22T15:40:00"
        context.session_id = "flat-json-session"
        context.turn_number = 12

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="SAVE_ACTIVE_MEMORY",
                        payload=(
                            '{"conditions":"Track photo state",'
                            '"current_photo_id":"old",'
                            '"current_photo_id":"1sot0h",'
                            '"current_photo_count":2}'
                        ),
                    ),
                ),
            )
        )

        self.assertEqual(applied_count, 1)
        self.assertEqual(len(context.active_memory_records), 1)
        record = context.active_memory_records[0]
        self.assertIn("Track photo state", record)
        self.assertIn("[ current_photo_id: 1sot0h ]", record)
        self.assertIn("[ current_photo_count: 2 ]", record)
        self.assertNotIn("[ current_photo_id: old ]", record)


    def test_save_active_memory_flat_json_caps_custom_fields_without_dropping_save(self):

        context = FakeContext()
        context.emitter = FakeEmitter()
        context.timestamp = "2026-08-22T15:41:00"
        context.session_id = "flat-json-limit-session"
        context.turn_number = 13

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="SAVE_ACTIVE_MEMORY",
                        payload=(
                            '{"conditions":"Keep the memory",'
                            '"field_one":1,"field_two":2,'
                            '"field_three":3,"field_four":4}'
                        ),
                    ),
                ),
            )
        )

        self.assertEqual(applied_count, 1)
        record = context.active_memory_records[0]
        self.assertIn("Keep the memory", record)
        self.assertIn("[ field_one: 1 ]", record)
        self.assertIn("[ field_three: 3 ]", record)
        self.assertNotIn("[ field_four: 4 ]", record)


    def test_apply_runtime_action_calls_queues_active_memory_record(self):

        Emitter = FakeEmitter

        Context = FakeContext

        context = Context()
        context.emitter = Emitter()
        context.timestamp = "2026-06-24T15:00:00"
        context.session_id = "tab-session"
        context.turn_number = 7
        context.runtime_memory = "session_status: active"
        context.runtime_memory_updates = 0

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="SAVE_ACTIVE_MEMORY",
                        payload="Drink coffee | Trigger in 5 minutes | coffee",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            1,
        )
        self.assertEqual(
            context.runtime_memory_updates,
            0,
        )
        self.assertEqual(
            context.runtime_memory,
            "session_status: active",
        )
        self.assertEqual(
            len(context.active_memory_records),
            1,
        )
        self.assertRegex(
            context.active_memory_records[0],
            (
                r"^active_memory_1: Drink coffee \| Trigger in 5 minutes \| coffee "
                r"\[ active_memory_id: [a-z0-9]{6} \] "
                r"\[ conditions: Drink coffee \| Trigger in 5 minutes \| coffee \] "
                r"\[ creation_time: 2026-06-24T15:00:00 \] "
                r"\[ created_session_id: tab-session \] "
                r"\[ created_jin_message_number: 7 \] "
                r"\[ elapsed_time: 00:00:00 \] "
                r"\[ elapsed_jin_message_number: 0 \] "
                r"\[ status: pending \]$"
            ),
        )
        self.assertEqual(
            context.emitter.events[0]["type"],
            "runtime_action",
        )
        self.assertEqual(
            context.emitter.events[0]["action"],
            "save_active_memory",
        )
        self.assertEqual(
            context.emitter.events[0]["text"],
            "SAVE_ACTIVE_MEMORY: Drink coffee | Trigger in 5 minutes | coffee",
        )
        self.assertEqual(
            context.emitter.events[0]["display_name"],
            "SAVE_ACTIVE_MEMORY",
        )
        self.assertTrue(
            context.emitter.events[0]["close_tag"],
        )
        self.assertEqual(
            context.emitter.events[0]["active_memory"],
            context.active_memory_records[0],
        )


    def test_apply_runtime_action_calls_skips_exact_active_memory_copy(self):

        Emitter = FakeEmitter

        Context = FakeContext

        context = Context()
        context.emitter = Emitter()
        context.runtime_action_events = []
        context.runtime_search_calls = []
        context.runtime_memory = ""
        context.runtime_memory_stable = ""
        context.active_memory_records = [
            (
                "active_memory_1: remember cuckoo "
                "[ active_memory_id: 5fdg4g ] "
                "[ conditions: remember cuckoo ] "
                "[ creation_time: 2026-06-24T15:00:00 ] "
                "[ elapsed_time: 00:00:00 ] "
                "[ status: pending ]"
            ),
        ]

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="SAVE_ACTIVE_MEMORY",
                        payload="remember cuckoo",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            0,
        )
        self.assertEqual(
            len(context.active_memory_records),
            1,
        )
        self.assertEqual(
            context.runtime_action_events,
            [
                {
                    "id": "save_active_memory_001",
                    "name": "save_active_memory",
                    "payload": "remember cuckoo",
                },
            ],
        )
        self.assertEqual(
            context.emitter.events,
            [
                {
                    "type": "runtime_action",
                    "action": "save_active_memory",
                    "id": "save_active_memory_001",
                    "display_name": "SAVE_ACTIVE_MEMORY",
                    "text": "SAVE_ACTIVE_MEMORY: remember cuckoo",
                    "payload": "remember cuckoo",
                    "close_tag": True,
                },
                {
                    "type": "runtime_action",
                    "action": "save_active_memory",
                    "id": "save_active_memory_001",
                    "status": "completed",
                    "display_name": "SAVE_ACTIVE_MEMORY",
                    "close_tag": True,
                },
            ],
        )


    def test_apply_runtime_action_calls_skips_active_memory_copy_from_runtime_memory(self):

        Emitter = FakeEmitter

        Context = FakeContext

        context = Context()
        context.emitter = Emitter()
        context.runtime_action_events = []
        context.runtime_search_calls = []
        context.runtime_memory = (
            "session_status: active\n"
            "active_memory_1: remember cuckoo "
            "[ active_memory_id: 5fdg4g ] "
            "[ conditions: remember cuckoo ] "
            "[ status: pending ]"
        )
        context.runtime_memory_stable = ""
        context.active_memory_records = []

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="SAVE_ACTIVE_MEMORY",
                        payload="remember cuckoo",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            0,
        )
        self.assertEqual(
            context.active_memory_records,
            [],
        )
        self.assertEqual(
            context.runtime_action_events,
            [
                {
                    "id": "save_active_memory_001",
                    "name": "save_active_memory",
                    "payload": "remember cuckoo",
                },
            ],
        )
        self.assertEqual(
            context.emitter.events,
            [
                {
                    "type": "runtime_action",
                    "action": "save_active_memory",
                    "id": "save_active_memory_001",
                    "display_name": "SAVE_ACTIVE_MEMORY",
                    "text": "SAVE_ACTIVE_MEMORY: remember cuckoo",
                    "payload": "remember cuckoo",
                    "close_tag": True,
                },
                {
                    "type": "runtime_action",
                    "action": "save_active_memory",
                    "id": "save_active_memory_001",
                    "status": "completed",
                    "display_name": "SAVE_ACTIVE_MEMORY",
                    "close_tag": True,
                },
            ],
        )


    def test_apply_runtime_action_calls_resolves_active_memory_by_id(self):

        Emitter = FakeEmitter

        Context = FakeContext

        context = Context()
        context.emitter = Emitter()
        context.runtime_memory = (
            "session_status: active\n"
            "active_memory: remember cuckoo [ active_memory_id: 5fdg4g ] "
            "[ status: pending ]\n"
            "user_message: hello"
        )
        context.runtime_memory_stable = context.runtime_memory
        context.active_memory_records = [
            (
                "active_memory_1: remember cuckoo [ active_memory_id: 5fdg4g ] "
                "[ status: pending ]"
            ),
        ]

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="RESOLVE_ACTIVE_MEMORY",
                        payload="active_memory_id: 5fdg4g",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            1,
        )
        self.assertNotIn(
            "active_memory: remember cuckoo",
            context.runtime_memory,
        )
        self.assertNotIn(
            "5fdg4g",
            context.runtime_memory_stable,
        )
        self.assertIn(
            "session_status: active",
            context.runtime_memory,
        )
        self.assertEqual(
            context.active_memory_records,
            [],
        )
        self.assertEqual(
            context.runtime_action_events[0]["id"],
            "5fdg4g",
        )
        self.assertEqual(
            context.runtime_tool_results,
            [
                {
                    "kind": TOOL_RESULT_KIND_ACTIVE_MEMORY,
                    "result": {
                        "ok": True,
                        "action": "resolve_active_memory",
                        "destination": (
                            "active_memory_records -> <ACTIVE_MEMORY> "
                            "(resolved and removed)"
                        ),
                        "id": "5fdg4g",
                        "content": "remember cuckoo",
                        "record": (
                            "active_memory_1: remember cuckoo "
                            "[ active_memory_id: 5fdg4g ] "
                            "[ status: pending ]"
                        ),
                    },
                },
            ],
        )
        tool_results = build_tool_results_context(
            context
        )
        self.assertIn(
            '<TOOL_RESULT name="RESOLVE_ACTIVE_MEMORY"',
            tool_results,
        )
        self.assertIn(
            "remember cuckoo",
            tool_results,
        )
        self.assertIn(
            "active_memory_1:",
            tool_results,
        )
        self.assertIn(
            "5fdg4g",
            tool_results,
        )
        self.assertEqual(
            context.emitter.events,
            [
                {
                    "type": "runtime_action",
                    "action": "resolve_active_memory",
                    "id": "5fdg4g",
                    "display_name": "RESOLVE_ACTIVE_MEMORY",
                    "close_tag": False,
                    "text": "Active memory resolved",
                    "payload": "5fdg4g",
                    "detail": "id: 5fdg4g; content: remember cuckoo",
                },
                {
                    "type": "runtime_action",
                    "action": "resolve_active_memory",
                    "id": "5fdg4g",
                    "status": "completed",
                    "display_name": "RESOLVE_ACTIVE_MEMORY",
                    "close_tag": False,
                    "payload": "5fdg4g",
                    "detail": "id: 5fdg4g; content: remember cuckoo",
                },
            ],
        )


    def test_apply_runtime_action_calls_resolves_multiple_active_memories(self):

        Emitter = FakeEmitter

        Context = FakeContext

        context = Context()
        context.emitter = Emitter()
        context.runtime_memory = (
            "active_memory_1: first [ active_memory_id: one111 ] "
            "[ status: pending ]\n"
            "active_memory_2: second [ active_memory_id: two222 ] "
            "[ status: pending ]\n"
            "active_memory_3: third [ active_memory_id: tri333 ] "
            "[ status: pending ]"
        )
        context.runtime_memory_stable = context.runtime_memory
        context.active_memory_records = context.runtime_memory.splitlines()

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="RESOLVE_ACTIVE_MEMORY",
                        payload="one111",
                    ),
                    RuntimeActionCall(
                        name="RESOLVE_ACTIVE_MEMORY",
                        payload="two222",
                    ),
                    RuntimeActionCall(
                        name="RESOLVE_ACTIVE_MEMORY",
                        payload="tri333",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            3,
        )
        self.assertEqual(
            context.active_memory_records,
            [],
        )
        self.assertNotIn(
            "active_memory_",
            context.runtime_memory,
        )
        self.assertNotIn(
            "active_memory_",
            context.runtime_memory_stable,
        )
        self.assertTrue(
            context.runtime_active_memory_records_dirty,
        )
        self.assertEqual(
            [
                event.get("id")
                for event in context.emitter.events
                if event.get("status") == "completed"
            ],
            [
                "one111",
                "two222",
                "tri333",
            ],
        )
        self.assertEqual(
            [
                event.get("id")
                for event in context.runtime_action_events
            ],
            [
                "one111",
                "two222",
                "tri333",
            ],
        )


    def test_apply_runtime_action_calls_does_not_resolve_paused_active_memory(self):

        Emitter = FakeEmitter

        Context = FakeContext

        context = Context()
        context.emitter = Emitter()
        context.runtime_memory = (
            "session_status: active\n"
            "active_memory_1: respond only in Russian "
            "[ active_memory_id: one111 ] [ status: pending ]\n"
            "active_memory_2: remember cuckoo "
            "[ active_memory_id: two222 ] [ status: paused ]"
        )
        context.runtime_memory_stable = context.runtime_memory
        context.active_memory_records = [
            (
                "active_memory_1: respond only in Russian "
                "[ active_memory_id: one111 ] [ status: pending ]"
            ),
            (
                "active_memory_2: remember cuckoo "
                "[ active_memory_id: two222 ] [ status: paused ]"
            ),
        ]

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="RESOLVE_ACTIVE_MEMORY",
                        payload="active_memory_id: two222",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            0,
        )
        self.assertEqual(
            len(context.active_memory_records),
            2,
        )
        self.assertIn(
            "two222",
            "\n".join(context.active_memory_records),
        )
        self.assertIn(
            "two222",
            context.runtime_memory,
        )
        self.assertEqual(
            len(context.emitter.events),
            1,
        )
        self.assertEqual(
            context.emitter.events[0]["status"],
            "failed",
        )
        self.assertEqual(
            context.runtime_tool_results[0]["result"]["error"],
            "active_memory_not_resolved",
        )


    def test_apply_runtime_action_calls_allows_multiple_save_active_memory_turns(self):

        Context = FakeContext

        context = Context()
        context.runtime_action_events = []
        context.runtime_search_calls = []
        context.active_memory_records = []
        context.runtime_memory = ""
        context.runtime_memory_stable = ""

        first_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="SAVE_ACTIVE_MEMORY",
                        payload="First reminder",
                    ),
                ),
            )
        )
        second_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="SAVE_ACTIVE_MEMORY",
                        payload="Second reminder",
                    ),
                ),
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
            len(context.active_memory_records),
            2,
        )
        self.assertRegex(
            context.active_memory_records[0],
            r"^active_memory_1: First reminder ",
        )
        self.assertRegex(
            context.active_memory_records[1],
            r"^active_memory_2: Second reminder ",
        )


    def test_apply_runtime_action_calls_reports_invalid_active_memory_reference(self):

        Emitter = FakeEmitter

        Context = FakeContext

        context = Context()
        context.emitter = Emitter()
        context.runtime_memory = (
            "active_memory: remember cuckoo [ active_memory_id: 5fdg4g ] "
            "[ status: pending ]"
        )
        context.runtime_memory_stable = context.runtime_memory
        context.active_memory_records = [
            context.runtime_memory,
        ]

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="RESOLVE_ACTIVE_MEMORY",
                        payload="active_memory_10",
                    ),
                    RuntimeActionCall(
                        name="RESOLVE_ACTIVE_MEMORY",
                        payload="active_memory_10",
                    ),
                    RuntimeActionCall(
                        name="CLEAN_TOOL_RESULTS",
                        payload="",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            1,
        )
        self.assertIn(
            "5fdg4g",
            context.runtime_memory,
        )
        self.assertEqual(
            len(context.runtime_action_events),
            2,
        )
        self.assertEqual(
            context.runtime_action_events[0]["status"],
            "failed",
        )
        self.assertEqual(
            context.runtime_action_events[0]["requested"],
            "active_memory_10",
        )
        self.assertEqual(
            context.runtime_tool_results,
            [
                {
                    "kind": TOOL_RESULT_KIND_ACTIVE_MEMORY,
                    "result": {
                        "ok": False,
                        "action": "resolve_active_memory",
                        "error": "invalid_active_memory_id",
                        "requested": "active_memory_10",
                        "detail": (
                            "Active memory was not resolved. Use an exact "
                            "6-character active_memory_id from <ACTIVE_MEMORY> "
                            "and retry only for a record that is still pending."
                        ),
                        "available_ids": [
                            "5fdg4g",
                        ],
                    },
                },
            ],
        )
        self.assertEqual(
            [
                event.get("status")
                for event in context.emitter.events
            ],
            [
                "completed",
                "failed",
            ],
        )

        tool_results = build_tool_results_context(
            context
        )
        self.assertIn(
            '<TOOL_RESULT name="RESOLVE_ACTIVE_MEMORY"',
            tool_results,
        )
        self.assertIn(
            '"ok": false',
            tool_results,
        )
        self.assertIn(
            '"requested": "active_memory_10"',
            tool_results,
        )
        self.assertIn(
            '"available_ids": [',
            tool_results,
        )

        flush_pending_active_memory_resolve_failure_history(
            context
        )
        self.assertIn(
            "RESOLVE_ACTIVE_MEMORY - failed: active_memory_10",
            context.runtime_session_action_history[-1]["text"],
        )

