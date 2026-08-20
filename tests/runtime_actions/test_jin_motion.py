import asyncio
import unittest
from types import SimpleNamespace

from clients.brain_client import apply_runtime_action_calls
from contracts.rules_assembler import (
    RUNTIME_ACTION_JIN_POSITION,
    RUNTIME_ACTION_JIN_SPEED,
    build_runtime_action_instructions,
)
from tests.helpers.runtime_actions import FakeEmitter, RuntimeActionTestCase
from utils.actions import (
    RuntimeActionCall,
    extract_runtime_actions,
    normalize_jin_position_payload,
    normalize_jin_speed_payload,
)
from utils.context.runtime_state import build_runtime_xml


class RuntimeJinMotionActionTests(RuntimeActionTestCase):

    def test_jin_position_marker_normalizes_coordinates(self):
        cases = (
            ("<JIN_POSITION> 120px 80px </JIN_POSITION>", "x:120px y:80px"),
            ("<JIN_POSITION> 120 80 </JIN_POSITION>", "x:120px y:80px"),
            ("<JIN_POSITION> x:120px y:80px </JIN_POSITION>", "x:120px y:80px"),
            ("<JIN_POSITION> -20 0 </JIN_POSITION>", "x:-20px y:0px"),
        )

        for marker, expected in cases:
            with self.subTest(marker=marker):
                result = extract_runtime_actions(
                    f"before {marker} after",
                    enabled_actions=(RUNTIME_ACTION_JIN_POSITION,),
                )
                self.assertEqual(result.text, "before after")
                self.assertEqual(len(result.actions), 1)
                self.assertEqual(result.actions[0].name, RUNTIME_ACTION_JIN_POSITION)
                self.assertEqual(result.actions[0].payload, expected)

        self.assertEqual(
            normalize_jin_position_payload("x:33 y:44"),
            "x:33px y:44px",
        )
        self.assertEqual(normalize_jin_position_payload("33"), "")

    def test_jin_speed_marker_normalizes_pixels_per_second(self):
        cases = (
            ("<JIN_SPEED> 40px/s </JIN_SPEED>", "40px/s"),
            ("<JIN_SPEED> 2400 </JIN_SPEED>", "2400px/s"),
            ("<JIN_SPEED> 600pxps </JIN_SPEED>", "600px/s"),
        )

        for marker, expected in cases:
            with self.subTest(marker=marker):
                result = extract_runtime_actions(
                    marker,
                    enabled_actions=(RUNTIME_ACTION_JIN_SPEED,),
                )
                self.assertEqual(result.text, "")
                self.assertEqual(len(result.actions), 1)
                self.assertEqual(result.actions[0].payload, expected)

        self.assertEqual(normalize_jin_speed_payload("0"), "")
        self.assertEqual(normalize_jin_speed_payload("fast"), "")

    def test_motion_actions_emit_in_model_marker_order(self):
        async def run_case():
            emitter = FakeEmitter()
            context = SimpleNamespace(
                runtime_action_events=[],
                runtime_search_calls=[],
                runtime_loaded_skills=[],
                runtime_save_session_requested=False,
                runtime_save_session_action_emitted=False,
                runtime_skill_state_barrier_active=False,
                runtime_current_turn_id="turn-motion",
                runtime_avatar_move_speed=900,
                runtime_avatar_current_position={},
                logger=None,
                emitter=emitter,
            )
            actions = (
                RuntimeActionCall(
                    name=RUNTIME_ACTION_JIN_SPEED,
                    payload="40px/s",
                ),
                RuntimeActionCall(
                    name=RUNTIME_ACTION_JIN_POSITION,
                    payload="80 120",
                ),
            )

            applied_count = await apply_runtime_action_calls(
                context,
                actions,
                user_message="crawl there",
            )

            self.assertEqual(applied_count, 2)
            completed = [
                event
                for event in emitter.events
                if event.get("status") == "completed"
                and event.get("action") in {"jin_speed", "jin_position"}
            ]
            self.assertEqual(
                [event["action"] for event in completed],
                ["jin_speed", "jin_position"],
            )
            self.assertEqual(completed[0]["speed"], 40)
            self.assertEqual(completed[1]["x"], 80)
            self.assertEqual(completed[1]["y"], 120)
            self.assertEqual(context.runtime_avatar_move_speed, 40)
            self.assertEqual(
                context.runtime_avatar_current_position,
                {"x": 80, "y": 120},
            )

        asyncio.run(run_case())

    def test_runtime_context_exposes_window_position_and_speed(self):
        context = SimpleNamespace(
            runtime_action_events=[],
            runtime_current_context_window_text="",
            runtime_avatar_panel_collapsed=True,
            runtime_avatar_current_size={"width": 100, "height": 100},
            runtime_avatar_current_position={"x": 1500, "y": 40},
            runtime_avatar_window_size={"width": 1920, "height": 1080},
            runtime_avatar_move_speed=55,
        )

        xml = build_runtime_xml(
            context,
            runtime_actions={
                "CAN_JIN_POSITION": True,
                "CAN_JIN_SPEED": True,
            },
        )

        self.assertIn(
            "<CURRENT_JIN_POSITION>x: 1500px y: 40px</CURRENT_JIN_POSITION>",
            xml,
        )
        self.assertIn(
            "<CURRENT_JIN_SPEED>55px/s</CURRENT_JIN_SPEED>",
            xml,
        )
        self.assertIn(
            "<CURRENT_WINDOW_SIZE>width: 1920px height: 1080px</CURRENT_WINDOW_SIZE>",
            xml,
        )

        instructions = build_runtime_action_instructions(
            (RUNTIME_ACTION_JIN_SPEED, RUNTIME_ACTION_JIN_POSITION),
            context,
        )
        self.assertIn("<JIN_SPEED> 600px/s </JIN_SPEED>", instructions)
        self.assertIn("<JIN_POSITION> 120px 80px </JIN_POSITION>", instructions)

        context.runtime_avatar_panel_collapsed = False
        instructions = build_runtime_action_instructions(
            (RUNTIME_ACTION_JIN_SPEED, RUNTIME_ACTION_JIN_POSITION),
            context,
        )
        self.assertNotIn("<JIN_SPEED>", instructions)
        self.assertNotIn("<JIN_POSITION>", instructions)
        expanded_xml = build_runtime_xml(context)
        self.assertNotIn("CURRENT_JIN_POSITION", expanded_xml)
        self.assertNotIn("CURRENT_JIN_SPEED", expanded_xml)
        self.assertNotIn("CURRENT_WINDOW_SIZE", expanded_xml)


if __name__ == "__main__":
    unittest.main()
