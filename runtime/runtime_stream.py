import asyncio

from utils.runtime_state_sync import (
    refresh_runtime_state,
)

from utils.stream_handler import (
    StreamHandler,
)

from utils.tokens import (
    estimate_tokens,
)


class RuntimeStream:

    def __init__(
        self,
        *,
        websocket,
        logger,
        runtime_id: str,
        role: str,
        context_window: int,
        log_method,
        enable_validator: bool = True,
    ):

        self.websocket = websocket
        self.logger = logger

        self.runtime_id = runtime_id
        self.role = role

        self.context_window = (
            context_window
        )

        self.log_method = log_method

        self.stream = StreamHandler(
            websocket,
            logger,
            role=role,
            enable_validator=(
                enable_validator
            ),
        )

    # ---------------------------------------------------------
    # EXECUTE STREAM
    # ---------------------------------------------------------

    async def run(
        self,
        generator,
    ):

        try:

            await self.stream.start()

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
                # THINKING
                # -------------------------------------------------

                if chunk_type == "thinking":

                    await self.stream.send_thinking(
                        chunk.get(
                            "content",
                            "",
                        )
                    )

                    continue

                # -------------------------------------------------
                # CONTENT
                # -------------------------------------------------

                if chunk_type == "content":

                    is_valid = (
                        await self.stream.send_content(
                            chunk.get(
                                "content",
                                "",
                            )
                        )
                    )

                    if not is_valid:

                        await self.stream.finish()

                        return None

            await self.stream.finish()

            used_tokens = (
                self.stream.total_tokens
                or estimate_tokens(
                    self.stream.response
                )
            )

            await refresh_runtime_state(
                self.websocket,
                runtime_id=(
                    self.runtime_id
                ),
                used_tokens=(
                    used_tokens
                ),
                max_tokens=(
                    self.context_window
                ),
                last_error=None,
                status="online",
            )

            await self.log_method(
                self.stream.response
            )

            return self.stream.response

        # ---------------------------------------------------------
        # TASK CANCELLED
        # ---------------------------------------------------------

        except asyncio.CancelledError:

            await self.logger.log_runtime(
                f"{self.runtime_id} stream cancelled."
            )

            try:

                await self.websocket.send_json({
                    "type": "message_end",
                    "message_id": (
                        self.stream.message_id
                    ),
                })

            except Exception:
                pass

            try:

                await self.stream.finish()

            except Exception:
                pass

            raise
