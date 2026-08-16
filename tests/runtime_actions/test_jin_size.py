import asyncio
import unittest
from types import SimpleNamespace

from clients.brain_client import apply_runtime_action_calls
from contracts.rules_assembler import (
    RUNTIME_ACTION_JIN_SIZE,
    build_runtime_action_instructions,
)
from tests.helpers.runtime_actions import FakeEmitter, RuntimeActionTestCase
from utils.actions import (
    RuntimeActionCall,
    extract_runtime_actions,
    normalize_jin_size_payload,
)
from utils.context.runtime_state import build_runtime_xml


class RuntimeJinSizeActionTests(RuntimeActionTestCase):

    def test_jin_size_marker_validates_supported_payload_forms(self):

        cases = (
            ("<JIN_SIZE: 120px 120px >", "120px"),
            ("<JIN_SIZE: 120 140 >", "w:120px h:140px"),
            ("<JIN_SIZE: w:120px h:140px >", "w:120px h:140px"),
            ("<JIN_SIZE: w:120 h:140 >", "w:120px h:140px"),
            ("<JIN_SIZE: 120px >", "120px"),
            ("<JIN_SIZE: 120 >", "120px"),
            ("<JIN_SIZE: w:120 >", "120px"),
            ("<JIN_SIZE: h:120px >", "120px"),
            (
                "<JIN_SIZE: width: 500px height: 300px >",
                "w:500px h:300px",
            ),
            (
                "<JIN_SIZE: junk width=500px / height=300px ignore 777 >",
                "w:500px h:300px",
            ),
        )

        for marker, expected_size in cases:
            with self.subTest(marker=marker):
                result = extract_runtime_actions(
                    f"before {marker} after",
                    enabled_actions=(
                        RUNTIME_ACTION_JIN_SIZE,
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
                    RUNTIME_ACTION_JIN_SIZE,
                )
                self.assertEqual(
                    result.actions[0].payload,
                    expected_size,
                )


    def test_normalize_jin_size_payload_rejects_bad_sizes(self):

        self.assertEqual(
            normalize_jin_size_payload("120px"),
            "120px",
        )
        self.assertEqual(
            normalize_jin_size_payload("120 140"),
            "w:120px h:140px",
        )
        self.assertEqual(
            normalize_jin_size_payload("w:120"),
            "120px",
        )
        self.assertEqual(
            normalize_jin_size_payload(
                "width: 500px height: 300px ignored 777"
            ),
            "w:500px h:300px",
        )
        self.assertEqual(
            normalize_jin_size_payload("120 140 160"),
            "w:120px h:140px",
        )
        self.assertEqual(
            normalize_jin_size_payload("120em"),
            "120px",
        )

        for payload in (
            "",
            "0",
            "-1",
            "w:120 h:-1",
        ):
            with self.subTest(payload=payload):
                self.assertEqual(
                    normalize_jin_size_payload(payload),
                    "",
                )


    def test_apply_runtime_action_calls_emits_jin_size(self):

        async def run_case():
            emitter = FakeEmitter()
            context = SimpleNamespace(
                runtime_action_events=[],
                runtime_search_calls=[],
                runtime_loaded_skills=[],
                runtime_save_session_requested=False,
                runtime_save_session_action_emitted=False,
                runtime_skill_state_barrier_active=False,
                runtime_current_turn_id="turn-size",
                logger=None,
                emitter=emitter,
            )
            actions = (
                RuntimeActionCall(
                    name=RUNTIME_ACTION_JIN_SIZE,
                    payload="220 440",
                ),
            )

            applied_count = await apply_runtime_action_calls(
                context,
                actions,
                user_message="resize avatar",
            )

            self.assertEqual(
                applied_count,
                1,
            )
            self.assertEqual(
                context.runtime_action_events[-1]["payload"],
                "w:220px h:440px",
            )
            self.assertEqual(
                context.runtime_action_events[-1]["width"],
                220,
            )
            self.assertEqual(
                context.runtime_action_events[-1]["height"],
                440,
            )
            self.assertEqual(
                emitter.events[-1]["size"],
                "w:220px h:440px",
            )

        asyncio.run(run_case())


    def test_current_jin_size_context_only_when_avatar_collapsed(self):

        context = SimpleNamespace(
            runtime_action_events=[],
            runtime_current_context_window_text="",
            runtime_avatar_panel_collapsed=True,
            runtime_avatar_current_size={
                "width": 220,
                "height": 440,
            },
        )

        self.assertIn(
            "<CURRENT_JIN_SIZE>width: 220px height: 440px</CURRENT_JIN_SIZE>",
            build_runtime_xml(
                context,
                runtime_actions={
                    "CAN_JIN_SIZE": True,
                },
            ),
        )

        self.assertIn(
            "<JIN_SIZE: 120px 120px >",
            build_runtime_action_instructions(
                (
                    RUNTIME_ACTION_JIN_SIZE,
                ),
                context,
            ),
        )

        context.runtime_avatar_panel_collapsed = False

        self.assertNotIn(
            "CURRENT_JIN_SIZE",
            build_runtime_xml(
                context,
                runtime_actions={
                    "CAN_JIN_SIZE": True,
                },
            ),
        )
        self.assertNotIn(
            "<JIN_SIZE:",
            build_runtime_action_instructions(
                (
                    RUNTIME_ACTION_JIN_SIZE,
                ),
                context,
            ),
        )


if __name__ == "__main__":
    unittest.main()
