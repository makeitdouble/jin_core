import traceback

import config

from clients.translation_client import (
    translate_ru_to_en,
)

from clients.service_client import (
    ask_service_model,
)

from memory.runtime_state import (
    runtime_state,
)

from utils.tokens import (
    estimate_tokens,
)

from utils.telemetry import (
    send_telemetry,
)

from utils.language import (
    contains_cyrillic,
)


class BypassPipeline:

    async def run(
        self,
        websocket,
        logger,
        message_data,
    ):

        try:

            user_text = (
                message_data.get("text", "")
                .strip()
            )

            if not user_text:

                await logger.log_error(
                    "Received empty message."
                )

                return

            await logger.log_runtime(
                "BYPASS pipeline enabled."
            )

            # ---------------------------------------------------------
            # TRANSLATOR ROUTE
            # ---------------------------------------------------------

            if contains_cyrillic(
                user_text
            ):

                await logger.log_runtime(
                    "Routing request to translator."
                )

                try:

                    response = (
                        await translate_ru_to_en(
                            user_text
                        )
                    )

                    runtime_state.update_node_state(
                        "translator",
                        model=(
                            config
                            .TRANSLATOR_MODEL_UID
                        ),
                        used_tokens=(
                            estimate_tokens(
                                user_text
                                + response
                            )
                        ),
                        max_tokens=(
                            config
                            .TRANSLATOR_CONTEXT_WINDOW
                        ),
                    )

                    await logger.log_translation(
                        response
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
                        f"Translator error: {e}"
                    )

                    await websocket.send_json({
                        "type": "error",
                        "source": "translator",
                        "text": str(e),
                    })

                    return

            # ---------------------------------------------------------
            # SERVICE ROUTE
            # ---------------------------------------------------------

            else:

                await logger.log_runtime(
                    "Routing request to service."
                )

                try:

                    response = (
                        await ask_service_model(
                            user_prompt=user_text,
                            system_prompt="",
                            temperature=(
                                config
                                .SERVICE_TEMPERATURE
                            ),
                            max_tokens=(
                                config
                                .SERVICE_MAX_TOKENS
                            ),
                        )
                    )

                    runtime_state.update_node_state(
                        "service",
                        model=(
                            config
                            .SERVICE_MODEL_UID
                        ),
                        used_tokens=(
                            estimate_tokens(
                                user_text
                                + response
                            )
                        ),
                        max_tokens=(
                            config
                            .SERVICE_CONTEXT_WINDOW
                        ),
                    )

                    await logger.log_service(
                        response
                    )

                except Exception as e:

                    runtime_state.update_node_state(
                        "service",
                        model="OFFLINE",
                    )

                    await send_telemetry(
                        websocket
                    )

                    await logger.log_error(
                        f"Service error: {e}"
                    )

                    await websocket.send_json({
                        "type": "error",
                        "source": "service",
                        "text": str(e),
                    })

                    return

            # ---------------------------------------------------------
            # SEND RESPONSE
            # ---------------------------------------------------------

            await send_telemetry(
                websocket
            )

            await websocket.send_json({
                "type": "message",
                "text": response,
            })

            await logger.log_runtime(
                "Bypass pipeline complete."
            )

        except Exception as e:

            await logger.log_error(
                traceback.format_exc()
            )

            await logger.log_error(
                f"Direct runtime error: {e}"
            )

            await websocket.send_json({
                "type": "error",
                "source": "direct_runtime_pipeline",
                "text": str(e),
            })
