import asyncio
import json
import logging

import httpx

from app_settings import settings

from utils.urls import (
    join_url,
)
from utils.tokens import (
    estimate_runtime_tokens,
)

from clients.response_extractor import (
    ResponseExtractor,
)

logger = logging.getLogger(__name__)


class RuntimeClient:

    def __init__(
            self,
            *,
            api_base: str,
            model_uid: str,
            timeout: float,
            configured_context_window: int | None = None,
            client: httpx.AsyncClient,
    ):

        self.api_base = api_base
        self.model_uid = model_uid
        self.timeout = timeout
        self.configured_context_window = configured_context_window
        self.client = client
        self.detected_context_window = None
        self.context_window_detection_attempted = False

    # ---------------------------------------------------------
    # CONTEXT WINDOW DETECTION
    # ---------------------------------------------------------

    @staticmethod
    def extract_context_window_from_model(
            model,
    ) -> int | None:

        if not isinstance(
            model,
            dict,
        ):
            return None

        context_keys = {
            "context_length",
            "context_window",
            "max_context_length",
            "max_context_window",
            "n_ctx",
            "num_ctx",
            "ctx_size",
            "context_size",
            "max_position_embeddings",
        }

        stack = [
            model
        ]

        while stack:
            current = stack.pop()

            if isinstance(
                current,
                dict,
            ):
                for key, value in current.items():
                    normalized_key = str(
                        key
                    ).lower()

                    if normalized_key in context_keys:
                        try:
                            context_window = int(
                                value
                            )
                        except (
                            TypeError,
                            ValueError,
                        ):
                            context_window = 0

                        if context_window > 0:
                            return context_window

                    if isinstance(
                        value,
                        (
                            dict,
                            list,
                        ),
                    ):
                        stack.append(
                            value
                        )

            elif isinstance(
                current,
                list,
            ):
                stack.extend(
                    item
                    for item in current
                    if isinstance(
                        item,
                        (
                            dict,
                            list,
                        ),
                    )
                )

        return None

    @staticmethod
    def extract_model_list(
            payload,
    ) -> list[dict]:

        if isinstance(
            payload,
            dict,
        ):
            models = payload.get(
                "data",
                payload.get(
                    "models",
                    [],
                ),
            )
        else:
            models = payload

        if not isinstance(
            models,
            list,
        ):
            return []

        return [
            model
            for model in models
            if isinstance(
                model,
                dict,
            )
        ]

    def select_model_metadata(
            self,
            models: list[dict],
    ) -> dict | None:

        for model in models:
            model_id = (
                model.get(
                    "id"
                )
                or model.get(
                    "model"
                )
                or model.get(
                    "name"
                )
            )

            if model_id == self.model_uid:
                return model

            if self.model_uid in model_id or model_id in self.model_uid:
                return model

            if len(models) == 1:
                return models[0]

        return None

    async def detect_context_window(self) -> int | None:

        if self.context_window_detection_attempted:
            return self.detected_context_window

        self.context_window_detection_attempted = True

        try:
            response = await self.client.get(
                join_url(
                    self.api_base,
                    settings.MODELS_ENDPOINT,
                ),
                timeout=min(
                    self.timeout,
                    5.0,
                ),
            )
            response.raise_for_status()

            models = self.extract_model_list(
                response.json()
            )
            model = self.select_model_metadata(
                models
            )

            if model is None:
                return None

            self.detected_context_window = (
                self.extract_context_window_from_model(
                    model
                )
            )

        except Exception:
            self.detected_context_window = None

        return self.detected_context_window

    async def resolve_request_context_window(self) -> int | None:

        detected_context_window = await self.detect_context_window()

        return (
            detected_context_window
            or self.configured_context_window
        )

    async def resolve_safe_max_tokens(
            self,
            *,
            system_prompt: str,
            user_prompt: str,
            requested_max_tokens: int,
    ) -> int:

        request_context_window = (
            await self.resolve_request_context_window()
        )

        if not request_context_window:
            return requested_max_tokens

        prompt_tokens = estimate_runtime_tokens(
            system_prompt=system_prompt,
            user_input=user_prompt,
        )
        response_budget = (
            request_context_window
            - prompt_tokens
            - 128
        )

        return max(
            1,
            min(
                requested_max_tokens,
                response_budget,
            ),
        )

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
    ) -> dict[str, object]:

        payload: dict[str, object] = {
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

    async def build_safe_payload(
            self,
            *,
            system_prompt: str,
            user_prompt: str,
            temperature: float,
            max_tokens: int,
            stream: bool = False,
    ) -> dict[str, object]:

        safe_max_tokens = await self.resolve_safe_max_tokens(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            requested_max_tokens=max_tokens,
        )

        return self.build_payload(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=safe_max_tokens,
            stream=stream,
        )

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
            timeout: float | None = None,
    ):

        payload = await self.build_safe_payload(
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
            timeout=(
                self.timeout
                if timeout is None
                else timeout
            ),
        )

        response.raise_for_status()

        return response.json()

    # ---------------------------------------------------------
    # STREAM REQUEST
    # ---------------------------------------------------------

    async def stream(
            self,
            *,
            context,
            system_prompt: str,
            user_prompt: str,
            temperature: float,
            max_tokens: int,
    ):

        payload = await self.build_safe_payload(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )

        stream_id = None

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

                stream_id = id(response)

                context.active_streams[
                    stream_id
                ] = response

                async for raw_line in response.aiter_lines():

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

                        break

                    # -------------------------------------------------
                    # JSON
                    # -------------------------------------------------

                    try:

                        chunk = json.loads(
                            data
                        )

                    except Exception as e:

                        context_logger = getattr(
                            context,
                            "logger",
                            None,
                        )
                        log_error = getattr(
                            context_logger,
                            "log_error",
                            None,
                        )

                        if log_error is not None:
                            await log_error(
                                f"[JSON PARSE ERROR] {e}"
                            )
                        else:
                            logger.warning(
                                "JSON parse error: %s",
                                e,
                            )

                        continue

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

                        continue

        # ---------------------------------------------------------
        # TASK CANCELLED
        # ---------------------------------------------------------

        except asyncio.CancelledError:

            raise

        # ---------------------------------------------------------
        # FATAL ERROR
        # ---------------------------------------------------------

        except Exception as e:

            context_logger = getattr(
                context,
                "logger",
                None,
            )
            log_error = getattr(
                context_logger,
                "log_error",
                None,
            )

            if log_error is not None:
                await log_error(
                    f"[RUNTIME CLIENT ERROR] {repr(e)}"
                )

            logger.exception(
                "Runtime client error"
            )

            raise

        # ---------------------------------------------------------
        # FINAL CLEANUP
        # ---------------------------------------------------------

        finally:

            if (
                    context
                    and stream_id is not None
            ):

                context.active_streams.pop(
                    stream_id,
                    None,
                )
