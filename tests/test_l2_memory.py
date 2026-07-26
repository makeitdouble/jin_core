import unittest
from types import (
    SimpleNamespace,
)
from runtime.L2_memory_rules import (
    BEHAVIOR_VS_INTENT,
    CONFIRMABLE_KEYS,
    EVIDENCE_LINE_LIFECYCLE,
    L2_PATCH_WINDOW,
    OCCURRENCE_COUNTING,
    OUTPUT_FORMAT,
    PATTERN_EVIDENCE_LINES,
    PATTERN_FAMILY_DEDUPLICATION,
    ROLE,
    RUNTIME_L2_MEMORY_SYSTEM_PROMPT,
    SELF_LEARNING_GUARD,
    SPAN_METADATA,
)
from runtime.L1_memory_utils import (
    build_runtime_memory_context_text,
)
from runtime.L2_memory_utils import (
    build_runtime_l2_memory_system_prompt,
    extract_runtime_l2_pattern_evidence_lines,
    merge_runtime_l2_pattern_evidence_memory,
    normalize_l2_pattern_evidence_example,
    remove_runtime_l2_pattern_evidence_lines,
)
from runtime.L2_memory import (
    maybe_summarize_runtime_l2_memory,
    record_runtime_l1_diff,
)
from config_loader import (
    config,
)
from tests.helpers.memory import (
    FakeLogger,
    FakeServiceClient,
)

