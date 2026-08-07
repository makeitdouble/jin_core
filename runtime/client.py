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


class LMStudioAPIError(RuntimeError):

    def __init__(
            self,
            summary: str,
            *,
            details: str,
    ):

        super().__init__(summary)
        self.summary = str(summary or "LM Studio request failed.")
        self.details = str(details or "")


def _extract_lm_studio_error_payload(value):

    if not isinstance(value, dict):
        return None

    error_value = value.get("error")
    if error_value not in (None, "", {}, []):
        return error_value

    event_type = str(
        value.get("type", "")
        or value.get("object", "")
        or ""
    ).strip().casefold()

    if event_type in {
        "error",
        "response.error",
    }:
        return value

    return None


def _lm_studio_error_message(value) -> str:

    if isinstance(value, dict):
        for key in (
            "message",
            "detail",
            "error",
            "code",
        ):
            candidate = value.get(key)
            if candidate not in (None, "", {}, []):
                if isinstance(candidate, (dict, list)):
                    return _preview_runtime_payload(
                        candidate,
                        limit=1200,
                    )
                return str(candidate).strip()

        return _preview_runtime_payload(
            value,
            limit=1200,
        ).strip()

    if isinstance(value, list):
        return _preview_runtime_payload(
            value,
            limit=1200,
        ).strip()

    return str(value or "").strip()


