import config

from clients.brain_client import (
    ask_brain,
)

from clients.translation_client import (
    translate_ru_to_en,
    translate_en_to_ru,
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

TRANSLATE_ANSWER = False

class TranslationPipeline:

    async def run(
        self,
        websocket,
        logger,
        message_data,
    ):

        try:

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

            final_response = (
                await self.build_final_response(
                    websocket,
                    logger,
                    brain_response_en,
                )
            )

            if final_response is None:
                return

            await self.send_response(
                websocket,
                final_response,
            )

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
    # STEP 1: INPUT TRANSLATION
    # ---------------------------------------------------------

    async def translate_input(
        self,
        websocket,
        logger,
        user_text_ru: str,
    ) -> str | None:

        await logger.log_runtime(
            "Translating RU -> EN..."
        )

        try:

            text_en = (
                await translate_ru_to_en(
                    user_text_ru
                )
            )

            await refresh_runtime_state(
                websocket,
                runtime_id=(
                    config
                    .TRANSLATOR_MODEL_UID
                ),
                used_tokens=(
                    estimate_tokens(
                        user_text_ru
                        + text_en
                    )
                ),
                max_tokens=(
                    config
                    .TRANSLATOR_CONTEXT_WINDOW
                ),
                last_error=None,
                status="online",
            )

            await logger.log_translation(
                f"EN input: '{text_en}'"
            )

            return text_en

        except Exception as error:

            await handle_pipeline_error(
                websocket,
                logger,
                runtime_id=(
                    config
                    .TRANSLATOR_MODEL_UID
                ),
                public_message=(
                    "Prompt translation failed."
                ),
                exception=error,
            )

            return None

    # ---------------------------------------------------------
    # STEP 2: BRAIN
    # ---------------------------------------------------------

    async def ask_brain(
        self,
        websocket,
        logger,
        text_en: str,
    ) -> str | None:

        await logger.log_runtime(
            "Sending context to brain..."
        )

        brain_runtime = (
            get_brain_runtime_config()
        )

        try:

            brain_response_en = (
                await ask_brain(
                    text_en
                )
            )

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
                        + brain_response_en
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
                brain_response_en
            )

            return brain_response_en

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

    async def build_final_response(
        self,
        websocket,
        logger,
        brain_response_en: str,
    ) -> str | None:

        if not TRANSLATE_ANSWER:
            return brain_response_en

        await logger.log_runtime(
            "Translating EN -> RU..."
        )

        try:

            brain_response_ru = (
                await translate_en_to_ru(
                    brain_response_en
                )
            )

            brain_response_ru, removed_chunks = (
                cleanup_text(
                    brain_response_ru
                )
            )

            if removed_chunks:

                removed_text = "\n".join(
                    f"  - {repr(chunk)}"
                    for chunk in removed_chunks
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
                        brain_response_en
                        + brain_response_ru
                    )
                ),
                last_error=None,
                status="online",
            )

            await logger.log_translation(
                f"RU output: '{brain_response_ru}'"
            )

            return brain_response_ru

        except Exception as error:

            await handle_pipeline_error(
                websocket,
                logger,
                runtime_id=(
                    config
                    .TRANSLATOR_MODEL_UID
                ),
                public_message=(
                    "Answer translation failed."
                ),
                exception=error,
            )

            return None

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
