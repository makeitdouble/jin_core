import unittest
from types import SimpleNamespace

from clients.brain_client import (
    MAX_PREVIOUS_THINK_CHARS,
    MAX_PREVIOUS_THINK_SECTION_CHARS,
    build_brain_runtime_context,
    build_brain_payload,
    extract_previous_think_tail,
    record_previous_think,
)


class PreviousThinkTailTests(unittest.TestCase):

    def test_extracts_only_allowed_numbered_sections(self):

        raw_think = (
            "1. **Analyze User Input:**\n"
            "   user asks for a feature\n"
            "2. **Check Context/State:**\n"
            "   inspect payload code\n"
            "3. **Determine JIN's Tone and Persona:**\n"
            "   should not leak\n"
            "4. **Formulate Response:**\n"
            "   answer in Russian\n"
            "5. **Refining:**\n"
            "   should not leak either\n"
        )

        result = extract_previous_think_tail(
            raw_think
        )

        self.assertEqual(
            result["sections_found"],
            [
                "Analyze User Input",
                "Check Context/State",
                "Formulate Response",
            ],
        )
        self.assertIn(
            "Analyze User Input:",
            result["text"],
        )
        self.assertIn(
            "Check Context/State:",
            result["text"],
        )
        self.assertIn(
            "Formulate Response:",
            result["text"],
        )
        self.assertNotIn(
            "1. **",
            result["text"],
        )
        self.assertNotIn(
            "Determine JIN",
            result["text"],
        )
        self.assertNotIn(
            "Refining",
            result["text"],
        )

    def test_matches_optional_markdown_colon_and_any_number(self):

        raw_think = (
            "7. Analyze User Input\n"
            "   plain title\n"
            "11. **Check Context/State**:\n"
            "   bold title with external colon\n"
            "19. **Formulate Response:** draft response\n"
            "   title with same-line content\n"
            "20. Other Section\n"
            "   ignored\n"
        )

        result = extract_previous_think_tail(
            raw_think
        )

        self.assertEqual(
            result["sections_found"],
            [
                "Analyze User Input",
                "Check Context/State",
                "Formulate Response",
            ],
        )
        self.assertIn(
            "Formulate Response: draft response",
            result["text"],
        )
        self.assertNotIn(
            "20. Other Section",
            result["text"],
        )

    def test_matches_alias_group_and_logs_canonical_title(self):

        raw_think = (
            "1. **Analyze Intent:** The intent is playful.\n"
            "2. **Apply Persona Constraints:**\n"
            "   ignored\n"
            "3. **Check Context/State:**\n"
            "   current session state\n"
        )

        result = extract_previous_think_tail(
            raw_think
        )

        self.assertEqual(
            result["sections_found"],
            [
                "Analyze User Input",
                "Check Context/State",
            ],
        )
        self.assertIn(
            "Analyze Intent:",
            result["text"],
        )
        self.assertNotIn(
            "Apply Persona",
            result["text"],
        )

    def test_matches_check_memory_context_alias(self):

        raw_think = (
            "1. **Identify the Goal:**\n"
            "   ignored\n"
            "2. **Check Memory/Context:** The runtime memory shows state.\n"
            "   `last_jin_response`: saved recommendation.\n"
            "3. **Determine Tone/Style:**\n"
            "   ignored\n"
        )

        result = extract_previous_think_tail(
            raw_think
        )

        self.assertEqual(
            result["sections_found"],
            [
                "Check Context/State",
            ],
        )
        self.assertIn(
            "Check Memory/Context: The runtime memory shows state.",
            result["text"],
        )
        self.assertNotIn(
            "Identify the Goal",
            result["text"],
        )

    def test_matches_last_jin_response_with_or_without_quotes(self):

        raw_think = (
            "1. **Check `last_jin_response`:**\n"
            "   latest response summary\n"
            "2. **Check \"last_jin_response\":**\n"
            "   quoted response summary\n"
            "3. **Check 'last_jin_response':**\n"
            "   single quoted response summary\n"
            "4. **Check last_jin_response:**\n"
            "   plain response summary\n"
        )

        result = extract_previous_think_tail(
            raw_think
        )

        self.assertEqual(
            result["sections_found"],
            [
                "Check last_jin_response",
                "Check last_jin_response",
                "Check last_jin_response",
                "Check last_jin_response",
            ],
        )
        self.assertIn(
            "Check last_jin_response:",
            result["text"],
        )
        self.assertNotIn(
            "`last_jin_response`",
            result["text"],
        )

    def test_cleans_number_and_markdown_from_inline_heading(self):

        raw_think = (
            "1. **Analyze the Request:** The user asked \"ты кто\" "
            "(Ty kto), which translates to \"Who are you?\".\n"
            "2. **Apply Persona Constraints:**\n"
            "   ignored\n"
        )

        result = extract_previous_think_tail(
            raw_think
        )

        self.assertEqual(
            result["text"],
            (
                "Analyze the Request: The user asked \"ты кто\" "
                "(Ty kto), which translates to \"Who are you?\"."
            ),
        )
        self.assertEqual(
            result["sections_found"],
            [
                "Analyze User Input",
            ],
        )

    def test_build_payload_keeps_user_text_only(self):

        context = SimpleNamespace(
            runtime_previous_think_raw=(
                "1. **Analyze User Input:**\n"
                "   keep this\n"
                "2. **Unrelated:**\n"
                "   drop this\n"
            )
        )

        payload = build_brain_payload(
            "hello",
            context=context,
        )

        self.assertEqual(
            payload,
            "hello",
        )

    def test_runtime_context_places_previous_think_after_activity(self):

        context = SimpleNamespace(
            deep_thought_count=0,
            turn_number=1,
            user_message_count=1,
            assistant_message_count=1,
            runtime_memory="",
            runtime_l3_session_memory="",
            session_memory="",
            runtime_session_event_snapshots=[],
            runtime_l2_memory="",
            runtime_zero_diff_alert=None,
            runtime_search_result="",
            runtime_search_result_id="",
            runtime_previous_think_raw=(
                "1. **Analyze User Input:**\n"
                "   keep this\n"
                "2. **Unrelated:**\n"
                "   drop this\n"
            ),
            runtime_conversation_activity_diff=100,
        )

        runtime_context = build_brain_runtime_context(
            context,
        )

        activity_index = runtime_context.index(
            "</CONVERSATION_ACTIVITY>"
        )
        previous_think_index = runtime_context.index(
            "<LOW_PRIORITY_PREVIOUS_THINK>"
        )

        self.assertGreater(
            previous_think_index,
            activity_index,
        )
        self.assertIn(
            "keep this",
            runtime_context,
        )
        self.assertIn(
            "Analyze User Input:",
            runtime_context,
        )
        self.assertNotIn(
            "1. **Analyze User Input:**",
            runtime_context,
        )
        self.assertNotIn(
            "drop this",
            runtime_context,
        )
        self.assertEqual(
            context.runtime_previous_think_payload_log,
            {
                "previous_think_appended": True,
                "previous_think_sections_found": [
                    "Analyze User Input",
                ],
                "previous_think_chars": len(
                    "Analyze User Input:\n"
                    "   keep this"
                ),
                "previous_think_trimmed": False,
            },
        )

    def test_runtime_context_skips_block_when_no_sections_match(self):

        context = SimpleNamespace(
            deep_thought_count=0,
            turn_number=1,
            user_message_count=1,
            assistant_message_count=1,
            runtime_memory="",
            runtime_l3_session_memory="",
            session_memory="",
            runtime_session_event_snapshots=[],
            runtime_l2_memory="",
            runtime_zero_diff_alert=None,
            runtime_search_result="",
            runtime_search_result_id="",
            runtime_previous_think_raw=(
                "1. **Determine Tone:**\n"
                "   nothing useful here\n"
            ),
            runtime_conversation_activity_diff=100,
        )

        runtime_context = build_brain_runtime_context(
            context,
        )

        self.assertNotIn(
            "<LOW_PRIORITY_PREVIOUS_THINK>",
            runtime_context,
        )
        self.assertEqual(
            context.runtime_previous_think_payload_log,
            {
                "previous_think_appended": False,
                "previous_think_sections_found": [],
                "previous_think_chars": 0,
                "previous_think_trimmed": False,
            },
        )

    def test_extract_caps_text_by_cutting_from_end(self):

        raw_think = (
            "1. **Analyze User Input:**\n"
            + ("x" * MAX_PREVIOUS_THINK_SECTION_CHARS)
            + "\n"
            "2. **Check Context/State:**\n"
            + ("y" * MAX_PREVIOUS_THINK_SECTION_CHARS)
            + "\n"
            "3. **Formulate Response:**\n"
            + ("z" * MAX_PREVIOUS_THINK_SECTION_CHARS)
        )

        result = extract_previous_think_tail(
            raw_think
        )

        self.assertEqual(
            result["chars"],
            MAX_PREVIOUS_THINK_CHARS,
        )
        self.assertTrue(
            result["trimmed"],
        )
        self.assertTrue(
            result["text"].startswith(
                "Analyze User Input:"
            )
        )

    def test_caps_each_section_before_total_cap(self):

        raw_think = (
            "1. **Analyze User Input:**\n"
            + ("x" * (MAX_PREVIOUS_THINK_SECTION_CHARS + 100))
            + "\n"
            "2. **Check Context/State:**\n"
            "   still included\n"
        )

        result = extract_previous_think_tail(
            raw_think
        )

        self.assertTrue(
            result["trimmed"],
        )
        self.assertIn(
            "Analyze User Input:",
            result["text"],
        )
        self.assertIn(
            "Check Context/State:",
            result["text"],
        )
        self.assertIn(
            "still included",
            result["text"],
        )
        first_section = result["text"].split(
            "\n\n",
            1,
        )[0]
        self.assertLessEqual(
            len(
                first_section
            ),
            MAX_PREVIOUS_THINK_SECTION_CHARS,
        )

    def test_record_previous_think_replaces_existing_value(self):

        context = SimpleNamespace(
            runtime_previous_think_raw="old think",
        )

        record_previous_think(
            context,
            "new think",
        )

        self.assertEqual(
            context.runtime_previous_think_raw,
            "new think",
        )


if __name__ == "__main__":
    unittest.main()
