import asyncio

from settings.config_loader import (
    config,
)
from clients.brain_client import (
    ask_brain_stream,
)

from clients.translation_client import (
    translate,
)

from utils.tokens import (
    estimate_stream_tokens,
)

from utils.text_cleanup import (
    cleanup_text,
)

from utils.brain import (
    get_brain_runtime_config,
)

from utils.runtime_state_sync import (
    refresh_runtime_state,
)

from utils.ws_errors import (
    handle_pipeline_error,
    handle_fatal_pipeline_error,
)

from utils.stream_handler import (
    StreamHandler,
)


TRANSLATE_RESPONSE = False

SOURCE_LANGUAGE = "Russian"
TARGET_LANGUAGE = "English"


class TranslationPipeline:

    async def run(
        self,
        context,
        message_data,
    ):
        websocket = context.websocket
        logger = context.logger

        try:

            await logger.log_runtime(
                "Translation pipeline started."
            )

            user_text = (
                message_data.get(
                    "text",
                    "",
                ).strip()
            )

            if not user_text:

                await logger.log_error(
                    "Received empty message."
                )

                return

            # -------------------------------------------------
            # STEP 1: INPUT TRANSLATION
            # -------------------------------------------------

            user_text_translated = (
                await self.translate_input(
                    context,
                    user_text,
                )
            )

            if user_text_translated is None:
                return

            # -------------------------------------------------
            # STEP 2: ASK BRAIN
            # -------------------------------------------------

            brain_response = (
                await self.ask_brain(
                    context,
                    user_text_translated,
                )
            )

            if brain_response is None:
                return

            # -------------------------------------------------
            # STEP 3: OUTPUT TRANSLATION
            # -------------------------------------------------

            translated_response = (
                await self.translate_response(
                    context,
                    brain_response,
                )
            )

            if translated_response is None:
                return

            await logger.log_runtime(
                "Translation pipeline complete."
            )

        except asyncio.CancelledError:

                    await logger.log_runtime(
                        "Translation pipeline cancelled."
                    )

                    raise

        except Exception as error:

            await handle_fatal_pipeline_error(
                context,
                pipeline_name=(
                    "translation_pipeline"
                ),
                exception=error,
            )

    # ---------------------------------------------------------
    # TRANSLATE TEXT
    # ---------------------------------------------------------

    async def translate_text(
        self,
        context,
        *,
        text: str,
        source_language: str,
        target_language: str,
        public_error_message: str,
        cleanup_output: bool = False,
    ) -> str | None:

        websocket = context.websocket
        logger = context.logger

        translator_client = (
            context.clients[
                "translator"
            ]
        )

        await logger.log_runtime(
            f"Translating "
            f"{source_language} -> "
            f"{target_language}"
        )

        try:

            translated = await translate(
                client=translator_client,
                text=text,
                source_language=(
                    source_language
                ),
                target_language=(
                    target_language
                ),
            )

            translated_text = (
                translated["content"]
            )

            usage = (
                translated["usage"]
            )

            # -------------------------------------------------
            # CLEANUP
            # -------------------------------------------------

            if cleanup_output:

                translated_text, removed_chunks = (
                    cleanup_text(
                        translated_text
                    )
                )

                if removed_chunks:

                    removed_text = "\n".join(
                        f"  - {repr(chunk)}"
                        for chunk
                        in removed_chunks
                    )

                    await logger.log_runtime(
                        "Removed junk tokens:\n"
                        f"{removed_text}"
                    )

            # -------------------------------------------------
            # TELEMETRY
            # -------------------------------------------------

