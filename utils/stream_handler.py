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
    ):

        self.websocket = websocket
        self.logger = logger

        self.role = role

        self.message_id = str(
            uuid.uuid4()
        )

        self.response = ""

        self.validator = (
            StreamValidator()
            if enable_validator
            else None
        )

    # ---------------------------------------------------------
    # START STREAM
    # ---------------------------------------------------------

    async def start(self):

        await self.websocket.send_json({
            "type": "message_start",
            "message_id": (
                self.message_id
            ),
            "role": self.role,
        })

    # ---------------------------------------------------------
    # THINKING CHUNK
    # ---------------------------------------------------------

    async def send_thinking(
        self,
        chunk: str,
    ):

        await self.websocket.send_json({
            "type": "thinking_chunk",
            "message_id": (
                self.message_id
            ),
            "chunk": chunk,
        })

    # ---------------------------------------------------------
    # CONTENT CHUNK
    # ---------------------------------------------------------

    async def send_content(
        self,
        chunk: str,
    ) -> bool:

        safe_chunk = chunk

        # -----------------------------------------------------
        # VALIDATION
        # -----------------------------------------------------

        if self.validator:

            safe_chunk, is_valid = (
                self.validator.filter_chunk(
                    chunk
                )
            )

            if not is_valid:

                await self.logger.log_validator(
                    f"{self.validator.last_failure_reason}\n"
                    f'Preview: "{self.validator.last_failure_preview}"'
                )

                await self.websocket.send_json({
                    "type": "message_error",
                    "message_id": (
                        self.message_id
                    ),
                    "text": (
                        "Generation stopped: "
                        "model repetition detected."
                    ),
                })

                return False

        # -----------------------------------------------------
        # ACCUMULATE RESPONSE
        # -----------------------------------------------------

        self.response += safe_chunk

        # -----------------------------------------------------
        # SEND CHUNK
        # -----------------------------------------------------

        await self.websocket.send_json({
            "type": "message_chunk",
            "message_id": (
                self.message_id
            ),
            "chunk": safe_chunk,
        })

        return True

    # ---------------------------------------------------------
    # FINISH STREAM
    # ---------------------------------------------------------

    async def finish(self):

        await self.websocket.send_json({
            "type": "message_end",
            "message_id": (
                self.message_id
            ),
        })
