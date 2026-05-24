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

                    print("[RAW SSE]", raw_line)

                    if raw_line is None:
                        continue

                    line = raw_line.strip()

                    if not line:
                        continue

                    # -------------------------------------------------
                    # SSE / NON-SSE SUPPORT
                    # -------------------------------------------------

                    if line.startswith("data:"):

                        data = (
                            line.split(
                                "data:",
                                1,
                            )[1]
                            .strip()
                        )

                    else:

                        data = line.strip()

                    # -------------------------------------------------
                    # DONE
                    # -------------------------------------------------

                    if data == "[DONE]":
                        print("[STREAM DONE]")
                        break

                    # -------------------------------------------------
                    # JSON
                    # -------------------------------------------------

                    try:

                        chunk = json.loads(
                            data
                        )

                    except Exception as e:

                        print(
                            "[JSON PARSE ERROR]",
                            e,
                        )

                        print(
                            "[BROKEN DATA]",
                            data,
                        )

                        continue

                    # -------------------------------------------------
                    # DEBUG
                    # -------------------------------------------------

                    print(
                        "[PARSED CHUNK]",
                        chunk,
                    )

                    # -------------------------------------------------
                    # USAGE
                    # -------------------------------------------------

                    usage = (
                        ResponseExtractor
                        .extract_usage(
                            chunk
                        )
                    )

                    if usage:

                        yield usage

                    # -------------------------------------------------
                    # THINKING
                    # -------------------------------------------------

                    reasoning = (
                        ResponseExtractor
                        .extract_reasoning_chunk(
                            chunk
                        )
                    )

                    if reasoning:

                        yield reasoning

                    # -------------------------------------------------
                    # CONTENT
                    # -------------------------------------------------

                    content = (
                        ResponseExtractor
                        .extract_content_chunk(
                            chunk
                        )
                    )

                    if content:

                        yield content

                    # -------------------------------------------------
                    # FINISH REASON
                    # -------------------------------------------------

                    finish_reason = (
                        ResponseExtractor
                        .extract_finish_reason(
                            chunk
                        )
                    )

                    if finish_reason:

                        print(
                            "[FINISH REASON]",
                            finish_reason,
                        )

                        break

        # ---------------------------------------------------------
        # TASK CANCELLED
        # ---------------------------------------------------------

        except asyncio.CancelledError:

            print(
                "[STREAM CANCELLED]"
            )

            if response is not None:

                try:

                    await response.aclose()

                except Exception:
                    pass

            raise

        # ---------------------------------------------------------
        # FATAL ERROR
        # ---------------------------------------------------------

        except Exception as e:

            print(
                "[RUNTIME CLIENT ERROR]",
                repr(e),
            )

            raise