class L2MemoryTests(
    unittest.IsolatedAsyncioTestCase
):

    def test_runtime_l2_memory_prompt_defines_pattern_layer(self):

            prompt = build_runtime_l2_memory_system_prompt()

            self.assertEqual(
                prompt,
                RUNTIME_L2_MEMORY_SYSTEM_PROMPT,
            )

            # Verify that the builder keeps every dedicated L2 rules section.
            for rules_section in (
                    ROLE,
                    OUTPUT_FORMAT,
                    BEHAVIOR_VS_INTENT,
                    SPAN_METADATA,
                    OCCURRENCE_COUNTING,
                    PATTERN_EVIDENCE_LINES,
                    EVIDENCE_LINE_LIFECYCLE,
                    PATTERN_FAMILY_DEDUPLICATION,
                    SELF_LEARNING_GUARD,
                    CONFIRMABLE_KEYS,
            ):
                self.assertIn(
                    rules_section,
                    prompt,
                )

    def test_l2_pattern_evidence_merge_preserves_first_seen_and_deduplicates(self):

            merged = merge_runtime_l2_pattern_evidence_memory(
                previous_memory=(
                    "possible pattern: old line. Occurrences: 1; "
                    "first_seen_snapshot: 5; last_seen_snapshot: 5; "
                    "evidence summary: banana question; confidence: medium\n"
                    'L2_pattern_evidence_1: user repeatedly sending message - "что такое бананы" '
                    "[ first_seen_turn_snapshot: 5 ] [ last_seen_turn_snapshot: 5 ] [ occurrences: 1 ]"
                ),
                candidate_memory=(
                    "possible pattern: updated line. Occurrences: 2; "
                    "first_seen_snapshot: 5; last_seen_snapshot: 10; "
                    "evidence summary: banana question; confidence: medium\n"
                    'L2_pattern_evidence_2: user repeatedly sending message - "что такое бананы" '
                    "[ last_seen_turn_snapshot: 10 ] [ occurrences: 2 ]"
                ),
            )

            self.assertIn(
                "possible pattern: updated line",
                merged,
            )
            self.assertEqual(
                1,
                merged.count(
                    "L2_pattern_evidence_"
                ),
            )
            self.assertIn(
                "L2_pattern_evidence_1:",
                merged,
            )
            self.assertIn(
                "что такое бананы",
                merged,
            )
            self.assertIn(
                "[ first_seen_turn_snapshot: 5 ]",
                merged,
            )
            self.assertIn(
                "[ last_seen_turn_snapshot: 10 ]",
                merged,
            )

    def test_l2_candidate_evidence_lines_are_removed_before_deterministic_merge(self):

            cleaned = remove_runtime_l2_pattern_evidence_lines(
                "possible pattern: repeated message. Occurrences: 4\n"
                'L2_pattern_evidence_1: user repeatedly sending one message [ quote: "ping" ] '
                "[ first_seen_turn_snapshot: 9 ] [ last_seen_turn_snapshot: 10 ] [ occurrences: 4 ]\n"
                "scope: current session"
            )

            self.assertEqual(
                "possible pattern: repeated message. Occurrences: 4\n"
                "scope: current session",
                cleaned,
            )

    def test_embedded_l2_pattern_evidence_is_extracted_for_runtime_display(self):

            runtime_l2_memory = (
                "possible pattern: User initiates a request for abstract creative content. "
                'Occurrences: 1; evidence: [ user_message: "draw something unusual" ]; '
                "L2_pattern_evidence_3: User initiates a request for abstract creative content. "
                '[ quote: "draw something unusual" ] '
                "[ first_seen_turn_snapshot: 4 ] "
                "[ last_seen_turn_snapshot: 4 ]"
            )

            evidence_lines = extract_runtime_l2_pattern_evidence_lines(
                runtime_l2_memory
            )

            self.assertEqual(
                [
                    "L2_pattern_evidence_3: User initiates a request for abstract creative content. "
                    '[ quote: "draw something unusual" ] '
                    "[ first_seen_turn_snapshot: 4 ] "
                    "[ last_seen_turn_snapshot: 4 ]",
                ],
                evidence_lines,
            )

            rendered = build_runtime_memory_context_text(
                "current_request: waiting",
                SimpleNamespace(
                    runtime_l2_memory=runtime_l2_memory,
                ),
            )

            self.assertIn(
                "L2_pattern_evidence_3:",
                rendered,
            )

    def test_l2_pattern_evidence_example_normalizer_strips_spaces_commas_and_dots(self):

            self.assertEqual(
                "чтотакоебананы",
                normalize_l2_pattern_evidence_example(
                    " Что, такое. бананы "
                ),
            )

    async def test_runtime_l1_diff_log_formats_float_noise(self):

            logger = FakeLogger()
            context = SimpleNamespace(
                logger=logger,
                runtime_l2_pending_patches=[
                    {
                        "total_diff": 4.65,
                    },
                    {
                        "total_diff": 296.85,
                    },
                ],
                runtime_l2_last_turn=2,
                user_message_count=5,
            )

            await record_runtime_l1_diff(
                context=context,
                snapshot={
                    "index": 3,
                    "total_diff": 167.29999999999998,
                    "patch": {},
                },
                turns=[],
            )

            self.assertEqual(
                len(logger.service_logs),
                1,
            )
            self.assertIn(
                "[MEMORY:L1] L1 diff +167.3; "
                "recent diffs [4.65, 296.85, 167.3]; "
                "avg 156.27; range 292.2;",
                logger.service_logs[0],
            )
            self.assertNotIn(
                "167.29999999999998",
                logger.service_logs[0],
            )

    async def test_l2_memory_waits_for_repeated_patch_keys(self):

            service_client = FakeServiceClient(
                "possible pattern: should not run"
            )
            logger = FakeLogger()
            context = SimpleNamespace(
                clients={
                    "service": service_client,
                },
                logger=logger,
                runtime_l2_memory="",
                runtime_l2_pending_patches=[
                    {
                        "turn_number": 1,
                        "snapshot_index": 1,
                        "total_diff": 110,
                        "changes": {
                            "added": [
                                {
                                    "key": "topic",
                                    "value": "one",
                                },
                            ],
                        },
                    },
                    {
                        "turn_number": 2,
                        "snapshot_index": 2,
                        "total_diff": 254,
                        "changes": {
                            "added": [
                                {
                                    "key": "intent",
                                    "value": "two",
                                },
                            ],
                        },
                    },
                    {
                        "turn_number": 3,
                        "snapshot_index": 3,
                        "total_diff": 80,
                        "changes": {
                            "added": [
                                {
                                    "key": "choice",
                                    "value": "three",
                                },
                            ],
                        },
                    },
                    {
                        "turn_number": 4,
                        "snapshot_index": 4,
                        "total_diff": 140,
                        "changes": {
                            "added": [
                                {
                                    "key": "status",
                                    "value": "four",
                                },
                            ],
                        },
                    },
                    {
                        "turn_number": 5,
                        "snapshot_index": 5,
                        "total_diff": 90,
                        "changes": {
                            "added": [
                                {
                                    "key": "reference",
                                    "value": "five",
                                },
                            ],
                        },
                    },
                ],
                runtime_l2_last_turn=0,
                user_message_count=L2_PATCH_WINDOW,
            )

            updated_memory = await maybe_summarize_runtime_l2_memory(
                context=context,
            )

            self.assertEqual(
                updated_memory,
                "",
            )
            self.assertEqual(
                len(service_client.calls),
                0,
            )
            self.assertEqual(
                context.runtime_l2_memory,
                "",
            )

    async def test_l2_memory_keeps_evidence_but_drops_unconfirmed_pattern(self):

            service_client = FakeServiceClient(
                "possible pattern: user may be repeating one message. "
                "Occurrences: 4; first_seen_snapshot: 9; last_seen_snapshot: 10; "
                "evidence summary: duplicate rows for one snapshot; confidence: medium\n"
                'L2_pattern_evidence_1: user repeatedly sending one message [ quote: "ping" ] '
                "[ first_seen_turn_snapshot: 9 ] [ last_seen_turn_snapshot: 10 ] [ occurrences: 4 ]"
            )
            logger = FakeLogger()
            context = SimpleNamespace(
                clients={
                    "service": service_client,
                },
                logger=logger,
                runtime_memory="",
                runtime_memory_snapshots=[],
                runtime_memory_snapshot_index=0,
                runtime_l2_memory="",
                runtime_l2_pending_patches=[
                    {
                        "turn_number": index + 1,
                        "snapshot_index": index + 1,
                        "total_diff": 120,
                        "changes": {
                            "added": [
                                {
                                    "key": "topic",
                                    "value": f"value {index}",
                                },
                            ],
                        },
                    }
                    for index in range(L2_PATCH_WINDOW - 1)
                ] + [
                    {
                        "turn_number": 10,
                        "snapshot_index": 10,
                        "total_diff": 140,
                        "user_message": "ping",
                        "user_messages": [
                            "ping",
                        ],
                        "changes": {
                            "added": [
                                {
                                    "key": "topic",
                                    "value": "value final",
                                },
                                {
                                    "key": "user_message",
                                    "value": "ping",
                                },
                            ],
                        },
                    },
                ],
                runtime_l1_diff_history=[],
                runtime_l2_last_turn=0,
                user_message_count=L2_PATCH_WINDOW,
            )

            updated_memory = await maybe_summarize_runtime_l2_memory(
                context=context,
            )

            self.assertNotIn(
                "possible pattern",
                updated_memory,
            )
            self.assertIn(
                "L2_pattern_evidence_1:",
                updated_memory,
            )
            self.assertIn(
                'quote: "ping"',
                updated_memory,
            )
            self.assertIn(
                "[ first_seen_turn_snapshot: 9 ]",
                updated_memory,
            )
            self.assertIn(
                "[ last_seen_turn_snapshot: 10 ]",
                updated_memory,
            )

    async def test_l2_memory_runs_after_repeated_patch_keys_even_with_noisy_diff(self):

            service_client = FakeServiceClient(
                "possible pattern: user revisits the same implementation tradeoff",
            )
            logger = FakeLogger()
            emitter = SimpleNamespace(
                events=[],
                emit=None,
            )
            context = SimpleNamespace(
                clients={
                    "service": service_client,
                },
                emitter=emitter,
                logger=logger,
                runtime_memory="",
                runtime_memory_snapshots=[],
                runtime_memory_snapshot_index=0,
                runtime_l2_memory="",
                runtime_l2_pending_patches=[
                    {
                        "turn_number": 1,
                        "snapshot_index": 1,
                        "total_diff": 110,
                        "changes": {
                            "added": [
                                {
                                    "key": "topic",
                                    "value": "early broad update",
                                },
                            ],
                        },
                    },
                    {
                        "turn_number": 2,
                        "snapshot_index": 2,
                        "total_diff": 254,
                        "changes": {
                            "changed": [
                                {
                                    "previous_key": "topic",
                                    "previous_value": "early broad update",
                                    "current_key": "topic",
                                    "current_value": "large rewrite",
                                },
                            ],
                        },
                    },
                    {
                        "turn_number": 3,
                        "snapshot_index": 3,
                        "total_diff": 199.05,
                        "changes": {
                            "changed": [
                                {
                                    "previous_key": "topic",
                                    "previous_value": "large rewrite",
                                    "current_key": "topic",
                                    "current_value": "memory mechanics",
                                },
                            ],
                        },
                    },
                    {
                        "turn_number": 4,
                        "snapshot_index": 4,
                        "total_diff": 151,
                        "changes": {
                            "changed": [
                                {
                                    "previous_key": "topic",
                                    "previous_value": "memory mechanics",
                                    "current_key": "topic",
                                    "current_value": "pattern trigger",
                                },
                            ],
                        },
                    },
                    {
                        "turn_number": 5,
                        "snapshot_index": 5,
                        "total_diff": 144.9,
                        "changes": {
                            "changed": [
                                {
                                    "previous_key": "topic",
                                    "previous_value": "pattern trigger",
                                    "current_key": "topic",
                                    "current_value": "L2 window",
                                },
                            ],
                        },
                    },
                    {
                        "turn_number": 6,
                        "snapshot_index": 6,
                        "total_diff": 77.6,
                        "changes": {
                            "changed": [
                                {
                                    "previous_key": "intent",
                                    "previous_value": "inspect diff",
                                    "current_key": "intent",
                                    "current_value": "adjust trigger",
                                },
                            ],
                        },
                    },
                    {
                        "turn_number": 7,
                        "snapshot_index": 7,
                        "total_diff": 104.69,
                        "changes": {
                            "changed": [
                                {
                                    "previous_key": "topic",
                                    "previous_value": "L2 window",
                                    "current_key": "topic",
                                    "current_value": "repeated keys",
                                },
                            ],
                        },
                    },
                ],
                runtime_l1_diff_history=[
                    {
                        "snapshot_index": 1,
                        "total_diff": 110,
                    },
                    {
                        "snapshot_index": 7,
                        "total_diff": 104.69,
                    },
                ],
                runtime_l2_last_turn=0,
                user_message_count=7,
                session_id="test-session",
            )

            async def emit(event):
                context.emitter.events.append(
                    event
                )

            context.emitter.emit = emit

            updated_memory = await maybe_summarize_runtime_l2_memory(
                context=context,
            )

            self.assertEqual(
                updated_memory,
                "possible pattern: user revisits the same implementation tradeoff",
            )
            self.assertEqual(
                len(service_client.calls),
                1,
            )
            self.assertEqual(
                service_client.calls[0]["timeout"],
                config.SERVICE_REQUEST_TIMEOUT,
            )
            self.assertEqual(
                context.runtime_l2_memory,
                "possible pattern: user revisits the same implementation tradeoff",
            )
            self.assertEqual(
                context.runtime_l2_last_turn,
                7,
            )
            self.assertEqual(
                context.runtime_l2_pending_patches,
                [],
            )
            self.assertEqual(
                len(context.runtime_l1_diff_history),
                2,
            )
            self.assertIn(
                "Recent L1 patches",
                service_client.calls[0]["user_prompt"],
            )
            self.assertIn(
                "total_diff: 199.05",
                service_client.calls[0]["user_prompt"],
            )
            self.assertNotIn(
                "total_diff: 110",
                service_client.calls[0]["user_prompt"],
            )
            self.assertNotIn(
                "total_diff: 254",
                service_client.calls[0]["user_prompt"],
            )
            self.assertEqual(
                logger.summarizer_logs[0][0],
                "[MEMORY:L2] L2 summarizer request",
            )
            self.assertIn(
                '"messages"',
                logger.summarizer_logs[0][1],
            )
            self.assertIn(
                "total_diff: 199.05",
                logger.summarizer_logs[0][1],
            )
            self.assertEqual(
                logger.summarizer_logs[1][0],
                "[MEMORY:L2] L2 pattern memory summarizer result",
            )
            self.assertEqual(
                logger.summarizer_logs[1][1],
                "possible pattern: user revisits the same implementation tradeoff",
            )
            self.assertEqual(
                context.runtime_memory_snapshots,
                [],
            )
            memory_events = [
                event
                for event in context.emitter.events
                if event["type"] == "runtime_memory_update"
            ]

            self.assertEqual(
                len(memory_events),
                0,
            )

