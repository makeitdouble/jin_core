import unittest
from types import SimpleNamespace

from clients.brain_client import (
    build_brain_system_prompt,
)
from memory.message_memory import (
    DEFAULT_RUNTIME_MEMORY,
    L2_PATCH_WINDOW,
    build_interrupted_assistant_message,
    build_runtime_l2_memory_system_prompt,
    build_runtime_memory_system_prompt,
    build_runtime_memory_user_prompt,
    maybe_summarize_runtime_l2_memory,
    schedule_interrupted_runtime_memory_update,
    schedule_runtime_memory_update,
    summarize_runtime_memory,
)
from runtime.runtime_context import (
    RuntimeContext,
)
from memory.runtime_state import (
    RUNTIME_MEMORY_SUMMARIZER_RUNTIME_ID,
)
from settings.config_loader import (
    config,
)


class FakeServiceClient:

    def __init__(
        self,
        response_text,
        finish_reasons=None,
        usage=None,
    ):

        self.response_text = response_text
        self.finish_reasons = list(
            finish_reasons
            or []
        )
        self.usage = usage
        self.calls = []

    async def ask(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
        timeout: float | None = None,
    ):

        self.calls.append({
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": timeout,
        })

        if isinstance(
            self.response_text,
            Exception,
        ):
            raise self.response_text

        if isinstance(
            self.response_text,
            list,
        ):
            content = self.response_text[
                len(
                    self.calls
                )
                - 1
            ]
        else:
            content = self.response_text

        choice = {
            "message": {
                "content": content,
            },
        }

        if self.finish_reasons:
            choice["finish_reason"] = (
                self.finish_reasons.pop(0)
            )

        response = {
            "choices": [
                choice,
            ],
        }

        if self.usage is not None:
            response["usage"] = self.usage

        return response


class FakeLogger:

    def __init__(self):
        self.service_logs = []
        self.summarizer_logs = []
        self.errors = []

    async def log_service(
        self,
        message: str,
    ):

        self.service_logs.append(
            message
        )

    async def log_summarizer(
        self,
        message: str,
        details: str | None = None,
    ):

        self.summarizer_logs.append(
            (
                message,
                details,
            )
        )

    async def log_error(
        self,
        message: str,
        details: str | None = None,
    ):

        self.errors.append(
            (
                message,
                details,
            )
        )


