import config

from clients.model_client import (
    ask_model,
    ask_model_stream,
)


def build_service_system_prompt():

    return (
        "You are a backend service model.\n"
        "Your task is to produce clean final outputs.\n"
        "Do not explain reasoning.\n"
        "Do not describe intentions.\n"
        "Do not output analysis.\n"
        "Do not output plans.\n"
        "Do not output chain-of-thought.\n"
        "Respond only with the final result.\n"
        "Keep responses concise and direct.\n"
    )


async def ask_service_model(
    *,
    user_prompt: str,
    system_prompt: str | None = None,
    temperature: float,
    max_tokens: int,
) -> str:

    final_system_prompt = (
        system_prompt
        or build_service_system_prompt()
    )

    return await ask_model(
        api_base=(
            config.SERVICE_API_BASE
        ),
        model_uid=(
            config.SERVICE_MODEL_UID
        ),
        user_prompt=user_prompt,
        system_prompt=(
            final_system_prompt
        ),
        timeout=(
            config
            .SERVICE_REQUEST_TIMEOUT
        ),
        temperature=temperature,
        max_tokens=max_tokens,
        validate_model=False,
    )


async def ask_service_model_stream(
    *,
    user_prompt: str,
    system_prompt: str | None = None,
    temperature: float,
    max_tokens: int,
):

    final_system_prompt = (
        system_prompt
        or build_service_system_prompt()
    )

    async for chunk in ask_model_stream(
        api_base=(
            config.SERVICE_API_BASE
        ),
        model_uid=(
            config.SERVICE_MODEL_UID
        ),
        user_prompt=user_prompt,
        system_prompt=(
            final_system_prompt
        ),
        timeout=(
            config
            .SERVICE_REQUEST_TIMEOUT
        ),
        temperature=temperature,
        max_tokens=max_tokens,
    ):

        yield chunk
