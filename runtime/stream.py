import asyncio
import contextlib
import traceback

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
    RuntimeActionRepetitionGuard,
    RuntimeActionStreamFilter,
)
from rules.runtime import (
    RUNTIME_ACTION_APPEND_SKILL,
    RUNTIME_ACTION_ASSET_ACTION,
    RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT,
)
from utils.assets_service import (
    normalize_skill_name,
)
from utils.session_actions_history import (
    build_asset_action_history_text,
    build_context_limit_history_text,
    build_reasoning_loop_history_text,
    record_session_action_history,
)
from utils.tool_results import (
    TOOL_RESULT_KIND_DELAYED_MEMORY,
    record_runtime_tool_result,
)
from config_loader import (
    config,
)


CONTEXT_LIMIT_FINISH_REASONS = frozenset({
    "length",
    "max_tokens",
    "max_output_tokens",
    "context_length",
    "context_limit",
})


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
        self.context_limit_recovery_armed = False
        self.started_delayed_memory_action_ids = []
        self.delayed_memory_action_payload = ""
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
            in CONTEXT_LIMIT_FINISH_REASONS
        )

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

        self.capture_runtime_turn_response()
        self.context.runtime_turn_interrupted = True
        self.context.runtime_context_limit_recovery_pending = True
        self.context.runtime_context_limit_stage = stage
        self.context.runtime_context_limit_finish_reason = (
            normalized_reason
        )
        self.context.runtime_turn_interruption_reason = (
            "Context limit reached during "
            f"{stage}."
        )
        self.context.runtime_turn_interruption_quote = ""

        record_session_action_history(
            self.context,
            build_context_limit_history_text(
                stage
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

        if result.actions:
            from clients.brain_client_utils import (
                apply_runtime_action_calls,
                log_runtime_action_marker_removals,
            )

            await log_runtime_action_marker_removals(
                self.context,
                result,
                source="runtime stream content",
            )
            await apply_runtime_action_calls(
                self.context,
                result.actions,
                context_snapshot=self.context_snapshot,
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

            failure_result = {
                "ok": False,
                "action": "save_delayed_memory_content",
                "id": action_id,
                "error": "Delayed memory report was not saved",
                "payload": self.delayed_memory_action_payload,
            }
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
                await emit({
                    "type": "runtime_action",
                    "action": "save_delayed_memory_content",
                    "id": action_id,
                    "status": "failed",
                    "text": "Delayed memory report was not saved",
                })

        self.started_delayed_memory_action_ids.clear()
        self.delayed_memory_action_payload = ""

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
                if self.marker_repetition_aborted
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
