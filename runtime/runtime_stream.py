import asyncio

import httpx

from utils.runtime_state_sync import (
    refresh_runtime_state,
)

from utils.stream_handler import (
    StreamHandler,
)

from utils.tokens import (
    estimate_stream_tokens,
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

        self.stream = StreamHandler(
            self.websocket,
            self.logger,
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

            await self.stream.start(
                emit=self.emit_to_chat
            )

            await self.logger.log_runtime(
                f"[STREAM START] role={self.role}"
            )

            await self.logger.log_runtime(
                "[GENERATOR LOOP START]"
            )

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
                        ),
                        emit=self.emit_to_chat,
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
                            ),
                            emit=self.emit_to_chat,
                        )
                    )

                    if not is_valid:
                        await self.stream.finish(
                            emit=self.emit_to_chat
                        )

                        return None

            await self.stream.finish(
                emit=self.emit_to_chat
            )

            used_tokens = (
                estimate_stream_tokens(
                    self.stream
                )
            )

            await refresh_runtime_state(
                self.context,
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

                if self.emit_to_chat:

                    await self.websocket.send_json({
                        "type": "message_end",
                        "message_id": (
                            self.stream.message_id
                        ),
                    })

            except Exception:
                pass

            try:

                await self.stream.finish(
                    emit=self.emit_to_chat
                )

            except Exception:
                pass

            return None

        # ---------------------------------------------------------
        # RUNTIME ERROR
        # ---------------------------------------------------------
        except (
                asyncio.CancelledError,
                GeneratorExit,
                httpx.ReadError,
                httpx.RemoteProtocolError,
        ):

            await self.logger.log_system(
                "Generation aborted."
            )

            try:

                await self.stream.finish(
                    emit=self.emit_to_chat
                )

            except Exception:
                pass

            return None

        except Exception as e:

            import traceback

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

            try:

                if self.emit_to_chat:

                    await self.websocket.send_json({
                        "type": "message_error",
                        "message_id": (
                            self.stream.message_id
                        ),
                        "text": public_error,
                    })

            except Exception:
                pass

            return None
