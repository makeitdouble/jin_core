import asyncio
import unittest
from unittest.mock import patch

from clients import (
    apply_runtime_action_calls,
)
from clients.brain_client import (
    should_execute_save_session,
)
from rules import runtime as runtime_rules
from utils.runtime_actions import (
    RuntimeActionCall,
    RuntimeActionStreamFilter,
    extract_active_memory_update_slot_id,
    extract_search_query,
    extract_runtime_actions,
)


class RuntimeActionTests(unittest.TestCase):

    def test_extract_runtime_actions_handles_none_text(self):

        result = extract_runtime_actions(
            None
        )

        self.assertEqual(
            result.text,
            "",
        )
        self.assertEqual(
            result.actions,
            (),
        )


    def test_extracts_bracketed_web_search_marker(self):

        result = extract_runtime_actions(
            "<INTERNAL_ACTION_WEB_SEARCH:\u0441\u0438\u043d\u0438\u0439 \u043f\u043e\u043c\u0438\u0434\u043e\u0440>",
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
        )

        self.assertEqual(
            result.text,
            "",
        )
        self.assertEqual(
            result.search_queries,
            (
                "\u0441\u0438\u043d\u0438\u0439 \u043f\u043e\u043c\u0438\u0434\u043e\u0440",
            ),
        )

    def test_extracts_bracketed_web_search_marker_inside_text(self):

        result = extract_runtime_actions(
            (
                "Before\n"
                "<INTERNAL_ACTION_WEB_SEARCH:\u0441\u0438\u043d\u0438\u0439 \u043f\u043e\u043c\u0438\u0434\u043e\u0440>\n"
                "After"
            ),
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
        )

        self.assertNotIn(
            "INTERNAL_ACTION_WEB_SEARCH",
            result.text,
        )
        self.assertIn(
            "Before",
            result.text,
        )
        self.assertIn(
            "After",
            result.text,
        )
        self.assertEqual(
            result.search_queries,
            (
                "\u0441\u0438\u043d\u0438\u0439 \u043f\u043e\u043c\u0438\u0434\u043e\u0440",
            ),
        )

    def test_ignores_placeholder_bracketed_web_search_marker(self):

        for marker in (
            "<INTERNAL_ACTION_WEB_SEARCH:plain text query>",
            "<INTERNAL_ACTION_WEB_SEARCH:<plain text query>>",
            "<INTERNAL_ACTION_WEB_SEARCH:...>",
        ):

            result = extract_runtime_actions(
                marker,
                enabled_actions=[
                    "CAN_WEB_SEARCH",
                ],
            )

            self.assertEqual(
                result.text,
                "",
            )
            self.assertEqual(
                result.count("WEB_SEARCH"),
                0,
            )

    def test_extracts_bracketed_save_session_marker(self):

        result = extract_runtime_actions(
            "<INTERNAL_ACTION_SAVE_SESSION>",
            enabled_actions=[
                "CAN_SAVE_SESSION",
            ],
        )

        self.assertEqual(
            result.text,
            "",
        )
        self.assertEqual(
            result.count("SAVE_SESSION"),
            1,
        )

    def test_extracts_bracketed_create_active_memory_marker(self):

        result = extract_runtime_actions(
            (
                "before "
                "<INTERNAL_ACTION_CREATE_ACTIVE_MEMORY:remind later | tomorrow | coffee>"
                " after"
            ),
            enabled_actions=[
                "CAN_SAVE_ACTIVE_MEMORY",
            ],
        )

        self.assertEqual(
            result.text,
            "before  after",
        )
        self.assertEqual(
            result.count("CREATE_ACTIVE_MEMORY"),
            1,
        )
        self.assertEqual(
            result.actions[0].payload,
            "remind later | tomorrow | coffee",
        )

    def test_extracts_bare_update_active_memory_marker(self):

        result = extract_runtime_actions(
            (
                "INTERNAL_ACTION_UPDATE_ACTIVE_MEMORY: "
                "active_memory_id=e2qxe7 STATUS=resolved\n"
                "\n"
                "Память очищена."
            ),
            enabled_actions=[
                "CAN_SAVE_ACTIVE_MEMORY",
            ],
        )

        self.assertEqual(
            result.text,
            "Память очищена.",
        )
        self.assertEqual(
            result.count("UPDATE_ACTIVE_MEMORY"),
            1,
        )
        self.assertEqual(
            result.actions[0].payload,
            "active_memory_id=e2qxe7 STATUS=resolved",
        )

    def test_extracts_bracketed_update_active_memory_marker(self):

        result = extract_runtime_actions(
            (
                "before "
                "<INTERNAL_ACTION_UPDATE_ACTIVE_MEMORY:e2qxe7 | resolved>"
                " after"
            ),
            enabled_actions=[
                "CAN_SAVE_ACTIVE_MEMORY",
            ],
        )

        self.assertEqual(
            result.text,
            "before  after",
        )
        self.assertEqual(
            result.count("UPDATE_ACTIVE_MEMORY"),
            1,
        )
        self.assertEqual(
            result.actions[0].payload,
            "e2qxe7 | resolved",
        )

    def test_extract_active_memory_update_slot_id_accepts_loose_payload_shape(self):

        self.assertEqual(
            extract_active_memory_update_slot_id(
                "active_memory_id: 5fdg4g",
            ),
            "5fdg4g",
        )
        self.assertEqual(
            extract_active_memory_update_slot_id(
                "resolve slot 5fdg4g please",
                existing_ids={
                    "5fdg4g",
                },
            ),
            "5fdg4g",
        )

    def test_extract_active_memory_update_slot_id_skips_non_existing_tokens(self):

        self.assertEqual(
            extract_active_memory_update_slot_id(
                "active_memory_id | STATUS",
                existing_ids={
                    "5fdg4g",
                },
            ),
            "",
        )
        self.assertEqual(
            extract_active_memory_update_slot_id(
                "resolve status abc123",
                existing_ids={
                    "5fdg4g",
                },
            ),
            "",
        )

    def test_ignores_placeholder_create_active_memory_marker(self):

        with patch.object(
            runtime_rules,
            "INTERNAL_ACTIONS_WITH_PAYLOAD",
            [
                "<INTERNAL_ACTION_CREATE_ACTIVE_MEMORY: DETAILS | PURPOSE | VALUE >",
            ],
        ):
            result = extract_runtime_actions(
                "<INTERNAL_ACTION_CREATE_ACTIVE_MEMORY: details|purpose|value >",
                enabled_actions=[
                    "CAN_SAVE_ACTIVE_MEMORY",
                ],
            )

        self.assertEqual(
            result.text,
            "",
        )
        self.assertEqual(
            result.count("CREATE_ACTIVE_MEMORY"),
            0,
        )

    def test_ignores_placeholder_from_all_payload_marker_bodies(self):

        with patch.object(
            runtime_rules,
            "INTERNAL_ACTIONS_WITH_PAYLOAD",
            [
                "<INTERNAL_ACTION_WEB_SEARCH: plain text query >",
                "<INTERNAL_ACTION_UPDATE_ACTIVE_MEMORY: active_memory_id | STATUS >",
            ],
        ):
            search_result = extract_runtime_actions(
                "<INTERNAL_ACTION_WEB_SEARCH:<plain text query>>",
                enabled_actions=[
                    "CAN_WEB_SEARCH",
                ],
            )
            memory_result = extract_runtime_actions(
                "<INTERNAL_ACTION_CREATE_ACTIVE_MEMORY: active_memory_id|status>",
                enabled_actions=[
                    "CAN_SAVE_ACTIVE_MEMORY",
                ],
            )

        self.assertEqual(
            search_result.count("WEB_SEARCH"),
            0,
        )
        self.assertEqual(
            memory_result.count("CREATE_ACTIVE_MEMORY"),
            0,
        )

    def test_old_xml_runtime_action_protocol_is_not_parsed(self):

        result = extract_runtime_actions(
            '<RUNTIME_ACTION:SAVE_SESSION enabled="true"/>',
            enabled_actions=[
                "CAN_SAVE_SESSION",
            ],
        )

        self.assertEqual(
            result.text,
            '<RUNTIME_ACTION:SAVE_SESSION enabled="true"/>',
        )
        self.assertEqual(
            result.actions,
            (),
        )

    def test_old_internal_action_line_protocol_is_not_parsed(self):

        result = extract_runtime_actions(
            "INTERNAL_ACTION: WEB_SEARCH query: blue tomato",
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
        )

        self.assertEqual(
            result.text,
            "INTERNAL_ACTION: WEB_SEARCH query: blue tomato",
        )
        self.assertEqual(
            result.actions,
            (),
        )

    def test_stream_filter_keeps_deep_thought_marker_as_text(self):

        stream_filter = RuntimeActionStreamFilter()

        first = stream_filter.filter(
            "before <INTERNAL_ACTION_DEEP"
        )
        second = stream_filter.filter(
            "_THOUGHT> after"
        )

        self.assertEqual(
            first.text,
            "before <INTERNAL_ACTION_DEEP",
        )
        self.assertEqual(
            second.text,
            "_THOUGHT> after",
        )
        self.assertEqual(
            stream_filter.flush(),
            "",
        )

    def test_stream_filter_handles_split_bracketed_web_search_marker(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
        )

        first = stream_filter.filter(
            "<INTERNAL_ACTION_WEB_SEARCH:\u0441\u0438"
        )
        second = stream_filter.filter(
            "\u043d\u0438\u0439 \u043f\u043e\u043c\u0438\u0434\u043e\u0440>"
        )

        self.assertEqual(
            first.text,
            "",
        )
        self.assertEqual(
            first.count("WEB_SEARCH"),
            0,
        )
        self.assertEqual(
            second.text,
            "",
        )
        self.assertEqual(
            second.search_queries,
            (
                "\u0441\u0438\u043d\u0438\u0439 \u043f\u043e\u043c\u0438\u0434\u043e\u0440",
            ),
        )
        self.assertEqual(
            stream_filter.flush(),
            "",
        )

    def test_stream_filter_preserves_thinking_marker_text_when_requested(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
            preserve_action_text=True,
        )

        result = stream_filter.filter(
            "Need search. <INTERNAL_ACTION_WEB_SEARCH:\u0441\u0438\u043d\u0438\u0439 \u043f\u043e\u043c\u0438\u0434\u043e\u0440>"
        )

        self.assertEqual(
            result.text,
            "Need search. <INTERNAL_ACTION_WEB_SEARCH:\u0441\u0438\u043d\u0438\u0439 \u043f\u043e\u043c\u0438\u0434\u043e\u0440>",
        )
        self.assertEqual(
            result.search_queries,
            (
                "\u0441\u0438\u043d\u0438\u0439 \u043f\u043e\u043c\u0438\u0434\u043e\u0440",
            ),
        )

    def test_stream_filter_flush_drops_incomplete_private_marker(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
        )

        result = stream_filter.filter(
            "hello <INTERNAL_ACTION_WEB_SEARCH:??"
        )

        self.assertEqual(
            result.text,
            "hello ",
        )
        self.assertEqual(
            stream_filter.flush(),
            "",
        )

    def test_stream_filter_does_not_hold_plain_angle_text(self):

        stream_filter = RuntimeActionStreamFilter()

        first = stream_filter.filter(
            "hello <"
        )
        second = stream_filter.filter(
            "not action"
        )

        self.assertEqual(
            first.text,
            "hello ",
        )
        self.assertEqual(
            second.text,
            "<not action",
        )

    def test_stream_filter_holds_confirmed_action_until_close(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_WEB_SEARCH",
            ],
        )

        first = stream_filter.filter(
            "<INTERNAL_ACTION_WEB_SEARCH:"
        )
        middle = stream_filter.filter(
            "blue tomato"
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
            final.search_queries,
            (
                "blue tomato",
            ),
        )

    def test_apply_runtime_action_calls_stores_search_queries(self):

        class Context:
            pass

        context = Context()

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="WEB_SEARCH",
                        payload='{"query":"test"}',
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            1,
        )
        self.assertEqual(
            getattr(
                context,
                "runtime_search_queries",
            ),
            [
                "test",
            ],
        )
        self.assertEqual(
            getattr(
                context,
                "runtime_action_events",
            )[0]["id"],
            "web_search_001",
        )

    def test_apply_runtime_action_calls_ignores_empty_search_payload(self):

        class Context:
            pass

        context = Context()

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="WEB_SEARCH",
                        payload='{"query":"..."}',
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            0,
        )
        self.assertFalse(
            getattr(
                context,
                "runtime_search_calls",
            ),
        )
        self.assertFalse(
            getattr(
                context,
                "runtime_action_events",
            ),
        )

    def test_apply_runtime_action_calls_uses_one_search_query(self):

        class Context:
            pass

        context = Context()

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="WEB_SEARCH",
                        payload='{"query":"first"}',
                    ),
                    RuntimeActionCall(
                        name="WEB_SEARCH",
                        payload='{"query":"second"}',
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            1,
        )
        self.assertEqual(
            getattr(
                context,
                "runtime_search_queries",
            ),
            [
                "first",
            ],
        )

    def test_bracketed_save_session_marker_allowed_by_save_request(self):

        class Context:
            pass

        context = Context()
        result = extract_runtime_actions(
            "<INTERNAL_ACTION_SAVE_SESSION>",
            enabled_actions=[
                "CAN_SAVE_SESSION",
            ],
        )

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                result.actions,
                user_message="\u0441\u043e\u0445\u0440\u0430\u043d\u0438 \u0441\u0435\u0441\u0441\u0438\u044e",
            )
        )

        self.assertEqual(
            result.text,
            "",
        )
        self.assertEqual(
            applied_count,
            1,
        )
        self.assertTrue(
            context.runtime_save_session_requested,
        )

    def test_bracketed_save_session_marker_allowed_by_bedtime_pause(self):

        class Context:
            pass

        context = Context()
        result = extract_runtime_actions(
            "<INTERNAL_ACTION_SAVE_SESSION>",
            enabled_actions=[
                "CAN_SAVE_SESSION",
            ],
        )

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                result.actions,
                user_message="ладно, я спать, до завтра!",
            )
        )

        self.assertEqual(
            applied_count,
            1,
        )
        self.assertTrue(
            context.runtime_save_session_requested,
        )

    def test_bracketed_save_session_marker_blocked_by_meta_request(self):

        class Context:
            pass

        context = Context()
        result = extract_runtime_actions(
            "<INTERNAL_ACTION_SAVE_SESSION>",
            enabled_actions=[
                "CAN_SAVE_SESSION",
            ],
        )

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                result.actions,
                user_message="\u043d\u0430\u043f\u0438\u0448\u0438 \u043f\u043e\u043b\u043d\u044b\u0439 \u0442\u0435\u0433 \u0441\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u0438\u044f \u0441\u0435\u0441\u0441\u0438\u0438",
            )
        )

        self.assertEqual(
            result.text,
            "",
        )
        self.assertEqual(
            applied_count,
            0,
        )
        self.assertFalse(
            getattr(
                context,
                "runtime_save_session_requested",
                False,
            )
        )

    def test_save_session_guard_intents(self):

        self.assertTrue(
            should_execute_save_session(
                "\u0441\u043e\u0445\u0440\u0430\u043d\u0438 \u0441\u0435\u0441\u0441\u0438\u044e"
            )
        )
        self.assertTrue(
            should_execute_save_session(
                "\u0437\u0430\u043a\u043e\u043d\u0447\u0438\u043c"
            )
        )
        self.assertTrue(
            should_execute_save_session(
                "\u043b\u0430\u0434\u043d\u043e, \u044f \u0441\u043f\u0430\u0442\u044c, \u0434\u043e \u0437\u0430\u0432\u0442\u0440\u0430!"
            )
        )
        self.assertFalse(
            should_execute_save_session(
                "\u043d\u0430\u043f\u0438\u0448\u0438 \u043f\u043e\u043b\u043d\u044b\u0439 \u0442\u0435\u0433 \u0441\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u0438\u044f \u0441\u0435\u0441\u0441\u0438\u0438"
            )
        )
        self.assertFalse(
            should_execute_save_session(
                "\u043f\u043e\u043a\u0430\u0436\u0438 \u0442\u043e\u0447\u043d\u044b\u0439 \u0442\u0435\u0433 \u0434\u043b\u044f \u0441\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u0438\u044f \u0441\u0435\u0441\u0441\u0438\u0438"
            )
        )
        self.assertFalse(
            should_execute_save_session(
                "\u043f\u0440\u0438\u043c\u0435\u0440 \u0442\u0435\u0433\u0430"
            )
        )
        self.assertFalse(
            should_execute_save_session(
                "\u0437\u0430\u0431\u0443\u0434\u044c \u043f\u0440\u043e\u0448\u043b\u043e\u0435, \u0441\u043c\u0435\u043d\u0438\u043c \u0442\u0435\u043c\u0443"
            )
        )
        self.assertFalse(
            should_execute_save_session(
                "\u0445\u043e\u0440\u043e\u0448\u043e, \u044f \u0441\u043e\u0445\u0440\u0430\u043d\u0438\u043b, \u0441\u043f\u0430\u0441\u0438\u0431\u043e"
            )
        )

    def test_apply_runtime_action_calls_records_create_active_memory(self):

        class Context:
            pass

        context = Context()

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="CREATE_ACTIVE_MEMORY",
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
                    "name": "create_active_memory",
                    "payload": "remind later",
                }
            ],
        )

    def test_apply_runtime_action_calls_emits_create_active_memory_bubble(self):

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        context = Context()
        context.emitter = Emitter()

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="CREATE_ACTIVE_MEMORY",
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
            1,
        )
        self.assertEqual(
            context.emitter.events[0],
            {
                "type": "runtime_action",
                "action": "create_active_memory",
                "text": "Saving: remind later",
            },
        )
        self.assertEqual(
            len(context.runtime_pending_active_memory_records),
            1,
        )
        self.assertRegex(
            context.runtime_pending_active_memory_records[0],
            (
                r"^active_memory: remind later "
                r"\[ id: [a-z0-9]{6} \] "
                r"\[ conditions: remind later \] "
                r"\[ status: pending \]$"
            ),
        )

    def test_apply_runtime_action_calls_queues_active_memory_record(self):

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        context = Context()
        context.emitter = Emitter()
        context.timestamp = "2026-06-24T15:00:00"
        context.turn_number = 7
        context.runtime_memory = "session_status: active"
        context.runtime_memory_updates = 0

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="CREATE_ACTIVE_MEMORY",
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
            len(context.runtime_pending_active_memory_records),
            1,
        )
        self.assertRegex(
            context.runtime_pending_active_memory_records[0],
            (
                r"^active_memory: Drink coffee \| Trigger in 5 minutes \| coffee "
                r"\[ id: [a-z0-9]{6} \] "
                r"\[ conditions: Drink coffee \| Trigger in 5 minutes \| coffee \] "
                r"\[ status: pending \]$"
            ),
        )
        self.assertEqual(
            context.emitter.events,
            [
                {
                    "type": "runtime_action",
                    "action": "create_active_memory",
                    "text": "Saving: Drink coffee | Trigger in 5 minutes | coffee",
                },
            ],
        )

    def test_apply_runtime_action_calls_resolves_active_memory_by_id(self):

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        context = Context()
        context.emitter = Emitter()
        context.runtime_memory = (
            "session_status: active\n"
            "active_memory: remember cuckoo [ id: 5fdg4g ] "
            "[ status: pending ]\n"
            "user_message: hello"
        )
        context.runtime_memory_stable = context.runtime_memory
        context.runtime_pending_active_memory_records = [
            (
                "active_memory: keep this [ id: abc123 ] "
                "[ status: pending ]"
            ),
        ]

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="UPDATE_ACTIVE_MEMORY",
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
            context.runtime_pending_active_memory_records,
            [
                (
                    "active_memory: keep this [ id: abc123 ] "
                    "[ status: pending ]"
                ),
            ],
        )
        self.assertEqual(
            context.emitter.events,
            [
                {
                    "type": "runtime_action",
                    "action": "update_active_memory",
                    "text": "Active memory resolved",
                },
            ],
        )

    def test_apply_runtime_action_calls_skips_unknown_active_memory_id(self):

        class Context:
            pass

        context = Context()
        context.runtime_memory = (
            "active_memory: remember cuckoo [ id: 5fdg4g ] "
            "[ status: pending ]"
        )
        context.runtime_memory_stable = context.runtime_memory
        context.runtime_pending_active_memory_records = []

        applied_count = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="UPDATE_ACTIVE_MEMORY",
                        payload="active_memory_id: abc123",
                    ),
                ),
            )
        )

        self.assertEqual(
            applied_count,
            0,
        )
        self.assertIn(
            "5fdg4g",
            context.runtime_memory,
        )
        self.assertEqual(
            context.runtime_action_events,
            [],
        )


    def test_extract_search_query_unnests_json_string(self):

        self.assertEqual(
            extract_search_query(
                '"{\\"query\\":\\"apples price 2026\\"}"'
            ),
            "apples price 2026",
        )

    def test_extract_search_query_unnests_query_json_string(self):

        self.assertEqual(
            extract_search_query(
                '{"query":"{\\"query\\":\\"apples price 2026\\"}"}'
            ),
            "apples price 2026",
        )


if __name__ == "__main__":
    unittest.main()