class MessageMemoryTests(
    unittest.IsolatedAsyncioTestCase
):

    def test_runtime_memory_user_prompt_uses_session_fallback(self):

        prompt = build_runtime_memory_user_prompt(
            current_memory="",
            user_message="hello",
            assistant_message="hi",
            current_l2_memory=(
                "possible pattern: repeated greeting loop; Occurrences: 2"
            ),
        )

        self.assertIn(
            DEFAULT_RUNTIME_MEMORY,
            prompt,
        )
        self.assertIn(
            "Current L2 pattern memory for occurrence tracking only",
            prompt,
        )
        self.assertIn(
            "Occurrences: 2",
            prompt,
        )

    def test_first_brain_prompt_includes_default_runtime_memory(self):

        context = RuntimeContext(
            websocket=object(),
            emitter=object(),
            logger=object(),
            clients={},
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_SEARCH": False,
                "CAN_DEEP_THOUGHT": False,
            },
        )

        self.assertIn(
            "<RUNTIME_MEMORY>",
            prompt,
        )
        self.assertIn(
            DEFAULT_RUNTIME_MEMORY,
            prompt,
        )

    def test_runtime_memory_prompt_focuses_on_summary_depth(self):

        prompt = build_runtime_memory_system_prompt()

        self.assertIn(
            "Decide the summary depth",
            prompt,
        )
        self.assertIn(
            "Use shallow summarization",
            prompt,
        )
        self.assertIn(
            "Use deep summarization",
            prompt,
        )
        self.assertIn(
            "atomic bullet lines",
            prompt,
        )
        self.assertIn(
            "one semantic entity per line",
            prompt,
        )
        self.assertIn(
            "compact semantic label",
            prompt,
        )
        self.assertIn(
            "Keep memory actionable",
            prompt,
        )
        self.assertIn(
            "failures or interruptions",
            prompt,
        )
        self.assertIn(
            "merely paraphrased, reordered, or reworded",
            prompt,
        )
        self.assertIn(
            "Treat semantic rephrasing as no-op memory",
            prompt,
        )
        self.assertIn(
            "do not treat it as resolved",
            prompt,
        )
        self.assertNotIn(
            "space exploration costs",
            prompt,
        )
        self.assertNotIn(
            "assistant established",
            prompt,
        )
        self.assertNotIn(
            "after one completed user/JIN turn",
            prompt,
        )

    def test_runtime_l2_memory_prompt_defines_pattern_layer(self):

        prompt = build_runtime_l2_memory_system_prompt()

        self.assertIn(
            "L2 pattern memory summarizer",
            prompt,
        )
        self.assertIn(
            "possible pattern",
            prompt,
        )
        self.assertIn(
            "Prefer 'possible pattern' over 'pattern'",
            prompt,
        )
        self.assertIn(
            "Occurrences: N",
            prompt,
        )
        self.assertIn(
            "last_seen_snapshot",
            prompt,
        )
        self.assertIn(
            "evidence summary",
            prompt,
        )
        self.assertIn(
            "confidence",
            prompt,
        )
        self.assertIn(
            "brand-new pattern",
            prompt,
        )
        self.assertIn(
            "same-intent behavior repeated before L2 named it",
            prompt,
        )
        self.assertIn(
            "Never write Occurrences: 1",
            prompt,
        )
        self.assertIn(
            "do not recompute Occurrences from the supplied patch window alone",
            prompt,
        )
        self.assertIn(
            "new_occurrences = old_occurrences + count(new matching L1 evidence after last_seen_snapshot)",
            prompt,
        )
        self.assertIn(
            "patch snapshot > last_seen_snapshot",
            prompt,
        )
        self.assertIn(
            "initialize it as a baseline without incrementing Occurrences for old visible evidence",
            prompt,
        )
        self.assertIn(
            "Never reduce an existing Occurrences count",
            prompt,
        )
        self.assertIn(
            "reset that pattern to Occurrences: 0",
            prompt,
        )
        self.assertIn(
            "emerging signal",
            prompt,
        )
        self.assertIn(
            "may indicate",
            prompt,
        )
        self.assertIn(
            "hypothesis generator",
            prompt,
        )
        self.assertIn(
            "contradiction",
            prompt,
        )
        self.assertIn(
            "corrected assumption",
            prompt,
        )
        self.assertIn(
            "strong signal",
            prompt,
        )
        self.assertIn(
            "return the current L2 memory unchanged",
            prompt,
        )
        self.assertIn(
            "Pattern memory should not learn from itself",
            prompt,
        )
        self.assertIn(
            "Occurrences must be derived only from actual conversation evidence",
            prompt,
        )

    def test_interrupted_assistant_message_marks_incomplete(self):

        message = build_interrupted_assistant_message(
            user_message="Tell me a story.",
            assistant_message="Once upon a",
        )

        self.assertIn(
            "interrupted by the user",
            message,
        )
        self.assertIn(
            "incomplete",
            message,
        )
        self.assertIn(
            "Do not treat this turn as resolved",
            message,
        )
        self.assertIn(
            "Tell me a story.",
            message,
        )
        self.assertIn(
            "Once upon a",
            message,
        )

    def test_brain_prompt_includes_runtime_memory(self):

        context = SimpleNamespace(
            runtime_memory=(
                "The user recently asked about Lamborghini pricing."
            ),
            deep_thought_count=0,
            runtime_search_result="",
            runtime_search_result_id="",
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_SEARCH": False,
                "CAN_DEEP_THOUGHT": False,
            },
        )

        self.assertIn(
            "<RUNTIME_MEMORY>",
            prompt,
        )
        self.assertIn(
            "Lamborghini pricing",
            prompt,
        )

    def test_brain_prompt_includes_l2_memory_separately(self):

        context = SimpleNamespace(
            runtime_memory="topic: current factual work",
            runtime_l2_memory="possible pattern: user compares implementation paths before coding",
            deep_thought_count=0,
            runtime_search_result="",
            runtime_search_result_id="",
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_SEARCH": False,
                "CAN_DEEP_THOUGHT": False,
            },
        )

        self.assertIn(
            "<RUNTIME_MEMORY>",
            prompt,
        )
        self.assertIn(
            "<RUNTIME_PATTERN_MEMORY>",
            prompt,
        )
        self.assertIn(
            "current factual work",
            prompt,
        )
        self.assertIn(
            "compares implementation paths",
            prompt,
        )
        self.assertIn(
            "Keep responses natural, conversational",
            prompt,
        )
        self.assertIn(
            "soft dialog closure",
            prompt,
        )
        self.assertIn(
            "No new signal, no new strategy",
            prompt,
        )
        self.assertIn(
            "do not ask for a topic, preference, choice, task, or next step",
            prompt,
        )
        self.assertIn(
            "Allowed response: acknowledge the repeated input",
            prompt,
        )
        self.assertIn(
            "not to extract a useful request from the user",
            prompt,
        )

    def test_brain_prompt_includes_conditional_zero_diff_alert(self):

        context = SimpleNamespace(
            runtime_memory="topic: active loop diagnostics",
            runtime_l2_memory="",
            runtime_zero_diff_alert={
                "turn_number": 8,
                "user_message": "привет",
                "assistant_message": "Привет! Чем займемся?",
            },
            deep_thought_count=0,
            runtime_search_result="",
            runtime_search_result_id="",
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_SEARCH": False,
                "CAN_DEEP_THOUGHT": False,
            },
        )

        self.assertIn(
            "<ZERO_DIFF_STALL_ALERT>",
            prompt,
        )
        self.assertIn(
            "Do not alarm from this fact alone",
            prompt,
        )
        self.assertIn(
            "soft success rules are intentionally not rendered",
            prompt,
        )
        self.assertIn(
            "No new signal, no new strategy",
            prompt,
        )
        self.assertIn(
            "do not ask for a topic, preference, choice, task, or next step",
            prompt,
        )
        self.assertNotIn(
            "Keep responses natural, conversational",
            prompt,
        )
        self.assertNotIn(
            "soft dialog closure",
            prompt,
        )
        self.assertNotIn(
            "closest achievable form",
            prompt,
        )
        self.assertIn(
            "bad rules for this turn",
            prompt,
        )
        self.assertIn(
            "Disable the usual greeting, reassurance, helpful menu",
            prompt,
        )
        self.assertIn(
            "Do not try to break the loop by forcing the user",
            prompt,
        )
        self.assertIn(
            "topic, task, purpose, choice, or next step",
            prompt,
        )
        self.assertIn(
            "Do not answer a repeated zero-diff trigger with extra warmth",
            prompt,
        )
        self.assertIn(
            "larger menu of choices",
            prompt,
        )
        self.assertIn(
            "short, pointed, off-angle move",
            prompt,
        )
        self.assertIn(
            "rewrite it as a no-request observation or counter-move",
            prompt,
        )
        self.assertIn(
            "same local interaction",
            prompt,
        )
        self.assertIn(
            "привет",
            prompt,
        )

    def test_brain_prompt_includes_conversation_activity(self):

        context = SimpleNamespace(
            runtime_memory="topic: active loop diagnostics",
            runtime_l2_memory=(
                "possible pattern: repeated greeting loop; Occurrences: 3"
            ),
            runtime_l2_pending_patches=[
                {
                    "total_diff": 29.85,
                },
            ],
            runtime_zero_diff_alert=None,
            deep_thought_count=0,
            runtime_search_result="",
            runtime_search_result_id="",
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_SEARCH": False,
                "CAN_DEEP_THOUGHT": False,
            },
        )

        self.assertIn(
            "<CONVERSATION_ACTIVITY>",
            prompt,
        )
        self.assertIn(
            "<PERCENT>30</PERCENT>",
            prompt,
        )
        self.assertNotIn(
            "SOURCE_L1_DIFF",
            prompt,
        )
        self.assertIn(
            "LOW activity. The conversation is fading",
            prompt,
        )
        self.assertIn(
            "acting against the expected pattern",
            prompt,
        )

    def test_brain_prompt_marks_critical_conversation_activity(self):

        context = SimpleNamespace(
            runtime_memory="topic: active loop diagnostics",
            runtime_l2_memory=(
                "possible pattern: repeated greeting loop; Occurrences: 4"
            ),
            runtime_l2_pending_patches=[
                {
                    "total_diff": 9.85,
                },
            ],
            runtime_zero_diff_alert=None,
            deep_thought_count=0,
            runtime_search_result="",
            runtime_search_result_id="",
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_SEARCH": False,
                "CAN_DEEP_THOUGHT": False,
            },
        )

        self.assertIn(
            "<PERCENT>10</PERCENT>",
            prompt,
        )
        self.assertIn(
            "CRITICAL activity collapse",
            prompt,
        )
        self.assertIn(
            "current local response rules have failed",
            prompt,
        )
        self.assertIn(
            "resist the repetitive behavior",
            prompt,
        )
        self.assertIn(
            "Use a counter-reaction",
            prompt,
        )
        self.assertIn(
            "Do not force progress or extract a useful request",
            prompt,
        )
        self.assertIn(
            "Refuse the repeated frame",
            prompt,
        )
        self.assertIn(
            "does not ask for a topic, task, purpose, choice, or next step",
            prompt,
        )

    def test_brain_prompt_marks_activity_below_twenty_as_critical(self):

        context = SimpleNamespace(
            runtime_memory="topic: active loop diagnostics",
            runtime_l2_memory="",
            runtime_l2_pending_patches=[
                {
                    "total_diff": 19,
                },
            ],
            runtime_zero_diff_alert=None,
            deep_thought_count=0,
            runtime_search_result="",
            runtime_search_result_id="",
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_SEARCH": False,
                "CAN_DEEP_THOUGHT": False,
            },
        )

        self.assertIn(
            "<PERCENT>19</PERCENT>",
            prompt,
        )
        self.assertIn(
            "CRITICAL activity collapse",
            prompt,
        )

    def test_brain_prompt_caps_conversation_activity_at_full(self):

        context = SimpleNamespace(
            runtime_memory="topic: active exchange",
            runtime_l2_memory="",
            runtime_l2_pending_patches=[
                {
                    "total_diff": 142,
                },
            ],
            runtime_zero_diff_alert=None,
            deep_thought_count=0,
            runtime_search_result="",
            runtime_search_result_id="",
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_SEARCH": False,
                "CAN_DEEP_THOUGHT": False,
            },
        )

        self.assertIn(
            "<PERCENT>100</PERCENT>",
            prompt,
        )
        self.assertNotIn(
            "SOURCE_L1_DIFF",
            prompt,
        )

    async def test_summarizer_updates_runtime_memory(self):

        service_client = FakeServiceClient(
            "The user is testing live runtime memory."
        )
        logger = FakeLogger()
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            emitter=SimpleNamespace(
                events=[],
                emit=None,
            ),
            logger=logger,
            runtime_memory="",
            runtime_memory_updates=0,
            runtime_memory_snapshots=[],
            runtime_memory_snapshot_index=0,
            session_id="test-session",
        )

        async def emit(event):
            context.emitter.events.append(
                event
            )

        context.emitter.emit = emit

        updated_memory = await summarize_runtime_memory(
            context=context,
            user_message="Do you remember this?",
            assistant_message="Yes, I can keep the live context updated.",
        )

        self.assertEqual(
            updated_memory,
            "The user is testing live runtime memory.",
        )
        self.assertEqual(
            context.runtime_memory,
            "The user is testing live runtime memory.",
        )
        self.assertEqual(
            context.runtime_memory_updates,
            1,
        )
        self.assertIn(
            "Do you remember this?",
            service_client.calls[0]["user_prompt"],
        )
        self.assertIn(
            "atomic bullet lines",
            service_client.calls[0]["user_prompt"],
        )
        self.assertEqual(
            service_client.calls[0]["system_prompt"],
            build_runtime_memory_system_prompt(),
        )
        self.assertIn(
            "[MEMORY] runtime memory updated",
            logger.service_logs,
        )
        self.assertEqual(
            logger.summarizer_logs[0][0],
            "[MEMORY] L1 summarizer request",
        )
        self.assertIn(
            '"messages"',
            logger.summarizer_logs[0][1],
        )
        self.assertIn(
            "Do you remember this?",
            logger.summarizer_logs[0][1],
        )
        self.assertEqual(
            len(context.emitter.events),
            2,
        )

        telemetry_event = context.emitter.events[0]

        self.assertEqual(
            telemetry_event["type"],
            "telemetry",
        )
        self.assertGreater(
            telemetry_event["runtime"][
                RUNTIME_MEMORY_SUMMARIZER_RUNTIME_ID
            ]["used_tokens"],
            0,
        )

        event = context.emitter.events[1]

        self.assertEqual(
            event["type"],
            "runtime_memory_update",
        )

        self.assertEqual(
            event["memory"],
            "The user is testing live runtime memory.",
        )

        self.assertEqual(
            event["updates"],
            1,
        )

        self.assertIn(
            "snapshot",
            event,
        )

        self.assertEqual(
            event["snapshot"]["index"],
            0,
        )

        self.assertEqual(
            event["snapshot"]["raw_memory"],
            "The user is testing live runtime memory.",
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
        self.assertIn(
            "[MEMORY] L2 memory updated",
            logger.service_logs,
        )
        self.assertEqual(
            logger.summarizer_logs[0][0],
            "[MEMORY] L2 summarizer request",
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
            "[MEMORY] L2 pattern memory summarizer result",
        )
        self.assertEqual(
            logger.summarizer_logs[1][1],
            "possible pattern: user revisits the same implementation tradeoff",
        )
        memory_events = [
            event
            for event in context.emitter.events
            if event["type"] == "runtime_memory_update"
        ]

        self.assertEqual(
            len(memory_events),
            1,
        )
        self.assertEqual(
            memory_events[0]["type"],
            "runtime_memory_update",
        )
        self.assertNotIn(
            "possible pattern: user revisits the same implementation tradeoff",
            memory_events[0]["snapshot"]["raw_memory"],
        )
        self.assertEqual(
            memory_events[0]["snapshot"]["raw_memory"],
            "",
        )

    async def test_summarizer_usage_corrects_estimate_with_prompt_usage(self):

        service_client = FakeServiceClient(
            "Exact memory.",
            usage={
                "prompt_tokens": 90,
                "completion_tokens": 33,
                "total_tokens": 123,
            },
        )
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            emitter=SimpleNamespace(
                events=[],
                emit=None,
            ),
            logger=FakeLogger(),
            runtime_memory="Initial memory.",
            runtime_memory_updates=0,
            runtime_memory_snapshots=[],
            runtime_memory_snapshot_index=0,
            session_id="test-session",
        )

        async def emit(event):
            context.emitter.events.append(
                event
            )

        context.emitter.emit = emit

        await summarize_runtime_memory(
            context=context,
            user_message="Remember this exactly.",
            assistant_message="I will update memory.",
        )

        telemetry_events = [
            event
            for event in context.emitter.events
            if event["type"] == "telemetry"
        ]

        self.assertEqual(
            len(telemetry_events),
            2,
        )
        self.assertEqual(
            telemetry_events[-1]["runtime"][
                RUNTIME_MEMORY_SUMMARIZER_RUNTIME_ID
            ]["used_tokens"],
            123,
        )
        self.assertEqual(
            telemetry_events[-1]["runtime"][
                RUNTIME_MEMORY_SUMMARIZER_RUNTIME_ID
            ]["context_tokens"],
            90,
        )
        self.assertEqual(
            telemetry_events[-1]["runtime"][
                RUNTIME_MEMORY_SUMMARIZER_RUNTIME_ID
            ]["total_tokens"],
            123,
        )

    async def test_summarizer_uses_service_max_tokens(self):

        service_client = FakeServiceClient(
            "- Active topic: available functions\n"
            "- Capabilities listed: answering questions and writing text",
        )
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            emitter=SimpleNamespace(
                events=[],
                emit=None,
            ),
            logger=FakeLogger(),
            runtime_memory="",
            runtime_memory_updates=0,
            runtime_memory_snapshots=[],
            runtime_memory_snapshot_index=0,
            session_id="test-session",
        )

        updated_memory = await summarize_runtime_memory(
            context=context,
            user_message="What can you do?",
            assistant_message="I can answer questions and write text.",
        )

        self.assertEqual(
            updated_memory,
            (
                "- Active topic: available functions\n"
                "- Capabilities listed: answering questions and writing text"
            ),
        )
        self.assertEqual(
            len(
                service_client.calls
            ),
            1,
        )
        self.assertEqual(
            service_client.calls[0]["max_tokens"],
            config.SERVICE_MAX_TOKENS,
        )

    async def test_summarizer_skips_incomplete_memory(self):

        logger = FakeLogger()
        service_client = FakeServiceClient(
            "- Active topic: available functions\n"
            "- Capabilities listed: answering questions (emails",
        )
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            logger=logger,
            runtime_memory="Initial memory.",
            runtime_memory_updates=0,
        )

        updated_memory = await summarize_runtime_memory(
            context=context,
            user_message="What can you do?",
            assistant_message="I can answer questions.",
        )

        self.assertEqual(
            updated_memory,
            "Initial memory.",
        )
        self.assertEqual(
            context.runtime_memory,
            "Initial memory.",
        )
        self.assertEqual(
            context.runtime_memory_updates,
            0,
        )
        self.assertTrue(
            logger.errors
        )

    async def test_summarizer_failure_logs_traceback_details(self):

        class SilentError(Exception):
            def __str__(self):
                return ""

        logger = FakeLogger()
        service_client = FakeServiceClient(
            SilentError()
        )
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            logger=logger,
            runtime_memory="Initial memory.",
            runtime_memory_updates=0,
        )

        updated_memory = await summarize_runtime_memory(
            context=context,
            user_message="Remember this.",
            assistant_message="I will remember it.",
        )

        self.assertEqual(
            updated_memory,
            "Initial memory.",
        )
        self.assertEqual(
            len(logger.errors),
            1,
        )

        message, details = logger.errors[0]

        self.assertEqual(
            message,
            "[MEMORY] runtime memory update failed",
        )
        self.assertIn(
            "Traceback (most recent call last):",
            details,
        )
        self.assertIn(
            "SilentError",
            details,
        )

    async def test_scheduled_update_is_background_task(self):

        service_client = FakeServiceClient(
            "Updated background memory."
        )
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            logger=FakeLogger(),
            runtime_memory="Initial memory.",
            runtime_memory_stable="Initial memory.",
            runtime_memory_updates=0,
            runtime_memory_pending_turns=[],
            runtime_memory_update_task=None,
        )

        task = schedule_runtime_memory_update(
            context=context,
            user_message="First message",
            assistant_message="First answer",
        )

        self.assertIsNotNone(
            task
        )
        self.assertTrue(
            hasattr(
                context,
                "background_tasks",
            )
        )

        await task

        self.assertEqual(
            context.runtime_memory,
            "Updated background memory.",
        )
        self.assertEqual(
            len(
                context.background_tasks
            ),
            0,
        )

    async def test_interrupted_update_uses_partial_response(self):

        service_client = FakeServiceClient(
            "- Active topic: storytelling\n"
            "- Interrupted response: user stopped the answer before completion"
        )
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            logger=FakeLogger(),
            runtime_memory="Initial memory.",
            runtime_memory_stable="Initial memory.",
            runtime_memory_updates=0,
            runtime_memory_pending_turns=[],
            runtime_memory_update_task=None,
            runtime_turn_user_message="Tell me a story.",
            runtime_turn_assistant_response="Once upon a",
        )

        task = schedule_interrupted_runtime_memory_update(
            context=context,
        )

        self.assertIsNotNone(
            task
        )

        await task

        user_prompt = service_client.calls[0]["user_prompt"]

        self.assertIn(
            "interrupted by the user",
            user_prompt,
        )
        self.assertIn(
            "Tell me a story.",
            user_prompt,
        )
        self.assertIn(
            "Once upon a",
            user_prompt,
        )
        self.assertIn(
            "Interrupted response",
            context.runtime_memory,
        )


if __name__ == "__main__":
    unittest.main()
