import config

from clients.runtime_client import (
    RuntimeClient,
)


service_client = RuntimeClient(
    api_base=(
        config.SERVICE_API_BASE
    ),
    model_uid=(
        config.SERVICE_MODEL_UID
    ),
    timeout=(
        config
        .SERVICE_REQUEST_TIMEOUT
    ),
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
    system_prompt: str = "",
    temperature: float,
    max_tokens: int,
):

    return await service_client.ask(
        system_prompt=(
            system_prompt
            or build_service_system_prompt()
        ),
        user_prompt=user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )


async def ask_service_model_stream(
    *,
    user_prompt: str,
    system_prompt: str = "",
    temperature: float,
    max_tokens: int,
):

    async for chunk in (
        service_client.stream(
            system_prompt=(
                system_prompt
                or build_service_system_prompt()
            ),
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    ):

        yield chunk
