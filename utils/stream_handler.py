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
    ):

        self.reasoning += chunk

        if not emit:
            return

        await self.websocket.send_json({
            "type": "thinking_chunk",
            "message_id": (
                self.message_id
            ),
            "chunk": chunk,
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

            # ---------------------------------------------------------
            # CLEANUP EVENTS
            # ---------------------------------------------------------

            if self.validator.cleanup_events:

                for event in (
                    self.validator.cleanup_events
                ):

                    await self.logger.log_validator(
                        f'{event["reason"]}\n'
                        f'Preview: "{event["preview"]}"'
                    )

                self.validator.cleanup_events.clear()

            if not is_valid:

                await self.logger.log_validator(
                    f"{self.validator.last_failure_reason}\n"
                    f'Preview: "{self.validator.last_failure_preview}"'
                )

                reason = (
                    self.validator.last_failure_reason
                    or "Generation stopped."
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

        if not emit:
            return

        await self.websocket.send_json({
            "type": "message_end",
            "message_id": (
                self.message_id
            ),
        })
