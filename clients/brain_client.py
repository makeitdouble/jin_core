import config
from contracts.context_contract import ContextContract
from clients.errors import format_client_error
from clients.model_client import (
    ask_brain_model,
    ask_service_model,
)

def build_brain_payload(text_en: str) -> str:

    if config.USE_SERVICE_AS_BRAIN:
        return text_en

    context_contract = ContextContract(
        user_input=text_en,
        compressed_history="",
        system_state="ACTIVE",
    )

    return context_contract.to_xml()

async def ask_brain(text_en: str) -> str:

    brain_payload = build_brain_payload(text_en)

    if config.USE_SERVICE_AS_BRAIN:

        try:
            return await ask_service_model(brain_payload)

        except Exception as service_error:

            error = format_client_error(
                "service_as_brain",
                config.SERVICE_API_BASE,
                config.SERVICE_MODEL_UID,
                service_error,
            )

            raise RuntimeError(error)

    try:
        return await ask_brain_model(brain_payload)

    except Exception as brain_error:

        brain_error_text = format_client_error(
            config.BRAIN_MODEL_UID[:10],
            config.BRAIN_API_BASE,
            config.BRAIN_MODEL_UID,
            brain_error,
        )

        raise RuntimeError(brain_error_text)
