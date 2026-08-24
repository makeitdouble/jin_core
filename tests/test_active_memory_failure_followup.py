import json
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

from agent.nodes.brain import (
    BrainNode,
    action_event_requires_follow_up,
)
from runtime.runtime_context import RuntimeContext
from utils.actions.common_action_utils import (
    RuntimeActionCall,
    extract_runtime_actions,
)
from utils.actions.dispatcher import apply_runtime_action_calls
from utils.context.tool_results import build_tool_results_context


class _Emitter:

    def __init__(self):
        self.items = []

    async def emit(self, payload):
        self.items.append(payload)


class _Logger:

    async def log(self, *args, **kwargs):
        return None


class ActiveMemoryFailureFollowupTests(IsolatedAsyncioTestCase):

    def test_contract_follow_up_on_fail_is_explicit(self):
        contract_dir = Path(__file__).resolve().parents[1] / "contracts"
        true_actions = set()
        for path in contract_dir.glob("*.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))

            for contract in payload.values():
                if not isinstance(contract, dict) or not contract.get("runtime_action"):
                    continue

                self.assertNotIn("body_placeholder", contract)
                self.assertIn("follow_up_on_fail", contract.get("effects", {}))

                if contract["effects"]["follow_up_on_fail"]:
                    true_actions.add(contract["runtime_action"])

        self.assertEqual(
            true_actions,
            {"SAVE_ACTIVE_MEMORY", "UPDATE_ACTIVE_MEMORY"},
        )

    def test_closed_invalid_update_marker_is_fully_hidden(self):
        failed_payload = (
            '{"active_memory_id":"zgctxy","field_name":"last_photo_id","VALUE":"hpfgfn"}\n'
            '{"active_memory_id":"zgctxy","field_name":"current_photos","VALUE":"3"}'
        )
        source = (
            "before\n"
            "<UPDATE_ACTIVE_MEMORY>\n"
            f"{failed_payload}\n"
            "</UPDATE_ACTIVE_MEMORY>\n"
            "after"
        )

        result = extract_runtime_actions(
            source,
            enabled_actions=["CAN_SAVE_ACTIVE_MEMORY"],
        )

        self.assertEqual(result.text, "before\nafter")
        self.assertEqual(len(result.actions), 1)
        self.assertEqual(result.actions[0].name, "UPDATE_ACTIVE_MEMORY")
        self.assertEqual(result.actions[0].payload, failed_payload)
        self.assertNotIn("UPDATE_ACTIVE_MEMORY", result.text)
        self.assertNotIn("active_memory_id", result.text)

    def test_failure_followup_is_contract_controlled(self):
        self.assertTrue(action_event_requires_follow_up({
            "name": "save_active_memory",
            "status": "failed",
        }))
        self.assertTrue(action_event_requires_follow_up({
            "name": "update_active_memory",
            "status": "failed",
        }))
        self.assertFalse(action_event_requires_follow_up({
            "name": "web_search",
            "status": "failed",
        }))

    async def test_invalid_update_gets_failed_event_and_retry_context(self):
        emitter = _Emitter()
        context = RuntimeContext(
            websocket=None,
            emitter=emitter,
            logger=_Logger(),
            clients={},
        )
        context.runtime_current_turn_id = "turn-1"
        context.runtime_current_sequence_turn_id = "turn-1"
        context.runtime_turn_user_message = "update photo state"
        failed_payload = (
            '{"active_memory_id":"zgctxy","field_name":"last_photo_id","VALUE":"hpfgfn"}\n'
            '{"active_memory_id":"zgctxy","field_name":"current_photos","VALUE":"3"}'
        )

        await apply_runtime_action_calls(
            context,
            [RuntimeActionCall(
                name="UPDATE_ACTIVE_MEMORY",
                payload=failed_payload,
            )],
            assistant_message="",
        )

        event = context.runtime_action_events[-1]
        self.assertEqual(event["status"], "failed")
        self.assertEqual(event["error"], "invalid_update_active_memory_payload")
        self.assertEqual(event["failure_reason"], "invalid payload")
        self.assertEqual(event["failed_marker_payload"], failed_payload)
        self.assertTrue(action_event_requires_follow_up(event))
        self.assertTrue(emitter.items[-1]["close_tag"])
        self.assertNotIn("payload", emitter.items[-1])

        tool_results_context = build_tool_results_context(context)
        self.assertIn('name="UPDATE_ACTIVE_MEMORY"', tool_results_context)
        self.assertIn("invalid_update_active_memory_payload", tool_results_context)
        base_prompt = tool_results_context + "\n\nBASE RULES"
        prompt = BrainNode.build_followup_system_prompt(
            base_prompt,
            "update photo state",
            context=context,
            latest_action="UPDATE_ACTIVE_MEMORY",
        )

        self.assertNotIn("<FOLLOWUP_TICK>", prompt)
        mandatory = prompt.index("<MANDATORY_ACTION_RULES>")
        failed = prompt.index("<FAILED_MARKER_CONTENT>")
        tools = prompt.index("<TOOLS_RESULTS>")
        self.assertLess(mandatory, failed)
        self.assertLess(failed, tools)
        self.assertIn("Use to update active memory values.", prompt)
        self.assertIn(
            "<FAILED_MARKER_CONTENT>\n"
            "<UPDATE_ACTIVE_MEMORY>\n"
            f"{failed_payload}\n"
            "</UPDATE_ACTIVE_MEMORY>\n"
            "</FAILED_MARKER_CONTENT>",
            prompt,
        )

        context.runtime_action_events.append({
            "name": "update_active_memory",
            "status": "completed",
            "runtime_turn_id": "turn-1",
        })
        second_prompt = BrainNode.build_followup_system_prompt(
            base_prompt,
            "update photo state",
            context=context,
            latest_action="UPDATE_ACTIVE_MEMORY",
        )
        self.assertNotIn("<FAILED_MARKER_CONTENT>", second_prompt)

    async def test_update_wrong_id_and_field_use_existing_failures(self):
        active_record = (
            "active_memory_1: test "
            "[ active_memory_id: abc123 ] "
            "[ conditions: test ] "
            "[ current_photos: 2 ] "
            "[ status: pending ]"
        )
        cases = (
            (
                '{"active_memory_id":"zzzzzz","current_photos":"3"}',
                "active_memory_not_found",
                "incorrect id",
            ),
            (
                '{"active_memory_id":"abc123","wrong_field":"3"}',
                "active_memory_field_not_declared",
                "unknown field: wrong_field",
            ),
        )

        for payload, error, reason in cases:
            with self.subTest(error=error):
                context = RuntimeContext(
                    websocket=None,
                    emitter=_Emitter(),
                    logger=_Logger(),
                    clients={},
                )
                context.runtime_current_turn_id = "turn-1"
                context.runtime_current_sequence_turn_id = "turn-1"
                context.active_memory_records = [active_record]

                await apply_runtime_action_calls(
                    context,
                    [RuntimeActionCall(
                        name="UPDATE_ACTIVE_MEMORY",
                        payload=payload,
                    )],
                    assistant_message="",
                )

                event = context.runtime_action_events[-1]
                self.assertEqual(event["status"], "failed")
                self.assertEqual(event["error"], error)
                self.assertEqual(event["failure_reason"], reason)
                self.assertTrue(action_event_requires_follow_up(event))

    async def test_invalid_save_gets_failed_event(self):
        emitter = _Emitter()
        context = RuntimeContext(
            websocket=None,
            emitter=emitter,
            logger=_Logger(),
            clients={},
        )
        context.runtime_current_turn_id = "turn-1"
        context.runtime_current_sequence_turn_id = "turn-1"

        await apply_runtime_action_calls(
            context,
            [RuntimeActionCall(
                name="SAVE_ACTIVE_MEMORY",
                payload='{"wrong_field":"value"}',
            )],
            assistant_message="",
        )

        event = context.runtime_action_events[-1]
        self.assertEqual(event["status"], "failed")
        self.assertEqual(event["failure_reason"], "invalid payload")
        self.assertTrue(action_event_requires_follow_up(event))

    def test_old_turn_failed_event_is_not_replayed(self):
        context = RuntimeContext(
            websocket=None,
            emitter=_Emitter(),
            logger=_Logger(),
            clients={},
        )
        context.runtime_current_turn_id = "turn-2"
        context.runtime_current_sequence_turn_id = "turn-2"
        context.runtime_action_events.append({
            "name": "update_active_memory",
            "status": "failed",
            "runtime_turn_id": "turn-1",
            "failure_reason": "incorrect id",
            "payload": '{"active_memory_id":"abcdef","counter":"2"}',
        })

        prompt = BrainNode.build_followup_system_prompt(
            "BASE RULES",
            "new request",
            context=context,
            latest_action="UPDATE_ACTIVE_MEMORY",
        )

        self.assertNotIn("<FAILED_MARKER_CONTENT>", prompt)
