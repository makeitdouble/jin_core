import unittest

from utils.actions import (
    RuntimeActionCall,
    RuntimeActionStreamFilter,
    extract_runtime_actions,
)


class BarePrefixActionFallbackTests(unittest.TestCase):

    def test_plain_extractor_stays_strict_without_explicit_fallback(self):
        text = "JIN_REACTION: 🔥\nhello"

        result = extract_runtime_actions(
            text,
            enabled_actions=("JIN_REACTION",),
        )

        self.assertEqual(result.text, text)
        self.assertEqual(result.actions, ())
        self.assertEqual(result.removed_markers, ())

    def test_leading_reaction_line_executes_and_leaves_no_blank_line(self):
        result = extract_runtime_actions(
            "\n\nJIN_REACTION: 🔥\n\nhello",
            enabled_actions=("JIN_REACTION",),
            allow_bare_prefix_fallback=True,
        )

        self.assertEqual(result.text, "hello")
        self.assertEqual(
            result.actions,
            (RuntimeActionCall(name="JIN_REACTION", payload="🔥"),),
        )
        self.assertEqual(
            result.removed_markers,
            ("JIN_REACTION: 🔥",),
        )

    def test_invalid_reaction_payload_is_ordinary_text(self):
        text = "JIN_REACTION: это должен быть emoji\nhello"

        result = extract_runtime_actions(
            text,
            enabled_actions=("JIN_REACTION",),
            allow_bare_prefix_fallback=True,
        )

        self.assertEqual(result.text, text)
        self.assertEqual(result.actions, ())
        self.assertEqual(result.removed_markers, ())

    def test_text_first_disables_bare_fallback_but_not_normal_markers(self):
        result = extract_runtime_actions(
            "hello\nJIN_REACTION: 🔥\n<JIN_REACTION: 😂 >",
            enabled_actions=("JIN_REACTION",),
            allow_bare_prefix_fallback=True,
        )

        self.assertEqual(
            result.text,
            "hello\nJIN_REACTION: 🔥",
        )
        self.assertEqual(
            result.actions,
            (RuntimeActionCall(name="JIN_REACTION", payload="😂"),),
        )

    def test_all_jin_payload_actions_support_leading_bare_line(self):
        cases = (
            ("JIN_COLOR", "#f00", "#ff0000"),
            ("JIN_REACTION", "🔥", "🔥"),
            ("JIN_SIZE", "120", "120px"),
            ("JIN_POSITION", "x:10 y:20", "x:10px y:20px"),
            ("JIN_SPEED", "900", "900px/s"),
        )

        for action_name, raw_payload, expected_payload in cases:
            with self.subTest(action=action_name):
                result = extract_runtime_actions(
                    f"{action_name}: {raw_payload}\nhello",
                    enabled_actions=(action_name,),
                    allow_bare_prefix_fallback=True,
                )

                self.assertEqual(result.text, "hello")
                self.assertEqual(len(result.actions), 1)
                self.assertEqual(result.actions[0].name, action_name)
                self.assertEqual(result.actions[0].payload, expected_payload)

    def test_short_colon_attach_file_content_is_supported(self):
        result = extract_runtime_actions(
            "ATTACH_FILE_CONTENT: src/main.py\nhello",
            enabled_actions=("ATTACH_FILE_CONTENT",),
            allow_bare_prefix_fallback=True,
        )

        self.assertEqual(result.text, "hello")
        self.assertEqual(
            result.actions,
            (RuntimeActionCall(name="ATTACH_FILE_CONTENT", payload="src/main.py"),),
        )

    def test_other_payload_short_actions_use_same_exact_line_fallback(self):
        cases = (
            ("WEB_SEARCH", "blue tomato", '{"query": "blue tomato"}'),
            ("LOAD_DELAYED_MEMORY", "abc123", "abc123"),
            ("UNLOAD_DELAYED_MEMORY", "abc123", "abc123"),
            ("LOAD_SKILL", "python", "python"),
            ("UNLOAD_SKILL", "python", "python"),
            ("DELETE_ACTIVE_MEMORY", "abc123", "abc123"),
            ("RECALL_FACT_CONTEXT", "F12", "F12"),
        )

        for action_name, raw_payload, expected_payload in cases:
            with self.subTest(action=action_name):
                result = extract_runtime_actions(
                    f"{action_name}: {raw_payload}\nhello",
                    enabled_actions=(action_name,),
                    allow_bare_prefix_fallback=True,
                )

                self.assertEqual(result.text, "hello")
                self.assertEqual(len(result.actions), 1)
                self.assertEqual(result.actions[0].name, action_name)
                self.assertEqual(result.actions[0].payload, expected_payload)

    def test_id_actions_require_strict_id_shape_in_bare_fallback(self):
        invalid = extract_runtime_actions(
            "DELETE_ACTIVE_MEMORY: active_memory_id=e2qxe7 STATUS=deleted\nhello",
            enabled_actions=("DELETE_ACTIVE_MEMORY",),
            allow_bare_prefix_fallback=True,
        )
        self.assertEqual(
            invalid.text,
            "DELETE_ACTIVE_MEMORY: active_memory_id=e2qxe7 STATUS=deleted\nhello",
        )
        self.assertEqual(invalid.actions, ())

        recall_invalid = extract_runtime_actions(
            "RECALL_FACT_CONTEXT: this should be F123\nhello",
            enabled_actions=("RECALL_FACT_CONTEXT",),
            allow_bare_prefix_fallback=True,
        )
        self.assertEqual(recall_invalid.actions, ())

        recall_valid = extract_runtime_actions(
            "RECALL_FACT_CONTEXT: F123\nhello",
            enabled_actions=("RECALL_FACT_CONTEXT",),
            allow_bare_prefix_fallback=True,
        )
        self.assertEqual(recall_valid.text, "hello")
        self.assertEqual(recall_valid.actions[0].payload, "F123")

    def test_block_and_unknown_action_names_are_not_guessed(self):
        for text, action_name in (
            ('SAVE_DELAYED_MEMORY: {"title":"x"}\nhello', "SAVE_DELAYED_MEMORY"),
            ("SOME_ACTION: value\nhello", "JIN_REACTION"),
        ):
            with self.subTest(text=text):
                result = extract_runtime_actions(
                    text,
                    enabled_actions=(action_name,),
                    allow_bare_prefix_fallback=True,
                )
                self.assertEqual(result.text, text)
                self.assertEqual(result.actions, ())

    def test_stream_holds_split_bare_line_until_newline(self):
        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=("JIN_REACTION",),
        )

        first = stream_filter.filter("JIN_")
        second = stream_filter.filter("REACTION: 🔥")
        third = stream_filter.filter("\nhello")

        self.assertEqual(first.text, "")
        self.assertEqual(second.text, "")
        self.assertEqual(third.text, "hello")
        self.assertEqual(
            third.actions,
            (RuntimeActionCall(name="JIN_REACTION", payload="🔥"),),
        )
        self.assertEqual(stream_filter.flush(), "")

    def test_stream_flush_accepts_valid_bare_action_at_end_of_output(self):
        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=("JIN_REACTION",),
        )

        pending = stream_filter.filter("JIN_REACTION: 🔥")
        flushed = stream_filter.flush_result()

        self.assertEqual(pending.text, "")
        self.assertEqual(flushed.text, "")
        self.assertEqual(
            flushed.actions,
            (RuntimeActionCall(name="JIN_REACTION", payload="🔥"),),
        )

    def test_stream_bare_reaction_is_removed_even_when_normal_marker_is_preserved(self):
        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=("JIN_REACTION",),
            preserve_action_marker=(
                lambda _raw, action: action.name == "JIN_REACTION"
            ),
        )

        result = stream_filter.filter(
            "JIN_REACTION: 😂\nhello"
        )

        self.assertEqual(result.text, "hello")
        self.assertEqual(
            result.actions,
            (RuntimeActionCall(name="JIN_REACTION", payload="😂"),),
        )
        self.assertEqual(
            result.removed_markers,
            ("JIN_REACTION: 😂",),
        )

    def test_stream_invalid_bare_line_turns_fallback_off(self):
        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=("JIN_REACTION",),
        )

        first = stream_filter.filter(
            "JIN_REACTION: это должен быть emoji\n"
        )
        second = stream_filter.filter(
            "JIN_REACTION: 🔥\n"
        )
        tail = stream_filter.flush()

        combined = first.text + second.text + tail

        self.assertEqual(
            combined,
            "JIN_REACTION: это должен быть emoji\nJIN_REACTION: 🔥\n",
        )
        self.assertEqual(first.actions, ())
        self.assertEqual(second.actions, ())

    def test_stream_after_visible_text_still_executes_angle_markers(self):
        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=("JIN_REACTION",),
        )

        visible = stream_filter.filter("hello ")
        marker = stream_filter.filter("<JIN_REACTION: 😂 >")
        tail = stream_filter.filter("world")

        self.assertEqual(visible.text, "hello ")
        self.assertEqual(marker.text, "")
        self.assertEqual(
            marker.actions,
            (RuntimeActionCall(name="JIN_REACTION", payload="😂"),),
        )
        self.assertEqual(tail.text, "world")


if __name__ == "__main__":
    unittest.main()
