import json

import httpx

import config

from utils.urls import (
    join_url,
)


def build_payload(
    *,
    model_uid: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
    stream: bool = False,
) -> dict:

    return {
        "model": model_uid,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": stream,
    }


async def ask_model(
    *,
    api_base: str,
    model_uid: str,
    system_prompt: str,
    user_prompt: str,
    timeout: float,
    temperature: float,
    max_tokens: int,
    validate_model: bool = False,
) -> str:

    payload = build_payload(
        model_uid=model_uid,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    async with httpx.AsyncClient(
        timeout=timeout,
    ) as client:

        response = await client.post(
            join_url(
                api_base,
                config.CHAT_ENDPOINT,
            ),
            json=payload,
        )

        response.raise_for_status()

        result = response.json()

    if validate_model:

        returned_model = result.get(
            "model",
            "",
        )

        if returned_model != model_uid:

            raise RuntimeError(
                f"Wrong model loaded. "
                f"Expected '{model_uid}', "
                f"got '{returned_model}'"
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

    reasoning = (
        message.get(
            "reasoning_content",
            "",
        ).strip()
    )

    return reasoning


async def ask_model_stream(
    *,
    api_base: str,
    model_uid: str,
    system_prompt: str,
    user_prompt: str,
    timeout: float,
    temperature: float,
    max_tokens: int,
):

    payload = build_payload(
        model_uid=model_uid,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )

    async with httpx.AsyncClient(
        timeout=None,
    ) as client:

        async with client.stream(
            "POST",
            join_url(
                api_base,
                config.CHAT_ENDPOINT,
            ),
            json=payload,
        ) as response:

            response.raise_for_status()

            async for line in response.aiter_lines():

                if not line:
                    continue

                if not line.startswith(
                    "data:"
                ):
                    continue

                data = line.removeprefix(
                    "data:"
                ).strip()

                if data == "[DONE]":
                    break

                try:

                    chunk = json.loads(
                        data
                    )

                except Exception:
                    continue

                choices = chunk.get(
                    "choices",
                    []
                )

                if not choices:
                    continue

                delta = choices[0].get(
                    "delta",
                    {}
                )

                reasoning = (
                    delta.get(
                        "reasoning_content"
                    )
                    or delta.get(
                        "reasoning"
                    )
                )

                if reasoning:

                    yield {
                        "type": "thinking",
                        "content": reasoning,
                    }


                content = delta.get(
                    "content"
                )

                if content:

                    yield {
                        "type": "content",
                        "content": content,
                    }
