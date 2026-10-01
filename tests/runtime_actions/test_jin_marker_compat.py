import unittest

from contracts.rules_assembler import (
    RUNTIME_ACTION_JIN_COLOR,
    RUNTIME_ACTION_JIN_POSITION,
    RUNTIME_ACTION_JIN_SIZE,
    RUNTIME_ACTION_JIN_SPEED,
)
from tests.helpers.runtime_actions import RuntimeActionTestCase
from utils.actions import RuntimeActionStreamFilter, extract_runtime_actions


class RuntimeJinMarkerCompatibilityTests(RuntimeActionTestCase):

    def test_jin_markers_accept_canonical_colon_and_space_payload_forms(self):
        cases = (
            (
                RUNTIME_ACTION_JIN_COLOR,
                (
                    "<JIN_COLOR> #00f2ff </JIN_COLOR>",
                    "< JIN_COLOR : #00f2ff >",
                    "< JIN_COLOR #00f2ff >",
                ),
                "#00f2ff",
            ),
            (
                RUNTIME_ACTION_JIN_SIZE,
                (
                    "<JIN_SIZE> 390px 300px </JIN_SIZE>",
                    "< JIN_SIZE : 390px 300px >",
                    "< JIN_SIZE 390px 300px >",
                ),
                "w:390px h:300px",
            ),
            (
                RUNTIME_ACTION_JIN_POSITION,
                (
                    "<JIN_POSITION> x:1500px y:50px </JIN_POSITION>",
                    "< JIN_POSITION : x:1500px y:50px >",
                    "< JIN_POSITION x:1500px y:50px >",
                ),
                "x:1500px y:50px",
            ),
            (
                RUNTIME_ACTION_JIN_SPEED,
                (
                    "<JIN_SPEED> 600px/s </JIN_SPEED>",
                    "< JIN_SPEED : 600px/s >",
                    "< JIN_SPEED 600px/s >",
                ),
                "600px/s",
            ),
        )

        for action_name, markers, expected_payload in cases:
            for marker in markers:
                with self.subTest(action=action_name, marker=marker):
                    result = extract_runtime_actions(
                        f"before {marker} after",
                        enabled_actions=(action_name,),
                    )

                    self.assertEqual(result.text, "before after")
                    self.assertEqual(len(result.actions), 1)
                    self.assertEqual(result.actions[0].name, action_name)
                    self.assertEqual(result.actions[0].payload, expected_payload)

    def test_inline_and_canonical_jin_markers_can_be_mixed(self):
        result = extract_runtime_actions(
            (
                "<JIN_COLOR: #ff0000 > hello "
                "<JIN_COLOR> #00ff00 </JIN_COLOR>"
            ),
            enabled_actions=(RUNTIME_ACTION_JIN_COLOR,),
        )

        self.assertEqual(result.text, "hello")
        self.assertEqual(
            [action.payload for action in result.actions],
            ["#ff0000", "#00ff00"],
        )

    def test_inline_jin_marker_is_held_and_parsed_across_stream_chunks(self):
        for marker_chunks in (
            ("before < JIN_COLOR", " : #00", "f2ff > after"),
            ("before <JIN_COLOR", " #00", "f2ff> after"),
        ):
            with self.subTest(marker_chunks=marker_chunks):
                stream_filter = RuntimeActionStreamFilter(
                    enabled_actions=(RUNTIME_ACTION_JIN_COLOR,),
                )

                first = stream_filter.filter(marker_chunks[0])
                second = stream_filter.filter(marker_chunks[1])
                third = stream_filter.filter(marker_chunks[2])
                final = stream_filter.flush_result()

                self.assertEqual(first.text, "before ")
                self.assertEqual(first.actions, ())
                self.assertEqual(second.text, "")
                self.assertEqual(second.actions, ())
                self.assertEqual(third.text, "after")
                self.assertEqual(
                    [action.payload for action in third.actions],
                    ["#00f2ff"],
                )
                self.assertEqual(final.text, "")


if __name__ == "__main__":
    unittest.main()
