import config

from contracts.context_contract import (
    ContextContract,
)

from utils.errors import (
    format_client_error,
)

from clients.runtime_client import (
    RuntimeClient,
)

from clients.service_client import (
    ask_service_model,
    ask_service_model_stream,
)


brain_client = RuntimeClient(
    api_base=(
        config.BRAIN_API_BASE
    ),
    model_uid=(
        config.BRAIN_MODEL_UID
    ),
    timeout=(
        config
        .BRAIN_REQUEST_TIMEOUT
    ),
)


# ---------------------------------------------------------
# SYSTEM PROMPT
# ---------------------------------------------------------

def build_brain_system_prompt():

    return (
        "You are JIN, a human-like assistant.\n"
        "NEVER explain your reasoning.\n"
        "NEVER analyze the request.\n"
        "NEVER describe your plan.\n"
        "NEVER output chain-of-thought.\n"
        "Reply with ONLY the final answer.\n"
        "Keep responses natural and conversational.\n"
    )


# ---------------------------------------------------------
# PAYLOAD
# ---------------------------------------------------------

def build_brain_payload(
    text_en: str,
) -> str:

    context_contract = ContextContract(
        user_input=text_en,
        compressed_history="",
        system_state="ACTIVE",
    )

    return context_contract.to_xml()


# ---------------------------------------------------------
# NORMAL REQUEST
# ---------------------------------------------------------

async def ask_brain(
    text_en: str,
) -> str:

    brain_payload = (
        build_brain_payload(
            text_en
        )
    )

    # -----------------------------------------------------
    # SERVICE AS BRAIN
    # -----------------------------------------------------

    if config.USE_SERVICE_AS_BRAIN:

        try:

            result = await ask_service_model(
                user_prompt=brain_payload,
                system_prompt=(
                    build_brain_system_prompt()
                ),
                temperature=(
                    config.BRAIN_TEMPERATURE
                ),
                max_tokens=(
                    config.BRAIN_MAX_TOKENS
                ),
            )

            message = (
                result
                .get("choices", [{}])[0]
                .get("message", {})
            )

            return (
                message.get(
                    "content",
                    "",
                ).strip()
            )

        except Exception as error:

            formatted_error = (
                format_client_error(
                    "service_as_brain",
                    config.SERVICE_API_BASE,
                    config.SERVICE_MODEL_UID,
                    error,
                )
            )

            raise RuntimeError(
                formatted_error
            )

    # -----------------------------------------------------
    # REAL BRAIN
    # -----------------------------------------------------

    try:

        result = await brain_client.ask(
            system_prompt=(
                build_brain_system_prompt()
            ),
            user_prompt=brain_payload,
            temperature=(
                config
                .BRAIN_TEMPERATURE
            ),
            max_tokens=(
                config
                .BRAIN_MAX_TOKENS
            ),
        )

        returned_model = result.get(
            "model",
            "",
        )

        if (
            returned_model
            != config.BRAIN_MODEL_UID
        ):

            raise RuntimeError(
                f"Wrong model loaded. "
                f"Expected "
                f"'{config.BRAIN_MODEL_UID}', "
                f"got "
                f"'{returned_model}'"
            )

        message = (
            result
            .get("choices", [{}])[0]
            .get("message", {})
        )

        content = (
            message.get(
                "content",
                "",
            ).strip()
        )

        if content:
            return content

        return (
            message.get(
                "reasoning_content",
                "",
            ).strip()
        )

    except Exception as error:

        formatted_error = (
            format_client_error(
                "brain",
                config.BRAIN_API_BASE,
                config.BRAIN_MODEL_UID,
                error,
            )
        )

        raise RuntimeError(
            formatted_error
        )


# ---------------------------------------------------------
# STREAM REQUEST
# ---------------------------------------------------------

async def ask_brain_stream(
    text_en: str,
):

    brain_payload = (
        build_brain_payload(
            text_en
        )
    )

    # -----------------------------------------------------
    # SERVICE AS BRAIN
    # -----------------------------------------------------

    if config.USE_SERVICE_AS_BRAIN:

        try:

            async for chunk in (
                ask_service_model_stream(
                    user_prompt=(
                        brain_payload
                    ),
                    system_prompt=(
                        build_brain_system_prompt()
                    ),
                    temperature=(
                        config
                        .BRAIN_TEMPERATURE
                    ),
                    max_tokens=(
                        config
                        .BRAIN_MAX_TOKENS
                    ),
                )
            ):

                yield chunk

            return

        except Exception as error:

            formatted_error = (
                format_client_error(
                    "service_as_brain",
                    config.SERVICE_API_BASE,
                    config.SERVICE_MODEL_UID,
                    error,
                )
            )

            raise RuntimeError(
                formatted_error
            )

    # -----------------------------------------------------
    # REAL BRAIN
    # -----------------------------------------------------

    try:

        async for chunk in (
            brain_client.stream(
                system_prompt=(
                    build_brain_system_prompt()
                ),
                user_prompt=brain_payload,
                temperature=(
                    config
                    .BRAIN_TEMPERATURE
                ),
                max_tokens=(
                    config
                    .BRAIN_MAX_TOKENS
                ),
            )
        ):

            yield chunk

    except Exception as error:

        formatted_error = (
            format_client_error(
                "brain",
                config.BRAIN_API_BASE,
                config.BRAIN_MODEL_UID,
                error,
            )
        )

        raise RuntimeError(
            formatted_error
        )