#            await refresh_runtime_state(
#                websocket,
#                runtime_id=(
#                    config
#                    .TRANSLATOR_MODEL_UID
#                ),
#                add_tokens=(
#                    usage.get(
#                        "total_tokens",
#                        0,
#                    )
#                ),
#                max_tokens=(
#                    config
#                    .TRANSLATOR_CONTEXT_WINDOW
#                ),
#                last_error=None,
#                status="online",
#            )

            # -------------------------------------------------
            # LOGGING
            # -------------------------------------------------

            source_short = (
                source_language[:2]
                .upper()
            )

            target_short = (
                target_language[:2]
                .upper()
            )

            await logger.log_translation(
                f"{source_short} -> "
                f"{target_short}: "
                f"'{translated_text}'"
            )

            return translated_text

        except asyncio.CancelledError:
                    raise

        except Exception as error:

            await handle_pipeline_error(
                context,
                runtime_id=(
                    config
                    .TRANSLATOR_MODEL_UID
                ),
                public_message=(
                    public_error_message
                ),
                exception=error,
            )

            return None

    # ---------------------------------------------------------
    # INPUT TRANSLATION
    # ---------------------------------------------------------

    async def translate_input(
        self,
        context,
        user_text: str,
    ) -> str | None:

        websocket = context.websocket
        logger = context.logger

        return await self.translate_text(
            context,
            text=user_text,
            source_language=(
                SOURCE_LANGUAGE
            ),
            target_language=(
                TARGET_LANGUAGE
            ),
            public_error_message=(
                "Prompt translation failed."
            ),
        )

    # ---------------------------------------------------------
    # ASK BRAIN
    # ---------------------------------------------------------

    async def ask_brain(
        self,
        context,
        user_text_translated: str,
    ) -> str | None:

        websocket = context.websocket
        logger = context.logger

        await logger.log_runtime(
            "Send request to brain..."
        )

        brain_runtime = (
            get_brain_runtime_config()
        )

        brain_client = (
            context.clients[
                "brain"
            ]
        )

        stream = StreamHandler(
            websocket,
            logger,
            role=(
                "service"
                if config.USE_SERVICE_AS_BRAIN
                else "brain"
            ),
            enable_validator=True,
        )

        try:

            await stream.start()

            async for chunk in (
                ask_brain_stream(
                    context=context,
                    client=brain_client,
                    text=user_text_translated,
                )
            ):

                chunk_type = (
                    chunk.get("type")
                )

                chunk_content = (
                    chunk.get(
                        "content",
                        ""
                    )
                )

                if chunk_type == "usage":

                    stream.update_usage(chunk)

                    continue

                # ---------------------------------------------
                # THINKING STREAM
                # ---------------------------------------------

                if chunk_type == "thinking":

                    await stream.send_thinking(
                        chunk_content
                    )

                    continue

                # ---------------------------------------------
                # CONTENT STREAM
                # ---------------------------------------------

                if chunk_type == "content":

                    is_valid = (
                        await stream.send_content(
                            chunk_content
                        )
                    )

                    if not is_valid:

                        await stream.finish()

                        return None

            await stream.finish()

            await refresh_runtime_state(
                context,
                runtime_id=(
                    brain_runtime[
                        "runtime_id"
                    ]
                ),
                used_tokens=(
                    estimate_stream_tokens(
                        stream,
                        prompt_text=(
                            user_text_translated
                        ),
                    )
                ),
                max_tokens=(
                    brain_runtime[
                        "context_window"
                    ]
                ),
                last_error=None,
                status="online",
            )

            await getattr(
                logger,
                brain_runtime[
                    "log_method"
                ],
            )(
                stream.response
            )

            return stream.response

        except asyncio.CancelledError:

                    await logger.log_runtime(
                        "Translation brain stream cancelled."
                    )

                    try:

                        await stream.finish()

                    except Exception:
                        pass

                    raise

        except Exception as error:

            await handle_pipeline_error(
                context,
                runtime_id=(
                    brain_runtime[
                        "runtime_id"
                    ]
                ),
                public_message=(
                    "Brain request failed."
                ),
                exception=error,
            )

            return None

    # ---------------------------------------------------------
    # OUTPUT TRANSLATION
    # ---------------------------------------------------------

    async def translate_response(
        self,
        context,
        brain_response: str,
    ) -> str | None:

        if not TRANSLATE_RESPONSE:
            return brain_response

        websocket = context.websocket
        logger = context.logger

        return await self.translate_text(
            context,
            text=brain_response,
            source_language=(
                TARGET_LANGUAGE
            ),
            target_language=(
                SOURCE_LANGUAGE
            ),
            public_error_message=(
                "Answer translation failed."
            ),
            cleanup_output=True,
        )
