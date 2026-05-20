import uuid

import config

from clients.brain_client import (
    ask_brain,
    ask_brain_stream,
)

from utils.tokens import (
    estimate_tokens,
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


class BrainPipeline:

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
                "Brain pipeline started."
            )

            brain_runtime = (
                get_brain_runtime_config()
            )

            response = ""

            try:

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
                        user_text
                    )
                ):

                    response += chunk

                    await websocket.send_json({
                        "type": "message_chunk",
                        "message_id": (
                            message_id
                        ),
                        "chunk": chunk,
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
                            user_text
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

                return

            await logger.log_runtime(
                "Brain pipeline complete."
            )

        except Exception as error:

            await handle_fatal_pipeline_error(
                websocket,
                logger,
                pipeline_name=(
                    "brain_pipeline"
                ),
                exception=error,
            )
