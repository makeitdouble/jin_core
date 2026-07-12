import uuid

from utils.stream_validator import (
    StreamValidator,
)


class StreamHandler:

    def __init__(
        self,
        websocket,
        logger,
        *,
        role: str,
        enable_validator: bool = False,
        context_snapshot: dict | None = None,
    ):

        self.websocket = websocket
        self.logger = logger

        self.role = role
        self.context_snapshot = context_snapshot

        self.message_id = str(
            uuid.uuid4()
        )

        self.response = ""
        self.reasoning = ""

        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0

        self.validator = (
            StreamValidator()
            if enable_validator
            else None
        )
        self.thinking_validator = (
            StreamValidator()
            if enable_validator
            else None
        )

    def build_validator_error_text(
        self,
        validator,
    ) -> str:

        reason = (
            validator.last_failure_reason
            or "Generation stopped."
        )

        if validator.last_failure_preview:
            reason = (
                f'{reason} Looped text: '
                f'"{validator.last_failure_preview}"'
            )

        return reason

    # ---------------------------------------------------------
    # START STREAM
    # ---------------------------------------------------------

    async def start(
        self,
        *,
        emit: bool = True,
    ):

        if not emit:
            return

        payload: dict[str, object] = {
            "type": "message_start",
            "message_id": (
                self.message_id
            ),
            "role": self.role,
        }

        if self.context_snapshot:
            payload["context"] = (
                self.context_snapshot
            )

        await self.websocket.send_json(
            payload
        )

    # ---------------------------------------------------------
    # THINKING
    # ---------------------------------------------------------

    async def send_thinking(
        self,
        chunk: str,
        *,
        emit: bool = True,
    ) -> bool:

        if self.thinking_validator:

            is_valid = (
                self.thinking_validator.validate_repetitions(
                    chunk
                )
            )

            if not is_valid:

                failure_reason = (
                    self.thinking_validator.last_failure_reason
                    or "Repeated thinking loop detected."
                )

                if failure_reason.startswith("Repeated "):
                    failure_reason = failure_reason.replace(
                        "Repeated ",
                        "Repeated thinking ",
                        1,
                    )

                self.thinking_validator.last_failure_reason = (
                    failure_reason
                )

                raw_chunk_preview = (
                    chunk
                    .replace("\n", "\\n")
                )[:160]

                await self.logger.log_validator(
                    f"{self.thinking_validator.last_failure_reason}\n"
                    f'Preview: "{self.thinking_validator.last_failure_preview}"\n'
                    f'Raw thinking chunk: "{raw_chunk_preview}"'
                )

                if emit:

                    await self.websocket.send_json({
                        "type": "message_error",
                        "message_id": (
                            self.message_id
                        ),
                        "text": self.build_validator_error_text(
                            self.thinking_validator
                        ),
                    })

                return False

        self.reasoning += chunk

        if not emit:
            return True

        await self.websocket.send_json({
            "type": "thinking_chunk",
            "message_id": (
                self.message_id
            ),
            "chunk": chunk,
        })

        return True

    async def log_validator_cleanup_events(
        self,
    ):

        if not self.validator:
            return

        if not self.validator.cleanup_events:
            return

        for event in (
            self.validator.cleanup_events
        ):

            await self.logger.log_validator(
                f'{event["reason"]}\n'
                f'Preview: "{event["preview"]}"'
            )

        self.validator.cleanup_events.clear()

    async def flush_validator_tail(
        self,
        *,
        emit: bool = True,
    ):

        if not self.validator:
            return

        safe_tail = (
            self.validator.flush_trailing_artifact_candidate()
        )

        await self.log_validator_cleanup_events()

        if not safe_tail:
            return

        self.response += safe_tail

        if not emit:
            return

        await self.websocket.send_json({
            "type": "message_chunk",
            "message_id": (
                self.message_id
            ),
            "chunk": safe_tail,
        })

    # ---------------------------------------------------------
    # CONTENT
    # ---------------------------------------------------------

    async def send_content(
        self,
        chunk: str,
        *,
        emit: bool = True,
    ) -> bool:

        safe_chunk = chunk

        if self.validator:

            safe_chunk, is_valid = (
                self.validator.filter_chunk(
                    chunk
                )
            )

            await self.log_validator_cleanup_events()

            if not is_valid:

                raw_chunk_preview = (
                    chunk
                    .replace("\n", "\\n")
                )[:160]

                safe_chunk_preview = (
                    safe_chunk
                    .replace("\n", "\\n")
                )[:160]

                await self.logger.log_validator(
                    f"{self.validator.last_failure_reason}\n"
                    f'Preview: "{self.validator.last_failure_preview}"\n'
                    f'Raw chunk: "{raw_chunk_preview}"\n'
                    f'Safe chunk: "{safe_chunk_preview}"'
                )

                reason = (
                    self.build_validator_error_text(
                        self.validator
                    )
                )

                if emit:

                    await self.websocket.send_json({
                        "type": "message_error",
                        "message_id": (
                            self.message_id
                        ),
                        "text": reason,
                    })

                return False
            # ---------------------------------------------------------
            # EMPTY SAFE CHUNK
            # ---------------------------------------------------------

            if not safe_chunk:

                return True
        self.response += safe_chunk

        if not emit:
            return True

        await self.websocket.send_json({
            "type": "message_chunk",
            "message_id": (
                self.message_id
            ),
            "chunk": safe_chunk,
        })

        return True

    # ---------------------------------------------------------
    # TOKEN USAGE
    # ---------------------------------------------------------

    def update_usage(
        self,
        usage_chunk: dict,
    ):

        self.prompt_tokens = (
            usage_chunk.get(
                "prompt_tokens",
                0,
            )
        )

        self.completion_tokens = (
            usage_chunk.get(
                "completion_tokens",
                0,
            )
        )

        self.total_tokens = (
            usage_chunk.get(
                "total_tokens",
                0,
            )
        )

    # ---------------------------------------------------------
    # FINISH
    # ---------------------------------------------------------

    async def finish(
        self,
        *,
        emit: bool = True,
    ):

        await self.flush_validator_tail(
            emit=emit,
        )

        if not emit:
            return

        await self.websocket.send_json({
            "type": "message_end",
            "message_id": (
                self.message_id
            ),
        })
