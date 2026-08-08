import asyncio


async def ask_service_model(
    *,
    client,
    user_prompt,
    system_prompt: str = "",
    temperature: float,
    max_tokens: int | None,
    timeout: float | None = None,
):

    request = {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    if timeout is not None:
        request["timeout"] = timeout

    return await client.ask(
        **request
    )


async def ask_service_model_stream(
    *,
    context,
    client,
    user_prompt,
    system_prompt: str = "",
    temperature: float,
    max_tokens: int | None,
):

    try:

        async for chunk in (
            client.stream(
                context=context,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        ):

            yield chunk

    except asyncio.CancelledError:
        raise
