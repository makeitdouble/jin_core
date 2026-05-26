import unittest

from contracts.context_contract import (
    DEEP_THOUGHT_ACTION,
)
from utils.runtime_actions import (
    RuntimeActionStreamFilter,
    extract_runtime_actions,
)


class RuntimeActionTests(unittest.TestCase):

    def test_extracts_and_removes_deep_thought_marker(self):

        result = extract_runtime_actions(
            f"before {DEEP_THOUGHT_ACTION} after"
        )

        self.assertEqual(
            result.text,
            "before  after",
        )

        self.assertEqual(
            result.deep_thought_count,
            1,
        )

    def test_stream_filter_handles_split_marker(self):

        stream_filter = RuntimeActionStreamFilter()

        first = stream_filter.filter(
            "before <RUNTIME_ACTION"
        )

        second = stream_filter.filter(
            ":DEEP_THOUGHT/> after"
        )

        self.assertEqual(
            first.text,
            "before ",
        )

        self.assertEqual(
            first.deep_thought_count,
            0,
        )

        self.assertEqual(
            second.text,
            " after",
        )

        self.assertEqual(
            second.deep_thought_count,
            1,
        )

        self.assertEqual(
            stream_filter.flush(),
            "",
        )

    def test_stream_filter_flushes_false_partial(self):

        stream_filter = RuntimeActionStreamFilter()

        result = stream_filter.filter(
            "hello <RUNTIME"
        )

        self.assertEqual(
            result.text,
            "hello ",
        )

        self.assertEqual(
            stream_filter.flush(),
            "<RUNTIME",
        )

    def test_extracts_multiple_markers(self):

        result = extract_runtime_actions(
            (
                DEEP_THOUGHT_ACTION
                + "answer"
                + DEEP_THOUGHT_ACTION
            )
        )

        self.assertEqual(
            result.text,
            "answer",
        )

        self.assertEqual(
            result.deep_thought_count,
            2,
        )


if __name__ == "__main__":
    unittest.main()
