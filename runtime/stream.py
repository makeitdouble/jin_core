import asyncio
import contextlib
import traceback
import uuid
import time

import httpx



from runtime.state_sync import (
    refresh_runtime_state,
)

from runtime.L1_memory_utils import (
    build_runtime_session_checkpoint,
)
from runtime.runtime_context import (
    RECENT_MESSAGES_MAX_PAIRS,
)


from runtime.client import (
    LMStudioAPIError,
)


from utils.stream_handler import (
    StreamHandler,
)
from utils.stream_validator import (
    INCORRECT_LT_FACT_IDS_HALLUCINATION_REASON,
    SAME_ANSWER_OUTPUT_REASON,
)

from utils.token_usage import (
    calibrate_runtime_token_estimate,
    get_runtime_token_estimate_scale,
    record_stream_token_usage,
)

from utils.tokens import (
    estimate_stream_input_tokens,
    estimate_stream_live_tokens,
)
from utils.actions import (
    build_runtime_action_id,
    emit_runtime_action_counter_updates,
    extract_search_query,
    is_delayed_memory_report_id,
    RuntimeActionCounter,
    normalize_jin_color_payload,
    normalize_jin_size_dict,
    normalize_jin_size_payload,
    format_jin_size_payload,
    RuntimeActionRepetitionGuard,
    RuntimeActionStreamFilter,
)
from runtime.behavior_contract import (
    get_action_guard_name_for_runtime_action,
    get_action_guard_triggers,
    should_pause_action_guard_for_confirmation,
)
from contracts.rules_assembler import (
    RUNTIME_ACTION_DEEP_WEB_SEARCH,
    RUNTIME_ACTION_LOAD_DELAYED_MEMORY,
    RUNTIME_ACTION_LOAD_SKILL,
    RUNTIME_ACTION_ASSET_ACTION,
    RUNTIME_ACTION_JIN_COLOR,
    RUNTIME_ACTION_JIN_SIZE,
    RUNTIME_ACTION_SAVE_ACTIVE_MEMORY,
    RUNTIME_ACTION_UPDATE_LT_FACTS,
    RUNTIME_ACTION_UNLOAD_DELAYED_MEMORY,
    RUNTIME_ACTION_SAVE_DELAYED_MEMORY,
    build_runtime_action_display_text,
    get_runtime_action_display_name,
    runtime_action_has_close_tag,
)
from rules.runtime import (
    ACTION_ACCEPTED_MISSING_TRIGGER_WORDS_MESSAGE,
    ACTION_REJECTED_MISSING_TRIGGER_WORDS_MESSAGE,
)
from utils.skills_asset_utils import (
    normalize_skill_name,
)
from utils.session_actions_history import (
    attach_session_action_jin_message_since,
    build_context_limit_history_text,
    build_delayed_memory_save_rejected_history_text,
    build_reasoning_loop_history_text,
    compact_session_action_history_since,
    emit_session_actions_update,
    extract_asset_action_marker_name,
    prune_session_action_history_to_current_session,
    replace_session_action_history_since,
    record_session_action_history,
    upsert_session_action_marker_history_since,
)
from utils.tool_results import (
    TOOL_RESULT_KIND_DELAYED_MEMORY,
    record_runtime_tool_result,
)
from utils.runtime_action_abort import (
    mark_runtime_action_completed,
    mark_runtime_action_started,
)
from config_loader import (
    config,
)


OUTPUT_LIMIT_FINISH_REASONS = frozenset({
    "length",
    "max_tokens",
    "max_output_tokens",
})

CONTEXT_LIMIT_FINISH_REASONS = frozenset({
    "context_length",
    "context_limit",
    "context_overflow",
})

GENERATION_LIMIT_FINISH_REASONS = (
    OUTPUT_LIMIT_FINISH_REASONS
    | CONTEXT_LIMIT_FINISH_REASONS
)

