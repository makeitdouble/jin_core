import asyncio
import contextlib
import traceback
import uuid

import httpx

from runtime.state_sync import (
    refresh_runtime_state,
)

from utils.stream_handler import (
    StreamHandler,
)

from utils.token_usage import (
    record_stream_token_usage,
)

from utils.tokens import (
    estimate_stream_input_tokens,
    estimate_stream_live_tokens,
)
from utils.runtime_actions import (
    build_runtime_action_id,
    normalize_jin_color_payload,
    RuntimeActionRepetitionGuard,
    RuntimeActionStreamFilter,
)
from runtime.behavior_contract import (
    get_action_guard_name_for_runtime_action,
    get_action_guard_triggers,
    should_pause_action_guard_for_confirmation,
)
from contracts.rules_assembler import (
    RUNTIME_ACTION_APPEND_SKILL,
    RUNTIME_ACTION_ASSET_ACTION,
    RUNTIME_ACTION_IDLE,
    RUNTIME_ACTION_JIN_COLOR,
    RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT,
)
from rules.runtime import (
    ACTION_ACCEPTED_MISSING_TRIGGER_WORDS_MESSAGE,
    ACTION_REJECTED_MISSING_TRIGGER_WORDS_MESSAGE,
)
from utils.assets_service import (
    normalize_skill_name,
)
from utils.session_actions_history import (
    build_asset_action_history_text,
    build_context_limit_history_text,
    build_delayed_memory_save_rejected_history_text,
    build_reasoning_loop_history_text,
    compact_session_action_history_since,
    emit_session_actions_update,
    record_session_action_history,
)
from utils.tool_results import (
    TOOL_RESULT_KIND_DELAYED_MEMORY,
    record_runtime_tool_result,
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
        self.emit_to_chat = emit_to_chat
        self.emit_content_to_chat = (
            emit_to_chat
            if emit_content_to_chat is None
            else emit_content_to_chat
        )
        self.context_snapshot = context_snapshot or {}
        self.runtime_actions = runtime_actions or {}
        self.filter_runtime_actions_enabled = filter_runtime_actions
        if self.filter_runtime_actions_enabled:
            self.context.runtime_skill_state_barrier_active = False
        self.append_skill_marker_names = self.build_appended_skill_name_set()
        self.repetition_guard = RuntimeActionRepetitionGuard()
        self.marker_repetition_aborted = False
        self.action_guard_rejected_aborted = False
        self.context_limit_recovery_armed = False
        self.started_delayed_memory_action_ids = []
        self.confirmed_action_guard_names = set()
        self.rejected_action_guard_names = set()
        self.action_guard_confirmation_ids = {}
        self.jin_color_action_id = ""
        self.delayed_memory_action_payload = ""
        self.raw_content_parts = []
        self.pending_idle_actions = []
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
        )

    def build_appended_skill_name_set(self) -> set[str]:

        names = set()

        for skill in (
            getattr(
                self.context,
                "runtime_appended_skills",
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

    def should_preserve_action_marker(
        self,
        raw_marker: str,
        action,
    ) -> bool:

        if action.name != RUNTIME_ACTION_APPEND_SKILL:
            return False

        requested_skill = normalize_skill_name(
            action.payload
        )

        if not requested_skill:
            return False

        if requested_skill in self.append_skill_marker_names:
            return True

        self.append_skill_marker_names.add(
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

        if not self.is_brain_context():
            return

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

        context_tokens = (
            prompt_tokens
            or estimated_context_tokens
        )
        total_tokens = max(
            provider_total_tokens,
            estimated_total_tokens,
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

    def estimate_input_tokens(self) -> int:

        return estimate_stream_input_tokens(
            self.stream,
            prompt_text=(
                self.build_input_prompt_text()
            ),
        )

    def estimate_live_tokens(self) -> int:

        return estimate_stream_live_tokens(
            self.stream,
            prompt_text=(
                self.build_input_prompt_text()
            ),
        )

    async def refresh_token_usage(self):

        if not self.is_brain_context():
            return

        context_tokens = (
            self.estimate_input_tokens()
        )

        total_tokens = (
            self.estimate_live_tokens()
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
        )

    def capture_runtime_turn_response(self):

        if not self.is_brain_context():
            return

        self.context.runtime_turn_assistant_response = (
            self.stream.response
        )

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
    ) -> None:

        if not self.should_follow_up_on_context_limit(
            finish_reason
        ):
            return

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

        quote = getattr(
            validator,
            "last_failure_preview",
            "",
        )

        self.context.runtime_turn_interruption_reason = reason
        self.context.runtime_turn_interruption_quote = quote

    def record_validator_interruption_history(
        self,
        validator=None,
    ) -> None:

        if not self.is_brain_context():
            return

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

        record_session_action_history(
            self.context,
            build_reasoning_loop_history_text(
                quote
            ),
        )

    async def filter_runtime_action_content(
        self,
        content: str,
    ) -> str | None:

        if not self.filter_runtime_actions_enabled:
            return content

        result = self.action_filter.filter(
            content
        )

        return await self.apply_runtime_action_filter_result(
            result,
        )

    async def apply_runtime_action_filter_result(
        self,
        result,
    ) -> str | None:

        for action in getattr(
            result,
            "actions",
            (),
        ):
            if (
                action.name
                == RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT
                and action.payload
            ):
                self.delayed_memory_action_payload = action.payload

        for marker in getattr(
            result,
            "removed_markers",
            (),
        ):
            if (
                "SAVE_DELAYED_MEMORY_CONTENT"
                in str(marker).upper()
            ):
                self.delayed_memory_action_payload = str(marker)

        if getattr(
            result,
            "started_actions",
            (),
        ):
            await self.emit_started_runtime_actions(
                result.started_actions,
            )
            await self.confirm_started_runtime_action_guards(
                result.started_actions,
            )

        if result.actions:
            from utils.brain_client_utils import (
                apply_runtime_action_calls,
                log_runtime_action_marker_removals,
            )

            await log_runtime_action_marker_removals(
                self.context,
                result,
                source="runtime stream content",
            )

            idle_actions = tuple(
                action
                for action in result.actions
                if action.name == RUNTIME_ACTION_IDLE
            )
            immediate_actions = tuple(
                action
                for action in result.actions
                if action.name != RUNTIME_ACTION_IDLE
            )
            self.pending_idle_actions.extend(
                idle_actions
            )

            if immediate_actions:
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
                        == RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT
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
                        == RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT
                    )
                )

                if actions_to_apply:
                    await apply_runtime_action_calls(
                        self.context,
                        actions_to_apply,
                        context_snapshot=self.context_snapshot,
                        confirmed_action_ids=confirmed_action_ids,
                        rejected_action_ids=rejected_action_ids,
                        guard_confirmation_ids=(
                            self.action_guard_confirmation_ids
                        ),
                        action_display_ids={
                            id(action): self.get_runtime_action_display_id(
                                action
                            )
                            for action in actions_to_apply
                        },
                    )
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
            await self.logger.log_runtime(
                "[RUNTIME ACTION] marker repetition guard interrupted stream: "
                f"{reason}"
            )

        if not result.text:
            return None

        return result.text

    def get_runtime_action_display_id(
        self,
        action,
    ) -> str:

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

        if (
            action.name
            == RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT
            and self.started_delayed_memory_action_ids
        ):
            return self.started_delayed_memory_action_ids[-1]

        return ""

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
                == RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT
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
            or "<SAVE_DELAYED_MEMORY_CONTENT>"
        )

    def append_action_guard_missing_trigger_message(
        self,
        guard_name: str,
        template: str,
    ) -> None:
        from utils.context.runtime_state import (
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
            "action": action_name,
            "id": action_id,
            "confirmation_id": confirmation_id,
            "guard": guard_name,
            "status": "pending",
            "text": self.build_action_guard_confirmation_text(
                action_name
            ),
            "detail": (
                "Runtime action marker emitted without matching "
                "behavior-contract trigger words in the user message."
            ),
            "missing_triggers": triggers,
            "timeout_ms": 0,
        }

        if action.name == RUNTIME_ACTION_JIN_COLOR:
            color = normalize_jin_color_payload(
                action.payload
            )
            if color:
                payload["color"] = color
                payload["payload"] = color

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
    ) -> str:

        if action_name == "save_delayed_memory_content":
            return "Saving delayed memory report"

        if action_name == "save_session":
            return "Saving session"

        return action_name.replace(
            "_",
            " ",
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

                action_id = build_runtime_action_id(
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
                pending_ids.append(
                    action_id
                )

                payload = {
                    "type": "runtime_action",
                    "action": "asset_action",
                    "id": action_id,
                    "status": "started",
                    "text": build_asset_action_history_text({
                        "action": "asset_action",
                    }),
                }
            elif action.name == RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT:
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
                        ) == "save_delayed_memory_content"
                    ]),
                )
                next_sequence = current_sequence + 1
                self.context.runtime_delayed_memory_action_sequence = (
                    next_sequence
                )
                action_id = build_runtime_action_id(
                    RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT,
                    next_sequence,
                )
                pending_ids.append(
                    action_id
                )
                self.started_delayed_memory_action_ids.append(
                    action_id
                )

                payload = {
                    "type": "runtime_action",
                    "action": "save_delayed_memory_content",
                    "id": action_id,
                    "status": "started",
                    "text": "Saving delayed memory report",
                }
            elif action.name == RUNTIME_ACTION_JIN_COLOR:
                color = normalize_jin_color_payload(
                    action.payload
                )
                if not color:
                    continue

                payload = {
                    "type": "runtime_action",
                    "action": "jin_color",
                    "id": self.get_runtime_action_display_id(
                        action
                    ),
                    "status": "started",
                    "text": "JIN_COLOR",
                    "color": color,
                    "payload": color,
                }
            else:
                continue

            if action_context_snapshot:
                payload["context"] = action_context_snapshot

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
                "action": "save_delayed_memory_content",
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
                    "action": "save_delayed_memory_content",
                    "id": action_id,
                    "status": "failed",
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

    async def flush_pending_idle_actions(
        self,
    ) -> None:

        if not self.pending_idle_actions:
            return

        from utils.brain_client_utils import (
            apply_runtime_action_calls,
        )

        idle_actions = tuple(
            self.pending_idle_actions
        )
        self.pending_idle_actions.clear()

        await apply_runtime_action_calls(
            self.context,
            idle_actions,
            context_snapshot=self.context_snapshot,
            assistant_message="".join(
                self.raw_content_parts
            ),
        )


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

            lines.append(
                f"action: {name}"
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
        session_action_history_start = len(
            getattr(
                self.context,
                "runtime_session_action_history",
                [],
            )
            or []
        )

        try:

            action_event_offset = len(
                getattr(
                    self.context,
                    "runtime_action_events",
                    [],
                )
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

                    continue

                # -------------------------------------------------
                # FINISH REASON
                # -------------------------------------------------

                if chunk_type == "finish":
                    self.mark_context_limit_recovery(
                        chunk.get(
                            "finish_reason",
                            "",
                        )
                    )

                    continue

                # -------------------------------------------------
                # THINKING
                # -------------------------------------------------

                if chunk_type == "thinking":

                    is_valid = (
                        await self.stream.send_thinking(
                            chunk.get(
                                "content",
                                "",
                            ),
                            emit=self.emit_to_chat,
                        )
                    )

                    if not is_valid:
                        self.capture_runtime_turn_response()
                        self.mark_validator_interruption(
                            self.stream.thinking_validator
                        )

                        await self.close_active_streams()
                        await self.close_generator(
                            generator
                        )
                        self.record_validator_interruption_history(
                            self.stream.thinking_validator
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

                        await self.close_active_streams()
                        await self.close_generator(
                            generator
                        )
                        self.record_validator_interruption_history()

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

            await self.flush_pending_idle_actions()

            if self.action_guard_rejected_aborted:
                await self.fail_unfinished_delayed_memory_actions()

            await self.stream.finish(
                emit=self.emit_to_chat
            )

            await self.refresh_token_usage()
            self.record_token_usage()
            await self.refresh_provider_token_usage()
            self.capture_runtime_turn_response()

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

            if isinstance(
                    e,
                    httpx.ConnectError,
            ):

                public_error = (
                    "Model server offline "
                    "or unreachable."
                )

            elif isinstance(
                    e,
                    httpx.ReadTimeout,
            ):

                public_error = (
                    "Model request timeout."
                )

            elif isinstance(
                    e,
                    httpx.HTTPStatusError,
            ):

                public_error = (
                    "Model server returned HTTP error."
                )

            # -----------------------------------------------------
            # LOG FULL TRACEBACK
            # -----------------------------------------------------

            await self.logger.log_error(
                f"[RUNTIME STREAM CRASH] {public_error}",
                details=tb,
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

            history_compacted = (
                compact_session_action_history_since(
                    self.context,
                    session_action_history_start,
                )
            )

            if history_compacted:
                with contextlib.suppress(
                    Exception
                ):
                    await emit_session_actions_update(
                        self.context,
                        current_sequence=True,
                    )
