import unittest

from utils.actions import RuntimeActionStreamFilter, extract_runtime_actions


class HtmlEscapedRuntimeMarkerTests(unittest.TestCase):

    def test_inline_marker_executes_and_keeps_surrounding_text(self):
        result = extract_runtime_actions(
            "before &lt;ATTACH_FILE_CONTENT: caption_test/4.png&gt; after",
            enabled_actions=["ATTACH_FILE_CONTENT"],
        )

        self.assertEqual(result.text, "before after")
        self.assertEqual(
            [(action.name, action.payload) for action in result.actions],
            [("ATTACH_FILE_CONTENT", "caption_test/4.png")],
        )

    def test_paired_marker_executes_generically(self):
        result = extract_runtime_actions(
            "&lt;JIN_COLOR&gt; #00f2ff &lt;/JIN_COLOR&gt;",
            enabled_actions=["JIN_COLOR"],
        )

        self.assertEqual(result.text, "")
        self.assertEqual(
            [(action.name, action.payload) for action in result.actions],
            [("JIN_COLOR", "#00f2ff")],
        )

        text = "&lt;JIN_COLOR&gt; #00f2ff &lt;/JIN_COLOR&gt;"
        for split in (1, 4, 12, 20, 31, len(text) - 2):
            stream = RuntimeActionStreamFilter(enabled_actions=["JIN_COLOR"])
            results = [
                stream.filter(text[:split]),
                stream.filter(text[split:]),
                stream.flush_result(),
            ]
            with self.subTest(split=split):
                self.assertEqual("".join(item.text for item in results), "")
                self.assertEqual(
                    [
                        (action.name, action.payload)
                        for item in results
                        for action in item.actions
                    ],
                    [("JIN_COLOR", "#00f2ff")],
                )

    def test_stream_handles_every_entity_and_marker_boundary(self):
        text = "before|&lt;ATTACH_FILE_CONTENT: caption_test/4.png&gt;|after"
        for split in range(1, len(text)):
            stream = RuntimeActionStreamFilter(
                enabled_actions=["ATTACH_FILE_CONTENT"],
            )
            results = [
                stream.filter(text[:split]),
                stream.filter(text[split:]),
                stream.flush_result(),
            ]
            with self.subTest(split=split):
                self.assertEqual(
                    "".join(result.text for result in results),
                    "before||after",
                )
                self.assertEqual(
                    [
                        (action.name, action.payload)
                        for result in results
                        for action in result.actions
                    ],
                    [("ATTACH_FILE_CONTENT", "caption_test/4.png")],
                )

    def test_quoted_and_unrelated_entities_remain_literal(self):
        for text in (
            '"&lt;ATTACH_FILE_CONTENT: caption_test/4.png&gt;"',
            "before &lt;NOT_A_RUNTIME_ACTION&gt; after",
            "math: 1 &lt; 2 &gt; 0",
        ):
            with self.subTest(text=text):
                result = extract_runtime_actions(
                    text,
                    enabled_actions=["ATTACH_FILE_CONTENT"],
                )
                self.assertEqual(result.text, text)
                self.assertFalse(result.actions)

    def test_incomplete_escaped_marker_survives_flush(self):
        text = "before &lt;ATTACH_FILE_CONTENT: caption_test/4.png"
        stream = RuntimeActionStreamFilter(
            enabled_actions=["ATTACH_FILE_CONTENT"],
        )
        results = [
            stream.filter(text[:9]),
            stream.filter(text[9:]),
            stream.flush_result(),
        ]

        self.assertEqual("".join(result.text for result in results), text)
        self.assertFalse(any(result.actions for result in results))


if __name__ == "__main__":
    unittest.main()
