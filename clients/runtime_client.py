import json

import httpx

import config

from utils.urls import (
    join_url,
)

from utils.chunk_extractor import (
    ChunkExtractor,
)


class RuntimeClient:

    def __init__(
        self,
        *,
        api_base: str,
        model_uid: str,
        timeout: float,
    ):

        self.api_base = api_base
        self.model_uid = model_uid
        self.timeout = timeout

    # ---------------------------------------------------------
    # PAYLOAD
    # ---------------------------------------------------------

    def build_payload(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
        stream: bool = False,
    ):

        payload = {
            "model": self.model_uid,
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

        if stream:

            payload["stream_options"] = {
                "include_usage": True
            }

        return payload

    # ---------------------------------------------------------
    # NORMAL REQUEST
    # ---------------------------------------------------------

    async def ask(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ):

        payload = self.build_payload(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
        )

        async with httpx.AsyncClient(
            timeout=self.timeout,
        ) as client:

            response = await client.post(
                join_url(
                    self.api_base,
                    config.CHAT_ENDPOINT,
                ),
                json=payload,
            )

            response.raise_for_status()

            return response.json()

    # ---------------------------------------------------------
    # STREAM REQUEST
    # ---------------------------------------------------------

    async def stream(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ):

        payload = self.build_payload(
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
                    self.api_base,
                    config.CHAT_ENDPOINT,
                ),
                json=payload,
            ) as response:

                response.raise_for_status()

                buffer = ""

                async for raw_line in response.aiter_lines():

                    if raw_line is None:
                        continue

                    line = raw_line.strip()

                    if not line:
                        continue

                    # only SSE payloads

                    if not line.startswith("data:"):
                        continue

                    try:

                        data = (
                            line.split(
                                "data:",
                                1,
                            )[1]
                            .strip()
                        )

                    except Exception:
                        continue

                    if data == "[DONE]":
                        break

                    try:

                        chunk = json.loads(
                            data
                        )

                    except Exception:
                        continue

                    usage = (
                        ChunkExtractor
                        .extract_usage(
                            chunk
                        )
                    )

                    if usage:
                        yield usage

                    reasoning = (
                        ChunkExtractor
                        .extract_reasoning(
                            chunk
                        )
                    )

                    if reasoning:
                        yield reasoning

                    content = (
                        ChunkExtractor
                        .extract_content(
                            chunk
                        )
                    )

                    if content:
                        yield content
