import uuid

import config

from clients.service_client import (
    ask_service_model_stream,
)

from utils.tokens import (
    estimate_tokens,
)

from utils.runtime_state_sync import (
    refresh_runtime_state,
)

from utils.ws_errors import (
    handle_pipeline_error,
    handle_fatal_pipeline_error,
)

from hooks.stream_validator import (
    StreamValidator,
)


class ServicePipeline:

    async def run(
        self,
        websocket,
        logger,
        message_data,
    ):

        try:

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

            await logger.log_runtime(
                "SERVICE pipeline started."
            )

            response = ""

            # -------------------------------------------------
            # DURING-HOOK VALIDATOR
            # -------------------------------------------------
            #
            # Monitors streamed output for:
            # - repetition loops
            # - sentence duplication
            # - paragraph duplication
            # - runaway generation
            #
            # -------------------------------------------------

            validator = StreamValidator()

            try:

                message_id = str(
                    uuid.uuid4()
                )

                await websocket.send_json({
                    "type": "message_start",
                    "message_id": (
                        message_id
                    ),
                    "role": "service",
                })

                async for chunk in (
                    ask_service_model_stream(
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

                    # -----------------------------------------
                    # THINKING STREAM
                    # -----------------------------------------

                    if (
                        chunk_type
                        == "thinking"
                    ):

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

                    # -----------------------------------------
                    # DURING STREAM VALIDATION
                    # -----------------------------------------

                    safe_chunk, is_valid = (
                        validator.filter_chunk(
                            chunk_content
                        )
                    )

                    if not is_valid:

                        await logger.log_validator(
                            f"{validator.last_failure_reason}\n"
                            f'Preview: "{validator.last_failure_preview}"'
                        )

                        await websocket.send_json({
                            "type": "message_error",
                            "message_id": (
                                message_id
                            ),
                            "text": (
                                "Generation stopped: "
                                "model repetition detected."
                            ),
                        })

                        if safe_chunk:

                            response += safe_chunk

                            await websocket.send_json({
                                "type": "message_chunk",
                                "message_id": (
                                    message_id
                                ),
                                "chunk": (
                                    safe_chunk
                                ),
                            })

                        break

                    # -----------------------------------------
                    # STREAM OUTPUT
                    # -----------------------------------------

                    response += (
                        safe_chunk
                    )

                    await websocket.send_json({
                        "type": "message_chunk",
                        "message_id": (
                            message_id
                        ),
                        "chunk": (
                            chunk_content
                        ),
                    })

                # ---------------------------------------------
                # STREAM COMPLETE
                # ---------------------------------------------

                await websocket.send_json({
                    "type": "message_end",
                    "message_id": (
                        message_id
                    ),
                })

                # ---------------------------------------------
                # TELEMETRY UPDATE
                # ---------------------------------------------

                await refresh_runtime_state(
                    websocket,
                    runtime_id=(
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
                    last_error=None,
                    status="online",
                )

                await logger.log_service(
                    response
                )

            except Exception as error:

                await handle_pipeline_error(
                    websocket,
                    logger,
                    runtime_id=(
                        config
                        .SERVICE_MODEL_UID
                    ),
                    public_message=(
                        "Service request failed."
                    ),
                    exception=error,
                )

                return

            await logger.log_runtime(
                "Service pipeline complete."
            )

        except Exception as error:

            await handle_fatal_pipeline_error(
                websocket,
                logger,
                pipeline_name=(
                    "service_pipeline"
                ),
                exception=error,
            )