class RuntimeStream:

    def __init__(
            self,
            *,
            context,
            runtime_id: str,
            role: str,
            context_window: int,
            log_method,
            enable_validator: bool = True,
            emit_to_chat: bool = True,
            emit_content_to_chat: bool | None = None,
            context_snapshot: dict | None = None,
            runtime_actions=None,
            filter_runtime_actions: bool = True,
            model_output_log_method=None,
    ):

        self.context = context
        self.websocket = context.websocket
        self.logger = context.logger

        self.runtime_id = runtime_id
        self.role = role

        self.context_window = (
            context_window
        )

        self.log_method = log_method
        self.model_output_log_method = (
            model_output_log_method
        )
        suppress_chat_content = bool(
            getattr(
                context,
                "runtime_suppress_chat_content",
                False,
            )
        )
        self.emit_to_chat = (
            emit_to_chat
            and not suppress_chat_content
        )
        self.emit_content_to_chat = (
            self.emit_to_chat
            if emit_content_to_chat is None
            else (
                emit_content_to_chat
                and not suppress_chat_content
            )
        )
        self.context_snapshot = context_snapshot or {}
        self.runtime_actions = runtime_actions or {}
        self.filter_runtime_actions_enabled = filter_runtime_actions
        if self.filter_runtime_actions_enabled:
            self.context.runtime_skill_state_barrier_active = False
        self.load_skill_marker_names = self.build_loaded_skill_name_set()
        self.repetition_guard = RuntimeActionRepetitionGuard()
        self.action_counter = RuntimeActionCounter()
        self.marker_repetition_aborted = False
        self.action_guard_rejected_aborted = False
        self.potential_loop_aborted = False
        self.context_limit_recovery_armed = False
        self.started_active_memory_action_ids = []
        self.started_delayed_memory_action_ids = []
        self.started_update_lt_facts_action_ids = []
        self.confirmed_action_guard_names = set()
        self.rejected_action_guard_names = set()
        self.action_guard_confirmation_ids = {}
        self.jin_color_action_id = ""
        self.jin_size_action_ids = {}
        self.deep_web_search_action_ids = {}
        self.started_deep_web_search_action_ids = []
        self.update_lt_facts_action_ids = {}
        self.last_jin_color_action_color = ""
        self.last_jin_size_action_size = ""
        self.runtime_action_event_offset = 0
        self.session_action_history_start = 0
        self.delayed_memory_action_payload = ""
        self.raw_content_parts = []
        self.raw_model_output = ""
        self.action_filter = RuntimeActionStreamFilter(
            enabled_actions=self.runtime_actions,
            preserve_action_marker=self.should_preserve_action_marker,
            repetition_guard=self.repetition_guard,
        )

        self.stream = StreamHandler(
            self.websocket,
            self.logger,
            role=role,
            enable_validator=(
                enable_validator
            ),
            context_snapshot=(
                context_snapshot
            ),
            previous_output=(
                getattr(
                    self.context,
                    "runtime_turn_assistant_response",
                    "",
                )
                if self.is_brain_context()
                else ""
            ),
            thinking_valid_lt_fact_ids=(
                self.get_reasoning_lt_fact_ids()
                if self.is_brain_context()
                else None
            ),
        )

    def get_reasoning_lt_fact_ids(self) -> set[str] | None:

        store = getattr(
            self.context,
            "runtime_long_term_memory_store",
            None,
        )

        if (
            not isinstance(store, dict)
            or not isinstance(store.get("facts"), list)
        ):
            return None

        fact_ids = set()

        for fact in store.get("facts", []) or []:
            if not isinstance(fact, dict):
                continue

            fact_id = str(
                fact.get(
                    "id",
                    "",
                )
                or ""
            ).strip().upper()

            if fact_id:
                fact_ids.add(
                    fact_id
                )

        return fact_ids

    def build_loaded_skill_name_set(self) -> set[str]:

        names = set()

        for skill in (
            getattr(
                self.context,
                "runtime_loaded_skills",
                [],
            )
            or []
        ):
            if isinstance(
                skill,
                dict,
            ):
                name = skill.get(
                    "name",
                    "",
                )
            else:
                name = skill

            normalized_name = normalize_skill_name(
                name
            )

            if normalized_name:
                names.add(
                    normalized_name
                )

        return names

    def get_action_guard_retry(
        self,
        action,
        guard_name: str = "",
    ) -> dict:

        retry = getattr(
            self.context,
            "runtime_action_guard_retry",
            None,
        )

        if not isinstance(retry, dict) or not retry:
            return {}

        action_name = str(
            getattr(action, "name", "")
            or ""
        ).strip().lower()
        retry_action = str(
            retry.get("action", "")
            or ""
        ).strip().lower()

        if not action_name or action_name != retry_action:
            return {}

        expected_guard = get_action_guard_name_for_runtime_action(
            getattr(action, "name", "")
        )
        retry_guard = str(
            retry.get("guard", "")
            or ""
        ).strip()

        if (
            not expected_guard
            or retry_guard != expected_guard
            or (guard_name and guard_name != expected_guard)
        ):
            return {}

        return retry

    def get_action_guard_retry_confirmation_id(
        self,
        action,
        guard_name: str = "",
    ) -> str:

        retry = self.get_action_guard_retry(
            action,
            guard_name,
        )

        return str(
            retry.get("confirmation_id", "")
            if retry
            else ""
        ).strip()

    def get_action_guard_retry_display_id(
        self,
        action,
    ) -> str:

        retry = self.get_action_guard_retry(
            action
        )

        return str(
            retry.get("id", "")
            if retry
            else ""
        ).strip()

    def accept_action_guard_retry(
        self,
        action,
        guard_name: str,
        *,
        completed: bool = False,
    ) -> bool:

        confirmation_id = (
            self.get_action_guard_retry_confirmation_id(
                action,
                guard_name,
            )
        )

        if not confirmation_id:
            return False

        self.confirmed_action_guard_names.add(
            guard_name
        )
        self.action_guard_confirmation_ids[
            id(action)
        ] = confirmation_id

        if completed:
            self.context.runtime_action_guard_retry_consumed = True

        return True

    def should_preserve_action_marker(
        self,
        raw_marker: str,
        action,
    ) -> bool:

        if action.name != RUNTIME_ACTION_LOAD_SKILL:
            return False

        requested_skill = normalize_skill_name(
            action.payload
        )

        if not requested_skill:
            return False

        if requested_skill in self.load_skill_marker_names:
            return True

        self.load_skill_marker_names.add(
            requested_skill
        )

        return False

    def build_input_prompt_text(self) -> str:

        if not isinstance(
            self.context_snapshot,
            dict,
        ):
            return ""

        parts = []

        for key in (
            "system_prompt",
            "user_prompt",
            "context_payload",
        ):

            value = self.context_snapshot.get(
                key,
                "",
            )

            if value:
                parts.append(
                    str(value)
                )

        return "\n".join(
            parts
        )

    def is_brain_context(self) -> bool:

        if not isinstance(
            self.context_snapshot,
            dict,
        ):
            return False

        return (
            self.context_snapshot.get(
                "context_role"
            )
            == "brain"
        )

    async def refresh_provider_token_usage(self):

        prompt_tokens = getattr(
            self.stream,
            "prompt_tokens",
            0,
        )

        provider_total_tokens = getattr(
            self.stream,
            "total_tokens",
            0,
        )

        estimated_context_tokens = (
            self.estimate_input_tokens()
        )
        estimated_total_tokens = (
            self.estimate_live_tokens()
        )
        estimated_output_tokens = max(
            0,
            estimated_total_tokens
            - estimated_context_tokens,
        )

        context_tokens = (
            prompt_tokens
            or estimated_context_tokens
        )
        estimated_total_with_context = (
            context_tokens
            + estimated_output_tokens
        )
        total_tokens = max(
            provider_total_tokens,
            estimated_total_with_context,
            context_tokens,
        )

        if not (
            context_tokens
            or total_tokens
        ):
            return

        await refresh_runtime_state(
            self.context,
            runtime_id=self.runtime_id,
            used_tokens=total_tokens,
            context_tokens=context_tokens,
            total_tokens=total_tokens,
            max_tokens=self.context_window,
            last_error=None,
            status="online",
        )

    def get_token_estimate_scale(self) -> float:

        return get_runtime_token_estimate_scale(
            self.context,
            self.runtime_id,
        )

    def estimate_raw_input_tokens(self) -> int:

        return estimate_stream_input_tokens(
            self.stream,
            prompt_text=(
                self.build_input_prompt_text()
            ),
        )

    def estimate_input_tokens(self) -> int:

        return estimate_stream_input_tokens(
            self.stream,
            prompt_text=(
                self.build_input_prompt_text()
            ),
            scale=self.get_token_estimate_scale(),
        )

    def estimate_live_tokens(self) -> int:

        return estimate_stream_live_tokens(
            self.stream,
            prompt_text=(
                self.build_input_prompt_text()
            ),
            scale=self.get_token_estimate_scale(),
        )

    def calibrate_token_estimate(self) -> float:

        return calibrate_runtime_token_estimate(
            self.context,
            runtime_id=self.runtime_id,
            estimated_prompt_tokens=(
                self.estimate_raw_input_tokens()
            ),
            provider_prompt_tokens=getattr(
                self.stream,
                "prompt_tokens",
                0,
            ),
        )

    async def refresh_token_usage(self):

        prompt_tokens = getattr(
            self.stream,
            "prompt_tokens",
            0,
        )

        context_tokens = (
            prompt_tokens
            or self.estimate_input_tokens()
        )

        estimated_context_tokens = (
            self.estimate_input_tokens()
        )
        estimated_total_tokens = (
            self.estimate_live_tokens()
        )
        estimated_output_tokens = max(
            0,
            estimated_total_tokens
            - estimated_context_tokens,
        )
        total_tokens = max(
            getattr(
                self.stream,
                "total_tokens",
                0,
            ),
            context_tokens
            + estimated_output_tokens,
            context_tokens,
        )

        if not total_tokens:
            return

        await refresh_runtime_state(
            self.context,
            runtime_id=(
                self.runtime_id
            ),
            used_tokens=(
                total_tokens
            ),
            context_tokens=context_tokens,
            total_tokens=total_tokens,
            max_tokens=(
                self.context_window
            ),
            last_error=None,
            status="online",
        )

    def record_token_usage(self):
        is_brain_context = self.is_brain_context()

        record_stream_token_usage(
            self.context,
            runtime_id=(
                self.runtime_id
            ),
            role=(
                "brain"
                if is_brain_context
                else self.role
            ),
            kind=(
                "brain"
                if is_brain_context
                else "service"
            ),
            stream=(
                self.stream
            ),
            prompt_text=(
                self.build_input_prompt_text()
            ),
            estimate_scale=(
                self.get_token_estimate_scale()
            ),
        )

    def capture_runtime_turn_response(self):

        if not self.is_brain_context():
            return

        validator = getattr(
            self.stream,
            "validator",
            None,
        )

        if validator and (
            getattr(
                validator,
                "same_output_reference_prefix",
                "",
            )
            or getattr(
                validator,
                "last_failure_reason",
                "",
            ) == SAME_ANSWER_OUTPUT_REASON
        ):
            return

        self.context.runtime_turn_assistant_response = (
            self.stream.response
        )

    def build_message_end_checkpoint_payload(self) -> dict:
        if not self.is_brain_context():
            return {}

        user_message = str(
            getattr(
                self.context,
                "runtime_turn_user_message",
                "",
            )
            or ""
        ).strip()
        assistant_message = str(
            getattr(
                self.stream,
                "response",
                "",
            )
            or ""
        ).strip()

        # An action-only/internal stream has no visible completed USER/JIN pair.
        # Its later follow-up stream will carry the actual visible checkpoint.
        if not user_message or not assistant_message:
            return {}

        session_snapshot = build_runtime_session_checkpoint(
            self.context
        )
        recent_turns = [
            dict(turn)
            for turn in session_snapshot.get(
                "recent_turns",
                [],
            )
            if isinstance(turn, dict)
        ]
        reasoning = str(
            getattr(
                self.stream,
                "reasoning",
                "",
            )
            or ""
        ).strip()
        now = time.time()
        current_turn = {
            "user": user_message,
            "jin": assistant_message,
            "user_created_at": float(
                getattr(
                    self.context,
                    "runtime_turn_started_at",
                    now,
                )
                or now
            ),
            "jin_created_at": now,
        }
        if reasoning:
            current_turn["reasoning"] = reasoning

        session_snapshot["recent_turns"] = (
            recent_turns + [current_turn]
        )[-RECENT_MESSAGES_MAX_PAIRS:]
        session_snapshot["previous_reasoning"] = reasoning

        if not getattr(
            self.context,
            "runtime_user_retry_active",
            False,
        ):
            session_snapshot["assistant_message_count"] = (
                int(
                    session_snapshot.get(
                        "assistant_message_count",
                        0,
                    )
                    or 0
                )
                + 1
            )
            session_snapshot[
                "current_session_assistant_message_count"
            ] = (
                int(
                    session_snapshot.get(
                        "current_session_assistant_message_count",
                        0,
                    )
                    or 0
                )
                + 1
            )
            session_snapshot["turn_number"] = (
                int(
                    session_snapshot.get(
                        "turn_number",
                        0,
                    )
                    or 0
                )
                + 1
            )

        return {
            "session_snapshot": session_snapshot,
            "completed_turn_commit": not bool(
                getattr(
                    self.context,
                    "runtime_turn_interrupted",
                    False,
                )
                or getattr(
                    self.context,
                    "runtime_turn_discard_requested",
                    False,
                )
            ),
        }


    def detect_context_limit_stage(self) -> str:

        if self.stream.response.strip():
            return "answer"

        if self.stream.reasoning.strip():
            return "reasoning"

        return "generation"

    def should_follow_up_on_context_limit(
        self,
        finish_reason: str,
    ) -> bool:

        normalized_reason = str(
            finish_reason
            or ""
        ).strip().casefold()

        return (
            not self.context_limit_recovery_armed
            and self.is_brain_context()
            and bool(
                getattr(
                    config,
                    "FOLLOW_UP_ON_LIMIT",
                    True,
                )
            )
            and normalized_reason
            in GENERATION_LIMIT_FINISH_REASONS
        )

    @staticmethod
    def classify_generation_limit(
        finish_reason: str,
    ) -> str:

        normalized_reason = str(
            finish_reason
            or ""
        ).strip().casefold()

        if normalized_reason in OUTPUT_LIMIT_FINISH_REASONS:
            return "output"

        return "context"

    def mark_context_limit_recovery(
        self,
        finish_reason: str,
    ) -> bool:

        if not self.should_follow_up_on_context_limit(
            finish_reason
        ):
            return False

        self.context_limit_recovery_armed = True
        stage = self.detect_context_limit_stage()
        normalized_reason = str(
            finish_reason
            or "length"
        ).strip().casefold()
        limit_kind = self.classify_generation_limit(
            normalized_reason
        )
        limit_label = (
            "Output token limit"
            if limit_kind == "output"
            else "Context limit"
        )

        self.capture_runtime_turn_response()
        self.context.runtime_turn_interrupted = True
        self.context.runtime_context_limit_recovery_pending = True
        self.context.runtime_context_limit_stage = stage
        self.context.runtime_context_limit_kind = limit_kind
        self.context.runtime_context_limit_finish_reason = (
            normalized_reason
        )
        self.context.runtime_turn_interruption_reason = (
            f"{limit_label} reached during "
            f"{stage}."
        )
        self.context.runtime_turn_interruption_quote = ""

        record_session_action_history(
            self.context,
            build_context_limit_history_text(
                stage,
                limit_kind,
            ),
        )

        return True

    async def close_active_streams(self):

        active_streams = getattr(
            self.context,
            "active_streams",
            {},
        )

        for response in list(
            active_streams.values()
        ):

            with contextlib.suppress(Exception):
                await response.aclose()

        active_streams.clear()

    @staticmethod
    async def close_generator(
        generator,
    ) -> None:

        close = getattr(
            generator,
            "aclose",
            None,
        )

        if close is None:
            return

        with contextlib.suppress(
            asyncio.CancelledError,
            Exception,
        ):
            await close()

    def mark_validator_interruption(
        self,
        validator=None,
    ):

        self.context.runtime_turn_interrupted = True
        self.context.runtime_reasoning_recovery_pending = True

        if validator is None:
            validator = getattr(
                self.stream,
                "validator",
                None,
            )

        reason = (
            getattr(
                validator,
                "last_failure_reason",
                "",
            )
            or "Runtime stream validator interrupted generation."
        )

        quote = (
            getattr(
                validator,
                "last_failure_loop_preview",
                "",
            )
            or getattr(
                validator,
                "last_failure_preview",
                "",
            )
        )

        self.context.runtime_turn_interruption_reason = reason
        self.context.runtime_turn_interruption_quote = quote

    def record_validator_interruption_history(
        self,
        validator=None,
    ) -> bool:

        if not self.is_brain_context():
            return False

        if validator is None:
            validator = getattr(
                self.stream,
                "validator",
                None,
            )

        quote = (
            getattr(
                validator,
                "last_failure_loop_preview",
                "",
            )
            or getattr(
                validator,
                "last_failure_preview",
                "",
            )
        )

        reason = str(
            getattr(
                validator,
                "last_failure_reason",
                "",
            )
            or ""
        ).strip()

        if reason == SAME_ANSWER_OUTPUT_REASON:
            history_text = (
                'stuck in answering loop reason '
                f'"{reason}"'
            )
        elif reason == INCORRECT_LT_FACT_IDS_HALLUCINATION_REASON:
            history_text = (
                'stuck in a reasoning loop reason '
                f'"{reason}"'
            )
        else:
            history_text = build_reasoning_loop_history_text(
                quote
            )

        record_session_action_history(
            self.context,
            history_text,
        )

        return True

    async def filter_runtime_action_content(
        self,
        content: str,
    ) -> str | None:

        if not self.filter_runtime_actions_enabled:
            return content

        result = self.action_filter.filter(
            content
        )
        filtered_content = await self.apply_runtime_action_filter_result(
            result,
        )

        return filtered_content

    def filter_noop_jin_color_sequence(
        self,
        actions,
        *,
        remember: bool = True,
    ):

        current_color = self.last_jin_color_action_color
        filtered_actions = []

        for action in actions or ():
            if getattr(
                action,
                "name",
                "",
            ) != RUNTIME_ACTION_JIN_COLOR:
                filtered_actions.append(
                    action
                )
                continue

            color = normalize_jin_color_payload(
                getattr(
                    action,
                    "payload",
                    "",
                )
            )

            if (
                not color
                or color == current_color
            ):
                continue

            current_color = color
            filtered_actions.append(
                action
            )

        if remember:
            self.last_jin_color_action_color = current_color

        return tuple(
            filtered_actions
        )

    def filter_noop_jin_size_sequence(
        self,
        actions,
        *,
        remember: bool = True,
    ):

        current_size = self.last_jin_size_action_size
        filtered_actions = []

        for action in actions or ():
            if getattr(
                action,
                "name",
                "",
            ) != RUNTIME_ACTION_JIN_SIZE:
                filtered_actions.append(
                    action
                )
                continue

            size = normalize_jin_size_payload(
                getattr(
                    action,
                    "payload",
                    "",
                )
            )

            if (
                not size
                or size == current_size
            ):
                continue

            current_size = size
            filtered_actions.append(
                action
            )

        if remember:
            self.last_jin_size_action_size = current_size

        return tuple(
            filtered_actions
        )

    def get_applied_runtime_action_markers(
        self,
    ) -> list[dict]:

        current_turn_id = str(
            getattr(
                self.context,
                "runtime_current_turn_id",
                "",
            )
            or ""
        ).strip()
        markers = []

        for event in (
            getattr(
                self.context,
                "runtime_action_events",
                [],
            )
            or []
        )[
            self.runtime_action_event_offset:
        ]:
            if not isinstance(
                event,
                dict,
            ):
                continue

            if (
                str(
                    event.get("status")
                    or ""
                ).strip().casefold()
                in {
                    "failed",
                    "aborted",
                }
                or event.get("error")
            ):
                continue

            event_turn_id = str(
                event.get("runtime_turn_id")
                or ""
            ).strip()

            if (
                current_turn_id
                and event_turn_id
                and event_turn_id != current_turn_id
            ):
                continue

            action_name = str(
                event.get("name")
                or event.get("action")
                or ""
            ).strip().upper()

            if not action_name:
                continue

            payload = str(
                event.get("payload")
                or event.get("query")
                or ""
            ).strip()
            markers.append({
                "name": action_name,
                "payload": payload,
            })

        return markers

    def get_action_counter_display_payloads(
        self,
    ) -> dict:

        display_payloads = {}

        for marker in self.get_applied_runtime_action_markers():
            action_name = str(
                marker.get(
                    "name",
                    "",
                )
                or ""
            ).strip().upper()

            if action_name not in {
                RUNTIME_ACTION_JIN_COLOR,
                RUNTIME_ACTION_JIN_SIZE,
            }:
                continue

            payload = str(
                marker.get(
                    "payload",
                    "",
                )
                or ""
            ).strip()

            if not action_name or not payload:
                continue

            display_payloads.setdefault(
                action_name,
                [],
            ).append(
                payload
            )

        return display_payloads

    async def sync_session_action_marker_history(
        self,
    ) -> None:

        marker_actions = self.action_counter.marker_actions(
            display_payloads=(
                self.get_action_counter_display_payloads()
            ),
        )

        if not marker_actions:
            return

        updated = upsert_session_action_marker_history_since(
            self.context,
            self.session_action_history_start,
            marker_actions,
        )

        if not updated:
            return

        await emit_session_actions_update(
            self.context,
            current_sequence=True,
        )

    async def emit_marker_repetition_interruption(
        self,
        reason: str,
    ) -> None:

        action = getattr(
            self.repetition_guard,
            "triggered_action",
            None,
        )

        if action is None:
            return

        entry = self.action_counter.get(
            getattr(
                action,
                "name",
                "",
            ),
            getattr(
                action,
                "payload",
                "",
            ),
        )

        if entry is None:
            return

        await emit_runtime_action_counter_updates(
            self.context,
            (entry,),
            context_snapshot=(
                self.context_snapshot
            ),
            display_payloads=(
                self.get_action_counter_display_payloads()
            ),
            status="interrupted",
            detail=reason,
            runtime_message_id=(
                self.stream.message_id
            ),
        )


    def get_duplicate_delayed_memory_title(
        self,
        action,
    ) -> str:

        if (
            action.name
            != RUNTIME_ACTION_SAVE_DELAYED_MEMORY
            or not action.payload
        ):
            return ""

        from utils.brain_client_utils import (
            build_delayed_memory_report,
        )

        candidate_report = build_delayed_memory_report(
            self.context,
            action.payload,
        )
        candidate_title = ""

        for report_value in (
            candidate_report.values()
            if isinstance(candidate_report, dict)
            else ()
        ):
            if not isinstance(report_value, dict):
                continue
            candidate_title = str(
                report_value.get("title", "") or ""
            ).strip()
            if candidate_title:
                break

        if not candidate_title:
            return ""

        existing_reports = getattr(
            self.context,
            "delayed_memory_reports",
            {},
        )
        if not isinstance(existing_reports, dict):
            return ""

        for report_value in existing_reports.values():
            if not isinstance(report_value, dict):
                continue
            existing_title = str(
                report_value.get("title", "") or ""
            ).strip()
            if existing_title == candidate_title:
                return candidate_title

        return ""

    async def abort_duplicate_delayed_memory_save(
        self,
        action,
        duplicate_title: str,
    ) -> None:

        duplicate_title = str(duplicate_title or "").strip()
        if not duplicate_title:
            return

        self.potential_loop_aborted = True
        self.context.runtime_turn_interrupted = True
        self.context.runtime_reasoning_recovery_pending = True
        self.context.runtime_potential_loop_detected_pending = True
        self.context.runtime_turn_interruption_reason = (
            "Potential delayed-memory save loop detected: "
            f"duplicate title {duplicate_title!r}."
        )
        self.context.runtime_turn_interruption_quote = duplicate_title

        action_id = self.get_runtime_action_display_id(action)
        runtime_turn_id = str(
            getattr(
                self.context,
                "runtime_current_turn_id",
                "",
            )
            or ""
        ).strip()
        failure_result = {
            "ok": False,
            "action": "save_delayed_memory",
            "id": action_id,
            "title": duplicate_title,
            "error": "duplicate_delayed_memory_title",
            "detail": (
                "Potential loop detected. A delayed memory report with "
                "the exact same title already exists; save was blocked."
            ),
        }
        if runtime_turn_id:
            failure_result["runtime_turn_id"] = runtime_turn_id

        from utils.brain_client_utils import (
            record_delayed_memory_runtime_result,
        )

        record_delayed_memory_runtime_result(
            self.context,
            failure_result,
        )

        action_events = getattr(
            self.context,
            "runtime_action_events",
            None,
        )
        if not isinstance(action_events, list):
            action_events = []
            self.context.runtime_action_events = action_events

        action_event = {
            "name": "save_delayed_memory",
            "status": "failed",
            "id": action_id,
            "title": duplicate_title,
            "error": "duplicate_delayed_memory_title",
        }
        if runtime_turn_id:
            action_event["runtime_turn_id"] = runtime_turn_id
        action_events.append(action_event)

        record_session_action_history(
            self.context,
            (
                "SAVE_DELAYED_MEMORY: failed - "
                f"{duplicate_title} "
                "(duplicate delayed memory title; potential loop blocked)"
            ),
        )

        emitter = getattr(self.context, "emitter", None)
        emit = getattr(emitter, "emit", None)
        if emit is not None:
            await emit({
                "type": "runtime_action",
                "runtime_message_id": self.stream.message_id,
                "action": "save_delayed_memory",
                "id": action_id,
                "status": "failed",
                "display_name": get_runtime_action_display_name(
                    RUNTIME_ACTION_SAVE_DELAYED_MEMORY
                ),
                "close_tag": runtime_action_has_close_tag(
                    RUNTIME_ACTION_SAVE_DELAYED_MEMORY
                ),
                "text": duplicate_title,
                "error": "duplicate_delayed_memory_title",
                "detail": failure_result["detail"],
                "context": (
                    dict(self.context_snapshot)
                    if isinstance(self.context_snapshot, dict)
                    else None
                ),
            })

        await self.logger.log_runtime(
            "[RUNTIME ACTION] duplicate delayed memory title guard "
            f"interrupted stream: {duplicate_title!r}"
        )


    async def apply_runtime_action_filter_result(
        self,
        result,
    ) -> str | None:

        observed_actions = tuple(
            action
            for action in getattr(
                result,
                "observed_actions",
                (),
            )
            if action.name != RUNTIME_ACTION_DEEP_WEB_SEARCH
        )
        counter_entries = self.action_counter.record(
            observed_actions
        )
        await emit_runtime_action_counter_updates(
            self.context,
            counter_entries,
            context_snapshot=(
                self.context_snapshot
            ),
            display_payloads=(
                self.get_action_counter_display_payloads()
            ),
            runtime_message_id=(
                self.stream.message_id
            ),
        )

        started_actions = self.filter_noop_jin_color_sequence(
            getattr(
                result,
                "started_actions",
                (),
            ),
            remember=False,
        )
        started_actions = self.filter_noop_jin_size_sequence(
            started_actions,
            remember=False,
        )
        actions = self.filter_noop_jin_color_sequence(
            getattr(
                result,
                "actions",
                (),
            )
        )
        actions = self.filter_noop_jin_size_sequence(
            actions
        )

        for action in actions:
            if (
                action.name
                == RUNTIME_ACTION_SAVE_DELAYED_MEMORY
                and action.payload
            ):
                self.delayed_memory_action_payload = action.payload

        for marker in getattr(
            result,
            "removed_markers",
            (),
        ):
            if (
                "SAVE_DELAYED_MEMORY"
                in str(marker).upper()
            ):
                self.delayed_memory_action_payload = str(marker)

        if started_actions:
            await self.emit_started_runtime_actions(
                started_actions,
            )
            await self.confirm_started_runtime_action_guards(
                started_actions,
            )

        if actions:
            from utils.brain_client_utils import (
                apply_runtime_action_calls,
                log_runtime_action_marker_removals,
            )

            await log_runtime_action_marker_removals(
                self.context,
                result,
                source="runtime stream content",
            )

            immediate_actions = tuple(actions)

            if immediate_actions:
                duplicate_detected = False

                for action in immediate_actions:
                    duplicate_title = (
                        self.get_duplicate_delayed_memory_title(action)
                    )
                    if not duplicate_title:
                        continue

                    duplicate_detected = True
                    await self.abort_duplicate_delayed_memory_save(
                        action,
                        duplicate_title,
                    )
                    break

                if duplicate_detected:
                    immediate_actions = ()

                if not immediate_actions:
                    confirmed_action_ids = set()
                    rejected_action_ids = set()
                else:
                    (
                        confirmed_action_ids,
                        rejected_action_ids,
                    ) = await self.confirm_unmatched_action_guards(
                        immediate_actions
                    )

                for action in immediate_actions:
                    if (
                        id(action) in rejected_action_ids
                        and action.name
                        == RUNTIME_ACTION_SAVE_DELAYED_MEMORY
                    ):
                        self.mark_started_runtime_action_guard_rejected(
                            action,
                            result,
                        )

                actions_to_apply = tuple(
                    action
                    for action in immediate_actions
                    if not (
                        id(action) in rejected_action_ids
                        and action.name
                        == RUNTIME_ACTION_SAVE_DELAYED_MEMORY
                    )
                )

                if actions_to_apply:
                    action_display_ids = {
                        id(action): self.get_runtime_action_display_id(
                            action
                        )
                        for action in actions_to_apply
                    }

                    await apply_runtime_action_calls(
                        self.context,
                        actions_to_apply,
                        context_snapshot=self.context_snapshot,
                        confirmed_action_ids=confirmed_action_ids,
                        rejected_action_ids=rejected_action_ids,
                        guard_confirmation_ids=(
                            self.action_guard_confirmation_ids
                        ),
                        action_display_ids=action_display_ids,
                        runtime_message_id=(
                            self.stream.message_id
                        ),
                    )

        if counter_entries:
            await self.sync_session_action_marker_history()

        if getattr(
            result,
            "marker_repetition_exceeded",
            False,
        ):
            self.marker_repetition_aborted = True
            reason = getattr(
                result,
                "marker_repetition_reason",
                "",
            ) or "runtime action marker repetition limit exceeded"
            await self.emit_marker_repetition_interruption(
                reason
            )
            await self.logger.log_runtime(
                "[RUNTIME ACTION] marker repetition guard interrupted stream: "
                f"{reason}"
            )
            await self.sync_session_action_marker_history()

        if not result.text:
            return None

        return result.text

    def get_runtime_action_display_id(
        self,
        action,
    ) -> str:

        retry_display_id = self.get_action_guard_retry_display_id(
            action
        )
        if retry_display_id:
            return retry_display_id

        if action.name == RUNTIME_ACTION_JIN_COLOR:
            if not self.jin_color_action_id:
                sequence = int(
                    getattr(
                        self.context,
                        "runtime_jin_color_action_sequence",
                        0,
                    )
                    or 0
                ) + 1
                self.context.runtime_jin_color_action_sequence = sequence
                self.jin_color_action_id = build_runtime_action_id(
                    RUNTIME_ACTION_JIN_COLOR,
                    sequence,
                )

            return self.jin_color_action_id

        if action.name == RUNTIME_ACTION_JIN_SIZE:
            action_key = id(action)
            action_entry = self.jin_size_action_ids.get(
                action_key
            )
            action_id = (
                str(action_entry[1] or "").strip()
                if (
                    isinstance(action_entry, tuple)
                    and len(action_entry) == 2
                    and action_entry[0] is action
                )
                else ""
            )

            if not action_id:
                sequence = int(
                    getattr(
                        self.context,
                        "runtime_jin_size_action_sequence",
                        0,
                    )
                    or 0
                ) + 1
                self.context.runtime_jin_size_action_sequence = sequence
                action_id = build_runtime_action_id(
                    RUNTIME_ACTION_JIN_SIZE,
                    sequence,
                )
                self.jin_size_action_ids[
                    action_key
                ] = (action, action_id)

            return action_id

        if action.name == RUNTIME_ACTION_DEEP_WEB_SEARCH:
            payload_key = str(
                action.payload
                or ""
            ).strip()
            deep_search_action_ids = getattr(
                self,
                "deep_web_search_action_ids",
                None,
            )

            if not isinstance(
                deep_search_action_ids,
                dict,
            ):
                deep_search_action_ids = {}
                self.deep_web_search_action_ids = (
                    deep_search_action_ids
                )

            started_action_ids = getattr(
                self,
                "started_deep_web_search_action_ids",
                None,
            )
            if not isinstance(
                started_action_ids,
                list,
            ):
                started_action_ids = []
                self.started_deep_web_search_action_ids = (
                    started_action_ids
                )

            action_id = (
                deep_search_action_ids.get(
                    payload_key,
                    "",
                )
                if payload_key
                else ""
            )

            # Pair the opening marker and closing block to one UI row.
            if (
                not action_id
                and payload_key
                and started_action_ids
            ):
                action_id = str(
                    started_action_ids.pop(0)
                    or ""
                ).strip()
                if action_id:
                    deep_search_action_ids[payload_key] = (
                        action_id
                    )

            if not action_id:
                existing_count = len([
                    event
                    for event in getattr(
                        self.context,
                        "runtime_action_events",
                        [],
                    )
                    if isinstance(
                        event,
                        dict,
                    )
                    and event.get(
                        "name"
                    ) == RUNTIME_ACTION_DEEP_WEB_SEARCH.lower()
                ])
                sequence = max(
                    int(
                        getattr(
                            self.context,
                            "runtime_deep_web_search_action_sequence",
                            0,
                        )
                        or 0
                    ),
                    existing_count,
                ) + 1
                self.context.runtime_deep_web_search_action_sequence = (
                    sequence
                )
                action_id = build_runtime_action_id(
                    RUNTIME_ACTION_DEEP_WEB_SEARCH,
                    sequence,
                )

                if payload_key:
                    deep_search_action_ids[payload_key] = (
                        action_id
                    )
                elif action_id not in started_action_ids:
                    started_action_ids.append(
                        action_id
                    )

            return action_id

        if action.name == RUNTIME_ACTION_UPDATE_LT_FACTS:
            payload_key = str(action.payload or "").strip()
            action_id = (
                self.update_lt_facts_action_ids.get(payload_key, "")
                if payload_key
                else ""
            )

            if not action_id:
                if payload_key and self.started_update_lt_facts_action_ids:
                    action_id = self.started_update_lt_facts_action_ids.pop(0)
                else:
                    sequence = int(
                        getattr(
                            self.context,
                            "runtime_update_lt_facts_action_sequence",
                            0,
                        )
                        or 0
                    ) + 1
                    self.context.runtime_update_lt_facts_action_sequence = sequence
                    action_id = build_runtime_action_id(
                        RUNTIME_ACTION_UPDATE_LT_FACTS,
                        sequence,
                    )

                    if not payload_key:
                        self.started_update_lt_facts_action_ids.append(
                            action_id
                        )

                if payload_key:
                    self.update_lt_facts_action_ids[payload_key] = action_id

            return action_id

        if action.name == RUNTIME_ACTION_SAVE_ACTIVE_MEMORY:
            if self.started_active_memory_action_ids:
                return self.started_active_memory_action_ids.pop(0)

            sequence = int(
                getattr(
                    self.context,
                    "runtime_active_memory_action_sequence",
                    0,
                )
                or 0
            ) + 1
            self.context.runtime_active_memory_action_sequence = sequence

            return build_runtime_action_id(
                RUNTIME_ACTION_SAVE_ACTIVE_MEMORY,
                sequence,
            )

        if action.name in {
            RUNTIME_ACTION_LOAD_DELAYED_MEMORY,
            RUNTIME_ACTION_UNLOAD_DELAYED_MEMORY,
        }:
            report_id, _report = (
                self.get_delayed_memory_runtime_action_report(
                    action
                )
            )
            return report_id

        if (
            action.name
            == RUNTIME_ACTION_SAVE_DELAYED_MEMORY
            and self.started_delayed_memory_action_ids
        ):
            return self.started_delayed_memory_action_ids[-1]

        return ""

    def get_delayed_memory_runtime_action_report(
        self,
        action,
    ):

        if action.name not in {
            RUNTIME_ACTION_LOAD_DELAYED_MEMORY,
            RUNTIME_ACTION_UNLOAD_DELAYED_MEMORY,
        }:
            return "", None

        report_id = str(
            action.payload
            or ""
        ).strip().casefold()

        if not is_delayed_memory_report_id(
            report_id
        ):
            return "", None

        reports = getattr(
            self.context,
            "delayed_memory_reports",
            None,
        )

        if not isinstance(
            reports,
            dict,
        ):
            return report_id, None

        report = reports.get(
            report_id
        )

        if not isinstance(
            report,
            dict,
        ):
            return report_id, None

        return report_id, {
            **report,
            "id": report_id,
        }

    async def confirm_unmatched_action_guards(
        self,
        actions,
    ) -> tuple[set[int], set[int]]:

        confirmed_action_ids = set()
        rejected_action_ids = set()
        user_message = str(
            getattr(
                self.context,
                "runtime_turn_user_message",
                "",
            )
            or ""
        )
        emitter = getattr(
            self.context,
            "emitter",
            None,
        )
        emit = getattr(
            emitter,
            "emit",
            None,
        )

        if emit is None:
            return (
                confirmed_action_ids,
                rejected_action_ids,
            )

        for action in actions:
            guard_name = get_action_guard_name_for_runtime_action(
                action.name
            )

            if not guard_name:
                continue

            retry_was_confirmed = (
                guard_name in self.confirmed_action_guard_names
            )
            if self.accept_action_guard_retry(
                action,
                guard_name,
                completed=True,
            ):
                if not retry_was_confirmed:
                    self.append_action_guard_missing_trigger_message(
                        guard_name,
                        ACTION_ACCEPTED_MISSING_TRIGGER_WORDS_MESSAGE,
                    )
                confirmed_action_ids.add(
                    id(action)
                )
                continue

            if guard_name in self.rejected_action_guard_names:
                rejected_action_ids.add(
                    id(action)
                )
                continue

            if guard_name in self.confirmed_action_guard_names:
                confirmed_action_ids.add(
                    id(action)
                )
                continue

            if not should_pause_action_guard_for_confirmation(
                guard_name,
                user_message,
            ):
                continue

            decision = await self.wait_for_action_guard_confirmation(
                action,
                guard_name,
            )

            if decision == "reject":
                self.rejected_action_guard_names.add(
                    guard_name
                )
                rejected_action_ids.add(
                    id(action)
                )
                self.append_action_guard_missing_trigger_message(
                    guard_name,
                    ACTION_REJECTED_MISSING_TRIGGER_WORDS_MESSAGE,
                )
                continue

            self.confirmed_action_guard_names.add(
                guard_name
            )
            self.append_action_guard_missing_trigger_message(
                guard_name,
                ACTION_ACCEPTED_MISSING_TRIGGER_WORDS_MESSAGE,
            )
            confirmed_action_ids.add(
                id(action)
            )

        return (
            confirmed_action_ids,
            rejected_action_ids,
        )

    async def confirm_started_runtime_action_guards(
        self,
        actions,
    ) -> None:

        user_message = str(
            getattr(
                self.context,
                "runtime_turn_user_message",
                "",
            )
            or ""
        )

        for action in actions:
            guard_name = get_action_guard_name_for_runtime_action(
                action.name
            )

            if not guard_name:
                continue

            if self.accept_action_guard_retry(
                action,
                guard_name,
            ):
                self.append_action_guard_missing_trigger_message(
                    guard_name,
                    ACTION_ACCEPTED_MISSING_TRIGGER_WORDS_MESSAGE,
                )
                continue

            if (
                guard_name in self.confirmed_action_guard_names
                or guard_name in self.rejected_action_guard_names
            ):
                continue

            if not should_pause_action_guard_for_confirmation(
                guard_name,
                user_message,
            ):
                continue

            decision = await self.wait_for_action_guard_confirmation(
                action,
                guard_name,
            )

            if decision == "reject":
                self.rejected_action_guard_names.add(
                    guard_name
                )
                self.action_guard_rejected_aborted = True
                self.mark_started_runtime_action_guard_rejected(
                    action,
                )
                if guard_name != "save_delayed_memory":
                    self.append_action_guard_missing_trigger_message(
                        guard_name,
                        ACTION_REJECTED_MISSING_TRIGGER_WORDS_MESSAGE,
                    )
                continue

            self.confirmed_action_guard_names.add(
                guard_name
            )
            self.append_action_guard_missing_trigger_message(
                guard_name,
                ACTION_ACCEPTED_MISSING_TRIGGER_WORDS_MESSAGE,
            )

    def mark_started_runtime_action_guard_rejected(
        self,
        action,
        result=None,
    ) -> None:

        guard_name = get_action_guard_name_for_runtime_action(
            action.name
        )

        if guard_name != "save_delayed_memory":
            return

        rejected_payload = ""

        for completed_action in getattr(
            result,
            "actions",
            (),
        ):
            if (
                getattr(
                    completed_action,
                    "name",
                    "",
                )
                == RUNTIME_ACTION_SAVE_DELAYED_MEMORY
            ):
                rejected_payload = str(
                    getattr(
                        completed_action,
                        "payload",
                        "",
                    )
                    or ""
                )
                break

        rejected_title = ""

        if rejected_payload:
            from utils.brain_client_utils import (
                build_delayed_memory_report,
            )

            rejected_report = build_delayed_memory_report(
                self.context,
                rejected_payload,
            )

            for report_value in rejected_report.values():
                if isinstance(
                    report_value,
                    dict,
                ):
                    rejected_title = str(
                        report_value.get(
                            "title",
                            "",
                        )
                        or ""
                    ).strip()

                if rejected_title:
                    break

        self.context.runtime_delayed_memory_save_rejected_pending = True
        self.context.runtime_delayed_memory_save_rejected_title = (
            rejected_title
        )
        self.context.runtime_delayed_memory_save_rejected_confirmation_id = (
            self.action_guard_confirmation_ids.get(
                id(action),
                "",
            )
        )
        self.append_action_guard_missing_trigger_message(
            guard_name,
            ACTION_REJECTED_MISSING_TRIGGER_WORDS_MESSAGE,
        )

        self.delayed_memory_action_payload = (
            rejected_payload
            or self.delayed_memory_action_payload
            or "<SAVE_DELAYED_MEMORY>"
        )

    def append_action_guard_missing_trigger_message(
        self,
        guard_name: str,
        template: str,
    ) -> None:
        from utils.actions.common_action_utils import (
            format_runtime_trigger_words_message,
        )

        failure_messages = getattr(
            self.context,
            "runtime_action_failure_followup_messages",
            None,
        )
        if not isinstance(
            failure_messages,
            list,
        ):
            failure_messages = []
            self.context.runtime_action_failure_followup_messages = (
                failure_messages
            )

        message = format_runtime_trigger_words_message(
            template,
            get_action_guard_triggers(
                guard_name
            ),
        )
        if message:
            failure_messages.append(
                message
            )

    async def wait_for_action_guard_confirmation(
        self,
        action,
        guard_name: str,
    ) -> str:

        emitter = getattr(
            self.context,
            "emitter",
            None,
        )
        emit = getattr(
            emitter,
            "emit",
            None,
        )

        if emit is None:
            return "reject"

        pending = getattr(
            self.context,
            "runtime_action_guard_confirmations",
            None,
        )

        if not isinstance(
            pending,
            dict,
        ):
            pending = {}
            self.context.runtime_action_guard_confirmations = pending

        loop = asyncio.get_running_loop()
        confirmation_id = (
            f"{getattr(self.context, 'runtime_current_turn_id', '')}:"
            f"{action.name.lower()}:{uuid.uuid4().hex[:12]}"
        )
        self.action_guard_confirmation_ids[
            id(action)
        ] = confirmation_id
        future = loop.create_future()
        pending[confirmation_id] = future

        action_id = self.get_runtime_action_display_id(
            action
        )
        action_name = action.name.lower()
        triggers = list(
            get_action_guard_triggers(
                guard_name
            )
        )

        action_context_snapshot = (
            dict(self.context_snapshot)
            if isinstance(
                self.context_snapshot,
                dict,
            )
            else None
        )
        payload = {
            "type": "runtime_action_guard_confirmation",
            "runtime_message_id": self.stream.message_id,
            "action": action_name,
            "id": action_id,
            "confirmation_id": confirmation_id,
            "guard": guard_name,
            "status": "pending",
            "text": self.build_action_guard_confirmation_text(
                action_name,
                action.payload,
            ),
            "display_name": get_runtime_action_display_name(
                action.name
            ),
            "close_tag": runtime_action_has_close_tag(
                action.name
            ),
            "detail": (
                "Runtime action marker emitted without matching "
                "behavior-contract trigger words in the user message."
            ),
            "missing_triggers": triggers,
            "timeout_ms": 0,
            "retry_user_message": str(
                getattr(
                    self.context,
                    "runtime_turn_user_message",
                    "",
                )
                or ""
            ),
            "retry_attempt": 1,
        }

        if action.name == RUNTIME_ACTION_JIN_COLOR:
            color = normalize_jin_color_payload(
                action.payload
            )
            if color:
                payload["color"] = color
                payload["payload"] = color

        if action.name == RUNTIME_ACTION_JIN_SIZE:
            size = normalize_jin_size_dict(
                action.payload
            )
            size_payload = format_jin_size_payload(
                size
            )
            if size and size_payload:
                payload["size"] = size_payload
                payload["width"] = size["width"]
                payload["height"] = size["height"]
                payload["payload"] = size_payload

        if action_context_snapshot:
            payload["context"] = action_context_snapshot

        try:
            await emit(
                payload
            )

            return str(
                await future
                or "reject"
            ).strip().casefold()

        finally:
            pending.pop(
                confirmation_id,
                None,
            )

    @staticmethod
    def build_action_guard_confirmation_text(
        action_name: str,
        payload: str = "",
    ) -> str:

        return build_runtime_action_display_text(
            action_name,
            payload,
        )

    async def emit_started_runtime_actions(
        self,
        actions,
    ) -> None:

        emitter = getattr(
            self.context,
            "emitter",
            None,
        )
        emit = getattr(
            emitter,
            "emit",
            None,
        )

        if emit is None:
            return

        action_context_snapshot = (
            dict(self.context_snapshot)
            if isinstance(
                self.context_snapshot,
                dict,
            )
            else None
        )

        for action in actions:
            display_name = get_runtime_action_display_name(
                action.name
            )
            display_text = build_runtime_action_display_text(
                action.name,
                action.payload,
            )
            search_query = ""

            if action.name == RUNTIME_ACTION_DEEP_WEB_SEARCH:
                search_query = extract_search_query(
                    action.payload
                )

                if search_query:
                    display_text = f"{display_name}: {search_query}"

            (
                delayed_memory_report_id,
                delayed_memory_report,
            ) = self.get_delayed_memory_runtime_action_report(
                action
            )
            delayed_memory_title = str(
                delayed_memory_report.get(
                    "title",
                    "",
                )
                if delayed_memory_report
                else ""
            ).strip()

            if delayed_memory_title:
                display_text = (
                    f"{display_name}: "
                    f"{delayed_memory_title}"
                )
            has_close_tag = runtime_action_has_close_tag(
                action.name
            )

            if action.name == RUNTIME_ACTION_ASSET_ACTION:
                pending_ids = getattr(
                    self.context,
                    "runtime_pending_asset_action_ids",
                    None,
                )

                if not isinstance(
                    pending_ids,
                    list,
                ):
                    pending_ids = []
                    self.context.runtime_pending_asset_action_ids = (
                        pending_ids
                    )

                action_id = (
                    self.get_action_guard_retry_display_id(
                        action
                    )
                    or build_runtime_action_id(
                        RUNTIME_ACTION_ASSET_ACTION,
                        len(
                            getattr(
                                self.context,
                                "runtime_asset_results",
                                [],
                            )
                            or []
                        )
                        + len(pending_ids)
                        + 1,
                    )
                )
                if action_id not in pending_ids:
                    pending_ids.append(
                        action_id
                    )

                payload = {
                    "type": "runtime_action",
                    "action": "asset_action",
                    "id": action_id,
                    "status": "started",
                    "display_name": display_name,
                    "text": display_text,
                    "close_tag": has_close_tag,
                }
            elif action.name == RUNTIME_ACTION_SAVE_ACTIVE_MEMORY:
                action_id = self.get_action_guard_retry_display_id(
                    action
                )
                if not action_id:
                    current_sequence = int(
                        getattr(
                            self.context,
                            "runtime_active_memory_action_sequence",
                            0,
                        )
                        or 0
                    )
                    next_sequence = current_sequence + 1
                    self.context.runtime_active_memory_action_sequence = (
                        next_sequence
                    )
                    action_id = build_runtime_action_id(
                        RUNTIME_ACTION_SAVE_ACTIVE_MEMORY,
                        next_sequence,
                    )
                self.started_active_memory_action_ids.append(
                    action_id
                )

                payload = {
                    "type": "runtime_action",
                    "runtime_message_id": self.stream.message_id,
                    "action": "save_active_memory",
                    "id": action_id,
                    "status": "started",
                    "display_name": display_name,
                    "text": display_text,
                    "close_tag": has_close_tag,
                }

                if action.payload and not has_close_tag:
                    payload["payload"] = action.payload
            elif action.name == RUNTIME_ACTION_SAVE_DELAYED_MEMORY:
                pending_ids = getattr(
                    self.context,
                    "runtime_pending_delayed_memory_action_ids",
                    None,
                )

                if not isinstance(
                    pending_ids,
                    list,
                ):
                    pending_ids = []
                    self.context.runtime_pending_delayed_memory_action_ids = (
                        pending_ids
                    )

                action_id = self.get_action_guard_retry_display_id(
                    action
                )
                if not action_id:
                    current_sequence = max(
                        int(
                            getattr(
                                self.context,
                                "runtime_delayed_memory_action_sequence",
                                0,
                            )
                            or 0
                        ),
                        len(
                            getattr(
                                self.context,
                                "delayed_memory_reports",
                                {},
                            )
                            or {}
                        ),
                        len([
                            event
                            for event in getattr(
                                self.context,
                                "runtime_action_events",
                                [],
                            )
                            if isinstance(
                                event,
                                dict,
                            )
                            and event.get(
                                "name"
                            ) == "save_delayed_memory"
                        ]),
                    )
                    next_sequence = current_sequence + 1
                    self.context.runtime_delayed_memory_action_sequence = (
                        next_sequence
                    )
                    action_id = build_runtime_action_id(
                        RUNTIME_ACTION_SAVE_DELAYED_MEMORY,
                        next_sequence,
                    )
                if action_id not in pending_ids:
                    pending_ids.append(
                        action_id
                    )
                self.started_delayed_memory_action_ids.append(
                    action_id
                )

                payload = {
                    "type": "runtime_action",
                    "runtime_message_id": self.stream.message_id,
                    "action": "save_delayed_memory",
                    "id": action_id,
                    "status": "started",
                    "display_name": display_name,
                    "text": display_text,
                    "close_tag": has_close_tag,
                }
            elif action.name == RUNTIME_ACTION_JIN_COLOR:
                color = normalize_jin_color_payload(
                    action.payload
                )
                if not color:
                    continue

                payload = {
                    "type": "runtime_action",
                    "runtime_message_id": self.stream.message_id,
                    "action": "jin_color",
                    "id": self.get_runtime_action_display_id(
                        action
                    ),
                    "status": "started",
                    "display_name": display_name,
                    "text": display_text,
                    "close_tag": has_close_tag,
                    "color": color,
                    "payload": color,
                }
            elif action.name == RUNTIME_ACTION_JIN_SIZE:
                size = normalize_jin_size_dict(
                    action.payload
                )
                size_payload = format_jin_size_payload(
                    size
                )
                if not size or not size_payload:
                    continue

                payload = {
                    "type": "runtime_action",
                    "runtime_message_id": self.stream.message_id,
                    "action": "jin_size",
                    "id": self.get_runtime_action_display_id(
                        action
                    ),
                    "status": "started",
                    "display_name": display_name,
                    "text": display_text,
                    "close_tag": has_close_tag,
                    "size": size_payload,
                    "width": size["width"],
                    "height": size["height"],
                    "payload": size_payload,
                }
            else:
                payload = {
                    "type": "runtime_action",
                    "runtime_message_id": self.stream.message_id,
                    "action": action.name.lower(),
                    "id": self.get_runtime_action_display_id(
                        action
                    ),
                    "status": "started",
                    "display_name": display_name,
                    "text": display_text,
                    "close_tag": has_close_tag,
                }

                if action.name == RUNTIME_ACTION_DEEP_WEB_SEARCH:
                    payload["deep_search_parent"] = True
                    payload["deep_search_payload_ready"] = False
                    payload["scene_effect"] = "search"

                    if search_query:
                        payload["query"] = search_query

                if action.payload and not has_close_tag:
                    payload["payload"] = action.payload

            retry_confirmation_id = (
                self.get_action_guard_retry_confirmation_id(
                    action
                )
            )
            if retry_confirmation_id:
                payload["confirmation_id"] = (
                    retry_confirmation_id
                )

            if delayed_memory_report_id:
                payload["delayed_memory_report_id"] = (
                    delayed_memory_report_id
                )

            if delayed_memory_report:
                payload["delayed_memory_report"] = (
                    delayed_memory_report
                )

            if action_context_snapshot:
                payload["context"] = action_context_snapshot

            mark_runtime_action_started(
                self.context,
                action=payload.get(
                    "action",
                    action.name.lower(),
                ),
                action_id=payload.get(
                    "id",
                    "",
                ),
                display_name=payload.get(
                    "display_name",
                    display_name,
                ),
                text=payload.get(
                    "text",
                    display_text,
                ),
                payload=payload.get(
                    "payload",
                    action.payload,
                ),
                close_tag=payload.get(
                    "close_tag",
                    has_close_tag,
                ),
                context_snapshot=action_context_snapshot,
            )

            await emit(
                payload
            )

    async def fail_unfinished_delayed_memory_actions(
        self,
    ) -> None:

        if not self.started_delayed_memory_action_ids:
            return

        pending_ids = getattr(
            self.context,
            "runtime_pending_delayed_memory_action_ids",
            None,
        )

        if not isinstance(
            pending_ids,
            list,
        ):
            self.started_delayed_memory_action_ids.clear()
            return

        emitter = getattr(
            self.context,
            "emitter",
            None,
        )
        emit = getattr(
            emitter,
            "emit",
            None,
        )

        for action_id in tuple(
            self.started_delayed_memory_action_ids
        ):
            if action_id not in pending_ids:
                continue

            pending_ids.remove(
                action_id
            )

            mark_runtime_action_completed(
                self.context,
                action=RUNTIME_ACTION_SAVE_DELAYED_MEMORY,
                action_id=action_id,
            )

            save_rejected = bool(
                getattr(
                    self.context,
                    "runtime_delayed_memory_save_rejected_pending",
                    False,
                )
            )
            rejected_title = str(
                getattr(
                    self.context,
                    "runtime_delayed_memory_save_rejected_title",
                    "",
                )
                or ""
            ).strip()

            failure_result = {
                "ok": False,
                "action": "save_delayed_memory",
                "id": action_id,
                "error": (
                    "user_did_not_explicitly_request_report_save"
                    if save_rejected
                    else "Delayed memory report was not saved"
                ),
                "payload": self.delayed_memory_action_payload,
            }

            if save_rejected:
                failure_result["detail"] = "\n".join(
                    str(
                        message
                        or ""
                    ).strip()
                    for message in getattr(
                        self.context,
                        "runtime_action_failure_followup_messages",
                        [],
                    )
                    if str(
                        message
                        or ""
                    ).strip()
                )

                if rejected_title:
                    failure_result["title"] = rejected_title

                record_session_action_history(
                    self.context,
                    build_delayed_memory_save_rejected_history_text(
                        rejected_title
                    ),
                )
                await emit_session_actions_update(
                    self.context,
                    current_sequence=True,
                )
            runtime_turn_id = str(
                getattr(
                    self.context,
                    "runtime_current_turn_id",
                    "",
                )
                or ""
            ).strip()
            if runtime_turn_id:
                failure_result["runtime_turn_id"] = runtime_turn_id

            delayed_memory_results = getattr(
                self.context,
                "runtime_delayed_memory_results",
                None,
            )
            if not isinstance(
                delayed_memory_results,
                list,
            ):
                delayed_memory_results = []
                self.context.runtime_delayed_memory_results = (
                    delayed_memory_results
                )
            delayed_memory_results.append(
                failure_result
            )
            record_runtime_tool_result(
                self.context,
                TOOL_RESULT_KIND_DELAYED_MEMORY,
                failure_result,
            )

            if emit is not None:
                payload = {
                    "type": "runtime_action",
                    "runtime_message_id": self.stream.message_id,
                    "action": "save_delayed_memory",
                    "id": action_id,
                    "status": "failed",
                    "display_name": get_runtime_action_display_name(
                        RUNTIME_ACTION_SAVE_DELAYED_MEMORY
                    ),
                    "close_tag": runtime_action_has_close_tag(
                        RUNTIME_ACTION_SAVE_DELAYED_MEMORY
                    ),
                    "text": (
                        "Delayed memory save rejected"
                        if save_rejected
                        else "Delayed memory report was not saved"
                    ),
                    "delayed_memory_result": failure_result,
                }
                confirmation_id = str(
                    getattr(
                        self.context,
                        "runtime_delayed_memory_save_rejected_confirmation_id",
                        "",
                    )
                    or ""
                ).strip()
                if confirmation_id:
                    payload["confirmation_id"] = confirmation_id

                await emit(payload)

        self.started_delayed_memory_action_ids.clear()
        self.delayed_memory_action_payload = ""
        self.context.runtime_delayed_memory_save_rejected_confirmation_id = ""

    async def flush_runtime_action_content(
        self,
    ) -> str | None:

        if not self.filter_runtime_actions_enabled:
            return None

        result = self.action_filter.flush_result()

        content = await self.apply_runtime_action_filter_result(
            result,
        )

        await self.fail_unfinished_delayed_memory_actions()

        return content

    def build_action_log(
        self,
        action_event_offset: int,
    ) -> str:

        action_events = getattr(
            self.context,
            "runtime_action_events",
            [],
        )

        new_events = action_events[
            action_event_offset:
        ]

        lines = []

        for event in new_events:

            name = event.get(
                "name",
                "unknown",
            )
            action_label = str(
                name
                or "unknown"
            ).strip()

            if action_label.casefold() == "asset_action":
                action_label = "ASSET_ACTION"
                asset_action_name = extract_asset_action_marker_name(
                    event.get("payload")
                    or event.get("asset_result")
                    or event.get("detail")
                    or ""
                )
                if asset_action_name:
                    action_label = (
                        f"{action_label}: {asset_action_name}"
                    )

            lines.append(
                f"action: {action_label}"
            )

            action_id = event.get(
                "id",
                "",
            )

            if action_id:
                lines.append(
                    f"id: {action_id}"
                )

            query = event.get(
                "query",
                "",
            )

            if query:
                lines.append(
                    f"query: {query}"
                )

        return "\n".join(
            lines
        )

    # ---------------------------------------------------------
    # EXECUTE STREAM
    # ---------------------------------------------------------

    async def run(
            self,
            generator,
    ):

        # The inner brain filter and the outer runtime filter can strip
        # different markers from the same model message. Keep one history
        # boundary for the whole runtime message and compact it at the end.
        prune_session_action_history_to_current_session(
            self.context
        )
        session_action_history_start = len(
            getattr(
                self.context,
                "runtime_session_action_history",
                [],
            )
            or []
        )
        self.session_action_history_start = (
            session_action_history_start
        )

        try:

            action_event_offset = len(
                getattr(
                    self.context,
                    "runtime_action_events",
                    [],
                )
            )
            self.runtime_action_event_offset = (
                action_event_offset
            )

            await self.stream.start(
                emit=self.emit_to_chat
            )

            await self.refresh_token_usage()

            async for chunk in generator:
                chunk_type = chunk.get(
                    "type"
                )

                # -------------------------------------------------
                # USAGE
                # -------------------------------------------------

                if chunk_type == "usage":
                    self.stream.update_usage(
                        chunk
                    )
                    self.calibrate_token_estimate()
                    await self.refresh_provider_token_usage()

                    continue

                # -------------------------------------------------
                # FINISH REASON
                # -------------------------------------------------

                if chunk_type == "finish":
                    context_limit_recorded = (
                        self.mark_context_limit_recovery(
                            chunk.get(
                                "finish_reason",
                                "",
                            )
                        )
                    )
                    if context_limit_recorded:
                        await emit_session_actions_update(
                            self.context,
                            current_sequence=True,
                        )

                    continue

                # The brain client sends the unfiltered answer content at
                # the end of the stream. Keep it out of chat, but use it for
                # the dedicated BRAIN / SERVICE logger card so marker tags are
                # still visible there after runtime filtering. Reasoning is
                # intentionally excluded from this logger payload.
                if chunk_type == "raw_model_output":
                    self.raw_model_output += str(
                        chunk.get(
                            "content",
                            "",
                        )
                        or ""
                    )

                    continue

                # -------------------------------------------------
                # THINKING
                # -------------------------------------------------

                if chunk_type == "thinking":

                    thinking_content = str(
                        chunk.get(
                            "content",
                            "",
                        )
                        or ""
                    )
                    is_valid = (
                        await self.stream.send_thinking(
                            thinking_content,
                            emit=self.emit_to_chat,
                        )
                    )

                    if (
                        is_valid
                        and thinking_content.strip()
                        and self.is_brain_context()
                        and self.emit_to_chat
                        and getattr(
                            self.context,
                            "runtime_user_waiting_for_jin_answer_tracking_enabled",
                            False,
                        )
                        and not float(
                            getattr(
                                self.context,
                                "runtime_user_waiting_for_jin_answer_started_at",
                                0.0,
                            )
                            or 0.0
                        )
                    ):
                        # Start only after the first visible reasoning chunk has
                        # actually been emitted to the user. Follow-up Brain
                        # streams in the same answer reuse this single timer.
                        self.context.runtime_user_waiting_for_jin_answer_started_at = (
                            time.monotonic()
                        )

                    if not is_valid:
                        self.capture_runtime_turn_response()
                        self.mark_validator_interruption(
                            self.stream.thinking_validator
                        )
                        history_recorded = (
                            self.record_validator_interruption_history(
                                self.stream.thinking_validator
                            )
                        )
                        if history_recorded:
                            await emit_session_actions_update(
                                self.context,
                                current_sequence=True,
                            )

                        await self.close_active_streams()
                        await self.close_generator(
                            generator
                        )

                        await self.stream.finish(
                            emit=self.emit_to_chat
                        )

                        return None

                    await self.refresh_token_usage()

                    continue

                # -------------------------------------------------
                # CONTENT
                # -------------------------------------------------

                if chunk_type == "content":

                    self.raw_content_parts.append(
                        str(
                            chunk.get(
                                "content",
                                "",
                            )
                            or ""
                        )
                    )
                    content = await self.filter_runtime_action_content(
                        chunk.get(
                            "content",
                            "",
                        )
                    )

                    if (
                            content is None
                            and self.marker_repetition_aborted
                    ):
                        break

                    if self.potential_loop_aborted:
                        self.capture_runtime_turn_response()
                        await self.close_active_streams()
                        await self.close_generator(
                            generator
                        )
                        break

                    if self.action_guard_rejected_aborted:
                        await self.close_active_streams()
                        await self.close_generator(
                            generator
                        )
                        break

                    if content is None:
                        continue

                    is_valid = (
                        await self.stream.send_content(
                            content,
                            emit=(
                                self.emit_to_chat
                                and self.emit_content_to_chat
                            ),
                        )
                    )

                    if (
                            not is_valid
                    ):
                        self.capture_runtime_turn_response()
                        self.mark_validator_interruption()
                        history_recorded = (
                            self.record_validator_interruption_history()
                        )
                        if history_recorded:
                            await emit_session_actions_update(
                                self.context,
                                current_sequence=True,
                            )

                        await self.close_active_streams()
                        await self.close_generator(
                            generator
                        )

                        await self.stream.finish(
                            emit=self.emit_to_chat
                        )

                        return None

                    await self.refresh_token_usage()
                    self.capture_runtime_turn_response()

                    if self.marker_repetition_aborted:
                        break

            content_tail = (
                None
                if (
                    self.marker_repetition_aborted
                    or self.action_guard_rejected_aborted
                    or self.potential_loop_aborted
                )
                else await self.flush_runtime_action_content()
            )
            if content_tail:
                await self.stream.send_content(
                    content_tail,
                    emit=(
                        self.emit_to_chat
                        and self.emit_content_to_chat
                    ),
                )

            if self.action_guard_rejected_aborted:
                await self.fail_unfinished_delayed_memory_actions()

            await self.stream.finish(
                emit=self.emit_to_chat,
                end_payload_builder=(
                    self.build_message_end_checkpoint_payload
                    if self.emit_to_chat
                    else None
                ),
            )

            await self.refresh_token_usage()
            self.record_token_usage()
            await self.refresh_provider_token_usage()
            self.capture_runtime_turn_response()

            raw_model_output = (
                self.raw_model_output
                or "".join(
                    self.raw_content_parts
                )
            )

            if (
                self.model_output_log_method is not None
                and raw_model_output
            ):
                await self.model_output_log_method(
                    raw_model_output
                )

            log_response = self.stream.response

            if not log_response.strip():
                log_response = self.build_action_log(
                    action_event_offset
                )

            await self.log_method(
                log_response
            )

            return self.stream.response

        # ---------------------------------------------------------
        # TASK CANCELLED
        # ---------------------------------------------------------

        except asyncio.CancelledError:

            self.context.runtime_turn_interrupted = True
            self.capture_runtime_turn_response()

            await self.logger.log_runtime(
                f"{self.runtime_id} stream cancelled."
            )

            with contextlib.suppress(Exception):

                if self.emit_to_chat:

                    await self.websocket.send_json({
                        "type": "message_end",
                        "message_id": (
                            self.stream.message_id
                        ),
                    })

            with contextlib.suppress(Exception):

                await self.stream.finish(
                    emit=self.emit_to_chat
                )

            return None

        # ---------------------------------------------------------
        # RUNTIME ERROR
        # ---------------------------------------------------------
        except (
                GeneratorExit,
                httpx.ReadError,
                httpx.RemoteProtocolError,
        ):

            self.context.runtime_turn_interrupted = True
            self.capture_runtime_turn_response()

            await self.logger.log_system(
                "Generation aborted."
            )

            with contextlib.suppress(Exception):

                await self.stream.finish(
                    emit=self.emit_to_chat
                )

            return None

        except Exception as e:

            tb = traceback.format_exc()

            # -----------------------------------------------------
            # HUMAN READABLE ERROR
            # -----------------------------------------------------

            public_error = (
                "Runtime stream failed."
            )
            log_message = (
                f"[RUNTIME STREAM CRASH] {public_error}"
            )
            error_details = tb
            error_meta = {}

            if isinstance(
                    e,
                    LMStudioAPIError,
            ):

                public_error = (
                    "LM Studio request failed."
                )
                provider_summary = str(
                    getattr(
                        e,
                        "summary",
                        "",
                    )
                    or str(e)
                    or public_error
                ).strip()
                visible_summary = (
                    provider_summary[:260]
                    + (
                        "..."
                        if len(provider_summary) > 260
                        else ""
                    )
                )
                log_message = (
                    f"[LM STUDIO ERROR] {visible_summary}"
                )
                error_details = str(
                    getattr(
                        e,
                        "details",
                        "",
                    )
                    or tb
                )
                error_meta = {
                    "provider": "lm_studio",
                    "error_kind": "provider",
                }

                self.context.runtime_turn_interrupted = True
                self.context.runtime_turn_interruption_reason = (
                    provider_summary
                )
                self.context.runtime_turn_interruption_quote = ""
                self.capture_runtime_turn_response()

            elif isinstance(
                    e,
                    httpx.ConnectError,
            ):

                public_error = (
                    "Model server offline "
                    "or unreachable."
                )
                log_message = (
                    f"[RUNTIME STREAM CRASH] {public_error}"
                )

            elif isinstance(
                    e,
                    httpx.ReadTimeout,
            ):

                public_error = (
                    "Model request timeout."
                )
                log_message = (
                    f"[RUNTIME STREAM CRASH] {public_error}"
                )

            elif isinstance(
                    e,
                    httpx.HTTPStatusError,
            ):

                public_error = (
                    "Model server returned HTTP error."
                )
                log_message = (
                    f"[RUNTIME STREAM CRASH] {public_error}"
                )

            # -----------------------------------------------------
            # LOG PROVIDER PAYLOAD / FULL TRACEBACK
            # -----------------------------------------------------

            await self.logger.log_error(
                log_message,
                details=error_details,
                **error_meta,
            )

            # -----------------------------------------------------
            # SEND CLEAN ERROR TO UI
            # -----------------------------------------------------

            with contextlib.suppress(Exception):

                if self.emit_to_chat:

                    await self.websocket.send_json({
                        "type": "message_error",
                        "message_id": (
                            self.stream.message_id
                        ),
                        "text": public_error,
                    })

            return None

        finally:

            with contextlib.suppress(
                Exception
            ):
                await emit_runtime_action_counter_updates(
                    self.context,
                    self.action_counter.entries(),
                    context_snapshot=(
                        self.context_snapshot
                    ),
                    display_payloads=(
                        self.get_action_counter_display_payloads()
                    ),
                    status="counter_final",
                    runtime_message_id=(
                        self.stream.message_id
                    ),
                )

            counted_markers = (
                self.action_counter.marker_actions(
                    display_payloads=(
                        self.get_action_counter_display_payloads()
                    ),
                )
            )

            session_action_history = getattr(
                self.context,
                "runtime_session_action_history",
                [],
            )
            has_recorded_history = (
                isinstance(
                    session_action_history,
                    list,
                )
                and len(
                    session_action_history
                ) > session_action_history_start
            )

            marker_history_replaced = False

            if has_recorded_history:
                live_history_tail = [
                    item
                    for item in session_action_history[
                        session_action_history_start:
                    ]
                    if isinstance(
                        item,
                        dict,
                    )
                ]
                has_live_marker_item = any(
                    item.get(
                        "runtime_session_action_marker_item"
                    ) is True
                    for item in live_history_tail
                )
                has_semantic_history_item = any(
                    item.get(
                        "runtime_session_action_marker_item"
                    ) is not True
                    for item in live_history_tail
                )

                if (
                    has_live_marker_item
                    and has_semantic_history_item
                ):
                    session_action_history[
                        session_action_history_start:
                    ] = [
                        item
                        for item in live_history_tail
                        if item.get(
                            "runtime_session_action_marker_item"
                        ) is not True
                    ]
                    marker_history_replaced = True

            if (
                counted_markers
                and not has_recorded_history
            ):
                replace_session_action_history_since(
                    self.context,
                    session_action_history_start,
                    counted_markers,
                )
                history_compacted = True
            else:
                history_compacted = (
                    compact_session_action_history_since(
                        self.context,
                        session_action_history_start,
                    )
                    or marker_history_replaced
                )

            history_message_attached = False

            if counted_markers:
                history_message_attached = (
                    attach_session_action_jin_message_since(
                        self.context,
                        session_action_history_start,
                        self.stream.response,
                    )
                )

            if (
                history_compacted
                or history_message_attached
            ):
                with contextlib.suppress(
                    Exception
                ):
                    await emit_session_actions_update(
                        self.context,
                        current_sequence=True,
                    )
