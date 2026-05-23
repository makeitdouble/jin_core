import asyncio
import json

import httpx

from settings.app_settings import settings

from utils.urls import (
    join_url,
)

from utils.response_extractor import (
    ResponseExtractor,
)


class RuntimeClient:

    def __init__(
        self,
        *,
        api_base: str,
        model_uid: str,
        timeout: float,
        client: httpx.AsyncClient,
    ):

        self.api_base = api_base
        self.model_uid = model_uid
        self.timeout = timeout
        self.client = client

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

        response = await self.client.post(
            join_url(
                self.api_base,
                settings.CHAT_ENDPOINT,
            ),
            json=payload,
            timeout=self.timeout,
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

        response = None

        try:

            async with self.client.stream(
                "POST",
                join_url(
                    self.api_base,
                    settings.CHAT_ENDPOINT,
                ),
                json=payload,
                timeout=None,
            ) as response:

                response.raise_for_status()

                async for raw_line in response.aiter_lines():

                    if raw_line is None:
                        continue

                    line = raw_line.strip()

                    if not line:
                        continue

                    # -------------------------------------------------
                    # ONLY SSE
                    # -------------------------------------------------

                    if not line.startswith(
                        "data:"
                    ):
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
                        ResponseExtractor
                        .extract_usage(
                            chunk
                        )
                    )

                    if usage:
                        yield usage

                    reasoning = (
                        ResponseExtractor
                        .extract_reasoning_chunk(
                            chunk
                        )
                    )

                    if reasoning:
                        yield reasoning

                    content = (
                        ResponseExtractor
                        .extract_content_chunk(
                            chunk
                        )
                    )

                    if content:
                        yield content

        # ---------------------------------------------------------
        # TASK CANCELLED
        # ---------------------------------------------------------

        except asyncio.CancelledError:

            if response is not None:

                try:

                    await response.aclose()

                except Exception:
                    pass

            raise
