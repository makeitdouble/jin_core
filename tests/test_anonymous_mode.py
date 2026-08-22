import json
import unittest

from contracts.rules_assembler import (
    RUNTIME_ACTION_ASSET_ACTION,
    RUNTIME_ACTION_SAVE_DELAYED_MEMORY,
    RUNTIME_ACTION_UPDATE_L4_FACTS,
)
from runtime.anonymous_mode import (
    RESTRICTED_WRITE_ERROR,
    RESTRICTED_WRITE_FOLLOWUP_MESSAGE,
    RESTRICTED_WRITE_REASON,
    asset_action_writes_persistent_data,
    build_restricted_write_event,
    configure_runtime_anonymous_mode,
    runtime_action_write_is_restricted,
)
from runtime.runtime_context import RuntimeContext
from tests.helpers.memory import FakeLogger
from utils.actions import RuntimeActionCall
from utils.actions.dispatcher import apply_runtime_action_calls
from utils.context.session_actions import build_session_actions_history_context
from utils.session_actions_history import (
    record_session_action_history,
    replace_session_action_history_since,
)


class FakeEmitter:

    def __init__(self):
        self.events = []

    async def emit(self, payload):
        self.events.append(payload)


class AnonymousModeTests(unittest.IsolatedAsyncioTestCase):

    def test_configuration_restricts_only_persistent_writes(self):
        context = RuntimeContext(
            websocket=None,
            emitter=FakeEmitter(),
            logger=FakeLogger(),
            clients={},
        )
        context.delayed_memory_file_store_enabled = True

        configure_runtime_anonymous_mode(context, True)

        self.assertTrue(context.runtime_anonymous_mode)
        self.assertTrue(context.runtime_persistent_writes_restricted)
        self.assertFalse(context.delayed_memory_file_store_enabled)
        self.assertTrue(
            runtime_action_write_is_restricted(
                context,
                RUNTIME_ACTION_UPDATE_L4_FACTS,
                "{}",
            )
        )
        self.assertTrue(
            runtime_action_write_is_restricted(
                context,
                RUNTIME_ACTION_SAVE_DELAYED_MEMORY,
                "{}",
            )
        )
        self.assertFalse(
            runtime_action_write_is_restricted(
                context,
                "SAVE_ACTIVE_MEMORY",
                "active_memory: keep this locally",
            )
        )

        configure_runtime_anonymous_mode(context, False)

        self.assertFalse(context.runtime_anonymous_mode)
        self.assertFalse(context.runtime_persistent_writes_restricted)
        self.assertTrue(context.delayed_memory_file_store_enabled)
        self.assertFalse(
            runtime_action_write_is_restricted(
                context,
                RUNTIME_ACTION_UPDATE_L4_FACTS,
                "{}",
            )
        )

    def test_asset_action_classifier_blocks_mutations_but_allows_reads(self):
        for action_name in (
            "create_asset_file",
            "append_asset_file",
            "create_wildcard_file",
            "append_wildcard_file",
            "create_wildcard_library",
            "generate_prompt_batch",
            "delete_future_asset",
            "rename_future_asset",
        ):
            with self.subTest(action_name=action_name):
                self.assertTrue(
                    asset_action_writes_persistent_data(
                        json.dumps({"action": action_name})
                    )
                )

        for action_name in (
            "list_wildcards",
            "sample_wildcard",
            "expand_template",
            "check_duplicates",
            "preview_file",
        ):
            with self.subTest(action_name=action_name):
                self.assertFalse(
                    asset_action_writes_persistent_data(
                        json.dumps({"action": action_name})
                    )
                )

    def test_restricted_event_contract_is_explicit(self):
        event = build_restricted_write_event(
            RUNTIME_ACTION_UPDATE_L4_FACTS
        )

        self.assertEqual(event["status"], "failed")
        self.assertEqual(event["error"], RESTRICTED_WRITE_ERROR)
        self.assertEqual(event["failure_reason"], RESTRICTED_WRITE_REASON)
        self.assertIn("failed: restricted write", event["title"])
        self.assertEqual(
            event["failure_followup_message"],
            RESTRICTED_WRITE_FOLLOWUP_MESSAGE,
        )
        no_followup_event = build_restricted_write_event(
            RUNTIME_ACTION_UPDATE_L4_FACTS,
            include_followup=False,
        )
        self.assertNotIn("failure_followup_message", no_followup_event)

    async def test_dispatcher_rejects_l4_write_before_execution_and_emits_failure(self):
        emitter = FakeEmitter()
        logger = FakeLogger()
        context = RuntimeContext(
            websocket=None,
            emitter=emitter,
            logger=logger,
            clients={},
        )
        configure_runtime_anonymous_mode(context, True)
        context.runtime_long_term_memory_store = {
            "version": 1,
            "facts": [],
            "next_id": 1,
        }

        action = RuntimeActionCall(
            name=RUNTIME_ACTION_UPDATE_L4_FACTS,
            payload=json.dumps({
                "fact_ids": [],
                "message": "Create a durable fact.",
            }),
        )

        applied = await apply_runtime_action_calls(
            context,
            (action,),
            action_display_ids={id(action): "update_l4_facts_001"},
        )

        self.assertEqual(applied, 0)
        self.assertFalse(getattr(context, "background_tasks", set()))
        self.assertEqual(
            getattr(
                context,
                "runtime_action_failure_followup_messages",
                [],
            ),
            [],
        )
        self.assertTrue(
            any(
                "update_l4_facts failed: restricted write" in line
                for line in logger.runtime_logs
            )
        )
        self.assertEqual(len(emitter.events), 1)
        self.assertEqual(emitter.events[0]["status"], "failed")
        self.assertEqual(emitter.events[0]["error"], RESTRICTED_WRITE_ERROR)
        self.assertEqual(
            emitter.events[0]["detail"],
            "",
        )
        self.assertEqual(
            context.runtime_action_events[0]["failure_reason"],
            RESTRICTED_WRITE_REASON,
        )

        replace_session_action_history_since(
            context,
            0,
            [{
                "name": RUNTIME_ACTION_UPDATE_L4_FACTS,
                "payload": action.payload,
                "payloads": [action.payload],
                "raw_payloads": [action.payload],
                "marker_count": 1,
            }],
        )
        rendered = build_session_actions_history_context(context)
        self.assertIn("UPDATE_L4_FACTS:failed", rendered)
        self.assertIn("restricted write", rendered)

    async def test_dispatcher_rejects_mutating_asset_action_but_allows_read_classifier(self):
        context = RuntimeContext(
            websocket=None,
            emitter=FakeEmitter(),
            logger=FakeLogger(),
            clients={},
        )
        configure_runtime_anonymous_mode(context, True)

        write_action = RuntimeActionCall(
            name=RUNTIME_ACTION_ASSET_ACTION,
            payload=json.dumps({
                "action": "create_asset_file",
                "path": "forbidden.txt",
                "content": "nope",
            }),
        )

        self.assertTrue(
            runtime_action_write_is_restricted(
                context,
                write_action.name,
                write_action.payload,
            )
        )
        self.assertFalse(
            runtime_action_write_is_restricted(
                context,
                RUNTIME_ACTION_ASSET_ACTION,
                json.dumps({"action": "preview_file", "path": "x.txt"}),
            )
        )

        applied = await apply_runtime_action_calls(
            context,
            (write_action,),
        )
        self.assertEqual(applied, 0)
        self.assertEqual(
            context.runtime_action_failure_followup_messages,
            [RESTRICTED_WRITE_FOLLOWUP_MESSAGE],
        )

    def test_session_actions_context_keeps_restricted_reason(self):
        context = RuntimeContext(
            websocket=None,
            emitter=FakeEmitter(),
            logger=FakeLogger(),
            clients={},
        )

        record_session_action_history(
            context,
            "UPDATE_L4_FACTS:failed - restricted write",
        )

        rendered = build_session_actions_history_context(context)
        self.assertIn("UPDATE_L4_FACTS:failed", rendered)
        self.assertIn("restricted write", rendered)


if __name__ == "__main__":
    unittest.main()