def _build_lm_studio_error(
        *,
        endpoint: str,
        payload: dict,
        error_payload=None,
        response=None,
        error: Exception | None = None,
) -> LMStudioAPIError:

    status_code = getattr(
        response,
        "status_code",
        None,
    )
    response_json = None
    response_text = ""

    if response is not None:
        try:
            response_json = response.json()
        except Exception:
            response_json = None

        try:
            response_text = str(
                response.text
                or ""
            ).strip()
        except Exception:
            response_text = ""

    if error_payload is None:
        error_payload = _extract_lm_studio_error_payload(
            response_json
        )

    provider_message = _lm_studio_error_message(
        error_payload
    )

    if not provider_message and response_text:
        provider_message = response_text[:1200]

    if not provider_message and error is not None:
        provider_message = str(error).strip()

    if status_code:
        summary = f"HTTP {status_code}"
        if provider_message:
            summary += f": {provider_message}"
    else:
        summary = (
            provider_message
            or "LM Studio request failed."
        )

    details = {
        "provider": "LM Studio",
        "summary": summary,
        "endpoint": endpoint,
        "status": status_code,
        "model": payload.get("model"),
        "request": {
            "stream": payload.get("stream"),
            "max_tokens": payload.get("max_tokens"),
            "temperature": payload.get("temperature"),
        },
        "lm_studio_error": error_payload,
        "response_json": response_json,
        "response_body": (
            response_text[:8000]
            if response_text
            else ""
        ),
        "client_exception": (
            repr(error)
            if error is not None
            else ""
        ),
    }

    return LMStudioAPIError(
        summary,
        details=json.dumps(
            details,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
    )


def _preview_runtime_payload(
        value,
        *,
        limit: int = 4000,
) -> str:

    if isinstance(
        value,
        (
            dict,
            list,
        ),
    ):
        text = json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    else:
        text = str(
            value
            or ""
        )

    if len(text) <= limit:
        return text

    return (
        text[:limit]
        + f"\n... <truncated {len(text) - limit} chars>"
    )


def _build_stream_json_error_details(
        *,
        payload: dict,
        error: Exception | None = None,
        invalid_json_samples: list[str] | None = None,
        valid_json_chunks: int = 0,
        followup_tick: bool = False,
) -> str:

    messages = payload.get(
        "messages",
        [],
    )
    system_prompt = ""
    user_prompt = ""

    if isinstance(
        messages,
        list,
    ):
        for message in messages:
            if not isinstance(
                message,
                dict,
            ):
                continue

            role = message.get(
                "role",
            )
            if role == "system":
                system_prompt = message.get(
                    "content",
                    "",
                )
            elif role == "user":
                user_prompt = message.get(
                    "content",
                    "",
                )

    details = {
        "error": repr(error) if error is not None else "",
        "model": payload.get("model"),
        "stream": payload.get("stream"),
        "max_tokens": payload.get("max_tokens"),
        "temperature": payload.get("temperature"),
        "followup_tick": followup_tick,
        "valid_json_chunks": valid_json_chunks,
        "invalid_json_samples": invalid_json_samples or [],
        "system_prompt_preview": _preview_runtime_payload(
            system_prompt,
            limit=2500,
        ),
        "user_prompt_type": type(user_prompt).__name__,
        "user_prompt_preview": _preview_runtime_payload(
            user_prompt,
            limit=2500,
        ),
    }

    return json.dumps(
        details,
        ensure_ascii=False,
        indent=2,
        default=str,
    )


async def _log_context_error(
        context,
        message: str,
        *,
        details: str | None = None,
) -> None:

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

    if log_error is None:
        logger.warning(
            "%s",
            message,
        )
        return

    try:
        await log_error(
            message,
            details=details,
        )
    except TypeError:
        await log_error(
            message
        )


class RuntimeClient:

    def __init__(
            self,
            *,
            api_base: str,
            model_uid: str,
            timeout: float,
            configured_context_window: int | None = None,
            configured_max_tokens: int | None = None,
            client: httpx.AsyncClient,
    ):

        self.api_base = api_base
        self.model_uid = model_uid
        self.timeout = timeout
        self.configured_context_window = configured_context_window
        self.configured_max_tokens = configured_max_tokens
        self.client = client
        self.detected_context_window = None
        self.detected_max_tokens = None
        self.model_limits_detection_attempted = False

    # ---------------------------------------------------------
    # MODEL LIMIT DETECTION
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

        # Prefer the loaded/runtime context window over the model's theoretical
        # maximum. LM Studio native metadata can expose both values; using the
        # theoretical maximum would overestimate the real request budget.
        context_key_priority = {
            "loaded_context_length": 0,
            "loaded_context_window": 0,
            "loaded_n_ctx": 0,
            "context_length": 1,
            "context_window": 1,
            "n_ctx": 1,
            "num_ctx": 1,
            "ctx_size": 1,
            "context_size": 1,
            "max_context_length": 2,
            "max_context_window": 2,
            "max_position_embeddings": 2,
        }
        candidates: list[tuple[int, int]] = []

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

                    if normalized_key in context_key_priority:
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
                            candidates.append(
                                (
                                    context_key_priority[normalized_key],
                                    context_window,
                                )
                            )

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

        if not candidates:
            return None

        candidates.sort(
            key=lambda item: item[0]
        )
        return candidates[0][1]

    @staticmethod
    def extract_max_tokens_from_model(
            model,
    ) -> int | None:

        if not isinstance(
            model,
            dict,
        ):
            return None

        max_tokens_key_priority = {
            "loaded_max_tokens": 0,
            "loaded_max_output_tokens": 0,
            "loaded_max_completion_tokens": 0,
            "max_tokens": 1,
            "max_output_tokens": 1,
            "max_completion_tokens": 1,
            "n_predict": 1,
            "max_new_tokens": 1,
        }
        candidates: list[tuple[int, int]] = []

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

                    if normalized_key in max_tokens_key_priority:
                        try:
                            max_tokens = int(
                                value
                            )
                        except (
                            TypeError,
                            ValueError,
                        ):
                            max_tokens = 0

                        if max_tokens > 0:
                            candidates.append(
                                (
                                    max_tokens_key_priority[normalized_key],
                                    max_tokens,
                                )
                            )

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

        if not candidates:
            return None

        candidates.sort(
            key=lambda item: item[0]
        )
        return candidates[0][1]

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

            if not model_id:
                continue

            model_id = str(
                model_id
            )

            if model_id == self.model_uid:
                return model

            if self.model_uid in model_id or model_id in self.model_uid:
                return model

            if len(models) == 1:
                return models[0]

        return None

    def model_limits_detection_endpoints(self) -> list[str]:

        endpoints = [
            settings.MODELS_ENDPOINT,
        ]
        native_endpoint = getattr(
            settings,
            "NATIVE_MODELS_ENDPOINT",
            "",
        )

        if native_endpoint and native_endpoint not in endpoints:
            endpoints.append(
                native_endpoint
            )

        return endpoints

    async def detect_model_limits(
            self,
            *,
            force_refresh: bool = False,
    ) -> tuple[int | None, int | None]:

        if force_refresh:
            self.model_limits_detection_attempted = False
            self.detected_context_window = None
            self.detected_max_tokens = None

        if self.model_limits_detection_attempted:
            return (
                self.detected_context_window,
                self.detected_max_tokens,
            )

        self.model_limits_detection_attempted = True

        for endpoint in self.model_limits_detection_endpoints():

            try:
                response = await self.client.get(
                    join_url(
                        self.api_base,
                        endpoint,
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
                    continue

                context_window = (
                    self.extract_context_window_from_model(
                        model
                    )
                )

                max_tokens = (
                    self.extract_max_tokens_from_model(
                        model
                    )
                )

                if context_window:
                    self.detected_context_window = context_window

                if max_tokens:
                    self.detected_max_tokens = max_tokens

                if self.detected_context_window or self.detected_max_tokens:
                    return (
                        self.detected_context_window,
                        self.detected_max_tokens,
                    )

            except Exception:
                continue

        self.detected_context_window = None
        self.detected_max_tokens = None
        return (
            self.detected_context_window,
            self.detected_max_tokens,
        )

    async def detect_context_window(
            self,
            *,
            force_refresh: bool = False,
    ) -> int | None:

        detected_context_window, _ = await self.detect_model_limits(
            force_refresh=force_refresh,
        )
        return detected_context_window

    async def detect_max_tokens(self) -> int | None:

        _, detected_max_tokens = await self.detect_model_limits()
        return detected_max_tokens

    async def resolve_request_context_window(
            self,
            *,
            force_refresh: bool = False,
    ) -> int | None:

        if not settings.RUNTIME_CONTEXT_WINDOW_FALLBACK_TO_SERVER:
            return self.configured_context_window

        detected_context_window = await self.detect_context_window(
            force_refresh=force_refresh,
        )

        return (
            detected_context_window
            or self.configured_context_window
        )

    async def resolve_request_max_tokens(
            self,
            requested_max_tokens: int,
    ) -> int:

        if not settings.RUNTIME_MAX_TOKENS_FALLBACK_TO_SERVER:
            return requested_max_tokens

        if (
            self.configured_max_tokens is not None
            and requested_max_tokens != self.configured_max_tokens
        ):
            return requested_max_tokens

        detected_max_tokens = await self.detect_max_tokens()

        if detected_max_tokens:
            return detected_max_tokens

        if (
            self.detected_context_window
            and self.configured_max_tokens is not None
            and requested_max_tokens == self.configured_max_tokens
        ):
            return self.detected_context_window

        return requested_max_tokens

    async def resolve_safe_max_tokens(
            self,
            *,
            system_prompt: str,
            user_prompt,
            requested_max_tokens: int,
    ) -> int:

        request_context_window = (
            await self.resolve_request_context_window()
        )
        request_max_tokens = await self.resolve_request_max_tokens(
            requested_max_tokens
        )

        if not request_context_window:
            return request_max_tokens

        prompt_tokens = estimate_runtime_tokens(
            system_prompt=system_prompt,
            user_input=self.text_from_user_prompt(
                user_prompt
            ),
        )
        response_budget = (
            request_context_window
            - prompt_tokens
            - settings.RUNTIME_OUTPUT_TOKEN_RESERVE
        )

        return max(
            1,
            min(
                request_max_tokens,
                response_budget,
            ),
        )

    # ---------------------------------------------------------
    # PAYLOAD
    # ---------------------------------------------------------

    @staticmethod
    def text_from_user_prompt(
            user_prompt,
    ) -> str:

        if isinstance(
            user_prompt,
            str,
        ):
            return user_prompt

        if isinstance(
            user_prompt,
            list,
        ):
            text_parts = []

            for item in user_prompt:
                if not isinstance(
                    item,
                    dict,
                ):
                    continue

                if item.get(
                    "type",
                ) != "text":
                    continue

                text_parts.append(
                    str(
                        item.get(
                            "text",
                            "",
                        )
                    )
                )

            return "\n".join(
                text_parts,
            )

        return str(
            user_prompt
            or ""
        )

    def build_payload(
            self,
            *,
            system_prompt: str,
            user_prompt,
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

    @staticmethod
    def provider_user_prompt(
            context,
            user_prompt,
    ):

        if (
            isinstance(
                user_prompt,
                str,
            )
            and user_prompt == ""
            and bool(
                getattr(
                    context,
                    "runtime_followup_tick_active",
                    False,
                )
            )
        ):
            # Do not replace this with "" or "(empty)": LM Studio prompt
            # templates reject a truly empty user message ("No user query
            # found"), while visible context must still stay empty so the
            # model does not interpret a follow-up label as user input.
            return " "

        return user_prompt

    async def build_safe_payload(
            self,
            *,
            system_prompt: str,
            user_prompt,
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
            user_prompt,
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

        endpoint = join_url(
            self.api_base,
            settings.CHAT_ENDPOINT,
        )

        try:
            response = await self.client.post(
                endpoint,
                json=payload,
                timeout=(
                    self.timeout
                    if timeout is None
                    else timeout
                ),
            )

            response.raise_for_status()

        except httpx.HTTPError as error:
            raise _build_lm_studio_error(
                endpoint=endpoint,
                payload=payload,
                response=getattr(
                    error,
                    "response",
                    None,
                ),
                error=error,
            ) from error

        try:
            result = response.json()
        except Exception as error:
            raise _build_lm_studio_error(
                endpoint=endpoint,
                payload=payload,
                response=response,
                error=error,
            ) from error

        provider_error = _extract_lm_studio_error_payload(
            result
        )
        if provider_error is not None:
            raise _build_lm_studio_error(
                endpoint=endpoint,
                payload=payload,
                error_payload=provider_error,
                response=response,
            )

        return result

    # ---------------------------------------------------------
    # STREAM REQUEST
    # ---------------------------------------------------------

    async def stream(
            self,
            *,
            context,
            system_prompt: str,
            user_prompt,
            temperature: float,
            max_tokens: int,
    ):

        provider_user_prompt = self.provider_user_prompt(
            context,
            user_prompt,
        )

        payload = await self.build_safe_payload(
            system_prompt=system_prompt,
            user_prompt=provider_user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )

        stream_id = None
        valid_json_chunks = 0
        invalid_json_samples: list[str] = []
        endpoint = join_url(
            self.api_base,
            settings.CHAT_ENDPOINT,
        )

        try:

            async with self.client.stream(
                    "POST",
                    endpoint,
                    json=payload,
                    timeout=None,
            ) as response:

                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as error:
                    read_response = getattr(
                        response,
                        "aread",
                        None,
                    )
                    if read_response is not None:
                        try:
                            await read_response()
                        except Exception:
                            pass

                    raise _build_lm_studio_error(
                        endpoint=endpoint,
                        payload=payload,
                        response=response,
                        error=error,
                    ) from error

                stream_id = id(response)

                context.active_streams[
                    stream_id
                ] = response

                response_headers = getattr(
                    response,
                    "headers",
                    {},
                ) or {}
                content_type = str(
                    response_headers.get(
                        "content-type",
                        "",
                    )
                ).lower()
                is_sse_stream = (
                    "text/event-stream" in content_type
                )

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

                        is_sse_stream = True
                        data = (
                            line.split(
                                "data:",
                                1,
                            )[1]
                            .strip()
                        )

                    else:

                        if line.startswith(":"):
                            continue

                        sse_field = (
                            line.split(
                                ":",
                                1,
                            )[0]
                            .strip()
                            .lower()
                        )

                        if sse_field in {
                            "event",
                            "id",
                            "retry",
                        }:
                            is_sse_stream = True
                            continue

                        if is_sse_stream:
                            continue

                        data = line.strip()

                    # -------------------------------------------------
                    # DONE
                    # -------------------------------------------------

                    if data == "[DONE]":

                        break

                    if not data:

                        continue

                    # -------------------------------------------------
                    # JSON
                    # -------------------------------------------------

                    try:

                        chunk = json.loads(
                            data
                        )

                    except Exception as e:

                        if len(invalid_json_samples) < 3:
                            invalid_json_samples.append(
                                data[:200]
                            )

                        followup_tick = bool(
                            getattr(
                                context,
                                "runtime_followup_tick_active",
                                False,
                            )
                        )
                        await _log_context_error(
                            context,
                            f"[JSON PARSE ERROR] {e}",
                            details=_build_stream_json_error_details(
                                payload=payload,
                                error=e,
                                invalid_json_samples=[
                                    data[:200],
                                ],
                                valid_json_chunks=valid_json_chunks,
                                followup_tick=followup_tick,
                            ),
                        )

                        continue

                    valid_json_chunks += 1

                    provider_error = (
                        _extract_lm_studio_error_payload(
                            chunk
                        )
                    )
                    if provider_error is not None:
                        raise _build_lm_studio_error(
                            endpoint=endpoint,
                            payload=payload,
                            error_payload=provider_error,
                            response=response,
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

                        yield {
                            "type": "finish",
                            "finish_reason": finish_reason,
                        }

                        continue

                if valid_json_chunks <= 0:
                    followup_tick = bool(
                        getattr(
                            context,
                            "runtime_followup_tick_active",
                            False,
                        )
                    )
                    error_details = _build_stream_json_error_details(
                        payload=payload,
                        invalid_json_samples=invalid_json_samples,
                        valid_json_chunks=valid_json_chunks,
                        followup_tick=followup_tick,
                    )

                    if invalid_json_samples:
                        first_sample = invalid_json_samples[0]
                        raise RuntimeError(
                            "runtime stream ended without any valid JSON "
                            "chunks; first invalid payload: "
                            f"{first_sample!r}"
                        )

                    raise RuntimeError(
                        "runtime stream ended without any JSON chunks"
                    )

        # ---------------------------------------------------------
        # TASK CANCELLED
        # ---------------------------------------------------------

        except asyncio.CancelledError:

            raise

        # ---------------------------------------------------------
        # FATAL ERROR
        # ---------------------------------------------------------

        except LMStudioAPIError:

            raise

        except httpx.HTTPError as e:

            raise _build_lm_studio_error(
                endpoint=endpoint,
                payload=payload,
                response=getattr(
                    e,
                    "response",
                    None,
                ),
                error=e,
            ) from e

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
