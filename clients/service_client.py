import asyncio


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
    client,
    user_prompt: str,
    system_prompt: str = "",
    temperature: float,
    max_tokens: int,
):

    return await client.ask(
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
    context,
    client,
    user_prompt: str,
    system_prompt: str = "",
    temperature: float,
    max_tokens: int,
):

    try:

        async for chunk in (
            client.stream(
                context=context,
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

    except asyncio.CancelledError:
        raise
