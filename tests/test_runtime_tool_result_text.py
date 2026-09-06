import json
from pathlib import Path
from unittest import TestCase

from utils.context.runtime_action_result_text import (
    format_runtime_action_result,
)


class RuntimeToolResultTextTests(TestCase):

    def test_every_contract_declares_schema_before_rules(self):
        contract_dir = Path(__file__).resolve().parents[1] / "contracts"

        for path in contract_dir.glob("*.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            for name, contract in payload.items():
                if not isinstance(contract, dict) or not contract.get("runtime_action"):
                    continue

                self.assertIn("schema", contract, msg=name)
                self.assertIsInstance(contract["schema"], list, msg=name)
                keys = list(contract)
                self.assertLess(
                    keys.index("schema"),
                    keys.index("rules"),
                    msg=name,
                )

    def test_failed_update_is_readable_and_includes_schema(self):
        payload = (
            '{"active_memory_id":"zgctxy",'
            '"field_to_update":"current_photos=5"}'
        )
        rendered = format_runtime_action_result(
            {
                "ok": False,
                "action": "update_active_memory",
                "error": "active_memory_field_not_declared",
                "detail": "unknown field: field_to_update",
                "id": "zgctxy",
                "payload": payload,
                "available_fields": [
                    "last_update",
                    "current_photos",
                    "last_photo_id",
                ],
            },
            runtime_action="UPDATE_ACTIVE_MEMORY",
        )

        self.assertIn("Active memory id: zgctxy", rendered)
        self.assertIn("Status: failed", rendered)
        self.assertIn("Reason: unknown field: field_to_update", rendered)
        self.assertIn("Provided payload:", rendered)
        self.assertIn(payload, rendered)
        self.assertIn("Correct action schema:", rendered)
        self.assertIn('"fields_to_update"', rendered)
        self.assertIn('"field_to_update"', rendered)
        self.assertNotIn('"ok": false', rendered)


    def test_recall_fact_context_messages_use_compact_transcript_format(self):
        rendered = format_runtime_action_result(
            {
                "ok": True,
                "fact_id": "F382",
                "sources": [
                    {
                        "source_id": "session/frame",
                        "messages": [
                            {
                                "message_id": "session/2",
                                "turn_id": "turn_000005",
                                "role": "jin",
                                "timestamp": "2026-09-04T16:33:34+03:00",
                                "text": "\n\nПонял. Лишний шум убран.",
                                "anchor": False,
                            },
                            {
                                "message_id": "session/3",
                                "turn_id": "turn_000006",
                                "role": "user",
                                "timestamp": "2026-09-04T16:34:50+03:00",
                                "text": "отлично, нарисуй чёнить чиловое",
                                "anchor": True,
                            },
                        ],
                    },
                ],
            },
            runtime_action="RECALL_FACT_CONTEXT",
        )

        self.assertIn("Messages:", rendered)
        self.assertIn("turn_5 | 2026-09-04T16:33:34+03:00", rendered)
        self.assertIn("jin: Понял. Лишний шум убран.", rendered)
        self.assertIn("turn_6 | 2026-09-04T16:34:50+03:00", rendered)
        self.assertIn("user: отлично, нарисуй чёнить чиловое", rendered)
        self.assertNotIn("Message id:", rendered)
        self.assertNotIn("Anchor:", rendered)
        self.assertNotIn("Turn id:", rendered)

    def test_success_update_is_readable_without_result_json(self):
        rendered = format_runtime_action_result(
            {
                "ok": True,
                "action": "update_active_memory",
                "id": "zgctxy",
                "changes": [
                    {
                        "field": "current_photos",
                        "before": "4",
                        "after": "5",
                    },
                ],
            },
            runtime_action="UPDATE_ACTIVE_MEMORY",
        )

        self.assertIn("Active memory id: zgctxy", rendered)
        self.assertIn("Status: success", rendered)
        self.assertIn("current_photos: 4 -> 5", rendered)
        self.assertNotIn('"ok": true', rendered)
