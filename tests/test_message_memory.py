import unittest
from types import SimpleNamespace

import httpx

from clients import (
    build_brain_system_prompt,
)
from runtime import (
    DEFAULT_RUNTIME_MEMORY,
    L2_PATCH_WINDOW,
    RUNTIME_MEMORY_SUMMARIZER_RUNTIME_ID,
    RuntimeContext,
    build_interrupted_assistant_message,
    build_runtime_l2_memory_system_prompt,
    build_runtime_memory_system_prompt,
    build_runtime_memory_user_prompt,
    build_runtime_session_memory_system_prompt,
    build_runtime_session_memory_user_prompt,
    maybe_summarize_runtime_l2_memory,
    maybe_summarize_runtime_session_memory,
    record_runtime_l1_diff,
    schedule_interrupted_runtime_memory_update,
    schedule_runtime_memory_update,
    summarize_runtime_memory,
)
from runtime.L1_memory import (
    ask_runtime_memory_model,
    summarize_runtime_memory_pending_turns,
)
from runtime.L1_memory_utils import (
    build_runtime_memory_context_text,
    build_runtime_memory_snapshot,
    enforce_runtime_turn_fields,
    ensure_active_memory_status_suffixes,
    get_strength_zones,
    normalize_managed_runtime_memory_slots,
    parse_runtime_memory_lines,
    quote_runtime_user_message_value,
    refresh_active_memory_runtime_metadata,
    strip_active_memory_runtime_metadata,
)
from runtime.L3_memory_utils import (
    build_l3_session_memory_max_tokens,
)
from runtime.L3_memory_rules import (
    L3_OUTPUT_MAX_TOKENS,
)
from runtime.L2_memory_utils import (
    merge_runtime_l2_pattern_evidence_memory,
    normalize_l2_pattern_evidence_example,
    remove_runtime_l2_pattern_evidence_lines,
)
from runtime.L1_memory_rules import (
    RUNTIME_MEMORY_CONTEXT_OVERLOAD_RULES,
)
from runtime.registry import (
    runtime_state,
)
from config_loader import (
    config,
)


