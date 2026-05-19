import traceback

import config

from clients.brain_client import ask_brain
from utils.tokens import estimate_tokens

from clients.translation_client import (
    translate_ru_to_en,
    translate_en_to_ru,
)

from memory.runtime_state import (
    runtime_state,
)

from utils.telemetry import (
    send_telemetry,
)

from utils.text_cleanup import (
    cleanup_text,
)

from utils.brain import (
    get_brain_runtime_config,
)



class TranslationPipeline:

    async def run(
        self,
        websocket,
        logger,
        message_data,
    ):

        try:

            user_text_ru = (
                message_data.get("text", "")
                .strip()
            )

            if not user_text_ru:

                await logger.log_error(
                    "Received empty message."
                )

                return

            # ---------------------------------------------------------
            # STEP 1: RU -> EN
            # ---------------------------------------------------------

            await logger.log_runtime(
                "Translating RU -> EN..."
            )

            try:

                text_en = await (
                    translate_ru_to_en(
                        user_text_ru
                    )
                )

                runtime_state.update_node_state(
                    "translator",
                    model=config.TRANSLATOR_MODEL_UID,
                    used_tokens=estimate_tokens(
                        user_text_ru + text_en
                    ),
                    max_tokens=(
                        config.TRANSLATOR_CONTEXT_WINDOW
                    ),
                )

                await send_telemetry(
                    websocket
                )

            except Exception as e:

                runtime_state.update_node_state(
                    "translator",
                    model="OFFLINE",
                )

                await send_telemetry(
                    websocket
                )

                await logger.log_error(
                    f"Translation error: {e}"
                )

                await websocket.send_json({
                    "type": "error",
                    "source": "translator",
                    "text": str(e),
                })

                return

            await logger.log_translation(
                f"EN input: '{text_en}'"
            )

            # ---------------------------------------------------------
            # STEP 2: BRAIN
            # ---------------------------------------------------------

            await logger.log_runtime(
                "Sending context to brain..."
            )

            try:

                brain_response_en = (
                    await ask_brain(
                        text_en
                    )
                )

                brain_runtime = (
                    get_brain_runtime_config()
                )

                runtime_state.update_node_state(
                    "brain",
                    model=(
                        brain_runtime["model_uid"]
                    ),
                    used_tokens=estimate_tokens(
                        text_en
                        + brain_response_en
                    ),
                    max_tokens=(
                        brain_runtime[
                            "context_window"
                        ]
                    ),
                )

            except Exception as e:

                runtime_state.update_node_state(
                    "brain",
                    model="OFFLINE",
                )

                await send_telemetry(
                    websocket
                )

                await logger.log_error(
                    f"Brain error: {e}"
                )

                await websocket.send_json({
                    "type": "error",
                    "source": "brain",
                    "text": str(e),
                })

                return

            await getattr(
                logger,
                brain_runtime["log_method"],
            )(
                brain_response_en
            )

            # ---------------------------------------------------------
            # STEP 4: EN -> RU
            # ---------------------------------------------------------

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

                runtime_state.update_node_state(
                    "translator",
                    add_tokens=estimate_tokens(
                        brain_response_en
                        + brain_response_ru
                    ),
                )

                await send_telemetry(
                    websocket
                )

            except Exception as e:

                runtime_state.update_node_state(
                    "translator",
                    model="OFFLINE",
                )

                await send_telemetry(
                    websocket
                )

                await logger.log_error(
                    f"Reverse translation error: {e}"
                )

                await websocket.send_json({
                    "type": "error",
                    "source": "translator",
                    "text": str(e),
                })

                return

            await logger.log_translation(
                f"RU output: '{brain_response_ru}'"
            )

            # ---------------------------------------------------------
            # STEP 5: SEND RESPONSE
            # ---------------------------------------------------------

            await websocket.send_json({
                "type": "message",
                "role": (
                    "service"
                    if config.USE_SERVICE_AS_BRAIN
                    else "brain"
                ),
                "text": brain_response_ru,
            })

            await logger.log_runtime(
                "Pipeline cycle complete."
            )

        except Exception as e:

            await logger.log_error(
                traceback.format_exc()
                )

            await logger.log_error(
                f"Pipeline error: {e}"
            )

            await websocket.send_json({
                "type": "error",
                "source": "pipeline",
                "text": str(e),
            })
