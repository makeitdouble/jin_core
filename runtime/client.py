import asyncio
import json
import logging
import re
import time

import httpx

from app_settings import settings

from utils.urls import (
    join_url,
)
from utils.tokens import (
    estimate_prompt_tokens,
)

from clients.response_extractor import (
    ResponseExtractor,
)

logger = logging.getLogger(__name__)

MODEL_LIMITS_CACHE_TTL_SECONDS = 2.0
LEGACY_NATIVE_MODELS_ENDPOINT = "/api/v0/models"
LM_STUDIO_CONTEXT_WINDOW_PATTERNS = (
    re.compile(r"\bn_ctx[\"']?\s*[:=]\s*[\"']?(\d+)\b", re.IGNORECASE),
    re.compile(r"available context size\s*\(\s*(\d+)\s+tokens\s*\)", re.IGNORECASE),
    re.compile(
        r"\bcontext(?:\s+length|\s+window)?\s*(?:is|[:=])\s*(\d+)\b",
        re.IGNORECASE,
    ),
)

GENERIC_STREAM_PROVIDER = "generic_openai"
LM_STUDIO_STREAM_PROVIDER = "lm_studio"
LLAMA_CPP_STREAM_PROVIDER = "llama_cpp"
LM_STUDIO_NATIVE_CHAT_ENDPOINT = "/api/v1/chat"
LLAMA_CPP_PROPS_ENDPOINT = "/props"
LLAMA_CPP_MODEL_EVENTS_ENDPOINT = "/models/sse"


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


    def is_context_overflow(self) -> bool:
        # Inspect provider diagnostics only; request prompt text is not an error.
        diagnostic = (self.summary + "\n" + self.details).casefold()
        return any(marker in diagnostic for marker in (
            "context_overflow",
            "context_length_exceeded",
            "context window is full",
            "context length too small",
            "exceeds the available context",
            "exceed the available context",
            "maximum context length",
        ))


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
    system_prompt = payload.get(
        "system_prompt",
        "",
    )
    user_prompt = payload.get(
        "input",
        "",
    )

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
                    system_prompt,
                )
            elif role == "user":
                user_prompt = message.get(
                    "content",
                    user_prompt,
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
            configured_max_tokens: int | None = None,
            client: httpx.AsyncClient,
    ):

        self.api_base = api_base
        self.model_uid = model_uid
        self.timeout = timeout
        self.configured_max_tokens = configured_max_tokens
        self.client = client
        self.detected_context_window = None
        self.detected_max_tokens = None
        self.provider_context_window_ceiling = None
        self.provider_context_window_ceiling_detected_context = None
        self.model_limits_detection_attempted = False
        self.model_limits_detected_at = 0.0
        self.stream_provider_kind = None
        self.stream_provider_detected_at = 0.0

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

        # This extractor is intentionally LIVE-only. Provider metadata may
        # expose the model's theoretical capability (for example
        # max_context_length=131072) next to the context actually loaded for
        # the current instance (for example context_length=32768). The
        # theoretical value must never become the request/UI context budget.
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
                    "key"
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

        endpoints = []
        native_endpoint = getattr(
            settings,
            "NATIVE_MODELS_ENDPOINT",
            "",
        )

        # LM Studio's native metadata exposes the context_length of the
        # actually loaded instance. Prefer both native API generations over
        # OpenAI-compatible metadata: /v1/models may expose the model's
        # theoretical context length instead of the n_ctx used by the loaded
        # instance.
        for endpoint in (
            native_endpoint,
            LEGACY_NATIVE_MODELS_ENDPOINT,
            settings.MODELS_ENDPOINT,
        ):
            endpoint = str(endpoint or "").strip()
            if endpoint and endpoint not in endpoints:
                endpoints.append(endpoint)

        return endpoints

    @staticmethod
    def extract_context_window_from_error(
            error,
    ) -> int | None:

        # Error details retain the full JSON payload even when the public
        # summary is shortened. Prefer its explicit n_ctx to prose fallbacks.
        stack = [error, getattr(error, "details", None)]
        while stack:
            value = stack.pop()
            if isinstance(value, str):
                try:
                    decoded = json.loads(value)
                except (ValueError, TypeError):
                    continue
                if isinstance(decoded, (dict, list)):
                    stack.append(decoded)
            elif isinstance(value, dict):
                try:
                    limit = int(value.get("n_ctx", 0))
                except (ValueError, TypeError):
                    limit = 0
                if limit > 0:
                    return limit
                stack.extend(value.values())
            elif isinstance(value, list):
                stack.extend(value)

        text_parts = [
            str(
                getattr(
                    error,
                    "summary",
                    "",
                )
                or ""
            ),
            str(
                getattr(
                    error,
                    "details",
                    "",
                )
                or ""
            ),
            str(
                error
                or ""
            ),
        ]
        text = "\n".join(
            part
            for part in text_parts
            if part
        )

        for pattern in LM_STUDIO_CONTEXT_WINDOW_PATTERNS:
            match = pattern.search(
                text
            )
            if not match:
                continue

            try:
                context_window = int(
                    match.group(1)
                )
            except (
                TypeError,
                ValueError,
            ):
                context_window = 0

            if context_window > 0:
                return context_window

        return None

    def remember_provider_context_window(
            self,
            error,
    ) -> int | None:

        context_window = self.extract_context_window_from_error(
            error
        )
        if not context_window:
            return None

        detected_when_learned = self.detected_context_window
        current_ceiling = self.provider_context_window_ceiling
        if current_ceiling:
            context_window = min(
                int(current_ceiling),
                context_window,
            )

        self.provider_context_window_ceiling = context_window
        if detected_when_learned:
            self.provider_context_window_ceiling_detected_context = int(
                detected_when_learned
            )

        if self.detected_context_window:
            self.detected_context_window = min(
                int(self.detected_context_window),
                context_window,
            )

        return context_window

    def release_stale_provider_context_window_ceiling(
            self,
            detected_context_window: int | None,
    ) -> bool:

        ceiling = self.provider_context_window_ceiling
        learned_against = self.provider_context_window_ceiling_detected_context
        if not ceiling or not learned_against or not detected_context_window:
            return False

        try:
            detected = int(detected_context_window)
            learned = int(learned_against)
        except (TypeError, ValueError):
            return False

        # A provider 400 is authoritative only for the loaded model instance
        # that produced it. If a fresh metadata read now reports a larger live
        # n_ctx than the one seen when the ceiling was learned, LM Studio was
        # reconfigured in-place and the old ceiling must not pin future turns.
        if detected <= learned:
            return False

        self.provider_context_window_ceiling = None
        self.provider_context_window_ceiling_detected_context = None
        return True

    def select_loaded_model_metadata(
            self,
            model: dict,
    ) -> dict | None:

        loaded_instances = model.get(
            "loaded_instances"
        )

        if not isinstance(loaded_instances, list):
            return model

        instances = [
            instance
            for instance in loaded_instances
            if isinstance(instance, dict)
        ]
        if not instances:
            # Native v1 can list an available but unloaded model together with
            # its theoretical max_context_length. Never use that as the live
            # request budget.
            return None

        for instance in instances:
            instance_id = str(
                instance.get("id")
                or instance.get("key")
                or instance.get("model")
                or ""
            )
            if (
                instance_id == self.model_uid
                or self.model_uid in instance_id
                or instance_id in self.model_uid
            ):
                return instance

        return instances[0]

    async def detect_model_limits(
            self,
            *,
            force_refresh: bool = False,
    ) -> tuple[int | None, int | None]:

        now = time.monotonic()
        cache_is_fresh = (
            self.model_limits_detection_attempted
            and self.model_limits_detected_at > 0
            and (
                now - self.model_limits_detected_at
                < MODEL_LIMITS_CACHE_TTL_SECONDS
            )
        )

        if force_refresh:
            cache_is_fresh = False
            self.model_limits_detection_attempted = False
            self.detected_context_window = None
            self.detected_max_tokens = None

        if cache_is_fresh:
            return (
                self.detected_context_window,
                self.detected_max_tokens,
            )

        self.model_limits_detection_attempted = True
        self.model_limits_detected_at = now
        self.detected_context_window = None
        self.detected_max_tokens = None

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

                live_model = self.select_loaded_model_metadata(
                    model
                )
                if live_model is None:
                    continue

                context_window = (
                    self.extract_context_window_from_model(
                        live_model
                    )
                )

                max_tokens = (
                    self.extract_max_tokens_from_model(
                        live_model
                    )
                )

                if context_window:
                    self.detected_context_window = context_window
                    if force_refresh:
                        self.release_stale_provider_context_window_ceiling(
                            context_window
                        )

                if max_tokens:
                    self.detected_max_tokens = max_tokens

                if self.detected_context_window or self.detected_max_tokens:
                    return (
                        self.detected_context_window,
                        self.detected_max_tokens,
                    )

            except Exception:
                continue

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

        detected_context_window = await self.detect_context_window(
            force_refresh=force_refresh,
        )

        resolved_context_window = detected_context_window

        if self.provider_context_window_ceiling:
            if resolved_context_window:
                resolved_context_window = min(
                    int(resolved_context_window),
                    int(self.provider_context_window_ceiling),
                )
            else:
                resolved_context_window = int(
                    self.provider_context_window_ceiling
                )

        return resolved_context_window

    async def resolve_request_max_tokens(
            self,
            requested_max_tokens: int | None,
            *,
            force_refresh: bool = False,
    ) -> int | None:

        try:
            explicit_limit = int(requested_max_tokens)
        except (TypeError, ValueError):
            explicit_limit = 0

        detected_context_window, detected_max_tokens = (
            await self.detect_model_limits(
                force_refresh=force_refresh,
            )
        )

        if explicit_limit > 0:
            # Specialized calls (document result caps, etc.)
            # keep their smaller cap, while an explicit provider output ceiling
            # still wins if LM Studio reports one.
            if detected_max_tokens:
                return min(
                    explicit_limit,
                    int(detected_max_tokens),
                )
            return explicit_limit

        detected_limit = (
            detected_max_tokens
            or detected_context_window
        )
        if not detected_limit:
            return None

        return max(1, int(detected_limit))

    async def resolve_safe_max_tokens(
            self,
            *,
            system_prompt: str,
            user_prompt,
            requested_max_tokens: int | None,
            force_refresh: bool = False,
    ) -> int | None:

        request_context_window = (
            await self.resolve_request_context_window(
                force_refresh=force_refresh,
            )
        )
        # resolve_request_context_window() already refreshed the shared model
        # metadata above, so reuse that same snapshot for the output ceiling.
        request_max_tokens = await self.resolve_request_max_tokens(
            requested_max_tokens,
            force_refresh=False,
        )

        if not request_context_window or not request_max_tokens:
            return request_max_tokens

        prompt_tokens = estimate_prompt_tokens(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        response_budget = (
            request_context_window
            - prompt_tokens
            - settings.RUNTIME_OUTPUT_TOKEN_RESERVE
        )

        if response_budget <= 0:
            raise LMStudioAPIError(
                "Context overflow before request: estimated prompt "
                f"({prompt_tokens} tokens) plus output reserve "
                f"({settings.RUNTIME_OUTPUT_TOKEN_RESERVE}) exceeds available "
                f"context size ({request_context_window} tokens). "
                "Reduce attached context and retry.",
                details=json.dumps({
                    "error_kind": "context_overflow",
                    "phase": "preflight",
                    "estimated_prompt_tokens": prompt_tokens,
                    "n_ctx": request_context_window,
                }),
            )

        # One generation budget covers reasoning + visible answer together.
        # There is deliberately no fixed reasoning/answer split.
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

    def build_payload(
            self,
            *,
            system_prompt: str,
            user_prompt,
            temperature: float,
            max_tokens: int | None,
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
            "stream": stream,
        }

        if max_tokens is not None and int(max_tokens) > 0:
            payload["max_tokens"] = int(max_tokens)

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

        if isinstance(user_prompt, str):
            followup_tick = bool(
                getattr(
                    context,
                    "runtime_followup_tick_active",
                    False,
                )
            )
            restore_tick = bool(
                getattr(
                    context,
                    "runtime_session_restore_priming",
                    False,
                )
            )

            if followup_tick or (restore_tick and user_prompt == ""):
                # Do not replace this with "" or "(empty)": LM Studio prompt
                # templates reject a truly empty user message ("No user query
                # found"). Text-only follow-ups are system/context continuations,
                # so discard any stale caller payload and give the provider one
                # whitespace character instead of replaying a USER message.
                return " "

        return user_prompt

    async def build_safe_payload(
            self,
            *,
            system_prompt: str,
            user_prompt,
            temperature: float,
            max_tokens: int | None,
            stream: bool = False,
            force_refresh_limits: bool = False,
    ) -> dict[str, object]:

        safe_max_tokens = await self.resolve_safe_max_tokens(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            requested_max_tokens=max_tokens,
            force_refresh=force_refresh_limits,
        )

        return self.build_payload(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=safe_max_tokens,
            stream=stream,
        )


    async def detect_stream_provider_kind(
            self,
            *,
            force_refresh: bool = False,
    ) -> str:

        if (
                self.stream_provider_kind
                and not force_refresh
        ):
            return self.stream_provider_kind

        native_models_endpoint = getattr(
            settings,
            "NATIVE_MODELS_ENDPOINT",
            None,
        ) or LEGACY_NATIVE_MODELS_ENDPOINT

        native_models_payload = await self._probe_json_endpoint(
            native_models_endpoint
        )

        if native_models_payload is None and native_models_endpoint != LEGACY_NATIVE_MODELS_ENDPOINT:
            native_models_payload = await self._probe_json_endpoint(
                LEGACY_NATIVE_MODELS_ENDPOINT
            )

        # LM Studio native v1 returns {"models": [...]}; legacy native v0
        # returned {"data": [...]}. Accept both. The previous detector only
        # recognized v0, so LM Studio 0.4.x fell through to /props and was
        # incorrectly classified as plain llama.cpp (LM Studio exposes that
        # compatibility endpoint because its engine is llama.cpp-based).
        is_lm_studio_native = bool(
            isinstance(native_models_payload, dict)
            and (
                isinstance(native_models_payload.get("models"), list)
                or isinstance(native_models_payload.get("data"), list)
            )
        )

        if is_lm_studio_native:
            provider_kind = LM_STUDIO_STREAM_PROVIDER
        else:
            props_payload = await self._probe_json_endpoint(
                LLAMA_CPP_PROPS_ENDPOINT
            )
            provider_kind = (
                LLAMA_CPP_STREAM_PROVIDER
                if isinstance(props_payload, dict) and props_payload
                else GENERIC_STREAM_PROVIDER
            )

        self.stream_provider_kind = provider_kind
        self.stream_provider_detected_at = time.time()
        return provider_kind

    async def _probe_json_endpoint(
            self,
            endpoint: str,
    ):

        if not endpoint:
            return None

        try:
            response = await self.client.get(
                join_url(
                    self.api_base,
                    endpoint,
                ),
                timeout=2.0,
            )
        except (
            httpx.HTTPError,
            asyncio.TimeoutError,
            RuntimeError,
        ):
            return None

        if getattr(response, "status_code", 0) != 200:
            return None

        try:
            return response.json()
        except Exception:
            return None

    @staticmethod
    def build_lm_studio_input(
            user_prompt,
    ):

        if isinstance(user_prompt, str):
            return user_prompt

        if not isinstance(user_prompt, list):
            return str(user_prompt or "")

        normalized_items = []

        for item in user_prompt:
            if not isinstance(item, dict):
                continue

            item_type = str(
                item.get("type", "")
            ).strip().lower()

            if item_type == "text":
                content = item.get("text") or item.get("content") or ""
                if isinstance(content, str) and content:
                    normalized_items.append({
                        "type": "text",
                        "content": content,
                    })
                continue

            if item_type == "image_url":
                image_url = item.get("image_url") or {}
                if isinstance(image_url, dict):
                    data_url = image_url.get("url")
                else:
                    data_url = image_url

                if isinstance(data_url, str) and data_url:
                    normalized_items.append({
                        "type": "image",
                        "data_url": data_url,
                    })

        return normalized_items or " "

    async def build_stream_request(
            self,
            *,
            provider_kind: str,
            system_prompt: str,
            user_prompt,
            temperature: float,
            max_tokens: int | None,
            force_refresh_limits: bool,
    ) -> tuple[str, dict[str, object]]:

        safe_max_tokens = await self.resolve_safe_max_tokens(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            requested_max_tokens=max_tokens,
            force_refresh=force_refresh_limits,
        )

        if provider_kind == LM_STUDIO_STREAM_PROVIDER:
            payload: dict[str, object] = {
                "model": self.model_uid,
                "input": self.build_lm_studio_input(
                    user_prompt
                ),
                "system_prompt": system_prompt,
                "temperature": temperature,
                "stream": True,
                "store": False,
            }

            request_context_window = await self.resolve_request_context_window(
                force_refresh=force_refresh_limits,
            )

            if safe_max_tokens is not None and int(safe_max_tokens) > 0:
                payload["max_output_tokens"] = int(
                    safe_max_tokens
                )

            if request_context_window is not None and int(request_context_window) > 0:
                payload["context_length"] = int(
                    request_context_window
                )

            return (
                join_url(
                    self.api_base,
                    LM_STUDIO_NATIVE_CHAT_ENDPOINT,
                ),
                payload,
            )

        payload = self.build_payload(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=safe_max_tokens,
            stream=True,
        )

        if provider_kind == LLAMA_CPP_STREAM_PROVIDER:
            payload["return_progress"] = True

        return (
            join_url(
                self.api_base,
                settings.CHAT_ENDPOINT,
            ),
            payload,
        )

    @staticmethod
    def _normalize_sse_data_line(
            raw_line,
            *,
            is_sse_stream: bool,
    ) -> tuple[bool, str | None, bool]:

        if raw_line is None:
            return is_sse_stream, None, False

        line = raw_line.strip()

        if not line:
            return is_sse_stream, None, False

        if line.startswith("data:"):
            data = line.split(
                "data:",
                1,
            )[1].strip()
            return True, data, False

        if line.startswith(":"):
            return is_sse_stream, None, False

        sse_field = line.split(
            ":",
            1,
        )[0].strip().lower()

        if sse_field == "event":
            event_name = line.split(
                ":",
                1,
            )[1].strip() if ":" in line else ""
            return True, None, event_name

        if sse_field in {
            "id",
            "retry",
        }:
            return True, None, False

        if is_sse_stream:
            return is_sse_stream, None, False

        return is_sse_stream, line, False

    def extract_llama_model_progress_event(
            self,
            payload,
    ):

        if not isinstance(payload, dict):
            return None

        if str(payload.get("event", "")).strip().casefold() != "model_status":
            return None

        model = str(
            payload.get("model", "")
            or ""
        ).strip()

        if model and model != "*" and model.casefold() != str(self.model_uid or "").strip().casefold():
            return None

        data = payload.get("data") or {}
        if not isinstance(data, dict):
            return None

        status = str(
            data.get("status", "")
            or ""
        ).strip().casefold()

        if status == "loading":
            progress_data = data.get("progress") or {}
            progress_value = None

            if isinstance(progress_data, dict):
                progress_value = ResponseExtractor._clamp_progress(
                    progress_data.get("value")
                )

            event = {
                "type": "progress",
                "phase": "model_load",
                "state": "progress" if progress_value is not None else "start",
                "provider": "llama_cpp",
            }

            if progress_value is not None:
                event["progress"] = progress_value
            else:
                event["progress"] = 0.0

            return event

        if status == "loaded":
            return {
                "type": "progress",
                "phase": "model_load",
                "state": "end",
                "provider": "llama_cpp",
                "progress": 1.0,
            }

        return None


    # ---------------------------------------------------------
    # NORMAL REQUEST
    # ---------------------------------------------------------

    async def ask(
            self,
            *,
            system_prompt: str,
            user_prompt,
            temperature: float,
            max_tokens: int | None,
            timeout: float | None = None,
    ):

        payload = await self.build_safe_payload(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
            force_refresh_limits=True,
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
            api_error = _build_lm_studio_error(
                endpoint=endpoint,
                payload=payload,
                response=getattr(
                    error,
                    "response",
                    None,
                ),
                error=error,
            )
            self.remember_provider_context_window(
                api_error
            )
            raise api_error from error

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
            api_error = _build_lm_studio_error(
                endpoint=endpoint,
                payload=payload,
                error_payload=provider_error,
                response=response,
            )
            self.remember_provider_context_window(
                api_error
            )
            raise api_error

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
            max_tokens: int | None,
    ):

        provider_user_prompt = self.provider_user_prompt(
            context,
            user_prompt,
        )

        provider_kind = await self.detect_stream_provider_kind()
        endpoint, payload = await self.build_stream_request(
            provider_kind=provider_kind,
            system_prompt=system_prompt,
            user_prompt=provider_user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            force_refresh_limits=True,
        )

        event_queue: asyncio.Queue = asyncio.Queue()
        llama_model_progress_stop = asyncio.Event()

        async def produce_primary_stream():

            stream_id = None
            valid_json_chunks = 0
            invalid_json_samples: list[str] = []
            llama_prompt_processing_active = False

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

                        api_error = _build_lm_studio_error(
                            endpoint=endpoint,
                            payload=payload,
                            response=response,
                            error=error,
                        )
                        self.remember_provider_context_window(
                            api_error
                        )
                        raise api_error from error

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
                    current_sse_event_name = ""

                    async for raw_line in response.aiter_lines():

                        is_sse_stream, data, event_name = self._normalize_sse_data_line(
                            raw_line,
                            is_sse_stream=is_sse_stream,
                        )

                        if event_name is not False:
                            current_sse_event_name = str(
                                event_name or ""
                            ).strip()

                        if data is None:
                            continue

                        if not self.detected_context_window and not valid_json_chunks:
                            # The request can trigger LM Studio JIT loading after
                            # preflight metadata said loaded_instances: []. Retry
                            # discovery once when the response starts, not per token.
                            await self.resolve_request_context_window(
                                force_refresh=True,
                            )

                        if data == "[DONE]":
                            break

                        if not data:
                            continue

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

                        if (
                            current_sse_event_name
                            and isinstance(chunk, dict)
                            and not str(chunk.get("type", "") or "").strip()
                            and current_sse_event_name.casefold() not in {"message", "data"}
                        ):
                            chunk = {
                                **chunk,
                                "type": current_sse_event_name,
                            }

                        current_sse_event_name = ""
                        valid_json_chunks += 1

                        provider_error = (
                            _extract_lm_studio_error_payload(
                                chunk
                            )
                        )
                        if provider_error is not None:
                            api_error = _build_lm_studio_error(
                                endpoint=endpoint,
                                payload=payload,
                                error_payload=provider_error,
                                response=response,
                            )
                            self.remember_provider_context_window(
                                api_error
                            )
                            raise api_error

                        progress_event = (
                            ResponseExtractor
                            .extract_progress_event(
                                chunk
                            )
                        )
                        if progress_event:
                            if progress_event.get("phase") == "prompt_processing":
                                llama_prompt_processing_active = (
                                    provider_kind == LLAMA_CPP_STREAM_PROVIDER
                                    and progress_event.get("state") != "end"
                                )
                            await event_queue.put((
                                "event",
                                progress_event,
                            ))

                        usage = (
                            ResponseExtractor
                            .extract_usage(
                                chunk
                            )
                        )

                        if usage:
                            await event_queue.put((
                                "event",
                                usage,
                            ))

                        reasoning = (
                            ResponseExtractor
                            .extract_reasoning_chunk(
                                chunk
                            )
                        )

                        if reasoning:
                            if llama_prompt_processing_active:
                                llama_prompt_processing_active = False
                                await event_queue.put((
                                    "event",
                                    {
                                        "type": "progress",
                                        "phase": "prompt_processing",
                                        "state": "end",
                                        "provider": "llama_cpp",
                                        "progress": 1.0,
                                    },
                                ))

                            await event_queue.put((
                                "event",
                                reasoning,
                            ))

                        content = (
                            ResponseExtractor
                            .extract_content_chunk(
                                chunk
                            )
                        )

                        if content:
                            if llama_prompt_processing_active:
                                llama_prompt_processing_active = False
                                await event_queue.put((
                                    "event",
                                    {
                                        "type": "progress",
                                        "phase": "prompt_processing",
                                        "state": "end",
                                        "provider": "llama_cpp",
                                        "progress": 1.0,
                                    },
                                ))

                            await event_queue.put((
                                "event",
                                content,
                            ))

                        finish_reason = (
                            ResponseExtractor
                            .extract_finish_reason(
                                chunk
                            )
                        )

                        if finish_reason:
                            if llama_prompt_processing_active:
                                llama_prompt_processing_active = False
                                await event_queue.put((
                                    "event",
                                    {
                                        "type": "progress",
                                        "phase": "prompt_processing",
                                        "state": "end",
                                        "provider": "llama_cpp",
                                        "progress": 1.0,
                                    },
                                ))

                            await event_queue.put((
                                "event",
                                {
                                    "type": "finish",
                                    "finish_reason": finish_reason,
                                },
                            ))

                    if llama_prompt_processing_active:
                        await event_queue.put((
                            "event",
                            {
                                "type": "progress",
                                "phase": "prompt_processing",
                                "state": "end",
                                "provider": "llama_cpp",
                                "progress": 1.0,
                            },
                        ))

                    if valid_json_chunks <= 0:
                        followup_tick = bool(
                            getattr(
                                context,
                                "runtime_followup_tick_active",
                                False,
                            )
                        )
                        _build_stream_json_error_details(
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

            except asyncio.CancelledError:
                raise
            except LMStudioAPIError as error:
                self.remember_provider_context_window(
                    error
                )
                await event_queue.put((
                    "error",
                    error,
                ))
            except httpx.HTTPError as e:
                api_error = _build_lm_studio_error(
                    endpoint=endpoint,
                    payload=payload,
                    response=getattr(
                        e,
                        "response",
                        None,
                    ),
                    error=e,
                )
                self.remember_provider_context_window(
                    api_error
                )
                await event_queue.put((
                    "error",
                    api_error,
                ))
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

                await event_queue.put((
                    "error",
                    e,
                ))
            finally:
                if (
                        context
                        and stream_id is not None
                ):
                    context.active_streams.pop(
                        stream_id,
                        None,
                    )

                await event_queue.put((
                    "done",
                    "primary",
                ))

        async def produce_llama_model_progress():


            try:
                async with self.client.stream(
                        "GET",
                        join_url(
                            self.api_base,
                            LLAMA_CPP_MODEL_EVENTS_ENDPOINT,
                        ),
                        json=None,
                        timeout=None,
                ) as response:
                    try:
                        response.raise_for_status()
                    except Exception:
                        return

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
                    current_sse_event_name = ""

                    async for raw_line in response.aiter_lines():
                        if llama_model_progress_stop.is_set():
                            break

                        is_sse_stream, data, event_name = self._normalize_sse_data_line(
                            raw_line,
                            is_sse_stream=is_sse_stream,
                        )

                        if event_name is not False:
                            current_sse_event_name = str(
                                event_name or ""
                            ).strip()

                        if not data or data == "[DONE]":
                            continue

                        try:
                            chunk = json.loads(
                                data
                            )
                        except Exception:
                            continue

                        progress_event = self.extract_llama_model_progress_event(
                            chunk
                        )
                        if progress_event:
                            await event_queue.put((
                                "event",
                                progress_event,
                            ))

            except asyncio.CancelledError:
                raise
            except Exception:
                return
            finally:
                await event_queue.put((
                    "done",
                    "llama_model_progress",
                ))

        llama_model_progress_task = None
        pending_producers = 1

        if provider_kind == LLAMA_CPP_STREAM_PROVIDER:
            llama_model_progress_task = asyncio.create_task(
                produce_llama_model_progress()
            )
            pending_producers += 1
            await asyncio.sleep(0)

        primary_task = asyncio.create_task(
            produce_primary_stream()
        )

        try:
            while pending_producers > 0:
                item_type, item_value = await event_queue.get()

                if item_type == "event":
                    yield item_value
                    continue

                if item_type == "done":
                    pending_producers -= 1

                    if item_value == "primary":
                        llama_model_progress_stop.set()
                        if (
                                llama_model_progress_task is not None
                                and not llama_model_progress_task.done()
                        ):
                            llama_model_progress_task.cancel()

                    continue

                if item_type == "error":
                    raise item_value

        except asyncio.CancelledError:
            raise
        finally:
            llama_model_progress_stop.set()

            for task in (
                primary_task,
                llama_model_progress_task,
            ):
                if task is not None and not task.done():
                    task.cancel()

            await asyncio.gather(
                *[
                    task
                    for task in (
                        primary_task,
                        llama_model_progress_task,
                    )
                    if task is not None
                ],
                return_exceptions=True,
            )
