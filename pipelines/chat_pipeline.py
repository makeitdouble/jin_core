import traceback

import config

from clients.brain_client import ask_brain
from clients.service_client import (
    translate_en_to_ru,
    translate_ru_to_en,
)

from memory.runtime_state import runtime_state


def estimate_tokens(text: str) -> int:
    return max(
        1,
        len(text) // config.TOKEN_ESTIMATION_DIVISOR,
    )


async def send_telemetry(websocket):
    await websocket.send_json({
        "type": "telemetry",
        "brain": runtime_state.brain,
        "service": runtime_state.service,
    })


async def process_chat_message(
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

        await logger.log_system(
            f"Received user message: '{user_text_ru}'"
        )

        # ---------------------------------------------------------
        # BYPASS BRAIN
        # ---------------------------------------------------------

        if config.BYPASS_BRAIN:

            await logger.log_runtime(
                "BYPASS_BRAIN enabled."
            )

            response_ru = await ask_brain(
                user_text_ru
            )

            runtime_state.brain["model"] = (
                config.SERVICE_MODEL_UID
            )

            runtime_state.brain["used_tokens"] = (
                estimate_tokens(
                    user_text_ru + response_ru
                )
            )

            runtime_state.brain["max_tokens"] = (
                config.SERVICE_CONTEXT_WINDOW
            )

            await send_telemetry(websocket)

            await websocket.send_json({
                "type": "message",
                "text": response_ru,
            })

            return

        # ---------------------------------------------------------
        # STEP 1 — RU -> EN
        # ---------------------------------------------------------

        await logger.log_translation(
            "Translating RU -> EN..."
        )

        text_en = await translate_ru_to_en(
            user_text_ru
        )

        runtime_state.service["model"] = (
            config.SERVICE_MODEL_UID
        )

        runtime_state.service["used_tokens"] = (
            estimate_tokens(
                user_text_ru + text_en
            )
        )

        runtime_state.service["max_tokens"] = (
            config.SERVICE_CONTEXT_WINDOW
        )

        await send_telemetry(websocket)

        if text_en.startswith(
            "[TRANSLATION_ERROR"
        ):

            runtime_state.service["model"] = (
                "OFFLINE"
            )

            await send_telemetry(websocket)

            await logger.log_error(
                f"Translator failed: {text_en}"
            )

            await websocket.send_json({
                "type": "error",
                "source": "translator",
                "text": text_en,
            })

            return

        await logger.log_translation(
            f"EN input: '{text_en}'"
        )

        # ---------------------------------------------------------
        # STEP 2 — BRAIN
        # ---------------------------------------------------------

        await logger.log_brain(
            "Sending message to brain..."
        )

        try:

            brain_response_en = await ask_brain(
                text_en
            )

            runtime_state.brain["model"] = (
                config.BRAIN_MODEL_UID
            )

            runtime_state.brain["used_tokens"] = (
                estimate_tokens(
                    text_en + brain_response_en
                )
            )

            runtime_state.brain["max_tokens"] = (
                config.BRAIN_CONTEXT_WINDOW
            )

            await send_telemetry(websocket)

        except Exception as e:

            runtime_state.brain["model"] = (
                "OFFLINE"
            )

            await send_telemetry(websocket)

            await logger.log_error(str(e))

            await websocket.send_json({
                "type": "error",
                "source": "brain",
                "text": str(e),
            })

            return

        if config.USE_SERVICE_AS_BRAIN:

            await logger.log_service_as_brain(
                brain_response_en
            )

        else:

            await logger.log_brain(
                brain_response_en
            )

        # ---------------------------------------------------------
        # STEP 3 — EN -> RU
        # ---------------------------------------------------------

        await logger.log_translation(
            "Translating EN -> RU..."
        )

        brain_response_ru = (
            await translate_en_to_ru(
                brain_response_en
            )
        )

        runtime_state.service["used_tokens"] += (
            estimate_tokens(
                brain_response_en
                + brain_response_ru
            )
        )

        await send_telemetry(websocket)

        await logger.log_translation(
            f"RU output: '{brain_response_ru}'"
        )

        # ---------------------------------------------------------
        # STEP 4 — SEND RESPONSE
        # ---------------------------------------------------------

        await websocket.send_json({
            "type": "message",
            "text": brain_response_ru,
        })

        await logger.log_runtime(
            "Pipeline cycle complete."
        )

    except Exception as e:

        traceback.print_exc()

        await logger.log_error(
            f"Pipeline error: {e}"
        )

        await websocket.send_json({
            "type": "error",
            "source": "pipeline",
            "text": str(e),
        })