class FakeServiceClient:

    def __init__(
        self,
        response_text,
        finish_reasons=None,
        usage=None,
        context_window=None,
    ):

        self.response_text = response_text
        self.finish_reasons = list(
            finish_reasons
            or []
        )
        self.usage = usage
        self.context_window = context_window
        self.calls = []

    async def resolve_request_context_window(self):

        return self.context_window

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
        self.active_memory_logs = []
        self.runtime_logs = []
        self.errors = []

    async def log_runtime(
        self,
        message: str,
    ):

        self.runtime_logs.append(
            message
        )

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

    async def log_active_memory(
            self,
            message: str,
            details: str | None = None,
            event: str | None = None,
    ):

        self.active_memory_logs.append(
            (
                message,
                details,
                event,
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
        )

        self.assertIn(
            DEFAULT_RUNTIME_MEMORY,
            prompt,
        )
        self.assertNotIn(
            "Current L2 pattern memory",
            prompt,
        )
        self.assertNotIn(
            "Occurrences: 2",
            prompt,
        )

    def test_runtime_memory_user_prompt_uses_filtered_hot_traces(self):

        prompt = build_runtime_memory_user_prompt(
            current_memory="user_message: hello",
            user_message="hello",
            assistant_message="hi",
            strength_zones=get_strength_zones([
                {
                    "key": "user_message",
                    "strength": 0.9,
                },
                {
                    "key": "user_idle",
                    "strength": 0.9,
                },
            ]),
        )

        self.assertIn(
            "hot_traces: user_message",
            prompt,
        )
        self.assertNotIn(
            "user_idle",
            prompt,
        )
        self.assertNotIn(
            "Memory traces (pheromone strength)",
            prompt,
        )
        self.assertNotIn(
            "Crystallized (stable facts)",
            prompt,
        )
        self.assertNotIn(
            "Fading (deprioritize)",
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
                "CAN_WEB_SEARCH": False,
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

    def test_brain_prompt_places_user_idle_in_runtime_memory(self):

        context = RuntimeContext(
            websocket=object(),
            emitter=object(),
            logger=object(),
            clients={},
        )
        context.runtime_user_idle_seconds = 2

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_WEB_SEARCH": False,
                "CAN_DEEP_THOUGHT": False,
            },
        )

        self.assertNotIn(
            "<USER_IDLE>",
            prompt,
        )
        self.assertIn(
            "<RUNTIME_MEMORY>",
            prompt,
        )
        self.assertIn(
            f"note: {DEFAULT_RUNTIME_MEMORY}",
            prompt,
        )
        self.assertIn(
            "user_idle: 2s",
            prompt,
        )

        snapshot = build_runtime_memory_snapshot(
            context,
            context.runtime_memory,
        )

        self.assertIn(
            f"note: {DEFAULT_RUNTIME_MEMORY}",
            snapshot["raw_memory"],
        )
        self.assertIn(
            "user_idle: 2s",
            snapshot["raw_memory"],
        )

    def test_runtime_memory_context_replaces_stale_user_idle(self):

        context = RuntimeContext(
            websocket=object(),
            emitter=object(),
            logger=object(),
            clients={},
        )
        context.runtime_memory = (
            "active topic: Metaphorical identity query\n"
            "user_idle: 3m 3s (trace: 0.50)"
        )
        context.runtime_user_idle_seconds = 9

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_WEB_SEARCH": False,
                "CAN_DEEP_THOUGHT": False,
            },
        )

        self.assertEqual(
            prompt.count("user_idle:"),
            1,
        )
        self.assertIn(
            "user_idle: 9s",
            prompt,
        )
        self.assertNotIn(
            "user_idle: 3m 3s",
            prompt,
        )

        snapshot = build_runtime_memory_snapshot(
            context,
            context.runtime_memory,
        )

        self.assertEqual(
            snapshot["raw_memory"].count("user_idle:"),
            1,
        )
        self.assertIn(
            "user_idle: 9s",
            snapshot["raw_memory"],
        )
        self.assertNotIn(
            "user_idle: 3m 3s",
            snapshot["raw_memory"],
        )

    def test_runtime_memory_prompt_focuses_on_summary_depth(self):

        prompt = build_runtime_memory_system_prompt()

        # Keep this test focused on durable L1 prompt contracts, not exact wording.
        # Rules text is intentionally editable and should not break tests on every polish.
        for required_text in (
                "runtime L1 memory summarizer",
                "Return only the new compressed L1 memory state",
                "<key>: <value>",
                "last_jin_response",
                "user_fact",
                "jin_fact",
                "active_memory",
        ):
            self.assertIn(
                required_text,
                prompt,
            )

        for conditional_text in (
                "L2_pattern_evidence_N",
                "active_memory and active_memory_N are high-priority active recall contracts",
                "The user asked JIN to remember a specific value",
                "identity_state: JIN identity remains unchanged",
        ):
            self.assertNotIn(
                conditional_text,
                prompt,
            )

        for removed_text in (
                "space exploration costs",
                "assistant established",
                "after one completed user/JIN turn",
                RUNTIME_MEMORY_CONTEXT_OVERLOAD_RULES.strip(),
        ):
            self.assertNotIn(
                removed_text,
                prompt,
            )

    def test_runtime_memory_prompt_adds_conditional_blocks_from_memory_and_user_message(self):

        prompt = build_runtime_memory_system_prompt(
            current_memory=(
                "active_memory: \"banana\" (purpose: test; status: pending)\n"
                "L2_pattern_evidence_1: repeat question [ occurrences: 2 ]"
            ),
            user_message="ты теперь пират",
        )

        for required_text in (
                "Scan all existing active_memory family slots",
                "L2_pattern_evidence_N lines are owned by L2",
                "identity_state: JIN identity remains unchanged",
        ):
            self.assertIn(
                required_text,
                prompt,
            )

    def test_runtime_memory_prompt_adds_create_block_from_user_message(self):

        prompt = build_runtime_memory_system_prompt(
            current_memory="",
            user_message="запомни слово банан через 3 хода",
        )

        # Keep this test focused on the durable create-block contracts,
        # not on exact prompt prose.
        for required_text in (
                "Write active_memory only when this turn creates an active contract",
                "active_memory:",
                "<value>",
                "active_memory_2",
                "conditions:",
                "<what must happen later>",
        ):
            self.assertIn(
                required_text,
                prompt,
            )

    def test_runtime_memory_prompt_can_include_context_overload_rules(self):

        prompt = build_runtime_memory_system_prompt(
            last_turn_context_overloaded=True,
        )

        self.assertIn(
            RUNTIME_MEMORY_CONTEXT_OVERLOAD_RULES.strip(),
            prompt,
        )

    async def test_l1_prompt_includes_context_overload_rules_after_turn_overload(self):

        service_client = FakeServiceClient(
            "- active_topic: context overload handling",
            context_window=8192,
        )
        context = SimpleNamespace(
            runtime_memory="Initial memory.",
            runtime_l2_memory="",
            runtime_memory_snapshots=[],
            emitter=SimpleNamespace(
                emit=None,
            ),
            logger=FakeLogger(),
        )
        runtime_id = (
            config.SERVICE_MODEL_UID
            if config.USE_SERVICE_AS_BRAIN
            else config.BRAIN_MODEL_UID
        )
        previous_state = runtime_state.get_runtime_state(
            runtime_id
        )

        runtime_state.update_runtime_state(
            runtime_id=runtime_id,
            used_tokens=5000,
            context_tokens=3900,
            total_tokens=5000,
            max_tokens=4096,
            last_error=None,
            status="online",
        )

        try:
            await ask_runtime_memory_model(
                context=context,
                service_client=service_client,
                current_memory="Initial memory.",
                user_message="Remember the overload behavior.",
                assistant_message="I will preserve it.",
            )
        finally:
            runtime_state.update_runtime_state(
                runtime_id=runtime_id,
                used_tokens=previous_state["used_tokens"],
                context_tokens=previous_state["context_tokens"],
                total_tokens=previous_state["total_tokens"],
                max_tokens=previous_state["max_tokens"],
                last_error=previous_state["last_error"],
                status=previous_state["status"],
            )

        self.assertIn(
            RUNTIME_MEMORY_CONTEXT_OVERLOAD_RULES.strip(),
            service_client.calls[0]["system_prompt"],
        )

    def test_runtime_l2_memory_prompt_defines_pattern_layer(self):

        prompt = build_runtime_l2_memory_system_prompt()

        # Verify the durable L2 contract without pinning every prompt sentence.
        for required_text in (
                "L2 pattern memory summarizer",
                "hypothesis generator",
                "possible pattern",
                "Occurrences",
                "first_seen_snapshot",
                "last_seen_snapshot",
                "L2_pattern_evidence_N",
                "first_seen_turn_snapshot",
                "last_seen_turn_snapshot",
                "evidence summary",
                "confidence",
                "weak evidence",
                "learn from itself",
                "actual conversation evidence",
        ):
            self.assertIn(
                required_text,
                prompt,
            )

        self.assertNotIn(
            "Do not output JSON",
            prompt.replace(
                "Do not output JSON, Markdown headings, nested bullets, or numbered lists.",
                "",
            ),
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

    def test_l2_pattern_evidence_example_normalizer_strips_spaces_commas_and_dots(self):

        self.assertEqual(
            "чтотакоебананы",
            normalize_l2_pattern_evidence_example(
                " Что, такое. бананы "
            ),
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
                "CAN_WEB_SEARCH": False,
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

    def test_brain_prompt_anchors_short_feedback_to_last_jin_response(self):

        context = SimpleNamespace(
            runtime_memory=(
                "last_jin_response: Offered a short poem about rain."
            ),
            deep_thought_count=0,
            runtime_search_result="",
            runtime_search_result_id="",
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_WEB_SEARCH": False,
                "CAN_DEEP_THOUGHT": False,
            },
        )

        self.assertIn(
            "<RUNTIME_MEMORY>",
            prompt,
        )
        self.assertIn(
            "last_jin_response: Offered a short poem about rain.",
            prompt,
        )

    def test_brain_prompt_places_session_memory_above_runtime_memory(self):

        context = SimpleNamespace(
            session_memory=(
                "session_snapshot_first_turn: 0\n"
                "session_snapshot_last_turn: 6\n"
                "decision: Continue the memory architecture work."
            ),
            runtime_memory=(
                "topic: live runtime state"
            ),
            deep_thought_count=0,
            runtime_search_result="",
            runtime_search_result_id="",
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_WEB_SEARCH": False,
                "CAN_DEEP_THOUGHT": False,
            },
        )

        self.assertIn(
            "<PREVIOUS_SESSION_STATE priority=\"higher_than_runtime_memory\">",
            prompt,
        )
        self.assertIn(
            "Continue the memory architecture work",
            prompt,
        )
        self.assertIn(
            "session_snapshot_first_turn",
            prompt,
        )
        self.assertIn(
            "session_snapshot_last_turn",
            prompt,
        )
        self.assertLess(
            prompt.index(
                "<PREVIOUS_SESSION_STATE"
            ),
            prompt.index(
                "<RUNTIME_MEMORY>"
            ),
        )

    def test_brain_prompt_includes_nonempty_session_event_snapshots_array(self):

        context = SimpleNamespace(
            session_memory="decision: Continue session snapshots",
            runtime_session_event_snapshots=[
                {
                    "memory_type": "session_event_snapshot",
                    "memory": "decision: Use session snapshots array",
                }
            ],
            runtime_memory="topic: live runtime state",
            deep_thought_count=0,
            runtime_search_result="",
            runtime_search_result_id="",
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_WEB_SEARCH": False,
                "CAN_DEEP_THOUGHT": False,
            },
        )

        self.assertIn(
            "<SESSION_EVENT_SNAPSHOTS priority=\"session_context\">",
            prompt,
        )
        self.assertIn(
            "session_event_snapshot",
            prompt,
        )
        self.assertIn(
            "Use session snapshots array",
            prompt,
        )

    def test_brain_prompt_omits_empty_session_event_snapshots_array(self):

        context = SimpleNamespace(
            session_memory="decision: Continue session snapshots",
            runtime_session_event_snapshots=[],
            runtime_memory="topic: live runtime state",
            deep_thought_count=0,
            runtime_search_result="",
            runtime_search_result_id="",
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_WEB_SEARCH": False,
                "CAN_DEEP_THOUGHT": False,
            },
        )

        self.assertNotIn(
            "<SESSION_EVENT_SNAPSHOTS",
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
                "CAN_WEB_SEARCH": False,
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
        self.assertNotIn(
            "image/action tool",
            prompt,
        )
        self.assertNotIn(
            "Choose the best available visual representation of the request instead of description",
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
                "CAN_WEB_SEARCH": False,
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
        self.assertNotIn(
            "soft success rules are intentionally not rendered",
            prompt,
        )
        self.assertIn(
            "bad rules for this turn",
            prompt,
        )
        self.assertIn(
            "stop continuing normally and refuse the repeated frame",
            prompt,
        )
        self.assertIn(
            "Do not try to break the loop by forcing the user",
            prompt,
        )
        self.assertIn(
            "purpose, task, topic, choice, or next step",
            prompt,
        )
        self.assertIn(
            "short, pointed, off-angle move",
            prompt,
        )
        self.assertIn(
            "changes the interaction shape",
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
                "CAN_WEB_SEARCH": False,
                "CAN_DEEP_THOUGHT": False,
            },
        )

        self.assertIn(
            "<CONVERSATION_ACTIVITY>",
            prompt,
        )
        self.assertLess(
            prompt.index(
                "<USER_DATETIME>"
            ),
            prompt.index(
                "<CONVERSATION_ACTIVITY>"
            ),
        )
        self.assertLess(
            prompt.index(
                "<CONVERSATION_ACTIVITY>"
            ),
            prompt.index(
                "</CURRENT_TRUSTED_RUNTIME_VARIABLES>"
            ),
        )
        self.assertNotIn(
            "<PERCENT>",
            prompt,
        )
        self.assertNotIn(
            "<INSTRUCTION>",
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
                "CAN_WEB_SEARCH": False,
                "CAN_DEEP_THOUGHT": False,
            },
        )

        self.assertIn(
            "<CONVERSATION_ACTIVITY>",
            prompt,
        )
        self.assertNotIn(
            "<PERCENT>",
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
            "Use a counter-reaction",
            prompt,
        )
        self.assertIn(
            "Do not force progress or extract a useful request",
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
                "CAN_WEB_SEARCH": False,
                "CAN_DEEP_THOUGHT": False,
            },
        )

        self.assertIn(
            "<CONVERSATION_ACTIVITY>",
            prompt,
        )
        self.assertNotIn(
            "<PERCENT>",
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
                "CAN_WEB_SEARCH": False,
                "CAN_DEEP_THOUGHT": False,
            },
        )

        self.assertNotIn(
            "<CONVERSATION_ACTIVITY>",
            prompt,
        )
        self.assertNotIn(
            "SOURCE_L1_DIFF",
            prompt,
        )

    def test_brain_prompt_uses_recorded_activity_after_l2_clears_pending(self):

        context = SimpleNamespace(
            runtime_memory="topic: active exchange",
            runtime_l2_memory=(
                "possible pattern: user revisits memory mechanics"
            ),
            runtime_l2_pending_patches=[],
            runtime_memory_snapshots=[
                {
                    "total_diff": 0,
                },
            ],
            runtime_conversation_activity_diff=150.55,
            runtime_zero_diff_alert=None,
            deep_thought_count=0,
            runtime_search_result="",
            runtime_search_result_id="",
        )

        prompt = build_brain_system_prompt(
            context=context,
            runtime_actions={
                "CAN_WEB_SEARCH": False,
                "CAN_DEEP_THOUGHT": False,
            },
        )

        self.assertNotIn(
            "<CONVERSATION_ACTIVITY>",
            prompt,
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

        self.assertIn(
            "The user is testing live runtime memory.",
            updated_memory,
        )
        self.assertIn(
            'user_message: "Do you remember this?"',
            context.runtime_memory,
        )
        self.assertIn(
            "last_jin_response: Yes, I can keep the live context updated.",
            context.runtime_memory,
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
            build_runtime_memory_system_prompt(
                current_memory="",
                user_message="Do you remember this?",
            ),
        )
        self.assertEqual(
            logger.summarizer_logs[0][0],
            "[MEMORY:L1] L1 summarizer request",
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
            3,
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

        diff_event = context.emitter.events[2]

        self.assertEqual(
            diff_event["type"],
            "runtime_l1_diff_update",
        )

        self.assertIn(
            "The user is testing live runtime memory.",
            event["memory"],
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

        self.assertIn(
            'user_message: "Do you remember this?"',
            event["snapshot"]["raw_memory"],
        )

    def test_enforce_runtime_turn_fields_keeps_repetition_metadata_outside_quote(self):

        memory = enforce_runtime_turn_fields(
            "active_topic: loop check",
            user_message='"hello" [ repeated: 3 ]',
            assistant_message="I noticed the repeat.",
        )

        self.assertIn(
            'user_message: "hello" [ repeated: 3 ]',
            memory,
        )

    def test_quote_runtime_user_message_preserves_verbatim_quotes(self):

        self.assertEqual(
            quote_runtime_user_message_value(
                '"hello"'
            ),
            '"\\"hello\\""',
        )

    def test_parse_runtime_memory_keeps_multiline_user_message_together(self):

        lines = parse_runtime_memory_lines(
            'user_message: "first line\n'
            'second line\n'
            'third line"\n'
            "standalone continuation stays note\n"
            "last_jin_response: Answered."
        )

        self.assertEqual(
            lines[0]["key"],
            "user_message",
        )
        self.assertEqual(
            lines[0]["value"],
            '"first line\\nsecond line\\nthird line"',
        )
        self.assertEqual(
            lines[1],
            {
                "key": "note",
                "value": "standalone continuation stays note",
                "status": "same",
            },
        )
        self.assertEqual(
            lines[2]["key"],
            "last_jin_response",
        )

    def test_parse_runtime_memory_keeps_quoted_user_message_fragments_together(self):

        lines = parse_runtime_memory_lines(
            'user_message: "first line"\n'
            '"second line\\n"\n'
            '"third line\\n"\n'
            "active_memory: value"
        )

        self.assertEqual(
            [
                line["key"]
                for line in lines
            ],
            [
                "user_message",
                "active_memory",
            ],
        )
        self.assertIn(
            "second line",
            lines[0]["value"],
        )
        self.assertIn(
            "third line",
            lines[0]["value"],
        )

    def test_enforce_runtime_turn_fields_removes_broken_user_message_note_fragments(self):

        memory = enforce_runtime_turn_fields(
            (
                'user_message: "old"\n'
                'note: "\\"fragment one\\\\n\\""\n'
                'note: "fragment two\\\\n\\""\n'
                'active_memory: "Книга" (purpose: recall test; status: pending)'
            ),
            user_message="fresh message",
            assistant_message="Fresh answer.",
        )

        self.assertIn(
            'user_message: "fresh message"',
            memory,
        )
        self.assertIn(
            "active_memory:",
            memory,
        )
        self.assertNotIn(
            "fragment one",
            memory,
        )
        self.assertNotIn(
            "fragment two",
            memory,
        )

    def test_managed_active_memory_collapses_numeric_status_duplicate_to_parent(self):

        previous_memory = (
            "active_memory_1: Secret word: Water "
            "[ purpose: Remind user to guess it ] "
            "[ conditions: Remind only once ] "
            "[ status: pending ]"
        )
        candidate_memory = (
            previous_memory
            + "\n"
            "active_memory_2: Secret word: Water "
            "[ purpose: Remind user to guess it ] "
            "[ conditions: Remind only once ] "
            "[ status: pending, Reminder given in Turn 1 ] "
            "[trace: 0.55]\n"
            "primary_goal: Play a memory guessing game."
        )

        collapse_events = []
        memory = normalize_managed_runtime_memory_slots(
            previous_memory,
            candidate_memory,
            collapse_events=collapse_events,
        )

        self.assertIn(
            (
                "active_memory_1: Secret word: Water "
                "[ purpose: Remind user to guess it ] "
                "[ conditions: Remind only once ] "
                "[ status: pending, Reminder given in Turn 1 ]"
            ),
            memory,
        )
        self.assertIn(
            "primary_goal: Play a memory guessing game.",
            memory,
        )
        self.assertNotIn(
            "active_memory_2:",
            memory,
        )
        self.assertIn(
            "Reminder given in Turn 1",
            memory,
        )
        self.assertEqual(
            len(collapse_events),
            1,
        )
        self.assertEqual(
            collapse_events[0]["parent_key"],
            "active_memory_1",
        )

    def test_managed_active_memory_keeps_numeric_suffix_when_value_differs(self):

        previous_memory = (
            "active_memory_1: Secret word: Water "
            "[ purpose: Remind user to guess it ] "
            "[ status: pending ]"
        )
        candidate_memory = (
            previous_memory
            + "\n"
            "active_memory_2: Book title: Dune "
            "[ purpose: Remind user to guess it ] "
            "[ status: pending, Reminder given in Turn 1 ]"
        )

        memory = normalize_managed_runtime_memory_slots(
            previous_memory,
            candidate_memory,
        )

        self.assertIn(
            previous_memory,
            memory,
        )
        self.assertIn(
            "active_memory_2: Book title: Dune",
            memory,
        )

    def test_managed_active_memory_merges_same_key_status_update(self):

        previous_memory = (
            "active_memory: Secret word: Water "
            "[ purpose: Ask user to guess ] "
            "[ status: pending ]"
        )
        candidate_memory = (
            "active_memory: Secret word: Water "
            "[ purpose: Ask user to guess ] "
            "[ status: pending, Reminder given in Turn 1 ]"
        )

        memory = normalize_managed_runtime_memory_slots(
            previous_memory,
            candidate_memory,
        )

        self.assertIn(
            (
                "active_memory: Secret word: Water "
                "[ purpose: Ask user to guess ] "
                "[ status: pending, Reminder given in Turn 1 ]"
            ),
            memory,
        )
        self.assertNotIn(
            "active_memory_2:",
            memory,
        )

    def test_ensure_active_memory_status_suffixes_adds_pending(self):

        memory = ensure_active_memory_status_suffixes(
            (
                "active_memory: Secret word: Sun "
                "[ purpose: Ask user to guess ]\n"
                "primary_goal: Play a memory game."
            )
        )

        self.assertIn(
            (
                "active_memory: Secret word: Sun "
                "[ purpose: Ask user to guess ] "
                "[ status: pending ]"
            ),
            memory,
        )
        self.assertIn(
            "primary_goal: Play a memory game.",
            memory,
        )

    def test_refresh_active_memory_runtime_metadata_attaches_suffixes_before_status(self):

        memory = refresh_active_memory_runtime_metadata(
            (
                "active_memory: Secret word: Sun "
                "[ purpose: Ask user to guess ] "
                "[ status: pending ]"
            ),
            context=SimpleNamespace(
                timestamp="2026-06-20T10:00:00",
                turn_number=3,
            ),
        )

        self.assertIn(
            "[ creation_time: 2026-06-20T10:00:00 ]",
            memory,
        )
        self.assertIn(
            "[ created_jin_message_number: 3 ]",
            memory,
        )
        self.assertIn(
            "[ elapsed_time: 00:00:00 ]",
            memory,
        )
        self.assertIn(
            "[ elapsed_jin_message_number: 0 ] [ status: pending ]",
            memory,
        )

    def test_refresh_active_memory_runtime_metadata_updates_elapsed_suffixes(self):

        previous_memory = (
            "active_memory: Secret word: Sun "
            "[ purpose: Ask user to guess ] "
            "[ creation_time: 2026-06-20T10:00:00 ] "
            "[ created_jin_message_number: 3 ] "
            "[ elapsed_time: 00:00:00 ] "
            "[ elapsed_jin_message_number: 0 ] "
            "[ status: pending ]"
        )

        memory = refresh_active_memory_runtime_metadata(
            (
                "active_memory: Secret word: Sun "
                "[ purpose: Ask user to guess ] "
                "[ status: pending ]"
            ),
            previous_memory=previous_memory,
            context=SimpleNamespace(
                timestamp="2026-06-20T11:02:03",
                turn_number=5,
            ),
        )

        self.assertIn(
            "[ creation_time: 2026-06-20T10:00:00 ]",
            memory,
        )
        self.assertIn(
            "[ created_jin_message_number: 3 ]",
            memory,
        )
        self.assertIn(
            "[ elapsed_time: 01:02:03 ]",
            memory,
        )
        self.assertIn(
            "[ elapsed_jin_message_number: 2 ]",
            memory,
        )

    def test_runtime_context_refresh_adds_user_idle_to_active_memory_elapsed(self):

        memory = (
            "active_memory: Reminder set for potatoes "
            "[ purpose: remind user ] "
            "[ creation_time: 2026-06-20T10:00:00 ] "
            "[ created_jin_message_number: 3 ] "
            "[ elapsed_time: 00:00:00 ] "
            "[ elapsed_jin_message_number: 0 ] "
            "[ status: pending ]"
        )

        refreshed = build_runtime_memory_context_text(
            memory,
            SimpleNamespace(
                timestamp="2026-06-20T10:00:00",
                turn_number=4,
                runtime_user_idle_seconds=300,
                runtime_user_idle_text="5m 0s",
            ),
            refresh_active_memory_elapsed=True,
        )

        self.assertIn(
            "[ elapsed_time: 00:05:00 ]",
            refreshed,
        )
        self.assertIn(
            "user_idle: 5m",
            refreshed,
        )

    def test_runtime_context_refresh_does_not_mutate_stored_elapsed_by_default(self):

        memory = (
            "active_memory: Reminder set for potatoes "
            "[ creation_time: 2026-06-20T10:00:00 ] "
            "[ created_jin_message_number: 3 ] "
            "[ elapsed_time: 00:00:00 ] "
            "[ elapsed_jin_message_number: 0 ] "
            "[ status: pending ]"
        )

        rendered = build_runtime_memory_context_text(
            memory,
            SimpleNamespace(
                timestamp="2026-06-20T10:00:00",
                turn_number=4,
                runtime_user_idle_seconds=300,
                runtime_user_idle_text="5m 0s",
            ),
        )

        self.assertIn(
            "[ elapsed_time: 00:00:00 ]",
            rendered,
        )


    def test_strip_active_memory_runtime_metadata_keeps_status_for_l1(self):

        memory = strip_active_memory_runtime_metadata(
            (
                "active_memory: Secret word: Sun "
                "[ purpose: Ask user to guess ] "
                "[ creation_time: 2026-06-20T10:00:00 ] "
                "[ created_jin_message_number: 3 ] "
                "[ elapsed_time: 01:02:03 ] "
                "[ elapsed_jin_message_number: 2 ] "
                "[ status: pending ]\n"
                "primary_goal: Play a memory game."
            )
        )

        self.assertIn(
            (
                "active_memory: Secret word: Sun "
                "[ purpose: Ask user to guess ] "
                "[ status: pending ]"
            ),
            memory,
        )
        self.assertIn(
            "primary_goal: Play a memory game.",
            memory,
        )
        self.assertNotIn(
            "creation_time",
            memory,
        )
        self.assertNotIn(
            "elapsed_time",
            memory,
        )

    async def test_summarizer_hides_active_memory_runtime_metadata_from_l1_payload(self):

        service_client = FakeServiceClient(
            (
                "active_memory: Secret word: Sun "
                "[ purpose: Ask user to guess ] "
                "[ status: pending ]"
            )
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
            runtime_memory=(
                "active_memory: Secret word: Sun "
                "[ purpose: Ask user to guess ] "
                "[ creation_time: 2026-06-20T10:00:00 ] "
                "[ created_jin_message_number: 3 ] "
                "[ elapsed_time: 00:00:00 ] "
                "[ elapsed_jin_message_number: 0 ] "
                "[ status: pending ]"
            ),
            runtime_memory_stable=(
                "active_memory: Secret word: Sun "
                "[ purpose: Ask user to guess ] "
                "[ creation_time: 2026-06-20T10:00:00 ] "
                "[ created_jin_message_number: 3 ] "
                "[ elapsed_time: 00:00:00 ] "
                "[ elapsed_jin_message_number: 0 ] "
                "[ status: pending ]"
            ),
            runtime_memory_updates=1,
            runtime_memory_snapshots=[],
            runtime_memory_snapshot_index=0,
            session_id="test-session",
            timestamp="2026-06-20T10:03:04",
            turn_number=5,
        )

        async def emit(event):
            context.emitter.events.append(
                event
            )

        context.emitter.emit = emit

        updated_memory = await summarize_runtime_memory(
            context=context,
            user_message="thanks",
            assistant_message="You are welcome.",
        )

        user_prompt = service_client.calls[0]["user_prompt"]

        self.assertNotIn(
            "creation_time",
            user_prompt,
        )
        self.assertNotIn(
            "elapsed_time",
            user_prompt,
        )
        self.assertIn(
            "[ status: pending ]",
            user_prompt,
        )
        self.assertIn(
            "[ elapsed_time: 00:03:04 ]",
            updated_memory,
        )
        self.assertIn(
            "[ elapsed_jin_message_number: 2 ]",
            updated_memory,
        )

    async def test_summarizer_logs_active_memory_collapse_payload(self):

        service_client = FakeServiceClient(
            (
                "active_memory_2: Secret word: Water "
                "[ purpose: Ask user to guess ] "
                "[ status: pending, Reminder given in Turn 1 ]"
            )
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
            runtime_memory=(
                "active_memory_1: Secret word: Water "
                "[ purpose: Ask user to guess ] "
                "[ status: pending ]"
            ),
            runtime_memory_stable=(
                "active_memory_1: Secret word: Water "
                "[ purpose: Ask user to guess ] "
                "[ status: pending ]"
            ),
            runtime_memory_updates=1,
            runtime_memory_snapshots=[],
            runtime_memory_snapshot_index=0,
            session_id="test-session",
            timestamp="2026-06-20T10:03:04",
            turn_number=5,
        )

        async def emit(event):
            context.emitter.events.append(
                event
            )

        context.emitter.emit = emit

        updated_memory = await summarize_runtime_memory(
            context=context,
            user_message="next",
            assistant_message="Reminder sent.",
        )

        self.assertIn(
            (
                "active_memory_1: Secret word: Water "
                "[ purpose: Ask user to guess ]"
            ),
            updated_memory,
        )
        self.assertIn(
            "[ status: pending, Reminder given in Turn 1 ]",
            updated_memory,
        )
        self.assertNotIn(
            "active_memory_2:",
            updated_memory,
        )
        self.assertEqual(
            len(logger.active_memory_logs),
            1,
        )
        message, details, event = logger.active_memory_logs[0]
        self.assertIn(
            "collapsed",
            message,
        )
        self.assertEqual(
            event,
            "collapse",
        )
        self.assertIn(
            '"candidate_key": "active_memory_2"',
            details,
        )
        self.assertIn(
            '"result_memory"',
            details,
        )

    async def test_summarizer_enforces_latest_user_message_when_model_is_stale(self):

        service_client = FakeServiceClient(
            (
                'user_message: "old message"\n'
                "last_jin_response: Fresh answer summary."
            )
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
            runtime_memory=(
                'user_message: "old message"\n'
                "last_jin_response: Previous answer."
            ),
            runtime_memory_updates=1,
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
            user_message="latest message",
            assistant_message="Fresh assistant answer.",
        )

        self.assertIn(
            'user_message: "latest message"',
            updated_memory,
        )
        self.assertNotIn(
            'user_message: "old message"',
            updated_memory,
        )

    async def test_summarizer_replaces_stale_last_jin_response(self):

        service_client = FakeServiceClient(
            (
                'user_message: "latest message"\n'
                "last_jin_response: Previous answer summary."
            )
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
            runtime_memory=(
                'user_message: "old message"\n'
                "last_jin_response: Previous answer summary."
            ),
            runtime_memory_updates=1,
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
            user_message="latest message",
            assistant_message="Latest assistant answer replaces the stale summary.",
        )

        self.assertIn(
            "last_jin_response: Latest assistant answer replaces the stale summary.",
            updated_memory,
        )
        self.assertNotIn(
            "last_jin_response: Previous answer summary.",
            updated_memory,
        )

    async def test_pending_turns_enforces_latest_turn_fields(self):

        service_client = FakeServiceClient(
            (
                'user_message: "first message"\n'
                "last_jin_response: Previous answer summary."
            )
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
            runtime_memory=(
                'user_message: "first message"\n'
                "last_jin_response: Previous answer summary."
            ),
            runtime_memory_stable=(
                'user_message: "first message"\n'
                "last_jin_response: Previous answer summary."
            ),
            runtime_memory_updates=1,
            runtime_memory_pending_turns=[
                {
                    "user_message": "first message",
                    "assistant_message": "First answer.",
                },
                {
                    "user_message": '"hello" [ repeated: 3 ]',
                    "assistant_message": "Latest repeated answer.",
                },
            ],
            runtime_memory_update_task=None,
            runtime_memory_snapshots=[],
            runtime_memory_snapshot_index=0,
            session_id="test-session",
        )

        async def emit(event):
            context.emitter.events.append(
                event
            )

        context.emitter.emit = emit

        updated_memory = await summarize_runtime_memory_pending_turns(
            context=context,
        )

        self.assertIn(
            'user_message: "hello" [ repeated: 3 ]',
            updated_memory,
        )
        self.assertIn(
            "last_jin_response: Latest repeated answer.",
            updated_memory,
        )

    async def test_l1_summarizer_user_prompt_stays_turn_only(self):

        service_client = FakeServiceClient(
            (
                "temporary_preference: On 2026-06-05, user requested "
                "not to discuss past topics for the rest of that day.\n"
                "last_jin_response: Acknowledged the fresh-topic preference."
            )
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
            runtime_l2_memory="",
            session_id="test-session",
            timestamp="2026-06-05T13:38:50",
            current_date="2026-06-05",
            current_time="13:38:50",
            weekday="Friday",
            year=2026,
            turn_number=12,
            user_message_count=7,
            assistant_message_count=6,
        )

        async def emit(event):
            context.emitter.events.append(
                event
            )

        context.emitter.emit = emit

        updated_memory = await summarize_runtime_memory(
            context=context,
            user_message="сегодня не хочу обсуждать прошлые темы",
            assistant_message="Хорошо, выберем свежую тему.",
        )

        user_prompt = service_client.calls[0]["user_prompt"]

        self.assertNotIn(
            "<CURRENT_TRUSTED_RUNTIME_VARIABLES>",
            user_prompt,
        )
        self.assertNotIn(
            "<CURRENT_SESSION_STATE>",
            user_prompt,
        )
        self.assertNotIn(
            "Total turns count:",
            user_prompt,
        )
        self.assertIn(
            "Latest user message:\nсегодня не хочу обсуждать прошлые темы",
            user_prompt,
        )
        self.assertIn(
            "Latest JIN answer:\nХорошо, выберем свежую тему.",
            user_prompt,
        )
        self.assertNotIn(
            "today",
            updated_memory.lower(),
        )
        self.assertIn(
            "On 2026-06-05, user requested not to discuss past topics for the rest of that day",
            updated_memory,
        )

    async def test_summarizer_preserves_durable_fact_keys(self):

        service_client = FakeServiceClient(
            (
                "session_status: Active, discussing a new topic\n"
                "last_jin_response: Asked a follow-up question."
            )
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
            runtime_memory=(
                "user_fact: Name is Sergey; lives in Kyiv\n"
                "jin_facts: JIN can keep runtime memory\n"
                "active topic: Ukraine news"
            ),
            runtime_memory_updates=1,
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
            user_message="Давай сменим тему.",
            assistant_message="Хорошо, о чем поговорим?",
        )

        self.assertIn(
            "session_status: Active, discussing a new topic",
            updated_memory,
        )
        self.assertIn(
            "user_fact: Name is Sergey; lives in Kyiv",
            updated_memory,
        )
        self.assertIn(
            "jin_facts: JIN can keep runtime memory",
            updated_memory,
        )

    async def test_summarizer_allows_explicit_fact_negation(self):

        service_client = FakeServiceClient(
            (
                "user_fact: not true; user corrected this fact\n"
                "session_status: Active, discussing a correction\n"
                "last_jin_response: Acknowledged the correction."
            )
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
            runtime_memory=(
                "user_fact: Name is Sergey; lives in Kyiv\n"
                "active topic: personal context"
            ),
            runtime_memory_updates=1,
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
            user_message="Это уже не факт.",
            assistant_message="Понял, убираю этот факт из памяти.",
        )

        self.assertIn(
            "user_fact: not true; user corrected this fact",
            updated_memory,
        )
        self.assertNotIn(
            "Name is Sergey; lives in Kyiv",
            updated_memory,
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
        self.assertIn(
            "[MEMORY:L2] L2 memory updated",
            logger.service_logs,
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

    def test_l3_session_memory_prompt_uses_all_runtime_snapshots(self):

        prompt = build_runtime_session_memory_user_prompt(
            current_session_memory="decision: old handoff",
            session_event_snapshots=[
                {
                    "memory_type": "session_event_snapshot",
                    "memory": "decision: previous event",
                }
            ],
            runtime_memory_snapshots=[
                {
                    "index": 0,
                    "raw_memory": "topic: first topic",
                    "total_diff": 30,
                },
                {
                    "index": 1,
                    "raw_memory": "decision: final direction",
                    "total_diff": 80,
                },
            ],
            diff_history=[
                {
                    "snapshot_index": 1,
                    "total_diff": 80,
                },
            ],
        )

        self.assertIn(
            "Selected L1 runtime memory snapshot history",
            prompt,
        )
        self.assertIn(
            "topic: first topic",
            prompt,
        )
        self.assertIn(
            "decision: final direction",
            prompt,
        )
        self.assertIn(
            '"total_diff": 80',
            prompt,
        )
        self.assertIn(
            "omitted_middle_snapshots: 0",
            prompt,
        )
        self.assertIn(
            "Recent L1 diff history",
            prompt,
        )
        self.assertIn(
            "omitted_older_diffs: 0",
            prompt,
        )
        self.assertIn(
            "Session event snapshots array",
            prompt,
        )
        self.assertIn(
            "previous event",
            prompt,
        )

    def test_l3_session_memory_prompt_bounds_long_snapshot_history(self):

        prompt = build_runtime_session_memory_user_prompt(
            current_session_memory="decision: old handoff",
            session_event_snapshots=[
                {
                    "memory_type": "session_event_snapshot",
                    "initiated_by": "user",
                    "assistant_response": "x" * 1200,
                }
            ],
            runtime_memory_snapshots=[
                {
                    "index": index,
                    "raw_memory": f"topic: snapshot {index}",
                    "total_diff": index,
                }
                for index in range(30)
            ],
            diff_history=[
                {
                    "snapshot_index": index,
                    "total_diff": index,
                }
                for index in range(40)
            ],
        )

        self.assertIn(
            "omitted_middle_snapshots: 24",
            prompt,
        )
        self.assertIn(
            "topic: snapshot 0",
            prompt,
        )
        self.assertIn(
            "topic: snapshot 29",
            prompt,
        )
        self.assertNotIn(
            "topic: snapshot 10",
            prompt,
        )
        self.assertIn(
            "omitted_older_diffs: 32",
            prompt,
        )
        self.assertIn(
            "<truncated>",
            prompt,
        )

    def test_l3_session_memory_prompt_uses_compact_digest_not_raw_archive(self):

        prompt = build_runtime_session_memory_user_prompt(
            current_session_memory="\n".join(
                f"old narrative {index}: {'a' * 300}"
                for index in range(20)
            ),
            runtime_l2_memory="\n".join(
                f"stale l2 archive {index}: {'b' * 200}"
                for index in range(20)
            ),
            session_event_snapshots=[
                {
                    "memory_type": "session_event_snapshot",
                    "assistant_response": "c" * 1000,
                }
                for _index in range(10)
            ],
            runtime_memory_snapshots=[
                {
                    "index": index,
                    "raw_memory": (
                        f"decision: keep snapshot {index}\n"
                        f"narrative: {'d' * 1200}"
                    ),
                    "total_diff": index,
                }
                for index in range(12)
            ],
            diff_history=[
                {
                    "snapshot_index": index,
                    "total_diff": index,
                    "changes": {
                        "changed": [
                            {
                                "previous_key": "narrative",
                                "previous_value": "e" * 1000,
                                "current_key": "decision",
                                "current_value": "f" * 1000,
                            }
                        ],
                    },
                }
                for index in range(20)
            ],
        )

        self.assertIn(
            "L3 compact digest minimal: False",
            prompt,
        )
        self.assertIn(
            "Compact L2 pattern context:",
            prompt,
        )
        self.assertNotIn(
            "Current L2 pattern memory for context only:",
            prompt,
        )
        self.assertLessEqual(
            prompt.count("snapshot:"),
            6,
        )
        self.assertNotIn(
            "c" * 500,
            prompt,
        )
        self.assertNotIn(
            "e" * 500,
            prompt,
        )
        self.assertIn(
            "omitted_older_diffs:",
            prompt,
        )

    def test_l3_session_memory_prompt_defines_episodic_key_moments(self):

        prompt = build_runtime_session_memory_system_prompt()

        # Check stable L3 session-memory capabilities, not the exact prose.
        for required_text in (
                "episodic_key_moment",
                "Session event snapshots",
                "session-context level",
                "Do not ask the user to fill snapshot fields manually",
                "cause",
                "event",
                "outcome",
                "emotional",
                "memory_type: episodic_key_moment",
                "emotional_weight:",
                "preserve_detail:",
                "durable JIN/user fact",
                "CURRENT_TRUSTED_RUNTIME_VARIABLES",
                "USER_DATETIME",
                "relative temporal phrases",
                "today, now, or recently",
                "temporary_preference:",
        ):
            self.assertIn(
                required_text,
                prompt,
            )

    def test_l3_session_memory_user_prompt_preserves_existing_episodic_memory(self):

        current_session_memory = (
            "memory_type: episodic_key_moment\n"
            "title: Meta-debug moment\n"
            "emotional_weight: high\n"
            "why_it_matters: The user corrected a memory interpretation bug.\n"
            "sequence:\n"
            "1. The assistant misread the experiment.\n"
            "2. The user corrected it.\n"
            "preserve_detail: The correction chain matters."
        )

        prompt = build_runtime_session_memory_user_prompt(
            current_session_memory=current_session_memory,
            runtime_memory_snapshots=[],
            diff_history=[],
        )

        self.assertIn(
            "Current L3 session memory:",
            prompt,
        )
        self.assertIn(
            "memory_type: episodic_key_moment",
            prompt,
        )
        self.assertIn(
            "title: Meta-debug moment",
            prompt,
        )
        self.assertIn(
            "preserve_detail: The correction chain matters.",
            prompt,
        )

    def test_l3_session_memory_budget_uses_detected_context_window(self):

        system_prompt = "system " * 2000
        user_prompt = "user " * 2000

        configured_budget = build_l3_session_memory_max_tokens(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        detected_budget = build_l3_session_memory_max_tokens(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            context_window=8192,
        )

        self.assertEqual(
            configured_budget,
            128,
        )
        self.assertGreater(
            detected_budget,
            configured_budget,
        )

    async def test_l3_session_memory_updates_from_snapshot_history(self):

        service_client = FakeServiceClient(
            "decision: Continue session memory implementation\n"
            "next step: Verify browser persistence"
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
            runtime_remember_session_requested=True,
            runtime_l3_session_memory="",
            session_memory="",
            session_memory_source="",
            runtime_session_memory_updates=0,
            runtime_session_event_snapshots=[],
            runtime_l2_memory="",
            timestamp="2026-06-05T13:38:50",
            current_date="2026-06-05",
            current_time="13:38:50",
            weekday="Friday",
            year=2026,
            runtime_l1_diff_history=[
                {
                    "snapshot_index": 1,
                    "total_diff": 80,
                },
            ],
            runtime_memory_snapshot_index=1,
            runtime_memory_snapshots=[
                {
                    "index": 0,
                    "raw_memory": "topic: first topic",
                    "total_diff": 30,
                },
                {
                    "index": 1,
                    "raw_memory": "decision: final direction",
                    "total_diff": 80,
                },
            ],
        )

        async def emit(event):
            context.emitter.events.append(
                event
            )

        context.emitter.emit = emit

        updated_memory = await maybe_summarize_runtime_session_memory(
            context=context,
        )

        self.assertIn(
            "Continue session memory implementation",
            updated_memory,
        )
        self.assertEqual(
            context.runtime_session_memory_updates,
            1,
        )
        self.assertFalse(
            context.runtime_remember_session_requested,
        )
        self.assertEqual(
            context.runtime_memory_snapshots,
            [
                {
                    "index": 0,
                    "raw_memory": "topic: first topic",
                    "total_diff": 30,
                },
                {
                    "index": 1,
                    "raw_memory": "decision: final direction",
                    "total_diff": 80,
                },
            ],
        )
        self.assertEqual(
            context.runtime_memory_snapshot_index,
            1,
        )
        self.assertEqual(
            context.session_memory_source,
            "L3",
        )
        self.assertEqual(
            context.runtime_session_event_snapshots,
            [],
        )
        self.assertIn(
            "topic: first topic",
            service_client.calls[0]["user_prompt"],
        )
        self.assertIn(
            "decision: final direction",
            service_client.calls[0]["user_prompt"],
        )
        self.assertIn(
            "<USER_DATETIME>2026-06-05 13:38, Friday</USER_DATETIME>",
            service_client.calls[0]["user_prompt"],
        )
        self.assertLess(
            service_client.calls[0]["user_prompt"].index(
                "<CURRENT_TRUSTED_RUNTIME_VARIABLES>"
            ),
            service_client.calls[0]["user_prompt"].index(
                "Current L3 session memory:"
            ),
        )
        self.assertEqual(
            service_client.calls[0]["timeout"],
            config.SERVICE_REQUEST_TIMEOUT,
        )
        self.assertLess(
            service_client.calls[0]["max_tokens"],
            config.SERVICE_MAX_TOKENS,
        )
        self.assertGreaterEqual(
            service_client.calls[0]["max_tokens"],
            128,
        )
        self.assertEqual(
            service_client.calls[0]["max_tokens"],
            L3_OUTPUT_MAX_TOKENS,
        )
        self.assertIn(
            (
                "[MEMORY:L3] L3 session output token budget capped at "
                f"{L3_OUTPUT_MAX_TOKENS}"
            ),
            logger.runtime_logs,
        )
        self.assertEqual(
            context.emitter.events[-2]["type"],
            "runtime_session_memory_update",
        )
        self.assertTrue(
            context.emitter.events[-2]["persist"],
        )
        self.assertEqual(
            context.emitter.events[-1],
            {
                "type": "runtime_action",
                "action": "remember_session",
                "status": "completed",
            },
        )

    async def test_l3_session_memory_merges_previous_snapshot_with_unsaved_tail_only(self):

        service_client = FakeServiceClient(
            "decision: merged handoff after new tail"
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
            runtime_remember_session_requested=True,
            runtime_l3_session_memory=(
                "session_snapshot_first_turn: 0\n"
                "session_snapshot_last_turn: 15\n"
                "decision: old consolidated handoff"
            ),
            session_memory="",
            session_memory_source="",
            runtime_session_memory_updates=1,
            runtime_l3_saved_runtime_snapshot_index=15,
            runtime_l3_session_first_turn=0,
            runtime_l3_session_last_turn=15,
            runtime_session_event_snapshots=[],
            runtime_l2_memory="",
            timestamp="2026-06-05T13:38:50",
            current_date="2026-06-05",
            current_time="13:38:50",
            weekday="Friday",
            year=2026,
            runtime_l1_diff_history=[
                {
                    "snapshot_index": 15,
                    "total_diff": 80,
                },
                {
                    "snapshot_index": 16,
                    "total_diff": 20,
                },
                {
                    "snapshot_index": 20,
                    "total_diff": 70,
                },
            ],
            runtime_memory_snapshot_index=20,
            runtime_memory_snapshots=[
                {
                    "index": 14,
                    "raw_memory": "topic: old stale page",
                    "total_diff": 30,
                },
                {
                    "index": 15,
                    "raw_memory": "decision: old saved boundary",
                    "total_diff": 80,
                },
                {
                    "index": 16,
                    "raw_memory": "topic: fresh tail starts",
                    "total_diff": 20,
                },
                {
                    "index": 20,
                    "raw_memory": "decision: fresh tail ends",
                    "total_diff": 70,
                },
            ],
        )

        async def emit(event):
            context.emitter.events.append(
                event
            )

        context.emitter.emit = emit

        updated_memory = await maybe_summarize_runtime_session_memory(
            context=context,
        )

        prompt = service_client.calls[0]["user_prompt"]

        self.assertIn(
            "decision: old consolidated handoff",
            prompt,
        )
        self.assertIn(
            "topic: fresh tail starts",
            prompt,
        )
        self.assertIn(
            "decision: fresh tail ends",
            prompt,
        )
        self.assertNotIn(
            "topic: old stale page",
            prompt,
        )
        self.assertNotIn(
            "decision: old saved boundary",
            prompt,
        )
        self.assertIn(
            "session_snapshot_first_turn: 0",
            updated_memory,
        )
        self.assertIn(
            "session_snapshot_last_turn: 20",
            updated_memory,
        )
        self.assertEqual(
            context.runtime_l3_saved_runtime_snapshot_index,
            20,
        )
        self.assertEqual(
            context.runtime_l3_session_last_turn,
            20,
        )

    async def test_l3_session_memory_logs_when_response_reaches_max_tokens(self):

        service_client = FakeServiceClient(
            "decision: incomplete",
            finish_reasons=[
                "length",
            ],
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
            runtime_remember_session_requested=True,
            runtime_l3_session_memory="decision: keep current",
            session_memory="decision: keep current",
            session_memory_source="",
            runtime_session_memory_updates=0,
            runtime_session_event_snapshots=[],
            runtime_l2_memory="",
            runtime_l1_diff_history=[],
            runtime_memory_snapshots=[
                {
                    "index": 0,
                    "raw_memory": "topic: first topic",
                    "total_diff": 30,
                },
            ],
        )

        async def emit(event):
            context.emitter.events.append(
                event
            )

        context.emitter.emit = emit

        updated_memory = await maybe_summarize_runtime_session_memory(
            context=context,
        )

        self.assertEqual(
            updated_memory,
            "decision: keep current",
        )
        self.assertTrue(
            context.runtime_remember_session_requested,
        )
        self.assertEqual(
            context.runtime_memory_snapshots,
            [
                {
                    "index": 0,
                    "raw_memory": "topic: first topic",
                    "total_diff": 30,
                },
            ],
        )
        self.assertIn(
            "[MEMORY:L3] L3 session summarizer reached max_tokens",
            logger.runtime_logs,
        )
        self.assertEqual(
            logger.errors[-1][0],
            "[MEMORY:L3] L3 session memory update skipped",
        )
        self.assertIn(
            "truncated by max_tokens",
            logger.errors[-1][1],
        )

    async def test_l3_session_memory_skips_when_minimal_digest_exceeds_budget(self):

        class TinyContextServiceClient(FakeServiceClient):

            async def resolve_request_context_window(self):
                return 600

        service_client = TinyContextServiceClient(
            "should not be called"
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
            runtime_remember_session_requested=True,
            runtime_l3_session_memory="decision: keep current",
            session_memory="decision: keep current",
            session_memory_source="",
            runtime_session_memory_updates=0,
            runtime_session_event_snapshots=[],
            runtime_l2_memory="",
            runtime_l1_diff_history=[],
            runtime_memory_snapshots=[
                {
                    "index": 0,
                    "raw_memory": "decision: keep latest",
                    "total_diff": 1,
                }
            ],
        )

        async def emit(event):
            context.emitter.events.append(
                event
            )

        context.emitter.emit = emit

        updated_memory = await maybe_summarize_runtime_session_memory(
            context=context,
        )

        self.assertEqual(
            updated_memory,
            "decision: keep current",
        )
        self.assertEqual(
            service_client.calls,
            [],
        )
        self.assertEqual(
            context.emitter.events[-1],
            {
                "type": "runtime_action",
                "action": "remember_session",
                "status": "completed",
            },
        )
        self.assertEqual(
            logger.errors[-1][0],
            "[MEMORY:L3] L3 session memory update skipped",
        )
        self.assertIn(
            "compact digest still exceeds safe input budget",
            logger.errors[-1][1],
        )
        self.assertEqual(
            context.runtime_memory_snapshots,
            [
                {
                    "index": 0,
                    "raw_memory": "decision: keep latest",
                    "total_diff": 1,
                }
            ],
        )

    async def test_l3_session_memory_preserves_snapshots_when_update_fails(self):

        service_client = FakeServiceClient(
            RuntimeError("service unavailable")
        )
        logger = FakeLogger()
        snapshots = [
            {
                "index": 0,
                "raw_memory": "topic: first topic",
                "total_diff": 30,
            },
            {
                "index": 1,
                "raw_memory": "decision: final direction",
                "total_diff": 80,
            },
        ]
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            emitter=SimpleNamespace(
                events=[],
                emit=None,
            ),
            logger=logger,
            runtime_remember_session_requested=True,
            runtime_l3_session_memory="decision: keep current",
            session_memory="decision: keep current",
            session_memory_source="",
            runtime_session_event_snapshots=[],
            runtime_l2_memory="",
            runtime_l1_diff_history=[],
            runtime_memory_snapshots=list(snapshots),
        )

        async def emit(event):
            context.emitter.events.append(
                event
            )

        context.emitter.emit = emit

        updated_memory = await maybe_summarize_runtime_session_memory(
            context=context,
        )

        self.assertEqual(
            updated_memory,
            "decision: keep current",
        )
        self.assertTrue(
            context.runtime_remember_session_requested,
        )
        self.assertEqual(
            context.runtime_memory_snapshots,
            snapshots,
        )
        self.assertEqual(
            logger.errors[-1][0],
            "[MEMORY:L3] L3 session memory update failed",
        )

    async def test_l3_session_memory_no_snapshots_leaves_buffer_empty(self):

        service_client = FakeServiceClient(
            "should not be called"
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
            runtime_remember_session_requested=True,
            runtime_l3_session_memory="decision: keep current",
            session_memory="decision: keep current",
            runtime_memory_snapshots=[],
        )

        async def emit(event):
            context.emitter.events.append(
                event
            )

        context.emitter.emit = emit

        updated_memory = await maybe_summarize_runtime_session_memory(
            context=context,
        )

        self.assertEqual(
            updated_memory,
            "decision: keep current",
        )
        self.assertEqual(
            service_client.calls,
            [],
        )
        self.assertEqual(
            context.runtime_memory_snapshots,
            [],
        )
        self.assertTrue(
            context.runtime_remember_session_requested,
        )
        self.assertEqual(
            logger.runtime_logs,
            [
                "[MEMORY:L3] L3 session save skipped: no snapshots",
            ],
        )

    async def test_summarizer_usage_corrects_estimate_with_prompt_usage(self):

        service_client = FakeServiceClient(
            "Exact memory.",
            usage={
                "prompt_tokens": 90,
                "completion_tokens": 33,
                "total_tokens": 123,
            },
            context_window=8192,
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
        self.assertEqual(
            telemetry_events[-1]["runtime"][
                RUNTIME_MEMORY_SUMMARIZER_RUNTIME_ID
            ]["max_tokens"],
            8192,
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

        # Keep this test focused on the L1 request budget contract.
        # The summarizer may normalize bullet prefixes, so exact formatting is not relevant here.
        self.assertIn(
            "Active topic: available functions",
            updated_memory,
        )
        self.assertIn(
            "Capabilities listed: answering questions and writing text",
            updated_memory,
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
        self.assertEqual(
            service_client.calls[0]["timeout"],
            config.SERVICE_REQUEST_TIMEOUT,
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
            "[MEMORY:L1] L1 runtime memory update failed",
        )
        self.assertIn(
            "Traceback (most recent call last):",
            details,
        )
        self.assertIn(
            "SilentError",
            details,
        )

    async def test_summarizer_failure_logs_likely_token_reason(self):

        request = httpx.Request(
            "POST",
            "http://127.0.0.1:1234/v1/chat/completions",
        )
        response = httpx.Response(
            400,
            json={
                "error": {
                    "message": (
                        "This model's maximum context length is 8192 tokens, "
                        "but the request asked for 9000 tokens."
                    ),
                    "type": "invalid_request_error",
                    "code": "context_length_exceeded",
                }
            },
            request=request,
        )
        service_client = FakeServiceClient(
            httpx.HTTPStatusError(
                "Client error '400 Bad Request'",
                request=request,
                response=response,
            )
        )
        logger = FakeLogger()
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            logger=logger,
            runtime_memory="Initial memory.",
            runtime_memory_updates=0,
        )

        await summarize_runtime_memory(
            context=context,
            user_message="Remember this.",
            assistant_message="I will remember it.",
        )

        _message, details = logger.errors[0]

        self.assertIn(
            "Likely reason: Token/context limit exceeded",
            details,
        )
        self.assertIn(
            "context_length_exceeded",
            details,
        )
        self.assertIn(
            "Traceback:",
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

        user_prompt = service_client.calls[0]["user_prompt"]

        self.assertNotIn(
            "<CURRENT_TRUSTED_RUNTIME_VARIABLES>",
            user_prompt,
        )
        self.assertNotIn(
            "New completed turns since that memory snapshot:",
            user_prompt,
        )

        self.assertIn(
            "Updated background memory.",
            context.runtime_memory,
        )
        self.assertIn(
            'user_message: "First message"',
            context.runtime_memory,
        )
        self.assertIn(
            "last_jin_response: First answer",
            context.runtime_memory,
        )
        self.assertEqual(
            context.logger.summarizer_logs[0][0],
            "[MEMORY:L1] L1 summarizer request",
        )
        self.assertEqual(
            service_client.calls[0]["timeout"],
            config.SERVICE_REQUEST_TIMEOUT,
        )
        self.assertEqual(
            len(
                context.background_tasks
            ),
            0,
        )

    async def test_pending_turns_log_batch_only_for_multiple_turns(self):

        service_client = FakeServiceClient(
            "Updated batch memory."
        )
        logger = FakeLogger()
        context = SimpleNamespace(
            clients={
                "service": service_client,
            },
            logger=logger,
            runtime_memory="Initial memory.",
            runtime_memory_stable="Initial memory.",
            runtime_memory_updates=0,
            runtime_memory_pending_turns=[
                {
                    "user_message": "First message",
                    "assistant_message": "First answer",
                },
                {
                    "user_message": "Second message",
                    "assistant_message": "Second answer",
                },
            ],
            runtime_memory_update_task=None,
        )

        await summarize_runtime_memory_pending_turns(
            context=context,
        )

        self.assertEqual(
            logger.summarizer_logs[0][0],
            "[MEMORY:L1] L1 batch summarizer request",
        )
        self.assertEqual(
            service_client.calls[0]["timeout"],
            config.SERVICE_REQUEST_TIMEOUT,
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
