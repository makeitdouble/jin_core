import config

from clients.model_client import ask_model

async def ask_service_model(
    *,
    user_prompt: str,
    system_prompt: str,
    temperature: float,
    max_tokens: int,
) -> str:

    return await ask_model(
        api_base=config.SERVICE_API_BASE,
        model_uid=config.SERVICE_MODEL_UID,
        user_prompt=user_prompt,
        system_prompt=system_prompt,
        timeout=config.SERVICE_REQUEST_TIMEOUT,
        temperature=temperature,
        max_tokens=max_tokens,
        validate_model=False,
    )
