import config

from contracts.context_contract import (
    ContextContract,
)

from utils.errors import (
    format_client_error,
)

from clients.model_client import (
    ask_model,
)

from clients.service_client import (
    ask_service_model,
)


def build_brain_system_prompt():

    return (
        "You are JIN, "
        "a human-like assistant.\n"
    )


def build_brain_payload(
    text_en: str,
) -> str:

    context_contract = ContextContract(
        user_input=text_en,
        compressed_history="",
        system_state="ACTIVE",
    )

    return context_contract.to_xml()


async def ask_brain(
    text_en: str,
) -> str:

    brain_payload = (
        build_brain_payload(
            text_en
        )
    )

    if config.USE_SERVICE_AS_BRAIN:

        try:

            return await ask_service_model(
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

    try:

        return await ask_model(
            api_base=(
                config.BRAIN_API_BASE
            ),
            model_uid=(
                config.BRAIN_MODEL_UID
            ),
            user_prompt=brain_payload,
            system_prompt=(
                build_brain_system_prompt()
            ),
            timeout=(
                config
                .BRAIN_REQUEST_TIMEOUT
            ),
            temperature=(
                config
                .BRAIN_TEMPERATURE
            ),
            max_tokens=(
                config
                .BRAIN_MAX_TOKENS
            ),
            validate_model=True,
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
