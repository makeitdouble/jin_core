import config

from clients.brain_client import (
    ask_brain,
    ask_brain_stream,
)

from clients.translation_client import (
    translate,
)

from utils.tokens import (
    estimate_tokens,
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

TRANSLATE_RESPONSE = False


class TranslationPipeline:

    async def run(
        self,
        websocket,
        logger,
        message_data,
    ):

        try:

            await logger.log_runtime(
                            "Translation pipeline started."
                        )

            user_text_ru = (
                message_data.get(
                    "text",
                    "",
                ).strip()
            )

            if not user_text_ru:

                await logger.log_error(
                    "Received empty message."
                )

                return

            text_en = await self.translate_input(
                websocket,
                logger,
                user_text_ru,
            )

            if text_en is None:
                return

            brain_response_en = (
                await self.ask_brain(
                    websocket,
                    logger,
                    text_en,
                )
            )

            if brain_response_en is None:
                return

            translated_response = (
                await self.translate_response(
                    websocket,
                    logger,
                    brain_response_en,
                )
            )

            if translated_response is None:
                return

            await logger.log_runtime(
                "Translation pipeline complete."
            )

        except Exception as error:

            await handle_fatal_pipeline_error(
                websocket,
                logger,
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
        websocket,
        logger,
        *,
        text: str,
        source_language: str,
        target_language: str,
        public_error_message: str,
        cleanup_output: bool = False,
    ) -> str | None:

        await logger.log_runtime(
            f"Translating "
            f"{source_language} -> "
            f"{target_language}"
        )

        try:

            translated_text = (
                await translate(
                    text=text,
                    source_language=(
                        source_language
                    ),
                    target_language=(
                        target_language
                    ),
                )
            )

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

            await refresh_runtime_state(
                websocket,
                runtime_id=(
                    config
                    .TRANSLATOR_MODEL_UID
                ),
                add_tokens=(
                    estimate_tokens(
                        text
                        + translated_text
                    )
                ),
                max_tokens=(
                    config
                    .TRANSLATOR_CONTEXT_WINDOW
                ),
                last_error=None,
                status="online",
            )

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

        except Exception as error:

            await handle_pipeline_error(
                websocket,
                logger,
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
    # STEP 1: INPUT TRANSLATION
    # ---------------------------------------------------------

    async def translate_input(
        self,
        websocket,
        logger,
        user_text_ru: str,
    ) -> str | None:

        return await self.translate_text(
            websocket,
            logger,
            text=user_text_ru,
            source_language="Russian",
            target_language="English",
            public_error_message=(
                "Prompt translation failed."
            ),
        )

    # ---------------------------------------------------------
    # STEP 2: ASK BRAIN
    # ---------------------------------------------------------

    async def ask_brain(
        self,
        websocket,
        logger,
        text_en: str,
    ) -> str | None:

        await logger.log_runtime(
            "Send request to brain..."
        )

        brain_runtime = (
            get_brain_runtime_config()
        )

        response = ""

        try:

            import uuid

            message_id = str(
                uuid.uuid4()
            )

            await websocket.send_json({
                "type": "message_start",
                "message_id": (
                    message_id
                ),
                "role": (
                    "service"
                    if config.USE_SERVICE_AS_BRAIN
                    else "brain"
                ),
            })

            async for chunk in (
                ask_brain_stream(
                    text_en
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

                if chunk_type == "thinking":

                    await websocket.send_json({
                        "type": "thinking_chunk",
                        "message_id": (
                            message_id
                        ),
                        "chunk": (
                            chunk_content
                        ),
                    })

                    continue

                response += chunk_content

                await websocket.send_json({
                    "type": "message_chunk",
                    "message_id": (
                        message_id
                    ),
                    "chunk": (
                        chunk_content
                    ),
                })

            await websocket.send_json({
                "type": "message_end",
                "message_id": (
                    message_id
                ),
            })

            await refresh_runtime_state(
                websocket,
                runtime_id=(
                    brain_runtime[
                        "runtime_id"
                    ]
                ),
                used_tokens=(
                    estimate_tokens(
                        text_en
                        + response
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
                response
            )

            return response

        except Exception as error:

            await handle_pipeline_error(
                websocket,
                logger,
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
    # STEP 3: OUTPUT TRANSLATION
    # ---------------------------------------------------------

    async def translate_response(
        self,
        websocket,
        logger,
        brain_response_en: str,
    ) -> str | None:

        if not TRANSLATE_RESPONSE:
            return brain_response_en

        return await self.translate_text(
            websocket,
            logger,
            text=brain_response_en,
            source_language="English",
            target_language="Russian",
            public_error_message=(
                "Answer translation failed."
            ),
            cleanup_output=True,
        )

    # ---------------------------------------------------------
    # STEP 4: SEND RESPONSE
    # ---------------------------------------------------------

    async def send_response(
        self,
        websocket,
        text: str,
    ):

        await websocket.send_json({
            "type": "message",
            "role": (
                "service"
                if config.USE_SERVICE_AS_BRAIN
                else "brain"
            ),
            "text": text,
        })
