import asyncio
import unittest

from clients import (
    apply_runtime_action_calls,
)
from runtime import (
    DEEP_THOUGHT_ACTION,
    SEARCH_ACTION_CLOSE,
    SEARCH_ACTION_OPEN,
)
from utils.runtime_actions import (
    RuntimeActionCall,
    RuntimeActionStreamFilter,
    extract_search_query,
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

    def test_extracts_enabled_search_action(self):

        result = extract_runtime_actions(
            (
                "before "
                f'{SEARCH_ACTION_OPEN}{{"query":"python news"}}'
                f"{SEARCH_ACTION_CLOSE} after"
            ),
            enabled_actions=[
                "CAN_SEARCH",
            ],
        )

        self.assertEqual(
            result.text,
            "before  after",
        )

        self.assertEqual(
            result.count("SEARCH"),
            1,
        )

        self.assertEqual(
            result.search_queries,
            (
                "python news",
            ),
        )

    def test_extracts_tool_call_prefixed_search_action(self):

        result = extract_runtime_actions(
            (
                "before "
                '<|tool_call>call:RUNTIME_ACTION:SEARCH>'
                '{"query":"marijuana"}'
                f"{SEARCH_ACTION_CLOSE} after"
            ),
            enabled_actions=[
                "CAN_SEARCH",
            ],
        )

        self.assertEqual(
            result.text,
            "before  after",
        )

        self.assertEqual(
            result.count("SEARCH"),
            1,
        )

        self.assertEqual(
            result.search_queries,
            (
                "marijuana",
            ),
        )

    def test_preserves_canonical_search_action_text_when_requested(self):

        result = extract_runtime_actions(
            (
                "before "
                '<|tool_call>call:RUNTIME_ACTION:SEARCH>'
                '{"query":"marijuana"}'
                f"{SEARCH_ACTION_CLOSE} after"
            ),
            enabled_actions=[
                "CAN_SEARCH",
            ],
            preserve_action_text=True,
        )

        self.assertEqual(
            result.text,
            (
                "before "
                f'{SEARCH_ACTION_OPEN}{{"query":"marijuana"}}'
                f"{SEARCH_ACTION_CLOSE} after"
            ),
        )

        self.assertEqual(
            result.search_queries,
            (
                "marijuana",
            ),
        )

    def test_ignores_disabled_search_action(self):

        text = (
            f'{SEARCH_ACTION_OPEN}{{"query":"python news"}}'
            f"{SEARCH_ACTION_CLOSE}"
        )

        result = extract_runtime_actions(
            text,
            enabled_actions=[],
        )

        self.assertEqual(
            result.text,
            text,
        )

        self.assertEqual(
            result.count("SEARCH"),
            0,
        )

    def test_stream_filter_handles_split_search_action(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_SEARCH",
            ],
        )

        first = stream_filter.filter(
            f'before {SEARCH_ACTION_OPEN}{{"query":"py'
        )

        second = stream_filter.filter(
            f'thon"}}{SEARCH_ACTION_CLOSE} after'
        )

        self.assertEqual(
            first.text,
            "before ",
        )

        self.assertEqual(
            first.count("SEARCH"),
            0,
        )

        self.assertEqual(
            second.text,
            " after",
        )

        self.assertEqual(
            second.search_queries,
            (
                "python",
            ),
        )

        self.assertEqual(
            stream_filter.flush(),
            "",
        )

    def test_stream_filter_handles_split_tool_call_prefixed_search_action(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_SEARCH",
            ],
        )

        first = stream_filter.filter(
            (
                "before "
                '<|tool_call>call:RUNTIME_ACTION:SEARCH>'
                '{"query":"mari'
            )
        )

        second = stream_filter.filter(
            f'juana"}}{SEARCH_ACTION_CLOSE} after'
        )

        self.assertEqual(
            first.text,
            "before ",
        )

        self.assertEqual(
            first.count("SEARCH"),
            0,
        )

        self.assertEqual(
            second.text,
            " after",
        )

        self.assertEqual(
            second.search_queries,
            (
                "marijuana",
            ),
        )

        self.assertEqual(
            stream_filter.flush(),
            "",
        )

    def test_stream_filter_preserves_complete_search_action_when_requested(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_SEARCH",
            ],
            preserve_action_text=True,
        )

        first = stream_filter.filter(
            (
                "before "
                '<|tool_call>call:RUNTIME_ACTION:SEARCH>'
                '{"query":"mari'
            )
        )

        second = stream_filter.filter(
            f'juana"}}{SEARCH_ACTION_CLOSE} after'
        )

        self.assertEqual(
            first.text,
            "before ",
        )

        self.assertEqual(
            second.text,
            (
                f'{SEARCH_ACTION_OPEN}{{"query":"marijuana"}}'
                f"{SEARCH_ACTION_CLOSE} after"
            ),
        )

        self.assertEqual(
            second.search_queries,
            (
                "marijuana",
            ),
        )

    def test_stream_filter_preserves_mentioned_search_tag_without_stalling(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_SEARCH",
            ],
            preserve_action_text=True,
        )

        first = stream_filter.filter(
            "like `<RUNTIME_ACTION:SEARCH>"
        )

        second = stream_filter.filter(
            "`) is just a tag name"
        )

        self.assertEqual(
            first.text,
            "like `<RUNTIME_ACTION:SEARCH>",
        )

        self.assertEqual(
            first.actions,
            (),
        )

        self.assertEqual(
            second.text,
            "`) is just a tag name",
        )

        self.assertEqual(
            second.actions,
            (),
        )

    def test_stream_filter_parses_search_when_payload_follows_preserved_open_tag(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_SEARCH",
            ],
            preserve_action_text=True,
        )

        first = stream_filter.filter(
            f"before {SEARCH_ACTION_OPEN}"
        )

        second = stream_filter.filter(
            f'{{"query":"marijuana"}}{SEARCH_ACTION_CLOSE} after'
        )

        self.assertEqual(
            first.text,
            f"before {SEARCH_ACTION_OPEN}",
        )

        self.assertEqual(
            first.actions,
            (),
        )

        self.assertEqual(
            second.text,
            f'{{"query":"marijuana"}}{SEARCH_ACTION_CLOSE} after',
        )

        self.assertEqual(
            second.search_queries,
            (
                "marijuana",
            ),
        )

    def test_removes_stray_tool_call_marker(self):

        result = extract_runtime_actions(
            "before <|tool_call> after"
        )

        self.assertEqual(
            result.text,
            "before  after",
        )

        self.assertEqual(
            result.actions,
            (),
        )

    def test_stream_filter_removes_split_tool_call_marker(self):

        stream_filter = RuntimeActionStreamFilter()

        first = stream_filter.filter(
            "before <|tool"
        )

        second = stream_filter.filter(
            "_call> after"
        )

        self.assertEqual(
            first.text,
            "before ",
        )

        self.assertEqual(
            second.text,
            " after",
        )

        self.assertEqual(
            stream_filter.flush(),
            "",
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
                        name="SEARCH",
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
                "runtime_search_calls",
            ),
            [
                {
                    "id": "search_001",
                    "query": "test",
                },
            ],
        )
        self.assertEqual(
            getattr(
                context,
                "runtime_action_events",
            )[0]["id"],
            "search_001",
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
