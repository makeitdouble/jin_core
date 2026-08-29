import asyncio

from runtime.memory_common import (
    refresh_service_runtime_usage,
)


async def ask_service_model(
    *,
    client,
    context=None,
    user_prompt,
    system_prompt: str = "",
    temperature: float,
    max_tokens: int | None,
    timeout: float | None = None,
    track_usage: bool = True,
):

    request = {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    if timeout is not None:
        request["timeout"] = timeout

    if track_usage:
        await refresh_service_runtime_usage(
            context,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

    response = await client.ask(
        **request
    )

    if track_usage:
        await refresh_service_runtime_usage(
            context,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response=response,
        )

    return response


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
