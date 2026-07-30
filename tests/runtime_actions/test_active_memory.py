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
    get_save_active_memory_marker_fields,
    get_save_active_memory_placeholder_payload,
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



class RuntimeActiveMemoryTests(RuntimeActionTestCase):

    def test_extracts_bracketed_save_active_memory_marker(self):

        result = extract_runtime_actions(
            (
                "before "
                "<SAVE_ACTIVE_MEMORY:remind later | tomorrow | coffee>"
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


    def test_extracts_save_active_memory_marker_closed_with_short_end_tag(self):

        result = extract_runtime_actions(
            (
                "before "
                "<SAVE_ACTIVE_MEMORY: remember the word coffee "
                "and ask for a guess later.</>"
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

    def test_save_active_memory_marker_helpers_accept_bare_marker(self):

        marker = "SAVE_ACTIVE_MEMORY: PURPOSE | CONDITIONS"

        self.assertEqual(
            get_save_active_memory_marker_fields(
                marker
            ),
            (
                "purpose",
                "conditions",
            ),
        )
        self.assertEqual(
            get_save_active_memory_placeholder_payload(
                marker
            ),
            "PURPOSE | CONDITIONS",
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

        with patch(
            "utils.actions.action_payload_utils.get_internal_actions_with_payload",
            return_value=(
                "<SAVE_ACTIVE_MEMORY: DETAILS | PURPOSE | VALUE >",
            ),
        ):
            result = extract_runtime_actions(
                "<SAVE_ACTIVE_MEMORY: details|purpose|value >",
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


    def test_stream_filter_handles_short_end_tag_closed_active_memory_marker(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_SAVE_ACTIVE_MEMORY",
            ],
        )

        first = stream_filter.filter(
            "<SAVE_ACTIVE_MEMORY: remember"
        )
        middle = stream_filter.filter(
            " the word coffee and ask for a guess later.</"
        )
        final = stream_filter.filter(
            ">"
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
        self.assertFalse(
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
            context.emitter.events[1],
            {
                "type": "runtime_action",
                "action": "save_active_memory",
                "status": "completed",
                "display_name": "SAVE_ACTIVE_MEMORY",
                "close_tag": False,
            },
        )

        tool_results = build_tool_results_context(
            context
        )
        self.assertIn(
            '<TOOL_RESULT name="SAVE_ACTIVE_MEMORY">',
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
        self.assertFalse(
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
                    "display_name": "SAVE_ACTIVE_MEMORY",
                    "text": "SAVE_ACTIVE_MEMORY: remember cuckoo",
                    "payload": "remember cuckoo",
                    "close_tag": False,
                },
                {
                    "type": "runtime_action",
                    "action": "save_active_memory",
                    "status": "completed",
                    "display_name": "SAVE_ACTIVE_MEMORY",
                    "close_tag": False,
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
                    "display_name": "SAVE_ACTIVE_MEMORY",
                    "text": "SAVE_ACTIVE_MEMORY: remember cuckoo",
                    "payload": "remember cuckoo",
                    "close_tag": False,
                },
                {
                    "type": "runtime_action",
                    "action": "save_active_memory",
                    "status": "completed",
                    "display_name": "SAVE_ACTIVE_MEMORY",
                    "close_tag": False,
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
            '<TOOL_RESULT name="RESOLVE_ACTIVE_MEMORY">',
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
            '<TOOL_RESULT name="RESOLVE_ACTIVE_MEMORY">',
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

